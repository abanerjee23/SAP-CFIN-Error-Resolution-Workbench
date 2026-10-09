"""Build safeguards with local fakes; no paid models or cloud writes."""

import asyncio
import copy
import json
import re
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from pglast import parse_plpgsql, parse_sql
from test_operations import CASE, HEADERS, RUN, WORKSPACE, CloudHTTP

from cfin.arize_tracing import _metadata
from cfin.fixture_loader import load_md01
from cfin.live_evaluations import EvaluationRequest
from cfin.workflow import RetryableStageError, ScriptedStageAdapter, WorkflowExecutor


def test_completion_migrations_parse_sql_and_function_bodies():
    root = Path(__file__).resolve().parents[2] / "supabase/migrations"
    for path in sorted(root.glob("20261001000[4567]*.sql")):
        sql = path.read_text()
        assert parse_sql(sql), path.name
        for function in re.findall(r"create(?: or replace)? function .*?end \$\$;", sql, re.S):
            if "language plpgsql" in function:
                assert parse_plpgsql(function), (path.name, function.splitlines()[0])


def test_malformed_preparation_retries_once_with_unchanged_evidence():
    class BadOnce(ScriptedStageAdapter):
        def __init__(self):
            self.failed = []
            self.validated = []

        async def execute(self, stage, payload, output_type, inputs):
            result = await super().execute(stage, payload, output_type, inputs)
            if stage == "agent1" and not self.failed:
                message = result.messages[0].model_copy(update={"original_wording": "invented"})
                return result.model_copy(update={"messages": [message]})
            return result

        async def record_failed(self, stage):
            self.failed.append(stage)

        async def record_validated(self, stage, output):
            self.validated.append(stage)

    adapter = BadOnce()
    result = asyncio.run(
        WorkflowExecutor(adapter, max_retries=1, as_of=date(2026, 9, 30)).run(load_md01())
    )
    assert not result.errors
    assert result.stage_calls == {"agent1": 2, "agent2": 1, "agent3": 0}
    assert adapter.failed == ["agent1"]
    assert adapter.validated == ["agent1", "agent2"]


def test_access_budget_failures_do_not_automatically_retry():
    class Blocked(ScriptedStageAdapter):
        async def execute(self, *args):
            raise RuntimeError("Durable model budget reservation failed")

    result = asyncio.run(WorkflowExecutor(Blocked(), max_retries=1).run(load_md01()))
    assert result.stage_calls["agent1"] == 1
    assert result.errors


def test_transient_failure_retries_at_most_once():
    class Offline(ScriptedStageAdapter):
        async def execute(self, *args):
            raise RetryableStageError("Transient request")

    result = asyncio.run(WorkflowExecutor(Offline(), max_retries=1).run(load_md01()))
    assert result.stage_calls["agent1"] == 2
    assert result.errors


def test_overview_tracing_uses_actual_overview_ids_only():
    ids = {key: str(uuid4()) for key in ("workspace_id", "run_id", "snapshot_id")}
    value = _metadata({**ids, "stage": "agent4"})
    assert value == {**ids, "stage": "agent4"}
    assert "case_id" not in value and "attempt_id" not in value
    with pytest.raises((KeyError, ValueError)):
        _metadata({"workspace_id": ids["workspace_id"], "stage": "agent4"})


def test_evaluation_queue_requires_unique_cases_and_bounded_repeats():
    with pytest.raises(ValueError):
        EvaluationRequest(workspace_id=WORKSPACE, case_ids=[CASE, CASE], reason="baseline")
    with pytest.raises(ValueError):
        EvaluationRequest(workspace_id=WORKSPACE, case_ids=[CASE], repeats=4, reason="baseline")


def test_corrected_human_findings_stay_separate_from_ai():
    cloud = CloudHTTP()
    cloud.seed_inputs()
    diagnosis = {"findings": [], "original_ai": True}
    cloud.runs[0]["output"]["diagnosis"] = copy.deepcopy(diagnosis)
    corrected = {
        "cause_label": "unknown",
        "explanation": "Human investigation found a gap",
        "gaps": ["A complete target check is missing"],
        "citations": [],
    }
    with cloud.client() as client:
        response = client.post(
            f"/api/cases/{CASE}/actions",
            headers=HEADERS,
            json={
                "workspace_id": str(WORKSPACE),
                "expected_version": 1,
                "action": "review_diagnosis",
                "acting_role": "process_owner",
                "payload": {
                    "run_id": str(RUN),
                    "decision": "Corrected",
                    "reason": "Correct AI interpretation",
                    "cause_confirmed": False,
                    "findings": corrected,
                },
            },
        )
    assert response.status_code == 200
    request = next(r for r in cloud.requests if r.url.path.endswith("cfin_case_action"))
    saved = json.loads(request.content)["payload"]["data"]["findings"]
    assert saved == {**corrected, "provenance": "human_correction"}
    assert cloud.runs[0]["output"]["diagnosis"] == diagnosis


def test_corrected_human_findings_reject_out_of_pack_citations():
    cloud = CloudHTTP()
    cloud.seed_inputs()
    with cloud.client() as client:
        response = client.post(
            f"/api/cases/{CASE}/actions",
            headers=HEADERS,
            json={
                "workspace_id": str(WORKSPACE),
                "expected_version": 1,
                "action": "review_diagnosis",
                "acting_role": "process_owner",
                "payload": {
                    "run_id": str(RUN),
                    "decision": "Corrected",
                    "reason": "Human investigation",
                    "cause_confirmed": True,
                    "findings": {
                        "cause_label": "missing_gl_mapping",
                        "explanation": "Human finding",
                        "gaps": [],
                        "citations": [
                            {
                                "source_id": "other-case",
                                "source_version": "1",
                                "attempt_id": "MD01-0001",
                                "record_id": "invented",
                            }
                        ],
                    },
                },
            },
        )
    assert response.status_code == 422
    assert not any(r.url.path.endswith("cfin_case_action") for r in cloud.requests)


def test_latest_failed_run_can_receive_insufficient_human_review():
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.runs[0]["state"] = "failed"
    cloud.runs[0]["output"] = None
    cloud.case["published_run_id"] = None
    with cloud.client() as client:
        response = client.post(
            f"/api/cases/{CASE}/actions",
            headers=HEADERS,
            json={
                "workspace_id": str(WORKSPACE),
                "expected_version": 1,
                "action": "review_diagnosis",
                "acting_role": "process_owner",
                "payload": {
                    "run_id": str(RUN),
                    "decision": "Insufficient",
                    "reason": "Provider failure",
                    "cause_confirmed": False,
                },
            },
        )
    assert response.status_code == 200


def test_linked_alias_rejects_further_human_workflow():
    cloud = CloudHTTP()
    cloud.case["linked_case_id"] = str(uuid4())
    with cloud.client() as client:
        response = client.post(
            f"/api/cases/{CASE}/actions",
            headers=HEADERS,
            json={
                "workspace_id": str(WORKSPACE),
                "expected_version": 1,
                "action": "block",
                "acting_role": "process_owner",
                "payload": {"reason": "Blocked"},
            },
        )
    assert response.status_code == 409
