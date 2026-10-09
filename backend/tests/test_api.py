from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from cfin.config import Settings
from cfin.main import create_app

ACTOR = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE = "22222222-2222-4222-8222-222222222222"


def make_client(handler):
    settings = Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="test-publishable-key",
    )
    return TestClient(create_app(settings, httpx.MockTransport(handler)))


def test_unconfigured_health_and_explicit_setup_state():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.get("/api/cases", params={"workspace_id": WORKSPACE}).status_code == 401


def test_signed_out_and_invalid_tokens_cannot_read_cases():
    def handler(request):
        assert request.url.path == "/auth/v1/user"
        return httpx.Response(401)

    with make_client(handler) as client:
        assert client.get("/api/workspaces").status_code == 401
        assert (
            client.get("/api/workspaces", headers={"Authorization": "Bearer forged"}).status_code
            == 401
        )


def test_nonmember_denied_before_case_query():
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": str(ACTOR)})
        return httpx.Response(200, json=[])

    with make_client(handler) as client:
        response = client.get(
            "/api/cases",
            params={"workspace_id": WORKSPACE},
            headers={"Authorization": "Bearer user-token"},
        )
        assert response.status_code == 403
        assert "/rest/v1/cases" not in requested


def test_cloud_reads_forward_user_token_and_workspace_scope():
    def handler(request):
        assert request.headers["authorization"] == "Bearer user-token"
        assert request.headers["apikey"] == "test-publishable-key"
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": str(ACTOR)})
        if request.url.path == "/rest/v1/workspace_memberships":
            assert request.url.params["user_id"] == f"eq.{ACTOR}"
            return httpx.Response(
                200,
                json=[
                    {
                        "workspace_id": WORKSPACE,
                        "roles": ["process_owner"],
                        "workspaces": {"id": WORKSPACE, "name": "Synthetic POC"},
                    }
                ],
            )
        assert request.url.params["workspace_id"] == f"eq.{WORKSPACE}"
        return httpx.Response(200, json=[])

    with make_client(handler) as client:
        headers = {"Authorization": "Bearer user-token"}
        workspaces = client.get("/api/workspaces", headers=headers)
        assert workspaces.json()[0]["roles"] == ["process_owner"]
        assert (
            client.get("/api/cases", params={"workspace_id": WORKSPACE}, headers=headers).json()
            == []
        )


def test_cloud_outage_has_retryable_error_without_raw_credentials():
    def handler(request):
        raise httpx.ConnectError("sensitive upstream diagnostic", request=request)

    with make_client(handler) as client:
        response = client.get("/api/workspaces", headers={"Authorization": "Bearer user-token"})
        assert response.status_code == 503
        assert "sensitive" not in response.text
