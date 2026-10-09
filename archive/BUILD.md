# BUILD — factual-case delivery and verification

Updated 2 October 2026. The rebuild now connects log-only intake, immutable originals, the three factual agents, durable execution, the portal, reviewed history, human investigation controls and versioned read-only machine access. Existing diagnostic cases remain on their explicit legacy path. Software implementation, deployment verification and human/model-quality acceptance are separate checkpoints.

Use [README](README.md) for the product architecture, [REBUILD_210](REBUILD_210.md) for the original work packages and acceptance criteria, and [the implementation record](docs/implementation-log.md) for dated verification results.

## Delivered implementation

| Area | Delivered behavior |
| --- | --- |
| Intake and originals | `POST /api/intakes/log-only` receives 1–8 separately preserved UTF-8 text originals with truthful provenance, stable delivery identity and optional administrative routing context. Initial limits are 8,192 aggregate bytes and 64 lines; unsupported input is rejected without truncation. Incomplete SAP identity stays provisional. |
| Durable storage | Additive `202610020001_log_only.sql` extends existing cases, attempts, evidence, runs, stages, reviews and commands; preserves legacy data and workflow identity. Original snapshots, hashes, leases, revision fences, evaluation isolation and same-run stage recovery remain guarded. |
| Agent pipeline | Code ingestion → GPT-6 Luna extraction → GPT-6.1 Sol evidence selection → GPT-6.1 Sol summary. Stage-specific Pydantic payloads, prompt versions, source/quote validation, limitations, usage/budget checks and explicit failure outcomes are connected through the existing Agents SDK and worker. |
| Case experience | Factual title and statements, linked source lines, uncertainty, related reviewed cases, complete expandable originals and exact-byte downloads. Full extraction is secondary. Running, stale and failed replacements are explicit. `/preview/factual` is a clearly labelled hand-authored illustration using the same renderer. |
| Reviewed history | Bounded authorised prior case/log content reaches Agent 3 only. Retrieval state, exact versions, citation eligibility, independent access and withdrawal are checked. Historical findings remain separate from current-log facts. |
| Human controls | Factual Accepted/Corrected/Insufficient review without a cause prerequisite; investigation scope, meaningful findings/action-or-no-change/outcome/scope/gaps, stored proof and explicit attestation. Completion explicitly distinguishes corrective work from no change; corrections require separate authority and final resolution must match completed work. Reprocessing chronology and posting validation remain human evidence. |
| Assignment and backlog | Manual assignment and versioned exact-context owner defaults retain valid membership, reason and expiry checks. Factual availability/review filters are separate from labelled legacy diagnosis/cause filters. Provisional records remain distinct from known-document counts. |
| External reads | Versioned typed case/source/extraction/human-record reads and OpenAPI, snapshot-consistent bounded pagination, exact originals, scoped revocable machine credentials and read audit. No model calls or business-state writes occur on GET. Customer-specific Joule wiring and external writes remain separate work. |
| Evaluation | A distinct factual fixture/rubric/report path, held-out expectations, saved-run version binding, bounded model execution and cost/latency accounting supplement existing legacy regressions. Exports recheck historical access; a pending human review packet binds actual saved output to source/model/prompt/rubric versions. Software checks do not establish factual quality or human acceptance. |

No diagnosis, recommended fix, live SAP lookup, SAP write or additional analysis agent is added to the factual workflow. The existing optional backlog explanation remains separate.

## Verification ledger

