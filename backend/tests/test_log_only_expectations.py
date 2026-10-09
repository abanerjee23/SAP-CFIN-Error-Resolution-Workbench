"""Offline corpus integrity and answer-boundary checks, not model-quality scores."""

import asyncio
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from cfin.log_only_contracts import ExecutionBinding
from cfin.log_only_inputs import MAX_LOG_BYTES, MAX_LOG_LINES, MAX_LOG_SOURCES
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.log_only_sources import manifest_fingerprint, source_lines
from cfin.log_only_workflow import LogWorkflowExecutor

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "log_only_evaluation_fixtures", ROOT / "evals/log_only_fixtures.py"
)
assert SPEC is not None and SPEC.loader is not None
fixtures = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fixtures
SPEC.loader.exec_module(fixtures)
EXPECTATIONS = json.loads((ROOT / "evals/log-only-expectations.json").read_text())
CASE_SPECS = {case["case_id"]: case for case in EXPECTATIONS["cases"]}


def copy_originals(destination: Path) -> None:
    for scenario in ("MD-01", "MAP-01"):
        relative = Path("fixtures") / scenario / "agent-visible" / "original-log.txt"
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def test_corpus_is_complete_but_does_not_claim_human_review_or_model_quality():
    assert set(CASE_SPECS) == set(fixtures.CASE_IDS)
    assert len(CASE_SPECS) == len(EXPECTATIONS["cases"])
    assert EXPECTATIONS["synthetic"] is True
    assert EXPECTATIONS["review_status"] == "draft_pending_human_review"
    assert EXPECTATIONS["quality_thresholds"] is None


@pytest.mark.parametrize("case_id", fixtures.CASE_IDS)
def test_factual_expectations_resolve_to_exact_original_source_versions(case_id):
    inputs = fixtures.build_inputs(case_id)
    expected = CASE_SPECS[case_id]
    assert len(inputs.sources) == expected["source_count"]
    sources = {(source.source_id, source.source_version): source for source in inputs.sources}
    for evidence in expected["required_evidence"]:
        source = sources[(evidence["source_id"], evidence["source_version"])]
        lines = source_lines(source.original_bytes)
        start, end = evidence["line_start"], evidence["line_end"]
        assert 1 <= start <= end <= len(lines)
        assert "".join(lines[start - 1:end]) == evidence["text_as_logged"]


