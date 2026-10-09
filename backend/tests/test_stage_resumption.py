"""Resumed candidates are revalidated; paid usage and retries stay truthful."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from agents.exceptions import ModelBehaviorError
from test_model_adapter import RecordingLedger, configured_settings
from test_operations import RUN, WORKSPACE, CloudHTTP
from test_worker import install_provider, run_worker

from cfin import model_adapter
from cfin.contracts import FailureCategory, Preparation
from cfin.evaluation import build_eval_inputs
from cfin.fixture_loader import load_md01
from cfin.worker import CloudCallLedger
from cfin.workflow import (
    RetryableStageError,
    ScriptedStageAdapter,
    WorkflowExecutor,
    build_diagnosis,
    build_preparation,
)


class Cloud:
    def __init__(self, saved):
        self.saved = saved
        self.calls = []

    async def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == "cfin_stage_resume":
            return self.saved
        if name == "cfin_reserve_call":
            return {
                "execute": True,
                "call": {"id": "new-call", "price_version": model_adapter.PRICE_VERSION},
            }
        if name == "cfin_reconcile_call":
            return {
                "id": payload["call_id"],
                "state": "succeeded",
                "usage": payload["usage"],
                "actual_usd": "0.000023",
            }
        return {"saved": True}


def ledger(saved):
    value = CloudCallLedger(Cloud(saved), {"id": "test-job", "lease_token": "test-lease"})
    asyncio.run(value.resume())
    return value


@pytest.fixture
def client(monkeypatch):
    class Client:
        async def close(self):
            pass

    monkeypatch.setattr(model_adapter, "AsyncOpenAI", lambda **_: Client())


def test_resume_retains_all_known_usage_including_failed_candidates_and_unknown_reserves():
    value = ledger(
        {
            "outputs": {},
            "calls": [
                {
                    "id": "first",
                    "stage": "agent_1",
                    "invocation": 0,
                    "state": "failed",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "actual_usd": "0.000023",
                },
                {
                    "id": "retry",
                    "stage": "agent_1",
                    "invocation": 1,
                    "state": "succeeded",
                    "usage": {"input_tokens": 200, "output_tokens": 40},
                    "actual_usd": "0.000045",
                },
                {
                    "id": "unknown",
                    "stage": "agent_2",
                    "invocation": 0,
                    "state": "usage_unknown",
                    "usage": None,
                    "actual_usd": None,
                },
            ],
        }
    )
    assert value.total_usage == {"input_tokens": 300, "output_tokens": 60}
    assert value.total_cost_usd == Decimal("0.000068")
    assert value.invocations == {"agent1": 2, "agent2": 1}
    assert value.dispatch_counts == {"agent1": 2, "agent2": 1}
    assert not value.usage_complete


def test_cached_preparation_is_revalidated_without_adding_fake_provider_usage(monkeypatch, client):
    inputs = load_md01()
    prepared = build_preparation(inputs, "resumed-run").model_dump(mode="json")
    value = ledger(
        {
            "outputs": {"agent1": prepared},
            "calls": [
                {
                    "id": "prior-call",
                    "stage": "agent_1",
                    "invocation": 0,
                    "state": "succeeded",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "actual_usd": "0.000023",
                }
            ],
        }
    )
    dispatches = []

    async def run(agent, encoded, **_):
        dispatches.append(agent.name)
        output = build_diagnosis(inputs, "resumed-run", date(2026, 10, 1))
        return SimpleNamespace(
            final_output=output,
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(requests=1, input_tokens=100, output_tokens=20)
            ),
        )

    monkeypatch.setattr(model_adapter.Runner, "run", run)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), value)
    result = asyncio.run(
        WorkflowExecutor(adapter, run_id="resumed-run", as_of=date(2026, 10, 1)).run(inputs)
    )
    assert not result.errors and dispatches == ["agent2"]
    assert result.stage_calls == {"agent1": 1, "agent2": 1, "agent3": 0}
    assert result.usage == {"input_tokens": 200, "output_tokens": 40}
    assert result.cost_usd == Decimal("0.000046") and result.usage_complete
    assert result.stage_reuses["agent1"] == "validated_or_reconciled_same_run_candidate"


def test_expired_stage_cannot_gain_another_60_seconds_after_worker_restart(monkeypatch, client):
    value = ledger(
        {
            "outputs": {},
            "calls": [
                {
                    "id": "prior-call",
                    "stage": "agent_1",
                    "invocation": 0,
                    "state": "usage_unknown",
                    "usage": None,
                    "actual_usd": None,
                    "created_at": (datetime.now(UTC) - timedelta(seconds=61)).isoformat(),
                }
            ],
        }
    )
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), value)
    result = asyncio.run(
        WorkflowExecutor(adapter, run_id="resumed-run", max_retries=1).run(load_md01())
    )
    assert result.errors == ("agent1_failed_validation_or_execution",)
    assert result.stage_calls["agent1"] == 1
    assert all(name != "cfin_reserve_call" for name, _ in value.cloud.calls)


def test_sdk_malformed_output_is_retryable_but_keeps_its_unknown_usage_reserve(monkeypatch, client):
    value = RecordingLedger()

    async def run(*args, **kwargs):
        raise ModelBehaviorError("Private malformed candidate content")

    monkeypatch.setattr(model_adapter.Runner, "run", run)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), value)
    with pytest.raises(RetryableStageError, match="malformed structured") as failure:
        asyncio.run(adapter.execute("agent1", {}, Preparation, load_md01()))
    assert "Private" not in str(failure.value)
    assert value.pending == {"reservation-1"} and not value.reconciliations
    assert adapter.dispatch_counts["agent1"] == 1 and not adapter.usage_complete


def test_wrong_brief_category_is_never_saved_as_a_validated_checkpoint():
    class CorruptBrief(ScriptedStageAdapter):
        def __init__(self):
            self.saved = []

        async def execute(self, stage, payload, output_type, inputs):
            output = await super().execute(stage, payload, output_type, inputs)
            if stage == "agent3":
                return output.model_copy(update={"category": FailureCategory.MISSING_GL_MAPPING})
            return output

        async def record_validated(self, stage, output):
            self.saved.append(stage)

    adapter = CorruptBrief()
    result = asyncio.run(
        WorkflowExecutor(adapter, as_of=date(2026, 9, 30)).run(
            build_eval_inputs("md01-reviewed-simulation")
        )
    )
    assert result.errors == ("agent3_failed_validation_or_execution",)
    assert adapter.saved == ["agent1", "agent2"] and result.brief is None


def test_supported_diagnosis_with_wrong_lookup_claim_is_rejected_before_checkpoint():
    class CorruptCheck(ScriptedStageAdapter):
        def __init__(self):
            self.saved = []

        async def execute(self, stage, payload, output_type, inputs):
            output = await super().execute(stage, payload, output_type, inputs)
            if stage == "agent2":
                data = output.model_dump(mode="json")
                data["findings"][0]["checks"][0]["lookup_id"] = "invented-approved-reference"
                return data
            return output

        async def record_validated(self, stage, output):
            self.saved.append(stage)

    adapter = CorruptCheck()
    result = asyncio.run(
        WorkflowExecutor(adapter, as_of=date(2026, 9, 30)).run(
            build_eval_inputs("md01-reviewed-simulation")
        )
    )
    assert result.errors == ("agent2_failed_validation_or_execution",)
    assert adapter.saved == ["agent1"] and result.diagnosis is None


@pytest.mark.parametrize("valid", [True, False])
def test_cross_run_reuse_rebinds_only_run_id_and_revalidates_original_source(monkeypatch, valid):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    source_run = "88888888-8888-4888-8888-888888888888"
    inputs = load_md01()
    manifest = inputs.manifest.model_copy(
        update={
            "identity": inputs.manifest.identity.model_copy(update={"workspace_id": str(WORKSPACE)})
        }
    )
    candidate = build_preparation(replace(inputs, manifest=manifest), source_run).model_dump(
        mode="json"
    )
    if not valid:
        candidate["input_source_version"] = "different-source-version"
    original_handler = cloud.handler

    def handler(request):
        if request.url.path.endswith("cfin_preparation_reuse"):
            cloud.requests.append(request)
            return httpx.Response(
                200, json={"reused": True, "source_run_id": source_run, "preparation": candidate}
            )
        return original_handler(request)

    cloud.handler = handler
    _, payloads = install_provider(monkeypatch, cloud)
    result = run_worker(cloud)
    assert result["succeeded"]
    output = cloud.completed[0]["output"]
    if valid:
        assert [stage for stage, _ in payloads] == ["agent2"]
        assert output["preparation"]["run_id"] == str(RUN)
        assert output["stage_calls"] == {"agent1": 0, "agent2": 1, "agent3": 0}
        assert output["stage_reuses"] == {"agent1": source_run}
        assert output["usage"] == {"input_tokens": 100, "output_tokens": 20}
    else:
        assert [stage for stage, _ in payloads] == ["agent1", "agent2"]
        assert not output["stage_reuses"]
    assert output["auto_owner"] is None


def test_model_evaluation_jobs_always_dispatch_agent1_instead_of_reusing_prior_run(monkeypatch):
    cloud = CloudHTTP()
    cloud.seed_inputs()
    cloud.claimed = True
    cloud.runs[0]["evaluation_only"] = True
    cloud.runs[0]["snapshot"]["evaluation_configuration"] = {
        "models": {"agent1": "gpt-6-luna", "agent2": "gpt-6-luna", "agent3": "gpt-6-luna"},
        "reasoning_effort": "medium",
    }
    _, payloads = install_provider(monkeypatch, cloud)
    result = run_worker(cloud)
    assert result["succeeded"] and [stage for stage, _ in payloads] == ["agent1", "agent2"]
    assert not any(
        request.url.path.endswith("cfin_preparation_reuse") for request in cloud.requests
    )
