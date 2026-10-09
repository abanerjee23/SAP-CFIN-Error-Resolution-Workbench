"""Restore immutable originals for the Error Analysis workflow."""

from typing import Any, Literal

from pydantic import Field, model_validator

from cfin.error_analysis_contracts import ErrorAnalysisBinding
from cfin.gateway import ServiceGateway
from cfin.log_only_contracts import (
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


class SavedErrorAnalysisEvidence(LogContract):
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


class ErrorAnalysisInputSnapshot(LogContract):
    snapshot_version: Literal["error-analysis-snapshot-v1"]
    binding: ErrorAnalysisBinding
    source_manifest: LogSourceManifest
    sources: tuple[SavedErrorAnalysisEvidence, ...]
    routing_context: dict[str, NonEmptyText] = Field(default_factory=dict)

    @model_validator(mode="after")
    def all_metadata_matches(self) -> "ErrorAnalysisInputSnapshot":
        if self.binding.source_manifest_sha256 != manifest_fingerprint(self.source_manifest):
            raise ValueError("Saved source manifest differs from the execution binding")
        if len(self.sources) != len(self.source_manifest.sources):
            raise ValueError("Snapshot must declare exactly every original")
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Saved evidence IDs must be unique")
        for original, saved in zip(self.source_manifest.sources, self.sources, strict=True):
            if (saved.workspace_id, saved.case_id, saved.attempt_id) != (
                self.binding.workspace_id,
                self.binding.case_id,
                self.binding.attempt_id,
            ):
                raise ValueError("Saved original belongs to another case scope")
            if (
                saved.source_id,
                saved.source_version,
                saved.filename,
                saved.sha256,
                saved.byte_size,
                saved.content_type,
                saved.provenance,
            ) != (
                original.source_id,
                original.source_version,
                original.original_filename,
                original.content_sha256,
                original.byte_size,
                original.content_type,
                original.provenance,
            ):
                raise ValueError("Saved original metadata differs from immutable manifest")
        if (
            len(self.sources) > MAX_LOG_SOURCES
            or sum(item.byte_size for item in self.sources) > MAX_LOG_BYTES
        ):
            raise LogCapacityError("Saved originals exceed the supported analysis envelope")
        if sum(item.readable.line_count for item in self.source_manifest.sources) > MAX_LOG_LINES:
            raise LogCapacityError("Saved originals exceed the supported analysis envelope")
        return self


async def restore_error_analysis_inputs(
    snapshot: ErrorAnalysisInputSnapshot | dict[str, Any],
    cloud: ServiceGateway,
    *,
    expected_binding: ErrorAnalysisBinding,
) -> LogInputs:
    saved = ErrorAnalysisInputSnapshot.model_validate(
        snapshot.model_dump() if isinstance(snapshot, ErrorAnalysisInputSnapshot) else snapshot
    )
    if saved.binding != expected_binding:
        raise ValueError("Snapshot differs from independently leased execution binding")
    originals: dict[tuple[str, str], bytes] = {}
    for source, original in zip(saved.sources, saved.source_manifest.sources, strict=True):
        raw = await cloud.download(source.model_dump(mode="json"))
        validate_originals(
            LogSourceManifest(sources=(original,)), {(source.source_id, source.source_version): raw}
        )
        originals[(source.source_id, source.source_version)] = raw
    return LogInputs(manifest=saved.source_manifest, originals=originals)
