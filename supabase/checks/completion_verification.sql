-- PREPARED ONLY. Run the entire file as postgres AFTER migrations 002-007.
-- Stop both workers first. This probes SQL contracts with explicitly labelled
-- database rows; it does not upload Storage bytes, call models, send messages,
-- provide real human approvals, or establish model/evaluation quality.
-- All fixture changes, reservations and settings are rolled back, even on error.
-- The chosen actor is an existing confirmed Auth account; no Auth user is made.
begin;
set local statement_timeout = '25s';
set local lock_timeout = '2s';
create temporary table cfin_completion_verification_report(report jsonb) on commit drop;

do $verification$
<<probe>>
declare
  actor uuid;
  workspace uuid:=gen_random_uuid();
  foreign_workspace uuid:=gen_random_uuid();
  case_id uuid:=gen_random_uuid();
  alias_id uuid:=gen_random_uuid();
  attempt_id uuid:=gen_random_uuid();
  intake_id uuid:=gen_random_uuid();
  evidence_id uuid;
  original_id uuid;
  original_run uuid;
  evaluation_run uuid;
  job_id uuid;
  lease uuid;
  notification_id uuid;
  notification_lease uuid;
  overview_id uuid;
  group_id uuid;
  call_id uuid;
  expected_version bigint;
  before_case jsonb;
  result jsonb;
  payload jsonb;
  manifest jsonb;
  filename text;
  table_name text;
  function_name text;
  relation_oid oid;
  public_oid oid;
  private_oid oid;
  denied boolean;
  passed boolean:=false;
  error_code text;
  error_message text;
  checks jsonb:='[]';
  old_slot jsonb;
  old_jobs jsonb;
  old_notifications jsonb;
  old_job_ids uuid[];
  old_notification_ids uuid[];
  tables text[]:=array['intake_sources','input_controls','overview_snapshots',
    'overview_members','overview_groups','overview_runs','knowledge_versions',
    'knowledge_feedback','knowledge_publication_policies',
    'knowledge_evaluation_attestations','run_knowledge_sources','validated_stages',
    'evaluation_batches','owner_rules'];
  user_functions text[]:=array['intake_control','create_overview_snapshot','read_overview_snapshot',
    'overview_group','knowledge_reviews','knowledge_version','knowledge_draft','knowledge_review',
    'knowledge_feedback','review_knowledge_feedback','publication_policy',
    'queue_evaluations','case_page','workspace_directory'];
  shared_functions text[]:=array['search_history','revalidate_history'];
  service_functions text[]:=array['reserve_overview_call','complete_overview_call',
    'attest_knowledge_evaluation','register_run_history','stage_resume','save_stage',
    'fail_stage','preparation_reuse','claim_notification','complete_notification'];
  filenames text[]:=array['original-log.txt','manifest.json','source-posting.json',
    'mapping-reference.json','target-master-lookup.json','target-master-query-audit.json',
    'missing-gl-master-playbook.json','owner-directory.json','source-catalogue.json'];
