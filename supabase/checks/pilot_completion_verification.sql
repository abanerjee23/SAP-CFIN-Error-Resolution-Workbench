begin;
set local statement_timeout='30s';
create or replace function pg_temp.assert(ok boolean,label text) returns void language plpgsql as $$ begin if ok is distinct from true then raise exception 'FAILED: %',label; end if; end $$;
do $probe$
#variable_conflict use_variable
declare
 actor uuid:='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'; w uuid:=gen_random_uuid(); c uuid; at_id uuid; proof uuid; other_proof uuid;
 policy public.error_route_policies; p jsonb; result jsonb; retry jsonb; denied boolean; i integer; path text; scenario text; saved_version bigint; run_id uuid; claim jsonb;
begin
 perform set_config('request.jwt.claim.sub',actor::text,true);
 insert into public.workspaces(id,name,synthetic) values(w,'ROLLBACK pilot workflow',true);
 insert into public.workspace_memberships(workspace_id,user_id,roles) values(w,actor,array['process_owner','mdg_process_owner','data_operations','cfin_exception_manager']);
 select * into policy from public.error_route_policies where category_id='master_data' and workspace_id is null and active;
 foreach scenario in array array['success','rejected','failed'] loop
  insert into public.cases(workspace_id,title,workflow_version,analysis_status,category,route_policy_id,route_policy_version,due_at) values(w,'Pilot guard test','error-analysis-v1','available','master_data',policy.id,policy.version,now()+interval '1 day') returning id into c;
  insert into public.attempts(workspace_id,case_id,attempt_key,result) values(w,c,scenario,'unknown') returning id into at_id;
  update public.cases set current_attempt_id=at_id where id=c;
  path:=w::text||'/'||gen_random_uuid()::text||'/proof.txt';
  insert into public.evidence_versions(workspace_id,source_id,source_version,case_id,attempt_id,kind,filename,object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at,work_cycle) values(w,gen_random_uuid()::text,'1',c,at_id,'proof','proof.txt',path,repeat('a',64),10,'text/plain','{"synthetic":true}',actor,now(),1) returning id into proof;
  p:=jsonb_build_object('workspace_id',w,'case_id',c,'expected_version',1,'acting_role','data_operations','request_key',gen_random_uuid(),'action','finish_resolution','data',jsonb_build_object('note','Validated fixture','human_confirmed',true,'posting_reference','SYNTHETIC-001','evidence_ids',jsonb_build_array(proof)));
  denied:=false; begin perform public.cfin_error_workbench_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'cannot close before successful route');
  denied:=false; begin perform public.cfin_case_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'legacy endpoint cannot bypass closure guard');
  for i in 1..7 loop
   p:=jsonb_build_object('workspace_id',w,'case_id',c,'expected_version',(select version from public.cases where id=c),'acting_role',policy.steps->(i-1)->>'required_role','request_key',gen_random_uuid(),'data',jsonb_build_object('note','Synthetic step '||i,'evidence_ids',jsonb_build_array(proof)));
   if i=1 then
    denied:=false; begin perform public.cfin_error_route_action(p||'{"acting_role":"process_owner"}'::jsonb); exception when insufficient_privilege then denied:=true; end; perform pg_temp.assert(denied,'wrong step role denied');
   end if;
   if i=2 then
    denied:=false; begin perform public.cfin_error_route_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'missing explicit approval denied');
    p:=jsonb_set(p,'{data,decision}',to_jsonb(case when scenario='rejected' then 'rejected' else 'approved' end));
    denied:=false; begin perform public.cfin_error_route_action(jsonb_set(p,'{data,evidence_ids}','[]')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'approval evidence required');
   end if;
   if i=4 then
    denied:=false; begin perform public.cfin_error_route_action(jsonb_set(p,'{data,evidence_ids}','[]')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'implementation evidence required');
   end if;
   if i=7 then
    denied:=false; begin perform public.cfin_error_route_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'posting outcome required');
    p:=jsonb_set(p,'{data,decision}',to_jsonb(case when scenario='failed' then 'failed' else 'completed' end));
    if scenario='success' then
     denied:=false; begin perform public.cfin_error_route_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'successful posting reference required');
     p:=jsonb_set(p,'{data,posting_reference}','"SYNTHETIC-001"');
    end if;
   end if;
   result:=public.cfin_error_route_action(p);
   retry:=public.cfin_error_route_action(p); perform pg_temp.assert(retry=result,'duplicate step response stable');
   if scenario='rejected' and i=2 then exit; end if;
  end loop;
  p:=jsonb_build_object('workspace_id',w,'case_id',c,'expected_version',(select version from public.cases where id=c),'acting_role','data_operations','request_key',gen_random_uuid(),'action','finish_resolution','data',jsonb_build_object('note','Validated synthetic posting','human_confirmed',true,'posting_reference','SYNTHETIC-001','evidence_ids',jsonb_build_array(proof)));
  if scenario='success' then
   denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,evidence_ids}','[]')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'closure requires validation proof');
   denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,human_confirmed}','false')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'closure requires human validation');
   result:=public.cfin_error_workbench_action(p);
   perform pg_temp.assert(result->'case'->>'status'='complete','successful case closed');
   perform pg_temp.assert((select count(*)=1 from public.resolution_records where case_id=c),'one persistent resolution');
   perform pg_temp.assert((select private.case_resolved(cs) from public.cases cs where cs.id=c),'machine and portal agree case is resolved');
   perform pg_temp.assert(public.cfin_error_workbench_action(p)=result,'duplicate closure stable');
  else
   perform pg_temp.assert((select route_state='escalated' and status='blocked' from public.cases where id=c),'rejection or failed posting escalates');
   denied:=false; begin perform public.cfin_error_workbench_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'failed route cannot close');
  end if;
 end loop;
 insert into public.analysis_runs(workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by,workflow_version,schema_version)
 values(w,c,at_id,repeat('f',64),'{"binding":{},"source_manifest":{}}',(select version from public.cases where id=c),1,actor,'error-analysis-v1','error-analysis-v1') returning id into run_id;
 insert into public.jobs(workspace_id,run_id) values(w,run_id);
 update public.cases set requested_run_id=run_id,analysis_status='pending' where id=c;
 claim:=public.cfin_claim_job(jsonb_build_object('worker_id','pilot-regression','run_id',run_id,'log_only_enabled',true));
 perform pg_temp.assert(claim->>'claimed'='true','analysis failure test claimed');
 result:=public.cfin_error_analysis_complete_run(jsonb_build_object('job_id',claim->'job'->>'id','lease_token',claim->'job'->>'lease_token','succeeded',false,'output',null,'error_code','synthetic_pre_model_failure'));
 perform pg_temp.assert((select analysis_status='unavailable' from public.cases where id=c),'empty failure result published as unavailable');
 perform pg_temp.assert((select state='failed' and lease_token is null from public.jobs where jobs.run_id=run_id),'failed job releases lease');
 perform pg_temp.assert(not has_function_privilege('authenticated','private.case_action_before_pilot(jsonb)','execute'),'old generic bypass inaccessible');
 perform pg_temp.assert(not has_function_privilege('anon','public.cfin_error_workbench_action(jsonb)','execute'),'anonymous writes denied');
end $probe$;
rollback;
