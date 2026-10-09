import base64
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from cfin.arize_evaluation import (
    ArizeEvaluationError,
    EvaluationReceipt,
    _dataset,
    _same_json_output,
    prepare_saved_run_evaluation,
    prepare_software_evaluation,
    upload_evaluation,
    verify_existing_evaluation,
)
from cfin.config import Settings
from cfin.evaluation import CASE_IDS, AssertionResult, evaluate_gates


def resource(kind, value=1):
    return base64.b64encode(f"{kind}:{value}:test".encode()).decode()


SPACE, DATASET, EXPERIMENT, PROJECT = map(resource, ("Space", "Dataset", "Experiment", "Project"))


def settings(**changes):
    return Settings(
        _env_file=None,
        **{
            "arize_enabled": True,
            "arize_api_key": SecretStr("fake-test-only-key"),
            "arize_space_id": SPACE,
            **changes,
        },
    )


@pytest.fixture(autouse=True)
def no_readback_wait(monkeypatch):
    monkeypatch.setattr("cfin.arize_evaluation.sleep", lambda _: None)


class FakeRuntime:
    def __init__(self, *, skip=False, tamper=False, verified=True):
        self.skip, self.tamper, self.verified = skip, tamper, verified
        self.dataset, self.outputs = None, []

    def execute(self, settings, name, dataset, replay, scorers, *, dataset_id=None):
        self.dataset = dataset
        for row in dataset:
            value = json.loads(row["attributes.input.value"])
            assert "expected" not in value and "ground_truth" not in value
            output = replay(value)
            self.outputs.append(output)
            if self.tamper:
                output = output.replace('"agent3_eligible":false', '"agent3_eligible":true')
            if not self.skip:
                for scorer in scorers.values():
                    scorer(output)
        return EvaluationReceipt(DATASET, EXPERIMENT, PROJECT, self.verified)


class FakeClient:
    def __init__(self):
        self.rows, self.runs, self.trace_records, self.events = [], [], {}, []
        self.experiment = {
            "id": EXPERIMENT,
            "space_id": SPACE,
            "dataset_id": DATASET,
            "dataset_version_id": "version1",
            "experiment_traces_project_id": PROJECT,
        }
        self.datasets = SimpleNamespace(
            create=self.create_dataset, get=self.get_dataset, list_examples=self.examples
        )
        self.experiments = SimpleNamespace(
            run=self.run, get=lambda **_: self.experiment, list_runs=self.list_runs
        )
        self.traces = SimpleNamespace(list=self.list_traces)
        self.after_run = lambda: None

    def create_dataset(self, **kwargs):
        self.events.append("dataset_create")
        assert kwargs["space"] == SPACE and kwargs["force_http"] is True
        self.rows = [
            {"id": f"example{index}", **deepcopy(row)}
            for index, row in enumerate(kwargs["examples"])
        ]
        return SimpleNamespace(id=DATASET)

    def get_dataset(self, **kwargs):
        assert kwargs["dataset"] == DATASET
        return {"id": DATASET, "space_id": SPACE}

    def examples(self, **kwargs):
        self.events.append("examples_read")
        assert kwargs["all"] is False
        return SimpleNamespace(
            examples=deepcopy(self.rows), pagination=SimpleNamespace(has_more=False)
        )

    def run(self, **kwargs):
        self.events.append("native_run")
        assert kwargs["force_http"] is False  # HTTP path does not log native traces in8.57
        assert kwargs["concurrency"] == 1 and kwargs["exit_on_error"] is True
        assert kwargs["set_global_tracer_provider"] is False and kwargs["dry_run"] is False
        assert list(inspect.signature(kwargs["task"]).parameters) == ["input"]
        from arize.experiments.functions import _bind_task_signature
        from arize.experiments.types import Example

        for index, row in enumerate(self.rows):
            binding = _bind_task_signature(
                inspect.signature(kwargs["task"]), Example(dataset_row=row)
            )
            output = kwargs["task"](*binding.args, **binding.kwargs)
            trace_id = f"{index + 1:032x}"
            run = {
                "id": f"run{index}",
                "example_id": row["id"],
                "output": output,
                "error": None,
                "result.trace.id": trace_id,
            }
            for name, evaluator in kwargs["evaluators"].items():
                result = evaluator(output)
                run.update(
                    {
                        f"eval.{name}.score": result.score,
                        f"eval.{name}.label": result.label,
                        f"eval.{name}.metadata.applicable": result.metadata["applicable"],
                    }
                )
            self.runs.append(run)
            self.trace_records[trace_id] = {
                "trace_id": trace_id,
                "root_span_id": "0123456789abcdef",
                "spans_truncated": False,
                "spans": [
                    {
                        "parent_id": None,
                        "context": {"trace_id": trace_id, "span_id": "0123456789abcdef"},
                        "status_code": "OK",
                        "attributes": {
                            "output.value": output,
                            "metadata": json.dumps({"experiment_id": EXPERIMENT}),
                        },
                    }
                ],
            }
        self.after_run()
        return self.experiment, None

    def list_runs(self, **kwargs):
        self.events.append("runs_read")
        assert kwargs["experiment"] == EXPERIMENT and kwargs["all"] is False
        return SimpleNamespace(
            experiment_runs=deepcopy(self.runs), pagination=SimpleNamespace(has_more=False)
        )

    def list_traces(self, **kwargs):
        self.events.append("traces_read")
        assert kwargs["project"] == PROJECT and kwargs["space"] == SPACE
        trace_id = kwargs["filter"].split("'")[1]
        assert kwargs["filter"] == f"context.trace_id = '{trace_id}'"
        row = self.trace_records.get(trace_id)
        return SimpleNamespace(
            traces=[deepcopy(row)] if row else [], pagination=SimpleNamespace(has_more=False)
        )


