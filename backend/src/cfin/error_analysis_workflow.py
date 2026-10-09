"""Extraction → Error Analysis → governed route → readable case workflow."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

from cfin.error_analysis_contracts import (
    CaseContent,
    ErrorAnalysisBinding,
    ErrorAnalysisDraft,
    ErrorAnalysisResult,
    attach_route,
    validate_case_content,
    validate_error_analysis_draft,
)
from cfin.error_analysis_prompts import ERROR_ANALYSIS_PROMPT_VERSIONS
from cfin.error_route_registry import RouteRegistry, taxonomy_payload
from cfin.log_only_contracts import ExtractedLog, HistoryRetrievalResult
from cfin.log_only_inputs import LogInputs
from cfin.log_only_sources import manifest_fingerprint, validate_extraction
from cfin.stage_errors import RetryableStageError


class ErrorAnalysisStageAdapter(Protocol):
    evaluation_only: bool
    workflow_version: str

    async def execute(
        self, stage: str, payload: dict[str, Any], output_type: type[BaseModel], inputs: LogInputs
    ) -> BaseModel: ...


HistoryReader = Callable[[ExtractedLog, dict[str, Any]], Awaitable[HistoryRetrievalResult]]


@dataclass(frozen=True)
class ErrorAnalysisWorkflowExecution:
    result: ErrorAnalysisResult
    stage_calls: dict[str, int]
    stage_reuses: dict[str, str]
    latency_ms: int
    usage: dict[str, int]
    cost_usd: Decimal
    usage_complete: bool
    evaluation_only: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.model_dump(mode="json"),
            "stage_calls": self.stage_calls,
            "stage_reuses": self.stage_reuses,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "cost_usd": str(self.cost_usd),
            "usage_complete": self.usage_complete,
            "evaluation_only": self.evaluation_only,
        }


class ErrorAnalysisWorkflowExecutor:
    def __init__(
        self,
        adapter: ErrorAnalysisStageAdapter,
        binding: ErrorAnalysisBinding,
        registry: RouteRegistry,
        *,
        timeout_seconds: float = 60,
        max_retries: int = 0,
        history_reader: HistoryReader | None = None,
    ):
        if not 0 < timeout_seconds <= 60:
            raise ValueError("Stage timeout must be greater than zero and at most 60 seconds")
        if max_retries not in (0, 1):
            raise ValueError("At most one retry per stage is supported")
        if getattr(adapter, "workflow_version", None) != binding.workflow_version:
            raise ValueError("Adapter and Error Analysis binding versions differ")
        if binding.prompt_versions != ERROR_ANALYSIS_PROMPT_VERSIONS:
            raise ValueError("Execution prompt versions do not match Error Analysis workflow")
        self.adapter = adapter
        self.binding = binding
        self.registry = registry
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.history_reader = history_reader

    async def run(
        self, inputs: LogInputs, *, routing_context: Mapping[str, str] | None = None
    ) -> ErrorAnalysisWorkflowExecution:
        if self.binding.source_manifest_sha256 != manifest_fingerprint(inputs.manifest):
            raise ValueError("Execution binding differs from the preserved source manifest")
        started = time.monotonic()
        calls = dict.fromkeys(("agent1", "agent2", "agent3"), 0)
        extraction = draft = analysis = content = None
        history = HistoryRetrievalResult(status="not_searched")
        limitations: list[str] = []
        outcome: str = "completed"
        failure_reason: str | None = None
        active_stage = "agent1"
        base = {"binding": self.binding.model_dump(mode="json")}

        async def stage(
            name: str,
            payload: dict[str, Any],
            output_type: type[BaseModel],
            validator: Callable[[Any], None],
        ) -> Any:
            for attempt in range(self.max_retries + 1):
                try:
                    calls[name] += 1
                    candidate = await asyncio.wait_for(
                        self.adapter.execute(name, payload, output_type, inputs),
                        timeout=self.timeout_seconds,
                    )
                    value = output_type.model_validate(
                        candidate.model_dump() if isinstance(candidate, BaseModel) else candidate
                    )
                    validator(value)
                    checkpoint = getattr(self.adapter, "record_validated", None)
                    if checkpoint:
                        await checkpoint(name, value, binding=self.binding)
                    return value
                except (ValueError, RetryableStageError, TimeoutError):
                    failed = getattr(self.adapter, "record_failed", None)
                    if failed:
                        await failed(name)
                    if attempt >= self.max_retries:
                        raise
                    payload = {
                        **payload,
                        "retry_instruction": "Use only the same validated evidence and IDs.",
                    }
            raise RuntimeError("Stage retry exhausted")

        try:
            extraction = await stage(
                "agent1",
                {**base, "sources": inputs.extraction_payload()},
                ExtractedLog,
                lambda value: validate_extraction(inputs.manifest, inputs.originals, value),
            )
            coverage = validate_extraction(inputs.manifest, inputs.originals, extraction)
            limitations = list(
                dict.fromkeys([*extraction.extraction_limitations, *coverage.limitations])
            )
            if not any(entry.raw_text.strip() for entry in extraction.entries):
                outcome = "no_usable_evidence"
                failure_reason = "The supplied originals produced no usable extracted entries."
            else:
                active_stage = "agent2"
                # This intentionally passes no originals, source lines, history, or SAP tool.
                draft = await stage(
                    "agent2",
                    {
                        **base,
                        "extracted": extraction.model_dump(mode="json"),
                        "taxonomy": taxonomy_payload(),
                    },
                    ErrorAnalysisDraft,
                    lambda value: validate_error_analysis_draft(extraction, value),
                )
                route = await self.registry.get_error_route(
                    self.binding.workspace_id, draft.category_id, routing_context
                )
                analysis = attach_route(extraction, draft, route)
                active_stage = "agent3"
                if self.history_reader is not None:
                    try:
                        history = await asyncio.wait_for(
                            self.history_reader(extraction, analysis.model_dump(mode="json")),
                            timeout=min(15, self.timeout_seconds),
                        )
                        history = HistoryRetrievalResult.model_validate(history)
                    except Exception:
                        history = HistoryRetrievalResult(
                            status="unavailable",
                            limitation="Reviewed case history could not be retrieved.",
                        )
                content = await stage(
                    "agent3",
                    {
                        **base,
                        "sources": inputs.extraction_payload(),
                        "extracted": extraction.model_dump(mode="json"),
                        "analysis": analysis.model_dump(mode="json"),
                        "history": history.model_dump(mode="json"),
                    },
                    CaseContent,
                    lambda value: validate_case_content(extraction, value, history=history),
                )
                if not getattr(self.adapter, "usage_complete", True):
                    raise RuntimeError("Model usage remains unknown; publication is blocked")
        except Exception as exc:
            outcome = "failed"
            content = None
            category = "invalid_output" if isinstance(exc, ValueError) else "execution_failed"
            if isinstance(exc, TimeoutError):
                category = "timeout"
            failure_reason = (
                f"{active_stage}: {category}; no new Error Analysis case was published."
            )
        result = ErrorAnalysisResult(
            **self.binding.model_dump(),
            source_manifest=inputs.manifest,
            outcome=outcome,
            extraction=extraction,
            analysis=analysis,
            case_content=content,
            history=history,
            limitations=tuple(limitations),
            failure_reason=failure_reason,
        )
        return ErrorAnalysisWorkflowExecution(
            result=result,
            stage_calls=dict(getattr(self.adapter, "dispatch_counts", calls)),
            stage_reuses=dict(getattr(self.adapter, "stage_reuses", {})),
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=dict(getattr(self.adapter, "usage", {})),
            cost_usd=getattr(self.adapter, "cost_usd", Decimal("0")),
            usage_complete=getattr(self.adapter, "usage_complete", True),
            evaluation_only=self.adapter.evaluation_only,
        )
