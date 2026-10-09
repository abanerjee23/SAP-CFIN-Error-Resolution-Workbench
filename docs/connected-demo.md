# Connected persona demo

This mode connects the original workbench to saved Supabase cases. It is a local synthetic
demo, with the existing persona selector and no new sign-in screen. It is not public authentication.

## Setup

1. Configure the private backend environment from `backend/.env.example` using keys for the
   same Supabase project. Apply migrations in order to a fresh database. For an existing database,
   inspect its schema first: previously applied migrations must not be replayed blindly.
2. Set `LOCAL_DEMO_ENABLED=true`, `LOG_ONLY_ENABLED=true`, `DEMO_WORKSPACE_ID` and
   `DEMO_ACTOR_ID`. Use a synthetic workspace and an existing test account with all four roles:
   `process_owner`, `mdg_process_owner`, `data_operations`, `cfin_exception_manager`.
3. Add `http://127.0.0.1:3011` and `http://localhost:3011` to backend `CORS_ORIGINS`. In `frontend/.env.local`, set
   `NEXT_PUBLIC_WORKBENCH_CONNECTED=true` and `NEXT_PUBLIC_API_URL=http://127.0.0.1:8011`.
4. From `backend`, run `uv run uvicorn cfin.main:app --host 127.0.0.1 --port 8011`.
   From the repository root, run `bash scripts/frontend-local.sh dev --port 3011`.
5. Open `http://127.0.0.1:3011`. The header identifies Connected demo. Only this synthetic
   workspace is accessible through the demo session. Keep service keys and DATABASE_URL server-side.

## Analysis

Upload a synthetic UTF-8 `.txt`, `.log`, `.csv` or `.tsv` file up to 8 KB through the Dashboard's
lower-right upload panel. Choose a file, then select **Upload and analyse**. The panel stays in
place and shows queued, reading, investigation, preparation, retry or failure states from the
saved run. **Open case** appears after the current verified result is available. Navigating
away keeps a compact progress notice available; returning or reloading restores saved progress.
An unfinished analysis is never labelled as a diagnostic category such as cause not established.
The original is saved before a case is created. The initial manager assignment is recorded.
A queued analysis needs an enabled worker; uploading alone does not run a model.
For the complete local demo, set `PAID_MODELS_ENABLED=true` in the private backend environment,
restart the API, and run `uv run python -m cfin.demo_worker` from `backend` in a third terminal.
The command supervises two separate Python worker processes by default. Each verifies the
configured workspace is synthetic and claims only its Error Analysis runs by ID. Separate
processes keep Arize's instrumentation isolated. `--workers 1` restores a single process;
`--once` processes at most one job. The database independently permits at most two active
Error Analysis cases, with one active analysis per case. Legacy and overview runs retain
exclusive execution. Lease ownership, heartbeat expiry, crash recovery, duplicate protection
and budget reservations remain enforced in the database.

The demo workers do not dispatch other workspaces or notifications. Stop the supervisor's
terminal to stop both child processes and automatic model dispatch. Temporary service failures
retry with bounded backoff, up to 30 seconds between polls. Configuration and access failures
stop the worker; inspect the error and saved run before restarting.

For a bounded verification, find the case's `requested_run_id`, then run from `backend`:

```sh
PAID_MODELS_ENABLED=true LOG_ONLY_ENABLED=true uv run python -m cfin.worker --once --run-id <run-uuid>
```

This processes only the named run. Keep the default $1 per-run and $10 monthly budget guards.
The stage deadline cancels a slow call and permits one automatic retry. Retry exhaustion keeps
the original file and displays an explicit failure with a manual retry action. Stage deadlines
and queue wait are different: waiting for an available worker does not consume model time.
The app refreshes the selected case and all active analyses, and shows only the current published analysis. It does not
substitute a sample brief when analysis fails. Model dispatch stays disabled by default.

Arize credentials alone do not enable tracing: set `ARIZE_ENABLED=true` for the worker.
Use `scripts/benchmark-analysis.py` to generate five two-file batches (one to five errors per
file), and add `--execute` to run the real local intake/worker path with tracing. Stop the
automatic demo worker while that targeted benchmark runs. Its incremental report separates
workflow latency, upload-to-result latency, known cost and unresolved reservations. Verify saved
trace IDs independently with `scripts/verify-analysis-traces.py`, then restart the demo worker.

### Latency profiles and comparison runs

The latency experiment adds two explicit profiles without changing the diagnosis model or
its reasoning setting. Configure `ERROR_ANALYSIS_PROFILE` on the API before accepting the
test uploads, and restart the API after changing it:

| Profile | Extraction and case preparation | Reasoning: extraction / diagnosis / preparation |
| --- | --- | --- |
| `baseline` | Original full output contracts | medium / medium / medium |
| `compact` | Compact model outputs; code attaches exact source text, identifiers and maintained route | medium / medium / medium |
| `fast` | Same compact contracts | low / medium / low |

