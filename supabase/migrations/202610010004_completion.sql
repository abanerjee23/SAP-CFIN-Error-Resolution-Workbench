-- Remaining POC workflow controls, durable validated stages and simulated notifications.
begin;
alter table public.notifications add column case_id uuid;
update public.notifications n set case_id=a.case_id from public.assignments a where a.id=n.assignment_id and a.workspace_id=n.workspace_id;
alter table public.notifications alter column case_id set not null;
alter table public.notifications add foreign key(workspace_id,case_id) references public.cases(workspace_id,id);
alter table public.notifications add column available_at timestamptz not null default now();
alter table public.notifications add column lease_token uuid;
alter table public.notifications add column lease_until timestamptz;
alter table public.notifications add column delivered_at timestamptz;
alter table public.notifications add column error_code text;
alter table public.notifications add column delivery_attempts integer not null default 0;
create table public.validated_stages (
  workspace_id uuid not null, run_id uuid not null, stage text not null check(stage in ('agent1','agent2','agent3')),
  output jsonb not null, saved_at timestamptz not null default now(), invalidated_at timestamptz, source_run_id uuid references public.analysis_runs(id),
  foreign key(workspace_id,run_id) references public.analysis_runs(workspace_id,id), primary key(workspace_id,run_id,stage)
);
alter table public.validated_stages enable row level security;
create policy stages_member_read on public.validated_stages for select to authenticated using(private.is_member(workspace_id));
revoke all on public.validated_stages from anon,authenticated;
grant select on public.validated_stages to authenticated;
grant all on public.validated_stages to service_role;

