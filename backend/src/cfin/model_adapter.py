"""Real Agents SDK adapter. Every invocation requires a durable cost reservation."""

import hashlib
import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from agents import Agent, AgentOutputSchema, ModelSettings, OpenAIResponsesModel, RunConfig, Runner
from agents.exceptions import ModelBehaviorError
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import BaseModel

from cfin.config import Settings
from cfin.stage_errors import RetryableStageError

if TYPE_CHECKING:
    from cfin.log_only_contracts import ExecutionBinding

PRICE_VERSION = "openai-standard-2026-10-01"
MODEL = "gpt-6-luna"
SOL_MODEL = "gpt-6.1-sol"
# Includes full input and cache-write charge; no cached-input discount assumed.
INPUT_PRICE = Decimal("0.125")
OUTPUT_PRICE = Decimal("0.50")
PRICES = {
    MODEL: (INPUT_PRICE, OUTPUT_PRICE),
    SOL_MODEL: (Decimal("2.50"), Decimal("10.00")),
    "gpt-6-sol": (Decimal("2.50"), Decimal("10.00")),
}
MAX_OUTPUT_TOKENS = 8192
MAX_INPUT_BOUND = 131072
LEGACY_WORKFLOW_VERSION = "legacy-v1"
LOG_WORKFLOW_VERSION = "log-only-v1"
ERROR_ANALYSIS_WORKFLOW_VERSION = "error-analysis-v1"
LOG_PAYLOAD_KEYS = {
    "agent1": {"binding", "sources"},
    "agent2": {"binding", "extracted", "source_manifest"},
    "agent3": {"binding", "evidence", "history"},
}
ERROR_ANALYSIS_PAYLOAD_KEYS = {
    "agent1": {"binding", "sources"},
    "agent2": {"binding", "extracted", "taxonomy"},
    "agent3": {"binding", "sources", "extracted", "analysis", "history"},
}


class CallLedger(Protocol):
    async def reserve(
        self, stage: str, model: str, input_bound: int, output_bound: int, price_version: str
    ) -> str: ...

    async def reconcile(
        self,
        reservation_id: str,
        usage: dict[str, int],
        cost_usd: Decimal,
        *,
        trace_payload: dict[str, Any] | None = None,
        provider_request_id: str | None = None,
    ) -> None: ...


