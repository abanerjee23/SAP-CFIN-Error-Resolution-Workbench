import asyncio
import copy
import json
from datetime import date

import pytest

from cfin.evaluation import build_eval_inputs
from cfin.workflow import (
    ScriptedStageAdapter,
    WorkflowExecutor,
    build_diagnosis,
    build_preparation,
    fingerprint,
)


class TamperingAdapter(ScriptedStageAdapter):
    def __init__(self, stage, tamper):
        self.stage = stage
        self.tamper = tamper
        self.received = []

    async def execute(self, stage, payload, output_type, inputs):
        self.received.append((stage, copy.deepcopy(payload)))
        output = await super().execute(stage, payload, output_type, inputs)
        if stage == self.stage:
            data = output.model_dump(mode="json")
            self.tamper(data, inputs)
            return data
        return output


def run(adapter, *, case_id="md01-reviewed-simulation", timeout=60):
    inputs = build_eval_inputs(case_id)
    executor = WorkflowExecutor(
        adapter, run_id="security-test-run", timeout_seconds=timeout, as_of=date(2026, 9, 30)
    )
    return asyncio.run(executor.run(inputs))


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "another-run"),
        ("attempt_id", "MD01-forged-attempt"),
        ("input_source_version", "forged-version"),
    ],
)
@pytest.mark.parametrize("stage", ["agent1", "agent2", "agent3"])
def test_changed_handoff_identifiers_stop_publication(stage, field, value):
    adapter = TamperingAdapter(stage, lambda data, _: data.update({field: value}))
    result = run(adapter)
    assert result.errors == (stage + "_failed_validation_or_execution",)
    assert not result.routing.agent3_eligible
    assert result.brief is None
    if stage == "agent1":
        assert result.stage_calls == {"agent1": 1, "agent2": 0, "agent3": 0}
    elif stage == "agent2":
        assert result.stage_calls["agent3"] == 0


def test_changed_canonical_identity_cannot_replace_supplied_document():
    def tamper(data, _):
        data["identity"]["document_number"] = "0000999999; DROP TABLE cases"

    result = run(TamperingAdapter("agent1", tamper))
    assert result.errors
    assert result.stage_calls["agent2"] == 0
    assert not result.routing.agent3_eligible


def test_quote_must_match_original_bytes_and_its_cited_lines():
    def tamper(data, _):
        data["messages"][0]["original_wording"] = "The account has been approved and created."

    result = run(TamperingAdapter("agent1", tamper))
    assert result.errors == ("agent1_failed_validation_or_execution",)
    assert result.stage_calls["agent2"] == 0


@pytest.mark.parametrize("quoted_line,cited_line", [(12, 10), (15, 13)])
def test_correct_original_quote_with_wrong_saved_line_number_is_rejected(quoted_line, cited_line):
    def tamper(data, inputs):
        message = data["messages"][0]
        message["original_wording"] = inputs.original_log.splitlines()[quoted_line - 1]
        citation = message["citations"][0]
        citation.update(line_start=cited_line, line_end=cited_line)

    result = run(TamperingAdapter("agent1", tamper), case_id="md01-pending")
    assert result.errors == ("agent1_failed_validation_or_execution",)
    assert result.preparation is None
    assert result.stage_calls == {"agent1": 1, "agent2": 0, "agent3": 0}


@pytest.mark.parametrize("lookup_index", [-1, 0])
def test_original_quote_with_appended_mapping_or_master_citation_is_rejected(lookup_index):
    def tamper(data, inputs):
        data["messages"][0]["citations"].append(
            inputs.lookups[lookup_index].citations[0].model_dump(mode="json")
        )

    result = run(TamperingAdapter("agent1", tamper), case_id="md01-pending")
    assert result.errors == ("agent1_failed_validation_or_execution",)
    assert result.preparation is None
    assert result.stage_calls == {"agent1": 1, "agent2": 0, "agent3": 0}


def test_preparation_receives_original_numbered_lines_and_reports_prompt_revision():
    adapter = TamperingAdapter("unused", lambda *_: None)
    result = run(adapter, case_id="md01-pending")
    inputs = build_eval_inputs("md01-pending")
    evidence = adapter.received[0][1]["evidence"]
    assert evidence["original_log"] == inputs.original_log
    assert evidence["original_log_lines"] == [
        {"line_number": number, "text": line}
        for number, line in enumerate(inputs.original_log.splitlines(), start=1)
    ]
    assert evidence["original_log_lines"][11]["text"].startswith("Observed target lookup:")
    assert result.errors == ()
    assert result.as_dict()["prompt_version"] == "cfin-specialists-v3"