`baseline` remains the repository configuration default. The local demo now selects
`writer_luna`: Luna medium extraction, Sol medium diagnosis and Luna medium writing.
Set `ERROR_ANALYSIS_PROFILE=writer_luna` in `backend/.env` and restart the API and
demo supervisor to reproduce this selection. It replaces the earlier `compact`
selection for new uploads; existing runs retain their saved configuration.
`fast` remains experimental because one file failed extraction on both attempts.
See [measured results](latency-optimization-results.md) and
[model comparison and open reliability issues](model-comparison-results.md).
The database accepts only the explicit
reviewed prompt/model combinations. Each intake and run saves its exact configuration;
the worker follows those immutable settings rather than the API's current preference.
Uncertainty remains visible in the case's cited **Open questions** section when present.

Stop the automatic demo supervisor before running a targeted comparison. From `backend`,
use the installed project environment to run the offline fixture preflight first:

```sh
uv run python ../scripts/benchmark-latency.py --suite latency-trial \
  --expect-profile compact --concurrency 1
```

Without `--execute`, the script validates the fixture envelope and hashes and prints the
planned run; it makes no uploads or model calls. It includes the existing batch files and
harder ambiguity/conflict fixtures. With the API already configured for `compact`, execute:

```sh
uv run python ../scripts/benchmark-latency.py --suite latency-trial \
  --expect-profile compact --concurrency 1 --execute
```

Use `--concurrency 2` to compare paired arrivals with two independent worker processes.
Use `--expect-profile fast` only after restarting the API with that profile. The runner
checks the actual saved prompt and reasoning settings and records observed execution
overlap; asking for two workers does not itself prove concurrent execution. Reuse the
same suite, profile and concurrency to resume its saved runs without creating duplicate
analyses. Use a new suite name only for a deliberate fresh experiment.

Read the emitted report path, then verify those exact trace IDs against Arize. For the
single-worker compact example above:

```sh
uv run python ../scripts/verify-analysis-traces.py \
  --report ../.local-runtime/latency-benchmark/latency-trial-compact-c1/report.json
```

The report separates workflow, queue/startup and upload-to-result latency, durable cost,
unresolved reservations, stage usage and automated quality checks. Trace export receipts
and independent Arize readback are separate evidence. Review every distinct error,
identifiers, citations and uncertainty before treating reduced latency as an improvement;
automated checks alone do not establish semantic quality. Restart the demo supervisor after
the experiment.

To roll back, restart the API with `ERROR_ANALYSIS_PROFILE=baseline`. This changes future
intakes only: existing cases, queued jobs and retries keep their original saved configuration.
Use `--workers 1` for single-worker execution; this does not require removing the database
migration or weakening leases and budget guards.

### Model-only comparison

Migration `202610090008_model_matrix.sql` adds three exact experimental combinations:
`writer_luna` uses Luna medium for writing; `writer_low` uses Sol low for writing;
`all_luna` uses Luna medium for diagnosis and writing. All keep Luna medium extraction
and the existing compact prompts, output schema and display. These names are explicit
opt-ins and do not change the repository default or any existing run.

`scripts/benchmark-model-matrix.py` performs a fresh compact control and these three
candidates. Run it without `--execute` for an offline plan. Stop the automatic demo
supervisor before adding `--execute`; the runner owns a separate loopback API on port
8012 and leaves the normal UI/API configuration untouched. Every file pair is tested
by each profile, rotating profile order between pairs. Two-case concurrency stays fixed.
Stable suite keys resume completed observations without repeating paid calls.

```sh
uv run python ../scripts/benchmark-model-matrix.py --suite model-matrix-20261009 --execute
```

Read each profile's report under `.local-runtime/latency-benchmark/`, verify its traces
with `verify-analysis-traces.py --report ...`, and review facts and uncertainty separately
from structural checks. Individual reports retain the historical baseline comparison;
use the fresh compact results from the same matrix for the new model decision. Restart
the automatic demo supervisor after the comparison. Testing a candidate does not select
it for normal uploads.

## Human actions

Select Olivia to assign the case to a named persona. The assignee can update status and close
the case; Olivia can also manage it. Comments do not move route steps automatically.

For an external approval, select the actual approver in the existing chat control and attach
the email or other evidence. The record distinguishes the uploader from the approver. This is
a human-entered record, not an independently verified external identity.

To generate a demo proof from the repository root:

```sh
uv run --no-project --with pillow python scripts/generate-synthetic-proof.py \
  --case-id <case-uuid> --source-document <source-document-number>
```

The command writes a labelled PNG and suggested closure note under the ignored
`.local-runtime/synthetic-proofs/` folder. It never contacts SAP. Review the generated proof,
open Close case, paste the note and attach that case's PNG. The note includes
`Target document: DEMO-...`; submitting attests successful simulated reprocessing and data validation.
The screenshot, note and closure remain available after reconnecting. Clicking a saved attachment
name downloads its private file bytes.

## Limits

The UI keeps the original illustrative dashboard metrics. Do not present those sample figures
as measured production benefits. The connected demo has no SAP execution, real persona identities,
or production authentication. A browser walkthrough is still required before recording a portfolio demo.
Reopening a closed case is not exposed by this connected flow.
