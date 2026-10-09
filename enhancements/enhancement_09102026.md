# Enhancements for 9 October 2026

## Repository preparation and documentation organization

**Status:** Implemented.

**User need:** Publish the copied Desktop project to its GitHub repository with current documentation and essential software checks completed.

**Changes:** Moved active frontend and rebuild notes into `docs/`, leaving only README Markdown at the root. Updated README status and setup guidance to reflect the current Mantine browser-local workbench, its latest case/approval/closure/filter/export design, and pending backend integration. Repaired current and archived documentation links, retained existing project artifacts, and excluded local secrets, dependencies, caches and runtime symlinks.

**Reliability fix:** Makefile setup/check targets now invoke Railway tooling through the same Node 22 launcher as the frontend, preventing a shell-level Node 18 installation from breaking an otherwise valid check.

**Validation:** Full checks passed: 786 backend tests including local database execution, 6 example tests, Python lint, frontend typecheck/build and Railway validation. Five deterministic Promptfoo gates passed. Both deployment images built and served their HTTP smoke endpoints. Browser checks verified board and case rendering. Detailed evidence and remaining limitations are in [repository-validation.md](../docs/repository-validation.md).

**Limitations:** The current workbench remains a browser-local demo; cloud rollout and provider-backed semantic acceptance remain release work. npm reports 7 build-tool dependency advisories requiring a reviewed Tailwind major migration; production dependency audit reports none.

## README simplification

**User need:** Give a first-time reader a short, plain-language product overview.

**Changes:** Rewrote the README around the problem, experience, architecture, pilot scope, trust and success measures. Preserved the architecture diagram exactly. Removed dated status updates and moved detailed product rules and development instructions into `docs/`, with supporting links updated.

**Validation:** Checked Markdown links, the unchanged Mermaid diagram and the documentation diff. No application code changed.

## Problem and solution explanation

**User need:** Give readers more context about the problem and the solution delivered, while keeping the README simple.

**Changes:** Expanded the problem statement to explain investigation effort, scattered evidence and difficult handovers. Added a solution section covering the analysis backend, case coordination and decision record, with clear human responsibilities and the intended business outcome. Retained the demo limitations and architecture diagram.

**Validation:** Reviewed the wording against the documented implementation, checked the unchanged diagram and ran the documentation whitespace check. No application code changed.

## Browser connection repair

**User need:** Fix the empty Case Board and determine whether switching browsers helps.

**Cause and change:** Chrome and the Codex in-app browser reproduced the connection failure. The connection adapter invoked native `fetch` as an instance method, passing the adapter as its receiver. The default transport now delegates to `globalThis.fetch`, preserving the browser receiver. Injected test transports, request options, UI, prompts and business rules remain intact. The product-freeze manifest records only this authorised transport change.

**Validation:** A receiver-sensitive regression test fails against the old transport and passes against the repair. All 21 frontend tests, TypeScript checking and the production build pass. Both browsers display all six saved cases. Chrome's assigned-case filter shows Maya's two cases, and the mapping case opens with its cited summary, saved closure and original log.

**Limits:** This fixes case loading. It does not establish completion of the wider real-model browser journeys. No new model calls or business-record mutations were made for this check.

## Saved metadata, case references and removal of Value

**User need:** Apply the field-mapping repairs and remove the unnecessary Value field.

**Changes:** Project supported, current extracted identifiers into the board, detail header,
search and CSV while preserving leading zeroes, source/target scope and conflicts. Show the
existing cited document context. Add immutable `CFIN-YYYY-NNNNNN` database references,
backfilled without altering any other saved case fields; retain UUIDs for all relationships
and API actions. Remove Value/Amount from board/detail/export and the illustrative monetary
KPI. Export document number separately from case reference. Preserve original evidence.

**Validation:** 820 backend tests, 31 frontend tests, six example tests, lint, typecheck,
production build and Railway checks pass. The live database backfill preserved all prior
case fields for eight cases; the six visible saved cases pass metadata readback checks.
The new database CI target includes concurrent-numbering and immutability regressions.

**Limits:** No new model calls; complete workflow browser release gates remain open.

## Upload progress, recovery and measured analysis

**User need:** Separate unfinished analysis from a legitimate unclassified result, move
upload to the personalized Dashboard, allow leaving and returning, explain retries and
measure latency/cost with Arize traces.

**Changes:** Dashboard upload at lower right, animated actual-stage progress, persisted
recent uploads, background progress notice, completion navigation and manual failure retry.
Current-run server progress comes from the durable call ledger. Preserve the existing
60-second stage timeout with one retry. Enable local Arize export; provide five two-file
synthetic batches with at most five errors per file. Correct line-number extraction context
found by the browser run, with source-line verification and regression coverage.

**Evidence:** Ten real benchmark analyses succeeded, 30 calls cost $0.446880, mean analysis
51.91 seconds, all 30 trace IDs read back from Arize. A separate real browser upload verified
leave/return and completion navigation. 826 unique backend tests (including database
checks), 35 frontend tests, lint, TypeScript and production build pass.

**Decision:** Do not cancel at average workflow latency; successful runs exceeded it.
Keep stage deadlines with headroom and collect a larger sample before tuning. See
[baseline and reproducible evidence](../docs/analysis-latency-baseline.md).

## Faster analysis with measured quality

**User need:** Try the recommended latency improvements and compare real model results.

**Changes:** Compact extraction and summaries, deterministic evidence/context attachment,
versioned reasoning profiles, and two independent workers with database-enforced concurrency.
Expose cited open questions and fix projection of verified attempt-scoped metadata.

**Decision and evidence:** Select compact output with medium reasoning. On the same ten
files, mean upload-to-result fell from 82.86 to 37.87 seconds and model cost fell 39.09%.
All thirteen selected-profile examples passed automated and semantic review; all 39 trace IDs
were read back from Arize. Low reasoning remained experimental after one double extraction
failure. No evidence validation was weakened to obtain a speed gain.

**Validation:** Backend/database concurrency checks, frontend tests/typecheck/build, trace
readback, source-based semantic review and actual frontend projection checks passed.
See [complete results and limitations](../docs/latency-optimization-results.md).

## Compare models without changing the case layout

**User need:** Test writing-model combinations while retaining the established format.

**Changes:** Add opt-in Luna-writing, lower-effort Sol-writing and all-Luna profiles,
an exact database allowlist, and a resumable runner that rotates configuration order
on the same files. Prompts, frontend and output schema are unchanged for this work.

**Evidence and judgment:** The main comparison made 52 analyses across four profiles.
Lower-effort Sol writing passed all 13 initial cases with a 12.6% shorter average wait.
Luna writing reduced writing time by 23.4% and whole-workflow cost by 50.6% on the
12 matched completed cases, but shared extraction failed on the remaining case.
The all-Luna run and a targeted Sol-diagnosis repeat both exposed a confidence-label
inconsistency. Retain failures and repeats separately; do not declare a production
winner or change the active setting based only on speed.

**Validation:** 852 backend tests passed. Recorded traces were read back from Arize;
actual frontend projection and source-grounded output review were also performed.
See [model comparison and reproducible evidence](../docs/model-comparison-results.md).
