# MVP design rules

**Agreed baseline — 2 October 2026.** These rules define the revised log-only product. [README](../README.md) provides the business overview and AIF guide; [BUILD](../BUILD.md) records integration work. The existing runtime still uses earlier diagnosis/resolution contracts. A rule described here is a product requirement, not evidence that it is already wired or validated.

## Evidence and agent responsibilities

**Code ingestion → Agent 1 extraction → Agent 2 evidence selection → Agent 3 summary → code case creation and routing.** The original also passes unchanged from ingestion into the case. Reviewed case history feeds Agent 3 only.

| Responsibility | Rule |
| --- | --- |
| Ingestion — code | Receive the supplied log, preserve its original bytes and included sections, record source identity/version and receipt metadata, deduplicate deliveries and queue processing. Do not interpret business errors at intake. |
| Agent 1 — GPT-6 Luna | Extract all supplied entries and fields into the provisional schema. Preserve exact identifiers, leading zeroes, wording, source/target scope, hierarchy and attempt context where present. Retain unfamiliar content as unclassified; record ambiguities and extraction limitations. |
| Agent 2 — GPT-6.1 Sol | Select essential evidence from Agent 1's full output: reported errors, affected records, context, consequences, material warnings, contradictions and gaps. Use existing source references. Do not add facts, perform SAP checks or search history. |
| Agent 3 — GPT-6.1 Sol | Write a factual case brief from selected evidence, preserving material uncertainty. Read eligible historical case/log content and cite it separately under Related cases. Do not infer causes or suggest actions. |
| Case creation and routing — code | Compile the structured output, limitations and references, embed the full original and assign using valid supplied context/configuration. Keep unassigned cases visible. Agents do not directly mutate cases or choose authenticated owners. |
| Human updates and history | Record meaningful findings, work and outcomes through existing case controls. Review, version and approve eligible knowledge before reuse. Learning is retrieval of reviewed material, not automatic model training. |

Model IDs are `gpt-6-luna` for Agent 1 and `gpt-6.1-sol` for Agents 2 and 3. These are the baseline for later measured comparisons. The existing medium-effort default and bounded cost controls remain.

There is no diagnostic rules engine, parallel code extraction, comparison agent or separate verification agent. All three agents normally run; an unknown cause or lack of a playbook is not a reason to bypass the factual summary. Input, access, budget or execution failures still stop dependent processing safely and remain visible.

### Current-case evidence boundary

The supplied original log is the golden record for current-case statements. It may contain multiple exported views or sections. No SAP integration, external mapping/master-data lookup or independent business reference is available to these agents in the MVP. Historical findings and later human comments must not silently become facts attributed to the original log.

AIF's structured concepts do not guarantee a uniform export. Capture what is actually supplied; never manufacture an omitted view, message code, timestamp, intended mapping, complete chronology or confirmed system state. Distinguish a missing section, a blank field and an explicit logged “not found” statement. Preserve conflicting entries instead of choosing a convenient interpretation.

All logs, case content and retrieved history are untrusted source material. Instructions embedded in them cannot change agent behaviour, permissions or workflow. Read tools are limited to authorised internal evidence and eligible history; they do not provide live SAP access.

### Structured handoffs and checks

All agents return Pydantic-defined output. The provisional [log-only contracts](../../backend/src/cfin/log_only_contracts.py) separate full extraction, evidence selection and case summary. They currently locate supplied text by source line; real formats may need additional locators after sample review.

Code checks the output shape, source identity/version, reference membership and eligible historical versions. Agent 2 must select existing extracted entries; Agent 3 must cite selected evidence for its current-case title and statements. Retain the entire extraction even when only some entries are selected. Render extraction limitations alongside the brief.

These checks do not establish completeness or semantic truth. Measure omissions, misreadings and unsupported statements through reviewed examples. If essential evidence was not captured or selected, expose the limitation; do not let downstream fluency disguise an incomplete result. Do not add a verification agent to solve this by default.

## Factual summary and reference rules

The Summary Agent produces user-facing content. Its [draft system prompt](../../backend/src/cfin/log_only_prompts.py) is the starting specification for these requirements:

