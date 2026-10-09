"""Draft restoration boundary tests; no claim of migrated SQL compatibility."""

import asyncio
import copy
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import HTTPException

from cfin.gateway import ServiceGateway
from cfin.log_only_contracts import ExecutionBinding, LogSourceManifest
from cfin.log_only_inputs import MAX_LOG_BYTES, MAX_LOG_LINES, OriginalUpload, prepare_log_inputs
from cfin.log_only_prompts import LOG_PROMPT_VERSIONS
from cfin.log_only_snapshots import LogInputSnapshot, restore_log_inputs
from cfin.log_only_sources import build_log_source, manifest_fingerprint


class SavedBytes:
    def __init__(self, files):
        self.files = files
        self.downloads = []
        self.error = None

    async def download(self, evidence):
        self.downloads.append(evidence)
        if self.error:
            raise self.error
        return self.files[evidence["object_path"]]


def snapshot_for(raws=(b"Client=010\r\nError\r\n", b"Item=0001\nUnknown field\n")):
    inputs = prepare_log_inputs(
        [OriginalUpload(f"view-{i}.txt", raw) for i, raw in enumerate(raws)],
        provenance="synthetic",
        intake_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    binding = ExecutionBinding(
        workspace_id="workspace-1",
        run_id="run-1",
        case_id="case-1",
        attempt_id="attempt-1",
        input_revision="revision-1",
        source_manifest_sha256=manifest_fingerprint(inputs.manifest),
        prompt_versions=LOG_PROMPT_VERSIONS,
        model_configuration={
            "agent1": "gpt-6-luna",
            "agent2": "gpt-6.1-sol",
            "agent3": "gpt-6.1-sol",
            "reasoning_effort": "medium",
        },
    )
    refs = []
    files = {}
    for index, source in enumerate(inputs.manifest.sources):
        path = f"workspace-1/object-{index}/{source.original_filename}"
        files[path] = inputs.originals[(source.source_id, source.source_version)]
        refs.append(
            {
                "id": f"evidence-{index}",
                "workspace_id": binding.workspace_id,
                "case_id": binding.case_id,
                "attempt_id": binding.attempt_id,
                "source_id": source.source_id,
                "source_version": source.source_version,
                "filename": source.original_filename,
                "object_path": path,
                "sha256": source.content_sha256,
                "byte_size": source.byte_size,
                "provenance": source.provenance,
            }
        )
    snapshot = LogInputSnapshot(
        snapshot_version="log-only-snapshot-draft-v1",
        binding=binding,
        source_manifest=inputs.manifest,
        sources=refs,
    )
    return snapshot.model_dump(mode="json"), binding, SavedBytes(files), inputs


def restore(snapshot, binding, cloud):
    return asyncio.run(
        restore_log_inputs(snapshot, cast(ServiceGateway, cloud), expected_binding=binding)
    )


def test_exact_multisource_restore_has_no_sap_identity_requirement_or_local_fallback(monkeypatch):
    snapshot, binding, cloud, expected = snapshot_for()
    before = copy.deepcopy(snapshot)

    def no_files(*args, **kwargs):
        pytest.fail("Snapshot restoration must not read repository fixtures or local originals")

    monkeypatch.setattr(Path, "read_bytes", no_files)
    monkeypatch.setattr(Path, "read_text", no_files)
    actual = restore(snapshot, binding, cloud)
    assert actual == expected
    assert snapshot == before
    assert list(actual.originals.values()) == [
        b"Client=010\r\nError\r\n",
        b"Item=0001\nUnknown field\n",
    ]
    assert [row["id"] for row in cloud.downloads] == ["evidence-0", "evidence-1"]
    assert all(row["kind"] == "original_log" for row in cloud.downloads)
    assert (
        not {"identity", "business_context", "processing_at", "processing_order"} & snapshot.keys()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "workspace-2"),
        ("case_id", "case-2"),
        ("attempt_id", "attempt-2"),
        ("run_id", "run-2"),
        ("input_revision", "revision-2"),
        ("source_manifest_sha256", "a" * 64),
        ("prompt_versions", {**LOG_PROMPT_VERSIONS, "agent1": "older-extraction"}),
    ],
)
def test_independently_expected_binding_rejects_other_scope_before_download(field, value):
    snapshot, binding, cloud, _ = snapshot_for()
    changed = ExecutionBinding.model_validate({**binding.model_dump(), field: value})
    with pytest.raises(ValueError, match="independently authorised"):
        restore(snapshot, changed, cloud)
    assert cloud.downloads == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "workspace-2"),
        ("case_id", "case-2"),
        ("attempt_id", "attempt-2"),
        ("source_id", "unregistered"),
        ("source_version", "other-version"),
        ("filename", "other.txt"),
        ("sha256", "a" * 64),
        ("byte_size", 42),
        ("provenance", "user_supplied"),
        ("kind", "proof"),
        ("bucket_id", "other"),
        ("content_type", "application/pdf"),
        ("object_path", "workspace-2/object/view-1.txt"),
        ("object_path", "workspace-1/../view-1.txt"),
        ("object_path", "workspace-1/object/../view-1.txt"),
    ],
)
def test_any_bad_reference_is_rejected_before_even_the_first_download(field, value):
    snapshot, binding, cloud, _ = snapshot_for()
    snapshot["sources"][1][field] = value
    with pytest.raises(ValueError):
        restore(snapshot, binding, cloud)
    assert cloud.downloads == []


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate_id", "duplicate_path", "order"])
def test_snapshot_requires_exact_unique_ordered_source_references(change):
    snapshot, binding, cloud, _ = snapshot_for()
    if change == "missing":
        snapshot["sources"].pop()
    elif change == "extra":
        snapshot["sources"].append(copy.deepcopy(snapshot["sources"][0]))
    elif change == "duplicate_id":
        snapshot["sources"][1]["id"] = snapshot["sources"][0]["id"]
    elif change == "duplicate_path":
        snapshot["sources"][1]["filename"] = snapshot["sources"][0]["filename"]
        snapshot["sources"][1]["object_path"] = snapshot["sources"][0]["object_path"]
    else:
        snapshot["sources"].reverse()
    with pytest.raises(ValueError):
        restore(snapshot, binding, cloud)
    assert cloud.downloads == []


