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