- Use a friendly, calm, professional tone with plain language and a short factual title.
- Lead with what the log reports, then the affected records/objects, relevant identifiers, material messages, reported outcome and uncertainty.
- Use separate concise bullets wherever they improve scanning. Keep one clear point per item; avoid one long paragraph and unnecessary repetition.
- Retain essential details without an arbitrary bullet cap. Do not reproduce the whole log in the summary.
- Preserve exact values and source/target/item/attempt distinctions. Use “the log reports” where a statement is a recorded observation rather than independently verified system state.
- Do not diagnose a root cause, recommend fixes, prescribe SAP commands, assign responsibility or imply successful resolution.
- Treat long-text advice as supplied content; extraction can retain it without the summary adopting it as a recommendation.

Every case contains the full unchanged original, including every supplied view, with reference navigation. An excerpt or external link alone does not meet the embedding requirement. The original supports optional review and validation; routine comprehension should come from the brief.

### Related cases

Only Agent 3 uses the reviewed-history connection. It should inspect actual retrieved case/log evidence before citing it, explain specific similarities and important differences, and keep historical findings or outcomes clearly attributed to that prior case. A past fix is not a current recommendation and similarity does not prove a shared cause.

Copy real case IDs, source references and knowledge versions from authorised retrieval results. Code constructs valid case links; the agent must not invent URLs. Preserve exact versions for audit and apply existing access/withdrawal checks before publishing the new brief.

A completed search with no relevant result, an unavailable search and a search not performed are different states. Display the correct state. The normal factual brief does not depend on finding a historical match.

## Portal appearance

Keep the user-selected ElevenLabs-inspired neutral appearance: near-white canvas, white work surfaces, dark text, black primary controls, neutral borders and locally bundled Inter. Use compact navigation, plain functional headings, a scannable worklist and a stable detail panel. The revised flow does not require a new portal or theme.

`/preview` remains a labelled synthetic preview; `/preview/studio` redirects to it. Preview data stays separate from authenticated records and must never substitute for failed persistence or real case results. Preview interactions do not approve knowledge or execute analysis.

## Semantic tags and case context

Keep observed evidence, AI wording and human investigation findings distinguishable. Do not populate a diagnosis label merely because an old table or control expects one.

| Field | Ownership and meaning |
| --- | --- |
| Source/document/item context | Agent 1 captures values explicitly supplied in the log. Code preserves provenance and validates relationships. Missing identity stays unknown. |
| Reported error / affected object | Preserve the message and object labels as supplied. A report that an account could not be found is not an independent finding of missing master data. |
| Analysis availability and limitations | Make incomplete, failed, stale or unavailable analysis visible. Do not represent schema-valid output as verified fact. |
| Priority | Code applies configured business defaults; process owners record overrides. Log message severity alone does not determine business urgency. |
| Human findings | People record their findings, evidence and cause confirmation or uncertainty separately from immutable AI output. Accepting summary wording does not confirm a root cause. |
| Ownership / operational status | Code and authorised people administer the case. Assignment, successful reprocessing, validation and knowledge approval remain separate events. |

The existing runtime's `AI-supported` diagnosis labels and cause categories belong to its earlier workflow. Preserve historical records, but reconcile those fields and displays during integration rather than deriving new diagnoses from factual summaries.

## Case identity, attempts and reruns

| Event | Rule |
| --- | --- |
| First intake | Preserve the original before analysis. Code may create the intake/provisional case first and compile the brief later. Storage failure must remain visible and must not produce an apparently analysed case. |
| Canonical identity | Keep workspace, source system/client/company, fiscal year, document number, target system/client and interface distinct where available. Preserve identifiers as strings. The existing manifest supplies these today; revised extraction must not invent missing business keys. |
| Missing identity | Retain a provisional case and request the necessary context through existing controls. Supplied facts can still be represented, but do not invent correlation or claim a unique affected document. Current runtime gates based on complete identity need reconciliation with the revised flow. |
| Repeated delivery | Same delivery key and same content returns the existing intake without a duplicate run/notification. Same key with different content is a visible conflict requiring a new revision. Similar wording alone never justifies merging cases. |
| New attempt | Append the attempt to the same document/target case only when identity supports it. Keep its source/version, recorded order/time and receipt time distinct. Identical text does not make attempts interchangeable. |
| Current versus historical | Use supplied processing order/time rather than upload arrival order. Ambiguous order requires human review; a late older upload cannot replace a newer outcome. |
| Revised evidence | Save a new source version without overwriting the original. Mark affected analysis for refresh and preserve earlier AI and human records. |
| Rerun / checkpoint reuse | Reuse only compatible stage outputs tied to the same case/attempt, source versions, context, prompt, schema and model configuration. Changing the workflow invalidates incompatible legacy checkpoints. Identical text in another attempt cannot reuse old citations. |
| Late result | Tie every run to its saved input snapshot. A late result cannot replace a newer current analysis or overwrite human progress. |
| Later failure | Flag a new current failure for review. Earlier successful reprocessing/validation cannot resolve it; reopening preserves the earlier cycle and requires a specific human reason. |

