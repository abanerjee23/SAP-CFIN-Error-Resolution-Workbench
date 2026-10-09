# MAP-01 synthetic log sample

**Aligned with the 2 October 2026 MVP.** This sample is useful for testing whether the system faithfully explains a reported mapping error. The agreed flow uses **GPT-6 Luna** for full extraction, **GPT-6.1 Sol** for evidence selection, and **GPT-6.1 Sol** for a factual, friendly summary. Code preserves the original and embeds it in the created case. Reviewed historical references belong in Agent 3's separate **Related cases** section.

The original is fictional application text, not an SAP export. No SAP query was executed and no correction, verified business outcome or actual human approval is implied. The revised flow still needs runtime wiring; the existing pack and tests belong to the earlier implementation.

## What the original supports

The [original log](../../../fixtures/MAP-01/agent-visible/original-log.txt) contains the following:

| Supplied evidence | What the case may state |
| --- | --- |
| Document `0000123457`, company `0010`, year `2026`, source `ERP-DEMO / 010`. | The source identity as recorded in the log. It also records the source status as `posted`. |
| Attempt `MAP01-0001`, order `1`, at `2026-09-30T09:00:00Z`; target `CFIN-DEMO / 100`. | The supplied processing context for this attempt. |
| “No applicable source-to-target mapping for source G/L account 0000400000 in company 0010.” | The log reports this mapping failure for that source account/company. Preserve the wording and scope. |
| Requested posting company `0010`, target line `0001`. | The requested company and line associated with the reported error. |
| Posting stopped; no target document reference returned; result `failed`. | The recorded outcome for this attempt, without asserting a later outcome. |
| Two GBP lines with debit and credit `1250.00`. | The supplied payload values, with exact formatting and source/line context. |
| Explicit limitation to this attempt. | The source does not establish a complete processing history or independently verified root cause. |

The log does **not** identify intended target account `0041001000`, establish that its target master components exist or authorise changing a mapping. Those details are in separate legacy JSON files. They must not leak into the revised current-case analysis.

MD-01 and MAP-01 both use the generic synthetic identifier `DEMO_GL_LOOKUP_FAILURE`, while their readable error statements differ. Preserve the identifier and text; do not infer the case's meaning from the identifier or filename alone.

## Expected user experience

Agent 1 captures the whole supplied log into the provisional Pydantic schema. Agent 2 selects the identity, attempt context, reported mapping error, affected line, outcome and material limits. Agent 3 presents these in concise factual bullets, without suggested corrections or inferred causes. Every important statement traces back to the original.

If relevant approved history exists, Agent 3 cites the actual past case and its evidence separately, explaining similarities and differences. Historical findings cannot establish the current cause or turn an earlier fix into a recommendation. No eligible match, unavailable history and an unperformed search are different states.

All three agents form the normal flow. A missing approved mapping design or playbook does not prevent a factual summary. Code routes the completed case using valid ownership configuration; if no valid owner matches, it remains unassigned for manual assignment. Existing human feedback, findings and review records remain available.

## Legacy bundle retained for compatibility

The nine files under `agent-visible/` still satisfy the existing MD-01/MAP-01 bundle loader. That historical folder name does not make all nine files eligible for the revised agents. The API has not yet become a standalone-log uploader.

The legacy pack includes a synthetic completed mapping query with `records: []`, a distinct pending intended-target design, target lookup records and draft guidance. Its `unaffected_mapping_records` keeps the separate counterpart mapping `0000200000 → 0021000000`; that record must never be represented as a result of the failed-account query. All generated approval fields remain pending, with no actual reviewer signoff.

These files and the legacy simulation paths remain intact for regression continuity. The historical simulated correction produces a `mapping_change`; later target proof retains a `mapping_correction` receipt. Existing authenticated milestone, actor, work-cycle and validation controls still apply if that older simulation is exercised. A simulator response, prepared attachment or upload alone satisfies no human milestone or Passed validation. None of these actions is part of the target log-summary pipeline.

Current intake still requires its manifest, hash, source versions, attempt metadata and matching catalogue/audits. Changed bytes require a new version; a reused source ID/version must match saved bytes exactly. Workers restore the saved private pack, not local fixture files. Provisional links preserve the alias history and existing canonical-intake/order-review requirements; they transfer no approval or closure.

The fixture's owner labels bind no actual users. Existing manual assignment requires a valid workspace member, and evaluation output never assigns an owner or promotes a case. Reusing assignment infrastructure must not reintroduce a diagnosis requirement into the new summary or routing design.

See [the complete input boundary and legacy contract](../../docs/fixtures.md), [the MAP-01 walkthrough variation](../../docs/md01-walkthrough.md#map-01-variation), and [the evaluation guide](../../evals/README.md). Legacy software tests and hypothetical approval states do not establish the new flow's quality or a successful live model baseline.
