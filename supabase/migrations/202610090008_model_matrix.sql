-- Authorised model-only experiment; prompts, layout and previous runs stay unchanged.
begin;

create or replace function private.error_analysis_configuration_supported(prompts jsonb, models jsonb)
returns boolean language sql immutable set search_path='' as $$
 select coalesce(
  (prompts='{"agent1":"error-analysis-extraction-v1","agent2":"error-analysis-v1","agent3":"error-analysis-summary-v1"}'::jsonb
   and models='{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium"}'::jsonb)
  or
  (prompts='{"agent1":"error-analysis-extraction-compact-v2","agent2":"error-analysis-v1","agent3":"error-analysis-summary-compact-v2"}'::jsonb
   and models in (
    '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium","agent1_reasoning_effort":"medium","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"medium"}'::jsonb,
    '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium","agent1_reasoning_effort":"low","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"low"}'::jsonb
,
    '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6-luna","reasoning_effort":"medium","agent1_reasoning_effort":"medium","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"medium"}'::jsonb,
    '{"agent1":"gpt-6-luna","agent2":"gpt-6.1-sol","agent3":"gpt-6.1-sol","reasoning_effort":"medium","agent1_reasoning_effort":"medium","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"low"}'::jsonb,
    '{"agent1":"gpt-6-luna","agent2":"gpt-6-luna","agent3":"gpt-6-luna","reasoning_effort":"medium","agent1_reasoning_effort":"medium","agent2_reasoning_effort":"medium","agent3_reasoning_effort":"medium"}'::jsonb
   )), false)
$$;
revoke all on function private.error_analysis_configuration_supported(jsonb,jsonb) from public;

commit;
