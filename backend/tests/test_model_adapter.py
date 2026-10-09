import asyncio
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agents import AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

from cfin import model_adapter
from cfin.config import Settings
from cfin.contracts import CaseBrief, Diagnosis, Preparation
from cfin.evaluation import build_eval_inputs
from cfin.fixture_loader import load_md01
from cfin.workflow import ScriptedStageAdapter, WorkflowExecutor, build_preparation


class RecordingLedger:
    def __init__(self, *, reserve_error=None, reconcile_error=None):
        self.reserve_error = reserve_error
        self.reconcile_error = reconcile_error
        self.reservations = []
        self.reconciliations = []
        self.trace_payloads = []
        self.pending = set()

    async def reserve(self, stage, model, input_bound, output_bound, price_version):
        if self.reserve_error:
            raise self.reserve_error
        reservation_id = f"reservation-{len(self.reservations) + 1}"
        self.reservations.append(
            (reservation_id, stage, model, input_bound, output_bound, price_version)
        )
        self.pending.add(reservation_id)
        return reservation_id

    async def reconcile(self, reservation_id, usage, cost_usd, **metadata):
        if self.reconcile_error:
            raise self.reconcile_error
        self.reconciliations.append((reservation_id, usage, cost_usd))
        self.trace_payloads.append(metadata)
        self.pending.remove(reservation_id)


def configured_settings(**changes):
    data = {
        "_env_file": None,
        "supabase_url": "https://synthetic-test.supabase.co",
        "supabase_publishable_key": "test-only-publishable-key",
        "supabase_secret_key": "test-only-worker-secret",
        "openai_api_key": "test-only-openai-key",
        "paid_models_enabled": True,
        "model_agent_1": model_adapter.MODEL,
        "model_agent_2": model_adapter.MODEL,
        "model_agent_3": model_adapter.MODEL,
    }
    return Settings(**{**data, **changes})


@pytest.fixture
def client_factory(monkeypatch):
    created = []

    class FakeClient:
        closed = False

        async def close(self):
            self.closed = True

    def factory(**kwargs):
        client = FakeClient()
        created.append((kwargs, client))
        return client

    monkeypatch.setattr(model_adapter, "AsyncOpenAI", factory)
    return created


def execute(adapter):
    inputs = load_md01()
    payload = {
        "run_id": "adapter-test-run",
        "attempt_id": inputs.manifest.attempt_id,
        "input_source_version": inputs.manifest.source_version,
    }
    return asyncio.run(adapter.execute("agent1", payload, Preparation, inputs))


def test_only_verified_auto_processor_enables_sensitive_trace_data(monkeypatch, client_factory):
    ledger = RecordingLedger()
    received = install_response(monkeypatch, ledger)
    adapter = model_adapter.OpenAIStageAdapter(
        configured_settings(),
        ledger,
        tracing_enabled=True,
        trace_metadata={"run_id": "synthetic-auto-trace-run", "provenance": "synthetic_test"},
    )
    execute(adapter)
    options = received[0][2]["run_config"]
    assert not options.tracing_disabled
    assert options.trace_include_sensitive_data
    assert options.trace_metadata == {
        "run_id": "synthetic-auto-trace-run",
        "provenance": "synthetic_test",
        "stage": "agent1",
        "model": model_adapter.MODEL,
    }
    assert "test-only-openai-key" not in json.dumps(options.trace_metadata)


def install_response(
    monkeypatch,
    ledger,
    *,
    requests=1,
    input_tokens=100,
    output_tokens=20,
    error=None,
    invalid_output=False,
):
    received = []

    async def run(agent, encoded, **kwargs):
        # The model cannot be invoked before a durable reservation succeeds.
        assert len(ledger.reservations) == 1 and ledger.pending == {"reservation-1"}
        received.append((agent, encoded, kwargs))
        if error:
            raise error
        output = build_preparation(load_md01(), "adapter-test-run").model_dump(mode="json")
        if invalid_output:
            output["identity"]["document_number"] = 123456
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(
                    requests=requests,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            ),
            final_output=output,
            raw_responses=[SimpleNamespace(request_id="test-provider-request")],
        )

    monkeypatch.setattr(model_adapter.Runner, "run", run)
    return received


@pytest.mark.parametrize(
    "changes",
    [
        {"openai_api_key": ""},
        {"paid_models_enabled": False},
        {"supabase_secret_key": ""},
        {"model_agent_1": ""},
    ],
)
def test_missing_configuration_blocks_before_client_or_reservation(changes, client_factory):
    ledger = RecordingLedger()
    with pytest.raises(RuntimeError, match="not configured"):
        model_adapter.OpenAIStageAdapter(configured_settings(**changes), ledger)
    assert client_factory == [] and not ledger.reservations


def test_unknown_model_pricing_blocks_before_client_creation(client_factory):
    with pytest.raises(RuntimeError, match="verified price"):
        model_adapter.OpenAIStageAdapter(
            configured_settings(model_agent_2="unpriced-model"), RecordingLedger()
        )
    assert client_factory == []


