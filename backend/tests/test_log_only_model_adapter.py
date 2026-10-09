import asyncio
import builtins
import copy
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agents import AgentOutputSchema
from agents.exceptions import ModelBehaviorError

from cfin import model_adapter
from cfin.config import Settings
from cfin.log_only_contracts import EvidenceSelection, ExtractedLog, LogSummary
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.stage_errors import RetryableStageError


class Ledger:
    def __init__(self):
        self.cached_outputs = {}
        self.reservations = []
        self.reconciliations = []
        self.saved = []
        self.pending = set()

    async def reserve(self, *args):
        reservation = f"reservation-{len(self.reservations) + 1}"
        self.reservations.append((reservation, args))
        self.pending.add(reservation)
        return reservation

    async def reconcile(self, reservation, usage, cost, **metadata):
        self.reconciliations.append((reservation, usage, cost, metadata))
        self.pending.remove(reservation)

    async def record_validated(self, stage, output):
        self.saved.append((stage, output))
        self.cached_outputs[stage] = output


@pytest.fixture
def configured(monkeypatch):
    class Client:
        async def close(self):
            pass

    monkeypatch.setattr(model_adapter, "AsyncOpenAI", lambda **kwargs: Client())
    return Settings(
        _env_file=None,
        supabase_url="https://synthetic-test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_secret_key="test-worker-secret",
        openai_api_key="test-api-key",
        paid_models_enabled=True,
    )


def binding():
    return {
        "workspace_id": "workspace-1",
        "run_id": "run-1",
        "case_id": "case-1",
        "attempt_id": "attempt-1",
        "input_revision": "revision-1",
        "workflow_version": "log-only-v1",
        "schema_version": "log-only-v1",
        "source_manifest_sha256": "a" * 64,
        "prompt_versions": dict(LOG_PROMPT_VERSIONS),
        "model_configuration": {
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    }


def outputs():
    entry = {
        "entry_id": "entry-1",
        "source_id": "source-1",
        "source_version": "1",
        "kind": "message",
        "source_span": {"line_start": 1, "line_end": 1},
        "raw_text": "Document 000001 failed.\r\n",
    }
    return {
        "agent1": ExtractedLog(entries=[entry]),
        "agent2": EvidenceSelection(selected_entry_ids=["entry-1"]),
        "agent3": LogSummary(
            title={"text": "Reported document failure", "supporting_entry_ids": ["entry-1"]},
            statements=[
                {
                    "text": "The log reports that document 000001 failed.",
                    "supporting_entry_ids": ["entry-1"],
                }
            ],
        ),
    }


def payload(stage):
    data = {"binding": binding()}
    if stage == "agent1":
        data["sources"] = [
            {
                "source": {"source_id": "source-1", "source_version": "1"},
                "lines": [{"line_number": 1, "text": "Document 000001 failed.\r\n"}],
            }
        ]
    elif stage == "agent2":
        data.update(
            extracted=outputs()["agent1"].model_dump(mode="json"), source_manifest={"sources": []}
        )
    else:
        data.update(evidence={"selected_entries": []}, history={"status": "not_searched"})
    return data


def adapter(settings, ledger):
    return model_adapter.OpenAIStageAdapter(settings, ledger, workflow_version="log-only-v1")


def install_response(monkeypatch, ledger, *, error=None, input_tokens=100, output_tokens=20):
    received = []

    async def run(agent, encoded, **kwargs):
        assert ledger.pending
        received.append((agent, json.loads(encoded), kwargs))
        if error:
            raise error
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(
                    requests=1, input_tokens=input_tokens, output_tokens=output_tokens
                )
            ),
            final_output=outputs()[agent.name],
            raw_responses=[SimpleNamespace(request_id="synthetic-request")],
        )

    monkeypatch.setattr(model_adapter.Runner, "run", run)
    return received


def execute(instance, stage="agent1", data=None):
    return asyncio.run(
        instance.execute(stage, data or payload(stage), type(outputs()[stage]), None)
    )


@pytest.mark.parametrize("stage", ["agent1", "agent2", "agent3"])
def test_factual_stage_uses_own_strict_schema_prompts_and_existing_paid_controls(
    monkeypatch, configured, stage
):
    ledger = Ledger()
    received = install_response(monkeypatch, ledger)
    real_import = builtins.__import__

    def no_diagnostic_import(name, *args, **kwargs):
        assert name != "cfin.workflow", "factual stage must not import legacy instructions"
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_diagnostic_import)
    instance = adapter(configured, ledger)
    output = execute(instance, stage)
    assert output == outputs()[stage]
    agent, actual_payload, options = received[0]
    assert agent.name == stage
    assert actual_payload == payload(stage)
    assert "Do not diagnose a root cause" in agent.instructions
    assert "missing_target_gl_master_data" not in agent.instructions
    assert "required_unmet_prerequisites" not in agent.instructions
    assert agent.tools == []
    assert agent.model_settings.reasoning.effort == "medium"
    assert agent.model_settings.extra_body == {"service_tier": "default"}
    assert agent.model_settings.store is False
    assert options["max_turns"] == 1
    assert options["run_config"].workflow_name == "CFIN " + LOG_PROMPT_VERSIONS[stage]
    assert options["run_config"].tracing_disabled
    assert options["run_config"].trace_metadata["workflow_version"] == "log-only-v1"
    assert ledger.pending == set()
    assert instance.usage == {"input_tokens": 100, "output_tokens": 20}
    assert instance.cost_usd > Decimal(0)
    trace = ledger.reconciliations[0][3]["trace_payload"]
    assert trace["output"]["binding"] == binding()
    assert trace["output"]["stage"] == stage
    assert trace["output"]["output"] == output.model_dump(mode="json")
    assert trace["output"]["input_sha256"] == instance.stage_input_hashes[stage]
    assert trace["validation_status"] == "pending_workflow_validation"
    schema = AgentOutputSchema(type(output))
    assert schema.is_strict_json_schema()
    assert schema.validate_json(output.model_dump_json()) == output


