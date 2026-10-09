-- Run as the project administrator AFTER both migrations, only in the isolated POC.
-- Replace NULL with the UUID of the actual activated Auth account. This is not an invite.
-- One real person exercises labelled demo roles; this is not independent signoff.
begin;
do $$
declare
  demo_actor_id uuid := NULL;
  demo_workspace_id uuid;
begin
  if demo_actor_id is null or not exists (select 1 from auth.users where id=demo_actor_id) then
    raise exception 'Set demo_actor_id to the actual activated Auth account UUID';
  end if;
  select workspace_id into demo_workspace_id from public.workspace_memberships
    where user_id=demo_actor_id and workspace_id in (
      select id from public.workspaces where name='CFIN synthetic walkthrough'
    ) limit 1;
  if demo_workspace_id is null then
    insert into public.workspaces(name) values ('CFIN synthetic walkthrough')
      returning id into demo_workspace_id;
    insert into public.workspace_memberships(workspace_id,user_id,roles)
      values (demo_workspace_id,demo_actor_id,array[
        'process_owner','mapping_owner','master_data_owner','finance_owner','validator'
      ]);
  end if;
  raise notice 'Demo workspace: %; actual actor: %',demo_workspace_id,demo_actor_id;
end $$;
commit;
