# Evaluation and Arize observability

**Agreed evaluation direction — 2 October 2026.** The product must faithfully turn the supplied original log into a useful factual case. Evaluate extraction, evidence selection and summary quality against that log, with historical context assessed separately. Root-cause accuracy and recommended fixes are not the MVP's objective.

**Arize AI (Arize AX) remains the project's evaluation and observability platform.** Automatic OpenAI Agents instrumentation and native experiments are already integrated. The saved-case queue and earlier reports still exercise the legacy runtime. The opt-in factual executor and SDK adapter now have dedicated software tests and an originals-only fixture corpus; operational integration and a measured model-quality baseline remain pending.

## Factual foundation — software checks and draft expectations

[log_only_fixtures.py](../../evals/log_only_fixtures.py) reads only the hash-pinned MD-01/MAP-01 original text files. Eleven cases cover the originals, missing identity, contradictory outcomes, unfamiliar content, embedded instructions, multiple/repeated originals, empty/blank input and invalid UTF-8. Readable inputs pass through the production `LogInputs` boundary and exact numbered payload; the builder never reads sidecars, expected answers or later proof.

[log-only-expectations.json](../../evals/log-only-expectations.json) is **evaluator-only and pending human review**. It records source-backed facts, qualifications and prohibited inferences. It must never enter an agent payload or retrieved-history corpus. The corpus supplies no accuracy score, acceptance threshold or production-coverage claim.

Run the factual software suite from `backend`:

```sh
uv run pytest -q tests/test_log_only_*.py
```

These tests use explicit test doubles or a replaced SDK runner. They check source integrity, handoff/reference validation, factual/legacy boundaries, budget/usage handling and checkpoint recovery, including a full three-stage run and a zero-call same-run resume. They make no paid model calls and do not assess semantic extraction or summary quality. The operational evaluation CLI below remains legacy-only until saved-run persistence and publication are migrated.

## Baseline and comparison discipline

| Stage | Baseline model | What to evaluate |
| --- | --- | --- |
| **Agent 1 — Full extraction** | **GPT-6 Luna** (`gpt-6-luna`) | Completeness and faithful preservation of supplied entries, values, context, source references and uncertainty. |
| **Agent 2 — Evidence selection** | **GPT-6.1 Sol** (`gpt-6.1-sol`) | Whether the selected evidence includes the essential facts, qualifications and contradictions needed to understand the case. |
| **Agent 3 — Factual summary** | **GPT-6.1 Sol** (`gpt-6.1-sol`) | Accuracy, useful completeness, readability, citation support and correct separation of related historical cases. |

Compare additional models later using equivalent input, prompt, schema and history snapshots. Record stage-level and end-to-end results so a downstream fluent answer cannot hide extraction loss. Current configuration defaults to `medium` reasoning effort; retain effort as an explicit comparison variable.

The architecture is code intake → three agents → code case creation/routing with the unchanged original embedded. There is no diagnostic rules engine, comparator, separate verification agent or conditional summary gate. Pydantic/reference checks remain normal code controls, not proof of factual accuracy. Only Agent 3 receives eligible reviewed history.

## What a revised quality baseline must measure

