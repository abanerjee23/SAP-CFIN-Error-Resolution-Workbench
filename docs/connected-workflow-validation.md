# Connected workflow verification

The latest authorised latency iteration is documented in
[latency-optimization-results.md](latency-optimization-results.md). Compact/medium analysis
and two workers are active locally after 13/13 synthetic quality passes; the original
baseline and earlier verification records below remain historical evidence.

## Result

The original frontend's connection adapter completed two live synthetic journeys against
Supabase: master data and mapping. Each used real agent analysis, then persisted human-action
records through the same API called by the existing frontend. Both cases stayed Closed after
reconnecting. This is adapter/API verification. Browser access and saved-case loading now pass in Chrome
and the Codex in-app browser; the complete upload-to-closure browser walkthrough remains pending.

| Journey | Saved case | Analysis run |
| --- | --- | --- |
| Master data | `4eb9dd45-88eb-4ee7-b217-dc6e0801496c` | `a21c0328-83c9-4938-83c0-58c1349c80e8` |
| Mapping | `a4f6ee4c-d7ef-47fe-aea4-f56fbbaa1d8e` | `9e316204-8ab0-4ce1-b663-eb272349e2ab` |

Verified: original-byte hash readback; duplicate intake handling; saved initial assignment;
published analysis with exact original citations; explicit handover; owner status updates;
ordinary comments; stored email proof with distinct uploader and external approver; PNG proof
byte readback; closure; repeated closure receipt; and persistence after a new session bootstrap.

Negative checks rejected stale writes, non-owner closure, missing screenshot, failed validation
and changing status after closure. Executable local database probes additionally cover master-data,
mapping, tax and unclassified closure, foreign-case proof, text-only proof, unconfirmed outcomes,
failed reprocessing, receipt conflicts and attempts to bypass closure guards.

A live retry exposed an API version precheck that prevented recovery of an already-committed save.
The API now allows these Error Analysis actions to reach the database's receipt-before-version
check. New stale actions still fail. The fix is covered by regression tests and live closure retries.

## Automated checks

- 814 backend tests, including local database transactions against all 14 migrations.
- 21 connection-adapter and case-mapping tests; six example tests from the earlier API verification.
- Python lint, frontend TypeScript and production build.
- Railway configuration/type checks and the updated product-freeze manifest.
- Original CSS, root page, model prompts and route registry unchanged. Existing layout class
  attributes remain in their original order; this does not establish pixel-level equivalence.

The two model runs made three calls each. Recorded costs were $0.048435 for master data and
$0.046298 for mapping ($0.094733 combined), using the saved application price catalogue.
These measurements are examples, not accuracy or ROI claims. Arize export was disabled for this
verification; database stage-call accounting and saved outputs supplied the evidence.

## Automatic demo dispatch

The scoped demo worker automatically analysed a third upload, case
`19a4f67e-6ea5-496d-86a2-e09163098362` (run `8ffd182b-e89b-4cfe-a718-39f7673120d4`).
The sparse log remained `unclassified`, with published cited analysis and explicit manager
ownership. The case is deliberately left Open for the browser walkthrough. This check made
3 model calls with recorded cost $0.023960. New uploads in this workspace can be picked
up while the local demo worker remains running.

## Empty-board report and recovery checks

The user reported an empty Case Board. Live adapter reads still returned all six cases,
including the same parallel loading pattern used by the frontend. On 9 October, the failure
was reproduced in Chrome and the Codex in-app browser despite a healthy API and passing CORS.
The default transport stored native `fetch` directly, then invoked it with the connection
instance as its receiver. The generic catch converted that browser failure into an apparent
API outage. Wrapping the default transport with `globalThis.fetch(...)` fixed the connection.
A receiver-sensitive regression test failed before the change and passes after it; the earlier
Node tests used arrow-function doubles that did not enforce the browser receiver contract.

After rebuilding, both browsers showed all six saved cases. In Chrome, Assigned to me showed
Maya's two cases, and the saved mapping case opened with its cited summary, closure record and
18-line original log. All 21 frontend tests, TypeScript checking and the production build pass.
No new model calls or business-record mutations were needed for this connection check.
Backend, database and model results above remain evidence from the earlier verification,
not checks rerun for this frontend-only fix.

