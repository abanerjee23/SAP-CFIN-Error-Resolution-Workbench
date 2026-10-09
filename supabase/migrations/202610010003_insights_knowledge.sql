-- Durable read-only backlog snapshots and explicitly reviewed knowledge.
-- No synthetic approvals, model calls, or cloud-side embeddings are created here.
begin;
create extension if not exists vector with schema extensions;

create table public.overview_snapshots (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id),
  actor_id uuid not null references auth.users(id),
  filters jsonb not null,
  fingerprint text not null,
  metrics jsonb not null,
  as_of timestamptz not null default clock_timestamp(),
  expires_at timestamptz not null default clock_timestamp()+interval '5 minutes',
  narrative jsonb,
  unique(workspace_id,id)
);
create index overview_cache on public.overview_snapshots(workspace_id,actor_id,as_of desc);
create table public.overview_members (
  workspace_id uuid not null,
  snapshot_id uuid not null,
  case_id uuid not null,
  case_version bigint not null,
  identity_known boolean not null,
  attempt_count integer not null check(attempt_count>=0),
  case_data jsonb not null,
  foreign key(workspace_id,snapshot_id) references public.overview_snapshots(workspace_id,id),
  foreign key(workspace_id,case_id) references public.cases(workspace_id,id),
  primary key(snapshot_id,case_id)
);
create table public.overview_groups (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  snapshot_id uuid not null,
  dimension text not null,
  value text not null,
  count integer not null check(count>=0),
  unit text not null default 'cases' check(unit='cases'),
  case_ids jsonb not null,
  foreign key(workspace_id,snapshot_id) references public.overview_snapshots(workspace_id,id),
  unique(snapshot_id,dimension,value)
);
create table public.overview_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  snapshot_id uuid not null,
  actor_id uuid not null references auth.users(id),
  state text not null check(state in ('in_flight','succeeded','failed','usage_unknown')),
  model_id text not null,
  price_version text not null,
  price_input numeric(12,6) not null,
  price_output numeric(12,6) not null,
  month_start date not null,
  max_input_tokens integer not null check(max_input_tokens between 1 and 131072),
  max_output_tokens integer not null check(max_output_tokens between 1 and 8192),
  reserved_usd numeric(12,6) not null check(reserved_usd>=0),
  actual_usd numeric(12,6) check(actual_usd>=0),
  usage jsonb,
  error_code text,
  output jsonb,
  created_at timestamptz not null default clock_timestamp(),
  reconciled_at timestamptz,
  foreign key(workspace_id,snapshot_id) references public.overview_snapshots(workspace_id,id)
);
create unique index one_overview_explanation on public.overview_runs(snapshot_id)
  where state='in_flight';

create table public.knowledge_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  resolution_id uuid not null,
  version integer not null check(version>0),
  revision bigint not null default 1 check(revision>0),
  supersedes_id uuid,
  lesson text not null check(length(btrim(lesson)) between 10 and 4000),
  scope jsonb not null,
  evidence jsonb not null,
  resolution_snapshot jsonb not null,
  reuse_state text not null default 'pending_review'
    check(reuse_state in ('pending_review','approved','rejected','withdrawn')),
  concept_vector extensions.vector(64) not null,
  search_document tsvector generated always as (
    to_tsvector('english'::regconfig,lesson || ' ' || scope::text)
  ) stored,
  proposed_by uuid not null references auth.users(id),
  proposed_at timestamptz not null default clock_timestamp(),
  reviewed_by uuid references auth.users(id),
  reviewed_at timestamptz,
  review_reason text,
  foreign key(workspace_id,case_id) references public.cases(workspace_id,id),
  foreign key(workspace_id,resolution_id) references public.resolution_records(workspace_id,id),
  unique(workspace_id,id),
  unique(workspace_id,resolution_id,version),
  foreign key(workspace_id,supersedes_id) references public.knowledge_versions(workspace_id,id)
);
create index knowledge_lexical on public.knowledge_versions using gin(search_document);
create table public.knowledge_feedback (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  run_id uuid,
  why_help_needed text not null,
  proposed_change text not null,
  state text not null default 'pending_review'
    check(state in ('pending_review','accepted','rejected')),
  actor_id uuid not null references auth.users(id),
  acting_role text not null,
  reason text not null,
  reviewed_by uuid references auth.users(id),
  reviewed_at timestamptz,
  review_reason text,
  created_at timestamptz not null default clock_timestamp(),
  foreign key(workspace_id,case_id) references public.cases(workspace_id,id),
  foreign key(workspace_id,case_id,run_id) references public.analysis_runs(workspace_id,case_id,id)
);
create table public.knowledge_publication_policies (
  workspace_id uuid primary key references public.workspaces(id),
  revision bigint not null default 1,
  minimum_cases integer not null check(minimum_cases between 1 and 10000),
  minimum_pass_rate numeric not null check(minimum_pass_rate between 0 and 1),
  maximum_critical_failures integer not null check(maximum_critical_failures=0),
  require_human_review boolean not null check(require_human_review),
  actor_id uuid not null references auth.users(id),
  reason text not null,
  configured_at timestamptz not null default clock_timestamp()
);
create table public.knowledge_evaluation_attestations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  knowledge_id uuid not null,
  knowledge_revision bigint not null,
  policy_revision bigint not null,
  evidence_id uuid not null,
  report_sha256 text not null,
  cases integer not null check(cases>0),
  passed_cases integer not null check(passed_cases between 0 and cases),
  critical_failures integer not null check(critical_failures>=0),
  actor_id uuid not null references auth.users(id),
  human_reviewed boolean not null check(human_reviewed),
  reason text not null,
  created_at timestamptz not null default clock_timestamp(),
  foreign key(workspace_id,knowledge_id) references public.knowledge_versions(workspace_id,id),
  foreign key(workspace_id,evidence_id) references public.evidence_versions(workspace_id,id)
);
create table public.run_knowledge_sources (
  workspace_id uuid not null,
  run_id uuid not null,
  knowledge_id uuid not null,
  knowledge_version integer not null,
  knowledge_revision bigint not null,
  source_snapshot jsonb not null,
  foreign key(workspace_id,run_id) references public.analysis_runs(workspace_id,id),
  foreign key(workspace_id,knowledge_id) references public.knowledge_versions(workspace_id,id),
  primary key(run_id,knowledge_id)
);

