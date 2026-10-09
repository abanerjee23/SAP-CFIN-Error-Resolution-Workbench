"""Reviewed, versioned history. Publication is a human decision with durable prerequisites.

Retrieval combines PostgreSQL full-text matching, controlled context, and a local
concept vector. The vector is deterministic and makes no embedding-provider calls.
It supplies a broad candidate ranking, never evidence or permission to act.
"""

import hashlib
import json
import math
import re
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from cfin.gateway import ServiceGateway, UserGateway

ROLES = Literal["process_owner", "master_data_owner", "mapping_owner", "finance_owner", "validator"]
Text = str


class KnowledgeScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_system: str = Field(min_length=1, max_length=120)
    company_code: str = Field(min_length=1, max_length=120)
    affected_object: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=120)
    reuse_limitations: str = Field(min_length=1, max_length=2000)

    @field_validator("target_system", "company_code", "affected_object", "category")
    @classmethod
    def identifiers_are_exact(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Use an exact nonempty identifier")
        return value


class FactualKnowledgeScope(BaseModel):
    """Human-reviewed applicability of factual findings, without a diagnostic category."""

    model_config = ConfigDict(extra="forbid")
    workflow_version: Literal["log-only-v1"]
    applicability: str = Field(min_length=1, max_length=2000, pattern=r".*\S.*")
    reuse_limitations: str = Field(min_length=1, max_length=2000, pattern=r".*\S.*")
    context: dict[Literal["source_system", "target_system", "interface", "company_code"], str] = (
        Field(
            default_factory=dict,
        )
    )

    @field_validator("context")
    @classmethod
    def context_is_explicit_and_exact(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not text.strip() or text != text.strip() or len(text) > 120 for text in value.values()
        ):
            raise ValueError("Applicability context must use exact nonempty supplied values")
        return value


class KnowledgeDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: Literal["process_owner"]
    resolution_id: UUID
    lesson: str = Field(min_length=10, max_length=4000)
    scope: KnowledgeScope | FactualKnowledgeScope
    reason: str = Field(min_length=1, max_length=2000)
    supersedes_id: UUID | None = None
    materially_disputed: StrictBool = False


class KnowledgeReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: Literal["process_owner"]
    expected_version: StrictInt = Field(ge=1)
    decision: Literal["approved", "rejected", "withdrawn"]
    reason: str = Field(min_length=1, max_length=2000)
    evaluation_evidence_id: UUID | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: ROLES
    case_id: UUID
    run_id: UUID | None = None
    why_help_needed: str = Field(min_length=1, max_length=2000)
    proposed_change: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)


class FeedbackReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: Literal["process_owner"]
    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


class PublicationPolicyRequest(BaseModel):
    """Criteria are chosen explicitly by the process owner, never inferred from tests."""

    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: Literal["process_owner"]
    minimum_cases: StrictInt = Field(ge=1, le=10000)
    minimum_pass_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    maximum_critical_failures: StrictInt = Field(ge=0, le=0)
    require_human_review: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)


class EvaluationAttestationRequest(BaseModel):
    """Attach a saved model-evaluation report and explicitly review its relevance."""

    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: Literal["process_owner"]
    knowledge_id: UUID
    evidence_id: UUID
    human_reviewed: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)


def concept_vector(text: str) -> list[float]:
    """Local concept hashing with explicit first-family synonyms; no learned embedding.

    Keep exact identifier tokens (including leading zeros). Small concept aliases
    improve paraphrase recall but cannot invent applicability or a confirmed cause.
    """
    aliases = {
        "absent": "missing",
        "unavailable": "missing",
        "nonexistent": "missing",
        "ledger": "gl",
        "account": "account",
        "accounts": "account",
        "mapping": "map",
        "mapped": "map",
        "masterdata": "master",
        "periods": "period",
        "posting": "post",
        "posted": "post",
        "centres": "center",
        "centre": "center",
        "centers": "center",
        "closed": "closed",
        "blocked": "block",
        "blocker": "block",
    }
    terms = [aliases.get(t, t) for t in re.findall(r"[a-z0-9_]+", text.lower())]
    values = [0.0] * 64
    for term in terms:
        digest = hashlib.sha256(term.encode()).digest()
        values[int.from_bytes(digest[:2], "big") % 64] += 1 if digest[2] % 2 else -1
    length = math.sqrt(sum(x * x for x in values))
    return [round(x / length, 8) if length else 0.0 for x in values]


def vector_literal(values: list[float]) -> str | None:
    # A zero vector has no defined cosine direction. Empty searches use
    # controlled context and lexical fields rather than a NaN distance.
    if not any(values):
        return None
    return "[" + ",".join(str(x) for x in values) + "]"


