"""Public HTTP contract and redaction; SQL scope fences are tested in PostgreSQL."""

import asyncio
import hashlib
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_log_only_workflow import RecordingAdapter, binding_for, inputs_for

from cfin.case_read_api import Cursor, _encode_cursor
from cfin.config import Settings
from cfin.log_only_workflow import LogWorkflowExecutor
from cfin.main import create_app

W = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"
TOKEN = "cfin_read_" + "a" * 43
HEADERS = {"Authorization": "Bearer " + TOKEN}
PARAMS = {"workspace_id": W, "case_version": 3}
INPUTS = inputs_for(b"E item=0001\r\n", b"W unclear value\n")
RESULT = asyncio.run(LogWorkflowExecutor(RecordingAdapter(INPUTS), binding_for(INPUTS)).run(INPUTS))
FACTUAL = RESULT.result.model_dump(mode="json")
CASE = {
    "id": C,
    "workspace_id": W,
    "version": 3,
    "title": "Saved factual title",
    "priority": "P2",
    "status": "open",
    "workflow_version": "log-only-v1",
    "factual_review_status": "Accepted",
    "input_revision": 1,
    "requested_run_id": "run-1",
    "published_run_id": "run-1",
    "owner_user_id": "owner-1",
    "analysis_status": "available",
    "factual_result": FACTUAL,
    "source_manifest": INPUTS.manifest.model_dump(mode="json"),
    "secret_key": "never-public",
}


class Service:
    def __init__(self):
        self.calls = []
        self.denied = False
        self.after_download_deny = False
        self.case = dict(CASE)
        self.latest = {"state": "succeeded"}
        self.resource = {}

    async def rpc(self, name, payload):
        assert name == "cfin_machine_read"
        self.calls.append(payload)
        assert payload["token_sha256"] == hashlib.sha256(TOKEN.encode()).hexdigest()
        assert TOKEN not in str(payload)
        if self.denied:
            return {"error": "access_denied"}
        if payload.get("case_version", 3) != 3:
            raise HTTPException(409, "Case snapshot changed")
        resource = payload["resource"]
        if resource in self.resource:
            return self.resource[resource]
        if resource == "case":
            return {
                "case": self.case,
                "evidence": [],
                "latest_run": self.latest,
                "snapshot": {"secret": "never-public"},
            }
        if resource == "cases":
            return {
                "items": [self.case],
                "total": 2,
                "snapshot_id": "44444444-4444-4444-8444-444444444444",
                "expires_at": "2026-10-02T12:00:00Z",
            }
        if resource == "source":
            source = INPUTS.manifest.sources[0]
            return {
                "evidence": {
                    "filename": source.original_filename,
                    "byte_size": source.byte_size,
                    "sha256": source.content_sha256,
                    "content_type": "text/plain",
                    "object_path": "private/storage/key",
                }
            }
        raise AssertionError(resource)

    async def download(self, evidence):
        self.denied = self.after_download_deny
        return b"E item=0001\r\n"


@pytest.fixture
def client():
    with TestClient(create_app(Settings(_env_file=None)), base_url="https://consumer.test") as test:
        test.app.state.service = Service()
        yield test


def test_saved_case_public_shape_owner_and_no_service_or_unselected_history(client):
    response = client.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS)
    assert response.status_code == 200
    value = response.json()
    assert value["owner_id"] == "owner-1" and value["review_status"] == "Accepted"
    assert value["analysis"]["stale"] is False
    assert value["result"]["result_kind"] == "factual"
    assert value["result"]["title"] == FACTUAL["summary"]["title"]
    assert value["sources"][0]["content_sha256"] == INPUTS.manifest.sources[0].content_sha256
    assert response.headers["cache-control"] == "no-store"
    for hidden in (
        "never-public",
        "object_path",
        "candidates",
        "prompt_versions",
        "model_configuration",
    ):
        assert hidden not in response.text


