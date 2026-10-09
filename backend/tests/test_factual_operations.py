"""Human factual controls keep investigation independent of diagnostic restoration."""

import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from cfin.factual_operations import factual_action, visible_factual_result
from cfin.operations import ActionRequest, Operations, SimulationRequest

W = UUID("11111111-1111-4111-8111-111111111111")
C = UUID("22222222-2222-4222-8222-222222222222")
A = UUID("33333333-3333-4333-8333-333333333333")
R = UUID("44444444-4444-4444-8444-444444444444")
P = UUID("55555555-5555-4555-8555-555555555555")


class User:
    def __init__(self):
        self.calls = []
        self.case = {
            "id": str(C),
            "workspace_id": str(W),
            "version": 1,
            "workflow_version": "log-only-v1",
            "status": "created",
            "work_cycle": 1,
            "current_attempt_id": "attempt",
            "input_revision": 1,
            "published_run_id": str(R),
            "requested_run_id": str(R),
        }
        self.proof = {
            "id": str(P),
            "case_id": str(C),
            "workspace_id": str(W),
            "work_cycle": 1,
            "kind": "proof",
        }
        self.run = {
            "id": str(R),
            "case_id": str(C),
            "workflow_version": "log-only-v1",
            "state": "succeeded",
            "attempt_id": "attempt",
            "input_revision": 1,
            "created_at": "2026-10-02",
            "output": {
                "result_kind": "factual",
                "outcome": "completed",
                "summary": {"title": {"text": "Observed failure"}, "related_cases": []},
                "extraction": {"entries": [{"entry_id": "entry-1"}]},
            },
        }
        self.history_eligible = False

    async def require_member(self, *args):
        return {}

    async def rows(self, table, token, workspace, filters=None):
        self.calls.append((table, filters))
        if table == "cases":
            return [self.case]
        if table == "analysis_runs":
            return [self.run]
        if table == "evidence_versions":
            return [self.proof]
        return []

    async def download(self, token, proof):
        self.calls.append(("download", proof["id"]))
        return b"Human supplied observation"

    async def rpc(self, name, token, payload):
        self.calls.append((name, payload))
        if name == "cfin_revalidate_history":
            return {"eligible": self.history_eligible}
        return payload


def action(user, kind, payload):
    return asyncio.run(
        factual_action(
            user, "token", W, user.case, kind, payload, {"case_id": str(C), "workspace_id": str(W)}
        )
    )


def guided():
    return {
        "human_confirmed": True,
        "action_kind": "no_change",
        "proof_ids": [str(P)],
        "findings": "Observed target posting in the attached reconciliation",
        "action_or_no_change": "No SAP changes were required; a prior reprocess completed",
        "outcome": "All four human posting comparisons passed",
        "scope": "Document 0001",
        "gaps": [],
        "occurred_at": "2026-10-02T10:00:00Z",
    }


def test_corrected_summary_accepts_source_evidence_without_cause_label():
    user = User()
    value = action(
        user,
        "review_summary",
        {
            "run_id": str(R),
            "decision": "Corrected",
            "reason": "Correct the preserved account value",
            "findings": {
                "explanation": "Account is 000123, including its leading zeroes",
                "entry_ids": ["entry-1"],
                "gaps": [],
            },
        },
    )
    assert value["data"]["findings"]["provenance"] == "human_factual_review"
    assert "cause_label" not in value["data"]["findings"]


@pytest.mark.parametrize("entry_ids", [[], ["fabricated-entry"]])
def test_corrected_summary_needs_real_evidence(entry_ids):
    user = User()
    with pytest.raises(HTTPException) as exc:
        action(
            user,
            "review_summary",
            {
                "run_id": str(R),
                "decision": "Corrected",
                "reason": "Correction",
                "findings": {
                    "explanation": "Account correction",
                    "entry_ids": entry_ids,
                    "gaps": [],
                },
            },
        )
    assert exc.value.status_code == 422
    assert not any(name == "cfin_case_action" for name, _ in user.calls)


def test_failed_analysis_can_be_reviewed_insufficient_but_not_accepted():
    user = User()
    user.run["state"] = "failed"
    user.run["output"] = {"outcome": "failed"}
    with pytest.raises(HTTPException):
        action(user, "review_summary", {"run_id": str(R), "decision": "Accepted", "reason": "okay"})
    value = action(
        user,
        "review_summary",
        {
            "run_id": str(R),
            "decision": "Insufficient",
            "reason": "Awaiting complete evidence",
            "findings": {
                "explanation": "The extraction did not complete",
                "gaps": ["Retry analysis"],
            },
        },
    )
    assert value["data"]["decision"] == "Insufficient"


def test_start_investigation_does_not_require_or_assert_change_authority():
    user = User()
    value = action(
        user,
        "start_work",
        {
            "reason": "Inspect current failure",
            "investigation_scope": "Compare supplied views",
            "target_change_authority": True,
        },
    )
    assert value["data"]["work_kind"] == "investigation"
    assert "target_change_authority" not in value["data"]


