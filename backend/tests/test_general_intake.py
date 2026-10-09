"""Generic pack boundaries, immutable restoration and the second-family evidence gate.

All reviews in these tests are hypothetical software states; no person approved a reference.
"""

import asyncio
import copy
import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import HTTPException
from pglast import parse_sql
from test_operations import CloudHTTP

from cfin.contracts import ReferenceGovernance, route_diagnosis
from cfin.fixture_loader import AGENT_FILES, parse_input_files
from cfin.gateway import ServiceGateway
from cfin.intake import (
    IntakeControlRequest,
    apply_intake_control,
    encode_json,
    prepare_pack,
    scenario_template,
)
from cfin.operations import IntakeRequest
from cfin.snapshots import restore_inputs
from cfin.workflow import build_brief, build_diagnosis

WORKSPACE = UUID("22222222-2222-4222-8222-222222222222")
CASE = "33333333-3333-4333-8333-333333333333"
ATTEMPT = "44444444-4444-4444-8444-444444444444"
ACTOR = UUID("11111111-1111-4111-8111-111111111111")


def request(scenario="MD-01"):
    template = scenario_template(scenario, WORKSPACE)
    return IntakeRequest(
        workspace_id=WORKSPACE,
        delivery_key=template["manifest"]["delivery_key"],
        manifest=template["manifest"],
        original_log=template["original_log"],
        agent_files=template["agent_files"],
    )


@pytest.mark.parametrize("scenario", ["MD-01", "MAP-01"])
def test_template_is_a_complete_pending_synthetic_input_pack(scenario):
    inputs, files, legacy = prepare_pack(request(scenario))
    assert inputs.manifest.scenario_id == scenario and not legacy
    assert set(files) == set(AGENT_FILES)
    assert inputs.manifest.identity.workspace_id == str(WORKSPACE)
    assert (
        inputs.sources["source-posting.json"]["identity"] == inputs.manifest.identity.model_dump()
    )
    assert all(guide.reuse_status == "pending_review" for guide in inputs.guidance)
    assert all(
        source.governance is None or source.governance.reviewer is None
        for source in inputs.catalogue
    )
    assert "0000900123" not in json.dumps(inputs.agent_payload())


@pytest.mark.parametrize("filename", ["oracle.json", "simulated-proof.json", "../manifest.json"])
def test_upload_does_not_accept_oracle_proof_or_arbitrary_paths(filename):
    body = request()
    body.agent_files[filename] = {"synthetic": True}
    with pytest.raises(HTTPException, match="eight allowed") as failure:
        prepare_pack(body)
    assert failure.value.status_code == 422


def test_dedicated_proof_embedded_in_an_input_is_rejected():
    body = request()
    body.agent_files["source-posting.json"]["correction_proof"] = {"action": "invented"}
    with pytest.raises(HTTPException, match="Proof, answer keys"):
        prepare_pack(body)


def test_original_hash_and_embedded_manifest_must_match():
    body = request()
    body.original_log += "new observation"
    with pytest.raises(HTTPException, match="hash differs"):
        prepare_pack(body)
    body = request()
    body.agent_files["manifest.json"]["delivery_key"] = "different-delivery"
    with pytest.raises(HTTPException, match="match the submitted"):
        prepare_pack(body)


def test_upload_cannot_forge_an_approval_even_when_catalogue_and_source_agree():
    body = request()
    approval = {
        "reuse_status": "approved",
        "approved_version": "1",
        "reviewer": str(ACTOR),
        "reviewed_at": "2026-09-30T10:00:00Z",
    }
    body.agent_files["mapping-reference.json"]["review"].update(approval)
    body.agent_files["source-catalogue.json"][2]["governance"] = approval
    with pytest.raises(HTTPException, match="cannot supply a reference approval"):
        prepare_pack(body)


def test_upload_cannot_attest_human_prerequisites():
    body = request()
    body.agent_files["missing-gl-master-playbook.json"]["prerequisites_and_approvals"][1][
        "currently_satisfied"
    ] = True
    with pytest.raises(HTTPException, match="cannot attest"):
        prepare_pack(body)


def test_pack_limits_are_measured_in_bytes():
    body = request()
    body.original_log = "é" * 600_000
    body.manifest = body.manifest.model_copy(
        update={"content_sha256": hashlib.sha256(body.original_log.encode()).hexdigest()}
    )
    body.agent_files["manifest.json"] = body.manifest.model_dump(mode="json")
    with pytest.raises(HTTPException, match="bounded input"):
        prepare_pack(body)


