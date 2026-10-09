-- Additive factual workflow. Legacy inputs and outputs retain their original meaning.
-- Apply to an isolated verification database before scheduling an operational cutover.
begin;
alter table public.workspaces drop constraint workspaces_synthetic_check;
alter table public.evidence_versions drop constraint evidence_versions_synthetic_check;
alter table public.cases add column workflow_version text not null default 'legacy-v1' check(workflow_version in ('legacy-v1','log-only-v1'));
alter table public.cases add column factual_review_status text not null default 'pending_review' check(factual_review_status in ('pending_review','Accepted','Corrected','Insufficient'));
alter table public.cases add column factual_result jsonb;
alter table public.cases add column source_manifest jsonb;
alter table public.cases add column updated_at timestamptz not null default now();
alter table public.analysis_runs add column workflow_version text not null default 'legacy-v1';
alter table public.analysis_runs add column schema_version text not null default 'legacy-v1';
alter table public.analysis_runs add column prompt_versions jsonb not null default '{}';
alter table public.analysis_runs add column model_configuration jsonb not null default '{}';
alter table public.analysis_runs add column source_manifest_sha256 text;
alter table public.case_reviews add column review_kind text not null default 'diagnosis' check(review_kind in ('diagnosis','factual'));
alter table public.intake_sources drop constraint intake_sources_filename_check;
alter table public.intake_sources drop constraint intake_sources_pkey;
alter table public.intake_sources add primary key(workspace_id,intake_id,evidence_id);
alter table public.intake_sources add column ordinal integer;
alter table public.intake_sources add constraint intake_source_order unique(workspace_id,intake_id,ordinal);
alter table public.milestones drop constraint milestones_kind_check;
alter table public.milestones add constraint milestones_kind_check check(kind in ('correction','reprocessing','validation','investigation','work_completion'));
-- Preserve accepted empty originals too; they cannot yield a completed factual brief.
alter table public.evidence_versions drop constraint evidence_versions_byte_size_check;
alter table public.evidence_versions add constraint evidence_versions_byte_size_check check(byte_size>=0 and byte_size<=10485760);

create function private.touch_case() returns trigger language plpgsql set search_path='' as $$
begin
 if new.workflow_version='log-only-v1' and new.version=old.version and (to_jsonb(new)-'updated_at') is distinct from (to_jsonb(old)-'updated_at') then new.version:=old.version+1; end if;
 new.updated_at:=clock_timestamp(); return new;
end $$;
create trigger case_updated_at before update on public.cases for each row execute function private.touch_case();

create or replace function private.preserve_run_input() returns trigger language plpgsql set search_path='' as $$
begin
 if (to_jsonb(new)-array['state','output','error_code']) is distinct from (to_jsonb(old)-array['state','output','error_code']) then
  raise sqlstate 'PT409' using message='Run input snapshot is immutable';
 end if; return new;
end $$;

-- Storage byte verification belongs to the authenticated upload service. SQL additionally
-- verifies the object exists, its size, scope, version identity and explicit provenance.
create or replace function private.register_evidence(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=(p->>'actor_id')::uuid; r text:=p->>'acting_role';
 c uuid:=(p->>'case_id')::uuid; at_id uuid:=(p->>'attempt_id')::uuid; s jsonb:=p->'storage'; e public.evidence_versions; stored_size bigint; synthetic_source boolean;
begin
 perform private.require_actor(w,a,r);
 if coalesce(p->>'kind','') not in ('original_log','reference','guidance','proof') or jsonb_typeof(s) is distinct from 'object' or coalesce(s->>'sha256','') !~ '^[a-f0-9]{64}$' then raise sqlstate 'PT422' using message='Verified storage metadata required'; end if;
 select (metadata->>'size')::bigint into stored_size from storage.objects where bucket_id='evidence' and name=s->>'object_path';
 if not found or stored_size is null or stored_size is distinct from (s->>'byte_size')::bigint then raise sqlstate 'PT422' using message='Stored object verification required'; end if;
 if p->>'kind'='proof' and (c is null or at_id is null or (p->>'work_cycle')::integer is null) then raise sqlstate 'PT422' using message='Proof needs case, attempt and work cycle'; end if;
 synthetic_source:=case when s->'provenance'->>'kind'='user_supplied' then false else true end;
 if not synthetic_source and exists(select 1 from public.workspaces where id=w and synthetic) then raise sqlstate 'PT422' using message='Real evidence requires a non-synthetic workspace'; end if;
 insert into public.evidence_versions(workspace_id,source_id,source_version,case_id,attempt_id,kind,filename,object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at,work_cycle,synthetic)
 values(w,private.nonempty(s->>'source_id','source_id'),private.nonempty(s->>'source_version','source_version'),c,at_id,p->>'kind',private.nonempty(s->>'filename','filename'),s->>'object_path',s->>'sha256',stored_size,s->>'content_type',s->'provenance',a,(s->>'observed_at')::timestamptz,(p->>'work_cycle')::integer,synthetic_source)
 on conflict(workspace_id,source_id,source_version) do nothing returning * into e;
 if not found then
  select * into e from public.evidence_versions where workspace_id=w and source_id=s->>'source_id' and source_version=s->>'source_version';
  if e.sha256<>s->>'sha256' or e.case_id is distinct from c or e.attempt_id is distinct from at_id or e.kind<>p->>'kind' or e.synthetic<>synthetic_source then raise sqlstate 'PT409' using message='Evidence version conflict'; end if;
 else perform private.audit(w,c,a,r,'evidence_registered',null,jsonb_build_object('evidence_id',e.id,'kind',e.kind),null);
 end if; return to_jsonb(e);
end $$;

alter function private.enqueue(uuid,uuid,uuid) rename to enqueue_legacy;
create function private.enqueue(w uuid,c_id uuid,a uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.cases; i public.intakes; run public.analysis_runs; run_id uuid:=gen_random_uuid(); sn jsonb; sources jsonb; binding jsonb; digest text;
 prompts jsonb; models jsonb;
begin
 select * into c from public.cases where workspace_id=w and id=c_id for update;
 if c.id is null then raise sqlstate 'PT404' using message='Case not found'; end if;
 if c.workflow_version<>'log-only-v1' then return private.enqueue_legacy(w,c_id,a); end if;
 if c.linked_case_id is not null then return jsonb_build_object('queued',false,'reason','linked_case_use_canonical_case'); end if;
 select * into i from public.intakes where workspace_id=w and case_id=c.id and attempt_id=c.current_attempt_id order by received_at desc,id desc limit 1;
 if not found then raise sqlstate 'PT422' using message='Saved current log intake required'; end if;
 prompts:=coalesce(i.manifest->'prompt_versions','{"agent1":"log-extraction-v1","agent2":"log-selection-v1","agent3":"log-summary-v1"}');
 models:=coalesce(i.manifest->'model_configuration','{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium"}');
 select coalesce(jsonb_agg(jsonb_build_object('id',e.id,'workspace_id',w,'case_id',c.id,'attempt_id',c.current_attempt_id,'source_id',e.source_id,'source_version',e.source_version,'kind',e.kind,'filename',e.filename,'bucket_id',e.bucket_id,'object_path',e.object_path,'sha256',e.sha256,'byte_size',e.byte_size,'content_type',e.content_type,'provenance',case when e.synthetic then 'synthetic' else 'user_supplied' end) order by s.ordinal),'[]') into sources
 from public.intake_sources s join public.evidence_versions e on e.workspace_id=s.workspace_id and e.id=s.evidence_id where s.workspace_id=w and s.intake_id=i.id;
 if jsonb_array_length(sources)<>jsonb_array_length(i.manifest->'source_manifest'->'sources') then raise sqlstate 'PT422' using message='Complete saved source set required'; end if;
 -- Snapshot identity omits the new run UUID when looking for an already active input.
 select * into run from public.analysis_runs where workspace_id=w and case_id=c.id and attempt_id=c.current_attempt_id and input_revision=c.input_revision and workflow_version='log-only-v1' and not evaluation_only and state in ('queued','running') limit 1;
 if found then return jsonb_build_object('queued',true,'run_id',run.id,'duplicate',true); end if;
 binding:=jsonb_build_object('workspace_id',w,'run_id',run_id,'case_id',c.id,'attempt_id',c.current_attempt_id,'input_revision',c.input_revision::text,'source_manifest_sha256',i.manifest->>'source_manifest_sha256','workflow_version','log-only-v1','schema_version','log-only-v1','prompt_versions',prompts,'model_configuration',models);
 sn:=jsonb_build_object('snapshot_version','log-only-snapshot-draft-v1','binding',binding,'source_manifest',i.manifest->'source_manifest','sources',sources);
 digest:=encode(pg_catalog.sha256(convert_to(sn::text,'UTF8')),'hex');
 insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by,workflow_version,schema_version,prompt_versions,model_configuration,source_manifest_sha256)
 values(run_id,w,c.id,c.current_attempt_id,digest,sn,c.version,c.input_revision,a,'log-only-v1','log-only-v1',prompts,models,i.manifest->>'source_manifest_sha256') returning * into run;
 insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot) select w,run.id,(s->>'id')::uuid,jsonb_build_object('evidence',s) from jsonb_array_elements(sources) s;
 insert into public.jobs(workspace_id,run_id) values(w,run.id);
 update public.cases set requested_run_id=run.id,analysis_status='pending' where id=c.id;
 perform private.audit(w,c.id,a,'process_owner','analysis_queued',null,jsonb_build_object('run_id',run.id,'workflow_version',run.workflow_version,'input_revision',c.input_revision),null);
 return jsonb_build_object('queued',true,'run_id',run.id,'snapshot_hash',digest,'duplicate',false);
end $$;