def test_failed_replacement_is_separate_and_marks_preserved_result_old(client):
    client.app.state.service.case.update(requested_run_id="run-2", analysis_status="unavailable")
    client.app.state.service.latest = {
        "state": "failed",
        "output": {"failure_reason": "No usable evidence"},
    }
    value = client.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS).json()
    assert value["analysis"]["stale"] and value["analysis"]["run_id"] == "run-1"
    assert value["analysis"]["latest_failure"] == "No usable evidence"
    assert value["result"]["title"] == FACTUAL["summary"]["title"]


def test_legacy_keeps_diagnostic_meaning_and_no_invented_readable_lines(client):
    client.app.state.service.case.update(
        workflow_version="legacy-v1",
        diagnosis_status="Corrected",
        category="legacy-category",
        description="old output",
    )
    value = client.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS).json()
    assert value["result"]["result_kind"] == "legacy"
    assert value["review_status"] == "Corrected"
    assert value["result"]["cause_label"] == "legacy-category"
    assert (
        client.get(f"/api/v1/cases/{C}/extraction", params=PARAMS, headers=HEADERS).status_code
        == 409
    )


@pytest.mark.parametrize("auth", [None, "Bearer user-jwt", "Bearer cfin_read_bad"])
def test_unscoped_tokens_are_rejected_before_cloud(client, auth):
    response = client.get(
        f"/api/v1/cases/{C}", params=PARAMS, headers={"Authorization": auth} if auth else {}
    )
    assert response.status_code == 401
    assert not client.app.state.service.calls


def test_denial_is_translated_without_leaking_existence(client):
    client.app.state.service.denied = True
    response = client.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS)
    assert response.status_code == 403
    assert "token_sha256" not in response.text


def test_network_http_requires_tls_before_cloud(client):
    response = client.get(f"http://consumer.test/api/v1/cases/{C}", params=PARAMS, headers=HEADERS)
    assert response.status_code == 400 and not client.app.state.service.calls


def test_exact_original_json_and_raw_download_recheck_revocation(client):
    source = INPUTS.manifest.sources[0]
    url = f"/api/v1/cases/{C}/sources/{source.source_id}"
    params = {**PARAMS, "source_version": source.source_version}
    response = client.get(url, params=params, headers=HEADERS)
    value = response.json()
    assert value["text"] == "E item=0001\r\n"
    assert hashlib.sha256(value["text"].encode()).hexdigest() == value["sha256"]
    assert "object_path" not in response.text
    assert len(client.app.state.service.calls) == 2
    assert (
        client.get(url + "/download", params=params, headers=HEADERS).content == b"E item=0001\r\n"
    )
    client.app.state.service.after_download_deny = True
    assert client.get(url, params=params, headers=HEADERS).status_code == 403


def test_extraction_and_selection_pages_require_stable_case_version(client):
    url = f"/api/v1/cases/{C}/extraction"
    params = {**PARAMS, "limit": 1}
    first = client.get(url, params=params, headers=HEADERS).json()
    assert first["total"] == 2 and len(first["items"]) == 1
    second = client.get(
        url, params={**params, "cursor": first["next_cursor"]}, headers=HEADERS
    ).json()
    assert second["next_cursor"] is None
    assert first["items"][0]["entry_id"] != second["items"][0]["entry_id"]
    assert client.get(url, params={"workspace_id": W}, headers=HEADERS).status_code == 422
    assert client.get(url, params={**PARAMS, "case_version": 4}, headers=HEADERS).status_code == 409
    assert (
        client.get(
            f"/api/v1/cases/{C}/selected-evidence",
            params={**params, "cursor": first["next_cursor"]},
            headers=HEADERS,
        ).status_code
        == 422
    )


