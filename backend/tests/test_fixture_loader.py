import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from cfin.contracts import Citation, Diagnosis, SourceReference, route_diagnosis
from cfin.fixture_loader import AGENT_FILES, load_md01

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/MD-01/agent-visible"


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "MD-01/agent-visible"
    shutil.copytree(FIXTURE, root)
    return root


def test_fixture_loads_with_exact_identifiers_and_no_answers():
    pack = load_md01()
    assert pack.manifest.identity.document_number == "0000123456"
    assert pack.manifest.identity.source_client == "010"
    assert pack.original_log.encode("utf-8") == (FIXTURE / "original-log.txt").read_bytes()
    assert len(pack.lookups) == 5
    assert pack.guidance[0].reuse_status == "pending_review"
    assert pack.guidance[0].reviewer is None
    payload = json.dumps(pack.agent_payload())
    assert "0000900123" not in payload  # Future successful target document.
    assert "routing-oracle" not in payload
    assert "simulated-proof" not in payload


def test_numbered_original_lines_preserve_blank_lines_prefixes_and_leading_zeros():
    original = "2026-09-30T09:00:00Z | document_number=0000123456\r\n\r\n  source_client=010  \n"
    pack = replace(load_md01(), original_log=original)
    payload = pack.agent_payload()
    assert payload["original_log"] == original
    assert payload["original_log_lines"] == [
        {"line_number": 1, "text": "2026-09-30T09:00:00Z | document_number=0000123456"},
        {"line_number": 2, "text": ""},
        {"line_number": 3, "text": "  source_client=010  "},
    ]
    assert [row["text"] for row in payload["original_log_lines"]] == original.splitlines()
    encoded = json.dumps(payload)
    assert "0000900123" not in encoded
    assert "routing-oracle" not in encoded
    assert "simulated-proof" not in encoded


def asserted_diagnosis(pack):
    mapping = pack.lookups[-1]
    negative = pack.lookups[0]
    return Diagnosis.model_validate(
        {
            "run_id": "test-run",
            "attempt_id": pack.manifest.attempt_id,
            "input_source_version": "1",
            "status": "ai_supported",
            "findings": [
                {
                    "cause": "missing_target_gl_master_data",
                    "statement": "Test assertion",
                    "supported": True,
                    "checks": [
                        {
                            "check_id": "approved_mapping_identifies_target",
                            "result": "passed",
                            "observation": "Model falsely calls the pending mapping approved",
                            "lookup_id": mapping.lookup_id,
                            "citations": [mapping.citations[0].model_dump()],
                        },
                        {
                            "check_id": "target_master_absence_confirmed",
                            "result": "passed",
                            "observation": "Completed scoped negative lookup",
                            "lookup_id": negative.lookup_id,
                            "citations": [item.model_dump() for item in negative.citations],
                        },
                    ],
                }
            ],
        }
    )


def test_pending_fixture_cannot_bypass_mapping_approval():
    pack = load_md01()
    decision = route_diagnosis(
        asserted_diagnosis(pack),
        identity=pack.manifest.identity,
        business_context=pack.manifest.business_context,
        source_catalogue=list(pack.catalogue),
        lookups=list(pack.lookups),
        guidance=list(pack.guidance),
        as_of=pack.manifest.processing_at.date(),
    )
    assert not decision.agent3_eligible
    assert decision.reason == "cause_not_established"


def test_exact_fixture_eligibility_is_conditional_on_separate_reviews():
    pack = load_md01()
    # Hypothetical software state only. No fixture or actual review is changed.
    approval = {
        "reuse_status": "approved",
        "approved_version": "1",
        "reviewer": "hypothetical-test-user",
        "reviewed_at": "2026-09-30T10:00:00Z",
    }
    catalogue = [
        SourceReference.model_validate({**item.model_dump(), "governance": approval})
        if item.source_id == "MD01-mapping"
        else item
        for item in pack.catalogue
    ]
    mapping_source = next(item for item in catalogue if item.source_id == "MD01-mapping")
    lookups = [
        item.model_copy(update={"source": mapping_source})
        if item.lookup_id == "md01-applicable-mapping"
        else item
        for item in pack.lookups
    ]
    arguments = {
        "identity": pack.manifest.identity,
        "business_context": pack.manifest.business_context,
        "source_catalogue": catalogue,
        "lookups": lookups,
        "as_of": pack.manifest.processing_at.date(),
    }
    pending = route_diagnosis(asserted_diagnosis(pack), guidance=list(pack.guidance), **arguments)
    assert not pending.agent3_eligible
    assert pending.reason == "guidance_unavailable"
    guide = type(pack.guidance[0]).model_validate({**pack.guidance[0].model_dump(), **approval})
    eligible = route_diagnosis(asserted_diagnosis(pack), guidance=[guide], **arguments)
    assert eligible.agent3_eligible
    assert eligible.guidance_id == "SYN-MD-GL-001"


def test_extra_files_are_never_read(inputs):
    (inputs / "expected-answer.json").write_text("this is not valid JSON")
    assert load_md01(inputs).manifest.scenario_id == "MD-01"
    assert "expected-answer.json" not in AGENT_FILES


def test_expected_and_proof_directories_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="agent-visible"):
        load_md01(tmp_path / "MD-01/expected")


def test_original_hash_mismatch_is_visible(inputs):
    with (inputs / "original-log.txt").open("ab") as file:
        file.write(b"changed")
    with pytest.raises(ValueError, match="hash differs"):
        load_md01(inputs)


def test_missing_and_symlink_sources_are_rejected(inputs, tmp_path):
    path = inputs / "mapping-reference.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    with pytest.raises(ValueError, match="Missing or unsafe"):
        load_md01(inputs)
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="Missing or unsafe"):
        load_md01(inputs)


def test_catalogue_cannot_invent_record_or_line_locators(inputs):
    path = inputs / "source-catalogue.json"
    catalogue = json.loads(path.read_text())
    catalogue[0]["line_count"] += 1
    path.write_text(json.dumps(catalogue))
    with pytest.raises(ValueError, match="line count"):
        load_md01(inputs)
    catalogue[0]["line_count"] -= 1
    catalogue[1]["record_ids"].append("invented-record")
    path.write_text(json.dumps(catalogue))
    with pytest.raises(ValueError, match="locators"):
        load_md01(inputs)


def test_catalogue_cannot_silently_approve_pending_source(inputs):
    path = inputs / "source-catalogue.json"
    catalogue = json.loads(path.read_text())
    catalogue[2]["governance"] = {
        "reuse_status": "approved",
        "approved_version": "1",
        "reviewer": "hypothetical-test-actor",
        "reviewed_at": "2026-09-30T09:00:00Z",
    }
    path.write_text(json.dumps(catalogue))
    with pytest.raises(ValueError, match="governance differs"):
        load_md01(inputs)


def test_lookup_audit_must_match_supplied_result(inputs):
    path = inputs / "target-master-query-audit.json"
    audit = json.loads(path.read_text())
    audit["records"][0]["row_count"] = 1
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match="query audit"):
        load_md01(inputs)


def test_loader_returns_only_resolvable_failure_citations():
    pack = load_md01()
    original = pack.catalogue[0]
    cited = Citation(
        source_id=original.source_id,
        source_version=original.source_version,
        attempt_id=original.attempt_id,
        line_start=1,
        line_end=original.line_count,
    )
    assert cited.line_end == len(pack.original_log.splitlines())
