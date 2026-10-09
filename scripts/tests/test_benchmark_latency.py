"""Offline tests for experimental evidence; never instantiate a client or model."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "benchmark-latency.py"
SPEC = importlib.util.spec_from_file_location("benchmark_latency", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)

def sample_output(record):
    from cfin.log_only_inputs import OriginalUpload, prepare_log_inputs
    from cfin.log_only_sources import source_lines

    raw = (benchmark.ROOT / record["path"]).read_bytes()
    inputs = prepare_log_inputs([OriginalUpload(record["file"], raw)], provenance="synthetic")
    source = inputs.manifest.sources[0]
    entry = {
        "source_id": source.source_id, "source_version": source.source_version,
        "source_span": {"line_start": 1, "line_end": len(source_lines(raw))},
        "entry_id": "entry-1", "kind": "metadata", "raw_text": raw.decode(),
        "fields": [{"name_as_logged": key, "value_as_logged": value}
                   for key, value in record["metadata"].items()],
    }
    category = record["allowed_categories"][0]
    statement = {"text": "The log reports a failed attempt.", "supporting_entry_ids": ["entry-1"]}
    return {
        "outcome": "completed", "source_manifest": inputs.manifest.model_dump(mode="json"),
        "extraction": {"entries": [entry]},
        "analysis": {
            "category_id": category, "cause_hypothesis": "Requires investigation.",
            "confidence": "low", "supporting_entry_ids": ["entry-1"],
            "gaps": ["Current SAP state is unverified."],
            "route": {
                "policy_id": "synthetic-test-policy", "policy_version": 1,
                "category_id": category,
                "route_kind": "unclassified" if category == "unclassified" else "pilot",
                "owner_role": "process_owner",
                "steps": [{"order": 1, "step_id": "review", "kind": "manual_investigation",
                           "description": "Review the log."}],
            },
        },
        "case_content": {"title": statement, "what_happened": [statement],
                         "original_log_evidence": [statement]},
        "history": {"status": "not_searched"},
    }


def test_fixture_preflight_includes_distinct_hard_cases_and_preserved_baseline_hashes():
    records = benchmark.records()
    assert len(records) == 13
    assert len({row["file"] for row in records}) == 13
    assert max(row["errors"] for row in records) == 5
    assert [row["file"] for row in records[-3:]] == [
        "unknown.txt", "ambiguous.txt", "multiple-attempts.txt"]
    assert records[-1]["metadata"]["source_company_code"] != (
        records[-1]["metadata"]["target_company_code"])


def test_quality_requires_exact_metadata_and_source_bytes_not_just_valid_json():
    record = benchmark.records()[0]
    output = sample_output(record)
    quality = benchmark.quality_gates(record, output, True)
    assert quality["passed"]
    assert quality["semantic_review_status"] == "pending"
    tampered = deepcopy(output)
    tampered["extraction"]["entries"][0]["raw_text"] += "Invented source text"
    assert not benchmark.quality_gates(record, tampered, True)["passed"]
    missing_zeroes = deepcopy(output)
    fields = missing_zeroes["extraction"]["entries"][0]["fields"]
    next(field for field in fields if field["name_as_logged"] == "document_number")[
        "value_as_logged"] = "123510"
    checks = benchmark.quality_gates(record, missing_zeroes, True)["checks"]
    assert not checks["exact_metadata"]


def test_quality_rejects_missing_coverage_and_dangling_citations():
    from cfin.log_only_sources import source_lines

    record = benchmark.records()[0]
    output = sample_output(record)
    entry = output["extraction"]["entries"][0]
    entry["raw_text"] = "".join(source_lines(entry["raw_text"].encode())[:-1])
    entry["source_span"]["line_end"] -= 1
    assert not benchmark.quality_gates(record, output, True)["checks"]["complete_source_coverage"]
    output = sample_output(record)
    output["case_content"]["title"]["supporting_entry_ids"] = ["invented-entry"]
    assert not benchmark.quality_gates(record, output, True)["passed"]


def test_unknown_and_ambiguous_need_uncertainty_beyond_category_match():
    for record in benchmark.records()[-3:-1]:
        output = sample_output(record)
        assert benchmark.quality_gates(record, output, True)["passed"]
        output["analysis"]["confidence"] = "high"
        quality = benchmark.quality_gates(record, output, True)
        assert not quality["passed"]
        assert not quality["checks"]["no_high_confidence_on_ambiguous_evidence"]


def test_profile_uses_actual_run_pins():
    run = {"prompt_versions": benchmark.COMPACT_PROMPTS,
           "model_configuration": {"reasoning_effort": "medium", "agent1": "gpt-6-luna",
                                   "agent2": "gpt-6.1-sol", "agent3": "gpt-6.1-sol"}}
    benchmark.validate_profile(run, "compact")
    with pytest.raises(ValueError, match="reasoning pins"):
        benchmark.validate_profile(run, "fast")
    run["model_configuration"].update(agent1_reasoning_effort="low",
                                      agent2_reasoning_effort="medium",
                                      agent3_reasoning_effort="low")
    benchmark.validate_profile(run, "fast")


@pytest.mark.parametrize("profile,diagnosis,writer,effort", [
    ("writer_luna", "gpt-6.1-sol", "gpt-6-luna", "medium"),
    ("writer_low", "gpt-6.1-sol", "gpt-6.1-sol", "low"),
    ("all_luna", "gpt-6-luna", "gpt-6-luna", "medium"),
])
def test_model_matrix_checks_model_and_reasoning_pins(profile, diagnosis, writer, effort):
    run = {"prompt_versions": benchmark.COMPACT_PROMPTS, "model_configuration": {
        "agent1": "gpt-6-luna", "agent2": diagnosis, "agent3": writer,
        "reasoning_effort": "medium", "agent1_reasoning_effort": "medium",
        "agent2_reasoning_effort": "medium", "agent3_reasoning_effort": effort,
    }}
    benchmark.validate_profile(run, profile)
    run["model_configuration"]["agent3"] = "unreviewed-model"
    with pytest.raises(ValueError, match="model pins"):
        benchmark.validate_profile(run, profile)


def test_summary_comparison_cost_math_and_actual_overlap():
    first = {
        "file": "a.txt", "collected_at": "2026-10-09T16:00:20+00:00", "published": True,
        "quality": {"passed": True}, "known_cost_usd": "0.10", "unresolved_reserved_usd": "0",
        "workflow_seconds": 20, "end_to_end_seconds": 22, "queue_and_startup_seconds": 2,
        "calls": [{"stage": "agent_1", "latency_seconds": 20,
                   "created_at": "2026-10-09T16:00:00+00:00",
                   "reconciled_at": "2026-10-09T16:00:20+00:00",
                   "usage": {"input_tokens": 100, "output_tokens": 50}}],
    }
    second = deepcopy(first)
    second["file"] = "b.txt"
    second["calls"][0]["created_at"] = "2026-10-09T16:00:10+00:00"
    second["calls"][0]["reconciled_at"] = "2026-10-09T16:00:30+00:00"
    summary = benchmark.summarise([first, second, {"file": "unfinished.txt"}])
    assert summary["completed_observations"] == 2
    assert summary["known_cost_usd"] == "0.20"
    assert summary["tokens"] == {"input_tokens": 200, "output_tokens": 100}
    assert summary["observed_peak_case_execution_overlap"] == 2
    assert summary["workflow_latency"]["mean_seconds"] == 20
    comparison = benchmark.baseline_comparison([first, second], {
        "runs": [{"file": "a.txt", "workflow_seconds": 40, "known_cost_usd": "0.25"}]})
    assert comparison["matched_files"] == 1
    assert comparison["workflow_reduction_percent"] == 50
    assert comparison["current_known_cost_usd"] == "0.10"
    assert benchmark.summarise([])["automated_quality_passes"] == 0
    assert benchmark.summarise([])["workflow_latency"] is None
