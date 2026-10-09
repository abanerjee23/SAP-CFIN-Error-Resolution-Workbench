-- Explicit process-owner defaults: actual accounts, exact scope, review expiry and audit.
begin;
create table public.owner_rules (
 id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.workspaces(id),
 category text not null check(category in ('missing_target_gl_master_data','missing_gl_mapping')),
 target_system text not null, target_client text not null, company_code text not null,
 chart_of_accounts text not null, interface text not null, version bigint not null check(version>0),
 assigned_user_id uuid, owner_role text not null check(owner_role in ('master_data_owner','mapping_owner')),
 active boolean not null, review_due date, actor_id uuid not null references auth.users(id),
 reason text not null check(length(btrim(reason))>0), configured_at timestamptz not null default now(),
 unique(workspace_id,id), unique(workspace_id,category,target_system,target_client,company_code,chart_of_accounts,interface,version),
 foreign key(workspace_id,assigned_user_id) references public.workspace_memberships(workspace_id,user_id),
 check(not active or (assigned_user_id is not null and review_due is not null)),
 check((category='missing_target_gl_master_data' and owner_role='master_data_owner') or (category='missing_gl_mapping' and owner_role='mapping_owner'))
);
alter table public.owner_rules enable row level security;
create policy member_read on public.owner_rules for select to authenticated using(private.is_member(workspace_id));
revoke all on public.owner_rules from public,anon,authenticated;
grant select on public.owner_rules to authenticated,service_role;
create trigger preserve_owner_rule before update or delete on public.owner_rules for each row execute function private.preserve_source();