def test_resume_before_initial_start_requires_investigation_scope_without_change_authority():
    user = User()
    user.case["status"] = "blocked"
    with pytest.raises(HTTPException) as exc:
        action(user, "resume", {"reason": "Block removed"})
    assert exc.value.status_code == 422
    assert not user.calls
    value = action(
        user,
        "resume",
        {
            "reason": "Block removed",
            "investigation_scope": "Reconcile supplied original views",
            "target_change_authority": True,
        },
    )
    assert value["data"]["work_kind"] == "investigation"
    assert "target_change_authority" not in value["data"]


def test_resume_of_started_investigation_keeps_existing_scope():
    user = User()
    user.case.update(status="blocked", work_started_at="2026-10-02T10:00:00Z")
    value = action(user, "resume", {"reason": "Required evidence is now available"})
    assert value["data"] == {"reason": "Required evidence is now available"}


@pytest.mark.parametrize("kind", ["block", "reopen", "resume"])
def test_specific_reasons_required(kind):
    with pytest.raises(HTTPException):
        action(User(), kind, {"reason": " "})


def test_bare_fixed_cannot_complete_or_resolve_case():
    for kind in ("complete_work", "finish_resolution"):
        with pytest.raises(HTTPException):
            action(
                User(), kind, {"human_confirmed": True, "proof_ids": [str(P)], "findings": "fixed"}
            )


def test_guided_resolution_uses_human_evidence_and_no_diagnostic_pack():
    user = User()
    value = action(user, "finish_resolution", guided())
    assert value["data"]["provenance"] == "human_investigation"
    assert value["data"]["cause_confirmed"] is False
    assert any(name == "download" for name, _ in user.calls)
    assert not any(name == "analysis_runs" for name, _ in user.calls)


def test_actual_correction_still_requires_explicit_authority():
    with pytest.raises(HTTPException) as exc:
        action(User(), "record_correction", guided())
    assert exc.value.status_code == 422


def test_proof_from_another_cycle_cannot_complete_current_work():
    user = User()
    user.proof["work_cycle"] = 2
    with pytest.raises(HTTPException):
        action(user, "complete_work", guided())


def test_human_validation_cannot_mark_different_expected_observed_as_passed():
    payload = guided()
    payload["checks"] = [
        {"dimension": dimension, "expected": "100", "observed": "101", "result": "passed"}
        for dimension in ("amount_currency", "company", "accounts", "source_target_reference")
    ]
    with pytest.raises(HTTPException):
        action(User(), "record_validation", payload)


def test_factual_detail_skips_legacy_reference_and_snapshot_restoration():
    user = User()
    value = asyncio.run(Operations(user, object()).detail("token", W, C))
    assert value["references"] == [] and value["validation_comparisons"] is None
    assert value["case"]["factual_result"]["summary"]["title"]["text"] == "Observed failure"
    assert not any(name in ("reference_reviews", "intakes", "download") for name, _ in user.calls)


def test_simulation_rejects_factual_case_before_any_legacy_restoration():
    user = User()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            Operations(user, object()).simulate(
                "token",
                A,
                C,
                SimulationRequest(
                    workspace_id=W,
                    acting_role="process_owner",
                    kind="correction",
                    human_confirmed=True,
                ),
            )
        )
    assert exc.value.status_code == 422
    assert not any(name == "analysis_runs" for name, _ in user.calls)


def test_summary_action_is_in_public_request_contract():
    request = ActionRequest(
        workspace_id=W, expected_version=1, acting_role="process_owner", action="review_summary"
    )
    assert request.action == "review_summary"


def test_withdrawn_cached_history_is_not_redisplayed_and_candidates_never_return():
    user = User()
    result = {
        "summary": {
            "title": {"text": "Current facts"},
            "related_cases": [{"knowledge_id": "withdrawn", "historical_note": "private"}],
        },
        "history": {"status": "completed", "candidates": [{"content": "unapproved cached"}]},
    }
    value = asyncio.run(visible_factual_result(user, "token", W, result))
    assert value["summary"]["title"]["text"] == "Current facts"
    assert value["summary"]["related_cases"] == []
    assert value["history"]["candidates"] == []
    assert "withheld" in value["limitations"][0]


def test_real_factual_proof_is_rejected_before_storage_in_synthetic_workspace():
    from cfin.operations import EvidenceRequest

    user = User()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            Operations(user, object()).evidence(
                "token",
                A,
                C,
                EvidenceRequest(
                    workspace_id=W,
                    acting_role="process_owner",
                    filename="real.txt",
                    content_type="text/plain",
                    content_base64="cHJvb2Y=",
                    provenance="user_supplied",
                ),
            )
        )
    assert exc.value.status_code == 422
    assert "non-synthetic" in exc.value.detail


@pytest.mark.parametrize("kind", ["complete_work", "finish_resolution"])
def test_completion_requires_explicit_change_or_no_change_classification(kind):
    payload = guided()
    del payload["action_kind"]
    with pytest.raises(HTTPException) as exc:
        action(User(), kind, payload)
    assert exc.value.status_code == 422 and "choose" in exc.value.detail
