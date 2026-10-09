begin;
set local statement_timeout='30s';
create or replace function pg_temp.assert(ok boolean,label text) returns void language plpgsql as $$ begin if ok is distinct from true then raise exception 'FAILED: %',label; end if; end $$;
do $probe$
#variable_conflict use_variable
declare
 a uuid:='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'; w uuid:=gen_random_uuid(); c uuid; at_id uuid; proof uuid; foreign_proof uuid; text_proof uuid;
 category text; policy public.error_route_policies; p jsonb; result jsonb; denied boolean; action_name text;
begin
 perform set_config('request.jwt.claim.sub',a::text,true);
 insert into public.workspaces(id,name,synthetic) values(w,'ROLLBACK workbench connection',true);
 insert into public.workspace_memberships(workspace_id,user_id,roles) values(w,a,array['process_owner','mdg_process_owner','data_operations','cfin_exception_manager']);
 foreach category in array array['master_data','mapping','tax','unclassified'] loop
  select * into policy from public.error_route_policies where category_id=category and workspace_id is null and active;
  insert into public.cases(workspace_id,title,workflow_version,analysis_status,category,route_policy_id,route_policy_version,due_at)
   values(w,'Connection test','error-analysis-v1','available',category,policy.id,policy.version,now()+interval '1 day') returning id into c;
  insert into public.attempts(workspace_id,case_id,attempt_key,result) values(w,c,category,'unknown') returning id into at_id;
  update public.cases set current_attempt_id=at_id where id=c;
  insert into public.evidence_versions(workspace_id,source_id,source_version,case_id,attempt_id,kind,filename,object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at,work_cycle)
   values(w,gen_random_uuid()::text,'1',c,at_id,'proof','synthetic-proof.png',w::text||'/'||gen_random_uuid()::text||'/proof.png',repeat('a',64),10,'image/png','{"synthetic":true}',a,now(),1) returning id into proof;
  p:=jsonb_build_object('workspace_id',w,'case_id',c,'expected_version',1,'acting_role','cfin_exception_manager','request_key',gen_random_uuid(),'action','assign','data',jsonb_build_object('note','Explicit handover','owner_role','data_operations','assigned_user_id',a));
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{acting_role}','"mdg_process_owner"')); exception when insufficient_privilege then denied:=true; end; perform pg_temp.assert(denied,'only manager can assign');
  result:=public.cfin_error_workbench_action(p);
  perform pg_temp.assert((select owner_role='data_operations' and assigned_user_id=a from public.assignments where case_id=c order by version desc limit 1),'named handover is persisted');
  perform pg_temp.assert(public.cfin_error_workbench_action(p)=result,'handover retry idempotent');
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,note}','"Changed receipt"')); exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'receipt content conflict rejected');
  p:=p||jsonb_build_object('expected_version',(result->'case'->>'version')::integer,'request_key',gen_random_uuid(),'acting_role','data_operations','action','set_status','data',jsonb_build_object('note','Owner working on case','status','in_progress'));
  result:=public.cfin_error_workbench_action(p);
  perform pg_temp.assert(result->'case'->>'status'='in_progress','named owner can change status');
  denied:=false; begin perform public.cfin_error_workbench_action(p||jsonb_build_object('request_key',gen_random_uuid())); exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'stale save rejected');
  p:=p||jsonb_build_object('expected_version',(result->'case'->>'version')::integer,'request_key',gen_random_uuid(),'acting_role','mdg_process_owner','action','record_approval','data',jsonb_build_object('note','External approval recorded by uploader','external_approver_role','process_owner','evidence_ids',jsonb_build_array(proof)));
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,evidence_ids}','[]')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'approval requires evidence');
  result:=public.cfin_error_workbench_action(p);
  perform pg_temp.assert(exists(select 1 from public.activity where case_id=c and event_type='case_record_approval' and acting_role='mdg_process_owner' and new_value->>'external_approver_role'='process_owner'),'external approver distinct from uploader');
  p:=p||jsonb_build_object('expected_version',(result->'case'->>'version')::integer,'request_key',gen_random_uuid(),'action','comment','data',jsonb_build_object('note','Ordinary case comment','evidence_ids',jsonb_build_array(proof)));
  result:=public.cfin_error_workbench_action(p);
  perform pg_temp.assert(exists(select 1 from public.activity where case_id=c and event_type='case_comment' and new_value->'evidence_ids'=jsonb_build_array(proof)),'comment retains message-linked proof');
  p:=jsonb_build_object('workspace_id',w,'case_id',c,'expected_version',(result->'case'->>'version')::integer,'acting_role','cfin_exception_manager','request_key',gen_random_uuid(),'action','finish_resolution','data',jsonb_build_object('note','Synthetic reprocessing and data validation confirmed','human_confirmed',true,'reprocessing_status','successful','validation_status','passed','posting_reference','DEMO-001','provenance','synthetic','evidence_ids',jsonb_build_array(proof)));
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,evidence_ids}','[]')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'screenshot required');
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,human_confirmed}','false')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'human confirmation required');
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,validation_status}','"failed"')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'failed validation cannot close');
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,reprocessing_status}','"failed"')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'failed reprocessing cannot close');
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{acting_role}','"mdg_process_owner"')); exception when insufficient_privilege then denied:=true; end; perform pg_temp.assert(denied,'nonowner cannot close');
  if foreign_proof is not null then
   denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,evidence_ids}',jsonb_build_array(foreign_proof))); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'other case proof rejected');
  end if;
  insert into public.evidence_versions(workspace_id,source_id,source_version,case_id,attempt_id,kind,filename,object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at,work_cycle)
   values(w,gen_random_uuid()::text,'1',c,at_id,'proof','note.txt',w::text||'/'||gen_random_uuid()::text||'/note.txt',repeat('b',64),10,'text/plain','{"synthetic":true}',a,now(),1) returning id into text_proof;
  denied:=false; begin perform public.cfin_error_workbench_action(jsonb_set(p,'{data,evidence_ids}',jsonb_build_array(text_proof))); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'text file alone cannot replace screenshot');
  result:=public.cfin_error_workbench_action(p);
  perform pg_temp.assert(result->'case'->>'status'='complete','any category closes after recorded successful reprocessing and validation');
  perform pg_temp.assert(public.cfin_error_workbench_action(p)=result,'identical receipt retry is idempotent');
  perform pg_temp.assert((select count(*)=1 from public.resolution_records where case_id=c),'one closure record');
  perform pg_temp.assert((select record->>'provenance'='synthetic' and record->'system_connection_verified'='false'::jsonb from public.resolution_records where case_id=c),'demo closure never claims SAP connectivity');
  perform pg_temp.assert((select private.case_resolved(cs) from public.cases cs where cs.id=c),'saved case is resolved');
  perform pg_temp.assert(not exists(select 1 from public.error_route_milestones where case_id=c),'closure does not invent approvals or route milestones');
  p:=p||jsonb_build_object('expected_version',(result->'case'->>'version')::integer,'request_key',gen_random_uuid(),'action','set_status','data',jsonb_build_object('note','Try reopening','status','in_progress'));
  denied:=false; begin perform public.cfin_case_action(p); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'generic endpoint cannot undo closure');
  denied:=false; begin perform public.cfin_error_route_action(p); exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'route endpoint cannot undo closure');
  foreign_proof:=proof;
 end loop;
 perform pg_temp.assert(not has_function_privilege('authenticated','private.error_route_action_before_workbench(jsonb)','execute'),'old route bypass inaccessible');
 perform pg_temp.assert(not has_function_privilege('anon','public.cfin_error_workbench_action(jsonb)','execute'),'anonymous actions denied');
end $probe$;
rollback;
