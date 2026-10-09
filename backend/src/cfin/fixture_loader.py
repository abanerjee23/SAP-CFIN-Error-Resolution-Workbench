"""Bounded synthetic input packs; local fixtures are never a persistence fallback."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cfin.contracts import (
    Citation,
    GuidanceVersion,
    IntakeManifest,
    LookupResponse,
    SourceReference,
    source_matches_catalogue,
    validate_citations,
)

AGENT_FILES = (
    "manifest.json",
    "original-log.txt",
    "source-posting.json",
    "mapping-reference.json",
    "target-master-lookup.json",
    "target-master-query-audit.json",
    "missing-gl-master-playbook.json",
    "owner-directory.json",
    "source-catalogue.json",
)
RECORD_FILES = (
    "source-posting.json",
    "mapping-reference.json",
    "target-master-query-audit.json",
    "missing-gl-master-playbook.json",
    "owner-directory.json",
)
MAX_INPUT_BYTES = 1_048_576


@dataclass(frozen=True)
class FixtureInputs:
    manifest: IntakeManifest
    original_log: str
    catalogue: tuple[SourceReference, ...]
    lookups: tuple[LookupResponse, ...]
    guidance: tuple[GuidanceVersion, ...]
    sources: dict[str, dict[str, Any]]

    def agent_payload(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.model_dump(mode="json"),
            "original_log": self.original_log,
            "original_log_lines": [
                {"line_number": number, "text": line}
                for number, line in enumerate(self.original_log.splitlines(), start=1)
            ],
            "source_catalogue": [item.model_dump(mode="json") for item in self.catalogue],
            "lookups": [item.model_dump(mode="json") for item in self.lookups],
            "sources": self.sources,
        }


def _read_files(root: Path) -> dict[str, bytes]:
    root = root.absolute()
    if root.name != "agent-visible" or root.parent.name != "MD-01":
        raise ValueError("Only the MD-01 agent-visible input directory is allowed")
    if root.resolve() != root or not root.is_dir():
        raise ValueError("Fixture directory must exist and cannot use symlinks")
    result = {}
    for filename in AGENT_FILES:
        path = root / filename
        if path.is_symlink() or path.resolve().parent != root or not path.is_file():
            raise ValueError(f"Missing or unsafe fixture source: {filename}")
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError(f"Fixture source exceeds input limit: {filename}")
        result[filename] = path.read_bytes()
        if len(result[filename]) > MAX_INPUT_BYTES:
            raise ValueError(f"Fixture source exceeds input limit: {filename}")
    return result


def load_md01(root: Path | None = None) -> FixtureInputs:
    """Read exact allowed names; never traverse proof/oracle folders or arbitrary paths."""
    root = root or Path(__file__).resolve().parents[3] / "fixtures/MD-01/agent-visible"
    files = _read_files(root)
    return parse_md01_files(files)


def parse_md01_files(files: dict[str, bytes]) -> FixtureInputs:
    """Compatibility name for the shared first-family immutable pack parser."""
    return parse_input_files(files)


def parse_input_files(files: dict[str, bytes]) -> FixtureInputs:
    """Validate saved synthetic packs without tying identities to the MD-01 fixture."""
    if set(files) != set(AGENT_FILES) or any(len(x) > MAX_INPUT_BYTES for x in files.values()):
        raise ValueError("The saved snapshot must contain the exact bounded input files")
    original = files["original-log.txt"].decode("utf-8", errors="strict")
    if not original.strip():
        raise ValueError("Original log must contain nonempty failure evidence")
    data = {name: json.loads(value) for name, value in files.items() if name.endswith(".json")}
    manifest = IntakeManifest.model_validate(data["manifest.json"])
    if hashlib.sha256(files["original-log.txt"]).hexdigest() != manifest.content_sha256:
        raise ValueError("Original source hash differs from the manifest")
    catalogue = [SourceReference.model_validate(item) for item in data["source-catalogue.json"]]
    validate_citations([], catalogue, attempt_id=manifest.attempt_id)
    indexed = {(item.source_id, item.source_version): item for item in catalogue}
    original_source = indexed.get((manifest.source_id, manifest.source_version))
    if (
        original_source is None
        or original_source.kind != "text"
        or original_source.attempt_id != manifest.attempt_id
        or original_source.observed_at != manifest.processing_at
        or original_source.line_count != len(original.splitlines())
    ):
        raise ValueError("Original source catalogue differs from the manifest or line count")

    sources = {name: data[name] for name in RECORD_FILES}
    for name, payload in sources.items():
        if not isinstance(payload, dict) or payload.get("synthetic") is not True:
            raise ValueError(f"Source must be labelled synthetic: {name}")
        reference = indexed.get((payload.get("source_id"), payload.get("source_version")))
        if reference is None or reference.kind != "records":
            raise ValueError(f"Undeclared record source: {name}")
        for field in ("kind", "observed_at", "attempt_id"):
            if field in payload and payload[field] != reference.model_dump(mode="json")[field]:
                # ISO times may use Z or +00:00; compare parsed observation times.
                if (
                    field != "observed_at"
                    or SourceReference.model_validate(
                        {**reference.model_dump(), field: payload[field]}
                    ).observed_at
                    != reference.observed_at
                ):
                    raise ValueError(f"Source metadata differs from its saved catalogue: {name}")
        records = payload.get("records", [payload])
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError(f"Source records must be an array of objects: {name}")
        if name == "mapping-reference.json" and payload.get("absence_audit"):
            records = [
                *records,
                payload["absence_audit"],
                *payload.get("independent_target_records", []),
                *payload.get("unaffected_mapping_records", []),
            ]
        if any(not isinstance(row, dict) for row in records):
            raise ValueError(f"Reference records must be objects: {name}")
        record_ids = [row.get("record_id") for row in records]
        if any(not isinstance(value, str) for value in record_ids) or len(record_ids) != len(
            set(record_ids)
        ):
            raise ValueError(f"Actual source record locators must be distinct strings: {name}")
        if {item.get("record_id") for item in records} != set(reference.record_ids):
            raise ValueError(f"Record citation locators differ from actual source records: {name}")
        if reference.governance is not None:
            review = payload.get("review", payload)
            expected = reference.governance.model_dump(mode="json")
            if any(review.get(field) != value for field, value in expected.items()):
                raise ValueError(f"Reference governance differs from its saved catalogue: {name}")

    posted = sources["source-posting.json"]
    if posted["identity"] != manifest.identity.model_dump(mode="json"):
        raise ValueError("Source posting identity differs from the intake")
    header = posted["records"][0]
    for field, header_field in (
        ("document_number", "source_document_number"),
        ("source_company_code", "source_company_code"),
        ("fiscal_year", "fiscal_year"),
    ):
        supplied = getattr(manifest.identity, field)
        if supplied is not None and header.get(header_field) != supplied:
            raise ValueError("Source posting header differs from the supplied identity")
    lookups = [LookupResponse.model_validate(item) for item in data["target-master-lookup.json"]]
    audit = sources["target-master-query-audit.json"]
    audit_records = {item["lookup_id"]: item for item in audit["records"]}
    if len(audit_records) != len(audit["records"]):
        raise ValueError("Duplicate lookup audit IDs")
    for lookup in lookups:
        if (
            lookup.source.source_id != audit["source_id"]
            or lookup.source.source_version != audit["source_version"]
            or lookup.source.attempt_id != manifest.attempt_id
            or lookup.source.observed_at != manifest.processing_at
        ):
            raise ValueError("Target lookup must belong to this exact failure-time audit source")
        if not source_matches_catalogue(
            lookup.source, indexed.get((lookup.source.source_id, lookup.source.source_version))
        ):
            raise ValueError("Lookup metadata differs from the authorised failure snapshot")
        validate_citations(lookup.citations, catalogue, attempt_id=manifest.attempt_id)
        query = audit_records.get(lookup.lookup_id)
        if query is None or (
            query["query_scope"] != lookup.query_scope
            or query["returned_records"] != lookup.records
            or query["row_count"] != len(lookup.records)
            or (
                lookup.scope_complete
                and any(
                    query[field] is not True
                    for field in (
                        "query_completed",
                        "pagination_exhausted",
                        "authorization_scope_complete",
                        "snapshot_matches_failure_attempt",
                    )
                )
            )
        ):
            raise ValueError("Lookup result differs from its complete query audit")

    mapping = sources["mapping-reference.json"]
    mapping_source = indexed[(mapping["source_id"], mapping["source_version"])]
    if mapping["state"] == "confirmed_absent":
        audit = mapping.get("absence_audit")
        if not isinstance(audit, dict) or (
            audit.get("query_scope") != mapping["query_scope"]
            or audit.get("row_count") != 0
            or audit.get("returned_records") != []
            or mapping_source.attempt_id != manifest.attempt_id
            or mapping_source.observed_at != manifest.processing_at
            or any(
                audit.get(field) is not True
                for field in (
                    "query_completed",
                    "pagination_exhausted",
                    "authorization_scope_complete",
                    "snapshot_matches_failure_attempt",
                )
            )
        ):
            raise ValueError("Mapping absence needs a complete failure-time query audit")
    unaffected = mapping.get("unaffected_mapping_records", [])
    if unaffected:
        known_accounts = {row["source_account"] for row in posted["records"][1:]}
        account = mapping["query_scope"].get("source_account")
        seen_accounts = set()
        for record in unaffected:
            scope = record.get("scope", {})
            source_account = record.get("source_account")
            try:
                effective = date.fromisoformat(record["effective_from"])
                expiry = (
                    date.fromisoformat(record["expires_on"]) if record.get("expires_on") else None
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "Unaffected mapping needs an applicable validity interval"
                ) from exc
            if (
                mapping["state"] != "confirmed_absent"
                or not isinstance(scope, dict)
                or record.get("reference_kind") != "existing_unaffected_mapping"
                or source_account == account
                or source_account not in known_accounts
                or source_account in seen_accounts
                or not isinstance(record.get("target_account"), str)
                or not record["target_account"].strip()
                or any(
                    scope.get(key) != value
                    for key, value in mapping["query_scope"].items()
                    if key != "source_account"
                )
                or record.get("posting_date_in_scope")
                != manifest.business_context.posting_date.isoformat()
                or effective > manifest.business_context.posting_date
                or (expiry is not None and expiry < manifest.business_context.posting_date)
            ):
                raise ValueError("Unaffected mapping must be a distinct scoped source-line record")
            seen_accounts.add(source_account)
    lookups.append(
        LookupResponse(
            lookup_id=mapping.get("lookup_id", "md01-applicable-mapping"),
            state=mapping["state"],
            query_scope=mapping["query_scope"],
            scope_complete=mapping["scope_complete"],
            records=mapping["records"],
            source=mapping_source,
            citations=[
                Citation(
                    source_id=mapping_source.source_id,
                    source_version=mapping_source.source_version,
                    attempt_id=mapping_source.attempt_id,
                    record_id=record_id,
                )
                for record_id in mapping_source.record_ids
                if not mapping.get("absence_audit")
                or record_id == mapping["absence_audit"]["record_id"]
            ],
        )
    )
    independent = mapping.get("independent_target_records", [])
    if independent:
        if any(
            record.get("reference_kind") != "independent_target_design" for record in independent
        ):
            raise ValueError("Independent target reference must declare its distinct provenance")
        lookups.append(
            LookupResponse(
                lookup_id=mapping.get("independent_lookup_id", "independent-target-reference"),
                state="found",
                query_scope=mapping["query_scope"],
                scope_complete=True,
                records=independent,
                source=mapping_source,
                citations=[
                    Citation(
                        source_id=mapping_source.source_id,
                        source_version=mapping_source.source_version,
                        attempt_id=mapping_source.attempt_id,
                        record_id=record["record_id"],
                    )
                    for record in independent
                ],
            )
        )
    playbook = sources["missing-gl-master-playbook.json"]
    guidance = GuidanceVersion.model_validate(
        {name: playbook[name] for name in GuidanceVersion.model_fields}
    )
    if guidance.cause.value not in ("missing_target_gl_master_data", "missing_gl_mapping"):
        raise ValueError("Only the two supported synthetic G/L failure families are accepted")
    declared = {(s.source_id, s.source_version) for s in catalogue}
    used = {(manifest.source_id, manifest.source_version)} | {
        (payload["source_id"], payload["source_version"]) for payload in sources.values()
    }
    if declared != used:
        raise ValueError("Catalogue contains undeclared or missing input sources")
    return FixtureInputs(manifest, original, tuple(catalogue), tuple(lookups), (guidance,), sources)
