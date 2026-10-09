"""Contracts for the governed Error Analysis workflow.

The factual-only contracts remain immutable for existing cases.  This module is
the explicit, versioned handoff for the approved three-agent rebuild.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cfin.log_only_contracts import (
    ExtractedLog,
    HistoryRetrievalResult,
    LogContract,
    LogSourceManifest,
    NonEmptyText,
    RelatedCaseReference,
    Sha256,
    StageName,
    SummaryStatement,
)
from cfin.log_only_sources import manifest_fingerprint

ERROR_ANALYSIS_WORKFLOW_VERSION = "error-analysis-v1"
ERROR_ANALYSIS_SCHEMA_VERSION = ERROR_ANALYSIS_WORKFLOW_VERSION
ErrorCategoryId = Literal[
    "master_data",
    "mapping",
    "integration_mapping",
    "master_data_restriction",
    "posting_period",
    "tax",
    "currency",
    "document_splitting",
    "account_assignment",
    "technical_interface",
    "unclassified",
]
KnownErrorCategoryId = Literal[
    "master_data",
    "mapping",
    "integration_mapping",
    "master_data_restriction",
    "posting_period",
    "tax",
    "currency",
    "document_splitting",
    "account_assignment",
    "technical_interface",
]
PilotCategoryId = Literal["master_data", "mapping"]
RouteKind = Literal["pilot", "manual", "unclassified"]
RouteStepKind = Literal[
    "request_process_owner_approval",
    "record_process_owner_decision",
    "confirm_mapping_with_process_owner",
    "maintain_mapping",
    "review_and_approve_mapping",
    "create_master_data",
    "upload_implementation_evidence",
    "record_reprocessing_go_ahead",
    "reprocess_document",
    "record_posting_outcome",
    "manual_investigation",
]


class ErrorAnalysisBinding(LogContract):
    workspace_id: NonEmptyText
    run_id: NonEmptyText
    case_id: NonEmptyText
    attempt_id: NonEmptyText
    input_revision: NonEmptyText
    source_manifest_sha256: Sha256
    workflow_version: Literal["error-analysis-v1"] = ERROR_ANALYSIS_WORKFLOW_VERSION
    schema_version: Literal["error-analysis-v1"] = ERROR_ANALYSIS_SCHEMA_VERSION
    prompt_versions: dict[Literal["agent1", "agent2", "agent3"], NonEmptyText]
    model_configuration: dict[str, str]

    @model_validator(mode="after")
    def prompt_and_model_shape(self) -> "ErrorAnalysisBinding":
        if set(self.prompt_versions) != {"agent1", "agent2", "agent3"}:
            raise ValueError("All three Error Analysis prompt versions are required")
        if set(self.model_configuration) != {
            "agent1",
            "agent2",
            "agent3",
            "reasoning_effort",
        }:
            raise ValueError("Pinned model configuration is required")
        return self


class TaxonomyCategory(LogContract):
    category_id: KnownErrorCategoryId
    label: NonEmptyText
    definition: NonEmptyText
    pilot_active: bool


class ErrorAnalysisDraft(LogContract):
    """Agent 2 output before code attaches a maintained route."""

    schema_version: Literal["error-analysis-v1"] = ERROR_ANALYSIS_SCHEMA_VERSION
    category_id: ErrorCategoryId
    cause_hypothesis: NonEmptyText
    confidence: Literal["low", "medium", "high"]
    supporting_entry_ids: list[NonEmptyText] = Field(min_length=1, max_length=32)
    competing_explanations: list[NonEmptyText] = Field(default_factory=list, max_length=10)
    gaps: list[NonEmptyText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def distinct_evidence(self) -> "ErrorAnalysisDraft":
        if len(self.supporting_entry_ids) != len(set(self.supporting_entry_ids)):
            raise ValueError("Error Analysis evidence references must be unique")
        return self


class RouteStep(LogContract):
    order: Annotated[int, Field(ge=1, le=20)]
    step_id: NonEmptyText
    kind: RouteStepKind
    description: NonEmptyText
    required_role: NonEmptyText | None = None
    requires_evidence: bool = False
    requires_approval: bool = False


class RouteDefinition(LogContract):
    """Code-owned policy snapshot returned by the narrow registry lookup."""

    policy_id: NonEmptyText
    policy_version: Annotated[int, Field(ge=1)]
    category_id: ErrorCategoryId
    route_kind: RouteKind
    owner_role: NonEmptyText
    escalation_role: Literal["cfin_exception_manager"] = "cfin_exception_manager"
    steps: tuple[RouteStep, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def ordered_steps(self) -> "RouteDefinition":
        orders = [step.order for step in self.steps]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("Route steps must be consecutive and ordered")
        if self.category_id in ("master_data", "mapping") and self.route_kind != "pilot":
            raise ValueError("Pilot categories require a pilot route")
        if self.category_id == "unclassified" and self.route_kind != "unclassified":
            raise ValueError("Unclassified cases require the unclassified route")
        if (
            self.category_id not in ("master_data", "mapping", "unclassified")
            and self.route_kind != "manual"
        ):
            raise ValueError("Known non-pilot categories require the manual route")
        return self


class ErrorAnalysis(LogContract):
    schema_version: Literal["error-analysis-v1"] = ERROR_ANALYSIS_SCHEMA_VERSION
    category_id: ErrorCategoryId
    cause_hypothesis: NonEmptyText
    confidence: Literal["low", "medium", "high"]
    supporting_entry_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    competing_explanations: tuple[NonEmptyText, ...] = ()
    gaps: tuple[NonEmptyText, ...] = ()
    route: RouteDefinition

    @model_validator(mode="after")
    def route_matches_category(self) -> "ErrorAnalysis":
        if self.category_id != self.route.category_id:
            raise ValueError("The route must match the Agent 2 category")
        return self


class CaseContent(LogContract):
    """Agent 3 output; the frontend renders these as a case, never raw JSON."""

    schema_version: Literal["error-analysis-v1"] = ERROR_ANALYSIS_SCHEMA_VERSION
    title: SummaryStatement
    what_happened: tuple[SummaryStatement, ...] = Field(min_length=1, max_length=20)
    document_context: tuple[SummaryStatement, ...] = Field(default_factory=tuple, max_length=20)
    original_log_evidence: tuple[SummaryStatement, ...] = Field(min_length=1, max_length=20)
    open_questions: tuple[SummaryStatement, ...] = Field(default_factory=tuple, max_length=20)
    related_cases: tuple[RelatedCaseReference, ...] = Field(default_factory=tuple, max_length=3)


class ErrorAnalysisStageEnvelope(LogContract):
    binding: ErrorAnalysisBinding
    stage: StageName
    input_sha256: Sha256
    output: ExtractedLog | ErrorAnalysisDraft | CaseContent

    @model_validator(mode="after")
    def stage_matches(self) -> "ErrorAnalysisStageEnvelope":
        expected = {"agent1": ExtractedLog, "agent2": ErrorAnalysisDraft, "agent3": CaseContent}
        if not isinstance(self.output, expected[self.stage]):
            raise ValueError("Stage envelope output does not match the Error Analysis stage")
        return self


class ErrorAnalysisResult(ErrorAnalysisBinding):
    result_kind: Literal["error_analysis"] = "error_analysis"
    outcome: Literal["completed", "no_usable_evidence", "failed"]
    source_manifest: LogSourceManifest
    extraction: ExtractedLog | None = None
    analysis: ErrorAnalysis | None = None
    case_content: CaseContent | None = None
    history: HistoryRetrievalResult = Field(default_factory=HistoryRetrievalResult)
    limitations: tuple[NonEmptyText, ...] = ()
    failure_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def coherent_result(self) -> "ErrorAnalysisResult":
        if self.source_manifest_sha256 != manifest_fingerprint(self.source_manifest):
            raise ValueError("Result source manifest does not match its execution binding")
        if self.outcome == "completed":
            if self.extraction is None or self.analysis is None or self.case_content is None:
                raise ValueError("Completed Error Analysis requires all three stages")
            validate_error_analysis(self.extraction, self.analysis)
            validate_case_content(self.extraction, self.case_content, history=self.history)
            if self.failure_reason is not None:
                raise ValueError("Completed Error Analysis cannot have a failure reason")
        elif self.case_content is not None or not self.failure_reason:
            raise ValueError("Unavailable Error Analysis needs a reason and no case content")
        return self


def validate_error_analysis_draft(extraction: ExtractedLog, draft: ErrorAnalysisDraft) -> None:
    known = {entry.entry_id for entry in extraction.entries}
    if not set(draft.supporting_entry_ids) <= known:
        raise ValueError("Error Analysis must cite extracted entries")
    if draft.category_id == "unclassified" and not draft.gaps:
        raise ValueError("Unclassified analysis must state the evidence gap")


def attach_route(
    extraction: ExtractedLog, draft: ErrorAnalysisDraft, route: RouteDefinition
) -> ErrorAnalysis:
    validate_error_analysis_draft(extraction, draft)
    return ErrorAnalysis(
        category_id=draft.category_id,
        cause_hypothesis=draft.cause_hypothesis,
        confidence=draft.confidence,
        supporting_entry_ids=tuple(draft.supporting_entry_ids),
        competing_explanations=tuple(draft.competing_explanations),
        gaps=tuple(draft.gaps),
        route=route,
    )


def validate_error_analysis(extraction: ExtractedLog, analysis: ErrorAnalysis) -> None:
    validate_error_analysis_draft(
        extraction,
        ErrorAnalysisDraft(
            category_id=analysis.category_id,
            cause_hypothesis=analysis.cause_hypothesis,
            confidence=analysis.confidence,
            supporting_entry_ids=list(analysis.supporting_entry_ids),
            competing_explanations=list(analysis.competing_explanations),
            gaps=list(analysis.gaps),
        ),
    )
    if analysis.route.category_id != analysis.category_id:
        raise ValueError("Resolved route differs from classification")


def validate_case_content(
    extraction: ExtractedLog,
    content: CaseContent,
    *,
    history: HistoryRetrievalResult,
) -> None:
    known = {entry.entry_id for entry in extraction.entries}
    for statement in (
        content.title,
        *content.what_happened,
        *content.document_context,
        *content.original_log_evidence,
        *content.open_questions,
    ):
        if not set(statement.supporting_entry_ids) <= known:
            raise ValueError("Case content must cite extracted current-log evidence")
    if content.related_cases and history.status != "completed":
        raise ValueError("Related cases require completed authorised retrieval")
    eligible = {
        (item.case_id, item.knowledge_id, item.knowledge_version): item
        for item in history.candidates
    }
    for reference in content.related_cases:
        key = (reference.case_id, reference.knowledge_id, reference.knowledge_version)
        if key not in eligible:
            raise ValueError("Related case was not returned by authorised retrieval")
        if not reference.differing_details:
            raise ValueError("Related case must state a material difference")
        if not set(reference.current_entry_ids) <= known:
            raise ValueError("Related-case comparison must cite current extracted evidence")
