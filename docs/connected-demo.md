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

Upload a synthetic UTF-8 `.txt`, `.log`, `.csv` or `.tsv` file up to 8 KB through Data.
The original is saved before a case is created. The initial manager assignment is recorded.
A queued analysis needs an enabled worker; uploading alone does not run a model.
For the complete local demo, set `PAID_MODELS_ENABLED=true` in the private backend environment,
restart the API, and run `uv run python -m cfin.demo_worker` from `backend` in a third terminal.
This worker verifies the configured workspace is synthetic and claims only its Error Analysis
runs by ID. It does not dispatch other workspaces or notifications. Stop that terminal to stop
automatic model dispatch. Temporary service failures retry with bounded backoff, up to 30 seconds between polls.
Configuration and access failures stop the worker; inspect the error and saved run before restarting.

For a bounded verification, find the case's `requested_run_id`, then run from `backend`:

```sh
PAID_MODELS_ENABLED=true LOG_ONLY_ENABLED=true uv run python -m cfin.worker --once --run-id <run-uuid>
```

This processes only the named run. Keep the default $1 per-run and $10 monthly budget guards.
The app refreshes the selected case and shows only the current published analysis. It does not
substitute a sample brief when analysis fails. Model dispatch stays disabled by default.

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