class OpenAIStageAdapter:
    evaluation_only = False

    def __init__(
        self,
        settings: Settings,
        ledger: CallLedger,
        *,
        tracing_enabled: bool = False,
        trace_metadata: dict[str, Any] | None = None,
        workflow_version: str = LEGACY_WORKFLOW_VERSION,
    ):
        if workflow_version not in {
            LEGACY_WORKFLOW_VERSION,
            LOG_WORKFLOW_VERSION,
            ERROR_ANALYSIS_WORKFLOW_VERSION,
        }:
            raise RuntimeError("Unsupported model workflow version")
        if not settings.models_configured or not settings.worker_configured:
            raise RuntimeError("Paid model execution is not configured")
        self.models = {
            "agent1": settings.model_agent_1,
            "agent2": settings.model_agent_2,
            "agent3": settings.model_agent_3,
        }
        if any(model not in PRICES for model in self.models.values()):
            raise RuntimeError("Model has no verified price adapter")
        self.settings = settings
        self.workflow_version = workflow_version
        self.ledger = ledger
        self.tracing_enabled = tracing_enabled
        self.trace_metadata = dict(trace_metadata or {})
        # Disable provider automatic retries; each billable invocation needs its own reservation.
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=0,
            timeout=settings.stage_timeout_seconds,
        )
        self.usage: dict[str, int] = dict(
            getattr(
                ledger,
                "total_usage",
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
        )
        self.cost_usd = getattr(ledger, "total_cost_usd", Decimal("0"))
        self.usage_complete = getattr(ledger, "usage_complete", True)
        self.dispatch_counts = {
            stage: getattr(ledger, "dispatch_counts", {}).get(stage, 0) for stage in self.models
        }
        self.stage_reuses: dict[str, str] = {}
        self.stage_remaining_seconds = dict(getattr(ledger, "stage_remaining_seconds", {}))
        self.stage_bindings: dict[str, Any] = {}
        self.stage_input_hashes: dict[str, str] = {}

    async def close(self) -> None:
        await self.client.close()

    async def record_validated(
        self,
        stage: str,
        output: BaseModel,
        *,
        binding: "ExecutionBinding | dict[str, Any] | None" = None,
    ) -> None:
        encoded = output.model_dump(mode="json")
        if self.workflow_version == LOG_WORKFLOW_VERSION:
            from cfin.log_only_contracts import ExecutionBinding, LogStageEnvelope

            expected = self.stage_bindings.get(stage)
            actual = ExecutionBinding.model_validate(binding) if binding is not None else expected
            if expected is None or actual != expected:
                raise RuntimeError("Validated output has no matching application execution binding")
            encoded = LogStageEnvelope(
                binding=actual,
                stage=stage,
                input_sha256=self.stage_input_hashes[stage],
                output=output,
            ).model_dump(mode="json")
        elif self.workflow_version == ERROR_ANALYSIS_WORKFLOW_VERSION:
            from cfin.error_analysis_contracts import (
                ErrorAnalysisBinding,
                ErrorAnalysisStageEnvelope,
            )

            expected = self.stage_bindings.get(stage)
            actual = (
                ErrorAnalysisBinding.model_validate(binding) if binding is not None else expected
            )
            if expected is None or actual != expected:
                raise RuntimeError("Validated output has no matching application execution binding")
            encoded = ErrorAnalysisStageEnvelope(
                binding=actual,
                stage=stage,
                input_sha256=self.stage_input_hashes[stage],
                output=output,
            ).model_dump(mode="json")
        callback = getattr(self.ledger, "record_validated", None)
        if callback:
            await callback(stage, encoded)

    async def record_failed(self, stage: str) -> None:
        callback = getattr(self.ledger, "record_failed", None)
        if callback:
            await callback(stage)

    def _log_request(
        self, stage: str, payload: dict[str, Any], output_type: type[BaseModel]
    ) -> tuple[str, str]:
        """Select factual instructions only after checking the code-owned stage boundary."""
        from cfin.log_only_contracts import (
            EvidenceSelection,
            ExecutionBinding,
            ExtractedLog,
            LogSummary,
        )
        from cfin.log_only_prompts import LOG_BOUNDARY, LOG_INSTRUCTIONS, LOG_PROMPT_VERSIONS

        expected_type = {
            "agent1": ExtractedLog,
            "agent2": EvidenceSelection,
            "agent3": LogSummary,
        }[stage]
        if output_type is not expected_type:
            raise RuntimeError("Output contract does not match the factual workflow stage")
        required = LOG_PAYLOAD_KEYS[stage]
        if not required <= payload.keys() or payload.keys() - required - {"retry_instruction"}:
            raise RuntimeError("Payload does not match the factual workflow stage boundary")
        binding = ExecutionBinding.model_validate(payload["binding"])
        if binding.prompt_versions.model_dump() != LOG_PROMPT_VERSIONS:
            raise RuntimeError("Application execution binding has incompatible prompt versions")
        if binding.model_configuration.model_dump() != {
            **self.models,
            "reasoning_effort": self.settings.model_reasoning_effort,
        }:
            raise RuntimeError("Application execution binding has incompatible model configuration")
        if any(previous != binding for previous in self.stage_bindings.values()):
            raise RuntimeError("Application execution binding changed within this adapter")
        self.stage_bindings[stage] = binding
        self.stage_input_hashes[stage] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "retry_instruction"},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return LOG_BOUNDARY + "\n\n" + LOG_INSTRUCTIONS[stage], LOG_PROMPT_VERSIONS[stage]

    def _error_analysis_request(
        self, stage: str, payload: dict[str, Any], output_type: type[BaseModel]
    ) -> tuple[str, str]:
        """Validate the new workflow's hard information boundaries before dispatch."""
        from cfin.error_analysis_contracts import (
            CaseContent,
            ErrorAnalysisBinding,
            ErrorAnalysisDraft,
        )
        from cfin.error_analysis_prompts import (
            ERROR_ANALYSIS_BOUNDARY,
            ERROR_ANALYSIS_INSTRUCTIONS,
            ERROR_ANALYSIS_PROMPT_VERSIONS,
        )
        from cfin.log_only_contracts import ExtractedLog

        expected_type = {
            "agent1": ExtractedLog,
            "agent2": ErrorAnalysisDraft,
            "agent3": CaseContent,
        }[stage]
        if output_type is not expected_type:
            raise RuntimeError("Output contract does not match the Error Analysis workflow stage")
        required = ERROR_ANALYSIS_PAYLOAD_KEYS[stage]
        if not required <= payload.keys() or payload.keys() - required - {"retry_instruction"}:
            raise RuntimeError("Payload does not match the Error Analysis stage boundary")
        if stage == "agent2" and any(key in payload for key in ("sources", "history", "route")):
            raise RuntimeError("Error Analysis must receive structured extraction only")
        binding = ErrorAnalysisBinding.model_validate(payload["binding"])
        if binding.prompt_versions != ERROR_ANALYSIS_PROMPT_VERSIONS:
            raise RuntimeError("Application execution binding has incompatible prompt versions")
        if binding.model_configuration != {
            **self.models,
            "reasoning_effort": self.settings.model_reasoning_effort,
        }:
            raise RuntimeError("Application execution binding has incompatible model configuration")
        if any(previous != binding for previous in self.stage_bindings.values()):
            raise RuntimeError("Application execution binding changed within this adapter")
        self.stage_bindings[stage] = binding
        self.stage_input_hashes[stage] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "retry_instruction"},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ERROR_ANALYSIS_BOUNDARY + "\n\n" + ERROR_ANALYSIS_INSTRUCTIONS[
            stage
        ], ERROR_ANALYSIS_PROMPT_VERSIONS[stage]

    async def execute(
        self,
        stage: str,
        payload: dict[str, Any],
        output_type: type[BaseModel],
        inputs: Any,
    ) -> BaseModel:
        if stage not in self.models:
            raise RuntimeError("Unknown model stage")
        if self.workflow_version == LOG_WORKFLOW_VERSION:
            instructions, prompt_version = self._log_request(stage, payload, output_type)
        elif self.workflow_version == ERROR_ANALYSIS_WORKFLOW_VERSION:
            instructions, prompt_version = self._error_analysis_request(stage, payload, output_type)
        else:
            # Historical callers retain their original prompts. Importing the factual
            # adapter does not load diagnostic instructions or the fixture workflow.
            from cfin.workflow import BOUNDARY, INSTRUCTIONS, PROMPT_VERSION

            instructions = BOUNDARY + INSTRUCTIONS[stage]
            prompt_version = PROMPT_VERSION
        cached = getattr(self.ledger, "cached_outputs", {}).get(stage)
        if cached is not None:
            if self.workflow_version == LOG_WORKFLOW_VERSION:
                from cfin.log_only_contracts import LogStageEnvelope

                envelope = LogStageEnvelope.model_validate(cached)
                if (
                    envelope.binding != self.stage_bindings[stage]
                    or envelope.stage != stage
                    or envelope.input_sha256 != self.stage_input_hashes[stage]
                ):
                    raise RuntimeError(
                        "Cached stage does not match the application execution binding"
                    )
                cached = envelope.output
            elif self.workflow_version == ERROR_ANALYSIS_WORKFLOW_VERSION:
                from cfin.error_analysis_contracts import ErrorAnalysisStageEnvelope

                envelope = ErrorAnalysisStageEnvelope.model_validate(cached)
                if (
                    envelope.binding != self.stage_bindings[stage]
                    or envelope.stage != stage
                    or envelope.input_sha256 != self.stage_input_hashes[stage]
                ):
                    raise RuntimeError("Cached stage does not match its execution binding")
                cached = envelope.output
            output = output_type.model_validate(cached)
            self.stage_reuses[stage] = getattr(self.ledger, "reused_from", {}).get(
                stage, "validated_or_reconciled_same_run_candidate"
            )
            return output
        model = self.models[stage]
        input_price, output_price = PRICES[model]
        schema = AgentOutputSchema(output_type)
        encoded = json.dumps(payload, ensure_ascii=False)
        # A UTF-8 byte bound is deliberately conservative for text-token input. Include the
        # exact schema/instructions and a bounded protocol overhead allowance before dispatch.
        bound = len((encoded + instructions + json.dumps(schema.json_schema())).encode()) + 32768
        if bound > MAX_INPUT_BOUND:
            raise RuntimeError("Input exceeds the bounded first-family model request")
        reservation = await self.ledger.reserve(
            stage, model, bound, MAX_OUTPUT_TOKENS, PRICE_VERSION
        )
        self.dispatch_counts[stage] += 1
        previous_usage_complete = self.usage_complete
        self.usage_complete = False
        try:
            agent = Agent(
                name=stage,
                instructions=instructions,
                model=OpenAIResponsesModel(model, self.client),
                output_type=schema,
                model_settings=ModelSettings(
                    max_tokens=MAX_OUTPUT_TOKENS,
                    reasoning={"effort": self.settings.model_reasoning_effort},
                    store=False,
                    extra_body={"service_tier": "default"},
                ),
            )
            result = await Runner.run(
                agent,
                encoded,
                max_turns=1,
                run_config=RunConfig(
                    tracing_disabled=not self.tracing_enabled,
                    # The selected automatic processor receives actual synthetic
                    # prompts/candidates. No provider-default tracing is enabled.
                    trace_include_sensitive_data=self.tracing_enabled,
                    workflow_name="CFIN " + prompt_version,
                    trace_metadata={
                        **self.trace_metadata,
                        **(
                            {
                                "workflow_version": self.workflow_version,
                                "prompt_version": prompt_version,
                            }
                            if self.workflow_version
                            in {LOG_WORKFLOW_VERSION, ERROR_ANALYSIS_WORKFLOW_VERSION}
                            else {}
                        ),
                        "stage": stage,
                        "model": model,
                    },
                ),
            )
        except ModelBehaviorError as exc:
            # The SDK may reject malformed JSON before returning usage. Retain the
            # reservation and let the workflow attempt one separately reserved retry.
            raise RetryableStageError("Model returned malformed structured output") from exc
        except (APIConnectionError, APIStatusError) as exc:
            if (
                isinstance(exc, APIConnectionError)
                or exc.status_code == 429
                or exc.status_code >= 500
            ):
                raise RetryableStageError("Transient model request failed") from exc
            raise RuntimeError("Model access or input failed; correction required") from exc
        except Exception as exc:
            # Unknown/timeout usage keeps the full reservation. No raw provider error is logged.
            raise RuntimeError("Model stage failed; reserved cost retained") from exc
        usage = result.context_wrapper.usage
        observed = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
        if (
            not isinstance(usage.requests, int)
            or isinstance(usage.requests, bool)
            or usage.requests < 1
        ):
            raise RuntimeError("Provider usage missing; reserved cost retained")
        if (
            any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in observed.values()
            )
            or observed["input_tokens"] > bound
            or observed["output_tokens"] > MAX_OUTPUT_TOKENS
        ):
            raise RuntimeError("Provider usage exceeded reserved bounds; review required")
        if observed["input_tokens"] + observed["output_tokens"] == 0:
            raise RuntimeError("Provider usage missing; reserved cost retained")
        cost = (
            Decimal(observed["input_tokens"]) * input_price
            + Decimal(observed["output_tokens"]) * output_price
        ) / Decimal(1_000_000)
        # Durable reconciliation precedes publication; failed reconciliation retains reserve.
        candidate = result.final_output
        if isinstance(candidate, BaseModel):
            candidate = candidate.model_dump(mode="json")
        if not isinstance(candidate, dict):
            candidate = {"invalid_output_type": type(candidate).__name__}
        if self.workflow_version == LOG_WORKFLOW_VERSION:
            # Reconciled candidates also carry application identity. The workflow must
            # still validate their source spans and handoffs before checkpointing.
            candidate = {
                "binding": self.stage_bindings[stage].model_dump(mode="json"),
                "stage": stage,
                "input_sha256": self.stage_input_hashes[stage],
                "output": candidate,
            }
        elif self.workflow_version == ERROR_ANALYSIS_WORKFLOW_VERSION:
            candidate = {
                "binding": self.stage_bindings[stage].model_dump(mode="json"),
                "stage": stage,
                "input_sha256": self.stage_input_hashes[stage],
                "output": candidate,
            }
        responses = getattr(result, "raw_responses", ())
        request_id = getattr(responses[-1], "request_id", None) if responses else None
        await self.ledger.reconcile(
            reservation,
            observed,
            cost,
            trace_payload={
                "input": {"instructions": instructions, "payload": payload},
                "output": candidate,
                "schema_name": output_type.__name__,
                "validation_status": "pending_workflow_validation",
            },
            provider_request_id=request_id if isinstance(request_id, str) else None,
        )
        for key, value in observed.items():
            self.usage[key] += value
        self.cost_usd += getattr(self.ledger, "reconciled_costs", {}).get(reservation, cost)
        self.usage_complete = previous_usage_complete
        return output_type.model_validate(result.final_output)