| Quality dimension | Evidence of useful behaviour | Typical failure |
| --- | --- | --- |
| **Extraction completeness** | All supplied entries and fields survive the structured handoff, including unfamiliar content and material qualifiers. | A field, later error or processing qualification disappears because it does not fit the familiar template. |
| **Exact values and context** | Identifiers, leading zeroes, amounts, dates, source/target distinctions and document/item scope are preserved. | Correct-looking value attached to the wrong item, system or attempt. |
| **Traceability** | Every material statement has a valid source location that actually supports it. | Valid-looking citation points to the wrong line or does not support the claim. |
| **Evidence selection** | The brief includes essential errors, affected records, reported outcomes and uncertainty; the full extraction remains available. | Important evidence is omitted, or repeated messages are counted as separate affected documents. |
| **Factual restraint** | “The log reports…” stays distinct from independently verified system state. Missing and conflicting information remains visible. | Inferred root cause, invented lookup result or implied current status beyond the supplied evidence. |
| **User-facing clarity** | Friendly, professional wording, a factual title and readable bullets preserve essential details. | Long undifferentiated prose, excessive repetition or brevity that drops crucial qualifiers. |
| **Historical references** | Actual eligible past cases are cited separately with meaningful similarities and differences. | A past cause/fix becomes a current fact or recommendation; an unavailable search is described as no matches. |
| **Instruction handling** | Logs and historical case text are treated as evidence. | Embedded instructions change behaviour, access, ownership or output constraints. |
| **Operational usefulness** | Readers can understand the exception without routinely reconstructing it from the original, while retaining access for validation. | Users still need to inspect the full log to discover essential facts omitted from the case. |
| **Reliability and cost** | Completion/failure rates, latency, actual token usage, cost and human corrections are recorded together. | Strong-looking quality score hides retries, incomplete output, unknown usage or excessive effort. |

Define the reviewed rubric and acceptance thresholds before claiming success. No numerical quality target or successful baseline has yet been established for this revised flow. Human ratings should include reasons and required corrections, not only a pass/fail label.

## Dataset and answer boundaries

MD-01 and MAP-01 supply authored original logs, not representative customer exports. Real AIF samples are still needed. Build variations covering wording, layouts, custom labels, multiple errors, missing sections, nested records, attempt histories, contradictory content and unfamiliar values; the [coverage catalogue](../docs/scenario-catalogue.md) distinguishes existing samples from planned coverage.

For current-case facts, evaluate against only the supplied original and its included views/details. Adjacent source postings, mapping designs, target lookups and playbooks are legacy inputs and cannot establish truth for the revised log-only pipeline. Their presence in the repository does not authorise access.

Keep expected facts, prohibited inferences and the current sample's later investigation outcomes outside agent input and retrieved history. History tests need a separately versioned eligible corpus; test whether Agent 3 retrieves and cites useful context without treating it as current proof. Record the history snapshot and actual retrieval status. Case feedback may become future historical learning only through the existing review/approval lifecycle.

Measure software correctness, model semantics and human business outcomes separately. Valid JSON is not accurate extraction; a completed Arize experiment is not a successful model baseline; a factual case summary does not establish a correction or successful posting.

## Software regression checks — legacy runtime

The following commands remain accurate for the current implementation. They exercise `cfin-specialists-v3`, its original preparation/diagnosis/conditional-guidance responsibilities and the earlier twelve-case MD-01 suite. They do **not** run the proposed log-only workflow or implement the rubric above.

`cases.json` is evaluator-only. `build_eval_inputs(case_id)` makes an in-memory variation through the restricted fixture loader without loading expected answers or future proof. Its simulated reviewer metadata is explicitly evaluation-only, never human approval. Legacy negative-lookup and injected-source variations remain unchanged for regression continuity.

From the repository root, with the existing Python environment:

```sh
PYTHONPATH=backend/src backend/.venv/bin/python -m cfin.eval_runner --mode gates --output evals/results/gates.json
PYTHONPATH=backend/src backend/.venv/bin/python -m cfin.eval_runner --mode replay --output evals/results/replay.json
PYTHONPATH=backend/src backend/.venv/bin/python -m cfin.eval_runner --mode replay --case-id md01-pending --repeat 3
```

`make eval-gates` and `make eval-replay` are the equivalent project entry points. Gate mode challenges the legacy code routing without executing an agent. Replay uses `ScriptedStageAdapter`, with scripted stage outputs derived from inputs. Assertions cover the old route, references, source/context binding and human prerequisites. These are software expectations, not factual-quality acceptance thresholds for the new design.

CLI `--mode live` fails closed. The internal `evaluate_workflow(..., mode="live")` accepts an explicitly constructed budgeted executor, and the existing saved-case queue below supports model execution through the shared worker. Neither is an independent unbudgeted provider path. No command was run as part of this documentation update.

## Arize automatic logging and native experiments