def test_list_snapshot_cursor_binds_filters_workspace_limit_and_snapshot(client):
    params = {"workspace_id": W, "limit": 1, "workflow_version": "log-only-v1"}
    first = client.get("/api/v1/cases", params=params, headers=HEADERS).json()
    response = client.get(
        "/api/v1/cases", params={**params, "cursor": first["next_cursor"]}, headers=HEADERS
    )
    assert response.status_code == 200
    payload = client.app.state.service.calls[-1]
    assert payload["snapshot_id"] == first["snapshot_id"] and payload["offset"] == 1
    assert (
        client.get(
            "/api/v1/cases",
            params={**params, "workflow_version": "legacy-v1", "cursor": first["next_cursor"]},
            headers=HEADERS,
        ).status_code
        == 422
    )
    bad = _encode_cursor(Cursor(resource="cases", workspace_id=UUID(C), offset=1, limit=1))
    assert (
        client.get("/api/v1/cases", params={**params, "cursor": bad}, headers=HEADERS).status_code
        == 422
    )


def test_records_export_human_findings_without_internal_service_fields(client):
    client.app.state.service.resource["records"] = {
        "total": 1,
        "items": [
            {
                "id": "review-1",
                "kind": "review_factual",
                "actor_id": "owner-1",
                "recorded_at": "2026-10-02T10:00:00Z",
                "payload": {
                    "decision": "Corrected",
                    "reason": "Item was misstated",
                    "findings": {
                        "explanation": "0001 is the logged item",
                        "gaps": [],
                        "entry_ids": ["entry-0"],
                        "private_candidate": "never-public",
                    },
                    "secret_key": "never-public",
                },
            }
        ],
    }
    response = client.get(f"/api/v1/cases/{C}/records", params=PARAMS, headers=HEADERS)
    assert response.status_code == 200
    value = response.json()["items"][0]
    assert value["findings"]["entry_ids"] == ["entry-0"]
    assert value["provenance"] == "recorded_case_history" and "never-public" not in response.text


def test_openapi_declares_concrete_versioned_response_contracts_and_no_write_routes(client):
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if path.startswith("/api/v1/"):
            assert set(operations) == {"get"}
            if not path.endswith("/download"):
                assert (
                    "$ref"
                    in operations["get"]["responses"]["200"]["content"]["application/json"][
                        "schema"
                    ]
                )


class CredentialUser:
    def __init__(self):
        self.calls = []
        self.denied = False

    async def actor(self, token):
        self.calls.append(("actor", token))
        if token.startswith("cfin_read_"):
            raise HTTPException(401, "Signed-in user required")
        return UUID(C)

    async def require_member(self, token, actor, workspace, role):
        self.calls.append(("member", str(actor), str(workspace), role))
        if self.denied:
            raise HTTPException(403, "Process owner required")

    async def rpc(self, name, token, payload):
        self.calls.append((name, payload))
        return {"id": "44444444-4444-4444-8444-444444444444"}


