"""Compact model outputs hydrated into the existing, fully cited case contracts.

Only immutable source addressing and presentation are deterministic here. The
model still interprets log fields, groups entries and writes the diagnosis.
"""

from typing import Literal

from pydantic import Field, StrictInt

from cfin.error_analysis_contracts import CaseContent
from cfin.log_only_contracts import (
    ExtractedEntry,
    ExtractedLog,
    LogContract,
    LoggedField,
    NonEmptyText,
    RelatedCaseReference,
    SourceSpan,
    SummaryStatement,
)
from cfin.log_only_inputs import LogInputs
from cfin.log_only_sources import source_span_text, validate_extraction


class CompactEntry(LogContract):
    source: StrictInt = Field(ge=1)
    start: StrictInt = Field(ge=1)
    end: StrictInt = Field(ge=1)
    kind: Literal["metadata", "message", "payload", "unclassified"]
    fields: tuple[LoggedField, ...] = ()
    message_type: str | None = None
    message_class: str | None = None
    message_number: str | None = None
    message_variables: tuple[LoggedField, ...] = ()
    ambiguity: str | None = None


class CompactExtraction(LogContract):
    entries: tuple[CompactEntry, ...]
    extraction_limitations: tuple[NonEmptyText, ...] = ()


class CaseNarrative(LogContract):
    title: SummaryStatement
    what_happened: tuple[SummaryStatement, ...] = Field(min_length=1, max_length=20)
    evidence_entry_ids: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=20)
    open_questions: tuple[SummaryStatement, ...] = Field(default_factory=tuple, max_length=20)
    related_cases: tuple[RelatedCaseReference, ...] = Field(default_factory=tuple, max_length=3)


def hydrate_extraction(value: CompactExtraction, inputs: LogInputs) -> ExtractedLog:
    entries = []
    covered: set[tuple[int, int]] = set()
    for index, item in enumerate(value.entries, 1):
        if item.source > len(inputs.manifest.sources):
            raise ValueError("Compact entry references an unknown source")
        source = inputs.manifest.sources[item.source - 1]
        span = SourceSpan(line_start=item.start, line_end=item.end)
        if source.readable.status != "available":
            raise ValueError("Compact entry references an unreadable source")
        if item.end > source.readable.line_count:
            raise ValueError("Compact entry exceeds the preserved original")
        lines = {(item.source, line) for line in range(item.start, item.end + 1)}
        if covered & lines:
            raise ValueError("Compact entries must not duplicate source regions")
        covered.update(lines)
        raw = source_span_text(inputs.originals[(source.source_id, source.source_version)], span)
        for field in (*item.fields, *item.message_variables):
            if field.name_as_logged not in raw or field.value_as_logged not in raw:
                raise ValueError("Compact fields must be literal values from the cited source")
        entries.append(ExtractedEntry(
            entry_id=f"entry-{index}", source_id=source.source_id,
            source_version=source.source_version, source_span=span, raw_text=raw,
            **item.model_dump(exclude={"source", "start", "end"}),
        ))
    result = ExtractedLog(entries=entries, extraction_limitations=value.extraction_limitations)
    coverage = validate_extraction(inputs.manifest, inputs.originals, result)
    if coverage.uncovered_regions:
        raise ValueError("Compact extraction must represent every readable original line")
    return result


def hydrate_narrative(value: CaseNarrative, extraction: ExtractedLog) -> CaseContent:
    by_id = {entry.entry_id: entry for entry in extraction.entries}
    if len(set(value.evidence_entry_ids)) != len(value.evidence_entry_ids):
        raise ValueError("Narrative evidence references must be unique")
    evidence = []
    for entry_id in value.evidence_entry_ids:
        if entry_id not in by_id or not by_id[entry_id].raw_text.strip():
            raise ValueError("Narrative evidence must refer to a nonempty extracted entry")
        evidence.append(SummaryStatement(
            text=by_id[entry_id].raw_text.strip(), supporting_entry_ids=[entry_id],
        ))
    # Copy logged context deterministically, including fields outside the header
    # (dates, fiscal year, affected objects). Group only to fit the existing
    # presentation contract; never drop context to save generated tokens.
    metadata = [entry for entry in extraction.entries
                if entry.kind in {"metadata", "payload"} and entry.fields]
    context = []
    group_size = max(1, (len(metadata) + 19) // 20)
    for offset in range(0, len(metadata), group_size):
        group = metadata[offset:offset + group_size]
        context.append(SummaryStatement(
            text="; ".join(
                f"{field.name_as_logged}: {field.value_as_logged}"
                + (f" ({field.context_as_logged})" if field.context_as_logged else "")
                for entry in group for field in entry.fields
            ),
            supporting_entry_ids=[entry.entry_id for entry in group],
        ))
    # Route steps still come from the registry, never generated prose.
    return CaseContent(
        title=value.title, what_happened=value.what_happened,
        document_context=tuple(context), original_log_evidence=tuple(evidence),
        open_questions=value.open_questions, related_cases=value.related_cases,
    )


COMPACT_EXTRACTION_PROMPT = """
Return CompactExtraction. Sources are numbered from 1 with application-supplied
line numbers and exact text. For every source, partition ALL readable lines into
nonoverlapping contiguous entries. Group related metadata or multiline messages;
keep distinct processing attempts and unrelated messages separate. Include blank
lines and unfamiliar text; use unclassified when needed. Do not omit, summarize,
deduplicate or diagnose. Return only source number, inclusive start/end, kind and
explicit logged fields/message attributes. Code restores raw text, immutable
source identity/version and entry IDs. Never generate or guess those values.
Copy field names/values literally, preserving leading zeros and source/target,
item and attempt distinctions. A field's name AND value must occur in its entry.
Use context_as_logged=null unless the source explicitly labels the scope; do not
invent line-number context. Record ambiguity and extraction limitations honestly.
Unknown/unreadable sources must not acquire invented content. No field parsing
rule, error meaning or SAP message code may be inferred from familiar wording.
""".strip()

COMPACT_SUMMARY_PROMPT = """
Return CaseNarrative for a human investigator from validated extraction,
diagnosis, code-owned route and authorised history. The extraction includes the
exact preserved source text; there is no need to repeat or reconstruct the log.
Write a short factual title and concise what_happened statements covering every
distinct material error, processing outcome, attempt, contradiction and warning.
Cite existing entry IDs for every statement. Separate logged facts from tentative
cause; do not repeat the cause or route, which the application displays directly.
Document number, source/target systems, clients, company and interface are shown
as structured fields; avoid rewriting them as a separate paragraph unless scope
or a conflict is essential to understanding an error. Do not sacrifice a material
fact merely to shorten the response. Prefer one short sentence per statement.
Return evidence_entry_ids for the material log entries; code copies their exact
text for the evidence section. Do not copy quotes into your generated narrative.
Keep uncertainty, missing information and blockers explicit in open_questions.
Use only supplied reviewed history, preserve material differences and citations,
and never infer current cause from past outcomes. Do not claim a search returned
no matches when it was unavailable or not performed. Never invent identifiers,
actions, approvals, owners, SAP checks, classifications or resolution steps.
""".strip()
