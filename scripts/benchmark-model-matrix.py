"""Compare model settings with identical prompts, fixtures and two-case concurrency.

Offline by default. --execute starts a private loopback API on an unused port;
the normal UI/API configuration is untouched. Stop the automatic demo worker first.
Each pair is tested by every profile, rotating profile order between pairs to
reduce time-of-run bias. Stable suite keys resume saved observations without
repeating completed paid runs. Full outputs and usage stay in local reports.
"""

import argparse
import fcntl
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("compact", "writer_luna", "writer_low", "all_luna")
SPEC = importlib.util.spec_from_file_location("latency", ROOT / "scripts/benchmark-latency.py")
latency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(latency)


def plan(files, profiles):
    return [
        {"pair": index // 2 + 1, "profile": profile, "files": files[index:index + 2]}
        for index in range(0, len(files), 2)
        for profile in (profiles[index // 2 % len(profiles):]
                        + profiles[:index // 2 % len(profiles)])
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--suite", default="model-matrix-20261009")
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", args.suite):
        parser.error("Use a short stable filename-safe suite name")
    if not 1024 <= args.port <= 65535 or args.port in (3011, 8011):
        parser.error("Use an unused unprivileged port distinct from the normal UI/API")
    if len(set(args.profiles)) != len(args.profiles):
        parser.error("Profiles must be unique")
    records = latency.records()
    if args.files:
        if set(args.files) - {record["file"] for record in records}:
            parser.error("Unknown fixture name")
        records = [record for record in records if record["file"] in args.files]
    schedule = plan([record["file"] for record in records], args.profiles)
    identity = {"suite": args.suite, "profiles": args.profiles, "concurrency": 2,
                "fixtures": {record["file"]: record["sha256"] for record in records},
                "schedule": schedule}
    if not args.execute:
        print(json.dumps({"mode": "offline; no calls or uploads", **identity}, indent=2))
        return
    directory = ROOT / ".local-runtime/model-matrix" / args.suite
    directory.mkdir(parents=True, exist_ok=True)
    with (directory.parent / f"port-{args.port}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", args.port))
        saved_plan = directory / "plan.json"
        if saved_plan.exists() and json.loads(saved_plan.read_text()) != identity:
            raise ValueError("Existing experiment plan differs; use its original arguments")
        latency.write_json(saved_plan, identity)
        for step in schedule:
            profile = step["profile"]
            report = ROOT / ".local-runtime/latency-benchmark" / f"{args.suite}-{profile}-c2/report.json"
            rows = json.loads(report.read_text())["runs"] if report.exists() else []
            done = {row["file"] for row in rows if row.get("collected_at")}
            if set(step["files"]) <= done:
                continue
            print(json.dumps({"event": "comparison_pair", **step}), flush=True)
            with (directory / f"api-{profile}.log").open("a") as log:
                api = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "cfin.main:app", "--host", "127.0.0.1",
                     "--port", str(args.port), "--no-access-log"], cwd=ROOT / "backend",
                    env={**os.environ, "ERROR_ANALYSIS_PROFILE": profile},
                    stdout=log, stderr=subprocess.STDOUT,
                )
                try:
                    ready = False
                    with httpx.Client(timeout=1) as client:
                        for _ in range(30):
                            if api.poll() is not None:
                                raise RuntimeError("Experiment API exited before readiness")
                            try:
                                ready = client.get(f"http://127.0.0.1:{args.port}/health").is_success
                            except httpx.RequestError:
                                pass
                            if ready:
                                break
                            time.sleep(0.5)
                    if not ready:
                        raise RuntimeError("Experiment API readiness deadline exceeded")
                    subprocess.run([
                        sys.executable, str(ROOT / "scripts/benchmark-latency.py"),
                        "--execute", "--suite", args.suite, "--expect-profile", profile,
                        "--concurrency", "2", "--api-url", f"http://127.0.0.1:{args.port}",
                        "--baseline", str(ROOT / "docs/validation/analysis-benchmark.json"),
                        "--files", *step["files"],
                    ], cwd=ROOT, check=True)
                finally:
                    api.terminate()
                    try:
                        api.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        api.kill()
                        api.wait(timeout=5)
        print(json.dumps({"event": "comparison_complete", "suite": args.suite,
                          "profiles": args.profiles}), flush=True)


if __name__ == "__main__":
    main()
