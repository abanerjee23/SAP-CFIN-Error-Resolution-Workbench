import json
import sys

from cfin import arize_eval_cli as cli
from cfin.arize_evaluation import ArizeEvaluationError
from cfin.evaluation import evaluate_gates


def invoke(monkeypatch, tmp_path, **arguments):
    source = tmp_path / "saved.json"
    source.write_text(json.dumps({"results": [evaluate_gates("md01-pending").to_dict()]}))
    output = tmp_path / "result.json"
    argv = ["arize-eval", "--software-report", str(source), "--output", str(output)]
    for key, value in arguments.items():
        argv += ["--" + key.replace("_", "-"), value]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(cli, "Settings", lambda: object())
    return output


def test_cli_uploads_saved_software_and_forwards_existing_dataset(monkeypatch, tmp_path):
    output = invoke(monkeypatch, tmp_path, experiment_name="offline", dataset_id="existing")

    def upload(prepared, settings, **kwargs):
        assert prepared.records[0].kind == "software_observation"
        assert kwargs == {"experiment_name": "offline", "dataset_id": "existing"}
        return {"upload_status": "uploaded", "records": 1, "quality_baseline_established": False}

    monkeypatch.setattr(cli, "upload_evaluation", upload)
    assert cli.main() == 0
    assert json.loads(output.read_text())["quality_baseline_established"] is False


def test_cli_readonly_verification_does_not_upload(monkeypatch, tmp_path):
    output = invoke(monkeypatch, tmp_path, verify_experiment_id="existing")
    monkeypatch.setattr(
        cli, "upload_evaluation", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError())
    )
    monkeypatch.setattr(
        cli, "verify_existing_evaluation", lambda *_a, **_k: {"upload_status": "verified_existing"}
    )
    assert cli.main() == 0
    assert json.loads(output.read_text())["upload_status"] == "verified_existing"


def test_cli_preserves_fixed_uncertain_diagnostics_without_raw_sdk_message(
    monkeypatch, tmp_path, capsys
):
    output = invoke(monkeypatch, tmp_path, experiment_name="offline")

    def fail(*_args, **_kwargs):
        raise ArizeEvaluationError(
            "Arize upload unverified",
            phase="experiment_execution",
            exception_class="RuntimeError",
            reason_code="sdk_error",
            outcome_uncertain=True,
        )

    monkeypatch.setattr(cli, "upload_evaluation", fail)
    assert cli.main() == 1
    report = json.loads(output.read_text())
    assert report["phase"] == "experiment_execution" and report["outcome_uncertain"]
    assert "results" not in capsys.readouterr().out
