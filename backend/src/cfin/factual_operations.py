"""Human factual review and investigation, independent of legacy diagnostic packs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from cfin.contracts import ValidationCheck
from cfin.gateway import UserGateway


def is_factual(case: dict[str, Any]) -> bool:
    return (
        case.get("workflow_version") == "log-only-v1"
        or (case.get("factual_result") or {}).get("result_kind") == "factual"
    )


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 10_000:
        raise HTTPException(422, "Record " + key.replace("_", " "))
    return value


def gaps(payload: dict[str, Any]) -> list[str]:
    value = payload.get("gaps")
    if (
        not isinstance(value, list)
        or len(value) > 50
        or any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in value)
    ):
        raise HTTPException(422, "Record explicit remaining gaps, or an empty list")
    return value


async def validate_proofs(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    case: dict[str, Any],
    proof_ids: Any,
    *,
    required: bool,
) -> list[str]:
    if proof_ids is None and not required:
        return []
    if (
        not isinstance(proof_ids, list)
        or len(proof_ids) > 20
        or (required and not proof_ids)
        or len(set(map(str, proof_ids))) != len(proof_ids)
    ):
        raise HTTPException(422, "Select distinct saved private proof records")
    checked = []
    for value in proof_ids:
        try:
            identifier = str(UUID(str(value)))
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "Select valid saved proof") from exc
        rows = await user.rows(
            "evidence_versions",
            token,
            workspace_id,
            {
                "id": f"eq.{identifier}",
                "case_id": f"eq.{case['id']}",
                "kind": "eq.proof",
            },
        )
        if (
            len(rows) != 1
            or str(rows[0].get("case_id")) != str(case["id"])
            or str(rows[0].get("workspace_id")) != str(workspace_id)
            or rows[0].get("kind") != "proof"
            or rows[0].get("work_cycle") != case["work_cycle"]
        ):
            raise HTTPException(422, "Proof must belong to this case and work cycle")
        await user.download(token, rows[0])
        checked.append(identifier)
    return checked


async def factual_action(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    case: dict[str, Any],
    action: str,
    data: dict[str, Any],
    common: dict[str, Any],
) -> dict[str, Any]:
    """Validate human inputs; SQL rechecks roles, versions, proofs and transitions."""
    if action in ("review_diagnosis", "approve_reference"):
        raise HTTPException(422, "This factual case uses summary review and human investigation")
    if action == "analyse":
        return await user.rpc("cfin_enqueue_run", token, common)
    if action == "review_summary":
        if data.get("decision") not in ("Accepted", "Corrected", "Insufficient"):
            raise HTTPException(422, "Choose Accepted, Corrected or Insufficient")
        required_text(data, "reason")
        run_id = data.get("run_id")
        if run_id not in (case.get("published_run_id"), case.get("requested_run_id")):
            raise HTTPException(409, "Review the latest saved analysis or failure")
        rows = await user.rows("analysis_runs", token, workspace_id, {"id": f"eq.{run_id}"})
        if (
            len(rows) != 1
            or rows[0].get("case_id") != case["id"]
            or rows[0].get("state") not in ("succeeded", "failed")
            or rows[0].get("attempt_id") != case["current_attempt_id"]
            or rows[0].get("input_revision") != case["input_revision"]
            or rows[0].get(
                "workflow_version",
                rows[0].get("snapshot", {}).get("binding", {}).get("workflow_version"),
            )
            != "log-only-v1"
        ):
            raise HTTPException(409, "Review the current factual run or failure")
        result = rows[0].get("output") or {}
        result = result.get("result", result)
        if data["decision"] == "Accepted" and (
            result.get("outcome") != "completed" or not result.get("summary")
        ):
            raise HTTPException(422, "An unavailable summary cannot be accepted")
        findings = data.get("findings", {})
        if not isinstance(findings, dict):
            raise HTTPException(422, "Record factual review findings")
        if data["decision"] in ("Corrected", "Insufficient"):
            required_text(findings, "explanation")
            gaps(findings)
            if data["decision"] == "Insufficient" and not findings["gaps"]:
                raise HTTPException(422, "Record at least one gap for an insufficient summary")
        entry_ids = findings.get("entry_ids", [])
        known = {entry["entry_id"] for entry in (result.get("extraction") or {}).get("entries", [])}
        if (
            not isinstance(entry_ids, list)
            or any(not isinstance(x, str) for x in entry_ids)
            or len(entry_ids) != len(set(entry_ids))
            or not set(entry_ids) <= known
        ):
            raise HTTPException(422, "Review references must identify saved extracted entries")
        proofs = await validate_proofs(
            user,
            token,
            workspace_id,
            case,
            findings.get("proof_ids"),
            required=False,
        )
        if data["decision"] == "Corrected" and not entry_ids and not proofs:
            raise HTTPException(422, "Corrected facts require saved evidence")
        data["findings"] = {
            "explanation": findings.get("explanation", data["reason"]),
            "gaps": findings.get("gaps", []),
            "entry_ids": entry_ids,
            "proof_ids": proofs,
            "provenance": "human_factual_review",
        }
        data.pop("cause_confirmed", None)
        data.pop("cause_evidence", None)
    elif action in ("start_work", "start_investigation") or (
        action == "resume" and not case.get("work_started_at")
    ):
        required_text(data, "reason")
        required_text(data, "investigation_scope")
        data["work_kind"] = "investigation"
        data.pop("target_change_authority", None)
        data.pop("approved_attributes", None)
    elif action in ("block", "reopen", "resume"):
        required_text(data, "reason")
    elif action in (
        "record_investigation",
        "record_correction",
        "complete_work",
        "finish_resolution",
        "record_reprocessing",
        "record_validation",
    ):
        if data.get("human_confirmed") is not True:
            raise HTTPException(422, "Explicit human attestation is required")
        data["proof_ids"] = await validate_proofs(
            user,
            token,
            workspace_id,
            case,
            data.get("proof_ids"),
            required=True,
        )
        data["provenance"] = "human_investigation"
        if action in (
            "record_investigation",
            "record_correction",
            "complete_work",
            "finish_resolution",
        ):
            for field in ("findings", "action_or_no_change", "outcome", "scope"):
                required_text(data, field)
            gaps(data)
        if action in ("complete_work", "finish_resolution") and data.get("action_kind") not in (
            "corrective_work",
            "no_change",
        ):
            raise HTTPException(422, "Explicitly choose corrective work or no change")
        if action == "record_correction":
            data["action_kind"] = "corrective_work"
            if data.get("target_change_authority") is not True:
                raise HTTPException(
                    422, "Recorded corrective work requires explicit change authority"
                )
            required_text(data, "occurred_at")
            required_text(data, "target_system")
            required_text(data, "target_object")
        if action == "record_reprocessing":
            required_text(data, "attempt_key")
            if data.get("result") != "successful":
                raise HTTPException(
                    422, "Record a successful reprocessing outcome with saved proof"
                )
            if type(data.get("processing_order")) is not int or data["processing_order"] < 1:
                raise HTTPException(422, "Record the observed processing order")
            try:
                timestamp = datetime.fromisoformat(
                    required_text(data, "processing_at").replace("Z", "+00:00")
                )
                if timestamp.tzinfo is None:
                    raise ValueError("Timezone is required")
            except ValueError as exc:
                raise HTTPException(
                    422, "Record the observed processing time with timezone"
                ) from exc
            if not case.get("attempt_order_known") and data.get("chronology_confirmed") is not True:
                raise HTTPException(422, "Explicitly confirm the observed business chronology")
            if data["result"] == "successful":
                required_text(data, "target_document_reference")
        if action == "record_validation":
            required_text(data, "occurred_at")
            required_text(data, "findings")
            gaps(data)
            try:
                checks = [ValidationCheck.model_validate(item) for item in data.get("checks", [])]
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    422, "Record the human expected and observed comparisons"
                ) from exc
            if len(checks) != 4 or {check.dimension for check in checks} != {
                "amount_currency",
                "company",
                "accounts",
                "source_target_reference",
            }:
                raise HTTPException(422, "All four distinct posting comparisons are required")
            if any(
                check.result == "passed" and check.expected != check.observed for check in checks
            ):
                raise HTTPException(422, "An observed discrepancy cannot pass validation")
            data["checks"] = [check.model_dump(mode="json") for check in checks]
            data["status"] = (
                "failed" if any(check.result == "failed" for check in checks) else "passed"
            )
        if action == "finish_resolution":
            required_text(data, "occurred_at")
            # Causes, when found, remain a separate human investigation record.
            data["cause_confirmed"] = False
            data["cause_evidence"] = []
    return await user.rpc("cfin_case_action", token, {**common, "action": action, "data": data})


async def visible_factual_result(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Redact candidate contents and withdrawn history on every authorised portal read."""
    if not result:
        return None
    value = {**result, "history": {**result.get("history", {}), "candidates": []}}
    summary = result.get("summary")
    if not summary:
        return value
    retained = []
    for reference in summary.get("related_cases", []):
        try:
            response = await user.rpc(
                "cfin_revalidate_history",
                token,
                {
                    "workspace_id": str(workspace_id),
                    "ids": [reference["knowledge_id"]],
                },
            )
            if response.get("eligible") is True:
                retained.append(reference)
        except Exception:
            pass
    value["summary"] = {**summary, "related_cases": retained}
    if len(retained) != len(summary.get("related_cases", [])):
        limitation = "Historical references are withheld because access or approval changed."
        value["limitations"] = list(dict.fromkeys([*result.get("limitations", []), limitation]))
        value["history"]["limitation"] = limitation
    return value