begin
  begin
    if current_user<>'postgres' then raise exception 'Use the SQL editor postgres role'; end if;
    select id into actor from auth.users where email_confirmed_at is not null order by created_at,id limit 1;
    if actor is null then raise exception 'An existing confirmed Auth account is required'; end if;

    foreach table_name in array tables loop
      relation_oid:=to_regclass('public.'||table_name);
      if relation_oid is null or not (select relrowsecurity from pg_class where oid=relation_oid)
        or not has_table_privilege('authenticated',relation_oid,'SELECT')
        or has_table_privilege('anon',relation_oid,'SELECT')
        or has_table_privilege('authenticated',relation_oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        or has_table_privilege('anon',relation_oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        or exists(select 1 from pg_policy where polrelid=relation_oid and polcmd<>'r') then
        raise exception 'RLS/read-only browser grants differ on public.%',table_name;
      end if;
    end loop;
    foreach function_name in array user_functions||shared_functions||service_functions loop
      public_oid:=to_regprocedure('public.cfin_'||function_name||'(jsonb)');
      private_oid:=to_regprocedure('private.'||function_name||'(jsonb)');
      if public_oid is null or private_oid is null
        or (select prosecdef from pg_proc where oid=public_oid)
        or not (select prosecdef from pg_proc where oid=private_oid)
        or not (select coalesce(proconfig @> array['search_path=""'],false) from pg_proc where oid=public_oid)
        or not (select coalesce(proconfig @> array['search_path=""'],false) from pg_proc where oid=private_oid)
        or has_function_privilege('anon',public_oid,'EXECUTE')
        or has_function_privilege('anon',private_oid,'EXECUTE')
        or has_function_privilege('authenticated',public_oid,'EXECUTE') is distinct from (function_name=any(user_functions||shared_functions))
        or has_function_privilege('authenticated',private_oid,'EXECUTE') is distinct from (function_name=any(user_functions||shared_functions))
        or has_function_privilege('service_role',public_oid,'EXECUTE') is distinct from (function_name=any(service_functions||shared_functions))
        or has_function_privilege('service_role',private_oid,'EXECUTE') is distinct from (function_name=any(service_functions||shared_functions)) then
        raise exception 'RPC boundary/grants differ for %',function_name;
      end if;
    end loop;
    checks:=checks||jsonb_build_array(jsonb_build_object('check','new_schema_rls_and_rpc_privileges','passed',true));

    -- Fail closed against live workers. Existing queues are restored by the
    -- enclosing subtransaction rollback, without compensating updates.
    perform 1 from private.worker_slot where singleton=1 for update nowait;
    lock table public.jobs in share row exclusive mode nowait;
    lock table public.notifications in share row exclusive mode nowait;
    if (select count(*) from private.worker_slot where singleton=1)<>1
      or exists(select 1 from private.worker_slot ws where ws.job_id is not null or ws.lease_token is not null or ws.lease_until is not null)
      or exists(select 1 from public.jobs where state='running')
      or exists(select 1 from public.overview_runs where state='in_flight')
      or exists(select 1 from public.notifications where lease_token is not null) then
      raise exception 'Stop model and notification workers before verification';
    end if;
    select to_jsonb(s) into old_slot from private.worker_slot s where singleton=1;
    select coalesce(array_agg(id order by id),'{}'),coalesce(jsonb_agg(to_jsonb(j) order by id),'[]')
      into old_job_ids,old_jobs from public.jobs j where state='queued';
    select coalesce(array_agg(id order by id),'{}'),coalesce(jsonb_agg(to_jsonb(n) order by id),'[]')
      into old_notification_ids,old_notifications from public.notifications n where state='queued';
    update public.jobs set available_at=clock_timestamp()+interval '100 years' where state='queued';
    update public.notifications set available_at=clock_timestamp()+interval '100 years' where state='queued';

    insert into public.workspaces(id,name) values(workspace,'ROLLBACK ONLY: completion contracts'),
      (foreign_workspace,'ROLLBACK ONLY: foreign completion contracts');
    insert into public.workspace_memberships(workspace_id,user_id,roles)
      values(workspace,actor,array['process_owner','master_data_owner']);
    insert into public.cases(id,workspace_id,title,due_at,source_system,source_client,
      source_company_code,fiscal_year,document_number,target_system,target_client,interface,business_context)
      values(case_id,workspace,'ROLLBACK ONLY: no model result',now()+interval '1 day',
        'ROLLBACK','100','1000','2026','rollback-1','ROLLBACK-TARGET','200','CFIN',
        '{"company_code":"1000","target_account":"rollback-target"}');
    insert into public.attempts(id,workspace_id,case_id,attempt_key,processing_at,processing_order,result)
      values(attempt_id,workspace,case_id,'rollback-failure-1',now()-interval '1 day',1,'failed');
    update public.cases set current_attempt_id=attempt_id,attempt_order_known=true where id=probe.case_id;
    manifest:=jsonb_build_object('synthetic',true,'attempt_id','rollback-failure-1',
      'business_context',jsonb_build_object('company_code','1000','target_account','rollback-target'),
      'identity',jsonb_build_object('workspace_id',workspace),'content_sha256',repeat('a',64));

    -- Labelled metadata fixtures intentionally have NO corresponding Storage
    -- objects. These exercise snapshot joins, not register_evidence attestation.
    foreach filename in array filenames loop
      evidence_id:=gen_random_uuid();
      insert into public.evidence_versions(id,workspace_id,source_id,source_version,case_id,attempt_id,
        kind,filename,object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at)
      values(evidence_id,workspace,'rollback-'||filename,'1',
        case when filename='original-log.txt' then probe.case_id else null end,
        case when filename='original-log.txt' then probe.attempt_id else null end,
        case when filename='original-log.txt' then 'original_log' else 'reference' end,
        filename,workspace::text||'/rollback/'||filename,repeat('a',64),1,
        case when filename='original-log.txt' then 'text/plain' else 'application/json' end,
        jsonb_build_object('input_filename',filename,'verification_only',true,'no_storage_object',true),actor,now());
      if filename='original-log.txt' then original_id:=evidence_id; end if;
    end loop;
    insert into public.intakes(id,workspace_id,case_id,attempt_id,original_evidence_id,
      delivery_key,payload_sha256,manifest,supplied_by)
      values(intake_id,workspace,case_id,attempt_id,original_id,'rollback-only',repeat('b',64),manifest,actor);
    insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename)
      select workspace,probe.intake_id,e.id,e.filename from public.evidence_versions e where e.workspace_id=workspace;
    insert into public.overview_snapshots(workspace_id,actor_id,filters,fingerprint,metrics)
      values(foreign_workspace,actor,'{}','rollback-only','{}');

    perform set_config('request.jwt.claim.sub',actor::text,true);
    perform set_config('request.jwt.claims',jsonb_build_object('sub',actor,'role','authenticated')::text,true);
    execute 'set local role authenticated';
    if (select count(*) from public.intake_sources where workspace_id=workspace)<>9
      or exists(select 1 from public.overview_snapshots where workspace_id=foreign_workspace) then
      raise exception 'Member positive control or foreign overview RLS failed';
    end if;
    denied:=false;
    begin perform public.cfin_stage_resume('{}'); exception when insufficient_privilege then denied:=true; end;
    if not denied then raise exception 'Browser obtained worker checkpoint RPC'; end if;
    result:=public.cfin_enqueue_run(jsonb_build_object('workspace_id',workspace,'case_id',case_id,
      'acting_role','process_owner','expected_version',1));
    original_run:=(result->>'run_id')::uuid;
    if result->'queued' is distinct from 'true'::jsonb or original_run is null then raise exception 'Exact nine-source snapshot did not queue'; end if;
    result:=public.cfin_queue_evaluations(jsonb_build_object('workspace_id',workspace,
      'case_ids',jsonb_build_array(case_id),'repeats',1,'reason','ROLLBACK ONLY: metadata contract',
      'configuration',jsonb_build_object('models',jsonb_build_object('agent1','gpt-6-luna','agent2','gpt-6.1-sol','agent3','gpt-6.1-sol'),
        'reasoning_effort','medium','price_version','openai-standard-2026-10-01','evaluation_only',true,'run_budget_usd','1')));
    evaluation_run:=(result->'run_ids'->>0)::uuid;
    result:=public.cfin_create_overview_snapshot(jsonb_build_object('workspace_id',workspace,'refresh',true));
    overview_id:=(result->'snapshot'->>'id')::uuid;
    group_id:=(result->'groups'->0->>'id')::uuid;
    result:=public.cfin_overview_group(jsonb_build_object('workspace_id',workspace,'snapshot_id',overview_id,'group_id',group_id,'page',1,'page_size',25));
    if (result->>'total')::integer<>1 or jsonb_array_length(result->'items')<>1 then raise exception 'Saved overview group drill-down failed'; end if;
    execute 'reset role';
    if (select count(*) from public.run_sources where run_id=original_run)<>9
      or (select count(*) from public.run_sources where run_id=evaluation_run)<>9 then raise exception 'Run source snapshot was not copied exactly'; end if;
    select to_jsonb(c) into before_case from public.cases c where id=probe.case_id;
    update public.jobs set available_at=clock_timestamp()+interval '100 years' where run_id=original_run;
    checks:=checks||jsonb_build_array(jsonb_build_object('check','member_rls_exact_pack_snapshot_eval_queue_and_overview_groups','passed',true));

    execute 'set local role service_role';
    result:=public.cfin_claim_job('{"worker_id":"ROLLBACK ONLY"}');
    if result->'run'->>'id' is distinct from evaluation_run::text then raise exception 'Expected isolated evaluation job'; end if;
    job_id:=(result->'job'->>'id')::uuid; lease:=(result->'job'->>'lease_token')::uuid;
    payload:=jsonb_build_object('job_id',job_id,'lease_token',lease,'stage','agent1',
      'output',jsonb_build_object('run_id',evaluation_run,'verification_only',true));
    perform public.cfin_save_stage(payload);
    denied:=false;
    begin perform public.cfin_save_stage(jsonb_set(payload,'{output,verification_only}','false'));
      exception when sqlstate 'PT409' then denied:=true; end;
    if not denied then raise exception 'Validated candidate changed without invalidation'; end if;
    result:=public.cfin_stage_resume(jsonb_build_object('job_id',job_id,'lease_token',lease));
    if result->'outputs'->'agent1' is distinct from payload->'output' then raise exception 'Durable stage output missing on resume'; end if;
    perform public.cfin_fail_stage(jsonb_build_object('job_id',job_id,'lease_token',lease,'stage','agent1'));
    result:=public.cfin_stage_resume(jsonb_build_object('job_id',job_id,'lease_token',lease));
    if result->'outputs' ? 'agent1' then raise exception 'Invalidated checkpoint returned as reusable'; end if;
    perform public.cfin_save_stage(payload);
    result:=public.cfin_preparation_reuse(jsonb_build_object('job_id',job_id,'lease_token',lease,
      'prompt_version','cfin-specialists-v3','model_id','gpt-6-luna','reasoning_effort','medium'));
    if result->'reused' is distinct from 'false'::jsonb then raise exception 'Evaluation reused Agent 1'; end if;
    result:=public.cfin_reserve_call(jsonb_build_object('job_id',job_id,'lease_token',lease,
      'stage','agent_1','invocation',0,'model_id','fake','max_input_tokens',100,'max_output_tokens',10));
    call_id:=(result->'call'->>'id')::uuid;
    if result->'execute' is distinct from 'true'::jsonb then raise exception 'Zero-price software reservation failed'; end if;
    perform public.cfin_reconcile_call(jsonb_build_object('job_id',job_id,'lease_token',lease,
      'call_id',call_id,'state','not_sent'));
    denied:=false;
    begin perform public.cfin_reserve_overview_call(jsonb_build_object('workspace_id',workspace,
      'actor_id',actor,'snapshot_id',overview_id,'model_id','gpt-6.1-sol',
      'monthly_budget_usd',10,'run_budget_usd',1,'max_input_tokens',1,'max_output_tokens',1));
      exception when sqlstate 'PT409' then denied:=true; end;
    if not denied then raise exception 'Overview bypassed the shared live worker slot'; end if;
    result:=public.cfin_complete_run(jsonb_build_object('job_id',job_id,'lease_token',lease,'succeeded',true,
      'output',jsonb_build_object('category','cause_not_established','diagnosis_status','needs_review',
        'affected_object','unknown','description','ROLLBACK ONLY: software result')));
    if result->'promoted' is distinct from 'false'::jsonb then raise exception 'Evaluation promoted a case'; end if;
    execute 'reset role';
    if (select to_jsonb(c) from public.cases c where id=probe.case_id) is distinct from before_case
      or exists(select 1 from public.assignments where workspace_id=workspace)
      or not exists(select 1 from public.analysis_runs where id=evaluation_run and evaluation_only and state='succeeded') then
      raise exception 'Evaluation completion changed live case/ownership';
    end if;
    denied:=false;
    begin update public.analysis_runs set evaluation_only=false where id=evaluation_run;
      exception when sqlstate 'PT409' then denied:=true; end;
    if not denied then raise exception 'Immutable evaluation classification changed'; end if;
    checks:=checks||jsonb_build_array(jsonb_build_object('check','checkpoint_invalidation_resumption_shared_slot_and_eval_nonpromotion','passed',true));

    -- Exercise the current FAILED-run catalogue when no publication exists.
    update public.analysis_runs set state='failed',output=jsonb_build_object('source_catalogue',
      jsonb_build_array(jsonb_build_object('source_id','rollback-original-log.txt','source_version','1',
        'attempt_id','rollback-failure-1','kind','text','line_count',1))) where id=original_run;
    execute 'set local role authenticated';
    perform public.cfin_case_action(jsonb_build_object('workspace_id',workspace,'case_id',case_id,
      'expected_version',1,'acting_role','process_owner','request_key','rollback-review','action','review',
      'data',jsonb_build_object('run_id',original_run,'decision','Accepted','cause_confirmed',true,
        'cause_evidence',jsonb_build_array(jsonb_build_object('source_id','rollback-original-log.txt',
          'source_version','1','attempt_id','rollback-failure-1','line_start',1,'line_end',1)))));
    result:=public.cfin_case_action(jsonb_build_object('workspace_id',workspace,'case_id',case_id,
      'expected_version',2,'acting_role','process_owner','request_key','rollback-assign','action','assign',
      'data',jsonb_build_object('assigned_user_id',actor,'owner_role','master_data_owner','reason','ROLLBACK ONLY: simulated assignment')));
    expected_version:=(result->'case'->>'version')::bigint;
    execute 'set local role service_role';
    result:=public.cfin_claim_notification('{}');
    notification_id:=(result->'notification'->>'id')::uuid;
    notification_lease:=(result->'notification'->>'lease_token')::uuid;
    if result->'claimed' is distinct from 'true'::jsonb then raise exception 'Simulated notification did not claim'; end if;
    perform public.cfin_complete_notification(jsonb_build_object('notification_id',notification_id,'lease_token',notification_lease,'succeeded',false));
    execute 'reset role';
    update public.notifications set available_at=clock_timestamp() where id=notification_id;
    execute 'set local role service_role';
    result:=public.cfin_claim_notification('{}');
    perform public.cfin_complete_notification(jsonb_build_object('notification_id',notification_id,'lease_token',result->'notification'->>'lease_token','succeeded',false));
    execute 'reset role';
    if not exists(select 1 from public.notifications where id=notification_id and state='failed' and retry_count=1 and delivery_attempts=2)
      or not exists(select 1 from public.cases where id=probe.case_id and status='created') then raise exception 'Failed simulated deliveries changed status or retried unboundedly'; end if;
    execute 'set local role authenticated';
    perform public.cfin_case_action(jsonb_build_object('workspace_id',workspace,'case_id',case_id,
      'expected_version',expected_version,'acting_role','process_owner','request_key','rollback-notification-retry',
      'action','retry_notification','data',jsonb_build_object('notification_id',notification_id,'reason','ROLLBACK ONLY: explicit retry')));
    execute 'set local role service_role';
    result:=public.cfin_claim_notification('{}');
    perform public.cfin_complete_notification(jsonb_build_object('notification_id',notification_id,'lease_token',result->'notification'->>'lease_token','succeeded',true));
    execute 'reset role';
    if not exists(select 1 from public.cases where id=probe.case_id and status='owner_notified')
      or not exists(select 1 from public.notifications where id=notification_id and simulated and state='succeeded' and delivery_attempts=3) then
      raise exception 'Explicit simulated retry did not notify the current owner';
    end if;
    insert into public.cases(id,workspace_id,title,due_at,linked_case_id)
      values(alias_id,workspace,'ROLLBACK ONLY: linked alias',now()+interval '1 day',case_id);
    execute 'set local role authenticated';
    denied:=false;
    begin perform public.cfin_case_action(jsonb_build_object('workspace_id',workspace,'case_id',alias_id,
      'expected_version',1,'acting_role','process_owner','request_key','rollback-alias','action','priority',
      'data',jsonb_build_object('priority','P3','reason','ROLLBACK ONLY')));
      exception when sqlstate 'PT409' then denied:=true; end;
    if not denied then raise exception 'Linked alias accepted case work'; end if;
    result:=public.cfin_case_page(jsonb_build_object('workspace_id',workspace));
    if (result->>'total')::integer<>1 then raise exception 'Case page double-counted a linked alias'; end if;
    checks:=checks||jsonb_build_array(jsonb_build_object('check','failed_run_citations_manual_owner_notification_retry_and_alias_fencing','passed',true));
    raise sqlstate 'ZX001' using message='Successful verification: rollback all fixtures';
  exception
    when sqlstate 'ZX001' then passed:=true;
    when others then
      get stacked diagnostics error_code=returned_sqlstate,error_message=message_text;
      checks:=checks||jsonb_build_array(jsonb_build_object('check','verification_aborted','passed',false,'sqlstate',error_code,'message',error_message));
  end;
  execute 'reset role';
  if exists(select 1 from public.workspaces where id in (workspace,foreign_workspace)) then raise exception 'Fixture rollback failed'; end if;
  if old_slot is not null and ((select to_jsonb(s) from private.worker_slot s where singleton=1) is distinct from old_slot
    or (select coalesce(jsonb_agg(to_jsonb(j) order by id),'[]') from public.jobs j where id=any(old_job_ids)) is distinct from old_jobs
    or (select coalesce(jsonb_agg(to_jsonb(n) order by id),'[]') from public.notifications n where id=any(old_notification_ids)) is distinct from old_notifications) then
    raise exception 'Existing worker state/queues were not restored exactly';
  end if;
  checks:=checks||jsonb_build_array(jsonb_build_object('check','fixtures_and_existing_queues_rolled_back','passed',true));
  insert into cfin_completion_verification_report values(jsonb_build_object('all_passed',passed,'checks',checks,
    'limitations',jsonb_build_array('SQL metadata fixtures only; no Storage bytes uploaded',
      'No provider calls, paid evaluations, real approvals or external notifications',
      'Does not replace actual JWT HTTP or model-quality verification')));
end;
$verification$;
select report from cfin_completion_verification_report;
rollback;