Keep existing explicit rerun controls after intake. New historical knowledge alone does not automatically rerun existing cases. Preserve assignments, due dates, human findings and milestone records when the AI is rerun.

## Human ownership, priority and due dates

Code owns assignment; the process owner chooses an actual eligible workspace member or configures an applicable default. Uploaded names and model text do not create authenticated owners. Missing or ambiguous ownership stays **Unassigned — Owner assignment required** and does not block summary generation.

Existing automatic defaults are tied to supported diagnoses and exact business scope. They cannot be assumed compatible with a flow that produces no diagnosis. During integration, preserve manual assignment and apply automatic defaults only when valid non-diagnostic context/configuration supports them. Do not fabricate causes, silently broaden rules or overwrite human assignment.

Existing workspace roles are `process_owner`, `master_data_owner`, `mapping_owner`, `finance_owner` and `validator`. Demo labels are fictional; the audit records the actual signed-in person and acting role. One person exercising several demo roles is not independent sign-off.

| Priority | Existing rule | Due date |
| --- | --- | --- |
| P1 — Low | Process owner records lower urgency. | Keep the two-business-day default; no automatic extension. |
| P2 — Medium | Default for new cases unless a valid configured rule or human override applies. | Two business days after creation. |
| P3 — High | Process owner or valid configuration establishes time-sensitive impact with a recorded basis. | One business day after creation or priority change. |

Sort P3 → P2 → P1. Business days are Monday–Friday in Europe/London; holidays are not modelled. Assignment, reruns and blocking do not restart or pause the deadline. Extensions, priority changes and reopening preserve actor, time and reason. These existing defaults do not assert a customer SLA.

## Meaningful comments and human review

Meaningful updates are mandatory at key milestones; “fixed”, “done” or an unexplained attachment is insufficient. Capture information once using the case's existing structured fields and evidence rather than requiring duplicate free-text comments.

| Situation | Required human content |
| --- | --- |
| Corrected or insufficient AI brief | Explain what is wrong or missing; support corrected factual claims with evidence. Keep changes separate from the original AI output. |
| Blocked or reopened work | State the specific blocker or reason for returning to active work. |
| Work completed | State what changed, the affected object/system, performer/time and supporting evidence. Explain explicitly if no change was needed. |
| Resolution record | Findings and evidence; cause confirmed or explicitly unconfirmed; action/no-change explanation; scope and reuse limitations; outcome/proof; unresolved details; person/time. |

Code can require fields and valid references; it cannot establish meaningfulness just from length or nonempty text. People judge relevance, support and accuracy through the existing review process. This requirement does not add an AI comment-scoring agent.

## Milestones, proof and resolution fields

Retain the existing human case lifecycle: **Created, Owner Notified, In Progress, Blocked, Complete, Document Reprocessed**. Validation remains **Pending, Passed or Failed**. A successful notification is distinct from assignment; delivery is simulated in the current POC.

| Milestone | Required record |
| --- | --- |
| Review | Record Accepted, Corrected or Insufficient against the AI brief; Corrected/Insufficient needs a reason. Review of factual accuracy is separate from human cause confirmation. |
| Complete | Correction or no-change explanation, object/system, person/time and stored proof explicitly reviewed by the human. |
| Document Reprocessed | Successful result for the applicable document/attempt, target reference, person/time and saved result proof. A retry alone is insufficient. |
| Validation Passed / Failed | Record expected-versus-observed posting checks, discrepancies or justified non-applicability, reviewer/time and supporting evidence. Failed validation keeps resolution open. |
| Return to active work | Record a reason, retain prior milestones and reset current validation appropriately. A new successful attempt needs its own validation. |

**Resolved** remains a derived outcome: successful reprocessing and Passed validation for the latest applicable attempt/current cycle, known attempt order, no unreviewed newer failure, and a complete resolution record. An incomplete record keeps resolution incomplete. Cause may be explicitly unconfirmed; successful posting does not prove a cause.

