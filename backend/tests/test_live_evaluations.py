"""Bounded actual-run status/export; fakes make no provider, judge or cloud calls."""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from cfin.config import Settings
from cfin.live_evaluations import (
    EvaluationRequest,
    evaluation_status,
    prepare_model_evaluation,
    queue_evaluations,
    saved_evaluation_report,
    saved_model_runs,
)

W = UUID("11111111-1111-4111-8111-111111111111")
A = UUID("22222222-2222-4222-8222-222222222222")
B = UUID("33333333-3333-4333-8333-333333333333")
C = UUID("44444444-4444-4444-8444-444444444444")
T = UUID("55555555-5555-4555-8555-555555555555")


def run_row(index=1, state="succeeded", batch=B):
    return {
        "id": str(UUID(int=index)), "workspace_id": str(W), "case_id": str(C),
        "attempt_id": str(T), "evaluation_batch_id": str(batch),
        "evaluation_only": True, "evaluation_repeat": 0,
        "state": state, "created_at": "2026-10-01T10:00:00Z",
        "snapshot": {"case_id": str(C), "attempt_id": str(T)},
        "output": (
            {"preparation": {"observed": True}, "errors": []} if state == "succeeded" else None
        ),
    }


class User:
    def __init__(self, runs=None, batches=None, calls=None, denied=False):
        self.requested = []
        self.runs = runs if runs is not None else [run_row()]
        self.batches = batches if batches is not None else [{"id": str(B), "reason": "Baseline"}]
        self.calls = calls or []
        self.denied = denied

    async def require_member(self, token, actor, workspace, role=None):
        self.requested.append(("member", role))
        if self.denied:
            raise HTTPException(403, "Denied")

    async def rows(self, table, token, workspace, filters):
        self.requested.append((table, filters))
        assert workspace == W
        rows = list({"analysis_runs": self.runs, "evaluation_batches": self.batches,
                     "stage_calls": self.calls}[table])
        for key in ("id", "evaluation_batch_id", "run_id"):
            expression = filters.get(key, "")
            if expression.startswith("eq."):
                rows = [r for r in rows if r.get(key) == expression[3:]]
            elif expression.startswith("in.("):
                identifiers = set(expression[4:-1].split(","))
                rows = [r for r in rows if r.get(key) in identifiers]
        offset, size = int(filters.get("offset", 0)), int(filters.get("limit", 100))
        assert size <= 100
        return rows[offset : offset + size]

    async def rpc(self, name, token, payload):
        self.requested.append((name, payload))
        return {"batch": {"id": str(B)}, "run_ids": [str(UUID(int=1))]}


def run(awaitable):
    return asyncio.run(awaitable)


def test_disabled_models_can_prepare_a_batch_but_do_not_claim_paid_dispatch():
    user = User()
    result = run(queue_evaluations(user, Settings(_env_file=None), "token", A,
        EvaluationRequest(workspace_id=W, case_ids=[C], reason=" Baseline ")))
    assert result["paid_dispatch_enabled"] is False
    assert user.requested[0] == ("member", "process_owner")
    assert user.requested[1][1]["reason"] == "Baseline"
    assert user.requested[1][1]["configuration"]["models"]["agent2"] == "gpt-6.1-sol"


@pytest.mark.parametrize("body", [
    {"case_ids": [C, C]}, {"case_ids": [C], "reason": " "},
    {"case_ids": [C], "repeats": True}, {"case_ids": [C], "repeats": 4},
])
def test_eval_request_is_bounded_and_requires_explicit_reason(body):
    with pytest.raises(ValidationError):
        EvaluationRequest(workspace_id=W, reason=body.get("reason", "Baseline"),
                          **{k: v for k, v in body.items() if k != "reason"})


