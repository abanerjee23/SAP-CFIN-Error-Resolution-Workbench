# Connected pilot demo

The local demo connects a persona selector, uploads, three-agent analysis, private evidence and human workflow commands. It opens without a user login; the backend establishes a session for an existing test account and keeps its Supabase token private. Shared pilots retain normal sign-in. It uses synthetic data and records fictional SAP results. It does not connect to SAP or establish production readiness.

## What has been demonstrated

- A real uploaded original was saved in Supabase Storage and downloaded unchanged; its SHA-256 matched.
- GPT-6 Luna extracted the log. GPT-6.1 Sol classified it as master data and produced the cited case brief through the Agents SDK.
- An authenticated HTTP walkthrough saved seven route steps, approval evidence, implementation evidence, a posting reference and a validated closure. A fresh read returned the closed case and its resolution record.
- The walkthrough rejected early closure and a missing approval decision. Database regression checks additionally cover wrong roles, missing approval/implementation evidence, rejected approval, failed posting, duplicate commands, closure without validation and recovery after a worker fails before producing output.
- A clean three-stage model run completed in **39.6 seconds**, with **8,854 input tokens**, **3,277 output tokens** and **$0.033191** in conservative model cost accounting. This is one synthetic observation, not an average or an invoice.
- Arize acknowledged export of **15 spans** for the clean run. Independent readback in Arize has not yet been verified.

The first run also exposed and helped fix real integration faults: routing context was missing from the worker's snapshot schema, and database publication mishandled an empty result and a JSON comparison. Saved checkpoints allowed recovery without repeating the successful model calls. Its 572 ms recovery time is not first-run model latency.

Evidence: [workflow report](../artifacts/pilot-validation.json), [clean analysis report](../artifacts/pilot-clean-analysis.json), [connected persona API report](../artifacts/persona-demo-validation.json). The automated walkthrough uses one existing synthetic test account with several roles. Its notes explicitly identify automated test decisions; they are not approvals by separate real people.

The connected persona API has also completed a fresh upload-to-closure walkthrough after configuration was restored. It verified all seven route steps, preserved original bytes, saved a resolution and labelled eight action records with simulated roles. That analysis took **41.4 seconds** and recorded **$0.031992** in model cost. Other-workspace requests, unsupported endpoints, early closure and a missing approval decision were rejected. This verifies the HTTP workflow; browser interaction remains unverified because the browser tool could not verify its access policy.

## Start the connected app

1. Configure `backend/.env` and `frontend/.env.local` from their examples. The browser gets only Supabase's publishable key. Keep the service key and OpenAI key in the backend.
2. Apply all migrations in `supabase/migrations/` in filename order. The pilot requires the factual and Error Analysis migrations, plus the pilot completion, failure recovery and approval evidence migrations. Validate them first with `supabase/checks/verify_local.py` against a disposable local PostgreSQL database.
3. Set `LOG_ONLY_ENABLED=true` and `PAID_MODELS_ENABLED=true` only in the configured pilot environment. The durable model limits remain $1 per run and $10 per month. Keep the configured models and verified price registry aligned.
4. Configure `LOCAL_DEMO_ENABLED=true`, `DEMO_WORKSPACE_ID` and `DEMO_ACTOR_ID` in `backend/.env`. Use an existing confirmed Supabase test account in a **synthetic** workspace with `process_owner`, `mdg_process_owner`, `data_operations` and `cfin_exception_manager`. The app opens directly into the saved Case Board. Select Maya, Daniel, Liam or Olivia at the top right; the case dialog includes the same selector.

   Demo access works only from loopback addresses and an explicitly allowed localhost origin. Its opaque browser token permits only the demo's case/evidence routes in the configured workspace; the underlying Supabase session stays on the server. Every action note identifies the simulated role. Real model calls retain the existing cost limits. Set `LOCAL_DEMO_ENABLED=false` for a shared or hosted pilot, where people sign in with their assigned roles. This local mode is not a public demo deployment.
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
2. **AI assistance:** select Daniel Ross at the top right and upload the text in Data. Open the saved case, review the hypothesis and expand a source citation. Open Original log to show the unchanged source.
3. **Human control:** record the MDG approval request, then select Daniel Ross, RTR Process Owner, and record approval with synthetic evidence. Explain that the named personas simulate roles using one isolated test account.
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

To exercise the same local access mode as the persona interface, replace `--actor-id` with `--demo-origin http://127.0.0.1:3011`. This uses the backend-held demo session and also verifies simulated-role attribution on all saved decisions.

The direct authenticated mode requires the backend's existing service credential to establish a session for the supplied confirmed test account. It sends no email, prints no credentials and refuses non-synthetic workspaces. It writes clearly labelled synthetic decisions and closes the case.

## Software validation

The full backend suite passed 810 tests after the persona demo change, with one optional local database check skipped. Two additional synthetic-upload boundary checks also passed. Six example tests, all 13 database migrations and the executable SQL regression checks also passed. Python lint, frontend typechecking, the production build and the offline Railway SDK configuration check passed. The five Promptfoo policy gates passed; these are deterministic checks, not model-quality scores.

## Remaining portfolio acceptance work

- Complete the connected persona browser walkthrough, including upload, role actions and refresh, once browser access is available. The live persona API workflow and restored configuration have been verified.
- Review a representative set of 15–20 synthetic logs with explicit expected classifications and factual claims. The five existing deterministic Promptfoo cases test policy interpretation; they do not measure model quality.
- Review the AI brief with a finance/domain reviewer, record corrections and rerun the same examples after changes.
- Read back the exported Arize trace, record a short demo, and test deployment before sharing a hosted link.

Use **working synthetic prototype** on a CV. Claim measured performance only for recorded tests. Real SAP integration, analyst time savings, independent-user acceptance, broad model quality and production operations remain unproven.
