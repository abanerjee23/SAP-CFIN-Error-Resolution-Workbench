"""Explicit queue/status/export CLI; never calls a provider or bypasses worker budgets."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import httpx

from cfin.config import Settings
from cfin.gateway import UserGateway
from cfin.live_evaluations import (
    EvaluationRequest,
    evaluation_status,
    prepare_model_evaluation,
    queue_evaluations,
    saved_evaluation_report,
    saved_model_runs,
)


async def execute(args):
    token = os.environ.get("CFIN_AUTH_TOKEN", "")
    if not token:
        raise ValueError("Set CFIN_AUTH_TOKEN locally with your signed-in session; do not paste it")
    settings = Settings()
    async with httpx.AsyncClient(timeout=30) as client:
        user = UserGateway(settings, client)
        actor = await user.actor(token)
        if args.queue:
            body = EvaluationRequest(
                workspace_id=args.workspace_id,
                case_ids=args.case_id,
                repeats=args.repeats,
                reason=args.reason,
                reasoning_effort=args.reasoning_effort,
                models={
                    k: v for k, v in {
                        "agent1": args.model_agent1, "agent2": args.model_agent2,
                        "agent3": args.model_agent3,
                    }.items() if v
                } or None,
            )
            result = await queue_evaluations(user, settings, token, actor, body)
        elif (
            args.export_saved_runs or args.arize_experiment_name or args.verify_arize_experiment_id
        ):
            batch, runs, calls = await saved_model_runs(
                user, token, actor, args.workspace_id, args.batch_id,
            )
            prepared = prepare_model_evaluation(runs)
            result = saved_evaluation_report(batch, runs, prepared, calls)
            if args.arize_experiment_name or args.verify_arize_experiment_id:
                from cfin.arize_evaluation import (
                    ArizeEvaluationError,
                    upload_evaluation,
                    verify_existing_evaluation,
                )

                try:
                    result["arize"] = (
                        verify_existing_evaluation(
                            prepared, settings, experiment_id=args.verify_arize_experiment_id,
                        ) if args.verify_arize_experiment_id else upload_evaluation(
                            prepared, settings, experiment_name=args.arize_experiment_name,
                            dataset_id=args.arize_dataset_id,
                        )
                    )
                except ArizeEvaluationError as exc:
                    result["arize"] = {"upload_status": "failed", **exc.diagnostic()}
        else:
            result = await evaluation_status(
                user, token, actor, args.workspace_id,
                page=args.page, page_size=args.page_size, batch_id=args.batch_id,
            )
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {
                    "queued": bool(args.queue),
                    "batches": 1 if result.get("batch") else len(result.get("batches", [])),
                    "output_saved": bool(args.output),
                    "provider_calls_this_command": 0,
                    "judge_calls_this_command": 0,
                    "arize_status": result.get("arize", {}).get("upload_status"),
                    "quality_baseline_established": False,
                }
            )
        )
        return 1 if result.get("arize", {}).get("upload_status") == "failed" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--case-id", type=UUID, action="append", default=[])
    parser.add_argument("--batch-id", type=UUID)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--reason", default="Requested baseline evaluation")
    parser.add_argument("--output")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--model-agent1")
    parser.add_argument("--model-agent2")
    parser.add_argument("--model-agent3")
    parser.add_argument("--export-saved-runs", action="store_true")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--arize-experiment-name")
    destination.add_argument("--verify-arize-experiment-id")
    parser.add_argument("--arize-dataset-id")
    args = parser.parse_args()
    exporting = bool(
        args.export_saved_runs or args.arize_experiment_name or args.verify_arize_experiment_id
    )
    if exporting and (args.queue or not args.batch_id or not args.output):
        parser.error("Saved-run export requires --batch-id and --output, without --queue")
    if args.arize_dataset_id and not args.arize_experiment_name:
        parser.error("--arize-dataset-id requires --arize-experiment-name")
    if args.queue and not args.case_id:
        parser.error("Select one or more --case-id values for --queue")
    try:
        return asyncio.run(execute(args))
    except Exception:
        parser.exit(
            1, "Evaluation command failed; check local configuration and saved-case access.\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())
