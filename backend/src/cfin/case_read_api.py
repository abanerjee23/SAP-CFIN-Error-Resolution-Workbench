"""Versioned, read-only machine contract over authorised saved case evidence.

Opaque read credentials are issued by a signed-in workspace process owner. Only
their SHA-256 digest is stored; a credential grants its explicit workspace scope,
never a portal user's identity. Every read rechecks expiry/revocation in SQL.
"""

import base64
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cfin.contracts import Citation, ResolutionScope, ValidationCheck
from cfin.log_only_contracts import (
    ExtractedEntry,
    ExtractedLog,
    LegacyAnalysisResult,
    LogSourceManifest,
    PublicCaseResult,
    PublicCaseSource,
    PublicFactualResult,
)

bearer = HTTPBearer(auto_error=False)
Scope = Literal["cases:read", "evidence:read"]


class ReadContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateReadCredential(ReadContract):
    label: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    scopes: list[Scope] = Field(min_length=1, max_length=2)
    expires_in_days: int = Field(default=30, ge=1, le=90, strict=True)

    @model_validator(mode="after")
    def unique_scopes(self):
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Choose each capability once")
        return self


class CreatedReadCredential(ReadContract):
    credential_id: UUID
    workspace_id: UUID
    label: str
    scopes: list[Scope]
    expires_at: datetime
    read_token: str = Field(
        description="Shown once. Store privately; never a Supabase service key."
    )


class AnalysisState(ReadContract):
    status: str
    workflow_version: str
    run_id: str | None = None
    requested_run_id: str | None = None
    latest_run_state: str | None = None
    latest_failure: str | None = None
    input_revision: str
    published_input_revision: str | None = None
    stale: bool


class CaseReadResponse(ReadContract):
    api_version: Literal["v1"] = "v1"
    case_id: UUID
    workspace_id: UUID
    case_version: int
    title: str
    priority: str
    operational_status: str
    resolved: bool
    review_status: str
    owner_id: str | None
    analysis: AnalysisState
    result: PublicCaseResult | None
    sources: list[PublicCaseSource]


class CaseListItem(ReadContract):
    case_id: UUID
    case_version: int
    title: str
    workflow_version: str
    operational_status: str
    resolved: bool
    review_status: str
    analysis_status: str
    priority: str


class CaseListResponse(ReadContract):
    api_version: Literal["v1"] = "v1"
    workspace_id: UUID
    snapshot_id: UUID
    expires_at: datetime
    total: int
    items: list[CaseListItem]
    next_cursor: str | None


class EntryPage(ReadContract):
    api_version: Literal["v1"] = "v1"
    case_id: UUID
    case_version: int
    analysis_run_id: str | None
    total: int
    items: list[ExtractedEntry]
    next_cursor: str | None


class ActivityItem(ReadContract):
    id: str
    recorded_at: str | None
    actor_id: str | None
    acting_role: str | None
    action: str
    reason: str | None


class ActivityPage(ReadContract):
    api_version: Literal["v1"] = "v1"
    case_id: UUID
    case_version: int
    total: int
    items: list[ActivityItem]
    next_cursor: str | None


class ReviewFindings(ReadContract):
    explanation: str | None = None
    gaps: list[str] = Field(default_factory=list)
    entry_ids: list[str] = Field(default_factory=list)
    proof_ids: list[str] = Field(default_factory=list)
    cause_label: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class HumanRecord(ReadContract):
    id: str
    kind: str
    actor_id: str | None
    recorded_at: str | None
    provenance: Literal["recorded_case_history"] = "recorded_case_history"
    decision: str | None = None
    reason: str | None = None
    findings: str | ReviewFindings | None = None
    action_or_no_change: str | None = None
    action_kind: Literal["corrective_work", "no_change"] | None = None
    outcome: str | None = None
    scope: str | ResolutionScope | None = None
    gaps: list[str] = Field(default_factory=list)
    proof_ids: list[str] = Field(default_factory=list)
    target_system: str | None = None
    target_object: str | None = None
    occurred_at: str | None = None
    status: str | None = None
    target_document_reference: str | None = None
    investigation_scope: str | None = None
    checks: list[ValidationCheck] = Field(default_factory=list)
    attempt_key: str | None = None
    result: str | None = None
    processing_at: str | None = None
    processing_order: int | None = None
    target_change_authority: bool | None = None
    human_confirmed: bool | None = None
    chronology_confirmed: bool | None = None


