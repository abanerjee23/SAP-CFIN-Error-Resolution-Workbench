-- Execute after all migrations in an isolated test database. No provider calls.
-- All synthetic fixtures and commands roll back on success or failure.
begin;
set local statement_timeout='30s';
create function pg_temp.assert(ok boolean,label text) returns void language plpgsql as $$ begin if ok is distinct from true then raise exception 'FAILED: %',label; end if; end $$;
do $probe$
#variable_conflict use_variable
declare
 actor uuid:='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'; w uuid:=gen_random_uuid(); other_w uuid:=gen_random_uuid(); c uuid; at_id uuid; run_id uuid; job_id uuid; lease uuid; bind jsonb; meta jsonb; meta2 jsonb; manifest jsonb; call_id uuid; payload jsonb; result jsonb; output jsonb; extracted jsonb; selected jsonb; summary jsonb; evidence_id uuid; credential uuid; snapshot_id uuid; first_run uuid; saved_version bigint; eval_run uuid; before_case jsonb; historical_id uuid; resolution_id uuid; knowledge_id uuid; proof_id uuid; denied boolean; stage text; check_count integer:=0; guided jsonb; result_checks jsonb; current_case uuid; old_run uuid; history_output jsonb; eval_evidence_id uuid; attestation_id uuid;