def test_status_reads_more_than_postgrest_default_cap_using_small_pages():
    batches = [{"id": str(UUID(int=10000 + i)), "reason": "Baseline"} for i in range(20)]
    runs = [run_row(i + 1, batch=UUID(batches[i // 90]["id"])) for i in range(1700)]
    user = User(runs=runs, batches=batches)
    result = run(evaluation_status(user, "token", A, W, page=2, page_size=25))
    assert result["total_runs"] == 1700
    assert len(result["runs"]) == 25
    assert result["runs"][0]["id"] == str(UUID(int=26))
    assert result["has_more_runs"] is True
    assert result["quality_baseline_established"] is False
    assert result["scope"] == "latest twenty accessible workspace batches"
    summary_reads = [x for x in user.requested if x[0] == "analysis_runs"
                     and "snapshot" not in x[1].get("select", "")]
    assert len(summary_reads) >= 18


def test_status_has_explicit_batch_scope_and_reports_additional_batches():
    batches = [{"id": str(UUID(int=10000 + i))} for i in range(21)]
    user = User(runs=[], batches=batches)
    result = run(evaluation_status(user, "token", A, W))
    assert len(result["batches"]) == 20
    assert result["has_more_batches"] is True
    assert result["runs"] == []
    with pytest.raises(HTTPException) as exc:
        run(evaluation_status(user, "token", A, W, batch_id=B))
    assert exc.value.status_code == 404


def test_membership_revocation_blocks_status_before_database_reads():
    user = User(denied=True)
    with pytest.raises(HTTPException):
        run(evaluation_status(user, "token", A, W))
    assert user.requested == [("member", None)]


def test_saved_export_only_accepts_exact_workspace_and_explicit_eval_runs():
    row = run_row()
    row["evaluation_only"] = False
    with pytest.raises(HTTPException) as exc:
        run(saved_model_runs(User(runs=[row]), "token", A, W, B))
    assert exc.value.status_code == 503
    with pytest.raises(HTTPException):
        prepare_model_evaluation([row])


def test_pending_runs_are_excluded_from_saved_code_grading_without_faking_completion():
    runs = [run_row(1), run_row(2, "failed"), run_row(3, "queued"), run_row(4, "running")]
    prepared = prepare_model_evaluation(runs)
    assert len(prepared.records) == 2
    assert all(r.kind == "persisted_model_evaluation_run" for r in prepared.records)
    assert prepared.records[0].checks[2].passed is True
    assert prepared.records[1].checks[2].passed is False
    assert prepared.report()["quality_baseline_established"] is False
    report = saved_evaluation_report({"id": str(B)}, runs, prepared, [])
    assert report["excluded_pending_runs"] == 2
    assert report["provider_calls_this_command"] == 0
    assert report["human_review_status"] == "pending"
    assert "publication_evidence" not in report
    assert report["source_run_states"] == {
        "succeeded": 1, "failed": 1, "queued": 1, "running": 1,
    }


def test_export_accounts_for_actual_ledger_usage_and_keeps_unknown_usage_visible():
    runs = [run_row(1), run_row(2, "failed")]
    calls = [
        {"id": "known", "state": "succeeded", "actual_usd": "0.001",
         "usage": {"input_tokens": 20, "output_tokens": 10}},
        {"id": "unknown", "state": "usage_unknown", "actual_usd": None, "usage": None},
    ]
    report = saved_evaluation_report({"id": str(B)}, runs, prepare_model_evaluation(runs), calls)
    assert report["source_observed_provider_calls"] == 1
    assert report["source_observed_cost_usd"] == "0.001"
    assert report["source_usage_complete"] is False
    assert report["quality_baseline_established"] is False


def test_no_completed_runs_cannot_create_a_native_saved_output_experiment():
    with pytest.raises(HTTPException) as exc:
        prepare_model_evaluation([run_row(1, "queued")])
    assert exc.value.status_code == 409


def test_export_cli_calls_only_native_saved_output_evaluation(monkeypatch, tmp_path, capsys):
    from cfin import live_eval_cli

    monkeypatch.setenv("CFIN_AUTH_TOKEN", "test-token-never-printed")
    user = User()

    async def actor(token):
        return A

    user.actor = actor
    monkeypatch.setattr(live_eval_cli, "UserGateway", lambda settings, client: user)
    seen = []

    def upload(prepared, settings, **kwargs):
        seen.append(prepared)
        return {"upload_status": "uploaded", "quality_baseline_established": False}

    monkeypatch.setattr("cfin.arize_evaluation.upload_evaluation", upload)
    target = tmp_path / "report.json"
    args = SimpleNamespace(
        workspace_id=W, queue=False, batch_id=B, page=1, page_size=25,
        export_saved_runs=True, arize_experiment_name="saved-baseline",
        verify_arize_experiment_id=None, arize_dataset_id=None, output=str(target),
    )
    assert run(live_eval_cli.execute(args)) == 0
    saved = json.loads(target.read_text())
    assert saved["source"] == "durable_private_model_evaluation_runs"
    assert saved["arize"]["upload_status"] == "uploaded"
    assert saved["provider_calls_this_command"] == 0
    assert saved["quality_baseline_established"] is False
    assert len(seen) == 1
    assert "test-token" not in capsys.readouterr().out
