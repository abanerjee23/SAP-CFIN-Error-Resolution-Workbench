from datetime import date

import pytest
from pydantic import ValidationError

from cfin.contracts import (
    BusinessContext,
    CaseStatus,
    Citation,
    CorrectionMilestone,
    Diagnosis,
    DocumentIdentity,
    GuidanceVersion,
    HumanMilestone,
    IntakeManifest,
    LookupResponse,
    Priority,
    ProofAttachment,
    ReprocessingMilestone,
    ResolutionRecord,
    SourceReference,
    ValidationRecord,
    derive_resolved,
    route_diagnosis,
    validate_citations,
)

AT = "2026-09-30T09:00:00Z"
ATTEMPT = "MD01-0001"
IDENTITY = dict(
    workspace_id="demo",
    source_system="ERP",
    source_client="010",
    source_company_code="0010",
    fiscal_year="2026",
    document_number="0000123456",
    target_system="CFIN",
    target_client="100",
    interface="CFIN_GL",
)
CONTEXT = dict(
    source_account="0000400000",
    target_account="0041001000",
    company_code="0010",
    chart_of_accounts="SYN1",
    posting_date="2026-09-30",
    currency="GBP",
)


def source(source_id="target", *, approved=False, kind="records"):
    data = dict(
        source_id=source_id, source_version="1", kind=kind, observed_at=AT, attempt_id=ATTEMPT
    )
    if kind == "records":
        data["record_ids"] = ["record-1"]
    else:
        data["line_count"] = 3
    if source_id == "mapping":
        data["governance"] = dict(
            reuse_status="pending_review", approved_version=None, reviewer=None, reviewed_at=None
        )
    if approved:
        data["governance"] = dict(
            reuse_status="approved",
            approved_version="1",
            reviewer="actual-demo-actor",
            reviewed_at=AT,
        )
    return SourceReference.model_validate(data)


def cite(source_id="target", **kwargs):
    return Citation(
        source_id=source_id,
        source_version="1",
        attempt_id=ATTEMPT,
        **(kwargs or {"record_id": "record-1"}),
    )


def lookup(state="confirmed_absent", *, scope_complete=True, records=None):
    return LookupResponse(
        lookup_id="target-lookup",
        state=state,
        query_scope=dict(
            target_system="CFIN",
            target_client="100",
            company_code="0010",
            target_account="0041001000",
            chart_of_accounts="SYN1",
            missing_component="chart_account",
        ),
        scope_complete=scope_complete,
        records=records or [],
        source=source(),
        citations=[cite()],
    )


def mapping_lookup(*, approved=True):
    return LookupResponse(
        lookup_id="mapping-lookup",
        state="found",
        scope_complete=True,
        query_scope={**IDENTITY, "company_code": "0010", "chart_of_accounts": "SYN1"},
        records=[
            dict(
                record_id="record-1",
                source_account="0000400000",
                target_account="0041001000",
                effective_from="2026-09-01",
                expires_on="2027-03-31",
            )
        ],
        source=source("mapping", approved=approved),
        citations=[cite("mapping")],
    )


def diagnosis(**changes):
    data = dict(
        run_id="run-1",
        attempt_id=ATTEMPT,
        input_source_version="1",
        status="ai_supported",
        findings=[
            dict(
                cause="missing_target_gl_master_data",
                statement="Required target G/L account absent",
                supported=True,
                affected_object="gl_account",
                checks=[
                    dict(
                        check_id="approved_mapping_identifies_target",
                        result="passed",
                        observation="Approved mapping identifies target",
                        citations=[cite("mapping").model_dump()],
                        lookup_id="mapping-lookup",
                    ),
                    dict(
                        check_id="target_master_absence_confirmed",
                        result="passed",
                        observation="Complete exact-key lookup returned no account",
                        citations=[cite().model_dump()],
                        lookup_id="target-lookup",
                    ),
                ],
            )
        ],
    )
    data.update(changes)
    return Diagnosis.model_validate(data)


def guidance(**changes):
    data = dict(
        guidance_id="gl-guide",
        source_version="1",
        cause="missing_target_gl_master_data",
        scope=dict(target_system="CFIN", company_code="0010"),
        reuse_status="approved",
        approved_version="1",
        reviewer="actual-demo-actor",
        reviewed_at=AT,
        effective_from="2026-09-01",
        review_due="2026-09-20",
        expires_on="2027-03-31",
    )
    data.update(changes)
    return GuidanceVersion.model_validate(data)