do $$ declare t text; begin
  foreach t in array array[
    'overview_snapshots','overview_members','overview_groups','overview_runs',
    'knowledge_versions','knowledge_feedback','knowledge_publication_policies',
    'knowledge_evaluation_attestations','run_knowledge_sources'
  ] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
    if t like 'overview_%' then
      if t in ('overview_snapshots','overview_runs') then
        execute format('create policy scoped_read on public.%I for select to authenticated using (private.is_member(workspace_id) and actor_id=(select auth.uid()))',t);
      else
        execute format('create policy scoped_read on public.%I for select to authenticated using (private.is_member(workspace_id) and exists(select 1 from public.overview_snapshots s where s.id=snapshot_id and s.actor_id=(select auth.uid())))',t);
      end if;
    elsif t in ('knowledge_feedback','knowledge_publication_policies','knowledge_evaluation_attestations') then
      execute format('create policy scoped_read on public.%I for select to authenticated using (exists(select 1 from public.workspace_memberships m where m.workspace_id=%I.workspace_id and m.user_id=(select auth.uid()) and ''process_owner''=any(m.roles)))',t,t);
    elsif t='knowledge_versions' then
      execute format('create policy reviewed_or_reviewer on public.%I for select to authenticated using (private.is_member(workspace_id) and (reuse_state=''approved'' or exists(select 1 from public.workspace_memberships m where m.workspace_id=knowledge_versions.workspace_id and m.user_id=(select auth.uid()) and ''process_owner''=any(m.roles))))',t);
    else
      execute format('create policy member_read on public.%I for select to authenticated using (private.is_member(workspace_id))',t);
    end if;
  end loop;
end $$;

create function private.overview_fingerprint(w uuid)
returns text language sql stable security definer set search_path='' as $$
  select md5(coalesce(jsonb_agg(jsonb_build_array(c.id,c.version,c.linked_case_id,
    (select jsonb_agg(jsonb_build_array(a.id,a.result,a.validation_status) order by a.id)
     from public.attempts a where a.workspace_id=w and a.case_id=c.id)) order by c.id)::text,'[]'))
  from public.cases c where c.workspace_id=w;
$$;

create function private.overview_payload(s public.overview_snapshots)
returns jsonb language sql stable security definer set search_path='' as $$
  select jsonb_build_object(
    'snapshot',jsonb_build_object('id',s.id,'workspace_id',s.workspace_id,'as_of',s.as_of,
      'expires_at',s.expires_at,'filters',s.filters,'stale',s.expires_at<=clock_timestamp()
      or s.fingerprint<>private.overview_fingerprint(s.workspace_id)),
    'metrics',s.metrics,'groups',coalesce((select jsonb_agg(to_jsonb(g)-'case_ids'-'workspace_id'-'snapshot_id'
      order by g.dimension,case when g.dimension='priority' then case g.value when 'P3' then 0 when 'P2' then 1 else 2 end else 0 end,g.value)
      from public.overview_groups g where g.snapshot_id=s.id),'[]'::jsonb),'narrative',
    case when s.expires_at<=clock_timestamp() or s.fingerprint<>private.overview_fingerprint(s.workspace_id)
      then jsonb_build_object('status','stale','text','Snapshot changed or expired; refresh to explain current cases.')
      else s.narrative end);
$$;

