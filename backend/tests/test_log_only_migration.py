"""Syntax regression plus opt-in execution of complete local SQL transactions.

The executable probe covers actual triggers, grants, leases, publication, machine
scope and revocation, human milestones and history withdrawal. Parser success is
not presented as equivalent to executing those database behaviors.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pglast import parse_plpgsql, parse_sql

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "supabase/migrations/202610020001_log_only.sql").read_text()


def test_additive_factual_migration_and_function_bodies_parse():
    assert parse_sql(SQL)
    definitions = re.findall(
        r"create (?:or replace )?function private\.\w+\b.*?\$\$;", SQL, re.S | re.I
    )
    assert definitions
    for definition in definitions:
        if "language plpgsql" in definition:
            assert parse_plpgsql(definition), definition.splitlines()[0]


@pytest.mark.skipif(
    not os.environ.get("CFIN_POSTGRES_CONTAINER"),
    reason="Set CFIN_POSTGRES_CONTAINER to a disposable local pgvector/PostgreSQL container",
)
def test_actual_factual_and_legacy_database_transactions():
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "supabase/checks/verify_local.py"),
            "--container",
            os.environ["CFIN_POSTGRES_CONTAINER"],
        ],
        check=True,
        timeout=120,
    )