def route(*, guides=None, lookups=None, result=None):
    responses = lookups if lookups is not None else [lookup(), mapping_lookup()]
    return route_diagnosis(
        result or diagnosis(),
        identity=DocumentIdentity(**IDENTITY),
        business_context=BusinessContext(**CONTEXT),
        source_catalogue=[
            source(),
            source("mapping").model_copy(update={"governance": responses[-1].source.governance}),
        ],
        lookups=responses,
        guidance=guides if guides is not None else [guidance()],
        as_of=date(2026, 9, 30),
    )


def proof(**changes):
    data = dict(
        proof_id="proof-1",
        source_id="stored-result",
        source_version="1",
        attempt_id=ATTEMPT,
        work_cycle_id="cycle-1",
        origin="simulated_fixture",
        content_type="text/plain",
        stored=True,
    )
    data.update(changes)
    return data


def milestone(**changes):
    data = dict(
        attempt_id=ATTEMPT,
        work_cycle_id="cycle-1",
        actor_id="actual-demo-actor",
        acting_role="Demo Validator",
        occurred_at=AT,
        human_confirmed=True,
        proof=[proof()],
    )
    data.update(changes)
    return data


def validation(**changes):
    data = dict(
        attempt_id=ATTEMPT,
        work_cycle_id="cycle-1",
        status="passed",
        attestation=milestone(),
        checks=[
            dict(
                dimension=dimension,
                result="passed",
                expected="Expected fixture posting",
                observed="Matching simulated result",
            )
            for dimension in ("amount_currency", "company", "accounts", "source_target_reference")
        ],
    )
    data.update(changes)
    return ValidationRecord.model_validate(data)


def resolution(**changes):
    data = dict(
        **milestone(),
        cause_status="confirmed",
        cause="missing_target_gl_master_data",
        cause_evidence=[cite().model_dump()],
        correction_or_no_change="Simulated creation of required account",
        scope=dict(
            target_system="CFIN",
            target_object="0041001000",
            company_code="0010",
            reuse_limitations="Synthetic example only",
        ),
        outcome="Simulated target posting validated",
    )
    data.update(changes)
    return ResolutionRecord.model_validate(data)


def resolved(**changes):
    data = dict(
        current_attempt_id=ATTEMPT,
        current_work_cycle_id="cycle-1",
        case_status=CaseStatus.DOCUMENT_REPROCESSED,
        attempt_order_known=True,
        unreviewed_new_failure=False,
        correction=CorrectionMilestone(
            **milestone(),
            explanation="Simulated account creation",
            target_system="CFIN",
            target_object="0041001000",
        ),
        reprocessing=ReprocessingMilestone(
            **milestone(), successful=True, target_document_reference="0000990001"
        ),
        validation=validation(),
        resolution_record=resolution(),
    )
    data.update(changes)
    return derive_resolved(**data)


def test_identifiers_preserve_zeros_and_reject_numbers():
    identity = DocumentIdentity(**IDENTITY)
    assert identity.canonical_key()[5] == "0000123456"
    assert identity.source_client == "010"
    for name in ("document_number", "fiscal_year", "source_client"):
        with pytest.raises(ValidationError):
            DocumentIdentity(**{**IDENTITY, name: 10})
    with pytest.raises(ValidationError):
        BusinessContext(target_account=41001000)
    provisional = DocumentIdentity(**{**IDENTITY, "document_number": None})
    assert provisional.missing_fields == ("document_number",)
    with pytest.raises(ValueError, match="identity required"):
        provisional.canonical_key()


def test_intake_requires_aware_time_and_numeric_processing_order():
    data = dict(
        scenario_id="MD-01",
        delivery_key="delivery-1",
        content_sha256="a" * 64,
        source_id="log",
        source_version="1",
        identity=IDENTITY,
        business_context=CONTEXT,
        attempt_id=ATTEMPT,
        processing_at=AT,
        processing_order=1,
    )
    assert IntakeManifest(**data).processing_order == 1
    for changes in (
        {"processing_at": "2026-09-30T09:00:00"},
        {"processing_order": "1"},
        {"processing_order": True},
        {"processing_order": 0},
    ):
        with pytest.raises(ValidationError):
            IntakeManifest(**{**data, **changes})


