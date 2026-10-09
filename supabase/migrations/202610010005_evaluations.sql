-- Budgeted model evaluation jobs use immutable private case snapshots and never promote cases.
begin;
create table public.evaluation_batches (
 id uuid primary key default gen_random_uuid(),workspace_id uuid not null references public.workspaces(id),
 actor_id uuid not null references auth.users(id),reason text not null check(length(btrim(reason))>0),
 configuration jsonb not null,created_at timestamptz not null default now(),unique(workspace_id,id)
);
alter table public.evaluation_batches enable row level security;
create policy evaluation_member_read on public.evaluation_batches for select to authenticated using(private.is_member(workspace_id));
revoke all on public.evaluation_batches from anon,authenticated;
grant select on public.evaluation_batches to authenticated;
grant all on public.evaluation_batches to service_role;
alter table public.analysis_runs add column evaluation_only boolean not null default false;
alter table public.analysis_runs add column evaluation_batch_id uuid;
alter table public.analysis_runs add column evaluation_repeat integer check(evaluation_repeat between 0 and 2);
alter table public.analysis_runs add foreign key(workspace_id,evaluation_batch_id) references public.evaluation_batches(workspace_id,id);
drop index public.one_active_snapshot_run;
create unique index one_active_snapshot_run on public.analysis_runs(workspace_id,case_id,snapshot_hash) where state in ('queued','running') and not evaluation_only;
create unique index evaluation_batch_repeat on public.analysis_runs(evaluation_batch_id,case_id,evaluation_repeat) where evaluation_only;
create function private.queue_evaluations(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); b public.evaluation_batches; c public.cases; original public.analysis_runs; run public.analysis_runs; item text; i integer; count_cases integer; repeats integer:=(p->>'repeats')::integer; ids jsonb:='[]'; sn jsonb;
begin
 perform private.require_actor(w,a,'process_owner');
 if jsonb_typeof(p->'case_ids') is distinct from 'array' then raise sqlstate 'PT422' using message='Select saved cases'; end if;
 count_cases:=jsonb_array_length(p->'case_ids');
 if count_cases<1 or count_cases>30 or repeats<1 or repeats>3 then raise sqlstate 'PT422' using message='At most30cases and3repeats'; end if;
 if count_cases<>(select count(distinct value) from jsonb_array_elements_text(p->'case_ids')) then raise sqlstate 'PT422' using message='Case IDs must be unique'; end if;
 perform private.nonempty(p->>'reason','reason');
 insert into public.evaluation_batches(workspace_id,actor_id,reason,configuration) values(w,a,p->>'reason',p->'configuration') returning * into b;
 for item in select jsonb_array_elements_text(p->'case_ids') loop
  select * into c from public.cases where workspace_id=w and id=item::uuid for update;
  if not found or not c.attempt_order_known or c.current_attempt_id is null then raise sqlstate 'PT422' using message='Current saved case/attempt required'; end if;
  select * into original from public.analysis_runs where workspace_id=w and case_id=c.id and attempt_id=c.current_attempt_id and input_revision=c.input_revision and not evaluation_only order by created_at desc,id desc limit 1;
  if not found then raise sqlstate 'PT422' using message='Save and queue the case snapshot before evaluation'; end if;
  for i in 0..repeats-1 loop
   sn:=original.snapshot||jsonb_build_object('evaluation_configuration',p->'configuration');
   insert into public.analysis_runs(workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by,evaluation_only,evaluation_batch_id,evaluation_repeat)
    values(w,c.id,c.current_attempt_id,encode(pg_catalog.sha256(convert_to(sn::text,'UTF8')),'hex'),sn,c.version,c.input_revision,a,true,b.id,i) returning * into run;
   insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot) select w,run.id,evidence_id,source_snapshot from public.run_sources where run_id=original.id;
   insert into public.jobs(workspace_id,run_id) values(w,run.id);
   ids:=ids||jsonb_build_array(run.id);
  end loop;
 end loop;
 perform private.audit(w,null,a,'process_owner','evaluation_batch_queued',null,jsonb_build_object('batch_id',b.id,'runs',ids),p->>'reason');
 return jsonb_build_object('batch',to_jsonb(b),'run_ids',ids,'paid_dispatch_enabled',false);
