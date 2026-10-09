# Deployment recipe

**Updated 2 October 2026.** The compatibility release implements the factual log-only workflow and preserves legacy diagnosis records. `LOG_ONLY_ENABLED=false` gates factual intake and dispatch until the additive migration and integration checks are verified on the target database. `PAID_MODELS_ENABLED` is independent. See [BUILD](../BUILD.md) for exact verification and release evidence.

The repository contains Next.js/API/worker container builds and a three-service Railway recipe. No hosted deployment is claimed. Supabase retains database, private evidence and Auth; application containers do not own durable records.

All nine migrations, including `202610020001_log_only.sql`, have been applied to a disposable local PostgreSQL 17 + pgvector 0.8.6 verification database. The rollback-only factual transaction harness and the existing completion harness passed there. This is actual local database evidence, not an applied cloud migration or hosted lifecycle result. The accepted Ireland project retains its separately recorded eight-migration installation until an authorised target deployment applies the new migration.

## Service configuration

Use the repository root as the build context for every service. The Dockerfiles copy `backend`, `frontend` and `fixtures` using repository-relative paths; setting a service root to `backend/` or `frontend/` would break these copies.

| Service | Dockerfile | Start command | Health check | Replicas |
| --- | --- | --- | --- | --- |
| API | `deploy/Dockerfile.backend` | Image default: Uvicorn on `0.0.0.0:${PORT:-8000}` | `/health` | 1 |
| Web | `deploy/Dockerfile.frontend` | Image default: `node server.js` | `/` | 1 |
| Worker | `deploy/Dockerfile.backend` | `python -m cfin.worker` | No HTTP health check | 1 |

The current recipe is [`.railway/railway.ts`](../../.railway/railway.ts), using Railway's generally available TypeScript Infrastructure as Code format. As verified against the official documentation on **2 October 2026**, per-service `railway.json` / `railway.toml` configuration is deprecated, cannot be enabled for new services, and stops being read for existing services on **1 December 2026**. The three `deploy/railway-*.json` files are retained only as historical recipes. [Railway IaC guide](https://docs.railway.com/infrastructure-as-code), [deprecation reference](https://docs.railway.com/config-as-code/reference).

The manifest preserves the Dockerfiles, repository-root context, one replica per service, `ON_FAILURE` with five restart attempts, API/web health checks and the worker command. All services target **EU West Metal / Amsterdam**, identifier **`europe-west4-drams3a`**, confirmed in Railway's [region reference](https://docs.railway.com/deployments/regions). It declares no new database, bucket, volume, domain or repository binding. Supabase remains the durable store.

The official `railway` SDK is pinned to **3.12.0** in `.railway/package.json`; its exported `BuildConfig` and `DeployConfig` types validate the Dockerfile and restart fields. Type checking plus SDK graph validation passed locally. Reproduce that credential-free check with Node 22+:

```sh
npm ci --prefix .railway --ignore-scripts
npm run check --prefix .railway
```