- The safe external consumer passed six offline tests for exact UTF-8/BOM/CRLF originals, integrity rejection, version recovery, page binding and credential transport controls; example Ruff checks passed.
- Frontend TypeScript checking and production compilation passed after the factual UI, human controls, source navigation and filters were integrated.
- Browser verification of `/preview/factual` confirmed citation navigation to original lines 11–13, all 17 original lines, source-download availability, full extraction disclosure and stale/failed replacement messages. Browser console errors/warnings were absent.
- All nine migrations applied to disposable local PostgreSQL 17 + pgvector 0.8.6. The rollback-only factual transaction harness and existing legacy completion harness passed; no cloud migration is inferred.
- **767 backend tests passed in 10.52 seconds, with no skips**, including the real local PostgreSQL transaction harness and 16 offline cloud-acceptance runner tests. Backend and example Ruff checks passed; the six external-consumer tests passed separately. See the [software report](../evals/results/full-build-software-2026-10-02.json) and [implementation record](docs/implementation-log.md#2-october-2026--full-factual-build-and-integration-verification). The earlier 646-test result remains historical.
- Local Docker images built; API health/OpenAPI and the factual preview returned HTTP 200. The final frontend image also passed an actual citation click check at `localhost:3001/preview/factual`: the original expanded and lines 11–13 were visible in the viewport, with no console warnings/errors. See the [production-container screenshot](../evals/results/factual-production-citation-2026-10-02.png). This is distinct from hosted deployment and recovery.
- The current Railway TypeScript deployment manifest passes official SDK type and graph checks through `make railway-check`; CI includes this check. The former per-service JSON files remain historical recipes. No remote plan or hosted deployment was run.
- Intended-environment database/Auth/Storage behavior, actual provider baseline runs, human semantic review and hosted recovery are distinct checks. Local database execution, a compiled portal, a software score or a synthetic preview does not imply that those checks passed.

The 1 October 472-test result and eight applied migrations remain historical evidence for the legacy application. Earlier paid Luna failures and Arize smoke/experiment records retain their original scope.

## Release gates

`LOG_ONLY_ENABLED` defaults to false. Verify and apply only the new additive migration on the intended database before enabling factual intake/dispatch. API and worker must agree on the release and workflow versions. `PAID_MODELS_ENABLED` independently controls paid provider execution; enabling the intake flag does not establish model readiness or approve spending.

The following require observed release evidence:

- A saved original reaches a factual case through actual database commands; duplicate/conflicting deliveries, failed storage, stale leases/revisions and recovery behave correctly.
- Scoped machine credentials can read the authorised saved projection and exact originals; expired/revoked/cross-workspace callers and inconsistent snapshots are denied.
- Human-authored expectations and model outputs receive actual semantic review, covering essential-fact retention, unsupported claims, prompt injection, ambiguity and historical attribution. Do not mark fixtures human-approved automatically.
- Representative users assess comprehension, required log inspection and correction effort. The software currently makes no measured time-saving or accuracy claim.
- Hosted sign-in, private evidence, worker recovery, monitoring, budget reconciliation and rollback are exercised in the intended environment.

See the current run reports for actual quality/latency/cost observations; those measurements are not promises of future performance. The initial input envelope is intentionally small and should grow only after representative source and provider-capacity evidence.

## Cutover and rollback

1. Preserve the existing database and evidence. Apply unapplied additive migrations once through a reviewed administrator step; application startup never migrates automatically.
2. Deploy a compatibility release able to read factual and legacy records. Existing queued legacy jobs retain their pinned legacy workflow; no automatic rerun or reclassification occurs.
3. Verify actual database transactions, authenticated source reads, history eligibility, human controls and machine access. Keep the factual flag and paid execution disabled until their respective checks and authorisations are satisfied.
4. Enable the bounded reviewed slice; observe failures, latency, cost and review corrections before expanding intake.
5. To roll back, disable `LOG_ONLY_ENABLED` and paid dispatch, stop affected workers, and deploy a compatible reader. Preserve additive schema, immutable originals, human records, audit and cost ledgers. Never pass factual originals into diagnostic prompts as fallback or delete factual data to support an old binary.

Deployment definitions retain Next.js/FastAPI/Supabase/OpenAI Agents SDK/Arize AX and Railway targets. The build does not establish a hosted deployment, SAP/Joule connection, enterprise throughput or wider binary-document support. See [deployment](docs/deployment.md) and [local development](docs/local-development.md).
