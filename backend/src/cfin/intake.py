"""General synthetic intake with immutable saved sources and explicit human context."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cfin.contracts import DocumentIdentity
from cfin.fixture_loader import (
    AGENT_FILES,
    MAX_INPUT_BYTES,
    RECORD_FILES,
    FixtureInputs,
    _read_files,
    parse_input_files,
)
from cfin.gateway import ServiceGateway, UserGateway

JSON_FILES = tuple(name for name in AGENT_FILES if name.endswith(".json"))
MAX_PACK_BYTES = 10_485_760
SUPPORTED_SCENARIOS = ("MD-01", "MAP-01")


class IntakeControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    expected_version: int = Field(gt=0, strict=True)
    acting_role: Literal["process_owner"] = "process_owner"
    action: Literal["complete_identity", "review_attempt_order", "link_case"]
    reason: str = Field(min_length=1, max_length=10000)
    payload: dict[str, Any] = Field(default_factory=dict)


def encode_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _forbidden_material(value: Any) -> bool:
    """Exclude dedicated answers/proof and authenticated overlays from input uploads."""
    forbidden = {
        "routing_oracle",
        "expected_answer",
        "expected_diagnosis",
        "correction_proof",
        "reprocessing_proof",
        "validation_proof",
        "authenticated_review_overlay",
        "authenticated_context_overlay",
        "resolved_outcome",
    }
    if isinstance(value, dict):
        return bool(forbidden.intersection(value)) or any(
            _forbidden_material(item) for item in value.values()
        )
    return isinstance(value, list) and any(_forbidden_material(item) for item in value)


def prepare_pack(body: Any) -> tuple[FixtureInputs, dict[str, bytes], bool]:
    """Validate all bytes before any privileged storage write; approvals are server-only."""
    legacy = body.agent_files is None
    try:
        if legacy:
            root = Path(__file__).resolve().parents[3] / "fixtures/MD-01/agent-visible"
            files = _read_files(root)
            inputs = parse_input_files(files)
            expected = inputs.manifest.model_copy(
                update={
                    "identity": inputs.manifest.identity.model_copy(
                        update={"workspace_id": str(body.workspace_id)}
                    ),
                    "delivery_key": body.delivery_key,
                }
            )
            if body.manifest != expected or body.original_log != inputs.original_log:
                raise ValueError("Supply a complete structured pack for revised or general intake")
            return inputs, files, True
        if set(body.agent_files) != set(JSON_FILES):
            raise ValueError("Supply exactly the eight allowed JSON input files")
        if _forbidden_material(body.agent_files):
            raise ValueError("Proof, answer keys and authenticated overlays are not intake inputs")
        if body.manifest.identity.workspace_id != str(body.workspace_id):
            raise ValueError("Manifest workspace must match the selected workspace")
        if body.manifest.delivery_key != body.delivery_key:
            raise ValueError("Manifest delivery key must match the submitted delivery key")
        files = {name: encode_json(value) for name, value in body.agent_files.items()}
        files["original-log.txt"] = body.original_log.encode("utf-8")
        if sum(map(len, files.values())) > MAX_PACK_BYTES:
            raise ValueError("The complete input pack must be at most 10 MiB")
        inputs = parse_input_files(files)
        if inputs.manifest != body.manifest:
            raise ValueError("Saved manifest must match the submitted manifest")
        for source in inputs.catalogue:
            review = source.governance
            if review and (
                review.reuse_status.value != "pending_review"
                or any(
                    value is not None
                    for value in (review.reviewer, review.reviewed_at, review.approved_version)
                )
            ):
                raise ValueError("Input uploads cannot supply a reference approval")
        guides = list(inputs.guidance)
        while guides:
            guide = guides.pop()
            if (
                guide.reuse_status.value != "pending_review"
                or guide.reviewer is not None
                or guide.reviewed_at is not None
                or guide.approved_version is not None
            ):
                raise ValueError("Input uploads cannot supply a guidance approval")
            guides.extend(guide.shared_policies)
        if any(
            item.get("currently_satisfied") is not False
            for item in inputs.sources["missing-gl-master-playbook.json"].get(
                "prerequisites_and_approvals", []
            )
        ):
            raise ValueError("Uploaded guidance cannot attest completed human prerequisites")
        return inputs, files, False
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        detail = (
            "Structured input schema is invalid" if isinstance(exc, ValidationError) else str(exc)
        )
        raise HTTPException(422, "Invalid synthetic input pack: " + detail[:220]) from exc


def source_metadata(name: str, content: bytes, inputs: FixtureInputs, *, legacy: bool) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    if name == "original-log.txt":
        source_id, version = inputs.manifest.source_id, inputs.manifest.source_version
    elif legacy:
        source_id = {
            "mapping-reference.json": "MD01-mapping",
            "missing-gl-master-playbook.json": "MD01-playbook",
        }.get(name, "MD01-file-" + name.removesuffix(".json"))
        version = "1"
    elif name in RECORD_FILES:
        payload = inputs.sources[name]
        source_id, version = payload["source_id"], payload["source_version"]
    else:
        # Ancillary manifest/catalogue/lookup containers have content-addressed versions.
        source_id = inputs.manifest.source_id + "-file-" + name.removesuffix(".json")
        version = digest
    provenance = {
        "synthetic": True,
        "input_filename": name,
        "description": "Preserved synthetic failure-time input; human approval remains separate",
    }
    if name in ("mapping-reference.json", "missing-gl-master-playbook.json"):
        payload = inputs.sources[name]
        provenance.update(
            reference_kind="mapping" if name == "mapping-reference.json" else "guidance",
            reference_scope=payload.get("scope", payload.get("query_scope", {})),
        )
    observed_at = inputs.manifest.processing_at
    if not legacy and name in RECORD_FILES:
        observed_at = next(
            source.observed_at
            for source in inputs.catalogue
            if source.source_id == source_id and source.source_version == version
        )
    return {
        "source_id": source_id,
        "source_version": version,
        "observed_at": observed_at.isoformat(),
        "provenance": provenance,
    }


async def commit_intake(
    user: UserGateway,
    service: ServiceGateway,
    token: str,
    actor_id: UUID,
    body: Any,
) -> dict[str, Any]:
    await user.require_member(token, actor_id, body.workspace_id, body.acting_role)
    if body.acting_role != "process_owner":
        raise HTTPException(403, "Process owner intake required")
    inputs, files, legacy = prepare_pack(body)
    existing = await user.rows(
        "evidence_versions", token, body.workspace_id, {"case_id": "is.null"}
    )
    source_links = []
    for name, content in files.items():
        if name == "original-log.txt":
            continue
        metadata = source_metadata(name, content, inputs, legacy=legacy)
        saved = next(
            (
                item
                for item in existing
                if item["source_id"] == metadata["source_id"]
                and item["source_version"] == metadata["source_version"]
            ),
            None,
        )
        digest = hashlib.sha256(content).hexdigest()
        if saved and (saved["sha256"] != digest or saved["filename"] != name):
            raise HTTPException(409, "Saved input version differs; provide a new source version")
        if not saved:
            storage = await service.store(body.workspace_id, content, name, "application/json")
            storage.update(metadata)
            saved = await service.rpc(
                "cfin_register_evidence",
                {
                    "actor_id": str(actor_id),
                    "acting_role": body.acting_role,
                    "workspace_id": str(body.workspace_id),
                    "kind": "guidance"
                    if name == "missing-gl-master-playbook.json"
                    else "reference",
                    "storage": storage,
                },
            )
        source_links.append(
            {
                "filename": name,
                "evidence_id": saved["id"],
                "sha256": digest,
                "source_id": metadata["source_id"],
                "source_version": metadata["source_version"],
            }
        )
    original = files["original-log.txt"]
    storage = await service.store(body.workspace_id, original, "original-log.txt", "text/plain")
    storage.update(source_metadata("original-log.txt", original, inputs, legacy=legacy))
    # Include every immutable input hash in delivery idempotency, not just the log hash.
    pack_hash = hashlib.sha256(
        encode_json({name: hashlib.sha256(files[name]).hexdigest() for name in sorted(files)})
    ).hexdigest()
    result = await service.rpc(
        "cfin_commit_intake",
        {
            "actor_id": str(actor_id),
            "acting_role": body.acting_role,
            "workspace_id": str(body.workspace_id),
            "delivery_key": body.delivery_key,
            "manifest": body.manifest.model_dump(mode="json"),
            "storage": storage,
            "input_sources": source_links,
            "input_pack_sha256": pack_hash,
        },
    )
    cases = await user.rows("cases", token, body.workspace_id, {"id": "eq." + result["case_id"]})
    if len(cases) != 1:
        raise HTTPException(503, "Saved intake case could not be read; refresh before retrying")
    return {**result, "version": cases[0]["version"]}


async def apply_intake_control(
    user: UserGateway,
    token: str,
    actor_id: UUID,
    case_id: UUID,
    body: IntakeControlRequest,
) -> dict[str, Any]:
    await user.require_member(token, actor_id, body.workspace_id, body.acting_role)
    if not body.reason.strip():
        raise HTTPException(422, "Record a reason for the context change")
    payload = body.payload
    try:
        if body.action == "complete_identity":
            if set(payload) != {"identity"}:
                raise ValueError("Supply identity only")
            identity = DocumentIdentity.model_validate(payload["identity"])
            if not identity.is_complete or identity.workspace_id != str(body.workspace_id):
                raise ValueError("Supply complete identity in the selected workspace")
        elif body.action == "review_attempt_order":
            if set(payload) != {"ordered_attempt_ids"}:
                raise ValueError("Supply ordered_attempt_ids only")
            ordered = payload["ordered_attempt_ids"]
            if not isinstance(ordered, list) or not ordered or len(ordered) > 1000:
                raise ValueError("Supply a bounded oldest-to-newest attempt list")
            if len({str(UUID(str(item))) for item in ordered}) != len(ordered):
                raise ValueError("Attempt IDs must be valid and unique")
        elif set(payload) != {"target_case_id", "expected_target_version"} or (
            not isinstance(payload["expected_target_version"], int)
            or isinstance(payload["expected_target_version"], bool)
            or payload["expected_target_version"] <= 0
        ):
            raise ValueError("Select a saved target case and its current version")
        elif UUID(str(payload["target_case_id"])) == case_id:
            raise ValueError("A case cannot link to itself")
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, "Invalid context control: " + str(exc)[:180]) from exc
    return await user.rpc(
        "cfin_intake_control",
        token,
        {
            **body.model_dump(mode="json"),
            "case_id": str(case_id),
        },
    )


def scenario_template(scenario_id: str, workspace_id: UUID) -> dict[str, Any]:
    """Return labelled pending-review input bytes; no successful outcome or answer files."""
    if scenario_id not in SUPPORTED_SCENARIOS:
        raise HTTPException(404, "Synthetic scenario not found")
    root = Path(__file__).resolve().parents[3] / "fixtures" / scenario_id / "agent-visible"
    if scenario_id == "MD-01":
        files = _read_files(root)
    else:
        files = {}
        for name in AGENT_FILES:
            path = root / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
                raise HTTPException(503, "Synthetic template is unavailable")
            files[name] = path.read_bytes()
    inputs = parse_input_files(files)
    manifest = inputs.manifest.model_dump(mode="json")
    manifest["identity"]["workspace_id"] = str(workspace_id)
    agent_files = {name: json.loads(value) for name, value in files.items() if name in JSON_FILES}
    agent_files["manifest.json"] = manifest
    agent_files["source-posting.json"]["identity"] = manifest["identity"]
    return {
        "synthetic": True,
        "manifest": manifest,
        "original_log": inputs.original_log,
        "agent_files": agent_files,
        "sources": [source.model_dump(mode="json") for source in inputs.catalogue],
    }
