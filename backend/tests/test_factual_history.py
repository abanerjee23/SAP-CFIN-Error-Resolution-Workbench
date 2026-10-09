"""History evidence/access tests use deterministic doubles, never paid model calls."""

import asyncio
import copy
import hashlib
import json

from test_log_only_workflow import binding_for, extraction_for, inputs_for, run

from cfin.factual_history import FactualHistoryReader, selected_history_query
from cfin.log_only_contracts import (
    EvidenceSelection,
    LogAnalysisResult,
    RelatedCaseReference,
    hydrate_selection,
)


class Cloud:
    def __init__(self):
        self.calls = []
        self.raw = b"Original prior log: Account 0041001000 failed.\r\n"
        self.fail_search = self.fail_register = False
        self.withdrawn = set()
        self.hits = [{"id": "known", "case_id": "prior", "version": 2}]

    async def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == "cfin_search_history":
            if self.fail_search:
                raise RuntimeError("Offline")
            return {"items": self.hits}
        if name == "cfin_load_history_evidence":
            identifier = payload["knowledge_id"]
            if identifier in self.withdrawn:
                raise RuntimeError("Withdrawn")
            return {
                "knowledge": {
                    "id": identifier,
                    "case_id": "prior",
                    "version": 2,
                    "reuse_state": "approved",
                    "lesson": "Actual reviewed prior lesson",
                },
                "case": {
                    "id": "prior",
                    "workspace_id": "workspace-1",
                    "title": "Prior failure",
                    "status": "document_reprocessed",
                },
                "resolution": {"outcome": "Human confirmed validation of the earlier document"},
                "originals": [
                    {
                        "id": "saved",
                        "case_id": "prior",
                        "workspace_id": "workspace-1",
                        "kind": "original_log",
                        "source_id": "prior-log",
                        "source_version": "1",
                        "filename": "prior.txt",
                        "content_type": "text/plain",
                        "byte_size": len(self.raw),
                        "sha256": hashlib.sha256(self.raw).hexdigest(),
                    }
                ],
            }
        if name == "cfin_register_run_history":
            if self.fail_register:
                raise RuntimeError("Withdrawn during registration")
            return {"registered": True}
        raise AssertionError(name)

    async def download(self, original):
        return self.raw


def setup():
    inputs = inputs_for()
    binding = binding_for(inputs)
    extracted = extraction_for(inputs)
    hydrated = hydrate_selection(
        inputs.manifest, extracted, EvidenceSelection(selected_entry_ids=["entry-0"])
    )
    cloud = Cloud()
    return inputs, cloud, FactualHistoryReader(cloud, binding, "actual-user"), hydrated


def with_reference(inputs, history):
    result = run(inputs).result
    candidate = history.candidates[0]
    payload = result.model_dump(mode="json")
    payload["history"] = history.model_dump(mode="json")
    payload["summary"]["related_cases"] = [
        RelatedCaseReference(
            case_id=candidate.case_id,
            knowledge_id=candidate.knowledge_id,
            knowledge_version=candidate.knowledge_version,
            current_entry_ids=["entry-0"],
            historical_citations=list(candidate.citations),
            matching_details=["Both logs report errors"],
            differing_details=["Different business documents"],
            historical_note="Earlier human finding",
        ).model_dump(mode="json")
    ]
    return LogAnalysisResult.model_validate(payload)


def test_history_reads_exact_prior_original_and_reviewed_findings_after_selection():
    _, cloud, reader, hydrated = setup()
    value = asyncio.run(reader.retrieve(hydrated))
    assert value.status == "completed"
    material = json.loads(value.candidates[0].content)
    assert material["originals"][0]["text"].encode() == cloud.raw
    assert "Human confirmed" in material["human_resolution"]["outcome"]
    assert value.candidates[0].citations[1].line_end == 1
    query = cloud.calls[0][1]
    assert query["actor_id"] == "actual-user"
    assert query["context"] == {}
    assert "case-1" in query["excluded_case_ids"]
    assert "cause" not in query["query"]


def test_current_and_held_out_cases_never_become_history():
    _, cloud, reader, hydrated = setup()
    reader.excluded.add("held-out")
    cloud.hits = [
        {"id": "same", "case_id": "case-1", "version": 1},
        {"id": "eval", "case_id": "held-out", "version": 1},
    ]
    result = asyncio.run(reader.retrieve(hydrated))
    assert result.status == "completed" and not result.candidates
    assert len(cloud.calls) == 1


def test_history_outage_and_no_matches_remain_distinct():
    _, cloud, reader, hydrated = setup()
    cloud.hits = []
    assert asyncio.run(reader.retrieve(hydrated)).status == "completed"
    cloud.fail_search = True
    unavailable = asyncio.run(reader.retrieve(hydrated))
    assert unavailable.status == "unavailable" and unavailable.limitation


def test_oversized_original_is_omitted_with_explicit_limitation_not_truncated():
    _, cloud, reader, hydrated = setup()
    cloud.raw = b"a" * 8193
    result = asyncio.run(reader.retrieve(hydrated))
    assert not result.candidates and "envelope" in result.limitation


def test_cited_only_registration_ignores_unused_withdrawn_candidate():
    inputs, cloud, reader, hydrated = setup()
    history = asyncio.run(reader.retrieve(hydrated))
    cloud.withdrawn.add("unused")
    result = asyncio.run(reader.finalize(with_reference(inputs, history)))
    assert result.summary.related_cases
    assert cloud.calls[-1][0] == "cfin_register_run_history"
    assert cloud.calls[-1][1]["sources"] == [{"id": "known", "version": 2}]


def test_withdrawal_strips_history_without_discarding_current_factual_brief():
    inputs, cloud, reader, hydrated = setup()
    history = asyncio.run(reader.retrieve(hydrated))
    original = with_reference(inputs, history)
    cloud.withdrawn.add("known")
    result = asyncio.run(reader.finalize(original))
    assert result.outcome == "completed"
    assert result.summary.title == original.summary.title
    assert not result.summary.related_cases
    assert "withheld" in result.limitations[-1]
    assert not any(name == "cfin_register_run_history" for name, _ in cloud.calls)


def test_registration_race_withholds_history_and_retains_current_log_facts():
    inputs, cloud, reader, hydrated = setup()
    history = asyncio.run(reader.retrieve(hydrated))
    cloud.fail_register = True
    result = asyncio.run(reader.finalize(with_reference(inputs, history)))
    assert result.summary.title and not result.summary.related_cases


def test_query_is_built_from_selected_evidence_and_explicitly_bounded():
    _, _, _, hydrated = setup()
    payload = copy.deepcopy(hydrated.model_dump())
    payload["selected_entries"][0]["raw_text"] = "Error " * 300
    selected = type(hydrated).model_validate(payload)
    query, limited = selected_history_query(selected)
    assert limited and len(query) == 1000
