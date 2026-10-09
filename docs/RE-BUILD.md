# Rebuild plan: CFIN Error Analysis pilot

**Status:** backend source implementation complete, 2 October 2026. The root [README](../README.md) introduces the product. [Product design and operating rules](product-design.md) define the taxonomy, routes and case format; [frontend design](FRONTEND_DESIGN.md) covers the interface. The additive cloud migration, provider-backed acceptance runs, integration of the current browser-local workbench with the authenticated backend, and deployment remain release work. Cloud cutover and paid-model execution default to disabled. Files under `archive/` are historical evidence, not design requirements.

## Goal and starting point

Build the approved flow from the README: immutable AIF log intake → comprehensive Extraction Agent → Error Analysis Agent → code-owned route lookup → Summary Agent with original-log citations and authorised similar cases → rendered case → human approval, remediation evidence and recorded CFIN reprocessing outcome.

The current `log-only-v1` path already has log intake, original storage, extraction, Agent 2 **evidence selection**, factual summary, durable worker checkpoints, reviewed history, case controls, read-only case API and a frontend. The new `error-analysis-v1` source path now adds the diagnostic handoff, ten-category database registry migration, two pilot routes, rendered case format and deterministic evaluation gates. Do not present an existing factual case as if it had been analysed under the new design.

The first users are CFIN support analysts, MDG Process Owners, relevant Process Owners and Data Operations. The rebuild should reduce time spent reconstructing an exception while preserving human control of changes. Measure extraction coverage, classification quality, investigator comprehension, corrections, time to resolution, latency and cost. A fluent summary alone is not a success measure.

Keep the README's starting model assignments: Extraction uses GPT-6 Luna (`gpt-6-luna`); Error Analysis and Summary use GPT-6.1 Sol (`gpt-6.1-sol`). Model comparisons come after representative examples and a measured baseline. Preserve the initial intake envelope of eight originals, 8,192 bytes and 64 lines until real AIF samples justify a change.

## Decisions that the build must preserve

1. **All ten categories exist from day one.** Persist the README's ten IDs and definitions in Supabase Postgres: `master_data`, `mapping`, `integration_mapping`, `master_data_restriction`, `posting_period`, `tax`, `currency`, `document_splitting`, `account_assignment` and `technical_interface`. Agent 2 can tag any supported category. `master_data` and `mapping` have pilot-active remediation routes; the other eight retain their category tags and receive a manual CFIN Exception Manager route. `unclassified` is separate from the ten and means no category is supported by the extraction.
2. **The pilot evaluates classification, not merely safe fallback.** On a reviewed evaluation example with an expected `master_data` or `mapping` label, Agent 2 returning `unclassified` is a classification failure. In a live case where evidence genuinely cannot support a tag, `unclassified` is correct and triggers human investigation. Evaluate false pilot labels on other categories as well as missed pilot labels.
3. **Agent 2 receives structured extraction only.** Its model input and tool responses must contain no original raw log, case history, SAP lookup or secret. It produces a tentative cause hypothesis with extracted-entry evidence and uncertainty. It cannot approve, change data or reprocess a document.
4. **The route lookup is a narrow tool backed by database policy.** Agent 2 supplies a category ID; backend code binds the workspace and relevant extracted context, resolves a versioned policy and returns owner **role**, route steps, approvals and escalation. Workspace membership resolves a role to a person. The model cannot supply an owner name, mapping value or bespoke remediation route.
5. **Summary receives broader but bounded evidence.** Agent 3 receives the validated Error Analysis result, resolved policy, original-log text/locations for citations, and a small authorised set of reviewed prior cases. Code searches history using the category tag first, then error identity and processing context. The Summary Agent may cite relevant cases with material differences or report none.
6. **The case is readable.** Pydantic validates the content internally; code renders the README case sections. Distinguish what the log reports, the agent's hypothesis, the maintained route, human findings and actual posting outcome. The board stores category, owner, policy version and activity as structured fields.
7. **Human actions remain decisive.** For `master_data`, the MDG Process Owner tags the relevant Process Owner in the case-log conversation to request approval; that person approves or rejects there. Only after recorded approval does MDG create the data, upload implementation evidence and record the reprocessing go-ahead. Data Operations then reprocesses and records the CFIN posting reference or failure evidence. For `mapping`, MDG confirms the correct mapping with the relevant Process Owner in the case-log conversation, maintains the mapping and records its changed scope and evidence; the relevant Process Owner then reviews and approves that change in the conversation before Data Operations reprocesses and records the result. Missing/rejected approval, insufficient master-data change evidence, unconfirmed mapping or failed reprocessing keeps the case open and escalates to the CFIN Exception Manager for assignment of the next human investigator. Agents cannot carry out or approve these actions.

