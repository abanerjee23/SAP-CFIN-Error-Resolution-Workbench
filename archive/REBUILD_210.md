# REBUILD_210 — code update plan for the factual-case MVP

**Prepared: 2 October 2026. Updated after the full-build implementation: phases 1–6 are connected in code, with a dedicated factual evaluation path. Deployment/database verification, measured provider results and human semantic acceptance remain separately recorded release gates.**

The recommendation is a targeted refactor of the existing application. Reuse the portal, private evidence store, database, worker, access controls, audit history, human case workflow and Arize integration. Replace the diagnosis-dependent analysis path with the agreed three-agent flow, preserving existing records and their original meaning.

[README](README.md) remains the product baseline. [Design rules](docs/design-rules.md) define behaviour. [BUILD](BUILD.md) is the delivery overview; this document supplies the code-level work packages, dependencies and acceptance criteria.

### Full-build implementation — 2 October

The remaining integration work is implemented: log-only text intake with truthful provenance and exact-byte storage; additive `202610020001_log_only.sql`; version-pinned worker stages and factual publication; claim-level source navigation and complete embedded originals; reviewed history supplied only to Agent 3; factual review/investigation/proof controls; versioned context owner defaults and honest mixed backlog; and typed read-only external machine access. The portal retains an explicit legacy branch and isolated synthetic previews.

The initial envelope remains eight originals / 8,192 aggregate bytes / 64 lines. `LOG_ONLY_ENABLED` defaults off until the new migration and integration checks are verified. Paid model dispatch has its own gate. The final backend suite passed 767 tests with no skips, including actual local PostgreSQL command execution; backend/example Ruff and six external-consumer tests passed. Frontend type/build and focused factual-preview browser checks passed. The authoritative final backend/database/provider evidence belongs in [BUILD](BUILD.md) and the [implementation record](docs/implementation-log.md); human expectation review, semantic acceptance and comprehension measurement are not automatically satisfied by this build.

The following audit and phase descriptions preserve the original requirements and first-increment record. “Work needed” language inside those historical sections describes the starting point, not the current implementation status.

### Build review and first increment — 2 October (historical checkpoint)

The audit supports the targeted refactor and dependency order. The main integration risk is replacing prompts before intake, immutable snapshots, stage persistence and case publication can represent a factual result. Keep the existing worker on its legacy path until those database commands and readers are updated together.

Implemented in this first increment:

- Versioned multisource contracts and exact original-byte, hash, line-range and quote checks. Coverage gaps are computed by code and carried to the summary and saved result.
- Original-only input preparation, draft exact-source snapshot restoration and an opt-in extraction → selection → summary executor, using the existing OpenAI Agents SDK adapter and cost ledger interface. Prompts, schemas and hydrated handoffs contain no diagnostic prerequisites.
- Application-owned run/workspace/case/attempt/input bindings; checkpoint validation also binds the exact stage input, model IDs and reasoning effort. No cross-run reuse. Empty/blank evidence, invalid references, stage failures and unknown usage cannot publish a new brief.
- Typed factual/legacy result projections and an evaluator-only synthetic expectation corpus. Expectations remain draft pending human review; software tests do not establish model quality.

The initial application envelope is **eight UTF-8 text originals, 8,192 aggregate original bytes and 64 aggregate lines**. It is deliberately bounded around the first fixtures, not a provider capacity claim or production sizing decision. The adapter also checks each complete encoded stage request before reserving a call. Nothing is silently truncated; a model output can still exceed its output allowance and fail visibly.

The running portal/API/worker still use the legacy workflow. No new migration has been applied, no new factual cloud job has been enabled and no paid baseline model run is claimed. Next, implement the additive intake/queue/stage/publication migration and connect the factual case renderer. Reviewed-history retrieval, human controls, machine authentication and measured rollout remain required before the rebuild is complete. See the [implementation record](docs/implementation-log.md) for verification evidence.

## 1. Fixed product requirements

| Step | Owner / baseline | Required behaviour |
| --- | --- | --- |
| Ingestion | Code | Receive the supplied log/views, preserve every accepted original unchanged, generate application metadata and queue analysis. |
| Extraction | Agent 1 — GPT-6 Luna (`gpt-6-luna`) | Extract all supplied entries and fields into a structured schema. Preserve exact values, context, unfamiliar content and limitations. |
| Evidence selection | Agent 2 — GPT-6.1 Sol (`gpt-6.1-sol`) | Select essential facts and qualifications from the full extraction. Retain contradictions and uncertainty. |
| Summary | Agent 3 — GPT-6.1 Sol (`gpt-6.1-sol`) | Write friendly, concise factual bullets and separately cite relevant reviewed historical cases. |
| Case creation and routing | Code | Compile the case, embed the complete original, resolve source links and apply valid ownership configuration. |
| Review and learning | People and existing infrastructure | Require meaningful updates at key milestones. Feed eligible reviewed findings back to Agent 3 only. |
| Case JSON API | Code | Make saved case data, state, full extraction, citations and original logs available through a versioned authenticated JSON read contract for authorised external tools, including future SAP Joule consumers. |

