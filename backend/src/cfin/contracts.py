"""Validated handoffs for the synthetic CFIN workflow.

Models validate structure; routing additionally checks the saved source catalogue,
lookup scope and governance state. A supported AI finding is still subject to
human review. Identifiers are always strings, including all leading zeroes.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

Identifier = Annotated[StrictStr, StringConstraints(min_length=1, pattern=r".*\S.*")]
Text = Annotated[StrictStr, StringConstraints(min_length=1, pattern=r".*\S.*")]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def label(self) -> str:
        return {self.P1: "P1 — Low", self.P2: "P2 — Medium", self.P3: "P3 — High"}[self]

    @property
    def sort_rank(self) -> int:
        return {self.P3: 0, self.P2: 1, self.P1: 2}[self]


class CaseStatus(StrEnum):
    CREATED = "created"
    OWNER_NOTIFIED = "owner_notified"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    DOCUMENT_REPROCESSED = "document_reprocessed"


class DiagnosisStatus(StrEnum):
    AI_SUPPORTED = "ai_supported"
    HUMAN_CONFIRMED = "human_confirmed"
    NEEDS_REVIEW = "needs_review"


class ValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ReuseStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class FailureCategory(StrEnum):
    MISSING_TARGET_GL_MASTER_DATA = "missing_target_gl_master_data"
    MISSING_GL_MAPPING = "missing_gl_mapping"
    CLOSED_TARGET_POSTING_PERIOD = "closed_target_posting_period"
    MULTIPLE_BLOCKERS = "multiple_blockers"
    CAUSE_NOT_ESTABLISHED = "cause_not_established"
    UNKNOWN = "unknown"


class AffectedObject(StrEnum):
    GL_ACCOUNT = "gl_account"
    COST_CENTER = "cost_center"
    PROFIT_CENTER = "profit_center"
    ASSET = "asset"
    POSTING_PERIOD = "posting_period"
    UNKNOWN = "unknown"


class LookupState(StrEnum):
    FOUND = "found"
    CONFIRMED_ABSENT = "confirmed_absent"
    UNAVAILABLE = "unavailable"
    INCOMPLETE = "incomplete"


class DocumentIdentity(Contract):
    workspace_id: Identifier | None = None
    source_system: Identifier | None = None
    source_client: Identifier | None = None
    source_company_code: Identifier | None = None
    fiscal_year: Identifier | None = None
    document_number: Identifier | None = None
    target_system: Identifier | None = None
    target_client: Identifier | None = None
    interface: Identifier | None = None

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(name for name in type(self).model_fields if getattr(self, name) is None)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields

    def canonical_key(self) -> tuple[str, ...]:
        if not self.is_complete:
            raise ValueError("Document identity required before correlation or diagnosis")
        return tuple(getattr(self, name) for name in type(self).model_fields)


class BusinessContext(Contract):
    source_account: Identifier | None = None
    target_account: Identifier | None = None
    company_code: Identifier | None = None
    chart_of_accounts: Identifier | None = None
    controlling_area: Identifier | None = None
    posting_date: date | None = None
    currency: Identifier | None = None


class IntakeManifest(Contract):
    scenario_id: Identifier
    synthetic: Literal[True] = True
    delivery_key: Identifier
    content_sha256: Sha256
    source_id: Identifier
    source_version: Identifier
    identity: DocumentIdentity
    attempt_id: Identifier
    processing_at: AwareDatetime
    processing_order: Annotated[StrictInt, Field(ge=1)] | None = None
    business_context: BusinessContext


class ReferenceGovernance(Contract):
    reuse_status: ReuseStatus = ReuseStatus.PENDING_REVIEW
    approved_version: Identifier | None = None
    reviewer: Identifier | None = None
    reviewed_at: AwareDatetime | None = None


class SourceReference(Contract):
    source_id: Identifier
    source_version: Identifier
    kind: Literal["text", "records"]
    observed_at: AwareDatetime
    attempt_id: Identifier | None = None
    synthetic: Literal[True] = True
    line_count: PositiveInt | None = None
    record_ids: list[Identifier] = Field(default_factory=list)
    governance: ReferenceGovernance | None = None

    @model_validator(mode="after")
    def validate_locator_catalogue(self) -> "SourceReference":
        if self.kind == "text" and (self.line_count is None or self.record_ids):
            raise ValueError("Text source needs line_count and no record_ids")
        if self.kind == "records" and (not self.record_ids or self.line_count is not None):
            raise ValueError("Record source needs record_ids and no line_count")
        if len(self.record_ids) != len(set(self.record_ids)):
            raise ValueError("Source record_ids must be unique")
        if (
            self.governance
            and self.governance.reuse_status == ReuseStatus.APPROVED
            and (
                self.governance.approved_version != self.source_version
                or self.governance.reviewer is None
                or self.governance.reviewed_at is None
            )
        ):
            raise ValueError("Reference approval needs an actual reviewer, time and exact version")
        return self


class Citation(Contract):
    source_id: Identifier
    source_version: Identifier
    attempt_id: Identifier | None = None
    line_start: PositiveInt | None = None
    line_end: PositiveInt | None = None
    record_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> "Citation":
        has_lines = self.line_start is not None or self.line_end is not None
        if has_lines == (self.record_id is not None):
            raise ValueError("Citation must identify a line range or a record")
        if has_lines and (
            self.line_start is None or self.line_end is None or self.line_end < self.line_start
        ):
            raise ValueError("Citation needs an ordered, inclusive line range")
        return self


def source_matches_catalogue(source: SourceReference, registered: SourceReference | None) -> bool:
    """Allow scoped record locators while requiring the same saved snapshot metadata."""
    return (
        registered is not None
        and source.model_dump(exclude={"record_ids"})
        == registered.model_dump(exclude={"record_ids"})
        and set(source.record_ids).issubset(set(registered.record_ids))
    )


def validate_citations(
    citations: list[Citation], catalogue: list[SourceReference], *, attempt_id: str
) -> None:
    """Resolve citations against the authorised immutable input catalogue."""
    sources = {(source.source_id, source.source_version): source for source in catalogue}
    if len(sources) != len(catalogue):
        raise ValueError("Source catalogue contains duplicate source/version entries")
    for citation in citations:
        source = sources.get((citation.source_id, citation.source_version))
        if source is None:
            raise ValueError("Citation source/version is outside the supplied catalogue")
        if citation.attempt_id != source.attempt_id:
            raise ValueError("Citation attempt does not match its source")
        if source.attempt_id is not None and source.attempt_id != attempt_id:
            raise ValueError("Citation belongs to a different attempt")
        if citation.record_id is not None:
            if source.kind != "records" or citation.record_id not in source.record_ids:
                raise ValueError("Citation record is outside the supplied source")
        elif source.kind != "text" or citation.line_end > source.line_count:
            raise ValueError("Citation line range is outside the supplied source")


class LookupResponse(Contract):
    lookup_id: Identifier
    state: LookupState
    query_scope: dict[Identifier, Identifier] = Field(min_length=1)
    scope_complete: StrictBool
    records: list[dict[str, Any]] = Field(default_factory=list)
    source: SourceReference
    citations: list[Citation] = Field(min_length=1)
    detail: Text | None = None

    @model_validator(mode="after")
    def validate_lookup_state(self) -> "LookupResponse":
        if self.state == LookupState.CONFIRMED_ABSENT and (not self.scope_complete or self.records):
            raise ValueError("Confirmed absence requires a complete scope and no returned records")
        if self.state == LookupState.FOUND and not self.records:
            raise ValueError("Found lookup requires returned records")
        if self.state == LookupState.UNAVAILABLE and (self.records or self.scope_complete):
            raise ValueError("Unavailable lookup cannot claim completed scope or returned records")
        if self.state == LookupState.INCOMPLETE and self.scope_complete:
            raise ValueError("Incomplete lookup cannot claim completed scope")
        validate_citations(self.citations, [self.source], attempt_id=self.source.attempt_id or "")
        return self


class EvidenceGap(Contract):
    reason: Text
    material: StrictBool = True
    citations: list[Citation] = Field(default_factory=list)


class PreparedMessage(Contract):
    original_wording: Text
    explanation: Text
    citations: list[Citation] = Field(min_length=1)


class Preparation(Contract):
    run_id: Identifier
    attempt_id: Identifier
    input_source_version: Identifier
    identity: DocumentIdentity
    business_context: BusinessContext
    affected_object: AffectedObject = AffectedObject.UNKNOWN
    messages: list[PreparedMessage] = Field(min_length=1)
    gaps: list[EvidenceGap] = Field(default_factory=list)


class CheckId(StrEnum):
    APPROVED_MAPPING_IDENTIFIES_TARGET = "approved_mapping_identifies_target"
    TARGET_MASTER_ABSENCE_CONFIRMED = "target_master_absence_confirmed"
    APPLICABLE_MAPPING_ABSENCE_CONFIRMED = "applicable_mapping_absence_confirmed"
    INDEPENDENT_APPROVED_TARGET_REFERENCE = "independent_approved_target_reference"
    TARGET_MASTER_EXISTS = "target_master_exists"
    FISCAL_PERIOD_DERIVED = "fiscal_period_derived"
    APPLICABLE_POSTING_PERIOD_CLOSED = "applicable_posting_period_closed"


class CheckState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class EvidenceCheck(Contract):
    check_id: CheckId
    result: CheckState
    observation: Text
    citations: list[Citation] = Field(default_factory=list)
    lookup_id: Identifier | None = None

    @model_validator(mode="after")
    def require_observation_evidence(self) -> "EvidenceCheck":
        if self.result in (CheckState.PASSED, CheckState.FAILED) and not self.citations:
            raise ValueError("Passed/failed checks require cited observations")
        return self


REQUIRED_CHECKS = {
    FailureCategory.MISSING_TARGET_GL_MASTER_DATA: {
        CheckId.APPROVED_MAPPING_IDENTIFIES_TARGET,
        CheckId.TARGET_MASTER_ABSENCE_CONFIRMED,
    },
    FailureCategory.MISSING_GL_MAPPING: {
        CheckId.APPLICABLE_MAPPING_ABSENCE_CONFIRMED,
        CheckId.INDEPENDENT_APPROVED_TARGET_REFERENCE,
        CheckId.TARGET_MASTER_EXISTS,
    },
    FailureCategory.CLOSED_TARGET_POSTING_PERIOD: {
        CheckId.FISCAL_PERIOD_DERIVED,
        CheckId.APPLICABLE_POSTING_PERIOD_CLOSED,
    },
}


class DiagnosticFinding(Contract):
    cause: FailureCategory
    statement: Text
    supported: StrictBool
    affected_object: AffectedObject = AffectedObject.UNKNOWN
    checks: list[EvidenceCheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_supported_checks(self) -> "DiagnosticFinding":
        checks = {check.check_id: check for check in self.checks}
        if len(checks) != len(self.checks):
            raise ValueError("Finding check identifiers must be unique")
        if self.supported:
            required = REQUIRED_CHECKS.get(self.cause)
            if required is None or not all(
                check_id in checks and checks[check_id].result == CheckState.PASSED
                for check_id in required
            ):
                raise ValueError("Supported cause requires every required check to pass")
        return self


class HumanConfirmation(Contract):
    actor_id: Identifier
    acting_role: Identifier
    confirmed_at: AwareDatetime
    rationale: Text
    citations: list[Citation] = Field(min_length=1)


class HistoryReference(Contract):
    knowledge_id: Identifier
    version: PositiveInt
    matching_facts: list[Text] = Field(default_factory=list)
    differing_facts: list[Text] = Field(default_factory=list)


class Diagnosis(Contract):
    run_id: Identifier
    attempt_id: Identifier
    input_source_version: Identifier
    status: DiagnosisStatus
    findings: list[DiagnosticFinding] = Field(default_factory=list)
    alternatives: list[EvidenceGap] = Field(default_factory=list)
    contradictions: list[EvidenceGap] = Field(default_factory=list)
    missing_checks: list[EvidenceGap] = Field(default_factory=list)
    uncertainty: list[EvidenceGap] = Field(default_factory=list)
    human_confirmation: HumanConfirmation | None = None
    history_references: list[HistoryReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_honest_status(self) -> "Diagnosis":
        if self.status != DiagnosisStatus.NEEDS_REVIEW and (
            not any(finding.supported for finding in self.findings)
            or any(
                gap.material for gap in self.contradictions + self.missing_checks + self.uncertainty
            )
        ):
            raise ValueError(
                "Established diagnosis requires supported findings and no material gaps"
            )
        if self.status == DiagnosisStatus.HUMAN_CONFIRMED and self.human_confirmation is None:
            raise ValueError("Human-confirmed diagnosis requires explicit human confirmation")
        return self

    def all_citations(self) -> list[Citation]:
        citations = [
            citation
            for finding in self.findings
            for check in finding.checks
            for citation in check.citations
        ]
        citations.extend(
            citation
            for gap in self.alternatives
            + self.contradictions
            + self.missing_checks
            + self.uncertainty
            for citation in gap.citations
        )
        if self.human_confirmation:
            citations.extend(self.human_confirmation.citations)
        return citations


class GuidanceVersion(Contract):
    guidance_id: Identifier
    source_version: Identifier
    cause: FailureCategory
    scope: dict[Identifier, Identifier] = Field(min_length=1)
    reuse_status: ReuseStatus = ReuseStatus.PENDING_REVIEW
    approved_version: Identifier | None = None
    reviewer: Identifier | None = None
    reviewed_at: AwareDatetime | None = None
    effective_from: date
    review_due: date
    expires_on: date | None = None
    withdrawn_at: AwareDatetime | None = None
    shared_policies: list["GuidanceVersion"] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_version_approval(self) -> "GuidanceVersion":
        if self.reuse_status == ReuseStatus.APPROVED and (
            self.approved_version != self.source_version
            or self.reviewer is None
            or self.reviewed_at is None
        ):
            raise ValueError(
                "Approval requires an actual reviewer, time and exact approved version"
            )
        if self.expires_on is not None and self.expires_on < self.effective_from:
            raise ValueError("Guidance expiry must not precede its effective date")
        return self


class RouteReason(StrEnum):
    ELIGIBLE = "eligible"
    CAUSE_NOT_ESTABLISHED = "cause_not_established"
    GUIDANCE_UNAVAILABLE = "guidance_unavailable"
    MULTIPLE_BLOCKERS = "multiple_blockers"


class RoutingDecision(Contract):
    agent3_eligible: StrictBool
    reason: RouteReason
    detail: Text
    guidance_id: Identifier | None = None
    guidance_version: Identifier | None = None
    review_overdue: StrictBool = False


def _guidance_matches(
    guidance: GuidanceVersion, scope: dict[str, str], cause: FailureCategory, day: date
) -> bool:
    return (
        guidance.cause == cause
        and all(scope.get(key) == value for key, value in guidance.scope.items())
        and guidance.effective_from <= day
        and (guidance.expires_on is None or day <= guidance.expires_on)
    )


def _guidance_approved(guidance: GuidanceVersion, scope: dict[str, str], day: date) -> bool:
    return (
        guidance.reuse_status == ReuseStatus.APPROVED
        and guidance.withdrawn_at is None
        and all(
            _guidance_matches(policy, scope, policy.cause, day)
            and _guidance_approved(policy, scope, day)
            for policy in guidance.shared_policies
        )
    )


def _mapping_applies(record: dict[str, Any], scope: dict[str, Any], day: date) -> bool:
    """Match row applicability to the document date, independently of agent assertions."""
    try:
        effective = date.fromisoformat(record["effective_from"])
        expiry = date.fromisoformat(record["expires_on"]) if record.get("expires_on") else None
    except (KeyError, TypeError, ValueError):
        return False
    row_scope = record.get("scope", {})
    return (
        isinstance(row_scope, dict)
        and all(scope.get(key) == value for key, value in row_scope.items())
        and effective <= day
        and (expiry is None or day <= expiry)
        and record.get("posting_date_in_scope", day.isoformat()) == day.isoformat()
    )


def _missing_mapping_supported(
    finding: DiagnosticFinding,
    diagnosis: Diagnosis,
    identity: DocumentIdentity,
    business_context: BusinessContext,
    source_catalogue: list[SourceReference],
    lookups: list[LookupResponse],
) -> bool:
    """Require scoped absence, separately identified approved target design, and existing master."""
    sources = {(item.source_id, item.source_version): item for item in source_catalogue}
    checks = {item.check_id: item for item in finding.checks}
    by_id = {item.lookup_id: item for item in lookups}
    scope = {
        **identity.model_dump(exclude_none=True),
        **business_context.model_dump(exclude_none=True, mode="json"),
    }
    mapping_scope = {
        key: scope.get(key)
        for key in (
            "source_system",
            "source_client",
            "source_company_code",
            "target_system",
            "target_client",
            "company_code",
            "chart_of_accounts",
            "interface",
            "source_account",
        )
    }
    target_scope = {
        key: scope.get(key)
        for key in (
            "target_system",
            "target_client",
            "company_code",
            "chart_of_accounts",
            "target_account",
        )
    }
    if any(value is None for value in (*mapping_scope.values(), *target_scope.values())):
        return False
    failure_time = next(
        (
            item.observed_at
            for item in source_catalogue
            if item.kind == "text" and item.attempt_id == diagnosis.attempt_id
        ),
        None,
    )

    def valid_lookup(lookup: LookupResponse | None, check: EvidenceCheck) -> bool:
        return bool(
            lookup
            and lookup.scope_complete
            and source_matches_catalogue(
                lookup.source, sources.get((lookup.source.source_id, lookup.source.source_version))
            )
            and set(lookup.citations).issubset(set(check.citations))
        )

    absent_check = checks[CheckId.APPLICABLE_MAPPING_ABSENCE_CONFIRMED]
    absent = by_id.get(absent_check.lookup_id)
    if not valid_lookup(absent, absent_check) or (
        absent.state != LookupState.CONFIRMED_ABSENT
        or absent.source.attempt_id != diagnosis.attempt_id
        or absent.source.observed_at != failure_time
        or any(absent.query_scope.get(key) != value for key, value in mapping_scope.items())
    ):
        return False
    reference_check = checks[CheckId.INDEPENDENT_APPROVED_TARGET_REFERENCE]
    reference = by_id.get(reference_check.lookup_id)
    if not valid_lookup(reference, reference_check) or (
        reference.state != LookupState.FOUND
        or reference.source.governance is None
        or reference.source.governance.reuse_status != ReuseStatus.APPROVED
        or business_context.posting_date is None
        or any(reference.query_scope.get(key) != value for key, value in mapping_scope.items())
    ):
        return False
    applicable = [
        record
        for record in reference.records
        if record.get("reference_kind") == "independent_target_design"
        and record.get("source_account") == business_context.source_account
        and record.get("target_account") == business_context.target_account
        and _mapping_applies(record, scope, business_context.posting_date)
    ]
    if len(applicable) != 1 or not any(
        citation.record_id == applicable[0].get("record_id")
        and citation.source_id == reference.source.source_id
        and citation.source_version == reference.source.source_version
        for citation in reference_check.citations
    ):
        return False
    master_check = checks[CheckId.TARGET_MASTER_EXISTS]
    selected = by_id.get(master_check.lookup_id)
    if not valid_lookup(selected, master_check):
        return False
    components = set()
    for lookup in lookups:
        if (
            lookup.state != LookupState.FOUND
            or not valid_lookup(lookup, master_check)
            or lookup.source.attempt_id != diagnosis.attempt_id
            or lookup.source.observed_at != failure_time
            or any(lookup.query_scope.get(key) != value for key, value in target_scope.items())
        ):
            continue
        if any(
            record.get("target_account") != business_context.target_account
            or record.get("chart_of_accounts") != business_context.chart_of_accounts
            or record.get("posting_blocked") is not False
            for record in lookup.records
        ):
            continue
        component = lookup.query_scope.get("missing_component")
        if component == "company_code_extension" and any(
            record.get("company_code") != business_context.company_code for record in lookup.records
        ):
            continue
        components.add(component)
    return {"chart_account", "company_code_extension"}.issubset(components)


def route_diagnosis(
    diagnosis: Diagnosis,
    *,
    identity: DocumentIdentity,
    business_context: BusinessContext,
    source_catalogue: list[SourceReference],
    lookups: list[LookupResponse],
    guidance: list[GuidanceVersion],
    as_of: date,
) -> RoutingDecision:
    """Gate Agent 3; owner availability is intentionally independent of eligibility."""
    validate_citations(diagnosis.all_citations(), source_catalogue, attempt_id=diagnosis.attempt_id)

    def blocked(reason: RouteReason, detail: str) -> RoutingDecision:
        return RoutingDecision(agent3_eligible=False, reason=reason, detail=detail)

    supported = [finding for finding in diagnosis.findings if finding.supported]
    if (
        not identity.is_complete
        or diagnosis.status == DiagnosisStatus.NEEDS_REVIEW
        or not supported
    ):
        return blocked(
            RouteReason.CAUSE_NOT_ESTABLISHED,
            "Document identity or required cause evidence needs review",
        )
    if len(supported) > 1:
        return blocked(
            RouteReason.MULTIPLE_BLOCKERS,
            "Several independent findings require coordinated human investigation",
        )
    finding = supported[0]
    scope = {
        **identity.model_dump(exclude_none=True),
        **business_context.model_dump(exclude_none=True, mode="json"),
    }
    if finding.cause == FailureCategory.MISSING_GL_MAPPING:
        if not _missing_mapping_supported(
            finding, diagnosis, identity, business_context, source_catalogue, lookups
        ):
            return blocked(
                RouteReason.CAUSE_NOT_ESTABLISHED,
                "Missing mapping needs a completed absence audit, approved independent target "
                "reference and existing target chart account/company extension",
            )
        candidates = [
            item for item in guidance if _guidance_matches(item, scope, finding.cause, as_of)
        ]
        if len(candidates) != 1 or not _guidance_approved(candidates[0], scope, as_of):
            return blocked(
                RouteReason.GUIDANCE_UNAVAILABLE,
                "Guidance is missing, conflicting, unapproved, expired or withdrawn",
            )
        selected = candidates[0]
        return RoutingDecision(
            agent3_eligible=True,
            reason=RouteReason.ELIGIBLE,
            detail="Supported missing mapping with approved independent target and guidance",
            guidance_id=selected.guidance_id,
            guidance_version=selected.source_version,
            review_overdue=as_of > selected.review_due,
        )
    if finding.cause != FailureCategory.MISSING_TARGET_GL_MASTER_DATA:
        return blocked(
            RouteReason.CAUSE_NOT_ESTABLISHED,
            "This increment supports missing target G/L master data and missing G/L mapping",
        )
    mapping_check = next(
        check
        for check in finding.checks
        if check.check_id == CheckId.APPROVED_MAPPING_IDENTIFIES_TARGET
    )
    sources = {(source.source_id, source.source_version): source for source in source_catalogue}
    mapping_lookup = next(
        (item for item in lookups if item.lookup_id == mapping_check.lookup_id), None
    )
    if (
        mapping_lookup is None
        or not source_matches_catalogue(
            mapping_lookup.source,
            sources.get((mapping_lookup.source.source_id, mapping_lookup.source.source_version)),
        )
        or mapping_lookup.state != LookupState.FOUND
        or not mapping_lookup.scope_complete
        or not any(
            (reference := sources[(citation.source_id, citation.source_version)]).governance
            is not None
            and reference.governance.reuse_status == ReuseStatus.APPROVED
            and citation.source_id == mapping_lookup.source.source_id
            and citation.source_version == mapping_lookup.source.source_version
            for citation in mapping_check.citations
        )
    ):
        return blocked(
            RouteReason.CAUSE_NOT_ESTABLISHED,
            "An explicitly approved mapping reference is required",
        )
    scope = {
        **identity.model_dump(exclude_none=True),
        **business_context.model_dump(exclude_none=True, mode="json"),
    }
    mapping_scope = {
        key: scope.get(key)
        for key in (
            "source_system",
            "source_client",
            "source_company_code",
            "target_system",
            "target_client",
            "company_code",
            "chart_of_accounts",
            "interface",
        )
    }
    applicable_rows = [
        record
        for record in mapping_lookup.records
        if business_context.source_account is not None
        and record.get("source_account") == business_context.source_account
        and business_context.posting_date is not None
        and _mapping_applies(record, scope, business_context.posting_date)
    ]
    if (
        any(
            value is None or mapping_lookup.query_scope.get(key) != value
            for key, value in mapping_scope.items()
        )
        or len(applicable_rows) != 1
        or business_context.target_account is None
        or applicable_rows[0].get("target_account") != business_context.target_account
        or not any(
            citation.record_id == applicable_rows[0].get("record_id")
            for citation in mapping_check.citations
        )
    ):
        return blocked(
            RouteReason.CAUSE_NOT_ESTABLISHED,
            "Approved mapping must identify the intended target for the applicable source scope",
        )
    required_scope = {
        key: scope.get(key)
        for key in (
            "target_system",
            "target_client",
            "company_code",
            "chart_of_accounts",
            "target_account",
        )
    }
    absent_check = next(
        check
        for check in finding.checks
        if check.check_id == CheckId.TARGET_MASTER_ABSENCE_CONFIRMED
    )
    lookup = next((item for item in lookups if item.lookup_id == absent_check.lookup_id), None)
    if (
        any(value is None for value in required_scope.values())
        or lookup is None
        or not source_matches_catalogue(
            lookup.source, sources.get((lookup.source.source_id, lookup.source.source_version))
        )
        or lookup.state != LookupState.CONFIRMED_ABSENT
        or lookup.source.attempt_id != diagnosis.attempt_id
        or any(lookup.query_scope.get(key) != value for key, value in required_scope.items())
        or lookup.query_scope.get("missing_component")
        not in ("chart_account", "company_code_extension")
        or not set(lookup.citations).issubset(set(absent_check.citations))
    ):
        return blocked(
            RouteReason.CAUSE_NOT_ESTABLISHED,
            "A complete applicable target-master absence lookup is required",
        )
    candidates = [item for item in guidance if _guidance_matches(item, scope, finding.cause, as_of)]
    if len(candidates) != 1 or not _guidance_approved(candidates[0], scope, as_of):
        return blocked(
            RouteReason.GUIDANCE_UNAVAILABLE,
            "Guidance is missing, conflicting, unapproved, expired or withdrawn",
        )
    selected = candidates[0]
    return RoutingDecision(
        agent3_eligible=True,
        reason=RouteReason.ELIGIBLE,
        detail="One supported cause and one applicable approved guidance version",
        guidance_id=selected.guidance_id,
        guidance_version=selected.source_version,
        review_overdue=as_of > selected.review_due,
    )


class CaseBrief(Contract):
    run_id: Identifier
    attempt_id: Identifier
    input_source_version: Identifier
    title: Text
    description: Text
    business_context: BusinessContext
    category: FailureCategory
    affected_object: AffectedObject
    diagnosis_status: DiagnosisStatus
    guidance_id: Identifier
    guidance_version: Identifier
    required_human_steps: list[Text] = Field(min_length=1)
    unmet_prerequisites: list[Text] = Field(default_factory=list)
    uncertainty: list[EvidenceGap] = Field(default_factory=list)
    citations: list[Citation] = Field(min_length=1)


class ProofAttachment(Contract):
    proof_id: Identifier
    source_id: Identifier
    source_version: Identifier
    attempt_id: Identifier
    work_cycle_id: Identifier
    origin: Literal["uploaded_evidence", "simulated_fixture"]
    content_type: Literal["application/pdf", "image/png", "image/jpeg", "text/plain"]
    stored: StrictBool

    @model_validator(mode="after")
    def require_stored_proof(self) -> "ProofAttachment":
        if not self.stored:
            raise ValueError("Proof must be successfully stored")
        return self


class HumanMilestone(Contract):
    attempt_id: Identifier
    work_cycle_id: Identifier
    actor_id: Identifier
    acting_role: Identifier
    occurred_at: AwareDatetime
    human_confirmed: StrictBool
    proof: list[ProofAttachment] = Field(min_length=1)

    @model_validator(mode="after")
    def require_current_proof(self) -> "HumanMilestone":
        if not self.human_confirmed:
            raise ValueError("Milestone requires explicit human confirmation of the saved proof")
        if any(
            item.attempt_id != self.attempt_id or item.work_cycle_id != self.work_cycle_id
            for item in self.proof
        ):
            raise ValueError("Proof must refer to the milestone's attempt and work cycle")
        return self


class CorrectionMilestone(HumanMilestone):
    explanation: Text
    target_system: Identifier
    target_object: Identifier
    no_change_needed: StrictBool = False


class ReprocessingMilestone(HumanMilestone):
    successful: StrictBool
    target_document_reference: Identifier

    @model_validator(mode="after")
    def require_success(self) -> "ReprocessingMilestone":
        if not self.successful:
            raise ValueError("Failed retry does not qualify for Document Reprocessed")
        return self


class ValidationCheck(Contract):
    dimension: Literal["amount_currency", "company", "accounts", "source_target_reference"]
    result: Literal["passed", "failed", "not_applicable"]
    expected: Text
    observed: Text
    reason: Text | None = None

    @model_validator(mode="after")
    def require_justification(self) -> "ValidationCheck":
        if self.result != "passed" and self.reason is None:
            raise ValueError("Failed or not-applicable posting checks need a reason")
        return self


class ValidationRecord(Contract):
    attempt_id: Identifier
    work_cycle_id: Identifier
    status: ValidationStatus = ValidationStatus.PENDING
    attestation: HumanMilestone | None = None
    checks: list[ValidationCheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_validation_evidence(self) -> "ValidationRecord":
        if self.attestation and (
            self.attestation.attempt_id != self.attempt_id
            or self.attestation.work_cycle_id != self.work_cycle_id
        ):
            raise ValueError("Validation attestation must use the selected attempt and cycle")
        if self.status != ValidationStatus.PENDING and self.attestation is None:
            raise ValueError("Completed validation requires validator, time and saved proof")
        dimensions = {check.dimension for check in self.checks}
        if len(dimensions) != len(self.checks):
            raise ValueError("Validation dimensions must be unique")
        if self.status == ValidationStatus.PASSED and (
            dimensions != {"amount_currency", "company", "accounts", "source_target_reference"}
            or any(check.result == "failed" for check in self.checks)
        ):
            raise ValueError("Passed validation requires all four checks with no failures")
        if self.status == ValidationStatus.FAILED and not any(
            check.result == "failed" for check in self.checks
        ):
            raise ValueError("Failed validation requires a failed check and discrepancy")
        return self


class ResolutionScope(Contract):
    target_system: Identifier
    target_object: Identifier
    company_code: Identifier
    reuse_limitations: Text


class ResolutionRecord(HumanMilestone):
    cause_status: Literal["confirmed", "not_confirmed"]
    cause: FailureCategory | None = None
    cause_evidence: list[Citation] = Field(default_factory=list)
    unresolved_gaps: list[Text] = Field(default_factory=list)
    correction_or_no_change: Text
    scope: ResolutionScope
    outcome: Text
    reuse_status: ReuseStatus = ReuseStatus.PENDING_REVIEW

    @model_validator(mode="after")
    def require_cause_or_gaps(self) -> "ResolutionRecord":
        if self.cause_status == "confirmed" and (
            self.cause not in REQUIRED_CHECKS or not self.cause_evidence or self.unresolved_gaps
        ):
            raise ValueError(
                "Confirmed resolution cause requires a cause and cited evidence "
                "with no unresolved cause gaps"
            )
        if self.cause_status == "not_confirmed" and (
            self.cause is not None or not self.unresolved_gaps
        ):
            raise ValueError(
                "Not-confirmed cause requires explicit unresolved gaps and no confirmed label"
            )
        if self.reuse_status == ReuseStatus.APPROVED:
            raise ValueError(
                "Reuse approval requires a separate versioned review; "
                "resolution cannot self-publish"
            )
        return self


def derive_resolved(
    *,
    current_attempt_id: str,
    current_work_cycle_id: str,
    case_status: CaseStatus,
    attempt_order_known: bool,
    unreviewed_new_failure: bool,
    correction: CorrectionMilestone | None,
    reprocessing: ReprocessingMilestone | None,
    validation: ValidationRecord,
    resolution_record: ResolutionRecord | None,
) -> bool:
    """Operational resolution is independent of historical reuse approval."""
    records = (correction, reprocessing, validation, resolution_record)
    return (
        case_status == CaseStatus.DOCUMENT_REPROCESSED
        and attempt_order_known
        and not unreviewed_new_failure
        and validation.status == ValidationStatus.PASSED
        and all(
            record is not None
            and record.attempt_id == current_attempt_id
            and record.work_cycle_id == current_work_cycle_id
            for record in records
        )
    )