create or replace function private.validate_case_citations(w uuid,c_id uuid,citations jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare catalogue jsonb; citation jsonb; source jsonb; start_line integer; end_line integer;
begin
  if jsonb_typeof(citations) is distinct from 'array' or jsonb_array_length(citations)=0 then
    raise sqlstate 'PT422' using message='Resolvable cause evidence required';
  end if;
  select run.output->'source_catalogue' into catalogue from public.cases c
    join public.analysis_runs run on run.workspace_id=c.workspace_id and run.id=case when exists(select 1 from public.analysis_runs latest where latest.id=c.requested_run_id and latest.state='failed' and latest.input_revision=c.input_revision and latest.attempt_id=c.current_attempt_id) then c.requested_run_id else c.published_run_id end
    where c.workspace_id=w and c.id=c_id;
  if jsonb_typeof(catalogue) is distinct from 'array' then
    raise sqlstate 'PT422' using message='Saved analysis source catalogue required';
  end if;
  for citation in select value from jsonb_array_elements(citations) loop
    if jsonb_typeof(citation) is distinct from 'object' then raise sqlstate 'PT422' using message='Invalid citation'; end if;
    select value into source from jsonb_array_elements(catalogue)
      where value->>'source_id'=citation->>'source_id' and value->>'source_version'=citation->>'source_version';
    if not found or source->>'attempt_id' is distinct from citation->>'attempt_id' then
      raise sqlstate 'PT422' using message='Citation source, version or attempt is not in the saved catalogue';
    end if;
    if citation->>'record_id' is not null then
      if source->>'kind'<>'records' or citation->>'line_start' is not null or citation->>'line_end' is not null
        or not (source->'record_ids' ? (citation->>'record_id')) then raise sqlstate 'PT422' using message='Invalid citation record'; end if;
    else
      start_line:=(citation->>'line_start')::integer; end_line:=(citation->>'line_end')::integer;
      if source->>'kind'<>'text' or start_line is null or end_line is null or start_line<1
        or end_line<start_line or end_line>(source->>'line_count')::integer then raise sqlstate 'PT422' using message='Invalid citation line range'; end if;
    end if;
  end loop;
end $$;

create or replace function private.case_action(p jsonb)
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
    if coalesce((body->>'cause_confirmed')::boolean,false) then
      if jsonb_typeof(body->'cause_evidence') is distinct from 'array' or jsonb_array_length(body->'cause_evidence')=0 then raise sqlstate 'PT422' using message='Cause confirmation requires evidence'; end if;
      perform private.validate_case_citations(w,c.id,body->'cause_evidence');
      update public.cases set diagnosis_status='human_confirmed' where id=c.id;
    end if;
  elsif action='start' then
    if c.status not in ('created','owner_notified') and not (c.status='in_progress' and c.work_started_at is null) then raise sqlstate 'PT409' using message='Work already started'; end if;
    if not exists(select 1 from public.case_reviews where workspace_id=w and case_id=c.id and run_id in (c.published_run_id,c.requested_run_id)) then raise sqlstate 'PT422' using message='Human review required before work'; end if;
    if body->>'target_change_authority' is distinct from 'true' then raise sqlstate 'PT422' using message='Human target-change authority confirmation required'; end if;
    perform private.nonempty(body->>'approved_attributes','approved_attributes');
    update public.cases set status='in_progress',work_started_at=now() where id=c.id;
  elsif action='block' then
    if c.status not in ('created','owner_notified','in_progress') then raise sqlstate 'PT409' using message='Invalid block transition'; end if;
    perform private.nonempty(body->>'reason','reason'); update public.cases set status='blocked' where id=c.id;
  elsif action='resume' then
    if c.status<>'blocked' then raise sqlstate 'PT409' using message='Case is not blocked'; end if;
    if c.work_started_at is null then
      if not exists(select 1 from public.case_reviews where workspace_id=w and case_id=c.id and run_id in (c.published_run_id,c.requested_run_id))
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


create function private.stage_resume(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs; result jsonb; calls jsonb;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 select coalesce(jsonb_object_agg(stage,output),'{}') into result from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and invalidated_at is null;
 select coalesce(jsonb_agg(to_jsonb(s) order by invocation),'[]') into calls from public.stage_calls s where workspace_id=j.workspace_id and run_id=j.run_id;
 return jsonb_build_object('outputs',result,'calls',calls,'reused_from',(select coalesce(jsonb_object_agg(stage,source_run_id),'{}') from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and invalidated_at is null and source_run_id is not null));
end $$;
create function private.save_stage(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs; old jsonb;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 if jsonb_typeof(p->'output') is distinct from 'object' or p->'output'->>'run_id' is distinct from j.run_id::text then raise sqlstate 'PT422' using message='Stage must match actual run'; end if;
 select output into old from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and stage=p->>'stage' and invalidated_at is null;
 if found and old is distinct from p->'output' then raise sqlstate 'PT409' using message='Immutable stage differs'; end if;
 insert into public.validated_stages(workspace_id,run_id,stage,output,source_run_id) values(j.workspace_id,j.run_id,p->>'stage',p->'output',(p->>'source_run_id')::uuid) on conflict(workspace_id,run_id,stage) do update set output=excluded.output,source_run_id=excluded.source_run_id,saved_at=now(),invalidated_at=null where validated_stages.invalidated_at is not null;
 return jsonb_build_object('saved',true);
end $$;
create function private.fail_stage(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 perform private.audit(j.workspace_id,null,null,'worker','stage_checkpoint_invalidated',
   (select output from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and stage=p->>'stage' and invalidated_at is null),
   jsonb_build_object('run_id',j.run_id,'stage',p->>'stage'), 'Failed validation');
 update public.validated_stages set invalidated_at=now() where workspace_id=j.workspace_id and run_id=j.run_id and stage=p->>'stage';
 update public.stage_calls set state=case when actual_usd is null then 'usage_unknown' else 'failed' end
   where workspace_id=j.workspace_id and run_id=j.run_id and id=(p->>'call_id')::uuid;
 return jsonb_build_object('recorded',found);
end $$;
create function private.claim_notification(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare n public.notifications; token uuid:=gen_random_uuid();
begin
 select * into n from public.notifications where state='queued' and available_at<=clock_timestamp() and (lease_until is null or lease_until<clock_timestamp()) order by available_at,id for update skip locked limit 1;
 if not found then return jsonb_build_object('claimed',false); end if;
 update public.notifications set lease_token=token,lease_until=clock_timestamp()+interval '30 seconds',delivery_attempts=delivery_attempts+1 where id=n.id returning * into n;
 return jsonb_build_object('claimed',true,'notification',to_jsonb(n));
end $$;
create function private.complete_notification(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare n public.notifications; a public.assignments; latest uuid; c public.cases; ok boolean:=coalesce((p->>'succeeded')::boolean,false);
begin
 select * into n from public.notifications where id=(p->>'notification_id')::uuid for update;
 if not found or n.state<>'queued' or n.lease_token is distinct from (p->>'lease_token')::uuid or n.lease_until<=clock_timestamp() then raise sqlstate 'PT409' using message='Notification lease expired'; end if;
 select * into a from public.assignments where workspace_id=n.workspace_id and id=n.assignment_id;
 select id into latest from public.assignments where workspace_id=n.workspace_id and case_id=n.case_id order by version desc limit 1;
 select * into c from public.cases where workspace_id=n.workspace_id and id=n.case_id for update;
 update public.notifications set state=case when ok then 'succeeded' when retry_count=0 then 'queued' else 'failed' end,
   retry_count=case when ok then retry_count else 1 end,available_at=clock_timestamp()+interval '3 seconds',
   delivered_at=case when ok then clock_timestamp() else null end,error_code=case when ok then null else 'simulated_delivery_failed' end,
   lease_until=null,lease_token=null where id=n.id;
 if ok and latest=a.id and a.assigned_user_id is not null and c.status='created' then
   update public.cases set status='owner_notified',version=version+1 where id=c.id;
 end if;
 perform private.audit(n.workspace_id,n.case_id,null,'worker','simulated_notification_result',null,jsonb_build_object('notification_id',n.id,'assignment_id',a.id,'succeeded',ok),null);
 return jsonb_build_object('recorded',true,'simulated',true);
end $$;
revoke all on function private.stage_resume(jsonb),private.save_stage(jsonb),private.fail_stage(jsonb),private.claim_notification(jsonb),private.complete_notification(jsonb) from public,anon,authenticated,service_role;
do $$ declare name text; begin
 foreach name in array array['stage_resume','save_stage','fail_stage','claim_notification','complete_notification'] loop
   execute format('create function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',name,name);
   execute format('revoke all on function public.cfin_%I(jsonb) from public,anon,authenticated,service_role',name);
   execute format('grant execute on function private.%I(jsonb),public.cfin_%I(jsonb) to service_role',name,name);
 end loop;
end $$;
revoke all on function private.complete_run_base(jsonb) from public,anon,authenticated;
grant execute on function private.complete_run_base(jsonb) to service_role;
create or replace function private.reserve_call(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; price private.model_prices; call_row public.stage_calls; month date:=(date_trunc('month',clock_timestamp() at time zone 'UTC'))::date;
  amount numeric(12,6); used numeric(12,6); run_used numeric(12,6); cap numeric(12,6);
  monthly_cap numeric:=coalesce((p->>'monthly_budget_usd')::numeric,10);
  run_cap numeric:=coalesce((p->>'run_budget_usd')::numeric,1);
begin
  select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
  if monthly_cap<=0 or monthly_cap>10 or run_cap<=0 or run_cap>1 then
    raise sqlstate 'PT422' using message='Invalid configured model budget';
  end if;
  select * into price from private.model_prices where model_id=p->>'model_id' and expires_at>clock_timestamp();
  if not found then raise sqlstate 'PT422' using message='Known current model pricing required'; end if;
  insert into private.budget_months(workspace_id,month_start) values(job.workspace_id,month) on conflict do nothing;
  select allowance_usd into cap from private.budget_months where workspace_id=job.workspace_id and month_start=month for update;
  select * into call_row from public.stage_calls where workspace_id=job.workspace_id and run_id=job.run_id and stage=p->>'stage' and invocation=(p->>'invocation')::integer;
  if found then return jsonb_build_object('call',to_jsonb(call_row),'duplicate',true,'execute',false); end if;
  if (p->>'invocation')::integer=1 and not exists(select 1 from public.stage_calls where run_id=job.run_id and stage=p->>'stage' and invocation=0 and state in ('failed','usage_unknown')) then
    raise sqlstate 'PT422' using message='Retry needs a failed first invocation';
  end if;
  amount:=ceil(((p->>'max_input_tokens')::numeric*price.input_usd_per_million+(p->>'max_output_tokens')::numeric*price.output_usd_per_million)/1000000*1000000)/1000000;
  select coalesce(sum(coalesce(actual_usd,reserved_usd)),0) into used from public.stage_calls where month_start=month and state<>'not_sent';
  used:=used+(select coalesce(sum(coalesce(actual_usd,reserved_usd)),0) from public.overview_runs where month_start=month);
  select coalesce(sum(coalesce(actual_usd,reserved_usd)),0) into run_used from public.stage_calls where workspace_id=job.workspace_id and run_id=job.run_id and state<>'not_sent';
  if used+amount>least(cap,10,monthly_cap) or run_used+amount>least(1,run_cap) then raise sqlstate 'PT422' using message='Model budget exhausted'; end if;
  insert into public.stage_calls(workspace_id,run_id,stage,invocation,model_id,price_version,price_input,price_output,month_start,max_input_tokens,max_output_tokens,reserved_usd,state)
    values(job.workspace_id,job.run_id,p->>'stage',(p->>'invocation')::integer,price.model_id,price.version,price.input_usd_per_million,price.output_usd_per_million,month,(p->>'max_input_tokens')::integer,(p->>'max_output_tokens')::integer,amount,'in_flight') returning * into call_row;
  return jsonb_build_object('call',to_jsonb(call_row),'duplicate',false,'execute',true);
end $$;

create function private.preparation_reuse(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs; current_run public.analysis_runs; prior public.analysis_runs;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 select * into current_run from public.analysis_runs where workspace_id=j.workspace_id and id=j.run_id;
 -- Evaluation markers are held inside the immutable snapshot until migration 005 adds a column.
 if current_run.snapshot ? 'evaluation_configuration' then return jsonb_build_object('reused',false); end if;
 select * into prior from public.analysis_runs r
 where r.workspace_id=current_run.workspace_id and r.case_id=current_run.case_id and r.attempt_id=current_run.attempt_id and r.id<>current_run.id
 and r.state in ('succeeded','historical') and not (r.snapshot ? 'evaluation_configuration')
 and r.output->>'prompt_version'=p->>'prompt_version'
 and r.output->'model_configuration'->'models'->>'agent1'=p->>'model_id'
 and r.output->'model_configuration'->>'reasoning_effort'=p->>'reasoning_effort'
 and jsonb_typeof(r.output->'preparation')='object' and r.output->'preparation'->>'run_id'=r.id::text
 and r.snapshot->'manifest'=current_run.snapshot->'manifest'
 and r.snapshot->'identity'=current_run.snapshot->'identity'
 and r.snapshot->'business_context'=current_run.snapshot->'business_context'
 and r.snapshot->'sources'=current_run.snapshot->'sources'
 and coalesce(r.snapshot->'context_overlay','[]'::jsonb)=coalesce(current_run.snapshot->'context_overlay','[]'::jsonb)
 order by r.created_at desc,r.id desc limit 1;
 if not found then return jsonb_build_object('reused',false); end if;
 return jsonb_build_object('reused',true,'preparation',prior.output->'preparation','source_run_id',prior.id);
end $$;
create function public.cfin_preparation_reuse(payload jsonb) returns jsonb language sql security invoker set search_path='' as $$ select private.preparation_reuse(payload) $$;
revoke all on function private.preparation_reuse(jsonb),public.cfin_preparation_reuse(jsonb) from public,anon,authenticated;
grant execute on function private.preparation_reuse(jsonb),public.cfin_preparation_reuse(jsonb) to service_role;
commit;
