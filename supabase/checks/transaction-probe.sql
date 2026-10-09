-- Run the whole file as postgres in the isolated synthetic project's SQL editor.
-- This exercises PostgreSQL, not LLM quality or Storage's HTTP byte persistence.
-- No Auth users, human reviews, model calls, or permanent fixtures are created.
-- The inner exception block rolls back ALL fixtures, including on success.
-- The final ROLLBACK additionally removes the temporary report and local settings.
-- Run BEFORE starting the worker: a busy singleton or running job fails closed.
-- Existing queued jobs are hidden from claim_job inside the rollback subtransaction.
-- Only actor_id below must identify an existing, confirmed demo Auth account.

begin;
set local statement_timeout = '20s';
set local lock_timeout = '2s';
create temporary table cfin_transaction_probe_report(report jsonb) on commit drop;

do $probe$
<<probe_data>>
declare
  actor_id uuid := '52df0735-bf8d-41d6-a24b-1965e4714196';
  member_workspace uuid := gen_random_uuid();
  foreign_workspace uuid := gen_random_uuid();
  member_case uuid := gen_random_uuid();
  foreign_case uuid := gen_random_uuid();
  attempt_id uuid := gen_random_uuid();
  evidence_id uuid := gen_random_uuid();
  intake_id uuid := gen_random_uuid();
  run_id uuid := gen_random_uuid();
  next_run_id uuid := gen_random_uuid();
  job_id uuid := gen_random_uuid();
  original_token uuid;
  replacement_token uuid;
  wrong_token uuid := gen_random_uuid();
  call_id uuid;
  tables text[] := array[
    'workspaces','workspace_memberships','cases','attempts','evidence_versions',
    'intakes','analysis_runs','jobs','guidance_versions','assignments','case_reviews',
    'milestones','milestone_proof','resolution_records','notifications','activity',
    'reference_reviews','run_sources','run_results','proof_applicability','stage_calls'
  ];
  service_functions text[] := array[
    'commit_intake','register_evidence','claim_job','heartbeat_job',
    'reserve_call','reconcile_call','complete_run'
  ];
  user_functions text[] := array['review_reference','enqueue_run','case_action'];
  table_name text;
  function_name text;
  privilege_name text;
  role_name text;
  denied boolean;
  row_count bigint;
  relation_oid oid;
  public_oid oid;
  private_oid oid;
  starting_spend numeric;
  manifest jsonb;
  payload jsonb;
  result jsonb;
  replay jsonb;
  reservation numeric;
  checks jsonb := '[]'::jsonb;
  all_passed boolean := false;
  error_code text;
  error_message text;
  queued_job_ids uuid[];
  queued_jobs_before jsonb;
  queued_jobs_after jsonb;
  worker_slot_before jsonb;