Reusing proof requires explicit applicability to the current attempt/cycle. Uploaded files and AI prose are not human attestations. The supplied AI log remains unchanged even when people later attach investigation or outcome evidence. Current correction/reprocessing/validation fixtures and external notifications are simulated; no SAP action is performed by the app.

## Reviewed knowledge and maintenance

Keep the existing **Pending review, Approved, Rejected and Withdrawn** lifecycle. Case resolution, acceptance of an AI brief and permission for historical reuse are separate decisions. A person must review the exact version and its applicability; software tests do not create approval.

| Responsibility | Rule |
| --- | --- |
| Resolver / contributor | Record useful findings and evidence, with honest uncertainty and scope. Completing a case cannot self-publish a lesson. |
| Process owner / reviewer | Assess support, relevance, scope and reuse limitations; approve or reject the exact version through existing controls. |
| Retrieval | Supply only currently authorised, eligible reviewed versions to Agent 3. Read relevant case/log evidence and preserve exact citations. |
| Correction / withdrawal | Record a new version and review decision. Materially disputed or withdrawn versions stop being eligible; recheck in-flight references and preserve past audit records. |
| Feedback iteration | Use observed omissions, incorrect statements and unhelpful references to prioritise prompt, schema, retrieval or UX changes; evaluate them on held-out examples. |

Existing publication controls include evidence-backed human cause confirmation, complete applicable successful validation, defined scope, exact-version approval and an attested model-quality report meeting configured criteria. Those controls are not removed by this documentation change. They govern reuse of historical lessons, **not** whether a new log can receive a factual summary. Their diagnosis-specific data dependencies must be reconciled during integration; do not bypass them or treat an uncertain cause as confirmed. Useful human feedback can remain pending without being published.

The existing search combines PostgreSQL text/context with deterministic local concept-vector ranking; it makes no embedding-provider call. Relevance and benefit still need evaluation. The runtime currently connects it to Agent 2; moving it and adding bounded full prior case/log reads for Agent 3 remains work. Historical findings cannot overwrite the current log or become suggested fixes.

No automated maintenance schedule is created by these rules. Preserve review/withdrawal controls and inspect new feedback during product iterations.

## Backlog overview and insights

The existing optional **Agent 4 — Backlog Insights** is a separate read-only feature, outside the revised three-agent case-analysis pipeline. Keep exact counts and charts in code and preserve permission-filtered snapshots, group links and case drilldowns.

Count distinct correlated cases separately from attempts and provisional records. Do not infer unique affected documents from repeated error entries or a replication failure rate from an exceptions-only dataset. Numerical narrative claims must reference returned metrics from the same scope/snapshot; case access is rechecked on navigation. Charts and links remain usable if AI explanation fails.

Old diagnosis categories and `AI-supported` labels need reconciliation before mixing revised factual cases into these displays. Historical classifications can remain attributed to their original analysis or human review; Agent 4 must not turn a log summary into a new inferred diagnosis or recommendation. Operational case visibility does not make a record approved historical knowledge.

Enterprise throughput, unrestricted conversational analytics and automatic bulk actions remain outside this revision. The existing single-worker implementation is not evidence of enterprise capacity.

## External JSON API and automation boundary

The rebuild must provide versioned, authenticated JSON reads of saved case data and original logs, documented through OpenAPI and an authenticated example. Reuse case/evidence services and the saved analysis; a read must not invoke agents or change business state. The three-agent workflow remains unchanged.

Return case identity/state, factual content, complete extraction and selected evidence, source references, limitations, separately attributed history and permitted human records. Expose every accepted original through an authorised manifest and source read, preserving exact text for supported text inputs and unchanged-file download access. Use bounded pages/source requests without silent truncation. Bind reads to case/run/source versions and expose freshness, unavailable content and legacy semantics explicitly.

Machine callers need explicit, revocable read access to permitted workspaces, cases and evidence over HTTPS. Record caller, resource/version, time and outcome; do not log private payloads or secrets as access telemetry. An authenticated Joule service identity is not automatically the end user's authority. Related-case citations do not grant access to those records. Existing portal endpoints and user authentication do not by themselves satisfy the external contract.

