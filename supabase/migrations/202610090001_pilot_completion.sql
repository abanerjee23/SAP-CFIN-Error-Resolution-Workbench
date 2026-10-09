-- Complete the human-controlled Error Analysis pilot without altering legacy cases.
begin;
alter table public.error_taxonomy enable row level security;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='error_taxonomy' and policyname='taxonomy_read') then
  create policy taxonomy_read on public.error_taxonomy for select to authenticated using(true);
 end if;
end $$;
alter table private.read_credentials enable row level security;
alter table private.read_snapshots enable row level security;
alter table private.machine_read_audit enable row level security;

alter table public.error_route_milestones add column posting_reference text;

create or replace function private.error_route_action(p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role';
 c public.cases; policy public.error_route_policies; step jsonb; order_n integer;
 decision text:=p->'data'->>'decision'; proof_ids jsonb:=coalesce(p->'data'->'evidence_ids','[]');
 key text; digest text; receipt private.action_receipts; result jsonb; note text;
begin
 perform private.require_actor(w,a,r);
 key:=private.nonempty(p->>'request_key','request_key');
 digest:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
 perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||key,2));
 select * into receipt from private.action_receipts where workspace_id=w and actor_id=a and request_key=key;
 if found then
  if receipt.payload_hash<>digest then raise sqlstate 'PT409' using message='Action key content conflict'; end if;
  return receipt.response;
 end if;
 select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
 if not found or c.workflow_version<>'error-analysis-v1' or c.version is distinct from (p->>'expected_version')::bigint or c.linked_case_id is not null then
  raise sqlstate 'PT409' using message='Current canonical Error Analysis case version required';
 end if;
 if c.route_state in ('escalated','completed') or c.analysis_status<>'available' then
  raise sqlstate 'PT422' using message='An available analysis and open route are required';
 end if;
 select * into policy from public.error_route_policies where id=c.route_policy_id and version=c.route_policy_version for share;
 if not found then raise sqlstate 'PT409' using message='Saved route policy unavailable'; end if;
 order_n:=coalesce((select max(step_order)+1 from public.error_route_milestones where workspace_id=w and case_id=c.id and policy_id=policy.id and policy_version=policy.version),1);
 step:=policy.steps->(order_n-1);
 if step is null then raise sqlstate 'PT422' using message='Route is already complete'; end if;
 if step->>'required_role' is distinct from r then raise insufficient_privilege using message='The configured route role is required'; end if;
 note:=private.nonempty(p->'data'->>'note','note');
 if length(note)>10000 or jsonb_typeof(proof_ids) is distinct from 'array' then raise sqlstate 'PT422' using message='Bounded note and proof list required'; end if;
 if jsonb_array_length(proof_ids)>20 or exists(select 1 from jsonb_array_elements_text(proof_ids) id where not exists(select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.id=id::uuid and e.kind='proof' and e.work_cycle=c.work_cycle)) then raise sqlstate 'PT422' using message='Each route evidence ID must be saved proof for this case and work cycle'; end if;
 if (step->>'requires_evidence'='true' or step->>'kind'='record_posting_outcome') and jsonb_array_length(proof_ids)=0 then raise sqlstate 'PT422' using message='Saved evidence is required for this route step'; end if;
 -- requires_approval on implementation means a prior approval, not a new MDG decision.
 if step->>'kind' in ('record_process_owner_decision','review_and_approve_mapping') then
  if decision is null or decision not in ('approved','rejected') then raise sqlstate 'PT422' using message='Record an explicit approval or rejection'; end if;
 elsif step->>'kind'='record_posting_outcome' then
  if decision is null or decision not in ('completed','failed') then raise sqlstate 'PT422' using message='Record an explicit posting success or failure'; end if;
  if decision='completed' then perform private.nonempty(p->'data'->>'posting_reference','posting reference'); end if;
 elsif decision is not null then raise sqlstate 'PT422' using message='This step does not accept a decision'; end if;
 if policy.category_id='master_data' and order_n>2 and not exists(select 1 from public.error_route_milestones m where m.workspace_id=w and m.case_id=c.id and m.policy_id=policy.id and m.policy_version=policy.version and m.step_order=2 and m.decision='approved') then raise sqlstate 'PT422' using message='Recorded Process Owner approval is required before master-data implementation'; end if;
 if policy.category_id='mapping' and order_n>3 and not exists(select 1 from public.error_route_milestones m where m.workspace_id=w and m.case_id=c.id and m.policy_id=policy.id and m.policy_version=policy.version and m.step_order=3 and m.decision='approved') then raise sqlstate 'PT422' using message='Recorded Process Owner approval is required before reprocessing'; end if;
 insert into public.error_route_milestones(workspace_id,case_id,policy_id,policy_version,step_order,step_id,decision,evidence_ids,note,actor_id,acting_role,posting_reference)
 values(w,c.id,policy.id,policy.version,order_n,step->>'step_id',coalesce(decision,'completed'),proof_ids,note,a,r,case when step->>'kind'='record_posting_outcome' then p->'data'->>'posting_reference' end);
 update public.cases set route_state=case when decision in ('rejected','failed') or policy.route_kind<>'pilot' then 'escalated' when order_n=jsonb_array_length(policy.steps) then 'completed' else 'in_progress' end,
 status=case when decision in ('rejected','failed') or policy.route_kind<>'pilot' then 'blocked' when step->>'kind'='record_posting_outcome' then 'document_reprocessed' else 'in_progress' end,version=version+1 where id=c.id returning * into c;
 perform private.audit(w,c.id,a,r,'route_step_recorded',null,p->'data'||jsonb_build_object('step_id',step->>'step_id'),note);
 result:=jsonb_build_object('saved',true,'case',to_jsonb(c));
 insert into private.action_receipts values(w,a,key,digest,result);
 return result;
