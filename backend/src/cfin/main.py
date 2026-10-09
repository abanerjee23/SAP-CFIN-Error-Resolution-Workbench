from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cfin.case_read_api import install_case_read_api
from cfin.config import Settings
from cfin.factual_intake import (
    ErrorAnalysisIntakeRequest,
    LogIntakeRequest,
    commit_error_analysis_intake,
    commit_log_intake,
)
from cfin.fixture_loader import load_md01
from cfin.gateway import ServiceGateway, UserGateway
from cfin.insights import ExplainOverviewRequest, InsightsService, OverviewRequest
from cfin.intake import IntakeControlRequest, apply_intake_control, scenario_template
from cfin.knowledge import (
    EvaluationAttestationRequest,
    FeedbackRequest,
    FeedbackReviewRequest,
    KnowledgeDraftRequest,
    KnowledgeReviewRequest,
    KnowledgeService,
    PublicationPolicyRequest,
)
from cfin.live_evaluations import EvaluationRequest, evaluation_status, queue_evaluations
from cfin.operations import (
    ActionRequest,
    EvidenceRequest,
    IntakeRequest,
    Operations,
    SimulationRequest,
)

bearer = HTTPBearer(auto_error=False)


def create_app(
    settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            app.state.cloud = UserGateway(settings, client)
            app.state.service = ServiceGateway(settings, client)
            app.state.operations = Operations(app.state.cloud, app.state.service)
            app.state.insights = InsightsService(app.state.cloud, app.state.service, settings)
            app.state.knowledge = KnowledgeService(app.state.cloud, app.state.service)
            yield

    app = FastAPI(title="CFIN Exception Management", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo log content, uploaded blobs or private field values in validation errors.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                    for error in exc.errors()[:10]
                ]
            },
        )

    @app.middleware("http")
    async def bounded_request(request: Request, call_next: Any) -> Response:
        if request.method == "POST":
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 16_000_000:
                    return JSONResponse(status_code=413, content={"detail": "Upload exceeds limit"})
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    async def signed_in(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> tuple[str, UUID, UserGateway]:
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "Sign in required")
        cloud: UserGateway = request.app.state.cloud
        actor_id = await cloud.actor(credentials.credentials)
        return credentials.credentials, actor_id, cloud

    actor_dependency = Annotated[tuple[str, UUID, UserGateway], Depends(signed_in)]

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "synthetic-poc"}

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        # Configuration presence does not establish connectivity or schema readiness.
        if not settings.cloud_configured:
            raise HTTPException(503, "Supabase setup is required")
        return {
            "cloud_configured": True,
            "cloud_verified": False,
            "worker_configured": settings.worker_configured,
            "paid_models_enabled": settings.models_configured,
            "log_only_enabled": settings.log_only_enabled,
        }

    @app.get("/api/workspaces")
    async def workspaces(actor: actor_dependency) -> list[dict[str, Any]]:
        token, actor_id, cloud = actor
        rows = await cloud.memberships(token, actor_id)
        return [
            {
                "id": row["workspace_id"],
                "name": row["workspaces"]["name"],
                "roles": row["roles"],
                "synthetic": row["workspaces"].get("synthetic", False),
            }
            for row in rows
            if isinstance(row.get("workspaces"), dict)
        ]

    @app.get("/api/cases")
    async def cases(workspace_id: UUID, actor: actor_dependency) -> list[dict[str, Any]]:
        token, actor_id, cloud = actor
        memberships = await cloud.memberships(token, actor_id)
        if not any(row.get("workspace_id") == str(workspace_id) for row in memberships):
            raise HTTPException(403, "Workspace membership required")
        return await cloud.cases(token, workspace_id)

    @app.get("/api/cases/page")
    async def case_page(
        workspace_id: UUID,
        actor: actor_dependency,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        q: str = Query(default="", max_length=200),
        category: str = "",
        priority: str = "",
        status: str = "",
        diagnosis_status: str = "",
        affected_object: str = "",
        workflow_version: str = "",
        analysis_status: str = "",
        factual_review_status: str = "",
    ) -> dict[str, Any]:
        token, actor_id, cloud = actor
        await cloud.require_member(token, actor_id, workspace_id)
        return await cloud.rpc(
            "cfin_case_page",
            token,
            {
                "workspace_id": str(workspace_id),
                "page": page,
                "page_size": page_size,
                "q": q,
                "category": category,
                "priority": priority,
                "status": status,
                "diagnosis_status": diagnosis_status,
                "affected_object": affected_object,
                "workflow_version": workflow_version,
                "analysis_status": analysis_status,
                "factual_review_status": factual_review_status,
            },
        )

    @app.get("/api/workspaces/{workspace_id}/members")
    async def members(workspace_id: UUID, actor: actor_dependency) -> list[dict[str, Any]]:
        token, actor_id, cloud = actor
        await cloud.require_member(token, actor_id, workspace_id)
        return await cloud.rpc(
            "cfin_workspace_directory", token, {"workspace_id": str(workspace_id)}
        )

    @app.post("/api/evaluations")
    async def create_evaluation(body: EvaluationRequest, actor: actor_dependency) -> dict:
        token, actor_id, cloud = actor
        return await queue_evaluations(cloud, settings, token, actor_id, body)

    @app.get("/api/evaluations")
    async def evaluations(
        workspace_id: UUID,
        actor: actor_dependency,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        batch_id: UUID | None = None,
    ) -> dict:
        token, actor_id, cloud = actor
        return await evaluation_status(
            cloud, token, actor_id, workspace_id, page, page_size, batch_id
        )

    @app.post("/api/overview")
    async def overview(body: OverviewRequest, request: Request, actor: actor_dependency):
        token, actor_id, _ = actor
        return await request.app.state.insights.create(token, actor_id, body)

    @app.get("/api/overview/{snapshot_id}")
    async def saved_overview(
        snapshot_id: UUID, workspace_id: UUID, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.insights.read(token, actor_id, workspace_id, snapshot_id)

    @app.get("/api/overview/{snapshot_id}/groups/{group_id}")
    async def overview_group(
        snapshot_id: UUID,
        group_id: UUID,
        workspace_id: UUID,
        request: Request,
        actor: actor_dependency,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
    ):
        token, actor_id, _ = actor
        return await request.app.state.insights.group(
            token, actor_id, workspace_id, snapshot_id, group_id, page, page_size
        )

    @app.post("/api/overview/{snapshot_id}/explain")
    async def explain_overview(
        snapshot_id: UUID, body: ExplainOverviewRequest, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.insights.explain(token, actor_id, snapshot_id, body)

    @app.get("/api/knowledge")
    async def knowledge(
        workspace_id: UUID,
        request: Request,
        actor: actor_dependency,
        q: str = Query(default="", max_length=1000),
        category: str = "",
        affected_object: str = "",
        company_code: str = "",
        target_system: str = "",
        limit: int = Query(default=10, ge=1, le=25),
    ):
        token, actor_id, _ = actor
        filters = {
            key: value
            for key, value in {
                "category": category,
                "affected_object": affected_object,
                "company_code": company_code,
                "target_system": target_system,
            }.items()
            if value
        }
        return await request.app.state.knowledge.search(
            token, actor_id, workspace_id, q, filters, limit
        )

    @app.get("/api/knowledge/reviews")
    async def knowledge_reviews(workspace_id: UUID, request: Request, actor: actor_dependency):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.reviews(token, actor_id, workspace_id)

    @app.post("/api/knowledge/drafts")
    async def draft_knowledge(
        body: KnowledgeDraftRequest, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.draft(token, actor_id, body)

    @app.post("/api/knowledge/{knowledge_id}/review")
    async def review_knowledge(
        knowledge_id: UUID, body: KnowledgeReviewRequest, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.review(token, actor_id, knowledge_id, body)

    @app.post("/api/knowledge/feedback")
    async def knowledge_feedback(body: FeedbackRequest, request: Request, actor: actor_dependency):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.feedback(token, actor_id, body)

    @app.post("/api/knowledge/policy")
    async def publication_policy(
        body: PublicationPolicyRequest, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.configure_policy(token, actor_id, body)

    @app.post("/api/knowledge/evaluation-attestation")
    async def knowledge_evaluation(
        body: EvaluationAttestationRequest, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.attest_evaluation(token, actor_id, body)

    @app.get("/api/knowledge/{knowledge_id}")
    async def knowledge_version(
        knowledge_id: UUID, workspace_id: UUID, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.version(
            token, actor_id, workspace_id, knowledge_id
        )

    @app.post("/api/knowledge/feedback/{feedback_id}/review")
    async def feedback_review(
        feedback_id: UUID, body: FeedbackReviewRequest, request: Request, actor: actor_dependency
    ):
        token, actor_id, _ = actor
        return await request.app.state.knowledge.review_feedback(token, actor_id, feedback_id, body)

    @app.get("/api/scenarios/MD-01")
    async def scenario(workspace_id: UUID, actor: actor_dependency) -> dict[str, Any]:
        token, actor_id, cloud = actor
        await cloud.require_member(token, actor_id, workspace_id)
        inputs = load_md01()
        manifest = inputs.manifest.model_copy(
            update={
                "identity": inputs.manifest.identity.model_copy(
                    update={"workspace_id": str(workspace_id)}
                )
            }
        )
        return {
            "synthetic": True,
            "manifest": manifest.model_dump(mode="json"),
            "original_log": inputs.original_log,
            "sources": [s.model_dump(mode="json") for s in inputs.catalogue],
            "agent_files": scenario_template("MD-01", workspace_id)["agent_files"],
        }

    @app.get("/api/scenarios/{scenario_id}")
    async def scenario_pack(scenario_id: str, workspace_id: UUID, actor: actor_dependency):
        token, actor_id, cloud = actor
        await cloud.require_member(token, actor_id, workspace_id)
        return scenario_template(scenario_id, workspace_id)

    @app.post("/api/cases/{case_id}/intake-controls")
    async def intake_control(case_id: UUID, body: IntakeControlRequest, actor: actor_dependency):
        token, actor_id, cloud = actor
        return await apply_intake_control(cloud, token, actor_id, case_id, body)

    @app.post("/api/intakes")
    async def intake(
        body: IntakeRequest, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, _ = actor
        ops: Operations = request.app.state.operations
        return await ops.intake(token, actor_id, body)

    @app.post("/api/intakes/log-only")
    async def log_intake(
        body: LogIntakeRequest, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, cloud = actor
        return await commit_log_intake(
            cloud, request.app.state.service, settings, token, actor_id, body
        )

    @app.post("/api/intakes/error-analysis")
    async def error_analysis_intake(
        body: ErrorAnalysisIntakeRequest, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, cloud = actor
        return await commit_error_analysis_intake(
            cloud, request.app.state.service, settings, token, actor_id, body
        )

    @app.get("/api/cases/{case_id}")
    async def case_detail(
        case_id: UUID, workspace_id: UUID, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, cloud = actor
        await cloud.require_member(token, actor_id, workspace_id)
        return await request.app.state.operations.detail(token, workspace_id, case_id)

    @app.post("/api/cases/{case_id}/actions")
    async def case_action(
        case_id: UUID, body: ActionRequest, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, _ = actor
        return await request.app.state.operations.action(token, actor_id, case_id, body)

    @app.post("/api/cases/{case_id}/evidence")
    async def save_evidence(
        case_id: UUID, body: EvidenceRequest, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, _ = actor
        return await request.app.state.operations.evidence(token, actor_id, case_id, body)

    @app.get("/api/evidence/{evidence_id}")
    async def get_evidence(
        evidence_id: UUID, workspace_id: UUID, actor: actor_dependency
    ) -> Response:
        token, actor_id, cloud = actor
        await cloud.require_member(token, actor_id, workspace_id)
        rows = await cloud.rows(
            "evidence_versions", token, workspace_id, {"id": f"eq.{evidence_id}"}
        )
        if len(rows) != 1:
            raise HTTPException(404, "Evidence not found")
        content = await cloud.download(token, rows[0])
        # Force downloads for binary types; text previews are fetched by the authenticated UI.
        return Response(
            content,
            media_type=rows[0]["content_type"],
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment",
            },
        )

    @app.post("/api/cases/{case_id}/simulation")
    async def simulation(
        case_id: UUID, body: SimulationRequest, request: Request, actor: actor_dependency
    ) -> dict[str, Any]:
        token, actor_id, _ = actor
        return await request.app.state.operations.simulate(token, actor_id, case_id, body)

    install_case_read_api(app)
    return app


app = create_app()
