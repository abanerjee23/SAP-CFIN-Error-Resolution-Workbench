"""Integrated factual worker SDK/HTTP fakes: no paid calls and no SQL emulation."""

import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_log_only_workflow import binding_for, extraction_for, inputs_for
from test_operations import ACTOR, ATTEMPT, CASE, RUN, WORKSPACE, CloudHTTP, test_settings

from cfin import factual_history, model_adapter, worker
from cfin.gateway import ServiceGateway
from cfin.log_only_contracts import (
    EvidenceSelection,
    HistoricalCaseEvidence,
    HistoryRetrievalResult,
    LogSummary,
    RelatedCaseReference,
    SummaryStatement,
)
from cfin.log_only_snapshots import LogInputSnapshot
from cfin.worker import process_one


def seed_factual(cloud, raw=b"Account 000123 unavailable\r\n", evaluation=False):
    inputs = inputs_for(raw)
    binding = binding_for(
        inputs,
        workspace_id=str(WORKSPACE),
        case_id=str(CASE),
        attempt_id=str(ATTEMPT),
        run_id=str(RUN),
    )
    source = inputs.manifest.sources[0]
    evidence = cloud.saved(
        raw, source.original_filename, "original_log", source_id=source.source_id
    )
    evidence["source_version"] = source.source_version
    snapshot = LogInputSnapshot(
        snapshot_version="log-only-snapshot-draft-v1",
        binding=binding,
        source_manifest=inputs.manifest,
        sources=[
            {
                key: value
                for key, value in evidence.items()
                if key in LogInputSnapshot.model_fields
                or key
                in {
                    "id",
                    "workspace_id",
                    "case_id",
                    "attempt_id",
                    "kind",
                    "source_id",
                    "source_version",
                    "filename",
                    "bucket_id",
                    "object_path",
                    "sha256",
                    "byte_size",
                    "content_type",
                }
            }
            | {"provenance": "synthetic"}
        ],
    )
    cloud.runs = [
        {
            "id": str(RUN),
            "workspace_id": str(WORKSPACE),
            "case_id": str(CASE),
            "attempt_id": str(ATTEMPT),
            "input_revision": 1,
            "requested_by": str(ACTOR),
            "state": "running",
            "output": None,
            "snapshot": snapshot.model_dump(mode="json"),
            "workflow_version": "log-only-v1",
            "schema_version": "log-only-v1",
            "prompt_versions": binding.prompt_versions.model_dump(),
            "model_configuration": binding.model_configuration.model_dump(),
            "source_manifest_sha256": binding.source_manifest_sha256,
            "evaluation_only": evaluation,
            "excluded_case_ids": [str(CASE), "held-out-case"],
            "evaluation_configuration": {"reasoning_effort": "medium"},
        }
    ]
    cloud.claimed = True
    return inputs, binding


def install_factual_provider(monkeypatch, cloud, *, cite_history=False):
    clients, payloads, actual_inputs = [], [], []

    class Client:
        closed = False

        async def close(self):
            self.closed = True

    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        client = Client()
        clients.append(client)
        return client

    class Adapter(model_adapter.OpenAIStageAdapter):
        async def execute(self, stage, payload, output_type, inputs):
            actual_inputs.append(inputs)
            return await super().execute(stage, payload, output_type, inputs)

    async def sdk_run(agent, encoded, **kwargs):
        assert cloud.pending and kwargs["max_turns"] == 1 and agent.tools == []
        payload = json.loads(encoded)
        payloads.append((agent.name, payload))
        extracted = extraction_for(actual_inputs[-1])
        ids = [entry.entry_id for entry in extracted.entries]
        if agent.name == "agent1":
            output = extracted
        elif agent.name == "agent2":
            output = EvidenceSelection(selected_entry_ids=ids)
        else:
            statement = SummaryStatement(
                text="The supplied account is unavailable.", supporting_entry_ids=ids
            )
            references = []
            if cite_history:
                candidate = payload["history"]["candidates"][0]
                references = [
                    RelatedCaseReference(
                        case_id=candidate["case_id"],
                        knowledge_id=candidate["knowledge_id"],
                        knowledge_version=candidate["knowledge_version"],
                        current_entry_ids=ids,
                        historical_citations=candidate["citations"],
                        matching_details=["Similar reported account error"],
                        differing_details=["Different document"],
                        historical_note="Prior human finding",
                    )
                ]
            output = LogSummary(title=statement, statements=[statement], related_cases=references)
        return SimpleNamespace(
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(
                    requests=1,
                    input_tokens=100,
                    output_tokens=30,
                )
            ),
            final_output=output.model_dump(mode="json"),
        )

    monkeypatch.setattr(model_adapter, "AsyncOpenAI", factory)
    monkeypatch.setattr(model_adapter.Runner, "run", sdk_run)
    monkeypatch.setattr(worker, "OpenAIStageAdapter", Adapter)
    return clients, payloads


