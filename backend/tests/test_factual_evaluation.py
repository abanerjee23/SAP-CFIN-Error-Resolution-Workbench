"""Factual evaluator versions/reference checks are not semantic model-quality scores."""

import asyncio
import copy
import json
from uuid import UUID

import pytest
from fastapi import HTTPException
from test_live_evaluations import A, B, C, T, User, W, run_row
from test_log_only_workflow import RecordingAdapter, binding_for, inputs_for

from cfin.factual_evaluation import (
    FACTUAL_RUBRIC_VERSION,
    load_factual_expectations,
    prepare_factual_run_evaluation,
)
from cfin.live_evaluations import (
    prepare_model_evaluation,
    saved_evaluation_report,
    saved_model_runs,
)
from cfin.log_only_snapshots import LogInputSnapshot
from cfin.log_only_workflow import LogWorkflowExecutor


def factual_run():
    inputs = inputs_for()
    binding = binding_for(
        inputs, workspace_id=str(W), case_id=str(C), attempt_id=str(T), run_id=str(UUID(int=20))
    )
    result = asyncio.run(LogWorkflowExecutor(RecordingAdapter(inputs), binding).run(inputs)).result
    source = inputs.manifest.sources[0]
    snapshot = LogInputSnapshot(
        snapshot_version="log-only-snapshot-draft-v1",
        binding=binding,
        source_manifest=inputs.manifest,
        sources=[
            {
                "id": str(UUID(int=30)),
                "workspace_id": str(W),
                "case_id": str(C),
                "attempt_id": str(T),
                "source_id": source.source_id,
                "source_version": source.source_version,
                "filename": source.original_filename,
                "object_path": f"{W}/object/{source.original_filename}",
                "sha256": source.content_sha256,
                "byte_size": source.byte_size,
                "provenance": "synthetic",
            }
        ],
    )
    row = {
        **run_row(20),
        "workflow_version": "log-only-v1",
        "input_revision": 1,
        "snapshot": snapshot.model_dump(mode="json"),
        "output": result.model_dump(mode="json"),
    }
    return row, inputs


def test_saved_factual_evaluation_never_runs_legacy_diagnostic_checks():
    row, _ = factual_run()
    prepared = prepare_model_evaluation([row])
    assert all(check.passed for check in prepared.records[0].checks)
    assert all("factual" in check.name for check in prepared.records[0].checks)
    report = prepared.report()
    assert report["quality_baseline_established"] is False
    assert report["human_review_status"] == "pending"
    assert prepared.records[0].ground_truth_json is None
    human = json.loads(prepared.records[0].output_json)["human_review"]
    assert all(item["score"] is None for item in human["semantic_dimensions"])
    assert human["original_quote_verification"] == "not_loaded"


def test_factual_model_input_prompt_rubric_history_versions_bound_to_report():
    row, _ = factual_run()
    metadata = prepare_model_evaluation([row]).records[0].metadata
    assert metadata["workflow_version"] == "log-only-v1"
    assert metadata["rubric_version"] == FACTUAL_RUBRIC_VERSION
    assert (
        metadata["source_manifest_sha256"] == row["snapshot"]["binding"]["source_manifest_sha256"]
    )
    assert json.loads(metadata["model_configuration"])["agent1"] == "gpt-6-luna"
    assert json.loads(metadata["prompt_versions"])["agent1"] == "log-extraction-v1"
    assert len(metadata["history_sha256"]) == 64


def test_original_quote_verification_uses_actual_preserved_bytes():
    row, inputs = factual_run()
    prepared = prepare_factual_run_evaluation([row], originals_by_run={row["id"]: inputs.originals})
    assert prepared.records[0].checks[-1].passed
    altered = copy.deepcopy(row)
    altered["output"]["extraction"]["entries"][0]["raw_text"] = "Fabricated source quote"
    checks = (
        prepare_factual_run_evaluation([altered], originals_by_run={row["id"]: inputs.originals})
        .records[0]
        .checks
    )
    assert checks[-1].name == "factual_exact_original_quotes" and not checks[-1].passed


def test_snapshot_binding_and_invented_summary_reference_fail_checks():
    row, _ = factual_run()
    row["snapshot"]["binding"]["run_id"] = str(UUID(int=99))
    row["output"]["summary"]["title"]["supporting_entry_ids"] = ["invented"]
    checks = prepare_model_evaluation([row]).records[0].checks
    assert checks[0].passed is False
    assert checks[1].passed is False


def test_failed_saved_run_retains_failure_and_never_establishes_quality():
    row, _ = factual_run()
    row.update(state="failed", output=None, error_code="capacity_exceeded")
    prepared = prepare_model_evaluation([row])
    checks = prepared.records[0].checks
    assert checks[2].name == "factual_outcome_honest" and checks[2].passed
    assert not checks[1].passed
    assert not prepared.report()["quality_baseline_established"]


