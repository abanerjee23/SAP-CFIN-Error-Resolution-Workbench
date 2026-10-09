"""Seed the unchanged synthetic intake and private foreign isolation controls.

No model calls or human workflow decisions. Uses one already-existing confirmed
demo account, creates a temporary no-email session and signs that session out.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from cfin.config import Settings
from cfin.gateway import ServiceGateway, checked_response
from cfin.integration_check import existing_user_session, sign_out_local


async def seed(actor_id: UUID, workspace_id: UUID) -> dict:
    settings = Settings()
    if settings.paid_models_enabled:
        raise ValueError("Disable paid model calls before preparing isolation controls")
    async with httpx.AsyncClient(timeout=40) as client:
        service = ServiceGateway(settings, client)
        memberships = await service.rows(
            "workspace_memberships",
            {"user_id": f"eq.{actor_id}", "workspace_id": f"eq.{workspace_id}"},
        )
        if len(memberships) != 1 or "process_owner" not in memberships[0]["roles"]:
            raise ValueError("An existing process-owner membership is required")
        session = await existing_user_session(settings, client, actor_id)
        try:
            headers = {"Authorization": "Bearer " + session.access_token.get_secret_value()}
            scenario = await client.get(
                "http://127.0.0.1:8000/api/scenarios/MD-01",
                headers=headers,
                params={"workspace_id": str(workspace_id)},
            )
            body = await checked_response(scenario)
            intake = await client.post(
                "http://127.0.0.1:8000/api/intakes",
                headers=headers,
                json={
                    "workspace_id": str(workspace_id),
                    "acting_role": "process_owner",
                    "delivery_key": "MD01-live-baseline-2026-10-01",
                    "manifest": {
                        **body["manifest"],
                        "delivery_key": "MD01-live-baseline-2026-10-01",
                    },
                    "original_log": body["original_log"],
                },
            )
            own = await checked_response(intake)
        finally:
            if not await sign_out_local(settings, client, session):
                raise ValueError("Temporary test session logout failed")

        foreign_workspace = uuid5(NAMESPACE_URL, "cfin:synthetic:isolation:workspace:2026-10-01")
        foreign_case = uuid5(NAMESPACE_URL, "cfin:synthetic:isolation:case:2026-10-01")
        for table, record in (
            (
                "workspaces",
                {
                    "id": str(foreign_workspace),
                    "name": "Synthetic isolation control",
                    "synthetic": True,
                },
            ),
            (
                "cases",
                {
                    "id": str(foreign_case),
                    "workspace_id": str(foreign_workspace),
                    "title": "Synthetic private access control",
                    "description": "Test data only; no SAP or human workflow.",
                    "due_at": "2026-10-05T16:00:00+00:00",
                },
            ),
        ):
            saved = await service.rows(table, {"id": f"eq.{record['id']}"})
            if saved:
                if len(saved) != 1 or any(saved[0].get(k) != v for k, v in record.items()):
                    raise ValueError(
                        "Existing isolation control differs from the expected synthetic row"
                    )
            else:
                await checked_response(
                    await client.post(
                        settings.supabase_url + "/rest/v1/" + table,
                        headers={**service.headers, "Prefer": "return=representation"},
                        json=record,
                    )
                )
        if await service.rows("workspace_memberships", {"workspace_id": f"eq.{foreign_workspace}"}):
            raise ValueError("The foreign isolation control must have no memberships")
        saved = await service.rows(
            "evidence_versions",
            {
                "workspace_id": f"eq.{foreign_workspace}",
                "source_id": "eq.ISOLATION-PROBE",
                "source_version": "eq.1",
            },
        )
        if not saved:
            storage = await service.store(
                foreign_workspace,
                b"Synthetic isolation probe. No business data.\n",
                "isolation.txt",
                "text/plain",
            )
            saved = await checked_response(
                await client.post(
                    settings.supabase_url + "/rest/v1/evidence_versions",
                    headers={**service.headers, "Prefer": "return=representation"},
                    json={
                        **storage,
                        "workspace_id": str(foreign_workspace),
                        "case_id": str(foreign_case),
                        "source_id": "ISOLATION-PROBE",
                        "source_version": "1",
                        "kind": "reference",
                        "provenance": {
                            "synthetic": True,
                            "description": "Private storage isolation control",
                        },
                        "uploader_id": str(actor_id),
                        "observed_at": datetime.now(UTC).isoformat(),
                    },
                )
            )
        if (
            len(saved) != 1
            or saved[0]["case_id"] != str(foreign_case)
            or saved[0]["filename"] != "isolation.txt"
            or saved[0]["kind"] != "reference"
            or await service.download(saved[0]) != b"Synthetic isolation probe. No business data.\n"
        ):
            raise ValueError("Foreign evidence control could not be verified")
        own_evidence = await service.rows(
            "evidence_versions",
            {
                "workspace_id": f"eq.{workspace_id}",
                "case_id": f"eq.{own['case_id']}",
                "kind": "eq.original_log",
            },
        )
        if len(own_evidence) != 1:
            raise ValueError("Exactly one saved original log is required")
        return {
            "actor_id": str(actor_id),
            "workspace_id": str(workspace_id),
            "case_id": own["case_id"],
            "evidence_id": own_evidence[0]["id"],
            "foreign_workspace_id": str(foreign_workspace),
            "foreign_case_id": str(foreign_case),
            "foreign_evidence_id": saved[0]["id"],
            "intake": own,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--workspace-id", required=True, type=UUID)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(seed(args.actor_id, args.workspace_id)), indent=2))


if __name__ == "__main__":
    main()