class HumanRecordPage(ReadContract):
    api_version: Literal["v1"] = "v1"
    case_id: UUID
    case_version: int
    total: int
    items: list[HumanRecord]
    next_cursor: str | None


class OriginalResponse(ReadContract):
    api_version: Literal["v1"] = "v1"
    case_id: UUID
    case_version: int
    source_id: str
    source_version: str
    filename: str
    content_type: str
    encoding: Literal["utf-8"] = "utf-8"
    sha256: str
    byte_size: int
    text: str = Field(
        description="Complete original text; UTF-8 encoding reproduces its exact hash."
    )


class Cursor(ReadContract):
    resource: str
    workspace_id: UUID
    case_id: UUID | None = None
    case_version: int | None = None
    snapshot_id: UUID | None = None
    offset: int = Field(ge=0, le=100000)
    limit: int = Field(ge=1, le=100)
    filters: dict[str, str] = Field(default_factory=dict)


def _encode_cursor(cursor: Cursor) -> str:
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip("=")


def _cursor(
    value: str | None,
    *,
    resource: str,
    workspace_id: UUID,
    limit: int,
    case_id: UUID | None = None,
    case_version: int | None = None,
    filters: dict[str, str] | None = None,
) -> Cursor:
    if value is None:
        return Cursor(
            resource=resource,
            workspace_id=workspace_id,
            case_id=case_id,
            case_version=case_version,
            offset=0,
            limit=limit,
            filters=filters or {},
        )
    try:
        if len(value) > 2000:
            raise ValueError("Cursor too long")
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        cursor = Cursor.model_validate_json(decoded)
        if (
            cursor.resource,
            cursor.workspace_id,
            cursor.case_id,
            cursor.case_version,
            cursor.limit,
            cursor.filters,
        ) != (resource, workspace_id, case_id, case_version, limit, filters or {}):
            raise ValueError("Cursor does not match the request")
        return cursor
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "Invalid or incompatible page cursor") from exc


def public_result(case: dict) -> PublicFactualResult | LegacyAnalysisResult | None:
    """Allowlisted projection; never expose whole run or service dictionaries."""
    if case.get("workflow_version", "legacy-v1") != "log-only-v1":
        return LegacyAnalysisResult(
            title=case["title"],
            description=case.get("description", ""),
            diagnosis_status=case.get("diagnosis_status"),
            cause_label=case.get("category"),
        )
    factual = case.get("factual_result")
    if not factual:
        return None
    summary = factual.get("summary") or {}
    history = factual.get("history") or {}
    return PublicFactualResult(
        outcome=factual["outcome"],
        title=summary.get("title"),
        statements=summary.get("statements", ()),
        unresolved_details=summary.get("unresolved_details", ()),
        extraction=factual.get("extraction"),
        limitations=factual.get("limitations", ()),
        failure_reason=factual.get("failure_reason"),
        history_retrieval_status=history.get("status", "not_searched"),
        history_retrieval_limitation=history.get("limitation"),
        related_cases=summary.get("related_cases", ()),
    )


def project_case(
    case: dict, evidence: list[dict], latest_run: dict | None = None
) -> CaseReadResponse:
    version = case.get("workflow_version", "legacy-v1")
    factual = case.get("factual_result") or {}
    published_revision = factual.get("input_revision")
    current_revision = str(case.get("input_revision", 0))
    sources = {}
    for manifest in (case.get("source_manifest"), factual.get("source_manifest")):
        if manifest:
            for source in LogSourceManifest.model_validate(manifest).sources:
                sources[(source.source_id, source.source_version)] = PublicCaseSource(
                    **source.model_dump(mode="json")
                )
    if version == "legacy-v1":
        from cfin.log_only_contracts import ReadableLocation

        for row in evidence:
            if row.get("kind") == "original_log":
                sources[(row["source_id"], row["source_version"])] = PublicCaseSource(
                    source_id=row["source_id"],
                    source_version=row["source_version"],
                    original_filename=row["filename"],
                    content_type="text/plain",
                    content_sha256=row["sha256"],
                    byte_size=row["byte_size"],
                    provenance="synthetic"
                    if row.get("provenance", {}).get("synthetic")
                    else "user_supplied",
                    readable=ReadableLocation(status="available", line_count=row["line_count"])
                    if "line_count" in row
                    else None,
                )
    return CaseReadResponse(
        case_id=case["id"],
        workspace_id=case["workspace_id"],
        case_version=case["version"],
        title=case["title"],
        priority=case["priority"],
        operational_status=case["status"],
        resolved=case.get("resolved", False),
        review_status=case.get("factual_review_status", "pending_review")
        if version == "log-only-v1"
        else case.get("diagnosis_status", "unreviewed"),
        owner_id=case.get("owner_user_id"),
        analysis=AnalysisState(
            status=case.get("analysis_status", "unavailable"),
            workflow_version=version,
            run_id=factual.get("run_id", case.get("published_run_id")),
            requested_run_id=case.get("requested_run_id"),
            latest_run_state=(latest_run or {}).get("state"),
            latest_failure=((latest_run or {}).get("output") or {}).get("failure_reason")
            or (latest_run or {}).get("error_code"),
            input_revision=current_revision,
            published_input_revision=published_revision,
            stale=bool(
                published_revision is not None
                and (
                    str(published_revision) != current_revision
                    or (
                        case.get("requested_run_id") is not None
                        and case["requested_run_id"] != factual.get("run_id")
                    )
                )
            ),
        ),
        result=public_result(case),
        sources=list(sources.values()),
    )


