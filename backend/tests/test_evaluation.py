import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from cfin.contracts import LookupState, ReuseStatus
from cfin.eval_runner import run_selected
from cfin.evaluation import (
    CASE_IDS,
    EVALUATION_REVIEWER,
    INJECTION_TEXT,
    ROOT,
    assess_observation,
    build_eval_inputs,
    evaluate_gates,
    evaluate_workflow,
    input_fingerprint,
    load_case_specs,
    summarize,
)
from cfin.fixture_loader import AGENT_FILES, load_md01
from cfin.workflow import ScriptedStageAdapter, WorkflowExecutor


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_deterministic_gate_variants_match_expected_eligibility(case_id):
    spec = next(item for item in load_case_specs() if item["case_id"] == case_id)
    observation = evaluate_gates(case_id)
    checks = assess_observation(observation, spec)
    assert all(item.passed for item in checks), [item for item in checks if not item.passed]
    assert observation.mode == "gates"
    assert observation.preparation is None and observation.diagnosis is None
    assert observation.stage_calls is None
    assert observation.usage == {} and observation.cost_usd == "0"
    assert observation.human_review_status == "pending"


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_shared_scripted_workflow_matches_expected_routes(case_id):
    executor = WorkflowExecutor(ScriptedStageAdapter(), as_of=date(2026, 9, 30))
    observation = asyncio.run(evaluate_workflow(case_id, executor))
    spec = next(item for item in load_case_specs() if item["case_id"] == case_id)
    checks = assess_observation(observation, spec)
    assert all(item.passed for item in checks), [item for item in checks if not item.passed]
    assert observation.input_fingerprint == input_fingerprint(build_eval_inputs(case_id))
    assert observation.cost_usd == "0"
    assert observation.human_review_status == "pending"


def test_evaluation_clones_never_change_shipped_files_or_governance():
    visible = ROOT / "fixtures/MD-01/agent-visible"
    before = {name: (visible / name).read_bytes() for name in AGENT_FILES}
    approved = build_eval_inputs("md01-reviewed-simulation")
    mapping = approved.sources["mapping-reference.json"]
    assert mapping["evaluation_only"] is True
    assert mapping["review"]["reviewer"] == EVALUATION_REVIEWER
    assert "No human reviewed" in mapping["review"]["approval_note"]
    # Deep-copy isolation also prevents one evaluation from altering the next.
    mapping["review"]["reuse_status"] = "withdrawn"
    assert (
        build_eval_inputs("md01-reviewed-simulation").sources["mapping-reference.json"]["review"][
            "reuse_status"
        ]
        == "approved"
    )
    for case_id in CASE_IDS:
        build_eval_inputs(case_id)
    assert before == {name: (visible / name).read_bytes() for name in AGENT_FILES}
    shipped = load_md01()
    assert shipped.guidance[0].reuse_status == ReuseStatus.PENDING_REVIEW
    assert shipped.guidance[0].reviewer is None
    assert shipped.lookups[-1].source.governance.reuse_status == ReuseStatus.PENDING_REVIEW


@pytest.mark.parametrize(
    "case_id,state",
    [
        ("md01-incomplete-lookups", LookupState.INCOMPLETE),
        ("md01-unavailable-lookups", LookupState.UNAVAILABLE),
    ],
)
def test_missing_evidence_changes_both_required_negative_queries(case_id, state):
    inputs = build_eval_inputs(case_id)
    required = [
        item for item in inputs.lookups if item.query_scope.get("target_account") == "0041001000"
    ]
    assert len(required) == 2
    assert all(
        item.state == state and not item.scope_complete and not item.records for item in required
    )
    counterpart = [
        item for item in inputs.lookups if item.query_scope.get("target_account") == "0021000000"
    ]
    assert all(item.state == LookupState.FOUND for item in counterpart)
    audit = inputs.sources["target-master-query-audit.json"]["records"]
    assert all(
        not item["query_completed"]
        for item in audit
        if item["lookup_id"] in {query.lookup_id for query in required}
    )


def test_injection_is_preserved_as_distinct_version_without_approval():
    base = load_md01()
    injected = build_eval_inputs("md01-injected-log")
    assert injected.original_log == base.original_log + INJECTION_TEXT
    assert injected.manifest.source_version != base.manifest.source_version
    assert (
        hashlib.sha256(injected.original_log.encode()).hexdigest()
        == injected.manifest.content_sha256
    )
    assert injected.manifest.identity == base.manifest.identity
    assert injected.lookups[-1].source.governance.reuse_status == "pending_review"
    decision = evaluate_gates("md01-injected-log")
    assert not decision.routing["agent3_eligible"]


def test_variant_builder_does_not_read_expected_answers(monkeypatch):
    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        if "expected" in path.parts or path.name == "cases.json":
            raise AssertionError("Variant builder attempted to read an answer")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    for case_id in CASE_IDS:
        payload = json.dumps(build_eval_inputs(case_id).agent_payload())
        assert "0000900123" not in payload
        assert "MD01-0002" not in payload
        assert "routing-oracle" not in payload
        assert "simulated-proof" not in payload


def test_dataset_ids_are_exact_and_unknown_cases_fail_closed():
    assert tuple(item["case_id"] for item in load_case_specs()) == CASE_IDS
    with pytest.raises(ValueError, match="Unknown evaluation case"):
        build_eval_inputs("../../../fixtures/MD-01/expected")
    with pytest.raises(ValueError, match="durable budget ledger"):
        asyncio.run(run_selected(mode="live", case_ids=["md01-pending"]))


def test_bad_observation_causes_visible_failed_assertions():
    good = evaluate_gates("md01-pending")
    bad = replace(
        good, answer_boundary_preserved=False, routing={**good.routing, "agent3_eligible": True}
    )
    spec = load_case_specs()[0]
    failed = {item.name for item in assess_observation(bad, spec) if not item.passed}
    assert failed == {"answer_separation", "agent3_gate"}


def test_repeated_replay_reports_software_results_and_pending_review():
    observations = asyncio.run(run_selected(mode="replay", case_ids=["md01-pending"], repeat=2))
    assert len(observations) == 2
    report = summarize(observations)
    assert report["checks_passed"] == report["checks_total"]
    assert report["human_review_status"] == "pending"
    assert "No production quality threshold" in report["interpretation"]
    assert all(item.stage_calls["agent3"] == 0 for item in observations)
