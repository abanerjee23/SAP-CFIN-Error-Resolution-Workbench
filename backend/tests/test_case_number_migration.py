"""Persistent display references, exercised only in disposable local databases."""

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from pglast import parse_plpgsql, parse_sql

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/202610090005_case_numbers.sql"
WORKSPACE = "10000000-0000-0000-0000-000000000001"
FOREIGN_WORKSPACE = "10000000-0000-0000-0000-000000000002"
ACTOR = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_case_number_migration_and_trigger_parse():
    source = MIGRATION.read_text()
    assert parse_sql(source)
    trigger = re.search(r"create function private\.assign_case_number\(\).*?\$\$;", source, re.S)
    assert trigger and parse_plpgsql(trigger.group())


@pytest.fixture(scope="module")
def case_number_database():
    container = os.environ.get("CFIN_POSTGRES_CONTAINER")
    if not container:
        pytest.skip("Set CFIN_POSTGRES_CONTAINER to a disposable local PostgreSQL container")
    database = f"cfin_case_numbers_{uuid4().hex[:12]}"
    subprocess.run(
        ["docker", "exec", container, "createdb", "-U", "postgres", database],
        check=True,
        timeout=30,
    )

    def run(source: str, *, error: str | None = None) -> str:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-U",
                "postgres",
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-qAt",
            ],
            input=source,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if error:
            assert result.returncode != 0 and error in result.stderr, result.stderr
        else:
            assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    try:
        run((ROOT / "supabase/checks/local_bootstrap.sql").read_text())
        for path in sorted(MIGRATION.parent.glob("*.sql")):
            if path.name < MIGRATION.name:
                run(path.read_text())
        run(f"""
            insert into public.workspaces(id,name) values
              ('{WORKSPACE}','Numbering member workspace'),
              ('{FOREIGN_WORKSPACE}','Numbering other workspace');
            insert into public.workspace_memberships(workspace_id,user_id,roles)
              values('{WORKSPACE}','{ACTOR}',array['process_owner']);
            -- Insert out of order; two timestamps tie, and UTC crosses the year boundary.
            insert into public.cases(id,workspace_id,title,workflow_version,created_at,
                                     updated_at,due_at,version,input_revision)
            values
              ('20000000-0000-0000-0000-000000000003','{WORKSPACE}','Third',
               'error-analysis-v1','2024-12-31 23:30:00-01','2025-02-01Z',now(),7,3),
              ('20000000-0000-0000-0000-000000000001','{WORKSPACE}','First',
               'legacy-v1','2024-06-01Z','2025-02-01Z',now(),7,3),
              ('20000000-0000-0000-0000-000000000002','{WORKSPACE}','Second',
               'log-only-v1','2024-12-31 23:30:00-01','2025-02-01Z',now(),7,3);
        """)
        before = json.loads(run("select jsonb_agg(to_jsonb(c) order by id) from public.cases c"))
        run("set timezone='Pacific/Honolulu';\n" + MIGRATION.read_text())
        run(f"""
            insert into public.cases(workspace_id,title,due_at)
              values('{FOREIGN_WORKSPACE}','Hidden numbered case',now())
        """)
        yield run, before
    finally:
        # Only the uniquely named database created by this fixture is removed.
        subprocess.run(
            ["docker", "exec", container, "dropdb", "-U", "postgres", database],
            check=True,
            timeout=30,
        )


def test_backfill_is_deterministic_and_preserves_all_existing_case_state(case_number_database):
    run, before = case_number_database
    after = json.loads(
        run("""
        select jsonb_agg(to_jsonb(c) order by id) from public.cases c
        where id in ('20000000-0000-0000-0000-000000000001',
                     '20000000-0000-0000-0000-000000000002',
                     '20000000-0000-0000-0000-000000000003')
    """)
    )
    assert [row.pop("case_number") for row in after] == [
        "CFIN-2024-000001",
        "CFIN-2025-000002",
        "CFIN-2025-000003",
    ]
    assert after == before
    assert (
        run("""
        select tgenabled from pg_trigger
        where tgrelid='public.cases'::regclass and tgname='case_updated_at'
    """)
        == "O"
    )