@pytest.mark.parametrize("stage", ["agent1", "agent2"])
def test_history_is_rejected_before_extraction_or_selection_dispatch(
    monkeypatch, configured, stage
):
    ledger = Ledger()
    received = install_response(monkeypatch, ledger)
    data = payload(stage)
    data["history"] = {"past_case": "historical diagnosis"}
    with pytest.raises(RuntimeError, match="stage boundary"):
        execute(adapter(configured, ledger), stage, data)
    assert not received and not ledger.reservations


def test_wrong_output_schema_and_prompt_versions_block_before_reservation(monkeypatch, configured):
    ledger = Ledger()
    received = install_response(monkeypatch, ledger)
    instance = adapter(configured, ledger)
    with pytest.raises(RuntimeError, match="Output contract"):
        asyncio.run(instance.execute("agent1", payload("agent1"), LogSummary, None))
    data = payload("agent1")
    data["binding"]["prompt_versions"]["agent1"] = "retired-prompt"
    with pytest.raises(RuntimeError, match="incompatible prompt"):
        execute(instance, data=data)
    assert not received and not ledger.reservations


def test_capacity_is_checked_before_reservation(monkeypatch, configured):
    ledger = Ledger()
    received = install_response(monkeypatch, ledger)
    data = payload("agent1")
    data["sources"][0]["lines"][0]["text"] = "€" * model_adapter.MAX_INPUT_BOUND
    with pytest.raises(RuntimeError, match="Input exceeds"):
        execute(adapter(configured, ledger), data=data)
    assert not received and not ledger.reservations


def saved_envelope(monkeypatch, configured):
    ledger = Ledger()
    install_response(monkeypatch, ledger)
    instance = adapter(configured, ledger)
    output = execute(instance)
    asyncio.run(instance.record_validated("agent1", output, binding=binding()))
    assert ledger.saved[0][1] == ledger.reconciliations[0][3]["trace_payload"]["output"]
    return ledger.saved[0][1]


def test_same_run_envelope_reuse_requires_stage_input_and_revalidates_output(
    monkeypatch, configured
):
    cached = saved_envelope(monkeypatch, configured)
    ledger = Ledger()
    ledger.cached_outputs["agent1"] = cached
    received = install_response(monkeypatch, ledger)
    instance = adapter(configured, ledger)
    data = payload("agent1")
    data["retry_instruction"] = "Return the same schema with exact source text."
    assert execute(instance, data=data) == outputs()["agent1"]
    assert not received and not ledger.reservations
    assert instance.stage_reuses == {"agent1": "validated_or_reconciled_same_run_candidate"}


@pytest.mark.parametrize(
    "setting,value",
    [
        ("model_agent_1", "gpt-6-sol"),
        ("model_agent_2", "gpt-6-sol"),
        ("model_agent_3", "gpt-6-sol"),
        ("model_reasoning_effort", "high"),
    ],
)
def test_changed_runtime_model_configuration_cannot_reuse_an_existing_checkpoint(
    monkeypatch, configured, setting, value
):
    cached = saved_envelope(monkeypatch, configured)
    ledger = Ledger()
    ledger.cached_outputs["agent1"] = cached
    received = install_response(monkeypatch, ledger)
    restarted = adapter(configured.model_copy(update={setting: value}), ledger)
    with pytest.raises(RuntimeError, match="incompatible model configuration"):
        execute(restarted)
    assert not received and not ledger.reservations
    assert not restarted.stage_reuses


