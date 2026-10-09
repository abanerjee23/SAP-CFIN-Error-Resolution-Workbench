-- Synthetic POC foundation. Apply only to the isolated synthetic project.
-- Writes remain denied to browser roles until audited workflow RPCs exist.
begin;

create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to authenticated;

create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(btrim(name)) > 0),
  synthetic boolean not null default true check (synthetic),
  created_at timestamptz not null default now()
);

create table public.workspace_memberships (
  workspace_id uuid not null references public.workspaces(id),
  user_id uuid not null references auth.users(id),
  roles text[] not null check (
    cardinality(roles) > 0 and roles <@ array[
      'process_owner','master_data_owner','mapping_owner','finance_owner','validator'
    ]::text[] and array_position(roles, null) is null
  ),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create function private.is_member(requested_workspace uuid)
returns boolean language sql stable security definer
set search_path = '' as $$
  select exists (
    select 1 from public.workspace_memberships
    where workspace_id = requested_workspace and user_id = (select auth.uid())
  );
$$;
revoke all on function private.is_member(uuid) from public;
grant execute on function private.is_member(uuid) to authenticated;

create table public.cases (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id),
  source_system text,
  source_client text,
  source_company_code text,
  fiscal_year text,
  document_number text,
  target_system text,
  target_client text,
  interface text,
  title text not null check (length(btrim(title)) > 0),
  description text not null default '',
  category text not null default 'cause_not_established' check (category in (
    'missing_target_gl_master_data','missing_gl_mapping','closed_target_posting_period',
    'multiple_blockers','cause_not_established','unknown'
  )),
  affected_object text not null default 'unknown' check (affected_object in (
    'gl_account','cost_center','profit_center','asset','posting_period','unknown'
  )),
  priority text not null default 'P2' check (priority in ('P1','P2','P3')),
  status text not null default 'created' check (status in (
    'created','owner_notified','in_progress','blocked','complete','document_reprocessed'
  )),
  diagnosis_status text not null default 'needs_review' check (diagnosis_status in (
    'ai_supported','human_confirmed','needs_review'
  )),
  analysis_status text not null default 'pending' check (analysis_status in (
    'pending','running','available','needs_refresh','unavailable'
  )),
  business_context jsonb not null default '{}',
  review_flags text[] not null default '{}',
  current_attempt_id uuid,
  attempt_order_known boolean not null default false,
  unreviewed_new_failure boolean not null default false,
  work_cycle integer not null default 1 check (work_cycle > 0),
  version bigint not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  due_at timestamptz not null,
  unique (workspace_id, id),
  check (source_system is null or length(btrim(source_system)) > 0),
  check (source_client is null or length(btrim(source_client)) > 0),
  check (source_company_code is null or length(btrim(source_company_code)) > 0),
  check (fiscal_year is null or length(btrim(fiscal_year)) > 0),
  check (document_number is null or length(btrim(document_number)) > 0),
  check (target_system is null or length(btrim(target_system)) > 0),
  check (target_client is null or length(btrim(target_client)) > 0),
  check (interface is null or length(btrim(interface)) > 0)
);

-- PostgreSQL permits several incomplete identities; they remain provisional.
create unique index canonical_case_identity on public.cases (
  workspace_id,source_system,source_client,source_company_code,fiscal_year,
  document_number,target_system,target_client,interface
) where source_system is not null and source_client is not null
  and source_company_code is not null and fiscal_year is not null
  and document_number is not null and target_system is not null
  and target_client is not null and interface is not null;
create index cases_board on public.cases (workspace_id, created_at desc, id);
create index cases_classification on public.cases (workspace_id, category, priority, diagnosis_status);

create table public.attempts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  attempt_key text not null check (length(btrim(attempt_key)) > 0),
  processing_at timestamptz,
  processing_order bigint check (processing_order > 0),
  result text not null check (result in ('failed','successful','unknown')),
  target_document_reference text,
  validation_status text not null default 'pending' check (validation_status in ('pending','passed','failed')),
  received_at timestamptz not null default now(),
  foreign key (workspace_id, case_id) references public.cases(workspace_id, id),
  unique (workspace_id, id),
  unique (workspace_id, case_id, id),
  unique (workspace_id, case_id, attempt_key)
);
alter table public.cases add constraint current_attempt_belongs_to_case
  foreign key (workspace_id, id, current_attempt_id)
  references public.attempts(workspace_id, case_id, id) deferrable initially deferred;

