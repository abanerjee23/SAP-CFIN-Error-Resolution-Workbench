"""Parse SQL and verify sensitive boundaries; live execution is a separate checkpoint."""

import re
from pathlib import Path

from pglast import parse_plpgsql, parse_sql

SQL = (Path(__file__).resolve().parents[2]
       / "supabase/migrations/202610010003_insights_knowledge.sql").read_text()
FUNCTIONS = {
    re.search(r"create function private\.(\w+)", d).group(1): d
    for d in re.findall(r"create function private\.\w+\b.*?\$\$;", SQL, re.S | re.I)
}


def test_sql_and_plpgsql_bodies_parse():
    assert parse_sql(SQL)
    for definition in FUNCTIONS.values():
        if "language plpgsql" in definition:
            assert parse_plpgsql(definition)


def test_snapshots_are_atomic_cached_by_actor_and_filter_and_expire():
    create = FUNCTIONS["create_overview_snapshot"]
    assert "auth.uid()" in create
    assert "user_id=a" in create
    assert "pg_advisory_xact_lock" in create
    assert "actor_id=a" in create and "filters=f" in create
    assert "expires_at>clock_timestamp()" in create
    assert "interval '5 minutes'" in SQL
    assert "insert into public.overview_members" in create
    assert "case_version" in SQL
    assert "linked_case_id is null" in create


def test_distinct_known_cases_provisional_identities_and_attempts_are_separate():
    create = FUNCTIONS["create_overview_snapshot"]
    assert "'unresolved_known_cases'" in create
    assert "'provisional_cases'" in create
    assert "coalesce(sum(attempt_count),0)" in create
    assert "identity_known" in create
    assert "c.document_number is not null" in create
    assert "t.id=c.current_attempt_id" in create
    assert "t.validation_status='passed'" in create
    assert "r.work_cycle=c.work_cycle" in create


def test_group_drilldown_rechecks_permissions_and_marks_live_changes():
    group = FUNCTIONS["overview_group"]
    assert "private.read_overview_snapshot(p)" in group
    assert "actor_id=a" in group
    assert "'changed_since_snapshot',c.version<>m.case_version" in group
    assert "when 'P3' then 0 when 'P2' then 1 else 2" in group
    assert "size not between 1 and 50" in group
    assert "g.case_ids @> jsonb_build_array(m.case_id)" in group


def test_agent4_reserves_against_shared_monthly_budget_and_fences_other_workers():
    reserve = FUNCTIONS["reserve_overview_call"]
    assert "private.worker_slot where singleton=1 for update" in reserve
    assert "from public.stage_calls where month_start=month" in reserve
    assert "from public.overview_runs where month_start=month" in reserve
    assert "amount>least(1,run_cap)" in reserve
    assert "least(cap,10,monthly_cap)" in reserve
    assert "expires_at>clock_timestamp()" in reserve
    assert "lease_token=run.id" in reserve
    finish = FUNCTIONS["complete_overview_call"]
    assert "lease_token=run.id and lease_until>clock_timestamp()" in finish
    assert "user_id=run.actor_id" in finish
    assert "count=(claim->>'count')::integer" in finish
    assert "state_value<>'usage_unknown'" in finish


def test_knowledge_publication_requires_all_actual_human_and_evaluation_prerequisites():
    review = FUNCTIONS["knowledge_review"]
    assert "auth.uid()" in review
    assert "private.require_actor(w,a,'process_owner')" in review
    assert "k.revision is distinct from" in review
    assert "'cause_status' is distinct from 'confirmed'" in review
    assert "jsonb_array_length(k.evidence)=0" in review
    assert "c.current_attempt_id<>r.attempt_id" in review
    assert "validation_status='passed'" in review
    assert "evaluation.knowledge_revision" not in review  # exact predicate below binds revision
    assert "knowledge_revision=k.revision" in review
    assert "policy_revision=policy.revision" in review
    assert "evaluation.critical_failures>policy.maximum_critical_failures" in review
    assert "private.validate_case_citations" in review


def test_search_returns_only_currently_approved_scoped_versions_with_differences():
    search = FUNCTIONS["search_history"]
    assert "private.knowledge_member(p)" in search
    assert "k.workspace_id=w and k.reuse_state='approved'" in search
    assert "ts_rank_cd" in search
    assert "OPERATOR(extensions.<=>)" in search
    assert "'matching_facts'" in search and "'differing_facts'" in search
    assert "'local_concept_hashing_not_a_learned_embedding'" in search
    assert "create extension if not exists vector" in SQL


def test_withdrawal_is_immediate_and_prevents_inflight_actionable_promotion():
    withdraw = FUNCTIONS["withdraw_knowledge"]
    assert "reuse_state='withdrawn',revision=revision+1" in withdraw
    assert "historical_knowledge_withdrawn" in withdraw
    assert "analysis_status='needs_refresh'" in withdraw
    assert "work_cycle=" not in withdraw and "status='in_progress'" not in withdraw
    promotion = FUNCTIONS["complete_run"]
    assert "for share of k" in promotion
    assert "k.reuse_state<>'approved' or k.revision<>h.knowledge_revision" in promotion
    assert "jsonb_build_object('succeeded',false" in promotion
    assert "private.complete_run_base(p)" in promotion


def test_only_service_can_reserve_commit_attest_or_register_history():
    allowlists = SQL[SQL.index("user_names text[]") :]
    users = allowlists.split("shared_names text[]")[0]
    services = allowlists.split("service_names text[]")[1].split("begin")[0]
    for name in (
        "reserve_overview_call", "complete_overview_call", "attest_knowledge_evaluation",
        "register_run_history",
    ):
        assert f"'{name}'" in services and f"'{name}'" not in users
    assert "from public,anon,authenticated,service_role" in allowlists
    assert "reviewed_or_reviewer" in SQL
    assert "immutable_history_sources" in SQL


def test_no_fixture_or_migration_invents_human_approval():
    prefix = SQL[:SQL.index("create function")]
    assert "insert into public.knowledge_versions" not in prefix
    assert "insert into public.knowledge_publication_policies" not in prefix
    assert "insert into public.knowledge_evaluation_attestations" not in prefix
