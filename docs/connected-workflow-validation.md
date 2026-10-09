# Connected workflow verification

## Result

The original frontend's connection adapter completed two live synthetic journeys against
Supabase: master data and mapping. Each used real agent analysis, then persisted human-action
records through the same API called by the existing frontend. Both cases stayed Closed after
reconnecting. This is adapter/API verification; the browser walkthrough remains blocked.

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

- 812 backend tests, including local database transactions against all 14 migrations.
- 19 connection-adapter and case-mapping tests; six example tests.
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

## Remaining check

The browser tool could not verify its admin-enforced policy and refused navigation. No browser
workflow or visual regression pass is claimed. Run the [browser demo steps](connected-demo.md)
before treating this as a recorded portfolio demo. The persona identities, approval email and SAP
proof are synthetic; the app did not reprocess or validate a document in a real SAP system.

The original design remains available under `product-design-freeze-v1`. Integration changes are
on the review branch until the browser walkthrough is verified.

Machine-readable evidence: [connected-workflow.json](validation/connected-workflow.json).
