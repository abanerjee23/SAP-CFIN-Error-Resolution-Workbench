"""Real executor/adapter wiring with synthetic SDK responses, never paid model evals."""

import asyncio
import copy
import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from agents.exceptions import ModelBehaviorError

from cfin import model_adapter
from cfin.config import Settings
from cfin.log_only_contracts import (
    EvidenceSelection,
    ExecutionBinding,
    ExtractedEntry,
    ExtractedLog,
    LogStageEnvelope,
    LogSummary,
    SummaryStatement,
)
from cfin.log_only_inputs import OriginalUpload, prepare_log_inputs
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.log_only_sources import manifest_fingerprint
from cfin.log_only_workflow import LogWorkflowExecutor


class RecordingLedger:
    """Keep actual adapter-facing accounting and checkpoint state across restarts."""

    def __init__(self):
        self.cached_outputs = {}
        self.dispatch_counts = {}
        self.total_usage = {"input_tokens": 0, "output_tokens": 0}
        self.total_cost_usd = Decimal(0)
        self.usage_complete = True
        self.reservations = []
        self.reconciliations = []
        self.saved = []
        self.failed = []
        self.pending = set()

    async def reserve(self, stage, model, input_bound, output_bound, price_version):
        reservation = f"reservation-{len(self.reservations) + 1}"
        self.reservations.append(
            (reservation, stage, model, input_bound, output_bound, price_version)
        )
        self.pending.add(reservation)
        self.dispatch_counts[stage] = self.dispatch_counts.get(stage, 0) + 1
        self.usage_complete = False
        return reservation

    async def reconcile(self, reservation, usage, cost_usd, **metadata):
        assert reservation in self.pending
        self.pending.remove(reservation)
        self.reconciliations.append((reservation, usage, cost_usd, metadata))
        for key, value in usage.items():
            self.total_usage[key] += value
        self.total_cost_usd += cost_usd
        self.usage_complete = not self.pending

    async def record_validated(self, stage, output):
        # The real adapter must supply a complete code-owned envelope.
        parsed = LogStageEnvelope.model_validate(output)
        assert parsed.stage == stage
        self.saved.append((stage, copy.deepcopy(output)))
        self.cached_outputs[stage] = copy.deepcopy(output)

    async def record_failed(self, stage):
        self.failed.append(stage)
        self.cached_outputs.pop(stage, None)


@pytest.fixture
def configured(monkeypatch):
    class FakeClient:
        async def close(self):
            pass

    monkeypatch.setattr(model_adapter, "AsyncOpenAI", lambda **kwargs: FakeClient())
    return Settings(
        _env_file=None,
        paid_models_enabled=True,
        supabase_url="https://synthetic-test.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_secret_key="test-worker-key",
        openai_api_key="test-model-key",
    )


@pytest.fixture
def originals():
    return prepare_log_inputs(
        [
            OriginalUpload("first.log", b"Item 0001: processing failed.\r\n"),
            OriginalUpload("second.log", b"Item 0002: processing stopped.\n"),
        ],
        provenance="synthetic",
        intake_id=UUID("87f3ac48-6057-40b3-ae4a-c5299e67301b"),
    )


