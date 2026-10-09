-- Governed Error Analysis rebuild. This migration is additive: legacy and
-- factual-only rows retain their original contracts and workflow semantics.
begin;

alter table public.workspace_memberships drop constraint if exists workspace_memberships_roles_check;
alter table public.workspace_memberships add constraint workspace_memberships_roles_check check (
  cardinality(roles)>0 and roles <@ array[
    'process_owner','master_data_owner','mapping_owner','finance_owner','validator',
    'mdg_process_owner','data_operations','cfin_exception_manager'
  ]::text[] and array_position(roles,null) is null
);
alter table public.cases drop constraint if exists cases_workflow_version_check;
alter table public.cases add constraint cases_workflow_version_check check(
  workflow_version in ('legacy-v1','log-only-v1','error-analysis-v1')
);
alter table public.cases drop constraint if exists cases_category_check;
alter table public.cases add constraint cases_category_check check(category in (
  'missing_target_gl_master_data','missing_gl_mapping','closed_target_posting_period',
  'multiple_blockers','cause_not_established','unknown','master_data','mapping',
  'integration_mapping','master_data_restriction','posting_period','tax','currency',
  'document_splitting','account_assignment','technical_interface','unclassified'
));
alter table public.cases add column if not exists error_analysis_result jsonb;
alter table public.cases add column if not exists route_policy_id uuid;
alter table public.cases add column if not exists route_policy_version integer;
alter table public.cases add column if not exists route_state text not null default 'not_started'
  check(route_state in ('not_started','in_progress','blocked','escalated','completed'));

create table public.error_taxonomy (
  category_id text primary key check(category_id in (
    'master_data','mapping','integration_mapping','master_data_restriction',
    'posting_period','tax','currency','document_splitting','account_assignment',
    'technical_interface'
  )),
  label text not null check(length(btrim(label))>0),
  definition text not null check(length(btrim(definition))>0),
  pilot_active boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.error_route_policies (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.workspaces(id),
  category_id text not null,
  version integer not null check(version>0),
  route_kind text not null check(route_kind in ('pilot','manual','unclassified')),
  owner_role text not null check(owner_role in ('mdg_process_owner','cfin_exception_manager')),
  escalation_role text not null default 'cfin_exception_manager'
    check(escalation_role='cfin_exception_manager'),
  steps jsonb not null check(jsonb_typeof(steps)='array' and jsonb_array_length(steps)>0),
  active boolean not null default true,
  configured_by uuid references auth.users(id),
  effective_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique nulls not distinct(workspace_id,category_id,version)
);
alter table public.error_route_policies enable row level security;
create policy error_route_policy_member_read on public.error_route_policies for select to authenticated using(
  workspace_id is null or private.is_member(workspace_id)
);
revoke all on public.error_taxonomy,public.error_route_policies from public,anon,authenticated;
grant select on public.error_taxonomy,error_route_policies to authenticated,service_role;

create table public.error_route_milestones (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id),
  case_id uuid not null,
  policy_id uuid not null references public.error_route_policies(id),
  policy_version integer not null,
  step_order integer not null check(step_order>0),
  step_id text not null check(length(btrim(step_id))>0),
  decision text check(decision in ('requested','approved','rejected','completed','failed')),
  evidence_ids jsonb not null default '[]' check(jsonb_typeof(evidence_ids)='array'),
  note text not null check(length(btrim(note))>0),
  actor_id uuid not null references auth.users(id),
  acting_role text not null,
  recorded_at timestamptz not null default now(),
  foreign key(workspace_id,case_id) references public.cases(workspace_id,id),
  unique(workspace_id,case_id,policy_id,policy_version,step_order)
);
alter table public.error_route_milestones enable row level security;
create policy error_route_milestone_member_read on public.error_route_milestones for select to authenticated using(private.is_member(workspace_id));
revoke all on public.error_route_milestones from public,anon,authenticated,service_role;
grant select on public.error_route_milestones to authenticated,service_role;

