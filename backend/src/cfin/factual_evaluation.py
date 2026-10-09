"""Evaluator-only factual software checks and pending human semantic review.

This module never dispatches models, publishes cases, approves knowledge or sends
expectations to an agent. Code scores concern bindings and structure, not whether
an LLM understood an error correctly or wrote useful prose.
"""

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from cfin.arize_evaluation import ArizeEvaluationError, EvaluationRecord, PreparedEvaluation
from cfin.evaluation import AssertionResult
from cfin.log_only_contracts import ExecutionBinding, LogAnalysisResult
from cfin.log_only_snapshots import LogInputSnapshot
from cfin.log_only_sources import validate_extraction

FACTUAL_RUBRIC_VERSION = "factual-review-v1"
HISTORY_READER_VERSION = "reviewed-history-reader-v1"
SEMANTIC_DIMENSIONS = (
    "extraction_fidelity",
    "selection_completeness",
    "summary_support",
    "factual_restraint",
    "historical_attribution",
    "reader_usefulness",
)
DEFAULT_EXPECTATIONS = Path(__file__).resolve().parents[3] / "evals/log-only-expectations.json"


def factual_review_checklist() -> list[dict[str, Any]]:
    return [
        {"dimension": dimension, "status": "pending_human_review", "score": None}
        for dimension in SEMANTIC_DIMENSIONS
    ]


def load_factual_expectations(path: Path = DEFAULT_EXPECTATIONS) -> dict[str, Any]:
    """Assessor-only expected answers with exact revision, never agent input."""
    raw = path.read_bytes()
    value = json.loads(raw)
    if (
        value.get("synthetic") is not True
        or not isinstance(value.get("cases"), list)
        or value.get("review_status") not in ("draft_pending_human_review", "human_reviewed")
    ):
        raise ValueError("An explicitly reviewed-or-draft factual expectation corpus is required")
    return {**value, "content_sha256": hashlib.sha256(raw).hexdigest()}


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _binding_matches(run: dict[str, Any], binding: ExecutionBinding) -> bool:
    return (
        all(
            str(run.get(key)) == getattr(binding, key)
            for key in (
                "workspace_id",
                "case_id",
                "attempt_id",
                "input_revision",
            )
        )
        and str(run.get("id")) == binding.run_id
    )


def prepare_factual_run_evaluation(
    runs: list[dict[str, Any]],
    *,
    originals_by_run: dict[str, dict[tuple[str, str], bytes]] | None = None,
) -> PreparedEvaluation:
    """Assess saved factual outputs without applying the legacy diagnostic oracle."""
    records = []
    for run in runs:
        try:
            run_id = str(UUID(run["id"]))
            for key in ("workspace_id", "case_id", "attempt_id"):
                UUID(run[key])
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ArizeEvaluationError("Saved factual run identifiers are required") from exc
        if run.get("evaluation_only") is not True or run.get("workflow_version") != "log-only-v1":
            raise ArizeEvaluationError("Only explicit factual evaluation runs are accepted")
        output = run.get("output") or {}
        if not isinstance(output, dict):
            raise ArizeEvaluationError("Saved factual output must be an object or null")
        result, snapshot = None, None
        try:
            snapshot = LogInputSnapshot.model_validate(run.get("snapshot"))
            binding_valid = _binding_matches(run, snapshot.binding)
        except ValueError:
            binding_valid = False
        raw_result = output.get("result", output)
        try:
            result = LogAnalysisResult.model_validate(
                {
                    key: value
                    for key, value in raw_result.items()
                    if key in LogAnalysisResult.model_fields
                }
            )
            sources = {
                (source.source_id, source.source_version): source
                for source in result.source_manifest.sources
            }
            locators_valid = all(
                (entry.source_id, entry.source_version) in sources
                and entry.source_span.line_end
                <= sources[(entry.source_id, entry.source_version)].readable.line_count
                for entry in (result.extraction.entries if result.extraction else [])
            )
            output_valid = bool(
                locators_valid
                and snapshot
                and result.source_manifest == snapshot.source_manifest
                and _binding_matches(run, result)
                and result.prompt_versions == snapshot.binding.prompt_versions
                and result.model_configuration == snapshot.binding.model_configuration
            )
        except (ValueError, AttributeError):
            output_valid = False
        completed = bool(
            result and result.outcome == "completed" and run.get("state") == "succeeded"
        )
        explicit_failure = bool(
            run.get("state") == "failed"
            and (run.get("error_code") or (result and result.failure_reason))
        )
        saved_history_case_ids = (
            {candidate.case_id for candidate in result.history.candidates} if result else set()
        )
        projection = run.get("history_read_projection") or {}
        saved_history_case_ids.update(projection.get("saved_candidate_case_ids", []))
        excluded_case_ids = {str(value) for value in run.get("excluded_case_ids", [])}
        checks = [
            AssertionResult(
                "factual_snapshot_binding",
                binding_valid,
                "Immutable originals and run/case/attempt/version bindings agree.",
            ),
            AssertionResult(
                "factual_output_contract",
                output_valid,
                "Saved factual schemas and current/history references resolve.",
            ),
            AssertionResult(
                "factual_outcome_honest",
                completed or explicit_failure,
                "Saved outcome is completed or an explicit recorded failure.",
            ),
            AssertionResult(
                "factual_current_case_excluded_from_history",
                bool(result and result.case_id not in saved_history_case_ids),
                "Current-case findings cannot enter historical context.",
            ),
            AssertionResult(
                "factual_held_out_cases_excluded_from_history",
                bool(result and not saved_history_case_ids.intersection(excluded_case_ids)),
                "Held-out evaluation cases cannot enter historical context.",
            ),
        ]
        originals = (originals_by_run or {}).get(run_id)
        if originals is not None:
            try:
                if result is None or result.extraction is None:
                    raise ValueError("No extraction to validate")
                validation = validate_extraction(
                    result.source_manifest, originals, result.extraction
                )
                fidelity_checked = all(
                    item in result.limitations for item in validation.limitations
                )
            except ValueError:
                fidelity_checked = False
            checks.append(
                AssertionResult(
                    "factual_exact_original_quotes",
                    fidelity_checked,
                    "Extracted spans match original bytes and uncovered regions remain limited.",
                )
            )
        record_id = "factual-evaluation:" + run_id
        binding_data = snapshot.binding.model_dump(mode="json") if snapshot else {}
        history_payload = result.history.model_dump(mode="json") if result else {}
        history_sha = hashlib.sha256(_dump(history_payload).encode()).hexdigest()
        review = {
            "rubric_version": FACTUAL_RUBRIC_VERSION,
            "semantic_dimensions": factual_review_checklist(),
            "quality_baseline_established": False,
            "human_review_status": "pending",
            "original_quote_verification": "checked" if originals is not None else "not_loaded",
            "limitation": "Software checks do not establish semantic accuracy or user value.",
        }
        metadata = {
            "provenance": "persisted_factual_model_evaluation_run",
            "evaluation_only": "true",
            "workflow_version": "log-only-v1",
            "rubric_version": FACTUAL_RUBRIC_VERSION,
            "schema_version": str(binding_data.get("schema_version", "unknown")),
            "prompt_versions": _dump(binding_data.get("prompt_versions", {})),
            "model_configuration": _dump(binding_data.get("model_configuration", {})),
            "source_manifest_sha256": str(binding_data.get("source_manifest_sha256", "unknown")),
            "input_revision": str(run.get("input_revision", "unknown")),
            "history_reader_version": HISTORY_READER_VERSION,
            "history_sha256": history_sha,
            "saved_history_sha256": str(projection.get("saved_history_sha256", history_sha)),
            "history_read_projection": str(projection.get("kind", "saved_native_history")),
            "outcome": result.outcome if result else "unavailable",
            "run_id": run_id,
            "case_id": run["case_id"],
            "state": run["state"],
            "human_review_status": "pending",
            "quality_baseline_established": "false",
        }
        records.append(
            EvaluationRecord(
                record_id=record_id,
                kind="persisted_factual_model_evaluation_run",
                input_json=_dump(
                    {
                        "record_id": record_id,
                        "run_id": run_id,
                        "source_manifest_sha256": metadata["source_manifest_sha256"],
                    }
                ),
                output_json=_dump(
                    {
                        "record_id": record_id,
                        "kind": "persisted_factual_model_evaluation_run",
                        "output": output,
                        "human_review": review,
                    }
                ),
                ground_truth_json=None,
                checks=tuple(checks),
                metadata=metadata,
            )
        )
    if not records:
        raise ArizeEvaluationError("At least one saved factual evaluation run is required")
    return PreparedEvaluation(tuple(records))


