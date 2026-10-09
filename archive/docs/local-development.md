# Local development

**Updated 2 October 2026.** The application implements factual original-only intake → extraction → evidence selection → summary, with reviewed history reaching Agent 3 only and explicit legacy compatibility. New intake/dispatch requires `LOG_ONLY_ENABLED=true` after the ninth additive migration is verified. Paid model execution has its own gate. See [BUILD](../BUILD.md) for software, database and human/model-quality evidence.

The nine-migration schema and rollback-only factual/legacy completion harnesses have been exercised on disposable local PostgreSQL 17 + pgvector 0.8.6. No cloud migration is inferred from that check. Preserve the configured Ireland project's existing records and apply only unapplied migrations through the intended administrator process.

## Existing implementation — recorded status

The earlier application includes general synthetic MD-01/MAP-01 intake, case and human workflow controls, durable notification/stage recovery, backlog snapshots with read-only Agent 4, reviewed-history retrieval/publication gates and a saved-case evaluation queue. The actual demo workspace/roles and private MD-01 intake are configured. Arize automatic tracing and its native twelve-case software experiment passed independent readback with no real provider/judge calls. Two earlier Luna preparations failed validation; neither reached Sol. The retained `cfin-specialists-v3` legacy prompts, factual `log-only-v1` workflow and source-reuse guards have local software coverage. Further real-model execution, quality evaluation, restart testing and the full human journey remain open. Keep software results distinct from model quality.

The user accepted the supplied Ireland project (`eu-west-1`) in place of planned London and created its sole real demo Auth account. That account is bound to the synthetic walkthrough workspace and labelled demo roles. Mapping/playbook approvals and actual human milestones remain pending. The earlier runtime is implemented; paid mode remains `false` until an explicitly authorised bounded test. The factual branch is implemented behind the explicit rollout gate. No successful live quality baseline is claimed. Hosting files are prepared; no hosting account or hosted application has been provisioned by this build.

## Run locally

Prerequisites: Python 3.11+, uv, Node.js 20.9+ and npm. The current workspace already has configured `backend/.env` and `frontend/.env.local`; preserve their values. From the repository root:

```sh
make setup
make api
```

In a second terminal:

```sh
make web
```

The portal is at `http://localhost:3000`; API docs at `http://localhost:8000/docs`. `/health` confirms the API process runs. `/ready` returns 503 until Supabase values are present; even when configured, its response explicitly says `cloud_verified: false`. It is a configuration check, not an integration or persistence test.

The following compatibility details describe retained legacy behavior; new factual intake is described under Factual-flow operating boundaries. Without Supabase configuration, the portal shows a **Workspace not connected** banner and unavailable counts; `/access` contains sign-in. There is no local database fallback. The authenticated board uses `/api/cases/page`, with twenty-five cases per page by default, bounded pagination, text/category/priority/status/diagnosis/object filters and P3 → P2 → P1 priority sorting. Linked provisional aliases remain preserved as history and are excluded from normal distinct-case counts.

**Retained legacy intake:** the form accepts a complete synthetic pack: one UTF-8 log up to 1 MiB and exactly eight declared JSON context/reference files, with a 10 MiB total pack limit. MD-01 and MAP-01 support distinct identities, revised evidence and additional attempts. The unchanged MD-01 shortcut remains available. Validated manifest/source versions and delivery hashes bind the immutable input; uploads cannot supply expected answers, future proof, authenticated review overlays or reference approval. Process owners can complete provisional identity, review ambiguous attempt order and link a duplicate provisional case with explicit reasons. Later failures mark analysis/diagnosis for review; older attempts remain historical.

In the earlier workflow, authorised people review saved references, record structured diagnosis corrections, assign/reassign, block/resume, change priority/due dates with reasons and reopen work. Explicit fictional correction/reprocessing/validation simulations create private proof; a separate human attestation records the milestone. Derived resolution requires the current applicable success, posting validation and complete resolution record. Resolution never grants knowledge reuse approval.

Use `/preview/factual` to inspect the factual case renderer, complete original, exact-line citations and failure states. It is a hand-authored synthetic illustration, not model-quality evidence. `/preview` retains the earlier examples. Existing `/preview/studio` links redirect to `/preview`. The workspace, access screen and preview share one neutral black/white theme with locally bundled Inter and plain headings; there is no theme switch or saved appearance preference. The preview contains six explicitly labelled synthetic design examples, with MD-01 sourced from the original fixture and five illustrative variants. It does not call the API, execute agents, save data or approve references. It is separate from the authenticated board and is never substituted for cloud reads.