def _require_tls(request: Request) -> None:
    if request.url.scheme == "https":
        return
    try:
        loopback_peer = bool(request.client and ip_address(request.client.host).is_loopback)
    except ValueError:
        loopback_peer = False
    if not (loopback_peer and request.url.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise HTTPException(400, "HTTPS is required for read credentials")


def install_case_read_api(app: FastAPI) -> None:
    router = APIRouter(tags=["Saved case read API"])

    async def machine_digest(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        _require_tls(request)
        if not credentials or not re.fullmatch(
            r"cfin_read_[A-Za-z0-9_-]{43}", credentials.credentials
        ):
            raise HTTPException(401, "A scoped read credential is required")
        return hashlib.sha256(credentials.credentials.encode()).hexdigest()

    Machine = Annotated[str, Depends(machine_digest)]

    async def read(
        request: Request, digest: str, workspace_id: UUID, resource: str, **values
    ) -> dict:
        result = await request.app.state.service.rpc(
            "cfin_machine_read",
            {
                "token_sha256": digest,
                "workspace_id": str(workspace_id),
                "resource": resource,
                **{
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in values.items()
                    if value is not None
                },
            },
        )
        failures = {
            "access_denied": (403, "The read credential does not grant access to this resource"),
            "not_found": (404, "Saved case resource not found"),
            "snapshot_changed": (409, "The saved case or list snapshot changed; refresh"),
            "invalid_input": (422, "Invalid saved case read request"),
        }
        if "error" in result:
            status, message = failures.get(result["error"], (503, "Saved case read is unavailable"))
            raise HTTPException(status, message)
        return result

    @router.post(
        "/api/workspaces/{workspace_id}/read-credentials", response_model=CreatedReadCredential
    )
    async def create_credential(
        workspace_id: UUID,
        body: CreateReadCredential,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        _require_tls(request)
        if not credentials:
            raise HTTPException(401, "Sign in required")
        user = request.app.state.cloud
        actor = await user.actor(credentials.credentials)
        await user.require_member(credentials.credentials, actor, workspace_id, "process_owner")
        token = "cfin_read_" + secrets.token_urlsafe(32)
        expiry = datetime.now(UTC) + timedelta(days=body.expires_in_days)
        row = await user.rpc(
            "cfin_create_read_credential",
            credentials.credentials,
            {
                "workspace_id": str(workspace_id),
                "label": body.label,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "scopes": body.scopes,
                "expires_at": expiry.isoformat(),
            },
        )
        return CreatedReadCredential(
            credential_id=row["id"],
            workspace_id=workspace_id,
            label=body.label,
            scopes=body.scopes,
            expires_at=expiry,
            read_token=token,
        )

    @router.post("/api/workspaces/{workspace_id}/read-credentials/{credential_id}/revoke")
    async def revoke_credential(
        workspace_id: UUID,
        credential_id: UUID,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        _require_tls(request)
        if not credentials:
            raise HTTPException(401, "Sign in required")
        user = request.app.state.cloud
        actor = await user.actor(credentials.credentials)
        await user.require_member(credentials.credentials, actor, workspace_id, "process_owner")
        await user.rpc(
            "cfin_revoke_read_credential",
            credentials.credentials,
            {
                "workspace_id": str(workspace_id),
                "credential_id": str(credential_id),
            },
        )
        return {"revoked": True, "credential_id": str(credential_id)}

    @router.get("/api/v1/cases", response_model=CaseListResponse)
    async def list_cases(
        request: Request,
        workspace_id: UUID,
        digest: Machine,
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
        status: str | None = Query(None, max_length=50),
        workflow_version: Literal["legacy-v1", "log-only-v1"] | None = None,
    ):
        filters = {
            key: value
            for key, value in {"status": status, "workflow_version": workflow_version}.items()
            if value is not None
        }
        page = _cursor(
            cursor, resource="cases", workspace_id=workspace_id, limit=limit, filters=filters
        )
        data = await read(
            request,
            digest,
            workspace_id,
            "cases",
            snapshot_id=page.snapshot_id,
            offset=page.offset,
            limit=limit,
            **filters,
        )
        items = [
            CaseListItem(
                case_id=row["id"],
                case_version=row["version"],
                title=row["title"],
                workflow_version=row.get("workflow_version", "legacy-v1"),
                operational_status=row["status"],
                resolved=row.get("resolved", False),
                priority=row["priority"],
                review_status=row.get("factual_review_status", "pending_review")
                if row.get("workflow_version") == "log-only-v1"
                else row.get("diagnosis_status", "unreviewed"),
                analysis_status=row.get("analysis_status", "unavailable"),
            )
            for row in data["items"]
        ]
        next_page = page.model_copy(
            update={"snapshot_id": UUID(data["snapshot_id"]), "offset": page.offset + len(items)}
        )
        return CaseListResponse(
            workspace_id=workspace_id,
            snapshot_id=data["snapshot_id"],
            expires_at=data["expires_at"],
            total=data["total"],
            items=items,
            next_cursor=_encode_cursor(next_page) if next_page.offset < data["total"] else None,
        )

    @router.get("/api/v1/cases/{case_id}", response_model=CaseReadResponse)
    async def get_case(
        case_id: UUID,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int | None = Query(None, ge=1),
    ):
        data = await read(
            request, digest, workspace_id, "case", case_id=case_id, case_version=case_version
        )
        return project_case(data["case"], data.get("evidence", []), data.get("latest_run"))

    async def entries(
        case_id, workspace_id, request, digest, case_version, limit, cursor, selected
    ):
        resource = "selected-evidence" if selected else "extraction"
        page = _cursor(
            cursor,
            resource=resource,
            workspace_id=workspace_id,
            limit=limit,
            case_id=case_id,
            case_version=case_version,
        )
        data = await read(
            request, digest, workspace_id, "case", case_id=case_id, case_version=case_version
        )
        case = data["case"]
        if case.get("workflow_version") != "log-only-v1":
            raise HTTPException(
                409, "Legacy analysis has no factual extraction; read its legacy result"
            )
        result = case.get("factual_result")
        if not result or result.get("extraction") is None:
            raise HTTPException(409, "No saved factual extraction is available")
        extracted = ExtractedLog.model_validate(result["extraction"])
        rows = extracted.entries
        if selected:
            ids = (result.get("selection") or {}).get("selected_entry_ids", [])
            by_id = {entry.entry_id: entry for entry in rows}
            rows = [by_id[identifier] for identifier in ids]
        items = rows[page.offset : page.offset + limit]
        next_page = page.model_copy(update={"offset": page.offset + len(items)})
        return EntryPage(
            case_id=case_id,
            case_version=case_version,
            analysis_run_id=result["run_id"],
            total=len(rows),
            items=items,
            next_cursor=_encode_cursor(next_page) if next_page.offset < len(rows) else None,
        )

    @router.get("/api/v1/cases/{case_id}/extraction", response_model=EntryPage)
    async def extraction(
        case_id: UUID,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int = Query(..., ge=1),
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ):
        return await entries(
            case_id, workspace_id, request, digest, case_version, limit, cursor, False
        )

    @router.get("/api/v1/cases/{case_id}/selected-evidence", response_model=EntryPage)
    async def selected_evidence(
        case_id: UUID,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int = Query(..., ge=1),
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ):
        return await entries(
            case_id, workspace_id, request, digest, case_version, limit, cursor, True
        )

    @router.get("/api/v1/cases/{case_id}/activity", response_model=ActivityPage)
    async def activity(
        case_id: UUID,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int = Query(..., ge=1),
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ):
        page = _cursor(
            cursor,
            resource="activity",
            workspace_id=workspace_id,
            limit=limit,
            case_id=case_id,
            case_version=case_version,
        )
        data = await read(
            request,
            digest,
            workspace_id,
            "activity",
            case_id=case_id,
            case_version=case_version,
            offset=page.offset,
            limit=limit,
        )
        items = [
            ActivityItem(
                id=row["id"],
                recorded_at=row.get("recorded_at", row.get("created_at")),
                actor_id=row.get("actor_id"),
                acting_role=row.get("acting_role"),
                action=row.get("event_type", row.get("action", "unknown")),
                reason=row.get("reason"),
            )
            for row in data["items"]
        ]
        next_page = page.model_copy(update={"offset": page.offset + len(items)})
        return ActivityPage(
            case_id=case_id,
            case_version=case_version,
            total=data["total"],
            items=items,
            next_cursor=_encode_cursor(next_page) if next_page.offset < data["total"] else None,
        )

    @router.get("/api/v1/cases/{case_id}/records", response_model=HumanRecordPage)
    async def records(
        case_id: UUID,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int = Query(..., ge=1),
        limit: int = Query(25, ge=1, le=100),
        cursor: str | None = None,
    ):
        page = _cursor(
            cursor,
            resource="records",
            workspace_id=workspace_id,
            limit=limit,
            case_id=case_id,
            case_version=case_version,
        )
        data = await read(
            request,
            digest,
            workspace_id,
            "records",
            case_id=case_id,
            case_version=case_version,
            offset=page.offset,
            limit=limit,
        )
        items = []
        private_fields = {"id", "kind", "actor_id", "recorded_at", "provenance"}
        for row in data["items"]:
            payload = row.get("payload") or {}
            fields = {
                key: payload[key]
                for key in HumanRecord.model_fields.keys() - private_fields
                if key in payload
            }
            if isinstance(fields.get("findings"), dict):
                fields["findings"] = ReviewFindings(
                    **{
                        key: fields["findings"][key]
                        for key in ReviewFindings.model_fields
                        if key in fields["findings"]
                    }
                )
            items.append(
                HumanRecord(
                    id=row["id"],
                    kind=row["kind"],
                    actor_id=row.get("actor_id"),
                    recorded_at=row.get("recorded_at"),
                    **fields,
                )
            )
        next_page = page.model_copy(update={"offset": page.offset + len(items)})
        return HumanRecordPage(
            case_id=case_id,
            case_version=case_version,
            total=data["total"],
            items=items,
            next_cursor=_encode_cursor(next_page) if next_page.offset < data["total"] else None,
        )

    async def original(
        case_id, workspace_id, request, digest, case_version, source_id, source_version
    ):
        data = await read(
            request,
            digest,
            workspace_id,
            "source",
            case_id=case_id,
            case_version=case_version,
            source_id=source_id,
            source_version=source_version,
        )
        evidence = data["evidence"]
        raw = await request.app.state.service.download(evidence)
        # A revoked credential or changed case while Storage was being read must
        # not return stale authorised content after that change.
        await read(
            request,
            digest,
            workspace_id,
            "source",
            case_id=case_id,
            case_version=case_version,
            source_id=source_id,
            source_version=source_version,
        )
        return evidence, raw

    @router.get("/api/v1/cases/{case_id}/sources/{source_id}", response_model=OriginalResponse)
    async def get_original(
        case_id: UUID,
        source_id: str,
        source_version: str,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int = Query(..., ge=1),
    ):
        evidence, raw = await original(
            case_id, workspace_id, request, digest, case_version, source_id, source_version
        )
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                422, "This original is not UTF-8; use the unchanged-byte download"
            ) from exc
        return OriginalResponse(
            case_id=case_id,
            case_version=case_version,
            source_id=source_id,
            source_version=source_version,
            filename=evidence["filename"],
            content_type=evidence["content_type"],
            sha256=evidence["sha256"],
            byte_size=len(raw),
            text=text,
        )

    @router.get("/api/v1/cases/{case_id}/sources/{source_id}/download")
    async def download_original(
        case_id: UUID,
        source_id: str,
        source_version: str,
        workspace_id: UUID,
        request: Request,
        digest: Machine,
        case_version: int = Query(..., ge=1),
    ):
        evidence, raw = await original(
            case_id, workspace_id, request, digest, case_version, source_id, source_version
        )
        return Response(
            raw,
            media_type=evidence["content_type"],
            headers={
                "Content-Disposition": "attachment",
                "X-Content-Type-Options": "nosniff",
            },
        )

    app.include_router(router)