def test_missing_model_configuration_is_not_filled_from_current_defaults(monkeypatch, configured):
    ledger = Ledger()
    received = install_response(monkeypatch, ledger)
    data = payload("agent1")
    del data["binding"]["model_configuration"]
    with pytest.raises(ValueError, match="model_configuration"):
        execute(adapter(configured, ledger), data=data)
    assert not received and not ledger.reservations


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "another-workspace"),
        ("run_id", "another-run"),
        ("case_id", "another-case"),
        ("attempt_id", "another-attempt"),
        ("input_revision", "another-revision"),
        ("source_manifest_sha256", "b" * 64),
        ("workflow_version", "legacy-v1"),
        ("schema_version", "legacy-v1"),
        ("prompt_versions", {**LOG_PROMPT_VERSIONS, "agent1": "older-prompt"}),
    ],
)
def test_stale_or_cross_scope_checkpoint_is_rejected_without_dispatch(
    monkeypatch, configured, field, value
):
    cached = copy.deepcopy(saved_envelope(monkeypatch, configured))
    cached["binding"][field] = value
    ledger = Ledger()
    ledger.cached_outputs["agent1"] = cached
    received = install_response(monkeypatch, ledger)
    with pytest.raises((ValueError, RuntimeError)):
        execute(adapter(configured, ledger))
    assert not received and not ledger.reservations


@pytest.mark.parametrize("candidate", [{"run_id": "old-run"}, {"entries": []}])
def test_raw_or_legacy_checkpoint_is_not_treated_as_a_factual_candidate(
    monkeypatch, configured, candidate
):
    ledger = Ledger()
    ledger.cached_outputs["agent1"] = candidate
    received = install_response(monkeypatch, ledger)
    with pytest.raises(ValueError):
        execute(adapter(configured, ledger))
    assert not received and not ledger.reservations


def test_changed_source_payload_invalidates_a_matching_binding_checkpoint(monkeypatch, configured):
    cached = saved_envelope(monkeypatch, configured)
    ledger = Ledger()
    ledger.cached_outputs["agent1"] = cached
    received = install_response(monkeypatch, ledger)
    data = payload("agent1")
    data["sources"][0]["lines"][0]["text"] = "Changed input under same binding."
    with pytest.raises(RuntimeError, match="Cached stage"):
        execute(adapter(configured, ledger), data=data)
    assert not received and not ledger.reservations


@pytest.mark.parametrize("stage,field", [("agent2", "extracted"), ("agent3", "history")])
def test_changed_upstream_evidence_or_history_invalidates_checkpoint(
    monkeypatch, configured, stage, field
):
    original_ledger = Ledger()
    install_response(monkeypatch, original_ledger)
    original_adapter = adapter(configured, original_ledger)
    output = execute(original_adapter, stage)
    asyncio.run(original_adapter.record_validated(stage, output))
    ledger = Ledger()
    ledger.cached_outputs[stage] = original_ledger.saved[0][1]
    received = install_response(monkeypatch, ledger)
    changed = payload(stage)
    if field == "extracted":
        changed[field]["entries"][0]["ambiguity"] = "A revised source interpretation."
    else:
        changed[field]["status"] = "unavailable"
    with pytest.raises(RuntimeError, match="Cached stage"):
        execute(adapter(configured, ledger), stage, changed)
    assert not received and not ledger.reservations


def test_cached_output_still_has_to_match_the_stage_schema(monkeypatch, configured):
    cached = saved_envelope(monkeypatch, configured)
    cached["output"] = outputs()["agent2"].model_dump(mode="json")
    ledger = Ledger()
    ledger.cached_outputs["agent1"] = cached
    received = install_response(monkeypatch, ledger)
    with pytest.raises(ValueError, match="Stage envelope output"):
        execute(adapter(configured, ledger))
    assert not received and not ledger.reservations


def test_validated_record_must_have_an_application_owned_binding(monkeypatch, configured):
    ledger = Ledger()
    install_response(monkeypatch, ledger)
    instance = adapter(configured, ledger)
    with pytest.raises(RuntimeError, match="execution binding"):
        asyncio.run(instance.record_validated("agent1", outputs()["agent1"], binding=binding()))
    output = execute(instance)
    altered = {**binding(), "run_id": "model-chosen-run"}
    with pytest.raises(RuntimeError, match="execution binding"):
        asyncio.run(instance.record_validated("agent1", output, binding=altered))
    assert ledger.saved == []


def test_malformed_factual_response_retains_reserve_for_separately_reserved_retry(
    monkeypatch, configured
):
    ledger = Ledger()
    install_response(monkeypatch, ledger, error=ModelBehaviorError("invalid output"))
    instance = adapter(configured, ledger)
    with pytest.raises(RetryableStageError, match="malformed structured output"):
        execute(instance)
    assert ledger.pending == {"reservation-1"}
    install_response(monkeypatch, ledger)
    assert execute(instance) == outputs()["agent1"]
    assert len(ledger.reservations) == 2
    assert ledger.pending == {"reservation-1"}
    assert instance.dispatch_counts["agent1"] == 2
    assert not instance.usage_complete


@pytest.mark.parametrize("input_tokens,output_tokens", [(0, 0), (True, 1), (None, 1), (1, -1)])
def test_invalid_factual_usage_retains_reserve_and_withholds_output(
    monkeypatch, configured, input_tokens, output_tokens
):
    ledger = Ledger()
    install_response(monkeypatch, ledger, input_tokens=input_tokens, output_tokens=output_tokens)
    with pytest.raises(RuntimeError, match="usage"):
        execute(adapter(configured, ledger))
    assert ledger.pending == {"reservation-1"}
    assert not ledger.reconciliations
