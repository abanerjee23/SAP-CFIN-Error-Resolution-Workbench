"""Evaluate saved software observations or a saved operational run in Arize."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx

from cfin.arize_evaluation import (
    ArizeEvaluationError,
    prepare_saved_run_evaluation,
    prepare_software_evaluation,
    upload_evaluation,
    verify_existing_evaluation,
)
from cfin.config import Settings
from cfin.evaluation import AssertionResult, EvalObservation
from cfin.gateway import ServiceGateway


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--software-report", type=Path)
    source.add_argument("--run-id", type=UUID)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--experiment-name")
    destination.add_argument("--verify-experiment-id")
    parser.add_argument("--dataset-id", help="Reuse an exact existing saved-output dataset ID")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.software_report:
            saved = json.loads(args.software_report.read_text())
            observations = []
            for row in saved["results"]:
                row = dict(row)
                row["assertions"] = tuple(AssertionResult(**check) for check in row["assertions"])
                row["errors"] = tuple(row["errors"])
                observations.append(EvalObservation(**row))
            prepared = prepare_software_evaluation(observations)
        else:

            async def read_saved_run() -> list[dict]:
                async with httpx.AsyncClient(timeout=15) as client:
                    return await ServiceGateway(settings, client).rows(
                        "analysis_runs", {"id": f"eq.{args.run_id}"}
                    )

            prepared = prepare_saved_run_evaluation(asyncio.run(read_saved_run()))
        report = (
            verify_existing_evaluation(
                prepared, settings, experiment_id=str(args.verify_experiment_id)
            )
            if args.verify_experiment_id
            else upload_evaluation(
                prepared, settings, experiment_name=args.experiment_name, dataset_id=args.dataset_id
            )
        )
    except ArizeEvaluationError as exc:
        report = {"upload_status": "failed", **exc.diagnostic()}
    except Exception:
        report = {"upload_status": "failed", "error": "Arize evaluation could not complete"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    return 0 if report.get("upload_status") in ("uploaded", "verified_existing") else 1


if __name__ == "__main__":
    raise SystemExit(main())
