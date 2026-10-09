"""Arize AX native experiments over saved outputs; no provider or judge calls.

Preparation stays offline. The SDK owns experiment tracing and logging. Success
requires independent readback of dataset binding, saved outputs, code scores and
automatically logged task traces. Software checks are not model-quality evidence.
"""

import base64
import json
import logging
import re
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import sleep
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from cfin.config import Settings
from cfin.evaluation import AssertionResult, EvalObservation, assess_observation, load_case_specs


class ArizeEvaluationError(RuntimeError):
    """Public diagnostics never include SDK response bodies or credentials."""

    def __init__(
        self,
        message: str,
        *,
        phase: str = "preparation",
        exception_class: str | None = None,
        reason_code: str | None = None,
        dataset_id: str | None = None,
        experiment_id: str | None = None,
        outcome_uncertain: bool = False,
    ) -> None:
        self.phase, self.exception_class, self.reason_code = phase, exception_class, reason_code
        self.dataset_id = dataset_id if _resource_id(dataset_id) else None
        self.experiment_id = experiment_id if _resource_id(experiment_id) else None
        self.outcome_uncertain = outcome_uncertain
        super().__init__(message)

    def diagnostic(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "phase": self.phase,
            "exception_class": self.exception_class,
            "reason_code": self.reason_code,
            "dataset_id": self.dataset_id,
            "experiment_id": self.experiment_id,
            "outcome_uncertain": self.outcome_uncertain,
        }


def _resource_id(value: Any, kind: str | None = None) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return False
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return False
    return ":" in decoded and (kind is None or decoded.startswith(kind + ":"))


def _exception_class(error: BaseException) -> str:
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) else "Exception"


class _ReadbackError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("Arize saved evaluation readback is unverified")


