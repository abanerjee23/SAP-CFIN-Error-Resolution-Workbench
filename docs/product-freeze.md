# Product freeze

The original design baseline is commit `6434d06`, restored by `b56beaa` and retained under
`product-design-freeze-v1`. Abhinav authorised connecting this frontend to the backend and
subsequently clarified closure: any case can close after successful reprocessing and data
validation, with a proof screenshot. The disconnected SAP demo uses clearly labelled synthetic proof.

The manifest records those narrow exceptions under `integration_authorization`. The original
CSS, root page, persona selector, navigation, layout, model prompts and route registry remain
unchanged. Existing controls now save and load data. See [the integration plan](frontend-integration-plan.md).

Do not redesign the frontend or change business rules outside this authorisation. Further
changes to design, permissions, routing, approvals, prompts or closure require Abhinav's approval.

Run `python3 scripts/check-product-freeze.py` from the repository root. SHA-256 hashes cover
protected source, dependencies, fixtures, evaluations and design documents. The check detects
changes, additions and deletions and runs in GitHub Actions. Updating the manifest requires
explicit authorisation; it is a regression guard, not a GitHub access-control rule.

Private environment files remain outside Git. The connected demo is localhost-only with
simulated personas. Its synthetic proof does not verify real SAP activity. Automated source,
API and database checks do not establish visual correctness; report browser verification separately.