create function private.create_overview_snapshot(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid();
  f jsonb:=coalesce(p->'filters','{}'::jsonb); v_fingerprint text;
  s public.overview_snapshots; dimension text;
begin
  if a is null or not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=a)
    then raise sqlstate 'PT403' using message='Workspace membership required'; end if;
  if jsonb_typeof(f)<>'object' or exists(select 1 from jsonb_object_keys(f) k where k not in (
    'category','priority','affected_object','diagnosis_status','status','company_code','target_system'))
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
      'category',c.category,'affected_object',c.affected_object,'diagnosis_status',c.diagnosis_status,
      'version',c.version,'company_code',c.business_context->>'company_code','target_system',c.target_system)
  from public.cases c where c.workspace_id=w and c.linked_case_id is null
    and (not (f ? 'category') or c.category=f->>'category')
    and (not (f ? 'priority') or c.priority=f->>'priority')
    and (not (f ? 'affected_object') or c.affected_object=f->>'affected_object')
    and (not (f ? 'diagnosis_status') or c.diagnosis_status=f->>'diagnosis_status')
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
        and m.work_cycle=c.work_cycle and m.kind='correction'
        and m.id=(select id from public.milestones where workspace_id=w and case_id=c.id
          and work_cycle=c.work_cycle and kind='correction' order by recorded_at desc,id desc limit 1)
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
  foreach dimension in array array['category','priority','affected_object','diagnosis_status','status','company_code','target_system'] loop
    insert into public.overview_groups(workspace_id,snapshot_id,dimension,value,count,case_ids)
    select w,s.id,dimension,coalesce(case_data->>dimension,'unknown'),count(*),jsonb_agg(case_id order by case_id)
      from public.overview_members where snapshot_id=s.id and identity_known
      group by coalesce(case_data->>dimension,'unknown');
  end loop;
  insert into public.overview_groups(workspace_id,snapshot_id,dimension,value,count,case_ids)
    select w,s.id,'identity','provisional',count(*),jsonb_agg(case_id order by case_id)
    from public.overview_members where snapshot_id=s.id and not identity_known having count(*)>0;
  return private.overview_payload(s);
end $$;

create function private.read_overview_snapshot(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); s public.overview_snapshots;
begin
  if a is null or not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=a)
    then raise sqlstate 'PT403' using message='Workspace membership required'; end if;
  select * into s from public.overview_snapshots where workspace_id=w and actor_id=a and id=(p->>'snapshot_id')::uuid;
  if not found then raise sqlstate 'PT404' using message='Overview not found'; end if;
  return private.overview_payload(s);
end $$;

