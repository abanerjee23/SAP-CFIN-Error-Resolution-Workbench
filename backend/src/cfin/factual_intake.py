"""Authenticated, idempotent original-only intake for the factual workflow."""

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cfin.config import Settings
from cfin.error_analysis_prompts import ERROR_ANALYSIS_PROMPT_VERSIONS
from cfin.gateway import ServiceGateway, UserGateway
from cfin.log_only_contracts import ModelConfiguration, Provenance
from cfin.log_only_inputs import OriginalUpload, prepare_log_inputs
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.log_only_sources import manifest_fingerprint


class TextOriginalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=150)
    content_base64: str = Field(max_length=10924)


class RoutingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_system: str | None = Field(default=None, max_length=150)
    target_system: str | None = Field(default=None, max_length=150)
    interface: str | None = Field(default=None, max_length=150)
    company_code: str | None = Field(default=None, max_length=150)


class LogIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    delivery_key: str = Field(min_length=1, max_length=150, pattern=r".*\S.*")
    acting_role: str = "process_owner"
    provenance: Provenance
    sources: list[TextOriginalRequest] = Field(min_length=1, max_length=8)
    routing_context: RoutingContext = Field(default_factory=RoutingContext)


class ErrorAnalysisIntakeRequest(LogIntakeRequest):
    """Intake for the new governed Error Analysis workflow."""

    workflow_version: Literal["error-analysis-v1"] = "error-analysis-v1"


async def commit_log_intake(
    user: UserGateway,
    service: ServiceGateway,
    settings: Settings,
    token: str,
    actor_id: UUID,
    body: LogIntakeRequest,
    *,
    workflow_version: str = "log-only-v1",
    rpc_name: str = "cfin_commit_intake",
    prompt_versions: dict[str, str] | None = None,
) -> dict:
    member = await user.require_member(token, actor_id, body.workspace_id, "process_owner")
    if body.acting_role != "process_owner":
        raise HTTPException(403, "Process owner intake required")
    if not settings.log_only_enabled:
        raise HTTPException(503, "Intake is disabled until the database migration is ready")
    if (
        body.provenance == "user_supplied"
        and (member.get("workspaces") or {}).get("synthetic") is not False
    ):
        raise HTTPException(422, "User-supplied evidence requires a non-synthetic workspace")
    # Stable application receipt identity makes partial-upload retries use the
    # same objects. Content changes keep their own hash/version and conflict.
    receipt_id = uuid5(body.workspace_id, workflow_version + "-intake:" + body.delivery_key)
    try:
        uploads = [
            OriginalUpload(source.filename, base64.b64decode(source.content_base64, validate=True))
            for source in body.sources
        ]
        inputs = prepare_log_inputs(uploads, provenance=body.provenance, intake_id=receipt_id)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "Unsupported original input: " + str(exc)[:160]) from exc
    # Validate every original before storing any. Queue only after all originals
    # have independently passed storage readback; retries reuse verified objects.
    saved = []
    received_at = datetime.now(UTC).isoformat()
    for source in inputs.manifest.sources:
        original = inputs.originals[(source.source_id, source.source_version)]
        stored = await service.store_original(
            body.workspace_id, original, source.original_filename, UUID(source.source_id)
        )
        saved.append(
            {
                **stored,
                "source_id": source.source_id,
                "source_version": source.source_version,
                "observed_at": received_at,
                "provenance": {"kind": source.provenance, "timestamp_kind": "application_receipt"},
            }
        )
    configuration = ModelConfiguration(
        agent1=settings.model_agent_1,
        agent2=settings.model_agent_2,
        agent3=settings.model_agent_3,
        reasoning_effort=settings.model_reasoning_effort,
    )
    result = await service.rpc(
        rpc_name,
        {
            "workflow_version": workflow_version,
            "workspace_id": str(body.workspace_id),
            "actor_id": str(actor_id),
            "acting_role": "process_owner",
            "delivery_key": body.delivery_key,
            "manifest": inputs.manifest.model_dump(mode="json"),
            "source_manifest_sha256": manifest_fingerprint(inputs.manifest),
            "input_pack_sha256": hashlib.sha256(
                json.dumps(
                    {
                        "source_manifest": inputs.manifest.model_dump(mode="json"),
                        "routing_context": body.routing_context.model_dump(exclude_none=True),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest(),
            "input_sources": saved,
            "prompt_versions": dict(prompt_versions or LOG_PROMPT_VERSIONS),
            "model_configuration": configuration.model_dump(mode="json"),
            "routing_context": body.routing_context.model_dump(exclude_none=True),
        },
    )
    cases = await user.rows("cases", token, body.workspace_id, {"id": "eq." + result["case_id"]})
    if len(cases) != 1:
        raise HTTPException(503, "Saved intake is unavailable; refresh before retrying")
    return {
        **result,
        "version": cases[0]["version"],
        "paid_dispatch_enabled": settings.models_configured,
    }


async def commit_error_analysis_intake(
    user: UserGateway,
    service: ServiceGateway,
    settings: Settings,
    token: str,
    actor_id: UUID,
    body: ErrorAnalysisIntakeRequest,
) -> dict:
    return await commit_log_intake(
        user,
        service,
        settings,
        token,
        actor_id,
        body,
        workflow_version=body.workflow_version,
        rpc_name="cfin_commit_error_analysis_intake",
        prompt_versions=ERROR_ANALYSIS_PROMPT_VERSIONS,
    )
