"""Check SQL and PL/pgSQL syntax plus security-sensitive migration boundaries.

These checks do not execute grants, RLS, constraints, or concurrency. Those
remain integration checkpoints on the configured isolated Supabase database.
"""

import re
from pathlib import Path

import pytest
from pglast import parse_plpgsql, parse_sql

PATH = Path(__file__).resolve().parents[2] / "supabase/migrations/202610010001_workflow.sql"
SQL = PATH.read_text()
FUNCTIONS = {
    re.search(r"create function private\.(\w+)", definition).group(1): definition
    for definition in re.findall(r"create function private\.\w+\b.*?\$\$;", SQL, re.S | re.I)
}
SERVICE = {
    "commit_intake",
    "register_evidence",
    "claim_job",
    "heartbeat_job",
    "reserve_call",
    "reconcile_call",
    "complete_run",
}
HUMAN = {"review_reference", "enqueue_run", "case_action"}


def test_workflow_sql_and_each_plpgsql_body_parse():
    assert parse_sql(SQL)
    for definition in FUNCTIONS.values():
        if "language plpgsql" in definition:
            assert parse_plpgsql(definition), definition.splitlines()[0]
    # Dynamic public wrappers must themselves be valid SQL; ordinary parsing of
    # the surrounding DO block does not examine generated statements.
    for name in SERVICE | HUMAN:
        assert parse_sql(
            f"create function public.cfin_{name}(payload jsonb) returns jsonb "
            "language sql security invoker set search_path='' "
            f"as $$ select private.{name}(payload); $$;"
        )


def test_finalize_and_worker_rpcs_are_excluded_from_authenticated_allowlist():
    block = SQL[SQL.index("service_names text[]") :]
    service_part = block.split("user_names text[]")[0]
    user_part = block.split("user_names text[]")[1].split("begin")[0]
    assert set(re.findall(r"'([a-z_]+)'", service_part)) == SERVICE
    assert set(re.findall(r"'([a-z_]+)'", user_part)) == HUMAN
    assert SERVICE.isdisjoint(HUMAN)
    assert "revoke execute on all functions in schema private" in SQL
    assert "from public,anon,authenticated,service_role" in SQL
    assert "security invoker" in block
    assert "grant execute on function public.cfin_%I(jsonb) to service_role" in block


@pytest.mark.parametrize("name", sorted(SERVICE | HUMAN))
def test_privileged_implementations_pin_search_path(name):
    assert "security definer set search_path=''" in FUNCTIONS[name]


@pytest.mark.parametrize("name", sorted(HUMAN))
def test_human_actions_derive_actual_actor_and_recheck_membership(name):
    definition = FUNCTIONS[name]
    assert "auth.uid()" in definition
    assert "private.require_actor(w,a,r)" in definition
    assert "(p->>'actor_id')::uuid" not in definition
    assert "public.workspace_memberships" in FUNCTIONS["require_actor"]
    assert "r=any(roles)" in FUNCTIONS["require_actor"]


def test_storage_is_verified_before_intake_can_create_a_job():
    intake = FUNCTIONS["commit_intake"]
    register = FUNCTIONS["register_evidence"]
    assert intake.index("private.register_evidence") < intake.index("private.enqueue")
    assert "storage.objects" in register
    assert "bucket_id='evidence'" in register
    assert "stored_size is distinct from" in register
    assert "Verified storage metadata required" in register
    assert "create policy" not in register
    assert "for insert to authenticated" not in SQL


def test_delivery_conflicts_do_not_queue_or_overwrite_the_prior_intake():
    definition = FUNCTIONS["commit_intake"]
    assert "pg_advisory_xact_lock" in definition
    assert "intake.payload_sha256<>payload_hash" in definition
    assert "'PT409'" in definition
    assert "'duplicate',true" in definition
    assert "update public.intakes" not in SQL
    assert "update public.attempts set result" not in SQL
    assert "'40001'" not in SQL


