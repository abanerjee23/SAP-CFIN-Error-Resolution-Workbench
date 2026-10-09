-- General synthetic packs, exact source selection and audited identity/order controls.
-- Prepared migration: applying it is a separate operational step.
begin;

alter table public.cases add column linked_case_id uuid;
alter table public.cases add constraint linked_case_same_workspace
  foreign key (workspace_id,linked_case_id) references public.cases(workspace_id,id);
alter table public.cases add constraint case_cannot_link_itself check (linked_case_id is distinct from id);
create index linked_case_history on public.cases(workspace_id,linked_case_id)
  where linked_case_id is not null;
alter table public.intakes add constraint intake_workspace_id unique (workspace_id,id);

create table public.intake_sources (
  workspace_id uuid not null,
  intake_id uuid not null,
  evidence_id uuid not null,
  filename text not null check (filename in (
    'original-log.txt','manifest.json','source-posting.json','mapping-reference.json',
    'target-master-lookup.json','target-master-query-audit.json',
    'missing-gl-master-playbook.json','owner-directory.json','source-catalogue.json'
  )),
  primary key (workspace_id,intake_id,filename),
  unique (workspace_id,intake_id,evidence_id),
  foreign key (workspace_id,intake_id) references public.intakes(workspace_id,id),
  foreign key (workspace_id,evidence_id) references public.evidence_versions(workspace_id,id)
);
create table public.input_controls (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  case_id uuid not null,
  kind text not null check (kind in ('complete_identity','review_attempt_order','link_case')),
  actor_id uuid not null references auth.users(id),
  acting_role text not null check (acting_role='process_owner'),
  reason text not null check (length(btrim(reason))>0),
  payload jsonb not null,
  recorded_at timestamptz not null default now(),
  foreign key (workspace_id,case_id) references public.cases(workspace_id,id)
);
create index input_controls_case on public.input_controls(workspace_id,case_id,recorded_at,id);
do $$ declare t text; begin
  foreach t in array array['intake_sources','input_controls'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
    execute format('grant select on public.%I to service_role',t);
    execute format('create policy member_read on public.%I for select to authenticated using (private.is_member(workspace_id))',t);
    execute format('create trigger immutable_saved_input before update or delete on public.%I for each row execute function private.preserve_source()',t);
  end loop;
end $$;

-- Preserve the previously saved MD-01 input set without loading local fixture bytes.
insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename)
select i.workspace_id,i.id,i.original_evidence_id,'original-log.txt' from public.intakes i;
insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename)
select i.workspace_id,i.id,e.id,e.filename from public.intakes i
cross join lateral (
  select distinct on (filename) id,filename from public.evidence_versions
  where workspace_id=i.workspace_id and case_id is null
    and provenance->>'input_filename'=filename
    and source_version='1' and source_id in (
      'MD01-file-manifest','MD01-file-source-posting','MD01-mapping',
      'MD01-file-target-master-lookup','MD01-file-target-master-query-audit',
      'MD01-playbook','MD01-file-owner-directory','MD01-file-source-catalogue'
    ) order by filename,stored_at,id
) e where i.manifest->>'scenario_id'='MD-01';