def run_worker(cloud, *, enabled=True, target=None):
    settings = test_settings(log_only_enabled=enabled)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cloud.handler)) as client:
            return await process_one(
                ServiceGateway(settings, client),
                settings,
                "factual-http-test",
                target_run_id=target,
            )

    return asyncio.run(run())


def test_factual_worker_restores_exact_originals_saves_stages_and_pins_models(monkeypatch):
    cloud = CloudHTTP()
    inputs, binding = seed_factual(cloud)
    clients, payloads = install_factual_provider(monkeypatch, cloud)
    monkeypatch.setattr(worker, "restore_inputs", lambda *a: pytest.fail("Legacy restoration"))
    result = run_worker(cloud, target=str(RUN))
    assert result["succeeded"]
    assert [stage for stage, _ in payloads] == ["agent1", "agent2", "agent3"]
    assert [row["model_id"] for row in cloud.reservations] == [
        "gpt-6-luna",
        "gpt-6.1-sol",
        "gpt-6.1-sol",
    ]
    for stage, saved in cloud.stage_outputs.items():
        assert saved["stage"] == stage and saved["binding"] == binding.model_dump(mode="json")
        assert len(saved["input_sha256"]) == 64
    output = cloud.completed[0]["output"]
    assert output["result_kind"] == "factual" and output["outcome"] == "completed"
    assert output["model_configuration"] == binding.model_configuration.model_dump()
    assert output["source_manifest"] == inputs.manifest.model_dump(mode="json")
    assert not {"diagnosis", "category", "routing", "auto_owner"} & output.keys()
    assert output["history"]["status"] == "completed"
    assert output["usage"] == {"input_tokens": 300, "output_tokens": 90}
    assert len(clients) == 1 and clients[0].closed
    claim = next(
        json.loads(request.content)["payload"]
        for request in cloud.requests
        if request.url.path.endswith("cfin_claim_job")
    )
    assert claim["run_id"] == str(RUN) and claim["log_only_enabled"] is True
    assert len([request for request in cloud.requests if "/storage/" in request.url.path]) == 1


def test_evaluation_history_exclusions_are_from_saved_run_and_only_agent3_gets_history(monkeypatch):
    cloud = CloudHTTP()
    seed_factual(cloud, evaluation=True)
    _, payloads = install_factual_provider(monkeypatch, cloud)
    seen = []

    class Reader:
        def __init__(self, service, binding, actor_id, excluded_case_ids):
            assert excluded_case_ids == [str(CASE), "held-out-case"]
            assert actor_id == str(ACTOR)
            seen.append("constructed")

        async def retrieve(self, selected):
            assert [stage for stage, _ in payloads] == ["agent1", "agent2"]
            assert selected.selected_entries[0].entry_id == "entry-0"
            seen.append("read_after_selection")
            return HistoryRetrievalResult(
                status="completed", limitation="Test bounded history result"
            )

        async def finalize(self, result):
            assert result.summary and result.history.status == "completed"
            seen.append("finalized")
            return result

    monkeypatch.setattr(factual_history, "FactualHistoryReader", Reader)
    assert run_worker(cloud)["succeeded"]
    assert cloud.completed[0]["output"]["evaluation_only"] is True
    assert seen == ["constructed", "read_after_selection", "finalized"]
    assert "history" not in payloads[0][1] and "history" not in payloads[1][1]
    assert payloads[2][1]["history"]["limitation"] == "Test bounded history result"


def test_history_search_failure_retains_valid_current_factual_summary(monkeypatch):
    cloud = CloudHTTP()
    seed_factual(cloud)
    cloud.rpc_errors["cfin_search_history"] = 503
    _, payloads = install_factual_provider(monkeypatch, cloud)
    assert run_worker(cloud)["succeeded"]
    output = cloud.completed[0]["output"]
    assert output["summary"]["title"] and output["history"]["status"] == "unavailable"
    assert payloads[2][1]["history"]["status"] == "unavailable"


@pytest.mark.parametrize("raw", [b"", b" \n\t\n"])
def test_no_usable_evidence_completes_failed_without_fabricated_title(monkeypatch, raw):
    cloud = CloudHTTP()
    seed_factual(cloud, raw)
    clients, payloads = install_factual_provider(monkeypatch, cloud)
    result = run_worker(cloud)
    assert not result["succeeded"]
    output = cloud.completed[0]["output"]
    assert output["outcome"] == "no_usable_evidence" and output["summary"] is None
    assert output["errors"]
    assert not any(stage == "agent3" for stage, _ in payloads)
    if clients:
        assert clients[0].closed


