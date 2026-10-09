"""Restore exact factual originals from a draft, versioned saved-run snapshot.

This is an internal foundation, not the shape of an installed database RPC. An
additive migration and authorised database projection must provide this envelope
before an operational worker uses it. It does not upload, register, enqueue,
mutate, consult repository fixtures, or complete missing SAP identity.

The caller must obtain ``expected_binding`` from the authenticated/leased run,
not from an untrusted snapshot or request. Scope checks here supplement that
access decision; possession of a matching snapshot is not authorisation.
"""

from typing import Any, Literal

from pydantic import model_validator

from cfin.gateway import ServiceGateway
from cfin.log_only_contracts import (
    ExecutionBinding,
    LogContract,
    LogSourceManifest,
    NonEmptyText,
    NonNegativeInt,
    Provenance,
    Sha256,
)
from cfin.log_only_inputs import (
    MAX_LOG_BYTES,
    MAX_LOG_LINES,
    MAX_LOG_SOURCES,
    LogCapacityError,
    LogInputs,
)
from cfin.log_only_sources import manifest_fingerprint, validate_originals


class SavedLogEvidence(LogContract):
    """Allowlisted saved original metadata, using ServiceGateway.download keys.

    This projection intentionally requires case/attempt scope for every supplied
    original. It does not accept unscoped legacy references or proof attachments.
    ``provenance`` is the normalised manifest label, not a raw legacy DB JSON row.
    """

    id: NonEmptyText
    workspace_id: NonEmptyText
    case_id: NonEmptyText
    attempt_id: NonEmptyText
    source_id: NonEmptyText
    source_version: NonEmptyText
    kind: Literal["original_log"] = "original_log"
    filename: NonEmptyText
    bucket_id: Literal["evidence"] = "evidence"
    object_path: NonEmptyText
    sha256: Sha256
    byte_size: NonNegativeInt
    content_type: Literal["text/plain"] = "text/plain"
    provenance: Provenance

    @model_validator(mode="after")
    def scoped_path(self) -> "SavedLogEvidence":
        # Existing storage uses workspace/object-directory/filename. Check the
        # actual path independently of claimed row scope before service access.
        parts = self.object_path.split("/")
        if (
            len(parts) != 3
            or parts[0] != self.workspace_id
            or parts[-1] != self.filename
            or any(part in ("", ".", "..") for part in parts)
            or any(char in self.object_path for char in ("\\", "\x00"))
            or len(self.filename) > 150
        ):
            raise ValueError("Saved original storage path must match its workspace and filename")
        return self


class LogInputSnapshot(LogContract):
    # Missing versions must not reinterpret an unversioned or legacy saved input.
    snapshot_version: Literal["log-only-snapshot-draft-v1"]
    binding: ExecutionBinding
    source_manifest: LogSourceManifest
    sources: tuple[SavedLogEvidence, ...]

    @model_validator(mode="after")
    def all_metadata_matches(self) -> "LogInputSnapshot":
        """Validate the whole catalogue before the first privileged download."""
        if self.binding.source_manifest_sha256 != manifest_fingerprint(self.source_manifest):
            raise ValueError("Saved source manifest differs from the execution binding")
        manifest = self.source_manifest.sources
        if len(self.sources) != len(manifest):
            raise ValueError("Snapshot must declare exactly every original in the source manifest")
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Saved evidence IDs must be unique")
        if len({source.object_path for source in self.sources}) != len(self.sources):
            raise ValueError("Saved original object paths must be unique")
        for original, saved in zip(manifest, self.sources, strict=True):
            if (saved.workspace_id, saved.case_id, saved.attempt_id) != (
                self.binding.workspace_id,
                self.binding.case_id,
                self.binding.attempt_id,
            ):
                raise ValueError("Saved original belongs to another workspace, case or attempt")
            if (
                saved.source_id != original.source_id
                or saved.source_version != original.source_version
                or saved.filename != original.original_filename
                or saved.sha256 != original.content_sha256
                or saved.byte_size != original.byte_size
                or saved.content_type != original.content_type
                or saved.provenance != original.provenance
            ):
                raise ValueError("Saved originals must match the ordered immutable source manifest")
        # Capacity is knowable from authenticated metadata before storage reads.
        if len(manifest) > MAX_LOG_SOURCES:
            raise LogCapacityError("Saved originals exceed the supported source-count envelope")
        if sum(source.byte_size for source in manifest) > MAX_LOG_BYTES:
            raise LogCapacityError("Saved originals exceed the supported byte envelope")
        if sum(source.readable.line_count for source in manifest) > MAX_LOG_LINES:
            raise LogCapacityError("Saved originals exceed the supported line envelope")
        return self


async def restore_log_inputs(
    snapshot: LogInputSnapshot | dict[str, Any],
    cloud: ServiceGateway,
    *,
    expected_binding: ExecutionBinding,
) -> LogInputs:
    """Read only the exact originals of the independently authorised run binding."""
    # Dump/revalidate also protects this boundary from nonvalidating model_copy()
    # constructions; callers cannot bypass checks by passing a model instance.
    saved = LogInputSnapshot.model_validate(
        snapshot.model_dump() if isinstance(snapshot, LogInputSnapshot) else snapshot
    )
    expected = ExecutionBinding.model_validate(expected_binding.model_dump())
    if saved.binding != expected:
        raise ValueError("Snapshot differs from the independently authorised execution binding")
    originals = {}
    for source, original in zip(saved.sources, saved.source_manifest.sources, strict=True):
        raw = await cloud.download(source.model_dump(mode="json"))
        if not isinstance(raw, bytes):
            raise ValueError("Saved original download did not return immutable bytes")
        key = (source.source_id, source.source_version)
        # Check each download immediately. The gateway normally checks hash/size;
        # this also confirms decoding/line metadata and defends alternate gateways.
        validate_originals(LogSourceManifest(sources=(original,)), {key: raw})
        originals[key] = raw
    return LogInputs(manifest=saved.source_manifest, originals=originals)
