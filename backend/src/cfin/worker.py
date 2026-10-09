"""One durable, database-fenced worker. Run with python -m cfin.worker --once."""

import argparse
import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException

from cfin.arize_tracing import ArizeTraceResult, AutoArizeTracing
from cfin.config import Settings
from cfin.contracts import Preparation
from cfin.error_analysis_contracts import ErrorAnalysisBinding
from cfin.error_analysis_snapshots import restore_error_analysis_inputs
from cfin.error_analysis_workflow import ErrorAnalysisWorkflowExecutor
from cfin.error_route_registry import SupabaseRouteRegistry
from cfin.gateway import ServiceGateway
from cfin.knowledge import register_history_for_run, search_for_run
from cfin.log_only_contracts import EvidenceSelection, ExecutionBinding, hydrate_selection
from cfin.log_only_snapshots import restore_log_inputs
from cfin.log_only_workflow import LogWorkflowExecutor
from cfin.model_adapter import MAX_OUTPUT_TOKENS, PRICE_VERSION, OpenAIStageAdapter
from cfin.notifications import process_notification
from cfin.snapshots import restore_inputs
from cfin.workflow import PROMPT_VERSION, WorkflowExecutor, validate_stage_output


class CloudCallLedger:
    def __init__(
        self,
        cloud: ServiceGateway,
        job: dict,
        settings: Settings | None = None,
        *,
        workflow_version: str = "legacy-v1",
    ):
        self.cloud = cloud
        self.job = job
        self.monthly_budget = settings.model_monthly_budget_usd if settings else Decimal("10")
        self.run_budget = settings.model_run_budget_usd if settings else Decimal("1")
        self.invocations: dict[str, int] = {}
        self.last_calls: dict[str, str] = {}
        self.cached_outputs: dict[str, Any] = {}
        self.reused_from: dict[str, str] = {}
        self.total_usage = {"input_tokens": 0, "output_tokens": 0}
        self.total_cost_usd = Decimal("0")
        self.usage_complete = True
        self.dispatch_counts: dict[str, int] = {}
        self.reconciled_costs: dict[str, Decimal] = {}
        self.stage_remaining_seconds: dict[str, float] = {}
        self.stage_timeout_seconds = settings.stage_timeout_seconds if settings else 60
        self.workflow_version = workflow_version

    async def resume(self) -> None:
        saved = await self.cloud.rpc("cfin_stage_resume", self.lease())
        self.cached_outputs = dict(saved["outputs"])
        self.reused_from = dict(saved.get("reused_from", {}))
        for call in saved["calls"]:
            stage = call["stage"].replace("agent_", "agent")
            self.invocations[stage] = max(self.invocations.get(stage, 0), call["invocation"] + 1)
            if call["state"] != "not_sent":
                if call.get("created_at"):
                    started = datetime.fromisoformat(call["created_at"].replace("Z", "+00:00"))
                    if started.tzinfo is None:
                        raise RuntimeError("Saved stage dispatch time must include timezone")
                    remaining = max(
                        0.0,
                        self.stage_timeout_seconds - (datetime.now(UTC) - started).total_seconds(),
                    )
                    self.stage_remaining_seconds[stage] = min(
                        self.stage_remaining_seconds.get(stage, remaining), remaining
                    )
                self.dispatch_counts[stage] = self.dispatch_counts.get(stage, 0) + 1
                usage = call.get("usage")
                cost = call.get("actual_usd")
                if (
                    isinstance(usage, dict)
                    and cost is not None
                    and all(
                        isinstance(usage.get(key), int)
                        and not isinstance(usage[key], bool)
                        and usage[key] >= 0
                        for key in self.total_usage
                    )
                    and Decimal(str(cost)).is_finite()
                    and Decimal(str(cost)) >= 0
                ):
                    for key in self.total_usage:
                        self.total_usage[key] += usage[key]
                    self.total_cost_usd += Decimal(str(cost))
                else:
                    self.usage_complete = False
            if call["state"] == "succeeded" and isinstance(call.get("output"), dict):
                candidate = call["output"].get("output")
                if isinstance(candidate, dict):
                    self.cached_outputs.setdefault(stage, candidate)
            self.last_calls[stage] = call["id"]

    async def record_validated(self, stage: str, output: dict[str, Any]) -> None:
        await self.cloud.rpc(
            (
                "cfin_error_analysis_save_stage"
                if self.workflow_version == "error-analysis-v1"
                else "cfin_save_stage"
            ),
            {
                **self.lease(),
                "stage": stage,
                "output": output,
                "source_run_id": self.reused_from.get(stage),
            },
        )
        self.cached_outputs[stage] = output

    async def record_failed(self, stage: str) -> None:
        # Failure markers are workflow-neutral; the lease and stage call retain
        # the exact run workflow for later resume.
        self.cached_outputs.pop(stage, None)
        if stage in self.last_calls:
            await self.cloud.rpc(
                "cfin_fail_stage",
                {
                    **self.lease(),
                    "call_id": self.last_calls[stage],
                    "stage": stage,
                },
            )
        else:
            await self.cloud.rpc("cfin_fail_stage", {**self.lease(), "stage": stage})

    def lease(self) -> dict:
        return {"job_id": self.job["id"], "lease_token": self.job["lease_token"]}

    async def reserve(
        self, stage: str, model: str, input_bound: int, output_bound: int, price_version: str
    ) -> str:
        try:
            result = await self.cloud.rpc(
                "cfin_reserve_call",
                {
                    **self.lease(),
                    "stage": stage.replace("agent", "agent_"),
                    "invocation": self.invocations.get(stage, 0),
                    "model_id": model,
                    "max_input_tokens": input_bound,
                    "max_output_tokens": output_bound,
                    "monthly_budget_usd": str(self.monthly_budget),
                    "run_budget_usd": str(self.run_budget),
                },
            )
        except HTTPException as exc:
            raise RuntimeError("Durable model budget reservation failed") from exc
        if not result.get("execute") or result["call"]["price_version"] != price_version:
            raise RuntimeError("Invocation already dispatched or verified pricing differs")
        self.invocations[stage] = self.invocations.get(stage, 0) + 1
        self.last_calls[stage] = result["call"]["id"]
        return result["call"]["id"]

    async def reconcile(
        self,
        reservation_id: str,
        usage: dict[str, int],
        cost_usd: Decimal,
        *,
        trace_payload: dict[str, Any] | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        try:
            row = await self.cloud.rpc(
                "cfin_reconcile_call",
                {
                    **self.lease(),
                    "call_id": reservation_id,
                    "state": "succeeded",
                    "usage": usage,
                    "output": trace_payload,
                    "provider_request_id": provider_request_id,
                },
            )
        except HTTPException as exc:
            raise RuntimeError("Durable model usage reconciliation failed") from exc
        try:
            valid = (
                row["id"] == reservation_id
                and row["state"] == "succeeded"
                and row["usage"] == usage
                and row["actual_usd"] is not None
                and Decimal(str(row["actual_usd"])).is_finite()
                and Decimal(str(row["actual_usd"])) >= 0
            )
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise RuntimeError("Durable usage remains unknown; publication is blocked")
        self.reconciled_costs[reservation_id] = Decimal(str(row["actual_usd"]))


async def process_one(
    cloud: ServiceGateway, settings: Settings, worker_id: str, *, target_run_id: str | None = None
) -> dict:
    if not settings.models_configured:
        raise RuntimeError("Configure model IDs, OpenAI key and PAID_MODELS_ENABLED first")
    # Optional SDK/exporter setup runs before a lease exists.
    # Only the actual claimed row supplies correlation; no placeholder IDs or
    # Runner traces are created while the queue is still unclaimed.
    with AutoArizeTracing(settings, metadata=None) as telemetry:
        claim = {"worker_id": worker_id, "log_only_enabled": settings.log_only_enabled}
        if target_run_id is not None:
            claim["run_id"] = str(UUID(target_run_id))
        claimed = await cloud.rpc("cfin_claim_job", claim)
        if not claimed.get("claimed"):
            return {"claimed": False}
        job, run = claimed["job"], claimed["run"]
        if telemetry.enabled:
            telemetry.bind_metadata(
                {
                    "run_id": run["id"],
                    "workspace_id": run["workspace_id"],
                    "case_id": run["case_id"],
                    "attempt_id": run["attempt_id"],
                }
            )
        lease = {"job_id": job["id"], "lease_token": job["lease_token"]}
        adapter = None
        work_task = heartbeat_task = None
        output = None
        error_code = None

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(25)
                await cloud.rpc("cfin_heartbeat_job", lease)

        async def execute() -> dict:
            nonlocal adapter
            version = run.get("workflow_version", "legacy-v1")
            if version == "error-analysis-v1":
                if not settings.log_only_enabled:
                    raise RuntimeError("Error Analysis dispatch is disabled")
                binding = ErrorAnalysisBinding(
                    workspace_id=run["workspace_id"],
                    run_id=run["id"],
                    case_id=run["case_id"],
                    attempt_id=run["attempt_id"],
                    input_revision=str(run["input_revision"]),
                    workflow_version=version,
                    schema_version=run["schema_version"],
                    source_manifest_sha256=run["source_manifest_sha256"],
                    prompt_versions=run["prompt_versions"],
                    model_configuration=run["model_configuration"],
                )
                originals = await restore_error_analysis_inputs(
                    run["snapshot"], cloud, expected_binding=binding
                )
                ledger = CloudCallLedger(cloud, job, settings, workflow_version="error-analysis-v1")
                await ledger.resume()
                models = binding.model_configuration
                run_settings = settings.model_copy(
                    update={
                        "model_agent_1": models["agent1"],
                        "model_agent_2": models["agent2"],
                        "model_agent_3": models["agent3"],
                        "model_reasoning_effort": models["reasoning_effort"],
                    }
                )
                adapter = OpenAIStageAdapter(
                    run_settings,
                    ledger,
                    workflow_version=version,
                    tracing_enabled=telemetry.enabled,
                    trace_metadata=telemetry.trace_metadata,
                )
                from cfin.factual_history import FactualHistoryReader

                routing_context = {
                    key: value
                    for key, value in (run["snapshot"].get("routing_context") or {}).items()
                    if isinstance(key, str) and isinstance(value, str) and value.strip()
                }
                history = FactualHistoryReader(
                    cloud,
                    binding,  # field-compatible binding; only scope identity is used by retrieval
                    run["requested_by"],
                    excluded_case_ids=run.get("excluded_case_ids", ()),
                    routing_context=routing_context,
                )

                async def error_history(extraction, analysis_payload):
                    history.category_id = analysis_payload["category_id"]
                    selection = EvidenceSelection(
                        selected_entry_ids=[entry.entry_id for entry in extraction.entries],
                        unresolved_entry_ids=[
                            entry.entry_id for entry in extraction.entries if entry.ambiguity
                        ],
                    )
                    hydrated = hydrate_selection(
                        originals.manifest,
                        extraction,
                        selection,
                        limitations=extraction.extraction_limitations,
                    )
                    return await history.retrieve(hydrated)

                execution = await ErrorAnalysisWorkflowExecutor(
                    adapter,
                    binding,
                    SupabaseRouteRegistry(cloud),
                    timeout_seconds=settings.stage_timeout_seconds,
                    max_retries=settings.stage_max_retries,
                    history_reader=error_history,
                ).run(originals, routing_context=routing_context)
                result = execution.result
                if result.case_content and result.case_content.related_cases:
                    await register_history_for_run(
                        cloud,
                        binding.workspace_id,
                        run["requested_by"],
                        binding.run_id,
                        [
                            {"id": item.knowledge_id, "version": item.knowledge_version}
                            for item in result.case_content.related_cases
                        ],
                    )
                stats = execution.as_dict()
                stats.pop("result")
                return {
                    **result.model_dump(mode="json"),
                    **stats,
                    "evaluation_only": bool(run.get("evaluation_only")),
                    "errors": [result.failure_reason] if result.outcome != "completed" else [],
                }
            if version == "log-only-v1":
                if not settings.log_only_enabled:
                    raise RuntimeError("Factual dispatch is disabled")
                # Build from the leased run row, independently of the saved input.
                binding = ExecutionBinding(
                    workspace_id=run["workspace_id"],
                    run_id=run["id"],
                    case_id=run["case_id"],
                    attempt_id=run["attempt_id"],
                    input_revision=str(run["input_revision"]),
                    workflow_version=version,
                    schema_version=run["schema_version"],
                    source_manifest_sha256=run["source_manifest_sha256"],
                    prompt_versions=run["prompt_versions"],
                    model_configuration=run["model_configuration"],
                )
                originals = await restore_log_inputs(
                    run["snapshot"], cloud, expected_binding=binding
                )
                ledger = CloudCallLedger(cloud, job, settings)
                await ledger.resume()
                models = binding.model_configuration
                run_settings = settings.model_copy(
                    update={
                        "model_agent_1": models.agent1,
                        "model_agent_2": models.agent2,
                        "model_agent_3": models.agent3,
                        "model_reasoning_effort": models.reasoning_effort,
                    }
                )
                adapter = OpenAIStageAdapter(
                    run_settings,
                    ledger,
                    workflow_version=version,
                    tracing_enabled=telemetry.enabled,
                    trace_metadata=telemetry.trace_metadata,
                )
                from cfin.factual_history import FactualHistoryReader

                history_reader = FactualHistoryReader(
                    cloud,
                    binding,
                    run["requested_by"],
                    excluded_case_ids=run.get("excluded_case_ids", ()),
                )
                execution = await LogWorkflowExecutor(
                    adapter,
                    binding,
                    timeout_seconds=settings.stage_timeout_seconds,
                    max_retries=settings.stage_max_retries,
                    history_reader=history_reader.retrieve,
                ).run(originals)
                factual = await history_reader.finalize(execution.result)
                stats = execution.as_dict()
                stats.pop("result")
                return {
                    **factual.model_dump(mode="json"),
                    **stats,
                    "evaluation_only": bool(run.get("evaluation_only")),
                    "errors": [factual.failure_reason] if factual.outcome != "completed" else [],
                }
            if version != "legacy-v1":
                raise RuntimeError("Unsupported pinned workflow version")
            inputs = await restore_inputs(run["snapshot"], cloud)
            history = await search_for_run(
                cloud,
                run["workspace_id"],
                run["requested_by"],
                {
                    **inputs.manifest.business_context.model_dump(mode="json"),
                    "error_text": inputs.original_log[:1000],
                    "target_system": inputs.manifest.identity.target_system,
                    "company_code": inputs.manifest.identity.source_company_code,
                },
            )
            await register_history_for_run(
                cloud, run["workspace_id"], run["requested_by"], run["id"], history
            )
            ledger = CloudCallLedger(cloud, job, settings)
            await ledger.resume()
            run_settings = settings
            if run.get("evaluation_only"):
                configuration = run["snapshot"]["evaluation_configuration"]
                models = configuration["models"]
                run_settings = settings.model_copy(
                    update={
                        "model_agent_1": models["agent1"],
                        "model_agent_2": models["agent2"],
                        "model_agent_3": models["agent3"],
                        "model_reasoning_effort": configuration["reasoning_effort"],
                    }
                )
            if (
                not run.get("evaluation_only")
                and "agent1" not in ledger.cached_outputs
                and not ledger.invocations.get("agent1")
            ):
                try:
                    reusable = await cloud.rpc(
                        "cfin_preparation_reuse",
                        {
                            **lease,
                            "prompt_version": PROMPT_VERSION,
                            "model_id": run_settings.model_agent_1,
                            "reasoning_effort": run_settings.model_reasoning_effort,
                        },
                    )
                    if reusable.get("reused") is True:
                        source_run = str(UUID(reusable["source_run_id"]))
                        preparation = Preparation.model_validate(reusable["preparation"])
                        if source_run == run["id"] or preparation.run_id != source_run:
                            raise ValueError("Reuse must identify its distinct actual source run")
                        preparation = preparation.model_copy(update={"run_id": run["id"]})
                        if (
                            preparation.attempt_id != inputs.manifest.attempt_id
                            or preparation.input_source_version != inputs.manifest.source_version
                        ):
                            raise ValueError("Preparation reuse changed attempt/source version")
                        validate_stage_output("agent1", preparation, inputs)
                        ledger.cached_outputs["agent1"] = preparation.model_dump(mode="json")
                        ledger.reused_from["agent1"] = source_run
                except (HTTPException, ValueError, KeyError, TypeError):
                    # Reuse is optional. A mismatched/unavailable older candidate
                    # receives no checkpoint; the normal reserved stage runs instead.
                    pass
            adapter = OpenAIStageAdapter(
                run_settings,
                ledger,
                tracing_enabled=telemetry.enabled,
                trace_metadata=telemetry.trace_metadata,
            )
            result = await WorkflowExecutor(
                adapter,
                run_id=run["id"],
                timeout_seconds=settings.stage_timeout_seconds,
                max_retries=settings.stage_max_retries,
                history=history,
            ).run(inputs)
            value = result.as_dict()
            value["evaluation_only"] = bool(run.get("evaluation_only"))
            # Save the actual dispatch configuration so later comparisons can reproduce
            # this baseline even after local model/effort settings change.
            value["model_configuration"] = {
                "models": dict(adapter.models),
                "reasoning_effort": run_settings.model_reasoning_effort,
                "service_tier": "default",
                "price_version": PRICE_VERSION,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            }
            value["source_catalogue"] = [
                source.model_dump(mode="json") for source in inputs.catalogue
            ]
            value["reviewed_history_sources"] = [
                {"id": row["id"], "version": row["version"]} for row in history
            ]
            # Pending uploaded role labels are not an approved owner directory.
            # Assignment remains an explicit process-owner action until a verified
            # authenticated binding is supplied through governance.
            value["auto_owner"] = None
            supported = result.diagnosis and any(f.supported for f in result.diagnosis.findings)
            value.update(
                category=(
                    "multiple_blockers"
                    if result.routing.reason.value == "multiple_blockers"
                    else next(f.cause.value for f in result.diagnosis.findings if f.supported)
                    if supported
                    else "cause_not_established"
                ),
                affected_object=result.preparation.affected_object
                if result.preparation
                else "unknown",
                diagnosis_status=result.diagnosis.status if result.diagnosis else "needs_review",
                description=result.brief.description if result.brief else result.routing.detail,
            )
            return value

        try:
            heartbeat_task = asyncio.create_task(heartbeat())
            work_task = asyncio.create_task(execute())
            done, _ = await asyncio.wait(
                (work_task, heartbeat_task), return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat_task in done:
                heartbeat_task.result()
                raise RuntimeError("Worker lease lost")
            output = work_task.result()
            if output["errors"]:
                error_code = output["errors"][0]
        except (HTTPException, ValueError, RuntimeError, KeyError):
            error_code = "worker_execution_failed"
        finally:
            for task in (work_task, heartbeat_task):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (work_task, heartbeat_task) if task), return_exceptions=True
            )
            if adapter:
                await adapter.close()
        result = await cloud.rpc(
            (
                "cfin_error_analysis_complete_run"
                if run.get("workflow_version") == "error-analysis-v1"
                else "cfin_complete_run"
            ),
            {**lease, "succeeded": error_code is None, "output": output, "error_code": error_code},
        )
        try:
            tracing_result = telemetry.flush(
                business_committed=True, run_state="succeeded" if error_code is None else "failed"
            )
        except Exception:
            # Telemetry is optional; the authoritative business commit already succeeded.
            tracing_result = ArizeTraceResult(
                "export_failed", True, error_code="optional_telemetry_error"
            )
        return {
            "claimed": True,
            "run_id": run["id"],
            "succeeded": error_code is None,
            **result,
            "arize": asdict(tracing_result),
        }