def test_mixed_saved_reports_keep_legacy_and_factual_evaluator_meanings():
    row, _ = factual_run()
    report = prepare_model_evaluation([row, run_row(1)])
    assert {record.kind for record in report.records} == {
        "persisted_factual_model_evaluation_run",
        "persisted_model_evaluation_run",
    }


def test_unversioned_factual_result_cannot_fall_through_to_legacy_evaluation():
    row, _ = factual_run()
    del row["workflow_version"]
    with pytest.raises(HTTPException):
        prepare_model_evaluation([row])


def test_factual_report_marks_draft_expectations_and_semantic_review_pending():
    row, _ = factual_run()
    report = saved_evaluation_report({"id": str(B)}, [row], prepare_model_evaluation([row]), [])
    factual = report["factual_review"]
    assert factual["expectation_corpus"]["review_status"] == "draft_pending_human_review"
    assert not factual["expectations_bound_to_saved_cases"]
    assert report["provider_calls_this_command"] == 0
    assert not report["quality_baseline_established"]
    assert "publication_evidence" not in report


def test_expectations_stay_evaluator_only_and_have_content_revision():
    expectations = load_factual_expectations()
    assert len(expectations["content_sha256"]) == 64
    assert "evaluator-only" in expectations["answer_boundary"]
    assert len(expectations["cases"]) >= 10


def test_human_review_packet_contains_real_saved_output_but_no_invented_human_signoff():
    row, _ = factual_run()
    report = saved_evaluation_report({"id": str(B)}, [row], prepare_model_evaluation([row]), [])
    packet = report["human_review_packet"]
    case = packet["cases"][0]
    assert case["summary_to_review"] == row["output"]["summary"]
    assert case["versions"]["source_manifest_sha256"] == row["output"]["source_manifest_sha256"]
    assert case["reviewer"] is None and case["reviewed_at"] is None
    assert case["critical_failure_assessment"] == "pending"
    assert all(dimension["decision"] == "pending" for dimension in case["dimensions"])
    assert all(value is None for value in case["user_value_measurements"].values())
    assert not packet["quality_baseline_established"]


def factual_run_with_history():
    from test_factual_history import setup, with_reference

    row, _ = factual_run()
    inputs, _, reader, selected = setup()
    history = asyncio.run(reader.retrieve(selected))
    referenced = with_reference(inputs, history).model_dump(mode="json")
    row["output"]["history"] = referenced["history"]
    row["output"]["summary"]["related_cases"] = referenced["summary"]["related_cases"]
    return row


def test_held_out_history_contamination_fails_factual_evaluation():
    row = factual_run_with_history()
    row["excluded_case_ids"] = ["prior"]
    checks = {
        check.name: check.passed for check in prepare_model_evaluation([row]).records[0].checks
    }
    assert checks["factual_output_contract"]
    assert not checks["factual_held_out_cases_excluded_from_history"]


@pytest.mark.parametrize("eligible", [True, False, None])
def test_saved_exports_recheck_cited_history_and_never_export_unused_candidate_content(eligible):
    row = factual_run_with_history()
    unused = copy.deepcopy(row["output"]["history"]["candidates"][0])
    unused.update(knowledge_id="unused", content="Unused private historical material")
    row["output"]["history"]["candidates"].append(unused)

    class HistoryUser(User):
        async def rpc(self, name, token, payload):
            assert name == "cfin_revalidate_history"
            assert payload == {"workspace_id": str(W), "ids": ["known"]}
            if eligible is None:
                raise HTTPException(503, "History temporarily unavailable")
            return {"eligible": eligible}

    _, exported, _ = asyncio.run(saved_model_runs(HistoryUser(runs=[row]), "token", A, W, B))
    actual = exported[0]
    count = 1 if eligible else 0
    assert len(actual["output"]["history"]["candidates"]) == count
    assert len(actual["output"]["summary"]["related_cases"]) == count
    assert actual["output"]["summary"]["title"] == row["output"]["summary"]["title"]
    assert len(row["output"]["history"]["candidates"]) == 2
    assert actual["history_read_projection"]["withheld_candidate_count"] == 2 - count
    prepared = prepare_model_evaluation(exported)
    assert all(check.passed for check in prepared.records[0].checks)
    assert "Unused private historical material" not in prepared.records[0].output_json
    report = saved_evaluation_report({"id": str(B)}, exported, prepared, [])
    assert "Unused private historical material" not in json.dumps(report)
    if not eligible:
        assert "Original prior log" not in json.dumps(report)
        assert "withheld" in actual["output"]["limitations"][-1]


def test_projection_preserves_detection_of_original_held_out_contamination():
    row = factual_run_with_history()
    row["excluded_case_ids"] = ["prior"]
    _, exported, _ = asyncio.run(saved_model_runs(User(runs=[row]), "token", A, W, B))
    assert not exported[0]["output"]["history"]["candidates"]
    checks = {
        check.name: check.passed for check in prepare_model_evaluation(exported).records[0].checks
    }
    assert not checks["factual_held_out_cases_excluded_from_history"]
