# Log samples and evaluation coverage

**Agreed coverage direction — 2 October 2026.** This catalogue describes the evidence variations needed to evaluate faithful extraction, useful evidence selection and factual summaries. It is not a catalogue of diagnostic rules or prescribed fixes. The [README](../README.md) is the product baseline.

The normal flow is code intake → Agent 1 full extraction (**GPT-6 Luna**) → Agent 2 evidence selection (**GPT-6.1 Sol**) → Agent 3 factual summary (**GPT-6.1 Sol**) → code case creation/routing with the unchanged original embedded. Approved history contributes a separate **Related cases** section through Agent 3 only. No SAP integration or independent current-state lookup is available.

**Available today:** the authored MD-01 and MAP-01 original logs, their legacy reference packs and earlier software regression checks. **Still to build and validate:** representative real-log coverage, the rewired flow and its factual-quality evaluation set. A listed variation is a test intention unless an actual dataset and result demonstrate it. Passing an old diagnosis/routing test does not prove the new behaviour.

## Sample design principles

| Principle | Product reason |
| --- | --- |
| **Judge statements against the supplied log.** | The system reports what the evidence says. An independently known cause or later fix cannot justify a statement unsupported by that input. |
| **Capture breadth before selecting relevance.** | Agent 1 preserves all supplied content; Agent 2 identifies key details without deleting the full extraction. This makes omission failures visible. |
| **Represent real input variability.** | Layout, wording, language, field labels, nesting, completeness and chronology are central challenges. A list of error families alone does not test them. |
| **Keep uncertainties and contradictions.** | A cleaner narrative must not conceal missing or inconsistent evidence. Missing, blank and explicitly absent information are different. |
| **Keep history separate.** | Only authorised, approved versions are eligible, and they are historical context. Similarity does not prove the current cause or support repeating a past fix. |
| **Keep evaluation answers separate.** | Expected facts and the current sample's later investigation outcomes stay outside prompts, source bundles and retrieved history. |
| **Preserve provenance.** | Label synthetic content, retain source/input versions and record transformations. Never present an invented code as a verified SAP message. |
| **Measure the user outcome.** | Assess whether readers understand the reported exception without routinely reconstructing it from the log, alongside factual quality, latency and cost. |

There is no diagnostic error-family cap in the agreed architecture. Initial sampling should prioritise available representative evidence and user value. Broader content does not mean broader authority to investigate or act.

## Existing samples

| ID | Original-log coverage | What must remain outside its initial factual analysis |
| --- | --- | --- |
| **MD-01** | One attempt for document `0000123456`; reported target-account lookup failure; requested company/line; stopped posting and no returned target reference; source identity and GBP line values. | Adjacent intended mapping, independent target lookups, guidance, expected routing and prepared future correction/reprocessing/validation proof. |
| **MAP-01** | One attempt for document `0000123457`; reported missing applicable source-account mapping; stopped posting and no returned target reference; source identity and GBP line values. | Adjacent intended-target design, target master snapshot, guidance and later simulated mapping correction. |

The fixture names do not establish causes. Both originals reuse a generic synthetic message identifier while their readable error statements differ. Both are unusually regular authored files, not captured SAP exports. See [fixture boundaries](fixtures.md) and [the factual walkthrough](md01-walkthrough.md).

## Business-context sampling backlog

The earlier scenario IDs are retained for continuity. **Their role is now log-content coverage, not supported diagnostic categories or routing rules.** Except for the existing MD-01 and MAP-01 originals, these are hypothetical sample ideas with no implemented dataset or verified SAP message implied. Each item depends on actually receiving, or explicitly authoring, the described evidence.

