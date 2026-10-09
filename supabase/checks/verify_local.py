"""Apply every migration and exercise rollback probes in a fresh local database.

Requires an already running disposable pgvector/PostgreSQL container; never uses
cloud connection strings. Example:
  python3 supabase/checks/verify_local.py --container cfin-rebuild-verification
The uniquely named verification database is retained for inspection. The SQL
checks roll their fixtures back. No model, HTTP, Storage-byte or human-quality
claims are made by this test.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True, help="Disposable local Docker container")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    database = f"cfin_verify_{uuid4().hex[:12]}"
    subprocess.run(
        ["docker", "exec", args.container, "createdb", "-U", "postgres", database], check=True
    )
    command = [
        "docker", "exec", "-i", args.container, "psql", "-U", "postgres", "-d", database,
        "-v", "ON_ERROR_STOP=1", "-At",
    ]
    inputs = [root / "supabase/checks/local_bootstrap.sql"]
    inputs.extend(sorted((root / "supabase/migrations").glob("*.sql")))
    inputs.extend([
        root / "supabase/checks/log_only_verification.sql",
        root / "supabase/checks/completion_verification.sql",
        root / "supabase/checks/workbench_connection_verification.sql",
    ])
    for path in inputs:
        result = subprocess.run(
            command, input=path.read_text(), text=True, capture_output=True, check=False
        )
        if result.returncode:
            raise RuntimeError(f"{path.name}: {result.stderr}")
        if path.name == "completion_verification.sql":
            reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            if len(reports) != 1 or reports[0].get("all_passed") is not True:
                raise RuntimeError(f"Legacy transaction probe failed: {result.stdout}")
        print(f"PASS {path.relative_to(root)}", flush=True)
    print(json.dumps({
        "database": database,
        "container": args.container,
        "migration_count": len(list((root / "supabase/migrations").glob("*.sql"))),
        "factual_transactions": "passed",
        "legacy_transactions": "passed",
        "fixtures": "rolled_back",
        "limitations": ["No actual Storage bytes", "No model calls", "No semantic approvals"],
    }))


if __name__ == "__main__":
    main()