def execution_binding(originals):
    return ExecutionBinding(
        workspace_id="workspace-1",
        run_id="run-1",
        case_id="case-1",
        attempt_id="attempt-1",
        input_revision="revision-1",
        source_manifest_sha256=manifest_fingerprint(originals.manifest),
        prompt_versions=LOG_PROMPT_VERSIONS,
        model_configuration={
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    )


def candidates(originals):
    # Test candidates are deliberately explicit; this is no production extractor
    # and passing the test says nothing about a real model's semantic quality.
    entries = [
        ExtractedEntry(
            entry_id=f"entry-{index}",
            source_id=source.source_id,
            source_version=source.source_version,
            source_span={"line_start": 1, "line_end": 1},
            kind="message",
            raw_text=originals.originals[(source.source_id, source.source_version)].decode(),
        )
        for index, source in enumerate(originals.manifest.sources, start=1)
    ]
    title = SummaryStatement(
        text="Reported item processing failures",
        supporting_entry_ids=[entry.entry_id for entry in entries],
    )
    return {
        "agent1": ExtractedLog(entries=entries),
        "agent2": EvidenceSelection(selected_entry_ids=[entry.entry_id for entry in entries]),
        "agent3": LogSummary(
            title=title,
            statements=[
                SummaryStatement(
                    text="The log reports that processing failed for item 0001.",
                    supporting_entry_ids=["entry-1"],
                ),
                SummaryStatement(
                    text="The log reports that processing stopped for item 0002.",
                    supporting_entry_ids=["entry-2"],
                ),
            ],
        ),
    }


def install_runner(monkeypatch, ledger, outputs, *, fail_stage=None):
    calls = []

    async def run(agent, encoded, **options):
        stage = agent.name
        reservation = ledger.reservations[-1]
        assert reservation[1] == stage and reservation[0] in ledger.pending
        assert not ledger.saved or ledger.saved[-1][0] != stage
        data = json.loads(encoded)
        calls.append((stage, data, options))
        if stage == fail_stage:
            raise ModelBehaviorError("Synthetic malformed response without returned usage")
        return SimpleNamespace(
            final_output=outputs[stage],
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(requests=1, input_tokens=100, output_tokens=20)
            ),
            raw_responses=[SimpleNamespace(request_id=f"synthetic-{reservation[0]}")],
        )

    monkeypatch.setattr(model_adapter.Runner, "run", run)
    return calls


def run_workflow(configured, ledger, originals, *, max_retries=0):
    async def execute():
        adapter = model_adapter.OpenAIStageAdapter(
            configured, ledger, workflow_version="log-only-v1"
        )
        try:
            return await LogWorkflowExecutor(
                adapter, execution_binding(originals), max_retries=max_retries
            ).run(originals)
        finally:
            await adapter.close()

    return asyncio.run(execute())


def test_complete_originals_to_summary_checkpoint_then_zero_dispatch_resume(
    monkeypatch, configured, originals
):
    ledger = RecordingLedger()
    calls = install_runner(monkeypatch, ledger, candidates(originals))
    first = run_workflow(configured, ledger, originals)
    assert first.result.outcome == "completed"
    assert first.result.summary == candidates(originals)["agent3"]
    assert first.result.limitations == ()
    assert first.usage == ledger.total_usage == {"input_tokens": 300, "output_tokens": 60}
    assert first.cost_usd == ledger.total_cost_usd > 0
    assert first.usage_complete and not ledger.pending
    assert [stage for stage, *_ in calls] == ["agent1", "agent2", "agent3"]
    assert [stage for stage, _ in ledger.saved] == ["agent1", "agent2", "agent3"]
    assert set(calls[0][1]) == {"binding", "sources"}
    assert set(calls[1][1]) == {"binding", "source_manifest", "extracted"}
    assert calls[2][1]["history"]["status"] == "not_searched"
    assert calls[0][1]["sources"][0]["lines"][0]["text"].endswith("\r\n")
    for stage, encoded in ledger.saved:
        envelope = LogStageEnvelope.model_validate(encoded)
        assert envelope.binding == execution_binding(originals)
        assert envelope.output == candidates(originals)[stage]
        assert envelope.input_sha256
    saved_cost = ledger.total_cost_usd
    saved_reservations = copy.deepcopy(ledger.reservations)
    resumed_calls = install_runner(monkeypatch, ledger, candidates(originals))
    resumed = run_workflow(configured, ledger, originals)
    assert resumed.result == first.result
    assert not resumed_calls
    assert resumed.stage_calls == {"agent1": 1, "agent2": 1, "agent3": 1}
    assert set(resumed.stage_reuses) == {"agent1", "agent2", "agent3"}
    assert ledger.reservations == saved_reservations
    assert resumed.usage == first.usage
    assert resumed.cost_usd == saved_cost


