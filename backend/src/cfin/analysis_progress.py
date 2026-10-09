"""User-facing progress derived from the current run's durable call ledger."""

from typing import Any


def analysis_progress(case: dict, runs: list[dict], calls: list[dict]) -> dict[str, Any]:
    run_id = case.get("requested_run_id")
    run = next((row for row in runs if row.get("id") == run_id), {})
    current = [row for row in calls if row.get("run_id") == run_id]
    current.sort(key=lambda row: (row.get("created_at", ""), row.get("invocation", 0)))
    latest = current[-1] if current else {}
    state = case.get("analysis_status", "pending")
    status = (
        "ready" if state == "available" and run_id == case.get("published_run_id")
        else "failed" if state in {"failed", "unavailable"} or run.get("state") == "failed"
        else "running" if current or run.get("state") == "running"
        else "queued"
    )
    attempt = int(latest.get("invocation", 0)) + 1
    return {
        "run_id": run_id,
        "status": status,
        "stage": latest.get("stage"),
        "attempt": attempt,
        "retrying": status == "running" and attempt > 1,
        "queued_at": run.get("created_at", case.get("created_at")),
        "stage_started_at": latest.get("created_at"),
        "completed_stages": sorted({
            row["stage"] for row in current if row.get("state") == "succeeded"
        }),
    }
