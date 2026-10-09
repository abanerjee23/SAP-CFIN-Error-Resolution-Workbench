-- Add reviewed latency profiles; existing intakes and run snapshots stay pinned.
begin;

create function private.error_analysis_configuration_supported(prompts jsonb, models jsonb)
returns boolean language sql immutable set search_path='' as $$
 select coalesce(
  (prompts='{"agent1":"error-analysis-extraction-v1","agent2":"error-analysis-v1","agent3":"error-analysis-summary-v1"}'::jsonb
   and models='{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium"}'::jsonb)
  or
  (prompts='{"agent1":"error-analysis-extraction-compact-v2","agent2":"error-analysis-v1","agent3":"error-analysis-summary-compact-v2"}'::jsonb
   and models in (
    '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium","agent1_reasoning_effort":"medium","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"medium"}'::jsonb,
    '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium","agent1_reasoning_effort":"low","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"low"}'::jsonb
   )), false)
$$;
revoke all on function private.error_analysis_configuration_supported(jsonb,jsonb) from public;

-- Change only the configuration allowlist in the existing security-definer intake.
-- Assert the previous definition so an unexpected database version fails closed.
do $migration$
declare definition text; old_guard text;
begin
 select pg_get_functiondef('private.commit_error_analysis_intake_before_workbench(jsonb)'::regprocedure)
 into definition;
 old_guard := $guard$if p->'prompt_versions' is distinct from '{"agent1":"error-analysis-extraction-v1","agent2":"error-analysis-v1","agent3":"error-analysis-summary-v1"}'::jsonb or p->'model_configuration' is distinct from '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium"}'::jsonb then$guard$;
 if (length(definition)-length(replace(definition,old_guard,'')))/length(old_guard) <> 1 then
  raise exception 'Unexpected Error Analysis intake definition; inspect before migration';
 end if;
 execute replace(definition, old_guard,
  $guard$if not private.error_analysis_configuration_supported(p->'prompt_versions', p->'model_configuration') then$guard$);
end $migration$;

commit;
