-- Run only against a disposable database after all migrations. Every row rolls back.
begin;
set local statement_timeout='30s';
create or replace function pg_temp.assert(ok boolean,label text) returns void language plpgsql as $$
begin if ok is distinct from true then raise exception 'FAILED: %',label; end if; end $$;
create function pg_temp.queue_case(w uuid,a uuid,workflow text) returns uuid language plpgsql as $$
declare c uuid; at_id uuid; run_id uuid:=gen_random_uuid();
begin
 insert into public.cases(workspace_id,title,workflow_version,due_at) values(w,'Concurrency fixture',workflow,now()+interval '1 day') returning id into c;
 insert into public.attempts(workspace_id,case_id,attempt_key,result) values(w,c,'concurrency','unknown') returning id into at_id;
 insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,requested_by,workflow_version)
  values(run_id,w,c,at_id,encode(sha256(run_id::text::bytea),'hex'),jsonb_build_object('binding',jsonb_build_object('run_id',run_id),'source_manifest','{}'::jsonb),1,a,workflow);
 update public.cases set current_attempt_id=at_id,requested_run_id=run_id where id=c;
 insert into public.jobs(workspace_id,run_id) values(w,run_id);
 return run_id;
end $$;
do $probe$
declare
 a uuid:='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'; w uuid:=gen_random_uuid();
 run_a uuid; run_b uuid; run_c uuid; legacy uuid; same_case uuid:=gen_random_uuid();
 first jsonb; second jsonb; recovered jsonb; result jsonb; params jsonb; candidate jsonb;
 denied boolean; call_id uuid; slot_until timestamptz;
