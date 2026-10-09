-- Test-only Supabase shape for a disposable PostgreSQL database. Never apply in a deployed project.
do $$ begin if not exists(select 1 from pg_roles where rolname='anon') then create role anon nologin; end if; if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if; if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if; end $$;
create schema auth;
create schema storage;
create schema extensions;
create table auth.users(id uuid primary key default gen_random_uuid(),email text,email_confirmed_at timestamptz,created_at timestamptz not null default now());
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
create function auth.role() returns text language sql stable as $$ select coalesce(nullif(current_setting('request.jwt.claim.role',true),''),current_user) $$;
grant usage on schema auth,storage,extensions to anon,authenticated,service_role;
grant execute on function auth.uid(),auth.role() to anon,authenticated,service_role;
create table storage.buckets(id text primary key,name text not null,public boolean,file_size_limit bigint,allowed_mime_types text[]);
create table storage.objects(id uuid primary key default gen_random_uuid(),bucket_id text references storage.buckets(id),name text not null,metadata jsonb,unique(bucket_id,name));
alter table storage.objects enable row level security;
grant select on storage.objects to authenticated;
alter default privileges in schema public grant all on tables to service_role;
insert into auth.users(id,email,email_confirmed_at) values('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','isolated-test@example.invalid',now());
