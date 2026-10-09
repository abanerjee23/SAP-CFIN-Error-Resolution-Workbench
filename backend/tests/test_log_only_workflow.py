"""Software handoff checks with explicit test doubles; these are not LLM evals."""

import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from cfin.log_only_contracts import (
    EvidenceSelection,
    ExecutionBinding,
    ExtractedEntry,
    ExtractedLog,
    LogSummary,
    PromptVersions,
    SourceSpan,
    SummaryStatement,
    project_factual_result,
)
from cfin.log_only_inputs import (
    MAX_LOG_BYTES,
    MAX_LOG_LINES,
    LogCapacityError,
    LogInputs,
    OriginalUpload,
    prepare_log_inputs,
)
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.log_only_sources import manifest_fingerprint
from cfin.log_only_workflow import LogWorkflowExecutor
from cfin.stage_errors import RetryableStageError


def inputs_for(*raw):
    return prepare_log_inputs(
        [OriginalUpload("original.txt", item) for item in (raw or (b"Error for item 0001\r\n",))],
        provenance="synthetic",
        intake_id=UUID("d2ac96a5-2b4c-4bd7-9e19-233ff8168b91"),
    )


def binding_for(inputs, **changes):
    return ExecutionBinding(
        **{
            "workspace_id": "workspace-1",
            "run_id": "run-1",
            "case_id": "case-1",
            "attempt_id": "application-attempt-1",
            "input_revision": "1",
            "source_manifest_sha256": manifest_fingerprint(inputs.manifest),
            "prompt_versions": PromptVersions(**LOG_PROMPT_VERSIONS),
            "model_configuration": {
                "agent1": "gpt-6-luna",
                "agent2": "gpt-6.1-sol",
                "agent3": "gpt-6.1-sol",
                "reasoning_effort": "medium",
            },
            **changes,
        }
    )


def extraction_for(inputs):
    # A test double representing the whole source as unclassified, never a
    # production deterministic extractor or a golden semantic model answer.
    return ExtractedLog(
        entries=[
            ExtractedEntry(
                entry_id=f"entry-{number}",
                source_id=source.source_id,
                source_version=source.source_version,
                source_span=SourceSpan(line_start=1, line_end=source.readable.line_count),
                kind="unclassified",
                raw_text=inputs.originals[(source.source_id, source.source_version)].decode(),
            )
            for number, source in enumerate(inputs.manifest.sources)
            if source.readable.line_count
        ]
    )


class RecordingAdapter:
    evaluation_only = True
    workflow_version = "log-only-v1"

    def __init__(self, inputs):
        extracted = extraction_for(inputs)
        selected = [entry.entry_id for entry in extracted.entries]
        statement = SummaryStatement(
            text="The supplied log reports an error.", supporting_entry_ids=selected or ["empty"]
        )
        self.outputs = {
            "agent1": extracted,
            "agent2": EvidenceSelection(selected_entry_ids=selected),
            "agent3": LogSummary(title=statement, statements=[statement]),
        }
        self.calls = []
        self.saved = []
        self.failed = []

    async def execute(self, stage, payload, output_type, inputs):
        self.calls.append((stage, payload, output_type))
        result = self.outputs[stage]
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def record_validated(self, stage, output, *, binding):
        self.saved.append((stage, output, binding))

    async def record_failed(self, stage):
        self.failed.append(stage)


def run(inputs=None, adapter=None, **kwargs):
    inputs = inputs or inputs_for()
    adapter = adapter or RecordingAdapter(inputs)
    return asyncio.run(LogWorkflowExecutor(adapter, binding_for(inputs), **kwargs).run(inputs))


def test_exact_multiple_originals_three_stages_and_app_owned_identity():
    inputs = inputs_for(b"item=0001\r\nError\r\n", b"item=0001\nError\n")
    adapter = RecordingAdapter(inputs)
    execution = run(inputs, adapter)
    assert execution.result.outcome == "completed"
    assert execution.result.run_id == "run-1"
    assert execution.result.history.status == "not_searched"
    assert execution.evaluation_only
    assert [stage for stage, *_ in adapter.calls] == ["agent1", "agent2", "agent3"]
    assert len(adapter.saved) == 3
    assert all(binding == binding_for(inputs) for _, _, binding in adapter.saved)
    assert set(adapter.calls[0][1]) == {"binding", "sources"}
    assert set(adapter.calls[1][1]) == {"binding", "extracted", "source_manifest"}
    assert set(adapter.calls[2][1]) == {"binding", "evidence", "history"}
    assert adapter.calls[0][1]["sources"][0]["lines"][0]["text"] == "item=0001\r\n"
    selected = adapter.calls[2][1]["evidence"]["selected_entries"]
    assert selected == execution.result.extraction.model_dump(mode="json")["entries"]
    public = project_factual_result(execution.result).model_dump()
    assert public["title"] == execution.result.summary.title.model_dump()
    assert not {"run_id", "prompt_versions", "binding", "candidates", "usage"} & public.keys()