The initial load previously kept an empty board after a failed request and never retried.
It now retries temporary connection failures up to three times, reconnects on focus after an
unsuccessful load, and distinguishes loading/error states from an empty filter result. Mutating
requests are not blindly retried. Both loopback hostnames on port 3011 pass CORS preflight and
session bootstrap checks. A stopped demo worker was also found; it now recovers from temporary
cloud failures with bounded backoff while still rejecting access and configuration failures.

## Remaining check

The earlier browser-tool policy error did not recur in this chat. Saved-case loading and
limited case inspection pass, but no complete browser workflow or visual regression pass is
claimed. Run the [browser demo steps](connected-demo.md)
before treating this as a recorded portfolio demo. The persona identities, approval email and SAP
proof are synthetic; the app did not reprocess or validate a document in a real SAP system.

The original design remains available under `product-design-freeze-v1`. Integration changes are
on the review branch until the browser walkthrough is verified.

Machine-readable evidence: [connected-workflow.json](validation/connected-workflow.json).

## Metadata and reference repair — 9 October 2026

The field audit found that legacy case identity columns were empty while the current
verified extraction contained the business context. The frontend also hardcoded every
Value cell to “Not supplied” and omitted the saved cited document context.

The shared mapper now projects document/source/company/target/interface from supported
fields in the current extraction, validating original source spans and literal label/value
association. It preserves leading zeroes, source/target scope and visible conflicts.
The case details render the saved cited context. At the user's request, Value/Amount was
removed from the board, detail fields and CSV, and the illustrative monetary KPI was removed.
Original log contents and cited monetary evidence remain unchanged.

Migration `202610090005_case_numbers.sql` adds immutable database-assigned references.
It was applied transactionally to the configured demo database: all eight existing case
rows across two synthetic workspaces retained every other field, including UUID, version,
timestamps, history bindings and published analysis. The displayed workspace has six cases.
No new model run was needed.

Verification: 820 backend tests (including executable database migrations and concurrent
case numbering), 31 frontend adapter/mapping tests, six example tests, Python lint,
TypeScript, production build and Railway configuration checks pass. Six current saved cases
pass API-to-mapper checks: all document numbers/source systems/company codes populated;
source company 1000 stays distinct from target company 2000. Only genuinely absent target
system/interface fields remain “Not supplied”. Database reference tests also cover immutable
references, RLS, concurrent creation, UTC year and retention of existing workflow data.

The rebuilt Codex in-app browser shows all six readable case references and document numbers.
Searching by reference finds the expected case, and the mapping case details show source
ERP-DEMO / 010, company 0010, target CFIN-DEMO / 100 and interface DEMO_CFIN_GL with
the saved cited context. The downloaded CSV has six rows and eight columns, preserves
leading-zero document numbers, and has no Value column.

Full upload-to-real-analysis-to-closure browser journeys remain a separate release gate.

## Dashboard upload and real-model baseline — 9 October 2026

The upload now sits beside the personalized priorities panel. Durable current-run progress
separates queued/running/retrying/failed states from actual diagnostic categories. Pending
and failed cases cannot display an unclassified diagnosis or a fabricated case summary.
Users can change tabs or reload, see progress on return, and open a completed case directly.
Failure retains the original and offers an authenticated, version-checked analysis retry.

The Codex browser walkthrough verified upload of `browser-walkthrough.txt`, saved queue
state after reload, board progress, real stage updates, completion and opening case
CFIN-2026-000012. One newly observed extraction used `line N` field context; a failing
regression reproduced the missing identifiers and the mapper now verifies their exact
source lines. No new model call was needed for that correction.

Five two-file synthetic batches completed with real calls. All ten published analyses matched
the expected master-data/mapping category. Average workflow latency was 51.91 seconds;
recorded model cost was $0.446880. Arize was enabled, and all 30 expected trace IDs were
read back from its API. Details and limitations are in [the baseline](analysis-latency-baseline.md).

Validation: 820 backend tests passed in the regular run; all six optional database checks
also passed in the disposable PostgreSQL container (826 unique tests total). All 35 frontend
tests, Python lint, TypeScript and production build pass. Injected timeout tests verify one
retry and terminal failure; no real provider timeout occurred in the benchmark.

The existing 60-second per-stage deadline remains appropriate for this small baseline.
The automatic demo processor was restored after the controlled measurements. Real SAP
execution and complete browser approval-to-closure remain outside this verification.
