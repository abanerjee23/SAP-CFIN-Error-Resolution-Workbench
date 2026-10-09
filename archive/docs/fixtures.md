# Supplied logs and synthetic fixtures

**Agreed direction — 2 October 2026.** The MVP turns the supplied original log into a factual case. Code receives and preserves it; Agent 1 extracts it with **GPT-6 Luna**; Agent 2 selects essential evidence with **GPT-6.1 Sol**; Agent 3 uses the same Sol model to write a concise, friendly summary with a separate **Related cases** section. Code creates and routes the case with the complete original embedded. See [the product architecture and AIF reading guide](../README.md).

The existing MD-01 and MAP-01 packs were created for the earlier diagnosis-and-guidance runtime. Their original logs remain useful synthetic samples. The surrounding reference packs, expected routes and simulated future proof do not define the new agent input or its factual-quality standard. The factual workflow is now wired through a versioned branch; the older packs remain legacy regression inputs. Human-reviewed factual expectations and actual provider results are separate release evidence.

## Current evidence boundary

| Material | Role in the agreed MVP |
| --- | --- |
| **Supplied original log, including any provided views/details** | The golden record for current-case statements. Extract the complete supplied content, preserve exact values and source locations, and identify limitations. The original remains unchanged and embedded in the case. |
| **Ingestion metadata** | Code records receipt, identity/version, fingerprints and delivery information. Application metadata must not be presented as a fact independently observed in SAP. |
| **Full structured extraction** | Agent 1 preserves all entries and fields, including unfamiliar or ambiguous material. Agent 2 selects relevant entries without deleting the rest. |
| **Reviewed historical cases and their evidence** | Authorised, approved versions may be retrieved for Agent 3 only. Cite relevant past cases separately, state similarities and material differences, and label past findings as historical. |
| **Independent source postings, mapping designs, target lookups and playbooks** | Outside the current-case evidence boundary. These files remain in the repository for the legacy runtime and regression tests; their presence beside a log does not make them current MVP input. |
| **Expected answers and later case findings/proof** | Excluded from initial agent input, prompts and retrieval for that evaluation case. A later outcome cannot retroactively establish what an earlier log showed. |

We have no SAP integration in this MVP. A statement such as “the log reports that the account could not be located” is supported by its wording; an independent claim about current target master data is not. A factual summary does not require a confirmed cause or an approved playbook. All three agents form the normal flow.

Pydantic defines each agent's structured output. Schema and reference checks protect handoffs; they do not prove that every fact was extracted or interpreted correctly. The initial schema is provisional until representative real AIF samples are available.

## What the two original logs actually support

Both files are explicitly fictional application logs, not SAP exports. They assert no SAP release, message class, message number or standard interface semantics. Identifiers and monetary values must retain their supplied formatting and leading zeroes.

| Sample | Facts present in the original | Limits of those facts |
| --- | --- | --- |
| **[MD-01 original](../../fixtures/MD-01/agent-visible/original-log.txt)** | Document `0000123456`, source `ERP-DEMO / 010 / 0010`, year `2026`; attempt `MD01-0001`, order `1`, at `2026-09-30T09:00:00Z`. The log reports that account `0041001000` could not be located for chart `SYN1` in `CFIN-DEMO/100`; it identifies requested company `0010` and target line `0001`. It says target posting stopped and no target reference was returned. | This is the recorded report for one attempt. It does not independently establish the intended mapping, the exact reason for the lookup failure, current target state or a corrective action. |
| **[MAP-01 original](../../fixtures/MAP-01/agent-visible/original-log.txt)** | Document `0000123457`, the same fictional systems and year; attempt `MAP01-0001`, order `1`, at the same timestamp. The log reports no applicable mapping for source account `0000400000` in company `0010`. It says target posting stopped and no target reference was returned. | The original does not state an intended target account, prove the target account exists or demonstrate how mapping should change. Those details occur in the separate legacy reference pack. |
| **Context common to both** | The log describes the source as posted, records its posting date/time, and shows two GBP lines: debit `1250.00` and credit `1250.00`. | Describe these as supplied log values. Do not imply an independent source-document verification, a complete accounting export or a later successful replication. |

“MD-01” and “MAP-01” are fixture identifiers. Their names are not additional evidence that an agent may use to fill missing facts or declare a root cause. The two samples also reuse a generic synthetic message identifier while their readable error statements differ: preserve both, rather than classifying from the identifier alone.

The [walkthrough](md01-walkthrough.md) illustrates the target factual output. The [coverage catalogue](scenario-catalogue.md) expands evaluation beyond these two unusually regular examples.

## Building representative log samples

Use real, appropriately prepared examples when available and retain their provenance. Until then, label authored content as synthetic and record every variation made. A test should exercise a meaningful uncertainty or reading challenge, rather than simply restating its expected answer.

