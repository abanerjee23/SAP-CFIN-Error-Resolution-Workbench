"""User-scoped cloud reads. No service key or local case fallback."""

from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException

from cfin.config import Settings


class CloudReader:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def _get(self, path: str, token: str, params: dict[str, str] | None = None) -> Any:
        if not self.settings.cloud_configured:
            raise HTTPException(503, "Supabase setup is required")
        try:
            response = await self.client.get(
                self.settings.supabase_url + path,
                headers={
                    "apikey": self.settings.supabase_publishable_key.get_secret_value(),
                    "Authorization": f"Bearer {token}",
                },
                params=params,
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Cloud service is unavailable; retry later") from exc
        if response.status_code == 401:
            raise HTTPException(401, "Sign in again")
        if response.status_code == 403:
            raise HTTPException(403, "Access denied")
        if response.is_error:
            raise HTTPException(503, "Cloud read failed; retry later")
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(503, "Invalid cloud response") from exc

    async def actor(self, token: str) -> UUID:
        # Auth server checks the token; do not trust a locally decoded JWT/user id.
        value = await self._get("/auth/v1/user", token)
        try:
            return UUID(value["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(401, "Invalid signed-in user") from exc

    async def memberships(self, token: str, actor_id: UUID) -> list[dict[str, Any]]:
        rows = await self._get(
            "/rest/v1/workspace_memberships",
            token,
            {
                "user_id": f"eq.{actor_id}",
                "select": "workspace_id,roles,workspaces(id,name,synthetic)",
            },
        )
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(503, "Invalid workspace response")
        return rows

    async def cases(self, token: str, workspace_id: UUID) -> list[dict[str, Any]]:
        rows = await self._get(
            "/rest/v1/cases",
            token,
            {
                "workspace_id": f"eq.{workspace_id}",
                "select": (
                    "id,title,description,priority,status,diagnosis_status,created_at,due_at,version"
                ),
                "order": "created_at.desc,id.asc",
                "limit": "100",
            },
        )
        if not isinstance(rows, list):
            raise HTTPException(503, "Invalid case response")
        return rows