def test_altered_manifest_cannot_be_paired_with_original_execution_binding():
    snapshot, binding, cloud, _ = snapshot_for()
    snapshot["source_manifest"]["sources"][0]["readable"]["line_count"] = 3
    with pytest.raises(ValueError, match="manifest differs"):
        restore(snapshot, binding, cloud)
    assert cloud.downloads == []


def test_changed_saved_bytes_fail_and_no_next_original_is_downloaded():
    snapshot, binding, cloud, _ = snapshot_for()
    first_path = snapshot["sources"][0]["object_path"]
    cloud.files[first_path] = cloud.files[first_path].replace(b"010", b"011")
    with pytest.raises(ValueError, match="bytes or readable metadata"):
        restore(snapshot, binding, cloud)
    assert len(cloud.downloads) == 1


def test_denied_storage_access_is_propagated_without_fallback():
    snapshot, binding, cloud, _ = snapshot_for()
    cloud.error = HTTPException(403, "Access denied")
    with pytest.raises(HTTPException) as error:
        restore(snapshot, binding, cloud)
    assert error.value.status_code == 403
    assert len(cloud.downloads) == 1


def test_model_instance_does_not_bypass_snapshot_revalidation():
    snapshot, binding, cloud, _ = snapshot_for()
    model = LogInputSnapshot.model_validate(snapshot)
    altered = model.sources[-1].model_copy(update={"case_id": "another-case"})
    model = model.model_copy(update={"sources": (model.sources[0], altered)})
    with pytest.raises(ValueError, match="another workspace, case or attempt"):
        restore(model, binding, cloud)
    assert cloud.downloads == []


@pytest.mark.parametrize("raw", [b"x" * (MAX_LOG_BYTES + 1), b"x\n" * (MAX_LOG_LINES + 1)])
def test_unsupported_snapshot_capacity_is_rejected_before_storage_access(raw):
    snapshot, binding, cloud, _ = snapshot_for((b"Original",))
    original = snapshot["source_manifest"]["sources"][0]
    source = build_log_source(
        source_id=original["source_id"],
        source_version=original["source_version"],
        original_filename=original["original_filename"],
        raw=raw,
        provenance="synthetic",
    )
    manifest = LogSourceManifest(sources=(source,))
    snapshot["source_manifest"] = manifest.model_dump(mode="json")
    snapshot["binding"]["source_manifest_sha256"] = manifest_fingerprint(manifest)
    snapshot["sources"][0].update(sha256=source.content_sha256, byte_size=source.byte_size)
    expected = ExecutionBinding.model_validate(snapshot["binding"])
    with pytest.raises(ValueError, match="envelope"):
        restore(snapshot, expected, cloud)
    assert cloud.downloads == []


def test_draft_version_is_explicit_and_unknown_fields_cannot_smuggle_sidecars():
    snapshot, binding, cloud, _ = snapshot_for()
    assert snapshot["snapshot_version"] == "log-only-snapshot-draft-v1"
    snapshot["reference_pack"] = {"mapping-reference.json": "legacy data"}
    with pytest.raises(ValueError, match="Extra inputs"):
        restore(snapshot, binding, cloud)
    assert cloud.downloads == []


@pytest.mark.parametrize("version", [None, "legacy-v1", "log-only-snapshot-v2"])
def test_missing_or_incompatible_snapshot_version_is_not_inferred(version):
    snapshot, binding, cloud, _ = snapshot_for()
    if version is None:
        del snapshot["snapshot_version"]
    else:
        snapshot["snapshot_version"] = version
    with pytest.raises(ValueError):
        restore(snapshot, binding, cloud)
    assert cloud.downloads == []