This validation neither contacts Railway nor establishes a hosted configuration. The SDK requires Railway CLI **5.42.1+** for a later cloud plan. Its `ctx.shared` references point to separately configured shared variables; values are never loaded into the local manifest. Supply the referenced server secrets and public settings privately in the intended environment before deployment. The web resource includes only public browser configuration. [Official TypeScript SDK](https://github.com/railwayapp/railway-ts-sdk), [IaC variable reference](https://docs.railway.com/infrastructure-as-code/reference#environment-variables).

When cloud setup is separately authorised, bind the reviewed repository/release at root `/`, establish domains, and use `railway config plan` to inspect the actual environment before applying anything. A project-wide file can propose deletion of omitted managed resources; reconcile existing resources first. Legacy Config as Code services must be migrated before IaC manages them. No Railway sign-in, remote plan, provisioning or deployment has been performed here. [IaC planning and migration](https://docs.railway.com/infrastructure-as-code).

## Variables and browser boundaries

The web service requires these **public build-time** variables:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | Existing Supabase project HTTPS URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Publishable key or legacy anon key |
| `NEXT_PUBLIC_API_URL` | Public HTTPS origin of the API, without a trailing slash |

`deploy/Dockerfile.frontend` declares them as arguments in its builder stage. They enter the browser bundle; changing them requires rebuilding the web image. The browser must be able to reach the API origin, so a Railway private-network hostname is unsuitable here. `next.config.ts` rejects a Supabase secret/service-role key in the public-key variable.

Configure the API and worker with server-side variables from `backend/.env.example`: Supabase URL/publishable key/secret key, OpenAI key, Arize API key/Space ID/project/collector settings, model IDs/effort and budgets. Keep secret keys out of the web service and Docker build arguments. `.dockerignore` excludes local environment files, credentials-bearing runtime configuration, virtual environments and generated reports from the build context. Railway service variables supply runtime values; the backend image never copies `backend/.env`.

The active platform is **Arize AI (Arize AX)** for both evaluations and observability. Preserve the locally configured Default Space and `ARIZE_PROJECT_NAME=cfin-document-error-analysis`; enable `ARIZE_ENABLED` only with the correct server-side key, Space ID and collector endpoint. `OpenAIAgentsInstrumentor` automatically captures OpenAI Agents activity; business commit precedes operational export, and no manual operational traces are created. Native code experiments can export saved software or model-run outputs without fresh provider/judge calls. Galileo and Promptfoo are retired; their retained reports are historical only. See [the Arize setup](local-development.md#arize-automatic-logging-and-evaluations) and [saved-case evaluation CLI](../evals/README.md#durable-saved-case-model-evaluations).

For TLS terminated by the hosting ingress, set Uvicorn `FORWARDED_ALLOW_IPS` to the actual trusted proxy IPs/networks. Uvicorn enables proxy-header processing but defaults to loopback trust; without the correct ingress allowlist, the read API HTTPS guard may see HTTP and reject external requests. Keep the application reachable only through intended ingress and verify the forwarded scheme with a real HTTPS request. Do not blindly use `*` or trust arbitrary client `X-Forwarded-*` headers.

Set `CORS_ORIGINS` on the API to a JSON list containing the exact hosted web origin, for example `["https://your-portal.example"]`. Keep Auth invite-only and configure the corresponding Supabase site/redirect URLs when that hosted origin is established. Membership and selected-role checks continue to run against actual Auth/database records.

Begin with these execution controls on **both** backend services:

```dotenv
LOG_ONLY_ENABLED=false
PAID_MODELS_ENABLED=false
MODEL_AGENT_1=gpt-6-luna
MODEL_AGENT_2=gpt-6.1-sol
MODEL_AGENT_3=gpt-6.1-sol
MODEL_AGENT_4=gpt-6.1-sol
MODEL_REASONING_EFFORT=medium
MODEL_RUN_BUDGET_USD=1.00
MODEL_MONTHLY_BUDGET_USD=10.00
STAGE_TIMEOUT_SECONDS=60
STAGE_MAX_RETRIES=1
```

The API's Agent 4 explanation and worker model execution remain disabled until explicitly enabled. The worker can still process durable **simulated** notifications with paid execution disabled. Factual jobs pin `log-only-v1` workflow/schema and their individual extraction/selection/summary prompt versions when queued. Legacy jobs retain `cfin-specialists-v3` and their earlier responsibilities. Model IDs use Luna for extraction and Sol for selection/summary in the new path. Each actual model invocation requires current registered pricing and a durable reservation; unknown usage keeps the reservation held. Operational runs, evaluation jobs and Agent 4 share the US$10 monthly model allowance. These model limits do not control Railway, Supabase or Arize infrastructure bills. Check the account's current service charges before provisioning against the US$25/month incremental POC planning ceiling, including the US$10 model allowance.

## Release boundaries for the revised flow

The agreed product accepts the supplied log without required mapping/master/playbook inputs, extracts it with Agent 1, selects key evidence with Agent 2 and writes factual bullets with Agent 3. Reviewed historical case/log content feeds Agent 3 only in a separate reference section. Current-case facts come from the current log; agents do not diagnose, suggest fixes or call SAP.

The integrated code supports this behavior. Production acceptance still requires actual target-database transactions, authenticated source reads, scoped machine credentials, reviewed model results, meaningful human records and recovery checks. The portal distinguishes factual summaries from legacy diagnoses and keeps manual assignment available. Existing Agent 4 backlog features remain separate.

Inspect actual queued workflow/schema/prompt versions and saved case behavior. Enable `LOG_ONLY_ENABLED` only after installing and verifying `202610020001_log_only.sql` on the intended database; do not infer schema readiness from configuration-only `/ready` output. Keep machine credentials scoped to explicit workspaces/read capabilities, serve production API traffic over HTTPS, and retain read audit without private payload logging.

## Local containers

`compose.yaml` builds the same three images from the repository root. It reads server variables from `backend/.env`, maps API port 8000 and web port 3000, and overrides the worker's command. To supply the public web build arguments from the already configured frontend file:

```sh
docker compose --env-file frontend/.env.local config --quiet
docker compose --env-file frontend/.env.local up --build
```

Use `config --quiet` to validate without printing resolved secrets. The existing public API default `http://localhost:8000` works for the locally mapped browser ports. Ensure paid mode remains false before starting the worker. These are execution instructions, not a claim that the images or daemon have run successfully.

## Rollout and recovery

1. Record the chosen release, its actual workflow/prompt/schema versions and current database migration state. Do not deploy the earlier flow under the revised product description. The eight legacy migrations are already installed in the existing Ireland project; do not rerun them. The ninth log-only migration must be applied and verified separately. For a fresh project or later upgrade, review the migrations in filename order and apply only unapplied migrations once through an administrator-controlled step. The images and worker do not run schema migrations on startup. Preserve the existing evidence, memberships, audit history and private budget ledger; [the local guide](local-development.md#configure-the-synthetic-cloud-project) lists the required schema.
2. Configure domains, public build variables, server secrets, Amsterdam region and one worker replica. Apply required additive schema changes before starting code that depends on them. Check function names, grants and RLS after an upgrade; preserve the earlier immutable snapshots and outcomes.
3. Deploy the API with factual rollout and paid execution disabled until the target checks pass. `/health` confirms process liveness; `/ready` checks configuration presence and explicitly does not establish verified cloud connectivity. Exercise signed-in reads, a denied workspace, private evidence access and relevant guarded RPCs independently.
4. Build/deploy the web against the actual public API origin. Check sign-in, CORS, case details, overview drilldowns and a fresh tab/session. Confirm public bundles contain no server keys.
5. Start exactly one intended worker. The database's shared model slot fences execution with a **90-second lease**; active case jobs renew every **25 seconds**. Agent 4 shares this slot and has a bounded request timeout. Overlapping old/new worker containers cannot bypass the lease, but avoiding unnecessary worker overlap keeps recovery and costs easier to interpret.
6. Exercise restart/redeployment with saved private evidence and queued work. Inspect actual job, stage-call, notification and audit records. Expired/interrupted requests retain cost reservations; only validated stage checkpoints can be resumed. Late results cannot replace a newer lease or current input snapshot.
7. Keep paid execution disabled until an explicitly authorised bounded test. Inspect the queued workflow and actual stage bindings before running the dedicated factual evaluation path; retained legacy scores cannot establish factual quality. Run model and human workflow checks separately from infrastructure checks. Automatic tracing must remain separate from the authoritative business commit; collector acceptance still needs independent visibility verification.

For rollback, disable `LOG_ONLY_ENABLED` and paid dispatch on API and worker, stop the intended worker and select a recorded application release that is compatible with the current schema and RPC contracts. Keep completed additive migrations and durable records. If an older release requires a previous RPC contract, supply a reviewed forward compatibility migration or redeploy the compatible release; do not drop tables, delete proof or erase audit/budget rows to make old code start. Recheck auth, reads, leases and queue state before restarting the worker. A hosted rollback and persistence drill remains an observed deployment checkpoint.
