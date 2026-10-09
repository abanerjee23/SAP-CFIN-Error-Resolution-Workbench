-- Approval decisions retain their supporting evidence with the case.
begin;
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
 if (step->>'requires_evidence'='true' or step->>'kind' in ('record_posting_outcome','record_process_owner_decision','review_and_approve_mapping')) and jsonb_array_length(proof_ids)=0 then raise sqlstate 'PT422' using message='Saved evidence is required for this route step'; end if;
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
commit;