create table public.evidence_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id),
  source_id text not null check (length(btrim(source_id)) > 0),
  source_version text not null check (length(btrim(source_version)) > 0),
  case_id uuid,
  attempt_id uuid,
  kind text not null check (kind in ('original_log','reference','guidance','proof')),
  filename text not null,
  bucket_id text not null default 'evidence' check (bucket_id = 'evidence'),
  object_path text not null check (split_part(object_path, '/', 1) = workspace_id::text),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint not null check (byte_size > 0 and byte_size <= 10485760),
  content_type text not null,
  synthetic boolean not null default true check (synthetic),
  provenance jsonb not null,
  uploader_id uuid not null references auth.users(id),
  observed_at timestamptz not null,
  stored_at timestamptz not null default now(),
  foreign key (workspace_id, case_id) references public.cases(workspace_id, id),
  foreign key (workspace_id, case_id, attempt_id) references public.attempts(workspace_id, case_id, id),
  check (attempt_id is null or case_id is not null),
  check (kind <> 'original_log' or (case_id is not null and attempt_id is not null
    and byte_size <= 1048576 and content_type = 'text/plain')),
  unique (workspace_id, id),
  unique (workspace_id, case_id, attempt_id, id),
  unique (workspace_id, case_id, id),
  unique (workspace_id, source_id, source_version),
  unique (bucket_id, object_path)
);

create table public.intakes (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  attempt_id uuid not null,
  original_evidence_id uuid not null,
  delivery_key text not null check (length(btrim(delivery_key)) > 0),
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  manifest jsonb not null,
  supplied_by uuid not null references auth.users(id),
  received_at timestamptz not null default now(),
  foreign key (workspace_id, case_id, attempt_id) references public.attempts(workspace_id, case_id, id),
  foreign key (workspace_id,case_id,attempt_id,original_evidence_id)
    references public.evidence_versions(workspace_id,case_id,attempt_id,id),
  unique (workspace_id, delivery_key)
);

create table public.analysis_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  attempt_id uuid not null,
  snapshot_hash text not null check (snapshot_hash ~ '^[0-9a-f]{64}$'),
  snapshot jsonb not null,
  case_version bigint not null check (case_version > 0),
  requested_by uuid not null references auth.users(id),
  state text not null default 'queued' check (state in ('queued','running','succeeded','failed','historical')),
  output jsonb,
  error_code text,
  created_at timestamptz not null default now(),
  foreign key (workspace_id, case_id, attempt_id) references public.attempts(workspace_id, case_id, id),
  unique (workspace_id, id),
  unique (workspace_id, case_id, id)
);
create unique index one_active_snapshot_run on public.analysis_runs (workspace_id, case_id, snapshot_hash)
  where state in ('queued','running');

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  run_id uuid not null,
  state text not null default 'queued' check (state in ('queued','running','succeeded','failed')),
  lease_until timestamptz,
  lease_token uuid,
  retry_count integer not null default 0 check (retry_count between 0 and 1),
  available_at timestamptz not null default now(),
  foreign key (workspace_id, run_id) references public.analysis_runs(workspace_id, id),
  unique (workspace_id, run_id)
);
create index job_poll on public.jobs (available_at) where state in ('queued','running');

create table public.guidance_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  evidence_id uuid not null,
  guidance_key text not null,
  version text not null check (length(btrim(version)) > 0),
  scope jsonb not null,
  owner_label text not null,
  review_state text not null default 'pending_review' check (review_state in (
    'pending_review','approved','rejected','withdrawn'
  )),
  actual_reviewer_id uuid references auth.users(id),
  acting_role text,
  reviewed_at timestamptz,
  review_reason text,
  valid_from timestamptz not null,
  valid_until timestamptz not null,
  review_due_at timestamptz not null,
  foreign key (workspace_id, evidence_id) references public.evidence_versions(workspace_id, id),
  check (valid_until > valid_from),
  check (review_state <> 'approved' or (
    actual_reviewer_id is not null and reviewed_at is not null
    and acting_role is not null and review_reason is not null and length(btrim(review_reason)) > 0
  )),
  unique (workspace_id, id),
  unique (workspace_id, guidance_key, version)
);

create table public.assignments (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  version integer not null check (version > 0),
  assigned_user_id uuid,
  owner_role text,
  actor_id uuid not null references auth.users(id),
  acting_role text not null,
  reason text not null,
  assigned_at timestamptz not null default now(),
  foreign key (workspace_id, case_id) references public.cases(workspace_id, id),
  foreign key (workspace_id, assigned_user_id) references public.workspace_memberships(workspace_id,user_id),
  unique (workspace_id, id),
  unique (workspace_id, case_id, version)
);

