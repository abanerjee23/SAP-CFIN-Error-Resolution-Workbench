"""Offline acceptance-runner lifecycle checks; these are not cloud evidence."""

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid5

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import SecretStr

from cfin import factual_live_check as check
from cfin.config import Settings
from cfin.integration_check import TestSession as Session

WORKSPACE = UUID("22222222-2222-4222-8222-222222222222")
ACTOR = UUID("11111111-1111-4111-8111-111111111111")
PORTAL = "private-portal-session"


class Harness:
    def __init__(self):
        self.intakes, self.runs, self.credentials, self.events = {}, {}, {}, []
        self.migration_ready = True
        self.fail_reads = False
        self.fail_revoke = False
        self.cancel_reads = False
        self.cancel_first_revoke = False
        self.corrupt_download = False
        self.legacy_changed = False
        self.evaluation_changes_case = False
        self.snapshots = 0
        self.settings = Settings.model_construct(
            supabase_url="https://synthetic.supabase.co",
            supabase_publishable_key=SecretStr("publishable-test"),
            supabase_secret_key=SecretStr("sb_secret_private-test"),
            openai_api_key=SecretStr("private-openai-test"),
            paid_models_enabled=True,  # The default run must override this.
        )

    async def rows(self, table, filters):
        self.events.append(("rows", table))
        if table == "workspaces":
            return [{"id": str(WORKSPACE), "synthetic": True}]
        if table == "workspace_memberships":
            assert filters["user_id"] == f"eq.{ACTOR}"
            return [{"roles": ["process_owner"]}]
        if "select" in filters:
            if not self.migration_ready:
                raise RuntimeError("database error could contain a secret")
            return []
        if table == "cases":
            if filters.get("workflow_version") == "eq.log-only-v1":
                identifiers = filters["id"][4:-1].split(",")
                return [
                    {
                        "id": identifier,
                        "version": 2
                        if self.evaluation_changes_case
                        and any(
                            run["case_id"] == identifier
                            and run["evaluation_only"]
                            and run["state"] == "succeeded"
                            for run in self.runs.values()
                        )
                        else 1,
                        "published_run_id": next(
                            run["id"]
                            for run in self.runs.values()
                            if run["case_id"] == identifier and not run["evaluation_only"]
                        ),
                    }
                    for identifier in sorted(identifiers)
                ]
            self.snapshots += 1
            return [
                {
                    "id": "legacy-case",
                    "version": 2 if self.legacy_changed and self.snapshots > 1 else 1,
                }
            ]
        if table == "analysis_runs":
            if "case_id" in filters:
                return [
                    run
                    for run in self.runs.values()
                    if "eq." + run["case_id"] == filters["case_id"] and not run["evaluation_only"]
                ]
            return [self.runs[filters["id"][3:]]]
        if table == "stage_calls":
            run = self.runs[filters["run_id"][3:]]
            return (
                []
                if run.get("empty") or run["state"] == "queued"
                else [
                    {
                        "id": "call",
                        "usage": {"input_tokens": 42, "output_tokens": 24},
                        "actual_usd": "0.001",
                        "state": "succeeded",
                    }
                ]
            )
        return []

    async def sign_in(self, settings, client, actor):
        self.events.append(("session", "create"))
        return Session(actor, SecretStr(PORTAL))

    async def sign_out(self, settings, client, session):
        self.events.append(("session", "logout"))
        return True

    async def process(self, service, settings, worker_id, *, target_run_id):
        assert settings.paid_models_enabled and settings.log_only_enabled
        self.events.append(("dispatch", target_run_id))
        run = self.runs[target_run_id]
        run["state"] = "failed" if run.get("empty") else "succeeded"
        run["output"] = {
            "outcome": "no_usable_evidence" if run.get("empty") else "completed",
            "summary": None,
        }
        return {"claimed": True, "run_id": target_run_id, "arize": {"status": "disabled"}}

    def app(self, settings, transport=None):
        self.ephemeral = settings
        app = FastAPI()

        @app.api_route("/{path:path}", methods=["POST", "GET"])
        async def route(request: Request, path):
            path = "/" + path
            self.events.append(("http", path))
            if path == "/api/intakes/log-only":
                body = await request.json()
                raw = base64.b64decode(body["sources"][0]["content_base64"])
                try:
                    raw.decode("utf-8")
                except UnicodeError:
                    return JSONResponse({"detail": "invalid"}, 422)
                key = body["delivery_key"]
                if key in self.intakes:
                    return {**self.intakes[key]["receipt"], "duplicate": True}
                case_id = str(uuid5(WORKSPACE, key))
                run_id = str(uuid5(WORKSPACE, "run:" + key))
                receipt = {
                    "case_id": case_id,
                    "attempt_id": case_id,
                    "intake_id": case_id,
                    "duplicate": False,
                }
                self.intakes[key] = {"receipt": receipt, "raw": raw}
                self.runs[run_id] = {
                    "id": run_id,
                    "case_id": case_id,
                    "workflow_version": "log-only-v1",
                    "evaluation_only": False,
                    "state": "queued",
                    "empty": not raw,
                    "snapshot": {
                        "source_manifest": {
                            "sources": [{"source_id": case_id, "source_version": "1"}]
                        }
                    },
                }
                return receipt
            if path.endswith("/read-credentials"):
                body = await request.json()
                assert body["expires_in_days"] == 1
                identifier = str(uuid5(WORKSPACE, str(len(self.credentials))))
                token = "cfin_read_" + ("a" if not self.credentials else "b") * 43
                credential = {
                    "credential_id": identifier,
                    "read_token": token,
                    "scopes": body["scopes"],
                    "expires_at": "2026-10-03T00:00:00Z",
                }
                self.credentials[token] = credential
                return credential
            if path.endswith("/revoke"):
                if self.cancel_first_revoke:
                    self.cancel_first_revoke = False
                    raise asyncio.CancelledError
                if self.fail_revoke:
                    return JSONResponse({}, 503)
                credential_id = path.split("/")[-2]
                for credential in self.credentials.values():
                    if credential["credential_id"] == credential_id:
                        credential["revoked"] = True
                return {"revoked": True}
            if path == "/api/evaluations":
                body = await request.json()
                assert body["repeats"] == 1 and len(body["case_ids"]) <= 2
                run_ids = []
                for case_id in body["case_ids"]:
                    original = next(run for run in self.runs.values() if run["case_id"] == case_id)
                    run_id = str(uuid5(WORKSPACE, "eval:" + case_id))
                    self.runs[run_id] = {
                        **original,
                        "id": run_id,
                        "evaluation_only": True,
                        "state": "queued",
                    }
                    run_ids.append(run_id)
                return {"batch": {"id": "batch"}, "run_ids": run_ids}
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if token not in self.credentials:
                return JSONResponse({}, 401)
            credential = self.credentials[token]
            if credential.get("revoked") or request.query_params["workspace_id"] != str(WORKSPACE):
                return JSONResponse({}, 403)
            if self.cancel_reads:
                raise asyncio.CancelledError
            if self.fail_reads:
                return JSONResponse({"error": PORTAL}, 500)
            if "/sources/" in path and "evidence:read" not in credential["scopes"]:
                return JSONResponse({}, 403)
            if path == "/api/v1/cases":
                items = [{"case_id": row["receipt"]["case_id"]} for row in self.intakes.values()]
                offset = int(request.query_params.get("cursor", 0))
                return {
                    "items": items[offset : offset + 1],
                    "total": len(items),
                    "next_cursor": str(offset + 1) if offset + 1 < len(items) else None,
                }
            case_id = path.split("/")[4]
            if request.query_params.get("case_version", "1") != "1":
                return JSONResponse({}, 409)
            raw = next(
                row["raw"] for row in self.intakes.values() if row["receipt"]["case_id"] == case_id
            )
            if path.endswith(("/extraction", "/selected-evidence")):
                return JSONResponse({}, 409)
            if path.endswith(("/activity", "/records")):
                return {"items": [], "total": 0, "next_cursor": None}
            if path.endswith("/download"):
                return Response(raw + b"changed" if self.corrupt_download else raw)
            if "/sources/" in path:
                return {"text": raw.decode(), "sha256": hashlib.sha256(raw).hexdigest()}
            return {
                "case_id": case_id,
                "case_version": 1,
                "result": None,
                "sources": [
                    {
                        "source_id": case_id,
                        "source_version": "1",
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ],
            }

        return app

    def install(self, monkeypatch):
        monkeypatch.setattr(check, "ServiceGateway", lambda settings, client: self)
        monkeypatch.setattr(check, "existing_user_session", self.sign_in)
        monkeypatch.setattr(check, "sign_out_local", self.sign_out)
        monkeypatch.setattr(check, "create_app", self.app)
        monkeypatch.setattr(check, "process_one", self.process)
        monkeypatch.setattr(
            check,
            "prepare_factual_run_evaluation",
            lambda *args, **kwargs: SimpleNamespace(report=lambda: {"local_checks_passed": True}),
        )
        monkeypatch.setattr(
            check, "factual_human_review_packet", lambda *args: {"human_review_status": "pending"}
        )

    def run(self, **kwargs):
        async def execute():
            async with httpx.AsyncClient() as client:
                return await check.run_checks(
                    self.settings,
                    client,
                    workspace_id=WORKSPACE,
                    actor_id=ACTOR,
                    delivery_prefix="offline-test",
                    **kwargs,
                )

        return asyncio.run(execute())


def test_default_never_dispatches_even_when_environment_enables_paid_models(monkeypatch):
    harness = Harness()
    harness.install(monkeypatch)
    report = harness.run()
    assert report["structural_pass"], report
    assert not harness.ephemeral.paid_models_enabled
    assert harness.settings.paid_models_enabled
    assert not any(event[0] == "dispatch" for event in harness.events)
    assert len(harness.intakes) == 3
    assert all(row["revoked"] for row in harness.credentials.values())
    assert report["cleanup"]["session_signed_out"]
    assert report["quality_baseline_established"] is False
    encoded = json.dumps(report)
    for secret in (PORTAL, "cfin_read_", "private-openai-test", "sb_secret_private-test"):
        assert secret not in encoded


def test_preflight_failure_happens_before_auth_or_any_writes(monkeypatch):
    harness = Harness()
    harness.migration_ready = False
    harness.install(monkeypatch)
    report = harness.run()
    assert not report["structural_pass"]
    assert all(event[0] == "rows" for event in harness.events)
    assert report["error"] == "cloud_acceptance_failed"


def test_read_failure_still_revokes_every_credential_and_signs_out(monkeypatch):
    harness = Harness()
    harness.fail_reads = True
    harness.install(monkeypatch)
    report = harness.run()
    assert not report["structural_pass"]
    assert report["cleanup"] == {"credentials_revoked": True, "session_signed_out": True}
    assert len(harness.credentials) == 2
    assert all(row["revoked"] for row in harness.credentials.values())
    assert PORTAL not in json.dumps(report)


def test_paid_opt_in_targets_only_own_runs_and_bounded_eval_clones(monkeypatch):
    harness = Harness()
    harness.install(monkeypatch)
    report = harness.run(with_models=True)
    assert report["structural_pass"], report
    dispatched = [event[1] for event in harness.events if event[0] == "dispatch"]
    assert len(dispatched) == 5 and set(dispatched) == set(harness.runs)
    assert sum(run["evaluation_only"] for run in harness.runs.values()) == 2
    assert report["human_review_packet"]["human_review_status"] == "pending"
    assert report["quality_baseline_established"] is False
    assert report["factual_before_evaluation"] == report["factual_after_evaluation"]
    assert report["factual_before_evaluation"]["row_count"] == 2
    assert (
        next(row for row in report["runs"] if row["usage"])["usage"][0]["usage"]["input_tokens"]
        == 42
    )


def test_evaluation_clones_cannot_change_operational_factual_case_rows(monkeypatch):
    harness = Harness()
    harness.evaluation_changes_case = True
    harness.install(monkeypatch)
    report = harness.run(with_models=True)
    assert not report["structural_pass"]
    assert report["error"] == "factual_case_rows_unchanged_by_evaluation"
    assert (
        report["factual_before_evaluation"]["sha256"]
        != report["factual_after_evaluation"]["sha256"]
    )
    assert set(report["factual_before_evaluation"]) == {"row_count", "sha256"}
    assert all(report["cleanup"].values())


def test_changed_legacy_case_fails_even_if_all_http_checks_pass(monkeypatch):
    harness = Harness()
    harness.legacy_changed = True
    harness.install(monkeypatch)
    report = harness.run()
    assert not report["structural_pass"]
    assert report["checks"][-1] == {"check": "legacy_case_rows_unchanged", "passed": False}


@pytest.mark.parametrize(
    "fixtures",
    [
        (),
        ("md01-original",) * 2,
        tuple(check.FIXTURES) + ("md01-original",),
        ("../expected-answers",),
    ],
)
def test_fixture_scope_is_strictly_bounded(fixtures):
    with pytest.raises(check.AcceptanceFailure):
        check.selected_originals(fixtures)


def test_real_authored_inputs_are_exact_and_no_sidecars_are_loaded(monkeypatch):
    paths = []
    original = check.Path.read_bytes

    def read(path):
        paths.append(str(path))
        return original(path)

    monkeypatch.setattr(check.Path, "read_bytes", read)
    sources = check.selected_originals(tuple(check.FIXTURES))
    assert len(paths) == 2
    assert all(path.endswith("/agent-visible/original-log.txt") for path in paths)
    assert sources["empty-original"] == b""


def test_redaction_is_recursive_and_strips_token_fields():
    assert check.redact(
        {"read_token": "secret", "items": [{"text": "prefix secret", "access_token": "hidden"}]},
        ["secret"],
    ) == {"items": [{"text": "prefix [redacted]"}]}


def test_credential_cleanup_failure_is_visible_and_session_still_signs_out(monkeypatch):
    harness = Harness()
    harness.fail_revoke = True
    harness.install(monkeypatch)
    report = harness.run()
    assert not report["structural_pass"]
    assert report["cleanup"] == {"credentials_revoked": False, "session_signed_out": True}
    assert len(report["credentials"]) == 2


def test_corrupt_download_fails_exact_original_check_and_still_cleans_up(monkeypatch):
    harness = Harness()
    harness.corrupt_download = True
    harness.install(monkeypatch)
    report = harness.run()
    assert not report["structural_pass"]
    assert report["error"] == "exact_original_json_and_download"
    assert all(report["cleanup"].values())


@pytest.mark.parametrize("phase", ["read", "revoke"])
def test_cancellation_retains_private_report_and_continues_remaining_cleanup(monkeypatch, phase):
    harness = Harness()
    harness.cancel_reads = phase == "read"
    harness.cancel_first_revoke = phase == "revoke"
    harness.install(monkeypatch)
    report = harness.run()
    assert not report["structural_pass"]
    assert report["error"] == "acceptance_cancelled"
    assert report["cleanup"]["session_signed_out"]
    assert len(report["credentials"]) == 2
    assert report["cleanup"]["credentials_revoked"] is (phase == "read")
    assert sum(bool(row.get("revoked")) for row in harness.credentials.values()) == (
        2 if phase == "read" else 1
    )
    assert PORTAL not in json.dumps(report) and "cfin_read_" not in json.dumps(report)