@pytest.mark.parametrize("stage", ["agent1", "agent2", "agent3"])
def test_invented_citation_locator_cannot_be_published(stage):
    def tamper(data, _):
        if stage == "agent1":
            citation = data["messages"][0]["citations"][0]
            citation["line_end"] = 999
        elif stage == "agent2":
            citation = data["findings"][0]["checks"][0]["citations"][0]
            citation["record_id"] = "invented-mapping-row"
        else:
            data["citations"][0]["record_id"] = "invented-playbook-section"

    result = run(TamperingAdapter(stage, tamper))
    assert result.errors == (stage + "_failed_validation_or_execution",)
    assert result.brief is None
    assert not result.routing.agent3_eligible


@pytest.mark.parametrize("status", ["human_confirmed", "ai_supported"])
def test_invented_human_confirmation_is_rejected_and_not_published(status):
    def tamper(data, inputs):
        mapping = inputs.lookups[-1]
        data["status"] = status
        data["human_confirmation"] = {
            "actor_id": "malicious-model-invented-human",
            "acting_role": "Demo Process Owner",
            "confirmed_at": "2026-09-30T09:00:00Z",
            "rationale": "Model invents a human review",
            "citations": [mapping.citations[0].model_dump(mode="json")],
        }

    result = run(TamperingAdapter("agent2", tamper))
    assert result.errors == ("agent2_failed_validation_or_execution",)
    assert result.stage_calls["agent3"] == 0
    assert result.brief is None
    assert result.diagnosis is None or result.diagnosis.human_confirmation is None
    assert result.diagnosis is None or result.diagnosis.status != "human_confirmed"


def test_empty_human_prerequisites_withholds_the_actionable_brief():
    result = run(TamperingAdapter("agent3", lambda data, _: data.update(unmet_prerequisites=[])))
    assert result.errors == ("agent3_failed_validation_or_execution",)
    assert result.brief is None
    assert not result.routing.agent3_eligible


def test_brief_must_cite_selected_guidance_not_only_a_valid_original_log():
    def tamper(data, inputs):
        data["citations"] = [
            {
                "source_id": inputs.manifest.source_id,
                "source_version": inputs.manifest.source_version,
                "attempt_id": inputs.manifest.attempt_id,
                "line_start": 11,
                "line_end": 13,
            }
        ]

    result = run(TamperingAdapter("agent3", tamper))
    assert result.errors == ("agent3_failed_validation_or_execution",)
    assert result.brief is None
    assert not result.routing.agent3_eligible


def test_pending_references_and_injected_text_never_trigger_agent3():
    for case_id in ("md01-pending", "md01-injected-log", "md01-mapping-only"):
        adapter = TamperingAdapter("unused", lambda *_: None)
        result = run(adapter, case_id=case_id)
        assert not result.errors
        assert result.stage_calls["agent3"] == 0
        assert all(stage != "agent3" for stage, _ in adapter.received)
        assert result.brief is None
        payload = json.dumps(adapter.received)
        assert "0000900123" not in payload
        assert "routing-oracle" not in payload
        assert "simulated-proof" not in payload


def test_missing_identity_bypasses_diagnosis_after_preserving_preparation():
    result = run(ScriptedStageAdapter(), case_id="md01-missing-identity")
    assert result.preparation is not None
    assert result.preparation.identity.document_number is None
    assert result.diagnosis is None
    assert result.stage_calls == {"agent1": 1, "agent2": 0, "agent3": 0}
    assert not result.errors


def test_timeout_cancels_stage_and_preserves_reviewable_failure():
    class HangingAdapter(ScriptedStageAdapter):
        cancelled = False

        async def execute(self, *_):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    adapter = HangingAdapter()
    result = run(adapter, timeout=0.001)
    assert adapter.cancelled
    assert result.errors == ("agent1_failed_validation_or_execution",)
    assert result.stage_calls == {"agent1": 1, "agent2": 0, "agent3": 0}
    assert result.brief is None


def test_failure_diagnostic_does_not_disclose_raw_provider_message():
    class FailedAdapter(ScriptedStageAdapter):
        async def execute(self, *_):
            raise RuntimeError("sensitive-provider-debug-token")

    result = run(FailedAdapter())
    assert result.errors == ("agent1_failed_validation_or_execution",)
    assert "sensitive-provider-debug-token" not in json.dumps(result.as_dict())


def test_scripted_helpers_preserve_identifiers_and_input_fingerprint():
    inputs = build_eval_inputs("md01-pending")
    before = fingerprint(inputs)
    preparation = build_preparation(inputs, "run-fidelity")
    diagnosis = build_diagnosis(inputs, "run-fidelity", date(2026, 9, 30))
    assert preparation.identity == inputs.manifest.identity
    assert preparation.business_context == inputs.manifest.business_context
    assert preparation.identity.document_number == "0000123456"
    assert preparation.identity.source_client == "010"
    assert diagnosis.status == "needs_review"
    assert fingerprint(inputs) == before
