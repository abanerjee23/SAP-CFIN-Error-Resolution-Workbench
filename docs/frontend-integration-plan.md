# Connect the approved frontend

## Boundary

Keep WorkbenchApp, its four tabs, persona selector, case table, case workspace,
summary sections, typography and styling. Connect existing controls to saved records.
The original design remains at `product-design-freeze-v1`; integration work is on
`codex/preserve-design-integration`. Model prompts and the route registry remain unchanged.

## Approved closure rule

Abhinav clarified that any case can close after its document has been reprocessed and its
data validated, with a screenshot as proof. Because SAP is not connected, this demo uses a
case-bound generated screenshot labelled synthetic. Closure records human confirmation,
the target document reference, successful reprocessing and passed validation. It does not
claim independent SAP verification or fabricate earlier route approvals.

## Implemented

- Loopback-only session for one existing synthetic workspace. The browser receives an opaque
  capability; the Supabase session stays on the backend. The four personas remain simulated.
- Original log upload with stable receipts, SHA-256 readback and published analysis with exact
  source citations. Pending or failed analysis does not receive an invented brief.
- Existing screen controls load saved cases and persist comments, evidence, external approval
  identity, named handovers, status changes and closure. Failed saves retain drafts.
- Private file bytes, including email evidence and PNG/JPEG proof, are linked to the message
  that supplied them. Saved attachments can be downloaded from the existing chat/summary.
- New synthetic uploads retain the original demo's initial manager ownership as an explicit
  assignment. Older cases without assignments display Unassigned. Route roles never silently
  change the named owner.
- Database action receipts, membership checks, owner checks, version conflicts and case/attempt/
  work-cycle evidence checks guard writes. Closed cases cannot be reopened by a status or route action.
- A separate demo worker uses the existing analysis executor and budget guards, but selects
  only Error Analysis jobs in the configured synthetic workspace.
- Restored migration files 202610090001–003 match the already-applied cloud functions.
  Migration 202610090004 adds these connections and the clarified closure rule.

## Verification boundary

Local automated checks cover backend behavior, executable database transactions, connection
adapter behavior, lint, TypeScript and production build. CSS, the root component entry point,
model prompts and route registry match the original design baseline. The existing layout's
class attributes remain in the same order. This is source-level evidence, not visual verification.

The browser tool is blocked by its admin-policy verification. API and adapter journeys must be
reported separately from an actual browser walkthrough. See [the connected demo guide](connected-demo.md)
and [verification results](connected-workflow-validation.md).

## Plan to finish and verify the complete demo

### Objective and scope

Deliver a reproducible local demo through the approved frontend: upload a synthetic log,
automatically run all three real model stages, review the cited brief, coordinate the work,
upload case-specific synthetic SAP proof, close the case and recover the same record after reload.
Keep the original design, persona toggle, prompts, route registry and clarified closure rule.
SAP execution and persona identities remain simulated. Public hosting and production sign-in
are separate work and are not prerequisites for this local demo.

Every defect found in this workflow goes into an issue log with a reproducible trigger,
expected/actual behavior, severity, fix and verification evidence. Fix all blocking/high-severity
issues before release; record any lower-severity limitation explicitly. A passing API check does
not close a browser issue. Changes to design or business rules require Abhinav's decision.

### Ordered release gates