The current log is the source of current-case facts. Historical findings and later human investigations remain separately attributed. Agents do not infer root causes, recommend fixes, make SAP queries or execute actions.

There is no diagnostic rules engine, code-based business-field extractor, comparison agent or additional verification agent. Code still handles storage, source numbering, validation, permissions, retrieval, assignment and persistence. Every agent output uses Pydantic; valid structure is not proof of factual accuracy.

## 2. What the code audit found

| Existing coupling | Why it matters for this rebuild |
| --- | --- |
| Intake and restoration require a manifest and eight named JSON sidecars alongside the original log. | Removing fields from the upload screen alone will break the API, database queue and worker. All must accept the same new source contract. |
| Queueing requires complete business identity and known attempt order. | Extraction would be blocked by information it is supposed to discover. A provisional case must be analysable without invented SAP identifiers or timestamps. |
| Workflow, adapter and worker all depend on `Preparation`, `Diagnosis`, diagnostic routing and conditional `CaseBrief`. | Changing prompts alone cannot produce the new behaviour. Output types, stage payloads, persistence and case projection must change together. |
| History is fetched before extraction and passed to Agent 2; retrieval does not load the full relevant historical evidence. | Move it after evidence selection and supply actual authorised past case/log content exclusively to Agent 3. |
| Database completion publishes diagnosis fields and does not update the generated case title. | Add a factual result projection; ensure the title and bullets reach the case without inventing diagnosis values. |
| Corrected human reviews require a cause label; starting work assumes a target change. | Reviewing facts and beginning investigation must work independently of diagnosis or change-authority assertions. |
| Owner defaults, backlog filters and publication machinery contain diagnosis-specific assumptions. | Adapt ownership and displays while preserving the existing human approval and audit controls. |
| The draft extraction schema identifies only one source and trusts a model-provided line count. | Multiple supplied views need source-specific locators and checks against the actual preserved content. |
| Intake storage limits exceed the adapter's analysis limits. | An accepted upload is not automatically a fully analysable log. Explicit capacity handling is necessary to avoid silent omissions. |
| Workspaces/evidence enforce synthetic provenance today. | Real sample ingestion requires a deliberate provenance change. Never label a real log synthetic to satisfy a database check. |
| FastAPI exposes portal case/evidence reads using signed-in user authentication; evidence downloads return source bytes. | Reuse these boundaries, but add a stable typed external JSON contract and scoped machine-caller access. Existing routes do not establish Joule readiness. |

The existing implementation is reusable, but these are functional dependencies rather than cosmetic naming changes.

## 3. Implementation defaults and scope

These are recommended starting choices for the rebuild, not claims of existing support or a universal SAP export format.

| Decision | Proposed first implementation |
| --- | --- |
| **Input formats** | Start with UTF-8 text originals, including several supplied text views in one case. Use an ordered source manifest rather than requiring users to fabricate the old reference pack. Retain each file separately; do not concatenate away source identity. Validate this format choice against real samples. |
| **Other formats** | Do not imply screenshots, PDFs or arbitrary exports are extractable because the existing proof uploader accepts them. Show explicit format limitations. Add their readable representations and locators only when samples justify that work; originals must remain unchanged. |
| **Identity** | Mint application case/intake/source IDs in code. Treat missing SAP document/attempt values as unknown. Use the existing provisional case/attempt mechanism; receipt time is not SAP processing time. |
| **Historical reading** | Begin with code retrieving and loading bounded eligible historical content before the Agent 3 call. Agent 3 reads that content and selects/cites references. This fits the existing single-turn adapter and avoids adding an open-ended tool loop. |
| **Model capacity** | Define and test a bounded first analysis envelope. Reject or visibly mark unsupported analysis sizes without truncating content. Do not promise that every storable file fits an agent call. |
| **Stage reuse** | Preserve same-run checkpoint recovery with version checks. Disable cross-run extraction reuse for the first baseline unless compatibility is demonstrated; add it back only when correctness is established. |
| **Legacy cases** | Keep historical outputs, source files, reviews and case progress. Read them through an explicit legacy branch; do not reclassify or automatically rerun them. |
| **External consumption** | Include a versioned read-only JSON API and OpenAPI contract in this rebuild. Reuse the saved case projection and evidence store. Defer customer-specific Joule wiring and external write commands; neither requires a new analysis agent. |
| **Stack and scope** | Retain OpenAI Agents SDK, Next.js/FastAPI, Supabase, Arize AX and existing Railway definitions. Keep the separate backlog feature; no new portal, agent platform or SAP integration. |

