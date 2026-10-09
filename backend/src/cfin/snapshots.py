"""Restore a run exclusively from its immutable saved evidence and review overlay."""

import json
from dataclasses import replace
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict

from cfin.contracts import (
    DocumentIdentity,
    Identifier,
    IntakeManifest,
    PositiveInt,
    ReferenceGovernance,
)
from cfin.fixture_loader import AGENT_FILES, FixtureInputs, parse_input_files
from cfin.gateway import ServiceGateway


class _SnapshotAttempt(BaseModel):
    """The immutable attempt fields used to bind a saved input pack."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Identifier
    workspace_id: Identifier
    case_id: Identifier
    attempt_key: Identifier
    processing_at: AwareDatetime
    processing_order: PositiveInt | None


async def restore_inputs(snapshot: dict[str, Any], cloud: ServiceGateway) -> FixtureInputs:
    files: dict[str, bytes] = {}
    reviews: dict[str, dict[str, Any]] = {}
    for source in snapshot["sources"]:
        evidence = source["evidence"]
        name = evidence["filename"]
        if name not in AGENT_FILES or evidence["kind"] == "proof":
            raise ValueError("Snapshot contains an undeclared input")
        if name in files:
            raise ValueError("Conflicting input source versions")
        files[name] = await cloud.download(evidence)
        if source.get("review"):
            review = source["review"]
            expected_kind = {
                "mapping-reference.json": "mapping",
                "missing-gl-master-playbook.json": "guidance",
            }.get(name)
            raw = json.loads(files[name])
            if review["reference_kind"] != expected_kind or review["scope"] != raw.get(
                "scope", raw.get("query_scope", {})
            ):
                raise ValueError("Review does not approve this exact saved reference scope")
            reviews[name] = source["review"]
    inputs = parse_input_files(files)
    identity = DocumentIdentity.model_validate(snapshot["identity"])
    overlays = snapshot.get("context_overlay", [])
    if not isinstance(overlays, list):
        raise ValueError("Invalid authenticated context overlay")
    original_identity = inputs.manifest.identity.model_dump(exclude={"workspace_id"})
    changed_identity = original_identity != identity.model_dump(exclude={"workspace_id"})
    order_review = None
    identity_review = None
    for overlay in overlays:
        if (
            overlay.get("case_id") != snapshot["case_id"]
            or overlay.get("workspace_id") != identity.workspace_id
            or overlay.get("acting_role") != "process_owner"
            or not overlay.get("actor_id")
            or not overlay.get("reason", "").strip()
            or not overlay.get("recorded_at")
        ):
            raise ValueError("Context overlay needs the authenticated process owner and scope")
        if overlay.get("kind") == "complete_identity":
            identity_review = overlay
        elif overlay.get("kind") == "review_attempt_order":
            order_review = overlay
        else:
            raise ValueError("Unknown context overlay")
    if changed_identity and (
        identity_review is None
        or identity_review["payload"].get("identity") != identity.model_dump(mode="json")
        or any(
            value is not None and value != getattr(identity, key)
            for key, value in original_identity.items()
        )
    ):
        raise ValueError("Saved document identity differs from the case")
    if inputs.manifest.business_context.model_dump(mode="json") != snapshot["business_context"]:
        raise ValueError("Saved business context differs from the case")
    manifest = IntakeManifest.model_validate(snapshot.get("manifest"))
    # Intake replaces only these two fixture values; every other manifest field
    # must still match the preserved bytes, including the original attempt time/order.
    # A supplied identity completion remains an authenticated overlay; source bytes are unchanged.
    expected = inputs.manifest.model_copy(
        update={
            "identity": inputs.manifest.identity.model_copy(
                update={"workspace_id": identity.workspace_id}
            ),
            "delivery_key": manifest.delivery_key,
        }
    )
    if manifest != expected:
        raise ValueError("Saved intake manifest differs from its immutable input")
    attempt = _SnapshotAttempt.model_validate(snapshot["attempt"])
    if attempt.attempt_key != manifest.attempt_id:
        raise ValueError("Original input belongs to a different attempt")
    reviewed_order = None
    if order_review:
        ordered = order_review["payload"].get("ordered_attempt_ids", [])
        if len(ordered) != len(set(ordered)) or attempt.id not in ordered:
            raise ValueError("Attempt order overlay must name this exact saved attempt once")
        reviewed_order = ordered.index(attempt.id) + 1
    if attempt.processing_at != manifest.processing_at or attempt.processing_order != (
        reviewed_order or manifest.processing_order
    ):
        raise ValueError("Saved attempt metadata differs from the intake manifest")
    if (
        attempt.id != snapshot["attempt_id"]
        or attempt.case_id != snapshot["case_id"]
        or attempt.workspace_id != identity.workspace_id
    ):
        raise ValueError("Saved attempt belongs to a different case or workspace")
    catalogue = []
    by_source = {
        inputs.sources[name]["source_id"]: row
        for name, row in reviews.items()
        if name in ("mapping-reference.json", "missing-gl-master-playbook.json")
    }
    for source in inputs.catalogue:
        row = by_source.get(source.source_id)
        if row and source.governance:
            data = source.governance.model_dump()
            data.update(
                reuse_status=row["decision"],
                approved_version=source.source_version if row["decision"] == "approved" else None,
                reviewer=str(row["actor_id"]),
                reviewed_at=row["reviewed_at"],
            )
            source = source.model_copy(
                update={"governance": ReferenceGovernance.model_validate(data)}
            )
        catalogue.append(source)
    indexed = {(s.source_id, s.source_version): s for s in catalogue}
    lookups = []
    for lookup in inputs.lookups:
        registered = indexed[(lookup.source.source_id, lookup.source.source_version)]
        lookups.append(
            lookup.model_copy(
                update={
                    "source": lookup.source.model_copy(update={"governance": registered.governance})
                }
            )
        )
    guidance = []
    for guide in inputs.guidance:
        row = reviews.get("missing-gl-master-playbook.json")
        if row:
            data = guide.model_dump()
            data.update(
                reuse_status=row["decision"],
                approved_version=guide.source_version if row["decision"] == "approved" else None,
                reviewer=str(row["actor_id"]),
                reviewed_at=row["reviewed_at"],
            )
            if row["decision"] == "withdrawn":
                data["withdrawn_at"] = row["reviewed_at"]
            guide = type(guide).model_validate(data)
        guidance.append(guide)
    sources = json.loads(json.dumps(inputs.sources))
    if overlays:
        sources["source-posting.json"]["authenticated_context_overlay"] = overlays
    for name, row in reviews.items():
        if name in sources:
            sources[name]["authenticated_review_overlay"] = row
    return replace(
        inputs,
        manifest=manifest.model_copy(
            update={
                "identity": identity,
                "processing_order": attempt.processing_order,
            }
        ),
        catalogue=tuple(catalogue),
        lookups=tuple(lookups),
        guidance=tuple(guidance),
        sources=sources,
    )