| Gate | Work | Evidence needed to pass |
| --- | --- | --- |
| 1. Visible Case Board | Reproduce the reported empty board in the browser. Capture the actual page URL, loading error, browser console/network failure and matching API request. Check session bootstrap, allowed origin, current frontend assets, filters and case projection. Diagnose the observed cause before adding further speculative fixes. | All existing saved cases appear under All cases for every persona; named-owner filters show the appropriate subset. Fresh open, reload and API restart recover correctly. Record the observed cause and verification. |
| 2. Reproducible startup | Check the frontend/API/worker start sequence and readiness. Provide one documented way to start the demo and diagnose a missing service. Verify the worker remains scoped to the synthetic workspace and recovers from a temporary outage. | A clean restart loads saved cases; a new upload is automatically claimed and analysed without a manual run command; a stopped worker is distinguishable from a completed/failed analysis. |
| 3. Existing controls | Audit Data, Case Board, Summary, Original log, case chat, persona selection, owner handover, status, external approval, attachments, downloads, filters and CSV. Compare displayed values with saved records. Keep illustrative metrics labelled. | Each control works through the browser, permissions match the existing rules, files reopen with identical bytes, and drafts survive a failed save. Changes persist after reconnecting. No data fallback silently substitutes local sample cases. |
| 4. Real AI and quality | Run fresh master-data, mapping and insufficient-information fixtures through all three configured models. Verify exact citations, factual completeness, supported categories, separation of facts/hypotheses and faithful route guidance. Verify the configured observability integration using synthetic inputs, alongside durable stage-call records. | Actual provider calls and saved stage outputs for every fixture; case/run correlation, model IDs, latency, usage/cost and failure state are visible. Sparse input remains uncertain/unclassified. Record human review findings; no unsupported quality or ROI claims. |
| 5. Failure and recovery | Exercise unavailable API, expired/restarted session, temporary database/worker failure, invalid or oversized input, model timeout/malformed result, duplicate upload/action, stale version, wrong owner, missing/foreign proof and failed reprocessing/validation. Use controlled failures for destructive/error paths. | No silent empty board, fabricated analysis, lost draft, duplicate business action, unauthorised write or invalid closure. Failures have a visible next step. Recovery completes without corrupting earlier records. |
| 6. Full browser journeys and release | Run master-data, mapping and unclassified journeys from upload through real analysis and recorded closure. Exercise rejection/blocked status separately without inventing approvals. Repeat complete successful journeys after a clean restart. | Two successful browser passes per main journey, with screenshots, correlated API/database evidence, downloaded proof and closure retained after reload. All required automated checks pass on the pushed commit; no open workflow-blocking defects. |

### Verification procedure

For each successful journey:

1. Upload a fresh synthetic file through Data and record its delivery receipt and case ID.
2. Let the scoped worker run real Extraction, Error Analysis and Summary calls. Record the run ID,
   stage results, elapsed time and recorded cost. Do not inject a prepared model response.
3. Open the case from Case Board. Check its original, citations, brief, classification and guidance.
4. Use the existing personas to record explicit handovers, comments, approval evidence and work
   outcomes. Verify uploader and external approver remain distinct simulated identities.
5. Generate a proof image bound to that case. Review it, record successful simulated reprocessing
   and data validation, include the target document reference, and upload the screenshot in Close case.
6. Reload, reconnect and reopen the case. Verify Closed status, owner, original bytes, activity and
   downloadable evidence. Retry the same committed action and check that only one outcome exists.

Keep the existing $1 per-run and $10 monthly model budget guards. Record spend before and after
verification; stop at a budget guard instead of silently raising it or repeatedly rerunning failures.
A successful real-model run is separate from a judgment that its content is accurate and useful.

### Browser access dependency

The browser tool currently refuses access because its admin-enforced policy cannot be verified.
Resolve that through the supported browser connection/security mechanism; do not bypass it.
While blocked, continue code, adapter, API, database and model checks, but keep the browser gates
open. A user-operated walkthrough can provide explicitly labelled manual evidence; automated UI
verification must never be inferred from API success or a successful build.

### Current issue log

| ID | Priority | Issue | State / next evidence |
| --- | --- | --- | --- |
| WB-01 | Blocking | Browser transport invoked native fetch with the connection object as its receiver, preventing case loading. | Fixed on 9 October. Reproduced in Chrome and the Codex in-app browser; all six saved cases load after the fix. Receiver regression, 21 frontend tests, typecheck and build pass. Broader persona/restart coverage remains in gate 1. |
| WB-02 | Blocking | Previous chat could not verify the browser automation security policy. | No longer blocking in this chat: Chrome and the Codex in-app browser were controlled successfully on 9 October. The underlying policy error was not diagnosed or changed. |
| WB-03 | High | Demo worker stopped; its previous output did not identify the exact cause. | Recovery fix and regression tests pass; verify resilience and automatic dispatch after a clean restart. |
| WB-04 | High | Complete UI control/permission matrix has not been exercised. | Open. Adapter/API tests cover core operations; browser interaction evidence is outstanding. |
| WB-05 | High | Repeatable real-model browser journeys and content review are incomplete. | Open. Prior master-data/mapping API journeys and an automatic unclassified run passed. Complete the browser quality gates above. |
| WB-06 | Medium | Observability export was disabled during the original real-model checks. | Export and correlation verified on 9 October: all 30 trace IDs from ten new runs read back through Arize's API. Timeout/retry failure paths pass injected tests; no real provider timeout was observed in this baseline. See [baseline](analysis-latency-baseline.md). |

Release evidence belongs in `docs/connected-workflow-validation.md` and `docs/validation/`.
Keep README concise and aligned with demonstrated behavior. Push each tested change to the existing
integration branch. Merge only when the browser gates pass; retain `product-design-freeze-v1` for recovery.
