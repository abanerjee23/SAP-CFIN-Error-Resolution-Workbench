-- Audited MD-01 workflow. Backend-only storage attestation is required.
-- SQL parsing is not a substitute for exercising these grants on Supabase.
begin;

alter table public.cases add column input_revision bigint not null default 1 check (input_revision > 0);
alter table public.cases add column requested_run_id uuid;
alter table public.cases add column published_run_id uuid;
alter table public.cases add column work_started_at timestamptz;
alter table public.analysis_runs add column input_revision bigint not null default 1;
alter table public.cases add foreign key (workspace_id,id,requested_run_id)
  references public.analysis_runs(workspace_id,case_id,id);
alter table public.cases add foreign key (workspace_id,id,published_run_id)
  references public.analysis_runs(workspace_id,case_id,id);
alter table public.evidence_versions add column work_cycle integer check (work_cycle > 0);
alter table public.jobs add column worker_id text;
alter table public.jobs add column claimed_at timestamptz;

create table public.reference_reviews (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  evidence_id uuid not null,
  version bigint not null check (version > 0),
  decision text not null check (decision in ('pending_review','approved','rejected','withdrawn')),
  reference_kind text not null check (reference_kind in ('mapping','guidance','policy','owner_directory')),
  scope jsonb not null,
  actor_id uuid not null references auth.users(id),
  acting_role text not null,
  reason text not null check (length(btrim(reason)) > 0),
  reviewed_at timestamptz not null default now(),
  foreign key (workspace_id,evidence_id) references public.evidence_versions(workspace_id,id),
  unique (workspace_id,evidence_id,version)
);

create table public.run_sources (
  workspace_id uuid not null,
  run_id uuid not null,
  evidence_id uuid not null,
  source_snapshot jsonb not null,
  foreign key (workspace_id,run_id) references public.analysis_runs(workspace_id,id),
  foreign key (workspace_id,evidence_id) references public.evidence_versions(workspace_id,id),
  primary key (workspace_id,run_id,evidence_id)
);

create table public.run_results (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  run_id uuid not null,
  job_id uuid not null references public.jobs(id),
  submitted_lease_token uuid not null,
  output jsonb,
  succeeded boolean not null,
  promoted boolean not null default false,
  received_at timestamptz not null default now(),
  foreign key (workspace_id,run_id) references public.analysis_runs(workspace_id,id),
  unique (job_id,submitted_lease_token)
);

create table public.proof_applicability (
  workspace_id uuid not null,
  case_id uuid not null,
  attempt_id uuid not null,
  work_cycle integer not null check (work_cycle > 0),
  evidence_id uuid not null,
  actor_id uuid not null references auth.users(id),
  reason text not null check (length(btrim(reason)) > 0),
  attested_at timestamptz not null default now(),
  foreign key (workspace_id,case_id,attempt_id) references public.attempts(workspace_id,case_id,id),
  foreign key (workspace_id,case_id,evidence_id) references public.evidence_versions(workspace_id,case_id,id),
  primary key (workspace_id,attempt_id,work_cycle,evidence_id)
);

create table private.action_receipts (
  workspace_id uuid not null references public.workspaces(id),
  actor_id uuid not null references auth.users(id),
  request_key text not null,
  payload_hash text not null,
  response jsonb not null,
  primary key (workspace_id,actor_id,request_key)
);
create table private.worker_slot (
  singleton integer primary key check (singleton = 1),
  job_id uuid references public.jobs(id),
  lease_token uuid,
  lease_until timestamptz
);
insert into private.worker_slot(singleton) values (1);
create table private.model_prices (
  model_id text primary key,
  version text not null,
  input_usd_per_million numeric(12,6) not null check (input_usd_per_million >= 0),
  output_usd_per_million numeric(12,6) not null check (output_usd_per_million >= 0),
  verified_at timestamptz not null,
  expires_at timestamptz not null,
  source text not null,
  check (expires_at > verified_at)
);
-- This is a deterministic local adapter, not a zero-price paid model.
insert into private.model_prices values ('fake','fixture-v1',0,0,now(),now()+interval '10 years','Deterministic software adapter; no provider call');
insert into private.model_prices values ('gpt-6-luna','openai-standard-2026-10-01',0.125,0.50,'2026-10-01T00:00:00Z','2026-11-01T00:00:00Z','https://developers.openai.com/api/docs/models/gpt-6-luna; standard default US endpoint; input includes cache-write maximum');
insert into private.model_prices values ('gpt-6.1-sol','openai-standard-2026-10-01',2.50,10.00,'2026-10-01T00:00:00Z','2026-11-01T00:00:00Z','https://developers.openai.com/api/docs/models/gpt-6.1-sol; standard default US endpoint; input includes cache-write maximum');
insert into private.model_prices values ('gpt-6-sol','openai-standard-2026-10-01',2.50,10.00,'2026-10-01T00:00:00Z','2026-11-01T00:00:00Z','https://developers.openai.com/api/docs/models/gpt-6-sol; standard default US endpoint; input includes cache-write maximum');
create table private.budget_months (
  workspace_id uuid not null references public.workspaces(id),
  month_start date not null,
  allowance_usd numeric(12,6) not null default 10 check (allowance_usd > 0 and allowance_usd <= 10),
  primary key (workspace_id,month_start)
);
create table public.stage_calls (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  run_id uuid not null,
  stage text not null check (stage in ('agent_1','agent_2','agent_3')),
  invocation integer not null check (invocation in (0,1)),
  model_id text not null,
  price_version text not null,
  price_input numeric(12,6) not null,
  price_output numeric(12,6) not null,
  month_start date not null,
  max_input_tokens integer not null check (max_input_tokens > 0 and max_input_tokens <= 131072),
  max_output_tokens integer not null check (max_output_tokens > 0 and max_output_tokens <= 8192),
  reserved_usd numeric(12,6) not null check (reserved_usd >= 0),
  actual_usd numeric(12,6) check (actual_usd >= 0),
  state text not null default 'reserved' check (state in ('reserved','in_flight','succeeded','failed','usage_unknown','not_sent')),
  usage jsonb,
  output jsonb,
  provider_request_id text,
  created_at timestamptz not null default now(),
  reconciled_at timestamptz,
  foreign key (workspace_id,run_id) references public.analysis_runs(workspace_id,id),
  unique (workspace_id,run_id,stage,invocation)
);

