"""Portal projections and human route actions for `error-analysis-v1`."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException

from cfin.factual_operations import required_text, validate_proofs
from cfin.gateway import UserGateway


def is_error_analysis(case: dict[str, Any]) -> bool:
    return case.get("workflow_version") == "error-analysis-v1"


async def error_analysis_detail(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    case: dict[str, Any],
    data: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    result = case.get("error_analysis_result")
    if not result:
        published = next(
            (row for row in data["analysis_runs"] if row["id"] == case.get("published_run_id")),
            None,
        )
        result = published.get("output") if published else None
    route_milestones = await user.rows(
        "error_route_milestones", token, workspace_id, {"case_id": f"eq.{case['id']}"}
    )
    return {
        "case": {**case, "error_analysis_result": result},
        "evidence": data["evidence_versions"],
        "runs": sorted(data["analysis_runs"], key=lambda row: row["created_at"], reverse=True),
        "references": [],
        "attempts": data["attempts"],
        "milestones": data["milestones"],
        "route_milestones": sorted(route_milestones, key=lambda row: row["recorded_at"]),
        "validations": [],
        "resolution_records": data["resolution_records"],
        "activity": sorted(data["activity"], key=lambda row: row["created_at"], reverse=True),
        "reviews": data["case_reviews"],
        "assignments": data["assignments"],
        "notifications": data["notifications"],
        "owner_rule": None,
        "validation_comparisons": None,
    }


async def record_error_route_step(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    case: dict[str, Any],
    common: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(data.get("note"), str)
        or not data["note"].strip()
        or len(data["note"]) > 10_000
    ):
        raise HTTPException(422, "Record a meaningful route-step note")
    evidence_ids = await validate_proofs(
        user, token, workspace_id, case, data.get("evidence_ids", []), required=False
    )
    return await user.rpc(
        "cfin_error_route_action",
        token,
        {
            **common,
            "data": {
                "note": data["note"],
                "decision": data.get("decision"),
                "posting_reference": data.get("posting_reference"),
                "evidence_ids": evidence_ids,
            },
        },
    )


async def error_workbench_action(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    case: dict[str, Any],
    common: dict[str, Any],
    action: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    if action == "analyse":
        return await user.rpc("cfin_enqueue_run", token, common)
    if action not in ("comment", "record_approval", "set_status", "finish_resolution", "assign"):
        raise HTTPException(422, "Use the governed Error Analysis route actions for this case")
    required_text(data, "note")
    if action == "finish_resolution":
        required_text(data, "posting_reference")
        if data.get("human_confirmed") is not True:
            raise HTTPException(422, "Confirm that posting has been validated")
        if (data.get("reprocessing_status") != "successful"
                or data.get("validation_status") != "passed"):
            raise HTTPException(422, "Confirm successful reprocessing and data validation")
    data = {
        **data,
        "evidence_ids": await validate_proofs(
            user, token, workspace_id, case, data.get("evidence_ids", []),
            required=action in ("finish_resolution", "record_approval"),
        ),
    }
    return await user.rpc(
        "cfin_error_workbench_action",
        token,
        {
            **common,
            "action": action,
            "data": data,
        },
    )