create table public.case_reviews (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  run_id uuid not null,
  decision text not null check (decision in ('Accepted','Corrected','Insufficient')),
  reason text,
  cause_confirmed boolean not null default false,
  findings jsonb not null,
  actor_id uuid not null references auth.users(id),
  acting_role text not null,
  reviewed_at timestamptz not null default now(),
  foreign key (workspace_id, case_id) references public.cases(workspace_id, id),
  foreign key (workspace_id, case_id, run_id) references public.analysis_runs(workspace_id, case_id, id),
  check (decision = 'Accepted' or (reason is not null and length(btrim(reason)) > 0))
);

create table public.milestones (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  attempt_id uuid not null,
  work_cycle integer not null check (work_cycle > 0),
  kind text not null check (kind in ('correction','reprocessing','validation')),
  details jsonb not null,
  actor_id uuid not null references auth.users(id),
  acting_role text not null,
  human_confirmed boolean not null check (human_confirmed),
  action_at timestamptz not null,
  recorded_at timestamptz not null default now(),
  foreign key (workspace_id, case_id, attempt_id) references public.attempts(workspace_id, case_id, id),
  unique (workspace_id, id),
  unique (workspace_id, case_id, id)
);
create table public.milestone_proof (
  workspace_id uuid not null,
  case_id uuid not null,
  milestone_id uuid not null,
  evidence_id uuid not null,
  foreign key (workspace_id,case_id,milestone_id) references public.milestones(workspace_id,case_id,id),
  foreign key (workspace_id,case_id,evidence_id) references public.evidence_versions(workspace_id,case_id,id),
  primary key (workspace_id,milestone_id,evidence_id)
);

create table public.resolution_records (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  attempt_id uuid not null,
  work_cycle integer not null check (work_cycle > 0),
  version integer not null check (version > 0),
  record jsonb not null,
  reuse_state text not null default 'pending_review' check (reuse_state in (
    'pending_review','approved','rejected','withdrawn'
  )),
  resolver_id uuid not null references auth.users(id),
  resolved_at timestamptz not null,
  foreign key (workspace_id,case_id,attempt_id) references public.attempts(workspace_id,case_id,id),
  unique (workspace_id, id),
  unique (workspace_id,case_id,work_cycle,version),
  -- Publishing new learned knowledge is disabled until deferred evaluation is met.
  check (reuse_state <> 'approved')
);

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  assignment_id uuid not null,
  event_key text not null,
  simulated boolean not null default true check (simulated),
  state text not null default 'queued' check (state in ('queued','succeeded','failed')),
  retry_count integer not null default 0 check (retry_count between 0 and 1),
  foreign key (workspace_id,assignment_id) references public.assignments(workspace_id,id),
  unique (workspace_id,event_key,assignment_id)
);

create table public.activity (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id),
  case_id uuid,
  actor_id uuid references auth.users(id),
  acting_role text not null,
  event_type text not null,
  old_value jsonb,
  new_value jsonb,
  reason text,
  created_at timestamptz not null default now(),
  foreign key (workspace_id,case_id) references public.cases(workspace_id,id)
);

-- Membership is looked up from the database, not long-lived JWT role metadata.
alter table public.workspaces enable row level security;
alter table public.workspace_memberships enable row level security;
create policy member_workspaces on public.workspaces for select to authenticated
  using (private.is_member(id));
create policy own_membership on public.workspace_memberships for select to authenticated
  using (user_id = (select auth.uid()));
revoke all on public.workspaces, public.workspace_memberships from anon, authenticated;
grant select on public.workspaces, public.workspace_memberships to authenticated;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'cases','attempts','evidence_versions','intakes','analysis_runs','jobs',
    'guidance_versions','assignments','case_reviews','milestones','milestone_proof',
    'resolution_records','notifications','activity'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format(
      'create policy member_read on public.%I for select to authenticated using (private.is_member(workspace_id))',
      table_name
    );
    execute format('revoke all on public.%I from anon, authenticated', table_name);
    execute format('grant select on public.%I to authenticated', table_name);
  end loop;
end;
$$;

insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('evidence','evidence',false,10485760,array[
  'text/plain','application/json','application/pdf','image/png','image/jpeg'
]);

create policy preserved_member_evidence on storage.objects for select to authenticated
using (
  bucket_id = 'evidence' and exists (
    select 1 from public.evidence_versions e
    where e.bucket_id = storage.objects.bucket_id and e.object_path = storage.objects.name
      and private.is_member(e.workspace_id)
  )
);
-- No anonymous policies or user write policies. Originals remain immutable.
commit;
