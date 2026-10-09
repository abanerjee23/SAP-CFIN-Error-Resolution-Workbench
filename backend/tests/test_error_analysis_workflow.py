"""Deterministic contract checks for the governed Error Analysis workflow."""

import asyncio
from uuid import UUID

import pytest

from cfin.error_analysis_contracts import (
    CaseContent,
    ErrorAnalysisBinding,
    ErrorAnalysisDraft,
)
from cfin.error_analysis_prompts import ERROR_ANALYSIS_PROMPT_VERSIONS
from cfin.error_analysis_workflow import ErrorAnalysisWorkflowExecutor
from cfin.error_route_registry import InMemoryRouteRegistry
from cfin.log_only_contracts import ExtractedEntry, ExtractedLog, SourceSpan, SummaryStatement
from cfin.log_only_inputs import OriginalUpload, prepare_log_inputs
from cfin.log_only_sources import manifest_fingerprint


def inputs():
    return prepare_log_inputs(
        [
            OriginalUpload(
                "aif-log.txt", b"Document 0000123456 failed: target account unavailable.\n"
            )
        ],
        provenance="synthetic",
        intake_id=UUID("d2ac96a5-2b4c-4bd7-9e19-233ff8168b91"),
    )


def binding(value):
    return ErrorAnalysisBinding(
        workspace_id="workspace-1",
        run_id="run-1",
        case_id="case-1",
        attempt_id="attempt-1",
        input_revision="1",
        source_manifest_sha256=manifest_fingerprint(value.manifest),
        prompt_versions=ERROR_ANALYSIS_PROMPT_VERSIONS,
        model_configuration={
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    )


class Adapter:
    workflow_version = "error-analysis-v1"
    evaluation_only = True
    usage_complete = True
    usage = {"input_tokens": 0, "output_tokens": 0}
    stage_reuses = {}
    cost_usd = 0

    def __init__(self, value):
        source = value.manifest.sources[0]
        self.extraction = ExtractedLog(
            entries=[
                ExtractedEntry(
                    entry_id="entry-1",
                    source_id=source.source_id,
                    source_version=source.source_version,
                    source_span=SourceSpan(line_start=1, line_end=1),
                    kind="message",
                    raw_text="Document 0000123456 failed: target account unavailable.\n",
                )
            ]
        )
        statement = SummaryStatement(
            text="The log reports that document 0000123456 could not post.",
            supporting_entry_ids=["entry-1"],
        )
        self.outputs = {
            "agent1": self.extraction,
            "agent2": ErrorAnalysisDraft(
                category_id="master_data",
                cause_hypothesis="Required target account master data may be unavailable.",
                confidence="medium",
                supporting_entry_ids=["entry-1"],
            ),
            "agent3": CaseContent(
                title=statement,
                what_happened=(statement,),
                document_context=(statement,),
                original_log_evidence=(statement,),
            ),
        }
        self.calls = []
        self.saved = []

    async def execute(self, stage, payload, output_type, value):
        self.calls.append((stage, payload))
        return self.outputs[stage]

    async def record_validated(self, stage, output, *, binding):
        self.saved.append((stage, output, binding))


def test_error_analysis_keeps_agent2_from_originals_and_attaches_code_route():
    value = inputs()
    adapter = Adapter(value)
    outcome = asyncio.run(
        ErrorAnalysisWorkflowExecutor(adapter, binding(value), InMemoryRouteRegistry()).run(
            value, routing_context={"interface": "AIF"}
        )
    )
    assert outcome.result.outcome == "completed"
    assert outcome.result.analysis.category_id == "master_data"
    assert outcome.result.analysis.route.owner_role == "mdg_process_owner"
    assert [stage for stage, _ in adapter.calls] == ["agent1", "agent2", "agent3"]
    assert set(adapter.calls[1][1]) == {"binding", "extracted", "taxonomy"}
    assert "sources" not in adapter.calls[1][1]
    assert "history" not in adapter.calls[1][1]
    assert {"sources", "analysis", "history"} <= set(adapter.calls[2][1])
    assert [stage for stage, *_ in adapter.saved] == ["agent1", "agent2", "agent3"]


def test_pilot_unclassified_is_a_valid_live_result_when_evidence_gap_is_explicit():
    value = inputs()
    adapter = Adapter(value)
    adapter.outputs["agent2"] = ErrorAnalysisDraft(
        category_id="unclassified",
        cause_hypothesis="The supplied evidence does not support a maintained error category.",
        confidence="low",
        supporting_entry_ids=["entry-1"],
        gaps=["The error code and affected object are not supplied."],
    )
    outcome = asyncio.run(
        ErrorAnalysisWorkflowExecutor(adapter, binding(value), InMemoryRouteRegistry()).run(value)
    )
    assert outcome.result.outcome == "completed"
    assert outcome.result.analysis.route.route_kind == "unclassified"
    assert outcome.result.analysis.route.owner_role == "cfin_exception_manager"


@pytest.mark.parametrize("always_stuck", [False, True])
def test_slow_stage_is_cancelled_then_retried_once(always_stuck):
    value = inputs()
    adapter = Adapter(value)
    original_execute = adapter.execute
    attempts = []
    cancelled = []

    async def slow(stage, payload, output_type, source):
        if stage == "agent1":
            attempts.append(stage)
            if always_stuck or len(attempts) == 1:
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    cancelled.append(stage)
                    raise
        return await original_execute(stage, payload, output_type, source)

    adapter.execute = slow
    result = asyncio.run(ErrorAnalysisWorkflowExecutor(
        adapter, binding(value), InMemoryRouteRegistry(), timeout_seconds=0.01, max_retries=1,
    ).run(value))
    assert len(attempts) == 2
    assert len(cancelled) == (2 if always_stuck else 1)
    assert result.result.outcome == ("failed" if always_stuck else "completed")
    if always_stuck:
        assert result.result.case_content is None
        assert "timeout" in result.result.failure_reason


@pytest.mark.parametrize(
    ("category", "route_kind", "owner"),
    [
        ("master_data", "pilot", "mdg_process_owner"),
        ("mapping", "pilot", "mdg_process_owner"),
        ("integration_mapping", "manual", "cfin_exception_manager"),
        ("master_data_restriction", "manual", "cfin_exception_manager"),
        ("posting_period", "manual", "cfin_exception_manager"),
        ("tax", "manual", "cfin_exception_manager"),
        ("currency", "manual", "cfin_exception_manager"),
        ("document_splitting", "manual", "cfin_exception_manager"),
        ("account_assignment", "manual", "cfin_exception_manager"),
        ("technical_interface", "manual", "cfin_exception_manager"),
        ("unclassified", "unclassified", "cfin_exception_manager"),
    ],
)
def test_every_maintained_category_has_a_governed_route(category, route_kind, owner):
    route = asyncio.run(InMemoryRouteRegistry().get_error_route("workspace-1", category))
    assert route.route_kind == route_kind
    assert route.owner_role == owner
    assert route.steps[0].required_role


def test_database_snapshot_accepts_saved_routing_context():
    from cfin.error_analysis_snapshots import ErrorAnalysisInputSnapshot

    value = inputs()
    original = value.manifest.sources[0]
    snapshot = ErrorAnalysisInputSnapshot.model_validate(
        {
            "snapshot_version": "error-analysis-snapshot-v1",
            "binding": binding(value).model_dump(mode="json"),
            "source_manifest": value.manifest.model_dump(mode="json"),
            "routing_context": {"company_code": "1000"},
            "sources": [
                {
                    "id": "saved-1",
                    "workspace_id": "workspace-1",
                    "case_id": "case-1",
                    "attempt_id": "attempt-1",
                    "source_id": original.source_id,
                    "source_version": original.source_version,
                    "filename": original.original_filename,
                    "object_path": "workspace-1/saved-1/aif-log.txt",
                    "sha256": original.content_sha256,
                    "byte_size": original.byte_size,
                    "provenance": "synthetic",
                }
            ],
        }
    )
    assert snapshot.routing_context == {"company_code": "1000"}
