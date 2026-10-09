# CFIN exception portal

Updated 2 October 2026. The portal supports factual log-only cases and preserves the earlier diagnostic workflow through an explicit legacy branch. See the [root README](../README.md), [rebuild plan](../REBUILD_210.md) and [build record](../BUILD.md) for release state, database verification and model-quality evidence.

Next.js 16.3.8 App Router, React 19.3 and TypeScript provide the private workspace. Supabase manages browser sessions; FastAPI and database commands enforce workspace access, acting roles, immutable evidence and current case versions. No model or service-role secrets belong in browser configuration.

## Local setup

Use Node.js 20.9 or later from `frontend/`:

```sh
npm ci
npm run dev
```

Preserve existing `.env.local`. For a fresh checkout, copy `.env.example` only if no environment file exists. Configure `NEXT_PUBLIC_SUPABASE_URL`, the browser-safe `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). Restart after environment changes and rebuild before deployment. Production builds use standalone output.

Open `http://localhost:3000`, then sign in at `/access` with an invited account. Missing configuration, membership or access produces an explicit unavailable state; preview cases never substitute for private records. Follow [local development](../docs/local-development.md) to run the API and worker. New factual intake requires the additive log-only migration and the backend rollout switch; the UI reports a disabled service clearly instead of sending originals into the legacy workflow.

## Factual case workflow

- **Intake:** choose 1–8 UTF-8 `.txt`, `.log`, `.csv` or `.tsv` originals. The initial analysis envelope is 8,192 aggregate bytes and 64 aggregate lines. Validate every file before upload; invalid UTF-8, binary content, blank files and unsupported sizes fail visibly. Base64 carries the exact original bytes, including line terminators and any UTF-8 BOM. Files remain distinct. The user explicitly chooses synthetic or user-supplied provenance. Synthetic workspaces disable the real-evidence option; a real-input workspace requires deliberate administrator provisioning, never relabelling a real log. A generated delivery reference makes a retry idempotent. Optional system/interface/company fields are attributed administrative ownership context, separate from extracted facts.
- **Summary:** a saved factual title, concise statements, uncertainty and extraction limitations. Each statement resolves its saved entry IDs to an exact source version and inclusive line range. The complete originals are expandable within the main case view and downloadable unchanged. The separate full-extraction disclosure includes all saved entries and every saved field. Queued/running, failed and stale replacements remain visible.
- **History:** a separate Related reviewed cases section attributes prior findings, similarities and differences. Historical case/source links re-enter authenticated case reads and select the cited source version. Unperformed, completed-without-citation and unavailable searches have different messages. Completed factual resolutions can propose a versioned knowledge draft with human applicability and reuse limitations, without a cause prerequisite; separate publication criteria, model-evaluation evidence and human approval still gate retrieval. The backend withholds withdrawn or inaccessible historical content.
- **Human review:** Accepted, Corrected or Insufficient reviews reference a saved run. Corrections need an explanation and saved evidence, with no cause label prerequisite. Insufficient reviews record explicit evidence gaps. Starting an investigation requires current human review and an investigation scope; recording actual corrective work separately asks for change authority and proof.
- **Milestones:** attributed findings, action or no-change explanation, observed outcome, scope and gaps accompany proof. Users inspect selected proof, choose truthful upload provenance and attest the record. Reprocessing requires an actual successful attempt, observed time/order and explicit chronology confirmation. Validation uses human-supplied expected/observed comparisons; incomplete records cannot finish resolution. SAP actions are not executed by the portal.
- **Ownership:** manual assignment remains available. A process owner can opt into a versioned default for exact supplied context, a valid member/role, reason and review date within 90 days. Context defaults and legacy cause defaults retain separate meanings.
- **Backlog:** server filters cover case type, analysis availability, factual review and work state. Legacy diagnosis/cause filters are labelled explicitly. Page-level groups and full filtered totals remain distinct; overview counts distinguish provisional cases from known documents. Dates use Europe/London.

The case workflow identifies new records using `workflow_version='log-only-v1'`. Existing legacy cases retain reference approval, diagnosis reviews, simulations and their original human records. The legacy bundle intake remains available in a secondary disclosure; real logs must use truthful provenance and cannot be relabelled synthetic to bypass workspace policy.

## API and access

Typed calls are in `src/lib/api.ts`. New intake calls `POST /api/intakes/log-only`; factual reads use the existing case/evidence routes and allowlisted factual projection. Existing case actions accept dedicated factual review/investigation commands. Read-only machine integrations use the backend's versioned external contract; the browser never handles their credentials.

Requests use bearer authentication, `cache: no-store` and bounded timeouts. Workspace/token changes abort requests and clear scoped data. HTTP 401/403 clears private content and refreshes access. Version conflicts require review rather than blind mutation retries. Evidence is fetched only after authenticated access checks. Existing knowledge publication and evaluation views remain separate from operational case approval.

## Preview and verification

`/preview/factual` exercises the same factual renderer with a clearly labelled, hand-authored synthetic illustration. It includes clickable exact-line citations, the complete original, extraction disclosure and selectable stale/running/failed replacement states. It performs no model call and claims no persisted case or semantic-quality result. `/preview` keeps six earlier visual examples and links to the new factual preview.

```sh
npm run typecheck
npm run build
```

The rebuild's frontend typecheck and production build passed. A browser check of `/preview/factual` verified source navigation to lines 11–13, all 17 original lines, download availability, extraction disclosure and visible stale/failed states, with no browser console errors or warnings. These checks establish interface behavior. Authenticated database journeys and paid model-quality release evidence are tracked separately in the root build record.

The existing neutral theme and bundled Inter Variable font remain in place. No new UI framework or authentication system was introduced. Generated `AGENTS.md` instructions remain unchanged.