def test_unknown_stage_blocks_before_reservation_or_provider(monkeypatch, client_factory):
    ledger = RecordingLedger()
    received = install_response(monkeypatch, ledger)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="Unknown model stage"):
        asyncio.run(adapter.execute("agent4", {}, Preparation, load_md01()))
    assert received == [] and ledger.reservations == [] and ledger.reconciliations == []


def test_reserved_call_reconciles_usage_before_publishing(monkeypatch, client_factory):
    ledger = RecordingLedger()
    received = install_response(monkeypatch, ledger)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    result = execute(adapter)
    assert result.identity.document_number == "0000123456"
    assert ledger.pending == set()
    expected_cost = (Decimal(100) * Decimal("0.125") + Decimal(20) * Decimal("0.50")) / Decimal(
        1_000_000
    )
    assert ledger.reconciliations == [
        ("reservation-1", {"input_tokens": 100, "output_tokens": 20}, expected_cost)
    ]
    assert adapter.usage == {"input_tokens": 100, "output_tokens": 20}
    assert adapter.cost_usd == expected_cost
    assert ledger.trace_payloads[0]["provider_request_id"] == "test-provider-request"
    trace = ledger.trace_payloads[0]["trace_payload"]
    assert trace["output"] == result.model_dump(mode="json")
    assert trace["input"]["payload"]["run_id"] == "adapter-test-run"
    assert trace["validation_status"] == "pending_workflow_validation"
    assert "test-only-openai-key" not in json.dumps(trace)
    kwargs, client = client_factory[0]
    assert kwargs["max_retries"] == 0
    assert kwargs["timeout"] <= 60
    agent, _, run_options = received[0]
    assert agent.tools == []
    assert agent.model_settings.store is False
    assert agent.model_settings.max_tokens == model_adapter.MAX_OUTPUT_TOKENS
    assert run_options["max_turns"] == 1
    assert run_options["run_config"].tracing_disabled
    assert not run_options["run_config"].trace_include_sensitive_data
    asyncio.run(adapter.close())
    assert client.closed


@pytest.mark.parametrize("analysis_model", ["gpt-6.1-sol", "gpt-6-sol"])
def test_preparation_and_analysis_use_configured_models_with_matching_reserved_costs(
    monkeypatch, client_factory, analysis_model
):
    inputs = build_eval_inputs("md01-reviewed-simulation")
    ledger = RecordingLedger()
    received = []
    stage_models = {"agent1": "gpt-6-luna", "agent2": analysis_model, "agent3": analysis_model}
    stage_usage = {"agent1": (200, 40), "agent2": (100, 20), "agent3": (300, 60)}
    output_types = {"agent1": Preparation, "agent2": Diagnosis, "agent3": CaseBrief}
    scripted = ScriptedStageAdapter()

    async def run(agent, encoded, **kwargs):
        stage = agent.name
        received.append((agent, kwargs, ledger.reservations[-1], set(ledger.pending)))
        output = await scripted.execute(stage, json.loads(encoded), output_types[stage], inputs)
        input_tokens, output_tokens = stage_usage[stage]
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(
                    requests=1, input_tokens=input_tokens, output_tokens=output_tokens
                )
            ),
            final_output=output.model_dump(mode="json"),
        )

    monkeypatch.setattr(model_adapter.Runner, "run", run)
    adapter = model_adapter.OpenAIStageAdapter(
        configured_settings(model_agent_2=analysis_model, model_agent_3=analysis_model), ledger
    )
    result = asyncio.run(
        WorkflowExecutor(adapter, run_id="mixed-model-test", as_of=date(2026, 9, 30)).run(inputs)
    )
    assert result.errors == ()
    assert (
        result.preparation is not None and result.diagnosis is not None and result.brief is not None
    )
    assert [agent.name for agent, *_ in received] == ["agent1", "agent2", "agent3"]
    for agent, options, reservation, pending in received:
        reservation_id, reserved_stage, reserved_model, input_bound, output_bound, price_version = (
            reservation
        )
        # Each provider dispatch used the model already authorized by the ledger.
        assert pending == {reservation_id}
        assert (reserved_stage, reserved_model) == (agent.name, stage_models[agent.name])
        assert agent.model.model == reserved_model
        assert 0 < input_bound <= 131_072 and output_bound == 8192
        assert price_version == "openai-standard-2026-10-01"
        assert agent.model_settings.reasoning.effort == "medium"
        assert agent.model_settings.extra_body == {"service_tier": "default"}
        assert agent.model_settings.store is False
        assert options["max_turns"] == 1
    assert result.stage_calls == {"agent1": 1, "agent2": 1, "agent3": 1}
    assert [(row[1], row[2]) for row in ledger.reservations] == list(stage_models.items())
    assert ledger.pending == set()
    # Literal verified prices catch accidental use of Luna pricing for a Sol response.
    assert ledger.reconciliations == [
        (
            "reservation-1",
            {"input_tokens": 200, "output_tokens": 40},
            Decimal("0.000045"),
        ),
        (
            "reservation-2",
            {"input_tokens": 100, "output_tokens": 20},
            Decimal("0.00045"),
        ),
        (
            "reservation-3",
            {"input_tokens": 300, "output_tokens": 60},
            Decimal("0.00135"),
        ),
    ]
    assert result.usage == adapter.usage == {"input_tokens": 600, "output_tokens": 120}
    assert result.cost_usd == adapter.cost_usd == Decimal("0.001845")
    kwargs, client = client_factory[0]
    assert kwargs["max_retries"] == 0
    asyncio.run(adapter.close())
    assert client.closed


