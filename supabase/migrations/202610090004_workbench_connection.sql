-- Persist the approved workbench controls and the owner's clarified closure rule.
begin;
update storage.buckets set allowed_mime_types=array_append(allowed_mime_types,'message/rfc822')
 where id='evidence' and not ('message/rfc822'=any(allowed_mime_types));

create or replace function private.error_workbench_action(p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role';
 c public.cases; body jsonb:=coalesce(p->'data','{}'); action text:=p->>'action';
 key text; digest text; receipt private.action_receipts; result jsonb; note text; n integer;
 proofs jsonb:=coalesce(body->'evidence_ids','[]'); owner public.assignments; is_owner boolean;
 synthetic_workspace boolean; resolution jsonb;
begin
 perform private.require_actor(w,a,r);
 if r not in ('mdg_process_owner','process_owner','data_operations','cfin_exception_manager') then
  raise insufficient_privilege using message='Workbench persona required';
 end if;
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
  raise sqlstate 'PT409' using message='Current canonical case version required';
 end if;
 select * into owner from public.assignments where workspace_id=w and case_id=c.id order by version desc limit 1;
 is_owner:=coalesce(owner.assigned_user_id=a and owner.owner_role=r,false);
 select synthetic into synthetic_workspace from public.workspaces where id=w;
 note:=private.nonempty(body->>'note','note');
 if length(note)>10000 or jsonb_typeof(proofs) is distinct from 'array' then raise sqlstate 'PT422' using message='Bounded note and proof list required'; end if;
 if jsonb_array_length(proofs)>20 or exists(
  select 1 from jsonb_array_elements_text(proofs) id where not exists(
   select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.id=id::uuid
    and e.kind='proof' and e.work_cycle=c.work_cycle and e.attempt_id=c.current_attempt_id)) then
  raise sqlstate 'PT422' using message='Saved evidence for this case and work cycle required';
 end if;
 if action='finish_resolution' then
  if not is_owner and r<>'cfin_exception_manager' then raise insufficient_privilege using message='Current owner or CFIN Exception Manager required'; end if;
  if body->'human_confirmed' is distinct from 'true'::jsonb or body->>'reprocessing_status' is distinct from 'successful'
   or body->>'validation_status' is distinct from 'passed' then
   raise sqlstate 'PT422' using message='Confirm successful reprocessing and system data validation';
  end if;
  perform private.nonempty(body->>'posting_reference','target document reference');
  if exists(select 1 from public.resolution_records where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle) then
   raise sqlstate 'PT409' using message='Case is already closed';
  end if;
  if not exists(select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id
   and e.id in (select value::uuid from jsonb_array_elements_text(proofs)) and e.content_type in ('image/png','image/jpeg')) then
   raise sqlstate 'PT422' using message='A saved proof screenshot is required';
  end if;
  if synthetic_workspace and body->>'provenance' is distinct from 'synthetic' then
   raise sqlstate 'PT422' using message='Synthetic workspace closure must be labelled synthetic';
  end if;
  resolution:=body||jsonb_build_object('workflow_version','error-analysis-v1','cause_confirmed',false,
   'provenance',case when synthetic_workspace then 'synthetic' else 'human_attested' end,
   'verification_method','human_attestation_with_uploaded_screenshot','system_connection_verified',false);
  insert into public.resolution_records(workspace_id,case_id,attempt_id,work_cycle,version,record,resolver_id,resolved_at)
   values(w,c.id,c.current_attempt_id,c.work_cycle,1,resolution,a,clock_timestamp());
  -- Closing records an attested outcome. It does not fabricate earlier approvals or route steps.
  update public.cases set status='complete' where id=c.id;
 elsif action='assign' then
  if r<>'cfin_exception_manager' then raise insufficient_privilege using message='CFIN Exception Manager required'; end if;
  if body->>'owner_role' not in ('mdg_process_owner','process_owner','data_operations','cfin_exception_manager')
   or not exists(select 1 from public.workspace_memberships m where m.workspace_id=w and m.user_id=(body->>'assigned_user_id')::uuid and body->>'owner_role'=any(m.roles)) then
   raise sqlstate 'PT422' using message='Select a workspace member with the required role';
  end if;
  select coalesce(max(version),0)+1 into n from public.assignments where workspace_id=w and case_id=c.id;
  insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason)
   values(w,c.id,n,(body->>'assigned_user_id')::uuid,body->>'owner_role',a,r,note);
 elsif action='set_status' then
  if not is_owner and r<>'cfin_exception_manager' then raise insufficient_privilege using message='Current owner or manager required'; end if;
  if exists(select 1 from public.resolution_records where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle) then
   raise sqlstate 'PT422' using message='Closed cases cannot change status'; end if;
  if body->>'status' is null or body->>'status' not in ('created','in_progress','blocked') then raise sqlstate 'PT422' using message='Use closure to record a closed case'; end if;
  update public.cases set status=body->>'status' where id=c.id;
 elsif action='record_approval' then
  if jsonb_array_length(proofs)=0 or body->>'external_approver_role' is null
   or body->>'external_approver_role' not in ('mdg_process_owner','process_owner','data_operations','cfin_exception_manager') then
   raise sqlstate 'PT422' using message='External approver and approval evidence required'; end if;
  -- Author and external approver remain distinct in the immutable activity payload.
 elsif action is null or action<>'comment' then raise sqlstate 'PT422' using message='Unsupported workbench action';
 end if;
 update public.cases set version=version+1 where id=c.id returning * into c;
 perform private.audit(w,c.id,a,r,'case_'||action,null,body,note);
 result:=jsonb_build_object('case',to_jsonb(c),'saved',true);
 insert into private.action_receipts values(w,a,key,digest,result);
 return result;
