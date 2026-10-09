# CFIN exception-management MVP brief

**Agreed product baseline — 2 October 2026.** This brief describes the intended experience. [README](../README.md) explains the architecture and AIF evidence; [design rules](design-rules.md) define behaviour; [BUILD](../BUILD.md) distinguishes implementation from remaining work.

## User, problem and outcome

CFIN support analysts and process owners need to understand document-processing exceptions without repeatedly reconstructing the story from scattered log messages, identifiers and payload fields. The product turns the supplied log into a concise, factual case with traceable evidence and useful historical references.

The product's main value is reliable extraction and evidence selection. The intended outcome is that a reader can understand the reported exception from the case brief, opening the embedded original when they want to review or validate it. Accuracy, reading effort and time saved require measurement.

The AI does not diagnose the root cause, suggest a fix or perform SAP work. People can investigate and record their findings through the existing case workflow. Those human records remain distinct from the AI summary.

## Agreed workflow and model baseline

| Step | Owner | Product responsibility |
| --- | --- | --- |
| Ingestion | Code | Receive the supplied log, preserve it unchanged, record source identity/version and queue analysis. |
| Extraction | Agent 1 — **GPT-6 Luna** | Capture all supplied entries, fields, context and uncertainty into a provisional structured schema. Retain unfamiliar content and source references. |
| Evidence selection | Agent 2 — **GPT-6.1 Sol** | Select the key reported errors, affected items, context, outcomes, contradictions and gaps from the full extraction. |
| Summary | Agent 3 — **GPT-6.1 Sol** | Write friendly, concise factual bullets with references. Read eligible historical cases/logs and cite them separately under **Related cases**. |
| Create case and route | Code | Compile the brief, embed the complete original and apply valid ownership configuration or leave assignment visibly outstanding. |
| Review and learning | People and existing case infrastructure | Capture meaningful findings and outcomes; review what may become historical context for future Summary Agent runs. |
| Case JSON API | Code | Serve saved case data, state and original logs to authorised external tools through a versioned read contract. |

Model IDs are `gpt-6-luna` and `gpt-6.1-sol`. This is the starting benchmark; add comparisons later using the same examples and quality criteria. No model-quality superiority is assumed.

There is no diagnostic rules engine, parallel code extraction, comparison agent or separate verification agent. Routine schema, reference, access and persistence checks remain code responsibilities. Pydantic structures agent outputs; it does not prove their factual correctness or completeness.

## Evidence boundaries and the case experience

- **Current-case facts come from the supplied original log.** There is no SAP integration or independent master-data/mapping lookup in the MVP. Absent content is a visible limitation, not a finding about SAP.
- **Variable inputs are expected.** AIF views can contain structured fields and natural-language text, but a universal export format is not assumed. Real samples will shape the provisional schema.
- **Extraction retains breadth.** Exact values, leading zeroes, source/target distinctions, item relationships and processing attempts must survive. Agent 2 selects relevant entries without discarding the stored full extraction.
- **The brief is user-facing.** Use plain language, a short factual title and scannable bullets. Include essential details and uncertainty; do not reproduce the entire log or hide facts behind an arbitrary length limit.
- **Every case embeds the complete original.** All supplied views remain accessible alongside the AI content, with evidence references back to their source locations.
- **History feeds Agent 3 only.** References explain specific similarities and important differences. Historical findings are attributed to the previous case, never treated as proof of the present cause or an instruction to repeat a fix.

## External consumption and future automation

Case data must be available as JSON as well as on the case page. The rebuild includes a documented, versioned API with OpenAPI, scoped machine authentication and access to the factual brief, full extraction, selected evidence, originals, limitations, related references and permitted human records. Large results remain fully retrievable through bounded pages/source requests, with versions and timestamps making freshness explicit.

A future SAP Joule tool can use this API to bring case context into the customer's SAP workflow. The exact connection is a later integration; the analysis agents and model baseline do not change. Later case-state commands and SAP-side actions require separate authority. Case writes retain meaningful comments, valid transitions, proof and audit; original logs remain immutable.

Joule operating in a customer's SAP environment does not automatically authorise access to this app or make external calls risk-free. Apply scoped credentials, workspace/case/evidence permissions and access audit. Keep app status, reported SAP status, AI wording and human findings distinct in the API. See [README](../README.md#case-data-as-a-json-api) for the business flow and verified SAP references.

## Meaningful human updates and learning

At key milestones, a generic “fixed” or “done” comment is insufficient. People record what they found, the supporting evidence, what changed or why no change was needed, the outcome and unresolved details. Blocking and reopening need specific reasons. A case cannot be treated as resolved while its required resolution record is incomplete.

Reuse existing case details so users do not have to repeat them in free text. Code requires the relevant fields and links; human review determines whether the content is meaningful and supported. Preserve authorship, time and earlier records.

The existing knowledge review, approval, versioning, access and withdrawal controls remain. Completing a case does not automatically publish a lesson. Eligible historical material is retrieved for the Summary Agent; the learning loop does not automatically retrain a model.

## Success measures and risks

| Question | Evidence to collect |
| --- | --- |
| Did extraction preserve the supplied facts? | Message/field coverage, exact identifier accuracy, source-reference validity and explicit handling of unfamiliar or unreadable content. |
| Did the brief retain the essentials? | Essential omissions, unsupported claims, lost qualifications and human corrections. |
| Can users understand the case efficiently? | Comprehension, reading time and how often the original must be opened to recover missing information. |
| Are historical references useful? | Relevance, valid citations, meaningful differences and separation of past findings from present evidence. |
| Is the workflow practical? | Completion/retry rates, stage latency, tokens and cost per completed case. |

Evaluate incomplete captures, custom wording, long inputs, repeated attempts, contradictions and misleading historical matches. Treat instructions embedded in logs or historical material as untrusted content. Do not expose private case data outside its authorised workspace. Keep expected answers and later case findings out of evaluation inputs and retrievable history.

## Delivery position

The existing portal, storage, case controls, worker, feedback infrastructure, backlog overview and observability are reusable. The provisional [handoff schemas](../../backend/src/cfin/log_only_contracts.py) and [summary prompt](../../backend/src/cfin/log_only_prompts.py) are drafted. They are not yet connected to the running workflow, which still uses the earlier diagnosis/resolution responsibilities.

The next increment is to connect the revised three stages, log-only input and Summary Agent history access; adapt the case rendering and any diagnosis-dependent controls; and establish a measured baseline. Existing MD-01/MAP-01 examples are synthetic and their old diagnostic tests do not validate the revised flow. Representative real AIF logs remain a priority.

Keep the existing OpenAI Agents SDK, Next.js/FastAPI, Supabase and Arize AX foundation. Deployment definitions target Railway; hosting and production capacity remain separate verification work. This documentation revision does not add a platform migration, new SAP integration or automatic remediation scope.
