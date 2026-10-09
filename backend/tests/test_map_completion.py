"""MAP lifecycle HTTP fakes: no human approval, provider call or cloud mutation."""

import asyncio
import copy
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from test_general_intake import request
from test_operations import ACTOR, ATTEMPT, CASE, HEADERS, RUN, WORKSPACE, CloudHTTP

from cfin.intake import prepare_pack
from cfin.operations import validation_values
from cfin.snapshots import restore_inputs


class MapCloud(CloudHTTP):
    def __init__(self):
        super().__init__()
        self.milestones = []
        self.links = []
        inputs, files, _ = prepare_pack(request("MAP-01"))
        manifest = inputs.manifest.model_dump(mode="json")
        sources = []
        for name, content in files.items():
            raw = json.loads(content) if name.endswith(".json") else {}
            source_id = raw.get("source_id") if isinstance(raw, dict) else None
            evidence = self.saved(
                content, name, "original_log" if name == "original-log.txt" else "reference",
                source_id=source_id or "MAP01-file-" + name,
            )
            review = None
            if name in ("mapping-reference.json", "missing-gl-master-playbook.json"):
                review = {
                    "id": str(uuid4()), "workspace_id": str(WORKSPACE),
                    "evidence_id": evidence["id"], "version": 1, "decision": "approved",
                    "reference_kind": "mapping" if name.startswith("mapping") else "guidance",
                    "scope": raw.get("scope", raw.get("query_scope", {})),
                    "actor_id": str(ACTOR), "acting_role": "process_owner",
                    "reason": "Hypothetical software test; no person approved this reference",
                    "reviewed_at": "2026-09-30T09:05:00Z",
                }
                self.reviews.append(review)
            sources.append({"evidence": evidence, "review": review})
        self.attempts = [{
            "id": str(ATTEMPT), "workspace_id": str(WORKSPACE), "case_id": str(CASE),
            "attempt_key": manifest["attempt_id"], "processing_at": manifest["processing_at"],
            "processing_order": manifest["processing_order"], "result": "failed",
            "validation_status": "pending", "target_document_reference": None,
        }]
        self.case["business_context"] = manifest["business_context"]
        self.case["status"] = "in_progress"
        self.runs = [{
            "id": str(RUN), "workspace_id": str(WORKSPACE), "case_id": str(CASE),
            "attempt_id": str(ATTEMPT), "input_revision": 1, "state": "succeeded",
            "output": {"routing": {"agent3_eligible": True}},
            "snapshot": {
                "case_id": str(CASE), "attempt_id": str(ATTEMPT), "input_revision": 1,
                "identity": manifest["identity"], "manifest": manifest,
                "business_context": manifest["business_context"],
                "attempt": copy.deepcopy(self.attempts[0]), "sources": sources,
            },
        }]

    def handler(self, request):
        table = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET" and table in ("milestones", "milestone_proof"):
            self.requests.append(request)
            rows = self.milestones if table == "milestones" else self.links
            return httpx.Response(200, json=rows)
        return super().handler(request)

    def saved_simulation(self, observation):
        row = self.saved(json.dumps(observation).encode(), "software-proof.json", "proof")
        row["provenance"]["verified_observation"] = copy.deepcopy(observation)
        return row


def simulate(client, kind, payload):
    return client.post(
        f"/api/cases/{CASE}/simulation", headers=HEADERS,
        json={"workspace_id": str(WORKSPACE), "acting_role": "process_owner",
              "kind": kind, "human_confirmed": True, "payload": payload},
    )


def save_correction_fixture(cloud, client):
    response = simulate(client, "correction", {"explanation": "Software test mapping change"})
    assert response.status_code == 200, response.text
    observation = cloud.registered[-1]["storage"]["provenance"]["verified_observation"]
    proof = cloud.saved_simulation(observation)
    response = client.post(
        f"/api/cases/{CASE}/actions", headers=HEADERS,
        json={
            "workspace_id": str(WORKSPACE), "acting_role": "process_owner",
            "expected_version": 1, "action": "record_correction",
            "payload": {
                "human_confirmed": True, "occurred_at": "2026-10-01T09:00:00Z",
                "proof_ids": [proof["id"]], "target_system": "CFIN-DEMO",
                "target_object": "0041001000", "explanation": "Software test mapping change",
            },
        },
    )
    assert response.status_code == 200, response.text
    action = next(
        json.loads(request.content)["payload"] for request in reversed(cloud.requests)
        if request.url.path.endswith("cfin_case_action")
    )
    assert action["action"] == "record_correction" and action["data"]["proof_ids"] == [proof["id"]]
    # Emulate the durable rows returned by the SQL action; this HTTP fake does
    # not claim to exercise PostgreSQL or record an actual person's approval.
    milestone = {
        "id": str(uuid4()), "workspace_id": str(WORKSPACE), "case_id": str(CASE),
        "attempt_id": str(ATTEMPT), "work_cycle": 1, "kind": "correction",
        "human_confirmed": True, "actor_id": str(ACTOR), "acting_role": "process_owner",
        "details": {"target_system": "CFIN-DEMO", "target_object": "0041001000"},
    }
    cloud.milestones.append(milestone)
    cloud.links.append({"milestone_id": milestone["id"], "evidence_id": proof["id"]})
    cloud.case["status"] = "complete"
    return proof, milestone