end $$;
-- A later route action must not undo a recorded closure.
alter function private.error_route_action(jsonb) rename to error_route_action_before_workbench;
create function private.error_route_action(p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 perform private.require_actor((p->>'workspace_id')::uuid,auth.uid(),p->>'acting_role');
 -- Take the same case lock as closure; a concurrent action cannot reopen the case.
 perform 1 from public.cases where workspace_id=(p->>'workspace_id')::uuid and id=(p->>'case_id')::uuid for update;
 if exists(select 1 from private.action_receipts where workspace_id=(p->>'workspace_id')::uuid and actor_id=auth.uid() and request_key=p->>'request_key') then
  return private.error_route_action_before_workbench(p);
 end if;
 if exists(select 1 from public.resolution_records r join public.cases c on c.workspace_id=r.workspace_id and c.id=r.case_id
  where c.workspace_id=(p->>'workspace_id')::uuid and c.id=(p->>'case_id')::uuid and r.work_cycle=c.work_cycle) then
  raise sqlstate 'PT409' using message='Closed cases cannot record further route steps'; end if;
 return private.error_route_action_before_workbench(p);
end $$;
revoke all on function private.error_route_action_before_workbench(jsonb),private.error_route_action(jsonb) from public,anon,authenticated,service_role;
grant execute on function private.error_route_action(jsonb) to authenticated;
-- Preserve the existing local demo's explicit initial manager ownership in saved data.
-- This applies only to the synthetic multi-persona account; no live assignment rule changes.
alter function private.commit_error_analysis_intake(jsonb) rename to commit_error_analysis_intake_before_workbench;
create function private.commit_error_analysis_intake(p jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; w uuid:=(p->>'workspace_id')::uuid; a uuid:=(p->>'actor_id')::uuid; c uuid;
begin
 result:=private.commit_error_analysis_intake_before_workbench(p);
 c:=(result->>'case_id')::uuid;
 if result->'duplicate'='false'::jsonb
  and exists(select 1 from public.workspaces where id=w and synthetic)
  and exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=a
   and roles @> array['process_owner','mdg_process_owner','data_operations','cfin_exception_manager']) then
  insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason)
   values(w,c,1,a,'cfin_exception_manager',a,'process_owner','Initial manager assignment for the simulated persona demo');
  perform private.audit(w,c,a,'process_owner','case_assign',null,
   jsonb_build_object('owner_role','cfin_exception_manager','assigned_user_id',a,'synthetic',true),
   'Initial manager assignment for the simulated persona demo');
 end if;
 return result;
end $$;
revoke all on function private.commit_error_analysis_intake_before_workbench(jsonb),private.commit_error_analysis_intake(jsonb) from public,anon,authenticated,service_role;
grant execute on function private.commit_error_analysis_intake(jsonb) to service_role;
commit;
