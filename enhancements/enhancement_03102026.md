# Enhancements for 3 October 2026

One file per date. This file consolidates all enhancements from the 3 October session, including work completed after midnight on 4 October, as requested. Sections retain the implementation sequence; the final refinement records the latest presentation. Implemented changes and pending designs are recorded separately.

## Case chat attachments

**Status:** Implemented in the local frontend preview.

**User need:** Preserve the relationship between a case message and its supporting evidence, especially approvals received by email, so the record remains understandable during later investigation and audit.

**Agreed behaviour:**

- Every case message supports one or more attachments; ordinary messages may be sent without files.
- An approval received by email must have the approval email attached to the message recording that decision.
- Show files on their originating message in the chronological case chat. A case evidence view links back to that message.
- Record the message author and time, attachment identity and filename, uploader and upload time. Identify the external approver separately from the uploader.
- File upload alone does not establish approval. Email capture remains manual for the MVP; automation is future work.

**Implemented behaviour:**

- Replaced the timeline-and-comment-card interaction with a chronological case conversation that displays messages, decisions and attached files together.
- Added a message composer with optional attachments for ordinary updates.
- Added a dedicated approval-recording mode. It requires an external approver and at least one supporting file before the approval action becomes available.
- Added attachment chips beneath each relevant message and an evidence view that identifies the originating message and author.
- The local preview preserves attachment metadata with the browser-local case. Durable file bytes, download links, malware scanning and access enforcement require the production storage service.

**Affected documents:** `README.md` and `docs/FRONTEND_DESIGN.md`.

**Validation:** TypeScript check passed. In the local preview, approval recording shows an external-approver field and remains disabled until attachment evidence is selected.

## Local preview build reliability

**Status:** Implemented.

**User need:** Keep the local frontend preview and build checks dependable on this iCloud-synced Apple Silicon workspace.

**Implemented behaviour:** The local launcher now marks local builds explicitly. Next.js omits standalone packaging only in that mode because standalone tracing follows the local dependency link into the OS temporary directory, where macOS rejects the generated trace path. Deployment builds retain standalone output.

**Validation:** Local production build and TypeScript check passed after the change.

## Case Board ownership, status and closure model

**Status:** Implemented in the local frontend preview.

**User need:** Make the visible case board accurately reflect a governed case-management workflow, rather than a route diagram that silently passes cases from one person to another.

**Implemented behaviour:**

- Simplified the board to Case number, Title, Error type, Assigned to, Status, Value and Age. Removed the `Current step` column.
- Replaced legacy statuses with the only four operational statuses: Open, In progress, Blocked and Closed. `Awaiting approval` is removed as a status and quick view.
- Enforced a single named owner. A route action or approval does not change ownership. Only an explicit reassignment by the CFIN Exception Manager changes the assignee and creates an attributed chat event.
- Moved approval and progression into Case chat. A recorded approval requires an external approver and attached evidence, and advances only the route guidance; it leaves the named assignee unchanged.
- Added a separate closure record. Closing requires a detailed outcome and at least one supporting file, then creates an auditable case-chat event and sets the status to Closed.
- Updated dashboard priorities so they include only cases explicitly assigned to the active named person that are blocked or past due.

**Affected documents:** `README.md`, `docs/FRONTEND_DESIGN.md` and `frontend/src/components/workbench-app.tsx`.

**Validation:** TypeScript check passed. Local production build and interactive preview refresh are run after this implementation.

## Enhancement logging convention

**Status:** Implemented in project documentation.

Future implemented enhancements are logged in `enhancements/enhancement_DDMMYYYY.md`, with exactly one file per date. Append additional entries to the existing daily file. Entries include the change, reason, affected components, validation and limitations. The README remains the authoritative design record; this folder retains the enhancement history.


## Enhancement 2 — Case controls, date interval and lighter discussion

**Status:** Implemented in the local frontend preview. Requested late on 3 October; implementation and verification continued after midnight on 4 October. Retained in this daily file as the requested second enhancement for 3 October.

**User need:** Make case details compact, accurate and easy to investigate, with visible ownership and deadlines, useful date filtering and a light discussion interface.