def reprocessing_payload():
    return {"attempt_key": "MAP-SUCCESS-2", "target_document_reference": "MAP-TARGET-123",
            "processing_order": 2, "processing_at": "2026-10-01T10:00:00Z"}


def test_map_correction_reprocessing_and_exact_validation_preserve_absent_failure_lookup():
    cloud = MapCloud()
    with cloud.client() as client:
        proof, milestone = save_correction_fixture(cloud, client)
        correction = proof["provenance"]["verified_observation"]
        assert correction["corrected_components"] == ["applicable_mapping"]
        assert (
            correction["mapping_change"]["independent_target_record_id"]
            == "independent-target-design"
        )
        response = simulate(client, "reprocessing", reprocessing_payload())
        assert response.status_code == 200, response.text
        target = cloud.registered[-1]["storage"]["provenance"]["verified_observation"]
        assert target["mapping_correction"]["milestone_id"] == milestone["id"]
        assert target["mapping_correction"]["proof_id"] == proof["id"]
        assert [row["target_account"] for row in target["posting"]["lines"]] == [
            "0041001000", "0021000000",
        ]
        inputs = asyncio.run(restore_inputs(cloud.runs[0]["snapshot"], _Bytes(cloud)))
        assert inputs.sources["mapping-reference.json"]["records"] == []
        header = inputs.sources["source-posting.json"]["records"][0]
        assert header["source_document_number"] == "0000123457"
        comparisons = validation_values(inputs, target)
        assert all(value["expected"] == value["observed"] for value in comparisons.values())
        cloud.saved_simulation(target)
        cloud.attempts[0].update(
            attempt_key=target["attempt_key"], result="successful",
            target_document_reference=target["target_document_reference"], processing_order=2,
        )
        cloud.case["status"] = "document_reprocessed"
        checks = [{"dimension": key, "result": "passed", **value}
                  for key, value in comparisons.items()]
        response = simulate(client, "validation", {"checks": checks})
        assert response.status_code == 200, response.text
        verified = cloud.registered[-1]["storage"]["provenance"]["verified_observation"]
        assert verified["status"] == "passed" and len(verified["checks"]) == 4


class _Bytes:
    def __init__(self, cloud):
        self.cloud = cloud

    async def download(self, evidence):
        return self.cloud.objects[evidence["object_path"]]


@pytest.mark.parametrize("tamper", ["missing", "actor", "cycle", "unlinked", "design", "target"])
def test_map_reprocessing_requires_exact_saved_authenticated_correction(tamper):
    cloud = MapCloud()
    with cloud.client() as client:
        proof, milestone = save_correction_fixture(cloud, client)
        if tamper == "missing":
            cloud.milestones = []
        elif tamper == "actor":
            milestone["actor_id"] = str(uuid4())
        elif tamper == "cycle":
            milestone["work_cycle"] = 2
        elif tamper == "unlinked":
            cloud.links = []
        elif tamper == "design":
            proof["provenance"]["verified_observation"]["mapping_change"]["target_account"] = (
                "0049999999"
            )
        else:
            milestone["details"]["target_object"] = "0049999999"
        before = len(cloud.registered)
        response = simulate(client, "reprocessing", reprocessing_payload())
        assert response.status_code == 422 and len(cloud.registered) == before


def test_map_validation_does_not_infer_a_correction_from_a_target_account():
    cloud = MapCloud()
    inputs = asyncio.run(restore_inputs(cloud.runs[0]["snapshot"], _Bytes(cloud)))
    with pytest.raises(HTTPException, match="Saved mapping correction"):
        validation_values(inputs, cloud.target_proof())
