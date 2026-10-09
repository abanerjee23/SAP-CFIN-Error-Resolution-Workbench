"""Demo access remains local, scoped, explicitly enabled, and visibly simulated."""

import time
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cfin.config import Settings
from cfin.demo import DEMO_ROLES
from cfin.integration_check import TestSession as DemoIdentity
from cfin.main import create_app

W = "22222222-2222-4222-8222-222222222222"
A = UUID("11111111-1111-4111-8111-111111111111")
C = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
ORIGIN = "http://127.0.0.1:3000"


def build(monkeypatch, *, enabled=True, synthetic=True, host="127.0.0.1"):
    settings = Settings(
        _env_file=None,
        local_demo_enabled=enabled,
        demo_workspace_id=W,
        demo_actor_id=A,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="public",
        supabase_secret_key="private",
    )
    establish = AsyncMock(return_value=DemoIdentity(A, SecretStr("private-user-jwt")))
    monkeypatch.setattr("cfin.demo.existing_user_session", establish)
    monkeypatch.setattr("cfin.demo.sign_out_local", AsyncMock(return_value=True))

    def handler(request):
        assert request.headers["authorization"] == "Bearer private-user-jwt"
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": str(A)})
        if request.url.path == "/rest/v1/workspace_memberships":
            return httpx.Response(
                200,
                json=[
                    {
                        "workspace_id": W,
                        "roles": list(DEMO_ROLES),
                        "workspaces": {"name": "Synthetic demo", "synthetic": synthetic},
                    },
                    {
                        "workspace_id": OTHER,
                        "roles": ["process_owner"],
                        "workspaces": {"name": "Private workspace", "synthetic": False},
                    },
                ],
            )
        if request.url.path == "/rest/v1/rpc/cfin_case_page":
            return httpx.Response(200, json={"items": [], "total": 0, "page": 1})
        raise AssertionError(request.url.path)

    client = TestClient(
        create_app(settings, httpx.MockTransport(handler)),
        base_url="http://127.0.0.1",
        client=(host, 1234),
        headers={"Origin": ORIGIN},
    )
    return client, establish


def start(client):
    response = client.post("/api/demo/session")
    assert response.status_code == 200, response.text
    assert "private-user-jwt" not in response.text
    assert response.json()["workspace"]["id"] == W
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_bootstrap_uses_server_session_and_hides_other_workspaces(monkeypatch):
    client, establish = build(monkeypatch)
    with client:
        headers = start(client)
        start(client)
        establish.assert_awaited_once()
        response = client.get("/api/workspaces", headers=headers)
        assert [w["id"] for w in response.json()] == [W]
        assert (
            client.get("/api/cases/page", params={"workspace_id": W}, headers=headers).status_code
            == 200
        )
        assert client.get("/api/workspaces").status_code == 401


@pytest.mark.parametrize(
    "enabled,synthetic,host,origin,status",
    [
        (False, True, "127.0.0.1", ORIGIN, 404),
        (True, False, "127.0.0.1", ORIGIN, 403),
        (True, True, "203.0.113.1", ORIGIN, 403),
        (True, True, "127.0.0.1", "https://evil.example", 403),
        (True, True, "127.0.0.1", "null", 403),
    ],
)
def test_bootstrap_rejects_unsafe_context(monkeypatch, enabled, synthetic, host, origin, status):
    client, _ = build(monkeypatch, enabled=enabled, synthetic=synthetic, host=host)
    with client:
        assert client.post("/api/demo/session", headers={"Origin": origin}).status_code == status


def test_public_host_and_forged_demo_capabilities_are_rejected(monkeypatch):
    client, _ = build(monkeypatch)
    with client:
        assert (
            client.post("/api/demo/session", headers={"Host": "public.example"}).status_code == 403
        )
        assert (
            client.get(
                "/api/workspaces", headers={"Authorization": "Bearer local-demo-forged"}
            ).status_code
            == 401
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/cases/page?workspace_id=" + OTHER,
        "/api/cases/page?workspace_id=" + OTHER + "&workspace_id=" + W,
        "/api/workspaces/" + OTHER + "/members",
        "/api/knowledge/" + C + "?workspace_id=" + W,
    ],
)
def test_demo_cannot_read_outside_allowlist(monkeypatch, path):
    client, _ = build(monkeypatch)
    with client:
        assert client.get(path, headers=start(client)).status_code == 403


@pytest.mark.parametrize(
    "patch",
    [
        {"workspace_id": OTHER},
        {"acting_role": "validator"},
        {"action": "reopen"},
    ],
)
def test_demo_cannot_write_outside_scope(monkeypatch, patch):
    client, _ = build(monkeypatch)
    with client:
        body = {
            "workspace_id": W,
            "expected_version": 1,
            "acting_role": "process_owner",
            "action": "comment",
            "payload": {"note": "Demo note"},
            **patch,
        }
        assert (
            client.post(
                "/api/cases/" + C + "/actions", json=body, headers=start(client)
            ).status_code
            == 403
        )


def test_demo_audit_label_and_empty_note_guard(monkeypatch):
    client, _ = build(monkeypatch)
    with client:
        headers = start(client)
        action = AsyncMock(return_value={"saved": True})
        client.app.state.operations.action = action
        body = {
            "workspace_id": W,
            "expected_version": 1,
            "acting_role": "mdg_process_owner",
            "action": "comment",
            "payload": {"note": "Fictional approval request"},
        }
        assert (
            client.post("/api/cases/" + C + "/actions", json=body, headers=headers).status_code
            == 200
        )
        saved = action.call_args.args[3]
        assert saved.payload["note"].startswith("[Simulated demo persona: mdg_process_owner]")
        body["payload"]["note"] = " "
        assert (
            client.post("/api/cases/" + C + "/actions", json=body, headers=headers).status_code
            == 422
        )
        action.assert_awaited_once()


def test_synthetic_flag_is_rechecked_and_session_refresh_stays_server_side(monkeypatch):
    client, establish = build(monkeypatch)
    with client:
        headers = start(client)
        client.app.state.demo.created_at = time.monotonic() - 1201
        assert client.get("/api/workspaces", headers=headers).status_code == 200
        assert establish.await_count == 2
        client.app.state.cloud.require_member = AsyncMock(
            return_value={"workspaces": {"synthetic": False}}
        )
        assert client.get("/api/workspaces", headers=headers).status_code == 403


@pytest.mark.parametrize("path", ["/api/intakes/error-analysis", "/api/cases/" + C + "/evidence"])
def test_non_synthetic_uploads_are_rejected(monkeypatch, path):
    client, _ = build(monkeypatch)
    with client:
        body = {"workspace_id": W, "acting_role": "process_owner", "provenance": "user_supplied"}
        # Invoke the auth boundary directly: endpoint schemas reject the intentionally
        # incomplete upload too, so this isolates the provenance guard before any write.
        import asyncio
        import json

        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1"), (b"origin", ORIGIN.encode())],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 80),
            "scheme": "http",
        }

        async def receive():
            return {"type": "http.request", "body": json.dumps(body).encode()}

        request = Request(scope, receive)
        demo = client.app.state.demo
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            asyncio.run(demo.authorise(request, demo.capability, client.app.state.cloud))
        assert error.value.status_code == 403
