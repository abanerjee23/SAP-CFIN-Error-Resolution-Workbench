"""Explicitly enabled, loopback-only access to one synthetic demo workspace.

The browser receives an opaque local capability, never the underlying Supabase
session. All normal membership, evidence and workflow checks still execute.
"""

import asyncio
import re
import secrets
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

from cfin.config import Settings
from cfin.gateway import UserGateway
from cfin.integration_check import IntegrationCheckError, existing_user_session, sign_out_local

DEMO_ROLES = ("mdg_process_owner", "process_owner", "data_operations", "cfin_exception_manager")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
READ_PATH = re.compile(r"/api/(?:cases/page|cases/[0-9a-f-]{36}|evidence/[0-9a-f-]{36})$")
WRITE_PATH = re.compile(r"/api/cases/[0-9a-f-]{36}/(?:actions|evidence)$")
ACTIONS = {
    "record_route_step", "comment", "record_approval", "assign", "set_status", "finish_resolution",
}


class LocalDemo:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client
        self.capability = "local-demo-" + secrets.token_urlsafe(32)
        self.session = None
        self.created_at = 0.0
        self.lock = asyncio.Lock()

    def require_local(self, request: Request) -> None:
        if not self.settings.local_demo_enabled:
            raise HTTPException(404, "Local demo is disabled")
        origin = request.headers.get("origin", "")
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in LOCAL_HOSTS
            or origin not in self.settings.cors_origins
            or urlsplit(origin).hostname not in LOCAL_HOSTS
        ):
            raise HTTPException(403, "The demo is available only on this computer")
        if not (
            self.settings.demo_workspace_id
            and self.settings.demo_actor_id
            and self.settings.worker_configured
        ):
            raise HTTPException(503, "Configure the synthetic demo workspace and test account")

    async def workspace(self, cloud: UserGateway) -> dict:
        async with self.lock:
            if self.session is None or time.monotonic() - self.created_at > 1200:
                if self.session:
                    await sign_out_local(self.settings, self.client, self.session)
                self.session = None
                try:
                    self.session = await existing_user_session(
                        self.settings, self.client, self.settings.demo_actor_id
                    )
                except (IntegrationCheckError, httpx.RequestError) as exc:
                    raise HTTPException(503, "The configured demo account is unavailable") from exc
                self.created_at = time.monotonic()
        token = self.session.access_token.get_secret_value()
        member = await cloud.require_member(
            token, self.settings.demo_actor_id, self.settings.demo_workspace_id
        )
        workspace = member.get("workspaces", {})
        if workspace.get("synthetic") is not True:
            raise HTTPException(403, "Demo access requires a synthetic workspace")
        roles = [role for role in DEMO_ROLES if role in member.get("roles", [])]
        if len(roles) != len(DEMO_ROLES):
            raise HTTPException(503, "The demo account needs all four walkthrough roles")
        return {
            "id": str(self.settings.demo_workspace_id),
            "name": workspace["name"],
            "roles": roles,
            "synthetic": True,
        }

    async def bootstrap(self, request: Request, cloud: UserGateway) -> dict:
        self.require_local(request)
        workspace = await self.workspace(cloud)
        return {"token": self.capability, "workspace": workspace}

    async def authorise(self, request: Request, capability: str, cloud: UserGateway) -> str:
        self.require_local(request)
        if not secrets.compare_digest(capability, self.capability):
            raise HTTPException(401, "Reload the page to restart the local demo")
        path = request.url.path
        workspace_id = str(self.settings.demo_workspace_id)
        if request.method == "GET":
            if path == "/api/workspaces":
                pass
            elif path == f"/api/workspaces/{workspace_id}/members":
                pass
            elif not READ_PATH.fullmatch(path) or request.query_params.getlist("workspace_id") != [
                workspace_id
            ]:
                raise HTTPException(403, "This request is outside the demo workspace")
        elif request.method == "POST":
            if path != "/api/intakes/error-analysis" and not WRITE_PATH.fullmatch(path):
                raise HTTPException(403, "This operation is outside the demo")
            body = await request.json()
            if not isinstance(body, dict) or body.get("workspace_id") != workspace_id:
                raise HTTPException(403, "This request is outside the demo workspace")
            if body.get("acting_role") not in DEMO_ROLES:
                raise HTTPException(403, "Choose a supported demo persona")
            if path.endswith("/actions") and body.get("action") not in ACTIONS:
                raise HTTPException(403, "This operation is outside the demo")
            if not path.endswith("/actions") and body.get("provenance") != "synthetic":
                raise HTTPException(403, "Demo uploads must be labelled synthetic")
        else:
            raise HTTPException(403, "This operation is outside the demo")
        request.state.demo_workspace = await self.workspace(cloud)
        return self.session.access_token.get_secret_value()

    async def close(self) -> None:
        if self.session:
            try:
                await sign_out_local(self.settings, self.client, self.session)
            except httpx.RequestError:
                pass