def prepared(case_ids=CASE_IDS):
    return prepare_software_evaluation([evaluate_gates(case_id) for case_id in case_ids])


def test_twelve_saved_software_cases_reassessed_without_answer_or_agent_input():
    runtime = FakeRuntime()
    report = upload_evaluation(prepared(), settings(), experiment_name="software", runtime=runtime)
    assert report["records"] == 12
    assert report["checks_total"] == report["checks_passed"] == 96
    assert report["native_local_metrics_complete"] and report["native_local_metrics_passed"]
    assert not report["quality_baseline_established"]
    assert report["human_review_status"] == "pending"
    assert report["provider_calls_during_evaluation"] == report["llm_grader_calls_requested"] == 0
    assert all("attributes.output.value" in row for row in runtime.dataset)
    assert all("assertions" not in json.loads(row)["output"] for row in runtime.outputs)


def test_native_sdk_run_and_independent_readback_use_automatic_traces(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    report = upload_evaluation(prepared(), settings(), experiment_name="native-software")
    assert report["upload_status"] == "uploaded"
    assert len(report["trace_ids"]) == 12 and report["automatic_task_traces_verified"]
    assert client.events[:3] == ["dataset_create", "examples_read", "native_run"]
    assert client.events.count("native_run") == client.events.count("dataset_create") == 1
    assert client.events.count("traces_read") == 12


def test_ax_rest_persisted_trace_id_alias_uses_actual_task_reference(monkeypatch):
    client = FakeClient()

    def rest_names():
        for run in client.runs:
            run["trace_id"] = run.pop("result.trace.id")

    client.after_run = rest_names
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    report = upload_evaluation(prepared(("md01-pending",)), settings(), experiment_name="rest")
    assert report["upload_status"] == "uploaded"
    assert report["trace_ids"] == [client.runs[0]["trace_id"]]


def test_conflicting_task_trace_id_aliases_cannot_substitute_evaluator_trace(monkeypatch):
    client = FakeClient()
    client.after_run = lambda: client.runs[0].update(trace_id="f" * 32)
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    with pytest.raises(ArizeEvaluationError) as error:
        upload_evaluation(prepared(("md01-pending",)), settings(), experiment_name="conflict")
    assert error.value.reason_code == "trace_id_alias_conflict"


@pytest.mark.parametrize(
    "runtime", [FakeRuntime(skip=True), FakeRuntime(tamper=True), FakeRuntime(verified=False)]
)
def test_skipped_changed_or_unread_results_never_claim_pass(runtime):
    report = upload_evaluation(
        prepared(("md01-pending",)), settings(), experiment_name="unverified", runtime=runtime
    )
    assert report["upload_status"] == "unverified_local_metrics"
    assert not report["native_local_metrics_passed"]


@pytest.mark.parametrize(
    "change", ["score", "output", "trace", "scope", "duplicate", "label", "applicable"]
)
def test_native_tampered_server_results_fail_closed_without_retrying_writes(monkeypatch, change):
    client = FakeClient()

    def tamper():
        if change == "score":
            client.runs[0]["eval.source_fidelity.score"] = 0.2
        if change == "output":
            client.runs[0]["output"] = "{}"
        if change == "trace":
            client.trace_records.clear()
        if change == "scope":
            client.experiment["space_id"] = resource("Space", 2)
        if change == "duplicate":
            client.runs.append(client.runs[0])
        if change == "label":
            client.runs[0]["eval.source_fidelity.label"] = "failed"
        if change == "applicable":
            client.runs[0]["eval.source_fidelity.metadata.applicable"] = "false"

    client.after_run = tamper
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    with pytest.raises(ArizeEvaluationError) as error:
        upload_evaluation(prepared(("md01-pending",)), settings(), experiment_name="tampered")
    assert error.value.phase == "server_readback" and error.value.outcome_uncertain
    assert error.value.dataset_id == DATASET and error.value.experiment_id == EXPERIMENT
    assert client.events.count("native_run") == client.events.count("dataset_create") == 1


def test_software_supplied_passes_are_not_trusted_and_live_cannot_be_mislabeled():
    observation = replace(
        evaluate_gates("md01-pending"),
        answer_boundary_preserved=False,
        assertions=(AssertionResult("answer_separation", True, "claim"),),
    )
    report = prepared_from_observation = prepare_software_evaluation([observation]).report()
    assert not prepared_from_observation["local_checks_passed"]
    assert (
        next(c for c in report["results"][0]["checks"] if c["name"] == "answer_separation")[
            "passed"
        ]
        is False
    )
    with pytest.raises(ArizeEvaluationError):
        prepare_software_evaluation([replace(observation, mode="live")])


def test_failed_saved_operational_run_remains_zero_quality_failure_evidence():
    identifier = "00000000-0000-4000-8000-000000000001"
    run = {
        "id": identifier,
        "workspace_id": identifier,
        "case_id": identifier,
        "attempt_id": identifier,
        "state": "failed",
        "output": None,
        "snapshot": {"case_id": identifier, "attempt_id": identifier},
    }
    runtime = FakeRuntime()
    report = upload_evaluation(
        prepare_saved_run_evaluation([run]), settings(), experiment_name="failed", runtime=runtime
    )
    assert not report["native_local_metrics_passed"] and not report["quality_baseline_established"]
    assert "attributes.output.value" not in runtime.dataset[0]
    assert json.loads(runtime.outputs[0])["output"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"arize_enabled": False},
        {"arize_space_id": "Default Space"},
        {"arize_api_url": "https://foreign.example/v2"},
    ],
)
def test_disabled_name_resolution_or_custom_rest_only_config_block_before_sdk(monkeypatch, changes):
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: pytest.fail("SDK constructed"))
    with pytest.raises(ArizeEvaluationError):
        upload_evaluation(
            prepared(("md01-pending",)), settings(**changes), experiment_name="disabled"
        )


