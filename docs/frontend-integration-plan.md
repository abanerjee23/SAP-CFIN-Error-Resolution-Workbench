# Connect the approved frontend

## Boundary

Keep the current WorkbenchApp, four tabs, persona selector, case table, case workspace,
summary sections, typography and styling. Connect existing controls to saved records.
Do not replace the interface, add a sign-in screen, change model prompts or alter route policy.
The frozen original remains available at `product-design-freeze-v1`.

Abhinav authorised planning and starting these connection fixes. The work is on
`codex/preserve-design-integration`; the frozen product on `main` remains available.

## Delivery sequence

| Step | Work | Acceptance evidence |
| --- | --- | --- |
| 1. Connection foundation | Local synthetic session; upload receipt; saved-case loading; original-file readback; cited-analysis adapter. | Session isolation, unchanged original bytes, stable retry receipt, complete pagination, no invented or stale analysis. |
| 2. Existing screen bindings | Replace browser-local data access in the existing components with the connection adapter. Keep drafts on failed saves; show success only after server confirmation. | Same layout and styles; upload creates a saved case; published analysis appears in the current Summary; refresh retains it. |
| 3. Human actions and evidence | Persist ordinary comments, message-linked file bytes, external approval identity, explicit reassignment, status changes and closure. | Actor attribution, access checks, required evidence, optimistic concurrency, rejected actions leave no partial milestone. |
| 4. Workflow verification | Run master-data, mapping, rejection and unclassified journeys through this frontend. | Browser screenshots and case/evidence readback; explain synthetic SAP evidence and actual model usage separately. |

## Implemented foundation

- A local session endpoint is disabled by default. When explicitly enabled, it permits only
  loopback requests from a configured local origin and only one synthetic workspace.
- The browser receives an opaque capability. The Supabase session stays on the server;
  membership and workspace scope are checked on every request.
- The connection adapter uploads unchanged UTF-8 logs with a caller-retained delivery key,
  reads all case pages, downloads original bytes and verifies their SHA-256 hashes.
- The brief adapter maps saved facts and hypotheses to exact original line citations. It does
  not invent a brief for pending/failed analysis or choose a different resolution route.
- Fixed a snapshot compatibility error: the database includes `routing_context`, but the
  restored Python snapshot schema rejected that field. The field is now accepted without
  changing model prompts or routing rules.
- The UI has not yet been switched to the adapter. This foundation is not an end-to-end release.

## Decision needed before action binding

The local demo permits closure when the owner or manager supplies a note and a file.
The documented product workflow requires approval, remediation, reprocessing and posting
validation first. Abhinav has been asked which behavior the connected product must enforce.
Do not silently decide this while wiring the API.

The existing chat also permits recording an external approval: uploader and approver are
separate identities. Preserve that distinction; do not turn every ordinary comment into a
route milestone or treat a uploaded email as a verified approval automatically.

## Remaining technical gaps

- The Error Analysis action dispatcher currently accepts route steps only. Ordinary chat,
  assignment, status and closure need an explicit compatible API mapping.
- Email evidence is accepted by the frontend file picker but `message/rfc822` is not in the
  backend/storage MIME allowlist. Reconcile file storage and message links before approval tests.
- Cloud migrations from the withdrawn integration remain applied. Compare the live schema with
  the committed migrations before making further database changes; do not delete cloud records.
- Browser automation still fails its admin-policy verification before navigation. No browser
  workflow has been completed in this integration pass. Do not bypass that control.

## Verification so far

The live API probe verified synthetic-session bootstrap, private case reads, original-byte hash
readback and rejection of a different workspace. It read three existing synthetic cases and did
not mutate cases or call a model. The adapter also projected a saved published analysis and
verified its citations against the saved original. These are API/data checks, not browser tests.

Run adapter tests with the repository's locked Node 22 runtime:

```sh
node --import ./.railway/node_modules/tsx/dist/loader.mjs --test frontend/tests/workbench-connection.test.ts
```

Install the existing locked Railway tooling first with `bash scripts/frontend-local.sh railway-install`
if needed. No new frontend dependency is required.

Local checks passed: 805 backend tests (including executable database probes), 12 connection
adapter tests, six example tests, Python lint and the frontend TypeScript check. The original
frontend components, app routes, CSS, model prompts, route registry and migrations still match
the frozen baseline exactly.
