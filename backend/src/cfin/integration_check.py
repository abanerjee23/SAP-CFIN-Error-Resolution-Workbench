"""Live Supabase isolation checks. No model calls, human approvals or operational writes.

Run only against explicitly supplied, already seeded test UUIDs. Authentication
creates a real existing-user session without sending email; its refresh session is
signed out locally afterwards. Access JWTs retain the project's normal expiry.
Configuration is loaded only by main(), never when importing this module.
"""

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import SecretStr, ValidationError

from cfin.config import Settings
from cfin.gateway import ServiceGateway

OPERATIONAL_TABLES = (
    "cases",
    "attempts",
    "evidence_versions",
    "intakes",
    "analysis_runs",
    "jobs",
    "guidance_versions",
    "assignments",
    "case_reviews",
    "milestones",
    "milestone_proof",
    "resolution_records",
    "notifications",
    "activity",
    "reference_reviews",
    "run_sources",
    "run_results",
    "proof_applicability",
    "stage_calls",
)
TABLES = ("workspaces", "workspace_memberships", *OPERATIONAL_TABLES)

# Each payload fails before any write even if a wrapper's grant has regressed.
# Validation failure is NOT a passed access check: only exact outer-function
# permission denial counts. Keep these aligned with the applied migrations.
SERVICE_RPC_PROBES = {
    "commit_intake": {"workspace_id": "not-a-uuid"},
    "register_evidence": {"workspace_id": "not-a-uuid"},
    "claim_job": {"worker_id": ""},
    "heartbeat_job": {"job_id": "not-a-uuid", "lease_token": "not-a-uuid"},
    "reserve_call": {"job_id": "not-a-uuid", "lease_token": "not-a-uuid"},
    "reconcile_call": {"job_id": "not-a-uuid", "lease_token": "not-a-uuid"},
    "complete_run": {"succeeded": "not-a-boolean", "job_id": "not-a-uuid"},
}


class IntegrationCheckError(RuntimeError):
    """Only fixed, credential-free diagnostic messages may be raised here."""


@dataclass(frozen=True)
class TestSession:
    actor_id: UUID
    access_token: SecretStr = field(repr=False)


def public_headers(settings: Settings, session: TestSession | None = None) -> dict[str, str]:
    headers = {"apikey": settings.supabase_publishable_key.get_secret_value()}
    if session:
        headers["Authorization"] = "Bearer " + session.access_token.get_secret_value()
    return headers


def response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise IntegrationCheckError("Cloud returned an invalid JSON response") from exc


async def existing_user_session(
    settings: Settings, client: httpx.AsyncClient, actor_id: UUID
) -> TestSession:
    """Verify an existing confirmed account before generating its no-email token."""
    admin = ServiceGateway(settings, client).headers
    user_response = await client.get(
        settings.supabase_url + f"/auth/v1/admin/users/{actor_id}", headers=admin
    )
    if user_response.status_code != 200:
        raise IntegrationCheckError("The supplied existing Auth account could not be verified")
    user = response_json(user_response)
    if (
        not isinstance(user, dict)
        or user.get("id") != str(actor_id)
        or user.get("role") != "authenticated"
        or user.get("is_anonymous") is True
        or not isinstance(user.get("email"), str)
        or not user["email"]
        or not user.get("email_confirmed_at")
    ):
        raise IntegrationCheckError("An existing confirmed email account is required")
    generated = await client.post(
        settings.supabase_url + "/auth/v1/admin/generate_link",
        headers=admin,
        json={"type": "magiclink", "email": user["email"]},
    )
    if generated.status_code != 200:
        raise IntegrationCheckError("Test-session link generation failed; no email was requested")
    link = response_json(generated)
    if (
        not isinstance(link, dict)
        or link.get("id") != str(actor_id)
        or link.get("verification_type") != "magiclink"
        or not isinstance(link.get("hashed_token"), str)
        or not link["hashed_token"]
    ):
        raise IntegrationCheckError("Generated link did not match the existing test account")
    verified = await client.post(
        settings.supabase_url + "/auth/v1/verify",
        headers=public_headers(settings),
        json={"token_hash": link["hashed_token"], "type": "email"},
    )
    if verified.status_code != 200:
        raise IntegrationCheckError("The generated test-session token could not be verified")
    value = response_json(verified)
    if not isinstance(value, dict) or not isinstance(value.get("access_token"), str):
        raise IntegrationCheckError("Auth did not return a usable test session")
    session = TestSession(actor_id, SecretStr(value["access_token"]))
    try:
        actual = await client.get(
            settings.supabase_url + "/auth/v1/user", headers=public_headers(settings, session)
        )
        actual_user = response_json(actual) if actual.status_code == 200 else None
        if not isinstance(actual_user, dict) or actual_user.get("id") != str(actor_id):
            raise IntegrationCheckError("The signed-in user did not match the requested account")
    except (Exception, asyncio.CancelledError):
        await sign_out_local(settings, client, session)
        raise
    return session


