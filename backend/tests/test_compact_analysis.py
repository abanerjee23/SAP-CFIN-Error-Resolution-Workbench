"""Deterministic integrity and usage checks; live semantic review is separate."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_error_analysis_model_adapter import adapter, binding
from test_factual_intake import ACTOR, Service, User, body
from test_model_adapter import RecordingLedger

from cfin.compact_analysis import (
    CaseNarrative,
    CompactExtraction,
    hydrate_extraction,
    hydrate_narrative,
)
from cfin.config import Settings
from cfin.error_analysis_contracts import CaseContent, ErrorAnalysisStageEnvelope
from cfin.error_analysis_prompts import COMPACT_PROMPT_VERSIONS
from cfin.factual_intake import ErrorAnalysisIntakeRequest, commit_error_analysis_intake
from cfin.log_only_contracts import ExtractedLog
from cfin.log_only_inputs import OriginalUpload, prepare_log_inputs


def original():
    return prepare_log_inputs([
        OriginalUpload("first.log", b"source_system=ERP-A | source_company_code=0010\r\n"
                       b"\r\ndocument_number=0000123600\n"),
        OriginalUpload("second.log", b"target_company_code=2000\nUnknown error.\n"),
    ], provenance="synthetic")


@pytest.mark.parametrize("profile,effort", [("baseline", None), ("compact", "medium"),
                                          ("fast", "low")])
def test_intake_pins_profile_and_efforts_without_changing_diagnosis(profile, effort):
    service = Service()
    asyncio.run(commit_error_analysis_intake(
        User(), service,
        Settings(_env_file=None, log_only_enabled=True, error_analysis_profile=profile),
        "user-token", ACTOR,
        ErrorAnalysisIntakeRequest.model_validate(body().model_dump()),
    ))
    payload = service.calls[0][1]
    config = payload["model_configuration"]
    assert config["agent2"] == "gpt-6.1-sol" and config["reasoning_effort"] == "medium"
    if effort:
        assert payload["prompt_versions"] == COMPACT_PROMPT_VERSIONS
        assert config["agent1_reasoning_effort"] == config["agent3_reasoning_effort"] == effort
        assert config["agent2_reasoning_effort"] == "medium"
    else:
        assert "agent1_reasoning_effort" not in config
        assert payload["prompt_versions"]["agent1"] == "error-analysis-extraction-v1"


def compact():
    return {"entries": [
        {"source": 1, "start": 1, "end": 3, "kind": "metadata", "fields": [
            {"name_as_logged": "document_number", "value_as_logged": "0000123600",
             "context_as_logged": None}]},
        {"source": 2, "start": 1, "end": 1, "kind": "metadata"},
        {"source": 2, "start": 2, "end": 2, "kind": "unclassified",
         "ambiguity": "No cause information is logged."},
    ]}


@pytest.mark.parametrize("profile,diagnosis,writer,effort", [
    ("writer_luna", "gpt-6.1-sol", "gpt-6-luna", "medium"),
    ("writer_low", "gpt-6.1-sol", "gpt-6.1-sol", "low"),
    ("all_luna", "gpt-6-luna", "gpt-6-luna", "medium"),
])
def test_model_matrix_intake_pins_models_without_changing_prompts(
    profile, diagnosis, writer, effort,
):
    service = Service()
    asyncio.run(commit_error_analysis_intake(
        User(), service,
        Settings(_env_file=None, log_only_enabled=True, error_analysis_profile=profile),
        "user-token", ACTOR, ErrorAnalysisIntakeRequest.model_validate(body().model_dump()),
    ))
    payload = service.calls[0][1]
    assert payload["prompt_versions"] == COMPACT_PROMPT_VERSIONS
    assert payload["model_configuration"] == {
        "agent1": "gpt-6-luna", "agent2": diagnosis, "agent3": writer,
        "reasoning_effort": "medium", "agent1_reasoning_effort": "medium",
        "agent2_reasoning_effort": "medium", "agent3_reasoning_effort": effort,
    }


def test_hydration_restores_exact_crlf_blanks_source_versions_and_leading_zeros():
    inputs = original()
    value = compact()
    value["entries"][0]["message_variables"] = value["entries"][0]["fields"]
    result = hydrate_extraction(CompactExtraction.model_validate(value), inputs)
    assert result.entries[0].raw_text == next(iter(inputs.originals.values())).decode()
    assert result.entries[0].fields[0].value_as_logged == "0000123600"
    assert result.entries[0].message_variables[0].value_as_logged == "0000123600"
    assert result.entries[1].source_id == inputs.manifest.sources[1].source_id
    assert result.entries[1].raw_text == "target_company_code=2000\n"
    assert result.entries[2].ambiguity == "No cause information is logged."
    assert len({e.entry_id for e in result.entries}) == 3


@pytest.mark.parametrize(
    "mutation", ["source", "span", "omission", "overlap", "invented", "invented_name"]
)
def test_hydration_rejects_invalid_source_regions_and_fabricated_fields(mutation):
    value = compact()
    if mutation == "source":
        value["entries"][0]["source"] = 99
    elif mutation == "span":
        value["entries"][0]["end"] = 1_000_000_000
    elif mutation == "omission":
        value["entries"].pop()
    elif mutation == "overlap":
        value["entries"].append(value["entries"][0])
    elif mutation == "invented_name":
        value["entries"][0]["fields"][0]["name_as_logged"] = "source document identifier"
    else:
        value["entries"][0]["fields"][0]["value_as_logged"] = "9999999999"
    with pytest.raises(ValueError):
        hydrate_extraction(CompactExtraction.model_validate(value), original())


def narrative():
    statement = {"text": "The log reports an unspecified error.",
                 "supporting_entry_ids": ["entry-3"]}
    return {"title": statement, "what_happened": [statement],
            "evidence_entry_ids": ["entry-3"]}


def test_narrative_quotes_are_copied_from_source_not_regenerated():
    extracted = hydrate_extraction(CompactExtraction.model_validate(compact()), original())
    content = hydrate_narrative(CaseNarrative.model_validate(narrative()), extracted)
    assert content.original_log_evidence[0].text == "Unknown error."
    assert content.document_context[0].text == "document_number: 0000123600"
    assert content.document_context[0].supporting_entry_ids == ["entry-1"]
    for refs in (["missing"], ["entry-3", "entry-3"]):
        with pytest.raises(ValueError):
            hydrate_narrative(CaseNarrative.model_validate(
                {**narrative(), "evidence_entry_ids": refs}), extracted)


@pytest.mark.parametrize("stage,invalid", [("agent1", False), ("agent1", True), ("agent3", False)])
def test_compact_adapter_pins_effort_and_reconciles_hydration_before_publication(
    monkeypatch, stage, invalid,
):
    instance = adapter()
    ledger = RecordingLedger()
    instance.ledger = ledger
    inputs = original()
    run_binding = binding()
    run_binding["prompt_versions"] = COMPACT_PROMPT_VERSIONS
    run_binding["model_configuration"].update({
        "agent1_reasoning_effort": "low", "agent2_reasoning_effort": "medium",
        "agent3_reasoning_effort": "low",
    })
    candidate = compact() if stage == "agent1" else narrative()
    if invalid:
        candidate["entries"].pop()
    received = []

    async def run(agent, encoded, **kwargs):
        received.append((agent, json.loads(encoded)))
        assert ledger.pending
        return SimpleNamespace(final_output=candidate, raw_responses=[],
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace(
                                   requests=1, input_tokens=100, output_tokens=50)))

    monkeypatch.setattr("cfin.model_adapter.Runner.run", run)
    payload = {"binding": run_binding, "sources": inputs.extraction_payload()}
    output_type = ExtractedLog
    if stage == "agent3":
        payload.update({"extracted": hydrate_extraction(
            CompactExtraction.model_validate(compact()), inputs).model_dump(mode="json"),
            "analysis": {}, "history": {}})
        output_type = CaseContent
    if invalid:
        with pytest.raises(ValueError, match="Compact output"):
            asyncio.run(instance.execute(stage, payload, output_type, inputs))
    else:
        result = asyncio.run(instance.execute(stage, payload, output_type, inputs))
        output = ledger.trace_payloads[0]["trace_payload"]["output"]
        envelope = ErrorAnalysisStageEnvelope.model_validate(output)
        assert envelope.output == result
        # Resume uses the hydrated same-run candidate without another paid call.
        ledger.cached_outputs = {stage: output}
        assert asyncio.run(instance.execute(stage, payload, output_type, inputs)) == result
        assert len(received) == 1
    assert ledger.pending == set() and instance.usage_complete
    assert received[0][0].model_settings.reasoning.effort == "low"
    assert "binding" not in received[0][1]
    trace = ledger.trace_payloads[0]["trace_payload"]
    assert trace["wire_input"]["payload"] == received[0][1]
    assert trace["raw_model_output"] == candidate
    assert trace["effective_reasoning_effort"] == "low"
    if stage == "agent3":
        assert "sources" not in received[0][1]
    else:
        assert received[0][1]["sources"][0]["source"] == 1
    asyncio.run(instance.close())