**Implemented behaviour:**

- Added Case Creation Date and Due Date to board rows and the top case-controls header. The table uses the full width, and open-case age is calculated from the creation timestamp. Creation timestamps are recorded for new local cases; existing sample cases receive their seeded creation date, and unknown dates are not invented.
- Kept exactly three board controls: All cases, Assigned to me and Date interval. Search and status filtering remain. The calendar selects an inclusive creation-date range, combines with other filters, supports reversed/same-day selections and can be cleared.
- Moved title, ID, owner, status, priority, error type, dates and actions into the header; removed the owner/controls sidebar.
- Ordered the detail tabs Summary, Case chat, Original log. Removed the Evidence tab; message attachments remain on their messages and the complete source is only in Original log.
- Replaced the bubble-like conversation with a plain discussion and comment composer, retaining message-specific files and approval-email requirements.
- Removed Error assessment, unsupported medium-confidence labels, the separate Escalation warning and Open questions and blockers.
- Consolidated supported proposed cause wording into Case summary. Corrected the preview so unrelated cases do not inherit a master-data diagnosis or fabricated source references.
- Explicitly stated both pilot routes in Summary, including named participants, approval records, change evidence, reprocessing, posting confirmation and the exception handover to the CFIN Exception Manager.

**Affected components:** `frontend/src/components/workbench-app.tsx`, `frontend/src/components/workbench.css`, `README.md`, `docs/FRONTEND_DESIGN.md`.

**Validation:** TypeScript and local production build passed. Browser verification confirmed the full-width nine-column board; inclusive same-day creation-date filtering; combined date and explicit-owner filtering; top controls; both pilot route descriptions; the three-tab order; plain discussion composer with attachments; and complete original-log rendering. The refreshed preview was opened after the final build.

**Limitations:** This is the existing local preview with simulated persona permissions. Attachments retain metadata only; shared storage, downloadable file bytes, authenticated enforcement and live agent execution remain separate integration work.

## Final refinement — Remove redundant age and exception-path text

**Status:** Implemented in the local frontend preview.

**User need:** Keep case views concise now that Case Creation Date and Due Date provide the time context and the pilot route is explicitly stated.

**Changes:**

- Removed the Age column from Case Board and the elapsed-age wording from Dashboard priorities.
- Removed age from the preview case model, sample data, new-case intake and closure updates, and removed age calculation helpers.
- Dashboard priorities now sort by blocked status, priority and due date, then case ID.
- Removed the additional Exception path paragraph from the summary for both pilot categories and from the current rendered-case documentation.
- Updated README and FRONTEND_DESIGN to match the simpler presentation. Earlier sections describe the implementation sequence; this refinement supersedes their age and additional exception-path presentation.

**Validation:** TypeScript and local production build passed. Refreshed browser verification confirmed eight Case Board columns, no elapsed-age text in Dashboard priorities, and no additional Exception path paragraph in the pilot summary. A source scan found no age field/helpers or Exception path text anywhere in the frontend.


## Case Board CSV download

**Status:** Implemented in the local preview. Recorded in this consolidated 3 October session log as requested.

**User need:** Download the cases currently being reviewed for offline analysis and sharing.

**Changes:** Added **Download as CSV** beside the search and status filters. The export uses the currently filtered cases and the same eight board columns, including the assignee’s name and role and the displayed creation/due dates. All active filters and row order are respected. The control is disabled when there are no matching cases. CSV includes an Excel-compatible UTF-8 BOM, correct cell escaping and literal-text handling for formula-like values. The filename is `case-board-YYYY-MM-DD.csv`.

**Affected components:** Case Board component, CSV serializer, README and FRONTEND_DESIGN.

**Validation:** TypeScript and local production build passed. Downloaded a CSV from the refreshed browser with search restricted to case CFIN-2026-0147; parsed the downloaded file and confirmed exactly one case, all eight columns, the assignee name/role and the displayed dates. Verified the button is disabled for no matching cases. Serializer round-trip checks covered commas, quotes, multiline text, Unicode, UTF-8 BOM and formula-like values.
