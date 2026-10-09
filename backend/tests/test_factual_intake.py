"""Intake integrity and retry boundaries; no cloud or model calls."""

import asyncio
import base64
import hashlib
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from cfin.config import Settings
from cfin.factual_intake import LogIntakeRequest, commit_log_intake
from cfin.gateway import ServiceGateway

WORKSPACE = UUID("22222222-2222-4222-8222-222222222222")
ACTOR = UUID("11111111-1111-4111-8111-111111111111")
CASE = "33333333-3333-4333-8333-333333333333"


def body(*originals, **changes):
    return LogIntakeRequest.model_validate(
        {
            "workspace_id": str(WORKSPACE),
            "delivery_key": "receipt-1",
            "provenance": "user_supplied",
            "sources": [
                {"filename": "original.txt", "content_base64": base64.b64encode(raw).decode()}
                for raw in originals or (b"E account=0001\r\n",)
            ],
            **changes,
        }
    )


class User:
    def __init__(self, allowed=True):
        self.allowed = allowed

    async def require_member(self, token, actor, workspace, role):
        assert (actor, workspace, role) == (ACTOR, WORKSPACE, "process_owner")
        if not self.allowed:
            raise HTTPException(403, "Denied")
        return {"workspaces": {"synthetic": False}}

    async def rows(self, table, token, workspace, filters):
        return [{"id": CASE, "version": 1}]


class Service:
    def __init__(self):
        self.saved, self.calls = [], []
        self.fail_on = None

    async def store_original(self, workspace, raw, filename, source):
        self.saved.append((workspace, raw, filename, source))
        if self.fail_on == len(self.saved):
            raise HTTPException(503, "Storage unavailable")
        return {
            "object_path": f"{workspace}/{source}/{filename}",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_size": len(raw),
            "filename": filename,
            "content_type": "text/plain",
        }

    async def rpc(self, name, payload):
        self.calls.append((name, payload))
        return {"case_id": CASE, "run_id": "run-1"}


def commit(request, service=None, user=None, enabled=True):
    service = service or Service()
    result = asyncio.run(
        commit_log_intake(
            user or User(),
            service,
            Settings(_env_file=None, log_only_enabled=enabled),
            "user-token",
            ACTOR,
            request,
        )
    )
    return result, service


def test_multisource_receipt_is_exact_stable_and_separate_from_business_time():
    request = body(b"\xef\xbb\xbfitem=0001\r\n", b"odd separator\x0b remains\n")
    result, service = commit(request)
    _, retry = commit(request)
    assert service.saved == retry.saved
    assert result["paid_dispatch_enabled"] is False
    payload = service.calls[0][1]
    assert len(payload["manifest"]["sources"]) == 2
    assert len({item[3] for item in service.saved}) == 2  # same filenames remain distinct
    assert "business_identity" not in payload and "processing_at" not in payload
    assert all(item["provenance"]["kind"] == "user_supplied" for item in payload["input_sources"])
    assert all(
        item["provenance"]["timestamp_kind"] == "application_receipt"
        for item in payload["input_sources"]
    )
    assert payload["model_configuration"]["agent1"] == "gpt-6-luna"
    _, changed = commit(
        request.model_copy(
            update={
                "routing_context": request.routing_context.model_copy(
                    update={"company_code": "0001"}
                )
            }
        )
    )
    assert payload["input_pack_sha256"] != changed.calls[0][1]["input_pack_sha256"]
    assert payload["source_manifest_sha256"] == changed.calls[0][1]["source_manifest_sha256"]


@pytest.mark.parametrize(
    "intake_request",
    [
        body(b"valid", b"\xff"),
        body(b"x" * 8193),
        body(sources=[{"filename": "bad.txt", "content_base64": "invalid!"}]),
        body(sources=[{"filename": "../bad.txt", "content_base64": "YQ=="}]),
    ],
)
def test_entire_envelope_is_validated_before_any_storage(intake_request):
    service = Service()
    with pytest.raises(HTTPException) as caught:
        commit(intake_request, service)
    assert caught.value.status_code == 422
    assert service.saved == service.calls == []


def test_failed_partial_upload_never_queues_and_retry_reuses_identity():
    request, service = body(b"one", b"two"), Service()
    service.fail_on = 2
    with pytest.raises(HTTPException):
        commit(request, service)
    assert not service.calls
    saved = list(service.saved)
    service.fail_on = None
    commit(request, service)
    assert service.saved[2:] == saved
    assert len(service.calls) == 1


@pytest.mark.parametrize("allowed,enabled,status", [(False, True, 403), (True, False, 503)])
def test_authentication_and_rollout_gate_precede_storage(allowed, enabled, status):
    service = Service()
    with pytest.raises(HTTPException) as caught:
        commit(body(), service, User(allowed), enabled)
    assert caught.value.status_code == status
    assert not service.saved and not service.calls


def storage(handler, raw=b"same\r\n"):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = ServiceGateway(
                Settings(
                    _env_file=None,
                    supabase_url="https://example.test",
                    supabase_publishable_key="public",
                    supabase_secret_key="secret",
                ),
                client,
            )
            return await gateway.store_original(WORKSPACE, raw, "original.txt", ACTOR)

    return asyncio.run(run())


def test_storage_create_once_conflict_race_accepts_only_exact_readback():
    calls = []

    def handler(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(404)
        if request.method == "POST":
            assert request.headers["x-upsert"] == "false"
            return httpx.Response(409)
        return httpx.Response(200, content=b"same\r\n")

    assert storage(handler)["byte_size"] == 6
    assert calls == ["GET", "POST", "GET"]


@pytest.mark.parametrize("status,raw,expected", [(403, b"", 503), (200, b"other", 409)])
def test_storage_denial_or_changed_original_never_overwrites(status, raw, expected):
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(status, content=raw)

    with pytest.raises(HTTPException) as caught:
        storage(handler)
    assert caught.value.status_code == expected


@pytest.mark.parametrize("synthetic", [True, None])
def test_real_source_is_rejected_before_storage_without_nonsynthetic_workspace(synthetic):
    class ProvenanceUser(User):
        async def require_member(self, token, actor, workspace, role):
            return {"workspaces": {"synthetic": synthetic}}

    service = Service()
    with pytest.raises(HTTPException) as exc:
        commit(body(provenance="user_supplied"), service=service, user=ProvenanceUser())
    assert exc.value.status_code == 422
    assert service.saved == [] and service.calls == []