def test_factual_dispatch_switch_blocks_even_if_cloud_returns_factual_job(monkeypatch):
    cloud = CloudHTTP()
    seed_factual(cloud)
    clients, payloads = install_factual_provider(monkeypatch, cloud)
    assert not run_worker(cloud, enabled=False)["succeeded"]
    assert not clients and not payloads and not cloud.reservations
    assert cloud.completed[0]["output"] is None


def test_snapshot_binding_tampering_is_rejected_before_paid_call(monkeypatch):
    cloud = CloudHTTP()
    seed_factual(cloud)
    cloud.runs[0]["snapshot"]["binding"]["run_id"] = "another-run"
    clients, payloads = install_factual_provider(monkeypatch, cloud)
    assert not run_worker(cloud)["succeeded"]
    assert not clients and not payloads and not cloud.reservations


def test_same_run_checkpoints_are_reused_without_new_provider_calls(monkeypatch):
    cloud = CloudHTTP()
    seed_factual(cloud)
    _, payloads = install_factual_provider(monkeypatch, cloud)
    assert run_worker(cloud)["succeeded"]
    saved = copy.deepcopy(cloud.stage_outputs)
    first_call_count = len(payloads)
    # HTTP fake supplies validated envelope recovery; no cross-run cache permitted.
    assert run_worker(cloud)["succeeded"]
    assert len(payloads) == first_call_count
    assert cloud.stage_outputs == saved


def test_old_legacy_checkpoint_cannot_satisfy_new_factual_stage(monkeypatch):
    cloud = CloudHTTP()
    seed_factual(cloud)
    cloud.stage_outputs = {"agent1": {"run_id": str(RUN), "attempt_id": "legacy"}}
    _, payloads = install_factual_provider(monkeypatch, cloud)
    assert run_worker(cloud)["succeeded"]
    assert [stage for stage, _ in payloads] == ["agent1", "agent2", "agent3"]
    assert cloud.stage_outputs["agent1"]["binding"]["workflow_version"] == "log-only-v1"


def test_withdrawal_finalization_keeps_current_brief_and_removes_only_historical_reference(
    monkeypatch,
):
    cloud = CloudHTTP()
    seed_factual(cloud)
    install_factual_provider(monkeypatch, cloud, cite_history=True)

    async def retrieve(self, selected):
        return HistoryRetrievalResult(
            status="completed",
            candidates=(
                HistoricalCaseEvidence(
                    case_id="prior-case",
                    knowledge_id="prior-knowledge",
                    knowledge_version=1,
                    content="Actual earlier reviewed case evidence",
                    citations=(
                        {"source_id": "prior-source", "source_version": "1", "record_id": "prior"},
                    ),
                ),
            ),
        )

    monkeypatch.setattr(factual_history.FactualHistoryReader, "retrieve", retrieve)
    # Cloud fake has no eligible knowledge at finalization; real finalizer withholds it.
    assert run_worker(cloud)["succeeded"]
    output = cloud.completed[0]["output"]
    assert output["summary"]["title"]["text"] == "The supplied account is unavailable."
    assert output["summary"]["related_cases"] == []
    assert "withheld" in output["limitations"][-1]
    assert cloud.stage_outputs["agent3"]["output"]["related_cases"]


def test_targeted_worker_iteration_never_dispatches_notifications(monkeypatch):
    import cfin.worker as worker

    captured = []
    settings = test_settings(log_only_enabled=True)
    monkeypatch.setattr(worker, "Settings", lambda: settings)

    async def model_call(cloud, actual_settings, worker_id, *, target_run_id):
        captured.append(target_run_id)
        return {"claimed": False}

    async def notification_call(cloud):
        raise AssertionError("A targeted model run must not dispatch unrelated notifications")

    monkeypatch.setattr(worker, "process_one", model_call)
    monkeypatch.setattr(worker, "process_notification", notification_call)
    asyncio.run(worker.run_worker(True, target_run_id=str(RUN)))
    assert captured == [str(RUN)]


def test_targeted_worker_requires_one_explicit_paid_iteration(monkeypatch):
    import cfin.worker as worker

    monkeypatch.setattr(worker, "Settings", lambda: test_settings(paid_models_enabled=False))
    with pytest.raises(RuntimeError, match="explicitly enabled"):
        asyncio.run(worker.run_worker(True, target_run_id=str(RUN)))
