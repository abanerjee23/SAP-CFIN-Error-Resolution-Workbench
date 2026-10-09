"""Run isolated synthetic gate/replay checks with evaluator-only expectations."""

import argparse
import asyncio
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from cfin.evaluation import (
    CASE_IDS,
    DEFAULT_CASES,
    EvalObservation,
    evaluate_gates,
    evaluate_workflow,
    load_case_specs,
    summarize,
    with_assessment,
)


async def run_selected(
    *,
    mode: str = "gates",
    case_ids: list[str] | None = None,
    repeat: int = 1,
    cases_path: Path = DEFAULT_CASES,
) -> list[EvalObservation]:
    if repeat < 1 or repeat > 10:
        raise ValueError("Repeat must be between 1 and 10")
    if mode == "live":
        raise ValueError(
            "Live CLI evaluation is disabled until a configured durable budget ledger "
            "is available. "
            "Use evaluate_workflow with an explicitly constructed budgeted executor; "
            "this runner never creates an unreserved paid provider."
        )
    if mode not in ("gates", "replay"):
        raise ValueError("Mode must be gates or replay")
    specs = load_case_specs(cases_path)
    selected = set(case_ids) if case_ids else set(CASE_IDS)
    if not selected.issubset({item["case_id"] for item in specs}):
        raise ValueError("Selected case is missing from the evaluator dataset")
    observations = []
    for spec in specs:
        if spec["case_id"] not in selected:
            continue
        for repeat_index in range(repeat):
            if mode == "gates":
                observation = evaluate_gates(spec["case_id"])
            else:
                # No paid provider is instantiated by this CLI or adapter.
                from cfin.workflow import ScriptedStageAdapter, WorkflowExecutor

                executor = WorkflowExecutor(
                    ScriptedStageAdapter(),
                    run_id="evaluation-" + str(uuid4()),
                    as_of=date(2026, 9, 30),
                )
                observation = await evaluate_workflow(spec["case_id"], executor, mode=mode)
            observation = replace(observation, repeat_index=repeat_index)
            observations.append(with_assessment(observation, spec))
    return observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("gates", "replay", "live"), default="gates")
    parser.add_argument("--case-id", action="append", choices=CASE_IDS)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        observations = asyncio.run(
            run_selected(
                mode=args.mode, case_ids=args.case_id, repeat=args.repeat, cases_path=args.cases
            )
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation did not run: {exc}\n")
    report = summarize(observations)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    failures = [
        f"{observation.case_id}: {check.name}: {check.detail}"
        for observation in observations
        for check in observation.assertions
        if not check.passed
    ]
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