async def sign_out_local(
    settings: Settings, client: httpx.AsyncClient, session: TestSession
) -> bool:
    response = await client.post(
        settings.supabase_url + "/auth/v1/logout",
        headers=public_headers(settings, session),
        params={"scope": "local"},
    )
    return response.status_code == 204


def permission_denied(
    response: httpx.Response, kind: str, name: str, *, authenticated: bool
) -> bool:
    statuses = {403} if authenticated else {401, 403}
    if response.status_code not in statuses:
        return False
    try:
        value = response.json()
    except ValueError:
        return False
    return (
        isinstance(value, dict)
        and value.get("code") == "42501"
        and value.get("message") == f"permission denied for {kind} {name}"
    )


def table_scope(table: str) -> str:
    return "id" if table == "workspaces" else "workspace_id"


async def run_checks(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    actor_id: UUID,
    workspace_id: UUID,
    foreign_workspace_id: UUID,
    case_id: UUID,
    foreign_case_id: UUID,
    evidence_id: UUID,
    foreign_evidence_id: UUID,
    nonmember_actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Use positive service-read controls, then probe real anon/user permissions."""
    if not settings.worker_configured:
        raise IntegrationCheckError("Server Supabase configuration is required")
    if (
        workspace_id == foreign_workspace_id
        or case_id == foreign_case_id
        or evidence_id == foreign_evidence_id
    ):
        raise IntegrationCheckError("Distinct seeded workspace and case UUIDs are required")
    service = ServiceGateway(settings, client)
    evidence_controls = []
    for workspace, case, evidence in (
        (workspace_id, case_id, evidence_id),
        (foreign_workspace_id, foreign_case_id, foreign_evidence_id),
    ):
        workspaces = await service.rows("workspaces", {"id": f"eq.{workspace}"})
        cases = await service.rows("cases", {"workspace_id": f"eq.{workspace}", "id": f"eq.{case}"})
        if len(workspaces) != 1 or len(cases) != 1:
            raise IntegrationCheckError("Both isolation workspaces and case controls must exist")
        attachments = await service.rows(
            "evidence_versions",
            {"workspace_id": f"eq.{workspace}", "case_id": f"eq.{case}", "id": f"eq.{evidence}"},
        )
        if len(attachments) != 1 or attachments[0].get("bucket_id") != "evidence":
            raise IntegrationCheckError("Both saved private evidence controls must exist")
        # Verifies actual stored bytes against the saved hash/size before a denial
        # can count; missing foreign objects are not evidence of isolation.
        await service.download(attachments[0])
        evidence_controls.append(attachments[0])
    memberships = await service.rows("workspace_memberships", {"user_id": f"eq.{actor_id}"})
    member_workspaces = {row["workspace_id"] for row in memberships}
    if str(workspace_id) not in member_workspaces or str(foreign_workspace_id) in member_workspaces:
        raise IntegrationCheckError(
            "The account must belong to the test workspace only of this pair"
        )
    if nonmember_actor_id:
        if nonmember_actor_id == actor_id or await service.rows(
            "workspace_memberships", {"user_id": f"eq.{nonmember_actor_id}"}
        ):
            raise IntegrationCheckError("The separate existing nonmember must have no memberships")

    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, response: httpx.Response | None = None) -> None:
        checks.append(
            {
                "name": name,
                "outcome": "passed" if passed else "failed",
                **({"http_status": response.status_code} if response is not None else {}),
            }
        )

    session = await existing_user_session(settings, client, actor_id)
    try:
        headers = public_headers(settings, session)
        for table in TABLES:
            path = settings.supabase_url + "/rest/v1/" + table
            column = table_scope(table)
            anonymous = await client.get(
                path,
                headers=public_headers(settings),
                params={"select": column, "limit": "1"},
            )
            record(
                f"anonymous_read_denied:{table}",
                permission_denied(anonymous, "table", table, authenticated=False),
                anonymous,
            )
            # Contradictory filters cannot match any row; no row trigger can run.
            updated = await client.patch(
                path,
                headers=headers,
                params={"and": f"({column}.eq.{workspace_id},{column}.neq.{workspace_id})"},
                json={column: str(workspace_id)},
            )
            record(
                f"direct_update_denied:{table}",
                permission_denied(updated, "table", table, authenticated=True),
                updated,
            )

        own = await client.get(
            settings.supabase_url + "/rest/v1/cases",
            headers=headers,
            params={"id": f"eq.{case_id}", "select": "id,workspace_id"},
        )
        record(
            "member_reads_seeded_case",
            own.status_code == 200
            and response_json(own) == [{"id": str(case_id), "workspace_id": str(workspace_id)}],
            own,
        )
        foreign = await client.get(
            settings.supabase_url + "/rest/v1/cases",
            headers=headers,
            params={"workspace_id": f"eq.{foreign_workspace_id}", "select": "id,workspace_id"},
        )
        record(
            "signed_in_foreign_workspace_nonmember_reads_no_cases",
            foreign.status_code == 200 and response_json(foreign) == [],
            foreign,
        )
        by_id = await client.get(
            settings.supabase_url + "/rest/v1/cases",
            headers=headers,
            params={"id": f"eq.{foreign_case_id}", "select": "id"},
        )
        record(
            "foreign_case_uuid_cannot_bypass_workspace_scope",
            by_id.status_code == 200 and response_json(by_id) == [],
            by_id,
        )
        workspaces = await client.get(
            settings.supabase_url + "/rest/v1/workspaces",
            headers=headers,
            params={"id": f"in.({workspace_id},{foreign_workspace_id})", "select": "id"},
        )
        record(
            "member_workspace_scope",
            workspaces.status_code == 200
            and response_json(workspaces) == [{"id": str(workspace_id)}],
            workspaces,
        )
        own_evidence, foreign_evidence = evidence_controls
        storage_base = settings.supabase_url + "/storage/v1/object/authenticated/evidence/"
        own_download = await client.get(
            storage_base + quote(own_evidence["object_path"], safe="/"), headers=headers
        )
        own_download_valid = (
            own_download.status_code == 200
            and len(own_download.content) == own_evidence["byte_size"]
            and hashlib.sha256(own_download.content).hexdigest() == own_evidence["sha256"]
        )
        record("member_downloads_verified_private_evidence", own_download_valid, own_download)
        foreign_download = await client.get(
            storage_base + quote(foreign_evidence["object_path"], safe="/"), headers=headers
        )
        try:
            storage_error = foreign_download.json()
        except ValueError:
            storage_error = None
        denied = (
            own_download_valid
            and foreign_download.status_code in (400, 403, 404)
            and isinstance(storage_error, dict)
            and (storage_error.get("code") or storage_error.get("error"))
            in ("NoSuchKey", "AccessDenied", "not_found", "unauthorized", "Unauthorized")
        )
        record("foreign_private_evidence_download_denied", denied, foreign_download)
        for name, payload in SERVICE_RPC_PROBES.items():
            wrapper = "cfin_" + name
            response = await client.post(
                settings.supabase_url + "/rest/v1/rpc/" + wrapper,
                headers=headers,
                json={"payload": payload},
            )
            record(
                f"service_rpc_denied_to_user:{wrapper}",
                permission_denied(response, "function", wrapper, authenticated=True),
                response,
            )

        if nonmember_actor_id:
            nonmember = await existing_user_session(settings, client, nonmember_actor_id)
            try:
                for table in ("workspaces", "cases", "workspace_memberships"):
                    response = await client.get(
                        settings.supabase_url + "/rest/v1/" + table,
                        headers=public_headers(settings, nonmember),
                        params={"select": table_scope(table), "limit": "1"},
                    )
                    record(
                        f"account_without_memberships_reads_no_rows:{table}",
                        response.status_code == 200 and response_json(response) == [],
                        response,
                    )
            finally:
                record(
                    "nonmember_test_session_signed_out_locally",
                    await sign_out_local(settings, client, nonmember),
                )
        else:
            checks.append(
                {
                    "name": "separate_account_without_any_memberships",
                    "outcome": "not_run",
                    "reason": "No separate existing nonmember Auth UUID was supplied; "
                    "none was created",
                }
            )
        checks.append(
            {
                "name": "direct_insert_privileges_via_sql_catalog",
                "outcome": "not_run",
                "reason": "Check authenticated INSERT grants with has_table_privilege in SQL; "
                "an empty REST insert does not prove denial",
            }
        )
    finally:
        record(
            "member_test_session_signed_out_locally",
            await sign_out_local(settings, client, session),
        )
    return {
        "live_isolation_verified": all(check["outcome"] == "passed" for check in checks),
        "workspace_isolation_verified": all(
            check["outcome"] == "passed" for check in checks if check["outcome"] != "not_run"
        ),
        "paid_model_calls": 0,
        "human_approvals": 0,
        "new_auth_users_requested": False,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", type=UUID, required=True)
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--foreign-workspace-id", type=UUID, required=True)
    parser.add_argument("--case-id", type=UUID, required=True)
    parser.add_argument("--foreign-case-id", type=UUID, required=True)
    parser.add_argument("--evidence-id", type=UUID, required=True)
    parser.add_argument("--foreign-evidence-id", type=UUID, required=True)
    parser.add_argument("--nonmember-actor-id", type=UUID)
    args = parser.parse_args()

    async def execute() -> dict[str, Any]:
        settings = Settings()
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            return await run_checks(settings, client, **vars(args))

    try:
        report = asyncio.run(execute())
    except (IntegrationCheckError, httpx.RequestError, ValidationError) as exc:
        # Never print SDK/cloud exception bodies, user details, configuration or headers.
        message = (
            str(exc) if isinstance(exc, IntegrationCheckError) else "Integration check aborted"
        )
        print(json.dumps({"live_isolation_verified": False, "error": message}))
        return 2
    except Exception:
        print(json.dumps({"live_isolation_verified": False, "error": "Integration check aborted"}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["live_isolation_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