The existing integration uses `OpenAIAgentsInstrumentor` for native SDK activity and Arize experiments with code evaluators over saved observations. Operational spans are buffered until the business commit. Transport acceptance and independent server readback are distinct evidence. Project configuration remains `cfin-document-error-analysis`; credential/setup guidance is in [local development](../docs/local-development.md).

From the repository root, `make arize-smoke` runs an offline SDK capture using a local HTTP fake and synthetic usage. It makes no real provider/judge call, case change or cloud export. The equivalent command runs from `backend` so settings load its local `.env`:

```sh
cd backend
PYTHONPATH=src .venv/bin/python -m cfin.arize_smoke \
  --output ../evals/results/arize-auto-smoke.json
```

`--upload` explicitly tests configured OTLP export. Use a separate report and distinguish acknowledged transport from verified visibility/content. Preserve earlier reports rather than overwriting evidence already submitted for comparison.

`make eval-arize` creates an Arize software experiment from a saved legacy gate report; `ARIZE_SOFTWARE_REPORT` can choose a different report, with its path relative to `backend`. This uploads evaluation data but makes no fresh model/judge call. It still measures legacy software expectations, not the new quality rubric.

To read-only verify the previously recorded migration experiment using its original report, run from `backend`:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.arize_eval_cli \
  --software-report ../evals/results/arize-migration-gates-2026-10-01.json \
  --verify-experiment-id RXhwZXJpbWVudDoxNTMxNzA6ZGJTRw== \
  --output ../evals/results/arize-native-gates-readback.json
```

This creates no dataset, experiment or provider/judge call. Creating a new native experiment uses `--experiment-name` instead of `--verify-experiment-id`; `--dataset-id` reuses an exactly matching dataset. After an uncertain creation outcome, inspect the saved diagnostics and verify the existing result instead of blindly creating another experiment.

## Durable saved-case model evaluations

**Existing infrastructure; still attached to the legacy workflow.** The portal's Evaluations view and `cfin.live_eval_cli` queue selected saved snapshots. Before using them for the revised baseline, update their input boundaries, agent responsibilities, history connection and evaluators. Changing model IDs alone does not implement the new architecture.

A process owner can select up to thirty distinct saved cases and one to three repeats. Each needs a current ordered attempt and operational input snapshot. Evaluation runs record batch/repeat IDs, models/effort and `evaluation_only=true`. They do not promote operational cases, assign owners, approve references or satisfy human milestones.

Queueing makes zero provider/judge calls. The shared worker dispatches only when paid execution is enabled and pricing/budget controls pass; it can also dispatch queued operational jobs. Existing settings default to `PAID_MODELS_ENABLED=false`, with maximum caps of US$1 per run and US$10 per UTC month, and lower configured caps enforced. These are code limits, not a price quote or a claim of observed cost. Actual stage usage, unknown usage, retries and reservations must remain visible.

The queue example below starts from the repository root and enters `backend`; subsequent examples run from `backend`. Obtain your own signed-in session token locally as `CFIN_AUTH_TOKEN`; keep it out of chat, reports and command arguments. Replace placeholder UUIDs with actual authorised workspace, case and returned batch IDs.

Queue a legacy saved-case batch without enabling paid dispatch:

```sh
cd backend
PYTHONPATH=src .venv/bin/python -m cfin.live_eval_cli \
  --workspace-id WORKSPACE_UUID --queue \
  --case-id CASE_UUID --repeats 1 --reason "Requested saved-case regression evaluation" \
  --reasoning-effort medium \
  --output ../evals/results/model-batch-request.json
```

`--model-agent1`, `--model-agent2` and `--model-agent3` select later comparison models if pricing is configured; unknown pricing rejects the request. The response includes batch/run IDs and `paid_dispatch_enabled`. A false value means dispatch remains gated; this command does not enable it.

Read saved status without starting model work:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.live_eval_cli \
  --workspace-id WORKSPACE_UUID --batch-id BATCH_UUID \
  --page 1 --page-size 25 \
  --output ../evals/results/model-batch-status.json
```