- Include available message identity, processing context, log entries, payload hierarchy, values and error details. Do not invent a missing view to complete a template.
- Vary wording, field labels, ordering, language, nested structures and the amount of supplied context. Include incomplete, unfamiliar and contradictory content.
- Preserve exact wording and source locations. Keep missing, blank, unreadable and explicitly absent information distinct.
- Separate attempts and documents only where the supplied evidence supports the relationship. Repeated error messages do not necessarily represent additional documents.
- Keep expected factual statements, essential omissions and prohibited inferences in evaluator-only records. Do not reveal them through filenames used as semantic clues, prompts or searchable history.
- For history tests, use a separate eligible past case. Keep the current evaluation case and its future findings out of the historical corpus. Record the history snapshot/version used.
- Record model, prompt, schema and input versions so later model comparisons use equivalent evidence.

These are sample-design requirements. The full variation set and revised evaluation harness still need to be built and reviewed; the existing tests do not establish this coverage.

## Legacy fixture packs retained for runtime compatibility

The current loader still expects nine files under each `agent-visible/` directory. That historical directory name does not authorise all nine files for the revised log-only agents. Changing the loader is implementation work, not part of this documentation update.

| Existing file | Existing purpose | Treatment in the revised design |
| --- | --- | --- |
| `manifest.json` | Delivery, fingerprint, identity, attempt and context metadata. | Preserve as existing intake/control data; revise the input contract without treating separately supplied business assertions as log evidence. |
| `original-log.txt` | Exact UTF-8 fictional original, with LF endings. | Current-case evidence for the new flow. Preserve and cite the original. |
| `source-posting.json` | Separate source header and line records. | Legacy input only; no independent source lookup in the target flow. |
| `mapping-reference.json` | Candidate mapping or independent intended-target design. | Legacy input only; not a prerequisite for a factual summary. |
| `target-master-lookup.json` | Synthetic target lookup results. | Legacy input only; never describe these as a live MVP SAP query. |
| `target-master-query-audit.json` | Synthetic query scope/completeness and result audit. | Legacy input only; does not independently verify the current log. |
| `missing-gl-master-playbook.json` | Generated draft guidance and review metadata. | Legacy input only; recommended fixes are outside the revised summary. MAP-01 retains this historical filename too. |
| `owner-directory.json` | Fictional owner roles, without authenticated member bindings. | Retained legacy data. Code routing needs valid ownership configuration and actual accessible members. |
| `source-catalogue.json` | Existing source/version IDs and allowed citation locators. | Retain for existing loader/tests; future references must remain within the revised evidence boundary. |

MD-01 uses `MD01-*` source identifiers and failed attempt `MD01-0001`; MAP-01 uses its own `MAP01-*` identifiers and `MAP01-0001`. Versioned reference sources and failure-time observations have different meanings and must retain their original identities/timestamps.

All shipped reference approvals remain `pending_review`; actual reviewer, approval time and approved version are unset. Synthetic reviewer labels in tests are not human approval. Existing review records and controls must be preserved, but they do not gate the target factual summary.

## Intake and immutable restoration

**Existing implementation contract, retained for compatibility.** The portal can load either starter, download an editable bundle or accept a JSON bundle. `GET /api/scenarios/{scenario_id}` returns `manifest`, `original_log` and `agent_files`; the last contains the eight allowed JSON files. `POST /api/intakes` accepts the pack with workspace, delivery key and acting role. This endpoint has not yet been converted into a standalone-log uploader.

The present limits are 1 MiB per saved input and 10 MiB for the complete pack. The loader validates the declared files, typed shapes, original hash, identities, versions and citation locators; it rejects path escapes, undeclared sources, mismatched hashes and imported proof/answers. Agents must not gain unrestricted repository-search access as a shortcut around the input boundary.

An identical delivery returns its saved intake. Different content under the same delivery key is rejected. Changed source bytes require a new version; reusing a source ID/version requires exactly matching bytes, including serialization. Revised evidence keeps its attempt identity/time/order where appropriate; a genuinely different processing attempt needs its own metadata. The request without `agent_files` exists only for unchanged MD-01 compatibility.

Workers restore exact private, hash-verified saved inputs. They do not reload a local fixture to fill missing operational evidence. Provisional identity, explicit attempt ordering and compatible-case linking preserve existing audit records. Linking does not transfer approval or closure; existing canonical-intake and order-review controls still apply. See [design rules](design-rules.md) for the current transition plan.

## Expected answers, simulated proof and human records

`fixtures/MD-01/expected/` and `fixtures/MD-01/simulated-proof/` remain outside initial agent input and retrieval. `expected/routing-oracle.json` defines earlier diagnosis/guidance routing expectations; it is regression evidence, not the acceptance oracle for the revised factual summary.

The prepared correction, reprocessing and target-validation files describe possible later synthetic observations. Their journey plan has actions marked `not_executed`, with actual actors/times unset. Existing simulation and human-attestation controls remain separate: a prepared file, simulator response or uploaded attachment does not establish an actual correction, successful reprocessing, Passed validation or a human decision. Earlier success cannot satisfy a later failure.

Case feedback, investigation findings, outcomes and human review remain valuable records. Eligible approved versions can become separately cited historical context for Agent 3 through the existing knowledge lifecycle. Neither a generated case nor a passing test automatically publishes a lesson. [Evaluation guidance](../evals/README.md) distinguishes log-faithfulness checks, legacy software results and actual human outcomes.