## Delivery plan

### Phase 0 — baseline and acceptance examples

- Freeze the current factual workflow version and capture its contracts, API shape, migration state, worker gates and frontend behaviour. Preserve legacy and factual case read compatibility.
- Turn the two existing synthetic Master Data and Mapping logs into reviewed pilot examples with expected category, supported facts, permissible hypothesis, missing evidence and citation spans. Add examples for the other eight known tags, ambiguous cases, a genuinely unclassifiable log, multi-error logs, truncated input and prompt injection. Keep the expected answers and later human findings outside model input and historical retrieval.
- Agree a small reviewer rubric for extraction completeness, category, hypothesis support, actionability, source citations and related-case relevance. Set release thresholds from a measured baseline rather than inventing accuracy claims in advance.

**Exit:** examples and scoring rules are reviewed; the baseline runs without a paid provider call; the new workflow has a distinct version identifier.

### Phase 1 — database policy and migration

- Add an **additive** Supabase migration for the ten category records, their definitions and status, versioned route policies and ordered route steps. Store policy author, approval, effective version and audit history. Seed all ten categories; seed full routes only for `master_data` and `mapping`; seed an explicit manual route for the other eight and `unclassified`.
- Maintain owner/approver **roles** in policy. Use the existing workspace membership and assignment controls to resolve actual people; add a scoped role binding only if those controls cannot represent MDG Process Owner, relevant Process Owner, Data Operations and CFIN Exception Manager cleanly. Missing or ambiguous membership must become a visible assignment exception.
- Add fields or versioned JSON projections for category, policy version, cause hypothesis, evidence references, route state, related-case search state and rendered case sections. Link each published run to its exact source, schema, prompt, model and policy versions. Preserve old case versions.
- Restrict policy maintenance and activation to an authorised administrative role. Changing a route creates a new version; it does not rewrite existing cases. Database constraints and row-level policies reject cross-workspace reads and writes, invalid category IDs, missing required route steps and unauthorised policy activation.

**Exit:** local migration and rollback path pass; all ten tags round-trip through the database; only two have full routes; old cases and reads still work.

### Phase 2 — contracts, Agent 2 and route lookup

- Introduce a new Pydantic workflow/schema version for `ErrorAnalysis` and `RouteDefinition`. Keep the existing extraction contract where possible. Agent 2's analysis contains one of ten category IDs or `unclassified`, a tentative cause hypothesis, confidence/uncertainty, competing explanations or gaps, and valid extracted-entry IDs. Preserve relevant Agent 1 document and process context in the validated handoff so Agent 3 can present the full case. Route fields originate from the tool result, not model-authored free text.
- Add a narrowly scoped `get_error_route(category_id)` tool. Backend code supplies workspace context, reads a single active policy version and returns an immutable snapshot. Known manual-route tags retain their IDs; `unclassified` resolves to manual investigation. Tool failure or stale policy produces a visible manual-review state and no invented route.
- Replace Agent 2 evidence selection only in the new workflow. Its system instructions include the maintained taxonomy definitions but no raw-original or history tools. Code validates category and cited entry IDs and binds route IDs/version to the database result. The evaluation rubric and human review assess whether cited evidence actually supports the cause hypothesis; Pydantic validation alone cannot establish that semantic claim.
- Preserve bounded deadlines, retries, cost reservations and stage checkpoints. A resume may reuse a stage only when source, workflow, schema, prompt, model and policy bindings still match; otherwise re-run or fail visibly.

**Exit:** contract/tool tests cover all ten tags, both pilot routes, manual fallback, `unclassified`, stale policy, missing owner and model attempts to invent owner/remediation. A recorded Agent 2 request demonstrably contains only structured extraction.

### Phase 3 — Summary Agent and related-case retrieval

- After Agent 2 and route resolution, have code query reviewed case history within the caller's authorised workspace. Use exact category first, then message/error identity, source and target system, interface, company/organisation, useful document attributes and recorded outcome when available. Exclude the current case, withdrawn versions and inaccessible records. Bound candidate count and excerpt size.
- Pass Agent 3 the validated analysis and preserved document context, resolved route, original log with source locations and returned candidates. Give it a Pydantic case-content contract for the README's sections: title/tags, what happened, document and processing context, original-log evidence, error assessment, required next steps/escalation, similar earlier cases and open questions. Include supplied document number, source/target system, client, company, interface, affected object, attempt, timestamp and outcome where available. Case activity remains system/human authored.
- Check current-log citations against the immutable source and historical citations against exact authorised case/version IDs. Require a candidate's shared facts and material differences before citing it; owner is not a similarity signal. Distinguish a search not performed, a completed search with no relevant result, and an unavailable search in saved output and UI.
- Keep the agent from reclassifying the error, changing the route or treating a prior fix as proof of the present cause. On summary validation failure, show analysis failure without publishing an apparently complete case.

