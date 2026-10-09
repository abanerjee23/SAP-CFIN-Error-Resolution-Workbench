"""Mock-transport checks for live-test safety; these are not live RLS verification."""

import asyncio
import hashlib
import json
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from cfin.config import Settings
from cfin.integration_check import (
    SERVICE_RPC_PROBES,
    IntegrationCheckError,
    existing_user_session,
    permission_denied,
    run_checks,
)

ACTOR = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE = UUID("22222222-2222-4222-8222-222222222222")
CASE = UUID("33333333-3333-4333-8333-333333333333")
EVIDENCE = UUID("44444444-4444-4444-8444-444444444444")
FOREIGN_WORKSPACE = UUID("55555555-5555-4555-8555-555555555555")
FOREIGN_CASE = UUID("66666666-6666-4666-8666-666666666666")
FOREIGN_EVIDENCE = UUID("77777777-7777-4777-8777-777777777777")
TOKEN = "synthetic-test-access-token"
LINK_TOKEN = "synthetic-test-one-time-token"
SECRET = "sb_secret_synthetic_test_only"
CONTENT = b"Synthetic saved evidence; no real SAP observation"


def settings():
    # model_construct deliberately avoids environment/settings-source reads.
    return Settings.model_construct(
        supabase_url="https://synthetic-test.supabase.co",
        supabase_publishable_key=SecretStr("synthetic-publishable"),
        supabase_secret_key=SecretStr(SECRET),
    )


def check_args():
    return {
        "actor_id": ACTOR,
        "workspace_id": WORKSPACE,
        "foreign_workspace_id": FOREIGN_WORKSPACE,
        "case_id": CASE,
        "foreign_case_id": FOREIGN_CASE,
        "evidence_id": EVIDENCE,
        "foreign_evidence_id": FOREIGN_EVIDENCE,
    }


class SupabaseHTTP:
    def __init__(self):
        self.requests = []
        self.existing_user = True
        self.confirmed = True
        self.seeded = True
        self.actual_actor = str(ACTOR)
        self.fail_rpc = None
        self.foreign_download = (404, {"code": "NoSuchKey", "message": "Object not found"})

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == f"/auth/v1/admin/users/{ACTOR}":
            if not self.existing_user:
                return httpx.Response(404, json={"message": "User not found"})
            return httpx.Response(
                200,
                json={
                    "id": str(ACTOR),
                    "role": "authenticated",
                    "email": "synthetic@example.invalid",
                    "email_confirmed_at": "2026-10-01T10:00:00Z" if self.confirmed else None,
                },
            )
        if path == "/auth/v1/admin/generate_link":
            assert json.loads(request.content) == {
                "type": "magiclink",
                "email": "synthetic@example.invalid",
            }
            return httpx.Response(
                200,
                json={
                    "id": str(ACTOR),
                    "verification_type": "magiclink",
                    "hashed_token": LINK_TOKEN,
                },
            )
        if path == "/auth/v1/verify":
            assert request.headers["apikey"] == "synthetic-publishable"
            assert "Authorization" not in request.headers
            assert json.loads(request.content) == {"token_hash": LINK_TOKEN, "type": "email"}
            return httpx.Response(200, json={"access_token": TOKEN, "refresh_token": "not-saved"})
        if path == "/auth/v1/user":
            assert request.headers["Authorization"] == "Bearer " + TOKEN
            return httpx.Response(200, json={"id": self.actual_actor})
        if path == "/auth/v1/logout":
            assert request.url.params["scope"] == "local"
            return httpx.Response(204)
        if path.startswith("/storage/v1/object/"):
            if "/authenticated/" in path and str(FOREIGN_WORKSPACE) in path:
                return httpx.Response(self.foreign_download[0], json=self.foreign_download[1])
            return httpx.Response(200, content=CONTENT)
        if path.startswith("/rest/v1/rpc/"):
            wrapper = path.rsplit("/", 1)[1]
            assert json.loads(request.content) == {"payload": SERVICE_RPC_PROBES[wrapper[5:]]}
            if wrapper == self.fail_rpc:
                return httpx.Response(400, json={"code": "22P02", "message": "Invalid UUID"})
            return httpx.Response(
                403,
                json={
                    "code": "42501",
                    "message": f"permission denied for function {wrapper}",
                },
            )
        table = path.rsplit("/", 1)[1]
        if request.headers.get("apikey") == SECRET:
            if table == "workspace_memberships":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "user_id": str(ACTOR),
                            "workspace_id": str(WORKSPACE),
                        }
                    ],
                )
            if not self.seeded:
                return httpx.Response(200, json=[])
            row = {"id": request.url.params["id"][3:]}
            if table != "workspaces":
                row["workspace_id"] = request.url.params["workspace_id"][3:]
            if table == "evidence_versions":
                row.update(
                    {
                        "case_id": request.url.params["case_id"][3:],
                        "bucket_id": "evidence",
                        "object_path": row["workspace_id"] + "/synthetic-evidence/original.txt",
                        "sha256": hashlib.sha256(CONTENT).hexdigest(),
                        "byte_size": len(CONTENT),
                    }
                )
            return httpx.Response(200, json=[row])
        if "Authorization" not in request.headers or request.method == "PATCH":
            status = 403 if request.method == "PATCH" else 401
            if request.method == "PATCH":
                column = "id" if table == "workspaces" else "workspace_id"
                assert request.url.params["and"] == (
                    f"({column}.eq.{WORKSPACE},{column}.neq.{WORKSPACE})"
                )
                assert json.loads(request.content) == {column: str(WORKSPACE)}
            return httpx.Response(
                status,
                json={
                    "code": "42501",
                    "message": f"permission denied for table {table}",
                },
            )
        if table == "workspaces":
            return httpx.Response(200, json=[{"id": str(WORKSPACE)}])
        if request.url.params.get("id") == f"eq.{CASE}":
            return httpx.Response(200, json=[{"id": str(CASE), "workspace_id": str(WORKSPACE)}])
        return httpx.Response(200, json=[])


