"""Reproducible synthetic latency experiment through intake and targeted workers.

Default is an offline fixture preflight: no network, intake, or model calls.
--execute explicitly opts in. Restarting the same suite/concurrency/profile uses
saved run IDs and stable intake keys; it never requests a new analysis for an
existing case. Each worker runs in a separate process because Arize tracing uses
process-global instrumentation. Both concurrency settings enqueue the same pairs,
so queue measurements compare like-for-like arrivals.

The API must already run the selected profile and the database must support the
requested concurrency. The runner checks actual immutable run pins and measures
overlap; a requested concurrency of two is not evidence of parallel execution.
Automated gates establish structure, exact provenance, selected metadata, and
category expectations. They do NOT establish semantic factuality or completeness.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import hashlib
import json
import math
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
SUITE = "latency-20261009-v2"
BASELINE = ROOT / "docs/validation/analysis-benchmark.json"
TERMINAL = {"succeeded", "failed", "stale", "cancelled", "canceled"}
COMPACT_PROMPTS = {
    "agent1": "error-analysis-extraction-compact-v2",
    "agent2": "error-analysis-v1",
    "agent3": "error-analysis-summary-compact-v2",
}
BASELINE_PROMPTS = {
    "agent1": "error-analysis-extraction-v1",
    "agent2": "error-analysis-v1",
    "agent3": "error-analysis-summary-v1",
}


def timestamp():
    return datetime.now(UTC).isoformat()


def elapsed(start, end):
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end.replace("Z", "+00:00"))
                  - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds(), 3)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def records():
    normal = json.loads((ROOT / "fixtures/analysis-batches/manifest.json").read_text())["files"]
    hard = json.loads((ROOT / "fixtures/latency-regression/manifest.json").read_text())["files"]
    result = []
    for source, directory in ((normal, "analysis-batches"), (hard, "latency-regression")):
        for original in source:
            row = dict(original)
            row["path"] = f"fixtures/{directory}/{row['file']}"
            raw = (ROOT / row["path"]).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if row.get("sha256", digest) != digest:
                raise ValueError(f"Fixture digest changed: {row['file']}")
            if (not raw or len(raw) > 8192 or len(raw.decode().splitlines()) > 64
                    or not 1 <= row["errors"] <= 5
                    or raw.count(b"severity=error") != row["errors"]):
                raise ValueError(f"Fixture exceeds its declared envelope: {row['file']}")
            row.update(sha256=digest, bytes=len(raw), group=directory)
            if directory == "analysis-batches":
                row.update(
                    allowed_categories=[row["expected_category"]], require_uncertainty=False,
                    metadata={"source_system": "ERP-DEMO", "source_client": "010",
                              "source_company_code": "0010", "target_system": "CFIN-DEMO",
                              "target_client": "100", "target_company_code": "0010",
                              "document_number": row["document"], "interface": "DEMO_CFIN_GL"},
                    review_expectations=[
                        "Every distinct logged error remains represented; no invented root cause.",
                        ("Logged failures remain separate from proposed human actions "
                         "and SAP state."),
                    ],
                )
            result.append(row)
    return result


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"mean_seconds": round(statistics.mean(ordered), 3),
            "median_seconds": round(statistics.median(ordered), 3),
            "p95_seconds": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
            "max_seconds": round(ordered[-1], 3)}


def observed_parallelism(rows):
    events = []
    for row in rows:
        calls = row.get("calls", [])
        starts = [call["created_at"] for call in calls if call.get("created_at")]
        ends = [call["reconciled_at"] for call in calls if call.get("reconciled_at")]
        if starts and ends:
            events.extend(((min(starts), 1), (max(ends), -1)))
    running = peak = 0
    for _, change in sorted(events):
        running += change
        peak = max(peak, running)
    return peak


def summarise(rows):
    completed = [row for row in rows if row.get("collected_at")]
    calls = [call for row in completed for call in row.get("calls", [])]
    return {
        "recorded_cases": len(rows), "completed_observations": len(completed),
        "published": sum(row.get("published", False) for row in completed),
        "automated_quality_passes": sum(row.get("quality", {}).get("passed", False)
                                       for row in completed),
        "semantic_review": "required; automatic checks are not semantic quality evidence",
        "model_calls": len(calls),
        "tokens": {key: sum((call.get("usage") or {}).get(key, 0) for call in calls)
                   for key in ("input_tokens", "output_tokens")},
        "known_cost_usd": str(sum((Decimal(row["known_cost_usd"]) for row in completed),
                                  Decimal(0))),
        "unresolved_reserved_usd": str(sum((Decimal(row["unresolved_reserved_usd"])
                                           for row in completed), Decimal(0))),
        "workflow_latency": distribution([row["workflow_seconds"] for row in completed
                                          if row.get("workflow_seconds") is not None]),
        "upload_to_result_latency": distribution([row["end_to_end_seconds"] for row in completed
                                                  if row.get("end_to_end_seconds") is not None]),
        "queue_and_startup_latency": distribution([row["queue_and_startup_seconds"]
                                                   for row in completed
                                                   if row.get("queue_and_startup_seconds")
                                                   is not None]),
        "stage_latency": {stage: distribution([call["latency_seconds"] for call in calls
                                               if call["stage"] == stage
                                               and call.get("latency_seconds") is not None])
                          for stage in ("agent_1", "agent_2", "agent_3")},
        "observed_peak_case_execution_overlap": observed_parallelism(completed),
        "trace_exports_acknowledged": sum(row.get("arize", {}).get("status")
                                          == "export_acknowledged" for row in completed),
        "caveat": "Small synthetic experiment, not a production SLA or load test. Stage timestamps "
                  "include reservation/reconciliation overhead. Upload-to-result includes queue, "
                  "worker/export, and API readback. Resumed runs are marked separately.",
    }


def baseline_comparison(rows, baseline):
    previous = {row["file"]: row for row in baseline["runs"]}
    matched = [row for row in rows if row.get("collected_at") and row["file"] in previous
               and row.get("workflow_seconds") is not None]
    if not matched:
        return {"matched_files": 0}
    before = statistics.mean(previous[row["file"]]["workflow_seconds"] for row in matched)
    after = statistics.mean(row["workflow_seconds"] for row in matched)
    return {"matched_files": len(matched),
            "published_matched_files": sum(row.get("published", False) for row in matched),
            "automated_quality_passes": sum(row.get("quality", {}).get("passed", False)
                                             for row in matched),
            "quality_preserving_speed_claim_ready": False,
            "baseline_mean_workflow_seconds": round(before, 3),
            "current_mean_workflow_seconds": round(after, 3),
            "workflow_reduction_percent": round((before - after) / before * 100, 2),
            "baseline_known_cost_usd": str(sum((Decimal(previous[row["file"]]["known_cost_usd"])
                                                for row in matched), Decimal(0))),
            "current_known_cost_usd": str(sum((Decimal(row["known_cost_usd"])
                                               for row in matched), Decimal(0))),
            "quality_caveat": "Compare these same files only; the harder fixtures have no prior "
                              "baseline. Latency improvement is not permission to regress quality."}


def validate_profile(run, expected):
    prompts = run.get("prompt_versions", {})
    models = run.get("model_configuration", {})
    if prompts != (BASELINE_PROMPTS if expected == "baseline" else COMPACT_PROMPTS):
        raise ValueError("The API saved different prompt pins from the requested profile")
    efforts = {stage: models.get(f"{stage}_reasoning_effort", models.get("reasoning_effort"))
               for stage in ("agent1", "agent2", "agent3")}
    wanted = {"agent1": "low", "agent2": "medium", "agent3": "low"} if expected == "fast" else {
        "agent1": "medium", "agent2": "medium", "agent3": "medium"}
    if expected == "writer_low":
        wanted["agent3"] = "low"
    if efforts != wanted:
        raise ValueError("The API saved different reasoning pins from the requested profile")
    wanted_models = {"agent1": "gpt-6-luna", "agent2": "gpt-6.1-sol",
                     "agent3": "gpt-6.1-sol"}
    if expected in {"writer_luna", "all_luna"}:
        wanted_models["agent3"] = "gpt-6-luna"
    if expected == "all_luna":
        wanted_models["agent2"] = "gpt-6-luna"
    if any(models.get(stage) != model for stage, model in wanted_models.items()):
        raise ValueError("The API saved different model pins from the requested profile")


def exact_metadata(extraction, expected):
    """Check explicit logged pairs, not guessed semantic equivalence or frontend projection."""
    observed = {}
    for key, value in expected.items():
        normal = key.replace("_", " ")
        supported = False
        for entry in extraction.entries:
            for field in entry.fields:
                label = re.sub(r"[_-]+", " ", field.name_as_logged.strip().lower())
                if label != normal or field.value_as_logged != value:
                    continue
                pattern = (r"(?:^|[|;\r\n])\s*" + re.escape(field.name_as_logged)
                           + r"\s*[:=]\s*" + re.escape(value) + r"(?=$|[|;\r\n\s])")
                if re.search(pattern, entry.raw_text):
                    supported = True
        observed[key] = {"expected": value, "exact_logged_pair_preserved": supported}
    return observed


def quality_gates(record, output, published):
    from cfin.error_analysis_contracts import (
        CaseContent,
        ErrorAnalysis,
        validate_case_content,
        validate_error_analysis,
    )
    from cfin.log_only_contracts import (
        ExtractedLog,
        HistoryRetrievalResult,
        LogSourceManifest,
    )
    from cfin.log_only_sources import validate_extraction

    checks = {"published_current_run": bool(published),
              "completed": output.get("outcome") == "completed",
              "category_allowed": (output.get("analysis") or {}).get("category_id")
              in record["allowed_categories"]}
    details = {}
    try:
        manifest = LogSourceManifest.model_validate(output.get("source_manifest"))
        extraction = ExtractedLog.model_validate(output.get("extraction"))
        raw = (ROOT / record["path"]).read_bytes()
        checks["original_hash_and_size"] = (
            len(manifest.sources) == 1
            and manifest.sources[0].content_sha256 == record["sha256"]
            and manifest.sources[0].byte_size == len(raw)
        )
        originals = {(source.source_id, source.source_version): raw for source in manifest.sources}
        coverage = validate_extraction(manifest, originals, extraction)
        checks["exact_source_spans"] = True
        checks["complete_source_coverage"] = coverage.complete_coverage
        metadata = exact_metadata(extraction, record["metadata"])
        details["metadata"] = metadata
        checks["exact_metadata"] = all(item["exact_logged_pair_preserved"]
                                       for item in metadata.values())
        analysis = ErrorAnalysis.model_validate(output.get("analysis"))
        content = CaseContent.model_validate(output.get("case_content"))
        history = HistoryRetrievalResult.model_validate(output.get("history") or {})
        validate_error_analysis(extraction, analysis)
        validate_case_content(extraction, content, history=history)
        checks["valid_citation_references_and_route"] = True
        if record.get("require_uncertainty"):
            checks["explicit_uncertainty"] = bool(analysis.gaps or analysis.competing_explanations)
            checks["no_high_confidence_on_ambiguous_evidence"] = analysis.confidence != "high"
    except (ValueError, TypeError, KeyError) as exc:
        checks["contract_and_provenance_validation"] = False
        details["validation_error_type"] = type(exc).__name__
    return {"passed": all(checks.values()), "checks": checks, **details,
            "semantic_review_status": "pending",
            "review_expectations": record["review_expectations"],
            "semantic_caveat": "Valid citations prove reference integrity, not that the prose "
                               "is entailed by its evidence. Review chronology, uncertainty, "
                               "all distinct errors, unsupported actions, and source/target roles."}


async def child_run(args):
    from cfin.config import Settings
    from cfin.gateway import ServiceGateway
    from cfin.worker import process_one

    settings = Settings(_env_file=ROOT / "backend/.env")
    run_id = str(UUID(args.child_run_id))
    deadline = time.monotonic() + args.claim_wait_seconds
    async with httpx.AsyncClient(timeout=45) as client:
        service = ServiceGateway(settings, client)
        while True:
            rows = await service.rows("analysis_runs", {
                "id": f"eq.{run_id}", "workspace_id": f"eq.{settings.demo_workspace_id}",
                "select": "id,state,prompt_versions,model_configuration"})
            if len(rows) != 1:
                raise RuntimeError("Target run is outside the configured synthetic workspace")
            validate_profile(rows[0], args.expect_profile)
            if rows[0]["state"] in TERMINAL:
                write_json(args.child_receipt, {"claimed": False, "already_terminal": True,
                                                "run_id": run_id, "finished_at": timestamp()})
                return
            result = await process_one(service, settings, args.worker_id, target_run_id=run_id)
            if result.get("claimed"):
                write_json(args.child_receipt, {**result, "finished_at": timestamp()})
                return
            if time.monotonic() >= deadline:
                write_json(args.child_receipt, {**result, "run_id": run_id,
                                                "claim_wait_expired": True})
                return
            await asyncio.sleep(2)


async def collect(client, service, headers, workspace, row, record, receipt):
    response = await client.get(f"/api/cases/{row['case_id']}", headers=headers,
                                params={"workspace_id": workspace})
    response.raise_for_status()
    saved = response.json()
    run = next(item for item in saved["runs"] if item["id"] == row["run_id"])
    if run["state"] not in TERMINAL:
        row["runner_status"] = "unfinished; rerun the same command to observe/reclaim this run"
        row["last_receipt"] = receipt
        return
    output = run.get("output") or {}
    calls = await service.rows("stage_calls", {
        "workspace_id": f"eq.{workspace}", "run_id": f"eq.{row['run_id']}",
        "select": "stage,invocation,model_id,state,actual_usd,reserved_usd,usage,"
                  "created_at,reconciled_at", "order": "created_at.asc"})
    for call in calls:
        call["latency_seconds"] = elapsed(call.get("created_at"), call.get("reconciled_at"))
    published = saved["case"].get("published_run_id") == run["id"]
    observed_at = timestamp()
    known = sum((Decimal(str(call["actual_usd"])) for call in calls
                 if call.get("actual_usd") is not None), Decimal(0))
    unknown = sum((Decimal(str(call["reserved_usd"])) for call in calls
                   if call.get("actual_usd") is None and call["state"] != "not_sent"), Decimal(0))
    row.update(
        collected_at=observed_at, runner_status="collected", state=run["state"],
        case_number=saved["case"].get("case_number"), published=published,
        outcome=output.get("outcome"), category=(output.get("analysis") or {}).get("category_id"),
        workflow_seconds=output["latency_ms"] / 1000 if "latency_ms" in output else None,
        end_to_end_seconds=elapsed(row["upload_started_at"], observed_at),
        queue_and_startup_seconds=elapsed(run["created_at"], calls[0]["created_at"])
        if calls else None,
        model_configuration=run.get("model_configuration"),
        prompt_versions=run.get("prompt_versions"),
        known_cost_usd=str(known), unresolved_reserved_usd=str(unknown), calls=calls,
        arize=receipt.get("arize", {}), quality=quality_gates(record, output, published),
        analysis_output=output,
    )


async def execute(args, selected, report_path):
    from cfin.config import Settings
    from cfin.gateway import ServiceGateway

    settings = Settings(_env_file=ROOT / "backend/.env")
    if not (settings.models_configured and settings.arize_configured):
        raise RuntimeError("Configured real models and enabled Arize tracing are required")
    workspace = str(settings.demo_workspace_id)
    identity = {"suite": args.suite, "concurrency": args.concurrency,
                "expected_profile": args.expect_profile, "workspace_id": workspace}
    report = json.loads(report_path.read_text()) if report_path.exists() else {
        **identity, "created_at": timestamp(), "runs": []}
    if any(report.get(key) != value for key, value in identity.items()):
        raise ValueError("Existing report has a different immutable experiment identity")
    baseline = json.loads(args.baseline.read_text())

    def save():
        report["summary"] = summarise(report["runs"])
        report["baseline_comparison"] = baseline_comparison(report["runs"], baseline)
        write_json(report_path, report)

    async with httpx.AsyncClient(base_url=args.api_url, timeout=45) as client:
        service = ServiceGateway(settings, client)
        spaces = await service.rows("workspaces", {"id": f"eq.{workspace}"})
        if len(spaces) != 1 or spaces[0].get("synthetic") is not True:
            raise RuntimeError("Only the configured synthetic workspace may be benchmarked")
        response = await client.post("/api/demo/session", headers={"Origin": args.origin})
        response.raise_for_status()
        session = response.json()
        if session["workspace"]["id"] != workspace:
            raise RuntimeError("Demo session workspace differs from the experiment")
        headers = {"Authorization": "Bearer " + session["token"], "Origin": args.origin}

        async def dispatch(row, record):
            receipt_path = report_path.parent / f"{row['run_id']}.worker.json"
            # Preserve a completed worker receipt after a parent interruption.
            receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
            if not receipt.get("finished_at"):
                command = [sys.executable, str(Path(__file__).resolve()), "--execute",
                           "--child-run-id", row["run_id"], "--child-receipt", str(receipt_path),
                           "--worker-id", f"{args.suite}-{row['run_id'][:8]}",
                           "--expect-profile", args.expect_profile,
                           "--claim-wait-seconds", str(args.claim_wait_seconds)]
                process = await asyncio.create_subprocess_exec(*command, cwd=ROOT)
                code = await process.wait()
                if code:
                    row["runner_error"] = f"Worker subprocess exited {code}; same run retained"
                receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
            await collect(client, service, headers, workspace, row, record, receipt)
            save()
            print(json.dumps({key: row.get(key) for key in (
                "file", "run_id", "published", "workflow_seconds", "known_cost_usd",
                "runner_status")}), flush=True)

        for start in range(0, len(selected), 2):
            pending = []
            for record in selected[start:start + 2]:
                row = next((item for item in report["runs"]
                            if item["file"] == record["file"]), None)
                if row:
                    if row["sha256"] != record["sha256"]:
                        raise ValueError("A fixture changed within this experiment")
                    if row.get("collected_at"):
                        continue
                    row["resumed_observation"] = True
                else:
                    started = timestamp()
                    key = f"{args.suite}-{args.expect_profile}-c{args.concurrency}-{record['file']}"
                    encoded = base64.b64encode((ROOT / record["path"]).read_bytes()).decode()
                    response = await client.post("/api/intakes/error-analysis", headers=headers,
                                                 json={
                        "workspace_id": workspace, "acting_role": "process_owner",
                        "provenance": "synthetic", "delivery_key": key,
                        "sources": [{"filename": record["file"], "content_base64": encoded}],
                    })
                    response.raise_for_status()
                    intake = response.json()
                    response = await client.get(f"/api/cases/{intake['case_id']}", headers=headers,
                                                params={"workspace_id": workspace})
                    response.raise_for_status()
                    saved = response.json()
                    run_id = saved["case"]["requested_run_id"]
                    run = next(item for item in saved["runs"] if item["id"] == run_id)
                    row = {**record, "case_id": saved["case"]["id"], "run_id": run_id,
                           "delivery_key": key, "upload_started_at": started,
                           "resumed_observation": False, "runner_status": "queued"}
                    report["runs"].append(row)
                    save()
                    validate_profile(run, args.expect_profile)
                pending.append((row, record))
            if args.concurrency == 1:
                for row, record in pending:
                    await dispatch(row, record)
            else:
                await asyncio.gather(*(dispatch(row, record) for row, record in pending))
    save()
    print(json.dumps({"report": str(report_path), "summary": report["summary"],
                      "baseline_comparison": report["baseline_comparison"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Opt in to paid traced model calls")
    parser.add_argument("--suite", default=SUITE, help="Stable experiment key; reuse it to resume")
    parser.add_argument("--expect-profile", choices=(
        "baseline", "compact", "fast", "writer_luna", "writer_low", "all_luna"
    ), default="compact")
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=1)
    parser.add_argument("--files", nargs="+", help="Exact fixture basenames; omitted means all 13")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--api-url", default="http://127.0.0.1:8011")
    parser.add_argument("--origin", default="http://127.0.0.1:3011")
    parser.add_argument("--claim-wait-seconds", type=int, default=240)
    parser.add_argument("--child-run-id", help=argparse.SUPPRESS)
    parser.add_argument("--child-receipt", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.claim_wait_seconds <= 0:
        parser.error("Claim wait must be a positive number of seconds")
    if args.child_run_id:
        if not args.execute or not args.child_receipt or not args.worker_id:
            parser.error("Internal worker mode requires --execute and receipt/worker identity")
        asyncio.run(child_run(args))
        return
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", args.suite):
        parser.error("Suite must be a short filename-safe experiment identity")
    selected = records()
    if args.files:
        unknown = set(args.files) - {row["file"] for row in selected}
        if unknown:
            parser.error(f"Unknown fixture names: {sorted(unknown)}")
        selected = [row for row in selected if row["file"] in args.files]
    report_path = (args.report or ROOT / ".local-runtime/latency-benchmark"
                   / f"{args.suite}-{args.expect_profile}-c{args.concurrency}" / "report.json")
    if not args.execute:
        print(json.dumps({"mode": "offline preflight; no calls or uploads", "suite": args.suite,
                          "files": selected, "concurrency": args.concurrency,
                          "expected_profile": args.expect_profile, "report": str(report_path),
                          "baseline_runs": len(json.loads(args.baseline.read_text())["runs"])},
                         indent=2))
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.with_suffix(".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("This experiment already has an active runner")
        asyncio.run(execute(args, selected, report_path))


if __name__ == "__main__":
    main()
