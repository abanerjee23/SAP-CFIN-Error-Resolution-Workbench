"""Software boundary tests, not claims of semantic extraction quality."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from cfin.contracts import Citation
from cfin.log_only_contracts import (
    EvidenceSelection,
    ExecutionBinding,
    ExtractedEntry,
    ExtractedLog,
    HistoricalCaseEvidence,
    HistoryRetrievalResult,
    LogAnalysisResult,
    LogSourceManifest,
    LogStageEnvelope,
    LogSummary,
    PublicCaseResponse,
    RelatedCaseReference,
    SavedAnalysisResult,
    SourceSpan,
    hydrate_selection,
    project_factual_result,
    validate_selection,
    validate_summary,
)
from cfin.log_only_sources import (
    build_log_source,
    manifest_fingerprint,
    source_lines,
    source_span_text,
    validate_extraction,
    validate_originals,
)

RAW = b"Client=010\r\nAccount=0041001000\r\nResult=failed\n"


def manifest_for(*raws):
    return LogSourceManifest(
        sources=tuple(
            build_log_source(
                source_id=f"source-{number}",
                source_version="1",
                original_filename=f"view-{number}.txt",
                raw=raw,
                provenance="synthetic",
            )
            for number, raw in enumerate(raws or (RAW,), 1)
        )
    )


def originals_for(*raws):
    return {(f"source-{number}", "1"): raw for number, raw in enumerate(raws or (RAW,), 1)}


def entry(number=1, *, source=1, raw=RAW, start=1, end=3, **changes):
    data = dict(
        entry_id=f"entry-{number}",
        source_id=f"source-{source}",
        source_version="1",
        kind="unclassified",
        source_span=SourceSpan(line_start=start, line_end=end),
        raw_text=source_span_text(raw, SourceSpan(line_start=start, line_end=end)),
    )
    data.update(changes)
    return ExtractedEntry(**data)


def binding_for(manifest=None):
    return ExecutionBinding(
        workspace_id="workspace-1",
        run_id="run-1",
        case_id="case-1",
        attempt_id="application-attempt-1",
        input_revision="revision-1",
        source_manifest_sha256=manifest_fingerprint(manifest or manifest_for()),
        prompt_versions={"agent1": "extract-v1", "agent2": "select-v1", "agent3": "summary-v1"},
        model_configuration={
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    )


def summary_for(*ids):
    return LogSummary(
        title={"text": "The log reports a failed result", "supporting_entry_ids": list(ids)},
        statements=[{"text": "Client 010 is reported.", "supporting_entry_ids": list(ids)}],
    )


def result_for(**changes):
    data = dict(
        **binding_for().model_dump(),
        outcome="completed",
        source_manifest=manifest_for(),
        extraction=ExtractedLog(entries=[entry()]),
        selection=EvidenceSelection(selected_entry_ids=["entry-1"]),
        summary=summary_for("entry-1"),
    )
    data.update(changes)
    return LogAnalysisResult(**data)


def test_manifest_is_immutable_preserves_order_and_original_byte_identity():
    manifest = manifest_for(RAW, RAW)
    assert manifest.sources[0].byte_size == len(RAW)
    assert manifest.sources[0].content_sha256 == manifest.sources[1].content_sha256
    assert manifest.sources[0].source_id != manifest.sources[1].source_id
    assert manifest.sources[0].readable.line_count == 3
    with pytest.raises(ValidationError, match="frozen"):
        manifest.sources[0].original_filename = "changed.txt"
    with pytest.raises(ValidationError, match="frozen"):
        manifest.sources += (manifest.sources[0],)
    assert manifest_fingerprint(manifest) == manifest_fingerprint(
        LogSourceManifest.model_validate_json(manifest.model_dump_json())
    )
    reordered = LogSourceManifest(sources=tuple(reversed(manifest.sources)))
    assert manifest_fingerprint(manifest) != manifest_fingerprint(reordered)


def test_duplicate_source_ids_rejected_even_with_different_versions():
    source = manifest_for().sources[0]
    with pytest.raises(ValidationError, match="unique"):
        LogSourceManifest(sources=(source, source.model_copy(update={"source_version": "2"})))


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"", ()),
        (b"\n", ("\n",)),
        (b"first\r\nlast\r", ("first\r\n", "last\r")),
        (b"first\nlast", ("first\n", "last")),
        ("é\u2028text\f\n".encode(), ("é\u2028text\f\n",)),
    ],
)
def test_line_numbering_preserves_exact_utf8_and_terminators(raw, expected):
    assert source_lines(raw) == expected
    assert "".join(source_lines(raw)).encode("utf-8") == raw


def test_integrity_rejects_changed_bytes_missing_extra_and_forged_counts():
    manifest = manifest_for()
    validate_originals(manifest, originals_for())
    for originals in (
        originals_for(RAW.replace(b"010", b"011")),
        {},
        {**originals_for(), ("unregistered", "1"): b"text"},
    ):
        with pytest.raises(ValueError):
            validate_originals(manifest, originals)
    data = manifest.model_dump()
    data["sources"][0]["readable"]["line_count"] = 50
    with pytest.raises(ValueError, match="metadata"):
        validate_originals(LogSourceManifest.model_validate(data), originals_for())


def test_multisource_extraction_resolves_repeated_lines_to_distinct_originals():
    extracted = ExtractedLog(entries=[entry(1), entry(2, source=2)])
    validated = validate_extraction(manifest_for(RAW, RAW), originals_for(RAW, RAW), extracted)
    assert validated.complete_coverage
    assert not validated.limitations
    with pytest.raises(ValidationError, match="globally unique"):
        ExtractedLog(entries=[entry(1), entry(1, source=2)])


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": "unknown"},
        {"source_version": "stale"},
        {"raw_text": RAW.decode().replace("0041001000", "41001000")},
        {"raw_text": RAW.decode().replace("\r\n", "\n")},
        {"raw_text": RAW.decode().rstrip()},
        {"source_span": SourceSpan(line_start=1, line_end=4)},
    ],
)
def test_out_of_manifest_spans_or_altered_quotes_fail(changes):
    with pytest.raises(ValueError):
        validate_extraction(
            manifest_for(), originals_for(), ExtractedLog(entries=[entry(**changes)])
        )


def test_uncovered_regions_are_code_owned_and_carried_to_summary_input():
    extraction = ExtractedLog(
        entries=[entry(start=2, end=2)], extraction_limitations=["The account label is unfamiliar."]
    )
    manifest = manifest_for()
    coverage = validate_extraction(manifest, originals_for(), extraction)
    assert [region.source_span.model_dump() for region in coverage.uncovered_regions] == [
        {"line_start": 1, "line_end": 1},
        {"line_start": 3, "line_end": 3},
    ]
    hydrated = hydrate_selection(
        manifest,
        extraction,
        EvidenceSelection(selected_entry_ids=["entry-1"]),
        limitations=coverage.limitations,
    )
    assert hydrated.selected_entries == (extraction.entries[0],)
    assert hydrated.extraction_limitations == (
        "The account label is unfamiliar.",
        *coverage.limitations,
    )


def test_empty_and_unreadable_originals_never_get_invented_readable_text():
    manifest = manifest_for(b"", b"\xffinvalid")
    originals = originals_for(b"", b"\xffinvalid")
    validate_originals(manifest, originals)
    coverage = validate_extraction(manifest, originals, ExtractedLog(entries=[]))
    assert coverage.unreadable_source_ids == ("source-2",)
    assert len(coverage.limitations) == 2
    assert manifest.sources[0].readable.line_count == 0
    assert manifest.sources[1].readable.status == "unreadable"
    fabricated = entry(source=2, raw=b"invented", start=1, end=1)
    with pytest.raises(ValueError, match="unreadable"):
        validate_extraction(manifest, originals, ExtractedLog(entries=[fabricated]))


def test_empty_extraction_is_valid_but_cannot_produce_a_cited_summary():
    empty = ExtractedLog(entries=[])
    selection = EvidenceSelection(selected_entry_ids=[])
    validate_selection(empty, selection)
    with pytest.raises(ValueError, match="no-usable-evidence"):
        validate_summary(selection, summary_for("invented"))
    result = result_for(
        outcome="no_usable_evidence",
        extraction=empty,
        selection=selection,
        summary=None,
        failure_reason="No usable current-log entries were selected.",
    )
    assert project_factual_result(result).title is None
    with pytest.raises(ValidationError, match="all three stages"):
        result_for(extraction=None, selection=None, summary=None)
    with pytest.raises(ValidationError, match="cannot have a summary"):
        result_for(outcome="no_usable_evidence", failure_reason="No evidence")


def test_selection_cannot_lose_unknown_ids_or_flagged_ambiguity():
    extraction = ExtractedLog(entries=[entry(ambiguity="Two statuses are reported.")])
    with pytest.raises(ValueError, match="ambiguous"):
        validate_selection(extraction, EvidenceSelection(selected_entry_ids=["entry-1"]))
    with pytest.raises(ValueError, match="extracted entry"):
        validate_selection(extraction, EvidenceSelection(selected_entry_ids=["invented"]))
    with pytest.raises(ValidationError, match="retain unresolved"):
        EvidenceSelection(selected_entry_ids=[], unresolved_entry_ids=["entry-1"])
    with pytest.raises(ValidationError, match="unique"):
        EvidenceSelection(selected_entry_ids=["entry-1", "entry-1"])
    validate_selection(
        extraction,
        EvidenceSelection(selected_entry_ids=["entry-1"], unresolved_entry_ids=["entry-1"]),
    )


def test_completed_result_cannot_cite_a_whitespace_only_selection():
    raw = b"Error\n\n"
    manifest = manifest_for(raw)
    extraction = ExtractedLog(
        entries=[
            entry(1, raw=raw, start=1, end=1),
            entry(2, raw=raw, start=2, end=2),
        ]
    )
    validate_extraction(manifest, originals_for(raw), extraction)
    with pytest.raises(ValidationError, match="only on blank evidence"):
        LogAnalysisResult(
            **binding_for(manifest).model_dump(),
            source_manifest=manifest,
            outcome="completed",
            extraction=extraction,
            selection=EvidenceSelection(selected_entry_ids=["entry-2"]),
            summary=summary_for("entry-2"),
        )


def test_summary_references_must_retain_every_unresolved_entry():
    selection = EvidenceSelection(
        selected_entry_ids=["entry-1", "entry-2"], unresolved_entry_ids=["entry-2"]
    )
    summary = summary_for("entry-1")
    with pytest.raises(ValueError, match="every unresolved"):
        validate_summary(selection, summary)
    with pytest.raises(ValueError, match="outside the selection"):
        validate_summary(selection, summary_for("invented"))
    retained = LogSummary.model_validate(
        {
            **summary.model_dump(),
            "unresolved_details": [
                {"text": "The second status is unclear.", "supporting_entry_ids": ["entry-2"]}
            ]
        }
    )
    validate_summary(selection, retained)


def historical_fixture():
    citation = Citation(source_id="past-source", source_version="2", line_start=1, line_end=2)
    candidate = HistoricalCaseEvidence(
        case_id="past-case",
        knowledge_id="knowledge-1",
        knowledge_version=2,
        content="Authorised historical source content",
        citations=(citation,),
    )
    reference = RelatedCaseReference(
        case_id="past-case",
        knowledge_id="knowledge-1",
        knowledge_version=2,
        current_entry_ids=["entry-1"],
        historical_citations=[citation],
        matching_details=["Both logs report client 010."],
        differing_details=["The earlier case reports a different account."],
    )
    return candidate, reference


def test_model_cannot_declare_history_search_status_and_code_status_is_honest():
    with pytest.raises(ValidationError, match="Extra inputs"):
        LogSummary.model_validate(
            {**summary_for("entry-1").model_dump(), "history_retrieval_status": "completed"}
        )
    candidate, reference = historical_fixture()
    for status in ("not_searched", "unavailable"):
        with pytest.raises(ValidationError, match="completed application"):
            HistoryRetrievalResult(status=status, candidates=(candidate,))
    with pytest.raises(ValidationError, match="explicit limitation"):
        HistoryRetrievalResult(status="unavailable")
    summary = summary_for("entry-1").model_copy(update={"related_cases": [reference]})
    selection = EvidenceSelection(selected_entry_ids=["entry-1"])
    with pytest.raises(ValueError, match="completed application retrieval"):
        validate_summary(selection, summary)
    history = HistoryRetrievalResult(status="completed", candidates=(candidate,))
    validate_summary(selection, summary, history=history)
    withdrawn = HistoryRetrievalResult(status="completed", candidates=())
    with pytest.raises(ValueError, match="outside retrieved"):
        validate_summary(selection, summary, history=withdrawn)
    stale_reference = reference.model_copy(update={"knowledge_version": 1})
    with pytest.raises(ValueError, match="outside retrieved"):
        validate_summary(
            selection,
            summary.model_copy(update={"related_cases": [stale_reference]}),
            history=history,
        )


def test_execution_metadata_is_application_owned_and_stage_type_checked():
    with pytest.raises(ValidationError, match="Extra inputs"):
        ExtractedLog(entries=[], run_id="model-invented")
    binding = binding_for()
    envelope = LogStageEnvelope(
        binding=binding,
        stage="agent1",
        input_sha256="a" * 64,
        output=ExtractedLog(entries=[entry()]),
    )
    assert envelope.run_id == binding.run_id
    assert LogStageEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    with pytest.raises(ValidationError, match="does not match"):
        LogStageEnvelope(
            binding=binding, stage="agent2", input_sha256="a" * 64, output=ExtractedLog(entries=[])
        )
    with pytest.raises(ValidationError, match="execution binding"):
        result_for(source_manifest_sha256="b" * 64)


def test_saved_results_distinguish_legacy_and_preserve_limitations():
    factual = result_for()
    union = TypeAdapter(SavedAnalysisResult)
    assert union.validate_json(factual.model_dump_json()).result_kind == "factual"
    legacy = union.validate_python(
        {
            "result_kind": "legacy",
            "title": "Old diagnosis",
            "description": "Historical content",
            "cause_label": "old",
        }
    )
    assert legacy.workflow_version == "legacy-v1"
    with pytest.raises(ValidationError, match="extraction limitation"):
        result_for(extraction=ExtractedLog(entries=[entry()], extraction_limitations=["A gap"]))
    result_for(
        extraction=ExtractedLog(entries=[entry()], extraction_limitations=["A gap"]),
        limitations=("A gap",),
    )
    failed = result_for(
        outcome="failed",
        extraction=None,
        selection=None,
        summary=None,
        failure_reason="Output exceeded the supported analysis envelope.",
    )
    assert failed.failure_reason


def test_public_projection_has_no_prompt_bindings_history_candidates_or_storage_paths():
    candidate, _ = historical_fixture()
    result = result_for(history=HistoryRetrievalResult(status="completed", candidates=(candidate,)))
    public = project_factual_result(result)
    payload = public.model_dump(mode="json")
    encoded = json.dumps(payload)
    for private_field in ("prompt_versions", "run_id", "workspace_id", "candidates", "binding"):
        assert private_field not in payload
    assert candidate.content not in encoded
    assert payload["history_retrieval_status"] == "completed"
    assert payload["extraction"] == result.extraction.model_dump(mode="json")
    schema = PublicCaseResponse.model_json_schema()
    assert "result_kind" in json.dumps(schema)
    assert schema["properties"]["api_version"]["const"] == "v1"


@pytest.mark.parametrize("fixture", ["MD-01", "MAP-01"])
def test_existing_fixture_originals_are_preserved_without_legacy_sidecars(fixture):
    original = Path(__file__).resolve().parents[2] / "fixtures" / fixture / "agent-visible"
    raw = (original / "original-log.txt").read_bytes()
    manifest = manifest_for(raw)
    extracted = ExtractedLog(entries=[entry(raw=raw, end=len(source_lines(raw)))])
    coverage = validate_extraction(manifest, originals_for(raw), extracted)
    assert coverage.complete_coverage
    assert extracted.entries[0].raw_text.encode("utf-8") == raw
    assert not coverage.limitations