async def factual_detail(
    user: UserGateway,
    token: str,
    workspace_id: UUID,
    case: dict[str, Any],
    data: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    result = case.get("factual_result")
    if not result:
        published = next(
            (row for row in data["analysis_runs"] if row["id"] == case.get("published_run_id")),
            None,
        )
        if published:
            result = published.get("output") or None
            if result and "result" in result:
                result = result["result"]
    visible = await visible_factual_result(user, token, workspace_id, result)
    runs = []
    for run in data["analysis_runs"]:
        output = run.get("output")
        if output and output.get("result_kind") == "factual":
            output = await visible_factual_result(user, token, workspace_id, output)
        # Private originals are accessed through the authenticated evidence route.
        runs.append({**run, "output": output})
    cycle = case["work_cycle"]
    records = [
        row
        for row in data["resolution_records"]
        if row["work_cycle"] == cycle and row["attempt_id"] == case["current_attempt_id"]
    ]
    current = next(
        (row for row in data["attempts"] if row["id"] == case["current_attempt_id"]), None
    )
    resolved = bool(
        case["status"] == "document_reprocessed"
        and case.get("attempt_order_known")
        and not case.get("unreviewed_new_failure")
        and current
        and current["result"] == "successful"
        and current["validation_status"] == "passed"
        and records
    )
    expected_context = case.get("business_context", {}).get("routing_context", {})
    available_rules = await user.rows(
        "context_owner_rules",
        token,
        workspace_id,
        {
            "order": "version.desc",
        },
    )
    owner_rules = [
        rule
        for rule in available_rules
        if expected_context and rule.get("context") == expected_context
    ]
    return {
        "case": {**case, "resolved": resolved, "factual_result": visible},
        "evidence": data["evidence_versions"],
        "runs": sorted(runs, key=lambda row: row["created_at"], reverse=True),
        "references": [],
        "attempts": sorted(data["attempts"], key=lambda row: row.get("processing_order") or 0),
        "milestones": sorted(data["milestones"], key=lambda row: row["recorded_at"]),
        "validations": [row for row in data["milestones"] if row["kind"] == "validation"],
        "resolution_records": records,
        "activity": sorted(data["activity"], key=lambda row: row["created_at"], reverse=True),
        "reviews": data["case_reviews"],
        "assignments": data["assignments"],
        "notifications": data["notifications"],
        "owner_rule": max(owner_rules, key=lambda rule: rule["version"], default=None),
        "validation_comparisons": None,
    }