insert into public.error_taxonomy(category_id,label,definition,pilot_active) values
 ('master_data','Master-data failure','A required master-data record, value or maintained target context may be unavailable.',true),
 ('mapping','Mapping failure','A required source-to-target mapping may be missing or incorrect.',true),
 ('integration_mapping','Integration or organisational mapping discrepancy','Interface or organisational mapping context does not align.',false),
 ('master_data_restriction','Master-data validity, restriction or block','A master-data validity, restriction or block may prevent processing.',false),
 ('posting_period','Posting-period failure','The reported posting period cannot be used for the attempted posting.',false),
 ('tax','Tax failure','Tax determination or tax data causes the reported exception.',false),
 ('currency','Currency or exchange-rate failure','Currency or exchange-rate information causes the reported exception.',false),
 ('document_splitting','Document-splitting failure','Document splitting causes the reported exception.',false),
 ('account_assignment','Account-assignment failure','Account assignment causes the reported exception.',false),
 ('technical_interface','Technical or interface failure','A technical or interface condition causes the reported exception.',false)
on conflict(category_id) do update set label=excluded.label,definition=excluded.definition,pilot_active=excluded.pilot_active;

insert into public.error_route_policies(category_id,version,route_kind,owner_role,steps) values
 ('master_data',1,'pilot','mdg_process_owner',jsonb_build_array(
   jsonb_build_object('order',1,'step_id','request_approval','kind','request_process_owner_approval','description','MDG Process Owner tags the relevant Process Owner in the case-log conversation to request approval.','required_role','mdg_process_owner','requires_evidence',false,'requires_approval',false),
   jsonb_build_object('order',2,'step_id','process_owner_approval','kind','record_process_owner_decision','description','Relevant Process Owner approves or rejects in the same case-log conversation.','required_role','process_owner','requires_evidence',false,'requires_approval',true),
   jsonb_build_object('order',3,'step_id','create_data','kind','create_master_data','description','After recorded approval, MDG Process Owner creates the required data.','required_role','mdg_process_owner','requires_evidence',false,'requires_approval',true),
   jsonb_build_object('order',4,'step_id','implementation_evidence','kind','upload_implementation_evidence','description','MDG Process Owner uploads implementation evidence to case history.','required_role','mdg_process_owner','requires_evidence',true,'requires_approval',false),
   jsonb_build_object('order',5,'step_id','reprocessing_go_ahead','kind','record_reprocessing_go_ahead','description','MDG Process Owner records the reprocessing go-ahead.','required_role','mdg_process_owner','requires_evidence',true,'requires_approval',false),
   jsonb_build_object('order',6,'step_id','reprocess','kind','reprocess_document','description','Data Operations reprocesses the document.','required_role','data_operations','requires_evidence',false,'requires_approval',false),
   jsonb_build_object('order',7,'step_id','posting_outcome','kind','record_posting_outcome','description','Data Operations records the CFIN posting reference or failure evidence.','required_role','data_operations','requires_evidence',true,'requires_approval',false)
 )),
 ('mapping',1,'pilot','mdg_process_owner',jsonb_build_array(
   jsonb_build_object('order',1,'step_id','confirm_mapping','kind','confirm_mapping_with_process_owner','description','MDG Process Owner confirms the correct mapping with the relevant Process Owner in the case-log conversation.','required_role','mdg_process_owner','requires_evidence',false,'requires_approval',false),
   jsonb_build_object('order',2,'step_id','maintain_mapping','kind','maintain_mapping','description','MDG Process Owner maintains the mapping and records changed scope and evidence.','required_role','mdg_process_owner','requires_evidence',true,'requires_approval',false),
   jsonb_build_object('order',3,'step_id','mapping_approval','kind','review_and_approve_mapping','description','Relevant Process Owner reviews and approves the mapping change in the case-log conversation.','required_role','process_owner','requires_evidence',false,'requires_approval',true),
   jsonb_build_object('order',4,'step_id','reprocess','kind','reprocess_document','description','Data Operations reprocesses the document.','required_role','data_operations','requires_evidence',false,'requires_approval',false),
   jsonb_build_object('order',5,'step_id','posting_outcome','kind','record_posting_outcome','description','Data Operations records the CFIN posting reference or failure evidence.','required_role','data_operations','requires_evidence',true,'requires_approval',false)
  )),
 ('integration_mapping',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('master_data_restriction',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('posting_period',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('tax',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('currency',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('document_splitting',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('account_assignment',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('technical_interface',1,'manual','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false))),
 ('unclassified',1,'unclassified','cfin_exception_manager',jsonb_build_array(jsonb_build_object('order',1,'step_id','manual_investigation','kind','manual_investigation','description','CFIN Exception Manager assigns a human investigation owner.','required_role','cfin_exception_manager','requires_evidence',false,'requires_approval',false)))
on conflict(workspace_id,category_id,version) do nothing;

create function private.get_error_route(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; category text:=p->>'category_id'; policy public.error_route_policies;
begin
 if not exists(select 1 from public.workspaces where id=w) then raise sqlstate 'PT404' using message='Workspace not found'; end if;
 if category not in ('master_data','mapping','integration_mapping','master_data_restriction','posting_period','tax','currency','document_splitting','account_assignment','technical_interface','unclassified') then raise sqlstate 'PT422' using message='Maintained category required'; end if;
 select * into policy from public.error_route_policies where category_id=category and active and (workspace_id=w or workspace_id is null) order by (workspace_id is not null) desc,version desc limit 1;
 if not found then raise sqlstate 'PT409' using message='No active governed route for category'; end if;
 return jsonb_build_object('policy_id',policy.id::text,'policy_version',policy.version,'category_id',policy.category_id,'route_kind',policy.route_kind,'owner_role',policy.owner_role,'escalation_role',policy.escalation_role,'steps',policy.steps);
end $$;

create function private.error_analysis_enqueue(w uuid,c_id uuid,a uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.cases; i public.intakes; run public.analysis_runs; run_id uuid:=gen_random_uuid(); source_list jsonb; binding jsonb; snapshot jsonb; digest text;
begin
 select * into c from public.cases where workspace_id=w and id=c_id for update;
 select * into i from public.intakes where workspace_id=w and case_id=c_id and attempt_id=c.current_attempt_id order by received_at desc,id desc limit 1;
 if not found then raise sqlstate 'PT422' using message='Saved current Error Analysis intake required'; end if;
 select * into run from public.analysis_runs where workspace_id=w and case_id=c_id and attempt_id=c.current_attempt_id and input_revision=c.input_revision and workflow_version='error-analysis-v1' and not evaluation_only and state in ('queued','running') limit 1;
 if found then return jsonb_build_object('queued',true,'run_id',run.id,'duplicate',true); end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',e.id,'workspace_id',w,'case_id',c.id,'attempt_id',c.current_attempt_id,'source_id',e.source_id,'source_version',e.source_version,'kind',e.kind,'filename',e.filename,'bucket_id',e.bucket_id,'object_path',e.object_path,'sha256',e.sha256,'byte_size',e.byte_size,'content_type',e.content_type,'provenance',case when e.synthetic then 'synthetic' else 'user_supplied' end) order by s.ordinal),'[]') into source_list from public.intake_sources s join public.evidence_versions e on e.workspace_id=s.workspace_id and e.id=s.evidence_id where s.workspace_id=w and s.intake_id=i.id;
 binding:=jsonb_build_object('workspace_id',w,'run_id',run_id,'case_id',c.id,'attempt_id',c.current_attempt_id,'input_revision',c.input_revision::text,'source_manifest_sha256',i.manifest->>'source_manifest_sha256','workflow_version','error-analysis-v1','schema_version','error-analysis-v1','prompt_versions',i.manifest->'prompt_versions','model_configuration',i.manifest->'model_configuration');
 snapshot:=jsonb_build_object('snapshot_version','error-analysis-snapshot-v1','binding',binding,'source_manifest',i.manifest->'source_manifest','sources',source_list,'routing_context',coalesce(c.business_context->'routing_context','{}'));
 digest:=encode(pg_catalog.sha256(convert_to(snapshot::text,'UTF8')),'hex');
 insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by,workflow_version,schema_version,prompt_versions,model_configuration,source_manifest_sha256) values(run_id,w,c.id,c.current_attempt_id,digest,snapshot,c.version,c.input_revision,a,'error-analysis-v1','error-analysis-v1',i.manifest->'prompt_versions',i.manifest->'model_configuration',i.manifest->>'source_manifest_sha256') returning * into run;
 insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot) select w,run.id,(value->>'id')::uuid,jsonb_build_object('evidence',value) from jsonb_array_elements(source_list);
 insert into public.jobs(workspace_id,run_id) values(w,run.id);
 update public.cases set requested_run_id=run.id,analysis_status='pending' where id=c.id;
 return jsonb_build_object('queued',true,'run_id',run.id,'snapshot_hash',digest,'duplicate',false);
end $$;

create function private.commit_error_analysis_intake(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=(p->>'actor_id')::uuid; r text:=p->>'acting_role'; m jsonb:=p->'manifest'; c public.cases; at_row public.attempts; intake public.intakes; delivery text:=private.nonempty(p->>'delivery_key','delivery_key'); payload_hash text; source jsonb; meta jsonb; evidence jsonb; ids uuid[]:='{}'; first_id uuid; n integer:=0; queued jsonb;
begin
 perform private.require_actor(w,a,r); if r<>'process_owner' or p->>'workflow_version' is distinct from 'error-analysis-v1' then raise insufficient_privilege using message='Process owner Error Analysis intake required'; end if;
 if m->>'schema_version' is distinct from 'log-only-v1' or jsonb_typeof(m->'sources') is distinct from 'array' or jsonb_array_length(m->'sources') not between 1 and 8 or jsonb_typeof(p->'input_sources') is distinct from 'array' or jsonb_array_length(p->'input_sources')<>jsonb_array_length(m->'sources') then raise sqlstate 'PT422' using message='Complete original source manifest required'; end if;
 if p->'prompt_versions' is distinct from '{"agent1":"error-analysis-extraction-v1","agent2":"error-analysis-v1","agent3":"error-analysis-summary-v1"}'::jsonb or p->'model_configuration' is distinct from '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium"}'::jsonb then raise sqlstate 'PT422' using message='Unsupported Error Analysis configuration'; end if;
 payload_hash:=encode(pg_catalog.sha256(convert_to(jsonb_build_object('manifest',m,'workflow_version','error-analysis-v1','routing_context',coalesce(p->'routing_context','{}'))::text,'UTF8')),'hex');
 perform pg_advisory_xact_lock(hashtextextended(w::text||':'||delivery,12)); select * into intake from public.intakes where workspace_id=w and delivery_key=delivery;
 if found then if intake.payload_sha256<>payload_hash then raise sqlstate 'PT409' using message='Delivery key content conflict'; end if; return jsonb_build_object('intake_id',intake.id,'case_id',intake.case_id,'attempt_id',intake.attempt_id,'duplicate',true); end if;
 insert into public.cases(workspace_id,title,description,due_at,workflow_version,source_manifest,review_flags) values(w,'Supplied log awaiting Error Analysis','Original evidence saved; human validation remains required',private.business_due(now(),2),'error-analysis-v1',m,array['document_identity_required']) returning * into c;
 insert into public.attempts(workspace_id,case_id,attempt_key,result) values(w,c.id,'intake:'||delivery,'unknown') returning * into at_row; update public.cases set current_attempt_id=at_row.id,business_context=jsonb_build_object('routing_context',coalesce(p->'routing_context','{}')) where id=c.id;
 for source in select value from jsonb_array_elements(m->'sources') loop
  meta:=p->'input_sources'->n; n:=n+1;
  if meta->>'source_id' is distinct from source->>'source_id' or meta->>'source_version' is distinct from source->>'source_version' or meta->>'filename' is distinct from source->>'original_filename' or meta->>'sha256' is distinct from source->>'content_sha256' then raise sqlstate 'PT422' using message='Stored original metadata differs from manifest'; end if;
  evidence:=private.register_evidence(jsonb_build_object('workspace_id',w,'actor_id',a,'acting_role',r,'case_id',c.id,'attempt_id',at_row.id,'kind','original_log','storage',meta)); ids:=array_append(ids,(evidence->>'id')::uuid); first_id:=coalesce(first_id,(evidence->>'id')::uuid);
 end loop;
 insert into public.intakes(workspace_id,case_id,attempt_id,original_evidence_id,delivery_key,payload_sha256,manifest,supplied_by) values(w,c.id,at_row.id,first_id,delivery,payload_hash,jsonb_build_object('workflow_version','error-analysis-v1','source_manifest',m,'source_manifest_sha256',p->>'source_manifest_sha256','prompt_versions',p->'prompt_versions','model_configuration',p->'model_configuration'),a) returning * into intake;
 insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename,ordinal) select w,intake.id,ids[x],m->'sources'->(x-1)->>'original_filename',x from generate_subscripts(ids,1) x;
 queued:=private.error_analysis_enqueue(w,c.id,a);
 return jsonb_build_object('intake_id',intake.id,'case_id',c.id,'attempt_id',at_row.id,'evidence_id',first_id,'duplicate',false,'analysis',queued);
end $$;

create function private.error_analysis_save_stage(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs; run public.analysis_runs; stage_name text:=p->>'stage'; prior jsonb;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid); select * into run from public.analysis_runs where id=j.run_id;
 if run.workflow_version<>'error-analysis-v1' then raise sqlstate 'PT422' using message='Error Analysis run required'; end if;
 if stage_name not in ('agent1','agent2','agent3') or p->'output'->'binding' is distinct from run.snapshot->'binding' or p->'output'->>'stage' is distinct from stage_name or (stage_name in ('agent2','agent3') and p->'output'->'output'->>'schema_version' is distinct from 'error-analysis-v1') then raise sqlstate 'PT422' using message='Error Analysis checkpoint binding mismatch'; end if;
 if stage_name='agent2' and not exists(select 1 from public.validated_stages where run_id=run.id and stage='agent1' and invalidated_at is null) or stage_name='agent3' and not exists(select 1 from public.validated_stages where run_id=run.id and stage='agent2' and invalidated_at is null) then raise sqlstate 'PT422' using message='Prior Error Analysis stage required'; end if;
 select output into prior from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and stage=stage_name and invalidated_at is null;
 if found and prior is distinct from p->'output' then raise sqlstate 'PT409' using message='Immutable stage differs'; end if;
 insert into public.validated_stages(workspace_id,run_id,stage,output) values(j.workspace_id,j.run_id,stage_name,p->'output') on conflict(workspace_id,run_id,stage) do update set output=excluded.output,saved_at=now(),invalidated_at=null where validated_stages.invalidated_at is not null;
 return jsonb_build_object('saved',true);
end $$;

create function private.error_analysis_complete_run(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; run public.analysis_runs; c public.cases; receipt public.run_results; output jsonb:=p->'output'; succeeded boolean:=coalesce((p->>'succeeded')::boolean,false); current_run boolean;
begin
 select * into job from public.jobs where id=(p->>'job_id')::uuid for update; if not found then raise sqlstate 'PT404' using message='Job not found'; end if;
 select * into run from public.analysis_runs where id=job.run_id for update; if run.workflow_version<>'error-analysis-v1' then raise sqlstate 'PT422' using message='Error Analysis run required'; end if;
 select * into receipt from public.run_results where job_id=job.id and submitted_lease_token=(p->>'lease_token')::uuid; if found then return jsonb_build_object('run_id',receipt.run_id,'promoted',receipt.promoted,'duplicate',true); end if;
 insert into public.run_results(workspace_id,run_id,job_id,submitted_lease_token,output,succeeded) values(job.workspace_id,job.run_id,job.id,(p->>'lease_token')::uuid,output,succeeded) returning * into receipt;
 select * into job from private.require_lease(job.id,(p->>'lease_token')::uuid); select * into c from public.cases where id=run.case_id for update;
 if output is not null and ((select jsonb_object_agg(k,output->k) from jsonb_object_keys(run.snapshot->'binding') k) is distinct from run.snapshot->'binding' or output->>'result_kind' is distinct from 'error_analysis' or output->'source_manifest' is distinct from run.snapshot->'source_manifest') then raise sqlstate 'PT422' using message='Error Analysis result binding mismatch'; end if;
 if succeeded and (output->>'outcome' is distinct from 'completed' or not exists(select 1 from public.validated_stages s where s.run_id=run.id and s.stage='agent1' and invalidated_at is null) or not exists(select 1 from public.validated_stages s where s.run_id=run.id and s.stage='agent2' and invalidated_at is null) or not exists(select 1 from public.validated_stages s where s.run_id=run.id and s.stage='agent3' and invalidated_at is null) or output->'extraction' is distinct from (select s.output->'output' from public.validated_stages s where s.run_id=run.id and s.stage='agent1' and s.invalidated_at is null) or output->'analysis' - 'route' is distinct from (select s.output->'output' from public.validated_stages s where s.run_id=run.id and s.stage='agent2' and s.invalidated_at is null) or output->'case_content' is distinct from (select s.output->'output' from public.validated_stages s where s.run_id=run.id and s.stage='agent3' and s.invalidated_at is null) or exists(select 1 from public.stage_calls where run_id=run.id and (state in ('reserved','in_flight','usage_unknown') or actual_usd is null))) then raise sqlstate 'PT422' using message='Validated Error Analysis stages and reconciled usage required'; end if;
 current_run:=not run.evaluation_only and c.linked_case_id is null and c.current_attempt_id=run.attempt_id and c.input_revision=run.input_revision and c.requested_run_id=run.id;
 update public.analysis_runs set state=case when run.evaluation_only then case when succeeded then 'succeeded' else 'failed' end when current_run and succeeded then 'succeeded' when current_run then 'failed' else 'historical' end,output=output,error_code=p->>'error_code' where id=run.id;
 if current_run then update public.cases set analysis_status=case when succeeded then 'available' else 'unavailable' end,published_run_id=case when succeeded then run.id else published_run_id end,error_analysis_result=case when succeeded or published_run_id is null then output else error_analysis_result end,category=case when succeeded then output->'analysis'->>'category_id' else category end,title=case when succeeded then output->'case_content'->'title'->>'text' else title end,description=case when succeeded then coalesce((select string_agg(x->>'text',E'\n') from jsonb_array_elements(output->'case_content'->'what_happened') x),'') else description end,route_policy_id=case when succeeded then (output->'analysis'->'route'->>'policy_id')::uuid else route_policy_id end,route_policy_version=case when succeeded then (output->'analysis'->'route'->>'policy_version')::integer else route_policy_version end,route_state=case when succeeded then 'not_started' else route_state end,version=version+1 where id=c.id; end if;
 update public.jobs set state=case when succeeded then 'succeeded' else 'failed' end,lease_until=null,lease_token=null where id=job.id; update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1 and job_id=job.id and lease_token=job.lease_token; update public.run_results set promoted=current_run where id=receipt.id;
 return jsonb_build_object('run_id',run.id,'promoted',current_run);
end $$;

create function private.error_route_action(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role'; c public.cases; policy public.error_route_policies; step jsonb; order_n integer; expected text; decision text:=p->'data'->>'decision'; proof_ids jsonb:=coalesce(p->'data'->'evidence_ids','[]');
begin
 perform private.require_actor(w,a,r); select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
 if not found or c.workflow_version<>'error-analysis-v1' or c.version<>(p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Current Error Analysis case version required'; end if;
 if c.route_state in ('escalated','completed') then raise sqlstate 'PT422' using message='This route is closed; start a governed follow-up case if more work is required'; end if;
 select * into policy from public.error_route_policies where id=c.route_policy_id and version=c.route_policy_version for share; if not found then raise sqlstate 'PT409' using message='Saved route policy unavailable'; end if;
 order_n:=coalesce((select max(step_order)+1 from public.error_route_milestones where workspace_id=w and case_id=c.id and policy_id=policy.id and policy_version=policy.version),1); step:=policy.steps->(order_n-1); if step is null then raise sqlstate 'PT422' using message='Route is already complete'; end if;
 expected:=step->>'required_role'; if expected<>r then raise insufficient_privilege using message='The configured route role is required'; end if;
 if coalesce(step->>'requires_evidence','false')='true' and (jsonb_typeof(proof_ids) is distinct from 'array' or jsonb_array_length(proof_ids)=0) then raise sqlstate 'PT422' using message='Saved evidence is required for this route step'; end if;
 if jsonb_typeof(proof_ids) is distinct from 'array' or exists(select 1 from jsonb_array_elements_text(proof_ids) id where not exists(select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.id=id::uuid and e.kind='proof')) then raise sqlstate 'PT422' using message='Each route evidence ID must be saved proof for this case'; end if;
 if step->>'requires_approval'='true' and decision not in ('approved','rejected') then raise sqlstate 'PT422' using message='Record an explicit approval or rejection'; end if;
 if step->>'requires_approval'='false' and decision is not null then raise sqlstate 'PT422' using message='Only configured approval steps accept a decision'; end if;
 if policy.category_id='master_data' and order_n>2 and not exists(select 1 from public.error_route_milestones m where m.workspace_id=w and m.case_id=c.id and m.policy_id=policy.id and m.policy_version=policy.version and m.step_order=2 and m.decision='approved') then raise sqlstate 'PT422' using message='Recorded Process Owner approval is required before master-data implementation'; end if;
 if policy.category_id='mapping' and order_n>3 and not exists(select 1 from public.error_route_milestones m where m.workspace_id=w and m.case_id=c.id and m.policy_id=policy.id and m.policy_version=policy.version and m.step_order=3 and m.decision='approved') then raise sqlstate 'PT422' using message='Recorded Process Owner approval is required before reprocessing'; end if;
 insert into public.error_route_milestones(workspace_id,case_id,policy_id,policy_version,step_order,step_id,decision,evidence_ids,note,actor_id,acting_role) values(w,c.id,policy.id,policy.version,order_n,step->>'step_id',coalesce(decision,'completed'),proof_ids,private.nonempty(p->'data'->>'note','note'),a,r);
 update public.cases set route_state=case when decision='rejected' then 'escalated' when order_n=jsonb_array_length(policy.steps) then 'completed' else 'in_progress' end,status=case when decision='rejected' then 'blocked' else status end,version=version+1 where id=c.id;
 return jsonb_build_object('saved',true,'next_step_order',case when decision='rejected' then null else order_n+1 end);
end $$;

create function private.search_error_analysis_history(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=private.knowledge_member(p); w uuid:=(p->>'workspace_id')::uuid; category text:=p->>'category_id'; q text:=coalesce(p->>'query',''); context jsonb:=coalesce(p->'context','{}'); size integer:=coalesce((p->>'limit')::integer,5); items jsonb;
begin
 if category not in ('master_data','mapping','integration_mapping','master_data_restriction','posting_period','tax','currency','document_splitting','account_assignment','technical_interface','unclassified') or length(q)>1000 or size not between 1 and 5 or jsonb_typeof(context)<>'object' then raise sqlstate 'PT422' using message='Invalid bounded Error Analysis history search'; end if;
 select coalesce(jsonb_agg(item order by score desc),'[]') into items from (
  select jsonb_build_object('id',k.id,'case_id',k.case_id,'version',k.version,'matching_facts',coalesce((select jsonb_agg(x.key||': '||x.value) from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key)=x.value),'[]'),'differing_facts',coalesce((select jsonb_agg(x.key||': current '||x.value||'; historical '||coalesce(k.scope->'context'->>x.key,k.scope->>x.key,'unknown')) from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key) is distinct from x.value),'[]'),'score',ts_rank_cd(k.search_document,websearch_to_tsquery('english'::regconfig,q))) item,ts_rank_cd(k.search_document,websearch_to_tsquery('english'::regconfig,q)) score
  from public.knowledge_versions k
  where k.workspace_id=w and k.reuse_state='approved'
   and coalesce(k.scope->>'category',k.resolution_snapshot->'analysis'->>'category_id')=category
   and not exists(select 1 from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key) is distinct from x.value)
   and (q='' or k.search_document @@ websearch_to_tsquery('english'::regconfig,q))
  order by score desc,k.id limit size
 ) ranked;
 return jsonb_build_object('items',items,'retrieval_method','category_then_context');
end $$;

do $$ declare n text; begin
 foreach n in array array['commit_error_analysis_intake','get_error_route','error_analysis_save_stage','error_analysis_complete_run','search_error_analysis_history'] loop
  execute format('create or replace function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',n,n);
  execute format('revoke all on function public.cfin_%I(jsonb),private.%I(jsonb) from public,anon,authenticated,service_role',n,n);
  execute format('grant execute on function public.cfin_%I(jsonb),private.%I(jsonb) to service_role',n,n);
 end loop;
 execute 'create or replace function public.cfin_error_route_action(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.error_route_action(payload); $rpc$';
 revoke all on function public.cfin_error_route_action(jsonb),private.error_route_action(jsonb) from public,anon,authenticated,service_role;
 grant execute on function public.cfin_error_route_action(jsonb),private.error_route_action(jsonb) to authenticated;
end $$;
revoke all on function private.error_analysis_enqueue(uuid,uuid,uuid) from public,anon,authenticated,service_role;
commit;