def run(cloud):
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cloud)) as client:
            return await run_checks(settings(), client, **check_args())

    return asyncio.run(execute())


def test_harness_reports_real_http_checks_and_unexecuted_sql_checks_separately():
    cloud = SupabaseHTTP()
    report = run(cloud)
    assert report["workspace_isolation_verified"] is True
    assert report["live_isolation_verified"] is False
    missing = [x["name"] for x in report["checks"] if x["outcome"] == "not_run"]
    assert missing == [
        "separate_account_without_any_memberships",
        "direct_insert_privileges_via_sql_catalog",
    ]
    assert report["paid_model_calls"] == report["human_approvals"] == 0
    assert report["new_auth_users_requested"] is False
    redacted = json.dumps(report)
    assert all(value not in redacted for value in (TOKEN, LINK_TOKEN, SECRET, "synthetic@example"))
    assert not any(r.method == "POST" and r.url.path == "/rest/v1/cases" for r in cloud.requests)
    assert cloud.requests[-1].url.path == "/auth/v1/logout"


@pytest.mark.parametrize("attribute", ["existing_user", "confirmed", "seeded"])
def test_missing_auth_or_seeded_controls_aborts_before_link_generation(attribute):
    cloud = SupabaseHTTP()
    setattr(cloud, attribute, False)
    with pytest.raises(IntegrationCheckError):
        run(cloud)
    assert not any(r.url.path == "/auth/v1/admin/generate_link" for r in cloud.requests)


def test_session_actor_mismatch_signs_out_and_does_not_probe_data():
    cloud = SupabaseHTTP()
    cloud.actual_actor = str(FOREIGN_CASE)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cloud)) as client:
            return await existing_user_session(settings(), client, ACTOR)

    with pytest.raises(IntegrationCheckError):
        asyncio.run(execute())
    assert cloud.requests[-1].url.path == "/auth/v1/logout"
    assert not any(r.url.path.startswith("/rest/") for r in cloud.requests)


def test_cancelling_actual_user_check_still_signs_out_created_session():
    class CancelledHTTP(SupabaseHTTP):
        def __call__(self, request):
            if request.url.path == "/auth/v1/user":
                self.requests.append(request)
                raise asyncio.CancelledError
            return super().__call__(request)

    cloud = CancelledHTTP()

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cloud)) as client:
            return await existing_user_session(settings(), client, ACTOR)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(execute())
    assert cloud.requests[-1].url.path == "/auth/v1/logout"


def test_rpc_validation_error_is_failed_denial_not_permission_success():
    cloud = SupabaseHTTP()
    cloud.fail_rpc = "cfin_claim_job"
    report = run(cloud)
    assert report["workspace_isolation_verified"] is False
    check = next(x for x in report["checks"] if x["name"].endswith("cfin_claim_job"))
    assert check == {
        "name": "service_rpc_denied_to_user:cfin_claim_job",
        "outcome": "failed",
        "http_status": 400,
    }


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, {"content": "leaked"}),
        (401, {"code": "InvalidJWT"}),
        (400, {"code": "InvalidRequest"}),
        (403, {"code": "InvalidJWT", "error": "Unauthorized"}),
    ],
)
def test_storage_leak_or_invalid_auth_request_is_not_a_pass(status, body):
    cloud = SupabaseHTTP()
    cloud.foreign_download = (status, body)
    report = run(cloud)
    check = next(
        x for x in report["checks"] if x["name"] == "foreign_private_evidence_download_denied"
    )
    assert check["outcome"] == "failed"


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (401, "42501", "permission denied for table cases"),
        (404, "PGRST202", "function does not exist"),
        (403, "42501", "permission denied for function claim_job"),
        (400, "22P02", "invalid input syntax"),
    ],
)
def test_only_exact_outer_object_permission_denial_counts(status, code, message):
    response = httpx.Response(status, json={"code": code, "message": message})
    assert not permission_denied(response, "function", "cfin_claim_job", authenticated=True)