Real samples may change the input schema or supported formats. They should not require changing the three logical agent responsibilities.

## 4. Delivery sequence

Each phase produces a reviewable result. Phases 5 and 6 can proceed in parallel once the versioned result contract and core workflow are stable. History must be included before the full product is considered complete.

| Phase | Main deliverable | Depends on | Exit evidence |
| --- | --- | --- | --- |
| **1. Contracts and fixtures** | Versioned input, source, stage and case-output contracts; reviewed factual expectations. | Existing design. | Valid and invalid examples exercise the proposed handoffs without model calls. |
| **2. Intake and persistence** | Log-only upload/restoration and additive database compatibility. | Phase 1. | A provisional case preserves all originals and queues without reference packs or invented identity. |
| **3. Agent pipeline** | Extraction → evidence selection → factual summary with durable execution. | Phases 1–2. | All three stages run on bounded test inputs; failures and limitations remain explicit. |
| **4. Case experience and JSON API** | Readable factual case, complete original, source navigation and versioned external reads. | Phases 1–3. | A person and an authorised machine caller can retrieve the same saved facts and exact permitted originals. |
| **5. Historical references** | Reviewed past case/log content supplied only to Agent 3. | Phases 1–3; renders through Phase 4. | Relevant references, no-match, unavailable and withdrawal paths behave correctly. |
| **6. Human controls and compatibility** | Factual review, valid assignment, meaningful records and honest mixed backlog. | Phases 1–4. | New and legacy cases remain usable without requiring new AI diagnoses. |
| **7. Evaluation and controlled rollout** | Reviewed model baseline, integrated regression evidence and rollback-ready release. | Phases 1–6. | The agreed release checklist passes; remaining limitations are documented. |

### Phase 1 — finalise contracts and factual examples

Build on [log_only_contracts.py](../backend/src/cfin/log_only_contracts.py) and [log_only_prompts.py](../backend/src/cfin/log_only_prompts.py), rather than introducing another agent framework.

- Define an immutable source manifest: source ID/version, original filename, content type, hash, byte size, provenance and readable-location metadata. Keep ingestion metadata distinct from facts reported by SAP.
- Give each extracted entry its own source ID/version and locator. Global entry IDs must distinguish repeated lines across different files. Keep any readable representation separate from original bytes.
- Add a code-owned execution envelope with the actual run/case/attempt binding, input revision, workflow/schema/prompt versions and stage output. The database currently expects `output.run_id`; the application must bind it rather than trust a model to choose it.
- Validate source counts and ranges against saved content, exact quoted text where required, and uncovered/unreadable regions. Coverage checks establish that source regions were represented, not that every field was correctly understood.
- Hydrate Agent 2's selected IDs into the actual extracted entries before Agent 3. Carry extraction limitations automatically; do not rely on a summary model to remember them.
- Require flagged unresolved entries to remain represented in the output references or an explicit limitation. Semantic omission remains an evaluation concern even when references are valid.
- Define a no-usable-evidence outcome. Empty extraction/selection cannot produce a fabricated, supposedly cited title. Code can show an analysis-unavailable case with its original and a specific reason.
- Make actual history-search status application-owned. Reconcile it with the rendered output; a model cannot claim a search succeeded or no matches exist when no search ran.
- Define typed external case/source JSON responses and their OpenAPI schema alongside the saved case contract. Keep internal stage payloads and service metadata out of the public response; identify legacy versus factual results explicitly.

Use a discriminated result contract for new versus legacy outputs. Proposed names such as `LogAnalysisResult` and `workflow_version` are implementation details to finalise here; they are not existing APIs. Retain `agent1`–`agent3` stage identifiers for the ledger, with versions defining their new responsibilities.

Prepare initial factual expectations from the existing MD-01/MAP-01 **original logs only**, plus small variations covering missing fields, contradictory entries, unknown content, multiple originals and empty/unreadable input. Keep expected answers outside agent input. The old mapping/master-data files and routing oracle remain legacy regression material.

**Exit:** reviewed examples prove reference resolution, version binding, explicit failure handling and the separation of full extraction from selected evidence. No claim of model accuracy is made at this phase.

### Phase 2 — implement log-only intake and durable storage

