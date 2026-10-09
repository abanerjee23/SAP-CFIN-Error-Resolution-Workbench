# Opt-in factual cloud acceptance

`cfin.factual_live_check` exercises the factual intake and machine read API through an in-process FastAPI HTTP client connected to **real Supabase Auth, Postgres and Storage**. It does not test a hosted URL, reverse proxy or deployed TLS configuration. Implementing or passing the offline tests does not mean this cloud check has run.

Apply and verify all nine migrations before using it. Choose an existing, confirmed account with `process_owner` membership in an explicitly synthetic workspace. The preflight checks the workspace, membership and factual migration columns before creating a session or any cloud records. Authentication reuses the existing-account integration-check flow; it creates a local session without sending email and signs that session out afterward.

Stop other workers for the acceptance window. The default does not invoke a model, but it saves queued factual runs that a separately running worker could otherwise consume. Set up the normal private backend environment locally; do not put keys or bearer tokens in command arguments. The runner uses temporary settings in memory and never changes `.env` or the deployed `LOG_ONLY_ENABLED` flag.

From `backend/`, after cloud changes and this test window are authorized:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.factual_live_check \
  --workspace-id WORKSPACE_UUID \
  --actor-id EXISTING_PROCESS_OWNER_UUID \
  --delivery-prefix factual-acceptance-20261002 \
  --output /absolute/private/path/factual-acceptance-unpaid.json
```

The output path must be new and its parent directory must exist. The report is created with mode `0600`. The default selects the exact authored MD-01 and MAP-01 original logs and one empty original. Only those original files are opened, their reviewed SHA-256 hashes are enforced, and no sidecars or expected answers enter intake. Select only one normal fixture with `--fixture md01-original` or `--fixture map01-original`; at most two distinct normal fixtures are accepted. Empty input is always included. Arbitrary paths, real evidence and expanded fixture sets are unsupported.

The default saves three synthetic cases, their originals and queued jobs. It checks duplicate delivery without a new case, invalid UTF-8 rejection without a new intake or job, complete original JSON and downloaded bytes against their SHA-256 hashes, stable paginated lists, case version conflicts, absent extraction reported honestly, activity/record reads, workspace isolation, missing authentication and original-download scope denial. It hashes complete pre-existing legacy **case rows** before and after; this is not a hash of every related table.

The runner issues two temporary one-day read credentials in memory: one with `cases:read` and `evidence:read`, and one with `cases:read` only. It revokes every issued credential and tests denial afterward, including when a later check fails. Credential IDs and expiration are recorded; tokens, service keys and session credentials are not. `cases:read` can expose raw quoted log text through extraction; `evidence:read` controls independent stored-original access. If `cleanup.credentials_revoked` is false, use the recorded credential IDs and the normal process-owner revocation endpoint immediately. Cancellation also produces a failed, redacted report and continues remaining cleanup. If cancellation interrupts a revocation itself, incomplete cleanup and the credential IDs remain visible. Inspect the cleanup fields even when another check fails.

For a separately authorized paid acceptance run, reuse the delivery prefix and use a new report path:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.factual_live_check \
  --workspace-id WORKSPACE_UUID \
  --actor-id EXISTING_PROCESS_OWNER_UUID \
  --delivery-prefix factual-acceptance-20261002 \
  --output /absolute/private/path/factual-acceptance-models.json \
  --with-models
```

`--with-models` enables factual and paid dispatch only in the runner's settings. It invokes `process_one(target_run_id=...)` for each exact accepted run; it never sweeps unrelated jobs or sends queued notifications. Existing terminal operational runs are reused instead of charged again. The empty-input check must save `no_usable_evidence` without a title or paid stage call. Two normal fixtures allow at most four paid runs: two operational analyses plus two evaluation-only clones queued through the actual evaluation API with one repeat. A repeat invocation creates a new evaluation batch, so do not repeat paid checks casually. The shared database ledger still enforces the configured ceiling of at most $1 per run and $10 per month, including prior spend.

The report includes run IDs, saved outputs, model usage/cost, timestamps, optional Arize tracing export status, structural evaluation checks, and a pending human review packet. Evaluation clones preserve the original snapshots and exclude the selected cases from reusable history. Immediately before queueing clones, the runner hashes the complete selected operational factual case rows, then compares them after clone completion. Any changed business or publication field fails the isolation check; only row counts and hashes are saved for that comparison. No evaluator expectation file is sent to a model or used to manufacture an approval. Review exact originals, extraction, selected statements and historical attribution against reviewed expectations afterward. `quality_baseline_established` remains `false` and human review remains pending even when `structural_pass` is true.

The runner leaves synthetic cases, originals, jobs, evaluation records and access audits saved for review. It does not approve summaries, fabricate human milestones, publish knowledge, remove existing cases or enable the hosted rollout. An unpaid success verifies access and saved-data behavior only; it provides no model-quality evidence. A paid structural success also requires an actual human semantic review and separate hosted/browser verification before any release decision.

Offline runner checks, without cloud access or paid calls:

```sh
cd backend
.venv/bin/pytest tests/test_factual_live_check.py -q
```