begin
  -- A PL/pgSQL exception block is a subtransaction. Deliberately raising ZX001
  -- after success removes its data changes while retaining the local checks array.
  begin
    if current_user <> 'postgres' then
      raise exception 'Use the SQL editor postgres role';
    end if;
    if not exists(select 1 from auth.users where id=actor_id and email_confirmed_at is not null) then
      raise exception 'The configured existing confirmed Auth account is required';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','existing_confirmed_actor','passed',true));

    foreach table_name in array tables loop
      relation_oid := to_regclass('public.' || table_name);
      if relation_oid is null or not (select relrowsecurity from pg_class where oid=relation_oid) then
        raise exception 'RLS missing on public.%',table_name;
      end if;
      if not has_table_privilege('authenticated',relation_oid,'SELECT')
        or has_table_privilege('anon',relation_oid,'SELECT') then
        raise exception 'Unexpected SELECT privileges on public.%',table_name;
      end if;
      foreach role_name in array array['anon','authenticated'] loop
        foreach privilege_name in array array['INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'] loop
          if has_table_privilege(role_name,relation_oid,privilege_name) then
            raise exception 'Unexpected % % privilege on public.%',role_name,privilege_name,table_name;
          end if;
        end loop;
      end loop;
      if exists(select 1 from pg_policy where polrelid=relation_oid and polcmd<>'r') then
        raise exception 'Unexpected non-SELECT policy on public.%',table_name;
      end if;
    end loop;
    checks := checks || jsonb_build_array(jsonb_build_object('check','all_21_public_tables_rls_and_read_only_user_grants','passed',true));

    foreach function_name in array service_functions || user_functions loop
      public_oid := to_regprocedure('public.cfin_' || function_name || '(jsonb)');
      private_oid := to_regprocedure('private.' || function_name || '(jsonb)');
      if public_oid is null or private_oid is null then
        raise exception 'Required RPC missing: %',function_name;
      end if;
      if (select prosecdef from pg_proc where oid=public_oid)
        or not (select prosecdef from pg_proc where oid=private_oid) then
        raise exception 'Unexpected invoker/definer boundary: %',function_name;
      end if;
      if not (select coalesce(proconfig @> array['search_path=""'],false) from pg_proc where oid=public_oid)
        or not (select coalesce(proconfig @> array['search_path=""'],false) from pg_proc where oid=private_oid) then
        raise exception 'Empty search_path missing: %',function_name;
      end if;
      if has_function_privilege('anon',public_oid,'EXECUTE')
        or has_function_privilege('anon',private_oid,'EXECUTE')
        or has_function_privilege('authenticated',public_oid,'EXECUTE') is distinct from (function_name=any(user_functions))
        or has_function_privilege('authenticated',private_oid,'EXECUTE') is distinct from (function_name=any(user_functions))
        or has_function_privilege('service_role',public_oid,'EXECUTE') is distinct from (function_name=any(service_functions))
        or has_function_privilege('service_role',private_oid,'EXECUTE') is distinct from (function_name=any(service_functions)) then
        raise exception 'Unexpected RPC execution grants: %',function_name;
      end if;
    end loop;
    if exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='private' and c.relkind in ('r','p')
        and (has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE')
          or has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE'))) then
      raise exception 'Private tables accessible to browser roles';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','service_only_and_user_rpc_grants_and_definer_boundaries','passed',true));

    if not exists(select 1 from storage.buckets where id='evidence' and not public
      and file_size_limit=10485760 and allowed_mime_types @> array['text/plain','application/json']) then
      raise exception 'Private evidence bucket configuration missing';
    end if;
    if not (select relrowsecurity from pg_class where oid='storage.objects'::regclass)
      or not exists(select 1 from pg_policy where polrelid='storage.objects'::regclass
        and polname='preserved_member_evidence' and polcmd='r'
        and polroles=array['authenticated'::regrole::oid]
        and pg_get_expr(polqual,polrelid) like '%evidence_versions%'
        and pg_get_expr(polqual,polrelid) like '%is_member%') then
      raise exception 'Preserved-evidence member Storage SELECT policy missing';
    end if;
    if exists(select 1 from pg_policy where polrelid='storage.objects'::regclass
      and polcmd in ('*','a','w','d')
      and polroles && array[0::oid,'anon'::regrole::oid,'authenticated'::regrole::oid]) then
      raise exception 'Unexpected browser Storage write policy; inspect bucket scope';
    end if;
    if exists(select 1 from pg_policy where polrelid='storage.objects'::regclass
      and polcmd in ('*','r') and polroles && array[0::oid,'anon'::regrole::oid]) then
      raise exception 'Unexpected anonymous Storage read policy; inspect bucket scope';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','private_evidence_bucket_and_storage_policy_catalog','passed',true));

    -- Abort rather than competing with a real worker. Hold a table lock while
    -- existing queued jobs are moved beyond claim eligibility, then restore them
    -- through the enclosing exception rollback, not a compensating UPDATE.
    perform 1 from private.worker_slot where singleton=1 for update nowait;
    lock table public.jobs in share row exclusive mode nowait;
    if (select count(*) from private.worker_slot where singleton=1)<>1 then
      raise exception 'The worker singleton row is missing';
    end if;
    if exists(select 1 from private.worker_slot s where s.job_id is not null or s.lease_token is not null or s.lease_until is not null)
      or exists(select 1 from public.jobs where state='running') then
      raise exception 'Worker or running work exists; stop the worker before this probe';
    end if;
    select to_jsonb(s) into worker_slot_before from private.worker_slot s where s.singleton=1;
    select coalesce(array_agg(j.id order by j.id),'{}'::uuid[]),
      coalesce(jsonb_agg(to_jsonb(j) order by j.id),'[]'::jsonb)
      into queued_job_ids,queued_jobs_before from public.jobs j where j.state='queued';
    update public.jobs set available_at=clock_timestamp()+interval '100 years' where state='queued';
    select coalesce(sum(coalesce(actual_usd,reserved_usd)),0) into starting_spend
      from public.stage_calls where month_start=(date_trunc('month',clock_timestamp() at time zone 'UTC'))::date and state<>'not_sent';
    if starting_spend>9 then raise exception 'Insufficient remaining synthetic budget probe headroom'; end if;

    insert into public.workspaces(id,name) values
      (member_workspace,'ROLLBACK ONLY: member transaction probe'),
      (foreign_workspace,'ROLLBACK ONLY: foreign transaction probe');
    insert into public.workspace_memberships(workspace_id,user_id,roles)
      values(member_workspace,actor_id,array['process_owner']);
    insert into public.cases(id,workspace_id,title,due_at) values
      (member_case,member_workspace,'ROLLBACK ONLY: member case',now()+interval '1 day'),
      (foreign_case,foreign_workspace,'ROLLBACK ONLY: foreign case',now()+interval '1 day');

    perform set_config('request.jwt.claim.sub',actor_id::text,true);
    perform set_config('request.jwt.claims',jsonb_build_object('sub',actor_id,'role','authenticated')::text,true);
    execute 'set local role authenticated';
    if auth.uid() is distinct from actor_id or current_user<>'authenticated' then
      raise exception 'The real actor claim and authenticated role were not selected';
    end if;
    select count(*) into row_count from public.workspaces where id=member_workspace;
    if row_count<>1 then raise exception 'Member workspace positive control is invisible'; end if;
    select count(*) into row_count from public.cases where id=member_case;
    if row_count<>1 then raise exception 'Member case positive control is invisible'; end if;
    select count(*) into row_count from public.workspaces where id=foreign_workspace;
    if row_count<>0 then raise exception 'Foreign workspace leaked through RLS'; end if;
    select count(*) into row_count from public.cases where id=foreign_case;
    if row_count<>0 then raise exception 'Foreign case leaked through RLS'; end if;
    select count(*) into row_count from public.workspace_memberships where workspace_id=foreign_workspace;
    if row_count<>0 then raise exception 'Foreign membership leaked through RLS'; end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','member_positive_controls_and_foreign_workspace_rls','passed',true));

    -- WHERE false guarantees no rows can change even if a write grant regresses.
    foreach table_name in array tables loop
      foreach privilege_name in array array['INSERT','UPDATE','DELETE'] loop
        denied := false;
        begin
          if privilege_name='INSERT' then
            execute format('insert into public.%I select * from public.%I where false',table_name,table_name);
          elsif privilege_name='UPDATE' then
            execute format('update public.%I set %I=%I where false',table_name,
              case when table_name='workspaces' then 'id' else 'workspace_id' end,
              case when table_name='workspaces' then 'id' else 'workspace_id' end);
          else
            execute format('delete from public.%I where false',table_name);
          end if;
        exception when insufficient_privilege then
          if sqlerrm<>'permission denied for table '||table_name then raise; end if;
          denied := true;
        end;
        if not denied then raise exception 'Direct % denial missing on public.%',privilege_name,table_name; end if;
      end loop;
    end loop;
    checks := checks || jsonb_build_array(jsonb_build_object('check','authenticated_all_63_direct_insert_update_delete_denials','passed',true));

    foreach function_name in array service_functions loop
      denied := false;
      begin
        execute format('select public.cfin_%I($1)',function_name) using '{}'::jsonb;
      exception when insufficient_privilege then
        if sqlerrm<>'permission denied for function cfin_'||function_name then raise; end if;
        denied := true;
      end;
      if not denied then raise exception 'Authenticated service RPC denial missing: %',function_name; end if;
    end loop;
    checks := checks || jsonb_build_array(jsonb_build_object('check','authenticated_all_7_service_rpc_outer_function_denials','passed',true));

    denied := false;
    begin
      perform public.cfin_enqueue_run(jsonb_build_object('workspace_id',foreign_workspace,'case_id',foreign_case,'acting_role','process_owner','expected_version',1));
    exception when insufficient_privilege then
      if sqlerrm<>'Workspace role required' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Foreign-workspace RPC role guard missing'; end if;
    denied := false;
    begin
      perform public.cfin_enqueue_run(jsonb_build_object('workspace_id',member_workspace,'case_id',member_case,'acting_role','mapping_owner','expected_version',1));
    exception when insufficient_privilege then
      if sqlerrm<>'Workspace role required' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Unheld acting-role guard missing'; end if;
    denied := false;
    begin
      perform public.cfin_case_action(jsonb_build_object('workspace_id',member_workspace,'case_id',member_case,'acting_role','process_owner','expected_version',0,'request_key','rollback-stale-action','action','unsupported_probe'));
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Case changed; refresh' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Stale case version guard missing'; end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','nonmember_and_unheld_role_rpc_guards_and_stale_version','passed',true));

    execute 'set local role anon';
    denied := false;
    begin
      perform 1 from public.cases where id=member_case;
    exception when insufficient_privilege then
      if sqlerrm<>'permission denied for table cases' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Anonymous case read denial missing'; end if;
    foreach function_name in array service_functions || user_functions loop
      denied := false;
      begin
        execute format('select public.cfin_%I($1)',function_name) using '{}'::jsonb;
      exception when insufficient_privilege then
        if sqlerrm<>'permission denied for function cfin_'||function_name then raise; end if;
        denied := true;
      end;
      if not denied then raise exception 'Anonymous RPC denial missing: %',function_name; end if;
    end loop;
    checks := checks || jsonb_build_array(jsonb_build_object('check','anonymous_case_read_and_all_10_rpc_denials','passed',true));
    execute 'reset role';

    -- Database-row fixture ONLY. No Storage object or fake byte attestation exists.
    -- The duplicate intake fast path returns before Storage registration. The live
    -- upload/intake still needs the separate backend HTTP walkthrough.
    insert into public.attempts(id,workspace_id,case_id,attempt_key,processing_at,processing_order,result)
      values(attempt_id,member_workspace,member_case,'rollback-attempt-1',now()-interval '1 day',1,'failed');
    update public.cases set current_attempt_id=attempt_id,attempt_order_known=true where id=member_case;
    insert into public.evidence_versions(id,workspace_id,source_id,source_version,case_id,attempt_id,kind,filename,object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at)
      values(evidence_id,member_workspace,'rollback-log','1',member_case,attempt_id,'original_log','rollback-only.txt',member_workspace::text||'/rollback-only.txt',repeat('a',64),1,'text/plain',jsonb_build_object('transaction_probe',true,'no_object_uploaded',true),actor_id,now());
    manifest := jsonb_build_object('identity',jsonb_build_object('workspace_id',member_workspace),'content_sha256',repeat('a',64),'processing_order',1);
    payload := jsonb_build_object('workspace_id',member_workspace,'actor_id',actor_id,'acting_role','process_owner','delivery_key','rollback-delivery','manifest',manifest,'storage',jsonb_build_object('sha256',repeat('a',64)));
    insert into public.intakes(id,workspace_id,case_id,attempt_id,original_evidence_id,delivery_key,payload_sha256,manifest,supplied_by)
      values(intake_id,member_workspace,member_case,attempt_id,evidence_id,'rollback-delivery',encode(pg_catalog.sha256(convert_to(jsonb_build_object('manifest',manifest,'sha256',repeat('a',64))::text,'UTF8')),'hex'),manifest,actor_id);
    execute 'set local role service_role';
    result := public.cfin_commit_intake(payload);
    replay := public.cfin_commit_intake(payload);
    if result->>'intake_id' is distinct from intake_id::text or result->'duplicate' is distinct from 'true'::jsonb or replay is distinct from result then
      raise exception 'Duplicate intake did not return the original immutable receipt';
    end if;
    denied := false;
    begin
      perform public.cfin_commit_intake(jsonb_set(payload,'{manifest,processing_order}','2'::jsonb));
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Delivery key content conflict' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Conflicting duplicate delivery guard missing'; end if;
    execute 'reset role';
    select count(*) into row_count from public.intakes where workspace_id=member_workspace;
    if row_count<>1 then raise exception 'Duplicate intake added a row'; end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','duplicate_intake_receipt_and_content_conflict_database_fixture','passed',true));

    denied := false;
    begin
      update public.evidence_versions set filename='changed' where id=evidence_id;
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Saved evidence and snapshot sources are immutable' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Evidence immutability trigger missing'; end if;
    insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by)
      values(run_id,member_workspace,member_case,attempt_id,repeat('b',64),jsonb_build_object('transaction_probe',true),1,1,actor_id);
    insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot)
      values(member_workspace,run_id,evidence_id,jsonb_build_object('transaction_probe',true));
    denied := false;
    begin
      update public.run_sources s set source_snapshot='{}'::jsonb where s.run_id=probe_data.run_id and s.workspace_id=member_workspace;
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Saved evidence and snapshot sources are immutable' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Snapshot source immutability trigger missing'; end if;
    denied := false;
    begin
      update public.analysis_runs set snapshot='{}'::jsonb where id=run_id;
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Run input snapshot is immutable' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Run input immutability trigger missing'; end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','evidence_run_source_and_run_input_immutability','passed',true));
    update public.cases set requested_run_id=run_id where id=member_case;
    insert into public.jobs(id,workspace_id,run_id) values(job_id,member_workspace,run_id);

    execute 'set local role service_role';
    result := public.cfin_claim_job(jsonb_build_object('worker_id','rollback-only-worker'));
    if result->'claimed' is distinct from 'true'::jsonb or result->'job'->>'id' is distinct from job_id::text then
      raise exception 'The singleton did not claim the only probe job';
    end if;
    original_token := (result->'job'->>'lease_token')::uuid;
    result := public.cfin_claim_job(jsonb_build_object('worker_id','rollback-only-competitor'));
    if result->'claimed' is distinct from 'false'::jsonb then raise exception 'Second worker acquired a live singleton'; end if;
    denied := false;
    begin
      perform public.cfin_heartbeat_job(jsonb_build_object('job_id',job_id,'lease_token',wrong_token));
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Worker lease expired or replaced' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Wrong lease heartbeat guard missing'; end if;
    result := public.cfin_heartbeat_job(jsonb_build_object('job_id',job_id,'lease_token',original_token));
    if result->>'lease_until' is null then raise exception 'Current lease heartbeat did not return expiry'; end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','single_worker_claim_and_heartbeat_token_fencing','passed',true));

    payload := jsonb_build_object('job_id',job_id,'lease_token',original_token,'stage','agent_1','invocation',0,'model_id','gpt-6-luna','max_input_tokens',1000,'max_output_tokens',100,'monthly_budget_usd',10,'run_budget_usd',0.0001);
    denied := false;
    begin
      perform public.cfin_reserve_call(payload);
    exception when sqlstate 'PT422' then
      if sqlerrm<>'Model budget exhausted' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Configured smaller run budget was not enforced'; end if;
    payload := jsonb_set(payload,'{run_budget_usd}','1'::jsonb);
    result := public.cfin_reserve_call(payload);
    call_id := (result->'call'->>'id')::uuid;
    reservation := (result->'call'->>'reserved_usd')::numeric;
    if result->'execute' is distinct from 'true'::jsonb or reservation<>0.000175 then
      raise exception 'Known Luna reservation was not calculated from locked pricing';
    end if;
    replay := public.cfin_reserve_call(payload);
    if replay->'execute' is distinct from 'false'::jsonb or replay->'duplicate' is distinct from 'true'::jsonb or replay->'call'->>'id' is distinct from call_id::text then
      raise exception 'Duplicate reservation allowed another dispatch';
    end if;
    result := public.cfin_reconcile_call(jsonb_build_object('job_id',job_id,'lease_token',original_token,'call_id',call_id,'state','usage_unknown'));
    if result->>'state'<>'usage_unknown' or result->'actual_usd' is distinct from 'null'::jsonb
      or (result->>'reserved_usd')::numeric<>reservation then
      raise exception 'Unknown usage did not retain the full reservation';
    end if;
    denied := false;
    begin
      perform public.cfin_reserve_call(jsonb_set(jsonb_set(payload,'{stage}','"agent_2"'::jsonb),'{monthly_budget_usd}',to_jsonb(starting_spend+reservation+reservation/2)));
    exception when sqlstate 'PT422' then
      if sqlerrm<>'Model budget exhausted' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Unknown usage was not counted against monthly budget'; end if;
    result := public.cfin_reconcile_call(jsonb_build_object('job_id',job_id,'lease_token',original_token,'call_id',call_id,'state','not_sent'));
    if result->>'state'<>'not_sent' or (result->>'actual_usd')::numeric<>0 then
      raise exception 'A confirmed undispatched call did not release its reservation';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','smaller_run_budget_duplicate_dispatch_unknown_usage_month_cap_and_not_sent_release','passed',true));

    execute 'reset role';
    update public.jobs set lease_until=clock_timestamp()-interval '1 second' where id=job_id;
    update private.worker_slot set lease_until=clock_timestamp()-interval '1 second' where singleton=1;
    execute 'set local role service_role';
    denied := false;
    begin
      perform public.cfin_heartbeat_job(jsonb_build_object('job_id',job_id,'lease_token',original_token));
    exception when sqlstate 'PT409' then
      if sqlerrm<>'Worker lease expired or replaced' then raise; end if;
      denied := true;
    end;
    if not denied then raise exception 'Expired lease heartbeat guard missing'; end if;
    result := public.cfin_claim_job(jsonb_build_object('worker_id','rollback-only-replacement'));
    replacement_token := (result->'job'->>'lease_token')::uuid;
    if result->'claimed' is distinct from 'true'::jsonb or result->'job'->>'id' is distinct from job_id::text
      or replacement_token is null or replacement_token=original_token then
      raise exception 'Expired worker was not replaced with a fresh lease';
    end if;
    payload := jsonb_build_object('job_id',job_id,'lease_token',original_token,'succeeded',false,'error_code','rollback_probe_stale_worker');
    result := public.cfin_complete_run(payload);
    replay := public.cfin_complete_run(payload);
    if result->'promoted' is distinct from 'false'::jsonb or result->'lease_rejected' is distinct from 'true'::jsonb
      or replay->'duplicate' is distinct from 'true'::jsonb then
      raise exception 'Replaced worker completion was not fenced and retained idempotently';
    end if;
    execute 'reset role';
    if not exists(select 1 from public.jobs where id=job_id and state='running' and lease_token=replacement_token)
      or exists(select 1 from public.cases where id=member_case and published_run_id is not null) then
      raise exception 'Replaced worker completion mutated current work';
    end if;
    update public.cases set input_revision=input_revision+1,analysis_status='needs_refresh' where id=member_case;
    execute 'set local role service_role';
    result := public.cfin_complete_run(jsonb_build_object('job_id',job_id,'lease_token',replacement_token,'succeeded',false,'error_code','rollback_probe_old_revision'));
    if result->'promoted' is distinct from 'false'::jsonb then raise exception 'Old input revision was promoted'; end if;
    execute 'reset role';
    if not exists(select 1 from public.analysis_runs where id=run_id and state='historical')
      or not exists(select 1 from public.cases where id=member_case and analysis_status='needs_refresh' and published_run_id is null)
      or exists(select 1 from private.worker_slot s where s.job_id is not null) then
      raise exception 'Old revision completion did not stay historical or release the slot';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','expired_replaced_worker_late_receipt_idempotency_and_input_revision_fencing','passed',true));

    insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by)
      values(next_run_id,member_workspace,member_case,attempt_id,repeat('c',64),jsonb_build_object('transaction_probe',true),1,2,actor_id);
    update public.cases set requested_run_id=next_run_id where id=member_case;
    insert into public.jobs(workspace_id,run_id) values(member_workspace,next_run_id);
    execute 'set local role service_role';
    result := public.cfin_claim_job(jsonb_build_object('worker_id','rollback-only-current-result'));
    payload := jsonb_build_object('job_id',result->'job'->>'id','lease_token',result->'job'->>'lease_token','succeeded',true,'output',jsonb_build_object('category','cause_not_established','affected_object','unknown','diagnosis_status','needs_review','description','ROLLBACK ONLY: software publication probe; no model was called'));
    result := public.cfin_complete_run(payload);
    replay := public.cfin_complete_run(payload);
    if result->'promoted' is distinct from 'true'::jsonb or replay->'duplicate' is distinct from 'true'::jsonb then
      raise exception 'Current completion was not published exactly once';
    end if;
    execute 'reset role';
    if not exists(select 1 from public.cases where id=member_case and published_run_id=next_run_id and analysis_status='available' and version=2)
      or not exists(select 1 from public.analysis_runs where id=next_run_id and state='succeeded') then
      raise exception 'Current result state and case version were not published atomically';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','current_result_atomic_publication_and_duplicate_completion','passed',true));

    -- Successful probe data is intentionally rolled back, never committed.
    raise sqlstate 'ZX001' using message='Successful transaction probe: roll back all fixtures';
  exception
    when sqlstate 'ZX001' then all_passed := true;
    when others then
      get stacked diagnostics error_code=returned_sqlstate,error_message=message_text;
      checks := checks || jsonb_build_array(jsonb_build_object('check','probe_aborted','passed',false,'sqlstate',error_code,'message',error_message));
  end;

  execute 'reset role';
  if exists(select 1 from public.workspaces where id in (member_workspace,foreign_workspace)) then
    raise exception 'Unexpected rollback failure: fixture workspace still exists';
  end if;
  checks := checks || jsonb_build_array(jsonb_build_object('check','all_transaction_fixtures_rolled_back','passed',true));
  if queued_jobs_before is not null then
    select coalesce(jsonb_agg(to_jsonb(j) order by j.id),'[]'::jsonb) into queued_jobs_after
      from public.jobs j where j.id=any(queued_job_ids);
    if queued_jobs_after is distinct from queued_jobs_before
      or (select to_jsonb(s) from private.worker_slot s where s.singleton=1) is distinct from worker_slot_before then
      raise exception 'Unexpected rollback failure: existing queued jobs or singleton changed';
    end if;
    checks := checks || jsonb_build_array(jsonb_build_object('check','existing_queued_jobs_and_singleton_restored_exactly','passed',true,'queued_job_count',cardinality(queued_job_ids)));
  end if;
  insert into cfin_transaction_probe_report values(jsonb_build_object(
    'all_passed',all_passed,'checks',checks,'check_groups',jsonb_array_length(checks),
    'limitations',array['SQL role/claims probes supplement real HTTP JWT checks','Storage catalog checks do not prove actual saved bytes','Duplicate intake uses a labelled rollback-only database fixture','No model quality or human approvals were exercised']
  ));
end;
$probe$;

select report from cfin_transaction_probe_report;
rollback;