alter function private.case_action(jsonb) rename to case_action_base;
revoke all on function private.case_action_base(jsonb) from public,anon,authenticated;
create or replace function private.case_action_base(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role'; action text:=case p->>'action' when 'review_diagnosis' then 'review' when 'start_work' then 'start' when 'record_correction' then 'correction' when 'record_reprocessing' then 'reprocessing' when 'record_validation' then 'validation' when 'finish_resolution' then 'resolution' else p->>'action' end;
  c public.cases; old_c jsonb; assigned uuid; body jsonb:=coalesce(p->'data','{}'); key text:=private.nonempty(p->>'request_key','request_key'); hash text;
  receipt private.action_receipts; result jsonb; milestone_id uuid; at_id uuid; attempt public.attempts; next_version integer; passed boolean; dim_count integer; reviewed_run uuid; observation jsonb;
begin
  perform private.require_actor(w,a,r);
  hash:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
  perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||key,2));
  select * into receipt from private.action_receipts where workspace_id=w and actor_id=a and request_key=key;
  if found then
    if receipt.payload_hash<>hash then raise sqlstate 'PT409' using message='Action key content conflict'; end if;
    return receipt.response;
  end if;
  select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Case not found'; end if;
  if c.version is distinct from (p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Case changed; refresh'; end if;
  if c.linked_case_id is not null then raise sqlstate 'PT409' using message='Use the linked canonical case'; end if;
  old_c:=to_jsonb(c); at_id:=c.current_attempt_id;
  select assigned_user_id into assigned from public.assignments where workspace_id=w and case_id=c.id order by version desc limit 1;
  if action in ('assign','priority','reopen','due_date','retry_notification') and r<>'process_owner' then raise insufficient_privilege using message='Process owner required'; end if;
  if action='validation' and r not in ('validator','process_owner') then raise insufficient_privilege using message='Validator required'; end if;
  if action not in ('assign','priority','reopen','due_date','retry_notification','validation') and r<>'process_owner' and assigned is distinct from a then raise insufficient_privilege using message='Assigned owner required'; end if;
  if action in ('correction','reprocessing','validation','resolution') and body->'human_confirmed' is distinct from 'true'::jsonb then
    raise sqlstate 'PT422' using message='Explicit human proof attestation required';
  end if;
  if action in ('correction','reprocessing','validation','resolution') then perform private.action_time(body->>'occurred_at'); end if;
  if body ? 'cause_confirmed' and jsonb_typeof(body->'cause_confirmed') is distinct from 'boolean' then
    raise sqlstate 'PT422' using message='Cause confirmation must be an explicit boolean';
  end if;
  if action='assign' then
    if body->>'assigned_user_id' is not null and not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=(body->>'assigned_user_id')::uuid and body->>'owner_role'=any(roles)) then raise sqlstate 'PT422' using message='Active owner membership required'; end if;
    select coalesce(max(version),0)+1 into next_version from public.assignments where workspace_id=w and case_id=c.id;
    insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason)
      values(w,c.id,next_version,(body->>'assigned_user_id')::uuid,body->>'owner_role',a,r,private.nonempty(body->>'reason','reason')) returning id into milestone_id;
    if body->>'assigned_user_id' is not null then insert into public.notifications(workspace_id,case_id,assignment_id,event_key) values(w,c.id,milestone_id,'assignment'); end if;
  elsif action='review' then
    reviewed_run:=coalesce((body->>'run_id')::uuid,c.published_run_id,c.requested_run_id);
    if reviewed_run is null or not exists(select 1 from public.analysis_runs where workspace_id=w and case_id=c.id and id=reviewed_run and state in ('succeeded','failed') and attempt_id=c.current_attempt_id and input_revision=c.input_revision and id in (c.published_run_id,c.requested_run_id)) then
      raise sqlstate 'PT422' using message='Current saved analysis or failure required before review';
    end if;
    if body->>'decision'='Corrected' then
      perform private.nonempty(body->'findings'->>'cause_label','corrected cause');
      perform private.nonempty(body->'findings'->>'explanation','corrected explanation');
      if body->'findings'->>'provenance' is distinct from 'human_correction' then raise sqlstate 'PT422' using message='Human correction must stay separate from AI'; end if;
      if jsonb_array_length(coalesce(body->'findings'->'citations','[]'))>0 then perform private.validate_case_citations(w,c.id,body->'findings'->'citations'); end if;
    end if;
    insert into public.case_reviews(workspace_id,case_id,run_id,decision,reason,cause_confirmed,findings,actor_id,acting_role)
      values(w,c.id,reviewed_run,body->>'decision',body->>'reason',coalesce((body->>'cause_confirmed')::boolean,false),coalesce(body->'findings','{}'),a,r);
    if c.status in ('created','owner_notified') and c.work_started_at is null then
      update public.cases set unreviewed_new_failure=false,review_flags=array_remove(review_flags,'new_failure_review_required') where id=c.id;
    end if;
    if coalesce((body->>'cause_confirmed')::boolean,false) then
      if jsonb_typeof(body->'cause_evidence') is distinct from 'array' or jsonb_array_length(body->'cause_evidence')=0 then raise sqlstate 'PT422' using message='Cause confirmation requires evidence'; end if;
      perform private.validate_case_citations(w,c.id,body->'cause_evidence');
      update public.cases set diagnosis_status='human_confirmed' where id=c.id;
    end if;
  elsif action='start' then
    if c.status not in ('created','owner_notified') and not (c.status='in_progress' and c.work_started_at is null) then raise sqlstate 'PT409' using message='Work already started'; end if;
    if not exists(select 1 from public.case_reviews review join public.analysis_runs reviewed on reviewed.workspace_id=review.workspace_id and reviewed.id=review.run_id where review.workspace_id=w and review.case_id=c.id and reviewed.attempt_id=c.current_attempt_id and reviewed.input_revision=c.input_revision and not reviewed.evaluation_only and reviewed.id in (c.published_run_id,c.requested_run_id)) then raise sqlstate 'PT422' using message='Human review required before work'; end if;
    if body->>'target_change_authority' is distinct from 'true' then raise sqlstate 'PT422' using message='Human target-change authority confirmation required'; end if;
    perform private.nonempty(body->>'approved_attributes','approved_attributes');
    update public.cases set status='in_progress',work_started_at=now() where id=c.id;
  elsif action='block' then
    if c.status not in ('created','owner_notified','in_progress') then raise sqlstate 'PT409' using message='Invalid block transition'; end if;
    perform private.nonempty(body->>'reason','reason'); update public.cases set status='blocked' where id=c.id;
  elsif action='resume' then
    if c.status<>'blocked' then raise sqlstate 'PT409' using message='Case is not blocked'; end if;
    if c.work_started_at is null then
      if not exists(select 1 from public.case_reviews review join public.analysis_runs reviewed on reviewed.workspace_id=review.workspace_id and reviewed.id=review.run_id where review.workspace_id=w and review.case_id=c.id and reviewed.attempt_id=c.current_attempt_id and reviewed.input_revision=c.input_revision and not reviewed.evaluation_only and reviewed.id in (c.published_run_id,c.requested_run_id))
        or body->'target_change_authority' is distinct from 'true'::jsonb then raise sqlstate 'PT422' using message='Human review and start-work authority are required before initial resume'; end if;
      perform private.nonempty(body->>'approved_attributes','approved_attributes');
    end if;
    perform private.nonempty(body->>'reason','reason'); update public.cases set status='in_progress',work_started_at=coalesce(work_started_at,now()) where id=c.id;
  elsif action='priority' then
    perform private.nonempty(body->>'reason','reason');
    update public.cases set priority=body->>'priority',due_at=least(due_at,private.business_due(now(),case when body->>'priority'='P3' then 1 else 2 end)) where id=c.id;
  elsif action='due_date' then
    perform private.nonempty(body->>'reason','reason');
    if coalesce(body->>'due_at','') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then raise sqlstate 'PT422' using message='Timezone-aware deadline required'; end if;
    update public.cases set due_at=(body->>'due_at')::timestamptz where id=c.id;
  elsif action='retry_notification' then
    perform private.nonempty(body->>'reason','reason');
    update public.notifications set state='queued',retry_count=0,available_at=clock_timestamp(),error_code=null,lease_token=null,lease_until=null
      where id=(body->>'notification_id')::uuid and workspace_id=w and case_id=c.id and state='failed';
    if not found then raise sqlstate 'PT409' using message='Select a failed notification for this case'; end if;
  elsif action='correction' then
    if c.status<>'in_progress' or c.work_started_at is null or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Started human-confirmed correction required'; end if;
    perform private.nonempty(body->>'explanation','explanation'); perform private.nonempty(body->>'target_system','target_system'); perform private.nonempty(body->>'target_object','target_object');
    if body->>'target_system' is distinct from c.target_system
      or body->>'target_object' is distinct from c.business_context->>'target_account' then
      raise sqlstate 'PT422' using message='Correction target must match the established case context';
    end if;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
    insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at)
      values(w,c.id,at_id,c.work_cycle,'correction',body,a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
    insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
  elsif action='complete_work' then
    if c.status<>'in_progress' or not exists(select 1 from public.milestones where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle and attempt_id=at_id and kind='correction') then raise sqlstate 'PT422' using message='Saved human-confirmed correction required'; end if;
    update public.cases set status='complete' where id=c.id;
  elsif action='reprocessing' then
    if c.status<>'complete' or not c.attempt_order_known or c.unreviewed_new_failure or coalesce(body->>'successful','true') is distinct from 'true' or body->>'correction_applicable' is distinct from 'true' or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Complete case and human-confirmed successful reprocessing required'; end if;
    perform private.nonempty(body->>'target_document_reference','target_document_reference');
    observation:=private.verified_proof(w,c.id,body->'proof_ids','reprocessing');
    if observation->>'result' is distinct from 'successful'
      or observation->>'attempt_key' is distinct from body->>'attempt_key'
      or (observation->>'processing_order')::bigint is distinct from (body->>'processing_order')::bigint
      or (observation->>'processing_at')::timestamptz is distinct from (body->>'processing_at')::timestamptz
      or observation->>'target_document_reference' is distinct from body->>'target_document_reference' then
      raise sqlstate 'PT422' using message='Reprocessing fields must match the saved verified result';
    end if;
    select * into attempt from public.attempts where id=at_id;
    if body->>'processing_order' is null or body->>'processing_at' is null or (body->>'processing_order')::bigint<=attempt.processing_order or (body->>'processing_at')::timestamptz<=attempt.processing_at then raise sqlstate 'PT422' using message='A later successful attempt is required'; end if;
    insert into public.attempts(workspace_id,case_id,attempt_key,processing_at,processing_order,result,target_document_reference)
      values(w,c.id,private.nonempty(body->>'attempt_key','attempt_key'),(body->>'processing_at')::timestamptz,(body->>'processing_order')::bigint,'successful',body->>'target_document_reference') returning id into at_id;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',coalesce(nullif(body->>'proof_reuse_reason',''),'Human confirms result proof and prior correction apply to this new successful attempt'));
    -- Preserve the original corrective milestone; explicitly attest applicability.
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,
      (select jsonb_agg(distinct mp.evidence_id) from public.milestones m join public.milestone_proof mp
        on mp.workspace_id=m.workspace_id and mp.milestone_id=m.id where m.workspace_id=w and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='correction'),
      'Human confirms prior corrective evidence applies to this successful attempt');
    insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at)
      values(w,c.id,at_id,c.work_cycle,'reprocessing',body,a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
    insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
    update public.cases set status='document_reprocessed',current_attempt_id=at_id,input_revision=input_revision+1,unreviewed_new_failure=false where id=c.id;
  elsif action='validation' then
    if c.status<>'document_reprocessed' or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Document reprocessed and human validation attestation required'; end if;
    if coalesce(body->>'status','') not in ('passed','failed') or jsonb_typeof(body->'checks') is distinct from 'array' then raise sqlstate 'PT422' using message='Validation checks required'; end if;
    observation:=private.verified_proof(w,c.id,body->'proof_ids','validation');
    select * into attempt from public.attempts where id=at_id;
    if observation->>'attempt_key' is distinct from attempt.attempt_key
      or observation->>'target_document_reference' is distinct from attempt.target_document_reference
      or observation->>'status' is distinct from body->>'status' or observation->'checks' is distinct from body->'checks' then
      raise sqlstate 'PT422' using message='Validation must match server-computed posting checks for the current attempt';
    end if;
    select count(distinct x->>'dimension') into dim_count from jsonb_array_elements(body->'checks') x where x->>'dimension' in ('amount_currency','company','accounts','source_target_reference');
    passed:=body->>'status'='passed';
    if passed and (dim_count<>4 or jsonb_array_length(body->'checks')<>4 or exists(select 1 from jsonb_array_elements(body->'checks') x where coalesce(x->>'result','') not in ('passed','not_applicable') or nullif(btrim(x->>'expected'),'') is null or nullif(btrim(x->>'observed'),'') is null or (x->>'result'='not_applicable' and nullif(btrim(x->>'reason'),'') is null))) then raise sqlstate 'PT422' using message='All four posting checks must pass or have justified exceptions'; end if;
    if not passed and not exists(select 1 from jsonb_array_elements(body->'checks') x where x->>'result'='failed' and nullif(btrim(x->>'reason'),'') is not null) then raise sqlstate 'PT422' using message='Failed validation needs discrepancy evidence'; end if;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
    insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at)
      values(w,c.id,at_id,c.work_cycle,'validation',body,a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
    insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
    update public.attempts set validation_status=body->>'status' where id=at_id;
  elsif action='resolution' then
    if c.status<>'document_reprocessed' or not c.attempt_order_known or c.unreviewed_new_failure or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Current successful reprocessing required'; end if;
    if not exists(select 1 from public.attempts where id=at_id and result='successful' and validation_status='passed') then raise sqlstate 'PT422' using message='Current attempt validation must pass'; end if;
    perform private.nonempty(body->>'correction_or_no_change','correction_or_no_change'); perform private.nonempty(body->>'outcome','outcome'); perform private.nonempty(body->'scope'->>'reuse_limitations','reuse_limitations'); perform private.nonempty(body->'scope'->>'target_system','target_system'); perform private.nonempty(body->'scope'->>'target_object','target_object'); perform private.nonempty(body->'scope'->>'company_code','company_code');
    if body->'scope'->>'target_system' is distinct from c.target_system
      or body->'scope'->>'target_object' is distinct from c.business_context->>'target_account'
      or body->'scope'->>'company_code' is distinct from c.business_context->>'company_code' then
      raise sqlstate 'PT422' using message='Resolution scope must match the established case context';
    end if;
    if body->>'cause_status'='confirmed' then
      if coalesce(body->>'cause','') not in ('missing_target_gl_master_data','missing_gl_mapping','closed_target_posting_period') or jsonb_typeof(body->'cause_evidence') is distinct from 'array' or jsonb_array_length(body->'cause_evidence')=0 then raise sqlstate 'PT422' using message='Confirmed cause requires evidence'; end if;
      perform private.validate_case_citations(w,c.id,body->'cause_evidence');
    elsif body->>'cause_status'='not_confirmed' then
      if body->>'cause' is not null or jsonb_typeof(body->'unresolved_gaps') is distinct from 'array' or jsonb_array_length(body->'unresolved_gaps')=0 then raise sqlstate 'PT422' using message='Unconfirmed cause needs unresolved gaps and no confirmed label'; end if;
    else raise sqlstate 'PT422' using message='Cause status required'; end if;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
    select coalesce(max(version),0)+1 into next_version from public.resolution_records where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle;
    insert into public.resolution_records(workspace_id,case_id,attempt_id,work_cycle,version,record,resolver_id,resolved_at)
      values(w,c.id,at_id,c.work_cycle,next_version,body||jsonb_build_object('reuse_status','pending_review'),a,private.action_time(body->>'occurred_at'));
  elsif action='reopen' then
    perform private.nonempty(body->>'reason','reason');
    if coalesce(body->>'status','') not in ('in_progress','blocked') then raise sqlstate 'PT422' using message='Reopen status must be active'; end if;
    update public.cases set status=body->>'status',work_cycle=work_cycle+1,work_started_at=null,unreviewed_new_failure=false,due_at=private.business_due(now(),case when priority='P3' then 1 else 2 end) where id=c.id;
    update public.attempts set validation_status='pending' where id=at_id;
    insert into public.notifications(workspace_id,case_id,assignment_id,event_key)
      select w,c.id,id,'reopen:'||(c.work_cycle+1)::text from public.assignments where workspace_id=w and case_id=c.id and assigned_user_id is not null order by version desc limit 1 on conflict do nothing;
  else raise sqlstate 'PT422' using message='Unsupported case action'; end if;
  update public.cases set version=version+1 where id=c.id returning * into c;
  perform private.audit(w,c.id,a,r,'case_'||action,old_c,to_jsonb(c),body->>'reason');
  result:=jsonb_build_object('case',to_jsonb(c),'action',action,'attempt_id',at_id);
  insert into private.action_receipts values(w,a,key,hash,result);
  return result;
end $$;



create function private.case_action(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); body jsonb:=coalesce(p->'data','{}');
 c public.cases; rule public.owner_rules; old_rule public.owner_rules; result jsonb;
 role text; old_version bigint; configured boolean:=false; due date;
 key text:=private.nonempty(p->>'request_key','request_key'); hash text;
begin
 perform private.require_actor(w,a,p->>'acting_role');
 -- Return/revalidate the original integrated receipt before touching a default.
 if exists(select 1 from private.action_receipts where workspace_id=w and actor_id=a and request_key=key) then
   if p->>'action'<>'owner_rule' then return private.case_action_base(p); end if;
   hash:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
   select response into result from private.action_receipts where workspace_id=w and actor_id=a and request_key=key and payload_hash=hash;
   if not found then raise sqlstate 'PT409' using message='Action key content conflict'; end if;
   return result;
 end if;
 if body ? 'save_owner_rule' and jsonb_typeof(body->'save_owner_rule') is distinct from 'boolean' then raise sqlstate 'PT422' using message='Explicit default-owner choice required'; end if;
 if p->>'action'='owner_rule' and body->>'assigned_user_id' is not null then raise sqlstate 'PT422' using message='Use assignment to configure a reviewed default owner'; end if;
 if body->'save_owner_rule'='true'::jsonb or p->>'action'='owner_rule' then
   if p->>'acting_role'<>'process_owner' or p->>'action' not in ('assign','owner_rule') then raise insufficient_privilege using message='Process owner configures default owners'; end if;
   perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||key,2));
   -- A concurrent identical request may have finished while waiting for the lock.
   if exists(select 1 from private.action_receipts where workspace_id=w and actor_id=a and request_key=key) then
     if p->>'action'<>'owner_rule' then return private.case_action_base(p); end if;
     hash:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
     select response into result from private.action_receipts where workspace_id=w and actor_id=a and request_key=key and payload_hash=hash;
     if not found then raise sqlstate 'PT409' using message='Action key content conflict'; end if;
     return result;
   end if;
   select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
   if not found then raise sqlstate 'PT404' using message='Case not found'; end if;
   if c.linked_case_id is not null or c.version is distinct from (p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Case changed; use current canonical case'; end if;
   if c.category not in ('missing_target_gl_master_data','missing_gl_mapping') or (p->>'action'='assign' and (c.analysis_status<>'available' or not exists(select 1 from public.analysis_runs ready_run where ready_run.id=c.published_run_id and ready_run.attempt_id=c.current_attempt_id and ready_run.input_revision=c.input_revision))) then raise sqlstate 'PT422' using message='Establish a supported cause before configuring its owner'; end if;
   perform private.nonempty(c.target_system,'target_system'); perform private.nonempty(c.target_client,'target_client');
   perform private.nonempty(c.business_context->>'company_code','company_code'); perform private.nonempty(c.business_context->>'chart_of_accounts','chart_of_accounts'); perform private.nonempty(c.interface,'interface');
   role:=case when c.category='missing_gl_mapping' then 'mapping_owner' else 'master_data_owner' end;
   if body->>'owner_role' is distinct from role then raise sqlstate 'PT422' using message='Owner role must match this cause'; end if;
   perform pg_advisory_xact_lock(hashtextextended(w::text||c.category||c.target_system||c.target_client||(c.business_context->>'company_code')||(c.business_context->>'chart_of_accounts')||c.interface,7));
   select * into old_rule from public.owner_rules r where r.workspace_id=w and r.category=c.category and r.target_system=c.target_system and r.target_client=c.target_client and r.company_code=c.business_context->>'company_code' and r.chart_of_accounts=c.business_context->>'chart_of_accounts' and r.interface=c.interface order by version desc limit 1;
   old_version:=coalesce(old_rule.version,0);
   if jsonb_typeof(body->'expected_owner_rule_version') is distinct from 'number' or (body->>'expected_owner_rule_version')::bigint<>old_version then raise sqlstate 'PT409' using message='Default owner changed; refresh'; end if;
   if body->>'assigned_user_id' is not null then
     if not exists(select 1 from public.workspace_memberships m where m.workspace_id=w and m.user_id=(body->>'assigned_user_id')::uuid and role=any(m.roles)) then raise sqlstate 'PT422' using message='Active owner role membership required'; end if;
     due:=(body->>'owner_rule_review_due')::date;
     if due is null or due<=current_date or due>current_date+90 then raise sqlstate 'PT422' using message='Review the default within the next 90 days'; end if;
   end if;
   insert into public.owner_rules(workspace_id,category,target_system,target_client,company_code,chart_of_accounts,interface,version,assigned_user_id,owner_role,active,review_due,actor_id,reason)
   values(w,c.category,c.target_system,c.target_client,c.business_context->>'company_code',c.business_context->>'chart_of_accounts',c.interface,old_version+1,(body->>'assigned_user_id')::uuid,role,body->>'assigned_user_id' is not null,due,a,private.nonempty(body->>'reason','reason')) returning * into rule;
   perform private.audit(w,c.id,a,'process_owner','owner_rule_configured',to_jsonb(old_rule),to_jsonb(rule),body->>'reason');
   configured:=true;
 end if;
 if p->>'action'='owner_rule' then
   update public.cases set version=version+1 where workspace_id=w and id=c.id returning * into c;
   result:=jsonb_build_object('case',to_jsonb(c),'action','owner_rule','owner_rule',to_jsonb(rule));
   hash:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
   insert into private.action_receipts values(w,a,key,hash,result);
   return result;
 end if;
 result:=private.case_action_base(p);
 if configured then
   result:=result||jsonb_build_object('owner_rule',to_jsonb(rule));
   update private.action_receipts set response=result where workspace_id=w and actor_id=a and request_key=key;
 end if;
 return result;
end $$;
create or replace function public.cfin_case_action(payload jsonb) returns jsonb language sql security invoker set search_path='' as $$ select private.case_action(payload); $$;
revoke all on function private.case_action(jsonb),public.cfin_case_action(jsonb) from public,anon,authenticated;
grant execute on function private.case_action(jsonb),public.cfin_case_action(jsonb) to authenticated;
create or replace function private.complete_run_base(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; run public.analysis_runs; c public.cases; is_current boolean; succeeded boolean:=(p->>'succeeded')::boolean; receipt public.run_results;
begin
  -- Keep late output as history before checking whether it can mutate current work.
  perform 1 from private.worker_slot where singleton=1 for update;
  select * into job from public.jobs where id=(p->>'job_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Job not found'; end if;
  select * into receipt from public.run_results where job_id=job.id and submitted_lease_token=(p->>'lease_token')::uuid;
  if found then return jsonb_build_object('run_id',receipt.run_id,'promoted',receipt.promoted,'duplicate',true); end if;
  insert into public.run_results(workspace_id,run_id,job_id,submitted_lease_token,output,succeeded)
    values(job.workspace_id,job.run_id,job.id,(p->>'lease_token')::uuid,p->'output',succeeded) returning * into receipt;
  if job.state<>'running' or job.lease_token is distinct from (p->>'lease_token')::uuid or job.lease_until<=clock_timestamp() then
    return jsonb_build_object('run_id',job.run_id,'promoted',false,'lease_rejected',true,'result_id',receipt.id);
  end if;
  select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
  select * into run from public.analysis_runs where id=job.run_id for update;
  select * into c from public.cases where id=run.case_id for update;
  is_current:=coalesce(not run.evaluation_only and c.attempt_order_known and c.current_attempt_id=run.attempt_id and c.input_revision=run.input_revision and c.requested_run_id=run.id,false);
  -- Withdrawal during a running model call prevents actionable promotion.
  if exists(select 1 from public.run_sources s join lateral (select decision from public.reference_reviews where workspace_id=s.workspace_id and evidence_id=s.evidence_id order by version desc limit 1) rev on true where s.run_id=run.id and rev.decision in ('withdrawn','rejected') and coalesce(s.source_snapshot->'review'->>'decision','pending_review')<>rev.decision) then
    is_current:=false;
  end if;
  update public.analysis_runs set state=case when run.evaluation_only then case when succeeded then 'succeeded' else 'failed' end when not is_current then 'historical' when succeeded then 'succeeded' else 'failed' end,output=p->'output',error_code=p->>'error_code' where id=run.id;
  if is_current then
    update public.cases set analysis_status=case when succeeded then 'available' else 'unavailable' end,
      published_run_id=case when succeeded then run.id else published_run_id end,
      category=case when c.diagnosis_status='human_confirmed' then c.category when succeeded then coalesce(p->'output'->>'category','cause_not_established') else 'cause_not_established' end,
      affected_object=case when c.diagnosis_status='human_confirmed' then c.affected_object when succeeded then coalesce(p->'output'->>'affected_object','unknown') else affected_object end,
      diagnosis_status=case when c.diagnosis_status='human_confirmed' then c.diagnosis_status when succeeded then coalesce(p->'output'->>'diagnosis_status','needs_review') else 'needs_review' end,
      description=case when succeeded then coalesce(p->'output'->>'description',description) else description end,
      version=version+1 where id=c.id;
  end if;
  -- Only actual process-owner configuration can select an owner; model/file labels cannot.
  if is_current and succeeded and c.linked_case_id is null and c.status in ('created','owner_notified')
    and c.diagnosis_status<>'human_confirmed' and c.work_started_at is null
    and p->'output'->'diagnosis'->>'status'='ai_supported'
    and p->'output'->'routing'->>'reason' is distinct from 'multiple_blockers'
    and not exists(select 1 from public.assignments where workspace_id=c.workspace_id and case_id=c.id) then
    perform pg_advisory_xact_lock(hashtextextended(c.workspace_id::text||(p->'output'->>'category')||c.target_system||c.target_client||(c.business_context->>'company_code')||(c.business_context->>'chart_of_accounts')||c.interface,7));
    insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason)
    select c.workspace_id,c.id,1,r.assigned_user_id,r.owner_role,r.actor_id,'process_owner',
      'Configured owner rule '||r.id::text||' version '||r.version::text
    from public.owner_rules r join public.workspace_memberships owner_member on owner_member.workspace_id=r.workspace_id and owner_member.user_id=r.assigned_user_id and r.owner_role=any(owner_member.roles)
    join public.workspace_memberships reviewer on reviewer.workspace_id=r.workspace_id and reviewer.user_id=r.actor_id and 'process_owner'=any(reviewer.roles)
    where r.workspace_id=c.workspace_id and r.category=p->'output'->>'category' and r.target_system=c.target_system and r.target_client=c.target_client and r.company_code=c.business_context->>'company_code' and r.chart_of_accounts=c.business_context->>'chart_of_accounts' and r.interface=c.interface
    and r.active and r.review_due>=current_date and r.version=(select max(version) from public.owner_rules latest where latest.workspace_id=r.workspace_id and latest.category=r.category and latest.target_system=r.target_system and latest.target_client=r.target_client and latest.company_code=r.company_code and latest.chart_of_accounts=r.chart_of_accounts and latest.interface=r.interface);
    if found then
      insert into public.notifications(workspace_id,case_id,assignment_id,event_key)
      select c.workspace_id,c.id,id,'assignment' from public.assignments where workspace_id=c.workspace_id and case_id=c.id and version=1 on conflict do nothing;
      perform private.audit(c.workspace_id,c.id,null,'worker','configured_owner_assigned',null,
        (select to_jsonb(a)||jsonb_build_object('run_id',run.id,'requested_by',run.requested_by) from public.assignments a where workspace_id=c.workspace_id and case_id=c.id and version=1),null);
    end if;
  end if;
  update public.jobs set state=case when succeeded then 'succeeded' else 'failed' end,lease_until=null,lease_token=null where id=job.id;
  update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1 and job_id=job.id and lease_token=job.lease_token;
  perform private.audit(c.workspace_id,c.id,null,'worker','analysis_finished',null,jsonb_build_object('run_id',run.id,'promoted',is_current,'succeeded',succeeded),p->>'error_code');
  update public.run_results set promoted=is_current where id=receipt.id;
  return jsonb_build_object('run_id',run.id,'promoted',is_current,'case_version',c.version+case when is_current then 1 else 0 end);
end $$;
create or replace function private.save_stage(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs; old jsonb;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 if jsonb_typeof(p->'output') is distinct from 'object' or p->'output'->>'run_id' is distinct from j.run_id::text then raise sqlstate 'PT422' using message='Stage must match actual run'; end if;
 if p->>'source_run_id' is not null and not exists(
   select 1 from public.analysis_runs current_run join public.analysis_runs source_run
     on source_run.workspace_id=current_run.workspace_id and source_run.case_id=current_run.case_id
     and source_run.attempt_id=current_run.attempt_id and source_run.id<>current_run.id
   where current_run.id=j.run_id and current_run.workspace_id=j.workspace_id
     and not current_run.evaluation_only and p->>'stage'='agent1'
     and source_run.id=(p->>'source_run_id')::uuid and not source_run.evaluation_only
 ) then raise sqlstate 'PT422' using message='Preparation reuse must bind this exact case/attempt'; end if;
 select output into old from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and stage=p->>'stage' and invalidated_at is null;
 if found and old is distinct from p->'output' then raise sqlstate 'PT409' using message='Immutable stage differs'; end if;
 insert into public.validated_stages(workspace_id,run_id,stage,output,source_run_id) values(j.workspace_id,j.run_id,p->>'stage',p->'output',(p->>'source_run_id')::uuid) on conflict(workspace_id,run_id,stage) do update set output=excluded.output,source_run_id=excluded.source_run_id,saved_at=now(),invalidated_at=null where validated_stages.invalidated_at is not null;
 return jsonb_build_object('saved',true);
end $$;
commit;