alter function private.commit_intake(jsonb) rename to commit_intake_legacy;
do $$ begin execute replace(pg_get_functiondef('private.commit_intake_legacy(jsonb)'::regprocedure),'insert into public.intake_sources values(', 'insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename) values('); end $$;
create function private.commit_intake(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=(p->>'actor_id')::uuid; r text:=p->>'acting_role'; m jsonb:=p->'manifest';
 delivery text; payload_hash text; c public.cases; at_row public.attempts; intake public.intakes; source jsonb; meta jsonb; evidence jsonb; ordinal integer:=0; first_evidence uuid; saved_ids uuid[]:='{}'; queue jsonb;
begin
 if p->>'workflow_version' is distinct from 'log-only-v1' then return private.commit_intake_legacy(p); end if;
 perform private.require_actor(w,a,r); if r<>'process_owner' then raise insufficient_privilege using message='Process owner intake required'; end if;
 delivery:=private.nonempty(p->>'delivery_key','delivery_key');
 if m->>'schema_version' is distinct from 'log-only-v1' or jsonb_typeof(m->'sources') is distinct from 'array' or jsonb_array_length(m->'sources') not between 1 and 8 or jsonb_typeof(p->'input_sources') is distinct from 'array' or jsonb_array_length(p->'input_sources')<>jsonb_array_length(m->'sources') or coalesce(p->>'source_manifest_sha256','') !~ '^[a-f0-9]{64}$' then raise sqlstate 'PT422' using message='Versioned complete original source manifest required'; end if;
 if (select count(distinct s->>'source_id') from jsonb_array_elements(m->'sources') s)<>jsonb_array_length(m->'sources') or (select sum((s->>'byte_size')::bigint) from jsonb_array_elements(m->'sources') s)>8192 or (select sum((s->'readable'->>'line_count')::bigint) from jsonb_array_elements(m->'sources') s)>64 then raise sqlstate 'PT422' using message='Original source identity or analysis capacity exceeded'; end if;
 if p ? 'prompt_versions' and p->'prompt_versions'<>'{"agent1":"log-extraction-v1","agent2":"log-selection-v1","agent3":"log-summary-v1"}'::jsonb then raise sqlstate 'PT422' using message='Unsupported factual prompt configuration'; end if;
 if p ? 'model_configuration' and p->'model_configuration'<>'{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium"}'::jsonb then raise sqlstate 'PT422' using message='Unsupported factual model configuration'; end if;
 payload_hash:=encode(pg_catalog.sha256(convert_to(jsonb_build_object('manifest',m,'workflow_version','log-only-v1','routing_context',coalesce(p->'routing_context','{}'))::text,'UTF8')),'hex');
 perform pg_advisory_xact_lock(hashtextextended(w::text||':'||delivery,0));
 select * into intake from public.intakes where workspace_id=w and delivery_key=delivery;
 if found then
  if intake.payload_sha256<>payload_hash then raise sqlstate 'PT409' using message='Delivery key content conflict'; end if;
  return jsonb_build_object('intake_id',intake.id,'case_id',intake.case_id,'attempt_id',intake.attempt_id,'duplicate',true);
 end if;
 insert into public.cases(workspace_id,title,description,due_at,workflow_version,source_manifest,review_flags)
 values(w,'Supplied log awaiting factual analysis','Original evidence saved; SAP identity and processing chronology are unconfirmed',private.business_due(now(),2),'log-only-v1',m,array['document_identity_required']) returning * into c;
 insert into public.attempts(workspace_id,case_id,attempt_key,result) values(w,c.id,'intake:'||delivery,'unknown') returning * into at_row;
 update public.cases set current_attempt_id=at_row.id where id=c.id;
 for source in select value from jsonb_array_elements(m->'sources') loop
  meta:=p->'input_sources'->ordinal; ordinal:=ordinal+1;
  if meta->>'source_id' is distinct from source->>'source_id' or meta->>'source_version' is distinct from source->>'source_version' or meta->>'filename' is distinct from source->>'original_filename' or meta->>'sha256' is distinct from source->>'content_sha256' or meta->'byte_size' is distinct from source->'byte_size' or meta->>'content_type' is distinct from 'text/plain' or source->>'content_type' is distinct from 'text/plain' or coalesce(source->>'provenance','') not in ('synthetic','user_supplied') or meta->'provenance'->>'kind' is distinct from source->>'provenance' then raise sqlstate 'PT422' using message='Stored original metadata differs from manifest'; end if;
  evidence:=private.register_evidence(jsonb_build_object('workspace_id',w,'actor_id',a,'acting_role',r,'case_id',c.id,'attempt_id',at_row.id,'kind','original_log','storage',meta));
  saved_ids:=array_append(saved_ids,(evidence->>'id')::uuid); first_evidence:=coalesce(first_evidence,(evidence->>'id')::uuid);
 end loop;
 insert into public.intakes(workspace_id,case_id,attempt_id,original_evidence_id,delivery_key,payload_sha256,manifest,supplied_by)
 values(w,c.id,at_row.id,first_evidence,delivery,payload_hash,jsonb_build_object('workflow_version','log-only-v1','source_manifest',m,'source_manifest_sha256',p->>'source_manifest_sha256')||case when p ? 'model_configuration' then jsonb_build_object('model_configuration',p->'model_configuration') else '{}' end||case when p ? 'prompt_versions' then jsonb_build_object('prompt_versions',p->'prompt_versions') else '{}' end,a) returning * into intake;
 insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename,ordinal) select w,intake.id,saved_ids[n],m->'sources'->(n-1)->>'original_filename',n from generate_subscripts(saved_ids,1) n;
 perform private.audit(w,c.id,a,r,'intake_saved',null,jsonb_build_object('intake_id',intake.id,'attempt_id',at_row.id,'workflow_version','log-only-v1','source_count',ordinal),null);
 if p ? 'routing_context' then
  if jsonb_typeof(p->'routing_context') is distinct from 'object' or exists(select 1 from jsonb_each(p->'routing_context') x where x.key not in ('source_system','target_system','interface','company_code') or jsonb_typeof(x.value)<>'string' or length(btrim(x.value#>>'{}'))=0) then raise sqlstate 'PT422' using message='Invalid administrative routing context'; end if;
  update public.cases set business_context=jsonb_build_object('routing_context',p->'routing_context') where id=c.id;
 end if;
 queue:=private.enqueue(w,c.id,a);
 return jsonb_build_object('intake_id',intake.id,'case_id',c.id,'attempt_id',at_row.id,'evidence_id',first_evidence,'duplicate',false,'analysis',queue);
end $$;

alter function private.save_stage(jsonb) rename to save_stage_legacy;
create function private.save_stage(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.jobs; run public.analysis_runs; prior jsonb;
begin
 select * into j from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
 select * into run from public.analysis_runs where id=j.run_id;
 if run.workflow_version<>'log-only-v1' then return private.save_stage_legacy(p); end if;
 if p->>'source_run_id' is not null or p->'output'->'binding' is distinct from run.snapshot->'binding' or p->'output'->>'stage' is distinct from p->>'stage' or coalesce(p->'output'->>'input_sha256','') !~ '^[a-f0-9]{64}$' or p->'output'->'output'->>'schema_version' is distinct from run.schema_version then raise sqlstate 'PT422' using message='Factual checkpoint binding mismatch'; end if;
 if p->>'stage' not in ('agent1','agent2','agent3') then raise sqlstate 'PT422' using message='Unknown factual stage'; end if;
 if p->>'stage'='agent2' and not exists(select 1 from public.validated_stages where run_id=run.id and stage='agent1' and invalidated_at is null) or p->>'stage'='agent3' and not exists(select 1 from public.validated_stages where run_id=run.id and stage='agent2' and invalidated_at is null) then raise sqlstate 'PT422' using message='Prior validated factual stage required'; end if;
 select output into prior from public.validated_stages where workspace_id=j.workspace_id and run_id=j.run_id and stage=p->>'stage' and invalidated_at is null;
 if found and prior is distinct from p->'output' then raise sqlstate 'PT409' using message='Immutable stage differs'; end if;
 insert into public.validated_stages(workspace_id,run_id,stage,output) values(j.workspace_id,j.run_id,p->>'stage',p->'output') on conflict(workspace_id,run_id,stage) do update set output=excluded.output,saved_at=now(),invalidated_at=null where validated_stages.invalidated_at is not null;
 return jsonb_build_object('saved',true);
end $$;

create table public.context_owner_rules (
 id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.workspaces(id),
 context jsonb not null check(jsonb_typeof(context)='object'), version bigint not null check(version>0),
 assigned_user_id uuid, owner_role text not null check(owner_role in ('process_owner','master_data_owner','mapping_owner','finance_owner','validator')),
 active boolean not null, review_due date, actor_id uuid not null references auth.users(id), reason text not null check(length(btrim(reason))>0), configured_at timestamptz not null default now(),
 unique(workspace_id,context,version), foreign key(workspace_id,assigned_user_id) references public.workspace_memberships(workspace_id,user_id),
 check(not active or (assigned_user_id is not null and review_due is not null))
);
alter table public.context_owner_rules enable row level security;
create policy member_read on public.context_owner_rules for select to authenticated using(private.is_member(workspace_id));
revoke all on public.context_owner_rules from public,anon,authenticated;
grant select on public.context_owner_rules to authenticated,service_role;
create trigger immutable_context_owner_rules before update or delete on public.context_owner_rules for each row execute function private.preserve_source();

create function private.filter_factual_history(value jsonb,w uuid,run_id uuid default null,keep_candidates boolean default false) returns jsonb language plpgsql security definer set search_path='' as $$
declare refs jsonb; withheld boolean; result jsonb:=value;
begin
 if value->>'result_kind' is distinct from 'factual' then return value; end if;
 select coalesce(jsonb_agg(ref),'[]'),coalesce(bool_or(not eligible),false) into refs,withheld from (
  select ref,exists(select 1 from public.knowledge_versions k where k.workspace_id=w and k.id=(ref->>'knowledge_id')::uuid and k.version=(ref->>'knowledge_version')::integer and k.reuse_state='approved' and k.case_id=(ref->>'case_id')::uuid and (run_id is null or exists(select 1 from public.run_knowledge_sources h where h.run_id=filter_factual_history.run_id and h.workspace_id=w and h.knowledge_id=k.id and h.knowledge_version=k.version and h.knowledge_revision=k.revision))) eligible
  from jsonb_array_elements(coalesce(value->'summary'->'related_cases','[]')) ref
 ) x where eligible;
 -- Detect withheld references separately because the aggregate above only sees eligible rows.
 withheld:=jsonb_array_length(refs)<>jsonb_array_length(coalesce(value->'summary'->'related_cases','[]'));
 if value->'summary'<>'null'::jsonb and value->'summary' is not null then result:=jsonb_set(result,'{summary,related_cases}',refs); end if;
 if not keep_candidates then result:=jsonb_set(result,'{history,candidates}','[]'); end if;
 if withheld then result:=jsonb_set(result,'{limitations}',coalesce(result->'limitations','[]')||jsonb_build_array('A historical reference is no longer eligible and has been withheld.')); end if;
 return result;
end $$;

alter function private.complete_run(jsonb) rename to complete_run_legacy;
create function private.complete_run(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
#variable_conflict use_variable
declare job public.jobs; run public.analysis_runs; c public.cases; is_current boolean; succeeded boolean:=coalesce((p->>'succeeded')::boolean,false); receipt public.run_results; output jsonb:=p->'output'; matched public.context_owner_rules; matches integer;
begin
 select * into job from public.jobs where id=(p->>'job_id')::uuid;
 select * into run from public.analysis_runs where id=job.run_id;
 if run.workflow_version is distinct from 'log-only-v1' then return private.complete_run_legacy(p); end if;
 perform 1 from private.worker_slot where singleton=1 for update;
 select * into job from public.jobs where id=job.id for update;
 select * into receipt from public.run_results where job_id=job.id and submitted_lease_token=(p->>'lease_token')::uuid;
 if found then return jsonb_build_object('run_id',receipt.run_id,'promoted',receipt.promoted,'duplicate',true); end if;
 insert into public.run_results(workspace_id,run_id,job_id,submitted_lease_token,output,succeeded) values(job.workspace_id,job.run_id,job.id,(p->>'lease_token')::uuid,output,succeeded) returning * into receipt;
 if job.state<>'running' or job.lease_token is distinct from (p->>'lease_token')::uuid or job.lease_until<=clock_timestamp() then return jsonb_build_object('run_id',job.run_id,'promoted',false,'lease_rejected',true,'result_id',receipt.id); end if;
 select * into job from private.require_lease(job.id,(p->>'lease_token')::uuid);
 select * into run from public.analysis_runs where id=job.run_id for update;
 select * into c from public.cases where id=run.case_id for update;
 if output is not null and output<>'null'::jsonb and ((select jsonb_object_agg(k,output->k) from jsonb_object_keys(run.snapshot->'binding') k) is distinct from run.snapshot->'binding' or output->>'result_kind' is distinct from 'factual' or output->'source_manifest' is distinct from run.snapshot->'source_manifest') then raise sqlstate 'PT422' using message='Factual result binding mismatch'; end if;
 if succeeded and (output->>'outcome' is distinct from 'completed' or nullif(btrim(output->'summary'->'title'->>'text'),'') is null or not exists(select 1 from public.validated_stages s where s.run_id=run.id and s.stage='agent1' and s.invalidated_at is null and s.output->'output'=output->'extraction') or not exists(select 1 from public.validated_stages s where s.run_id=run.id and s.stage='agent2' and s.invalidated_at is null and s.output->'output'=output->'selection') or not exists(select 1 from public.validated_stages s where s.run_id=run.id and s.stage='agent3' and s.invalidated_at is null and (s.output->'output')-'related_cases'=(output->'summary')-'related_cases' and not exists(select 1 from jsonb_array_elements(coalesce(output->'summary'->'related_cases','[]')) cited where not (s.output->'output'->'related_cases') @> jsonb_build_array(cited))) or exists(select 1 from public.stage_calls where run_id=run.id and (state in ('reserved','in_flight','usage_unknown') or actual_usd is null))) then raise sqlstate 'PT422' using message='Validated factual stages and reconciled usage required'; end if;
 -- Lock only cited knowledge. An unused withdrawn retrieval candidate cannot discard facts.
 perform 1 from public.knowledge_versions k where k.workspace_id=run.workspace_id and k.id in(select (x->>'knowledge_id')::uuid from jsonb_array_elements(coalesce(output->'summary'->'related_cases','[]')) x) for share;
 output:=private.filter_factual_history(output,run.workspace_id,run.id,true);
 is_current:=coalesce(not run.evaluation_only and c.linked_case_id is null and c.current_attempt_id=run.attempt_id and c.input_revision=run.input_revision and c.requested_run_id=run.id,false);
 update public.analysis_runs set state=case when run.evaluation_only then case when succeeded then 'succeeded' else 'failed' end when not is_current then 'historical' when succeeded then 'succeeded' else 'failed' end,output=output,error_code=p->>'error_code' where id=run.id;
 if is_current then
  update public.cases set analysis_status=case when succeeded then 'available' else 'unavailable' end,published_run_id=case when succeeded then run.id else published_run_id end,
   factual_result=case when succeeded or published_run_id is null then private.filter_factual_history(output,c.workspace_id,null) else factual_result end,
   title=case when succeeded then output->'summary'->'title'->>'text' else title end,
   description=case when succeeded then coalesce((select string_agg(x->>'text',E'\n') from jsonb_array_elements(output->'summary'->'statements') x),'') else description end,
   factual_review_status=case when succeeded then 'pending_review' else factual_review_status end,version=version+1 where id=c.id;
  if succeeded and c.status in ('created','owner_notified') and c.work_started_at is null and not exists(select 1 from public.assignments where workspace_id=c.workspace_id and case_id=c.id) then
   select count(*) into matches from public.context_owner_rules r where r.workspace_id=c.workspace_id and r.context=c.business_context->'routing_context' and r.active and r.review_due>=current_date and r.version=(select max(v.version) from public.context_owner_rules v where v.workspace_id=r.workspace_id and v.context=r.context) and exists(select 1 from public.workspace_memberships m where m.workspace_id=r.workspace_id and m.user_id=r.assigned_user_id and r.owner_role=any(m.roles)) and exists(select 1 from public.workspace_memberships m where m.workspace_id=r.workspace_id and m.user_id=r.actor_id and 'process_owner'=any(m.roles));
   if matches=1 then
    select * into matched from public.context_owner_rules r where r.workspace_id=c.workspace_id and r.context=c.business_context->'routing_context' order by version desc limit 1;
    insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason) values(c.workspace_id,c.id,1,matched.assigned_user_id,matched.owner_role,matched.actor_id,'process_owner','Configured factual context rule '||matched.id::text);
    insert into public.notifications(workspace_id,case_id,assignment_id,event_key) select c.workspace_id,c.id,id,'assignment' from public.assignments where workspace_id=c.workspace_id and case_id=c.id and version=1;
    perform private.audit(c.workspace_id,c.id,null,'worker','configured_owner_assigned',null,jsonb_build_object('rule_id',matched.id,'run_id',run.id),null);
   end if;
  end if;
 end if;
 update public.jobs set state=case when succeeded then 'succeeded' else 'failed' end,lease_until=null,lease_token=null where id=job.id;
 update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1 and job_id=job.id and lease_token=job.lease_token;
 update public.run_results set promoted=is_current where id=receipt.id;
 perform private.audit(c.workspace_id,c.id,null,'worker','analysis_finished',null,jsonb_build_object('run_id',run.id,'promoted',is_current,'succeeded',succeeded,'evaluation_only',run.evaluation_only),p->>'error_code');
 return jsonb_build_object('run_id',run.id,'promoted',is_current,'case_version',c.version+case when is_current then 1 else 0 end);
end $$;

create function private.load_history_evidence(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=private.knowledge_member(p); w uuid:=(p->>'workspace_id')::uuid; k public.knowledge_versions; c public.cases; ev jsonb; resolution jsonb;
begin
 select * into k from public.knowledge_versions where workspace_id=w and id=(p->>'knowledge_id')::uuid and version=(p->>'version')::integer and reuse_state='approved' for share;
 if not found or k.case_id is null or k.case_id=(p->>'current_case_id')::uuid or coalesce(p->'excluded_case_ids','[]') ? k.case_id::text then raise sqlstate 'PT404' using message='Eligible historical case not found'; end if;
 select * into c from public.cases where workspace_id=w and id=k.case_id;
 select to_jsonb(rr) into resolution from public.resolution_records rr where workspace_id=w and id=k.resolution_id;
 select coalesce(jsonb_agg(to_jsonb(e) order by e.stored_at,e.id),'[]') into ev from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.kind='original_log' and exists(select 1 from jsonb_array_elements(k.original_sources) original where original->>'id'=e.id::text and original->>'sha256'=e.sha256 and original->>'source_version'=e.source_version);
 if jsonb_array_length(ev)>8 then raise sqlstate 'PT422' using message='Historical originals exceed read envelope'; end if;
 return jsonb_build_object('knowledge',to_jsonb(k)-'concept_vector'-'search_document','case',to_jsonb(c),'resolution',resolution,'originals',ev);
end $$;

create function private.factual_record_complete(body jsonb) returns void language plpgsql set search_path='' as $$
begin
 perform private.nonempty(body->>'findings','findings'); perform private.nonempty(body->>'action_or_no_change','action_or_no_change'); perform private.nonempty(body->>'outcome','outcome'); perform private.nonempty(body->>'scope','scope');
 if jsonb_typeof(body->'gaps') is distinct from 'array' or exists(select 1 from jsonb_array_elements(body->'gaps') x where jsonb_typeof(x)<>'string' or length(btrim(x#>>'{}'))=0) then raise sqlstate 'PT422' using message='Explicit gaps array required'; end if;
 if jsonb_typeof(body->'proof_ids') is distinct from 'array' or jsonb_array_length(body->'proof_ids')=0 or body->'human_confirmed' is distinct from 'true'::jsonb then raise sqlstate 'PT422' using message='Human confirmation and saved evidence required'; end if;
end $$;

alter function private.case_action(jsonb) rename to case_action_legacy;
create function private.case_action(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
<<factual_action>>
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role'; c public.cases; before jsonb;
 body jsonb:=coalesce(p->'data','{}'); action text:=p->>'action'; key text; digest text; receipt private.action_receipts; assigned uuid;
 reviewed public.analysis_runs; milestone_id uuid; next_version integer; at_id uuid; old_attempt public.attempts; result jsonb; rule public.context_owner_rules; context jsonb; previous_version bigint; due date; count_checks integer;
begin
 perform private.require_actor(w,a,r);
 select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid;
 if not found then raise sqlstate 'PT404' using message='Case not found'; end if;
 if c.workflow_version<>'log-only-v1' then return private.case_action_legacy(p); end if;
 key:=private.nonempty(p->>'request_key','request_key'); digest:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
 perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||key,2));
 select * into receipt from private.action_receipts where workspace_id=w and actor_id=a and request_key=key;
 if found then if receipt.payload_hash<>digest then raise sqlstate 'PT409' using message='Action key content conflict'; end if; return receipt.response; end if;
 select * into c from public.cases where workspace_id=w and id=c.id for update;
 if c.version is distinct from (p->>'expected_version')::bigint or c.linked_case_id is not null then raise sqlstate 'PT409' using message='Case changed; use current canonical case'; end if;
 before:=to_jsonb(c); at_id:=c.current_attempt_id;
 select assigned_user_id into assigned from public.assignments where workspace_id=w and case_id=c.id order by version desc limit 1;
 if action in ('assign','owner_rule','priority','reopen','due_date','retry_notification') and r<>'process_owner' then raise insufficient_privilege using message='Process owner required'; end if;
 if action='record_validation' and r not in ('validator','process_owner') then raise insufficient_privilege using message='Validator required'; end if;
 if action not in ('assign','owner_rule','priority','reopen','due_date','retry_notification','record_validation') and r<>'process_owner' and assigned is distinct from a then raise insufficient_privilege using message='Assigned owner required'; end if;
 if action in ('review_summary','review_factual') then
  select * into reviewed from public.analysis_runs where workspace_id=w and case_id=c.id and id=coalesce((body->>'run_id')::uuid,c.published_run_id,c.requested_run_id) and not evaluation_only and state in ('succeeded','failed') and workflow_version='log-only-v1' and attempt_id=c.current_attempt_id and input_revision=c.input_revision and id in (c.published_run_id,c.requested_run_id);
  if not found then raise sqlstate 'PT422' using message='Current operational factual result or failure required'; end if;
  if body->>'decision'='Accepted' and (reviewed.state<>'succeeded' or reviewed.output->>'outcome' is distinct from 'completed' or reviewed.output->'summary' is null or reviewed.output->'summary'='null'::jsonb) then raise sqlstate 'PT422' using message='Accepted review requires a completed factual summary'; end if;
  if body->>'decision'='Insufficient' then perform private.nonempty(body->'findings'->>'explanation','insufficient summary findings'); if jsonb_typeof(body->'findings'->'gaps') is distinct from 'array' or jsonb_array_length(body->'findings'->'gaps')=0 then raise sqlstate 'PT422' using message='Insufficient summary requires specific gaps'; end if; end if;
  if body->>'decision'='Corrected' then
   perform private.nonempty(body->'findings'->>'explanation','corrected factual explanation');
   if body->'findings'->>'provenance' is distinct from 'human_factual_review' or jsonb_array_length(coalesce(body->'findings'->'entry_ids','[]'))+jsonb_array_length(coalesce(body->'findings'->'proof_ids','[]'))=0 then raise sqlstate 'PT422' using message='Corrected facts require attributed source or proof references'; end if;
  end if;
  if exists(select 1 from jsonb_array_elements_text(coalesce(body->'findings'->'entry_ids','[]')) x where not exists(select 1 from jsonb_array_elements(coalesce(reviewed.output->'extraction'->'entries','[]')) e where e->>'entry_id'=x.value)) then raise sqlstate 'PT422' using message='Factual review entry not in the reviewed extraction'; end if;
  if exists(select 1 from jsonb_array_elements_text(coalesce(body->'findings'->'proof_ids','[]')) x where not exists(select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.id=x.value::uuid and e.kind in ('original_log','proof'))) then raise sqlstate 'PT422' using message='Factual review evidence is not in this case'; end if;
  insert into public.case_reviews(workspace_id,case_id,run_id,decision,reason,cause_confirmed,findings,actor_id,acting_role,review_kind) values(w,c.id,reviewed.id,body->>'decision',body->>'reason',false,coalesce(body->'findings','{}'),a,r,'factual');
  update public.cases set factual_review_status=body->>'decision',unreviewed_new_failure=false where id=c.id;
 elsif action in ('start_work','start_investigation','resume') then
  if action='resume' and c.status<>'blocked' or action<>'resume' and c.status not in ('created','owner_notified') then raise sqlstate 'PT409' using message='Invalid investigation transition'; end if;
  if not exists(select 1 from public.case_reviews rv join public.analysis_runs ar on ar.id=rv.run_id and ar.workspace_id=rv.workspace_id where rv.workspace_id=w and rv.case_id=c.id and rv.review_kind='factual' and not ar.evaluation_only and ar.attempt_id=c.current_attempt_id and ar.input_revision=c.input_revision and ar.id in (c.published_run_id,c.requested_run_id)) then raise sqlstate 'PT422' using message='Current human factual review required before investigation'; end if;
  perform private.nonempty(body->>'reason','reason'); if c.work_started_at is null then perform private.nonempty(body->>'investigation_scope','investigation_scope'); end if;
  update public.cases set status='in_progress',work_started_at=coalesce(work_started_at,now()) where id=c.id;
 elsif action='assign' or action='owner_rule' then
  perform private.nonempty(body->>'reason','reason');
  if body->>'assigned_user_id' is not null and not exists(select 1 from public.workspace_memberships m where m.workspace_id=w and m.user_id=(body->>'assigned_user_id')::uuid and body->>'owner_role'=any(m.roles)) then raise sqlstate 'PT422' using message='Active owner role membership required'; end if;
  if body->'save_owner_rule'='true'::jsonb or action='owner_rule' then
   context:=coalesce(body->'context',c.business_context->'routing_context');
   if jsonb_typeof(context) is distinct from 'object' or nullif(context->>'interface','') is null or nullif(context->>'company_code','') is null or coalesce(nullif(context->>'source_system',''),nullif(context->>'target_system','')) is null or exists(select 1 from jsonb_each(context) x where x.key not in ('source_system','target_system','interface','company_code') or jsonb_typeof(x.value)<>'string' or length(btrim(x.value#>>'{}'))=0) then raise sqlstate 'PT422' using message='Explicit system, interface and company routing context required'; end if;
   perform pg_advisory_xact_lock(hashtextextended(w::text||context::text,9));
   select coalesce(max(version),0) into previous_version from public.context_owner_rules cr where cr.workspace_id=w and cr.context=factual_action.context;
   if (body->>'expected_owner_rule_version')::bigint is distinct from previous_version then raise sqlstate 'PT409' using message='Context owner configuration changed'; end if;
   due:=(body->>'owner_rule_review_due')::date;
   if body->>'assigned_user_id' is not null and (due is null or due<=current_date or due>current_date+90) then raise sqlstate 'PT422' using message='Owner rule needs review within 90 days'; end if;
   insert into public.context_owner_rules(workspace_id,context,version,assigned_user_id,owner_role,active,review_due,actor_id,reason) values(w,context,previous_version+1,(body->>'assigned_user_id')::uuid,body->>'owner_role',body->>'assigned_user_id' is not null,due,a,body->>'reason') returning * into rule;
   perform private.audit(w,c.id,a,r,'context_owner_rule_configured',null,to_jsonb(rule),body->>'reason');
  end if;
  if action='assign' then
   select coalesce(max(version),0)+1 into next_version from public.assignments where workspace_id=w and case_id=c.id;
   insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason) values(w,c.id,next_version,(body->>'assigned_user_id')::uuid,body->>'owner_role',a,r,body->>'reason') returning id into milestone_id;
   if body->>'assigned_user_id' is not null then insert into public.notifications(workspace_id,case_id,assignment_id,event_key) values(w,c.id,milestone_id,'assignment'); end if;
  end if;
 elsif action in ('record_investigation','record_correction','complete_work') then
  if c.status<>'in_progress' or c.work_started_at is null then raise sqlstate 'PT409' using message='Started investigation required'; end if;
  perform private.factual_record_complete(body);
  if action='complete_work' then
   if coalesce(body->>'action_kind','') not in ('corrective_work','no_change') then raise sqlstate 'PT422' using message='Explicit corrective-work or no-change completion required'; end if;
   if body->>'action_kind'='corrective_work' and not exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='correction' and m.human_confirmed and m.details->'target_change_authority'='true'::jsonb and exists(select 1 from public.milestone_proof mp where mp.workspace_id=w and mp.milestone_id=m.id)) then raise sqlstate 'PT422' using message='Corrective completion requires saved authority-backed corrective work and proof'; end if;
   if body->>'action_kind'='no_change' and exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='correction') then raise sqlstate 'PT422' using message='No-change completion conflicts with recorded corrective work'; end if;
  end if;
  if action='record_correction' then
   body:=body||jsonb_build_object('action_kind','corrective_work');
   if body->'target_change_authority' is distinct from 'true'::jsonb then raise sqlstate 'PT422' using message='Actual corrective work requires human target-change authority'; end if;
   perform private.nonempty(body->>'target_system','target_system'); perform private.nonempty(body->>'target_object','target_object'); perform private.action_time(body->>'occurred_at');
  end if;
  perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
  insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at) values(w,c.id,at_id,c.work_cycle,case action when 'record_correction' then 'correction' when 'complete_work' then 'work_completion' else 'investigation' end,body||jsonb_build_object('provenance','human_investigation'),a,r,true,case when action='record_correction' then private.action_time(body->>'occurred_at') else now() end) returning id into milestone_id;
  insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
  if action='complete_work' then update public.cases set status='complete' where id=c.id; end if;
 elsif action='record_reprocessing' then
  if c.status<>'complete' or body->'human_confirmed' is distinct from 'true'::jsonb or coalesce(body->>'result',case when body->>'successful'='true' then 'successful' end) is distinct from 'successful' then raise sqlstate 'PT422' using message='Completed human work and successful reprocessing evidence required'; end if;
  perform private.nonempty(body->>'target_document_reference','target_document_reference'); perform private.action_time(body->>'processing_at');
  if (body->>'processing_order')::bigint is null or (body->>'processing_order')::bigint<=0 then raise sqlstate 'PT422' using message='Explicit successful attempt chronology required'; end if;
  select * into old_attempt from public.attempts where id=at_id;
  if old_attempt.processing_order is not null and (body->>'processing_order')::bigint<=old_attempt.processing_order or old_attempt.processing_at is not null and (body->>'processing_at')::timestamptz<=old_attempt.processing_at then raise sqlstate 'PT422' using message='Successful attempt must be later than known current attempt'; end if;
  if not c.attempt_order_known and body->'chronology_confirmed' is distinct from 'true'::jsonb then raise sqlstate 'PT422' using message='Human chronology confirmation required for provisional original'; end if;
  insert into public.attempts(workspace_id,case_id,attempt_key,processing_at,processing_order,result,target_document_reference) values(w,c.id,private.nonempty(body->>'attempt_key','attempt_key'),(body->>'processing_at')::timestamptz,(body->>'processing_order')::bigint,'successful',body->>'target_document_reference') returning id into at_id;
  perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',coalesce(body->>'proof_reuse_reason','Human confirms saved evidence describes this successful attempt'));
  insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at) values(w,c.id,at_id,c.work_cycle,'reprocessing',body||jsonb_build_object('provenance','human_observation'),a,r,true,private.action_time(body->>'processing_at')) returning id into milestone_id;
  insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
  update public.cases set status='document_reprocessed',current_attempt_id=at_id,attempt_order_known=true,input_revision=input_revision+1,analysis_status='needs_refresh',unreviewed_new_failure=false where id=c.id;
 elsif action='record_validation' then
  if c.status<>'document_reprocessed' or body->'human_confirmed' is distinct from 'true'::jsonb or jsonb_typeof(body->'checks') is distinct from 'array' or coalesce(body->>'status','') not in ('passed','failed') then raise sqlstate 'PT422' using message='Reprocessed case and human comparisons required'; end if;
  perform private.nonempty(body->>'findings','findings'); perform private.action_time(body->>'occurred_at');
  if jsonb_typeof(body->'gaps') is distinct from 'array' then raise sqlstate 'PT422' using message='Explicit validation gaps required'; end if;
  select count(distinct x->>'dimension') into count_checks from jsonb_array_elements(body->'checks') x where x->>'dimension' in ('amount_currency','company','accounts','source_target_reference');
  if body->>'status'='passed' and (count_checks<>4 or jsonb_array_length(body->'checks')<>4 or exists(select 1 from jsonb_array_elements(body->'checks') x where coalesce(x->>'result','') not in ('passed','not_applicable') or nullif(btrim(x->>'expected'),'') is null or nullif(btrim(x->>'observed'),'') is null or x->>'result'='passed' and x->>'expected' is distinct from x->>'observed' or x->>'result'='not_applicable' and nullif(btrim(x->>'reason'),'') is null)) then raise sqlstate 'PT422' using message='Four explicit expected versus observed checks required'; end if;
  if body->>'status'='failed' and not exists(select 1 from jsonb_array_elements(body->'checks') x where x->>'result'='failed' and nullif(btrim(x->>'reason'),'') is not null) then raise sqlstate 'PT422' using message='Failed comparison needs discrepancy evidence'; end if;
  perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
  insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at) values(w,c.id,at_id,c.work_cycle,'validation',body||jsonb_build_object('provenance','human_comparison'),a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
  insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
  update public.attempts set validation_status=body->>'status' where id=at_id;
 elsif action='finish_resolution' then
  if c.status<>'document_reprocessed' or not c.attempt_order_known or c.unreviewed_new_failure or not exists(select 1 from public.attempts ap where ap.id=at_id and ap.result='successful' and ap.validation_status='passed') then raise sqlstate 'PT422' using message='Current successful attempt and passed human validation required'; end if;
  perform private.factual_record_complete(body); perform private.action_time(body->>'occurred_at');
  if coalesce(body->>'action_kind','') not in ('corrective_work','no_change') or body->>'action_kind' is distinct from (select m.details->>'action_kind' from public.milestones m where m.workspace_id=w and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='work_completion' order by m.recorded_at desc,m.id desc limit 1) then raise sqlstate 'PT422' using message='Resolution action kind must match completed human work'; end if;
  if not exists(select 1 from public.milestones where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle and kind='work_completion') or not exists(select 1 from public.milestones where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle and attempt_id=at_id and kind='validation') then raise sqlstate 'PT422' using message='Completed human work and current validation records required'; end if;
  perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
  select coalesce(max(version),0)+1 into next_version from public.resolution_records where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle;
  insert into public.resolution_records(workspace_id,case_id,attempt_id,work_cycle,version,record,resolver_id,resolved_at) values(w,c.id,at_id,c.work_cycle,next_version,body||jsonb_build_object('workflow_version','log-only-v1','provenance','human_resolution','cause_confirmed',false),a,private.action_time(body->>'occurred_at'));
 elsif action in ('priority','due_date','retry_notification','reopen','block') then
  -- These existing guarded commands contain no factual inference. Their own receipt
  -- remains keyed to the unchanged command and retains the same actor/version fence.
  return private.case_action_base(p);
 else raise sqlstate 'PT422' using message='Unsupported factual case action'; end if;
 update public.cases set version=version+1 where id=c.id returning * into c;
 perform private.audit(w,c.id,a,r,'case_'||action,before,to_jsonb(c),coalesce(body->>'reason',body->>'findings'));
 result:=jsonb_build_object('case',to_jsonb(c),'action',action,'attempt_id',at_id,'owner_rule',case when rule.id is not null then to_jsonb(rule)||jsonb_build_object('category','factual_context') else null end);
 insert into private.action_receipts values(w,a,key,digest,result);
 return result;
end $$;

alter table public.analysis_runs add column excluded_case_ids jsonb not null default '[]' check(jsonb_typeof(excluded_case_ids)='array');
alter table public.analysis_runs add column evaluation_configuration jsonb not null default '{}' check(jsonb_typeof(evaluation_configuration)='object');
alter function private.queue_evaluations(jsonb) rename to queue_evaluations_legacy;
create function private.queue_evaluations(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
<<factual_evals>>
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); batch public.evaluation_batches; c public.cases; original public.analysis_runs; item text; i integer; repeats integer:=(p->>'repeats')::integer; ids jsonb:='[]'; sn jsonb; run_id uuid; model_config jsonb; count_cases integer;
begin
 perform private.require_actor(w,a,'process_owner');
 if jsonb_typeof(p->'case_ids') is distinct from 'array' then raise sqlstate 'PT422' using message='Saved evaluation cases required'; end if;
 if not exists(select 1 from public.cases where workspace_id=w and workflow_version='log-only-v1' and id in(select value::uuid from jsonb_array_elements_text(p->'case_ids'))) then return private.queue_evaluations_legacy(p); end if;
 count_cases:=jsonb_array_length(p->'case_ids');
 if count_cases not between 1 and 30 or repeats is null or repeats not between 1 and 3 or count_cases<>(select count(distinct value) from jsonb_array_elements_text(p->'case_ids')) or jsonb_typeof(p->'configuration'->'models') is distinct from 'object' or coalesce(p->'configuration'->>'reasoning_effort','') not in ('low','medium','high') or exists(select 1 from unnest(array['agent1','agent2','agent3']) stage where not exists(select 1 from private.model_prices mp where mp.model_id=p->'configuration'->'models'->>stage and mp.model_id<>'fake' and mp.verified_at<=clock_timestamp() and mp.expires_at>clock_timestamp())) then raise sqlstate 'PT422' using message='Bounded evaluation cases, verified models and effort required'; end if;
 perform private.nonempty(p->>'reason','reason');
 insert into public.evaluation_batches(workspace_id,actor_id,reason,configuration) values(w,a,p->>'reason',p->'configuration') returning * into batch;
 model_config:=p->'configuration'->'models'||jsonb_build_object('reasoning_effort',p->'configuration'->>'reasoning_effort');
 for item in select jsonb_array_elements_text(p->'case_ids') loop
  select * into c from public.cases where workspace_id=w and id=item::uuid for update;
  if not found or c.linked_case_id is not null or c.current_attempt_id is null or c.workflow_version<>'log-only-v1' then raise sqlstate 'PT422' using message='Select factual cases in a separate evaluation batch'; end if;
  select * into original from public.analysis_runs where workspace_id=w and case_id=c.id and attempt_id=c.current_attempt_id and input_revision=c.input_revision and not evaluation_only and workflow_version='log-only-v1' order by created_at desc,id desc limit 1;
  if not found then raise sqlstate 'PT422' using message='Current saved factual snapshot required'; end if;
  for i in 0..repeats-1 loop
   run_id:=gen_random_uuid(); sn:=jsonb_set(jsonb_set(original.snapshot,'{binding,run_id}',to_jsonb(run_id::text)),'{binding,model_configuration}',model_config);
   insert into public.analysis_runs(id,workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by,evaluation_only,evaluation_batch_id,evaluation_repeat,workflow_version,schema_version,prompt_versions,model_configuration,source_manifest_sha256,excluded_case_ids,evaluation_configuration)
   values(run_id,w,c.id,c.current_attempt_id,encode(pg_catalog.sha256(convert_to(sn::text,'UTF8')),'hex'),sn,c.version,c.input_revision,a,true,batch.id,i,'log-only-v1',original.schema_version,original.prompt_versions,model_config,original.source_manifest_sha256,p->'case_ids',p->'configuration');
   insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot) select w,factual_evals.run_id,evidence_id,source_snapshot from public.run_sources rs where rs.run_id=original.id;
   insert into public.jobs(workspace_id,run_id) values(w,run_id); ids:=ids||jsonb_build_array(run_id);
  end loop;
 end loop;
 perform private.audit(w,null,a,'process_owner','evaluation_batch_queued',null,jsonb_build_object('batch_id',batch.id,'runs',ids),p->>'reason');
 return jsonb_build_object('batch',to_jsonb(batch),'run_ids',ids,'paid_dispatch_enabled',false);
end $$;

create or replace function private.claim_job(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare slot private.worker_slot; job public.jobs; run public.analysis_runs; token uuid:=gen_random_uuid(); t timestamptz:=clock_timestamp();
begin
 perform private.nonempty(p->>'worker_id','worker_id');
 select * into slot from private.worker_slot where singleton=1 for update;
 if slot.lease_until>t then return jsonb_build_object('claimed',false); end if;
 if slot.job_id is not null then
  update public.stage_calls set state='usage_unknown' where run_id=(select run_id from public.jobs where id=slot.job_id) and state='in_flight';
  update public.jobs set state='queued',lease_token=null,lease_until=null,worker_id=null where id=slot.job_id and state='running';
 end if;
 select j.* into job from public.jobs j join public.analysis_runs ar on ar.id=j.run_id where j.state='queued' and j.available_at<=t and (p->>'run_id' is null or j.run_id=(p->>'run_id')::uuid) and (ar.workflow_version<>'log-only-v1' or p->'log_only_enabled'='true'::jsonb) order by j.available_at,j.id for update of j skip locked limit 1;
 if not found then update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1; return jsonb_build_object('claimed',false); end if;
 update public.jobs set state='running',lease_token=token,lease_until=t+interval '90 seconds',worker_id=p->>'worker_id',claimed_at=t where id=job.id returning * into job;
 update private.worker_slot set job_id=job.id,lease_token=token,lease_until=job.lease_until where singleton=1;
 update public.analysis_runs set state='running' where id=job.run_id returning * into run;
 update public.cases set analysis_status='running' where id=run.case_id and requested_run_id=run.id and not run.evaluation_only;
 return jsonb_build_object('claimed',true,'job',to_jsonb(job),'run',to_jsonb(run));
end $$;

create table private.read_credentials (
 id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.workspaces(id), label text not null check(length(btrim(label)) between 1 and 100),
 token_sha256 text not null unique check(token_sha256 ~ '^[a-f0-9]{64}$'), scopes text[] not null check(cardinality(scopes)>0 and scopes <@ array['cases:read','evidence:read']::text[] and array_position(scopes,null) is null),
 created_by uuid not null references auth.users(id),created_at timestamptz not null default now(),expires_at timestamptz not null,revoked_at timestamptz,revoked_by uuid references auth.users(id)
);
create table private.read_snapshots (
 id uuid primary key default gen_random_uuid(),credential_id uuid not null references private.read_credentials(id),workspace_id uuid not null references public.workspaces(id),items jsonb not null,filters jsonb not null,page_size integer not null check(page_size between 1 and 100),created_at timestamptz not null default now(),expires_at timestamptz not null default now()+interval '10 minutes'
);
create table private.machine_read_audit (
 id uuid primary key default gen_random_uuid(),credential_id uuid references private.read_credentials(id),workspace_id uuid,resource text not null,resource_id text,case_version bigint,outcome text not null,read_at timestamptz not null default now()
);
revoke all on private.read_credentials,private.read_snapshots,private.machine_read_audit from public,anon,authenticated,service_role;

create function private.create_read_credential(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); cred private.read_credentials; expiry timestamptz:=(p->>'expires_at')::timestamptz;
begin
 perform private.require_actor(w,a,'process_owner');
 if expiry is null or expiry<=clock_timestamp() or expiry>clock_timestamp()+interval '90 days' or jsonb_typeof(p->'scopes') is distinct from 'array' then raise sqlstate 'PT422' using message='Explicit read scopes and expiry within 90 days required'; end if;
 insert into private.read_credentials(workspace_id,label,token_sha256,scopes,created_by,expires_at) values(w,p->>'label',p->>'token_sha256',array(select jsonb_array_elements_text(p->'scopes')),a,expiry) returning * into cred;
 perform private.audit(w,null,a,'process_owner','read_credential_created',null,to_jsonb(cred)-'token_sha256',null);
 return to_jsonb(cred)-'token_sha256';
end $$;
create function private.revoke_read_credential(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); cred private.read_credentials;
begin
 perform private.require_actor(w,a,'process_owner');
 update private.read_credentials set revoked_at=coalesce(revoked_at,clock_timestamp()),revoked_by=coalesce(revoked_by,a) where workspace_id=w and id=(p->>'credential_id')::uuid returning * into cred;
 if not found then raise sqlstate 'PT404' using message='Read credential not found'; end if;
 perform private.audit(w,null,a,'process_owner','read_credential_revoked',null,jsonb_build_object('credential_id',cred.id),null);
 return to_jsonb(cred)-'token_sha256';
end $$;

-- Match the portal's derived resolution state; the operational status intentionally
-- remains document_reprocessed while the human resolution record is reviewed.
create function private.case_resolved(c public.cases) returns boolean language sql stable security definer set search_path='' as $$
 select coalesce(c.status='document_reprocessed' and c.attempt_order_known and not c.unreviewed_new_failure
  and exists(select 1 from public.attempts a where a.workspace_id=c.workspace_id and a.case_id=c.id and a.id=c.current_attempt_id and a.result='successful' and a.validation_status='passed')
  and exists(select 1 from public.resolution_records r where r.workspace_id=c.workspace_id and r.case_id=c.id and r.attempt_id=c.current_attempt_id and r.work_cycle=c.work_cycle)
  and (c.workflow_version='log-only-v1' or (
   exists(select 1 from public.milestones m where m.workspace_id=c.workspace_id and m.case_id=c.id and m.attempt_id=c.current_attempt_id and m.work_cycle=c.work_cycle and m.kind='reprocessing')
   and (select m.details->>'status' from public.milestones m where m.workspace_id=c.workspace_id and m.case_id=c.id and m.attempt_id=c.current_attempt_id and m.work_cycle=c.work_cycle and m.kind='validation' order by m.recorded_at desc,m.id desc limit 1)='passed'
   and exists(select 1 from public.milestones m where m.workspace_id=c.workspace_id and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='correction'
    and m.id=(select latest.id from public.milestones latest where latest.workspace_id=c.workspace_id and latest.case_id=c.id and latest.work_cycle=c.work_cycle and latest.kind='correction' order by latest.recorded_at desc,latest.id desc limit 1)
    and exists(select 1 from public.milestone_proof mp where mp.workspace_id=c.workspace_id and mp.milestone_id=m.id)
    and not exists(select 1 from public.milestone_proof mp where mp.workspace_id=c.workspace_id and mp.milestone_id=m.id and not exists(select 1 from public.proof_applicability pa where pa.workspace_id=c.workspace_id and pa.case_id=c.id and pa.attempt_id=c.current_attempt_id and pa.work_cycle=c.work_cycle and pa.evidence_id=mp.evidence_id)))
  )),false);
$$;
create function private.machine_case(c public.cases) returns jsonb language sql security definer set search_path='' as $$
 select to_jsonb(c)||jsonb_build_object('resolved',private.case_resolved(c),'factual_result',private.filter_factual_history(c.factual_result,c.workspace_id,null),'owner_user_id',(select assigned_user_id from public.assignments where workspace_id=c.workspace_id and case_id=c.id order by version desc limit 1));
$$;
create function private.machine_read(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
<<machine_request>>
declare cred private.read_credentials; w uuid:=(p->>'workspace_id')::uuid; resource text:=p->>'resource'; c public.cases; ev public.evidence_versions; sn private.read_snapshots; count_rows integer; output jsonb; items jsonb; offset_n integer:=coalesce((p->>'offset')::integer,0); limit_n integer:=coalesce((p->>'limit')::integer,25); needed text; filters jsonb:=jsonb_strip_nulls(jsonb_build_object('status',p->>'status','workflow_version',p->>'workflow_version'));
begin
 select * into cred from private.read_credentials where token_sha256=p->>'token_sha256' for share;
 if not found or cred.workspace_id is distinct from w or cred.revoked_at is not null or cred.expires_at<=clock_timestamp() or not exists(select 1 from public.workspace_memberships m where m.workspace_id=w and m.user_id=cred.created_by and 'process_owner'=any(m.roles)) then
  -- Return a denial so the minimal audit row survives the transaction; the HTTP
  -- service translates this to 401/403 without exposing credential existence.
  insert into private.machine_read_audit(credential_id,workspace_id,resource,outcome) values(cred.id,w,coalesce(resource,'unknown'),'denied'); return jsonb_build_object('error','access_denied');
 end if;
 needed:=case when resource='source' then 'evidence:read' else 'cases:read' end;
 if not needed=any(cred.scopes) then insert into private.machine_read_audit(credential_id,workspace_id,resource,outcome) values(cred.id,w,coalesce(resource,'unknown'),'denied'); return jsonb_build_object('error','access_denied'); end if;
 if resource not in ('cases','case','source','activity','records') or offset_n<0 or offset_n>100000 or limit_n not between 1 and 100 then insert into private.machine_read_audit(credential_id,workspace_id,resource,outcome) values(cred.id,w,coalesce(resource,'unknown'),'invalid_input'); return jsonb_build_object('error','invalid_input'); end if;
 if resource='cases' then
  if p->>'snapshot_id' is null then
   select count(*) into count_rows from public.cases cs where cs.workspace_id=w and (p->>'status' is null or cs.status=p->>'status') and (p->>'workflow_version' is null or cs.workflow_version=p->>'workflow_version');
   if count_rows>1000 then insert into private.machine_read_audit(credential_id,workspace_id,resource,outcome) values(cred.id,w,resource,'invalid_input'); return jsonb_build_object('error','invalid_input','reason','narrow_filters'); end if;
   select coalesce(jsonb_agg(private.machine_case(cs) order by cs.updated_at desc,cs.id),'[]') into items from public.cases cs where cs.workspace_id=w and (p->>'status' is null or cs.status=p->>'status') and (p->>'workflow_version' is null or cs.workflow_version=p->>'workflow_version');
   insert into private.read_snapshots(credential_id,workspace_id,items,filters,page_size) values(cred.id,w,items,filters,limit_n) returning * into sn;
  else
   select * into sn from private.read_snapshots where id=(p->>'snapshot_id')::uuid and workspace_id=w and credential_id=cred.id and expires_at>clock_timestamp() and read_snapshots.filters=machine_request.filters and page_size=limit_n;
   if not found then insert into private.machine_read_audit(credential_id,workspace_id,resource,outcome) values(cred.id,w,resource,'snapshot_changed'); return jsonb_build_object('error','snapshot_changed'); end if;
  end if;
  select coalesce(jsonb_agg(x.value||jsonb_build_object('factual_result',private.filter_factual_history(x.value->'factual_result',w,null)) order by x.ordinality),'[]') into items from jsonb_array_elements(sn.items) with ordinality x where x.ordinality>offset_n and x.ordinality<=offset_n+limit_n;
  output:=jsonb_build_object('items',items,'total',jsonb_array_length(sn.items),'snapshot_id',sn.id,'expires_at',sn.expires_at);
 else
  select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid;
  if not found then insert into private.machine_read_audit(credential_id,workspace_id,resource,resource_id,outcome) values(cred.id,w,resource,p->>'case_id','not_found'); return jsonb_build_object('error','not_found'); end if;
  if p->>'case_version' is not null and (p->>'case_version')::bigint<>c.version then insert into private.machine_read_audit(credential_id,workspace_id,resource,resource_id,case_version,outcome) values(cred.id,w,resource,c.id::text,c.version,'snapshot_changed'); return jsonb_build_object('error','snapshot_changed'); end if;
  if resource='case' then
   select coalesce(jsonb_agg(to_jsonb(e) order by e.stored_at,e.id),'[]') into items from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.kind='original_log';
   output:=jsonb_build_object('case',private.machine_case(c),'evidence',case when 'evidence:read'=any(cred.scopes) then items else '[]'::jsonb end,'attempts',(select coalesce(jsonb_agg(to_jsonb(at_row) order by at_row.received_at,at_row.id),'[]') from public.attempts at_row where at_row.workspace_id=w and at_row.case_id=c.id),'latest_run',(select (to_jsonb(ar)-'snapshot')||jsonb_build_object('output',private.filter_factual_history(ar.output,w,null)) from public.analysis_runs ar where ar.workspace_id=w and ar.id=c.requested_run_id),'published_run',(select (to_jsonb(ar)-'snapshot')||jsonb_build_object('output',private.filter_factual_history(ar.output,w,null)) from public.analysis_runs ar where ar.workspace_id=w and ar.id=c.published_run_id));
  elsif resource='source' then
   select * into ev from public.evidence_versions e where e.workspace_id=w and e.case_id=c.id and e.source_id=p->>'source_id' and e.source_version=p->>'source_version' and e.kind='original_log';
   if not found then insert into private.machine_read_audit(credential_id,workspace_id,resource,resource_id,case_version,outcome) values(cred.id,w,resource,c.id::text,c.version,'not_found'); return jsonb_build_object('error','not_found'); end if;
   output:=jsonb_build_object('case_version',c.version,'evidence',to_jsonb(ev));
  elsif resource='records' then
   select coalesce(jsonb_agg(rec order by rec->>'recorded_at',rec->>'id'),'[]') into items from (
    select jsonb_build_object('id',m.id,'kind',m.kind,'actor_id',m.actor_id,'recorded_at',m.recorded_at,'payload',m.details) rec from public.milestones m where m.workspace_id=w and m.case_id=c.id
    union all select jsonb_build_object('id',rv.id,'kind','review_'||rv.review_kind,'actor_id',rv.actor_id,'recorded_at',rv.reviewed_at,'payload',jsonb_build_object('decision',rv.decision,'reason',rv.reason,'findings',rv.findings)) from public.case_reviews rv where rv.workspace_id=w and rv.case_id=c.id
    union all select jsonb_build_object('id',rr.id,'kind','resolution','actor_id',rr.resolver_id,'recorded_at',rr.resolved_at,'payload',rr.record) from public.resolution_records rr where rr.workspace_id=w and rr.case_id=c.id
   ) all_records;
   count_rows:=jsonb_array_length(items);
   select coalesce(jsonb_agg(x.value order by x.ordinality),'[]') into items from jsonb_array_elements(items) with ordinality x where x.ordinality>offset_n and x.ordinality<=offset_n+limit_n;
   output:=jsonb_build_object('case_version',c.version,'items',items,'total',count_rows);
  else
   select count(*) into count_rows from public.activity ac where ac.workspace_id=w and ac.case_id=c.id and ac.acting_role<>'worker';
   select coalesce(jsonb_agg(to_jsonb(ac) order by ac.created_at,ac.id),'[]') into items from(select * from public.activity ac where ac.workspace_id=w and ac.case_id=c.id and ac.acting_role<>'worker' order by ac.created_at,ac.id limit limit_n offset offset_n) ac;
   output:=jsonb_build_object('case_version',c.version,'items',items,'total',count_rows);
  end if;
 end if;
 insert into private.machine_read_audit(credential_id,workspace_id,resource,resource_id,case_version,outcome) values(cred.id,w,resource,p->>'case_id',c.version,'allowed');
 return output;
end $$;

-- Renamed implementations are reachable only through guarded dispatchers. Explicit
-- wrapper recreation avoids retaining a legacy function reference after renaming.
do $$ declare n text; service_names text[]:=array['commit_intake','save_stage','complete_run','claim_job','machine_read']; shared_names text[]:=array['load_history_evidence']; user_names text[]:=array['case_action','queue_evaluations','create_read_credential','revoke_read_credential']; begin
 foreach n in array service_names||shared_names||user_names loop
  execute format('create or replace function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',n,n);
  execute format('revoke all on function public.cfin_%I(jsonb) from public,anon,authenticated,service_role',n);
  execute format('revoke all on function private.%I(jsonb) from public,anon,authenticated,service_role',n);
  if n=any(service_names||shared_names) then execute format('grant execute on function public.cfin_%I(jsonb),private.%I(jsonb) to service_role',n,n); end if;
  if n=any(user_names||shared_names) then execute format('grant execute on function public.cfin_%I(jsonb),private.%I(jsonb) to authenticated',n,n); end if;
 end loop;
 foreach n in array array['commit_intake_legacy','save_stage_legacy','complete_run_legacy','case_action_legacy','queue_evaluations_legacy'] loop execute format('revoke all on function private.%I(jsonb) from public,anon,authenticated,service_role',n); end loop;
end $$;
revoke all on function private.enqueue_legacy(uuid,uuid,uuid),private.enqueue(uuid,uuid,uuid),private.filter_factual_history(jsonb,uuid,uuid,boolean),private.machine_case(public.cases),private.case_resolved(public.cases),private.factual_record_complete(jsonb) from public,anon,authenticated,service_role;
create or replace function private.case_page(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; page integer:=coalesce((p->>'page')::integer,1); size integer:=coalesce((p->>'page_size')::integer,25); rows jsonb; total integer;
begin
 if not private.is_member(w) then raise insufficient_privilege using message='Workspace membership required'; end if;
 if page<1 or size<1 or size>100 then raise sqlstate 'PT422' using message='Invalid page'; end if;
 select count(*) into total from public.cases c where workspace_id=w and linked_case_id is null
  and (coalesce(p->>'category','')='' or (c.workflow_version='legacy-v1' and category=p->>'category')) and (coalesce(p->>'priority','')='' or priority=p->>'priority')
  and (coalesce(p->>'status','')='' or status=p->>'status') and (coalesce(p->>'diagnosis_status','')='' or (c.workflow_version='legacy-v1' and diagnosis_status=p->>'diagnosis_status'))
  and (coalesce(p->>'affected_object','')='' or (c.workflow_version='legacy-v1' and affected_object=p->>'affected_object'))
  and (coalesce(p->>'workflow_version','')='' or c.workflow_version=p->>'workflow_version')
  and (coalesce(p->>'analysis_status','')='' or c.analysis_status=p->>'analysis_status')
  and (coalesce(p->>'factual_review_status','')='' or c.workflow_version='log-only-v1' and c.factual_review_status=p->>'factual_review_status')
  and (coalesce(p->>'q','')='' or position(lower(p->>'q') in lower(title||' '||description||' '||coalesce(document_number,'')))>0);
 select coalesce(jsonb_agg(to_jsonb(r)),'[]') into rows from (
  select * from public.cases c where workspace_id=w and linked_case_id is null
  and (coalesce(p->>'category','')='' or (c.workflow_version='legacy-v1' and category=p->>'category')) and (coalesce(p->>'priority','')='' or priority=p->>'priority')
  and (coalesce(p->>'status','')='' or status=p->>'status') and (coalesce(p->>'diagnosis_status','')='' or (c.workflow_version='legacy-v1' and diagnosis_status=p->>'diagnosis_status'))
  and (coalesce(p->>'affected_object','')='' or (c.workflow_version='legacy-v1' and affected_object=p->>'affected_object'))
  and (coalesce(p->>'workflow_version','')='' or c.workflow_version=p->>'workflow_version')
  and (coalesce(p->>'analysis_status','')='' or c.analysis_status=p->>'analysis_status')
  and (coalesce(p->>'factual_review_status','')='' or c.workflow_version='log-only-v1' and c.factual_review_status=p->>'factual_review_status')
  and (coalesce(p->>'q','')='' or position(lower(p->>'q') in lower(title||' '||description||' '||coalesce(document_number,'')))>0)
  order by case priority when 'P3' then 0 when 'P2' then 1 else 2 end,created_at desc,id offset (page-1)*size limit size
 ) r;
 return jsonb_build_object('items',rows,'total',total,'page',page,'page_size',size);
end $$;
create or replace function private.create_overview_snapshot(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid();
  f jsonb:=coalesce(p->'filters','{}'::jsonb); v_fingerprint text;
  s public.overview_snapshots; dimension text;
begin
  if a is null or not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=a)
    then raise sqlstate 'PT403' using message='Workspace membership required'; end if;
  if jsonb_typeof(f)<>'object' or exists(select 1 from jsonb_object_keys(f) k where k not in (
    'category','priority','affected_object','diagnosis_status','status','company_code','target_system','workflow_version','analysis_status','factual_review_status'))
    then raise sqlstate 'PT422' using message='Invalid overview filters'; end if;
  perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||f::text,0));
  v_fingerprint:=private.overview_fingerprint(w);
  if p->'refresh' is distinct from 'true'::jsonb then
    select * into s from public.overview_snapshots where workspace_id=w and actor_id=a
      and filters=f and overview_snapshots.fingerprint=v_fingerprint and expires_at>clock_timestamp()
      order by as_of desc limit 1;
    if found then return private.overview_payload(s); end if;
  end if;
  insert into public.overview_snapshots(workspace_id,actor_id,filters,fingerprint,metrics)
    values(w,a,f,v_fingerprint,'{}') returning * into s;
  insert into public.overview_members(workspace_id,snapshot_id,case_id,case_version,identity_known,attempt_count,case_data)
  select w,s.id,c.id,c.version,
    c.source_system is not null and c.source_client is not null and c.source_company_code is not null
      and c.fiscal_year is not null and c.document_number is not null and c.target_system is not null
      and c.target_client is not null and c.interface is not null,
    (select count(*) from public.attempts t where t.workspace_id=w and t.case_id=c.id),
    jsonb_build_object('id',c.id,'title',c.title,'priority',c.priority,'status',c.status,
      'category',case when c.workflow_version='legacy-v1' then c.category end,'affected_object',case when c.workflow_version='legacy-v1' then c.affected_object end,'diagnosis_status',case when c.workflow_version='legacy-v1' then c.diagnosis_status end,
      'workflow_version',c.workflow_version,'analysis_status',c.analysis_status,'factual_review_status',case when c.workflow_version='log-only-v1' then c.factual_review_status end,
      'version',c.version,'company_code',c.business_context->>'company_code','target_system',c.target_system)
  from public.cases c where c.workspace_id=w and c.linked_case_id is null
    and (not (f ? 'category') or c.workflow_version='legacy-v1' and c.category=f->>'category')
    and (not (f ? 'priority') or c.priority=f->>'priority')
    and (not (f ? 'affected_object') or c.workflow_version='legacy-v1' and c.affected_object=f->>'affected_object')
    and (not (f ? 'diagnosis_status') or c.workflow_version='legacy-v1' and c.diagnosis_status=f->>'diagnosis_status')
    and (not (f ? 'workflow_version') or c.workflow_version=f->>'workflow_version')
    and (not (f ? 'analysis_status') or c.analysis_status=f->>'analysis_status')
    and (not (f ? 'factual_review_status') or c.workflow_version='log-only-v1' and c.factual_review_status=f->>'factual_review_status')
    and (not (f ? 'status') or c.status=f->>'status')
    and (not (f ? 'company_code') or c.business_context->>'company_code'=f->>'company_code')
    and (not (f ? 'target_system') or c.target_system=f->>'target_system')
    and not (
      c.status='document_reprocessed' and c.attempt_order_known and not c.unreviewed_new_failure
      and exists(select 1 from public.attempts t where t.workspace_id=w and t.case_id=c.id
        and t.id=c.current_attempt_id and t.result='successful' and t.validation_status='passed')
      and exists(select 1 from public.resolution_records r where r.workspace_id=w and r.case_id=c.id
        and r.attempt_id=c.current_attempt_id and r.work_cycle=c.work_cycle)
      and exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c.id
        and m.attempt_id=c.current_attempt_id and m.work_cycle=c.work_cycle and m.kind='reprocessing')
      and exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c.id
        and m.work_cycle=c.work_cycle and m.kind=case when c.workflow_version='log-only-v1' then 'work_completion' else 'correction' end
        and m.id=(select id from public.milestones where workspace_id=w and case_id=c.id
          and work_cycle=c.work_cycle and kind=case when c.workflow_version='log-only-v1' then 'work_completion' else 'correction' end order by recorded_at desc,id desc limit 1)
        and exists(select 1 from public.milestone_proof p where p.workspace_id=w and p.milestone_id=m.id)
        and not exists(select 1 from public.milestone_proof p where p.workspace_id=w and p.milestone_id=m.id
          and not exists(select 1 from public.proof_applicability a where a.workspace_id=w
            and a.case_id=c.id and a.attempt_id=c.current_attempt_id and a.work_cycle=c.work_cycle and a.evidence_id=p.evidence_id)))
      and exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c.id
        and m.attempt_id=c.current_attempt_id and m.work_cycle=c.work_cycle and m.kind='validation'
        and m.details->>'status'='passed')
    );
  update public.overview_snapshots set metrics=jsonb_build_object(
    'unresolved_known_cases',(select count(*) from public.overview_members where snapshot_id=s.id and identity_known),
    'provisional_cases',(select count(*) from public.overview_members where snapshot_id=s.id and not identity_known),
    'attempts',(select coalesce(sum(attempt_count),0) from public.overview_members where snapshot_id=s.id),
    'units',jsonb_build_object('unresolved_known_cases','distinct cases','provisional_cases','distinct cases','attempts','attempts'),
    'scope','Unresolved cases in the selected workspace and filters; linked aliases excluded')
    where id=s.id returning * into s;
  foreach dimension in array array['category','priority','affected_object','diagnosis_status','status','company_code','target_system','workflow_version','analysis_status','factual_review_status'] loop
    insert into public.overview_groups(workspace_id,snapshot_id,dimension,value,count,case_ids)
    select w,s.id,dimension,coalesce(case_data->>dimension,'unknown'),count(*),jsonb_agg(case_id order by case_id)
      from public.overview_members where snapshot_id=s.id
       and (identity_known or dimension in ('workflow_version','analysis_status','factual_review_status'))
       and (dimension not in ('category','affected_object','diagnosis_status') or case_data->>'workflow_version'='legacy-v1')
       and (dimension<>'factual_review_status' or case_data->>'workflow_version'='log-only-v1')
      group by coalesce(case_data->>dimension,'unknown');
  end loop;
  insert into public.overview_groups(workspace_id,snapshot_id,dimension,value,count,case_ids)
    select w,s.id,'identity','provisional',count(*),jsonb_agg(case_id order by case_id)
    from public.overview_members where snapshot_id=s.id and not identity_known having count(*)>0;
  return private.overview_payload(s);
end $$;


-- Pin historical originals to their reviewed version instead of following a mutable
-- current case pointer. Existing knowledge resolves to an immutable run no later
-- than its resolution record; absent originals remain unavailable, never fabricated.
alter table public.knowledge_versions add column original_sources jsonb not null default '[]';
create function private.knowledge_originals(w uuid,c_id uuid,resolution_id uuid) returns jsonb language sql stable security definer set search_path='' as $$
 select coalesce(jsonb_agg(to_jsonb(e) order by e.stored_at,e.id),'[]') from public.evidence_versions e where e.workspace_id=w and e.case_id=c_id and e.kind='original_log' and e.id in(
  select rs.evidence_id from public.run_sources rs where rs.workspace_id=w and rs.run_id=(select ar.id from public.analysis_runs ar where ar.workspace_id=w and ar.case_id=c_id and not ar.evaluation_only and ar.created_at<=(select rr.resolved_at from public.resolution_records rr where rr.workspace_id=w and rr.id=resolution_id) order by ar.created_at desc,ar.id desc limit 1)
 );
$$;
update public.knowledge_versions k set original_sources=private.knowledge_originals(k.workspace_id,k.case_id,k.resolution_id);
create function private.pin_knowledge_originals() returns trigger language plpgsql security definer set search_path='' as $$
begin
 if tg_op='INSERT' then new.original_sources:=private.knowledge_originals(new.workspace_id,new.case_id,new.resolution_id);
 elsif new.original_sources is distinct from old.original_sources then raise sqlstate 'PT409' using message='Reviewed historical original versions are immutable'; end if;
 return new;
end $$;
create trigger pin_knowledge_originals before insert or update on public.knowledge_versions for each row execute function private.pin_knowledge_originals();
revoke all on function private.knowledge_originals(uuid,uuid,uuid),private.pin_knowledge_originals() from public,anon,authenticated,service_role;
create or replace function private.register_run_history(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=private.knowledge_member(p); w uuid:=(p->>'workspace_id')::uuid;
  run public.analysis_runs; source jsonb; k public.knowledge_versions;
begin
  select * into run from public.analysis_runs where workspace_id=w and id=(p->>'run_id')::uuid and requested_by=a for update;
  if not found or run.state<>'running' then raise sqlstate 'PT409' using message='Current running analysis required'; end if;
  if jsonb_typeof(p->'sources') is distinct from 'array' or jsonb_array_length(p->'sources')>5
    then raise sqlstate 'PT422' using message='Bounded exact history sources required'; end if;
  for source in select * from jsonb_array_elements(p->'sources') loop
    select * into k from public.knowledge_versions where workspace_id=w and id=(source->>'id')::uuid and version=(source->>'version')::integer for share;
    if not found or k.case_id=run.case_id or run.excluded_case_ids ? k.case_id::text or k.reuse_state<>'approved' then raise sqlstate 'PT409' using message='History eligibility changed'; end if;
    insert into public.run_knowledge_sources(workspace_id,run_id,knowledge_id,knowledge_version,knowledge_revision,source_snapshot)
      values(w,run.id,k.id,k.version,k.revision,to_jsonb(k)-'concept_vector'-'search_document') on conflict do nothing;
  end loop;
  return jsonb_build_object('registered',true);
end $$;


-- Factual knowledge publication is a human approval of validated findings and
-- applicability. It does not assert or require a diagnosed cause. The existing
-- exact-version model-evaluation policy remains mandatory.
create function private.validate_factual_resolution(w uuid,c_id uuid,resolution_id uuid) returns void language plpgsql security definer set search_path='' as $$
declare c public.cases; r public.resolution_records; proof jsonb;
begin
 select * into c from public.cases where workspace_id=w and id=c_id for share;
 select * into r from public.resolution_records where workspace_id=w and case_id=c_id and id=resolution_id;
 if c.id is null or r.id is null or c.workflow_version<>'log-only-v1' or r.record->>'workflow_version' is distinct from 'log-only-v1'
  or c.current_attempt_id<>r.attempt_id or c.work_cycle<>r.work_cycle or not c.attempt_order_known or c.unreviewed_new_failure or c.status<>'document_reprocessed'
  or r.version<>(select max(rr.version) from public.resolution_records rr where rr.workspace_id=w and rr.case_id=c_id and rr.work_cycle=c.work_cycle)
  or not exists(select 1 from public.attempts at_row where at_row.workspace_id=w and at_row.id=r.attempt_id and at_row.result='successful' and at_row.validation_status='passed')
  or not exists(select 1 from public.case_reviews rv join public.analysis_runs ar on ar.id=rv.run_id and ar.workspace_id=rv.workspace_id where rv.workspace_id=w and rv.case_id=c_id and rv.review_kind='factual' and rv.run_id=c.published_run_id and rv.decision in ('Accepted','Corrected') and not ar.evaluation_only and ar.workflow_version='log-only-v1')
  or not exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c_id and m.work_cycle=c.work_cycle and m.kind='work_completion' and exists(select 1 from public.milestone_proof mp where mp.workspace_id=w and mp.milestone_id=m.id))
  or not exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c_id and m.attempt_id=r.attempt_id and m.work_cycle=c.work_cycle and m.kind='reprocessing' and exists(select 1 from public.milestone_proof mp where mp.workspace_id=w and mp.milestone_id=m.id))
  or not exists(select 1 from public.milestones m where m.workspace_id=w and m.case_id=c_id and m.attempt_id=r.attempt_id and m.work_cycle=c.work_cycle and m.kind='validation' and m.details->>'status'='passed' and exists(select 1 from public.milestone_proof mp where mp.workspace_id=w and mp.milestone_id=m.id))
 then raise sqlstate 'PT422' using message='Current factual review, completed human work and proven successful validated resolution required'; end if;
 perform private.factual_record_complete(r.record);
 if coalesce(r.record->>'action_kind','') not in ('corrective_work','no_change') or r.record->>'action_kind' is distinct from (select m.details->>'action_kind' from public.milestones m where m.workspace_id=w and m.case_id=c_id and m.work_cycle=c.work_cycle and m.kind='work_completion' order by m.recorded_at desc,m.id desc limit 1) then raise sqlstate 'PT422' using message='Knowledge resolution action kind must match completed human work'; end if;
 for proof in select value from jsonb_array_elements(r.record->'proof_ids') loop
  if not exists(select 1 from public.evidence_versions e join public.proof_applicability pa on pa.workspace_id=e.workspace_id and pa.evidence_id=e.id where e.workspace_id=w and e.case_id=c_id and e.id=(proof#>>'{}')::uuid and e.kind='proof' and pa.case_id=c_id and pa.attempt_id=r.attempt_id and pa.work_cycle=r.work_cycle) then raise sqlstate 'PT422' using message='Exact saved resolution proof and applicability required'; end if;
 end loop;
end $$;

alter function private.knowledge_draft(jsonb) rename to knowledge_draft_legacy;
create function private.knowledge_draft(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid; r public.resolution_records; c public.cases; k public.knowledge_versions; old public.knowledge_versions; n integer; proof jsonb; scope jsonb:=p->'scope';
begin
 perform private.require_actor(w,a,'process_owner');
 select * into r from public.resolution_records where workspace_id=w and id=(p->>'resolution_id')::uuid for update;
 if not found then raise sqlstate 'PT404' using message='Resolution record not found'; end if;
 if r.record->>'workflow_version' is distinct from 'log-only-v1' then return private.knowledge_draft_legacy(p); end if;
 perform private.validate_factual_resolution(w,r.case_id,r.id);
 perform private.nonempty(p->>'lesson','lesson'); perform private.nonempty(p->>'reason','reason');
 if length(p->>'lesson') not between 10 and 4000 or jsonb_typeof(scope) is distinct from 'object' or scope->>'workflow_version' is distinct from 'log-only-v1'
  or exists(select 1 from jsonb_object_keys(scope) key where key not in ('workflow_version','applicability','reuse_limitations','context'))
  or (scope ? 'context' and (jsonb_typeof(scope->'context') is distinct from 'object' or exists(select 1 from jsonb_each(scope->'context') x where x.key not in ('source_system','target_system','interface','company_code') or jsonb_typeof(x.value)<>'string' or length(btrim(x.value#>>'{}'))=0)))
 then raise sqlstate 'PT422' using message='Explicit factual applicability scope required'; end if;
 perform private.nonempty(scope->>'applicability','applicability'); perform private.nonempty(scope->>'reuse_limitations','reuse_limitations');
 if p->>'supersedes_id' is not null then
  select * into old from public.knowledge_versions where workspace_id=w and id=(p->>'supersedes_id')::uuid for update;
  if not found or old.case_id<>r.case_id then raise sqlstate 'PT422' using message='Replacement must version the same case knowledge'; end if;
  if p->'materially_disputed'='true'::jsonb and old.reuse_state='approved' then perform private.withdraw_knowledge(w,old.id,a,p->>'reason'); end if;
 end if;
 select coalesce(jsonb_agg(jsonb_build_object('evidence_id',e.id,'source_id',e.source_id,'source_version',e.source_version,'sha256',e.sha256) order by e.id),'[]') into proof from public.evidence_versions e where e.workspace_id=w and e.case_id=r.case_id and e.kind='proof' and r.record->'proof_ids' ? e.id::text;
 select coalesce(max(version),0)+1 into n from public.knowledge_versions where workspace_id=w and case_id=r.case_id;
 insert into public.knowledge_versions(workspace_id,case_id,resolution_id,version,supersedes_id,lesson,scope,evidence,resolution_snapshot,concept_vector,proposed_by)
 values(w,r.case_id,r.id,n,(p->>'supersedes_id')::uuid,p->>'lesson',scope,proof,r.record,(p->>'concept_vector')::extensions.vector(64),a) returning * into k;
 if jsonb_array_length(k.original_sources)=0 then raise sqlstate 'PT422' using message='Pinned historical original evidence required'; end if;
 perform private.audit(w,r.case_id,a,'process_owner','knowledge_draft',null,to_jsonb(k)-'concept_vector'-'search_document',p->>'reason');
 return to_jsonb(k)-'concept_vector'-'search_document';
end $$;

alter function private.knowledge_review(jsonb) rename to knowledge_review_legacy;
create function private.knowledge_review(p jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid; k public.knowledge_versions; policy public.knowledge_publication_policies; evaluation public.knowledge_evaluation_attestations; decision text:=p->>'decision';
begin
 perform private.require_actor(w,a,'process_owner'); perform private.nonempty(p->>'reason','reason');
 select * into k from public.knowledge_versions where workspace_id=w and id=(p->>'knowledge_id')::uuid for update;
 if not found then raise sqlstate 'PT404' using message='Knowledge not found'; end if;
 if k.resolution_snapshot->>'workflow_version' is distinct from 'log-only-v1' then return private.knowledge_review_legacy(p); end if;
 if k.revision is distinct from (p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Knowledge version changed'; end if;
 if decision not in ('approved','rejected','withdrawn') then raise sqlstate 'PT422' using message='Invalid review decision'; end if;
 if decision='withdrawn' then
  if k.reuse_state<>'approved' then raise sqlstate 'PT422' using message='Only approved versions can be withdrawn'; end if;
  perform private.withdraw_knowledge(w,k.id,a,p->>'reason');
 else
  if k.reuse_state<>'pending_review' then raise sqlstate 'PT422' using message='Create a replacement draft for another review'; end if;
  if decision='approved' then
   perform private.validate_factual_resolution(w,k.case_id,k.resolution_id);
   if k.scope->>'workflow_version' is distinct from 'log-only-v1' or jsonb_array_length(k.evidence)=0 or jsonb_array_length(k.original_sources)=0 or exists(select 1 from jsonb_array_elements(k.evidence) proof where not exists(select 1 from public.evidence_versions e where e.workspace_id=w and e.case_id=k.case_id and e.id=(proof->>'evidence_id')::uuid and e.sha256=proof->>'sha256' and e.source_version=proof->>'source_version' and e.kind='proof')) then raise sqlstate 'PT422' using message='Exact factual applicability and saved evidence required'; end if;
   select * into policy from public.knowledge_publication_policies where workspace_id=w;
   if not found then raise sqlstate 'PT422' using message='Define publication evaluation criteria first'; end if;
   select * into evaluation from public.knowledge_evaluation_attestations where workspace_id=w and id=(p->>'evaluation_evidence_id')::uuid and knowledge_id=k.id and knowledge_revision=k.revision and policy_revision=policy.revision and human_reviewed;
   if not found or evaluation.cases<policy.minimum_cases or evaluation.critical_failures>policy.maximum_critical_failures or evaluation.passed_cases::numeric/evaluation.cases<policy.minimum_pass_rate then raise sqlstate 'PT422' using message='Reviewed model-evaluation prerequisites not met'; end if;
  end if;
  update public.knowledge_versions set reuse_state=decision,revision=revision+1,reviewed_by=a,reviewed_at=clock_timestamp(),review_reason=p->>'reason' where id=k.id;
  perform private.audit(w,k.case_id,a,'process_owner','knowledge_review',to_jsonb(k)-'concept_vector'-'search_document',jsonb_build_object('knowledge_id',k.id,'decision',decision,'workflow_version','log-only-v1'),p->>'reason');
 end if;
 select * into k from public.knowledge_versions where id=k.id;
 return to_jsonb(k)-'concept_vector'-'search_document';
end $$;

do $$ declare n text; begin
 foreach n in array array['knowledge_draft','knowledge_review'] loop
  execute format('create or replace function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',n,n);
  execute format('revoke all on function public.cfin_%I(jsonb),private.%I(jsonb) from public,anon,authenticated,service_role',n,n);
  execute format('grant execute on function public.cfin_%I(jsonb),private.%I(jsonb) to authenticated',n,n);
  execute format('revoke all on function private.%I(jsonb) from public,anon,authenticated,service_role',n||'_legacy');
 end loop;
end $$;
revoke all on function private.validate_factual_resolution(uuid,uuid,uuid) from public,anon,authenticated,service_role;
create or replace function private.search_history(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=private.knowledge_member(p); w uuid:=(p->>'workspace_id')::uuid;
  q text:=coalesce(p->>'query',''); f jsonb:=coalesce(p->'filters','{}');
  context jsonb:=coalesce(p->'context','{}'); size integer:=coalesce((p->>'limit')::integer,10);
  v extensions.vector(64):=(p->>'query_vector')::extensions.vector(64); items jsonb;
begin
  if length(q)>1000 or size not between 1 and 25 or jsonb_typeof(f)<>'object' or jsonb_typeof(context)<>'object'
    or exists(select 1 from jsonb_object_keys(f) key where key not in ('category','affected_object','company_code','target_system'))
    then raise sqlstate 'PT422' using message='Invalid bounded history search'; end if;
  select coalesce(jsonb_agg(row_data order by score desc,id),'[]') into items from (
    select k.id,
      ts_rank_cd(k.search_document,websearch_to_tsquery('english'::regconfig,q))*2
        + case when v is null then 0 else greatest(0,1-(k.concept_vector OPERATOR(extensions.<=>) v)) end
        + (select count(*)*0.25 from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key)=x.value) as score,
      jsonb_build_object('id',k.id,'case_id',k.case_id,'version',k.version,'revision',k.revision,
        'reuse_state',k.reuse_state,'lesson',k.lesson,'scope',k.scope,'evidence',k.evidence,
        'resolution_record',k.resolution_snapshot,'reviewed_by',k.reviewed_by,'reviewed_at',k.reviewed_at,
        'synthetic',not exists(select 1 from jsonb_array_elements(k.original_sources) original where original->'synthetic'='false'::jsonb),'matching_facts',coalesce((select jsonb_agg(x.key||': '||x.value) from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key)=x.value),'[]'),
        'differing_facts',coalesce((select jsonb_agg(x.key||': current '||x.value||'; historical '||coalesce(coalesce(k.scope->'context'->>x.key,k.scope->>x.key),'unknown')) from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key) is distinct from x.value),'[]'),
        'score',ts_rank_cd(k.search_document,websearch_to_tsquery('english'::regconfig,q))*2
          + case when v is null then 0 else greatest(0,1-(k.concept_vector OPERATOR(extensions.<=>) v)) end
          + (select count(*)*0.25 from jsonb_each_text(context) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key)=x.value)) as row_data
    from public.knowledge_versions k where k.workspace_id=w and k.reuse_state='approved'
      and not exists(select 1 from jsonb_each_text(f) x where coalesce(k.scope->'context'->>x.key,k.scope->>x.key) is distinct from x.value)
      and (q='' or k.search_document @@ websearch_to_tsquery('english'::regconfig,q)
        or (v is not null and (k.concept_vector OPERATOR(extensions.<=>) v)<0.9))
    order by score desc,k.id limit size
  ) matches;
  return jsonb_build_object('items',items,'retrieval_method','hybrid_lexical_context',
    'vector_method','local_concept_hashing_not_a_learned_embedding','publication_policy',private.publication_policy_payload(w));
end $$;

commit;
