"""Generate five synthetic batches; opt in to ten real, traced analysis runs.

Run from the repo root with the backend environment on PYTHONPATH. Execution
uses the local demo intake API and the normal targeted worker, never a model
shortcut. Existing report entries and stable delivery keys prevent duplicate
intake on restart. No case is closed and no human decision is simulated.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from cfin.config import Settings
from cfin.gateway import ServiceGateway
from cfin.worker import process_one

SUITE = "upload-progress-20261009-v1"
FIXTURES = ROOT / "fixtures/analysis-batches"
REPORT = ROOT / ".local-runtime/analysis-benchmark/report.json"


def generate():
    records = []
    for batch in range(1, 6):
        for variant, category in enumerate(("master_data", "mapping")):
            document = f"{123500 + batch * 10 + variant:010}"
            name = f"batch-{batch:02}-{category}.txt"
            errors = [
                f"Target G/L account 004100{line:03} could not be located in chart SYN1, "
                f"CFIN-DEMO/100, company code 0010; requested target line {line:04}."
                if category == "master_data" else
                f"No applicable source-to-target mapping for source G/L account 000040{line:04} "
                f"in company code 0010; requested target line {line:04}."
                for line in range(1, batch + 1)
            ]
            text = "\n".join([
                f"SYNTHETIC BENCHMARK {SUITE} / batch {batch}. Fictional application log, not an SAP export.",
                "No real customer data or SAP-specific message catalogue is asserted.",
                f"2026-10-09T15:00:00Z | attempt_id=BENCH-{batch}-{variant}-A1 | processing_order=1 | event=replication_started",
                "source_system=ERP-DEMO | source_client=010 | source_company_code=0010",
                f"fiscal_year=2026 | document_number={document} | source_status=posted",
                "source_posting_date=2026-10-09 | source_posted_at=2026-10-09T14:55:00Z",
                "target_system=CFIN-DEMO | target_client=100 | target_company_code=0010",
                "interface=DEMO_CFIN_GL | target_chart_of_accounts=SYN1",
                *[f"2026-10-09T15:00:{index:02}Z | severity=error | synthetic_message_id=BENCH-{index:02} | {error}"
                  for index, error in enumerate(errors, 1)],
                "Target posting stopped for this attempt; no target document reference was returned.",
                "2026-10-09T15:00:10Z | event=replication_finished | result=failed",
                "Evidence is limited to this attempt. No correction, approval or successful reprocessing is recorded.",
                "Human validation is required to establish the current target configuration and root cause.",
                "",
            ])
            path = FIXTURES / name
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = text.encode("utf-8")
            assert len(encoded) <= 8192 and text.count("severity=error") == batch
            path.write_bytes(encoded)
            records.append({"batch": batch, "file": name, "errors": batch,
                            "expected_category": category, "document": document,
                            "sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)})
    (FIXTURES / "manifest.json").write_text(json.dumps({"suite": SUITE, "files": records}, indent=2) + "\n")
    return records


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"mean_seconds": round(statistics.mean(values), 2),
            "median_seconds": round(statistics.median(values), 2),
            "p95_seconds": round(ordered[math.ceil(.95 * len(ordered)) - 1], 2),
            "max_seconds": round(max(values), 2)}


def summarise(rows):
    stage_seconds = {}
    for row in rows:
        for call in row["calls"]:
            if call.get("latency_seconds") is not None:
                stage_seconds.setdefault(call["stage"], []).append(call["latency_seconds"])
    return {
        "runs": len(rows), "succeeded": sum(row["published"] for row in rows),
        "model_calls": sum(len(row["calls"]) for row in rows),
        "tokens": {key: sum((call.get("usage") or {}).get(key, 0) for row in rows for call in row["calls"])
                   for key in ("input_tokens", "output_tokens")},
        "known_cost_usd": str(sum((Decimal(row["known_cost_usd"]) for row in rows), Decimal(0))),
        "unresolved_reserved_usd": str(sum((Decimal(row["unresolved_reserved_usd"]) for row in rows), Decimal(0))),
        "workflow_latency": distribution([row["workflow_seconds"] for row in rows if row["workflow_seconds"] is not None]),
        "upload_to_result_latency": distribution([row["end_to_end_seconds"] for row in rows]),
        "queue_and_startup_latency": distribution([row["queue_and_startup_seconds"] for row in rows if row.get("queue_and_startup_seconds") is not None]),
        "stage_latency": {stage: distribution(values) for stage, values in stage_seconds.items()},
        "trace_exports_acknowledged": sum(row.get("arize", {}).get("status") == "export_acknowledged" for row in rows),
        "trace_readback_evidence": ".local-runtime/analysis-benchmark/arize-readback.json (run verify-analysis-traces.py separately)",
        "caveat": "Ten serial runs are a small initial baseline, not a load test or production SLA.",
    }


async def run(records):
    settings = Settings(_env_file=ROOT / "backend/.env")
    if not (settings.models_configured and settings.arize_configured):
        raise RuntimeError("Enabled model execution and configured Arize tracing are required")
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {"suite": SUITE, "runs": []}
    assert report["suite"] == SUITE
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=45) as client:
        service = ServiceGateway(settings, client)
        workspaces = await service.rows("workspaces", {"id": f"eq.{settings.demo_workspace_id}"})
        assert len(workspaces) == 1 and workspaces[0]["synthetic"] is True
        response = await client.post("http://127.0.0.1:8011/api/demo/session", headers={"Origin": "http://127.0.0.1:3011"})
        response.raise_for_status()
        session = response.json()
        assert session["workspace"]["id"] == str(settings.demo_workspace_id)
        headers = {"Authorization": "Bearer " + session["token"], "Origin": "http://127.0.0.1:3011"}
        async def detail(case_id):
            response = await client.get(f"http://127.0.0.1:8011/api/cases/{case_id}", headers=headers,
                                        params={"workspace_id": str(settings.demo_workspace_id)})
            response.raise_for_status()
            return response.json()
        for batch in range(1, 6):
            queued = []
            for record in [row for row in records if row["batch"] == batch]:
                if any(row["file"] == record["file"] for row in report["runs"]):
                    continue
                started = time.monotonic()
                payload = {"workspace_id": str(settings.demo_workspace_id), "acting_role": "process_owner",
                           "provenance": "synthetic", "delivery_key": f"{SUITE}-{record['file']}",
                           "sources": [{"filename": record["file"], "content_base64": base64.b64encode((FIXTURES / record["file"]).read_bytes()).decode()}]}
                response = await client.post("http://127.0.0.1:8011/api/intakes/error-analysis", headers=headers, json=payload)
                response.raise_for_status()
                saved = await detail(response.json()["case_id"])
                queued.append((record, saved, started))
            for record, saved, started in queued:
                case_id, run_id = saved["case"]["id"], saved["case"]["requested_run_id"]
                print(json.dumps({"event": "run_started", "batch": batch, "file": record["file"], "run_id": run_id}), flush=True)
                execution = await process_one(service, settings, SUITE, target_run_id=run_id)
                saved = await detail(case_id)
                run = next(row for row in saved["runs"] if row["id"] == run_id)
                output = run.get("output") or {}
                calls = await service.rows("stage_calls", {"workspace_id": f"eq.{settings.demo_workspace_id}", "run_id": f"eq.{run_id}", "select": "stage,invocation,model_id,state,actual_usd,reserved_usd,usage,created_at,reconciled_at", "order": "created_at.asc"})
                for call in calls:
                    call["latency_seconds"] = round((datetime.fromisoformat(call["reconciled_at"].replace("Z", "+00:00")) - datetime.fromisoformat(call["created_at"].replace("Z", "+00:00"))).total_seconds(), 3) if call.get("reconciled_at") else None
                known = sum((Decimal(str(call["actual_usd"])) for call in calls if call.get("actual_usd") is not None), Decimal(0))
                unknown = sum((Decimal(str(call["reserved_usd"])) for call in calls if call.get("actual_usd") is None and call["state"] != "not_sent"), Decimal(0))
                result = {**record, "case_id": case_id, "case_number": saved["case"].get("case_number"), "run_id": run_id,
                          "published": saved["case"].get("published_run_id") == run_id,
                          "outcome": output.get("outcome"), "category": (output.get("analysis") or {}).get("category_id"),
                          "workflow_seconds": output.get("latency_ms", 0) / 1000 if "latency_ms" in output else None,
                          "end_to_end_seconds": round(time.monotonic() - started, 3),
                          "queue_and_startup_seconds": round((datetime.fromisoformat(calls[0]["created_at"].replace("Z", "+00:00")) - datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))).total_seconds(), 3) if calls else None,
                          "known_cost_usd": str(known), "unresolved_reserved_usd": str(unknown),
                          "failure_reason": output.get("failure_reason"), "arize": execution.get("arize", {}), "calls": calls}
                report["runs"].append(result)
                report["summary"] = summarise(report["runs"])
                REPORT.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps({key: result[key] for key in ("file", "published", "workflow_seconds", "known_cost_usd", "arize")}), flush=True)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Make paid model calls and export synthetic traces")
    args = parser.parse_args()
    files = generate()
    if args.execute:
        asyncio.run(run(files))
    else:
        print(json.dumps({"files": len(files), "batches": 5, "max_errors_per_file": 5, "directory": str(FIXTURES)}))
