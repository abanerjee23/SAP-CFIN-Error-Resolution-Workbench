"""Original-only preparation for the factual workflow.

This boundary does not parse business fields, read sidecars or create cloud cases.
The operational intake/worker must opt into it after the additive database migration.
The limits are an initial application envelope, not provider context guarantees.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID, uuid4, uuid5

from cfin.log_only_contracts import LogSourceManifest
from cfin.log_only_sources import (
    build_log_source,
    source_lines,
    validate_originals,
)

MAX_LOG_SOURCES = 8
MAX_LOG_BYTES = 8192
MAX_LOG_LINES = 64


class LogCapacityError(ValueError):
    """The complete input exceeds the supported baseline; nothing is truncated."""


@dataclass(frozen=True)
class OriginalUpload:
    filename: str
    content: bytes


@dataclass(frozen=True)
class LogInputs:
    manifest: LogSourceManifest
    originals: Mapping[tuple[str, str], bytes]

    def __post_init__(self) -> None:
        if any(not isinstance(raw, bytes) for raw in self.originals.values()):
            raise ValueError("Original content must be immutable bytes")
        # Copy the mapping so later mutation by an uploader cannot change a saved run.
        object.__setattr__(self, "originals", MappingProxyType(dict(self.originals)))
        validate_originals(self.manifest, self.originals)
        check_analysis_capacity(self)

    def extraction_payload(self) -> list[dict]:
        """One numbered representation, retaining line endings and source identity."""
        return [
            {
                "source": source.model_dump(mode="json"),
                "lines": [
                    {"line_number": number, "text": text}
                    for number, text in enumerate(
                        source_lines(self.originals[(source.source_id, source.source_version)])
                        if source.readable.status == "available"
                        else (),
                        start=1,
                    )
                ],
            }
            for source in self.manifest.sources
        ]


def check_analysis_capacity(inputs: LogInputs) -> None:
    if len(inputs.manifest.sources) > MAX_LOG_SOURCES:
        raise LogCapacityError(f"The first analysis envelope supports {MAX_LOG_SOURCES} originals")
    if sum(len(raw) for raw in inputs.originals.values()) > MAX_LOG_BYTES:
        raise LogCapacityError(f"The complete originals exceed the {MAX_LOG_BYTES}-byte envelope")
    if sum(source.readable.line_count for source in inputs.manifest.sources) > MAX_LOG_LINES:
        raise LogCapacityError(f"The complete originals exceed the {MAX_LOG_LINES}-line envelope")


def prepare_log_inputs(
    uploads: Sequence[OriginalUpload],
    *,
    provenance: str,
    intake_id: UUID | None = None,
) -> LogInputs:
    """Mint application identities; never infer SAP identity or processing chronology.

    ``intake_id`` is an application-owned receipt ID. Reusing it preserves source
    identities for a retry; changed bytes create a distinct content version.
    Provenance is explicit and is validated by the source contract.
    """
    if not uploads:
        raise ValueError("Supply at least one original UTF-8 text log")
    if len(uploads) > MAX_LOG_SOURCES:
        raise LogCapacityError(f"The first analysis envelope supports {MAX_LOG_SOURCES} originals")
    if any(not isinstance(upload.content, bytes) for upload in uploads):
        raise ValueError("Original content must be exact bytes")
    if sum(len(upload.content) for upload in uploads) > MAX_LOG_BYTES:
        raise LogCapacityError(f"The complete originals exceed the {MAX_LOG_BYTES}-byte envelope")
    receipt = intake_id or uuid4()
    sources = []
    originals = {}
    for index, upload in enumerate(uploads):
        if (
            not upload.filename.strip()
            or upload.filename in (".", "..")
            or len(upload.filename) > 150
            or any(char in upload.filename for char in ("/", "\\", "\x00"))
        ):
            raise ValueError("Use a simple original filename of at most 150 characters")
        source_id = str(uuid5(receipt, str(index)))
        version = hashlib.sha256(upload.content).hexdigest()
        source = build_log_source(
            source_id=source_id,
            source_version=version,
            original_filename=upload.filename,
            raw=upload.content,
            provenance=provenance,
        )
        if source.readable.status != "available":
            raise ValueError("Only UTF-8 text originals are supported for new log intake")
        sources.append(source)
        originals[(source_id, version)] = upload.content
    return LogInputs(manifest=LogSourceManifest(sources=tuple(sources)), originals=originals)