create or replace function private.enqueue(w uuid,c_id uuid,a uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.cases; at_row public.attempts; sn jsonb; hash text;
  run public.analysis_runs; i public.intakes; source_list jsonb; controls jsonb;
begin
  select * into c from public.cases where workspace_id=w and id=c_id for update;
  if c.id is null then raise sqlstate 'PT404' using message='Case not found'; end if;
  if c.linked_case_id is not null then return jsonb_build_object('queued',false,'reason','linked_case_use_canonical_case'); end if;
  if 'linked_input_review_required'=any(c.review_flags) then
    return jsonb_build_object('queued',false,'reason','corrected_canonical_intake_required');
  end if;
  select * into at_row from public.attempts where workspace_id=w and case_id=c_id and id=c.current_attempt_id;
  if c.current_attempt_id is null or not c.attempt_order_known then
    return jsonb_build_object('queued',false,'reason','identity_or_attempt_order_required');
  end if;
  if c.source_system is null or c.source_client is null or c.source_company_code is null
    or c.fiscal_year is null or c.document_number is null or c.target_system is null
    or c.target_client is null or c.interface is null then
    return jsonb_build_object('queued',false,'reason','document_identity_required');
  end if;
  select * into i from public.intakes where workspace_id=w and case_id=c_id
    and attempt_id=c.current_attempt_id order by received_at desc,id desc limit 1;
  if i.id is null or (select count(*) from public.intake_sources
    where workspace_id=w and intake_id=i.id)<>9 then
    return jsonb_build_object('queued',false,'reason','complete_saved_input_pack_required');
  end if;
  select jsonb_agg(jsonb_build_object('evidence',to_jsonb(e),'review',(
      select to_jsonb(rr) from public.reference_reviews rr
      where rr.workspace_id=w and rr.evidence_id=e.id order by rr.version desc limit 1
    )) order by s.filename) into source_list
    from public.intake_sources s join public.evidence_versions e
      on e.workspace_id=s.workspace_id and e.id=s.evidence_id
    where s.workspace_id=w and s.intake_id=i.id;
  select coalesce(jsonb_agg(to_jsonb(ic) order by ic.recorded_at,ic.id),'[]'::jsonb)
    into controls from public.input_controls ic where ic.workspace_id=w and ic.case_id=c_id
      and (ic.kind='complete_identity' or (ic.kind='review_attempt_order'
        and ic.payload->'ordered_attempt_ids' ? at_row.id::text));
  sn:=jsonb_build_object('case_id',c.id,'attempt_id',c.current_attempt_id,
    'input_revision',c.input_revision,'manifest',i.manifest,
    'identity',jsonb_build_object('workspace_id',w,'source_system',c.source_system,
      'source_client',c.source_client,'source_company_code',c.source_company_code,
      'fiscal_year',c.fiscal_year,'document_number',c.document_number,
      'target_system',c.target_system,'target_client',c.target_client,'interface',c.interface),
    'business_context',c.business_context,'attempt',to_jsonb(at_row),
    'context_overlay',controls,'sources',source_list);
  hash:=encode(pg_catalog.sha256(convert_to(sn::text,'UTF8')),'hex');
  select * into run from public.analysis_runs where workspace_id=w and case_id=c_id
    and snapshot_hash=hash and state in ('queued','running');
  if found then return jsonb_build_object('queued',true,'run_id',run.id,'duplicate',true); end if;
  insert into public.analysis_runs(workspace_id,case_id,attempt_id,snapshot_hash,snapshot,
    case_version,input_revision,requested_by)
    values(w,c_id,c.current_attempt_id,hash,sn,c.version,c.input_revision,a) returning * into run;
  insert into public.run_sources(workspace_id,run_id,evidence_id,source_snapshot)
    select w,run.id,(source->'evidence'->>'id')::uuid,source
      from jsonb_array_elements(sn->'sources') source;
  insert into public.jobs(workspace_id,run_id) values(w,run.id);
  update public.cases set requested_run_id=run.id,analysis_status='pending' where id=c_id;
  perform private.audit(w,c.id,a,'process_owner','analysis_queued',null,
    jsonb_build_object('run_id',run.id,'input_revision',c.input_revision),null);
  return jsonb_build_object('queued',true,'run_id',run.id,'snapshot_hash',hash,'duplicate',false);
end $$;

create or replace function private.commit_intake(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid := (p->>'workspace_id')::uuid; a uuid := (p->>'actor_id')::uuid;
  r text := p->>'acting_role'; m jsonb := p->'manifest'; ident jsonb := m->'identity';
  delivery text := private.nonempty(p->>'delivery_key','delivery_key'); payload_hash text;
  legacy_hash text; c public.cases; attempt public.attempts; old_attempt public.attempts;
  intake public.intakes; evidence jsonb; source jsonb; source_row public.evidence_versions;
  queue jsonb; provisional boolean; is_new boolean:=false; historical boolean:=false;
  keys text[]:=array['source_system','source_client','source_company_code','fiscal_year',
    'document_number','target_system','target_client','interface']; k text; sources_hash jsonb;
begin
  perform private.require_actor(w,a,r);
  if r<>'process_owner' then raise insufficient_privilege using message='Process owner intake required'; end if;
  if m->>'synthetic' is distinct from 'true' or ident->>'workspace_id' is distinct from w::text
    or m->>'delivery_key' is distinct from delivery then
    raise sqlstate 'PT422' using message='Synthetic manifest scope mismatch';
  end if;
  foreach k in array keys loop
    if ident->k is not null and jsonb_typeof(ident->k) not in ('string','null') then
      raise sqlstate 'PT422' using message='Identifiers must be strings';
    end if;
    if jsonb_typeof(ident->k)='string' then perform private.nonempty(ident->>k,k); end if;
  end loop;
  if m->>'content_sha256' is distinct from p->'storage'->>'sha256'
    or jsonb_typeof(m->'processing_order') not in ('number','null')
    or coalesce(p->>'input_pack_sha256','') !~ '^[a-f0-9]{64}$'
    or jsonb_typeof(p->'input_sources') is distinct from 'array'
    or jsonb_array_length(p->'input_sources')<>8 then
    raise sqlstate 'PT422' using message='Verified complete synthetic pack required';
  end if;
  if (select count(distinct s->>'filename') from jsonb_array_elements(p->'input_sources') s)<>8 then
    raise sqlstate 'PT422' using message='Exactly one of each saved input file required';
  end if;
  for source in select value from jsonb_array_elements(p->'input_sources') loop
    select * into source_row from public.evidence_versions where workspace_id=w
      and id=(source->>'evidence_id')::uuid and case_id is null and kind in ('reference','guidance');
    if not found or source_row.filename is distinct from source->>'filename'
      or source_row.sha256 is distinct from source->>'sha256'
      or source_row.source_id is distinct from source->>'source_id'
      or source_row.source_version is distinct from source->>'source_version'
      or source_row.provenance->>'input_filename' is distinct from source_row.filename
      or source_row.filename not in ('manifest.json','source-posting.json','mapping-reference.json',
        'target-master-lookup.json','target-master-query-audit.json','missing-gl-master-playbook.json',
        'owner-directory.json','source-catalogue.json') then
      raise sqlstate 'PT422' using message='Saved input source mismatch';
    end if;
  end loop;
  select jsonb_agg(jsonb_build_object('filename',s->>'filename','sha256',s->>'sha256')
    order by s->>'filename') into sources_hash from jsonb_array_elements(p->'input_sources') s;
  legacy_hash:=encode(pg_catalog.sha256(convert_to(jsonb_build_object('manifest',m,
    'sha256',p->'storage'->>'sha256')::text,'UTF8')),'hex');
  payload_hash:=encode(pg_catalog.sha256(convert_to(jsonb_build_object('manifest',m,
    'sha256',p->'storage'->>'sha256','input_sources',sources_hash,
    'input_pack_sha256',p->>'input_pack_sha256')::text,'UTF8')),'hex');
  perform pg_advisory_xact_lock(hashtextextended(w::text||':'||delivery,0));
  select * into intake from public.intakes where workspace_id=w and delivery_key=delivery;
  if found then
    if intake.payload_sha256<>payload_hash then
      if intake.payload_sha256<>legacy_hash or exists(
        select 1 from public.intake_sources old_s join public.evidence_versions e
          on e.workspace_id=old_s.workspace_id and e.id=old_s.evidence_id
        where old_s.workspace_id=w and old_s.intake_id=intake.id
          and old_s.filename<>'original-log.txt' and not exists(
            select 1 from jsonb_array_elements(p->'input_sources') s
              where s->>'filename'=old_s.filename and s->>'sha256'=e.sha256
          )
      ) or (select count(*) from public.intake_sources
            where workspace_id=w and intake_id=intake.id)<>9 then
        raise sqlstate 'PT409' using message='Delivery key content conflict';
      end if;
    end if;
    return jsonb_build_object('intake_id',intake.id,'case_id',intake.case_id,
      'attempt_id',intake.attempt_id,'duplicate',true);
  end if;
  provisional:=exists(select 1 from unnest(keys) x where ident->>x is null);
  if not provisional then
    perform pg_advisory_xact_lock(hashtextextended(w::text||':'||ident::text,1));
    select * into c from public.cases where workspace_id=w and linked_case_id is null
      and source_system=ident->>'source_system' and source_client=ident->>'source_client'
      and source_company_code=ident->>'source_company_code' and fiscal_year=ident->>'fiscal_year'
      and document_number=ident->>'document_number' and target_system=ident->>'target_system'
      and target_client=ident->>'target_client' and interface=ident->>'interface' for update;
  end if;
  if c.id is null then
    insert into public.cases(workspace_id,source_system,source_client,source_company_code,fiscal_year,
      document_number,target_system,target_client,interface,title,description,business_context,
      due_at,review_flags)
    values(w,ident->>'source_system',ident->>'source_client',ident->>'source_company_code',
      ident->>'fiscal_year',ident->>'document_number',ident->>'target_system',ident->>'target_client',
      ident->>'interface','Document exception '||coalesce(ident->>'document_number','identity required'),
      'Original evidence saved; analysis pending',m->'business_context',private.business_due(now(),2),
      case when provisional then array['document_identity_required'] else '{}'::text[] end)
    returning * into c; is_new:=true;
  end if;
  select * into attempt from public.attempts where workspace_id=w and case_id=c.id
    and attempt_key=m->>'attempt_id';
  if not found then
    insert into public.attempts(workspace_id,case_id,attempt_key,processing_at,processing_order,result)
      values(w,c.id,private.nonempty(m->>'attempt_id','attempt_id'),
        (m->>'processing_at')::timestamptz,(m->>'processing_order')::bigint,'failed') returning * into attempt;
  elsif attempt.processing_at is distinct from (m->>'processing_at')::timestamptz
    or coalesce((select manifest->>'processing_order' from public.intakes
      where workspace_id=w and case_id=c.id and attempt_id=attempt.id
      order by received_at,id limit 1),attempt.processing_order::text)
      is distinct from m->>'processing_order' then
    raise sqlstate 'PT409' using message='Attempt identity content conflict';
  elsif attempt.result<>'failed' then
    raise sqlstate 'PT409' using message='A failed intake needs a distinct failed attempt';
  end if;
  evidence:=private.register_evidence(jsonb_build_object('workspace_id',w,'actor_id',a,'acting_role',r,
    'case_id',c.id,'attempt_id',attempt.id,'kind','original_log','storage',p->'storage'));
  insert into public.intakes(workspace_id,case_id,attempt_id,original_evidence_id,delivery_key,
    payload_sha256,manifest,supplied_by) values(w,c.id,attempt.id,(evidence->>'id')::uuid,
    delivery,payload_hash,m,a) returning * into intake;
  insert into public.intake_sources values(w,intake.id,(evidence->>'id')::uuid,'original-log.txt');
  insert into public.intake_sources(workspace_id,intake_id,evidence_id,filename)
    select w,intake.id,(s->>'evidence_id')::uuid,s->>'filename'
      from jsonb_array_elements(p->'input_sources') s;
  select * into old_attempt from public.attempts where id=c.current_attempt_id;
  if c.current_attempt_id is null then
    update public.cases set current_attempt_id=attempt.id,
      attempt_order_known=attempt.processing_order is not null and attempt.processing_at is not null
      where id=c.id;
  elsif old_attempt.id<>attempt.id then
    if attempt.processing_order is null or old_attempt.processing_order is null
      or attempt.processing_at is null or old_attempt.processing_at is null
      or attempt.processing_order=old_attempt.processing_order
      or ((attempt.processing_order>old_attempt.processing_order)<>
          (attempt.processing_at>old_attempt.processing_at)) then
      update public.cases set attempt_order_known=false,input_revision=input_revision+1,
        analysis_status='needs_refresh',diagnosis_status='needs_review',
        review_flags=array_append(array_remove(review_flags,'attempt_order_review_required'),
          'attempt_order_review_required'),version=version+1 where id=c.id;
    elsif attempt.processing_order>old_attempt.processing_order then
      update public.cases set current_attempt_id=attempt.id,attempt_order_known=true,
        business_context=m->'business_context',input_revision=input_revision+1,
        analysis_status='needs_refresh',diagnosis_status='needs_review',unreviewed_new_failure=true,
        review_flags=array_append(array_remove(review_flags,'new_failure_review_required'),
          'new_failure_review_required'),version=version+1 where id=c.id;
    else historical:=true;
    end if;
  elsif not is_new then
    update public.cases set business_context=m->'business_context',input_revision=input_revision+1,
      analysis_status='needs_refresh',diagnosis_status='needs_review',version=version+1 where id=c.id;
  end if;
  -- An alias preserves historical associations. Adopt its original failure explicitly
  -- through a new full pack with complete identity/new source versions before rerunning.
  if 'linked_input_review_required'=any(c.review_flags) and not exists(
    select 1 from public.cases child join public.attempts child_at
      on child_at.workspace_id=child.workspace_id and child_at.id=child.current_attempt_id
    join public.intakes child_i on child_i.workspace_id=child.workspace_id
      and child_i.case_id=child.id and child_i.attempt_id=child_at.id
    where child.workspace_id=w and child.linked_case_id=c.id and not exists(
      select 1 from public.intakes adopted join public.attempts adopted_at
        on adopted_at.workspace_id=adopted.workspace_id and adopted_at.id=adopted.attempt_id
      where adopted.workspace_id=w and adopted.case_id=c.id
        and adopted_at.attempt_key=child_at.attempt_key
        and adopted_at.processing_at=child_at.processing_at
        and adopted.manifest->>'content_sha256'=child_i.manifest->>'content_sha256'
    )
  ) then
    update public.cases set review_flags=array_remove(review_flags,'linked_input_review_required'),
      attempt_order_known=false where id=c.id;
  end if;
  perform private.audit(w,c.id,a,r,'intake_saved',null,
    jsonb_build_object('intake_id',intake.id,'attempt_id',attempt.id,'historical',historical),null);
  if is_new then queue:=private.enqueue(w,c.id,a); end if;
  return jsonb_build_object('intake_id',intake.id,'case_id',c.id,'attempt_id',attempt.id,
    'evidence_id',evidence->>'id','duplicate',false,'historical',historical,'analysis',queue);
end $$;

create function private.intake_control(p jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare w uuid:=(p->>'workspace_id')::uuid; a uuid:=auth.uid(); r text:=p->>'acting_role';
  c_id uuid:=(p->>'case_id')::uuid; c public.cases; target public.cases;
  action text:=p->>'action'; body jsonb:=p->'payload'; ident jsonb; old_c jsonb;
  reason text:=private.nonempty(p->>'reason','reason'); record public.input_controls;
  keys text[]:=array['source_system','source_client','source_company_code','fiscal_year',
    'document_number','target_system','target_client','interface']; k text;
  ordered jsonb; n integer; at_id uuid; ordinal bigint; current_id uuid;
begin
  perform private.require_actor(w,a,r);
  if r<>'process_owner' then raise insufficient_privilege using message='Process owner context review required'; end if;
  -- Consistent UUID lock order prevents mutual provisional-link deadlocks.
  if action='link_case' then
    perform 1 from public.cases where workspace_id=w
      and id in (c_id,(body->>'target_case_id')::uuid) order by id for update;
  end if;
  select * into c from public.cases where workspace_id=w and id=c_id for update;
  if not found then raise sqlstate 'PT404' using message='Case not found'; end if;
  if c.version<>(p->>'expected_version')::bigint then raise sqlstate 'PT409' using message='Case changed'; end if;
  if c.linked_case_id is not null then raise sqlstate 'PT409' using message='Use the canonical linked case'; end if;
  old_c:=to_jsonb(c);
  if action='complete_identity' then
    ident:=body->'identity';
    if ident->>'workspace_id' is distinct from w::text then raise sqlstate 'PT422' using message='Identity workspace mismatch'; end if;
    foreach k in array keys loop
      if jsonb_typeof(ident->k) is distinct from 'string' then
        raise sqlstate 'PT422' using message='Complete identity with string identifiers required';
      end if;
      perform private.nonempty(ident->>k,k);
      if old_c->>k is not null and old_c->>k is distinct from ident->>k then
        raise sqlstate 'PT409' using message='Previously supplied identity cannot be replaced';
      end if;
    end loop;
    if not exists(select 1 from unnest(keys) x where old_c->>x is null) then
      raise sqlstate 'PT422' using message='Case identity is already complete';
    end if;
    perform pg_advisory_xact_lock(hashtextextended(w::text||':'||ident::text,1));
    if exists(select 1 from public.cases other where other.workspace_id=w and other.id<>c.id
      and other.source_system=ident->>'source_system' and other.source_client=ident->>'source_client'
      and other.source_company_code=ident->>'source_company_code' and other.fiscal_year=ident->>'fiscal_year'
      and other.document_number=ident->>'document_number' and other.target_system=ident->>'target_system'
      and other.target_client=ident->>'target_client' and other.interface=ident->>'interface') then
      raise sqlstate 'PT409' using message='This identity already exists; explicitly link its case';
    end if;
    update public.cases set source_system=ident->>'source_system',source_client=ident->>'source_client',
      source_company_code=ident->>'source_company_code',fiscal_year=ident->>'fiscal_year',
      document_number=ident->>'document_number',target_system=ident->>'target_system',
      target_client=ident->>'target_client',interface=ident->>'interface',
      title='Document exception '||(ident->>'document_number'),
      review_flags=array_remove(review_flags,'document_identity_required'),
      input_revision=input_revision+1,analysis_status='needs_refresh',diagnosis_status='needs_review'
      where id=c.id;
  elsif action='review_attempt_order' then
    if 'linked_input_review_required'=any(c.review_flags) then
      raise sqlstate 'PT422' using message='Save corrected canonical intake for linked failures first';
    end if;
    ordered:=body->'ordered_attempt_ids';
    if jsonb_typeof(ordered) is distinct from 'array' or jsonb_array_length(ordered)=0
      or jsonb_array_length(ordered)>1000 then raise sqlstate 'PT422' using message='Ordered attempt list required'; end if;
    select count(*) into n from public.attempts where workspace_id=w and case_id=c.id;
    if jsonb_array_length(ordered)<>n or (select count(distinct value) from jsonb_array_elements_text(ordered))<>n
      or exists(select 1 from jsonb_array_elements_text(ordered) x where not exists(
        select 1 from public.attempts where workspace_id=w and case_id=c.id and id=x.value::uuid
      )) then raise sqlstate 'PT422' using message='Review must order every saved attempt exactly once'; end if;
    for at_id,ordinal in select value::uuid,ordinality from jsonb_array_elements_text(ordered) with ordinality loop
      update public.attempts set processing_order=ordinal where workspace_id=w and case_id=c.id and id=at_id;
      current_id:=at_id;
    end loop;
    update public.cases set current_attempt_id=current_id,attempt_order_known=true,
      business_context=coalesce((select manifest->'business_context' from public.intakes
        where workspace_id=w and case_id=c.id and attempt_id=current_id
        order by received_at desc,id desc limit 1),business_context),
      input_revision=input_revision+1,analysis_status='needs_refresh',diagnosis_status='needs_review',
      unreviewed_new_failure=unreviewed_new_failure or (current_id is distinct from c.current_attempt_id
        and exists(select 1 from public.attempts where id=current_id and result='failed')),
      review_flags=array_remove(review_flags,'attempt_order_review_required') where id=c.id;
  elsif action='link_case' then
    select * into target from public.cases where workspace_id=w and id=(body->>'target_case_id')::uuid for update;
    if not found then raise sqlstate 'PT404' using message='Target case not found'; end if;
    if target.id=c.id or target.linked_case_id is not null
      or target.version<>(body->>'expected_target_version')::bigint then
      raise sqlstate 'PT409' using message='Select the current canonical target case';
    end if;
    foreach k in array keys loop
      if to_jsonb(target)->>k is null or (old_c->>k is not null
        and old_c->>k is distinct from to_jsonb(target)->>k) then
        raise sqlstate 'PT422' using message='Target identity must be complete and match every supplied identifier';
      end if;
    end loop;
    if not exists(select 1 from unnest(keys) x where old_c->>x is null) then
      raise sqlstate 'PT422' using message='Only a provisional identity can link';
    end if;
    if c.status<>'created' or exists(select 1 from public.milestones where workspace_id=w and case_id=c.id)
      or exists(select 1 from public.case_reviews where workspace_id=w and case_id=c.id)
      or exists(select 1 from public.assignments where workspace_id=w and case_id=c.id) then
      raise sqlstate 'PT422' using message='Review existing human progress before linking';
    end if;
    update public.cases set linked_case_id=target.id,analysis_status='unavailable',
      review_flags=array_append(array_remove(review_flags,'document_identity_required'),'linked_to_canonical_case')
      where id=c.id;
    perform private.audit(w,target.id,a,r,'provisional_case_linked',null,
      jsonb_build_object('linked_case_id',c.id),reason);
    update public.cases set version=version+1,input_revision=input_revision+1,
      analysis_status='needs_refresh',diagnosis_status='needs_review',attempt_order_known=false,
      unreviewed_new_failure=true,review_flags=array_append(
        array_remove(review_flags,'linked_input_review_required'),'linked_input_review_required')
      where id=target.id;
  else raise sqlstate 'PT422' using message='Unsupported context control'; end if;
  insert into public.input_controls(workspace_id,case_id,kind,actor_id,acting_role,reason,payload)
    values(w,c.id,action,a,r,reason,body) returning * into record;
  update public.cases set version=version+1 where id=c.id returning * into c;
  perform private.audit(w,c.id,a,r,'input_'||action,old_c,to_jsonb(c),reason);
  return jsonb_build_object('case_id',c.id,'version',c.version,'action',action,
    'linked_case_id',c.linked_case_id,'control_id',record.id,
    'requires_canonical_intake',action='link_case',
    'next_step',case when action='link_case' then
      'Save a corrected full input pack on the canonical identity with unchanged original log/attempt metadata and new source versions, then explicitly review attempt order.' else null end);
end $$;
create function public.cfin_intake_control(payload jsonb)
returns jsonb language sql security invoker set search_path='' as $$
  select private.intake_control(payload);
$$;
revoke execute on function private.intake_control(jsonb) from public,anon,authenticated,service_role;
revoke execute on function public.cfin_intake_control(jsonb) from public,anon,authenticated,service_role;
grant execute on function private.intake_control(jsonb) to authenticated;
grant execute on function public.cfin_intake_control(jsonb) to authenticated;
commit;
