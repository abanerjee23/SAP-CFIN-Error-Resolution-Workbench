"""Human actions verify private evidence before invoking database guards."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from cfin.error_analysis_operations import error_workbench_action, record_error_route_step


def fixture():
    workspace, case_id, proof_id = uuid4(), uuid4(), uuid4()
    case = {"id": str(case_id), "work_cycle": 1}
    proof = {
        "id": str(proof_id),
        "workspace_id": str(workspace),
        "case_id": str(case_id),
        "kind": "proof",
        "work_cycle": 1,
    }
    user = AsyncMock()
    user.rows.return_value = [proof]
    user.download.return_value = b"synthetic proof"
    user.rpc.return_value = {"saved": True}
    return user, workspace, case, proof


def test_route_reads_saved_bytes_before_recording_outcome():
    user, workspace, case, proof = fixture()
    asyncio.run(
        record_error_route_step(
            user,
            "token",
            workspace,
            case,
            {},
            {
                "note": "Synthetic posting succeeded",
                "decision": "completed",
                "posting_reference": "SYNTHETIC-001",
                "evidence_ids": [proof["id"]],
            },
        )
    )
    user.download.assert_awaited_once_with("token", proof)
    assert user.rpc.call_args.args[2]["data"]["posting_reference"] == "SYNTHETIC-001"


@pytest.mark.parametrize("failure", ["wrong_cycle", "missing_bytes", "duplicate"])
def test_invalid_route_proof_never_reaches_write_rpc(failure):
    user, workspace, case, proof = fixture()
    ids = [proof["id"]]
    if failure == "wrong_cycle":
        proof["work_cycle"] = 2
    elif failure == "missing_bytes":
        user.download.side_effect = HTTPException(503, "Unavailable")
    else:
        ids *= 2
    with pytest.raises(HTTPException):
        asyncio.run(
            record_error_route_step(
                user,
                "token",
                workspace,
                case,
                {},
                {
                    "note": "Synthetic observation",
                    "evidence_ids": ids,
                },
            )
        )
    user.rpc.assert_not_awaited()


def test_closure_requires_human_confirmation():
    user, workspace, case, proof = fixture()
    with pytest.raises(HTTPException):
        asyncio.run(
            error_workbench_action(
                user,
                "token",
                workspace,
                case,
                {},
                "finish_resolution",
                {
                    "note": "Synthetic validated outcome",
                    "posting_reference": "SYNTHETIC-001",
                    "evidence_ids": [proof["id"]],
                    "human_confirmed": False,
                },
            )
        )
    user.rpc.assert_not_awaited()


def test_closure_checks_saved_proof():
    user, workspace, case, proof = fixture()
    asyncio.run(
        error_workbench_action(
            user,
            "token",
            workspace,
            case,
            {},
            "finish_resolution",
            {
                "note": "Synthetic validated outcome",
                "posting_reference": "SYNTHETIC-001",
                "evidence_ids": [proof["id"]],
                "human_confirmed": True,
            },
        )
    )
    user.download.assert_awaited_once()
    assert user.rpc.call_args.args[0] == "cfin_error_workbench_action"


@pytest.mark.parametrize("queued", [[], [{"id": "44444444-4444-4444-8444-444444444444"}]])
def test_scoped_worker_never_falls_back_to_another_workspace(monkeypatch, queued):
    from types import SimpleNamespace

    from cfin import worker

    cloud = AsyncMock()
    cloud.rows.return_value = queued
    process = AsyncMock(return_value={"claimed": True})
    notifications = AsyncMock()
    monkeypatch.setattr(
        worker,
        "Settings",
        lambda: SimpleNamespace(
            worker_configured=True,
            models_configured=True,
        ),
    )
    monkeypatch.setattr(worker, "ServiceGateway", lambda *_: cloud)
    monkeypatch.setattr(worker, "process_one", process)
    monkeypatch.setattr(worker, "process_notification", notifications)
    workspace = str(uuid4())
    asyncio.run(worker.run_worker(True, workspace_id=workspace))
    assert cloud.rows.call_args.args[1]["workspace_id"] == "eq." + workspace
    assert cloud.rows.call_args.args[1]["workflow_version"] == "eq.error-analysis-v1"
    if queued:
        assert process.call_args.kwargs["target_run_id"] == queued[0]["id"]
    else:
        process.assert_not_awaited()
    notifications.assert_not_awaited()
