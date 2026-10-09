"""History eligibility and human publication prerequisites; no real approvals/calls."""

import asyncio
import json
import math
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from cfin.knowledge import (
    EvaluationAttestationRequest,
    KnowledgeDraftRequest,
    KnowledgeService,
    PublicationPolicyRequest,
    concept_vector,
    register_history_for_run,
    revalidate_history,
    search_for_run,
)

W = UUID("11111111-1111-4111-8111-111111111111")
A = UUID("22222222-2222-4222-8222-222222222222")
K = UUID("33333333-3333-4333-8333-333333333333")
E = UUID("44444444-4444-4444-8444-444444444444")
R = UUID("55555555-5555-4555-8555-555555555555")


class User:
    def __init__(self, report=None, denied=False):
        self.calls = []
        self.report = report
        self.denied = denied

    async def require_member(self, token, actor, workspace, role=None):
        self.calls.append(("member", role))
        if self.denied:
            raise HTTPException(403, "Denied")

    async def rpc(self, name, token, payload):
        self.calls.append((name, payload))
        return {"items": [], "publication_policy": {"configured": False}}

    async def rows(self, table, token, workspace, filters):
        self.calls.append((table, filters))
        return [{"content_type": "application/json", "sha256": "a" * 64}]

    async def download(self, token, row):
        return json.dumps(self.report).encode()


class Service:
    def __init__(self):
        self.calls = []

    async def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == "cfin_search_history":
            return {"items": [{"id": str(K), "version": 1}]}
        return {"eligible": True, "registered": True, "id": str(E)}


def run(awaitable):
    return asyncio.run(awaitable)


def test_local_concept_vector_is_normalised_and_deterministic():
    first = concept_vector("missing ledger accounts 000123")
    assert len(first) == 64
    assert math.isclose(sum(x * x for x in first), 1, rel_tol=1e-7)
    assert first == concept_vector("absent gl account 000123")
    assert first != concept_vector("absent gl account 123")
    assert concept_vector("") == [0.0] * 64


def test_search_requires_membership_before_any_history_read():
    user, service = User(denied=True), Service()
    with pytest.raises(HTTPException) as exc:
        run(KnowledgeService(user, service).search("token", A, W, "missing account"))
    assert exc.value.status_code == 403
    assert len(user.calls) == 1
    assert service.calls == []


def test_search_sends_exact_controlled_filters_and_bounded_local_vector():
    user = User()
    run(
        KnowledgeService(user, Service()).search(
            "token",
            A,
            W,
            "missing account 000123",
            {"company_code": "0010"},
            5,
        )
    )
    name, payload = user.calls[1]
    assert name == "cfin_search_history"
    assert payload["filters"] == {"company_code": "0010"}
    assert len(json.loads(payload["query_vector"])) == 64
    assert "actor_id" not in payload


@pytest.mark.parametrize(
    "query,filters,limit",
    [
        ("x" * 1001, {}, 10),
        ("", {"oracle": "answer"}, 10),
        ("", {}, 0),
        ("", {}, 26),
    ],
)
def test_search_rejects_unbounded_or_unknown_fields(query, filters, limit):
    user = User()
    with pytest.raises(HTTPException) as exc:
        run(KnowledgeService(user, Service()).search("token", A, W, query, filters, limit))
    assert exc.value.status_code == 422
    assert len(user.calls) == 1


def test_draft_is_human_proposed_and_contains_no_approval_or_provider_embedding():
    user = User()
    body = KnowledgeDraftRequest(
        workspace_id=W,
        acting_role="process_owner",
        resolution_id=R,
        lesson="Check the approved target master observation before classifying.",
        scope={
            "target_system": "TGT",
            "company_code": "0010",
            "affected_object": "gl_account",
            "category": "missing_target_gl_master_data",
            "reuse_limitations": "Synthetic only",
        },
        reason="Record a proposed lesson for review",
    )
    run(KnowledgeService(user, Service()).draft("token", A, body))
    assert user.calls[0] == ("member", "process_owner")
    assert user.calls[1][0] == "cfin_knowledge_draft"
    assert "reuse_state" not in user.calls[1][1]
    assert "actor_id" not in user.calls[1][1]


@pytest.mark.parametrize("critical,review", [(1, True), (0, False)])
def test_publication_criteria_cannot_allow_critical_failures_or_skip_human_review(critical, review):
    with pytest.raises(ValidationError):
        PublicationPolicyRequest(
            workspace_id=W,
            acting_role="process_owner",
            minimum_cases=12,
            minimum_pass_rate=0.9,
            maximum_critical_failures=critical,
            require_human_review=review,
            reason="Explicit chosen criteria",
        )


