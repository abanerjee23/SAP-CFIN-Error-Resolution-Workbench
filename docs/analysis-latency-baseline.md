# Upload analysis baseline — 9 October 2026

Five batches, two files per batch: one master-data scenario and one mapping scenario.
Each file contains one fictional source document and between one and five error messages.
All ten analyses completed and matched their expected category. This is a small latency and
cost baseline, not a broad quality evaluation, concurrency test or production SLA.

| Batch | Errors per file | Mean analysis | Mean intake-to-readback | Model cost, both files |
|---|---:|---:|---:|---:|
| 1 | 1 | 47.56 s | 76.92 s | $0.077046 |
| 2 | 2 | 48.83 s | 76.54 s | $0.084225 |
| 3 | 3 | 50.04 s | 79.48 s | $0.091705 |
| 4 | 4 | 55.13 s | 89.75 s | $0.092339 |
| 5 | 5 | 57.97 s | 91.59 s | $0.101565 |

## Measurements

- Analysis: mean **51.91 s**, median **50.30 s**, maximum **59.95 s**. Nearest-rank p95
  is also 59.95 s; ten samples do not establish a reliable production percentile.
- Intake-to-readback: mean **82.86 s**, maximum **120.69 s**, including API intake,
  queue, execution, trace export and final case readback. Browser polling can add up to
  another four seconds while visible.
- Durable run creation to first model-call reservation: mean **29.01 s**, maximum
  **62.66 s**. This includes queue and startup, not pure queue time.
- **30 model calls**, **129,287 input tokens**, **50,147 output tokens**; models
  `gpt-6-luna` and `gpt-6.1-sol` using the existing stage configuration.
- Recorded model cost: **$0.446880 total**, **$0.044688 per file**. No unresolved
  reservations and no retries in these ten runs. Cost comes from the durable call ledger;
  infrastructure and observability costs are excluded.
- Arize was configured but disabled. It is now enabled in the local environment.
  All ten exports were acknowledged; **30/30 expected trace IDs were independently
  found through Arize's spans API** in `cfin-document-error-analysis`.

Both files were queued together, then processed serially by one background processor.
The second file therefore waited for the first. This deliberately exposes waiting time;
it does not measure capacity under concurrent production traffic. The broader demo processor
was paused during the controlled benchmark and restored afterward.

## Timeout and recovery decision

Keep the existing **60-second deadline per analysis stage, with one automatic retry**.
The slowest observed individual stage was 27.49 seconds. Cancelling the whole workflow at
the 51.91-second average would interrupt successful work: three observed runs exceeded it.
The deadline cancels the local await; provider-side cancellation and billing are not guaranteed.
Unknown usage remains conservatively reserved under the existing cost controls.

Injected tests verify cancellation, recovery on the second attempt, and failure after the
second timeout. They are distinct from the successful live runs above. Queue waiting is
shown separately and does not trigger duplicate model execution. The UI explains a wait
over one minute, displays automatic retry progress, and offers manual retry after failure.
Recalibrate deadlines using a larger sample and high-percentile stage latency; do not
automatically learn a cutoff from these ten samples.

## Browser verification and evidence

A separate upload of `browser-walkthrough.txt` exercised Dashboard upload, saved pending
state, reload recovery, browsing the Case Board, live progress, completion and direct opening
of CFIN-2026-000012. Its three real calls are excluded from the benchmark totals. Its queue
wait was deliberately extended while the benchmark held the processor. The walkthrough
also exposed and fixed metadata context written as `line 3`: display projection now checks
the exact cited source line while retaining source/target and literal-value validation.

No SAP reprocessing or human approval/closure is claimed by this run.

- [Test files](../fixtures/analysis-batches/manifest.json)
- [Recorded benchmark data](validation/analysis-benchmark.json)
- Generate files: `python scripts/benchmark-analysis.py` in the backend environment.
- Run the suite: `python scripts/benchmark-analysis.py --execute` (real calls; requires
  configured local API, synthetic demo workspace and enabled tracing).
- Verify server receipt: `python scripts/verify-analysis-traces.py` (read-only).

The execution script records stable intake keys and resumes its saved report without
repeating completed runs. Keep the automatic demo processor paused when collecting a
controlled serial baseline. Raw local receipts are in `.local-runtime/analysis-benchmark/`;
the checked-in evidence contains synthetic identifiers and usage only.
