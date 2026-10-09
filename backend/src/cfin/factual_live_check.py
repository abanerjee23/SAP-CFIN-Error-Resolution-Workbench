"""Explicit synthetic cloud acceptance; importing this module performs no I/O.

The HTTP surface runs in-process against real Auth, Postgres and Storage. This
does not verify a hosted proxy/TLS deployment, semantic model quality, or human
approval. Only main() loads settings. No email is sent and credentials never
belong in the report.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import httpx

from cfin.config import Settings
from cfin.factual_evaluation import (
    factual_human_review_packet,
    factual_review_checklist,
    prepare_factual_run_evaluation,
)
from cfin.gateway import ServiceGateway
from cfin.integration_check import existing_user_session, sign_out_local
from cfin.main import create_app
from cfin.worker import process_one

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = {
    "md01-original": ("MD-01", "e71f15f124bef24fd09a02e1d2c2b952733e7d979716f5a431a1f1277c244af4"),
    "map01-original": (
        "MAP-01",
        "49436112fd8f71af65c0dfb36f3ba417a4e138307ba4353d62dc2f555400e29b",
    ),
}
PREFLIGHT_FIELDS = {
    "cases": "id,workflow_version,factual_result,source_manifest,factual_review_status",
    "analysis_runs": "id,workflow_version,excluded_case_ids,evaluation_configuration",
    "intake_sources": "intake_id,ordinal",
}


class AcceptanceFailure(RuntimeError):
    """Only fixed, non-secret check names are used as messages."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def selected_originals(fixtures: tuple[str, ...], root: Path = ROOT) -> dict[str, bytes]:
    if not 1 <= len(fixtures) <= 2 or len(set(fixtures)) != len(fixtures):
        raise AcceptanceFailure("select_one_or_two_unique_originals")
    originals = {}
    for label in fixtures:
        if label not in FIXTURES:
            raise AcceptanceFailure("fixture_not_allowlisted")
        scenario, expected_hash = FIXTURES[label]
        relative = Path("fixtures") / scenario / "agent-visible" / "original-log.txt"
        if any((root / component).is_symlink() for component in (relative, *relative.parents)):
            raise AcceptanceFailure("fixture_symlink_rejected")
        raw = (root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise AcceptanceFailure("fixture_hash_changed")
        originals[label] = raw
    return {**originals, "empty-original": b""}


async def bounded_rows(service, table: str, filters: dict[str, str]) -> list[dict]:
    rows = []
    while len(rows) <= 1000:
        page = await service.rows(table, {**filters, "offset": str(len(rows)), "limit": "100"})
        rows.extend(page)
        if len(rows) > 1000:
            raise AcceptanceFailure("cloud_check_scope_exceeds_1000_rows")
        if len(page) < 100:
            return rows
    raise AcceptanceFailure("cloud_check_scope_exceeds_1000_rows")


async def preflight(service, workspace_id: UUID, actor_id: UUID) -> None:
    workspace = await service.rows(
        "workspaces", {"id": f"eq.{workspace_id}", "select": "id,synthetic"}
    )
    if len(workspace) != 1 or workspace[0].get("synthetic") is not True:
        raise AcceptanceFailure("explicit_synthetic_workspace_required")
    membership = await service.rows(
        "workspace_memberships",
        {
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{actor_id}",
        },
    )
    if not any("process_owner" in row.get("roles", []) for row in membership):
        raise AcceptanceFailure("existing_process_owner_membership_required")
    for table, fields in PREFLIGHT_FIELDS.items():
        await service.rows(table, {"select": fields, "limit": "1"})


async def legacy_snapshot(service, workspace_id: UUID) -> dict:
    rows = await bounded_rows(
        service,
        "cases",
        {
            "workspace_id": f"eq.{workspace_id}",
            "workflow_version": "eq.legacy-v1",
            "order": "id",
        },
    )
    # Hash complete saved case rows. Never publish their contents in this report.
    return {"row_count": len(rows), "sha256": digest(rows), "scope": "complete legacy case rows"}


async def factual_snapshot(service, workspace_id: UUID, case_ids: list[str]) -> dict:
    identifiers = sorted({str(UUID(value)) for value in case_ids})
    if not 1 <= len(identifiers) <= 2 or len(identifiers) != len(case_ids):
        raise AcceptanceFailure("factual_case_snapshot_scope")
    rows = await bounded_rows(
        service,
        "cases",
        {
            "workspace_id": f"eq.{workspace_id}",
            "workflow_version": "eq.log-only-v1",
            "id": "in.(" + ",".join(identifiers) + ")",
            "order": "id",
        },
    )
    if sorted(row["id"] for row in rows) != identifiers:
        raise AcceptanceFailure("factual_case_snapshot_scope")
    return {"row_count": len(rows), "sha256": digest(rows)}


def redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return re.sub(r"cfin_read_[A-Za-z0-9_-]{43}", "[redacted]", value)
    if isinstance(value, dict):
        return {
            key: redact(item, secrets)
            for key, item in value.items()
            if key not in {"access_token", "refresh_token", "read_token", "authorization"}
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    return value


async def api_json(api, method, path, *, expected=200, **kwargs):
    response = await api.request(method, path, **kwargs)
    if response.status_code != expected:
        raise AcceptanceFailure("http_contract_unexpected_status")
    return response.json()


def record(report, name: str, passed: bool, **details):
    report["checks"].append({"check": name, "passed": passed, **details})
    if not passed:
        raise AcceptanceFailure(name)


async def pages(api, path, headers, params):
    items, cursor, cursors = [], None, set()
    for _ in range(1001):
        page = await api_json(
            api,
            "GET",
            path,
            headers=headers,
            params={**params, "limit": 1, **({"cursor": cursor} if cursor else {})},
        )
        items.extend(page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            if len(items) != page["total"]:
                raise AcceptanceFailure("pagination_total_mismatch")
            return items
        if cursor in cursors:
            raise AcceptanceFailure("pagination_cursor_repeated")
        cursors.add(cursor)
    raise AcceptanceFailure("pagination_bound_exceeded")


async def inspect_case(api, report, workspace_id, receipt, original, headers):
    case_id = receipt["case_id"]
    path = f"/api/v1/cases/{case_id}"
    base = {"workspace_id": str(workspace_id)}
    saved = await api_json(api, "GET", path, headers=headers, params=base)
    version = saved["case_version"]
    params = {**base, "case_version": version}
    await api_json(
        api,
        "GET",
        path,
        expected=409,
        headers=headers,
        params={**base, "case_version": version + 1},
    )
    record(report, "version_fence", True, case_id=case_id)
    extracted = (saved.get("result") or {}).get("extraction")
    for endpoint in ("extraction", "selected-evidence", "activity", "records"):
        if endpoint in {"extraction", "selected-evidence"} and extracted is None:
            await api_json(
                api, "GET", path + "/" + endpoint, expected=409, headers=headers, params=params
            )
            record(report, endpoint + "_honest_unavailable", True, case_id=case_id)
        else:
            items = await pages(api, path + "/" + endpoint, headers, params)
            record(report, endpoint + "_paged", True, case_id=case_id, count=len(items))
    record(report, "one_complete_original", len(saved["sources"]) == 1, case_id=case_id)
    source = saved["sources"][0]
    source_path = path + "/sources/" + source["source_id"]
    source_params = {**params, "source_version": source["source_version"]}
    original_json = await api_json(api, "GET", source_path, headers=headers, params=source_params)
    response = await api.get(source_path + "/download", headers=headers, params=source_params)
    expected_hash = hashlib.sha256(original).hexdigest()
    record(
        report,
        "exact_original_json_and_download",
        response.status_code == 200
        and response.content == original
        and original_json["text"].encode("utf-8") == original
        and source["content_sha256"] == expected_hash
        and original_json["sha256"] == expected_hash,
        case_id=case_id,
        sha256=expected_hash,
    )
    # A caller with cases:read may still see quoted log contents in extraction.
    report["cases"].append(saved)
    return source_path, source_params


async def inspect_run(service, workspace_id, run_id: str) -> dict:
    runs = await service.rows(
        "analysis_runs", {"workspace_id": f"eq.{workspace_id}", "id": f"eq.{run_id}"}
    )
    if len(runs) != 1:
        raise AcceptanceFailure("exact_run_unavailable")
    calls = await bounded_rows(
        service,
        "stage_calls",
        {
            "workspace_id": f"eq.{workspace_id}",
            "run_id": f"eq.{run_id}",
            "order": "id",
        },
    )
    # Fixed usage fields: no prompts, request headers, reservations or tokens.
    run = runs[0]
    return {
        "run": run,
        "usage": [
            {
                key: row.get(key)
                for key in (
                    "id",
                    "stage",
                    "model_id",
                    "state",
                    "usage",
                    "actual_usd",
                    "reserved_usd",
                    "created_at",
                    "reconciled_at",
                )
            }
            for row in calls
        ],
    }


async def run_checks(
    settings: Settings,
    cloud_client: httpx.AsyncClient,
    *,
    workspace_id: UUID,
    actor_id: UUID,
    delivery_prefix: str,
    fixtures: tuple[str, ...] = tuple(FIXTURES),
    with_models: bool = False,
    transport=None,
) -> dict:
    """Create at most three synthetic intakes; optionally dispatch exactly five runs.

    The default queues saved work but never dispatches a model. Stop other workers
    before running: a separately running authorized worker can consume that queue.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", delivery_prefix):
        raise AcceptanceFailure("invalid_delivery_prefix")
    originals = selected_originals(fixtures)
    ephemeral = settings.model_copy(
        update={"log_only_enabled": True, "paid_models_enabled": with_models}
    )
    if not ephemeral.worker_configured or (with_models and not ephemeral.models_configured):
        raise AcceptanceFailure("required_cloud_or_model_configuration_missing")
    report = {
        "schema_version": "factual-cloud-acceptance-v1",
        "started_at": datetime.now(UTC).isoformat(),
        "workspace_id": str(workspace_id),
        "actor_id": str(actor_id),
        "delivery_prefix": delivery_prefix,
        "synthetic": True,
        "with_models": with_models,
        "maximum_paid_runs_this_invocation": 2 * len(fixtures) if with_models else 0,
        "run_budget_usd": str(ephemeral.model_run_budget_usd),
        "monthly_budget_usd": str(ephemeral.model_monthly_budget_usd),
        "hosted_https_verified": False,
        "quality_baseline_established": False,
        "human_review_status": "pending",
        "semantic_review": factual_review_checklist(),
        "checks": [],
        "cases": [],
        "runs": [],
        "receipts": [],
        "credentials": [],
        "cleanup": {"credentials_revoked": True, "session_signed_out": False},
        "limitations": [
            "In-process HTTP test over real cloud services; hosted TLS is untested.",
            "Software checks do not establish semantic accuracy or user value.",
            "Synthetic cases, queued jobs, evaluation records and access audits remain saved.",
        ],
    }
    service = ServiceGateway(ephemeral, cloud_client)
    session = None
    credentials = []
    before = None
    secrets = [
        value.get_secret_value()
        for value in (
            settings.supabase_secret_key,
            settings.supabase_publishable_key,
            settings.openai_api_key,
            settings.arize_api_key,
        )
    ]
    try:
        await preflight(service, workspace_id, actor_id)
        before = await legacy_snapshot(service, workspace_id)
        report["legacy_before"] = before
        record(report, "migration_and_synthetic_membership_preflight", True)
        session = await existing_user_session(ephemeral, cloud_client, actor_id)
        token = session.access_token.get_secret_value()
        secrets.append(token)
        portal = {"Authorization": "Bearer " + token}
        app = create_app(ephemeral, transport=transport)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://acceptance.local",
                timeout=60,
            ) as api,
        ):
            try:
                for label, raw in originals.items():
                    body = {
                        "workspace_id": str(workspace_id),
                        "delivery_key": delivery_prefix + ":" + label,
                        "provenance": "synthetic",
                        "acting_role": "process_owner",
                        "sources": [
                            {
                                "filename": "original-log.txt",
                                "content_base64": base64.b64encode(raw).decode(),
                            }
                        ],
                    }
                    receipt = await api_json(
                        api, "POST", "/api/intakes/log-only", headers=portal, json=body
                    )
                    duplicate = await api_json(
                        api, "POST", "/api/intakes/log-only", headers=portal, json=body
                    )
                    record(
                        report,
                        "idempotent_intake",
                        duplicate.get("duplicate") is True
                        and all(
                            receipt[key] == duplicate[key]
                            for key in ("case_id", "attempt_id", "intake_id")
                        ),
                        fixture=label,
                    )
                    receipt = {**receipt, "fixture": label, "delivery_key": body["delivery_key"]}
                    # Duplicate receipts omit run identity; read the saved run.
                    runs = await service.rows(
                        "analysis_runs",
                        {
                            "workspace_id": f"eq.{workspace_id}",
                            "case_id": "eq." + receipt["case_id"],
                            "evaluation_only": "eq.false",
                            "order": "created_at.desc",
                            "limit": "1",
                        },
                    )
                    record(
                        report,
                        "saved_factual_run",
                        len(runs) == 1 and runs[0]["workflow_version"] == "log-only-v1",
                    )
                    receipt["run_id"] = runs[0]["id"]
                    report["receipts"].append(receipt)
                jobs_filter = {"workspace_id": f"eq.{workspace_id}", "select": "id", "order": "id"}
                jobs_before = await bounded_rows(service, "jobs", jobs_filter)
                bad_key = delivery_prefix + ":invalid-utf8"
                body["delivery_key"] = bad_key
                body["sources"][0]["content_base64"] = base64.b64encode(b"\xff").decode()
                await api_json(
                    api, "POST", "/api/intakes/log-only", expected=422, headers=portal, json=body
                )
                invalid = await service.rows(
                    "intakes",
                    {"workspace_id": f"eq.{workspace_id}", "delivery_key": f"eq.{bad_key}"},
                )
                jobs_after = await bounded_rows(service, "jobs", jobs_filter)
                record(
                    report,
                    "invalid_utf8_no_intake_or_job",
                    not invalid and jobs_before == jobs_after,
                )

                if with_models:
                    for receipt in report["receipts"]:
                        await dispatch_exact(
                            service,
                            ephemeral,
                            report,
                            workspace_id,
                            receipt["run_id"],
                            evaluation_only=False,
                            empty=receipt["fixture"] == "empty-original",
                        )
                    evaluation_case_ids = [
                        row["case_id"]
                        for row in report["receipts"]
                        if row["fixture"] != "empty-original"
                    ]
                    factual_before = await factual_snapshot(
                        service, workspace_id, evaluation_case_ids
                    )
                    report["factual_before_evaluation"] = factual_before
                    evaluation = await api_json(
                        api,
                        "POST",
                        "/api/evaluations",
                        headers=portal,
                        json={
                            "workspace_id": str(workspace_id),
                            "case_ids": evaluation_case_ids,
                            "repeats": 1,
                            "reason": "Synthetic factual acceptance; semantic review pending",
                        },
                    )
                    record(
                        report,
                        "bounded_evaluation_clones",
                        len(evaluation["run_ids"]) == len(fixtures),
                    )
                    report["evaluation_batch_id"] = evaluation["batch"]["id"]
                    evaluation_runs = []
                    for run_id in evaluation["run_ids"]:
                        evaluation_runs.append(
                            await dispatch_exact(
                                service,
                                ephemeral,
                                report,
                                workspace_id,
                                run_id,
                                evaluation_only=True,
                            )
                        )
                    factual_after = await factual_snapshot(
                        service, workspace_id, evaluation_case_ids
                    )
                    report["factual_after_evaluation"] = factual_after
                    record(
                        report,
                        "factual_case_rows_unchanged_by_evaluation",
                        factual_before == factual_after,
                    )
                    by_case = {
                        row["case_id"]: originals[row["fixture"]] for row in report["receipts"]
                    }
                    originals_by_run = {
                        run["id"]: {
                            (source["source_id"], source["source_version"]): by_case[run["case_id"]]
                            for source in run["snapshot"]["source_manifest"]["sources"]
                        }
                        for run in evaluation_runs
                    }
                    prepared = prepare_factual_run_evaluation(
                        evaluation_runs, originals_by_run=originals_by_run
                    )
                    report["evaluation_checks"] = prepared.report()
                    record(
                        report,
                        "factual_evaluation_structural_checks",
                        prepared.report()["local_checks_passed"],
                    )
                    report["human_review_packet"] = factual_human_review_packet(
                        evaluation_runs, prepared
                    )

                for scopes in (["cases:read", "evidence:read"], ["cases:read"]):
                    credential = await api_json(
                        api,
                        "POST",
                        f"/api/workspaces/{workspace_id}/read-credentials",
                        headers=portal,
                        json={
                            "label": "Synthetic factual acceptance",
                            "scopes": scopes,
                            "expires_in_days": 1,
                        },
                    )
                    credentials.append(credential)
                    secrets.append(credential["read_token"])
                    report["credentials"].append(
                        {key: credential[key] for key in ("credential_id", "scopes", "expires_at")}
                    )
                machine = {"Authorization": "Bearer " + credentials[0]["read_token"]}
                listed = await pages(
                    api,
                    "/api/v1/cases",
                    machine,
                    {"workspace_id": str(workspace_id), "workflow_version": "log-only-v1"},
                )
                record(
                    report,
                    "snapshot_list_pagination",
                    {row["case_id"] for row in report["receipts"]}.issubset(
                        {row["case_id"] for row in listed}
                    ),
                )
                for receipt in report["receipts"]:
                    source_path, source_params = await inspect_case(
                        api, report, workspace_id, receipt, originals[receipt["fixture"]], machine
                    )
                await api_json(
                    api,
                    "GET",
                    source_path,
                    expected=403,
                    params=source_params,
                    headers={"Authorization": "Bearer " + credentials[1]["read_token"]},
                )
                record(report, "evidence_scope_denied", True)
                await api_json(
                    api,
                    "GET",
                    "/api/v1/cases",
                    expected=403,
                    headers=machine,
                    params={
                        "workspace_id": str(uuid5(workspace_id, "acceptance-foreign-workspace"))
                    },
                )
                await api_json(
                    api,
                    "GET",
                    "/api/v1/cases",
                    expected=401,
                    params={"workspace_id": str(workspace_id)},
                )
                record(report, "wrong_workspace_and_missing_auth_denied", True)
            finally:
                for credential in credentials:
                    try:
                        await api_json(
                            api,
                            "POST",
                            f"/api/workspaces/{workspace_id}/read-credentials/{credential['credential_id']}/revoke",
                            headers=portal,
                        )
                        await api_json(
                            api,
                            "GET",
                            "/api/v1/cases",
                            expected=403,
                            params={"workspace_id": str(workspace_id)},
                            headers={"Authorization": "Bearer " + credential["read_token"]},
                        )
                    except (Exception, asyncio.CancelledError) as exc:
                        report["cleanup"]["credentials_revoked"] = False
                        if isinstance(exc, asyncio.CancelledError):
                            report["error"] = "acceptance_cancelled"
    except (Exception, asyncio.CancelledError) as exc:
        report["error"] = (
            "acceptance_cancelled"
            if isinstance(exc, asyncio.CancelledError)
            else str(exc)
            if isinstance(exc, AcceptanceFailure)
            else "cloud_acceptance_failed"
        )
    finally:
        if session is not None:
            try:
                report["cleanup"]["session_signed_out"] = await sign_out_local(
                    ephemeral, cloud_client, session
                )
            except (Exception, asyncio.CancelledError) as exc:
                report["cleanup"]["session_signed_out"] = False
                if isinstance(exc, asyncio.CancelledError):
                    report["error"] = "acceptance_cancelled"
        if before is not None:
            try:
                after = await legacy_snapshot(service, workspace_id)
                report["legacy_after"] = after
                report["checks"].append(
                    {"check": "legacy_case_rows_unchanged", "passed": before == after}
                )
            except (Exception, asyncio.CancelledError) as exc:
                report["checks"].append({"check": "legacy_case_rows_unchanged", "passed": False})
                if isinstance(exc, asyncio.CancelledError):
                    report["error"] = "acceptance_cancelled"
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["structural_pass"] = bool(
        not report.get("error")
        and report["checks"]
        and all(row["passed"] for row in report["checks"])
        and all(report["cleanup"].values())
    )
    return redact(report, secrets)


async def dispatch_exact(
    service, settings, report, workspace_id, run_id, *, evaluation_only, empty=False
):
    dispatch_started = datetime.now(UTC).isoformat()
    before = await inspect_run(service, workspace_id, run_id)
    run = before["run"]
    record(
        report,
        "exact_run_scope",
        run["workflow_version"] == "log-only-v1" and run["evaluation_only"] is evaluation_only,
    )
    if run["state"] == "queued":
        outcome = await process_one(
            service, settings, "factual-acceptance-" + run_id, target_run_id=run_id
        )
        record(
            report,
            "targeted_run_claimed",
            outcome.get("claimed") is True and outcome.get("run_id") == run_id,
        )
    elif run["state"] in {"succeeded", "failed", "historical"}:
        outcome = {"reused_saved_run": True}
    else:
        raise AcceptanceFailure("target_run_busy")
    saved = await inspect_run(service, workspace_id, run_id)
    run = saved["run"]
    report["runs"].append(
        {
            "run_id": run_id,
            "case_id": run["case_id"],
            "state": run["state"],
            "evaluation_only": evaluation_only,
            "created_at": run.get("created_at"),
            "check_started_at": dispatch_started,
            "check_finished_at": datetime.now(UTC).isoformat(),
            "output": run.get("output"),
            "usage": saved["usage"],
            "dispatch": outcome,
        }
    )
    if empty:
        output = run.get("output") or {}
        record(
            report,
            "empty_input_no_paid_calls_or_fabricated_title",
            not saved["usage"]
            and output.get("outcome") == "no_usable_evidence"
            and output.get("summary") is None,
        )
    else:
        record(report, "saved_model_run_completed", run["state"] == "succeeded", run_id=run_id)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--delivery-prefix", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fixture", action="append", choices=tuple(FIXTURES))
    parser.add_argument(
        "--with-models",
        action="store_true",
        help="Authorize up to four paid runs plus one free empty-input check",
    )
    args = parser.parse_args()

    async def execute():
        async with httpx.AsyncClient(timeout=30) as client:
            return await run_checks(
                Settings(),
                client,
                workspace_id=args.workspace_id,
                actor_id=args.actor_id,
                delivery_prefix=args.delivery_prefix,
                fixtures=tuple(args.fixture or FIXTURES),
                with_models=args.with_models,
            )

    # Refuse overwrite; establish private report permissions before cloud writes.
    try:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            try:
                report = asyncio.run(execute())
            except Exception:
                report = {
                    "structural_pass": False,
                    "error": "acceptance_setup_failed",
                    "quality_baseline_established": False,
                    "human_review_status": "pending",
                }
            json.dump(report, output, indent=2)
            output.write("\n")
    except OSError:
        parser.exit(2, "Cannot create a new private report file.\n")
    print("Acceptance report saved; semantic review remains pending.")
    raise SystemExit(0 if report["structural_pass"] else 1)


if __name__ == "__main__":
    main()