def test_assignment_is_automatic_immutable_and_available_to_existing_service_inserts(
    case_number_database,
):
    run, _ = case_number_database
    case = json.loads(
        run(f"""
        set role service_role;
        set timezone='Pacific/Honolulu';
        insert into public.cases(workspace_id,title,created_at,due_at)
          values('{FOREIGN_WORKSPACE}','Future intake','2026-01-01 00:15:00Z',now())
          returning jsonb_build_object('id',id,'case_number',case_number);
    """)
    )
    assert case["case_number"].startswith("CFIN-2026-")
    assert int(case["case_number"].split("-")[-1]) > 3
    run(
        f"""
        update public.cases set case_number='CFIN-2026-999999' where id='{case["id"]}'
    """,
        error="Case number is immutable",
    )
    run(
        f"""
        update public.cases set case_number=null where id='{case["id"]}'
    """,
        error="Case number is immutable",
    )
    run(
        f"""
        insert into public.cases(workspace_id,title,due_at,case_number)
        values('{WORKSPACE}','Spoofed case',now(),'CFIN-2026-999999')
    """,
        error="Case number is assigned automatically",
    )
    # Routine workflow writes and even a changed timestamp cannot renumber a case.
    assert (
        run(f"""
        update public.cases set title='Updated intake',created_at='2027-01-01Z'
          where id='{case["id"]}' returning case_number
    """)
        == case["case_number"]
    )


def test_concurrent_inserts_have_unique_persistent_references(case_number_database):
    run, _ = case_number_database

    def insert(index):
        return run(f"""
            insert into public.cases(workspace_id,title,due_at,created_at)
            values('{WORKSPACE}','Concurrent intake {index}',now(),'2030-01-01Z')
            returning case_number
        """)

    with ThreadPoolExecutor(max_workers=6) as executor:
        numbers = list(executor.map(insert, range(12)))
    assert len(set(numbers)) == 12
    assert all(re.fullmatch(r"CFIN-2030-\d{6,}", number) for number in numbers)
    saved = run("select case_number from public.cases where title like 'Concurrent intake %'")
    assert set(saved.splitlines()) == set(numbers)


def test_numbering_retains_workspace_isolation_and_does_not_grant_writes(case_number_database):
    run, _ = case_number_database
    assert (
        run(f"""
        set role authenticated;
        set request.jwt.claim.sub='{ACTOR}';
        select count(*) from public.cases where workspace_id='{FOREIGN_WORKSPACE}'
    """)
        == "0"
    )
    assert (
        int(
            run(f"""
        set role authenticated;
        set request.jwt.claim.sub='{ACTOR}';
        select count(case_number) from public.cases where workspace_id='{WORKSPACE}'
    """)
        )
        >= 3
    )
    run(
        f"""
        set role authenticated;
        set request.jwt.claim.sub='{ACTOR}';
        update public.cases set title='Unapproved write' where workspace_id='{WORKSPACE}'
    """,
        error="permission denied",
    )
    run("set role anon; select case_number from public.cases", error="permission denied")
    for role in ("anon", "authenticated", "service_role"):
        assert (
            run(f"""
            select has_sequence_privilege('{role}','private.case_number_sequence','USAGE')
                or has_function_privilege('{role}','private.assign_case_number()','EXECUTE')
        """)
            == "f"
        )
    assert (
        run("""
        select relrowsecurity from pg_class where oid='public.cases'::regclass
    """)
        == "t"
    )


def test_case_numbers_do_not_change_existing_action_version_and_receipt_guards(
    case_number_database,
):
    run, _ = case_number_database
    run((ROOT / "supabase/checks/workbench_connection_verification.sql").read_text())
