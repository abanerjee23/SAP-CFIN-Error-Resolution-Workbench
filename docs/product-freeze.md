# Product freeze

The original design baseline is commit `6434d06`, restored by `b56beaa` and retained under
`product-design-freeze-v1`. Abhinav authorised connecting this frontend to the backend and
subsequently clarified closure: any case can close after successful reprocessing and data
validation, with a proof screenshot. The disconnected SAP demo uses clearly labelled synthetic proof.

The manifest records those narrow exceptions under `integration_authorization`. The root page,
persona selector and route registry remain unchanged; the additional prompt exception below
is limited to the authorised latency experiment.
The user additionally authorised repairing metadata and case references and removing Value/Amount
from the board, details and export, plus the sample monetary dashboard card. On 9 October the user
also authorised moving upload to the dashboard's lower right, progress animation and completion
navigation, persistence across navigation, visible failure/retry states, and five traced synthetic
benchmark batches. This covers the associated CSS/navigation changes and progress projections.
Existing controls now save and load data. See [the integration plan](frontend-integration-plan.md).

Later on 9 October, Abhinav authorised the proposed latency changes with **“Ok let's try the
above recommendations”**. This permits compact extraction and case-preparation prompts and
schemas, deterministic attachment of exact original evidence and maintained routes, explicit
per-stage reasoning profiles, and up to two concurrent Error Analysis cases. It also covers
the separate worker processes, lease-aware database migration, comparison runner, regression
fixtures, trace readback and cited Open questions needed to evaluate those changes without
hiding uncertainty. The original diagnosis prompt/model, route ownership, human approval and
closure requirements are outside this exception and remain unchanged.

The baseline, compact-medium and compact-low profiles are pinned on intake and restricted
to reviewed combinations. Database concurrency, lease fencing, publication validation and
budget guards remain enforced. Changing the configured profile affects future intakes only;
it does not rewrite earlier runs. Candidate profiles must be assessed for evidence coverage,
uncertainty and diagnosis quality as well as latency and cost. This authorisation permits
the experiment; it does not establish a winning profile or a production latency guarantee.

The subsequent request **“Format wise I'm fine then as we have already defined the layout.
let's not disturb that. let's test the model combinations.”** authorises model-only
comparisons: Luna medium for writing, Sol low for writing, and Luna medium for diagnosis
and writing, against the existing compact/medium control. This permits the exact model
allowlist, immutable intake pins and experiment runner. Prompts, output schemas, layout,
extraction reasoning, route policy and evidence validation remain unchanged in this round.

After reviewing the comparison, Abhinav requested the agreed switch to Luna medium
extraction, Sol medium analysis and Luna medium writing. This selects the existing
`writer_luna` profile for new local-demo uploads and permits the API/worker restart
and documentation updates. It does not change prompts, layout or saved past runs.

Do not redesign the frontend or change business rules outside this authorisation. Further
changes to design, permissions, routing, approvals, prompts or closure require Abhinav's approval.

Run `python3 scripts/check-product-freeze.py` from the repository root. SHA-256 hashes cover
protected source, dependencies, fixtures, evaluations and design documents. The check detects
changes, additions and deletions and runs in GitHub Actions. Updating the manifest requires
explicit authorisation; it is a regression guard, not a GitHub access-control rule.

Private environment files remain outside Git. The connected demo is localhost-only with
simulated personas. Its synthetic proof does not verify real SAP activity. Automated source,
API and database checks do not establish visual correctness; report browser verification separately.