For a **fresh checkout only**, copy each example only when its destination does not exist, then configure it locally:

```sh
test -e backend/.env || cp backend/.env.example backend/.env
test -e frontend/.env.local || cp frontend/.env.example frontend/.env.local
```

The current configured files contain these settings; no replacement keys are requested:

| File | Variables |
| --- | --- |
| `backend/.env` | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`; Arize settings below; `CORS_ORIGINS` allows `http://localhost:3000` and `http://127.0.0.1:3000` by default |
| `frontend/.env.local` | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL` |

Use a publishable/legacy anon key in both files. The backend additionally needs a server secret/legacy service-role key for verified storage and worker commands. Keep it and the OpenAI key exclusively in `backend/.env`. Public frontend variables enter browser bundles; the build rejects secret/service-role keys. Both files are gitignored. Restart after changing configuration.

Keep `PAID_MODELS_ENABLED=false` during setup and until a bounded model test is explicitly authorised. The earlier legacy live preparations failed validation; retain that history separately from the new factual baseline reports. `LOG_ONLY_ENABLED` controls only the factual rollout, not permission for paid calls. `make readiness` reports configuration presence, never key values or verified cloud readiness; inspect saved evidence separately. `ARIZE_API_KEY` and `ARIZE_SPACE_ID` are already configured locally in `backend/.env`; no further setup input is requested. Keep keys out of chat, frontend variables and reports.

In a third terminal, `make worker` starts the durable worker. With paid mode false it processes **simulated notifications only**, leaving queued model jobs untouched. It polls every three seconds. The model worker and Agent 4 share one database slot with a ninety-second lease; active case jobs renew every twenty-five seconds. `--once` performs one worker iteration. For an authorised bounded model check, `python -m cfin.worker --once --run-id <queued-run-UUID>` claims only that queued model run and does not process unrelated notifications; it requires paid models configured and, for factual jobs, the factual rollout flag. Omitting `--run-id` allows the next eligible job. Never confuse the targeted run option with human approval or model-quality acceptance.

Validated stages persist after each handoff. Interrupted runs restore immutable inputs and valid checkpoints; invalidated checkpoints are rerun. A retry needs a fresh durable reservation, with at most one retry inside the stage time bound and provider retries disabled. Preparation reuse from a distinct older operational run requires the same workspace/case/attempt, manifest, identity, business context, exact source/review snapshots, context overlay, prompt version, preparation model and effort. The worker rebinds the current run ID and revalidates the cached candidate; reuse provenance stays saved. Evaluation runs do not borrow preparation from operational runs. Changed evidence, reviews, context or configuration prevents reuse, and late output cannot replace a newer lease/current input revision.

## Model baseline

The 2 October factual workflow pins the selected model IDs and stage-specific prompts when queued. The table distinguishes factual roles from retained legacy roles. `MODEL_REASONING_EFFORT=medium` is the default and can be configured to `low`, `medium` or `high`.

| Setting | Configured default | Agreed role | Retained legacy role |
| --- | --- | --- | --- |
| `MODEL_AGENT_1` | `gpt-6-luna` | Extract supplied log content. | Prepare failure evidence. |
| `MODEL_AGENT_2` | `gpt-6.1-sol` | Select key evidence from extraction. | Diagnose with reference data and reviewed history. |
| `MODEL_AGENT_3` | `gpt-6.1-sol` | Write factual bullets and separate related-case references. | Conditionally prepare a resolution brief. |
| `MODEL_AGENT_4` | Empty falls back to `gpt-6.1-sol`. | Existing separate backlog capability. | Explain authorised backlog aggregates. |

The checked-in price adapter is versioned `openai-standard-2026-10-01`. It records input/output estimates of US$0.125/0.50 per million tokens for Luna and US$2.50/10.00 for Sol. The configured ceilings were checked against [official OpenAI pricing](https://developers.openai.com/api/docs/pricing) on 2 October 2026. Reservations remain conservative estimates, not invoices; recheck pricing eligibility before later authorised dispatch.

The adapter uses Standard service and the default US endpoint. Its versioned estimate includes full input plus cache-write charges and assumes no cached-input discount; it is a conservative budget estimate, not an invoice. Each stage reserves a maximum in Postgres before dispatch; unknown usage retains that reservation. `MODEL_RUN_BUDGET_USD` defaults to US$1 and `MODEL_MONTHLY_BUDGET_USD` to US$10 per UTC month across this project. Agent 4 and evaluation jobs consume the same monthly allowance. Lower allowances are enforced; these defaults are maximum caps. Unknown/expired pricing blocks calls. No automatic SDK/provider retry is enabled; the workflow can perform one separately reserved retry. OpenAI's trace export stays disabled while SDK event collection is used by the selected automatic Arize integration. Durable run/stage usage and failures stay in Postgres.

Overview charts/counts remain available with paid execution disabled. They use an authorised immutable five-minute snapshot, distinct known cases, separate provisional cases/attempt counts and backend-issued drilldown groups. The API checks current membership and marks changed/expired snapshots stale. Agent 4 runs only after an explicit request, with bounded read-only case-group tools and validated group/count references. No failure rate is inferred without a matching denominator.

**Existing history/publication implementation:** retrieval combines PostgreSQL text/context matching and a local deterministic concept vector, with no embedding-provider calls. Normal retrieval returns only currently approved accessible versions. Drafts, feedback, publication criteria and exact-version evaluation attestations require authorised human actions. Factual publication requires a reviewed factual summary, meaningful completed work and resolution, current successful reprocessing/validation, pinned proof, explicit applicability/reuse limitations and exact-version human evaluation attestation. It does not require an invented cause or diagnostic category. Legacy publication retains its confirmed-cause requirements. Withdrawal excludes a version immediately, flags affected open cases and prevents in-flight actionable promotion while preserving history. Software experiments do not satisfy publication prerequisites.

## Factual-flow operating boundaries

- Upload 1–8 UTF-8 text originals to `/api/intakes/log-only`, using explicit synthetic or user-supplied provenance. The initial aggregate envelope is 8,192 bytes and 64 lines. Missing business identity remains unknown; application receipt time is not SAP processing time.
- Apply `202610020001_log_only.sql` after the eight legacy migrations. Verify actual storage, guarded queue/publication and read access before enabling `LOG_ONLY_ENABLED` on API/worker. `/ready` reports configuration, not proven connectivity or semantic quality.
- The main case view embeds all preserved originals, exact-version citation navigation and full extraction. Separate factual human review/investigation forms preserve immutable AI output and attributed human evidence.
- Factual history uses bounded authorised prior case/log reads for Agent 3 only. Context-based defaults are administrative configuration, not extracted SAP facts. Legacy simulations remain restricted to compatible synthetic legacy cases.
- Same-run factual recovery requires exact input/configuration bindings. Cross-run factual extraction reuse is disabled. Legacy reuse rules described above retain their old meaning.
- Run the factual rubric/fixture path with held-out expectations, actual usage/cost and explicit budget controls. Human semantic review and representative comprehension measurements remain necessary release evidence.


## Arize automatic logging and evaluations

The latest user decision selects **Arize AI (Arize AX) for both evaluations and observability** and retains the requirement for automatic logging without manual operational trace creation. The integration uses `OpenAIAgentsInstrumentor` to capture native OpenAI Agents activity automatically, buffering operational spans until the business result commits. Export acceptance and independent server/UI visibility are distinct; do not report a verified upload from a local flush result alone. Both were established for the saved integration smoke. See [Arize's official automatic integration](https://arize.com/docs/ax/integrations/llm-providers/openai/openai-agents-sdk-tracing) and [native evaluation SDK guide](https://arize.com/docs/ax/quickstarts/quickstart-write-first-eval).

| Backend setting | Setup/status |
| --- | --- |
| `ARIZE_API_KEY` | Already configured locally; value is never displayed |
| `ARIZE_SPACE_ID` | Configured to the sole accessible Default Space, `U3BhY2U6NTQ5OTM6Y1RPTw==` |
| `ARIZE_PROJECT_NAME` | `cfin-document-error-analysis`, verified project ID `TW9kZWw6MTAxNjA1MTY5NDk6T3d6dw==` |
| `ARIZE_OTLP_ENDPOINT` | Default `https://otlp.arize.com/v1/traces`; match the selected Arize space's region |
| `ARIZE_ENABLED` | Enabled locally; controls operational export, without verifying remote spans |

