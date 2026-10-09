# Product freeze

The approved design and business logic are frozen at commit `6434d06`, restored by `b56beaa`.
The tag `product-design-freeze-v1` records this baseline with its verification check.

Abhinav subsequently authorised starting frontend-to-backend connection fixes. The manifest
records the narrow connection changes under `integration_authorization`; original UI components,
styles, prompts, routing and closure rules remain unchanged. See [the integration plan](frontend-integration-plan.md).

Do not change the frontend design, navigation, personas, workflow, permissions, routing,
approvals, closure rules, prompts or database business rules without Abhinav’s explicit approval.
Testing and documentation may record failures; they must not silently change product behavior.

Run `python3 scripts/check-product-freeze.py` from the repository root. The manifest records
SHA-256 hashes of the protected source, dependencies, fixtures, evaluations and design documents.
The check detects changes, additions and deletions in these paths and also runs in GitHub Actions.
Updating this manifest to permit product changes requires explicit approval. This is a regression
guard, not a GitHub access-control rule.

## Workflow scope

The approved frontend uses browser-local demo cases and simulated personas. Uploaded logs are
staged locally; this frontend does not initiate the backend’s live analysis workflow. Attachments
retain metadata in this demo. Backend tests and a successful frontend build do not establish a
connected frontend-to-database workflow. Browser verification must report these limits honestly.

Private environment files remain outside Git. This freeze records source files; it does not revert
or change cloud database schemas or records.
