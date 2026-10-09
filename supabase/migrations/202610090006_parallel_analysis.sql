-- Two independent Error Analysis jobs may run together. The original singleton
-- remains the transaction mutex and the exclusive legacy/overview lease.
begin;

create table private.analysis_worker_slots (
 slot integer primary key check(slot in (1,2)),
 job_id uuid unique references public.jobs(id),
 lease_token uuid,
 lease_until timestamptz,
 check ((job_id is null and lease_token is null and lease_until is null)
     or (job_id is not null and lease_token is not null and lease_until is not null))
);
insert into private.analysis_worker_slots(slot) values(1),(2);
revoke all on private.analysis_worker_slots from public,anon,authenticated,service_role;

create or replace function private.claim_job(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 exclusive private.worker_slot; parallel private.analysis_worker_slots;
 job public.jobs; run public.analysis_runs; token uuid:=gen_random_uuid();
 t timestamptz:=clock_timestamp(); has_parallel boolean;
begin
 perform private.nonempty(p->>'worker_id','worker_id');
 select * into exclusive from private.worker_slot where singleton=1 for update;
 if exclusive.lease_until>t then return jsonb_build_object('claimed',false); end if;
 -- Recover expired leases without forgiving calls whose usage is still unknown.
 if exclusive.job_id is not null then
  update public.stage_calls set state='usage_unknown'
   where run_id=(select run_id from public.jobs where id=exclusive.job_id) and state='in_flight';
  update public.jobs set state='queued',lease_token=null,lease_until=null,worker_id=null
   where id=exclusive.job_id and state='running';
 end if;
 update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1;
 for parallel in select * from private.analysis_worker_slots where job_id is not null and lease_until<=t order by slot for update loop
  update public.stage_calls set state='usage_unknown'
   where run_id=(select run_id from public.jobs where id=parallel.job_id) and state='in_flight';
  update public.jobs set state='queued',lease_token=null,lease_until=null,worker_id=null
   where id=parallel.job_id and state='running' and lease_token=parallel.lease_token;
  update private.analysis_worker_slots set job_id=null,lease_token=null,lease_until=null where slot=parallel.slot;
 end loop;
 select exists(select 1 from private.analysis_worker_slots where job_id is not null) into has_parallel;
 select * into parallel from private.analysis_worker_slots where job_id is null order by slot for update limit 1;
 if not found then return jsonb_build_object('claimed',false); end if;
 select j.* into job from public.jobs j join public.analysis_runs ar on ar.id=j.run_id
  where j.state='queued' and j.available_at<=t
   and (p->>'run_id' is null or j.run_id=(p->>'run_id')::uuid)
   and (ar.workflow_version<>'log-only-v1' or p->'log_only_enabled'='true'::jsonb)
   and (not has_parallel or ar.workflow_version='error-analysis-v1')
   and not exists (
    select 1 from private.analysis_worker_slots s join public.jobs active_job on active_job.id=s.job_id
     join public.analysis_runs active_run on active_run.id=active_job.run_id
     where active_run.case_id=ar.case_id
   )
  order by j.available_at,j.id for update of j skip locked limit 1;
 if not found then return jsonb_build_object('claimed',false); end if;
 update public.jobs set state='running',lease_token=token,lease_until=t+interval '90 seconds',
  worker_id=p->>'worker_id',claimed_at=t where id=job.id returning * into job;
 update public.analysis_runs set state='running' where id=job.run_id returning * into run;
 if run.workflow_version='error-analysis-v1' then
  update private.analysis_worker_slots set job_id=job.id,lease_token=token,lease_until=job.lease_until where slot=parallel.slot;
 else
  update private.worker_slot set job_id=job.id,lease_token=token,lease_until=job.lease_until where singleton=1;
 end if;
 update public.cases set analysis_status='running' where id=run.case_id and requested_run_id=run.id and not run.evaluation_only;
 return jsonb_build_object('claimed',true,'job',to_jsonb(job),'run',to_jsonb(run));
end $$;

create or replace function private.require_lease(j uuid,token uuid)
returns public.jobs language plpgsql security definer set search_path='' as $$
declare job public.jobs;
begin
 perform 1 from private.worker_slot where singleton=1 for update;
 select * into job from public.jobs where id=j for update;
 if not found or job.state<>'running' or job.lease_token is distinct from token
  or job.lease_until is null or job.lease_until<=clock_timestamp()
  or not (
   exists(select 1 from private.worker_slot where singleton=1 and job_id=j and lease_token=token and lease_until>clock_timestamp())
   or exists(select 1 from private.analysis_worker_slots where job_id=j and lease_token=token and lease_until>clock_timestamp())
  ) then
  raise sqlstate 'PT409' using message='Worker lease expired or replaced';
 end if;
 return job;
end $$;

create or replace function private.heartbeat_job(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; t timestamptz:=clock_timestamp()+interval '90 seconds';
begin
 select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 update public.jobs set lease_until=t where id=job.id;
 update private.worker_slot set lease_until=t where singleton=1 and job_id=job.id and lease_token=job.lease_token;
 update private.analysis_worker_slots set lease_until=t where job_id=job.id and lease_token=job.lease_token;
 return jsonb_build_object('lease_until',t);
end $$;

-- Keep the complete binding, validated-stage, usage, and publication checks in
-- the existing implementation. Lock order is mutex -> job everywhere.
alter function private.error_analysis_complete_run(jsonb) rename to error_analysis_complete_run_before_parallel;
create function private.error_analysis_complete_run(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 perform 1 from private.worker_slot where singleton=1 for update;
 result:=private.error_analysis_complete_run_before_parallel(p);
 update private.analysis_worker_slots set job_id=null,lease_token=null,lease_until=null
  where job_id=(p->>'job_id')::uuid and lease_token=(p->>'lease_token')::uuid
   and exists(select 1 from public.jobs where id=(p->>'job_id')::uuid and state in ('succeeded','failed'));
 return result;
end $$;

-- Overview retains exclusive execution with both old and new workflows.
alter function private.reserve_overview_call(jsonb) rename to reserve_overview_call_before_parallel;
create function private.reserve_overview_call(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
 perform 1 from private.worker_slot where singleton=1 for update;
 if exists(select 1 from private.analysis_worker_slots where lease_until>clock_timestamp()) then
  raise sqlstate 'PT409' using message='Another model run is active';
 end if;
 return private.reserve_overview_call_before_parallel(p);
end $$;

-- Refresh invoker bodies as well, including sessions that previously cached
-- the renamed implementations.
create or replace function public.cfin_error_analysis_complete_run(payload jsonb)
returns jsonb language sql security invoker set search_path='' as $$
 select private.error_analysis_complete_run(payload);
$$;
create or replace function public.cfin_reserve_overview_call(payload jsonb)
returns jsonb language sql security invoker set search_path='' as $$
 select private.reserve_overview_call(payload);
$$;

revoke all on function private.error_analysis_complete_run_before_parallel(jsonb),
 private.reserve_overview_call_before_parallel(jsonb),
 private.error_analysis_complete_run(jsonb),private.reserve_overview_call(jsonb)
 from public,anon,authenticated,service_role;
grant execute on function private.error_analysis_complete_run(jsonb),private.reserve_overview_call(jsonb) to service_role;
commit;