begin
 perform pg_temp.assert(not exists(select 1 from public.jobs where state in ('queued','running')),'disposable queue starts empty');
 insert into public.workspaces(id,name,synthetic) values(w,'ROLLBACK parallel analysis',true);
 insert into public.workspace_memberships(workspace_id,user_id,roles) values(w,a,array['process_owner']);
 run_a:=pg_temp.queue_case(w,a,'error-analysis-v1');
 run_b:=pg_temp.queue_case(w,a,'error-analysis-v1');
 run_c:=pg_temp.queue_case(w,a,'error-analysis-v1');
 legacy:=pg_temp.queue_case(w,a,'legacy-v1');
 first:=public.cfin_claim_job(jsonb_build_object('worker_id','one','run_id',run_a));
 second:=public.cfin_claim_job(jsonb_build_object('worker_id','two','run_id',run_b));
 perform pg_temp.assert(first->>'claimed'='true' and second->>'claimed'='true','two independent cases claim together');
 perform pg_temp.assert((select count(*)=2 from private.analysis_worker_slots where job_id is not null),'both slots occupied');
 perform pg_temp.assert((public.cfin_claim_job(jsonb_build_object('worker_id','three','run_id',run_c))->>'claimed')='false','third case waits');
 perform pg_temp.assert((public.cfin_claim_job(jsonb_build_object('worker_id','duplicate','run_id',run_a))->>'claimed')='false','same job cannot be claimed twice');
 perform pg_temp.assert((public.cfin_claim_job(jsonb_build_object('worker_id','legacy','run_id',legacy))->>'claimed')='false','legacy remains exclusive');
 denied:=false;
 begin perform public.cfin_reserve_overview_call('{}'); exception when sqlstate 'PT409' then denied:=true; end;
 perform pg_temp.assert(denied,'overview cannot overlap analysis slots');

 params:=jsonb_build_object('job_id',first->'job'->>'id','lease_token',first->'job'->>'lease_token');
 denied:=false;
 begin perform public.cfin_heartbeat_job(params||jsonb_build_object('lease_token',second->'job'->>'lease_token')); exception when sqlstate 'PT409' then denied:=true; end;
 perform pg_temp.assert(denied,'another worker token cannot heartbeat this case');
 slot_until:=(public.cfin_heartbeat_job(params)->>'lease_until')::timestamptz;
 perform pg_temp.assert((select lease_until=slot_until from private.analysis_worker_slots where job_id=(first->'job'->>'id')::uuid),'heartbeat extends its parallel slot');
 result:=public.cfin_reserve_call(params||jsonb_build_object('stage','agent_1','invocation',0,'model_id','gpt-6.1-sol','max_input_tokens',100,'max_output_tokens',100));
 call_id:=(result->'call'->>'id')::uuid;
 perform pg_temp.assert(result->>'execute'='true','parallel job retains durable model reservation');
 perform pg_temp.assert((public.cfin_reserve_call(params||jsonb_build_object('stage','agent_1','invocation',0,'model_id','gpt-6.1-sol','max_input_tokens',100,'max_output_tokens',100))->>'execute')='false','duplicate dispatch remains blocked');
 denied:=false;
 begin perform public.cfin_reserve_call(params||jsonb_build_object('stage','agent_2','invocation',0,'model_id','gpt-6.1-sol','max_input_tokens',100,'max_output_tokens',100,'monthly_budget_usd',0.001)); exception when sqlstate 'PT422' then denied:=true; end;
 perform pg_temp.assert(denied,'existing spend counts against configured budget');

 -- Simulate process death: lease recovery must preserve unknown cost and fence old ownership.
 update public.jobs set lease_until=clock_timestamp()-interval '1 second' where id=(first->'job'->>'id')::uuid;
 update private.analysis_worker_slots set lease_until=clock_timestamp()-interval '1 second' where job_id=(first->'job'->>'id')::uuid;
 recovered:=public.cfin_claim_job(jsonb_build_object('worker_id','recovered','run_id',run_a));
 perform pg_temp.assert(recovered->>'claimed'='true' and recovered->'job'->>'lease_token'<>first->'job'->>'lease_token','expired worker receives fresh lease');
 perform pg_temp.assert((select state='usage_unknown' and actual_usd is null and reserved_usd>0 from public.stage_calls where id=call_id),'crash preserves unresolved spend');
 perform pg_temp.assert((select lease_token=(second->'job'->>'lease_token')::uuid from private.analysis_worker_slots where job_id=(second->'job'->>'id')::uuid),'recovery does not disturb other live worker');
 denied:=false;
 begin perform public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',false,'output',null)); exception when sqlstate 'PT409' then denied:=true; end;
 perform pg_temp.assert(denied,'old worker cannot complete after lease replacement');
 denied:=false;
 begin perform public.cfin_reconcile_call(params||jsonb_build_object('call_id',call_id,'state','succeeded','usage',jsonb_build_object('input_tokens',1,'output_tokens',1))); exception when sqlstate 'PT409' then denied:=true; end;
 perform pg_temp.assert(denied,'old worker cannot reconcile another lease');
 params:=jsonb_build_object('job_id',recovered->'job'->>'id','lease_token',recovered->'job'->>'lease_token');
 denied:=false;
 begin perform public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',true,'output',jsonb_build_object('run_id',run_a,'result_kind','error_analysis','source_manifest','{}'::jsonb,'outcome','completed'))); exception when sqlstate 'PT422' then denied:=true; end;
 perform pg_temp.assert(denied,'unvalidated or unreconciled result cannot publish');
 candidate:=jsonb_build_object('run_id',run_a,'result_kind','error_analysis','source_manifest','{}'::jsonb,
  'outcome','completed','extraction','{}'::jsonb,'analysis',jsonb_build_object('category_id','unclassified'),
  'case_content',jsonb_build_object('title',jsonb_build_object('text','Database publication fixture'),'what_happened','[]'::jsonb));
 -- These fixture checkpoints stand in for validated application output; no model calls are made.
 insert into public.validated_stages(workspace_id,run_id,stage,output) values
  (w,run_a,'agent1',jsonb_build_object('output',candidate->'extraction')),
  (w,run_a,'agent2',jsonb_build_object('output',candidate->'analysis')),
  (w,run_a,'agent3',jsonb_build_object('output',candidate->'case_content'));
 denied:=false;
 begin perform public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',true,'output',candidate)); exception when sqlstate 'PT422' then denied:=true; end;
 perform pg_temp.assert(denied,'validated stages cannot bypass unresolved model spend');

 result:=public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',false,'output',null,'error_code','test_timeout'));
 perform pg_temp.assert(result->>'promoted'='true','failure persists for current run');
 perform pg_temp.assert((select count(*)=1 from private.analysis_worker_slots where job_id is not null),'failure frees only its own slot');
 perform pg_temp.assert((public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',false,'output',null))->>'duplicate')='true','completion receipt is idempotent');

 -- Even a newer snapshot of the same case cannot consume the second slot.
 insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,requested_by,workflow_version)
  select same_case,workspace_id,case_id,attempt_id,repeat('c',64),'{}',1,a,'error-analysis-v1' from public.analysis_runs where id=run_b;
 insert into public.jobs(workspace_id,run_id) values(w,same_case);
 perform pg_temp.assert((public.cfin_claim_job(jsonb_build_object('worker_id','same-case','run_id',same_case))->>'claimed')='false','one active analysis per case');
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','third-now','run_id',run_c));
 perform pg_temp.assert(result->>'claimed'='true','waiting third case claims released capacity');
 params:=jsonb_build_object('job_id',result->'job'->>'id','lease_token',result->'job'->>'lease_token');
 denied:=false;
 begin perform public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',true,'output',candidate)); exception when sqlstate 'PT422' then denied:=true; end;
 perform pg_temp.assert(denied,'another case result cannot publish into this slot');
 candidate:=jsonb_set(candidate,'{run_id}',to_jsonb(run_c));
 insert into public.validated_stages(workspace_id,run_id,stage,output) values
  (w,run_c,'agent1',jsonb_build_object('output',candidate->'extraction')),
  (w,run_c,'agent2',jsonb_build_object('output',candidate->'analysis')),
  (w,run_c,'agent3',jsonb_build_object('output',candidate->'case_content'));
 result:=public.cfin_error_analysis_complete_run(params||jsonb_build_object('succeeded',true,'output',candidate));
 perform pg_temp.assert(result->>'promoted'='true','validated bound result publishes');
 perform pg_temp.assert((select analysis_status='available' and published_run_id=run_c from public.cases where requested_run_id=run_c),'successful completion is visible');
 perform pg_temp.assert((select count(*)=1 from private.analysis_worker_slots where job_id is not null),'success also frees only its own slot');
 perform public.cfin_error_analysis_complete_run(jsonb_build_object('job_id',second->'job'->>'id','lease_token',second->'job'->>'lease_token','succeeded',false,'output',null));
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','legacy-now','run_id',legacy));
 perform pg_temp.assert(result->>'claimed'='true','legacy claims after analysis jobs finish');
 perform pg_temp.assert((public.cfin_claim_job(jsonb_build_object('worker_id','wait-for-legacy','run_id',same_case))->>'claimed')='false','legacy lease blocks every analysis slot');
 perform pg_temp.assert((select lease_token=(result->'job'->>'lease_token')::uuid from private.worker_slot where singleton=1),'legacy keeps original singleton');
 perform public.cfin_heartbeat_job(jsonb_build_object('job_id',result->'job'->>'id','lease_token',result->'job'->>'lease_token'));

 -- Overview also blocks new analyses while its exclusive lease is live.
 update private.worker_slot set job_id=null,lease_token=gen_random_uuid(),lease_until=clock_timestamp()+interval '90 seconds' where singleton=1;
 perform pg_temp.assert((public.cfin_claim_job(jsonb_build_object('worker_id','wait-for-overview','run_id',same_case))->>'claimed')='false','overview lease blocks analysis');
 perform pg_temp.assert(not has_table_privilege('service_role','private.analysis_worker_slots','UPDATE'),'service cannot bypass slot claims');
 perform pg_temp.assert(not has_function_privilege('service_role','private.error_analysis_complete_run_before_parallel(jsonb)','EXECUTE'),'old completion bypass inaccessible');
 perform pg_temp.assert(not has_function_privilege('service_role','private.reserve_overview_call_before_parallel(jsonb)','EXECUTE'),'old overview bypass inaccessible');
 perform pg_temp.assert(has_function_privilege('service_role','private.error_analysis_complete_run(jsonb)','EXECUTE'),'service retains completion RPC');
 perform pg_temp.assert(not has_function_privilege('authenticated','private.error_analysis_complete_run(jsonb)','EXECUTE'),'user cannot impersonate worker');
end $probe$;
rollback;