**Exit:** reviewed examples produce readable case content with valid citations, correct tags and honest no-match/unavailable states. Cross-workspace and withdrawn history never enters model input.

### Phase 4 — case publication, board and human workflow

- Publish the new analysis result and rendered case atomically with version checks. Embed the complete unchanged original in every case, show it beside cited statements and preserve full original download and existing read-only API semantics. Extend the versioned API/OpenAPI projection with the new result kind and policy/route fields without changing the meaning of legacy/factual results.
- Update the case board to display the README case format and make facts, hypothesis and confirmed human findings visually distinct. Filter by all ten tags and `unclassified`. Show the MDG owner for pilot routes and CFIN Exception Manager for manual routes; show an explicit unassigned state when role resolution fails.
- Represent each pilot route as governed human milestones in the case-log conversation and case history. Record tagged approval request, approval/rejection, changed object and evidence, reprocessing go-ahead where the route requires it, Data Operations attempt, CFIN posting outcome/reference and escalation. Enforce role checks, required evidence, valid transition order and optimistic case versioning in backend/database code; generated prose cannot satisfy a milestone. These controls govern what the case board can record or mark complete; the MVP has no SAP write or processing authority.
- Keep feedback attributable and versioned. Human corrections can change a case's reviewed category without silently rewriting the agent result. Only approved reviewed case versions enter future history.

**Exit:** a synthetic Master Data case cannot record data creation or reprocessing go-ahead without recorded approval; a Mapping case cannot record reprocessing completion without the required review/approval; both can record successful CFIN posting or escalate on failure. Manual-route and unclassified cases cannot enter pilot remediation steps.

### Phase 5 — evaluations, observability and rollout

- Add Promptfoo regression suites for category selection, justified `unclassified`, pilot false negatives, wrong pilot labels, invented routes, injection attempts and similar-case overreach. Retain Arize AX for stage traces, latency, usage/cost and sampled quality review; redact logs, secrets and private payloads from telemetry. Save reviewer decisions and failure categories in the case/evaluation record.
- Run unit, migration, API, worker-resume, access-control and frontend checks, then end-to-end synthetic cases for both routes and a manual-route category. Compare extraction and summary quality against the factual baseline. Check cost per run and enforce the existing US$1/run and US$10/month model caps.
- Prepare the hosted migration and rollback procedure, then verify the exact database state, scoped access, durable processing and audit trail in the target environment. Use the README's `LOG_ONLY_ENABLED` cutover gate and a distinct workflow version after verification; paid execution remains separately controlled. Keep old cases on their original version. Use real AIF samples and human review before claiming field accuracy or time saved.

**Exit:** required software and database checks pass; human reviewers accept the pilot examples and read the case without reconstructing missing facts; route/approval controls pass; observed latency and cost fit the stated limits; rollback can return new intake to the previous workflow without altering saved cases.

## Implementation map

| Existing area | Rebuild work |
| --- | --- |
| `backend/src/cfin/log_only_contracts.py`, `log_only_workflow.py`, `log_only_prompts.py` | Add a new versioned Error Analysis path; preserve factual-only case compatibility. |
| `backend/src/cfin/model_adapter.py`, `worker.py`, `log_only_snapshots.py` | Wire the narrow route tool, stage validation, cost ledger, checkpoint compatibility and publication gate. |
| `backend/src/cfin/factual_history.py`, `knowledge.py` | Query by maintained category plus extracted context and load only eligible authorised prior versions for Agent 3. |
| `backend/src/cfin/factual_operations.py`, `case_read_api.py` | Project the new case fields, keep API version semantics and enforce human milestones. |
| `supabase/migrations/` | Add category/policy/role bindings, immutable policy snapshots, guarded workflow transitions and access checks. Never edit an applied migration in place. |
| `frontend/src/components/` | Render the new case, tags, source citations, related cases, approvals, evidence and reprocessing activity. |
| `evals/`, `backend/tests/` | Add reviewed examples, Promptfoo suites and meaningful integration tests for classification, routing, citations, access, resume and human controls. |

## Scope and release boundary

This rebuild does not add direct SAP reads or writes, model-selected mapping values, automatic approvals, automatic reprocessing, a live Joule connector, or full remediation routes for the eight non-pilot categories. The Case JSON API remains a read contract for saved records. Use the taxonomy definitions and pilot routes in [Product design and operating rules](product-design.md) when preparing migrations and examples.