do $$ declare t text; begin
  foreach t in array array['reference_reviews','run_sources','run_results','proof_applicability','stage_calls'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
    execute format('create policy member_read on public.%I for select to authenticated using (private.is_member(workspace_id))',t);
  end loop;
end $$;
revoke all on all tables in schema private from public,anon,authenticated;

create function private.preserve_source()
returns trigger language plpgsql set search_path='' as $$
begin
  raise sqlstate 'PT409' using message='Saved evidence and snapshot sources are immutable';
end $$;
create trigger immutable_evidence before update or delete on public.evidence_versions
  for each row execute function private.preserve_source();
create trigger immutable_run_sources before update or delete on public.run_sources
  for each row execute function private.preserve_source();
create function private.preserve_run_input()
returns trigger language plpgsql set search_path='' as $$
begin
  if new.workspace_id is distinct from old.workspace_id or new.case_id is distinct from old.case_id
    or new.attempt_id is distinct from old.attempt_id or new.snapshot is distinct from old.snapshot
    or new.snapshot_hash is distinct from old.snapshot_hash or new.input_revision is distinct from old.input_revision
    or new.case_version is distinct from old.case_version or new.requested_by is distinct from old.requested_by then
    raise sqlstate 'PT409' using message='Run input snapshot is immutable';
  end if;
  return new;
end $$;
create trigger immutable_run_input before update on public.analysis_runs
  for each row execute function private.preserve_run_input();

create function private.require_actor(w uuid,a uuid,r text)
returns void language plpgsql security definer set search_path='' as $$
begin
  if a is null or r is null or not exists (
    select 1 from public.workspace_memberships where workspace_id=w and user_id=a and r=any(roles)
  ) then raise insufficient_privilege using message='Workspace role required'; end if;
end $$;

create function private.nonempty(v text,field_name text)
returns text language plpgsql immutable set search_path='' as $$
begin
  if v is null or length(btrim(v))=0 then raise sqlstate 'PT422' using message='Required field missing',detail=field_name; end if;
  return v;
end $$;

create function private.business_due(t timestamptz,n integer)
returns timestamptz language plpgsql immutable set search_path='' as $$
declare local_t timestamp := t at time zone 'Europe/London'; counted integer := 0;
begin
  while counted<n loop
    local_t:=local_t+interval '1 day';
    if extract(isodow from local_t)<6 then counted:=counted+1; end if;
  end loop;
  return local_t at time zone 'Europe/London';
end $$;

create function private.action_time(value text)
returns timestamptz language plpgsql set search_path='' as $$
declare result timestamptz;
begin
  if value is null or value !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then
    raise sqlstate 'PT422' using message='Timezone-aware human action time required';
  end if;
  result:=value::timestamptz;
  if result>clock_timestamp() then raise sqlstate 'PT422' using message='Human action time cannot be in the future'; end if;
  return result;
end $$;

create function private.audit(w uuid,c uuid,a uuid,r text,event text,old_data jsonb,new_data jsonb,reason text)
returns void language sql security definer set search_path='' as $$
  insert into public.activity(workspace_id,case_id,actor_id,acting_role,event_type,old_value,new_value,reason)
  values(w,c,a,r,event,old_data,new_data,reason);
$$;

create function private.register_evidence(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid := (p->>'workspace_id')::uuid; a uuid := (p->>'actor_id')::uuid;
  r text := p->>'acting_role'; c uuid := (p->>'case_id')::uuid; at_id uuid := (p->>'attempt_id')::uuid;
  s jsonb := p->'storage'; e public.evidence_versions; stored_size bigint;
begin
  perform private.require_actor(w,a,r);
  if coalesce(p->>'kind','') not in ('original_log','reference','guidance','proof') then raise sqlstate 'PT422' using message='Invalid evidence kind'; end if;
  if jsonb_typeof(s) is distinct from 'object' or coalesce(s->>'sha256','') !~ '^[a-f0-9]{64}$' then raise sqlstate 'PT422' using message='Verified storage metadata required'; end if;
  select (metadata->>'size')::bigint into stored_size from storage.objects
    where bucket_id='evidence' and name=s->>'object_path';
  if not found or stored_size is null or stored_size is distinct from (s->>'byte_size')::bigint then
    raise sqlstate 'PT422' using message='Stored object verification required';
  end if;
  if p->>'kind'='proof' and (c is null or at_id is null or (p->>'work_cycle')::integer is null) then
    raise sqlstate 'PT422' using message='Proof needs case, attempt and work cycle';
  end if;
  insert into public.evidence_versions(workspace_id,source_id,source_version,case_id,attempt_id,kind,filename,
    object_path,sha256,byte_size,content_type,provenance,uploader_id,observed_at,work_cycle)
  values(w,private.nonempty(s->>'source_id','source_id'),private.nonempty(s->>'source_version','source_version'),c,at_id,
    p->>'kind',private.nonempty(s->>'filename','filename'),s->>'object_path',s->>'sha256',stored_size,
    s->>'content_type',s->'provenance',a,(s->>'observed_at')::timestamptz,(p->>'work_cycle')::integer)
  on conflict (workspace_id,source_id,source_version) do nothing returning * into e;
  if not found then
    select * into e from public.evidence_versions where workspace_id=w and source_id=s->>'source_id' and source_version=s->>'source_version';
    if e.sha256<>s->>'sha256' or e.case_id is distinct from c or e.attempt_id is distinct from at_id or e.kind<>p->>'kind' then
      raise sqlstate 'PT409' using message='Evidence version conflict';
    end if;
    return to_jsonb(e);
  end if;
  perform private.audit(w,c,a,r,'evidence_registered',null,jsonb_build_object('evidence_id',e.id,'kind',e.kind),null);
  return to_jsonb(e);
end $$;

create function private.enqueue(w uuid,c_id uuid,a uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.cases; at_row public.attempts; sn jsonb; hash text; run public.analysis_runs; n integer; original_id uuid; saved_manifest jsonb; source_list jsonb;
  filenames text[]:=array['original-log.txt','manifest.json','source-posting.json','mapping-reference.json','target-master-lookup.json','target-master-query-audit.json','missing-gl-master-playbook.json','owner-directory.json','source-catalogue.json'];
begin
  select * into c from public.cases where workspace_id=w and id=c_id for update;
  select * into at_row from public.attempts where workspace_id=w and case_id=c_id and id=c.current_attempt_id;
  if c.current_attempt_id is null or not c.attempt_order_known then return jsonb_build_object('queued',false,'reason','identity_or_attempt_order_required'); end if;
  if c.source_system is null or c.source_client is null or c.source_company_code is null or c.fiscal_year is null or c.document_number is null or c.target_system is null or c.target_client is null or c.interface is null then
    return jsonb_build_object('queued',false,'reason','document_identity_required');
  end if;
  select original_evidence_id,manifest into original_id,saved_manifest from public.intakes
    where workspace_id=w and case_id=c_id and attempt_id=c.current_attempt_id order by received_at desc,id desc limit 1;
  select count(*) into n from public.evidence_versions where workspace_id=w and
    (id=original_id or (case_id is null and kind in ('reference','guidance') and provenance->>'input_filename'=any(filenames)));
  if n<>9 then return jsonb_build_object('queued',false,'reason','nine_saved_MD01_inputs_required'); end if;
  if (select count(distinct coalesce(provenance->>'input_filename',filename)) from public.evidence_versions where workspace_id=w and
    (id=original_id or (case_id is null and kind in ('reference','guidance') and provenance->>'input_filename'=any(filenames))))<>9 then
    raise sqlstate 'PT422' using message='Exactly one saved version of each MD01 input is required';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
      'evidence',to_jsonb(e),'review',(select to_jsonb(rr) from public.reference_reviews rr where rr.workspace_id=w and rr.evidence_id=e.id order by rr.version desc limit 1)) order by e.source_id,e.source_version),'[]'::jsonb)
    into source_list from public.evidence_versions e where e.workspace_id=w and
    (e.id=original_id or (e.case_id is null and e.kind in ('reference','guidance') and e.provenance->>'input_filename'=any(filenames)));
  sn:=jsonb_build_object('case_id',c.id,'attempt_id',c.current_attempt_id,'input_revision',c.input_revision,
    'manifest',saved_manifest,
    'identity',jsonb_build_object('workspace_id',w,'source_system',c.source_system,'source_client',c.source_client,'source_company_code',c.source_company_code,'fiscal_year',c.fiscal_year,'document_number',c.document_number,'target_system',c.target_system,'target_client',c.target_client,'interface',c.interface),
    'business_context',c.business_context,'attempt',to_jsonb(at_row),'sources',source_list);
  hash:=encode(pg_catalog.sha256(convert_to(sn::text,'UTF8')),'hex');
  select * into run from public.analysis_runs where workspace_id=w and case_id=c_id and snapshot_hash=hash and state in ('queued','running');
  if found then return jsonb_build_object('queued',true,'run_id',run.id,'duplicate',true); end if;
  insert into public.analysis_runs(workspace_id,case_id,attempt_id,snapshot_hash,snapshot,case_version,input_revision,requested_by)
    values(w,c_id,c.current_attempt_id,hash,sn,c.version,c.input_revision,a) returning * into run;
  insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot)
    select w,run.id,(source->'evidence'->>'id')::uuid,source from jsonb_array_elements(sn->'sources') source;
  insert into public.jobs(workspace_id,run_id) values(w,run.id);
  update public.cases set requested_run_id=run.id,analysis_status='pending' where id=c_id;
  perform private.audit(w,c_id,a,'system','analysis_queued',null,jsonb_build_object('run_id',run.id),null);
  return jsonb_build_object('queued',true,'run_id',run.id,'snapshot_hash',hash,'duplicate',false);