class SavedBytes:
    def __init__(self, files):
        self.files = files

    async def download(self, evidence):
        return self.files[evidence["filename"]]


def snapshot_for(body):
    inputs, files, _ = prepare_pack(body)
    manifest = inputs.manifest.model_dump(mode="json")
    snapshot = {
        "manifest": manifest,
        "identity": copy.deepcopy(manifest["identity"]),
        "business_context": manifest["business_context"],
        "case_id": CASE,
        "attempt_id": ATTEMPT,
        "input_revision": 1,
        "context_overlay": [],
        "attempt": {
            "id": ATTEMPT,
            "workspace_id": str(WORKSPACE),
            "case_id": CASE,
            "attempt_key": manifest["attempt_id"],
            "processing_at": manifest["processing_at"],
            "processing_order": manifest["processing_order"],
        },
        "sources": [
            {
                "evidence": {
                    "filename": name,
                    "kind": "original_log" if name == "original-log.txt" else "reference",
                },
                "review": None,
            }
            for name in files
        ],
    }
    return snapshot, SavedBytes(files)


def restore(snapshot, cloud):
    return asyncio.run(restore_inputs(snapshot, cast(ServiceGateway, cloud)))


def test_new_family_restores_its_saved_pack_and_exact_identifiers():
    snapshot, cloud = snapshot_for(request("MAP-01"))
    restored = restore(snapshot, cloud)
    assert restored.manifest.identity.document_number == "0000123457"
    assert restored.manifest.scenario_id == "MAP-01"
    assert restored.lookups[-2].state == "confirmed_absent"
    assert restored.lookups[-1].lookup_id == "map01-independent-target-reference"


@pytest.mark.parametrize(
    "tamper", ["header", "failed_account", "scope", "expiry", "malformed", "duplicate_locator"]
)
def test_mapping_family_cannot_relabel_its_absent_or_unaffected_source_records(tamper):
    body = request("MAP-01")
    mapping = body.agent_files["mapping-reference.json"]
    row = mapping["unaffected_mapping_records"][0]
    if tamper == "header":
        body.agent_files["source-posting.json"]["records"][0]["source_document_number"] = "wrong"
    elif tamper == "failed_account":
        row["source_account"] = mapping["query_scope"]["source_account"]
    elif tamper == "scope":
        row["scope"]["company_code"] = "9999"
    elif tamper == "expiry":
        row["expires_on"] = "2026-09-01"
    elif tamper == "malformed":
        mapping["unaffected_mapping_records"] = ["not a record"]
    else:
        row["record_id"] = mapping["absence_audit"]["record_id"]
    with pytest.raises(HTTPException):
        prepare_pack(body)


def test_authenticated_completion_fills_only_missing_fields_without_changing_saved_bytes():
    body = request()
    original = body.manifest.identity.model_copy(update={"document_number": None})
    body.manifest = body.manifest.model_copy(update={"identity": original})
    body.agent_files["manifest.json"] = body.manifest.model_dump(mode="json")
    body.agent_files["source-posting.json"]["identity"] = original.model_dump(mode="json")
    snapshot, cloud = snapshot_for(body)
    snapshot["identity"]["document_number"] = "0000123456"
    snapshot["context_overlay"] = [
        {
            "id": "test-control",
            "case_id": CASE,
            "workspace_id": str(WORKSPACE),
            "actor_id": str(ACTOR),
            "acting_role": "process_owner",
            "kind": "complete_identity",
            "reason": "Human explicitly supplied missing document number",
            "recorded_at": "2026-10-01T09:00:00Z",
            "payload": {"identity": snapshot["identity"]},
        }
    ]
    before = copy.deepcopy(cloud.files)
    restored = restore(snapshot, cloud)
    assert restored.manifest.identity.document_number == "0000123456"
    assert json.loads(cloud.files["manifest.json"])["identity"]["document_number"] is None
    assert cloud.files == before
    snapshot["identity"]["source_client"] = "011"
    with pytest.raises(ValueError, match="identity differs"):
        restore(snapshot, cloud)