create function private.overview_group(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare s public.overview_snapshots; g public.overview_groups; a uuid:=auth.uid();
  w uuid:=(p->>'workspace_id')::uuid; page integer:=coalesce((p->>'page')::integer,1);
  size integer:=coalesce((p->>'page_size')::integer,25); items jsonb;
begin
  perform private.read_overview_snapshot(p);
  select * into s from public.overview_snapshots where id=(p->>'snapshot_id')::uuid and workspace_id=w and actor_id=a;
  select * into g from public.overview_groups where snapshot_id=s.id and id=(p->>'group_id')::uuid;
  if not found then raise sqlstate 'PT404' using message='Group not found'; end if;
  if page<1 or size not between 1 and 50 then raise sqlstate 'PT422' using message='Invalid page'; end if;
  select coalesce(jsonb_agg(row_data order by rank,id),'[]') into items from (
    select m.case_id as id,case c.priority when 'P3' then 0 when 'P2' then 1 else 2 end as rank,
      jsonb_build_object('id',c.id,'title',c.title,'priority',c.priority,'status',c.status,
        'category',c.category,'affected_object',c.affected_object,'diagnosis_status',c.diagnosis_status,
        'version',c.version,'snapshot_version',m.case_version,'changed_since_snapshot',c.version<>m.case_version,
        'snapshot_case',m.case_data,'linked_case_id',c.linked_case_id) as row_data
    from public.overview_members m join public.cases c on c.workspace_id=w and c.id=m.case_id
    where m.snapshot_id=s.id and g.case_ids @> jsonb_build_array(m.case_id)
    order by rank,id offset (page-1)*size limit size
  ) q;
  return jsonb_build_object('snapshot',(private.overview_payload(s))->'snapshot',
    'group',to_jsonb(g)-'case_ids'-'workspace_id'-'snapshot_id','items',items,
    'total',g.count,'page',page,'page_size',size);
end $$;

create function private.reserve_overview_call(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=(p->>'actor_id')::uuid;
  s public.overview_snapshots; run public.overview_runs; slot private.worker_slot;
  price private.model_prices; month date:=date_trunc('month',clock_timestamp() at time zone 'UTC')::date;
  cap numeric; amount numeric; used numeric;
  monthly_cap numeric:=(p->>'monthly_budget_usd')::numeric; run_cap numeric:=(p->>'run_budget_usd')::numeric;
begin
  if not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=a)
    then raise sqlstate 'PT403' using message='Workspace membership required'; end if;
  select * into slot from private.worker_slot where singleton=1 for update;
  update public.overview_runs set state='usage_unknown',error_code='overview_interrupted'
    where state='in_flight' and created_at<clock_timestamp()-interval '90 seconds';
  select * into s from public.overview_snapshots where workspace_id=w and actor_id=a and id=(p->>'snapshot_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Overview not found'; end if;
  if s.expires_at<=clock_timestamp() or s.fingerprint<>private.overview_fingerprint(w)
    then raise sqlstate 'PT409' using message='Overview is stale'; end if;
  if exists(select 1 from public.overview_runs where snapshot_id=s.id and state='in_flight')
    then return jsonb_build_object('execute',false); end if;
  if slot.lease_until>clock_timestamp() then raise sqlstate 'PT409' using message='Another model run is active'; end if;
  if monthly_cap is null or monthly_cap<=0 or monthly_cap>10 or run_cap is null or run_cap<=0 or run_cap>1
    then raise sqlstate 'PT422' using message='Invalid model budget'; end if;
  if p->>'model_id'<>'gpt-6.1-sol' then raise sqlstate 'PT422' using message='Agent 4 Sol baseline required'; end if;
  select * into price from private.model_prices where model_id=p->>'model_id' and expires_at>clock_timestamp();
  if not found or price.version is distinct from p->>'price_version' then raise sqlstate 'PT422' using message='Known current model pricing required'; end if;
  if (p->>'max_input_tokens')::integer not between 1 and 131072 or (p->>'max_output_tokens')::integer not between 1 and 8192
    then raise sqlstate 'PT422' using message='Invalid bounded model request'; end if;
  insert into private.budget_months(workspace_id,month_start) values(w,month) on conflict do nothing;
  select allowance_usd into cap from private.budget_months where workspace_id=w and month_start=month for update;
  amount:=ceil(((p->>'max_input_tokens')::numeric*price.input_usd_per_million+
    (p->>'max_output_tokens')::numeric*price.output_usd_per_million))/1000000;
  select coalesce(sum(cost),0) into used from (
    select coalesce(actual_usd,reserved_usd) cost from public.stage_calls where month_start=month and state<>'not_sent'
    union all select coalesce(actual_usd,reserved_usd) from public.overview_runs where month_start=month
  ) costs;
  if used+amount>least(cap,10,monthly_cap) or amount>least(1,run_cap)
    then raise sqlstate 'PT422' using message='Model budget exhausted'; end if;
  insert into public.overview_runs(workspace_id,snapshot_id,actor_id,state,model_id,price_version,
    price_input,price_output,month_start,max_input_tokens,max_output_tokens,reserved_usd)
  values(w,s.id,a,'in_flight',price.model_id,price.version,price.input_usd_per_million,
    price.output_usd_per_million,month,(p->>'max_input_tokens')::integer,(p->>'max_output_tokens')::integer,amount)
    returning * into run;
  update private.worker_slot set job_id=null,lease_token=run.id,lease_until=clock_timestamp()+interval '90 seconds' where singleton=1;
  return jsonb_build_object('execute',true,'run',to_jsonb(run));
end $$;

create function private.complete_overview_call(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare run public.overview_runs; s public.overview_snapshots; state_value text:=p->>'state';
  input_count integer; output_count integer; amount numeric; claim jsonb;
begin
  perform 1 from private.worker_slot where singleton=1 for update;
  select * into run from public.overview_runs where id=(p->>'run_id')::uuid
    and workspace_id=(p->>'workspace_id')::uuid and actor_id=(p->>'actor_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Overview run not found'; end if;
  if run.state<>'in_flight' then
    select * into s from public.overview_snapshots where id=run.snapshot_id;
    return private.overview_payload(s);
  end if;
  if state_value not in ('succeeded','failed','usage_unknown') then raise sqlstate 'PT422' using message='Invalid usage state'; end if;
  if state_value<>'usage_unknown' then
    input_count:=(p->'usage'->>'input_tokens')::integer; output_count:=(p->'usage'->>'output_tokens')::integer;
    if input_count is null or output_count is null or input_count not between 1 and run.max_input_tokens
      or output_count not between 0 and run.max_output_tokens then raise sqlstate 'PT422' using message='Invalid observed usage'; end if;
    amount:=(input_count*run.price_input+output_count*run.price_output)/1000000;
  end if;
  select * into s from public.overview_snapshots where id=run.snapshot_id for update;
  if state_value='succeeded' then
    if not exists(select 1 from public.workspace_memberships where workspace_id=run.workspace_id and user_id=run.actor_id)
      or s.expires_at<=clock_timestamp() or s.fingerprint<>private.overview_fingerprint(run.workspace_id)
      or not exists(select 1 from private.worker_slot where singleton=1 and lease_token=run.id and lease_until>clock_timestamp())
      then state_value:='failed';
    else
      if p->'output'->>'status'<>'available' or jsonb_typeof(p->'output'->'claims') is distinct from 'array'
        or jsonb_array_length(p->'output'->'claims') not between 1 and 8 then raise sqlstate 'PT422' using message='Exact group claims required'; end if;
      for claim in select * from jsonb_array_elements(p->'output'->'claims') loop
        if not exists(select 1 from public.overview_groups where snapshot_id=s.id and id=(claim->>'group_id')::uuid and count=(claim->>'count')::integer)
          then raise sqlstate 'PT422' using message='Overview claim differs from saved count'; end if;
      end loop;
      update public.overview_snapshots set narrative=p->'output' where id=s.id returning * into s;
    end if;
  end if;
  update public.overview_runs set state=state_value,actual_usd=amount,usage=p->'usage',output=p->'output',
    error_code=case when state_value='failed' then 'overview_changed_or_access_revoked' else p->>'error_code' end,
    reconciled_at=clock_timestamp() where id=run.id;
  update private.worker_slot set lease_token=null,lease_until=null where singleton=1 and job_id is null and lease_token=run.id;
  return private.overview_payload(s);
end $$;

create function private.knowledge_member(p jsonb)
returns uuid language plpgsql security definer set search_path='' as $$
declare a uuid; w uuid:=(p->>'workspace_id')::uuid;
begin
  a:=auth.uid();
  if a is null and auth.role()='service_role' then a:=(p->>'actor_id')::uuid; end if;
  if a is null or not exists(select 1 from public.workspace_memberships where workspace_id=w and user_id=a)
    then raise sqlstate 'PT403' using message='Workspace membership required'; end if;
  return a;
end $$;

create function private.publication_policy_payload(w uuid)
returns jsonb language sql stable security definer set search_path='' as $$
  select coalesce((select to_jsonb(p)-'actor_id' || jsonb_build_object('configured',true)
    from public.knowledge_publication_policies p where workspace_id=w),
    jsonb_build_object('configured',false,'reason','Define model-quality criteria and review saved evaluation evidence before publication.'));
$$;

create function private.search_history(p jsonb)
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
        + (select count(*)*0.25 from jsonb_each_text(context) x where k.scope->>x.key=x.value) as score,
      jsonb_build_object('id',k.id,'case_id',k.case_id,'version',k.version,'revision',k.revision,
        'reuse_state',k.reuse_state,'lesson',k.lesson,'scope',k.scope,'evidence',k.evidence,
        'resolution_record',k.resolution_snapshot,'reviewed_by',k.reviewed_by,'reviewed_at',k.reviewed_at,
        'synthetic',true,'matching_facts',coalesce((select jsonb_agg(x.key||': '||x.value) from jsonb_each_text(context) x where k.scope->>x.key=x.value),'[]'),
        'differing_facts',coalesce((select jsonb_agg(x.key||': current '||x.value||'; historical '||coalesce(k.scope->>x.key,'unknown')) from jsonb_each_text(context) x where k.scope->>x.key is distinct from x.value),'[]'),
        'score',ts_rank_cd(k.search_document,websearch_to_tsquery('english'::regconfig,q))*2
          + case when v is null then 0 else greatest(0,1-(k.concept_vector OPERATOR(extensions.<=>) v)) end
          + (select count(*)*0.25 from jsonb_each_text(context) x where k.scope->>x.key=x.value)) as row_data
    from public.knowledge_versions k where k.workspace_id=w and k.reuse_state='approved'
      and not exists(select 1 from jsonb_each_text(f) x where k.scope->>x.key is distinct from x.value)
      and (q='' or k.search_document @@ websearch_to_tsquery('english'::regconfig,q)
        or (v is not null and (k.concept_vector OPERATOR(extensions.<=>) v)<0.9))
    order by score desc,k.id limit size
  ) matches;
  return jsonb_build_object('items',items,'retrieval_method','hybrid_lexical_context',
    'vector_method','local_concept_hashing_not_a_learned_embedding','publication_policy',private.publication_policy_payload(w));
end $$;

create function private.knowledge_reviews(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid;
begin
  perform private.require_actor(w,a,'process_owner');
  return jsonb_build_object('items',coalesce((select jsonb_agg(to_jsonb(k)-'concept_vector'-'search_document' order by proposed_at desc)
    from public.knowledge_versions k where workspace_id=w),'[]'),
    'feedback',coalesce((select jsonb_agg(to_jsonb(f) order by created_at desc) from public.knowledge_feedback f where workspace_id=w),'[]'),
    'evaluation_attestations',coalesce((select jsonb_agg(to_jsonb(e) order by created_at desc)
      from public.knowledge_evaluation_attestations e where workspace_id=w),'[]'),
    'publication_policy',private.publication_policy_payload(w));
end $$;

create function private.knowledge_version(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=private.knowledge_member(p); w uuid:=(p->>'workspace_id')::uuid; k public.knowledge_versions;
begin
  select * into k from public.knowledge_versions where workspace_id=w and id=(p->>'knowledge_id')::uuid;
  if not found or (k.reuse_state<>'approved' and not exists(select 1 from public.workspace_memberships
    where workspace_id=w and user_id=a and 'process_owner'=any(roles)))
    then raise sqlstate 'PT404' using message='Eligible knowledge version not found'; end if;
  return to_jsonb(k)-'concept_vector'-'search_document';
end $$;

create function private.withdraw_knowledge(w uuid,k_id uuid,a uuid,reason text)
returns void language plpgsql security definer set search_path='' as $$
declare k public.knowledge_versions;
begin
  select * into k from public.knowledge_versions where workspace_id=w and id=k_id for update;
  update public.knowledge_versions set reuse_state='withdrawn',revision=revision+1,
    reviewed_by=a,reviewed_at=clock_timestamp(),review_reason=reason where id=k.id;
  update public.cases c set review_flags=(select array_agg(distinct value) from unnest(c.review_flags||array['historical_knowledge_withdrawn']) value),
    analysis_status='needs_refresh',version=version+1
    where c.workspace_id=w and exists(select 1 from public.run_knowledge_sources h where h.workspace_id=w
      and h.knowledge_id=k.id and h.run_id in (c.requested_run_id,c.published_run_id))
    and c.status<>'document_reprocessed';
  perform private.audit(w,k.case_id,a,'process_owner','knowledge_withdrawn',to_jsonb(k),
    jsonb_build_object('knowledge_id',k.id,'reuse_state','withdrawn'),reason);
end $$;

create function private.knowledge_draft(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid; r public.resolution_records;
  k public.knowledge_versions; old public.knowledge_versions; n integer;
begin
  perform private.require_actor(w,a,'process_owner');
  perform private.nonempty(p->>'lesson','lesson'); perform private.nonempty(p->>'reason','reason');
  if length(p->>'lesson') not between 10 and 4000 or jsonb_typeof(p->'scope') is distinct from 'object'
    or exists(select 1 from unnest(array['target_system','company_code','affected_object','category','reuse_limitations']) key
      where coalesce(length(btrim(p->'scope'->>key)),0)=0)
    then raise sqlstate 'PT422' using message='Defined applicability and lesson required'; end if;
  select * into r from public.resolution_records where workspace_id=w and id=(p->>'resolution_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Resolution record not found'; end if;
  if p->>'supersedes_id' is not null then
    select * into old from public.knowledge_versions where workspace_id=w and id=(p->>'supersedes_id')::uuid for update;
    if not found or old.case_id<>r.case_id then raise sqlstate 'PT422' using message='Replacement must version the same case knowledge'; end if;
    if p->'materially_disputed'='true'::jsonb and old.reuse_state='approved' then
      perform private.withdraw_knowledge(w,old.id,a,p->>'reason');
    end if;
  end if;
  select coalesce(max(version),0)+1 into n from public.knowledge_versions where workspace_id=w and case_id=r.case_id;
  insert into public.knowledge_versions(workspace_id,case_id,resolution_id,version,supersedes_id,lesson,scope,evidence,
    resolution_snapshot,concept_vector,proposed_by)
  values(w,r.case_id,r.id,n,(p->>'supersedes_id')::uuid,p->>'lesson',p->'scope',
    coalesce(r.record->'cause_evidence','[]'),r.record,(p->>'concept_vector')::extensions.vector(64),a) returning * into k;
  perform private.audit(w,r.case_id,a,'process_owner','knowledge_draft',null,to_jsonb(k)-'concept_vector'-'search_document',p->>'reason');
  return to_jsonb(k)-'concept_vector'-'search_document';
end $$;

create function private.publication_policy(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid; policy public.knowledge_publication_policies;
begin
  perform private.require_actor(w,a,'process_owner'); perform private.nonempty(p->>'reason','reason');
  if p->'require_human_review' is distinct from 'true'::jsonb or (p->>'maximum_critical_failures')::integer is distinct from 0
    or (p->>'minimum_cases')::integer not between 1 and 10000 or (p->>'minimum_pass_rate')::numeric not between 0 and 1
    then raise sqlstate 'PT422' using message='Explicit safe publication criteria required'; end if;
  insert into public.knowledge_publication_policies(workspace_id,minimum_cases,minimum_pass_rate,maximum_critical_failures,
    require_human_review,actor_id,reason)
  values(w,(p->>'minimum_cases')::integer,(p->>'minimum_pass_rate')::numeric,0,true,a,p->>'reason')
  on conflict(workspace_id) do update set revision=knowledge_publication_policies.revision+1,
    minimum_cases=excluded.minimum_cases,minimum_pass_rate=excluded.minimum_pass_rate,
    actor_id=a,reason=excluded.reason,configured_at=clock_timestamp() returning * into policy;
  perform private.audit(w,null,a,'process_owner','publication_policy',null,to_jsonb(policy),p->>'reason');
  return private.publication_policy_payload(w);
end $$;

create function private.attest_knowledge_evaluation(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=(p->>'actor_id')::uuid; w uuid:=(p->>'workspace_id')::uuid;
  k public.knowledge_versions; policy public.knowledge_publication_policies; e public.evidence_versions;
  review public.knowledge_evaluation_attestations; observations jsonb:=p->'observations';
begin
  perform private.require_actor(w,a,'process_owner'); perform private.nonempty(p->>'reason','reason');
  select * into policy from public.knowledge_publication_policies where workspace_id=w;
  if not found then raise sqlstate 'PT422' using message='Define publication criteria first'; end if;
  select * into k from public.knowledge_versions where workspace_id=w and id=(p->>'knowledge_id')::uuid for update;
  if not found or k.reuse_state<>'pending_review' then raise sqlstate 'PT422' using message='Pending exact knowledge version required'; end if;
  select * into e from public.evidence_versions where workspace_id=w and id=(p->>'evidence_id')::uuid;
  if not found or e.sha256 is distinct from p->>'report_sha256' or e.content_type<>'application/json'
    or observations->>'knowledge_id' is distinct from k.id::text or p->'human_reviewed' is distinct from 'true'::jsonb
    then raise sqlstate 'PT422' using message='Verified saved model evaluation and human review required'; end if;
  insert into public.knowledge_evaluation_attestations(workspace_id,knowledge_id,knowledge_revision,policy_revision,
    evidence_id,report_sha256,cases,passed_cases,critical_failures,actor_id,human_reviewed,reason)
  values(w,k.id,k.revision,policy.revision,e.id,e.sha256,(observations->>'cases')::integer,
    (observations->>'passed_cases')::integer,(observations->>'critical_failures')::integer,a,true,p->>'reason') returning * into review;
  perform private.audit(w,k.case_id,a,'process_owner','knowledge_evaluation_reviewed',null,to_jsonb(review),p->>'reason');
  return to_jsonb(review);
end $$;

create function private.knowledge_review(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid; k public.knowledge_versions;
  r public.resolution_records; c public.cases; policy public.knowledge_publication_policies;
  evaluation public.knowledge_evaluation_attestations; decision text:=p->>'decision';
begin
  perform private.require_actor(w,a,'process_owner'); perform private.nonempty(p->>'reason','reason');
  select * into k from public.knowledge_versions where workspace_id=w and id=(p->>'knowledge_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Knowledge not found'; end if;
  if k.revision is distinct from (p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Knowledge version changed'; end if;
  if decision not in ('approved','rejected','withdrawn') then raise sqlstate 'PT422' using message='Invalid review decision'; end if;
  if decision='withdrawn' then
    if k.reuse_state<>'approved' then raise sqlstate 'PT422' using message='Only an approved version can be withdrawn'; end if;
    perform private.withdraw_knowledge(w,k.id,a,p->>'reason');
  else
    if k.reuse_state<>'pending_review' then raise sqlstate 'PT422' using message='Create a replacement draft for another review'; end if;
    if decision='approved' then
      select * into r from public.resolution_records where workspace_id=w and id=k.resolution_id;
      select * into c from public.cases where workspace_id=w and id=k.case_id for update;
      if r.record->>'cause_status' is distinct from 'confirmed' or jsonb_array_length(k.evidence)=0
        or k.scope->>'target_system' is distinct from c.target_system
        or k.scope->>'company_code' is distinct from c.business_context->>'company_code'
        or k.scope->>'category' is distinct from r.record->>'cause'
        or k.scope->>'affected_object' is distinct from c.affected_object
        or c.current_attempt_id<>r.attempt_id or c.work_cycle<>r.work_cycle or not c.attempt_order_known
        or c.unreviewed_new_failure or c.status<>'document_reprocessed'
        or not exists(select 1 from public.attempts where workspace_id=w and id=r.attempt_id and result='successful' and validation_status='passed')
        or not exists(select 1 from public.milestones where workspace_id=w and case_id=c.id and attempt_id=r.attempt_id and work_cycle=r.work_cycle
          and kind='validation' and details->>'status'='passed')
        then raise sqlstate 'PT422' using message='Confirmed evidence-backed current validated resolution required'; end if;
      select * into policy from public.knowledge_publication_policies where workspace_id=w;
      if not found then raise sqlstate 'PT422' using message='Define publication evaluation criteria first'; end if;
      select * into evaluation from public.knowledge_evaluation_attestations where workspace_id=w
        and id=(p->>'evaluation_evidence_id')::uuid and knowledge_id=k.id and knowledge_revision=k.revision
        and policy_revision=policy.revision and human_reviewed;
      if not found or evaluation.cases<policy.minimum_cases or evaluation.critical_failures>policy.maximum_critical_failures
        or evaluation.passed_cases::numeric/evaluation.cases<policy.minimum_pass_rate
        then raise sqlstate 'PT422' using message='Reviewed model-evaluation prerequisites not met'; end if;
      perform private.validate_case_citations(w,c.id,k.evidence);
    end if;
    update public.knowledge_versions set reuse_state=decision,revision=revision+1,reviewed_by=a,
      reviewed_at=clock_timestamp(),review_reason=p->>'reason' where id=k.id;
    perform private.audit(w,k.case_id,a,'process_owner','knowledge_review',to_jsonb(k)-'concept_vector'-'search_document',
      jsonb_build_object('knowledge_id',k.id,'decision',decision),p->>'reason');
  end if;
  select * into k from public.knowledge_versions where id=k.id;
  return to_jsonb(k)-'concept_vector'-'search_document';
end $$;

create function private.knowledge_feedback(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid; feedback public.knowledge_feedback;
begin
  perform private.require_actor(w,a,p->>'acting_role');
  perform private.nonempty(p->>'why_help_needed','why_help_needed'); perform private.nonempty(p->>'proposed_change','proposed_change');
  perform private.nonempty(p->>'reason','reason');
  insert into public.knowledge_feedback(workspace_id,case_id,run_id,why_help_needed,proposed_change,actor_id,acting_role,reason)
    values(w,(p->>'case_id')::uuid,(p->>'run_id')::uuid,p->>'why_help_needed',p->>'proposed_change',a,p->>'acting_role',p->>'reason') returning * into feedback;
  perform private.audit(w,feedback.case_id,a,p->>'acting_role','knowledge_feedback',null,to_jsonb(feedback),p->>'reason');
  return to_jsonb(feedback);
end $$;

create function private.review_knowledge_feedback(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=auth.uid(); w uuid:=(p->>'workspace_id')::uuid;
  feedback public.knowledge_feedback; decision text:=p->>'decision';
begin
  perform private.require_actor(w,a,'process_owner'); perform private.nonempty(p->>'reason','reason');
  select * into feedback from public.knowledge_feedback where workspace_id=w and id=(p->>'feedback_id')::uuid for update;
  if not found then raise sqlstate 'PT404' using message='Feedback not found'; end if;
  if feedback.state<>'pending_review' then raise sqlstate 'PT409' using message='Feedback was already reviewed'; end if;
  if decision not in ('accepted','rejected') then raise sqlstate 'PT422' using message='Invalid feedback decision'; end if;
  update public.knowledge_feedback set state=decision,reviewed_by=a,reviewed_at=clock_timestamp(),review_reason=p->>'reason'
    where id=feedback.id returning * into feedback;
  perform private.audit(w,feedback.case_id,a,'process_owner','knowledge_feedback_review',null,to_jsonb(feedback),p->>'reason');
  -- Acceptance records review; it never edits guidance or publishes a precedent.
  return to_jsonb(feedback);
end $$;

create function private.register_run_history(p jsonb)
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
    if not found or k.reuse_state<>'approved' then raise sqlstate 'PT409' using message='History eligibility changed'; end if;
    insert into public.run_knowledge_sources(workspace_id,run_id,knowledge_id,knowledge_version,knowledge_revision,source_snapshot)
      values(w,run.id,k.id,k.version,k.revision,to_jsonb(k)-'concept_vector'-'search_document') on conflict do nothing;
  end loop;
  return jsonb_build_object('registered',true);
end $$;

create function private.revalidate_history(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a uuid:=private.knowledge_member(p); w uuid:=(p->>'workspace_id')::uuid;
begin
  if jsonb_typeof(p->'ids') is distinct from 'array' or jsonb_array_length(p->'ids')>5
    then raise sqlstate 'PT422' using message='Bounded history references required'; end if;
  return jsonb_build_object('eligible',not exists(select 1 from jsonb_array_elements_text(p->'ids') source_id
    where not exists(select 1 from public.knowledge_versions where workspace_id=w and id=source_id::uuid and reuse_state='approved')));
end $$;

-- Existing native worker retains its immutable output and lease fencing. This
-- final, database-level eligibility check prevents a withdrawal race from
-- promoting an actionable result after a read-time check already succeeded.
alter function private.complete_run(jsonb) rename to complete_run_base;
create function private.complete_run(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare blocked boolean;
begin
  perform 1 from public.knowledge_versions k join public.run_knowledge_sources h on h.knowledge_id=k.id
    where h.run_id=(select run_id from public.jobs where id=(p->>'job_id')::uuid) for share of k;
  select exists(select 1 from public.run_knowledge_sources h join public.knowledge_versions k on k.id=h.knowledge_id
    where h.run_id=(select run_id from public.jobs where id=(p->>'job_id')::uuid)
      and (k.reuse_state<>'approved' or k.revision<>h.knowledge_revision)) into blocked;
  if blocked then
    p:=p || jsonb_build_object('succeeded',false,'error_code','historical_knowledge_withdrawn');
  end if;
  return private.complete_run_base(p);
end $$;

-- Public wrappers preserve authenticated actor identity. Service-only methods
-- are never available to a browser, even when it knows a row UUID.
do $$ declare name text;
  user_names text[]:=array['create_overview_snapshot','read_overview_snapshot','overview_group',
    'knowledge_reviews','knowledge_version','knowledge_draft','knowledge_review','knowledge_feedback',
    'review_knowledge_feedback','publication_policy'];
  shared_names text[]:=array['search_history','revalidate_history'];
  service_names text[]:=array['reserve_overview_call','complete_overview_call','attest_knowledge_evaluation','register_run_history'];
begin
  foreach name in array user_names||shared_names||service_names loop
    execute format('create function public.cfin_%I(payload jsonb) returns jsonb language sql security invoker set search_path='''' as $rpc$ select private.%I(payload); $rpc$',name,name);
    execute format('revoke all on function private.%I(jsonb) from public,anon,authenticated,service_role',name);
    execute format('revoke all on function public.cfin_%I(jsonb) from public,anon,authenticated,service_role',name);
    if name=any(user_names||shared_names) then
      execute format('grant execute on function private.%I(jsonb) to authenticated',name);
      execute format('grant execute on function public.cfin_%I(jsonb) to authenticated',name);
    end if;
    if name=any(service_names||shared_names) then
      execute format('grant execute on function private.%I(jsonb) to service_role',name);
      execute format('grant execute on function public.cfin_%I(jsonb) to service_role',name);
    end if;
  end loop;
end $$;
revoke all on function private.overview_fingerprint(uuid),private.overview_payload(public.overview_snapshots),
  private.knowledge_member(jsonb),private.publication_policy_payload(uuid),private.withdraw_knowledge(uuid,uuid,uuid,text)
  from public,anon,authenticated;
revoke all on function private.complete_run(jsonb) from public,anon,authenticated;
grant execute on function private.complete_run(jsonb) to service_role;
create trigger immutable_overview_members before update or delete on public.overview_members
  for each row execute function private.preserve_source();
create trigger immutable_overview_groups before update or delete on public.overview_groups
  for each row execute function private.preserve_source();
create trigger immutable_history_sources before update or delete on public.run_knowledge_sources
  for each row execute function private.preserve_source();
commit;
