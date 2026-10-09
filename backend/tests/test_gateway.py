"""Gateway boundaries with HTTP responses, without network access or live credentials."""

import asyncio
import hashlib
import json
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from cfin.config import Settings
from cfin.gateway import ServiceGateway, UserGateway

WORKSPACE = UUID("00000000-0000-4000-8000-000000000001")
PUBLISHABLE = "test-only-publishable"
SECRET = "sb_secret_test_only_not_a_real_key"
TOKEN = "test-only-user-token"


def gateway_settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://synthetic-test.supabase.co",
        supabase_publishable_key=PUBLISHABLE,
        supabase_secret_key=SECRET,
    )


@pytest.mark.parametrize("privileged", [False, True], ids=["user-rpc", "service-rpc"])
@pytest.mark.parametrize(
    ("upstream_status", "public_status", "detail"),
    [
        (422, 422, "Action input or transition is invalid"),
        (500, 503, "Cloud action failed; retry later"),
    ],
    ids=["sql-PT422", "cloud-failure"],
)
def test_rpc_retains_validation_status_without_disclosing_sql(
    privileged: bool, upstream_status: int, public_status: int, detail: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/cfin_case_action"
        assert json.loads(request.content) == {"payload": {"action": "start_work"}}
        assert request.headers["apikey"] == (SECRET if privileged else PUBLISHABLE)
        if privileged:
            assert "authorization" not in request.headers
        else:
            assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(
            upstream_status,
            json={
                "code": "PT422" if upstream_status == 422 else "XX000",
                "message": "private SQL function and evidence details",
                "details": "private database context",
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if privileged:
                await ServiceGateway(gateway_settings(), client).rpc(
                    "cfin_case_action", {"action": "start_work"}
                )
            else:
                await UserGateway(gateway_settings(), client).rpc(
                    "cfin_case_action", TOKEN, {"action": "start_work"}
                )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(exercise())
    assert caught.value.status_code == public_status
    assert caught.value.detail == detail
    assert "private" not in caught.value.detail


def test_service_upload_readback_and_download_use_authenticated_base_object_route() -> None:
    content = b'{"document":"0000123456","synthetic":true}'
    requests: list[httpx.Request] = []
    stored: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.startswith(f"/storage/v1/object/evidence/{WORKSPACE}/")
        assert request.headers["apikey"] == SECRET
        assert "authorization" not in request.headers
        if request.method == "POST":
            assert request.headers["x-upsert"] == "false"
            assert request.headers["content-type"] == "application/json"
            stored[request.url.path] = request.content
            return httpx.Response(200, json={"Key": request.url.path})
        assert request.method == "GET"
        return httpx.Response(200, content=stored[request.url.path])

    async def exercise() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = ServiceGateway(gateway_settings(), client)
            evidence = await gateway.store(
                WORKSPACE, content, "source document.json", "application/json"
            )
            assert await gateway.download(evidence) == content
            return evidence

    evidence = asyncio.run(exercise())
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert len({request.url for request in requests}) == 1
    assert requests[0].url.raw_path.endswith(b"source%20document.json")
    assert evidence["sha256"] == hashlib.sha256(content).hexdigest()
    assert evidence["byte_size"] == len(content)


def test_service_upload_cannot_claim_verified_evidence_after_corrupt_readback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"Key": request.url.path})
        return httpx.Response(200, content=b"changed")

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ServiceGateway(gateway_settings(), client).store(
                WORKSPACE, b"original", "proof.txt", "text/plain"
            )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(exercise())
    assert caught.value.status_code == 503
    assert caught.value.detail == "Evidence verification failed; nothing was queued"


def test_service_snapshot_download_rejects_same_size_hash_mismatch() -> None:
    original = b"original"
    evidence = {
        "object_path": f"{WORKSPACE}/snapshot/proof.txt",
        "byte_size": len(original),
        "sha256": hashlib.sha256(original).hexdigest(),
    }

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"modified"))
        ) as client:
            await ServiceGateway(gateway_settings(), client).download(evidence)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(exercise())
    assert caught.value.status_code == 503
    assert caught.value.detail == "Snapshot evidence failed integrity verification"