def test_failed_selection_preserves_valid_extraction_for_bounded_same_run_resume(
    monkeypatch, configured, originals
):
    ledger = RecordingLedger()
    invalid = {
        **candidates(originals),
        "agent2": EvidenceSelection(selected_entry_ids=["invented-entry"]),
    }
    calls = install_runner(monkeypatch, ledger, invalid)
    first = run_workflow(configured, ledger, originals)
    assert first.result.outcome == "failed"
    assert first.result.failure_reason.startswith("agent2: invalid_output")
    assert first.result.summary is None
    assert [stage for stage, *_ in calls] == ["agent1", "agent2"]
    assert ledger.failed == ["agent2"]
    assert set(ledger.cached_outputs) == {"agent1"}
    assert first.usage == {"input_tokens": 200, "output_tokens": 40}
    assert not ledger.pending

    resumed_calls = install_runner(monkeypatch, ledger, candidates(originals))
    # The same run has one allowed selection invocation left. Restarting must
    # neither repay for extraction nor reset the selection's dispatch count.
    resumed = run_workflow(configured, ledger, originals, max_retries=1)
    assert resumed.result.outcome == "completed"
    assert [stage for stage, *_ in resumed_calls] == ["agent2", "agent3"]
    assert set(resumed.stage_reuses) == {"agent1"}
    assert resumed.stage_calls == {"agent1": 1, "agent2": 2, "agent3": 1}
    assert resumed.usage == ledger.total_usage == {"input_tokens": 400, "output_tokens": 80}
    assert resumed.cost_usd == ledger.total_cost_usd
    assert len(ledger.reservations) == len(ledger.reconciliations) == 4
    assert resumed.usage_complete and not ledger.pending


@pytest.mark.parametrize(
    "changed_stage,blocked_stage", [("agent1", "agent2"), ("agent2", "agent3")]
)
def test_changed_upstream_checkpoint_cannot_reuse_a_downstream_candidate(
    monkeypatch, configured, originals, changed_stage, blocked_stage
):
    ledger = RecordingLedger()
    install_runner(monkeypatch, ledger, candidates(originals))
    assert run_workflow(configured, ledger, originals).result.outcome == "completed"
    if changed_stage == "agent1":
        ledger.cached_outputs[changed_stage]["output"]["extraction_limitations"] = [
            "The saved extraction now records an unresolved context limitation."
        ]
    else:
        ledger.cached_outputs[changed_stage]["output"]["selected_entry_ids"] = ["entry-1"]
    resumed_calls = install_runner(monkeypatch, ledger, candidates(originals))
    resumed = run_workflow(configured, ledger, originals)
    assert resumed.result.outcome == "failed"
    assert resumed.result.failure_reason.startswith(blocked_stage)
    assert resumed.result.summary is None
    assert not resumed_calls
    assert blocked_stage not in resumed.stage_reuses
    assert len(ledger.reservations) == 3


def test_checkpoint_with_wrong_stage_fails_without_provider_dispatch(
    monkeypatch, configured, originals
):
    ledger = RecordingLedger()
    install_runner(monkeypatch, ledger, candidates(originals))
    assert run_workflow(configured, ledger, originals).result.outcome == "completed"
    ledger.cached_outputs["agent2"]["stage"] = "agent3"
    resumed_calls = install_runner(monkeypatch, ledger, candidates(originals))
    resumed = run_workflow(configured, ledger, originals)
    assert resumed.result.outcome == "failed"
    assert resumed.result.failure_reason.startswith("agent2: invalid_output")
    assert resumed.result.summary is None
    assert not resumed_calls
    assert "agent2" not in ledger.cached_outputs


def test_unknown_usage_preserves_reservation_and_blocks_retry_or_new_stages_on_resume(
    monkeypatch, configured, originals
):
    ledger = RecordingLedger()
    calls = install_runner(monkeypatch, ledger, candidates(originals), fail_stage="agent2")
    first = run_workflow(configured, ledger, originals, max_retries=1)
    assert first.result.outcome == "failed"
    assert first.result.summary is None
    assert not first.usage_complete
    assert [stage for stage, *_ in calls] == ["agent1", "agent2"]
    assert set(ledger.cached_outputs) == {"agent1"}
    assert ledger.pending == {"reservation-2"}
    assert len(ledger.reconciliations) == 1

    resumed_calls = install_runner(monkeypatch, ledger, candidates(originals))
    resumed = run_workflow(configured, ledger, originals, max_retries=1)
    assert resumed.result.outcome == "failed"
    assert not resumed_calls
    assert set(resumed.stage_reuses) == {"agent1"}
    assert not resumed.usage_complete
    assert ledger.pending == {"reservation-2"}
    assert len(ledger.reservations) == 2