def _same_json_output(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Nonfinite JSON constant")

    try:

        def canonical(value):
            return _json(
                json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
            )

        return canonical(actual) == canonical(expected)
    except (TypeError, ValueError):
        return False


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class EvaluationRecord:
    record_id: str
    kind: str
    input_json: str
    output_json: str
    ground_truth_json: str | None
    checks: tuple[AssertionResult, ...]
    metadata: dict[str, str]


@dataclass(frozen=True)
class PreparedEvaluation:
    records: tuple[EvaluationRecord, ...]

    def report(self) -> dict[str, Any]:
        checks = [check for record in self.records for check in record.checks]
        return {
            "backend": "arize_code_evaluators",
            "upload_status": "not_uploaded",
            "records": len(self.records),
            "checks_passed": sum(check.passed for check in checks),
            "checks_total": len(checks),
            "local_checks_passed": bool(checks) and all(check.passed for check in checks),
            "quality_baseline_established": False,
            "human_review_status": "pending",
            "provider_calls_during_evaluation": 0,
            "llm_grader_calls_requested": 0,
            "results": [
                {
                    "record_id": record.record_id,
                    "kind": record.kind,
                    "metadata": dict(record.metadata),
                    "checks": [
                        {"name": check.name, "passed": check.passed, "detail": check.detail}
                        for check in record.checks
                    ],
                }
                for record in self.records
            ],
        }


def prepare_software_evaluation(
    observations: Sequence[EvalObservation], *, specs: list[dict[str, Any]] | None = None
) -> PreparedEvaluation:
    """Assess existing software gate/replay observations with the shared evaluator."""
    cases = {item["case_id"]: item for item in (specs if specs is not None else load_case_specs())}
    records = []
    for index, observation in enumerate(observations):
        if (
            observation.mode not in ("gates", "replay")
            or not observation.evaluation_only
            or observation.case_id not in cases
        ):
            raise ArizeEvaluationError("Only saved software evaluation observations are accepted")
        checks = assess_observation(observation, cases[observation.case_id])
        record_id = f"software:{observation.case_id}:{observation.repeat_index}:{index}"
        output = observation.to_dict()
        output.pop("assertions", None)
        metadata = {
            "provenance": "software_observation",
            "case_id": observation.case_id,
            "mode": observation.mode,
            "evaluation_only": "true",
            "human_review_status": "pending",
            "quality_baseline_established": "false",
        }
        records.append(
            EvaluationRecord(
                record_id=record_id,
                kind="software_observation",
                input_json=_json(
                    {"record_id": record_id, "input_fingerprint": observation.input_fingerprint}
                ),
                output_json=_json(
                    {"record_id": record_id, "kind": "software_observation", "output": output}
                ),
                # Only Arize's assessor dataset receives expected answers. They are
                # never placed in the replay input or supplied to any agent/provider.
                ground_truth_json=_json(cases[observation.case_id]["expected"]),
                checks=checks,
                metadata=metadata,
            )
        )
    return _prepared(records)


def prepare_saved_run_evaluation(runs: Sequence[dict[str, Any]]) -> PreparedEvaluation:
    """Show persisted operational failures honestly, without inventing a quality baseline."""
    records = []
    for index, run in enumerate(runs):
        try:
            run_id = str(UUID(run["id"]))
            workspace_id = str(UUID(run["workspace_id"]))
            case_id = str(UUID(run["case_id"]))
            attempt_id = str(UUID(run["attempt_id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ArizeEvaluationError("Saved run identifiers are required") from None
        output = run.get("output")
        if output is not None and not isinstance(output, dict):
            raise ArizeEvaluationError("Saved run output must be an object or null")
        snapshot = run.get("snapshot")
        bound = isinstance(snapshot, dict) and (
            snapshot.get("case_id"),
            snapshot.get("attempt_id"),
        ) == (case_id, attempt_id)
        available = isinstance(output, dict) and any(
            isinstance(output.get(stage), dict) for stage in ("preparation", "diagnosis", "brief")
        )
        completed = run.get("state") == "succeeded" and available and not output.get("errors")
        checks = (
            AssertionResult(
                "saved_snapshot_binding", bound, "Run case and attempt match its saved snapshot."
            ),
            AssertionResult(
                "persisted_output_available", available, "Actual persisted stage output exists."
            ),
            AssertionResult(
                "persisted_run_completed",
                completed,
                "Saved run completed without execution errors.",
            ),
        )
        record_id = f"operational:{run_id}:{index}"
        records.append(
            EvaluationRecord(
                record_id=record_id,
                kind="persisted_operational_run",
                input_json=_json({"record_id": record_id, "run_id": run_id}),
                output_json=_json(
                    {"record_id": record_id, "kind": "persisted_operational_run", "output": output}
                ),
                ground_truth_json=None,
                checks=checks,
                metadata={
                    "provenance": "persisted_operational_run",
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "case_id": case_id,
                    "attempt_id": attempt_id,
                    "state": str(run.get("state", "unknown")),
                    "model_output_available": str(available).lower(),
                    "quality_baseline_established": "false",
                    "human_review_status": "pending",
                },
            )
        )
    return _prepared(records)


def _prepared(records: list[EvaluationRecord]) -> PreparedEvaluation:
    if not records:
        raise ArizeEvaluationError("At least one saved evaluation record is required")
    if len({record.record_id for record in records}) != len(records):
        raise ArizeEvaluationError("Evaluation record identifiers must be unique")
    return PreparedEvaluation(tuple(records))


@dataclass(frozen=True)
class LocalScore:
    score: bool | None
    detail: str

    @property
    def label(self) -> str:
        return "not_applicable" if self.score is None else "passed" if self.score else "failed"


@dataclass(frozen=True)
class EvaluationReceipt:
    dataset_id: str
    experiment_id: str
    trace_project_id: str
    verified: bool
    trace_ids: tuple[str, ...] = ()


class EvaluationRuntime(Protocol):
    def execute(
        self,
        settings: Settings,
        experiment_name: str,
        dataset: list[dict[str, Any]],
        replay: Callable[[Any], str],
        scorers: dict[str, Callable[[str], LocalScore]],
        *,
        dataset_id: str | None = None,
    ) -> EvaluationReceipt: ...


_SDK_LOCK = RLock()


def _configuration_error(settings: Settings) -> str | None:
    if not settings.arize_configured:
        return "not_configured"
    if not _resource_id(settings.arize_space_id, "Space"):
        return "exact_space_id_required"
    # This adapter currently supports the documented default AX service only.
    # Passing a custom REST host while leaving Flight/OTLP on US defaults is unsafe.
    if settings.arize_api_url.rstrip("/") != "https://api.arize.com/v2":
        return "unsupported_api_url"
    return None


def _client(settings: Settings):
    from arize import ArizeClient

    parsed = urlsplit(settings.arize_api_url)
    return ArizeClient(
        api_key=settings.arize_api_key.get_secret_value(),
        api_host=parsed.hostname,
        api_scheme="https",
        api_port=443,
        otlp_host="otlp.arize.com",
        otlp_scheme="https",
        otlp_port=443,
        flight_host="flight.arize.com",
        flight_scheme="grpc+tls",
        flight_port=443,
        request_verify=True,
        enable_caching=False,
        arize_directory=str(Path(__file__).resolve().parents[2] / ".arize"),
    )


@contextmanager
def _redacted_sdk_logs():
    # Pinned SDK logs raw Flight exceptions before rethrowing. Keep its public
    # diagnostics at our fixed boundary; restore all affected logger states.
    names = ("arize.experiments.client", "arize.experiments.functions", "arize._flight.client")
    loggers = [logging.getLogger(name) for name in names]
    previous = [logger.disabled for logger in loggers]
    try:
        for logger in loggers:
            logger.disabled = True
        yield
    finally:
        for logger, disabled in zip(loggers, previous, strict=True):
            logger.disabled = disabled


def _row(value: Any) -> dict[str, Any]:
    # Generated to_dict() omits read-only id/example_id. model_dump retains them;
    # custom run scores are in additional_properties and must be merged explicitly.
    if isinstance(value, dict):
        return dict(value)
    result = value.model_dump(mode="json")
    result.update(result.pop("additional_properties", {}))
    return result


def _verify_binding(experiment: Any, settings: Settings, dataset_id: str) -> dict[str, Any]:
    value = _row(experiment)
    if (
        value.get("space_id") != settings.arize_space_id
        or value.get("dataset_id") != dataset_id
        or not _resource_id(value.get("id"))
        or not isinstance(value.get("dataset_version_id"), str)
        or not _resource_id(value.get("experiment_traces_project_id"))
    ):
        raise _ReadbackError("experiment_binding_mismatch")
    return value


def _saved_examples(client, settings, dataset_id, dataset, *, version_id=None):
    value = _row(client.datasets.get(dataset=dataset_id))
    if value.get("id") != dataset_id or value.get("space_id") != settings.arize_space_id:
        raise _ReadbackError("dataset_binding_mismatch")
    response = client.datasets.list_examples(
        dataset=dataset_id, dataset_version_id=version_id, limit=500, all=False
    )
    if response.pagination.has_more:
        raise _ReadbackError("dataset_incomplete")
    saved = [_row(example) for example in response.examples]
    expected = {json.loads(row["attributes.input.value"])["record_id"]: row for row in dataset}
    if len(saved) != len(expected):
        raise _ReadbackError("dataset_count_mismatch")
    bindings = {}
    for row in saved:
        try:
            record_id = json.loads(row["attributes.input.value"])["record_id"]
            wanted = expected[record_id]
            example_id = row["id"]
            valid = _same_json_output(
                row["attributes.input.value"], wanted["attributes.input.value"]
            )
            if "attributes.output.value" in wanted:
                valid = valid and _same_json_output(
                    row.get("attributes.output.value"), wanted["attributes.output.value"]
                )
            else:
                valid = valid and row.get("attributes.output.value") in (None, "")
            # AX REST examples serialize attributes.metadata as a JSON string;
            # native/Flight rows can expose an object. Preserve exact keys, value
            # types and duplicate-key rejection across that documented boundary.
            metadata = row.get("attributes.metadata")
            valid = (
                valid
                and isinstance(metadata, (dict, str))
                and _same_json_output(
                    _json(metadata) if isinstance(metadata, dict) else metadata,
                    _json(wanted["attributes.metadata"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            raise _ReadbackError("dataset_payload_mismatch") from None
        if not valid or not isinstance(example_id, str) or record_id in bindings.values():
            raise _ReadbackError("dataset_payload_mismatch")
        if example_id in bindings:
            raise _ReadbackError("dataset_duplicate_example")
        bindings[example_id] = record_id
    return bindings


def _score_matches(row, name, score: LocalScore) -> bool:
    actual = row.get(f"eval.{name}.score")
    label = row.get(f"eval.{name}.label")
    applicable = row.get(f"eval.{name}.metadata.applicable")
    expected_applicable = "false" if score.score is None else "true"
    return (
        label == score.label
        and applicable == expected_applicable
        and (
            (actual is None)
            if score.score is None
            else type(actual) in (int, float) and actual == int(score.score)
        )
    )


def _verify_task_trace(client, settings, project_id, trace_id, output, experiment_id):
    if not isinstance(trace_id, str) or not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        raise _ReadbackError("trace_id_missing")
    response = client.traces.list(
        project=project_id,
        space=settings.arize_space_id,
        filter=f"context.trace_id = '{trace_id}'",
        limit=2,
    )
    traces = [_row(value) for value in response.traces]
    if response.pagination.has_more or len(traces) != 1:
        raise _ReadbackError("trace_missing")
    trace = traces[0]
    if trace.get("trace_id") != trace_id or trace.get("spans_truncated") is not False:
        raise _ReadbackError("trace_binding_mismatch")
    roots = [span for span in trace.get("spans", []) if span.get("parent_id") in (None, "")]
    if len(roots) != 1:
        raise _ReadbackError("trace_root_mismatch")
    root = roots[0]
    attributes = root.get("attributes") or {}
    metadata = attributes.get("metadata", attributes.get("attributes.metadata"))
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = None
    saved_output = attributes.get("output.value", attributes.get("attributes.output.value"))
    if (
        root.get("context", {}).get("trace_id") != trace_id
        or root.get("context", {}).get("span_id") != trace.get("root_span_id")
        or root.get("status_code") not in (None, "OK", "UNSET")
        or not isinstance(metadata, dict)
        or metadata.get("experiment_id") != experiment_id
        or not _same_json_output(saved_output, output)
    ):
        raise _ReadbackError("trace_content_mismatch")


def _verify_readback(client, settings, experiment, dataset, outputs, scores):
    dataset_id = _row(experiment)["dataset_id"]
    value = _verify_binding(
        client.experiments.get(experiment=_row(experiment)["id"]), settings, dataset_id
    )
    bindings = _saved_examples(
        client, settings, dataset_id, dataset, version_id=value["dataset_version_id"]
    )
    response = client.experiments.list_runs(experiment=value["id"], limit=500, all=False)
    runs = [_row(run) for run in response.experiment_runs]
    if response.pagination.has_more or len(runs) != len(outputs):
        raise _ReadbackError("run_count_mismatch")
    seen_records, seen_runs, trace_ids = set(), set(), []
    for row in runs:
        record_id = bindings.get(row.get("example_id"))
        run_id = row.get("id")
        if (
            record_id not in outputs
            or record_id in seen_records
            or not isinstance(run_id, str)
            or run_id in seen_runs
        ):
            raise _ReadbackError("run_binding_mismatch")
        if row.get("error") not in (None, "") or not _same_json_output(
            row.get("output"), outputs[record_id]
        ):
            raise _ReadbackError("run_output_mismatch")
        for name, score in scores[record_id].items():
            if not _score_matches(row, name, score):
                raise _ReadbackError("code_score_mismatch")
        # Flight input uses result.trace.id; AX REST run readback names that
        # persisted task reference trace_id. Both denote the actual task trace,
        # never the evaluator trace fields. Conflicting aliases must fail closed.
        trace_id = row.get("trace_id", row.get("result.trace.id"))
        if (
            "trace_id" in row
            and "result.trace.id" in row
            and row["trace_id"] != row["result.trace.id"]
        ):
            raise _ReadbackError("trace_id_alias_conflict")
        if trace_id in trace_ids:
            raise _ReadbackError("duplicate_task_trace")
        _verify_task_trace(
            client,
            settings,
            value["experiment_traces_project_id"],
            trace_id,
            outputs[record_id],
            value["id"],
        )
        trace_ids.append(trace_id)
        seen_records.add(record_id)
        seen_runs.add(run_id)
    return EvaluationReceipt(
        dataset_id, value["id"], value["experiment_traces_project_id"], True, tuple(trace_ids)
    )


class NativeArizeRuntime:
    def execute(self, settings, experiment_name, dataset, replay, scorers, *, dataset_id=None):
        phase = "config"
        experiment_id = None
        try:
            from arize.experiments import EvaluationResult
            from opentelemetry import trace

            with _SDK_LOCK, _redacted_sdk_logs():
                client = _client(settings)
                phase = "dataset_commit"
                if dataset_id is None:
                    created = client.datasets.create(
                        space=settings.arize_space_id,
                        name=f"{experiment_name}-saved-outputs",
                        examples=dataset,
                        force_http=True,
                    )
                    dataset_id = created.id
                if not _resource_id(dataset_id):
                    raise _ReadbackError("exact_dataset_id_required")
                phase = "dataset_preflight"
                _saved_examples(client, settings, dataset_id, dataset)
                outputs, scores = {}, {}

                def saved_output(input):
                    nonlocal experiment_id
                    # The SDK passes only attributes.input.value to this function.
                    # Its automatic parent is observed; no trace/span is created here.
                    span = trace.get_current_span()
                    metadata = (getattr(span, "attributes", None) or {}).get("metadata")
                    if isinstance(metadata, str):
                        candidate = json.loads(metadata).get("experiment_id")
                        if _resource_id(candidate):
                            experiment_id = candidate
                    parsed = json.loads(input) if isinstance(input, str) else input
                    output = replay(parsed)
                    outputs[parsed["record_id"]] = output
                    return output

                def evaluator(name, scorer):
                    def code_check(output):
                        result = scorer(output)
                        record_id = json.loads(output)["record_id"]
                        scores.setdefault(record_id, {})[name] = result
                        return EvaluationResult(
                            score=None if result.score is None else int(result.score),
                            label=result.label,
                            explanation=result.detail,
                            metadata={
                                "applicable": "false" if result.score is None else "true",
                                "source": "saved-output-code-check",
                            },
                        )

                    return code_check

                phase = "experiment_execution"
                experiment, _ = client.experiments.run(
                    name=experiment_name,
                    dataset=dataset_id,
                    space=settings.arize_space_id,
                    task=saved_output,
                    evaluators={name: evaluator(name, scorer) for name, scorer in scorers.items()},
                    concurrency=1,
                    exit_on_error=True,
                    timeout=30,
                    dry_run=False,
                    force_http=False,
                    set_global_tracer_provider=False,
                    metadata={
                        "source": "saved-output-replay",
                        "quality_baseline": "not-established",
                        "human_review_status": "pending",
                    },
                )
                experiment_id = _row(experiment)["id"]
                phase = "server_readback"
                return _read_with_retry(
                    lambda: _verify_readback(client, settings, experiment, dataset, outputs, scores)
                )
        except Exception as error:
            raise ArizeEvaluationError(
                "Arize evaluation upload failed or readback is unverified",
                phase=phase,
                exception_class=_exception_class(error),
                reason_code=error.reason_code if isinstance(error, _ReadbackError) else "sdk_error",
                dataset_id=dataset_id,
                experiment_id=experiment_id,
                outcome_uncertain=phase
                in ("dataset_commit", "experiment_execution", "server_readback"),
            ) from None


def _read_with_retry(read):
    delays = iter((1, 2, 4))
    while True:
        try:
            return read()
        except _ReadbackError as error:
            retryable = {"run_count_mismatch", "trace_missing", "code_score_mismatch"}
            delay = next(delays, None) if error.reason_code in retryable else None
            if delay is None:
                raise
            sleep(delay)


def _dataset(prepared):
    return [
        {
            "attributes.input.value": record.input_json,
            **(
                {"attributes.output.value": record.ground_truth_json}
                if record.ground_truth_json
                else {}
            ),
            "attributes.metadata": dict(record.metadata),
        }
        for record in prepared.records
    ]


def _scores(prepared):
    names = sorted({check.name for record in prepared.records for check in record.checks})
    return {
        record.record_id: {
            name: LocalScore(
                next((check.passed for check in record.checks if check.name == name), None),
                next(
                    (check.detail for check in record.checks if check.name == name),
                    "Not applicable",
                ),
            )
            for name in names
        }
        for record in prepared.records
    }


def upload_evaluation(
    prepared: PreparedEvaluation,
    settings: Settings,
    *,
    experiment_name: str,
    runtime: EvaluationRuntime | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    reason = _configuration_error(settings)
    if reason:
        raise ArizeEvaluationError(
            "Arize evaluation is not configured", phase="config", reason_code=reason
        )
    if not isinstance(experiment_name, str) or not 1 <= len(experiment_name.strip()) <= 120:
        raise ArizeEvaluationError("A bounded Arize experiment name is required")
    if dataset_id is not None and not _resource_id(dataset_id):
        raise ArizeEvaluationError("An exact existing Arize dataset ID is required")
    if not 1 <= len(prepared.records) <= 499:
        raise ArizeEvaluationError("Evaluation is limited to 499 saved records")
    records = {record.record_id: record for record in prepared.records}
    expected_scores = _scores(prepared)
    observed, invalid = set(), []

    def replay(value):
        if not isinstance(value, dict) or value.get("record_id") not in records:
            raise ValueError("Replay input differs from saved record")
        record = records[value["record_id"]]
        if _json(value) != record.input_json:
            raise ValueError("Replay input differs from saved record")
        return record.output_json

    def scorer_for(name):
        def scorer(output):
            try:
                value = json.loads(output)
                record = records[value["record_id"]]
                if not _same_json_output(output, record.output_json):
                    raise ValueError("Changed saved output")
                observed.add((record.record_id, name))
                return expected_scores[record.record_id][name]
            except (KeyError, TypeError, ValueError):
                invalid.append(name)
                return LocalScore(False, "Saved output integrity is unverified")

        return scorer

    names = sorted(next(iter(expected_scores.values())))
    try:
        receipt = (runtime or NativeArizeRuntime()).execute(
            settings,
            experiment_name,
            _dataset(prepared),
            replay,
            {name: scorer_for(name) for name in names},
            dataset_id=dataset_id,
        )
    except ArizeEvaluationError:
        raise
    except Exception as error:
        raise ArizeEvaluationError(
            "Arize evaluation upload failed or readback is unverified",
            phase="experiment_execution",
            exception_class=_exception_class(error),
            reason_code="sdk_error",
            dataset_id=dataset_id,
            outcome_uncertain=True,
        ) from None
    complete = (
        observed == {(record_id, name) for record_id in records for name in names} and not invalid
    )
    report = prepared.report()
    verified = receipt.verified and complete
    report.update(
        upload_status="uploaded" if verified else "unverified_local_metrics",
        native_local_metrics_complete=verified,
        native_local_metrics_passed=verified and report["local_checks_passed"],
        dataset_id=receipt.dataset_id,
        experiment_id=receipt.experiment_id,
        automatic_trace_project_id=receipt.trace_project_id,
        trace_ids=list(receipt.trace_ids),
        automatic_task_traces_verified=verified,
    )
    return report


def verify_existing_evaluation(
    prepared: PreparedEvaluation, settings: Settings, *, experiment_id: str, client=None
) -> dict[str, Any]:
    if _configuration_error(settings) or not _resource_id(experiment_id):
        raise ArizeEvaluationError(
            "Configured Arize and an exact existing experiment ID are required"
        )
    try:
        with _SDK_LOCK, _redacted_sdk_logs():
            client = client or _client(settings)
            experiment = client.experiments.get(experiment=experiment_id)
            receipt = _read_with_retry(
                lambda: _verify_readback(
                    client,
                    settings,
                    experiment,
                    _dataset(prepared),
                    {record.record_id: record.output_json for record in prepared.records},
                    _scores(prepared),
                )
            )
        report = prepared.report()
        report.update(
            upload_status="verified_existing",
            native_local_metrics_complete=True,
            native_local_metrics_passed=report["local_checks_passed"],
            dataset_id=receipt.dataset_id,
            experiment_id=receipt.experiment_id,
            automatic_trace_project_id=receipt.trace_project_id,
            trace_ids=list(receipt.trace_ids),
            automatic_task_traces_verified=True,
        )
        return report
    except Exception as error:
        raise ArizeEvaluationError(
            "Arize existing experiment readback is unverified",
            phase="server_readback",
            exception_class=_exception_class(error),
            reason_code=error.reason_code if isinstance(error, _ReadbackError) else "sdk_error",
            experiment_id=experiment_id,
        ) from None