begin
 perform set_config('request.jwt.claim.sub',actor::text,true);
 insert into public.workspaces(id,name,synthetic) values(w,'ROLLBACK factual contract',false),(other_w,'ROLLBACK other workspace',false);
 insert into public.workspace_memberships(workspace_id,user_id,roles) values(w,actor,array['process_owner','validator']);
 meta:=jsonb_build_object('source_id','source-'||w,'source_version','1','filename','view.txt','content_type','text/plain','sha256',repeat('a',64),'byte_size',2,'object_path',w::text||'/'||gen_random_uuid()::text||'/view.txt','provenance',jsonb_build_object('kind','user_supplied'),'observed_at',now());
 insert into storage.objects(bucket_id,name,metadata) values('evidence',meta->>'object_path','{"size":2}');
 manifest:=jsonb_build_object('schema_version','log-only-v1','sources',jsonb_build_array(jsonb_build_object('source_id',meta->>'source_id','source_version','1','original_filename','view.txt','content_type','text/plain','content_sha256',repeat('a',64),'byte_size',2,'provenance','user_supplied','readable',jsonb_build_object('status','available','representation','original_utf8','encoding','utf-8','line_count',1,'limitation',null))));
 meta2:=meta||jsonb_build_object('source_id','second-'||w,'object_path',w::text||'/'||gen_random_uuid()::text||'/view.txt');
 insert into storage.objects(bucket_id,name,metadata) values('evidence',meta2->>'object_path','{"size":2}');
 manifest:=jsonb_set(manifest,'{sources}',manifest->'sources'||jsonb_build_array((manifest->'sources'->0)||jsonb_build_object('source_id',meta2->>'source_id')));
 payload:=jsonb_build_object('workspace_id',w,'actor_id',actor,'acting_role','process_owner','delivery_key','rollback-delivery','workflow_version','log-only-v1','manifest',manifest,'source_manifest_sha256',repeat('b',64),'input_sources',jsonb_build_array(meta,meta2),'routing_context',jsonb_build_object('source_system','ERP','interface','AIF','company_code','1000'));
 result:=public.cfin_commit_intake(payload); c:=(result->>'case_id')::uuid; at_id:=(result->>'attempt_id')::uuid; run_id:=(result->'analysis'->>'run_id')::uuid; first_run:=run_id; evidence_id:=(result->>'evidence_id')::uuid;
 perform pg_temp.assert(result->'analysis'->>'queued'='true','provisional factual enqueue');
 perform pg_temp.assert((select count(*)=2 from public.intake_sources where intake_id=(result->>'intake_id')::uuid),'two exact originals with duplicate filenames retained');
 perform pg_temp.assert((select ap.result='unknown' and ap.processing_at is null and processing_order is null from public.attempts ap where id=at_id),'unknown SAP attempt preserved');
 perform pg_temp.assert((select not synthetic from public.evidence_versions where id=evidence_id),'real evidence truthful provenance');
 perform pg_temp.assert(public.cfin_commit_intake(payload)->>'duplicate'='true','delivery idempotence');
 denied:=false; begin perform public.cfin_commit_intake(jsonb_set(payload,'{routing_context,company_code}','"2000"')); exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'conflicting duplicate rejected');
 denied:=false; begin update public.analysis_runs set model_configuration='{}' where id=run_id; exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'model configuration immutable');
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','rollback','run_id',run_id)); perform pg_temp.assert(result->>'claimed'='false','rollout gate keeps factual queued');
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','rollback','run_id',run_id,'log_only_enabled',true));
 job_id:=(result->'job'->>'id')::uuid; lease:=(result->'job'->>'lease_token')::uuid; bind:=result->'run'->'snapshot'->'binding';
 perform pg_temp.assert(bind->>'run_id'=run_id::text and bind->'model_configuration'->>'agent1'='gpt-6-luna','pinned binding restored');
 extracted:='{"schema_version":"log-only-v1","entries":[{"entry_id":"entry-1","raw_text":"X\n"}],"extraction_limitations":[]}';
 selected:='{"schema_version":"log-only-v1","selected_entry_ids":["entry-1"],"unresolved_entry_ids":[]}';
 summary:='{"schema_version":"log-only-v1","title":{"text":"Observed X","supporting_entry_ids":["entry-1"]},"statements":[{"text":"The supplied view reports X.","supporting_entry_ids":["entry-1"]}],"unresolved_details":[],"related_cases":[]}';
 denied:=false; begin perform public.cfin_save_stage(jsonb_build_object('job_id',job_id,'lease_token',lease,'stage','agent1','output',jsonb_build_object('binding',bind||jsonb_build_object('run_id',gen_random_uuid()),'stage','agent1','input_sha256',repeat('c',64),'output',extracted))); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'cross-run nested stage denied');
 foreach stage in array array['agent1','agent2','agent3'] loop
  perform public.cfin_save_stage(jsonb_build_object('job_id',job_id,'lease_token',lease,'stage',stage,'output',jsonb_build_object('binding',bind,'stage',stage,'input_sha256',repeat('c',64),'output',case stage when 'agent1' then extracted when 'agent2' then selected else summary end)));
 end loop;
 denied:=false; begin perform public.cfin_save_stage(jsonb_build_object('job_id',job_id,'lease_token',gen_random_uuid(),'stage','agent1','output',jsonb_build_object('binding',bind,'stage','agent1','input_sha256',repeat('c',64),'output',extracted))); exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'stale lease stage denied');
 denied:=false; begin perform public.cfin_save_stage(jsonb_build_object('job_id',job_id,'lease_token',lease,'stage','agent1','output',jsonb_build_object('binding',bind,'stage','agent1','input_sha256',repeat('e',64),'output',extracted))); exception when sqlstate 'PT409' then denied:=true; end; perform pg_temp.assert(denied,'immutable checkpoint differing input denied');
 perform pg_temp.assert(public.cfin_stage_resume(jsonb_build_object('job_id',job_id,'lease_token',lease))->'outputs'->'agent1'->'binding'=bind,'nested checkpoint recovery');
 output:=bind||jsonb_build_object('result_kind','factual','outcome','completed','source_manifest',manifest,'extraction',extracted,'selection',selected,'summary',summary,'limitations','[]'::jsonb,'failure_reason',null,'history',jsonb_build_object('status','completed','limitation',null,'candidates','[]'::jsonb));
 insert into public.stage_calls(workspace_id,run_id,stage,invocation,model_id,price_version,price_input,price_output,month_start,max_input_tokens,max_output_tokens,reserved_usd,state) values(w,run_id,'agent_1',0,'fake','fixture-v1',0,0,current_date,100,100,0,'usage_unknown') returning id into call_id;
 denied:=false; begin perform public.cfin_complete_run(jsonb_build_object('job_id',job_id,'lease_token',lease,'succeeded',true,'output',output)); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'unknown usage cannot publish');
 update public.stage_calls set state='succeeded',actual_usd=0 where id=call_id;
 result:=public.cfin_complete_run(jsonb_build_object('job_id',job_id,'lease_token',lease,'succeeded',true,'output',output));
 perform pg_temp.assert(result->>'promoted'='true','unknown chronology factual publication');
 perform pg_temp.assert((select title='Observed X' and published_run_id=run_id and factual_result->>'result_kind'='factual' and not attempt_order_known from public.cases where id=c),'factual title preserved without SAP chronology claim');
 saved_version:=(select version from public.cases where id=c);
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',saved_version,'request_key','review','action','review_summary','data',jsonb_build_object('decision','Corrected','reason','Line X is qualified by the reviewer','findings',jsonb_build_object('explanation','Human clarifies scope','entry_ids',jsonb_build_array('entry-1'),'proof_ids','[]'::jsonb,'gaps','[]'::jsonb,'provenance','human_factual_review'))));
 perform pg_temp.assert((select review_kind='factual' and not cause_confirmed from public.case_reviews where case_id=c),'corrected factual review without cause');
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','start','action','start_work','data',jsonb_build_object('reason','Investigate the reported entry','investigation_scope','Supplied log context only')));
 perform pg_temp.assert(result->'case'->>'status'='in_progress','investigation without target-change authority');
 -- Machine identity is scoped independently of portal identity, and never sees token hashes.
 result:=public.cfin_create_read_credential(jsonb_build_object('workspace_id',w,'label','rollback consumer','token_sha256',repeat('d',64),'scopes',jsonb_build_array('cases:read','evidence:read'),'expires_at',now()+interval '1 day')); credential:=(result->>'id')::uuid;
 perform pg_temp.assert(not result ? 'token_sha256','credential response excludes hash');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','cases','limit',1)); snapshot_id:=(result->>'snapshot_id')::uuid;
 perform pg_temp.assert(result->>'total'='1' and jsonb_array_length(result->'items')=1,'machine discovery snapshot');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','source','case_id',c,'source_id',meta->>'source_id','source_version','1'));
 perform pg_temp.assert(result->'evidence'->>'id'=evidence_id::text,'machine exact original read');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','case','case_id',c));
 perform pg_temp.assert(jsonb_array_length(result->'evidence')=2 and result->'case'->'factual_result'->'history'->'candidates'='[]'::jsonb,'machine all originals and private candidate redaction');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',other_w,'token_sha256',repeat('d',64),'resource','cases')); perform pg_temp.assert(result->>'error'='access_denied','machine workspace denial');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','case','case_id',c,'case_version',1)); perform pg_temp.assert(result->>'error'='snapshot_changed','machine snapshot version fence');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','cases','snapshot_id',snapshot_id,'status','blocked','limit',1)); perform pg_temp.assert(result->>'error'='snapshot_changed','snapshot refuses forged filters');
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','records','case_id',c)); perform pg_temp.assert(result->>'total'='1','human records exposed through read scope');
 perform public.cfin_revoke_read_credential(jsonb_build_object('workspace_id',w,'credential_id',credential));
 result:=public.cfin_machine_read(jsonb_build_object('workspace_id',w,'token_sha256',repeat('d',64),'resource','cases','snapshot_id',snapshot_id)); perform pg_temp.assert(result->>'error'='access_denied','revoked token denies cached snapshot');
 -- Evaluation outputs cannot promote cases, alter owner configuration, or supply review milestones.
 before_case:=(select to_jsonb(cs) from public.cases cs where id=c);
 result:=public.cfin_queue_evaluations(jsonb_build_object('workspace_id',w,'case_ids',jsonb_build_array(c),'repeats',1,'reason','ROLLBACK SOFTWARE TEST','configuration',jsonb_build_object('models',(bind->'model_configuration')-'reasoning_effort','reasoning_effort','medium'))); eval_run:=(result->'run_ids'->>0)::uuid;
 perform pg_temp.assert((select excluded_case_ids=jsonb_build_array(c) and snapshot->'binding'->>'run_id'=eval_run::text from public.analysis_runs where id=eval_run),'evaluation exclusion and new binding');
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','rollback','run_id',eval_run,'log_only_enabled',true));
 result:=public.cfin_complete_run(jsonb_build_object('job_id',result->'job'->>'id','lease_token',result->'job'->>'lease_token','succeeded',false,'error_code','deliberate_software_test'));
 perform pg_temp.assert(result->>'promoted'='false' and (select to_jsonb(cs)=before_case from public.cases cs where id=c),'evaluation operational isolation');
 -- A failed operational retry preserves the older factual result and explicit newer failure.
 result:=public.cfin_enqueue_run(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',(select version from public.cases where id=c)));
 run_id:=(result->>'run_id')::uuid;
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','rollback','run_id',run_id,'log_only_enabled',true));
 result:=public.cfin_complete_run(jsonb_build_object('job_id',result->'job'->>'id','lease_token',result->'job'->>'lease_token','succeeded',false,'error_code','deliberate_software_test'));
 perform pg_temp.assert((select published_run_id=first_run and factual_result->'summary'->'title'->>'text'='Observed X' and analysis_status='unavailable' from public.cases where id=c),'failed rerun preserves older result');
 result:=public.cfin_case_page(jsonb_build_object('workspace_id',w,'workflow_version','log-only-v1','factual_review_status','Corrected'));
 perform pg_temp.assert(result->>'total'='1','factual case filters');
 result:=public.cfin_case_page(jsonb_build_object('workspace_id',w,'category','cause_not_established')); perform pg_temp.assert(result->>'total'='0','factual rows excluded from legacy diagnosis filters');
 result:=public.cfin_create_overview_snapshot(jsonb_build_object('workspace_id',w,'filters',jsonb_build_object('workflow_version','log-only-v1')));
 perform pg_temp.assert(result->'metrics'->>'provisional_cases'='1','provisional factual overview');
 perform pg_temp.assert(not has_function_privilege('authenticated','public.cfin_machine_read(jsonb)','execute') and has_function_privilege('service_role','public.cfin_machine_read(jsonb)','execute') and not has_table_privilege('service_role','private.read_credentials','select'),'machine privilege separation');
 perform pg_temp.assert(not has_function_privilege('authenticated','private.commit_intake_legacy(jsonb)','execute'),'legacy private bypass revoked');

 -- A late result with a stale input remains history and cannot change human work.
 result:=public.cfin_enqueue_run(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',(select version from public.cases where id=c)));
 result:=public.cfin_claim_job(jsonb_build_object('worker_id','rollback','run_id',result->>'run_id','log_only_enabled',true));
 update public.cases set input_revision=input_revision+1,analysis_status='needs_refresh' where id=c;
 result:=public.cfin_complete_run(jsonb_build_object('job_id',result->'job'->>'id','lease_token',result->'job'->>'lease_token','succeeded',false,'error_code','deliberate_late_result'));
 perform pg_temp.assert(result->>'promoted'='false' and (select status='in_progress' and analysis_status='needs_refresh' from public.cases where id=c),'stale input cannot overwrite human work');
 -- Human completion uses attributed proof and does not invent a corrective target.
 meta2:=meta||jsonb_build_object('source_id','proof-'||w,'object_path',w::text||'/'||gen_random_uuid()::text||'/view.txt');
 insert into storage.objects(bucket_id,name,metadata) values('evidence',meta2->>'object_path','{"size":2}');
 result:=public.cfin_register_evidence(jsonb_build_object('workspace_id',w,'actor_id',actor,'acting_role','process_owner','case_id',c,'attempt_id',at_id,'work_cycle',1,'kind','proof','storage',meta2)); proof_id:=(result->>'id')::uuid;
 guided:=jsonb_build_object('human_confirmed',true,'action_kind','no_change','findings','The observer verified the supplied input against the business record','action_or_no_change','No target change was required; observation recorded','outcome','Ready to test observed successful processing','scope','The supplied document only','gaps','[]'::jsonb,'proof_ids',jsonb_build_array(proof_id),'occurred_at',now()-interval '1 minute','proof_reuse_reason','Human confirms this attachment applies to the current observed attempt');
 denied:=false; begin perform public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',(select version from public.cases where id=c),'request_key','no-authority','action','record_correction','data',guided)); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'actual target correction still needs authority');
 denied:=false; begin perform public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',(select version from public.cases where id=c),'request_key','unrecorded-corrective-completion','action','complete_work','data',guided||jsonb_build_object('action_kind','corrective_work'))); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'corrective completion cannot bypass authority-backed correction');
 denied:=false; begin
  result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',(select version from public.cases where id=c),'request_key','rollback-correction','action','record_correction','data',guided||jsonb_build_object('target_change_authority',true,'target_system','ERP','target_object','human-observed-object')));
  perform public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','contradictory-no-change','action','complete_work','data',guided));
 exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'no-change completion cannot contradict recorded corrective work');
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',(select version from public.cases where id=c),'request_key','investigation','action','record_investigation','data',guided));
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','complete','action','complete_work','data',guided));
 perform pg_temp.assert(result->'case'->>'status'='complete','no-change human work completion');
 denied:=false; begin perform public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','premature-resolution','action','finish_resolution','data',guided)); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'resolution needs current successful validated attempt');
 payload:=jsonb_build_object('human_confirmed',true,'result','successful','attempt_key','human-success','processing_order',2,'processing_at',now()-interval '30 seconds','target_document_reference','HUMAN-DOC-1','proof_ids',jsonb_build_array(proof_id));
 denied:=false; begin perform public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','unknown-chronology','action','record_reprocessing','data',payload)); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'unknown original chronology requires human confirmation');
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','successful-reprocess','action','record_reprocessing','data',payload||jsonb_build_object('chronology_confirmed',true)));
 result_checks:=(select jsonb_agg(jsonb_build_object('dimension',dim,'expected','observed value','observed','observed value','result','passed')) from unnest(array['amount_currency','company','accounts','source_target_reference']) dim);
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','validate','action','record_validation','data',guided||jsonb_build_object('status','passed','checks',result_checks)));
 perform pg_temp.assert((select private.machine_case(cs)->'resolved'='false'::jsonb from public.cases cs where cs.id=c),'machine case distinguishes validated from resolved');
 denied:=false; begin perform public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','mismatched-resolution','action','finish_resolution','data',guided||jsonb_build_object('action_kind','corrective_work'))); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'resolution action kind matches completed work');
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','resolve','action','finish_resolution','data',guided||jsonb_build_object('occurred_at',clock_timestamp())));
 perform pg_temp.assert((select count(*)=1 from public.resolution_records where case_id=c and record->>'workflow_version'='log-only-v1'),'factual human resolution without cause label');
 perform pg_temp.assert((select private.machine_case(cs)->'resolved'='true'::jsonb from public.cases cs where cs.id=c),'machine case resolution matches portal');
 result:=public.cfin_case_action(jsonb_build_object('workspace_id',w,'case_id',c,'acting_role','process_owner','expected_version',result->'case'->'version','request_key','context-owner','action','assign','data',jsonb_build_object('assigned_user_id',actor,'owner_role','process_owner','reason','Explicit routing context ownership','save_owner_rule',true,'expected_owner_rule_version',0,'owner_rule_review_due',current_date+30)));
 perform pg_temp.assert(result->'owner_rule'->>'category'='factual_context','context ownership independent of cause');
 -- Pin historical originals to the knowledge version and test withdrawal without
 -- throwing away valid current facts or exposing an unused historical candidate.
 select id into resolution_id from public.resolution_records where case_id=c;
 payload:=jsonb_build_object('workspace_id',w,'resolution_id',resolution_id,'lesson','ROLLBACK reviewed historical factual lesson','reason','ROLLBACK SOFTWARE TEST: explicit applicability','scope',jsonb_build_object('workflow_version','log-only-v1','applicability','Observed no-change resolution for the reviewed document only','reuse_limitations','No general cause or corrective recommendation','context',jsonb_build_object('source_system','ERP','interface','AIF','company_code','1000')),'concept_vector',to_jsonb(array_fill(0::real,array[64]))::text);
 result:=public.cfin_knowledge_draft(payload); knowledge_id:=(result->>'id')::uuid;
 perform pg_temp.assert(result->>'reuse_state'='pending_review' and result->'scope'->>'workflow_version'='log-only-v1','factual knowledge draft without cause/category');
 denied:=false; begin perform public.cfin_knowledge_review(jsonb_build_object('workspace_id',w,'knowledge_id',knowledge_id,'expected_version',1,'decision','approved','reason','ROLLBACK POLICY GUARD')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'knowledge needs explicit evaluation policy');
 perform public.cfin_publication_policy(jsonb_build_object('workspace_id',w,'minimum_cases',1,'minimum_pass_rate',1,'maximum_critical_failures',0,'require_human_review',true,'reason','ROLLBACK SOFTWARE POLICY'));
 denied:=false; begin perform public.cfin_knowledge_review(jsonb_build_object('workspace_id',w,'knowledge_id',knowledge_id,'expected_version',1,'decision','approved','reason','ROLLBACK ATTESTATION GUARD')); exception when sqlstate 'PT422' then denied:=true; end; perform pg_temp.assert(denied,'knowledge needs exact reviewed evaluation evidence');
 meta2:=meta||jsonb_build_object('source_id','evaluation-report-'||w,'filename','evaluation.json','content_type','application/json','object_path',w::text||'/'||gen_random_uuid()::text||'/evaluation.json');
 insert into storage.objects(bucket_id,name,metadata) values('evidence',meta2->>'object_path','{"size":2}');
 result:=public.cfin_register_evidence(jsonb_build_object('workspace_id',w,'actor_id',actor,'acting_role','process_owner','kind','reference','storage',meta2)); eval_evidence_id:=(result->>'id')::uuid;
 result:=public.cfin_attest_knowledge_evaluation(jsonb_build_object('workspace_id',w,'actor_id',actor,'knowledge_id',knowledge_id,'evidence_id',eval_evidence_id,'report_sha256',repeat('a',64),'human_reviewed',true,'reason','ROLLBACK SOFTWARE FIXTURE; not a real quality approval','observations',jsonb_build_object('knowledge_id',knowledge_id,'cases',1,'passed_cases',1,'critical_failures',0))); attestation_id:=(result->>'id')::uuid;
 result:=public.cfin_knowledge_review(jsonb_build_object('workspace_id',w,'knowledge_id',knowledge_id,'expected_version',1,'decision','approved','evaluation_evidence_id',attestation_id,'reason','ROLLBACK SOFTWARE APPROVAL: exact gates checked'));
 perform pg_temp.assert(result->>'reuse_state'='approved' and result->'resolution_snapshot'->>'cause_confirmed'='false','factual approved findings do not assert a confirmed cause');
 result:=public.cfin_search_history(jsonb_build_object('workspace_id',w,'actor_id',actor,'query','','filters',jsonb_build_object('company_code','1000')));
 perform pg_temp.assert(jsonb_array_length(result->'items')=1 and result->'items'->0->'synthetic'='false'::jsonb,'factual history context and real provenance stay truthful');
 perform pg_temp.assert((select jsonb_array_length(original_sources)=2 from public.knowledge_versions where id=knowledge_id),'knowledge pins exact original evidence versions');
 insert into public.cases(workspace_id,title,due_at,workflow_version) values(w,'ROLLBACK second current case',now(),'log-only-v1') returning id into current_case;
 result:=public.cfin_load_history_evidence(jsonb_build_object('workspace_id',w,'actor_id',actor,'current_case_id',current_case,'knowledge_id',knowledge_id,'version',1));
 perform pg_temp.assert(jsonb_array_length(result->'originals')=2,'exact reviewed historical originals loaded');
 denied:=false; begin perform public.cfin_load_history_evidence(jsonb_build_object('workspace_id',w,'actor_id',actor,'current_case_id',c,'knowledge_id',knowledge_id,'version',1)); exception when sqlstate 'PT404' then denied:=true; end; perform pg_temp.assert(denied,'current case cannot become its own historical answer');
 history_output:=output||jsonb_build_object('summary',summary||jsonb_build_object('related_cases',jsonb_build_array(jsonb_build_object('case_id',c,'knowledge_id',knowledge_id,'knowledge_version',1))), 'history',jsonb_build_object('status','completed','candidates',jsonb_build_array(jsonb_build_object('knowledge_id',knowledge_id,'content','Retained private audit content'))));
 result:=private.filter_factual_history(history_output,w,null,true); perform pg_temp.assert(jsonb_array_length(result->'summary'->'related_cases')=1 and jsonb_array_length(result->'history'->'candidates')=1,'eligible citation and native candidate audit retained');
 perform public.cfin_knowledge_review(jsonb_build_object('workspace_id',w,'knowledge_id',knowledge_id,'expected_version',2,'decision','withdrawn','reason','ROLLBACK withdrawal regression'));
 result:=private.filter_factual_history(history_output,w,null,false); perform pg_temp.assert(jsonb_array_length(result->'summary'->'related_cases')=0 and result->'summary'->'title'=summary->'title' and jsonb_array_length(result->'limitations')=1 and result->'history'->'candidates'='[]'::jsonb,'withdrawal withholds related content and preserves current facts');
 result:=private.filter_factual_history(output,w,null,false); perform pg_temp.assert(result->'limitations'='[]'::jsonb,'unused withdrawn candidate does not degrade brief');
 perform pg_temp.assert((select count(*)>=2 from private.machine_read_audit where credential_id=credential and outcome='denied'),'denied requests audit without private payload');
 raise notice 'PASS: intake/provenance/duplicates, pinned versions, provisional publication, nested checkpoints, factual human review/investigation/authority/no-change resolution, reviewed knowledge gates/pinned originals/withdrawal, machine snapshots/revocation/scope, evaluation isolation, failed rerun preservation, filters and grants';
end $probe$;
rollback;