The saved 1 October 2026 verification records that the configured key returned HTTP 200 from the read-only `/v2/spaces` endpoint, which listed exactly one Default Space with no further page; its Space ID is saved locally. The [automatic smoke report](../../evals/results/arize-auto-smoke-2026-10-01.json) records `export_acknowledged` plus independently verified API readback for trace `1a9f863fdf4113c1c62c9499aafa5f3f`: all five SDK-generated spans and 34 captured attributes matched for IDs/hierarchy, correlation, model, prompt, response and synthetic token usage. The smoke used one local HTTP fake, zero actual provider calls and no operational case changes.

The 1 October 2026 [native experiment report](../../evals/results/arize-native-gates-2026-10-01.json) records `verified_existing` for twelve saved records, 96/96 software scores and twelve independently verified automatic task traces. One dataset/experiment was created; final format/readback checks created no duplicate experiment or real provider/judge calls. Arize's SDK generates a separate experiment trace project, whose identity is recorded in the report. See [the evaluation guide](../evals/README.md#arize-automatic-logging-and-native-experiments) for offline diagnostics and read-only experiment verification. No further key/Space ID setup action is needed. A successful traced operational model analysis remains open. These are dated integration observations; no remote status was rechecked for this documentation revision. Local reports are gitignored and may be absent from fresh checkouts.