def report():
    return {
        "quality_baseline_established": True,
        "provider_calls": 12,
        "evaluation_only": True,
        "publication_evidence": {
            "knowledge_id": str(K),
            "cases": 12,
            "passed_cases": 12,
            "critical_failures": 0,
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"quality_baseline_established": False},
        {"provider_calls": 0},
        {"evaluation_only": False},
        {
            "publication_evidence": {
                "knowledge_id": str(R),
                "cases": 12,
                "passed_cases": 12,
                "critical_failures": 0,
            }
        },
        {
            "publication_evidence": {
                "knowledge_id": str(K),
                "cases": 12,
                "passed_cases": 13,
                "critical_failures": 0,
            }
        },
    ],
)
def test_software_or_mismatched_report_cannot_attest_publication(change):
    value = {**report(), **change}
    user, service = User(value), Service()
    with pytest.raises(HTTPException) as exc:
        run(
            KnowledgeService(user, service).attest_evaluation(
                "token",
                A,
                EvaluationAttestationRequest(
                    workspace_id=W,
                    acting_role="process_owner",
                    knowledge_id=K,
                    evidence_id=E,
                    human_reviewed=True,
                    reason="Review saved evidence",
                ),
            )
        )
    assert exc.value.status_code == 422
    assert service.calls == []


def test_evaluation_attestation_binds_verified_bytes_to_actual_reviewer_and_version():
    user, service = User(report()), Service()
    run(
        KnowledgeService(user, service).attest_evaluation(
            "token",
            A,
            EvaluationAttestationRequest(
                workspace_id=W,
                acting_role="process_owner",
                knowledge_id=K,
                evidence_id=E,
                human_reviewed=True,
                reason="Review saved evidence",
            ),
        )
    )
    name, payload = service.calls[0]
    assert name == "cfin_attest_knowledge_evaluation"
    assert payload["actor_id"] == str(A)
    assert payload["report_sha256"] == "a" * 64
    assert payload["observations"]["knowledge_id"] == str(K)


def test_worker_search_registration_and_revalidation_preserve_actual_scope():
    cloud = Service()
    hits = run(
        search_for_run(
            cloud,
            str(W),
            str(A),
            {
                "error_text": "Account missing",
                "company_code": "0010",
                "target_account": "000123",
            },
        )
    )
    run(register_history_for_run(cloud, str(W), str(A), str(R), hits))
    assert run(revalidate_history(cloud, str(W), str(A), [str(K)]))
    assert [x[0] for x in cloud.calls] == [
        "cfin_search_history",
        "cfin_register_run_history",
        "cfin_revalidate_history",
    ]
    assert cloud.calls[0][1]["actor_id"] == str(A)
    assert cloud.calls[0][1]["context"] == {"company_code": "0010"}
    assert cloud.calls[1][1]["sources"] == [{"id": str(K), "version": 1}]


def test_factual_knowledge_draft_has_human_applicability_without_invented_cause():
    user = User()
    body = KnowledgeDraftRequest(
        workspace_id=W,
        acting_role="process_owner",
        resolution_id=R,
        lesson="The earlier document was reprocessed and its human posting comparisons passed.",
        scope={
            "workflow_version": "log-only-v1",
            "applicability": "Same supplied interface context",
            "reuse_limitations": "Prior observed outcome only; no current cause inference",
            "context": {"interface": "CFIN-DEMO", "company_code": "0010"},
        },
        reason="Propose the reviewed human outcome for controlled reuse",
    )
    run(KnowledgeService(user, Service()).draft("token", A, body))
    payload = user.calls[1][1]
    assert payload["scope"]["workflow_version"] == "log-only-v1"
    assert not {"category", "affected_object", "cause_confirmed"} & payload["scope"].keys()
    assert "reuse_state" not in payload and "approved" not in payload
    assert user.calls[0] == ("member", "process_owner")


@pytest.mark.parametrize(
    "scope",
    [
        {"workflow_version": "log-only-v1", "applicability": " ", "reuse_limitations": "Limited"},
        {
            "workflow_version": "log-only-v1",
            "applicability": "Observed",
            "reuse_limitations": " ",
        },
        {
            "workflow_version": "log-only-v1",
            "applicability": "Observed",
            "reuse_limitations": "Limited",
            "context": {"cause": "not allowed"},
        },
        {
            "workflow_version": "log-only-v1",
            "applicability": "Observed",
            "reuse_limitations": "Limited",
            "context": {"company_code": " 0010"},
        },
    ],
)
def test_factual_knowledge_rejects_blank_scope_or_diagnostic_context(scope):
    with pytest.raises(ValidationError):
        KnowledgeDraftRequest(
            workspace_id=W,
            acting_role="process_owner",
            resolution_id=R,
            lesson="A prior reviewed factual outcome",
            scope=scope,
            reason="Propose controlled reuse",
        )