def test_partial_coverage_and_agent_limitations_are_carried_to_summary_and_result():
    inputs = inputs_for(b"Error\nUnfamiliar section\n")
    adapter = RecordingAdapter(inputs)
    entry = adapter.outputs["agent1"].entries[0]
    adapter.outputs["agent1"] = ExtractedLog(
        entries=[
            entry.model_copy(
                update={"raw_text": "Error\n", "source_span": SourceSpan(line_start=1, line_end=1)}
            )
        ],
        extraction_limitations=["The custom label is unclear."],
    )
    result = run(inputs, adapter).result
    assert result.outcome == "completed"
    assert "The custom label is unclear." in result.limitations
    assert any("lines 2–2" in item for item in result.limitations)
    assert tuple(adapter.calls[2][1]["evidence"]["extraction_limitations"]) == result.limitations


@pytest.mark.parametrize("raw", [b"", b" \n\r\n"])
def test_empty_or_blank_original_has_no_model_calls_or_fabricated_title(raw):
    inputs = inputs_for(raw)
    adapter = RecordingAdapter(inputs)
    result = run(inputs, adapter).result
    assert result.outcome == "no_usable_evidence"
    assert result.failure_reason
    assert result.summary is None
    assert adapter.calls == []
    assert project_factual_result(result).title is None


@pytest.mark.parametrize("empty_stage", ["agent1", "agent2"])
def test_empty_extraction_or_selection_stops_before_summary(empty_stage):
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.outputs[empty_stage] = (
        ExtractedLog(entries=[])
        if empty_stage == "agent1"
        else EvidenceSelection(selected_entry_ids=[])
    )
    result = run(inputs, adapter).result
    assert result.outcome == "no_usable_evidence"
    assert result.summary is None
    assert "agent3" not in [stage for stage, *_ in adapter.calls]


def test_wrong_quote_is_retried_once_and_never_checkpointed():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    good = adapter.outputs["agent1"]
    bad = good.model_copy(
        update={
            "entries": [good.entries[0].model_copy(update={"raw_text": "Account 0001 is fixed."})]
        }
    )
    adapter.outputs["agent1"] = [bad, good]
    result = run(inputs, adapter, max_retries=1)
    assert result.result.outcome == "completed"
    assert result.stage_calls == {"agent1": 2, "agent2": 1, "agent3": 1}
    assert adapter.failed == ["agent1"]
    assert adapter.saved[0][1] == good


def test_selecting_only_a_blank_separator_cannot_generate_a_cited_title():
    inputs = inputs_for(b"Error\n\n")
    adapter = RecordingAdapter(inputs)
    source = inputs.manifest.sources[0]
    adapter.outputs["agent1"] = ExtractedLog(
        entries=[
            ExtractedEntry(
                entry_id=entry_id,
                source_id=source.source_id,
                source_version=source.source_version,
                source_span=SourceSpan(line_start=line, line_end=line),
                kind="unclassified",
                raw_text=text,
            )
            for entry_id, line, text in [("error", 1, "Error\n"), ("blank", 2, "\n")]
        ]
    )
    adapter.outputs["agent2"] = EvidenceSelection(selected_entry_ids=["blank"])
    result = run(inputs, adapter).result
    assert result.outcome == "no_usable_evidence"
    assert result.summary is None
    assert not any(stage == "agent3" for stage, *_ in adapter.calls)


def test_transient_failure_retry_keeps_same_binding():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.outputs["agent1"] = [
        RetryableStageError("private provider error"),
        adapter.outputs["agent1"],
    ]
    result = run(inputs, adapter, max_retries=1)
    assert result.result.outcome == "completed"
    assert adapter.calls[0][1]["binding"] == adapter.calls[1][1]["binding"]
    assert "retry_instruction" in adapter.calls[1][1]


@pytest.mark.parametrize("bad_stage", ["agent1", "agent2", "agent3"])
def test_stage_failure_is_explicit_and_provider_details_are_not_published(bad_stage):
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.outputs[bad_stage] = RuntimeError("secret/provider/source-content")
    execution = run(inputs, adapter)
    assert execution.result.outcome == "failed"
    assert execution.result.summary is None
    assert execution.result.failure_reason.startswith(bad_stage)
    assert "secret" not in str(execution.as_dict())
    assert bad_stage not in [stage for stage, *_ in adapter.saved]


def test_unknown_usage_blocks_factual_publication():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.usage_complete = False
    execution = run(inputs, adapter)
    assert not execution.usage_complete
    assert execution.result.outcome == "failed"
    assert execution.result.summary is None
    assert adapter.calls == []


