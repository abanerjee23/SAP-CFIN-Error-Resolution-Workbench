# Model comparison — 9 October 2026

**Luna with medium reasoning for writing is a promising cost-saving candidate;
Sol with low reasoning for writing showed the stronger initial latency result.**
Neither should be treated as a proven production winner yet. The main experiment
found an extraction failure, and a targeted repeat exposed inconsistent confidence
labels even with Sol diagnosis. The experiment left the demo on `compact`.
After reviewing the results, Abhinav selected `writer_luna` for new local-demo
uploads on 9 October: Luna medium extraction, Sol medium diagnosis and Luna medium
writing. The switch is for the next evaluation; the identified reliability issues
remain open. The measurements below retain the original control and candidate labels.

## Main experiment: the same 13 files, four configurations

Extraction uses GPT-6 Luna at medium in every row. “Sol” means GPT-6.1 Sol; “Luna”
means GPT-6 Luna. Diagnosis uses medium reasoning throughout.

| Configuration | Diagnosis | Writing | Average wait for a published result | Recorded cost, all 13 attempts | Quality gate |
| --- | --- | --- | ---: | ---: | --- |
| Current control (`compact`) | Sol | Sol medium | 40.2 s | $0.350858 | 13/13 |
| Luna writer (`writer_luna`) | Sol | Luna medium | 37.2 s, 12 results | $0.158109 | 12/13; one extraction failure |
| Lower-effort Sol writer (`writer_low`) | Sol | Sol low | 35.1 s | $0.321608 | 13/13 |
| Luna throughout (`all_luna`) | Luna | Luna medium | 33.6 s | $0.035339 | 12/13; one confidence failure |

Wait time includes upload, queue, analysis, trace export and API readback. It does
not measure browser rendering. The failed Luna-writer run ended after 35.7 seconds
without a result; it is excluded from the published-result time, but included in
the cost and completion denominator. A shorter failed run is not a speed gain.

The lower-effort Sol writer reduced average wait by **12.6%** and recorded cost by
**8.3%** in this sample. Luna throughout was faster and much cheaper, but one opaque
error received high confidence while its explanation correctly said the cause was
unknown. That conflicts with the uncertainty requirement, so this candidate should
not be selected on speed or cost alone.

A targeted repeat subsequently found the same confidence problem with Sol diagnosis
in the lower-effort-writing configuration. Confidence is produced before writing:
this is not evidence that low-effort writing caused the issue, nor that it is unique
to Luna diagnosis. The main table remains the original 13-file observation rather
than being rewritten with selected repeat results.

## What the writing change actually achieved

Across the 12 files completed by both the control and Luna writer, mean writing
time fell from **9.11 to 6.97 seconds** (23.4%). Whole-workflow recorded cost fell
from **$0.314206 to $0.155242** (50.6%). Average upload-to-result time only fell from
38.23 to 37.16 seconds (2.8%) on those matched completed files. The large cost saving
is clearer than the overall speed benefit in this small sample.

Sol with low reasoning averaged **8.05 seconds** for writing versus **9.56 seconds**
for the control across all 13 files. Its end-to-end gain also benefited from having
no extraction retries. We cannot attribute the full 12.6% wait reduction to writing.

The shared extraction stage produced two recovered retries in the control, two
recovered retries and one double failure with the Luna writer, one recovered retry
with Luna throughout, and none with the lower-effort Sol writer. All retry time and
recorded cost remain in the measurements. The Luna-writer failure happened before
either diagnosis or writing, so it is not evidence that Luna cannot write that case.

## Quality and experiment controls

The 52 analyses used real model calls: ten synthetic mapping/master-data files with
one to five errors each, plus unknown, ambiguous and multiple-attempt cases. Each
file ran once per configuration, two cases at a time. Configuration order rotated
between file pairs to reduce time-of-run bias. The control was rerun in the same
session; results are not compared against a selectively chosen historical baseline.

The layout, prompts, output schema, extraction reasoning, evidence validation and
approval routes were held fixed. Frontend projection checks passed for all 51
published outputs, including readable case numbers, document and system metadata,
target company context, and cited coverage of every error line. Source-grounded
assistant review found no material factual or uncertainty regressions in the 50
outputs that passed the quality gate. The remaining published output is the
all-Luna confidence failure described above. This review is not an independent SAP
domain-expert assessment.

All **160 model-call traces** were independently found in Arize, including failed
extraction attempts. Total recorded model cost for the main experiment was
**$0.865914**. Costs use the application's saved price catalogue, not a provider
invoice. Small synthetic samples and one observation per configuration/file cannot
establish production accuracy or stable latency percentiles. Real logs, additional
categories and repeated runs remain necessary before a production decision.

## Targeted repeat, kept separate from the main comparison

The unknown, ambiguous and multiple-attempt files were rerun with both writing
options after the main experiment. This deliberately selected difficult subset is
not an unbiased replacement for the main 13-file comparison.

| Repeat configuration | Published | Quality passes | Average wait | Recorded cost |
| --- | ---: | ---: | ---: | ---: |
| Sol diagnosis, Luna medium writing | 3/3 | 3/3 | 30.64 s | $0.033695 |
| Sol diagnosis, Sol low writing | 3/3 | 2/3 | 40.73 s | $0.067890 |

Luna writing successfully handled the previously blocked multiple-attempt case,
preserving both attempts and their uncertainty. All three completed without retries.
The Sol-writing repeat needed one extraction retry on each of two files. Its unknown
case received high confidence from Sol diagnosis despite an undetermined cause.
No writing-stage failures or material narrative regressions were found in either
candidate's completed outputs. These repeats support investigating shared extraction
reliability and confidence semantics before attributing whole-workflow differences
to a writer.

All six repeat outputs passed frontend projection checks; all 20 repeat traces were
read back from Arize. Across both experiments there were **58 analyses, 180 model
calls and $0.967499 recorded cost**. There were 57 published results, of which 55
passed the full fixture-specific quality gate. The one unpublished extraction
failure and two published confidence failures remain visible in the evidence.

**Recommendation:** retain Sol diagnosis and test Luna medium writing further as
the cost-saving option. Lower-effort Sol writing remains a speed candidate, but
the repeat does not establish a stable latency lead. Clarify and enforce the
confidence requirement, and address extraction failures, before selecting a new
production default. Those follow-ups need no change to the user-approved layout.

## Reproduce and inspect

Run `scripts/benchmark-model-matrix.py` without `--execute` to inspect the plan;
use `--execute` for real calls. The runner retains stable case/run identifiers for
resume and uses a separate API. See [setup](connected-demo.md) for profiles.

Main outputs and trace receipts are retained under the ignored
`.local-runtime/latency-benchmark/model-matrix-20261009-<profile>-c2/` directories.
The per-file measurements and review decisions are preserved in
[machine-readable evidence](validation/model-comparison.json).

The full backend suite passed **852 tests**, including disposable database checks;
the focused profile/database/benchmark suite passed 31 tests. The frozen product
manifest verified 168 files. The migration adding the experimental model allowlist
was applied with no pending jobs; fingerprints confirmed existing records were
unchanged. No frontend or prompt changes were made for this experiment.

After the comparison, normal two-worker processing was restored. The API on 8011
and frontend on 3011 returned HTTP 200. The private environment subsequently switched
from `compact` to `writer_luna` at Abhinav's request, with an API and worker restart.
Experimental API processes have exited.
