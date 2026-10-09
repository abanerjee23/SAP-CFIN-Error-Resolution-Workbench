"""Read one version-consistent case and verify every original; no writes or models.

CFIN_API_URL=https://your-api.example
CFIN_READ_TOKEN=<privately supplied scoped read token>
CFIN_WORKSPACE_ID=<workspace UUID>
python examples/read_case.py --case-id <UUID> [--output-dir ./private-case]

The token never appears in a URL, command argument, output or exported bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PAGES = 1000
TIMEOUT_SECONDS = 20


class ReadFailure(Exception):
    """Deliberately excludes private server bodies and credential-bearing requests."""


class SnapshotChanged(ReadFailure):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReadFailure("Redirect refused. Configure the API's final HTTPS origin.")


class Client:
    def __init__(self, origin: str, token: str, workspace_id: str):
        url = urlsplit(origin)
        if (
            not url.hostname
            or url.scheme not in ("http", "https")
            or (url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"))
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ReadFailure(
                "CFIN_API_URL must be an HTTPS origin (HTTP is allowed only on loopback)."
            )
        if not re.fullmatch(r"cfin_read_[A-Za-z0-9_-]{43}", token):
            raise ReadFailure("Supply a scoped CFIN_READ_TOKEN through the environment.")
        self.origin = origin.rstrip("/")
        self.token = token
        self.workspace_id = str(UUID(workspace_id))
        self.opener = build_opener(NoRedirect())

    def get(self, path: str, params: dict | None = None, *, raw: bool = False):
        query = urlencode({"workspace_id": self.workspace_id, **(params or {})})
        request = Request(
            self.origin + path + "?" + query,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/octet-stream" if raw else "application/json",
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ReadFailure("Response exceeded this client's explicit byte bound.")
        except HTTPError as exc:
            if exc.code == 409:
                raise SnapshotChanged("Case version or list snapshot changed.") from None
            reason = {
                400: "HTTPS is required.",
                401: "A scoped token is required.",
                403: "Scope, workspace, expiry or revocation denied access.",
                404: "The requested case/source is unavailable.",
                422: "Request or cursor is incompatible.",
                503: "Saved reads are temporarily unavailable.",
            }.get(exc.code, "Read failed.")
            raise ReadFailure(f"HTTP {exc.code}: {reason}") from None
        except (URLError, TimeoutError, OSError):
            raise ReadFailure("Network read failed; no private response was logged.") from None
        if raw:
            return body
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError):
            raise ReadFailure("The service returned invalid JSON.") from None
        if not isinstance(result, dict) or result.get("api_version") != "v1":
            raise ReadFailure("Unexpected case-read API version or response shape.")
        return result

    def pages(self, path: str, params: dict | None = None) -> list[dict]:
        query = {"limit": 25, **(params or {})}
        items, seen_cursors = [], set()
        first_binding = None
        for _ in range(MAX_PAGES):
            page = self.get(path, query)
            if "case_version" in query and (
                page.get("case_version") != query["case_version"]
                or page.get("case_id") != path.split("/")[4]
            ):
                raise ReadFailure("Page does not match the requested case version.")
            if path == "/api/v1/cases" and page.get("workspace_id") != self.workspace_id:
                raise ReadFailure("Listing does not match the requested workspace.")
            binding = (
                page.get("snapshot_id"),
                page.get("case_id"),
                page.get("case_version"),
                page.get("analysis_run_id"),
                page.get("total"),
            )
            if first_binding is None:
                first_binding = binding
            if binding != first_binding or not isinstance(page.get("items"), list):
                raise ReadFailure("Page binding changed; partial results were discarded.")
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if cursor is None:
                if len(items) != page.get("total"):
                    raise ReadFailure("Page totals do not match the complete response.")
                return items
            if not page["items"] or not isinstance(cursor, str) or cursor in seen_cursors:
                raise ReadFailure("Invalid or repeated page cursor.")
            seen_cursors.add(cursor)
            query["cursor"] = cursor
        raise ReadFailure("Page count exceeded this client's explicit limit.")

    def list_cases(self, *, workflow_version: str | None = None) -> list[dict]:
        # An expired 10-minute listing discards the whole old listing once.
        for attempt in range(2):
            try:
                return self.pages(
                    "/api/v1/cases",
                    {"workflow_version": workflow_version} if workflow_version else {},
                )
            except SnapshotChanged:
                if attempt:
                    raise
        raise AssertionError("Unreachable")

    def read_case(self, case_id: str) -> tuple[dict, list[tuple[dict, bytes]]]:
        case_id = str(UUID(case_id))
        path = "/api/v1/cases/" + case_id
        # Never join pages/originals from different case versions. One bounded
        # restart handles normal concurrent human updates without a retry loop.
        for attempt in range(2):
            try:
                case = self.get(path)
                version = case.get("case_version")
                if (
                    case.get("case_id") != case_id
                    or case.get("workspace_id") != self.workspace_id
                    or not isinstance(version, int)
                ):
                    raise ReadFailure("Unexpected case identity or version.")
                params = {"case_version": version}
                bundle = {
                    "case": case,
                    "activity": self.pages(path + "/activity", params),
                    "records": self.pages(path + "/records", params),
                }
                result = case.get("result") or {}
                if result.get("result_kind") == "factual" and result.get("extraction") is not None:
                    bundle["extraction"] = self.pages(path + "/extraction", params)
                    bundle["selected_evidence"] = self.pages(path + "/selected-evidence", params)
                originals = []
                for source in case.get("sources", []):
                    source_path = path + "/sources/" + quote(source["source_id"], safe="")
                    source_params = {**params, "source_version": source["source_version"]}
                    original = self.get(source_path, source_params)
                    if (
                        original.get("case_id"),
                        original.get("case_version"),
                        original.get("source_id"),
                        original.get("source_version"),
                    ) != (case_id, version, source["source_id"], source["source_version"]):
                        raise ReadFailure("Original binding differs from the requested snapshot.")
                    try:
                        encoded = original["text"].encode("utf-8")
                    except (KeyError, AttributeError, UnicodeError):
                        raise ReadFailure(
                            "Original text cannot reproduce its UTF-8 bytes."
                        ) from None
                    raw = self.get(source_path + "/download", source_params, raw=True)
                    digest = hashlib.sha256(raw).hexdigest()
                    if (
                        encoded != raw
                        or digest != original.get("sha256")
                        or digest != source.get("content_sha256")
                        or len(raw) != original.get("byte_size")
                        or len(raw) != source.get("byte_size")
                    ):
                        raise ReadFailure(
                            "Original byte size, text or SHA-256 verification failed."
                        )
                    originals.append((source, raw))
                self.get(path, params)  # Recheck case version and authorisation before publishing.
                return bundle, originals
            except SnapshotChanged:
                if attempt:
                    raise
        raise AssertionError("Unreachable")


def write_bundle(directory: Path, bundle: dict, originals: list[tuple[dict, bytes]]) -> None:
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    payloads = [("case.json", json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8"))]
    payloads.extend(
        (f"original-{index + 1}-{hashlib.sha256(raw).hexdigest()[:12]}.txt", raw)
        for index, (_, raw) in enumerate(originals)
    )
    for name, content in payloads:
        # Remote filenames are metadata only; never use them as local paths.
        fd = os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-id", help="Case UUID. Without this, list authorised cases and print only a count."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Create a new private directory after all reads/hash checks succeed.",
    )
    args = parser.parse_args()
    try:
        client = Client(
            os.environ.get("CFIN_API_URL", ""),
            os.environ.get("CFIN_READ_TOKEN", ""),
            os.environ.get("CFIN_WORKSPACE_ID", ""),
        )
        if not args.case_id:
            if args.output_dir:
                raise ReadFailure("--output-dir requires --case-id.")
            print(f"Verified listing: {len(client.list_cases())} authorised saved cases.")
            return 0
        bundle, originals = client.read_case(args.case_id)
        if args.output_dir:
            write_bundle(args.output_dir, bundle, originals)
        print(
            f"Verified one saved case and {len(originals)} unchanged originals; "
            "no model calls or case mutations."
        )
        return 0
    except ReadFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        # Avoid tracebacks, API payloads and environment values in terminal logs.
        print(
            "Read verification failed. Check configured scope, access, version, "
            "network and output destination.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
