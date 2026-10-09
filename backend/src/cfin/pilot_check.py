"""Exercise a saved, analysed synthetic case through authenticated HTTP commands.

This records fictional approval and SAP outcomes under an existing test account.
It does not establish human review, real SAP integration or model quality. Run only
against a synthetic workspace with the account's configured pilot roles.
"""

import argparse
import asyncio
import base64
import hashlib
import json
from pathlib import Path
from uuid import UUID

import httpx

from cfin.config import Settings
from cfin.integration_check import existing_user_session


async def check(api_url: str, workspace_id: UUID, actor_id: UUID, case_id: UUID) -> dict:
    async with httpx.AsyncClient(timeout=45) as client:
        session = await existing_user_session(Settings(), client, actor_id)
        headers = {"Authorization": "Bearer " + session.access_token.get_secret_value()}
        base = api_url.rstrip("/")

        async def request(method, path, *, body=None, expected=200):
            response = await client.request(method, base + path, headers=headers, json=body)
            if response.status_code != expected:
                raise RuntimeError(
                    f"{method} {path.split('?')[0]}: expected {expected}, "
                    f"received {response.status_code}: {response.text[:300]}"
                )
            return response.json() if expected == 200 else None

        workspaces = await request("GET", "/api/workspaces")
        workspace = next(w for w in workspaces if w["id"] == str(workspace_id))
        if workspace.get("synthetic") is not True:
            raise RuntimeError("This harness requires an explicitly synthetic workspace")
        required = {"process_owner", "mdg_process_owner", "data_operations"}
        if not required <= set(workspace["roles"]):
            raise RuntimeError("Assign the pilot roles to the synthetic test account first")
        path = f"/api/cases/{case_id}"
        query = f"?workspace_id={workspace_id}"
        detail = await request("GET", path + query)
        case = detail["case"]
        result = case.get("error_analysis_result") or {}
        if (
            case.get("workflow_version") != "error-analysis-v1"
            or case.get("analysis_status") != "available"
            or case.get("route_state") != "not_started"
            or result.get("analysis", {}).get("category_id") != "master_data"
        ):
            raise RuntimeError("Use a newly analysed synthetic master-data case with no route work")
        originals = [e for e in detail["evidence"] if e["kind"] == "original_log"]
        for original in originals:
            response = await client.get(
                base + f"/api/evidence/{original['id']}" + query, headers=headers
            )
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != original["sha256"]:
                raise RuntimeError("Original bytes changed")
        prefix = "AUTOMATED SYNTHETIC WALKTHROUGH — no real SAP action or human approval. "

        async def action(kind, role, payload, expected=200):
            nonlocal detail
            answer = await request(
                "POST",
                path + "/actions",
                body={
                    "workspace_id": str(workspace_id),
                    "expected_version": detail["case"]["version"],
                    "action": kind,
                    "acting_role": role,
                    "payload": payload,
                },
                expected=expected,
            )
            if expected == 200:
                detail = await request("GET", path + query)
            return answer

        async def proof(filename, note, role):
            saved = await request(
                "POST",
                path + "/evidence",
                body={
                    "workspace_id": str(workspace_id),
                    "acting_role": role,
                    "filename": filename,
                    "content_type": "text/plain",
                    "provenance": "synthetic",
                    "content_base64": base64.b64encode((prefix + note).encode()).decode(),
                },
            )
            return saved["id"]

        await action(
            "finish_resolution",
            "data_operations",
            {
                "note": prefix + "Premature closure probe",
                "posting_reference": "SYNTHETIC-001",
                "human_confirmed": True,
                "evidence_ids": [],
            },
            expected=422,
        )
        approval = await proof(
            "synthetic-approval.txt",
            "Fixture approval for account 0000410000 in company 2000. Test evidence only.",
            "process_owner",
        )
        implementation = await proof(
            "synthetic-implementation.txt",
            "Fixture account 0000410000 maintained in company 2000 after approval.",
            "mdg_process_owner",
        )
        posting = await proof(
            "synthetic-posting-validation.txt",
            "Posting SYNTHETIC-001: company "
            "2000, account 0000410000, GBP 1250.00, source 1900000421. "
            "All fixture values match the intended result.",
            "data_operations",
        )
        notes = [
            "Request fixture approval for account maintenance in target company 2000.",
            "Record fixture approval; synthetic approval evidence attached.",
            "Record fixture account maintenance after the saved approval.",
            "Attach fixture implementation evidence.",
            "Record fixture go-ahead to reprocess document 1900000421.",
            "Record fictional reprocessing in CFIN-DEMO.",
            "Record successful fictional posting SYNTHETIC-001.",
        ]
        for index, step in enumerate(result["analysis"]["route"]["steps"]):
            payload = {
                "note": prefix + notes[index],
                "evidence_ids": [
                    approval if index <= 1 else implementation if index <= 4 else posting
                ],
            }
            if index == 1:
                await action("record_route_step", step["required_role"], payload, expected=422)
                payload["decision"] = "approved"
            if index == 6:
                payload.update(decision="completed", posting_reference="SYNTHETIC-001")
            await action("record_route_step", step["required_role"], payload)
        await action(
            "finish_resolution",
            "data_operations",
            {
                "note": prefix
                + "Validated fixture amount, currency, company, account and references.",
                "posting_reference": "SYNTHETIC-001",
                "human_confirmed": True,
                "evidence_ids": [posting],
            },
        )
        # A fresh authenticated read proves durable closure, not frontend state.
        reloaded = await request("GET", path + query)
        assert reloaded["case"]["status"] == "complete"
        assert len(reloaded["route_milestones"]) == 7
        assert len(reloaded["resolution_records"]) == 1
        report = {
            "case_id": str(case_id),
            "workspace_id": str(workspace_id),
            "original_hashes_verified": len(originals),
            "route_steps": 7,
            "saved_resolution_records": 1,
            "status_after_fresh_read": "complete",
            "negative_checks": ["premature closure rejected", "missing approval decision rejected"],
            "analysis": {
                key: result.get(key)
                for key in ("latency_ms", "cost_usd", "usage", "usage_complete", "stage_reuses")
            },
            "limitations": [
                "Synthetic SAP outcomes",
                "Automated test decisions under one test account",
                "Not a human quality review or multi-user acceptance test",
            ],
        }
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8011")
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--actor-id", type=UUID, required=True)
    parser.add_argument("--case-id", type=UUID, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(check(args.api_url, args.workspace_id, args.actor_id, args.case_id))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