Update the API, UI contract, source preparation, snapshot restoration and database commands together.

- Introduce an explicit log-only intake variant. Generate technical receipt and source metadata in code; retain the old pack reader for compatible legacy records/tests.
- Store and hash-verify every accepted original before queueing. Handle partially failed uploads visibly and idempotently; never queue a snapshot that claims sources which were not saved.
- Replace the nine-filename assumption for new snapshots with the source manifest. Workers restore exact saved bytes, never repository fixtures or unregistered sidecars.
- Allow analysis of incomplete document identity and unknown processing order. Existing `attempts` can retain null processing time/order and `result='unknown'`; distinguish this application context from an observed SAP attempt.
- Keep correlation conservative. Promote identity only from explicit, source-backed values through validated code paths; conflicting or ambiguous identity stays provisional. Do not merge by wording, account similarity or upload time.
- Allow publication of a factual brief for the current intake revision even when SAP chronology is unknown. Preserve separate restrictions on claiming a latest business outcome or resolving the case.
- Carry truthful provenance. Existing synthetic constraints need an explicit compatible migration before real logs can be accepted; synthetic demonstrations and simulation actions must stay clearly bounded.

Create a new migration after the eight existing migrations. Do not edit applied migration files. Reuse the current cases, attempts, evidence, runs, jobs, stages and audit tables where practical; add the version/manifest/projection support required by the new path.

The migration must account for the latest definitions of `private.enqueue`, `private.commit_intake`, `private.save_stage`, `private.complete_run_base`, its historical-reference wrapper, and `private.preserve_run_input`. Preserve grants, workspace isolation, lease checks, immutable snapshots, duplicate protection and evaluation-only isolation.

**Exit:** an uploaded text log, including a set of supplied text views, can create a provisional analysable case with exact originals and no external reference pack. Duplicate/conflicting deliveries and denied access retain correct behaviour.

### Phase 3 — wire the three agents

Replace diagnostic logic only in the new versioned workflow.

| Agent | Input | Output / boundary |
| --- | --- | --- |
| **1: extraction** | Preserved readable content with application-issued source locators. | Full extraction and limitations. No history, separate lookups, playbooks or expected answers. |
| **2: evidence selection** | Full validated extraction and its source map. | Selected and unresolved entry references. No external fact gathering or historical search. |
| **3: summary** | Selected entries, limitations and the actual history result; initially explicitly `not_searched` until Phase 5. | Factual title, bullets, unresolved details and separately attributed Related cases. No diagnosis or recommended action. |

Create extraction and evidence-selection prompts; wire the existing summary prompt. Use stage-specific payloads so legacy references cannot leak through a shared `agent_payload()`. Remove `route_diagnosis`, cause probes, approved-guidance selection and identity-based diagnostic bypasses from this flow. Every prompt must treat log and historical text as untrusted evidence, never instructions; agents receive no generic repository, network, storage or mutation tools.

Update the adapter to select the proper prompts/schemas/version without importing the old instructions for new runs. Keep Luna/Sol/Sol, existing medium effort, `output_type`, durable reservations, usage reconciliation, bounded retries and automatic Arize instrumentation. Record actual workflow, prompt, schema, source and model configuration on the run.

Persist validated stage outputs under their actual run binding. Reject incompatible legacy checkpoints even though both pipelines use `agent1`. On a failed rerun, preserve earlier published output as an explicitly older result and show the new failure. Never overwrite human work, ownership or newer evidence with a late result.

**Capacity work is required:** the current adapter uses a conservative 131,072 input bound that includes encoded bytes, prompts/schema and 32,768 overhead, and an 8,192-token output cap. These are implementation limits, not assertions about provider model capacity. Full extraction can exceed them well before a 1 MiB upload limit. Preflight each stage, avoid duplicate raw/numbered payload copies and treat truncated or incomplete output as a visible failure/limitation.

Do not add hidden chunk loops. If real sample sizes require chunked extraction, it remains one logical Agent 1, but needs explicit chunk coverage, identities, checkpoints, reconciliation and call limits. The current initial-call-plus-retry ledger cannot be reused as unlimited chunk accounting. Treat that as a measured follow-up unless it is required for the first supported sample set.

**Exit:** the three-stage path produces a traceable factual result on the initial examples. Unknown causes and absent playbooks do not prevent summary; genuine input/execution failures do not masquerade as success.

### Phase 4 — publish the factual case and JSON API

Keep the existing case page and visual design.