end $$;

create function private.commit_intake(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid := (p->>'workspace_id')::uuid; a uuid := (p->>'actor_id')::uuid;
  r text := p->>'acting_role'; m jsonb := p->'manifest'; ident jsonb := m->'identity';
  delivery text := private.nonempty(p->>'delivery_key','delivery_key'); payload_hash text;
  c public.cases; attempt public.attempts; old_attempt public.attempts; intake public.intakes; evidence jsonb;
  queue jsonb; provisional boolean; is_new boolean := false; keys text[] := array['source_system','source_client','source_company_code','fiscal_year','document_number','target_system','target_client','interface']; k text;
begin
  perform private.require_actor(w,a,r);
  if (ident->>'workspace_id') is distinct from w::text then raise sqlstate 'PT422' using message='Manifest workspace mismatch'; end if;
  foreach k in array keys loop
    if ident->k is not null and jsonb_typeof(ident->k) not in ('string','null') then raise sqlstate 'PT422' using message='Identifiers must be strings'; end if;
    if jsonb_typeof(ident->k)='string' then perform private.nonempty(ident->>k,k); end if;
  end loop;
  if m->>'content_sha256' is distinct from p->'storage'->>'sha256' or jsonb_typeof(m->'processing_order') not in ('number','null') then raise sqlstate 'PT422' using message='Intake hash or attempt order mismatch'; end if;
  payload_hash:=encode(pg_catalog.sha256(convert_to(jsonb_build_object('manifest',m,'sha256',p->'storage'->>'sha256')::text,'UTF8')),'hex');
  perform pg_advisory_xact_lock(hashtextextended(w::text||':'||delivery,0));
  select * into intake from public.intakes where workspace_id=w and delivery_key=delivery;
  if found then
    if intake.payload_sha256<>payload_hash then raise sqlstate 'PT409' using message='Delivery key content conflict'; end if;
    return jsonb_build_object('intake_id',intake.id,'case_id',intake.case_id,'attempt_id',intake.attempt_id,'duplicate',true);
  end if;
  provisional:=exists(select 1 from unnest(keys) x where ident->>x is null);
  if not provisional then
    perform pg_advisory_xact_lock(hashtextextended(w::text||':'||ident::text,1));
    select * into c from public.cases where workspace_id=w and source_system=ident->>'source_system' and source_client=ident->>'source_client' and source_company_code=ident->>'source_company_code' and fiscal_year=ident->>'fiscal_year' and document_number=ident->>'document_number' and target_system=ident->>'target_system' and target_client=ident->>'target_client' and interface=ident->>'interface' for update;
  end if;
  if c.id is null then
    insert into public.cases(workspace_id,source_system,source_client,source_company_code,fiscal_year,document_number,target_system,target_client,interface,title,description,business_context,due_at,review_flags)
    values(w,ident->>'source_system',ident->>'source_client',ident->>'source_company_code',ident->>'fiscal_year',ident->>'document_number',ident->>'target_system',ident->>'target_client',ident->>'interface',
      'Document exception '||coalesce(ident->>'document_number','identity required'),'Original evidence saved; analysis pending',m->'business_context',private.business_due(now(),2),case when provisional then array['document_identity_required'] else '{}'::text[] end)
    returning * into c; is_new:=true;
  end if;
  select * into attempt from public.attempts where workspace_id=w and case_id=c.id and attempt_key=m->>'attempt_id';
  if not found then
    insert into public.attempts(workspace_id,case_id,attempt_key,processing_at,processing_order,result)
      values(w,c.id,private.nonempty(m->>'attempt_id','attempt_id'),(m->>'processing_at')::timestamptz,(m->>'processing_order')::bigint,'failed') returning * into attempt;
  elsif attempt.processing_at is distinct from (m->>'processing_at')::timestamptz or attempt.processing_order is distinct from (m->>'processing_order')::bigint then
    raise sqlstate 'PT409' using message='Attempt identity content conflict';
  end if;
  evidence:=private.register_evidence(jsonb_build_object('workspace_id',w,'actor_id',a,'acting_role',r,'case_id',c.id,'attempt_id',attempt.id,'kind','original_log','storage',p->'storage'));
  insert into public.intakes(workspace_id,case_id,attempt_id,original_evidence_id,delivery_key,payload_sha256,manifest,supplied_by)
    values(w,c.id,attempt.id,(evidence->>'id')::uuid,delivery,payload_hash,m,a) returning * into intake;
  select * into old_attempt from public.attempts where id=c.current_attempt_id;
  if c.current_attempt_id is null then
    update public.cases set current_attempt_id=attempt.id,attempt_order_known=attempt.processing_order is not null and attempt.processing_at is not null where id=c.id;
  elsif old_attempt.id<>attempt.id then
    if attempt.processing_order is null or old_attempt.processing_order is null or attempt.processing_at is null or old_attempt.processing_at is null or
      (attempt.processing_order=old_attempt.processing_order) or ((attempt.processing_order>old_attempt.processing_order) <> (attempt.processing_at>old_attempt.processing_at)) then
      update public.cases set attempt_order_known=false,input_revision=input_revision+1,analysis_status='needs_refresh',diagnosis_status='needs_review',review_flags=array_append(review_flags,'attempt_order_review_required'),version=version+1 where id=c.id;
    elsif attempt.processing_order>old_attempt.processing_order then
      update public.cases set current_attempt_id=attempt.id,attempt_order_known=true,input_revision=input_revision+1,analysis_status='needs_refresh',diagnosis_status='needs_review',unreviewed_new_failure=true,
        review_flags=array_append(review_flags,'new_failure_review_required'),version=version+1 where id=c.id;
    end if;
  elsif not is_new then
    update public.cases set input_revision=input_revision+1,analysis_status='needs_refresh',diagnosis_status='needs_review',version=version+1 where id=c.id;
  end if;
  perform private.audit(w,c.id,a,r,'intake_saved',null,jsonb_build_object('intake_id',intake.id,'attempt_id',attempt.id),null);
  if is_new then queue:=private.enqueue(w,c.id,a); end if;
  return jsonb_build_object('intake_id',intake.id,'case_id',c.id,'attempt_id',attempt.id,'evidence_id',evidence->>'id','duplicate',false,'analysis',queue);
end $$;

create function private.review_reference(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid := (p->>'workspace_id')::uuid; a uuid := auth.uid(); r text := p->>'acting_role';
  e public.evidence_versions; prior public.reference_reviews; result public.reference_reviews; v bigint; d text := p->>'decision'; expected_kind text;
begin
  perform private.require_actor(w,a,r);
  if r not in ('process_owner','mapping_owner','master_data_owner','finance_owner') then raise insufficient_privilege using message='Reference reviewer role required'; end if;
  select * into e from public.evidence_versions where workspace_id=w and id=(p->>'evidence_id')::uuid for update;
  if not found or e.kind not in ('reference','guidance') then raise sqlstate 'PT404' using message='Reference not found'; end if;
  if e.source_version is distinct from p->>'source_version' then raise sqlstate 'PT409' using message='Exact source version required'; end if;
  expected_kind:=case e.filename when 'mapping-reference.json' then 'mapping' when 'missing-gl-master-playbook.json' then 'guidance' else null end;
  if expected_kind is null or e.provenance->>'reference_kind' is distinct from expected_kind
    or p->>'reference_kind' is distinct from expected_kind
    or jsonb_typeof(e.provenance->'reference_scope') is distinct from 'object'
    or e.provenance->'reference_scope'='{}'::jsonb
    or p->'scope' is distinct from e.provenance->'reference_scope' then
    raise sqlstate 'PT422' using message='Review kind and scope must match the saved verified reference';
  end if;
  if d not in ('approved','rejected','withdrawn') then raise sqlstate 'PT422' using message='Invalid review decision'; end if;
  if p->>'reference_kind'='mapping' and r not in ('mapping_owner','process_owner') then raise insufficient_privilege using message='Mapping owner review required'; end if;
  select * into prior from public.reference_reviews where workspace_id=w and evidence_id=e.id order by version desc limit 1;
  v:=coalesce(prior.version,0);
  if v is distinct from (p->>'expected_review_version')::bigint then raise sqlstate 'PT409' using message='Reference review changed; refresh'; end if;
  if jsonb_typeof(p->'scope') is distinct from 'object' or p->'scope'='{}'::jsonb then raise sqlstate 'PT422' using message='Review scope required'; end if;
  insert into public.reference_reviews(workspace_id,evidence_id,version,decision,reference_kind,scope,actor_id,acting_role,reason)
    values(w,e.id,v+1,d,p->>'reference_kind',p->'scope',a,r,private.nonempty(p->>'reason','reason')) returning * into result;
  perform private.audit(w,null,a,r,'reference_review',to_jsonb(prior),to_jsonb(result),result.reason);
  if d in ('withdrawn','rejected') then
    update public.cases set review_flags=array_append(review_flags,'reference_withdrawn'),diagnosis_status='needs_review',version=version+1
      where workspace_id=w and id in (select run.case_id from public.analysis_runs run join public.run_sources s on s.workspace_id=run.workspace_id and s.run_id=run.id where s.evidence_id=e.id and s.workspace_id=w);
  end if;
  return to_jsonb(result);
end $$;

create function private.enqueue_run(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid := (p->>'workspace_id')::uuid; a uuid := auth.uid(); r text := p->>'acting_role'; c public.cases; assigned uuid;
begin
  perform private.require_actor(w,a,r);
  select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Case not found'; end if;
  if c.version is distinct from (p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Case changed; refresh'; end if;
  select assigned_user_id into assigned from public.assignments where workspace_id=w and case_id=c.id order by version desc limit 1;
  if r<>'process_owner' and assigned is distinct from a then raise insufficient_privilege using message='Assigned owner or process owner required'; end if;
  return private.enqueue(w,c.id,a);
end $$;

create function private.claim_job(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare slot private.worker_slot; job public.jobs; run public.analysis_runs; token uuid:=gen_random_uuid(); t timestamptz:=clock_timestamp();
begin
  perform private.nonempty(p->>'worker_id','worker_id');
  select * into slot from private.worker_slot where singleton=1 for update;
  if slot.lease_until>t then return jsonb_build_object('claimed',false); end if;
  if slot.job_id is not null then
    update public.stage_calls set state='usage_unknown' where run_id=(select run_id from public.jobs where id=slot.job_id) and state='in_flight';
    update public.jobs set state='queued',lease_token=null,lease_until=null,worker_id=null where id=slot.job_id and state='running';
  end if;
  select * into job from public.jobs where state='queued' and available_at<=t order by available_at,id for update skip locked limit 1;
  if not found then update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1; return jsonb_build_object('claimed',false); end if;
  update public.jobs set state='running',lease_token=token,lease_until=t+interval '90 seconds',worker_id=p->>'worker_id',claimed_at=t where id=job.id returning * into job;
  update private.worker_slot set job_id=job.id,lease_token=token,lease_until=job.lease_until where singleton=1;
  update public.analysis_runs set state='running' where id=job.run_id returning * into run;
  update public.cases set analysis_status='running' where id=run.case_id and requested_run_id=run.id;
  return jsonb_build_object('claimed',true,'job',to_jsonb(job),'run',to_jsonb(run));
end $$;

create function private.require_lease(j uuid,token uuid)
returns public.jobs language plpgsql security definer set search_path='' as $$
declare job public.jobs;
begin
  perform 1 from private.worker_slot where singleton=1 for update;
  select * into job from public.jobs where id=j for update;
  if not found or job.state<>'running' or job.lease_token is distinct from token or job.lease_until is null or job.lease_until<=clock_timestamp() then
    raise sqlstate 'PT409' using message='Worker lease expired or replaced';
  end if;
  return job;
end $$;

create function private.heartbeat_job(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; t timestamptz:=clock_timestamp()+interval '90 seconds';
begin
  select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
  update public.jobs set lease_until=t where id=job.id;
  update private.worker_slot set lease_until=t where singleton=1 and job_id=job.id and lease_token=job.lease_token;
  return jsonb_build_object('lease_until',t);
end $$;

create function private.reserve_call(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; price private.model_prices; call_row public.stage_calls; month date:=(date_trunc('month',clock_timestamp() at time zone 'UTC'))::date;
  amount numeric(12,6); used numeric(12,6); run_used numeric(12,6); cap numeric(12,6);
  monthly_cap numeric:=coalesce((p->>'monthly_budget_usd')::numeric,10);
  run_cap numeric:=coalesce((p->>'run_budget_usd')::numeric,1);
begin
  select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
  if monthly_cap<=0 or monthly_cap>10 or run_cap<=0 or run_cap>1 then
    raise sqlstate 'PT422' using message='Invalid configured model budget';
  end if;
  select * into price from private.model_prices where model_id=p->>'model_id' and expires_at>clock_timestamp();
  if not found then raise sqlstate 'PT422' using message='Known current model pricing required'; end if;
  insert into private.budget_months(workspace_id,month_start) values(job.workspace_id,month) on conflict do nothing;
  select allowance_usd into cap from private.budget_months where workspace_id=job.workspace_id and month_start=month for update;
  select * into call_row from public.stage_calls where workspace_id=job.workspace_id and run_id=job.run_id and stage=p->>'stage' and invocation=(p->>'invocation')::integer;
  if found then return jsonb_build_object('call',to_jsonb(call_row),'duplicate',true,'execute',false); end if;
  if (p->>'invocation')::integer=1 and not exists(select 1 from public.stage_calls where run_id=job.run_id and stage=p->>'stage' and invocation=0 and state in ('failed','usage_unknown')) then
    raise sqlstate 'PT422' using message='Retry needs a failed first invocation';
  end if;
  amount:=ceil(((p->>'max_input_tokens')::numeric*price.input_usd_per_million+(p->>'max_output_tokens')::numeric*price.output_usd_per_million)/1000000*1000000)/1000000;
  select coalesce(sum(coalesce(actual_usd,reserved_usd)),0) into used from public.stage_calls where month_start=month and state<>'not_sent';
  select coalesce(sum(coalesce(actual_usd,reserved_usd)),0) into run_used from public.stage_calls where workspace_id=job.workspace_id and run_id=job.run_id and state<>'not_sent';
  if used+amount>least(cap,10,monthly_cap) or run_used+amount>least(1,run_cap) then raise sqlstate 'PT422' using message='Model budget exhausted'; end if;
  insert into public.stage_calls(workspace_id,run_id,stage,invocation,model_id,price_version,price_input,price_output,month_start,max_input_tokens,max_output_tokens,reserved_usd,state)
    values(job.workspace_id,job.run_id,p->>'stage',(p->>'invocation')::integer,price.model_id,price.version,price.input_usd_per_million,price.output_usd_per_million,month,(p->>'max_input_tokens')::integer,(p->>'max_output_tokens')::integer,amount,'in_flight') returning * into call_row;
  return jsonb_build_object('call',to_jsonb(call_row),'duplicate',false,'execute',true);
end $$;

create function private.reconcile_call(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; call_row public.stage_calls; amount numeric(12,6); state_value text:=p->>'state';
begin
  select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
  select * into call_row from public.stage_calls where id=(p->>'call_id')::uuid and workspace_id=job.workspace_id and run_id=job.run_id for update;
  if not found then raise sqlstate 'PT404' using message='Stage call not found'; end if;
  if call_row.state not in ('in_flight','usage_unknown') then return to_jsonb(call_row); end if;
  if state_value not in ('succeeded','failed','usage_unknown','not_sent') then raise sqlstate 'PT422' using message='Invalid usage state'; end if;
  if state_value='usage_unknown' then amount:=null;
  elsif state_value='not_sent' then amount:=0;
  elsif p->'usage'->>'input_tokens' is null or p->'usage'->>'output_tokens' is null then state_value:='usage_unknown'; amount:=null;
  else
    if (p->'usage'->>'input_tokens')::bigint<0 or (p->'usage'->>'output_tokens')::bigint<0 then raise sqlstate 'PT422' using message='Invalid usage'; end if;
    amount:=ceil(((p->'usage'->>'input_tokens')::numeric*call_row.price_input+(p->'usage'->>'output_tokens')::numeric*call_row.price_output)/1000000*1000000)/1000000;
  end if;
  update public.stage_calls set state=state_value,actual_usd=amount,usage=p->'usage',output=p->'output',provider_request_id=p->>'provider_request_id',reconciled_at=clock_timestamp() where id=call_row.id returning * into call_row;
  return to_jsonb(call_row);
end $$;

create function private.complete_run(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare job public.jobs; run public.analysis_runs; c public.cases; is_current boolean; succeeded boolean:=(p->>'succeeded')::boolean; receipt public.run_results;
begin
  -- Keep late output as history before checking whether it can mutate current work.
  perform 1 from private.worker_slot where singleton=1 for update;
  select * into job from public.jobs where id=(p->>'job_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Job not found'; end if;
  select * into receipt from public.run_results where job_id=job.id and submitted_lease_token=(p->>'lease_token')::uuid;
  if found then return jsonb_build_object('run_id',receipt.run_id,'promoted',receipt.promoted,'duplicate',true); end if;
  insert into public.run_results(workspace_id,run_id,job_id,submitted_lease_token,output,succeeded)
    values(job.workspace_id,job.run_id,job.id,(p->>'lease_token')::uuid,p->'output',succeeded) returning * into receipt;
  if job.state<>'running' or job.lease_token is distinct from (p->>'lease_token')::uuid or job.lease_until<=clock_timestamp() then
    return jsonb_build_object('run_id',job.run_id,'promoted',false,'lease_rejected',true,'result_id',receipt.id);
  end if;
  select * into job from private.require_lease((p->>'job_id')::uuid,(p->>'lease_token')::uuid);
  select * into run from public.analysis_runs where id=job.run_id for update;
  select * into c from public.cases where id=run.case_id for update;
  is_current:=coalesce(c.attempt_order_known and c.current_attempt_id=run.attempt_id and c.input_revision=run.input_revision and c.requested_run_id=run.id,false);
  -- Withdrawal during a running model call prevents actionable promotion.
  if exists(select 1 from public.run_sources s join lateral (select decision from public.reference_reviews where workspace_id=s.workspace_id and evidence_id=s.evidence_id order by version desc limit 1) rev on true where s.run_id=run.id and rev.decision in ('withdrawn','rejected') and coalesce(s.source_snapshot->'review'->>'decision','pending_review')<>rev.decision) then
    is_current:=false;
  end if;
  update public.analysis_runs set state=case when not is_current then 'historical' when succeeded then 'succeeded' else 'failed' end,output=p->'output',error_code=p->>'error_code' where id=run.id;
  if is_current then
    update public.cases set analysis_status=case when succeeded then 'available' else 'unavailable' end,
      published_run_id=case when succeeded then run.id else published_run_id end,
      category=case when c.diagnosis_status='human_confirmed' then c.category when succeeded then coalesce(p->'output'->>'category','cause_not_established') else 'cause_not_established' end,
      affected_object=case when c.diagnosis_status='human_confirmed' then c.affected_object when succeeded then coalesce(p->'output'->>'affected_object','unknown') else affected_object end,
      diagnosis_status=case when c.diagnosis_status='human_confirmed' then c.diagnosis_status when succeeded then coalesce(p->'output'->>'diagnosis_status','needs_review') else 'needs_review' end,
      description=case when succeeded then coalesce(p->'output'->>'description',description) else description end,
      version=version+1 where id=c.id;
  end if;
  update public.jobs set state=case when succeeded then 'succeeded' else 'failed' end,lease_until=null,lease_token=null where id=job.id;
  update private.worker_slot set job_id=null,lease_token=null,lease_until=null where singleton=1 and job_id=job.id and lease_token=job.lease_token;
  perform private.audit(c.workspace_id,c.id,null,'worker','analysis_finished',null,jsonb_build_object('run_id',run.id,'promoted',is_current,'succeeded',succeeded),p->>'error_code');
  update public.run_results set promoted=is_current where id=receipt.id;
  return jsonb_build_object('run_id',run.id,'promoted',is_current,'case_version',c.version+case when is_current then 1 else 0 end);
end $$;

create function private.attest_proof(w uuid,c uuid,at_id uuid,cycle integer,a uuid,ids jsonb,reason text)
returns void language plpgsql security definer set search_path='' as $$
declare id_text text; e public.evidence_versions;
begin
  if jsonb_typeof(ids) is distinct from 'array' or jsonb_array_length(ids)=0 then raise sqlstate 'PT422' using message='Saved proof required'; end if;
  for id_text in select jsonb_array_elements_text(ids) loop
    select * into e from public.evidence_versions where workspace_id=w and case_id=c and id=id_text::uuid and kind='proof';
    if not found then raise sqlstate 'PT422' using message='Proof must be a saved attachment for this case'; end if;
    if e.attempt_id is distinct from at_id or e.work_cycle is distinct from cycle then perform private.nonempty(reason,'proof_reuse_reason'); end if;
    insert into public.proof_applicability(workspace_id,case_id,attempt_id,work_cycle,evidence_id,actor_id,reason)
      values(w,c,at_id,cycle,e.id,a,coalesce(nullif(reason,''),'Human attests this proof applies to the current attempt and work cycle')) on conflict do nothing;
  end loop;
end $$;

create function private.validate_case_citations(w uuid,c_id uuid,citations jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare catalogue jsonb; citation jsonb; source jsonb; start_line integer; end_line integer;
begin
  if jsonb_typeof(citations) is distinct from 'array' or jsonb_array_length(citations)=0 then
    raise sqlstate 'PT422' using message='Resolvable cause evidence required';
  end if;
  select run.output->'source_catalogue' into catalogue from public.cases c
    join public.analysis_runs run on run.workspace_id=c.workspace_id and run.id=c.published_run_id
    where c.workspace_id=w and c.id=c_id;
  if jsonb_typeof(catalogue) is distinct from 'array' then
    raise sqlstate 'PT422' using message='Saved analysis source catalogue required';
  end if;
  for citation in select value from jsonb_array_elements(citations) loop
    if jsonb_typeof(citation) is distinct from 'object' then raise sqlstate 'PT422' using message='Invalid citation'; end if;
    select value into source from jsonb_array_elements(catalogue)
      where value->>'source_id'=citation->>'source_id' and value->>'source_version'=citation->>'source_version';
    if not found or source->>'attempt_id' is distinct from citation->>'attempt_id' then
      raise sqlstate 'PT422' using message='Citation source, version or attempt is not in the saved catalogue';
    end if;
    if citation->>'record_id' is not null then
      if source->>'kind'<>'records' or citation->>'line_start' is not null or citation->>'line_end' is not null
        or not (source->'record_ids' ? (citation->>'record_id')) then raise sqlstate 'PT422' using message='Invalid citation record'; end if;
    else
      start_line:=(citation->>'line_start')::integer; end_line:=(citation->>'line_end')::integer;
      if source->>'kind'<>'text' or start_line is null or end_line is null or start_line<1
        or end_line<start_line or end_line>(source->>'line_count')::integer then raise sqlstate 'PT422' using message='Invalid citation line range'; end if;
    end if;
  end loop;
end $$;

create function private.check_milestone_proof()
returns trigger language plpgsql security definer set search_path='' as $$
begin
  if not exists(select 1 from public.milestones m join public.proof_applicability p
    on p.workspace_id=m.workspace_id and p.case_id=m.case_id and p.attempt_id=m.attempt_id and p.work_cycle=m.work_cycle
    where m.workspace_id=new.workspace_id and m.case_id=new.case_id and m.id=new.milestone_id and p.evidence_id=new.evidence_id) then
    raise sqlstate 'PT422' using message='Proof applicability must match milestone attempt and cycle';
  end if;
  return new;
end $$;
create trigger valid_milestone_proof before insert on public.milestone_proof
  for each row execute function private.check_milestone_proof();

create function private.verified_proof(w uuid,c_id uuid,ids jsonb,proof_kind text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.cases; expected_identity jsonb; observation jsonb;
begin
  select * into c from public.cases where workspace_id=w and id=c_id;
  expected_identity:=jsonb_build_object('workspace_id',w::text,'source_system',c.source_system,'source_client',c.source_client,
    'source_company_code',c.source_company_code,'fiscal_year',c.fiscal_year,'document_number',c.document_number,
    'target_system',c.target_system,'target_client',c.target_client,'interface',c.interface);
  if jsonb_typeof(ids) is distinct from 'array' or jsonb_array_length(ids)=0 then raise sqlstate 'PT422' using message='Verified result proof required'; end if;
  select e.provenance->'verified_observation' into observation from public.evidence_versions e
    where e.workspace_id=w and e.case_id=c_id and e.kind='proof' and e.id in (select value::uuid from jsonb_array_elements_text(ids))
      and e.provenance->'verified_observation'->>'kind'=proof_kind
      and e.provenance->'verified_observation'->'synthetic'='true'::jsonb
      and e.provenance->'verified_observation'->>'actual_actor_id'=e.uploader_id::text
      and e.provenance->'verified_observation'->'identity' @> expected_identity
    order by e.stored_at desc,e.id desc limit 1;
  if not found then raise sqlstate 'PT422' using message='Saved server-verified result with matching document identity required'; end if;
  return observation;
end $$;

create function private.case_action(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role'; action text:=case p->>'action' when 'review_diagnosis' then 'review' when 'start_work' then 'start' when 'record_correction' then 'correction' when 'record_reprocessing' then 'reprocessing' when 'record_validation' then 'validation' when 'finish_resolution' then 'resolution' else p->>'action' end;
  c public.cases; old_c jsonb; assigned uuid; body jsonb:=coalesce(p->'data','{}'); key text:=private.nonempty(p->>'request_key','request_key'); hash text;
  receipt private.action_receipts; result jsonb; milestone_id uuid; at_id uuid; attempt public.attempts; next_version integer; passed boolean; dim_count integer; reviewed_run uuid; observation jsonb;
begin
  perform private.require_actor(w,a,r);
  hash:=encode(pg_catalog.sha256(convert_to(p::text,'UTF8')),'hex');
  perform pg_advisory_xact_lock(hashtextextended(w::text||a::text||key,2));
  select * into receipt from private.action_receipts where workspace_id=w and actor_id=a and request_key=key;
  if found then
    if receipt.payload_hash<>hash then raise sqlstate 'PT409' using message='Action key content conflict'; end if;
    return receipt.response;
  end if;
  select * into c from public.cases where workspace_id=w and id=(p->>'case_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Case not found'; end if;
  if c.version is distinct from (p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Case changed; refresh'; end if;
  old_c:=to_jsonb(c); at_id:=c.current_attempt_id;
  select assigned_user_id into assigned from public.assignments where workspace_id=w and case_id=c.id order by version desc limit 1;
  if action in ('assign','priority','reopen') and r<>'process_owner' then raise insufficient_privilege using message='Process owner required'; end if;
  if action='validation' and r not in ('validator','process_owner') then raise insufficient_privilege using message='Validator required'; end if;
  if action not in ('assign','priority','reopen','validation') and r<>'process_owner' and assigned is distinct from a then raise insufficient_privilege using message='Assigned owner required'; end if;
  if action in ('correction','reprocessing','validation','resolution') and body->'human_confirmed' is distinct from 'true'::jsonb then
    raise sqlstate 'PT422' using message='Explicit human proof attestation required';
  end if;
  if action in ('correction','reprocessing','validation','resolution') then perform private.action_time(body->>'occurred_at'); end if;
  if body ? 'cause_confirmed' and jsonb_typeof(body->'cause_confirmed') is distinct from 'boolean' then
    raise sqlstate 'PT422' using message='Cause confirmation must be an explicit boolean';
  end if;
  if action='assign' then
    if body->>'assigned_user_id' is not null and not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=(body->>'assigned_user_id')::uuid and body->>'owner_role'=any(roles)) then raise sqlstate 'PT422' using message='Active owner membership required'; end if;
    select coalesce(max(version),0)+1 into next_version from public.assignments where workspace_id=w and case_id=c.id;
    insert into public.assignments(workspace_id,case_id,version,assigned_user_id,owner_role,actor_id,acting_role,reason)
      values(w,c.id,next_version,(body->>'assigned_user_id')::uuid,body->>'owner_role',a,r,private.nonempty(body->>'reason','reason')) returning id into milestone_id;
    if body->>'assigned_user_id' is not null then insert into public.notifications(workspace_id,assignment_id,event_key) values(w,milestone_id,'assignment'); end if;
  elsif action='review' then
    reviewed_run:=coalesce((body->>'run_id')::uuid,c.published_run_id,c.requested_run_id);
    if reviewed_run is null or not exists(select 1 from public.analysis_runs where workspace_id=w and case_id=c.id and id=reviewed_run and state in ('succeeded','failed') and id in (c.published_run_id,c.requested_run_id)) then
      raise sqlstate 'PT422' using message='Current saved analysis or failure required before review';
    end if;
    insert into public.case_reviews(workspace_id,case_id,run_id,decision,reason,cause_confirmed,findings,actor_id,acting_role)
      values(w,c.id,reviewed_run,body->>'decision',body->>'reason',coalesce((body->>'cause_confirmed')::boolean,false),coalesce(body->'findings','{}'),a,r);
    if coalesce((body->>'cause_confirmed')::boolean,false) then
      if jsonb_typeof(body->'cause_evidence') is distinct from 'array' or jsonb_array_length(body->'cause_evidence')=0 then raise sqlstate 'PT422' using message='Cause confirmation requires evidence'; end if;
      perform private.validate_case_citations(w,c.id,body->'cause_evidence');
      update public.cases set diagnosis_status='human_confirmed' where id=c.id;
    end if;
  elsif action='start' then
    if c.status not in ('created','owner_notified') and not (c.status='in_progress' and c.work_started_at is null) then raise sqlstate 'PT409' using message='Work already started'; end if;
    if not exists(select 1 from public.case_reviews where workspace_id=w and case_id=c.id and run_id in (c.published_run_id,c.requested_run_id)) then raise sqlstate 'PT422' using message='Human review required before work'; end if;
    if body->>'target_change_authority' is distinct from 'true' then raise sqlstate 'PT422' using message='Human target-change authority confirmation required'; end if;
    perform private.nonempty(body->>'approved_attributes','approved_attributes');
    update public.cases set status='in_progress',work_started_at=now() where id=c.id;
  elsif action='block' then
    if c.status not in ('created','owner_notified','in_progress') then raise sqlstate 'PT409' using message='Invalid block transition'; end if;
    perform private.nonempty(body->>'reason','reason'); update public.cases set status='blocked' where id=c.id;
  elsif action='resume' then
    if c.status<>'blocked' then raise sqlstate 'PT409' using message='Case is not blocked'; end if;
    if c.work_started_at is null then
      if not exists(select 1 from public.case_reviews where workspace_id=w and case_id=c.id and run_id in (c.published_run_id,c.requested_run_id))
        or body->'target_change_authority' is distinct from 'true'::jsonb then raise sqlstate 'PT422' using message='Human review and start-work authority are required before initial resume'; end if;
      perform private.nonempty(body->>'approved_attributes','approved_attributes');
    end if;
    perform private.nonempty(body->>'reason','reason'); update public.cases set status='in_progress',work_started_at=coalesce(work_started_at,now()) where id=c.id;
  elsif action='priority' then
    perform private.nonempty(body->>'reason','reason');
    update public.cases set priority=body->>'priority',due_at=least(due_at,private.business_due(now(),case when body->>'priority'='P3' then 1 else 2 end)) where id=c.id;
  elsif action='correction' then
    if c.status<>'in_progress' or c.work_started_at is null or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Started human-confirmed correction required'; end if;
    perform private.nonempty(body->>'explanation','explanation'); perform private.nonempty(body->>'target_system','target_system'); perform private.nonempty(body->>'target_object','target_object');
    if body->>'target_system' is distinct from c.target_system
      or body->>'target_object' is distinct from c.business_context->>'target_account' then
      raise sqlstate 'PT422' using message='Correction target must match the established case context';
    end if;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
    insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at)
      values(w,c.id,at_id,c.work_cycle,'correction',body,a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
    insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
  elsif action='complete_work' then
    if c.status<>'in_progress' or not exists(select 1 from public.milestones where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle and attempt_id=at_id and kind='correction') then raise sqlstate 'PT422' using message='Saved human-confirmed correction required'; end if;
    update public.cases set status='complete' where id=c.id;
  elsif action='reprocessing' then
    if c.status<>'complete' or not c.attempt_order_known or c.unreviewed_new_failure or coalesce(body->>'successful','true') is distinct from 'true' or body->>'correction_applicable' is distinct from 'true' or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Complete case and human-confirmed successful reprocessing required'; end if;
    perform private.nonempty(body->>'target_document_reference','target_document_reference');
    observation:=private.verified_proof(w,c.id,body->'proof_ids','reprocessing');
    if observation->>'result' is distinct from 'successful'
      or observation->>'attempt_key' is distinct from body->>'attempt_key'
      or (observation->>'processing_order')::bigint is distinct from (body->>'processing_order')::bigint
      or (observation->>'processing_at')::timestamptz is distinct from (body->>'processing_at')::timestamptz
      or observation->>'target_document_reference' is distinct from body->>'target_document_reference' then
      raise sqlstate 'PT422' using message='Reprocessing fields must match the saved verified result';
    end if;
    select * into attempt from public.attempts where id=at_id;
    if body->>'processing_order' is null or body->>'processing_at' is null or (body->>'processing_order')::bigint<=attempt.processing_order or (body->>'processing_at')::timestamptz<=attempt.processing_at then raise sqlstate 'PT422' using message='A later successful attempt is required'; end if;
    insert into public.attempts(workspace_id,case_id,attempt_key,processing_at,processing_order,result,target_document_reference)
      values(w,c.id,private.nonempty(body->>'attempt_key','attempt_key'),(body->>'processing_at')::timestamptz,(body->>'processing_order')::bigint,'successful',body->>'target_document_reference') returning id into at_id;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',coalesce(nullif(body->>'proof_reuse_reason',''),'Human confirms result proof and prior correction apply to this new successful attempt'));
    -- Preserve the original corrective milestone; explicitly attest applicability.
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,
      (select jsonb_agg(distinct mp.evidence_id) from public.milestones m join public.milestone_proof mp
        on mp.workspace_id=m.workspace_id and mp.milestone_id=m.id where m.workspace_id=w and m.case_id=c.id and m.work_cycle=c.work_cycle and m.kind='correction'),
      'Human confirms prior corrective evidence applies to this successful attempt');
    insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at)
      values(w,c.id,at_id,c.work_cycle,'reprocessing',body,a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
    insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
    update public.cases set status='document_reprocessed',current_attempt_id=at_id,input_revision=input_revision+1,unreviewed_new_failure=false where id=c.id;
  elsif action='validation' then
    if c.status<>'document_reprocessed' or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Document reprocessed and human validation attestation required'; end if;
    if coalesce(body->>'status','') not in ('passed','failed') or jsonb_typeof(body->'checks') is distinct from 'array' then raise sqlstate 'PT422' using message='Validation checks required'; end if;
    observation:=private.verified_proof(w,c.id,body->'proof_ids','validation');
    select * into attempt from public.attempts where id=at_id;
    if observation->>'attempt_key' is distinct from attempt.attempt_key
      or observation->>'target_document_reference' is distinct from attempt.target_document_reference
      or observation->>'status' is distinct from body->>'status' or observation->'checks' is distinct from body->'checks' then
      raise sqlstate 'PT422' using message='Validation must match server-computed posting checks for the current attempt';
    end if;
    select count(distinct x->>'dimension') into dim_count from jsonb_array_elements(body->'checks') x where x->>'dimension' in ('amount_currency','company','accounts','source_target_reference');
    passed:=body->>'status'='passed';
    if passed and (dim_count<>4 or jsonb_array_length(body->'checks')<>4 or exists(select 1 from jsonb_array_elements(body->'checks') x where coalesce(x->>'result','') not in ('passed','not_applicable') or nullif(btrim(x->>'expected'),'') is null or nullif(btrim(x->>'observed'),'') is null or (x->>'result'='not_applicable' and nullif(btrim(x->>'reason'),'') is null))) then raise sqlstate 'PT422' using message='All four posting checks must pass or have justified exceptions'; end if;
    if not passed and not exists(select 1 from jsonb_array_elements(body->'checks') x where x->>'result'='failed' and nullif(btrim(x->>'reason'),'') is not null) then raise sqlstate 'PT422' using message='Failed validation needs discrepancy evidence'; end if;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
    insert into public.milestones(workspace_id,case_id,attempt_id,work_cycle,kind,details,actor_id,acting_role,human_confirmed,action_at)
      values(w,c.id,at_id,c.work_cycle,'validation',body,a,r,true,private.action_time(body->>'occurred_at')) returning id into milestone_id;
    insert into public.milestone_proof select w,c.id,milestone_id,x::uuid from jsonb_array_elements_text(body->'proof_ids') x;
    update public.attempts set validation_status=body->>'status' where id=at_id;
  elsif action='resolution' then
    if c.status<>'document_reprocessed' or not c.attempt_order_known or c.unreviewed_new_failure or body->>'human_confirmed' is distinct from 'true' then raise sqlstate 'PT422' using message='Current successful reprocessing required'; end if;
    if not exists(select 1 from public.attempts where id=at_id and result='successful' and validation_status='passed') then raise sqlstate 'PT422' using message='Current attempt validation must pass'; end if;
    perform private.nonempty(body->>'correction_or_no_change','correction_or_no_change'); perform private.nonempty(body->>'outcome','outcome'); perform private.nonempty(body->'scope'->>'reuse_limitations','reuse_limitations'); perform private.nonempty(body->'scope'->>'target_system','target_system'); perform private.nonempty(body->'scope'->>'target_object','target_object'); perform private.nonempty(body->'scope'->>'company_code','company_code');
    if body->'scope'->>'target_system' is distinct from c.target_system
      or body->'scope'->>'target_object' is distinct from c.business_context->>'target_account'
      or body->'scope'->>'company_code' is distinct from c.business_context->>'company_code' then
      raise sqlstate 'PT422' using message='Resolution scope must match the established case context';
    end if;
    if body->>'cause_status'='confirmed' then
      if coalesce(body->>'cause','') not in ('missing_target_gl_master_data','missing_gl_mapping','closed_target_posting_period') or jsonb_typeof(body->'cause_evidence') is distinct from 'array' or jsonb_array_length(body->'cause_evidence')=0 then raise sqlstate 'PT422' using message='Confirmed cause requires evidence'; end if;
      perform private.validate_case_citations(w,c.id,body->'cause_evidence');
    elsif body->>'cause_status'='not_confirmed' then
      if body->>'cause' is not null or jsonb_typeof(body->'unresolved_gaps') is distinct from 'array' or jsonb_array_length(body->'unresolved_gaps')=0 then raise sqlstate 'PT422' using message='Unconfirmed cause needs unresolved gaps and no confirmed label'; end if;
    else raise sqlstate 'PT422' using message='Cause status required'; end if;
    perform private.attest_proof(w,c.id,at_id,c.work_cycle,a,body->'proof_ids',body->>'proof_reuse_reason');
    select coalesce(max(version),0)+1 into next_version from public.resolution_records where workspace_id=w and case_id=c.id and work_cycle=c.work_cycle;
    insert into public.resolution_records(workspace_id,case_id,attempt_id,work_cycle,version,record,resolver_id,resolved_at)
      values(w,c.id,at_id,c.work_cycle,next_version,body||jsonb_build_object('reuse_status','pending_review'),a,private.action_time(body->>'occurred_at'));
  elsif action='reopen' then
    perform private.nonempty(body->>'reason','reason');
    if coalesce(body->>'status','') not in ('in_progress','blocked') then raise sqlstate 'PT422' using message='Reopen status must be active'; end if;
    update public.cases set status=body->>'status',work_cycle=work_cycle+1,work_started_at=null,unreviewed_new_failure=false,due_at=private.business_due(now(),case when priority='P3' then 1 else 2 end) where id=c.id;
    update public.attempts set validation_status='pending' where id=at_id;
  else raise sqlstate 'PT422' using message='Unsupported case action'; end if;
  update public.cases set version=version+1 where id=c.id returning * into c;
  perform private.audit(w,c.id,a,r,'case_'||action,old_c,to_jsonb(c),body->>'reason');
  result:=jsonb_build_object('case',to_jsonb(c),'action',action,'attempt_id',at_id);
  insert into private.action_receipts values(w,a,key,hash,result);
  return result;
end $$;

-- Helpers are never directly executable through user or service clients.
revoke execute on all functions in schema private from public,anon,authenticated,service_role;
grant execute on function private.is_member(uuid) to authenticated;

-- Public wrappers contain no elevated logic; each calls one guarded implementation.
do $$ declare name text; service_names text[]:=array['commit_intake','register_evidence','claim_job','heartbeat_job','reserve_call','reconcile_call','complete_run'];
  user_names text[]:=array['review_reference','enqueue_run','case_action'];
begin
  foreach name in array service_names||user_names loop
    execute format('create function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',name,name);
    execute format('revoke execute on function public.cfin_%I(jsonb) from public,anon,authenticated,service_role',name);
    if name=any(service_names) then
      execute format('grant execute on function public.cfin_%I(jsonb) to service_role',name);
      execute format('grant execute on function private.%I(jsonb) to service_role',name);
    else
      execute format('grant execute on function public.cfin_%I(jsonb) to authenticated',name);
      execute format('grant execute on function private.%I(jsonb) to authenticated',name);
    end if;
  end loop;
end $$;
grant usage on schema private to service_role;
commit;
