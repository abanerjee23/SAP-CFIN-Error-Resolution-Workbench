"""Versioned handoffs for factual analysis of immutable supplied text originals.

Source metadata, execution bindings, coverage and history status belong to the
application. Agents supply extracted observations, selections and cited prose.
Reference validity does not establish semantic accuracy or completeness.
Legacy diagnostic contracts in :mod:`cfin.contracts` remain unchanged.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from cfin.contracts import Citation

LOG_WORKFLOW_VERSION = "log-only-v1"
LOG_SCHEMA_VERSION = "log-only-v1"
NonEmptyText = Annotated[StrictStr, Field(min_length=1, pattern=r".*\S.*")]
LineNumber = Annotated[StrictInt, Field(ge=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
StageName = Literal["agent1", "agent2", "agent3"]
Provenance = Literal["synthetic", "user_supplied"]


class LogContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceSpan(LogContract):
    """Inclusive, application-issued line numbers in an original's UTF-8 view."""

    line_start: LineNumber
    line_end: LineNumber

    @model_validator(mode="after")
    def ordered(self) -> "SourceSpan":
        if self.line_end < self.line_start:
            raise ValueError("Source span must be ordered")
        return self


class ReadableLocation(LogContract):
    """Readable view metadata; original bytes are always retained separately.

    The first version supports an exact UTF-8 decoding only. It does not quietly
    replace invalid bytes, remove a BOM, normalize newlines, or run OCR.
    """

    status: Literal["available", "unreadable"]
    representation: Literal["original_utf8"] = "original_utf8"
    encoding: Literal["utf-8"] = "utf-8"
    line_count: NonNegativeInt
    limitation: NonEmptyText | None = None

    @model_validator(mode="after")
    def consistent(self) -> "ReadableLocation":
        if self.status == "unreadable" and (self.line_count != 0 or not self.limitation):
            raise ValueError("Unreadable sources require zero readable lines and a limitation")
        if self.status == "available" and self.limitation is not None:
            raise ValueError("Available UTF-8 views cannot claim a decoding limitation")
        return self


class LogSource(LogContract):
    source_id: NonEmptyText
    source_version: NonEmptyText
    original_filename: NonEmptyText
    content_type: Literal["text/plain"] = "text/plain"
    content_sha256: Sha256
    byte_size: NonNegativeInt
    provenance: Provenance
    readable: ReadableLocation


class LogSourceManifest(LogContract):
    schema_version: Literal["log-only-v1"] = LOG_SCHEMA_VERSION
    # Tuple plus frozen nested models makes the source catalogue immutable in memory.
    sources: tuple[LogSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self) -> "LogSourceManifest":
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Source IDs must be unique within an input revision")
        return self


class SourceRegion(LogContract):
    source_id: NonEmptyText
    source_version: NonEmptyText
    source_span: SourceSpan


class LoggedField(LogContract):
    """Preserve raw values, leading zeroes, source/target and item/attempt scope."""

    name_as_logged: NonEmptyText
    value_as_logged: StrictStr
    context_as_logged: StrictStr | None = None


class ExtractedEntry(SourceRegion):
    entry_id: NonEmptyText
    kind: Literal["metadata", "message", "payload", "unclassified"]
    # Exact source slice, including its original line terminators when present.
    raw_text: Annotated[StrictStr, Field(min_length=1)]
    message_type: StrictStr | None = None
    message_class: StrictStr | None = None
    message_number: StrictStr | None = None
    message_variables: list[LoggedField] = Field(default_factory=list)
    fields: list[LoggedField] = Field(default_factory=list)
    ambiguity: NonEmptyText | None = None


class LogStageOutput(LogContract):
    schema_version: Literal["log-only-v1"] = LOG_SCHEMA_VERSION


class ExtractedLog(LogStageOutput):
    """Full extraction, including unfamiliar text; source counts are code-owned."""

    entries: list[ExtractedEntry]
    extraction_limitations: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_entries(self) -> "ExtractedLog":
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Extracted entry IDs must be globally unique across originals")
        return self


class ExtractionValidation(LogContract):
    """Code-computed coverage; it does not certify that fields were understood."""

    uncovered_regions: tuple[SourceRegion, ...] = ()
    unreadable_source_ids: tuple[NonEmptyText, ...] = ()
    limitations: tuple[NonEmptyText, ...] = ()

    @property
    def complete_coverage(self) -> bool:
        return not self.uncovered_regions and not self.unreadable_source_ids