class KnowledgeService:
    def __init__(self, user: UserGateway, service: ServiceGateway):
        self.user, self.service = user, service

    async def search(
        self,
        token: str,
        actor_id: UUID,
        workspace_id: UUID,
        query: str = "",
        filters: dict[str, str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, workspace_id)
        if len(query) > 1000 or not 1 <= limit <= 25:
            raise HTTPException(422, "Search must be bounded")
        filters = filters or {}
        if set(filters) - {"category", "affected_object", "company_code", "target_system"}:
            raise HTTPException(422, "Unknown history filter")
        return await self.user.rpc(
            "cfin_search_history",
            token,
            {
                "workspace_id": str(workspace_id),
                "query": query,
                "filters": filters,
                "limit": limit,
                "query_vector": vector_literal(concept_vector(query)),
            },
        )

    async def reviews(self, token: str, actor_id: UUID, workspace_id: UUID) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, workspace_id, "process_owner")
        return await self.user.rpc(
            "cfin_knowledge_reviews",
            token,
            {
                "workspace_id": str(workspace_id),
            },
        )

    async def draft(
        self,
        token: str,
        actor_id: UUID,
        body: KnowledgeDraftRequest,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        payload = body.model_dump(mode="json")
        payload["concept_vector"] = vector_literal(
            concept_vector(body.lesson + " " + json.dumps(body.scope.model_dump(), sort_keys=True))
        )
        if payload["concept_vector"] is None:
            raise HTTPException(422, "The proposed lesson must contain searchable text")
        return await self.user.rpc("cfin_knowledge_draft", token, payload)

    async def review(
        self,
        token: str,
        actor_id: UUID,
        knowledge_id: UUID,
        body: KnowledgeReviewRequest,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        return await self.user.rpc(
            "cfin_knowledge_review",
            token,
            {
                **body.model_dump(mode="json"),
                "knowledge_id": str(knowledge_id),
            },
        )

    async def feedback(
        self,
        token: str,
        actor_id: UUID,
        body: FeedbackRequest,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        return await self.user.rpc("cfin_knowledge_feedback", token, body.model_dump(mode="json"))

    async def review_feedback(
        self,
        token: str,
        actor_id: UUID,
        feedback_id: UUID,
        body: FeedbackReviewRequest,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        return await self.user.rpc(
            "cfin_review_knowledge_feedback",
            token,
            {
                **body.model_dump(mode="json"),
                "feedback_id": str(feedback_id),
            },
        )

    async def version(
        self,
        token: str,
        actor_id: UUID,
        workspace_id: UUID,
        knowledge_id: UUID,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, workspace_id)
        return await self.user.rpc(
            "cfin_knowledge_version",
            token,
            {
                "workspace_id": str(workspace_id),
                "knowledge_id": str(knowledge_id),
            },
        )

    async def configure_policy(
        self,
        token: str,
        actor_id: UUID,
        body: PublicationPolicyRequest,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        return await self.user.rpc("cfin_publication_policy", token, body.model_dump(mode="json"))

    async def attest_evaluation(
        self,
        token: str,
        actor_id: UUID,
        body: EvaluationAttestationRequest,
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        rows = await self.user.rows(
            "evidence_versions",
            token,
            body.workspace_id,
            {
                "id": f"eq.{body.evidence_id}",
            },
        )
        if len(rows) != 1 or rows[0]["content_type"] != "application/json":
            raise HTTPException(422, "A saved JSON model-evaluation report is required")
        try:
            report = json.loads(await self.user.download(token, rows[0]))
            observations = report["publication_evidence"]
            if (
                report.get("quality_baseline_established") is not True
                or type(report.get("provider_calls")) is not int
                or report["provider_calls"] < 1
                or report.get("evaluation_only") is not True
                or not isinstance(observations, dict)
                or observations.get("knowledge_id") != str(body.knowledge_id)
                or type(observations.get("cases")) is not int
                or type(observations.get("critical_failures")) is not int
                or type(observations.get("passed_cases")) is not int
                or not 0 <= observations["passed_cases"] <= observations["cases"]
                or observations["cases"] < 1
                or observations["critical_failures"] < 0
            ):
                raise ValueError("Invalid evaluation evidence")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                422,
                "Report must establish an actual model-quality baseline",
            ) from exc
        # Only the server verifies immutable bytes; the user RPC cannot attest a
        # fabricated summary or replace the saved report with browser fields.
        return await self.service.rpc(
            "cfin_attest_knowledge_evaluation",
            {
                **body.model_dump(mode="json"),
                "actor_id": str(actor_id),
                "report_sha256": rows[0]["sha256"],
                "observations": observations,
            },
        )


async def search_for_run(
    cloud: ServiceGateway,
    workspace_id: str,
    actor_id: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    query = " ".join(
        str(context.get(k, ""))
        for k in (
            "error_text",
            "affected_object",
            "category",
            "target_account",
            "source_account",
        )
    ).strip()
    result = await cloud.rpc(
        "cfin_search_history",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(actor_id),
            "query": query,
            "context": {
                k: str(context[k])
                for k in ("target_system", "company_code", "affected_object", "category")
                if context.get(k)
            },
            "limit": 5,
            "query_vector": vector_literal(concept_vector(query)),
        },
    )
    return result["items"]


async def register_history_for_run(
    cloud: ServiceGateway,
    workspace_id: str,
    actor_id: str,
    run_id: str,
    history: list[dict[str, Any]],
) -> None:
    await cloud.rpc(
        "cfin_register_run_history",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(actor_id),
            "run_id": str(run_id),
            "sources": [{"id": x["id"], "version": x["version"]} for x in history],
        },
    )


async def revalidate_history(
    cloud: ServiceGateway,
    workspace_id: str,
    actor_id: str,
    ids: list[str],
) -> bool:
    result = await cloud.rpc(
        "cfin_revalidate_history",
        {
            "workspace_id": str(workspace_id),
            "actor_id": str(actor_id),
            "ids": ids,
        },
    )
    return result.get("eligible") is True
