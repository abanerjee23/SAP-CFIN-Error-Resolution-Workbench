"""Bounded factual extraction → evidence selection → summary.

Explicit opt-in executor for the rebuild. The production worker continues to run
legacy jobs until versioned intake, persistence and case publication are ready.
No fixture replay or diagnostic fallback is an operational adapter.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

from cfin.log_only_contracts import (
    EvidenceSelection,
    ExecutionBinding,
    ExtractedLog,
    HistoryRetrievalResult,
    HydratedSelection,
    LogAnalysisResult,
    LogSummary,
    hydrate_selection,
    validate_selection,
    validate_summary,
)
from cfin.log_only_inputs import LogInputs
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.log_only_sources import manifest_fingerprint, validate_extraction
from cfin.stage_errors import RetryableStageError


class LogStageAdapter(Protocol):
    evaluation_only: bool
    workflow_version: str

    async def execute(
        self, stage: str, payload: dict[str, Any], output_type: type[BaseModel], inputs: LogInputs
    ) -> BaseModel: ...


@dataclass(frozen=True)
class LogWorkflowExecution:
    result: LogAnalysisResult
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


class LogWorkflowExecutor:
    def __init__(
        self,
        adapter: LogStageAdapter,
        binding: ExecutionBinding,
        *,
        timeout_seconds: float = 60,
        max_retries: int = 0,
        history_reader: Callable[[HydratedSelection], Awaitable[HistoryRetrievalResult]]
        | None = None,
    ):
        if not 0 < timeout_seconds <= 60:
            raise ValueError("Stage timeout must be greater than zero and at most 60 seconds")
        if max_retries not in (0, 1):
            raise ValueError("The factual baseline permits at most one retry per stage")
        if getattr(adapter, "workflow_version", None) != "log-only-v1":
            raise ValueError("The factual executor requires an explicitly compatible adapter")
        if binding.prompt_versions.model_dump() != LOG_PROMPT_VERSIONS:
            raise ValueError("Execution prompt versions do not match the running workflow")
        self.adapter = adapter
        self.binding = binding
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.history_reader = history_reader

    async def run(self, inputs: LogInputs) -> LogWorkflowExecution:
        if self.binding.source_manifest_sha256 != manifest_fingerprint(inputs.manifest):
            raise ValueError("Execution binding differs from the preserved source manifest")
        started = time.monotonic()
        calls = dict.fromkeys(("agent1", "agent2", "agent3"), 0)
        extracted = selection = summary = None
        limitations: list[str] = []
        # Application-owned, honest until reviewed retrieval is integrated. No
        # history provider/tool or history payload reaches extraction or selection.
        history = HistoryRetrievalResult(status="not_searched")
        outcome = "completed"
        failure_reason = None
        active_stage = "agent1"
        base = {"binding": self.binding.model_dump(mode="json")}

        async def stage(
            name: str,
            payload: dict[str, Any],
            output_type: type[BaseModel],
            validator: Callable[[Any], None],
        ) -> Any:
            remaining = getattr(self.adapter, "stage_remaining_seconds", {}).get(
                name, self.timeout_seconds
            )
            cached = getattr(getattr(self.adapter, "ledger", None), "cached_outputs", {})
            deadline = time.monotonic() + (
                self.timeout_seconds if name in cached else min(self.timeout_seconds, remaining)
            )
            for attempt in range(self.max_retries + 1):
                used = getattr(self.adapter, "dispatch_counts", calls).get(name, 0)
                cached = getattr(getattr(self.adapter, "ledger", None), "cached_outputs", {})
                if name not in cached and not getattr(self.adapter, "usage_complete", True):
                    raise RuntimeError("Prior model usage is unknown; fresh dispatch is blocked")
                if name not in cached and (used >= 1 + self.max_retries or remaining <= 0):
                    raise RuntimeError("Stage dispatch or time budget exhausted")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Stage time budget exhausted")
                try:
                    calls[name] += 1
                    candidate = await asyncio.wait_for(
                        self.adapter.execute(name, payload, output_type, inputs),
                        timeout=deadline - time.monotonic(),
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
                    if attempt >= self.max_retries or time.monotonic() >= deadline:
                        raise
                    payload = {
                        **payload,
                        "retry_instruction": "The previous candidate failed schema/reference "
                        "validation or a transient request failed. Use the unchanged supplied "
                        "evidence, exact source text and valid entry references.",
                    }
            raise RuntimeError("Stage retry exhausted")

        try:
            sources = inputs.extraction_payload()
            if any(line["text"].strip() for source in sources for line in source["lines"]):
                extracted = await stage(
                    "agent1",
                    {**base, "sources": sources},
                    ExtractedLog,
                    lambda value: validate_extraction(inputs.manifest, inputs.originals, value),
                )
            else:
                extracted = ExtractedLog(entries=[])
            coverage = validate_extraction(inputs.manifest, inputs.originals, extracted)
            limitations = list(
                dict.fromkeys(
                    [
                        *extracted.extraction_limitations,
                        *coverage.limitations,
                    ]
                )
            )
            if not any(entry.raw_text.strip() for entry in extracted.entries):
                outcome = "no_usable_evidence"
                failure_reason = "The supplied originals produced no usable extracted entries."
            else:
                active_stage = "agent2"
                selection = await stage(
                    "agent2",
                    {
                        **base,
                        "source_manifest": inputs.manifest.model_dump(mode="json"),
                        "extracted": extracted.model_dump(mode="json"),
                    },
                    EvidenceSelection,
                    lambda value: validate_selection(extracted, value),
                )
                evidence = hydrate_selection(
                    inputs.manifest, extracted, selection, limitations=limitations
                )
                if not any(entry.raw_text.strip() for entry in evidence.selected_entries):
                    outcome = "no_usable_evidence"
                    failure_reason = (
                        "No usable extracted entries were selected for a factual brief."
                    )
                else:
                    active_stage = "agent3"
                    if self.history_reader is not None:
                        try:
                            retrieved = await asyncio.wait_for(
                                self.history_reader(evidence), timeout=min(15, self.timeout_seconds)
                            )
                            history = HistoryRetrievalResult.model_validate(retrieved)
                        except Exception:
                            history = HistoryRetrievalResult(
                                status="unavailable",
                                limitation="Reviewed case history could not be retrieved.",
                            )
                    summary = await stage(
                        "agent3",
                        {
                            **base,
                            "evidence": evidence.model_dump(mode="json"),
                            "history": history.model_dump(mode="json"),
                        },
                        LogSummary,
                        lambda value: validate_summary(selection, value, history=history),
                    )
                    if not getattr(self.adapter, "usage_complete", True):
                        raise RuntimeError("Model usage remains unknown; publication is blocked")
        except Exception as exc:
            # Cancellation remains a BaseException and propagates to the lease
            # owner. Storage/ledger/provider failures become explicit outcomes.
            outcome = "failed"
            summary = None
            # Failure messages must not reproduce provider exceptions or source data.
            category = "invalid_output" if isinstance(exc, ValueError) else "execution_failed"
            if isinstance(exc, TimeoutError):
                category = "timeout"
            failure_reason = f"{active_stage}: {category}; no new factual brief was published."
        result = LogAnalysisResult(
            **self.binding.model_dump(),
            source_manifest=inputs.manifest,
            outcome=outcome,
            extraction=extracted,
            selection=selection,
            summary=summary,
            limitations=limitations,
            history=history,
            failure_reason=failure_reason,
        )
        return LogWorkflowExecution(
            result=result,
            stage_calls=dict(getattr(self.adapter, "dispatch_counts", calls)),
            stage_reuses=dict(getattr(self.adapter, "stage_reuses", {})),
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=dict(getattr(self.adapter, "usage", {})),
            cost_usd=getattr(self.adapter, "cost_usd", Decimal("0")),
            usage_complete=getattr(self.adapter, "usage_complete", True),
            evaluation_only=self.adapter.evaluation_only,
        )