Customer-specific Joule configuration is a later integration. External case writes, if subsequently added, use separate permissions and explicit commands with duplicate protection, expected versions, allowed transitions, actual actor attribution and meaningful records. Preserve human review, proof, resolution and knowledge-publication requirements; never offer arbitrary state patches or permit changes to original logs. SAP-side changes require separate customer-controlled SAP authority. Returned results are appended as attributed evidence and do not automatically prove resolution. A consumer must treat log/history text as data, never as instructions granting permission to act.

See [the README API section](../README.md#case-data-as-a-json-api) for the product scope and [rebuild Phase 4](../REBUILD_210.md#phase-4--publish-the-factual-case-and-json-api) for the proposed contract and checks. JSON API support is required; a live Joule connection and write automation are not claimed as implemented.

## Storage, access and operation

These foundations remain in place. Exact setup and current-runtime commands are documented in [local development](local-development.md), [database foundation](database-foundation.md) and [deployment](deployment.md).

| Area | Existing choice or constraint |
| --- | --- |
| Persistence | Supabase Postgres, private Storage and Auth on the accepted Ireland project. Preserve originals, versions, run outputs and business audit. The 1 October installation record covers eight migrations; do not blindly reapply them. |
| Hosting | Local Next.js/FastAPI with cloud persistence; prepared Railway web/API/worker definitions target Amsterdam. Provisioned hosting and hosted verification are separate from prepared files. |
| Access | Enforce actual workspace membership and role checks in the backend and data policies. No anonymous case access or public evidence bucket. Service secrets stay out of browsers, prompts and telemetry. Recheck access and clear private UI state after scope changes. |
| Input limits | Current legacy intake accepts one UTF-8 log up to 1 MiB plus exactly eight JSON files, with a 10 MiB pack limit. This is not the new input contract. Revised log-only formats/limits need integration and real-sample validation; unsupported or oversized input must fail visibly, never silently truncate. |
| Proof uploads | Existing proof types are JSON, PDF, PNG, JPEG or plain text, up to 10 MiB per file. This does not imply the Extraction Agent already supports those formats as log input. |
| Durable processing | Retain snapshots, leases, stage checkpoints, late-result/version protection and the shared worker slot. Adapt compatibility checks to the revised schema and prompts before reusing outputs. Restart/concurrency behaviour still needs integrated verification. |
| Failure limits | Existing maximum is 60 seconds per stage with at most one separately reserved automatic retry within that bound; SDK/provider retries are disabled. Respect input/access/budget failures and expose exhausted retries. |
| Notifications / edits | Notifications remain simulated with durable keys and bounded retries. Reject stale human writes; record actual actor, time, version and reason. Late results do not overwrite human progress. |
| Evaluation and observability | Retain Arize AI (Arize AX), automatic OpenAI Agents instrumentation and saved-output experiments. Business state/audit stay in Postgres. Telemetry receipt is separate from verified visibility and neither proves model quality. Process-local trace buffering is not durable telemetry delivery. |
| Cost | Retain the US$25/month incremental POC planning ceiling, including up to US$10/month for model/embedding usage and US$1/run. Reserve bounded calls, reconcile actual usage and retain unknown-usage reservations. Unknown pricing blocks dispatch. These are limits, not price estimates. |
| Retention | Preserve synthetic evidence and audit history; no automatic deletion. Agree real-data retention/access arrangements before a live pilot. |

The model defaults and example configuration leave paid dispatch disabled. Documentation cleanup does not enable execution, change budgets, deploy services or create approval decisions. Existing no-call software checks remain available.

## Evaluation and remaining rollout work

Measure full-extraction fidelity/completeness, essential evidence retention, faithful concise summaries, source references, useful historical comparisons, uncertainty, no-diagnosis/no-fix behaviour, case comprehension, latency and cost. Use the same examples for baseline and later model comparisons. Expected answers and a test case's later findings must stay outside its input and retrievable history.

Existing test counts, diagnostic gates, scripted replays and native software scores are dated regression evidence for the older implementation. They do not validate the revised contracts or establish real AIF coverage. Follow [the evaluation guide](../evals/README.md) and [scenario catalogue](scenario-catalogue.md) for the revised quality plan.

The next work is integration of the agreed flow, representative log collection, schema refinement, a reviewed model baseline and targeted operational regressions. Customer-specific collection, retention, authorities, SLAs and enterprise capacity remain later pilot decisions. A successful summary does not imply successful document posting or case resolution.
