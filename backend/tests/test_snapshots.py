"""Restore boundary checks using preserved bytes and the actual SQL snapshot shape."""

import asyncio
import copy
from pathlib import Path
from typing import cast

import pytest

from cfin import fixture_loader
from cfin.gateway import ServiceGateway
from cfin.snapshots import restore_inputs

WORKSPACE = "22222222-2222-4222-8222-222222222222"
CASE = "33333333-3333-4333-8333-333333333333"
ATTEMPT = "44444444-4444-4444-8444-444444444444"
OTHER = "99999999-9999-4999-8999-999999999999"


class SavedBytes:
    """In-memory downloads only; no credentials, network or local restore fallback."""

    def __init__(self, files):
        self.files = files
        self.downloaded = []

    async def download(self, evidence):
        name = evidence["filename"]
        self.downloaded.append(name)
        return self.files[name]


@pytest.fixture
def saved_snapshot(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "fixtures/MD-01/agent-visible"
    files = fixture_loader._read_files(root)
    manifest = fixture_loader.parse_md01_files(files).manifest.model_dump(mode="json")
    manifest["identity"]["workspace_id"] = WORKSPACE
    manifest["delivery_key"] = "user-chosen-delivery-20261001"
    snapshot = {
        "manifest": manifest,
        "identity": copy.deepcopy(manifest["identity"]),
        "business_context": copy.deepcopy(manifest["business_context"]),
        "case_id": CASE,
        "attempt_id": ATTEMPT,
        "input_revision": 1,
        "attempt": {
            "id": ATTEMPT,
            "workspace_id": WORKSPACE,
            "case_id": CASE,
            "attempt_key": manifest["attempt_id"],
            "processing_at": "2026-09-30T09:00:00+00:00",
            "processing_order": manifest["processing_order"],
            "result": "failed",
            "validation_status": "pending",
        },
        "sources": [
            {
                "evidence": {
                    "filename": name,
                    "kind": "original_log" if name == "original-log.txt" else "reference",
                },
                "review": None,
            }
            for name in fixture_loader.AGENT_FILES
        ],
    }

    def no_local_restore(*args, **kwargs):
        pytest.fail("Restoring a saved snapshot must not reload local fixture bytes")

    monkeypatch.setattr(fixture_loader, "_read_files", no_local_restore)
    return snapshot, SavedBytes(files)


def restore(saved_snapshot):
    snapshot, cloud = saved_snapshot
    return asyncio.run(restore_inputs(snapshot, cast(ServiceGateway, cloud)))


def test_restores_canonical_intake_without_mutating_preserved_inputs(saved_snapshot):
    snapshot, cloud = saved_snapshot
    before = copy.deepcopy(snapshot)
    inputs = restore(saved_snapshot)

    assert inputs.manifest.model_dump(mode="json") == snapshot["manifest"]
    assert inputs.manifest.identity.workspace_id == WORKSPACE
    assert inputs.manifest.identity.document_number == "0000123456"
    assert inputs.manifest.delivery_key == "user-chosen-delivery-20261001"
    assert cloud.downloaded == list(fixture_loader.AGENT_FILES)
    assert snapshot == before


def test_accepts_equivalent_aware_processing_instants(saved_snapshot):
    snapshot, _ = saved_snapshot
    snapshot["manifest"]["processing_at"] = "2026-09-30T10:00:00+01:00"
    snapshot["attempt"]["processing_at"] = "2026-09-30T09:00:00+00:00"

    assert restore(saved_snapshot).manifest.processing_at.isoformat() == "2026-09-30T10:00:00+01:00"


@pytest.mark.parametrize("missing", [True, False])
def test_requires_saved_canonical_manifest(saved_snapshot, missing):
    snapshot, _ = saved_snapshot
    if missing:
        del snapshot["manifest"]
    else:
        snapshot["manifest"] = None

    with pytest.raises(ValueError):
        restore(saved_snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scenario_id", "MD-02"),
        ("source_id", "different-log"),
        ("source_version", "2"),
        ("content_sha256", "0" * 64),
        ("attempt_id", "MD01-0002"),
        ("processing_at", "2026-09-30T09:01:00Z"),
        ("processing_order", 2),
        ("synthetic", False),
    ],
)
def test_rejects_canonical_manifest_changes_to_preserved_fields(saved_snapshot, field, value):
    snapshot, _ = saved_snapshot
    snapshot["manifest"][field] = value

    with pytest.raises(ValueError):
        restore(saved_snapshot)


@pytest.mark.parametrize("section", ["identity", "business_context"])
def test_rejects_canonical_manifest_differing_from_case(saved_snapshot, section):
    snapshot, _ = saved_snapshot
    if section == "identity":
        snapshot["manifest"][section]["workspace_id"] = OTHER
    else:
        snapshot["manifest"][section]["source_account"] = "0000400001"

    with pytest.raises(ValueError, match="Saved intake manifest"):
        restore(saved_snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt_key", "MD01-0002"),
        ("processing_at", "2026-09-30T09:01:00Z"),
        ("processing_at", "2026-09-30T09:00:00"),
        ("processing_order", 2),
        ("processing_order", None),
        ("processing_order", True),
        ("processing_order", "1"),
        ("processing_order", 1.0),
    ],
)
def test_rejects_snapshot_attempt_differing_from_intake(saved_snapshot, field, value):
    snapshot, _ = saved_snapshot
    snapshot["attempt"][field] = value

    with pytest.raises(ValueError):
        restore(saved_snapshot)


@pytest.mark.parametrize("field", ["processing_at", "processing_order"])
def test_rejects_matching_saved_manifest_and_attempt_that_differ_from_bytes(saved_snapshot, field):
    snapshot, _ = saved_snapshot
    value = "2026-09-30T09:01:00Z" if field == "processing_at" else 2
    snapshot["manifest"][field] = value
    snapshot["attempt"][field] = value

    with pytest.raises(ValueError, match="immutable input"):
        restore(saved_snapshot)


@pytest.mark.parametrize("field", ["processing_at", "processing_order"])
def test_requires_immutable_attempt_metadata(saved_snapshot, field):
    snapshot, _ = saved_snapshot
    del snapshot["attempt"][field]

    with pytest.raises(ValueError):
        restore(saved_snapshot)


@pytest.mark.parametrize("field", ["id", "case_id", "workspace_id"])
def test_rejects_attempt_from_another_snapshot_scope(saved_snapshot, field):
    snapshot, _ = saved_snapshot
    snapshot["attempt"][field] = OTHER

    with pytest.raises(ValueError, match="different case or workspace"):
        restore(saved_snapshot)
