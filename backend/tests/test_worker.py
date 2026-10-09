"""Worker HTTP/SDK fakes verify dispatch boundaries, not live SQL or model quality."""

import asyncio
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from test_operations import JOB, LEASE, RUN, SECRET, CloudHTTP, test_settings

from cfin import fixture_loader, model_adapter, worker, workflow
from cfin.arize_tracing import ArizeTraceResult
from cfin.gateway import ServiceGateway
from cfin.worker import CloudCallLedger, process_one
from cfin.workflow import build_diagnosis, build_preparation


@pytest.fixture(autouse=True)
def fixed_workflow_clock(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 1)

    monkeypatch.setattr(workflow, "date", FixedDate)


def install_provider(monkeypatch, cloud, *, requests=1, error=None, automatic_tracing=False):
    """Stub only the paid SDK dispatch; use the real adapter, executor and cloud ledger."""
    clients = []
    payloads = []
    live_inputs = []

    class Client:
        closed = False

        async def close(self):
            self.closed = True

    def client_factory(**kwargs):
        assert kwargs["max_retries"] == 0
        client = Client()
        clients.append(client)
        return client

    class CapturingAdapter(model_adapter.OpenAIStageAdapter):
        async def execute(self, stage, payload, output_type, inputs):
            live_inputs.append(inputs)
            return await super().execute(stage, payload, output_type, inputs)

    async def sdk_run(agent, encoded, **kwargs):
        assert cloud.pending, "The provider must never run without a saved reservation"
        assert kwargs["max_turns"] == 1
        assert kwargs["run_config"].tracing_disabled is not automatic_tracing
        assert agent.tools == []
        payload = json.loads(encoded)
        payloads.append((agent.name, payload))
        for forbidden in ("routing-oracle", "simulated-proof", "0000900123", SECRET):
            assert forbidden not in encoded
        if error:
            raise error
        if agent.name == "agent1":
            result = build_preparation(live_inputs[-1], payload["run_id"])
        elif agent.name == "agent2":
            result = build_diagnosis(
                live_inputs[-1], payload["run_id"], date.fromisoformat(payload["as_of"])
            )
        else:
            pytest.fail("The unapproved MD-01 fixture must never dispatch Agent 3")
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(
                    requests=requests,
                    input_tokens=100 if requests else 0,
                    output_tokens=20 if requests else 0,
                )
            ),
            final_output=result.model_dump(mode="json"),
        )

    monkeypatch.setattr(model_adapter, "AsyncOpenAI", client_factory)
    monkeypatch.setattr(model_adapter.Runner, "run", sdk_run)
    monkeypatch.setattr(worker, "OpenAIStageAdapter", CapturingAdapter)
    return clients, payloads


def run_worker(cloud, *, settings=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cloud.handler)) as client:
            return await process_one(
                ServiceGateway(settings or test_settings(), client),
                settings or test_settings(),
                "http-fake-worker",
            )

    return asyncio.run(run())


def test_unconfigured_paid_execution_is_blocked_before_claim_or_storage(monkeypatch):
    cloud = CloudHTTP()
    install_provider(monkeypatch, cloud)
    with pytest.raises(RuntimeError, match="Configure model IDs"):
        run_worker(cloud, settings=test_settings(paid_models_enabled=False))
    assert cloud.requests == []


def test_empty_queue_does_not_create_an_adapter_or_model_call(monkeypatch):
    cloud = CloudHTTP()
    clients, payloads = install_provider(monkeypatch, cloud)
    assert run_worker(cloud) == {"claimed": False}
    assert not clients and not payloads and not cloud.reservations
    assert len(cloud.requests) == 1