async def run_worker(once: bool, *, target_run_id: str | None = None) -> None:
    settings = Settings()
    if not settings.worker_configured:
        raise RuntimeError("Worker setup is incomplete; run python -m cfin.readiness")
    if target_run_id and (not once or not settings.models_configured):
        raise RuntimeError("A targeted run requires --once and explicitly enabled model execution")
    async with httpx.AsyncClient(timeout=15) as client:
        cloud = ServiceGateway(settings, client)
        worker_id = "cfin-local-" + str(uuid4())
        while True:
            notification = (
                await process_notification(cloud)
                if target_run_id is None
                else {"processed": False, "reason": "targeted_model_run"}
            )
            result = (
                await process_one(cloud, settings, worker_id, target_run_id=target_run_id)
                if settings.models_configured
                else {"claimed": False, "paid_models_enabled": False}
            )
            result["notification"] = notification
            print(result)
            if once:
                return
            await asyncio.sleep(3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process the private case queue")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--run-id", type=UUID, help="With --once, claim only this queued model run")
    args = parser.parse_args()
    try:
        if args.run_id and not args.once:
            parser.error("--run-id requires --once")
        asyncio.run(run_worker(args.once, target_run_id=str(args.run_id) if args.run_id else None))
    except (RuntimeError, HTTPException):
        parser.exit(
            2,
            "Worker configuration or cloud execution failed; inspect readiness and saved audit.\n",
        )


if __name__ == "__main__":
    main()
