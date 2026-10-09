-- Bind reused stages and validate direct evaluation RPC requests.
begin;
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
     and source_run.id=(p->>'source_run_id')::uuid and not source_run.evaluation_only
 ) then raise sqlstate 'PT422' using message='Preparation reuse must bind this exact case/attempt'; end if;
 select output into old from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and stage=p->>'stage' and invalidated_at is null;
 if found and old is distinct from p->'output' then raise sqlstate 'PT409' using message='Immutable stage differs'; end if;
 insert into public.validated_stages(workspace_id,run_id,stage,output,source_run_id) values(j.workspace_id,j.run_id,p->>'stage',p->'output',(p->>'source_run_id')::uuid) on conflict(workspace_id,run_id,stage) do update set output=excluded.output,source_run_id=excluded.source_run_id,saved_at=now(),invalidated_at=null where validated_stages.invalidated_at is not null;
 return jsonb_build_object('saved',true);
end $$;
create or replace function private.queue_evaluations(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); b public.evaluation_batches; c public.cases; original public.analysis_runs; run public.analysis_runs; item text; i integer; count_cases integer; repeats integer:=(p->>'repeats')::integer; ids jsonb:='[]'; sn jsonb;
begin
 perform private.require_actor(w,a,'process_owner');
 if jsonb_typeof(p->'case_ids') is distinct from 'array' then raise sqlstate 'PT422' using message='Select saved cases'; end if;
 count_cases:=jsonb_array_length(p->'case_ids');
 if count_cases<1 or count_cases>30 or repeats is null or repeats<1 or repeats>3 or jsonb_typeof(p->'configuration') is distinct from 'object' then raise sqlstate 'PT422' using message='At most30cases and3repeats'; end if;
 if count_cases<>(select count(distinct value) from jsonb_array_elements_text(p->'case_ids')) then raise sqlstate 'PT422' using message='Case IDs must be unique'; end if;
 if jsonb_typeof(p->'configuration'->'models') is distinct from 'object'
   or coalesce(p->'configuration'->>'reasoning_effort','') not in ('low','medium','high')
   or exists(select 1 from unnest(array['agent1','agent2','agent3']) stage
     where jsonb_typeof(p->'configuration'->'models'->stage) is distinct from 'string'
       or not exists(select 1 from private.model_prices mp where mp.model_id=p->'configuration'->'models'->>stage and mp.model_id<>'fake' and mp.verified_at<=clock_timestamp() and mp.expires_at>clock_timestamp()))
 then raise sqlstate 'PT422' using message='Verified stage models and effort required'; end if;
 perform private.nonempty(p->>'reason','reason');
 insert into public.evaluation_batches(workspace_id,actor_id,reason,configuration) values(w,a,p->>'reason',p->'configuration') returning * into b;
 for item in select jsonb_array_elements_text(p->'case_ids') loop
  select * into c from public.cases where workspace_id=w and id=item::uuid for update;
  if not found or c.linked_case_id is not null or not c.attempt_order_known or c.current_attempt_id is null then raise sqlstate 'PT422' using message='Current saved case/attempt required'; end if;
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
commit;