class EvidenceSelection(LogStageOutput):
    selected_entry_ids: list[NonEmptyText]
    unresolved_entry_ids: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self) -> "EvidenceSelection":
        if len(self.selected_entry_ids) != len(set(self.selected_entry_ids)):
            raise ValueError("Selected entry IDs must be unique")
        if len(self.unresolved_entry_ids) != len(set(self.unresolved_entry_ids)):
            raise ValueError("Unresolved entry IDs must be unique")
        if not set(self.unresolved_entry_ids) <= set(self.selected_entry_ids):
            raise ValueError("Selection must retain unresolved entries")
        return self


class HydratedSelection(LogContract):
    """Application-resolved Agent 3 input; never trust the model to copy entries."""

    source_manifest: LogSourceManifest
    selected_entries: tuple[ExtractedEntry, ...]
    unresolved_entry_ids: tuple[NonEmptyText, ...]
    extraction_limitations: tuple[NonEmptyText, ...]


class SummaryStatement(LogContract):
    text: NonEmptyText = Field(description="One concise, factual point, without a bullet marker.")
    supporting_entry_ids: list[NonEmptyText] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_references(self) -> "SummaryStatement":
        if len(self.supporting_entry_ids) != len(set(self.supporting_entry_ids)):
            raise ValueError("Statement evidence IDs must be unique")
        return self


class RelatedCaseReference(LogContract):
    """Separately attributed history; never evidence for present-case facts."""

    case_id: NonEmptyText
    knowledge_id: NonEmptyText
    knowledge_version: Annotated[StrictInt, Field(ge=1)]
    current_entry_ids: list[NonEmptyText] = Field(min_length=1)
    historical_citations: list[Citation] = Field(min_length=1)
    matching_details: list[NonEmptyText] = Field(min_length=1)
    differing_details: list[NonEmptyText] = Field(default_factory=list)
    historical_note: NonEmptyText | None = None


class HistoricalCaseEvidence(LogContract):
    """Exact eligible case/version evidence loaded by authorised application code."""

    case_id: NonEmptyText
    knowledge_id: NonEmptyText
    knowledge_version: Annotated[StrictInt, Field(ge=1)]
    content: NonEmptyText
    citations: tuple[Citation, ...] = Field(min_length=1)