end $$;
create function private.case_page(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; page integer:=coalesce((p->>'page')::integer,1); size integer:=coalesce((p->>'page_size')::integer,25); rows jsonb; total integer;
begin
 if not private.is_member(w) then raise insufficient_privilege using message='Workspace membership required'; end if;
 if page<1 or size<1 or size>100 then raise sqlstate 'PT422' using message='Invalid page'; end if;
 select count(*) into total from public.cases c where workspace_id=w and linked_case_id is null
  and (coalesce(p->>'category','')='' or category=p->>'category') and (coalesce(p->>'priority','')='' or priority=p->>'priority')
  and (coalesce(p->>'status','')='' or status=p->>'status') and (coalesce(p->>'diagnosis_status','')='' or diagnosis_status=p->>'diagnosis_status')
  and (coalesce(p->>'affected_object','')='' or affected_object=p->>'affected_object')
  and (coalesce(p->>'q','')='' or position(lower(p->>'q') in lower(title||' '||description||' '||coalesce(document_number,'')))>0);
 select coalesce(jsonb_agg(to_jsonb(r)),'[]') into rows from (
  select * from public.cases c where workspace_id=w and linked_case_id is null
  and (coalesce(p->>'category','')='' or category=p->>'category') and (coalesce(p->>'priority','')='' or priority=p->>'priority')
  and (coalesce(p->>'status','')='' or status=p->>'status') and (coalesce(p->>'diagnosis_status','')='' or diagnosis_status=p->>'diagnosis_status')
  and (coalesce(p->>'affected_object','')='' or affected_object=p->>'affected_object')
  and (coalesce(p->>'q','')='' or position(lower(p->>'q') in lower(title||' '||description||' '||coalesce(document_number,'')))>0)
  order by case priority when 'P3' then 0 when 'P2' then 1 else 2 end,created_at desc,id offset (page-1)*size limit size
 ) r;
 return jsonb_build_object('items',rows,'total',total,'page',page,'page_size',size);
end $$;
create function private.workspace_directory(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; result jsonb;
begin
 if not private.is_member(w) then raise insufficient_privilege using message='Workspace membership required'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('user_id',user_id,'roles',roles)),'[]') into result from public.workspace_memberships where workspace_id=w;
 return result;
end $$;
revoke all on function private.queue_evaluations(jsonb),private.case_page(jsonb),private.workspace_directory(jsonb) from public,anon,authenticated,service_role;
do $$ declare name text; begin
 foreach name in array array['queue_evaluations','case_page','workspace_directory'] loop
  execute format('create function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',name,name);
  execute format('revoke all on function public.cfin_%I(jsonb) from public,anon,authenticated,service_role',name);
  execute format('grant execute on function public.cfin_%I(jsonb),private.%I(jsonb) to authenticated',name,name);
 end loop;
end $$;
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
  -- Unreviewed fixture role labels do not bind actual people. A configured,
  -- applicable directory must be human-reviewed before automatic assignment.
  -- Manual assignment uses the authenticated, audited case action.
  update public.jobs set state=case when succeeded then 'succeeded' else 'failed' end,lease_until=null,lease_token=null where id=job.id;
  update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1 and job_id=job.id and lease_token=job.lease_token;
  perform private.audit(c.workspace_id,c.id,null,'worker','analysis_finished',null,jsonb_build_object('run_id',run.id,'promoted',is_current,'succeeded',succeeded),p->>'error_code');
  update public.run_results set promoted=is_current where id=receipt.id;
  return jsonb_build_object('run_id',run.id,'promoted',is_current,'case_version',c.version+case when is_current then 1 else 0 end);
end $$;
create or replace function private.preserve_run_input()
returns trigger language plpgsql set search_path='' as $$
begin
  if new.workspace_id is distinct from old.workspace_id or new.case_id is distinct from old.case_id
    or new.attempt_id is distinct from old.attempt_id or new.snapshot is distinct from old.snapshot
    or new.snapshot_hash is distinct from old.snapshot_hash or new.input_revision is distinct from old.input_revision
    or new.case_version is distinct from old.case_version or new.requested_by is distinct from old.requested_by
    or new.evaluation_only is distinct from old.evaluation_only
    or new.evaluation_batch_id is distinct from old.evaluation_batch_id
    or new.evaluation_repeat is distinct from old.evaluation_repeat then
    raise sqlstate 'PT409' using message='Run input snapshot is immutable';
  end if;
  return new;
end $$;
commit;