- Publish the generated factual title, statement arrays, unresolved details and extraction limitations from the saved versioned result. Do not flatten everything into a generic description or raw JSON.
- Add typed frontend payloads for the revised flow. A new case must not need a placeholder diagnosis to pass `CaseSummary` validation or render.
- Resolve statement entry IDs through the saved extraction/source map. Display references next to the claims they support, opening the exact source/version and highlighting the relevant lines.
- Embed all accepted originals in a clearly labelled, expandable **Original log** section inside the case. Retain downloads of unchanged bytes. Source fetch failures show an error, not an empty log.
- Preserve the full extraction for detailed review without requiring users to read it routinely. Keep implementation JSON secondary to the user-facing brief.
- Distinguish queued/running/failed/stale analysis, usable output with limitations, human review and operational resolution. These are different concepts, not a single confidence label.
- Maintain a labelled legacy renderer for old diagnosis/resolution outputs. Update synthetic previews so they demonstrate the new factual experience accurately.

**Exit:** the user can understand a case from concise bullets, inspect uncertainty, and open every cited original location without leaving the case or confusing it with a previous attempt.

#### External read contract — required in this phase

Serve persisted data through code, without rerunning agents on a read. Support case discovery and individual retrieval, including identity/context, owner/priority, operational and review state, factual title/bullets, selected evidence, complete extraction, limitations, separately attributed related cases and permitted human records. Distinguish reported SAP processing state from app state and human findings.

The following versioned routes are implemented. The original contract requirements remain below; [the API guide](docs/case-read-api.md) and generated OpenAPI define the current request parameters and typed responses:

| Read | Implemented route | Contract |
| --- | --- | --- |
| Case discovery | `GET /api/v1/cases` | Authorised workspace scope, bounded filters, stable pagination and updated timestamps. Never return cross-workspace results. |
| Case snapshot | `GET /api/v1/cases/{case_id}` | Saved case version, analysis run/version/status, brief, limitations and source manifest. Explicitly identify an absent, failed or stale analysis. |
| Evidence and records | `GET /api/v1/cases/{case_id}/extraction`, `/selected-evidence`, `/activity`, `/records` | Full authorised structured content through bounded pages tied to a snapshot/version. Expose meaningful human records, not private infrastructure traces or credentials. |
| Original content | `GET /api/v1/cases/{case_id}/sources/{source_id}` | JSON with source identity/version, content type, encoding, hash and exact preserved text for supported UTF-8 originals. Separate unchanged-byte downloads remain available. Every supplied view must be retrievable. |

Specify page cursors, response limits, freshness/version semantics and predictable errors in OpenAPI. Pin related reads to a returned snapshot and source version; reject expired or incompatible cursors visibly. Do not truncate long extraction/log content, return an excerpt as a complete original, invent unavailable fields, or relabel old diagnoses as new facts. Authorised exact originals and byte downloads must match the preserved source hashes. Historical citations still require independent evidence/case access checks and current eligibility handling.

Add a revocable non-interactive identity restricted to explicitly granted workspaces and read capabilities. Select and document the token issuer/authentication mechanism during implementation; the current portal user-token flow is not automatically a machine integration. Validate issuer/audience/expiry as applicable, enforce case/evidence access in the service and data layer, use HTTPS and bounded requests, and record caller/resource/version/time/outcome without logging full private payloads. Never share a Supabase service-role credential or impersonate an arbitrary portal user. If a service identity is used, its scope is the authority; it does not automatically carry a Joule user's permissions.