def test_order_overlay_uses_recorded_order_without_rewriting_original_manifest():
    snapshot, cloud = snapshot_for(request())
    snapshot["attempt"]["processing_order"] = 2
    with pytest.raises(ValueError, match="attempt metadata"):
        restore(snapshot, cloud)
    snapshot["context_overlay"] = [
        {
            "id": "test-control",
            "case_id": CASE,
            "workspace_id": str(WORKSPACE),
            "actor_id": str(ACTOR),
            "acting_role": "process_owner",
            "kind": "review_attempt_order",
            "reason": "Explicit human chronology review",
            "recorded_at": "2026-10-01T09:00:00Z",
            "payload": {"ordered_attempt_ids": ["88888888-8888-4888-8888-888888888888", ATTEMPT]},
        }
    ]
    restored = restore(snapshot, cloud)
    assert restored.manifest.processing_order == 2
    assert json.loads(cloud.files["manifest.json"])["processing_order"] == 1
    snapshot["context_overlay"][0]["actor_id"] = None
    with pytest.raises(ValueError, match="authenticated process owner"):
        restore(snapshot, cloud)


def hypothetical_approved(inputs, *, guidance=True):
    approval = ReferenceGovernance(
        reuse_status="approved",
        approved_version="1",
        reviewer="hypothetical-software-test-only",
        reviewed_at="2026-10-01T08:00:00Z",
    )
    catalogue = tuple(
        source.model_copy(update={"governance": approval})
        if source.source_id == "MAP01-mapping"
        else source
        for source in inputs.catalogue
    )
    indexed = {(source.source_id, source.source_version): source for source in catalogue}
    lookups = tuple(
        lookup.model_copy(
            update={
                "source": lookup.source.model_copy(
                    update={
                        "governance": indexed[
                            (lookup.source.source_id, lookup.source.source_version)
                        ].governance
                    }
                )
            }
        )
        for lookup in inputs.lookups
    )
    guides = (
        tuple(
            type(guide).model_validate({**guide.model_dump(), **approval.model_dump()})
            for guide in inputs.guidance
        )
        if guidance
        else inputs.guidance
    )
    return replace(inputs, catalogue=catalogue, lookups=lookups, guidance=guides)


def route(inputs):
    diagnosis = build_diagnosis(inputs, "test-run", date(2026, 10, 1))
    return diagnosis, route_diagnosis(
        diagnosis,
        identity=inputs.manifest.identity,
        business_context=inputs.manifest.business_context,
        source_catalogue=list(inputs.catalogue),
        lookups=list(inputs.lookups),
        guidance=list(inputs.guidance),
        as_of=date(2026, 10, 1),
    )


def test_mapping_family_needs_independent_reference_and_playbook_reviews():
    inputs = prepare_pack(request("MAP-01"))[0]
    diagnosis, decision = route(inputs)
    assert diagnosis.status == "needs_review" and not decision.agent3_eligible
    approved_reference = hypothetical_approved(inputs, guidance=False)
    diagnosis, decision = route(approved_reference)
    assert diagnosis.findings[0].cause == "missing_gl_mapping" and diagnosis.findings[0].supported
    assert decision.reason == "guidance_unavailable"
    all_approved = hypothetical_approved(inputs)
    diagnosis, decision = route(all_approved)
    assert decision.agent3_eligible
    brief = build_brief(all_approved, "test-run", decision)
    assert brief.category == "missing_gl_mapping" and "mapping" in brief.title


@pytest.mark.parametrize(
    "failure",
    ["wrong_source", "wrong_target", "missing_extension", "blocked_master", "wrong_attempt"],
)
def test_mapping_family_rejects_inapplicable_or_incomplete_observations(failure):
    inputs = hypothetical_approved(prepare_pack(request("MAP-01"))[0])
    lookups = list(inputs.lookups)
    if failure == "wrong_source":
        lookups[-2] = lookups[-2].model_copy(
            update={"query_scope": {**lookups[-2].query_scope, "source_account": "0000999999"}}
        )
    elif failure == "wrong_target":
        lookups[-1] = lookups[-1].model_copy(
            update={"records": [{**lookups[-1].records[0], "target_account": "0049999999"}]}
        )
    elif failure == "missing_extension":
        lookups.pop(1)
    elif failure == "blocked_master":
        lookups[0] = lookups[0].model_copy(
            update={"records": [{**lookups[0].records[0], "posting_blocked": True}]}
        )
    else:
        lookups[-2] = lookups[-2].model_copy(
            update={"source": lookups[-2].source.model_copy(update={"attempt_id": "other-attempt"})}
        )
    _, decision = route(replace(inputs, lookups=tuple(lookups)))
    assert not decision.agent3_eligible


