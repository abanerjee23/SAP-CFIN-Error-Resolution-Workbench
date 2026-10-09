"""Queue paid evaluations for saved private snapshots; dispatch remains worker-gated."""

import hashlib
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from cfin.arize_evaluation import PreparedEvaluation, prepare_saved_run_evaluation
from cfin.config import Settings
from cfin.factual_evaluation import (
    FACTUAL_RUBRIC_VERSION,
    factual_human_review_packet,
    factual_review_checklist,
    load_factual_expectations,
    prepare_factual_run_evaluation,
)
from cfin.factual_operations import visible_factual_result
from cfin.gateway import UserGateway
from cfin.model_adapter import PRICE_VERSION, PRICES


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    case_ids: list[UUID] = Field(min_length=1, max_length=30)
    repeats: StrictInt = Field(default=1, ge=1, le=3)
    reason: str = Field(min_length=1, max_length=1000)
    models: dict[Literal["agent1", "agent2", "agent3"], str] | None = None
    reasoning_effort: Literal["low", "medium", "high"] = "medium"

    @field_validator("case_ids")
    @classmethod
    def unique_cases(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Select each case once")
        return values

    @field_validator("reason")
    @classmethod
    def reason_is_nonempty(cls, value):
        if not value.strip():
            raise ValueError("An evaluation purpose is required")
        return value.strip()


async def queue_evaluations(
    user: UserGateway, settings: Settings, token: str, actor_id: UUID, body: EvaluationRequest
) -> dict:
    await user.require_member(token, actor_id, body.workspace_id, "process_owner")
    models = {
        "agent1": settings.model_agent_1,
        "agent2": settings.model_agent_2,
        "agent3": settings.model_agent_3,
        **(body.models or {}),
    }
    if any(model not in PRICES for model in models.values()):
        raise HTTPException(422, "Evaluation model needs verified pricing")
    configuration = {
        "models": models,
        "reasoning_effort": body.reasoning_effort,
        "price_version": PRICE_VERSION,
        "evaluation_only": True,
        "run_budget_usd": str(settings.model_run_budget_usd),
    }
    result = await user.rpc(
        "cfin_queue_evaluations",
        token,
        {
            "workspace_id": str(body.workspace_id),
            "case_ids": [str(x) for x in body.case_ids],
            "repeats": body.repeats,
            "reason": body.reason.strip(),
            "configuration": configuration,
        },
    )
    return {**result, "paid_dispatch_enabled": settings.models_configured}


async def _bounded_rows(
    user: UserGateway,
    table: str,
    token: str,
    workspace_id: UUID,
    filters: dict[str, str],
    *,
    maximum: int,
) -> list[dict[str, Any]]:
    """Read explicit small pages; never assume PostgREST honours a >1000 limit."""
    result: list[dict[str, Any]] = []
    seen = set()
    while len(result) <= maximum:
        size = min(100, maximum + 1 - len(result))
        page = await user.rows(
            table,
            token,
            workspace_id,
            {
                **filters,
                "offset": str(len(result)),
                "limit": str(size),
            },
        )
        for row in page:
            identifier = row.get("id")
            if not isinstance(identifier, str) or identifier in seen:
                raise HTTPException(503, "Evaluation rows changed during pagination; refresh")
            seen.add(identifier)
        result.extend(page)
        if len(result) > maximum:
            raise HTTPException(503, "Evaluation scope exceeds its documented bound")
        if len(page) < size:
            return result
    return result


def _in_ids(ids: list[str]) -> str:
    # Database-read IDs are checked as UUIDs before entering PostgREST syntax.
    return "in.(" + ",".join(str(UUID(x)) for x in ids) + ")"


async def evaluation_status(
    user: UserGateway,
    token: str,
    actor_id: UUID,
    workspace_id: UUID,
    page: int = 1,
    page_size: int = 25,
    batch_id: UUID | None = None,
) -> dict[str, Any]:
    await user.require_member(token, actor_id, workspace_id)
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(422, "Choose a bounded evaluation page")
    batches = await user.rows(
        "evaluation_batches",
        token,
        workspace_id,
        {
            "order": "created_at.desc,id.desc",
            "limit": "1" if batch_id else "21",
            **({"id": f"eq.{batch_id}"} if batch_id else {}),
        },
    )
    if batch_id and not batches:
        raise HTTPException(404, "Evaluation batch not found")
    has_more_batches = len(batches) > 20
    batches = batches[:20]
    ids = [row["id"] for row in batches]
    summaries = (
        await _bounded_rows(
            user,
            "analysis_runs",
            token,
            workspace_id,
            {
                "evaluation_only": "eq.true",
                "evaluation_batch_id": _in_ids(ids),
                "order": "created_at.desc,id.desc",
                "select": "id,evaluation_batch_id,evaluation_repeat,case_id,state,created_at",
            },
            maximum=len(ids) * 90,
        )
        if ids
        else []
    )
    selected = summaries[(page - 1) * page_size : page * page_size]
    selected_ids = [row["id"] for row in selected]
    runs = (
        await _bounded_rows(
            user,
            "analysis_runs",
            token,
            workspace_id,
            {
                "id": _in_ids(selected_ids),
                "evaluation_only": "eq.true",
                "order": "created_at.desc,id.desc",
                "select": (
                    "id,workspace_id,case_id,attempt_id,evaluation_batch_id,evaluation_repeat,"
                    "state,output,error_code,created_at,workflow_version,schema_version,prompt_versions,"
                    "model_configuration,input_revision,source_manifest_sha256"
                ),
            },
            maximum=len(selected_ids),
        )
        if selected_ids
        else []
    )
    calls = (
        await _bounded_rows(
            user,
            "stage_calls",
            token,
            workspace_id,
            {
                "run_id": _in_ids(selected_ids),
                "order": "created_at.asc,id.asc",
                "select": "id,run_id,stage,invocation,model_id,state,reserved_usd,actual_usd,usage",
            },
            maximum=len(selected_ids) * 6,
        )
        if selected_ids
        else []
    )
    for row in runs:
        if row.get("workflow_version") == "log-only-v1" and row.get("output"):
            row["output"] = await visible_factual_result(user, token, workspace_id, row["output"])
            row["human_semantic_review"] = factual_review_checklist()
    by_batch = {}
    for batch in batches:
        relevant = [r for r in summaries if r["evaluation_batch_id"] == batch["id"]]
        by_batch[batch["id"]] = {
            "total_runs": len(relevant),
            "run_states": dict(Counter(r["state"] for r in relevant)),
            "case_ids": sorted({r["case_id"] for r in relevant}),
            "repeats": len({r["evaluation_repeat"] for r in relevant}),
        }
    return {
        "batches": [{**row, **by_batch[row["id"]]} for row in batches],
        "runs": runs,
        "stage_calls": calls,
        "total_runs": len(summaries),
        "page": page,
        "page_size": page_size,
        "has_more_runs": page * page_size < len(summaries),
        "has_more_batches": has_more_batches,
        "scope": "selected batch" if batch_id else "latest twenty accessible workspace batches",
        "as_of_semantics": "Live paginated read; refresh if runs change while loading.",
        "human_review_status": "pending",
        "quality_baseline_established": False,
    }


async def saved_model_runs(
    user: UserGateway,
    token: str,
    actor_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read one bounded batch for evaluation/export with immutable source snapshots."""
    await user.require_member(token, actor_id, workspace_id)
    batches = await user.rows(
        "evaluation_batches",
        token,
        workspace_id,
        {
            "id": f"eq.{batch_id}",
            "limit": "1",
        },
    )
    if len(batches) != 1:
        raise HTTPException(404, "Evaluation batch not found")
    runs = await _bounded_rows(
        user,
        "analysis_runs",
        token,
        workspace_id,
        {
            "evaluation_only": "eq.true",
            "evaluation_batch_id": f"eq.{batch_id}",
            "order": "case_id.asc,evaluation_repeat.asc,id.asc",
        },
        maximum=90,
    )
    if any(
        r.get("evaluation_only") is not True
        or r.get("workspace_id") != str(workspace_id)
        or r.get("evaluation_batch_id") != str(batch_id)
        for r in runs
    ):
        raise HTTPException(503, "Saved evaluation scope differs from its batch")
    calls = (
        await _bounded_rows(
            user,
            "stage_calls",
            token,
            workspace_id,
            {
                "run_id": _in_ids([r["id"] for r in runs]),
                "order": "created_at.asc,id.asc",
                "select": "id,run_id,stage,invocation,model_id,state,reserved_usd,actual_usd,usage",
            },
            maximum=len(runs) * 6,
        )
        if runs
        else []
    )
    # Native outputs retain the historical material actually supplied to Agent 3
    # for the private audit record. A fresh export must not copy unused or now
    # withdrawn material into a report or external evaluation destination.
    visible_runs = []
    for row in runs:
        output = row.get("output")
        if row.get("workflow_version") != "log-only-v1" or not output:
            visible_runs.append(row)
            continue
        visible = await visible_factual_result(user, token, workspace_id, output)
        references = (visible.get("summary") or {}).get("related_cases", [])
        keys = {
            (reference["knowledge_id"], reference["knowledge_version"], reference["case_id"])
            for reference in references
        }
        history = output.get("history") or {}
        candidates = history.get("candidates", [])
        retained = [
            candidate
            for candidate in candidates
            if (candidate["knowledge_id"], candidate["knowledge_version"], candidate["case_id"])
            in keys
        ]
        visible["history"]["candidates"] = retained
        visible_runs.append(
            {
                **row,
                "output": visible,
                "history_read_projection": {
                    "kind": "currently_eligible_cited_history",
                    "saved_history_sha256": hashlib.sha256(
                        json.dumps(
                            history, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                    "saved_candidate_case_ids": [candidate["case_id"] for candidate in candidates],
                    "withheld_candidate_count": len(candidates) - len(retained),
                    "limitation": (
                        "Exported history is an access-checked projection; the private saved "
                        "run retains its original history for audit."
                    ),
                },
            }
        )
    return batches[0], visible_runs, calls


def prepare_model_evaluation(runs: list[dict[str, Any]]) -> PreparedEvaluation:
    """Code checks saved model runs; semantic quality remains a human review task."""
    completed = [r for r in runs if r.get("state") in ("succeeded", "failed", "historical")]
    if not completed:
        raise HTTPException(
            409,
            "No completed model runs are available for saved-output evaluation",
        )
    if any(r.get("evaluation_only") is not True for r in completed):
        raise HTTPException(422, "Export only explicit evaluation runs")
    factual = [run for run in completed if run.get("workflow_version") == "log-only-v1"]
    legacy = [run for run in completed if run.get("workflow_version") != "log-only-v1"]
    if any((run.get("output") or {}).get("result_kind") == "factual" for run in legacy):
        raise HTTPException(422, "Factual evaluation requires its explicit workflow version")
    prepared = prepare_saved_run_evaluation(legacy) if legacy else PreparedEvaluation(())
    factual_prepared = (
        prepare_factual_run_evaluation(factual) if factual else PreparedEvaluation(())
    )
    records = list(factual_prepared.records)
    for record in prepared.records:
        output = json.loads(record.output_json)
        output["kind"] = "persisted_model_evaluation_run"
        records.append(
            replace(
                record,
                kind="persisted_model_evaluation_run",
                output_json=json.dumps(output),
                metadata={
                    **record.metadata,
                    "provenance": "persisted_model_evaluation_run",
                    "evaluation_only": "true",
                },
            )
        )
    return PreparedEvaluation(tuple(records))


def saved_evaluation_report(
    batch: dict[str, Any],
    runs: list[dict[str, Any]],
    prepared: PreparedEvaluation,
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_calls = 0
    observed_cost = Decimal("0")
    for call in calls:
        usage = call.get("usage") or {}
        if type(usage.get("input_tokens")) is int and usage["input_tokens"] > 0:
            observed_calls += 1
        if call.get("actual_usd") is not None:
            cost = Decimal(str(call["actual_usd"]))
            if cost.is_finite() and cost >= 0:
                observed_cost += cost
    factual_runs = [run for run in runs if run.get("workflow_version") == "log-only-v1"]
    factual_review = None
    if factual_runs:
        try:
            corpus = load_factual_expectations()
            expectations = {
                key: corpus[key] for key in ("suite_id", "content_sha256", "review_status")
            }
        except (OSError, ValueError, KeyError):
            expectations = {"review_status": "unavailable"}
        factual_review = {
            "rubric_version": FACTUAL_RUBRIC_VERSION,
            "expectation_corpus": expectations,
            "expectations_bound_to_saved_cases": False,
            "semantic_dimensions": factual_review_checklist(),
            "quality_baseline_established": False,
            "limitation": (
                "Saved cases require explicit expectation matching and human semantic review."
            ),
        }
    return {
        "schema_version": "cfin-saved-model-evaluation-v1",
        "evaluation_only": True,
        "source": "durable_private_model_evaluation_runs",
        "batch": batch,
        "source_runs": [r for r in runs if r.get("state") in ("succeeded", "failed", "historical")],
        "source_run_states": dict(Counter(r["state"] for r in runs)),
        "excluded_pending_runs": sum(r.get("state") in ("queued", "running") for r in runs),
        "provider_calls_this_command": 0,
        "judge_calls_this_command": 0,
        "source_observed_provider_calls": observed_calls,
        "source_observed_cost_usd": str(observed_cost),
        "source_stage_calls": calls,
        "source_usage_complete": all(
            bool(c.get("usage")) and c.get("actual_usd") is not None
            for c in calls
            if c.get("state") != "not_sent"
        ),
        "code_evaluation": prepared.report(),
        "factual_review": factual_review,
        "human_review_packet": factual_human_review_packet(runs, prepared)
        if factual_runs
        else None,
        "quality_baseline_established": False,
        "human_review_status": "pending",
    }