def test_snapshots_use_the_nine_saved_inputs_and_exclude_proof_or_oracles():
    definition = FUNCTIONS["enqueue"]
    for filename in (
        "original-log.txt",
        "manifest.json",
        "source-posting.json",
        "mapping-reference.json",
        "target-master-lookup.json",
        "target-master-query-audit.json",
        "missing-gl-master-playbook.json",
        "owner-directory.json",
        "source-catalogue.json",
    ):
        assert f"'{filename}'" in definition
    assert "'manifest',saved_manifest" in definition
    assert "kind in ('reference','guidance')" in definition
    assert "'proof'" not in definition
    assert "expected/" not in definition
    assert "simulated-proof/" not in definition
    assert "insert into public.run_sources" in definition
    assert "immutable_run_sources" in SQL
    assert "new.snapshot is distinct from old.snapshot" in FUNCTIONS["preserve_run_input"]


def test_promotion_checks_input_lineage_without_changing_human_milestones():
    definition = FUNCTIONS["complete_run"]
    assert "c.current_attempt_id=run.attempt_id" in definition
    assert "c.input_revision=run.input_revision" in definition
    assert "c.requested_run_id=run.id" in definition
    assert "c.version=run.case_version" not in definition
    assert "rev.decision in ('withdrawn','rejected')" in definition
    assert "c.attempt_order_known" in definition
    assert "when c.diagnosis_status='human_confirmed' then c.diagnosis_status" in definition
    assert "status='in_progress'" not in definition
    assert "priority=" not in definition
    assert "due_at=" not in definition
    assert "public.assignments" not in definition
    assert "public.milestones" not in definition


def test_lease_is_global_and_fences_heartbeat_output_and_cost_mutations():
    claim = FUNCTIONS["claim_job"]
    assert "private.worker_slot where singleton=1 for update" in claim
    assert claim.index("private.worker_slot") < claim.index("from public.jobs")
    assert "for update skip locked limit 1" in claim
    assert "job.lease_token is distinct from token" in FUNCTIONS["require_lease"]
    assert "job.lease_until<=clock_timestamp()" in FUNCTIONS["require_lease"]
    for name in ("heartbeat_job", "reserve_call", "reconcile_call", "complete_run"):
        assert "private.require_lease" in FUNCTIONS[name]
    assert "set state='usage_unknown'" in claim


def test_budget_reservation_uses_registered_prices_and_keeps_unknown_usage_held():
    reserve = FUNCTIONS["reserve_call"]
    assert "private.model_prices" in reserve
    assert "expires_at>clock_timestamp()" in reserve
    assert "Known current model pricing required" in reserve
    assert "where month_start=month and state<>'not_sent'" in reserve
    assert "run_used+amount>least(1,run_cap)" in reserve
    assert "least(cap,10,monthly_cap)" in reserve
    assert "monthly_cap<=0 or monthly_cap>10 or run_cap<=0 or run_cap>1" in reserve
    assert "coalesce(actual_usd,reserved_usd)" in reserve
    assert "state_value='usage_unknown' then amount:=null" in FUNCTIONS["reconcile_call"]
    assert "max_input_tokens <= 131072" in SQL
    assert "max_output_tokens <= 8192" in SQL
    assert "'gpt-6-luna','openai-standard-2026-10-01',0.125,0.50" in SQL


def test_case_actions_require_stale_version_checks_and_audit_in_same_transaction():
    definition = FUNCTIONS["case_action"]
    assert "for update" in definition
    assert "c.version is distinct from (p->>'expected_version')::bigint" in definition
    assert "receipt.payload_hash<>hash" in definition
    assert definition.index("c.version is distinct") < definition.index("if action='assign'")
    assert "private.audit(w,c.id,a,r" in definition
    assert "insert into private.action_receipts" in definition
    assert "version=version+1" in definition


