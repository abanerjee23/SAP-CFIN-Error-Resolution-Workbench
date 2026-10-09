"""Exact source integrity and line coverage for the bounded log-only workflow.

No SAP field parsing or business inference belongs here. All line slices preserve
UTF-8 characters and original CR/LF terminators. Empty originals have zero lines.
"""

import hashlib
import json
from collections.abc import Mapping

from cfin.log_only_contracts import (
    ExtractedLog,
    ExtractionValidation,
    LogSource,
    LogSourceManifest,
    Provenance,
    ReadableLocation,
    SourceRegion,
    SourceSpan,
)

Originals = Mapping[tuple[str, str], bytes]


def source_lines(raw: bytes) -> tuple[str, ...]:
    """Strict UTF-8; only CR, LF and CRLF delimit lines, matching text logs.

    str.splitlines also treats Unicode separators/form feeds as line breaks.
    Those characters stay in their original line here, avoiding shifted locators.
    """
    text = raw.decode("utf-8", errors="strict")
    result = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\r\n":
            index += 1
            if char == "\r" and index < len(text) and text[index] == "\n":
                index += 1
            result.append(text[start:index])
            start = index
        else:
            index += 1
    if start < len(text):
        result.append(text[start:])
    return tuple(result)


def source_span_text(raw: bytes, span: SourceSpan) -> str:
    lines = source_lines(raw)
    if span.line_end > len(lines):
        raise ValueError("Entry source span exceeds the preserved original")
    return "".join(lines[span.line_start - 1 : span.line_end])


def build_log_source(
    *,
    source_id: str,
    source_version: str,
    original_filename: str,
    raw: bytes,
    provenance: Provenance,
) -> LogSource:
    try:
        readable = ReadableLocation(status="available", line_count=len(source_lines(raw)))
    except UnicodeDecodeError:
        readable = ReadableLocation(
            status="unreadable",
            line_count=0,
            limitation="The original cannot be decoded as UTF-8; no replacement text was used.",
        )
    return LogSource(
        source_id=source_id,
        source_version=source_version,
        original_filename=original_filename,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        provenance=provenance,
        readable=readable,
    )


def manifest_fingerprint(manifest: LogSourceManifest) -> str:
    encoded = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_originals(manifest: LogSourceManifest, originals: Originals) -> None:
    """Reject missing, extra, altered or falsely described original content."""
    expected = {(source.source_id, source.source_version) for source in manifest.sources}
    if set(originals) != expected:
        raise ValueError("Originals must match exactly the immutable source manifest")
    for source in manifest.sources:
        raw = originals[(source.source_id, source.source_version)]
        actual = build_log_source(
            source_id=source.source_id,
            source_version=source.source_version,
            original_filename=source.original_filename,
            raw=raw,
            provenance=source.provenance,
        )
        if actual != source:
            raise ValueError("Original bytes or readable metadata do not match the source manifest")


def validate_extraction(
    manifest: LogSourceManifest,
    originals: Originals,
    extracted: ExtractedLog,
) -> ExtractionValidation:
    """Validate exact quotes and compute visible omissions; never infer log fields."""
    validate_originals(manifest, originals)
    by_key = {(source.source_id, source.source_version): source for source in manifest.sources}
    covered: dict[tuple[str, str], set[int]] = {key: set() for key in by_key}
    for entry in extracted.entries:
        key = (entry.source_id, entry.source_version)
        source = by_key.get(key)
        if source is None:
            raise ValueError("Extraction references an unregistered source or version")
        if source.readable.status != "available":
            raise ValueError("Extraction cannot quote an unreadable source")
        if entry.raw_text != source_span_text(originals[key], entry.source_span):
            raise ValueError("Extracted raw_text must match its exact preserved source slice")
        covered[key].update(range(entry.source_span.line_start, entry.source_span.line_end + 1))
    gaps = []
    unreadable = []
    limitations = []
    for key, source in by_key.items():
        if source.readable.status == "unreadable":
            unreadable.append(source.source_id)
            limitations.append(f"Source {source.source_id}: {source.readable.limitation}")
            continue
        if source.readable.line_count == 0:
            limitations.append(
                f"Source {source.source_id} is empty; it contains no readable lines."
            )
        start = None
        for line in range(1, source.readable.line_count + 2):
            missing = line <= source.readable.line_count and line not in covered[key]
            if missing and start is None:
                start = line
            elif not missing and start is not None:
                region = SourceRegion(
                    source_id=source.source_id,
                    source_version=source.source_version,
                    source_span=SourceSpan(line_start=start, line_end=line - 1),
                )
                gaps.append(region)
                limitations.append(
                    f"Source {source.source_id} version {source.source_version}, lines "
                    f"{start}–{line - 1}, were not represented in the extraction."
                )
                start = None
    return ExtractionValidation(
        uncovered_regions=tuple(gaps),
        unreadable_source_ids=tuple(unreadable),
        limitations=tuple(limitations),
    )