end $$;

create function private.error_workbench_action(p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role';
 c public.cases; body jsonb:=coalesce(p->'data','{}'); action text:=p->>'action';
 key text; digest text; receipt private.action_receipts; result jsonb; note text; n integer;
 proof_ids jsonb:=coalesce(p->'data'->'evidence_ids','[]');
begin
 perform private.require_actor(w,a,r);
 key:=private.nonempty(p->>'request_key','request_key'); digest:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
 perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||key,2));
 select * into receipt from private.action_receipts where workspace_id=w and actor_id=a and request_key=key;
 if found then if receipt.payload_hash<>digest then raise sqlstate 'PT409' using message='Action key content conflict'; end if; return receipt.response; end if;
 select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
 if not found or c.workflow_version<>'error-analysis-v1' or c.version is distinct from (p->>'expected_version')::bigint or c.linked_case_id is not null then raise sqlstate 'PT409' using message='Current canonical Error Analysis case required'; end if;
 note:=private.nonempty(body->>'note','note');
 if length(note)>10000 then raise sqlstate 'PT422' using message='Note too long'; end if;
 if action='finish_resolution' then
  if r not in ('data_operations','process_owner') then raise insufficient_privilege using message='Data Operations or Process Owner required'; end if;
  if c.route_state<>'completed' or c.status<>'document_reprocessed' or body->'human_confirmed' is distinct from 'true'::jsonb or exists(select 1 from public.resolution_records where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle) then raise sqlstate 'PT422' using message='Successful route and human validation are required before closure'; end if;
  if jsonb_typeof(proof_ids) is distinct from 'array' then raise sqlstate 'PT422' using message='Saved validation evidence required'; end if;
  if jsonb_array_length(proof_ids) not between 1 and 20 or exists(select 1 from jsonb_array_elements_text(proof_ids) id where not exists(select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.id=id::uuid and e.kind='proof' and e.work_cycle=c.work_cycle)) then raise sqlstate 'PT422' using message='Saved validation evidence for this case required'; end if;
  perform private.nonempty(body->>'posting_reference','posting reference');
  if not exists(select 1 from public.error_route_milestones m where m.workspace_id=w and m.case_id=c.id and m.policy_id=c.route_policy_id and m.policy_version=c.route_policy_version and m.step_id='posting_outcome' and m.decision='completed' and m.posting_reference=body->>'posting_reference') then raise sqlstate 'PT422' using message='Validate the saved successful posting reference'; end if;
  insert into public.resolution_records(workspace_id,case_id,attempt_id,work_cycle,version,record,resolver_id,resolved_at)
  values(w,c.id,c.current_attempt_id,c.work_cycle,1,body||jsonb_build_object('workflow_version','error-analysis-v1','provenance','human_resolution','cause_confirmed',false),a,clock_timestamp());
  update public.cases set status='complete' where id=c.id;
 elsif action='assign' then
  if r<>'cfin_exception_manager' then raise insufficient_privilege using message='CFIN Exception Manager required'; end if;
  if not exists(select 1 from public.workspace_memberships m where m.workspace_id=w and m.user_id=(body->>'assigned_user_id')::uuid and body->>'owner_role'=any(m.roles)) then raise sqlstate 'PT422' using message='Select a workspace member with the required role'; end if;
  select coalesce(max(version),0)+1 into n from public.assignments where workspace_id=w and case_id=c.id;
  insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason) values(w,c.id,n,(body->>'assigned_user_id')::uuid,body->>'owner_role',a,r,note);
 elsif action<>'comment' then raise sqlstate 'PT422' using message='Unsupported Error Analysis action'; end if;
 update public.cases set version=version+1 where id=c.id returning * into c;
 perform private.audit(w,c.id,a,r,'case_'||action,null,body,note);
 result:=jsonb_build_object('case',to_jsonb(c),'saved',true);
 insert into private.action_receipts values(w,a,key,digest,result);
 return result;