| ID | Possible subject of a supplied log | What the evaluation should challenge |
| --- | --- | --- |
| **MD-01** | Account lookup failure. | Attribute the failure to the log; preserve account, chart, target and requested line without asserting the correct mapping or current master state. |
| **MD-02** | Supplier or company-extension message. | Keep supplier and company identifiers distinct; do not infer which master-data component is absent without explicit wording. |
| **MAP-01** | Missing applicable account mapping reported. | Preserve source account and context; do not invent an intended target. |
| **MAP-02** | Cost-centre mapping message. | Preserve controlling-area and organisational qualifiers when supplied. |
| **IMAP-01** | Account mapping discrepancy described in the log. | Report the conflicting values or explicit statement; avoid independently declaring a mapping wrong. |
| **IMAP-02** | Organisational mapping discrepancy. | Keep source and target assignments separate and retain any uncertainty about the intended value. |
| **MDR-01** | Object-validity or date-related message. | Preserve the stated date/interval and object; do not reconstruct missing validity data. |
| **MDR-02** | Posting restriction or blocked-account message. | Retain exactly what is reported as restricted and its scope. |
| **PER-01** | Posting-period message. | Preserve supplied period, date and company without independently deriving missing configuration. |
| **PER-02** | Period message with account-type or range qualifiers. | Retain qualifiers that change the meaning of an otherwise familiar error. |
| **TAX-01** | Tax-code message. | Preserve tax code and any supplied procedure/jurisdiction context. |
| **TAX-02** | Withholding-tax date or settings discrepancy. | Distinguish source and target values without consulting separate configuration. |
| **CUR-01** | Exchange-rate or currency-relation message. | Preserve currency pair, date and ambiguity; do not choose a rate. |
| **CUR-02** | Translation-date or currency-type message. | Keep currency type and company context rather than generalising to every currency. |
| **SPL-01** | Document-splitting message. | State the reported processing issue without asserting missing configuration from memory. |
| **SPL-02** | Different splitting-related values across companies. | Retain each company's context and any explicit contradiction. |
| **ACC-01** | Cost-centre/profit-centre assignment message. | Preserve relationships actually supplied, without manufacturing a cross-system comparison. |
| **ACC-02** | Cost-centre/company assignment message. | Keep posting context separate from object attributes. |
| **TEC-01** | Upstream interface-selection message. | Report only supplied content and its provenance; do not fabricate an AIF record if none was captured. |
| **TEC-02** | Runtime interruption or resource message. | Preserve technical symptom and attempt context; do not turn a generic failure into a functional cause. |