Status includes total runs, state counts and outputs/stage usage for the selected page. Page sizes are bounded at one hundred. Without `--batch-id`, the scope is the latest twenty accessible workspace batches; `has_more_batches` identifies omitted older batches. Refresh while jobs progress rather than treating an earlier snapshot as final.

Export a batch's immutable saved outputs:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.live_eval_cli \
  --workspace-id WORKSPACE_UUID --batch-id BATCH_UUID \
  --export-saved-runs \
  --output ../evals/results/model-batch-saved-outputs.json
```

Succeeded and failed runs retain input bindings. Queued/running work is excluded from grading and counted separately. Existing saved-output checks measure binding, output availability and completion; they do not judge the revised factual rubric. Usage and costs come from actual saved stage records, with unknown usage visible.

To explicitly create a native Arize experiment over completed saved outputs:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.live_eval_cli \
  --workspace-id WORKSPACE_UUID --batch-id BATCH_UUID \
  --arize-experiment-name cfin-saved-output-regression \
  --output ../evals/results/model-batch-arize.json
```

This uses saved output and native code evaluators with automatic experiment tracing; it makes no fresh provider/judge call. `--arize-dataset-id DATASET_ID` can reuse an exactly matching dataset. A failed or uncertain upload retains diagnostics and exits nonzero; verify before attempting another creation.

Use the returned experiment ID for read-only verification:

```sh
PYTHONPATH=src .venv/bin/python -m cfin.live_eval_cli \
  --workspace-id WORKSPACE_UUID --batch-id BATCH_UUID \
  --verify-arize-experiment-id EXPERIMENT_ID \
  --output ../evals/results/model-batch-arize-readback.json
```

Preserve the exact submitted input/output set and report. If more jobs finish after an experiment was created, the batch's record set changes and exact verification should fail. A fully completed batch gives a stable comparison. Human review, reviewed thresholds and publication evidence remain separate from these software checks.

## Historical results and their limits

These are retained observations from the earlier implementation, not current acceptance claims. Reports under `evals/results/` are local/gitignored and may not exist in a fresh checkout.

| Recorded evidence | What it established | What it did not establish |
| --- | --- | --- |
| [Migration gates](../../evals/results/arize-migration-gates-2026-10-01.json) and [scripted replay](../../evals/results/arize-migration-replay-2026-10-01.json): twelve cases, 96/96 and 170/170 assertions. | Legacy MD-01 software routing/replay expectations at that revision, without LLM calls. | Representative extraction quality, MAP-01 model quality or the revised factual workflow. |
| Earlier completed build: 472 backend tests, Ruff and frontend type/build checks. | Bounded software regression evidence recorded in the implementation log. | Current runtime alignment with the revised architecture or an executed human/model journey. |
| [HTTP isolation](../../evals/results/live-isolation-2026-10-01.json): 56 assertions; [SQL transactions](../../evals/results/live-transactions-2026-10-01.json): 17 groups. | Specific access/transaction behaviour at that checkpoint. | Full cloud/restart coverage, model quality or human outcomes. |
| [First Luna attempt](../../evals/results/live-worker-attempt-2026-10-01.json) and [retry details](../../evals/results/live-auto-retry-details-2026-10-01.json). | Two preparation failures stopped before downstream stages. Incorrect line citations were observed; recorded costs were US$0.002147 and US$0.001993 respectively. | A successful model baseline. Later prompt changes were not validated by these earlier failures. |
| [Automatic Arize smoke](../../evals/results/arize-auto-smoke-2026-10-01.json) and [native software experiment](../../evals/results/arize-native-gates-2026-10-01.json). | Readback of five SDK-generated smoke spans and twelve records/96 scores with automatic experiment task traces. The smoke used a local fake; no actual provider/judge calls established these results. | Semantic quality, a paid end-to-end run or completed human review. |

Earlier Galileo and Promptfoo results are retired integration history, retained in [the implementation log](../docs/implementation-log.md). They do not replace the project's Arize choice or establish quality for the revised flow. No report, synthetic actor or software score grants historical-knowledge approval or proves a human business outcome.
