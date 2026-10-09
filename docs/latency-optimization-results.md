# Analysis latency experiment — 9 October 2026

The local demo now uses **compact outputs with medium reasoning and two workers**.
Across the same ten synthetic files, average upload-to-result time decreased from
82.86 to 37.87 seconds (54.29%). All ten results passed automated and source-based
semantic review. Three additional hard cases also passed. This is a small synthetic
comparison, not a production latency or accuracy guarantee.

## Measured result

| Measure, same ten files | Original baseline | Selected compact profile |
| --- | ---: | ---: |
| Published and valid results | 10/10 | 10/10 |
| Mean upload-to-result | 82.86 s | 37.87 s |
| Mean analysis workflow | 51.91 s | 33.11 s |
| Mean queue plus worker startup | 29.01 s | 2.98 s |
| Recorded model cost, ten files | $0.446880 | $0.272207 |
| Model calls | 30 | 30 |
| Concurrent case limit | 1 | 2 |

Analysis time decreased 36.22%; recorded model cost decreased 39.09%. The matched
compact runs took 28.89–38.39 seconds for analysis and at most 43.70 seconds from
upload to readback. Paired uploads actually overlapped in the stage-call ledger.
The comparison includes queue/startup, trace export and API readback; it is not a
measurement of browser rendering or a production load test.

The selected full suite contains 13 files, at most five errors per file. It made
39 calls, cost $0.341809, and published 13/13 results with no model retries or
unresolved usage reservations. All 39 trace IDs were independently found in Arize.
The three extra files cover an unknown marker, competing mapping/master-data
explanations, and two attempts with different source/target identifiers. Their
outputs preserve uncertainty and chronology; there is no earlier baseline for them.

## What changed

- Extraction returns source line spans and logged fields. Code restores exact text,
  immutable source references and entry IDs, then validates full source coverage.
- The final model writes a concise narrative and open questions. Code supplies
  document context and copies selected evidence directly from the preserved log.
- Two separate Python worker processes analyse different cases concurrently. The
  database enforces two slots, exclusive ownership, lease recovery and safe cost
  reservation. Existing approval, closure and route requirements are unchanged.
- The case view now renders cited open questions. A browser check also found and
  fixed valid attempt-scoped metadata being hidden; literal field/source verification
  remains enforced. All 27 published experiment results passed actual frontend
  projection checks for 216 metadata fields, with no missing/mismatched values.

The diagnosis prompt and models are unchanged: `gpt-6-luna` for extraction and
`gpt-6.1-sol` for diagnosis and writing. The selected profile keeps medium reasoning
at every stage. Mean matched stage times are extraction 15.10 s, diagnosis 6.87 s,
and writing 10.37 s; the earlier baseline was 21.50 s, 8.11 s and 21.02 s.

## Why low reasoning was not selected

The `fast` profile uses low reasoning for extraction and writing, with diagnosis
still medium. It published 12/13 files; one master-data file failed extraction
validation twice. The model attached labels such as “target system” and “client”
to an unlabeled `CFIN-DEMO/100` fragment. The literal-evidence check correctly
rejected those invented labels, retained the original, and published no diagnosis.

The twelve published outputs passed semantic review, but a faster failed run is
not a quality-preserving improvement. This profile remains opt-in for experiments.
The same file succeeded with medium reasoning. We retain the failed run and its
traces; its failure is not removed from the experiment results.

A preceding two-file compact/medium smoke test averaged 26.24 seconds versus 47.56
for those files in the baseline. The larger matched result above supersedes that
early estimate. Across smoke plus both full candidates, this experiment made
83 model calls, recorded $0.677854, and verified all 83 trace IDs in Arize.
Costs use the saved application price catalogue, not a provider invoice.

## Verification and operation

The full backend suite passed 848 checks, including disposable PostgreSQL migration,
concurrent claim and budget race checks. An added invented-label regression also
passed in the 14-test compact suite. The frontend passed 39 tests, typechecking and
its production build; six benchmark-runner tests and scoped Python lint passed.
The rebuilt browser shows the previously missing document number and cited open
questions. The existing stage deadline and one retry remain; they were not reduced
to the average observed time.

Migrations `202610090006` and `202610090007` were applied transactionally to the
synthetic database with an empty queue. Fingerprints confirmed existing cases,
runs, evidence versions, intakes and stage-call records were unchanged. The local
private environment selects `ERROR_ANALYSIS_PROFILE=compact`; the API, frontend and
two-process demo worker are running. Repository configuration still defaults to
`baseline`, so another installation must explicitly select a profile.

For rollback, restart the API with `ERROR_ANALYSIS_PROFILE=baseline` and optionally
run the demo worker with `--workers 1`. Existing queued runs and retries keep their
saved prompt/model configuration. See [setup and reproducible commands](connected-demo.md).

Evidence: [machine-readable measurements](validation/latency-optimization.json),
[per-file semantic review](validation/latency-semantic-review.json), and the
[unchanged original baseline](analysis-latency-baseline.md). Full outputs and Arize
readback receipts remain in the ignored `.local-runtime/latency-benchmark/` directories
identified by the suite names in the measurements. Broader real-log, repeated-run,
domain-expert and load evaluations remain necessary before claiming production readiness.