Galileo and Promptfoo are retired from the active evaluation/observability paths. Earlier Galileo verification remains in [the implementation history](implementation-log.md#1-october-2026--corrected-galileo-destination-and-automatic-logging), including its twelve-record/96-score experiment and local-fake automatic trace; the earlier Promptfoo run is historical software evidence only. Those reports do not verify Arize or model quality. Keep the original saved observations/reports intact; no manual backfill is created for either failed Luna run.

## Configure the synthetic cloud project

1. Use the user-accepted Ireland project (`eu-west-1`), which replaces the original London (`eu-west-2`) plan. Review its current plan against the US$25 monthly incremental ceiling and US$10 model allowance before creating resources. No plan upgrade is authorised by this code. [Official Supabase pricing](https://supabase.com/pricing) is the source to recheck; pricing is not hardcoded into this project.
2. Disable public self-sign-up and anonymous sign-ins. Use the real email/password demo account created by the user. Configure local Auth origins/redirects as needed. This increment contains no application account-creation, invitation-sending or password-setting workflow.
3. All eight required migrations were recorded as installed on 1 October 2026 in the existing Ireland project, in filename order: `202609300001_foundation.sql`, `202610010001_workflow.sql`, `202610010002_intake.sql`, `202610010003_insights_knowledge.sql`, `202610010004_completion.sql`, `202610010005_evaluations.sql`, `202610010006_rpc_guards.sql` and `202610010007_owner_rules.sql`. Their SQL-editor execution reported **Success**. Eleven final read-only checks verified 14 new tables with RLS, zero anonymous reads/direct browser writes, 26 new RPCs and zero browser access to worker-only RPCs. **Do not rerun applied migrations** on this project. For factual support, apply the new `202610020001_log_only.sql` once after these eight, then run the relevant guarded-command checks. For a fresh project, apply all nine once in filename order and inspect failures. They require managed Supabase Auth/Storage, including pgvector for history ranking; they are not a standalone PostgreSQL bootstrap. Installation/grant inspection does not establish the full live lifecycle journey.
4. The actual demo account's bootstrap has already been applied on this project. For a fresh project, set its actual activated Auth UUID in `supabase/bootstrap-demo.sql` and run as administrator. This binds explicitly labelled demo roles; one person exercising several roles is not independent signoff. Browser writes remain denied; guarded RPCs enforce roles, current versions and human attestations.
5. Start both applications and sign in with the account you created. Existing live reports verify actual-member/foreign-workspace reads, anonymous table denial, private evidence bytes/foreign denial, direct writes and worker/budget fences. A separate account with no memberships was not supplied/created, and process-restart persistence remains open.

No cloud resource is provisioned by `make setup` or application startup. The nine allowed MD-01 inputs were uploaded privately through the real intake path; expected answers and future proof remain separate. Pending mapping/playbook versions stay pending until an actual authorised reviewer approves their exact versions. See [the fixture guide](fixtures.md).

## Software checks

```sh
make check
```

The final 2 October full-build check passed **767 backend tests in 10.52 seconds, with no skips**, including the actual local PostgreSQL harness, plus backend/example Ruff and six external-consumer tests. Reproduce the database-inclusive backend check with `CFIN_POSTGRES_CONTAINER=cfin-rebuild-verification LOG_ONLY_ENABLED=false PAID_MODELS_ENABLED=false .venv/bin/pytest -q` from `backend`, after starting a disposable compatible PostgreSQL container. See the [software report](../../evals/results/full-build-software-2026-10-02.json). Without that variable, the database execution test is explicitly skipped.

The 1 October 2026 earlier-workflow build recorded **472 backend tests and Ruff**. Frontend **TypeScript and production compilation passed** at that checkpoint. Backend checks cover general intake/order/aliases, MD/MAP routing, citations, human corrections and proof, owner rules, paginated snapshots/history/evaluation status, stage reuse/retry, notifications, shared budgets and automatic tracing/evaluations. SQL and PL/pgSQL bodies are parsed. The earlier twelve-case software checks passed 96/96 gates and 170/170 scripted replays. `make eval-gates` and `make eval-replay` save reports under `evals/results`; neither calls an LLM or approves operational evidence. Older counts describe historical revisions in the implementation record. These dated counts are not a newly run suite; see [BUILD](../BUILD.md) for later verification. This documentation update makes no model calls.

HTTP/provider fakes and SQL parsing do not verify Supabase or model quality. Separately, 1 October 2026 evidence recorded 56 HTTP checks and 17 rollback-only SQL groups, with evidence in [live-isolation-2026-10-01.json](../../evals/results/live-isolation-2026-10-01.json) and [live-transactions-2026-10-01.json](../../evals/results/live-transactions-2026-10-01.json). SQL covered 63 direct INSERT/UPDATE/DELETE denials and exact restoration of the existing queue after lease/budget probes. The HTTP report's separate membership-free account and REST INSERT checks are explicitly unrun. Human semantic review, successful live quality baseline, acceptance thresholds and throughput remain unmeasured.

The macOS environment used during the first check repeatedly marked uv's editable `.pth` file hidden, causing Python to skip it and tests to fail imports. The checked-in test configuration now declares the standard `src` path, and the API run command uses Uvicorn's explicit `--app-dir src`, so both run reliably without the editable path hook. For direct Python imports outside these commands, `ls -lO backend/.venv/lib/python*/site-packages/*cfin*.pth` identifies the flag; clearing it with `chflags nohidden` on that specific environment file restores the editable import. A normal non-editable package installation also avoids this environment issue.

## Remaining release evidence

The factual intake, three-agent worker, durable publication, portal/source navigation, human investigation controls, context ownership, reviewed-history publication and versioned machine reads are implemented. Local tests exercise original preservation, access and scope boundaries, history withdrawal, stage recovery, honest failures and legacy compatibility. The disposable PostgreSQL harness executes the actual guarded functions; this does not establish managed Supabase Auth/Storage or hosted recovery.

Next, verify the additive migration and exact saved originals through the intended cloud service, then run the authorised bounded model slice. Review actual outputs for omissions, factual fidelity, selection, uncertainty, useful summaries and historical attribution. The saved-output report includes a pending human review packet with source/model/prompt/rubric bindings and empty assessment/measurement fields. Real samples, human-approved expectations, acceptance thresholds and reader-effort measurements remain outstanding. Earlier failed Luna runs and software success cannot satisfy those gates.

The **Evaluations** portal and [live evaluation CLI](../evals/README.md#durable-saved-case-model-evaluations) retain workflow-version-aware saved-run execution. Factual reports use the dedicated rubric and keep pending semantic review separate from code validation. They remain isolated from operational promotion and gated by paid mode. Exporting saved outputs can contact Arize even without a fresh model call. Keep paid execution disabled until a bounded test is explicitly authorised. Local Docker images built and API health/OpenAPI plus the factual preview returned HTTP 200. The final frontend container also passed citation navigation with the referenced original lines visible and no console errors; see the [saved production-container check](../../evals/results/factual-production-citation-2026-10-02.png). The development app remains on port 3000; the container check used port 3001. Hosted persistence, worker restart and rollback still require their own evidence; see [deployment](deployment.md). The new cloud migration and bounded provider test remain pending until separately confirmed. No human approval or measured quality is inferred from this documentation revision.
