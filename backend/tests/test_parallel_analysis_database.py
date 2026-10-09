"""Bounded concurrency and ownership checks against disposable PostgreSQL only."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from pglast import parse_sql

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'supabase/migrations/202610090006_parallel_analysis.sql'


def test_parallel_migration_parses():
    assert parse_sql(MIGRATION.read_text())


@pytest.fixture
def parallel_database():
    container = os.environ.get('CFIN_POSTGRES_CONTAINER')
    if not container:
        pytest.skip('Set CFIN_POSTGRES_CONTAINER to a disposable local PostgreSQL container')
    database = 'cfin_parallel_' + uuid4().hex[:12]
    subprocess.run(['docker', 'exec', container, 'createdb', '-U', 'postgres', database],
                   check=True, timeout=30)

    def run(source: str, *, error: str | None = None) -> str:
        result = subprocess.run(
            ['docker', 'exec', '-i', container, 'psql', '-U', 'postgres', '-d', database,
             '-v', 'ON_ERROR_STOP=1', '-qAt'],
            input=source, text=True, capture_output=True, timeout=30, check=False,
        )
        if error:
            assert result.returncode and error in result.stderr, result.stderr
            return result.stderr
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    try:
        run((ROOT / 'supabase/checks/local_bootstrap.sql').read_text())
        for migration in sorted(MIGRATION.parent.glob('*.sql')):
            run(migration.read_text())
        yield run
    finally:
        # Never use a cloud URL; remove only this fixture's fresh random database.
        subprocess.run(['docker', 'exec', container, 'dropdb', '-U', 'postgres', database],
                       check=True, timeout=30)


def test_parallel_claim_recovery_ownership_budget_and_legacy_guards(parallel_database):
    parallel_database((ROOT / 'supabase/checks/parallel_analysis_verification.sql').read_text())


def test_parallel_slots_preserve_existing_workflow_transactions(parallel_database):
    for check in ('log_only_verification.sql', 'completion_verification.sql',
                  'workbench_connection_verification.sql'):
        output = parallel_database((ROOT / 'supabase/checks' / check).read_text())
        if check == 'completion_verification.sql':
            reports = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
            assert len(reports) == 1 and reports[0]['all_passed'] is True


def test_latency_profile_allowlist_is_exact_and_intake_uses_it(parallel_database):
    run = parallel_database
    baseline_prompts = {
        'agent1': 'error-analysis-extraction-v1', 'agent2': 'error-analysis-v1',
        'agent3': 'error-analysis-summary-v1',
    }
    compact_prompts = {
        **baseline_prompts, 'agent1': 'error-analysis-extraction-compact-v2',
        'agent3': 'error-analysis-summary-compact-v2',
    }
    baseline_models = {
        'agent1': 'gpt-6-luna', 'agent2': 'gpt-6.1-sol', 'agent3': 'gpt-6.1-sol',
        'reasoning_effort': 'medium',
    }
    compact_models = {
        **baseline_models, 'agent1_reasoning_effort': 'medium',
        'agent2_reasoning_effort': 'medium', 'agent3_reasoning_effort': 'medium',
    }
    fast_models = {
        **compact_models, 'agent1_reasoning_effort': 'low', 'agent3_reasoning_effort': 'low',
    }

    def supported(prompts, models):
        return run(f"""
            select private.error_analysis_configuration_supported(
              '{json.dumps(prompts)}'::jsonb, '{json.dumps(models)}'::jsonb)
        """) == 't'

    assert supported(baseline_prompts, baseline_models)
    assert supported(compact_prompts, compact_models)
    assert supported(compact_prompts, fast_models)
    assert supported(compact_prompts, {**compact_models, 'agent3': 'gpt-6-luna'})
    assert supported(compact_prompts, {**compact_models, 'agent3_reasoning_effort': 'low'})
    assert supported(compact_prompts, {
        **compact_models, 'agent2': 'gpt-6-luna', 'agent3': 'gpt-6-luna',
    })
    assert not supported(compact_prompts, {**compact_models, 'agent2': 'gpt-6-luna'})
    assert not supported(baseline_prompts, fast_models)
    assert not supported(compact_prompts, baseline_models)
    assert not supported(compact_prompts, {**fast_models, 'agent2_reasoning_effort': 'low'})
    assert not supported(compact_prompts, {**fast_models, 'agent1': 'different-model'})
    assert not supported(compact_prompts, {**fast_models, 'extra': 'unreviewed'})
    assert not supported({**compact_prompts, 'agent1': 'unknown-prompt'}, fast_models)
    assert not supported({**compact_prompts, 'extra': 'unreviewed'}, fast_models)
    assert not supported(None, None)
    assert run("""
        select strpos(pg_get_functiondef(
          'private.commit_error_analysis_intake_before_workbench(jsonb)'::regprocedure),
          'if not private.error_analysis_configuration_supported(')>0
    """) == 't'


def test_simultaneous_claims_and_budget_reservations_remain_bounded(parallel_database):
    run = parallel_database
    run("""
    do $$ declare w uuid; c uuid; a uuid; r uuid; begin
      for i in 1..4 loop
        insert into public.workspaces(name,synthetic) values('Parallel race '||i,true)
          returning id into w;
        insert into public.cases(workspace_id,title,workflow_version,due_at)
          values(w,'Parallel race '||i,'error-analysis-v1',now()) returning id into c;
        insert into public.attempts(workspace_id,case_id,attempt_key,result)
          values(w,c,'race','unknown') returning id into a;
        insert into public.analysis_runs(workspace_id,case_id,attempt_id,snapshot_hash,snapshot,
          case_version,requested_by,workflow_version)
          values(w,c,a,repeat('a',64),'{}',1,'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','error-analysis-v1')
          returning id into r;
        update public.cases set current_attempt_id=a,requested_run_id=r where id=c;
        insert into public.jobs(workspace_id,run_id) values(w,r);
      end loop;
    end $$;
    """)

    def claim(index):
        return json.loads(run(f"""
            set role service_role;
            select public.cfin_claim_job('{{"worker_id":"racer-{index}"}}');
        """))

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(claim, range(6)))
    claims = [result for result in results if result['claimed']]
    assert len(claims) == 2
    assert len({result['job']['id'] for result in claims}) == 2
    assert len({result['job']['workspace_id'] for result in claims}) == 2
    assert run("select count(*) from public.jobs where state='running'") == '2'

    def reserve(claim):
        payload = {
            'job_id': claim['job']['id'], 'lease_token': claim['job']['lease_token'],
            'stage': 'agent_1', 'invocation': 0, 'model_id': 'gpt-6.1-sol',
            'max_input_tokens': 100, 'max_output_tokens': 100,
            'monthly_budget_usd': 0.0015,
        }
        try:
            return json.loads(run(f"""
                set role service_role;
                select public.cfin_reserve_call('{json.dumps(payload)}');
            """))
        except AssertionError as exc:
            assert 'Model budget exhausted' in str(exc)
            return {'budget_blocked': True}

    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(reserve, claims))
    assert sum(result.get('execute', False) for result in reservations) == 1
    assert sum(result.get('budget_blocked', False) for result in reservations) == 1
    assert run('select sum(reserved_usd) from public.stage_calls') == '0.001250'