def test_checkpoint_storage_failure_stops_downstream_stages():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)

    async def fail_checkpoint(*args, **kwargs):
        raise HTTPException(503, "private storage details")

    adapter.record_validated = fail_checkpoint
    result = run(inputs, adapter).result
    assert result.outcome == "failed"
    assert [stage for stage, *_ in adapter.calls] == ["agent1"]
    assert "private" not in result.failure_reason


def test_lease_cancellation_propagates_instead_of_publishing_failure():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)

    async def cancel_stage(*args, **kwargs):
        raise asyncio.CancelledError()

    adapter.execute = cancel_stage
    with pytest.raises(asyncio.CancelledError):
        run(inputs, adapter)
    assert adapter.saved == []


def test_ambiguous_entry_cannot_disappear_at_selection():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    entry = (
        adapter.outputs["agent1"].entries[0].model_copy(update={"ambiguity": "Conflicting status"})
    )
    adapter.outputs["agent1"] = ExtractedLog(entries=[entry])
    result = run(inputs, adapter).result
    assert result.outcome == "failed"
    assert result.failure_reason.startswith("agent2")
    assert not any(stage == "agent3" for stage, *_ in adapter.calls)


def test_altered_source_manifest_binding_fails_before_dispatch():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    runner = LogWorkflowExecutor(adapter, binding_for(inputs, source_manifest_sha256="0" * 64))
    with pytest.raises(ValueError, match="source manifest"):
        asyncio.run(runner.run(inputs))
    assert adapter.calls == []


def test_legacy_adapter_and_wrong_prompt_version_are_rejected():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.workflow_version = "legacy-v1"
    with pytest.raises(ValueError, match="compatible adapter"):
        LogWorkflowExecutor(adapter, binding_for(inputs))
    adapter.workflow_version = "log-only-v1"
    with pytest.raises(ValueError, match="prompt versions"):
        LogWorkflowExecutor(
            adapter,
            binding_for(
                inputs,
                prompt_versions=PromptVersions(
                    **{**LOG_PROMPT_VERSIONS, "agent1": "legacy-prompt"}
                ),
            ),
        )


def test_resumed_dispatch_budget_cannot_start_a_third_call():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.dispatch_counts = {"agent1": 2, "agent2": 0, "agent3": 0}
    result = run(inputs, adapter, max_retries=1).result
    assert result.outcome == "failed"
    assert adapter.calls == []


def test_expired_stage_budget_does_not_dispatch():
    inputs = inputs_for()
    adapter = RecordingAdapter(inputs)
    adapter.stage_remaining_seconds = {"agent1": 0}
    assert run(inputs, adapter).result.outcome == "failed"
    assert adapter.calls == []


def test_intake_receipt_is_repeatable_but_versions_change_with_bytes():
    first = inputs_for(b"0001\r\n")
    retry = inputs_for(b"0001\r\n")
    changed = inputs_for(b"0001\n")
    assert first == retry
    assert first.manifest.sources[0].source_id == changed.manifest.sources[0].source_id
    assert first.manifest.sources[0].source_version != changed.manifest.sources[0].source_version
    assert first.originals != changed.originals


def test_original_mapping_is_immutable_and_tampering_is_rejected():
    inputs = inputs_for()
    key = next(iter(inputs.originals))
    with pytest.raises(TypeError):
        inputs.originals[key] = b"changed"
    with pytest.raises(ValueError, match="bytes or readable metadata"):
        LogInputs(manifest=inputs.manifest, originals={key: b"changed"})
    with pytest.raises(ValueError, match="immutable bytes"):
        LogInputs(manifest=inputs.manifest, originals={key: bytearray(inputs.originals[key])})


@pytest.mark.parametrize("raw", [b"x" * (MAX_LOG_BYTES + 1), b"x\n" * (MAX_LOG_LINES + 1)])
def test_complete_upload_capacity_is_rejected_without_truncation(raw):
    with pytest.raises(LogCapacityError):
        inputs_for(raw)


def test_new_intake_rejects_non_utf8_and_does_not_relabel_real_provenance():
    with pytest.raises(ValueError, match="UTF-8"):
        inputs_for(b"\xff")
    inputs = prepare_log_inputs(
        [OriginalUpload("real.txt", b"Supplied text")], provenance="user_supplied"
    )
    assert inputs.manifest.sources[0].provenance == "user_supplied"


@pytest.mark.parametrize("filename", ["../input.txt", "folder/input.txt", "folder\\input.txt", " "])
def test_intake_rejects_unsafe_filenames(filename):
    with pytest.raises(ValueError, match="filename"):
        prepare_log_inputs([OriginalUpload(filename, b"Error")], provenance="synthetic")