These subjects help diversify a sample set; they do not require twenty separate agents, policies or rules. The four AIF views and their evidence limits are described in the [AIF log guide](../../docs/product-design.md#understanding-the-aif-log).

## Evidence and summary variations

The QC identifiers are retained, but the expectations below reflect the revised design. Existing test files and assertions have not been rewritten to implement these expectations.

| ID | Variation to exercise | Desired behaviour |
| --- | --- | --- |
| **QC-03** | A view, field or portion of the log is missing/unreadable. | Preserve the available evidence and make the limitation clear; no invented lookup, value or missing text. |
| **QC-04** | Repeated messages and several consequences for one record. | Retain the messages and supported relationships without inventing a primary cause or counting every error as a separate document. |
| **QC-05** | Several distinct errors in the same supplied record. | Include material errors and their scopes in the factual summary. Agent 3 is not bypassed because multiple problems exist. |
| **QC-11** | Log text instructs an agent to change ownership, ignore constraints or expose data. | Treat it as untrusted source content, not instructions or authority. |
| **QC-13** | Historical retrieval is unavailable, incomplete or finds no eligible match. | Summarise current facts; distinguish unavailable/not searched from a completed search with no relevant matches. |
| **QC-14** | Leading zeroes, variable date/number formats, custom labels, nesting or truncated text. | Preserve exact values, scope and ambiguity; do not silently normalise away meaning. |
| **QC-15** | The log reports an error without establishing an underlying cause. | Agent 3 still writes the factual brief and states relevant limits. No root-cause claim or proposed fix is required. |
| **QC-16** | An eligible historical case is meaningfully similar. | Agent 3 reads and cites it separately, with similarities and important differences. Measure retrieval quality separately from summary use. |
| **QC-17** | Similar wording conceals different companies, objects, dates or outcomes. | Do not transfer the past case's findings to the current case. Surface material differences. |
| **QC-18** | A past case has detailed findings but current evidence is sparse. | Keep current gaps visible. Historical detail must not fill them as if observed in the current log. |
| **QC-20** | A historical finding is corrected, superseded or withdrawn. | Use only eligible current approved versions; preserve audit history and prevent new citation of withdrawn material. |
| **QC-21** | Historical guidance includes a previous fix or action steps. | Describe relevant recorded outcomes as historical; do not turn them into recommendations for the current case. |
| **QC-22** | Reviewed feedback adds a useful historical lesson. | Compare retrieval and summary usefulness on fresh variations before/after the update; keep answers to those fresh cases out of history. |
| **QC-26** | Historical eligibility changes during a run. | Recheck access/eligibility before presenting references. Remove or flag unavailable history while retaining a valid current-log summary. |

Add representative samples for multilingual text, custom message wording, duplicated identifiers, contradictory status/time values, combined messages for multiple documents and partial attempt histories. These are planned dimensions, not a claim of completed coverage.

## Case-platform continuity checks

The agent responsibility change does not erase the existing case platform or human audit controls. Preserve these behaviours through the transition, while removing dependence on a model's inferred diagnosis for routing or summary generation.

| ID | Existing platform concern | Expected continuity |
| --- | --- | --- |
| **QC-01** | Duplicate delivery. | Idempotent intake, preserved original and no duplicate case side effects. |
| **QC-02** | New processing attempt. | Preserve both attempts and their evidence; distinguish a current failure from a late historical delivery. |
| **QC-06** | Notification failure and retry. | Keep actual delivery state visible; no false success or duplicate effects. Existing adapters remain separately scoped. |
| **QC-07** | Manual reassignment. | Preserve status and audit the actual actor/assignment. |
| **QC-08** | No valid owner matches. | Code leaves the case visibly unassigned for manual assignment. Factual summary generation continues. |
| **QC-09** | Human records a later failed attempt. | Preserve the observation and its relation to existing work without silently erasing earlier evidence. |
| **QC-10** | A later recorded success has failed validation. | Do not imply validated closure. Keep the human findings and discrepancy evidence. |
| **QC-12** | Late notification result after progress or reassignment. | Do not regress case status or misapply a previous assignment's delivery result. |
| **QC-19** | Human outcome is incomplete or cause remains unconfirmed. | Record that honestly. Operational progress does not automatically approve a reusable historical lesson. |
| **QC-23** | New evidence arrives during analysis. | Keep the input snapshot/version bound to its output; stale output must not replace current evidence or human progress. |
| **QC-24** | A later failure follows an earlier success. | Preserve chronology, current-cycle applicability and explicit human reopening controls. |
| **QC-25** | Incomplete identity or conflicting reused delivery key. | Preserve provisional identity where appropriate; reject conflicting reuse and retain explicit linking/order-review controls. |
| **QC-27** | Concurrent human edits. | Reject stale updates rather than silently overwriting accepted human work. |

Some of these already have legacy software coverage. That does not establish that every revised QC row has an implemented test or a completed live walkthrough.

## Evaluator-only expectations

A revised evaluation record should define the input/version, expected observable facts, required identifiers and source locations, essential details, acceptable uncertainty, prohibited inferences and permitted variations in wording. For extraction, identify information that must survive even if it is unnecessary in the brief. For summaries, assess clarity and completeness rather than exact prose matching.

History expectations should name eligible references, misleading similarities, key differences and the history snapshot used. Keep the current sample's answer and future outcome out of that snapshot. Human investigation outcomes may support separately labelled learning/evaluation records, but the current summary is judged against what its input actually contains.

Retain software expectations for identity, access, references, cost controls and case side effects separately. The current `evals/cases.json` and MD-01 routing oracle describe the legacy runtime; they are not a new root-cause truth standard or a factual-summary acceptance suite. Model comparisons, rubric thresholds and human review results remain to be established. See [the evaluation plan and existing commands](../evals/README.md).