def factual_human_review_packet(
    runs: list[dict[str, Any]],
    prepared: PreparedEvaluation,
) -> dict[str, Any]:
    """Populate an editable assessor worksheet with saved outputs and exact run bindings.

    Pending fields are deliberately not approvals or zero-error measurements.
    Reviewers inspect the preserved originals and record evidence for each judgement.
    """
    metadata = {record.metadata.get("run_id"): record.metadata for record in prepared.records}
    cases = []
    for run in runs:
        if run.get("workflow_version") != "log-only-v1" or run.get("state") not in (
            "succeeded",
            "failed",
            "historical",
        ):
            continue
        output = run.get("output") or {}
        cases.append(
            {
                "run_id": run["id"],
                "case_id": run["case_id"],
                "versions": metadata.get(run["id"], {}),
                "expectation_case_id": None,
                "source_manifest": output.get(
                    "source_manifest", run.get("snapshot", {}).get("source_manifest")
                ),
                "summary_to_review": output.get("summary"),
                "limitations_to_review": output.get("limitations", []),
                "failure_reason": output.get("failure_reason", run.get("error_code")),
                "reviewer": None,
                "reviewed_at": None,
                "review_status": "pending",
                "dimensions": [
                    {
                        "dimension": dimension,
                        "decision": "pending",
                        "explanation": None,
                        "original_evidence_references": [],
                        "required_corrections": [],
                    }
                    for dimension in SEMANTIC_DIMENSIONS
                ],
                "critical_failure_assessment": "pending",
                "critical_observations": [],
                "user_value_measurements": {
                    "manual_log_reading_minutes": None,
                    "summary_assisted_reading_minutes": None,
                    "essential_facts_missed": None,
                    "corrections_required": None,
                    "comprehension_completed": None,
                },
                "release_decision": "pending",
            }
        )
    return {
        "schema_version": "factual-human-review-v1",
        "rubric_version": FACTUAL_RUBRIC_VERSION,
        "evaluation_only": True,
        "quality_baseline_established": False,
        "instructions": [
            "Bind the case to reviewed expectations before judging semantic completeness.",
            "Inspect all preserved originals, full extraction and selected summary claims.",
            "Record exact source/version/line references for unsupported claims and corrections.",
            "Judge current facts separately from attributed historical findings and human updates.",
            "Use accepted, correction_required or insufficient for each dimension; explain why.",
            "Record actual comprehension time and corrections; leave unmeasured values null.",
            "Pending fields and empty observation lists never establish approval or zero failures.",
            "This worksheet does not publish knowledge or satisfy operational human milestones.",
        ],
        "cases": cases,
    }