@pytest.mark.parametrize(
    "changes", [dict(scope_complete=False), dict(records=[{"account": "0041001000"}])]
)
def test_absence_requires_complete_lookup_with_zero_records(changes):
    with pytest.raises(ValidationError, match="Confirmed absence"):
        lookup(**changes)


def test_unavailable_remains_distinct_from_absence():
    unavailable = lookup(state="unavailable", scope_complete=False)
    assert unavailable.state == "unavailable"
    assert not route(lookups=[unavailable, mapping_lookup()]).agent3_eligible
    with pytest.raises(ValidationError):
        lookup(state="unavailable", scope_complete=True)


@pytest.mark.parametrize(
    "citation",
    [
        cite(source_version="2")
        if False
        else {
            "source_id": "target",
            "source_version": "2",
            "attempt_id": ATTEMPT,
            "record_id": "record-1",
        },
        {
            "source_id": "target",
            "source_version": "1",
            "attempt_id": "old-attempt",
            "record_id": "record-1",
        },
        {
            "source_id": "target",
            "source_version": "1",
            "attempt_id": ATTEMPT,
            "record_id": "invented-record",
        },
    ],
)
def test_citations_resolve_exact_source_version_attempt_and_record(citation):
    with pytest.raises(ValueError):
        validate_citations([Citation(**citation)], [source()], attempt_id=ATTEMPT)


def test_citation_boundaries_and_locator_exclusivity():
    validate_citations(
        [cite("log", line_start=1, line_end=3)], [source("log", kind="text")], attempt_id=ATTEMPT
    )
    with pytest.raises(ValueError, match="outside"):
        validate_citations(
            [cite("log", line_start=3, line_end=4)],
            [source("log", kind="text")],
            attempt_id=ATTEMPT,
        )
    for locator in (
        {"line_start": 2, "line_end": 1},
        {"line_start": 1, "line_end": 2, "record_id": "record-1"},
        {},
    ):
        with pytest.raises(ValidationError):
            Citation(source_id="log", source_version="1", **locator)


def test_pending_mapping_never_establishes_a_supported_route():
    decision = route(lookups=[lookup(), mapping_lookup(approved=False)])
    assert not decision.agent3_eligible
    assert decision.reason == "cause_not_established"


def test_supported_route_keeps_review_overdue_visible():
    decision = route()
    assert decision.agent3_eligible
    assert decision.guidance_version == "1"
    assert decision.review_overdue


def test_wrong_chart_and_later_lookup_snapshot_cannot_establish_absence():
    negative = lookup()
    wrong_chart = negative.model_copy(
        update={"query_scope": {**negative.query_scope, "chart_of_accounts": "OTHER"}}
    )
    assert not route(lookups=[wrong_chart, mapping_lookup()]).agent3_eligible
    later = negative.model_copy(
        update={
            "source": negative.source.model_copy(
                update={
                    "observed_at": SourceReference.model_validate(
                        {**negative.source.model_dump(), "observed_at": "2026-10-01T09:00:00Z"}
                    ).observed_at
                }
            )
        }
    )
    assert not route(lookups=[later, mapping_lookup()]).agent3_eligible


@pytest.mark.parametrize(
    "row_change",
    [
        {"expires_on": "2026-09-29"},
        {"effective_from": "2026-10-01"},
        {"scope": {"company_code": "9999"}},
        {"effective_from": "invalid-date"},
    ],
)
def test_mapping_row_must_be_applicable_to_document(row_change):
    mapped = mapping_lookup()
    changed = mapped.model_copy(update={"records": [{**mapped.records[0], **row_change}]})
    assert not route(lookups=[lookup(), changed]).agent3_eligible


def test_multiple_applicable_mapping_rows_require_review():
    mapped = mapping_lookup()
    conflicting = mapped.model_copy(
        update={
            "records": [
                *mapped.records,
                {**mapped.records[0], "record_id": "other-row", "target_account": "0099000000"},
            ]
        }
    )
    assert not route(lookups=[lookup(), conflicting]).agent3_eligible