class HistoryRetrievalResult(LogContract):
    status: Literal["not_searched", "completed", "unavailable"] = "not_searched"
    limitation: NonEmptyText | None = None
    candidates: tuple[HistoricalCaseEvidence, ...] = ()

    @model_validator(mode="after")
    def actual_retrieval(self) -> "HistoryRetrievalResult":
        if self.status != "completed" and self.candidates:
            raise ValueError("Historical content requires completed application retrieval")
        if self.status == "unavailable" and not self.limitation:
            raise ValueError("Unavailable history requires an explicit limitation")
        keys = [(x.knowledge_id, x.knowledge_version, x.case_id) for x in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("Historical candidates must have unique exact case/version keys")
        return self


class LogSummary(LogStageOutput):
    """Agent 3 prose. History status and extraction limitations are owned by code."""

    title: SummaryStatement
    statements: list[SummaryStatement]
    unresolved_details: list[SummaryStatement] = Field(default_factory=list)
    related_cases: list[RelatedCaseReference] = Field(default_factory=list)


class PromptVersions(LogContract):
    agent1: NonEmptyText
    agent2: NonEmptyText
    agent3: NonEmptyText


class ModelConfiguration(LogContract):
    """Actual run configuration, required for checkpoint compatibility and audit."""

    agent1: NonEmptyText
    agent2: NonEmptyText
    agent3: NonEmptyText
    reasoning_effort: Literal["low", "medium", "high"]


class ExecutionBinding(LogContract):
    workspace_id: NonEmptyText
    run_id: NonEmptyText
    case_id: NonEmptyText
    attempt_id: NonEmptyText
    input_revision: NonEmptyText
    source_manifest_sha256: Sha256
    workflow_version: Literal["log-only-v1"] = LOG_WORKFLOW_VERSION
    schema_version: Literal["log-only-v1"] = LOG_SCHEMA_VERSION
    prompt_versions: PromptVersions
    model_configuration: ModelConfiguration


class LogStageEnvelope(LogContract):
    binding: ExecutionBinding
    stage: StageName
    input_sha256: Sha256
    output: ExtractedLog | EvidenceSelection | LogSummary

    @model_validator(mode="after")
    def stage_matches(self) -> "LogStageEnvelope":
        expected = {"agent1": ExtractedLog, "agent2": EvidenceSelection, "agent3": LogSummary}
        if not isinstance(self.output, expected[self.stage]):
            raise ValueError("Stage envelope output does not match its stage")
        return self

    @property
    def run_id(self) -> str:
        return self.binding.run_id


StageEnvelope = LogStageEnvelope


class LogAnalysisResult(ExecutionBinding):
    result_kind: Literal["factual"] = "factual"
    outcome: Literal["completed", "no_usable_evidence", "failed"]
    source_manifest: LogSourceManifest
    extraction: ExtractedLog | None = None
    selection: EvidenceSelection | None = None
    summary: LogSummary | None = None
    limitations: tuple[NonEmptyText, ...] = ()
    failure_reason: NonEmptyText | None = None
    history: HistoryRetrievalResult = Field(default_factory=HistoryRetrievalResult)

    @model_validator(mode="after")
    def coherent_result(self) -> "LogAnalysisResult":
        # Local import avoids coupling source utilities into the model definitions.
        from cfin.log_only_sources import manifest_fingerprint

        if self.source_manifest_sha256 != manifest_fingerprint(self.source_manifest):
            raise ValueError("Result source manifest does not match its execution binding")
        if self.selection is not None:
            if self.extraction is None:
                raise ValueError("Selection requires saved extraction")
            validate_selection(self.extraction, self.selection)
        if self.outcome == "completed":
            if self.extraction is None or self.selection is None or self.summary is None:
                raise ValueError("Completed factual result requires all three stages")
            if not self.selection.selected_entry_ids or self.failure_reason is not None:
                raise ValueError("Completed factual result requires usable evidence and no failure")
            selected = set(self.selection.selected_entry_ids)
            if not any(
                entry.entry_id in selected and entry.raw_text.strip()
                for entry in self.extraction.entries
            ):
                raise ValueError("Completed factual result cannot rely only on blank evidence")
            validate_summary(self.selection, self.summary, history=self.history)
        elif self.summary is not None or not self.failure_reason:
            raise ValueError("Unavailable factual output needs a reason and cannot have a summary")
        if self.extraction is not None and not set(self.extraction.extraction_limitations) <= set(
            self.limitations
        ):
            raise ValueError("Result must carry every extraction limitation")
        return self


class LegacyAnalysisResult(LogContract):
    """Explicit public compatibility branch; legacy content keeps its own meaning."""

    result_kind: Literal["legacy"] = "legacy"
    workflow_version: Literal["legacy-v1"] = "legacy-v1"
    title: NonEmptyText
    description: StrictStr
    diagnosis_status: NonEmptyText | None = None
    cause_label: NonEmptyText | None = None


SavedAnalysisResult = Annotated[
    LogAnalysisResult | LegacyAnalysisResult, Field(discriminator="result_kind")
]


class PublicFactualResult(LogContract):
    """Allowlisted saved-case projection, excluding prompts, bindings and candidates."""

    result_kind: Literal["factual"] = "factual"
    workflow_version: Literal["log-only-v1"] = LOG_WORKFLOW_VERSION
    outcome: Literal["completed", "no_usable_evidence", "failed"]
    title: SummaryStatement | None
    statements: tuple[SummaryStatement, ...] = ()
    unresolved_details: tuple[SummaryStatement, ...] = ()
    extraction: ExtractedLog | None
    limitations: tuple[NonEmptyText, ...] = ()
    failure_reason: NonEmptyText | None = None
    history_retrieval_status: Literal["not_searched", "completed", "unavailable"]
    history_retrieval_limitation: NonEmptyText | None = None
    related_cases: tuple[RelatedCaseReference, ...] = ()


PublicCaseResult = Annotated[
    PublicFactualResult | LegacyAnalysisResult, Field(discriminator="result_kind")
]


class PublicCaseSource(LogContract):
    """Original metadata only; authorised read routes resolve the stored bytes."""

    source_id: NonEmptyText
    source_version: NonEmptyText
    original_filename: NonEmptyText
    content_type: Literal["text/plain"]
    content_sha256: Sha256
    byte_size: NonNegativeInt
    provenance: Provenance
    readable: ReadableLocation | None = Field(
        description="Null for legacy originals whose readable line metadata was not recorded."
    )


class PublicCaseResponse(LogContract):
    api_version: Literal["v1"] = "v1"
    case_id: NonEmptyText
    input_revision: NonEmptyText
    operational_status: NonEmptyText
    review_status: NonEmptyText
    owner_id: NonEmptyText | None = None
    priority: NonEmptyText
    result: PublicCaseResult | None
    sources: tuple[PublicCaseSource, ...]


def project_factual_result(result: LogAnalysisResult) -> PublicFactualResult:
    """No model calls or internal dictionary passthrough on public reads."""
    summary = result.summary
    return PublicFactualResult(
        outcome=result.outcome,
        title=summary.title if summary else None,
        statements=tuple(summary.statements) if summary else (),
        unresolved_details=tuple(summary.unresolved_details) if summary else (),
        extraction=result.extraction,
        limitations=result.limitations,
        failure_reason=result.failure_reason,
        history_retrieval_status=result.history.status,
        history_retrieval_limitation=result.history.limitation,
        related_cases=tuple(summary.related_cases) if summary else (),
    )


def validate_selection(extracted: ExtractedLog, selection: EvidenceSelection) -> None:
    """Check ID resolution and retention of ambiguity; not semantic relevance."""
    known = {entry.entry_id for entry in extracted.entries}
    selected = set(selection.selected_entry_ids)
    unresolved = set(selection.unresolved_entry_ids)
    if not selected <= known:
        raise ValueError("Selection must use extracted entry IDs")
    flagged = {entry.entry_id for entry in extracted.entries if entry.ambiguity is not None}
    if not flagged <= unresolved:
        raise ValueError("Selection must preserve all explicitly ambiguous entries as unresolved")


def hydrate_selection(
    manifest: LogSourceManifest,
    extracted: ExtractedLog,
    selection: EvidenceSelection,
    *,
    limitations: tuple[str, ...] | list[str] = (),
) -> HydratedSelection:
    validate_selection(extracted, selection)
    by_id = {entry.entry_id: entry for entry in extracted.entries}
    registered = {(source.source_id, source.source_version) for source in manifest.sources}
    if any(
        (entry.source_id, entry.source_version) not in registered for entry in extracted.entries
    ):
        raise ValueError("Extraction references a source outside the immutable manifest")
    return HydratedSelection(
        source_manifest=manifest,
        selected_entries=tuple(by_id[entry_id] for entry_id in selection.selected_entry_ids),
        unresolved_entry_ids=tuple(selection.unresolved_entry_ids),
        extraction_limitations=tuple(
            dict.fromkeys([*extracted.extraction_limitations, *limitations])
        ),
    )


def validate_summary(
    selection: EvidenceSelection,
    summary: LogSummary,
    *,
    history: HistoryRetrievalResult | None = None,
) -> None:
    """Resolve current and historical references against application-owned inputs."""
    selected = set(selection.selected_entry_ids)
    if not selected:
        raise ValueError("Empty selection requires a no-usable-evidence outcome")
    represented: set[str] = set()
    for statement in [summary.title, *summary.statements, *summary.unresolved_details]:
        ids = set(statement.supporting_entry_ids)
        if not ids <= selected:
            raise ValueError("Summary references evidence outside the selection")
        represented.update(ids)
    if not set(selection.unresolved_entry_ids) <= represented:
        raise ValueError("Summary must retain every unresolved entry in a statement or limitation")
    actual_history = history or HistoryRetrievalResult()
    if summary.related_cases and actual_history.status != "completed":
        raise ValueError("Historical references require completed application retrieval")
    registered = {
        (item.knowledge_id, item.knowledge_version, item.case_id): item.citations
        for item in actual_history.candidates
    }
    seen = set()
    for reference in summary.related_cases:
        key = (reference.knowledge_id, reference.knowledge_version, reference.case_id)
        if key in seen:
            raise ValueError("Historical references must not repeat a case/knowledge version")
        seen.add(key)
        if not set(reference.current_entry_ids) <= selected:
            raise ValueError("Historical comparison references unselected current evidence")
        if key not in registered or any(
            citation not in registered[key] for citation in reference.historical_citations
        ):
            raise ValueError("Historical reference is outside retrieved case/version evidence")