def test_sdk_exception_messages_are_redacted_and_unknown_outcome_blocks_false_success(monkeypatch):
    client = FakeClient()

    def failure(**kwargs):
        raise RuntimeError("fake-key SECRET raw-response-body")

    client.experiments.run = failure
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    with pytest.raises(ArizeEvaluationError) as error:
        upload_evaluation(prepared(("md01-pending",)), settings(), experiment_name="failed")
    assert "SECRET" not in str(error.value) and "SECRET" not in str(error.value.diagnostic())
    assert error.value.exception_class == "RuntimeError" and error.value.outcome_uncertain
    assert error.value.dataset_id == DATASET


def test_existing_experiment_verification_is_read_only_and_does_not_replay(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    original = prepared(("md01-pending",))
    upload_evaluation(original, settings(), experiment_name="initial")
    client.events.clear()
    report = verify_existing_evaluation(
        original, settings(), experiment_id=EXPERIMENT, client=client
    )
    assert report["upload_status"] == "verified_existing"
    assert "native_run" not in client.events and "dataset_create" not in client.events


def test_existing_dataset_reuse_checks_exact_inputs_before_native_run(monkeypatch):
    client = FakeClient()
    original = prepared(("md01-pending",))
    client.rows = [{"id": "example0", **_dataset(original)[0]}]
    client.rows[0]["attributes.output.value"] = "{}"
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    with pytest.raises(ArizeEvaluationError) as error:
        upload_evaluation(original, settings(), experiment_name="reuse", dataset_id=DATASET)
    assert error.value.reason_code == "dataset_payload_mismatch"
    assert "native_run" not in client.events and "dataset_create" not in client.events


def test_existing_dataset_ax_rest_metadata_string_preserves_exact_values(monkeypatch):
    client = FakeClient()
    original = prepared(("md01-pending",))
    row = _dataset(original)[0]
    row["attributes.metadata"] = json.dumps(row["attributes.metadata"])
    client.rows = [{"id": "example0", **row}]
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    report = upload_evaluation(original, settings(), experiment_name="reuse", dataset_id=DATASET)
    assert report["upload_status"] == "uploaded"
    assert "dataset_create" not in client.events


@pytest.mark.parametrize("tamper", ["changed_value", "boolean_coercion", "duplicate_key"])
def test_ax_rest_metadata_string_cannot_relax_values_types_or_unique_keys(monkeypatch, tamper):
    client = FakeClient()
    original = prepared(("md01-pending",))
    row = _dataset(original)[0]
    metadata = row["attributes.metadata"]
    if tamper == "changed_value":
        metadata["human_review_status"] = "approved"
    elif tamper == "boolean_coercion":
        metadata["evaluation_only"] = True
    text = json.dumps(metadata)
    if tamper == "duplicate_key":
        text = text[:-1] + ', "human_review_status": "pending"}'
    row["attributes.metadata"] = text
    client.rows = [{"id": "example0", **row}]
    monkeypatch.setattr("cfin.arize_evaluation._client", lambda _: client)
    with pytest.raises(ArizeEvaluationError) as error:
        upload_evaluation(original, settings(), experiment_name="reuse", dataset_id=DATASET)
    assert error.value.reason_code == "dataset_payload_mismatch"
    assert "native_run" not in client.events and "dataset_create" not in client.events


@pytest.mark.parametrize(
    "actual,accepted",
    [
        ('{ "count": 1, "passed": true }', True),
        ('{"count":1.0,"passed":true}', False),
        ('{"count":1,"passed":1}', False),
        ('{"count":1,"count":1,"passed":true}', False),
        ('{"count":NaN,"passed":true}', False),
    ],
)
def test_json_readback_preserves_exact_values_types_and_unique_keys(actual, accepted):
    assert _same_json_output(actual, '{"count":1,"passed":true}') is accepted