def test_http_fake_worker_restores_saved_inputs_reserves_reconciles_and_skips_agent3(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    clients, payloads = install_provider(monkeypatch, cloud)
    monkeypatch.setattr(fixture_loader, "_read_files", lambda *a: pytest.fail("Local fallback"))
    result = run_worker(cloud)
    assert result["succeeded"] is True and result["run_id"] == str(RUN)
    assert [stage for stage, _ in payloads] == ["agent1", "agent2"]
    assert [r["stage"] for r in cloud.reservations] == ["agent_1", "agent_2"]
    assert len(cloud.reconciliations) == 2 and not cloud.pending
    assert cloud.reconciliations[0]["output"]["schema_name"] == "Preparation"
    assert cloud.reconciliations[0]["output"]["input"]["payload"]["run_id"] == str(RUN)
    assert cloud.reconciliations[0]["output"]["validation_status"] == "pending_workflow_validation"
    assert all(r["invocation"] == 0 and r["max_output_tokens"] == 8192 for r in cloud.reservations)
    assert all(
        r["job_id"] == str(JOB) and r["lease_token"] == str(LEASE)
        for r in cloud.reservations + cloud.reconciliations
    )
    output = cloud.completed[0]["output"]
    assert output["category"] == "cause_not_established"
    assert output["diagnosis_status"] == "needs_review" and output["brief"] is None
    assert output["stage_calls"] == {"agent1": 1, "agent2": 1, "agent3": 0}
    assert output["preparation"]["identity"]["document_number"] == "0000123456"
    assert output["usage"] == {"input_tokens": 200, "output_tokens": 40}
    assert output["source_catalogue"]
    assert output["model_configuration"] == {
        "models": {"agent1": "gpt-6-luna", "agent2": "gpt-6-luna", "agent3": "gpt-6-luna"},
        "reasoning_effort": "medium",
        "service_tier": "default",
        "price_version": "openai-standard-2026-10-01",
        "max_output_tokens": 8192,
    }
    assert len(clients) == 1 and clients[0].closed
    downloads = [r for r in cloud.requests if "/storage/" in r.url.path]
    assert len(downloads) == 9 and all(r.method == "GET" for r in downloads)


def test_arize_failure_is_reported_after_commit_without_changing_case_result(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    install_provider(monkeypatch, cloud, automatic_tracing=True)

    class UnavailableAutomaticTracing:
        enabled = True

        def __init__(self, _settings, *, metadata):
            assert metadata is None
            self.trace_metadata = {}

        def bind_metadata(self, metadata):
            assert metadata["run_id"] == str(RUN)
            self.trace_metadata = metadata
            return True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def flush(self, *, business_committed, run_state):
            assert business_committed and run_state == "succeeded"
            assert len(cloud.completed) == 1 and cloud.completed[0]["succeeded"] is True
            return ArizeTraceResult("retryable_failure", True)

    monkeypatch.setattr(worker, "AutoArizeTracing", UnavailableAutomaticTracing)
    result = run_worker(cloud)
    assert result["succeeded"] is True
    assert result["arize"] == {
        "status": "retryable_failure",
        "retryable": True,
        "trace_ids": (),
        "span_count": 0,
        "readback_verified": False,
        "error_code": None,
    }
    assert cloud.completed[0]["output"]["errors"] == []


def test_unexpected_telemetry_export_error_does_not_change_completed_business_result(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    install_provider(monkeypatch, cloud)

    class BrokenExport:
        enabled = False
        trace_metadata = {}

        def __init__(self, _settings, *, metadata):
            assert metadata is None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def flush(self, **_kwargs):
            assert cloud.completed[0]["succeeded"]
            raise RuntimeError("Unredacted SDK failure must not reach worker output")

    monkeypatch.setattr(worker, "AutoArizeTracing", BrokenExport)
    result = run_worker(cloud)
    assert result["succeeded"] and result["arize"]["status"] == "export_failed"
    assert result["arize"]["error_code"] == "optional_telemetry_error"
    assert cloud.completed[0]["output"]["errors"] == []


def test_slow_optional_setup_finishes_before_claim_and_binds_actual_ids(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    install_provider(monkeypatch, cloud, automatic_tracing=True)
    state = {"time": 0, "setup": False, "claimed_at": None, "bound": False, "closed": False}
    original_handler = cloud.handler

    def lease_handler(request):
        if request.url.path.endswith("/cfin_claim_job"):
            assert state["setup"]
            state["claimed_at"] = state["time"]
        elif request.url.path.endswith("/cfin_reserve_call"):
            assert state["bound"]
            assert state["time"] - state["claimed_at"] < 90
        return original_handler(request)

    cloud.handler = lease_handler

    class SlowAutomaticSetup:
        enabled = True

        def __init__(self, _settings, *, metadata):
            assert metadata is None
            self.trace_metadata = {}

        def __enter__(self):
            assert cloud.requests == []  # no lease exists during setup
            state["time"] += 120  # longer than SQL's 90-second initial lease
            state["setup"] = True
            return self

        def bind_metadata(self, metadata):
            assert state["claimed_at"] == 120
            actual = cloud.runs[0]
            assert {key: metadata[key] for key in ("workspace_id", "case_id", "attempt_id")} == {
                key: actual[key] for key in ("workspace_id", "case_id", "attempt_id")
            }
            assert metadata["run_id"] == actual["id"]
            self.trace_metadata = metadata
            state["bound"] = True
            return True

        def flush(self, *, business_committed, run_state):
            assert business_committed and run_state == "succeeded" and cloud.completed
            return ArizeTraceResult("offline_test")

        def __exit__(self, *_args):
            state["closed"] = True

    monkeypatch.setattr(worker, "AutoArizeTracing", SlowAutomaticSetup)
    result = run_worker(cloud)
    assert result["succeeded"]
    assert state["closed"] and state["bound"]
    assert len(cloud.reservations) == 2


def test_optional_setup_failure_still_processes_claim_with_tracing_disabled(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    clients, payloads = install_provider(monkeypatch, cloud)

    class FailedAutomaticSetup:
        enabled = False
        trace_metadata = {}

        def __init__(self, _settings, *, metadata):
            assert metadata is None

        def __enter__(self):
            assert cloud.requests == []
            return self

        def bind_metadata(self, metadata):
            assert metadata["run_id"] == str(RUN)
            return False

        def flush(self, **_kwargs):
            assert cloud.completed
            return ArizeTraceResult("initialization_failed", True, error_code="setup_error")

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(worker, "AutoArizeTracing", FailedAutomaticSetup)
    result = run_worker(cloud)
    assert result["succeeded"] and len(payloads) == 2
    assert clients[0].closed and result["arize"]["status"] == "initialization_failed"


@pytest.mark.parametrize("claim_failure", [False, True])
def test_preclaim_auto_logger_cleanup_without_binding_or_upload(monkeypatch, claim_failure):
    cloud = CloudHTTP()
    if claim_failure:
        cloud.rpc_errors["cfin_claim_job"] = 409
    clients, payloads = install_provider(monkeypatch, cloud)
    closed = []

    class PreclaimAutomaticSetup:
        enabled = True

        def __init__(self, _settings, *, metadata):
            assert metadata is None

        def __enter__(self):
            assert cloud.requests == []
            return self

        def bind_metadata(self, *_args):
            pytest.fail("An unclaimed queue has no run IDs to bind")

        def flush(self, **_kwargs):
            pytest.fail("An unclaimed queue must not upload traces")

        def __exit__(self, *_args):
            closed.append(True)

    monkeypatch.setattr(worker, "AutoArizeTracing", PreclaimAutomaticSetup)
    if claim_failure:
        with pytest.raises(HTTPException):
            run_worker(cloud)
    else:
        assert run_worker(cloud) == {"claimed": False}
    assert closed == [True]
    assert not clients and not payloads and not cloud.reservations
    assert len(cloud.requests) == 1


def test_business_commit_failure_closes_auto_logger_without_uploading(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    cloud.rpc_errors["cfin_complete_run"] = 409
    install_provider(monkeypatch, cloud)
    closed = []

    class AutomaticTracing:
        enabled = False

        def __init__(self, _settings, *, metadata):
            assert metadata is None
            self.trace_metadata = {}

        def bind_metadata(self, metadata):
            self.trace_metadata = metadata
            return False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            closed.append(True)

        def flush(self, **_kwargs):
            pytest.fail("Uncommitted business results must not upload telemetry")

    monkeypatch.setattr(worker, "AutoArizeTracing", AutomaticTracing)
    with pytest.raises(HTTPException):
        run_worker(cloud)
    assert closed == [True]
    assert len(cloud.reconciliations) == 2


@pytest.mark.parametrize("invalid", ["missing_file", "wrong_identity", "corrupt_bytes", "proof"])
def test_invalid_saved_snapshot_fails_before_model_reservation(monkeypatch, invalid):
    cloud = CloudHTTP()
    snapshot = cloud.seed_inputs()
    cloud.claimed = True
    if invalid == "missing_file":
        snapshot["sources"].pop()
    elif invalid == "wrong_identity":
        snapshot["identity"]["document_number"] = "0000999999"
    elif invalid == "corrupt_bytes":
        cloud.corrupt_filename = "manifest.json"
    else:
        snapshot["sources"][0]["evidence"]["kind"] = "proof"
    clients, payloads = install_provider(monkeypatch, cloud)
    monkeypatch.setattr(fixture_loader, "_read_files", lambda *a: pytest.fail("Local fallback"))
    result = run_worker(cloud)
    assert not result["succeeded"] and not clients and not payloads
    assert not cloud.reservations and not cloud.pending
    assert cloud.completed[0]["error_code"] == "worker_execution_failed"
    assert cloud.completed[0]["output"] is None


@pytest.mark.parametrize("failure", ["duplicate", "budget", "pricing"])
def test_reservation_denial_blocks_sdk_dispatch_without_paid_duplicate(monkeypatch, failure):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    if failure == "duplicate":
        cloud.duplicate_reservation = True
    elif failure == "budget":
        cloud.rpc_errors["cfin_reserve_call"] = 400
    else:
        cloud.price_version = "wrong-price-version"
    clients, payloads = install_provider(monkeypatch, cloud)
    result = run_worker(cloud)
    assert not result["succeeded"] and not payloads and not cloud.reconciliations
    assert clients[0].closed and cloud.completed[0]["output"]["errors"]
    assert "private SQL text" not in json.dumps(cloud.completed)


@pytest.mark.parametrize("failure", ["missing_usage", "provider_error", "reconcile_failed"])
def test_uncertain_usage_keeps_reservation_and_withholds_workflow_result(monkeypatch, failure):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    if failure == "reconcile_failed":
        cloud.rpc_errors["cfin_reconcile_call"] = 409
    clients, payloads = install_provider(
        monkeypatch,
        cloud,
        requests=0 if failure == "missing_usage" else 1,
        error=RuntimeError("sensitive provider error") if failure == "provider_error" else None,
    )
    result = run_worker(cloud)
    assert not result["succeeded"] and len(payloads) == 1
    assert len(cloud.reservations) == 1 and len(cloud.pending) == 1
    assert not cloud.reconciliations and clients[0].closed
    assert not cloud.completed[0]["output"]["preparation"]
    assert "sensitive provider error" not in json.dumps(cloud.completed)
    assert "private SQL text" not in json.dumps(cloud.completed)


def test_cloud_ledger_requires_current_lease_on_reservation_and_reconciliation():
    cloud = CloudHTTP()
    cloud.rpc_errors["cfin_reserve_call"] = 409
    cloud.rpc_errors["cfin_reconcile_call"] = 409

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cloud.handler)) as client:
            ledger = CloudCallLedger(
                ServiceGateway(test_settings(), client), {"id": str(JOB), "lease_token": str(LEASE)}
            )
            with pytest.raises(RuntimeError, match="budget reservation failed"):
                await ledger.reserve(
                    "agent1", model_adapter.MODEL, 65536, 8192, model_adapter.PRICE_VERSION
                )
            with pytest.raises(RuntimeError, match="usage reconciliation failed"):
                await ledger.reconcile(
                    "test-call", {"input_tokens": 100, "output_tokens": 20}, Decimal("0.0000225")
                )

    asyncio.run(run())
    for request in cloud.requests:
        payload = json.loads(request.content)["payload"]
        assert payload["job_id"] == str(JOB) and payload["lease_token"] == str(LEASE)
        assert request.headers["apikey"] == SECRET


def test_worker_forwards_lower_configured_caps_to_durable_reservation(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    install_provider(monkeypatch, cloud)
    result = run_worker(
        cloud,
        settings=test_settings(model_monthly_budget_usd="0.50", model_run_budget_usd="0.05"),
    )
    assert result["succeeded"]
    assert len(cloud.reservations) == 2
    assert all(r["monthly_budget_usd"] == "0.50" for r in cloud.reservations)
    assert all(r["run_budget_usd"] == "0.05" for r in cloud.reservations)


def test_success_http_status_with_unknown_reconciled_usage_does_not_publish(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    cloud.reconcile_response_state = "usage_unknown"
    clients, payloads = install_provider(monkeypatch, cloud)
    result = run_worker(cloud)
    assert not result["succeeded"] and len(payloads) == 1
    assert len(cloud.pending) == 1 and clients[0].closed
    assert cloud.completed[0]["output"]["preparation"] is None


def test_worker_lost_heartbeat_cancels_inflight_stage_and_closes_client(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    cloud.rpc_errors["cfin_heartbeat_job"] = 409
    instances = []
    cancelled = []
    original_sleep = asyncio.sleep

    class WaitingAdapter:
        evaluation_only = True
        closed = False

        def __init__(self, settings, ledger, **_tracing):
            instances.append(self)

        async def execute(self, stage, payload, output_type, inputs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(stage)
                raise

        async def close(self):
            self.closed = True

    async def short_sleep(delay):
        await original_sleep(0)

    monkeypatch.setattr(worker, "OpenAIStageAdapter", WaitingAdapter)
    monkeypatch.setattr(worker.asyncio, "sleep", short_sleep)
    result = run_worker(cloud)
    assert not result["succeeded"]
    assert cancelled == ["agent1"] and instances[0].closed
    assert cloud.completed[0]["error_code"] == "worker_execution_failed"
    assert not cloud.reservations
