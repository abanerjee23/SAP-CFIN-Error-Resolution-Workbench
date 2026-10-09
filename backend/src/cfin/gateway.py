"""Scoped reads/user RPCs plus a separate privileged storage/worker gateway."""

import hashlib
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException

from cfin.cloud import CloudReader
from cfin.config import Settings


async def checked_response(response: httpx.Response) -> Any:
    if response.is_error:
        code = {400: 422, 401: 401, 403: 403, 404: 404, 409: 409, 422: 422}.get(
            response.status_code, 503
        )
        messages = {
            422: "Action input or transition is invalid",
            401: "Sign in again",
            403: "The selected role cannot perform this action",
            404: "Item not found",
            409: "The case or review changed. Refresh and try again",
            503: "Cloud action failed; retry later",
        }
        raise HTTPException(code, messages[code])
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(503, "Invalid cloud response") from exc


class UserGateway(CloudReader):
    async def require_member(
        self, token: str, actor_id: UUID, workspace_id: UUID, role: str | None = None
    ) -> dict[str, Any]:
        rows = await self.memberships(token, actor_id)
        member = next((r for r in rows if r.get("workspace_id") == str(workspace_id)), None)
        if member is None or (role and role not in member.get("roles", [])):
            raise HTTPException(403, "Workspace membership and the selected role are required")
        return member

    async def rows(
        self, table: str, token: str, workspace_id: UUID, filters: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        value = await self._get(
            "/rest/v1/" + table,
            token,
            {"workspace_id": f"eq.{workspace_id}", "select": "*", **(filters or {})},
        )
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            raise HTTPException(503, "Invalid cloud response")
        return value

    async def rpc(self, name: str, token: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self.client.post(
                self.settings.supabase_url + "/rest/v1/rpc/" + name,
                headers={
                    "apikey": self.settings.supabase_publishable_key.get_secret_value(),
                    "Authorization": f"Bearer {token}",
                },
                json={"payload": payload},
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Cloud service is unavailable") from exc
        return await checked_response(response)

    async def download(self, token: str, evidence: dict[str, Any]) -> bytes:
        try:
            response = await self.client.get(
                self.settings.supabase_url
                + "/storage/v1/object/authenticated/evidence/"
                + quote(evidence["object_path"], safe="/"),
                headers={
                    "apikey": self.settings.supabase_publishable_key.get_secret_value(),
                    "Authorization": f"Bearer {token}",
                },
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Evidence storage is unavailable") from exc
        if response.is_error:
            raise HTTPException(
                403 if response.status_code in (401, 403, 404) else 503, "Evidence is unavailable"
            )
        if (
            len(response.content) != evidence["byte_size"]
            or hashlib.sha256(response.content).hexdigest() != evidence["sha256"]
        ):
            raise HTTPException(503, "Stored evidence failed integrity verification")
        return response.content


class ServiceGateway:
    """This class never accepts user JWTs. Callers verify actual Auth/membership first."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    @property
    def headers(self) -> dict[str, str]:
        if not self.settings.worker_configured:
            raise HTTPException(503, "Server-side Supabase setup is required")
        key = self.settings.supabase_secret_key.get_secret_value()
        headers = {"apikey": key}
        # Legacy service_role JWTs need bearer auth. Modern secret keys use the API gateway.
        if not key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def rpc(self, name: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self.client.post(
                self.settings.supabase_url + "/rest/v1/rpc/" + name,
                headers=self.headers,
                json={"payload": payload},
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Cloud service is unavailable") from exc
        return await checked_response(response)

    async def rows(self, table: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        try:
            response = await self.client.get(
                self.settings.supabase_url + "/rest/v1/" + table,
                headers=self.headers,
                params={"select": "*", **filters},
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Cloud service is unavailable") from exc
        value = await checked_response(response)
        if not isinstance(value, list):
            raise HTTPException(503, "Invalid cloud response")
        return value

    async def store(
        self, workspace_id: UUID, content: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        if not content or len(content) > 10_485_760:
            raise HTTPException(422, "Evidence must be nonempty and at most 10 MiB")
        if "/" in filename or "\\" in filename or len(filename) > 150:
            raise HTTPException(422, "Use a simple filename")
        path = f"{workspace_id}/{uuid4()}/{filename}"
        try:
            response = await self.client.post(
                self.settings.supabase_url + "/storage/v1/object/evidence/" + quote(path, safe="/"),
                content=content,
                headers={**self.headers, "Content-Type": content_type, "x-upsert": "false"},
            )
            if response.is_error:
                raise HTTPException(503, "Evidence upload failed; nothing was queued")
            # Independently read actual stored bytes before claiming hash/size in a DB command.
            downloaded = await self.client.get(
                self.settings.supabase_url + "/storage/v1/object/evidence/" + quote(path, safe="/"),
                headers=self.headers,
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Evidence upload or verification failed") from exc
        if downloaded.is_error or downloaded.content != content:
            raise HTTPException(503, "Evidence verification failed; nothing was queued")
        return {
            "object_path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "filename": filename,
            "content_type": content_type,
        }

    async def download(self, evidence: dict[str, Any]) -> bytes:
        try:
            response = await self.client.get(
                self.settings.supabase_url
                + "/storage/v1/object/evidence/"
                + quote(evidence["object_path"], safe="/"),
                headers=self.headers,
            )
        except httpx.RequestError as exc:
            raise HTTPException(503, "Evidence storage unavailable") from exc
        if (
            response.is_error
            or len(response.content) != evidence["byte_size"]
            or hashlib.sha256(response.content).hexdigest() != evidence["sha256"]
        ):
            raise HTTPException(503, "Snapshot evidence failed integrity verification")
        return response.content

    async def store_original(
        self, workspace_id: UUID, content: bytes, filename: str, source_id: UUID
    ) -> dict[str, Any]:
        """Create-once original with stable retry identity and exact readback.

        Empty text is preserved too; it becomes an explicit no-evidence result.
        This does not change the proof uploader's nonempty requirement.
        """
        if not isinstance(content, bytes) or len(content) > 8192:
            raise HTTPException(422, "Original exceeds the supported analysis envelope")
        if (
            not filename.strip()
            or filename in (".", "..")
            or len(filename) > 150
            or any(char in filename for char in ("/", "\\", "\x00"))
        ):
            raise HTTPException(422, "Use a simple original filename")
        path = f"{workspace_id}/{source_id}/{filename}"
        url = self.settings.supabase_url + "/storage/v1/object/evidence/" + quote(path, safe="/")
        try:
            response = await self.client.get(url, headers=self.headers)
            if response.status_code in (400, 404):
                # Supabase Storage uses 400 with error=not_found on some versions.
                if response.status_code == 400:
                    try:
                        missing = response.json().get("error", "").lower() in {
                            "not_found",
                            "not found",
                            "object not found",
                        }
                    except ValueError:
                        missing = False
                    if not missing:
                        raise HTTPException(
                            503, "Original storage availability could not be checked"
                        )
                created = await self.client.post(
                    url,
                    content=content,
                    headers={
                        **self.headers,
                        "Content-Type": "text/plain",
                        "x-upsert": "false",
                    },
                )
                if created.is_error and created.status_code not in (400, 409):
                    raise HTTPException(503, "Original upload failed; nothing was queued")
                response = await self.client.get(url, headers=self.headers)
            if response.is_error:
                raise HTTPException(503, "Original storage verification failed; nothing was queued")
            if response.content != content:
                raise HTTPException(409, "Delivery already contains different bytes; use a new key")
        except httpx.RequestError as exc:
            raise HTTPException(
                503, "Original upload unavailable; retry with the same delivery key"
            ) from exc
        return {
            "object_path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "filename": filename,
            "content_type": "text/plain",
        }