@pytest.mark.parametrize(
    "changes",
    [
        dict(reuse_status="pending_review", approved_version=None, reviewer=None, reviewed_at=None),
        dict(expires_on="2026-09-29"),
        dict(reuse_status="withdrawn", withdrawn_at=AT),
    ],
)
def test_pending_expired_withdrawn_guidance_makes_zero_agent3_eligibility(changes):
    decision = route(guides=[guidance(**changes)])
    assert not decision.agent3_eligible
    assert decision.reason == "guidance_unavailable"


def test_conflicting_guidance_cannot_be_resolved_by_publication_order():
    assert not route(
        guides=[
            guidance(),
            guidance(guidance_id="other-guide", source_version="2", approved_version="2"),
        ]
    ).agent3_eligible
    policy = guidance(
        guidance_id="shared-policy",
        reuse_status="pending_review",
        approved_version=None,
        reviewer=None,
        reviewed_at=None,
    )
    assert not route(guides=[guidance(shared_policies=[policy])]).agent3_eligible


def test_material_uncertainty_cannot_be_hidden_behind_supported_status():
    with pytest.raises(ValidationError, match="material gaps"):
        diagnosis(uncertainty=[dict(reason="Snapshot may refer to a different failure attempt")])
    uncertain = diagnosis(
        status="needs_review", missing_checks=[dict(reason="Approved mapping not supplied")]
    )
    assert not route(result=uncertain).agent3_eligible
    with pytest.raises(ValidationError, match="explicit human confirmation"):
        diagnosis(status="human_confirmed")


def test_priority_codes_are_governed_and_p3_is_highest():
    assert Priority.P1.label == "P1 — Low"
    assert Priority.P2.label == "P2 — Medium"
    assert Priority.P3.label == "P3 — High"
    assert sorted(Priority, key=lambda item: item.sort_rank) == [
        Priority.P3,
        Priority.P2,
        Priority.P1,
    ]
    assert "resolved" not in {item.value for item in CaseStatus}


@pytest.mark.parametrize("changes", [dict(stored=False), dict(stored=1), dict(origin="ai_prose")])
def test_ai_prose_or_failed_storage_is_never_proof(changes):
    with pytest.raises(ValidationError):
        ProofAttachment(**proof(**changes))


def test_milestones_require_human_attestation_and_current_proof():
    for changes in (
        dict(human_confirmed=False),
        dict(proof=[]),
        dict(proof=[proof(attempt_id="earlier-attempt")]),
        dict(proof=[proof(work_cycle_id="earlier-cycle")]),
    ):
        with pytest.raises(ValidationError):
            HumanMilestone(**milestone(**changes))
    with pytest.raises(ValidationError, match="Failed retry"):
        ReprocessingMilestone(
            **milestone(), successful=False, target_document_reference="0000990001"
        )


def test_passed_validation_requires_every_posting_dimension():
    with pytest.raises(ValidationError, match="four checks"):
        validation(checks=[])
    with pytest.raises(ValidationError, match="validator"):
        validation(attestation=None)
    with pytest.raises(ValidationError, match="reason"):
        validation(
            status="failed",
            checks=[
                dict(
                    dimension="accounts",
                    result="failed",
                    expected="0041001000",
                    observed="Incorrect account",
                )
            ],
        )


def test_resolution_can_be_operationally_resolved_while_reuse_is_pending():
    assert resolved()
    assert resolution().reuse_status == "pending_review"
    unconfirmed = resolution(
        cause_status="not_confirmed",
        cause=None,
        cause_evidence=[],
        unresolved_gaps=["Original cause remains unproven"],
    )
    assert resolved(resolution_record=unconfirmed)
    with pytest.raises(ValidationError, match="self-publish"):
        resolution(reuse_status="approved")


@pytest.mark.parametrize(
    "changes",
    [
        dict(current_attempt_id="new-failure-attempt"),
        dict(current_work_cycle_id="new-cycle"),
        dict(attempt_order_known=False),
        dict(unreviewed_new_failure=True),
        dict(resolution_record=None),
        dict(case_status=CaseStatus.COMPLETE),
    ],
)
def test_old_success_unknown_order_and_incomplete_record_do_not_resolve(changes):
    assert not resolved(**changes)