Publish a minimal authenticated request/response example and test consumer against the OpenAPI contract. The initial API remains platform-neutral. SAP documents [Joule skills as tools](https://developers.sap.com/tutorials/joulestudio-agent-create?embed=full) and [MCP connections with destination and access requirements](https://help.sap.com/docs/Joule_Studio/45f9d2b8914b4f0ba731570ff9a85313/3d9dfad0bc39468292d508f0808a12fe.html); actual customer Joule configuration, supported authentication and any adapter are a later integration deliverable. Do not build an MCP server solely to deliver JSON access.

Future writes must use separately permissioned case commands with idempotency, expected case version, allowed-transition checks, actor attribution and meaningful evidence/comments. An external caller cannot bypass human review, proof or knowledge approval or overwrite immutable originals. SAP writes remain separately authorised SAP-side actions. Their reported outcomes would be appended as attributed evidence, not silently accepted as confirmed resolution. No general-purpose patch endpoint or external write authority is part of this read API increment.

**Additional exit evidence:** an authorised machine test client retrieves a case and every permitted original without UI access; unauthorised, revoked and cross-workspace calls are denied; all pages/citations remain version-consistent; GET requests cause no model calls or business-state changes. The contract and example identify limits and future integration work accurately.

### Phase 5 — connect history to Agent 3

Use the existing reviewed knowledge infrastructure, with a bounded evidence reader.

- Build retrieval queries from selected observed messages, identifiers and context. Replace the current first-1,000-characters query and remove any dependency on a known cause/category.
- Search only authorised eligible reviewed versions. Exclude the current case and its later findings from historical retrieval; apply the same separation to held-out evaluation cases.
- Fetch the referenced past case content and relevant original-log evidence through existing authenticated/service boundaries. Supply exact versions and locators, with clear limits on how much was read. A title or similarity score alone is insufficient evidence for a historical note.
- Start with bounded code retrieval/prefetch. The adapter currently has no tools and `max_turns=1`; agent-driven browsing would require explicit additional turn/tool limits and is not necessary for this first implementation.
- Supply that material only to Agent 3. It identifies useful references, explains similarities and differences, and attributes past findings/outcomes to the earlier case. Code builds links from registered IDs.
- Keep retrieved candidates separate from actually cited references. Preserve exact citation/version registration and atomic eligibility checks before publication.
- Make history optional to the current factual brief. If retrieval fails, show `unavailable`. If a cited version becomes ineligible, withhold the affected historical content and record the limitation while retaining a valid current-log brief. An unused withdrawn candidate must not discard that brief.
- Recheck access on case/source navigation and handle cached historical content appropriately. Preserve the audit record of what an older run read without presenting withdrawn material as a newly approved reference.

Knowledge publication safeguards stay in place: human review, exact versions, evidence, applicability and existing configured evaluation requirements. A new factual summary does not publish knowledge. Broader reuse of unconfirmed factual lessons would require an explicit later policy change; it is not silently introduced here.

**Exit:** a matching case, a misleading match, no relevant result, unavailable history and withdrawal during processing all produce honest, source-backed outcomes. Agents 1 and 2 receive no historical content.

### Phase 6 — adapt human controls, ownership and backlog

**Factual review:** add a review kind/action for Accepted, Corrected or Insufficient factual summaries. Corrected facts require the relevant explanation/evidence, not a `cause_label`. Keep any human-confirmed cause in a separate investigation record and preserve historical diagnosis reviews.

**Human work:** starting an investigation must not imply authority to modify SAP. Retain authority/proof requirements for actual recorded corrective work. For new cases, remove dependencies on legacy mapping/playbook restoration from case-detail and human-record paths. Do not invent a target account to satisfy a form. Where validation needs expected-versus-observed evidence, accept explicitly attributed human records with existing review controls; do not present them as facts extracted from the original log. Keep old simulation endpoints limited to compatible synthetic legacy cases.

**Meaningful updates:** use guided fields and existing saved context to capture findings/evidence, action or no-change explanation, outcome, scope and gaps. Require specific reasons for blocking/reopening. A bare “fixed” cannot satisfy a resolution record, but users need not repeat details already present in linked structured fields. Field checks establish completeness; human review judges substance. Do not add a comment-scoring agent or claim character counts prove meaningfulness. Retain the rule that incomplete required records prevent resolution.

**Assignment:** preserve manual assignment throughout. Extend explicit versioned owner configuration to use supplied system/interface/company context independently of diagnosis. Preserve member/role validity, expiry, configurator identity, reasons and assignment history. Old cause-specific defaults retain their old meaning; no exact valid match or conflicting matches means unassigned. This is case-administration code, not a new diagnostic rules engine.

**Backlog and previews:** replace new-flow diagnosis badges/filters with factual analysis/review availability and observed context. Keep historical cause labels distinguishable. Reuse code-generated counts, permission-filtered snapshots and case links; count provisional records separately. Update the separate Agent 4 instructions where necessary so it does not invent causes or fixes from factual summaries. It remains outside the three-agent case workflow.

**Exit:** a new case can be reviewed, assigned, investigated and updated without a model diagnosis. Required records and human proof still matter, and mixed legacy/new cases do not distort the backlog.

### Phase 7 — evaluate and release

Create a separate log-only evaluation path rather than relabelling the diagnostic oracle as ground truth. Reuse the saved-case queue, repeats, budget controls, stage usage records and Arize experiments; bind results to workflow/schema/prompt/rubric/input/history versions.

Start with reviewed expectations for MD-01/MAP-01 originals and a compact set of meaningful variations. Expand using representative real samples. Define what must be extracted, what must reach the brief, acceptable uncertainty and prohibited inferences before scoring. Keep semantic quality, software correctness and human business outcomes separate.

| Test area | Required evidence |
| --- | --- |
| Intake and sources | Exact original bytes/versions; multiple accepted originals; missing identity; duplicate/conflicting delivery; no sidecar requirement; accurate provenance. |
| Extraction and references | Exact values/leading zeroes, source/item/attempt scope, unfamiliar content retained, incorrect spans/quotes rejected and uncovered content visible. |
| Selection and summary | Essential facts and uncertainty retained; empty-selection path; useful bullets; no unsupported cause, fabricated fact or recommended fix; instructions embedded in source text do not change behaviour. |
| Historical context | Correct attribution, actual source content, useful differences, no current-case answer leakage, accurate search state and citation/access/withdrawal handling. |
| Human controls | Corrected factual review without a cause, meaningful milestone records, incomplete-resolution rejection, separate human findings and preserved audit. |
| Reliability and access | Workspace isolation, evidence integrity, stage recovery, bounded retries, unknown usage, stale lease/input rejection and no duplicate side effects. |
| External JSON API | OpenAPI response validation, portal/API fact parity, complete original retrieval, pagination/snapshot consistency, legacy handling, scoped machine identity and revocation, cross-case/workspace denial, citation access, no secrets/internal payloads and no business mutations or model calls on reads. |
| Compatibility | Legacy/new cases open correctly; no cross-version checkpoint reuse; factual title persists; backlog counts and manual/automatic assignment behave correctly. |
| Evaluation isolation | Evaluation outputs never promote operational cases, assign owners, approve knowledge or satisfy human milestones. |
| User value and economics | Case comprehension, manual-log-reading effort, corrections, completion rate, latency, tokens and cost per completed case. |

Recommended release expectation: no observed critical unsupported claims, invented citations, access leaks or unauthorised side effects in the reviewed release set; all annotated essential facts must be accounted for or explicitly limited. These are proposed acceptance conditions, not achieved results or production guarantees. Establish broader quality/latency targets from the baseline and observed user needs.

Run targeted software checks during each phase. After integration, run the relevant backend suite, frontend type/build checks and focused browser journeys, then bounded actual baseline-model evaluations and human semantic review. Verify database behaviour on an appropriate test setup; SQL parsing alone is insufficient. Existing 1 October passing counts do not validate the rebuild.

## 5. Code impact map

| Area | Main existing files / functions | Intended change |
| --- | --- | --- |
| Contracts/prompts | [log_only_contracts.py](../backend/src/cfin/log_only_contracts.py), [log_only_prompts.py](../backend/src/cfin/log_only_prompts.py), [contracts.py](../backend/src/cfin/contracts.py) | Harden draft source/outcome contracts; add execution envelope and missing prompts; preserve old models for historical outputs. |
| Intake/API | [operations.py](../backend/src/cfin/operations.py): `IntakeRequest`; [intake.py](../backend/src/cfin/intake.py): `prepare_pack`, `commit_intake`; [main.py](../backend/src/cfin/main.py) | Versioned log-only request, authenticated source storage and provisional analysis. |
| External case API | [main.py](../backend/src/cfin/main.py): case/evidence routes and authentication; [operations.py](../backend/src/cfin/operations.py): `detail`; [gateway.py](../backend/src/cfin/gateway.py); [test_api.py](../backend/tests/test_api.py) | Add typed versioned JSON projections, source reads, OpenAPI/examples, scoped machine identity and contract/access tests; reuse storage and case services without exposing internal dictionaries wholesale. |
| Restoration | [snapshots.py](../backend/src/cfin/snapshots.py): `restore_inputs`; [fixture_loader.py](../backend/src/cfin/fixture_loader.py) | Separate production log snapshots from the legacy fixture abstraction. |
| Orchestration | [workflow.py](../backend/src/cfin/workflow.py): executor, result, validation and fingerprint; [model_adapter.py](../backend/src/cfin/model_adapter.py) | Versioned three-stage payloads/prompts/output types, capacity checks and durable model execution. |
| Worker/publication | [worker.py](../backend/src/cfin/worker.py): `process_one`, `CloudCallLedger` | Revised stage envelope, history timing, compatible recovery and factual case projection. |
| Historical evidence | [knowledge.py](../backend/src/cfin/knowledge.py): search/registration/revalidation; [gateway.py](../backend/src/cfin/gateway.py) | Bounded authorised case/log reads, selected-fact queries, cited-source eligibility and graceful history failure. |
| Database commands | [supabase/migrations](../supabase/migrations) | New migration for versioned intake, enqueue, stage saving, projection, reviews/routing and history handling; preserve installed migrations and existing data. |
| Case and intake UI | [api.ts](../frontend/src/lib/api.ts), [intake-panel.tsx](../frontend/src/components/intake-panel.tsx), [case-workflow.tsx](../frontend/src/components/case-workflow.tsx), [citation-picker.tsx](../frontend/src/components/citation-picker.tsx) | Typed new payloads, log upload, factual renderer, embedded originals, claim-level source navigation and factual review. |
| Ownership/backlog/history UI | [case-controls.tsx](../frontend/src/components/case-controls.tsx), [case-worklist.tsx](../frontend/src/components/case-worklist.tsx), [operations-overview.tsx](../frontend/src/components/operations-overview.tsx), [knowledge-panel.tsx](../frontend/src/components/knowledge-panel.tsx), [insights.py](../backend/src/cfin/insights.py) | Remove new-flow cause prerequisites while preserving real human findings, ownership, permissions and exact counts. |
| Evaluations | [evaluation.py](../backend/src/cfin/evaluation.py), [eval_runner.py](../backend/src/cfin/eval_runner.py), [live_evaluations.py](../backend/src/cfin/live_evaluations.py), [arize_evaluation.py](../backend/src/cfin/arize_evaluation.py), [evaluations-panel.tsx](../frontend/src/components/evaluations-panel.tsx) | Separate factual rubric/dataset path and version-aware saved-run interpretation; retain legacy regressions and Arize infrastructure. |

Extend the existing intake, snapshot, workflow, adapter, worker, stage-resumption, operations, completion, knowledge, insights and evaluation tests where they exercise the changed behaviour. Add dedicated log-only contract/source tests where needed. Read the installed Next.js guidance required by [frontend/AGENTS.md](../frontend/AGENTS.md) before frontend implementation.

## 6. Migration, cutover and rollback

1. **Introduce compatibility first.** New readers distinguish legacy from log-only records. Existing records default to their actual legacy meaning; missing metadata must not silently identify them as new.
2. **Apply additive changes.** Add the required fields/contracts and guarded command branches. Review the latest SQL function definitions and preserve wrappers, grants and immutability triggers. No destructive reset or historical JSON rewrite.
3. **Keep new dispatch controlled during integration.** Use the existing paid-mode/budget controls and a small explicit new-flow rollout switch if needed. A new workflow version must be pinned when a job is queued, not guessed when it executes.
4. **Handle queued legacy jobs explicitly.** Pause or process them through compatible legacy code; never run an old snapshot through new prompts automatically. An intentional new analysis creates a new versioned run.
5. **Enable the reviewed slice.** Validate saved originals, case projection, history, human updates and the baseline report before directing normal new intake to the new flow.
6. **Rollback without data loss.** Disable new dispatch/intake if necessary and use a compatibility release that can still read both formats. Retain additive schema and originals. Do not send new logs into the old diagnostic path as an automatic fallback or delete new records to make an old binary work.

Cross-run caching, wider file support and additional models follow measured need. No automatic backfill, mass rerun, knowledge approval, schema deployment or paid execution is authorised merely by writing this plan.

## 7. Implementation and release checklist

- [x] New intake accepts supplied text originals and application metadata without legacy sidecars; truthful provenance and capacity checks are explicit.
- [x] All three agreed agents and baseline model configuration are connected with structured outputs and durable stage bindings.
- [x] Extraction, selection, coverage limitations and factual title/bullets have dedicated contracts and validation.
- [x] Complete originals, exact-version line citations, downloads and full extraction are exposed in the factual portal.
- [x] Versioned JSON reads, OpenAPI, scoped machine identity, revocation and source/pagination consistency are implemented; customer-specific Joule wiring and external writes remain separate.
- [x] Bounded reviewed history reaches Agent 3 only; search status, attribution, access and withdrawal handling remain explicit.
- [x] Factual reviews, manual/context assignment and meaningful human investigation milestones are implemented without diagnostic prerequisites.
- [x] Explicit legacy branches preserve earlier outputs, assignments, human findings and audit meaning.
- [x] Unsupported sizes, missing identity, failed/stale results and access changes have visible paths; focused frontend type/build/browser checks passed.
- [x] Recorded final local integrated regression evidence: 767 backend tests with the real PostgreSQL harness, Ruff, six external-consumer tests and frontend type/build/browser checks. Intended-cloud execution remains a separate release gate.
- [ ] Obtain human review of factual expectations and actual model-generated results; publish the measured baseline separately from software scores.
- [ ] Measure cost/latency from actual provider runs and case comprehension/manual-reading effort with representative users; document limitations.
- [ ] Complete the intended-environment cutover/rollback and hosted recovery checks before declaring production readiness.

The implementation fulfills the software work packages; the remaining checkboxes are observed release evidence. No checkbox grants human approval, fabricates model-quality success or records an SAP action. See [BUILD](BUILD.md) for the current release ledger.