@pytest.mark.parametrize(
    "requests,input_tokens,output_tokens",
    [
        (0, 0, 0),
        (1, 0, 0),
        (0, 100, 20),
    ],
)
def test_missing_usage_keeps_reservation_and_withholds_output(
    monkeypatch, client_factory, requests, input_tokens, output_tokens
):
    ledger = RecordingLedger()
    install_response(
        monkeypatch,
        ledger,
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="usage missing; reserved cost retained"):
        execute(adapter)
    assert ledger.pending == {"reservation-1"}
    assert ledger.reconciliations == []
    assert adapter.usage == {"input_tokens": 0, "output_tokens": 0}
    assert adapter.cost_usd == 0


def test_timeout_or_provider_error_retains_reservation_without_raw_error(
    monkeypatch, client_factory
):
    ledger = RecordingLedger()
    install_response(monkeypatch, ledger, error=RuntimeError("sensitive-provider-error"))
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="reserved cost retained") as exc:
        execute(adapter)
    assert "sensitive-provider-error" not in str(exc.value)
    assert ledger.pending == {"reservation-1"} and not ledger.reconciliations


def test_budget_denial_prevents_provider_invocation(monkeypatch, client_factory):
    ledger = RecordingLedger(reserve_error=RuntimeError("Budget allowance exhausted"))
    received = install_response(monkeypatch, ledger)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="allowance exhausted"):
        execute(adapter)
    assert received == [] and ledger.reservations == []


@pytest.mark.parametrize(
    "input_tokens,output_tokens",
    [
        (-1, 20),
        (100, model_adapter.MAX_OUTPUT_TOKENS + 1),
        (model_adapter.MAX_INPUT_BOUND + 1, 20),
    ],
)
def test_usage_outside_reservation_requires_review(
    monkeypatch, client_factory, input_tokens, output_tokens
):
    ledger = RecordingLedger()
    install_response(monkeypatch, ledger, input_tokens=input_tokens, output_tokens=output_tokens)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="reserved bounds"):
        execute(adapter)
    assert ledger.pending == {"reservation-1"} and not ledger.reconciliations


def test_reconciliation_failure_does_not_publish_or_release_reserve(monkeypatch, client_factory):
    ledger = RecordingLedger(reconcile_error=RuntimeError("Ledger unavailable"))
    install_response(monkeypatch, ledger)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="Ledger unavailable"):
        execute(adapter)
    assert ledger.pending == {"reservation-1"}
    assert adapter.usage == {"input_tokens": 0, "output_tokens": 0}


def test_invalid_output_still_accounts_for_known_paid_usage(monkeypatch, client_factory):
    ledger = RecordingLedger()
    install_response(monkeypatch, ledger, invalid_output=True)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(ValidationError):
        execute(adapter)
    assert len(ledger.reconciliations) == 1
    trace = ledger.trace_payloads[0]["trace_payload"]
    assert trace["output"]["identity"]["document_number"] == 123456
    assert trace["validation_status"] == "pending_workflow_validation"
    assert adapter.usage == {"input_tokens": 100, "output_tokens": 20}


def test_oversize_input_is_blocked_before_reservation_or_provider(monkeypatch, client_factory):
    ledger = RecordingLedger()
    received = install_response(monkeypatch, ledger)
    adapter = model_adapter.OpenAIStageAdapter(configured_settings(), ledger)
    with pytest.raises(RuntimeError, match="Input exceeds"):
        asyncio.run(
            adapter.execute(
                "agent1", {"text": "€" * model_adapter.MAX_INPUT_BOUND}, Preparation, load_md01()
            )
        )
    assert received == [] and not ledger.reservations


@pytest.mark.parametrize(
    "output_type,field",
    [
        (Preparation, "preparation"),
        (Diagnosis, "diagnosis"),
        (CaseBrief, "brief"),
    ],
)
def test_all_agent_output_contracts_support_sdk_strict_schema(output_type, field):
    inputs = build_eval_inputs("md01-reviewed-simulation")
    result = asyncio.run(
        WorkflowExecutor(ScriptedStageAdapter(), as_of=date(2026, 9, 30)).run(inputs)
    )
    output = getattr(result, field)
    schema = AgentOutputSchema(output_type)
    assert schema.is_strict_json_schema()
    assert schema.json_schema()["additionalProperties"] is False
    parsed = schema.validate_json(output.model_dump_json())
    assert isinstance(parsed, output_type)
    assert parsed == output


def test_sdk_schema_rejects_numeric_identifier_instead_of_losing_zeros():
    schema = AgentOutputSchema(Preparation)
    output = build_preparation(load_md01(), "schema-test-run").model_dump(mode="json")
    output["identity"]["document_number"] = 123456
    with pytest.raises(ModelBehaviorError):
        schema.validate_json(json.dumps(output))