def test_proof_and_resolution_preserve_attempt_and_cycle_boundaries():
    proof = FUNCTIONS["attest_proof"]
    assert "workspace_id=w and case_id=c" in proof
    assert "kind='proof'" in proof
    assert "e.attempt_id is distinct from at_id or e.work_cycle is distinct from cycle" in proof
    assert "proof_reuse_reason" in proof
    action = FUNCTIONS["case_action"]
    assert "body->>'correction_applicable' is distinct from 'true'" in action
    assert "insert into public.attempts" in action
    assert "result='successful' and validation_status='passed'" in action
    assert "c.unreviewed_new_failure" in action
    assert "dim_count<>4" in action
    assert "'reuse_status','pending_review'" in action
    assert "set status='resolved'" not in action


def test_reference_review_requires_actual_actor_exact_version_and_a_reason():
    definition = FUNCTIONS["review_reference"]
    assert "e.source_version is distinct from p->>'source_version'" in definition
    assert "expected_review_version" in definition
    assert "private.nonempty(p->>'reason','reason')" in definition
    assert "Mapping owner review required" in definition
    assert "p->>'reference_kind' is distinct from expected_kind" in definition
    assert "p->'scope' is distinct from e.provenance->'reference_scope'" in definition
    # No seed introduces approval or a fabricated human reviewer.
    assert "insert into public.reference_reviews" not in SQL[: SQL.index("create function")]


def test_missing_proof_cannot_bypass_the_guard_through_sql_null_semantics():
    assert "jsonb_typeof(ids) is distinct from 'array'" in FUNCTIONS["attest_proof"]
    assert "body->'human_confirmed' is distinct from 'true'::jsonb" in FUNCTIONS["case_action"]
    assert "valid_milestone_proof" in SQL
    assert (
        "p.attempt_id=m.attempt_id and p.work_cycle=m.work_cycle"
        in FUNCTIONS["check_milestone_proof"]
    )


def test_normalized_result_proof_gates_reprocessing_and_validation():
    verified = FUNCTIONS["verified_proof"]
    assert "'identity' @> expected_identity" in verified
    assert "'actual_actor_id'=e.uploader_id::text" in verified
    assert "'synthetic'='true'::jsonb" in verified
    action = FUNCTIONS["case_action"]
    assert "observation->>'attempt_key' is distinct from body->>'attempt_key'" in action
    assert (
        "observation->>'target_document_reference' is distinct from "
        "attempt.target_document_reference"
        in action
    )
    assert "observation->'checks' is distinct from body->'checks'" in action


def test_block_before_start_does_not_bypass_human_review_or_authority():
    definition = FUNCTIONS["case_action"]
    resume = definition.split("elsif action='resume' then")[1].split("elsif action='priority'")[0]
    assert "if c.work_started_at is null" in resume
    assert "public.case_reviews" in resume
    assert "target_change_authority" in resume
    assert "approved_attributes" in resume


def test_cause_citations_resolve_against_the_saved_authorized_catalogue():
    definition = FUNCTIONS["validate_case_citations"]
    assert "run.output->'source_catalogue'" in definition
    assert "source->>'attempt_id' is distinct from citation->>'attempt_id'" in definition
    assert "source->'record_ids' ? (citation->>'record_id')" in definition
    assert "end_line>(source->>'line_count')::integer" in definition
    assert (
        "private.validate_case_citations(w,c.id,body->'cause_evidence')" in FUNCTIONS["case_action"]
    )


def test_late_outputs_are_preserved_without_promoting_or_releasing_another_lease():
    definition = FUNCTIONS["complete_run"]
    assert definition.index("insert into public.run_results") < definition.index(
        "private.require_lease"
    )
    assert "'promoted',false,'lease_rejected',true" in definition
    assert "unique (job_id,submitted_lease_token)" in SQL


def test_human_milestone_times_and_targets_are_checked_in_the_database():
    action = FUNCTIONS["case_action"]
    assert "private.action_time(body->>'occurred_at')" in action
    assert "result>clock_timestamp()" in FUNCTIONS["action_time"]
    assert "body->>'target_system' is distinct from c.target_system" in action
    assert "body->>'target_object' is distinct from c.business_context->>'target_account'" in action
    assert (
        "body->'scope'->>'company_code' is distinct from c.business_context->>'company_code'"
        in action
    )