def test_mapping_absence_audit_cannot_claim_an_incomplete_empty_result_is_absence():
    body = request("MAP-01")
    body.agent_files["mapping-reference.json"]["absence_audit"]["pagination_exhausted"] = False
    with pytest.raises(HTTPException, match="complete failure-time query audit"):
        prepare_pack(body)


def test_target_lookup_from_a_different_time_cannot_enter_the_failure_snapshot():
    body = request()
    body.agent_files["target-master-query-audit.json"]["observed_at"] = "2026-09-29T09:00:00Z"
    body.agent_files["source-catalogue.json"][3]["observed_at"] = "2026-09-29T09:00:00Z"
    for lookup in body.agent_files["target-master-lookup.json"]:
        lookup["source"]["observed_at"] = "2026-09-29T09:00:00Z"
    with pytest.raises(HTTPException, match="exact failure-time audit source"):
        prepare_pack(body)


def test_prepared_intake_migration_parses_and_has_scoped_immutable_links():
    sql = (
        Path(__file__).resolve().parents[2] / "supabase/migrations/202610010002_intake.sql"
    ).read_text()
    assert len(parse_sql(sql)) == 21
    assert "private.is_member(workspace_id)" in sql
    assert "Saved input source mismatch" in sql
    assert "input_pack_sha256" in sql
    assert "context_overlay" in sql


class Controls:
    def __init__(self):
        self.saved = []

    async def require_member(self, *args):
        return {"roles": ["process_owner"]}

    async def rpc(self, name, token, payload):
        self.saved.append((name, token, payload))
        return {"case_id": CASE, "version": 2}


def test_context_control_requires_valid_distinct_complete_order_list():
    user = Controls()
    body = IntakeControlRequest(
        workspace_id=WORKSPACE,
        expected_version=1,
        action="review_attempt_order",
        reason="Human chronology review",
        payload={"ordered_attempt_ids": [ATTEMPT, ATTEMPT]},
    )
    with pytest.raises(HTTPException, match="unique"):
        asyncio.run(apply_intake_control(user, "test-token", ACTOR, UUID(CASE), body))
    assert not user.saved
    body.payload = {"ordered_attempt_ids": [ATTEMPT]}
    asyncio.run(apply_intake_control(user, "test-token", ACTOR, UUID(CASE), body))
    assert user.saved[0][0] == "cfin_intake_control"


def test_parser_never_accepts_an_extra_catalogue_source_without_saved_record_bytes():
    inputs, files, _ = prepare_pack(request())
    catalogue = [source.model_dump(mode="json") for source in inputs.catalogue]
    catalogue.append({**catalogue[1], "source_id": "unsaved-answer-source"})
    files["source-catalogue.json"] = encode_json(catalogue)
    with pytest.raises(ValueError, match="undeclared or missing"):
        parse_input_files(files)


def test_http_fake_general_intake_commits_exact_evidence_links_and_all_hashes():
    cloud = CloudHTTP()
    body = request("MAP-01")
    with cloud.client() as client:
        result = client.post(
            "/api/intakes",
            headers={"Authorization": "Bearer synthetic-user-token"},
            json=body.model_dump(mode="json"),
        )
    assert result.status_code == 200
    assert len(cloud.registered) == 8 and len(cloud.committed) == 1
    committed = cloud.committed[0]
    assert len(committed["input_sources"]) == 8
    assert len(committed["input_pack_sha256"]) == 64
    assert {source["filename"] for source in committed["input_sources"]} == {
        name for name in AGENT_FILES if name != "original-log.txt"
    }
    registered = {row["storage"]["filename"]: row["storage"] for row in cloud.registered}
    assert all(
        source["sha256"] == registered[source["filename"]]["sha256"]
        for source in committed["input_sources"]
    )
    assert all(row["storage"]["provenance"]["synthetic"] for row in cloud.registered)
    assert committed["manifest"]["attempt_id"] == "MAP01-0001"


def test_http_fake_invalid_general_pack_has_no_privileged_upload_or_db_write():
    cloud = CloudHTTP()
    body = request("MAP-01")
    body.agent_files["mapping-reference.json"]["absence_audit"]["query_completed"] = False
    with cloud.client() as client:
        result = client.post(
            "/api/intakes",
            headers={"Authorization": "Bearer synthetic-user-token"},
            json=body.model_dump(mode="json"),
        )
    assert result.status_code == 422
    assert not cloud.writes()
