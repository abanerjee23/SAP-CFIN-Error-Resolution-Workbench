# MD-01: from supplied log to factual case

**Agreed walkthrough — 2 October 2026.** This describes the revised MVP experience: code intake → full extraction → evidence selection → factual summary → case creation and routing. The original log stays embedded in the case, and reviewed historical references appear separately. The target flow is implemented behind the factual rollout gate; this walkthrough remains an illustrative acceptance journey, not a claim of a completed model run or human signoff. `/preview/factual` demonstrates the renderer with hand-authored synthetic content.

Agent 1 uses **GPT-6 Luna** (`gpt-6-luna`). Agents 2 and 3 use **GPT-6.1 Sol** (`gpt-6.1-sol`). Additional models can be compared later on the same samples. Arize AX remains the project's evaluation and observability platform. See [the architecture](../README.md), [input boundaries](fixtures.md) and [evaluation guide](../evals/README.md).

## What the user supplies

The example is [MD-01's original log](../../fixtures/MD-01/agent-visible/original-log.txt). It is an authored fictional application log, not a verified SAP export. Its consistent layout is convenient for a walkthrough, but it does not represent the variability we expect from actual AIF data.

The original describes source document `0000123456`, company `0010`, fiscal year `2026`, source `ERP-DEMO / 010`, and target `CFIN-DEMO / 100`. Attempt `MD01-0001`, order `1`, is recorded at `2026-09-30T09:00:00Z`.

The original's key statements are:

- **Line 12:** account `0041001000` could not be located for chart `SYN1` in `CFIN-DEMO/100`.
- **Line 13:** requested posting company `0010` and target line `0001`.
- **Line 15:** target posting stopped for this attempt; no target document reference was returned.
- **Line 17:** evidence is limited to this attempt, and error wording alone does not establish an approved diagnosis.

The adjacent mapping, master-data lookup and playbook files belong to the legacy fixture pack. The revised agents must not consult them to establish facts about this case. The log does not confirm the intended account mapping, independently verify current master data or tell us what anyone should change.

## Follow the case through the revised flow

| Step | What the system does | What a reviewer should be able to see |
| --- | --- | --- |
| **1. Code receives the evidence** | Save the complete original unchanged, record its source/version and receipt details, check duplicate delivery, and queue analysis. | A stable original and a traceable intake. Receiving the log does not require an agent. |
| **2. Agent 1 extracts the full log** | Capture every supplied entry and field into the provisional Pydantic schema. Preserve wording, timestamps, leading zeroes, amounts, source/target context and limitations. | The processing start/finish, source status, both GBP lines, both reported errors and final qualification remain available with source locations. Nothing is dropped merely because it is not selected for the brief. |
| **3. Agent 2 selects key evidence** | Select entries needed to understand the exception: document identity, attempt context, reported account lookup failure, requested line/company, reported posting outcome and evidence limit. | A focused set of references to the full extraction, including uncertainty. Selection does not turn an error statement into a verified root cause. |
| **4. Agent 3 writes the case content** | Produce a factual title and concise, friendly bullets. Include material limitations. Search eligible reviewed history and inspect relevant retrieved case/log content before citing it separately. | The reported failure is understandable without routine manual reconstruction. Related cases, if present, have references, similarities and important differences. |
| **5. Code creates and routes the case** | Compile the summary, evidence links, limitations and complete original. Apply valid ownership configuration using supplied context. | The user can expand the original to validate any statement. If no valid owner matches, the case remains visibly unassigned for manual assignment. |
| **6. People review and contribute feedback** | Existing case controls capture corrections, investigation findings and outcomes with their authors and times. | Feedback remains auditable. Approved historical learnings may later inform Agent 3 through the existing review/versioning lifecycle. |

All three agents are part of the normal flow. Summary generation does not wait for root-cause confirmation, a diagnostic rule or approval of a fix. No SAP lookup, correction, reprocessing or validation action is performed by this analysis pipeline.

## Illustrative user-facing summary

**Document 0000123456: target posting stopped after a reported account lookup failure**

- The log reports that account `0041001000` could not be located for chart `SYN1` in target `CFIN-DEMO / 100`. The requested posting company is `0010`, for target line `0001`. *(Original log, lines 12–13.)*
- Attempt `MD01-0001` is recorded at `2026-09-30T09:00:00Z`. The log says posting stopped and no target document reference was returned. *(Lines 3, 15–16.)*
- The source is recorded as document `0000123456`, company `0010`, year `2026`, in `ERP-DEMO / 010`, with status `posted`. *(Lines 4–6.)*
- This log covers one attempt. It does not establish the underlying cause or a later processing outcome. *(Line 17 and the scope of the supplied evidence.)*

**Related cases:** no historical references are fabricated for this example. In a real run, this section would show cited matches after an actual eligible-history search. “No relevant cases found,” “history unavailable” and “not searched” are distinct states and must be reported accurately.

This is illustrative wording, not a saved model output or a measured quality result. The final presentation should preserve essential details and readable references without forcing every extracted field into the short summary. The full extraction and original remain available.

## How history should contribute

When an eligible past case is retrieved, Agent 3 reads its available case details/log evidence and checks whether the comparison is meaningful. A useful reference names the past case, identifies the matching details, highlights important differences and attributes any recorded outcome to that historical case.

For example, a past case reporting the same account and chart may be relevant, but a different company, target environment or attempt context can matter. Similar wording alone does not establish the same cause. A past fix must not become a recommendation to repeat it. Agent 2 receives no history in the agreed design.

Human findings and feedback enter history through the existing review and approval lifecycle. Current-case expected answers and later findings are excluded from retrieval during evaluation of its original failure. Learning is retrieval of reviewed material, not automatic retraining.

## MAP-01 variation

[MAP-01's original](../../fixtures/MAP-01/agent-visible/original-log.txt) uses document `0000123457` and attempt `MAP01-0001`. Its key error says that no applicable source-to-target mapping was found for source account `0000400000` in company `0010`. It also records stopped target posting and no returned target reference.

The same three-agent flow should state those facts and their scope. It must not import intended target account `0041001000`, existing target master components, approved designs or proposed changes from the adjacent legacy JSON files; those facts are absent from the supplied original. See [the MAP-01 guide](../fixtures/MAP-01/README.md).

Both originals reuse the generic synthetic identifier `DEMO_GL_LOOKUP_FAILURE`, despite different message wording. This is a useful reading check: extraction preserves the identifier and actual text; the summary follows the supplied statement rather than guessing from the identifier or fixture name.

## Existing application and local checks

The existing portal, private evidence storage, saved cases, attempts, assignment, human records, learning lifecycle and evaluation queue are assets to reuse. The runtime still uses `cfin-specialists-v3`, with the older preparation/diagnosis/conditional-guidance responsibilities. The draft log-only contracts and summary prompt do not change that runtime by themselves. Existing mapping/playbook approvals and correction simulations therefore remain legacy behaviour, not steps required by this walkthrough.

For local access, run `make readiness`, `make api` and `make web` using [local development guidance](local-development.md). Readiness checks configuration presence; it does not prove live credentials, model quality or the revised workflow. Keep secrets in the existing local environment files and out of reports.

The current intake screen still accepts the full legacy bundle. It has not yet been converted into a standalone-log upload. Do not remove required files from a bundle and expect the current parser to accept it. Existing saved-case identities, original hashes, attempts and human audit records should survive the transition.

`make eval-gates` and `make eval-replay` run the legacy software checks. `make arize-smoke` exercises automatic SDK tracing with a local HTTP fake and no cloud export by default. These do not execute or validate the proposed log-only flow. No paid call is needed for this documentation or walkthrough.

The existing worker can dispatch both operational and evaluation jobs when paid mode is enabled. From `backend`, `PYTHONPATH=src uv run python -m cfin.worker --once` handles at most one claimed job, subject to its configured controls. Do not treat that command as a way to run the new architecture before it is implemented. Paid mode remains disabled by default.

## What will establish a successful baseline

Use the same saved log across model comparisons, and record input, prompt, schema and model versions. Review the extraction first, then the selection and summary: a readable brief cannot compensate for silently lost evidence.

Check factual support, exact identifiers, source references, essential omissions, visible uncertainty and separation of historical context. Assess whether a support analyst can understand the exception without opening the original, while still being able to validate every important statement. Record corrections, latency, usage, cost and failures alongside quality scores.

The earlier real Luna preparation attempts failed validation before the downstream stages. Earlier backend tests, scripted replay and Arize software experiments establish bounded implementation behaviour, not a successful current-model baseline. Historical details remain in [the implementation log](implementation-log.md); the [evaluation guide](../evals/README.md) defines the revised evidence standard.