end $$;
create function public.cfin_error_workbench_action(payload jsonb) returns jsonb language sql security invoker set search_path='' as $$ select private.error_workbench_action(payload); $$;
revoke all on function private.error_workbench_action(jsonb),public.cfin_error_workbench_action(jsonb) from public,anon,authenticated,service_role;
grant execute on function private.error_workbench_action(jsonb),public.cfin_error_workbench_action(jsonb) to authenticated;
-- Fence the older generic command endpoint too; clients cannot bypass route guards.
alter function private.case_action(jsonb) rename to case_action_before_pilot;
create function private.case_action(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if exists(select 1 from public.cases where workspace_id=(p->>'workspace_id')::uuid and id=(p->>'case_id')::uuid and workflow_version='error-analysis-v1') then
  if p->>'action'='record_route_step' then return private.error_route_action(p); end if;
  return private.error_workbench_action(p);
 end if;
 return private.case_action_before_pilot(p);
end $$;
revoke all on function private.case_action_before_pilot(jsonb),private.case_action(jsonb) from public,anon,authenticated,service_role;
grant execute on function private.case_action(jsonb) to authenticated;

-- Retry only failed analyses that have no recorded business steps.
alter function private.enqueue(uuid,uuid,uuid) rename to enqueue_before_pilot;
create function private.enqueue(w uuid,c_id uuid,a uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.cases;
begin
 select * into c from public.cases where workspace_id=w and id=c_id for update;
 if c.workflow_version='error-analysis-v1' then
  if c.analysis_status<>'unavailable' or c.route_state<>'not_started' or exists(select 1 from public.error_route_milestones where workspace_id=w and case_id=c_id) then raise sqlstate 'PT422' using message='Only failed analyses with no recorded route work can be retried'; end if;
  return private.error_analysis_enqueue(w,c_id,a);
 end if;
 return private.enqueue_before_pilot(w,c_id,a);
end $$;
revoke all on function private.enqueue(uuid,uuid,uuid),private.enqueue_before_pilot(uuid,uuid,uuid) from public,anon,authenticated,service_role;

create or replace function private.case_resolved(c public.cases) returns boolean language sql stable security definer set search_path='' as $$
 select case when c.workflow_version='error-analysis-v1' then c.status='complete' and exists(select 1 from public.resolution_records r where r.workspace_id=c.workspace_id and r.case_id=c.id and r.work_cycle=c.work_cycle) else coalesce(c.status='document_reprocessed' and c.attempt_order_known and not c.unreviewed_new_failure
  and exists(select 1 from public.attempts a where a.workspace_id=c.workspace_id and a.case_id=c.id and a.id=c.current_attempt_id and a.result='successful' and a.validation_status='passed')
  and exists(select 1 from public.resolution_records r where r.workspace_id=c.workspace_id and r.case_id=c.id and r.attempt_id=c.current_attempt_id and r.work_cycle=c.work_cycle)
  and (c.workflow_version='log-only-v1' or (
   exists(select 1 from public.milestones m where m.workspace_id=c.workspace_id and m.case_id=c.id and m.attempt_id=c.current_attempt_id and m.work_cycle=c.work_cycle and m.kind='reprocessing')
   and (select m.details->>'status' from public.milestones m where m.workspace_id=c.workspace_id and m.case_id=c.id and m.attempt_id=c.current_attempt_id and m.work_cycle=c.work_cycle and m.kind='validation' order by m.recorded_at desc,m.id desc limit 1)='passed'
   and exists(select 1 from public.milestones m where m.workspace_id=c.workspace_id and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='correction'
    and m.id=(select latest.id from public.milestones latest where latest.workspace_id=c.workspace_id and latest.case_id=c.id and latest.work_cycle=c.work_cycle and latest.kind='correction' order by latest.recorded_at desc,latest.id desc limit 1)
    and exists(select 1 from public.milestone_proof mp where mp.workspace_id=c.workspace_id and mp.milestone_id=m.id)
    and not exists(select 1 from public.milestone_proof mp where mp.workspace_id=c.workspace_id and mp.milestone_id=m.id and not exists(select 1 from public.proof_applicability pa where pa.workspace_id=c.workspace_id and pa.case_id=c.id and pa.attempt_id=c.current_attempt_id and pa.work_cycle=c.work_cycle and pa.evidence_id=mp.evidence_id)))
  )),false) end;
$$;
commit;
