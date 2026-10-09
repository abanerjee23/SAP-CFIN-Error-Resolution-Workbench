"""Apply reviewed latency migrations to the configured synthetic demo DB.

Default is read-only. --apply requires a drained queue and verifies existing cases,
runs and evidence are unchanged inside the same transaction. Credentials stay local.
"""

import argparse
import json
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ("202610090006_parallel_analysis.sql", "private.analysis_worker_slots"),
    ("202610090007_latency_profiles.sql", None),
    ("202610090008_model_matrix.sql", None),
]


def fingerprints(cursor):
    result = {}
    for table in ("cases", "analysis_runs", "evidence_versions", "intakes", "stage_calls"):
        cursor.execute(f"select id::text, md5(to_jsonb(t)::text) from public.{table} t order by id")
        result[table] = cursor.fetchall()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path,
                        default=ROOT / ".local-runtime/latency-migration-report.json")
    args = parser.parse_args()
    cfg = dotenv_values(ROOT / "backend/.env")
    try:
        with (
            psycopg.connect(cfg["DATABASE_URL"], connect_timeout=15, sslmode="require") as conn,
            conn.cursor() as cur,
        ):
            cur.execute("set local lock_timeout='5s'; set local statement_timeout='60s'")
            cur.execute("select count(*) from public.workspaces where synthetic is not true")
            if cur.fetchone()[0]:
                raise RuntimeError("Only an entirely synthetic demo database is supported")
            cur.execute("select count(*) from public.jobs where state in ('queued','running')")
            pending = cur.fetchone()[0]
            cur.execute("select to_regclass('private.analysis_worker_slots') is not null")
            parallel = cur.fetchone()[0]
            cur.execute("select to_regprocedure('private.error_analysis_configuration_supported(jsonb,jsonb)') is not null")
            profiles = cur.fetchone()[0]
            cur.execute("select to_regprocedure('private.error_analysis_configuration_supported(jsonb,jsonb)')")
            function_oid = cur.fetchone()[0]
            matrix = False
            if function_oid:
                cur.execute("select pg_get_functiondef(%s::regprocedure)", (function_oid,))
                matrix = '"agent2":"gpt-6-luna","agent3":"gpt-6-luna"' in cur.fetchone()[0]
            report = {"pending_jobs": pending, "parallel_installed": parallel,
                      "profiles_installed": profiles, "model_matrix_installed": matrix,
                      "applied": []}
            if args.apply:
                if pending:
                    raise RuntimeError("Drain the queue before applying latency migrations")
                cur.execute("lock table public.cases, public.analysis_runs, public.evidence_versions, public.intakes, public.stage_calls in share mode")
                before = fingerprints(cur)
                for (name, _), installed in zip(MIGRATIONS, (parallel, profiles, matrix), strict=True):
                    if installed:
                        continue
                    sql = (ROOT / "supabase/migrations" / name).read_text()
                    assert sql.count("\nbegin;\n") == 1 and sql.endswith("commit;\n")
                    cur.execute(sql.replace("\nbegin;\n", "\n", 1).removesuffix("commit;\n"))
                    report["applied"].append(name)
                if fingerprints(cur) != before:
                    raise RuntimeError("Existing saved records changed; transaction rolled back")
                report["existing_records_unchanged"] = True
            # Commit only after every integrity assertion above has passed.
        path = args.report
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    except (psycopg.Error, RuntimeError, ValueError, KeyError, OSError) as exc:
        print(json.dumps({"applied": False, "error_type": type(exc).__name__,
                          "sqlstate": getattr(exc, "sqlstate", None)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
