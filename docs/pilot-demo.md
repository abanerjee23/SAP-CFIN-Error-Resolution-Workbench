# Connected pilot demo

The pilot connects sign-in, uploads, three-agent analysis, private evidence and human workflow commands. It uses synthetic data and records fictional SAP results. It does not connect to SAP or establish production readiness.

## What has been demonstrated

- A real uploaded original was saved in Supabase Storage and downloaded unchanged; its SHA-256 matched.
- GPT-6 Luna extracted the log. GPT-6.1 Sol classified it as master data and produced the cited case brief through the Agents SDK.
- An authenticated HTTP walkthrough saved seven route steps, approval evidence, implementation evidence, a posting reference and a validated closure. A fresh read returned the closed case and its resolution record.
- The walkthrough rejected early closure and a missing approval decision. Database regression checks additionally cover wrong roles, missing approval/implementation evidence, rejected approval, failed posting, duplicate commands, closure without validation and recovery after a worker fails before producing output.
- A clean three-stage model run completed in **39.6 seconds**, with **8,854 input tokens**, **3,277 output tokens** and **$0.033191** in conservative model cost accounting. This is one synthetic observation, not an average or an invoice.
- Arize acknowledged export of **15 spans** for the clean run. Independent readback in Arize has not yet been verified.

The first run also exposed and helped fix real integration faults: routing context was missing from the worker's snapshot schema, and database publication mishandled an empty result and a JSON comparison. Saved checkpoints allowed recovery without repeating the successful model calls. Its 572 ms recovery time is not first-run model latency.

Evidence: [workflow report](../artifacts/pilot-validation.json), [clean analysis report](../artifacts/pilot-clean-analysis.json). The automated walkthrough uses one existing synthetic test account with several roles. Its notes explicitly identify automated test decisions; they are not approvals by separate real people.

## Start the connected app

1. Configure `backend/.env` and `frontend/.env.local` from their examples. The browser gets only Supabase's publishable key. Keep the service key and OpenAI key in the backend.
2. Apply all migrations in `supabase/migrations/` in filename order. The pilot requires the factual and Error Analysis migrations, plus the pilot completion, failure recovery and approval evidence migrations. Validate them first with `supabase/checks/verify_local.py` against a disposable local PostgreSQL database.
3. Set `LOG_ONLY_ENABLED=true` and `PAID_MODELS_ENABLED=true` only in the configured pilot environment. The durable model limits remain $1 per run and $10 per month. Keep the configured models and verified price registry aligned.
4. Use an existing Supabase account with membership in a **synthetic** workspace. The walkthrough needs `process_owner`, `mdg_process_owner` and `data_operations`; `cfin_exception_manager` can assign owners. A real multi-user pilot should allocate these roles to the appropriate people.
5. Run the API, worker and web app in separate terminals using the README commands. For an isolated demo, scope the worker:

```bash
cd backend
uv run python -m cfin.worker --workspace-id YOUR_SYNTHETIC_WORKSPACE_UUID
```

That worker processes only Error Analysis cases in the selected workspace. It does not process legacy jobs or other workspaces. Keep the worker running so new uploads progress automatically.

On an iCloud-managed Desktop, keep the Python environment outside the synced folder if imports stall:

```bash
cd backend
UV_PROJECT_ENVIRONMENT=/tmp/cfin-backend-runtime uv sync --frozen --group dev
UV_PROJECT_ENVIRONMENT=/tmp/cfin-backend-runtime uv run python -m cfin.worker --workspace-id YOUR_SYNTHETIC_WORKSPACE_UUID
```

The current local test uses API port **8011** and frontend port **3011** to avoid another app on port 8000. Set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8011` for that frontend and include port 3011 in backend `CORS_ORIGINS`.

For the existing cloud project's upgrade, some old constraint names were already absent. The factual migration was applied with `DROP CONSTRAINT IF EXISTS`; its resulting schema is the same. Private read tables and taxonomy access also received explicit RLS protection. No original log or legacy case was deleted.

## A three-minute walkthrough

Prepare the analysis before recording; mention the observed analysis time instead of implying it is instantaneous.

1. **Problem:** show the fictional [master-data log](../fixtures/pilot/master-data-log.txt). Explain how a finance analyst must interpret the error, find an owner and coordinate a safe change.
2. **AI assistance:** upload the text in Data. Open the saved case, review the hypothesis and expand a source citation. Open Original log to show the unchanged source.
3. **Human control:** record the MDG approval request, then switch to the test account's RTR role and record approval with synthetic evidence. Explain that role switching is available because this test account holds several roles.
4. **Resolution:** record implementation, attach evidence, give the reprocessing go-ahead, then use Data Operations to record the fictional posting result and reference. Attach validation evidence and close the case.
5. **Persistence:** refresh and reopen the case. Show the saved decisions, files and resolution. State clearly that the SAP result is simulated.

For rejected approval or failed posting, show that the case becomes blocked and cannot close. An exception manager can assign further investigation; resuming an escalated route is outside this narrow pilot.

The replayable authenticated HTTP check is available for a newly analysed synthetic master-data case:

```bash
cd backend
uv run python -m cfin.pilot_check \
  --api-url http://127.0.0.1:8011 \
  --workspace-id YOUR_SYNTHETIC_WORKSPACE_UUID \
  --actor-id YOUR_EXISTING_TEST_ACCOUNT_UUID \
  --case-id YOUR_NEW_ANALYSED_CASE_UUID \
  --output ../evals/results/pilot-workflow.json
```

It requires the backend's existing service credential to establish a session for the supplied confirmed test account. It sends no email, prints no credentials and refuses non-synthetic workspaces. It writes clearly labelled synthetic decisions and closes the case.

## Software validation

The full backend suite passed 793 tests. After adding workspace-scoped worker coverage, 22 focused workflow tests passed, including the two new scope checks. Six example tests, all 13 database migrations and the executable SQL regression checks also passed. Python lint, frontend typechecking, the production build and the offline Railway SDK configuration check passed. The five Promptfoo policy gates passed; these are deterministic checks, not model-quality scores.

## Remaining portfolio acceptance work

- Complete the signed-in browser walkthrough, including upload, role actions and refresh, with the intended demo user.
- Review a representative set of 15–20 synthetic logs with explicit expected classifications and factual claims. The five existing deterministic Promptfoo cases test policy interpretation; they do not measure model quality.
- Review the AI brief with a finance/domain reviewer, record corrections and rerun the same examples after changes.
- Read back the exported Arize trace, record a short demo, and test deployment before sharing a hosted link.

Use **working synthetic prototype** on a CV. Claim measured performance only for recorded tests. Real SAP integration, analyst time savings, independent-user acceptance, broad model quality and production operations remain unproven.
