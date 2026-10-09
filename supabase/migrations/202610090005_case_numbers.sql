-- Stable display references; UUIDs remain the identity for relationships and APIs.
begin;
lock table public.cases in access exclusive mode;

alter table public.cases add column case_number text;
create sequence private.case_number_sequence as bigint no cycle;
revoke all on sequence private.case_number_sequence from public,anon,authenticated,service_role;

-- This is display metadata, not an edit to the saved workflow or analysis input.
-- The transaction's table lock prevents writes while this one trigger is disabled;
-- rollback also restores the trigger if any part of the migration fails.
alter table public.cases disable trigger case_updated_at;
with numbered as (
 select id,created_at,row_number() over (order by created_at,id) as ordinal
 from public.cases
)
update public.cases c
set case_number='CFIN-'||to_char(n.created_at at time zone 'UTC','YYYY')||'-'||
 lpad(n.ordinal::text,greatest(6,length(n.ordinal::text)),'0')
from numbered n where n.id=c.id;
alter table public.cases enable trigger case_updated_at;

-- The first nextval is count + 1, including an empty database's first case.
select setval('private.case_number_sequence'::regclass,
 (select count(*)+1 from public.cases),false);
alter table public.cases alter column case_number set not null;
alter table public.cases add constraint cases_case_number_format
 check(case_number ~ '^CFIN-[0-9]{4}-[0-9]{6,}$');
alter table public.cases add constraint cases_case_number_key unique(case_number);

-- A private trigger is the only allocator: callers cannot choose or rewrite a
-- reference, and PostgreSQL's sequence serializes allocations across transactions.
-- No browser/service role receives direct sequence or function privileges.
create function private.assign_case_number() returns trigger
language plpgsql security definer set search_path='' as $$
declare ordinal text;
begin
 if tg_op='INSERT' then
  if new.case_number is not null then
   raise sqlstate 'PT422' using message='Case number is assigned automatically';
  end if;
  ordinal:=nextval('private.case_number_sequence'::regclass)::text;
  new.case_number:='CFIN-'||to_char(new.created_at at time zone 'UTC','YYYY')||'-'||
   lpad(ordinal,greatest(6,length(ordinal)),'0');
 elsif new.case_number is distinct from old.case_number then
  raise sqlstate 'PT409' using message='Case number is immutable';
 end if;
 return new;
end $$;
revoke all on function private.assign_case_number() from public,anon,authenticated,service_role;
create trigger case_number_assignment before insert or update of case_number on public.cases
 for each row execute function private.assign_case_number();

comment on column public.cases.case_number is
 'Immutable display reference: CFIN, UTC creation year, and a global sequence. UUID remains the API identity; sequence gaps are expected.';
commit;