@pytest.mark.parametrize("case_id,scenario", [
    ("md01-original", "MD-01"), ("map01-original", "MAP-01")
])
def test_base_inputs_preserve_original_bytes_including_final_newline(case_id, scenario):
    original = ROOT / "fixtures" / scenario / "agent-visible/original-log.txt"
    inputs = fixtures.build_inputs(case_id)
    assert inputs.sources[0].original_bytes == original.read_bytes()
    payload = inputs.agent_payload()["sources"][0]
    assert payload["source"]["content_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert payload["source"]["byte_size"] == len(original.read_bytes())
    assert payload["lines"][-1]["text"].endswith("approved diagnosis.\n")
    assert inputs.sources[0].original_bytes.endswith(b"\n")


def test_input_builder_reads_only_allowlisted_originals(monkeypatch):
    read_bytes = Path.read_bytes
    opened = []
    allowed = {
        ROOT / "fixtures" / scenario / "agent-visible/original-log.txt"
        for scenario in ("MD-01", "MAP-01")
    }

    def guarded_read(path):
        assert path in allowed, f"Unexpected evaluator input file read: {path}"
        opened.append(path)
        return read_bytes(path)

    def forbidden_read_text(path, *args, **kwargs):
        pytest.fail(f"Input preparation must not read evaluator JSON or sidecars: {path}")

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    monkeypatch.setattr(Path, "read_text", forbidden_read_text)
    for case_id in fixtures.CASE_IDS:
        fixtures.build_inputs(case_id)
    assert set(opened) == allowed


def test_expectations_sidecars_and_future_proof_are_not_needed_or_serialized(tmp_path):
    copy_originals(tmp_path)
    sentinel = "EVALUATOR_ONLY_SECRET_91d2"
    # Hostile/invalid adjacent data cannot influence input construction.
    for relative in (
        "evals/log-only-expectations.json",
        "fixtures/MD-01/expected/routing-oracle.json",
        "fixtures/MD-01/simulated-proof/target-posting.json",
        "fixtures/MD-01/agent-visible/mapping-reference.json",
        "fixtures/MD-01/agent-visible/target-master-lookup.json",
        "fixtures/MD-01/agent-visible/manifest.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sentinel)
    for case_id in fixtures.CASE_IDS:
        if case_id == "unreadable-original":
            continue
        built = fixtures.build_inputs(case_id, repository_root=tmp_path).agent_payload()
        assert built == fixtures.build_inputs(case_id).agent_payload()
        encoded = json.dumps(built)
        assert sentinel not in encoded
        assert "0000900123" not in encoded  # Later simulated posting, absent from originals.
        assert "summary_requirements" not in encoded
        assert "prohibited_inferences" not in encoded
        assert "required_evidence" not in encoded
        assert "history_retrieval_status" not in encoded
        assert set(built) == {"sources"}


def test_missing_identity_still_supplies_the_error_without_recovering_deleted_facts():
    payload = fixtures.build_inputs("md01-missing-identity").agent_payload()
    text = "\n".join(line["text"] for line in payload["sources"][0]["lines"])
    assert "G/L account 0041001000 could not be located" in text
    for absent in (
        "attempt_id=", "processing_order=", "document_number=", "fiscal_year=",
        "source_posting_date=", "source_posted_at=",
    ):
        assert absent not in text
    assert "source_client=010" in text
    assert "source_line=0001" in text


def test_contradictory_outcomes_are_both_preserved_with_unknown_observation_order():
    source = fixtures.build_inputs("md01-contradictory-outcomes").sources[0]
    text = source.original_bytes.decode("utf-8")
    assert "result=failed" in text
    assert "result=success" in text
    assert "no target document reference was returned" in text
    assert "target_document_number=0000999999" in text
    assert "observation_time=unknown" in text
    purposes = {
        evidence["purpose"]
        for evidence in CASE_SPECS["md01-contradictory-outcomes"]["required_evidence"]
    }
    assert {"reported_target_outcome", "contradictory_outcome"} <= purposes


@pytest.mark.parametrize("case_id", ["two-originals", "repeated-original"])
def test_repeated_lines_in_different_originals_keep_distinct_source_locators(case_id):
    inputs = fixtures.build_inputs(case_id)
    first, second = inputs.agent_payload()["sources"]
    assert first["source"]["source_id"] != second["source"]["source_id"]
    assert first["lines"][3] == second["lines"][3]
    # Matching content or filenames cannot collapse separately supplied originals.
    assert first["source"]["original_filename"] == second["source"]["original_filename"]
    assert len({
        (item["source"]["source_id"], item["source"]["source_version"])
        for item in (first, second)
    }) == 2
    if case_id == "repeated-original":
        assert inputs.sources[0].original_bytes == inputs.sources[1].original_bytes


@pytest.mark.parametrize("case_id", ["empty-original", "blank-original"])
def test_empty_input_does_not_acquire_factual_evidence_or_an_expected_summary(case_id):
    payload = fixtures.build_inputs(case_id).agent_payload()
    assert not any(line["text"].strip() for line in payload["sources"][0]["lines"])
    expected = CASE_SPECS[case_id]
    assert expected["expected_outcome"] == "no_usable_evidence"
    assert expected["required_evidence"] == []


def test_unreadable_bytes_fail_strict_payload_preparation_without_replacement():
    inputs = fixtures.build_inputs("unreadable-original")
    original = inputs.sources[0].original_bytes
    assert b"\xff\xfe" in original
    with pytest.raises(UnicodeDecodeError):
        inputs.agent_payload()
    assert inputs.sources[0].original_bytes == original
    assert CASE_SPECS[inputs.case_id]["expected_outcome"] == "rejected_unsupported_encoding"


def test_injection_and_unfamiliar_content_are_preserved_verbatim_as_source_lines():
    for case_id, text in (
        ("md01-injected-instructions", fixtures.INJECTION_LINE),
        ("md01-unfamiliar-content", fixtures.UNFAMILIAR_LINE),
    ):
        payload = fixtures.build_inputs(case_id).agent_payload()
        assert payload["sources"][0]["lines"][-1] == {"line_number": 18, "text": text + "\n"}
        assert "instructions" not in payload
        assert "tools" not in payload


def test_variations_do_not_change_originals_or_leak_mutation_between_runs():
    originals = {
        scenario: (ROOT / "fixtures" / scenario / "agent-visible/original-log.txt").read_bytes()
        for scenario in ("MD-01", "MAP-01")
    }
    first = fixtures.build_inputs("md01-original").agent_payload()
    first["sources"][0]["lines"][0]["text"] = "caller mutation"
    for case_id in fixtures.CASE_IDS:
        fixtures.build_inputs(case_id)
    rebuilt = fixtures.build_inputs("md01-original").agent_payload()
    assert "caller mutation" not in json.dumps(rebuilt)
    for scenario, original in originals.items():
        path = ROOT / "fixtures" / scenario / "agent-visible/original-log.txt"
        assert path.read_bytes() == original


def test_changed_original_requires_explicit_corpus_review(tmp_path):
    copy_originals(tmp_path)
    original = tmp_path / "fixtures/MD-01/agent-visible/original-log.txt"
    original.write_bytes(original.read_bytes().replace(b"0041001000", b"0099999999"))
    with pytest.raises(ValueError, match="hash changed"):
        fixtures.build_inputs("md01-original", repository_root=tmp_path)


def test_symlinks_cannot_substitute_a_sidecar_for_an_original(tmp_path):
    copy_originals(tmp_path)
    original = tmp_path / "fixtures/MD-01/agent-visible/original-log.txt"
    copied = original.with_name("expected-answer.txt")
    original.rename(copied)
    original.symlink_to(copied)
    with pytest.raises(ValueError, match="symlink"):
        fixtures.build_inputs("md01-original", repository_root=tmp_path)


def test_unknown_case_cannot_select_an_arbitrary_fixture_path():
    with pytest.raises(ValueError, match="Unknown log-only evaluation case"):
        fixtures.build_inputs("../MD-01/expected/routing-oracle.json")


@pytest.mark.parametrize("case_id", [
    case_id for case_id in fixtures.CASE_IDS if case_id != "unreadable-original"
])
def test_readable_corpus_uses_production_inputs_and_fits_first_analysis_envelope(case_id):
    sample = fixtures.build_inputs(case_id)
    inputs = sample.runtime_inputs()
    assert sample.agent_payload() == {"sources": inputs.extraction_payload()}
    assert len(inputs.manifest.sources) <= MAX_LOG_SOURCES
    assert sum(len(raw) for raw in inputs.originals.values()) <= MAX_LOG_BYTES
    assert sum(source.readable.line_count for source in inputs.manifest.sources) <= MAX_LOG_LINES
    for source, original in zip(inputs.manifest.sources, sample.sources, strict=True):
        assert source.source_id == original.source_id
        assert source.source_version == original.source_version
        saved_bytes = inputs.originals[(source.source_id, source.source_version)]
        assert saved_bytes == original.original_bytes


def test_eval_numbering_uses_runtime_cr_lf_rules_and_retains_other_unicode_separators():
    raw = "first\r\nsecond\fwithin\u2028line\rthird\n".encode("utf-8")
    sample = fixtures.EvaluationInput(
        "authored-line-delimiters",
        (fixtures.EvaluationSource("log-1", "1", "line-delimiters.txt", raw),),
    )
    payload = sample.agent_payload()["sources"][0]
    assert payload["source"]["readable"]["line_count"] == 3
    assert payload["lines"] == [
        {"line_number": 1, "text": "first\r\n"},
        {"line_number": 2, "text": "second\fwithin\u2028line\r"},
        {"line_number": 3, "text": "third\n"},
    ]
    assert "".join(line["text"] for line in payload["lines"]).encode("utf-8") == raw


def test_originals_only_fixture_executes_real_three_stage_handoffs_without_expected_answers():
    sample = fixtures.build_inputs("two-originals")
    inputs = sample.runtime_inputs()
    binding = ExecutionBinding(
        workspace_id="evaluation-workspace",
        run_id="evaluation-run",
        case_id="evaluation-case",
        attempt_id="application-attempt",
        input_revision="1",
        source_manifest_sha256=manifest_fingerprint(inputs.manifest),
        prompt_versions=LOG_PROMPT_VERSIONS,
        model_configuration={
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    )

    class ExplicitTestAdapter:
        """Authored output for plumbing tests; no model or semantic-quality claim."""

        evaluation_only = True
        workflow_version = "log-only-v1"

        def __init__(self):
            self.payloads = {}

        async def execute(self, stage, payload, output_type, inputs):
            self.payloads[stage] = payload
            if stage == "agent1":
                entries = []
                for original in payload["sources"]:
                    source = original["source"]
                    for line in original["lines"]:
                        entries.append({
                            "entry_id": f'{source["source_id"]}:{line["line_number"]}',
                            "source_id": source["source_id"],
                            "source_version": source["source_version"],
                            "source_span": {
                                "line_start": line["line_number"],
                                "line_end": line["line_number"],
                            },
                            "kind": "unclassified",
                            "raw_text": line["text"],
                        })
                return output_type.model_validate({"entries": entries})
            if stage == "agent2":
                return output_type.model_validate({
                    "selected_entry_ids": [
                        entry["entry_id"] for entry in payload["extracted"]["entries"]
                    ]
                })
            stopped = [
                entry for entry in payload["evidence"]["selected_entries"]
                if "Target posting stopped" in entry["raw_text"]
            ]
            return output_type.model_validate({
                "title": {
                    "text": "Both supplied logs report stopped target posting",
                    "supporting_entry_ids": [entry["entry_id"] for entry in stopped],
                },
                "statements": [{
                    "text": "The supplied log reports no returned target document reference.",
                    "supporting_entry_ids": [entry["entry_id"]],
                } for entry in stopped],
            })

    adapter = ExplicitTestAdapter()
    execution = asyncio.run(LogWorkflowExecutor(adapter, binding).run(inputs))
    assert execution.result.outcome == "completed"
    assert execution.evaluation_only is True
    assert execution.stage_calls == {"agent1": 1, "agent2": 1, "agent3": 1}
    assert execution.result.history.status == "not_searched"
    assert execution.result.limitations == ()
    assert adapter.payloads["agent1"]["sources"] == sample.agent_payload()["sources"]
    assert "history" not in adapter.payloads["agent1"]
    assert "history" not in adapter.payloads["agent2"]
    for entry in execution.result.extraction.entries:
        original_lines = source_lines(inputs.originals[(entry.source_id, entry.source_version)])
        assert entry.raw_text == original_lines[entry.source_span.line_start - 1]
    for payload in adapter.payloads.values():
        encoded = json.dumps(payload)
        assert "summary_requirements" not in encoded
        assert "required_evidence" not in encoded
        assert "prohibited_inferences" not in encoded
        assert "routing-oracle" not in encoded
        assert "0000900123" not in encoded