def test_read_credential_issuance_requires_signed_owner_and_only_stores_hash(client):
    user = CredentialUser()
    client.app.state.cloud = user
    response = client.post(
        f"/api/workspaces/{W}/read-credentials",
        json={
            "label": "External reader",
            "scopes": ["cases:read"],
            "expires_in_days": 1,
        },
        headers={"Authorization": "Bearer signed-user-token"},
    )
    assert response.status_code == 200
    token = response.json()["read_token"]
    assert token.startswith("cfin_read_") and len(token) == 53
    assert user.calls[1] == ("member", C, W, "process_owner")
    payload = user.calls[2][1]
    assert payload["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(payload)
    assert "actor_id" not in payload
    assert payload["scopes"] == ["cases:read"]
    assert response.headers["cache-control"] == "no-store"
    assert not client.app.state.service.calls


@pytest.mark.parametrize("action", ["create", "revoke"])
def test_credential_admin_routes_require_tls_before_auth_or_mutation(client, action):
    user = CredentialUser()
    client.app.state.cloud = user
    url = f"http://consumer.test/api/workspaces/{W}/read-credentials"
    if action == "revoke":
        url += f"/{C}/revoke"
    response = client.post(
        url,
        headers={"Authorization": "Bearer signed-user-token"},
        json={"label": "Reader", "scopes": ["cases:read"]},
    )
    assert response.status_code == 400 and user.calls == []


def test_machine_read_token_cannot_issue_additional_credentials(client):
    user = CredentialUser()
    client.app.state.cloud = user
    response = client.post(
        f"/api/workspaces/{W}/read-credentials",
        headers=HEADERS,
        json={"label": "Escalation", "scopes": ["evidence:read"]},
    )
    assert response.status_code == 401
    assert [call[0] for call in user.calls] == ["actor"]


def test_non_owner_cannot_issue_credentials(client):
    user = CredentialUser()
    user.denied = True
    client.app.state.cloud = user
    response = client.post(
        f"/api/workspaces/{W}/read-credentials",
        headers={"Authorization": "Bearer signed-user-token"},
        json={"label": "Escalation", "scopes": ["evidence:read"]},
    )
    assert response.status_code == 403
    assert [call[0] for call in user.calls] == ["actor", "member"]


def test_activity_reads_real_event_type_column_without_exporting_internal_payload(client):
    client.app.state.service.resource["activity"] = {
        "total": 1,
        "items": [
            {
                "id": "event-1",
                "event_type": "summary_reviewed",
                "actor_id": "reviewer",
                "acting_role": "process_owner",
                "created_at": "2026-10-02T10:00:00Z",
                "reason": "Reviewed current original",
                "after": {"private_key": "never-public"},
            }
        ],
    }
    response = client.get(f"/api/v1/cases/{C}/activity", params=PARAMS, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["items"][0]["action"] == "summary_reviewed"
    assert "never-public" not in response.text


def test_legacy_human_scope_and_corrected_cause_remain_typed_and_separate(client):
    client.app.state.service.resource["records"] = {
        "total": 1,
        "items": [
            {
                "id": "legacy-review",
                "kind": "review_diagnosis",
                "payload": {
                    "scope": {
                        "target_system": "TGT",
                        "target_object": "000123",
                        "company_code": "0010",
                        "reuse_limitations": "This historical document only",
                    },
                    "findings": {
                        "cause_label": "Human reviewed legacy cause",
                        "explanation": "Old review",
                        "citations": [
                            {"source_id": "old", "source_version": "1", "record_id": "row1"}
                        ],
                    },
                },
            }
        ],
    }
    response = client.get(f"/api/v1/cases/{C}/records", params=PARAMS, headers=HEADERS)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["scope"]["target_object"] == "000123"
    assert item["findings"]["cause_label"] == "Human reviewed legacy cause"
    assert item["provenance"] == "recorded_case_history"


@pytest.mark.parametrize(
    "error,status",
    [
        ("access_denied", 403),
        ("not_found", 404),
        ("snapshot_changed", 409),
        ("invalid_input", 422),
        ("unexpected_internal_detail", 503),
    ],
)
def test_database_read_errors_have_safe_http_contract(client, error, status):
    client.app.state.service.resource["case"] = {"error": error, "detail": "private SQL text"}
    response = client.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS)
    assert response.status_code == status
    assert "private SQL text" not in response.text
    assert "unexpected_internal_detail" not in response.text


def test_resolved_state_is_explicit_in_case_and_list(client):
    client.app.state.service.case.update(status="document_reprocessed", resolved=True)
    detail = client.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS).json()
    page = client.get("/api/v1/cases", params={"workspace_id": W}, headers=HEADERS).json()
    assert detail["operational_status"] == "document_reprocessed" and detail["resolved"] is True
    assert page["items"][0]["resolved"] is True


def test_plaintext_cannot_bypass_tls_with_a_spoofed_localhost_header(client):
    response = client.get(
        f"http://consumer.test/api/v1/cases/{C}",
        params=PARAMS,
        headers={**HEADERS, "Host": "localhost"},
    )
    assert response.status_code == 400 and not client.app.state.service.calls


def test_plaintext_loopback_development_requires_both_local_origin_and_peer():
    with TestClient(
        create_app(Settings(_env_file=None)),
        base_url="http://localhost",
        client=("127.0.0.1", 51000),
    ) as test:
        test.app.state.service = Service()
        assert test.get(f"/api/v1/cases/{C}", params=PARAMS, headers=HEADERS).status_code == 200
