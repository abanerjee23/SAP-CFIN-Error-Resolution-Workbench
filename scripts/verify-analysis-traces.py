"""Read benchmark trace IDs back from Arize; do not export new spans or call a model."""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from cfin.arize_evaluation import _client
from cfin.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path,
                        default=ROOT / ".local-runtime/analysis-benchmark/report.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    settings = Settings(_env_file=ROOT / "backend/.env")
    report = json.loads(args.report.read_text())
    client = _client(settings)
    project = client.projects.get(project=settings.arize_project_name, space=settings.arize_space_id)
    expected = {trace for row in report["runs"] for trace in row["arize"].get("trace_ids", [])}
    earliest = min(call["created_at"] for row in report["runs"] for call in row["calls"])
    start = datetime.fromisoformat(earliest.replace("Z", "+00:00")) - timedelta(minutes=1)
    end = datetime.now(UTC)
    observed = {}
    cursor = None
    for _ in range(10):
        page = client.spans.list(project=project.id, start_time=start, end_time=end,
                                 included_columns=["attributes.metadata", "attributes.llm.token_count.prompt", "attributes.llm.token_count.completion"],
                                 limit=100, cursor=cursor)
        for span in page.spans:
            if span.context.trace_id in expected:
                observed.setdefault(span.context.trace_id, []).append({
                    "kind": str(span.kind), "span_id": span.context.span_id,
                    "latency_seconds": (span.end_time - span.start_time).total_seconds(),
                    "attributes": span.attributes,
                })
        if not page.pagination.has_more:
            break
        cursor = page.pagination.next_cursor
    rows = [{"run_id": row["run_id"], "expected_trace_ids": row["arize"].get("trace_ids", []),
             "all_traces_found": bool(row["arize"].get("trace_ids")) and all(trace in observed for trace in row["arize"]["trace_ids"])}
            for row in report["runs"]]
    result = {"project_id": project.id, "project_name": settings.arize_project_name,
              "expected_traces": len(expected), "found_traces": len(observed),
              "readback_verified": bool(rows) and all(row["all_traces_found"] for row in rows),
              "runs": rows, "observed": observed}
    path = args.output or args.report.parent / "arize-readback.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("project_name", "expected_traces", "found_traces", "readback_verified")}))
    return 0 if result["readback_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
