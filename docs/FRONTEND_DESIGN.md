# AIF Resolution Workbench — frontend design

## Purpose

The workbench helps CFIN support analysts and process owners progress a document failure from its supplied AIF log to a validated CFIN posting. It is an investigation and coordination product. The AI brief makes the case easier to understand; people own approvals, remediation, evidence and outcomes.

The design must always answer:

1. What failed, and what source evidence supports that statement?
2. Who owns the case and the next action?
3. Where is the case in its governed route?
4. What has happened, including decisions, handovers and evidence?
5. What must happen before the document can be confirmed as posted and validated?

## Technical direction

- **Application:** Next.js and React.
- **Interface system:** Mantine, with the existing Supabase and API foundations retained.
- **Authentication for a shared pilot:** invite-only Supabase accounts. The server remains authoritative for workspace membership, roles, state transitions and audit attribution.
- **Local design/demo mode:** explicit simulated personas backed by browser-local data. A demo persona is not an authenticated identity and every generated event is labelled as simulated.

The component library accelerates reliable interaction patterns; it does not replace product design. The implementation must keep facts, AI hypotheses and human findings visibly separate.

## Visual system

The workbench uses a full-width application layout, not a card wrapped around the entire page. A slate gradient belongs to the navigation band; the workspace below stays a quiet light canvas. Every primary page starts with the same dark slate title panel, with its page name, short explanation and contextual action or cue. White panels are reserved for distinct work areas such as metrics, tables, forms and case sections, with clear spacing between them.

| Token | Value | Use |
| --- | --- | --- |
| Workspace canvas | `#EDF1F3` | Full-width page background |
| Navigation gradient | `linear-gradient(105deg, #859398 0%, #283048 72%)` | Product header band only |
| Navigation base | `#283048` | Tab strip and shared page-title panels |
| Surface | `#FFFFFF` | Tables, forms, case content and dialogs |
| Soft surface | `#F3F6F7` | Table headers, filters and secondary regions |
| Main text | `#182536` | Headings and body copy |
| Supporting text | `#52616E` | Labels and metadata |
| Primary action | `#0E6371` | Primary buttons, active selection and links |
| AI annotation | `#6554A4` on `#F1EEFA` | Generated hypothesis and analysis markers |
| Confirmed | `#14634B` on `#E9F5EF` | Confirmed completion or successful outcome |
| Attention | `#835300` on `#FFF3DA` | Past-due work and pending action |
| Escalation | `#A52C3B` on `#FCECEF` | Blocked, rejected or escalated work |

All normal text on solid surfaces must meet WCAG AA contrast. Status colour is always paired with text and an icon or shape. Typography uses Inter Variable with a clear scale: 15–16 px body text, 19–21 px section titles and 30–36 px page titles. The product name is 20–25 px and remains prominent on narrow screens.

### About page

The page opens with: “AI structures the facts and proposes a route. People validate findings, approve governed changes and confirm CFIN posting. The original AIF log and decision history stay with every case.” Three substantial **Guiding principles** panels cover intact evidence, bounded automation and human-owned outcomes. A final success marker states that the target outcome is a document successfully posted and validated in CFIN.

The Dashboard uses the same dark title panel as the other primary pages. It is titled **Your work, in view**, greets the active persona, and introduces priorities and log upload. Three metrics sit immediately below. At desktop widths they share one row so the work area remains easy to reach.

At the bottom, **[Person]'s Priorities** shows only explicitly person-assigned cases that meet a priority condition. The local demo maps each persona to a named person; role membership alone does not qualify a case. A blocked or past-due case appears for its explicit assignee. Approval belongs in the evidence-backed case chat and does not transfer case ownership. Due status uses the case's `dueAt` timestamp. Ordinary open cases and extra role-matched cases are excluded. Priority items sort by blocked status, case priority and due date, with case ID as the final tie-breaker. Selecting one opens that case on the Case Board.

The average resolution-time metric keeps its week-over-week comparison callout and has a configurable ideal in days. The **Set ideal?** control sits beside the metric value and appears only for the CFIN Exception Manager; the clock icon stays fixed at the top-right. The preview compares its current illustrative value with the target: below target is green, above target is red, and equal is neutral. The target is saved in browser-local storage for the local demo. In a shared authenticated build, the backend must enforce this role permission; hiding the control in the UI is not sufficient authorization.

## Application structure

The header contains the product name and signed-in user or clearly labelled local demo persona; a separate top tab strip holds three primary pages. The header and tabs span the viewport, and page content sits directly on the workspace canvas rather than inside a single oversized shell tile.

| Page | Job |
| --- | --- |
| About | Explain the workflow, what AI does and what remains human-controlled. |
| Dashboard | Show metrics and personalised priorities; receive logs and track analysis. |
| Case Board | Search, filter, assign, investigate and progress cases. |

Each page has a route in the production version. The design preview preserves page state in the current browser session while routing is introduced with the API integration.

### Upload and analysis experience

The desktop lower work area pairs a broad priorities panel on the left with an upload panel
on the right. On narrower screens these stack. The existing Inter typography, navy `#283048`,
teal `#0E6371`, mist `#EDF1F3`, paper `#FFFFFF` and ink `#182536` keep this change part of the
workbench. Text is left aligned. The upload panel has a single teal edge and a document-shaped
icon; one rotating ring answers the upload action. There are no invented progress percentages.
The review pass moved the three KPI cards onto one desktop row to avoid unused space pushing
the upload out of view.

Choosing a file shows its name and size. **Upload and analyse** saves the original and remains
on the dashboard. Pending files show **Waiting to start**, followed by **Reading your log**,
**Investigating the errors**, and **Preparing your case**, derived from the current run's call
ledger. **Retrying analysis** reflects a real second invocation. The original is safe if analysis
fails; **Review original** and **Retry analysis** provide recovery. An available result with
invalid/missing current citations is an attention state, never a successful result.

**Ready for review** provides **Open case**, which opens that exact case on the board. The app
never automatically redirects on completion. A compact notice follows active work across tabs.
All active analyses refresh independently of the selected case; focus/visibility changes refresh
saved progress after returning. Browser storage keeps only recent-case bookmarks; database
state remains authoritative. The upload selection remains mounted while browsing other tabs.
Reduced-motion settings stop the rotating ring, and status changes have polite live announcements.

Operational states do not imply a business diagnosis: before publication, the board displays
**Analysis in progress** or **Analysis incomplete**, not **Cause not established** or **Unclassified**.

Two independent cases can be analysed at the same time. Each retains its own durable progress,
retry state and completion link; a third waits for capacity. Progress comes from actual saved
work and never implies a guaranteed completion time. The compact latency profiles change
how the backend prepares validated content, not the user's upload or review controls. Exact
original evidence, identifiers, governed routes and explicit uncertainty remain visible.

## Case Board

The default is a full-width table, because users need to compare documents, responsibility, time and work state. No duplicate case-owner preview sidebar reduces its width. Creation and due dates provide the time context; do not show a separate age field in any case view.

| Column | Purpose |
| --- | --- |
| Case number | Stable `CFIN-YYYY-NNNNNN` reference and source document number; UUID remains internal |
| Title | Factual case title |
| Error type | Published category or `Unclassified`; explicit analysis state before publication |
| Assigned to | Named person and role |
| Status | `Open`, `In progress`, `Blocked` or `Closed` |
| Case Creation Date | Recorded creation timestamp, displayed as a date in the board |
| Due Date | Case deadline, highlighted when overdue |

The **Assigned to** cells keep a fixed-size avatar beside a two-line name and role block, vertically centred in each row. Longer labels truncate within the column rather than wrapping the avatar above the name.

The toolbar has exactly three controls: **All cases**, **Assigned to me** and **Date interval**, plus the retained search and status boxes. Date interval opens a two-month calendar for choosing the start and end date. It applies inclusively to Case Creation Date, combines with owner/search/status filters, highlights the selection and can be cleared. A reversed selection is normalised and a same-day interval is supported. Unknown creation dates are excluded when a range is active.

**Download as CSV** sits beside search and status in the board toolbar. It exports only the rows matching the active owner, creation-date interval, search and status filters, in the board’s current order and with eight columns: the seven visible board columns plus Document, exported separately from Case number. Value is excluded. The assignee cell includes the person and role. The download is disabled when no rows match. CSV uses UTF-8 with a BOM for Excel, quotes commas/quotes/newlines correctly, and treats formula-like cell values as literal text. The file is named `case-board-YYYY-MM-DD.csv`.

## Case workspace

The investigation workspace has three tabs, in this order:

| Tab | Content |
| --- | --- |
| Summary | The agreed Summary Agent format, rendered as a readable case brief. |
| Case chat | A light discussion area: plain chronological comments, approvals, handovers and their message-specific files, with the composer above the history. |
| Original log | The complete, unchanged supplied original, with cited lines highlighted. Source files are not duplicated into a separate evidence tab. |

The persistent header contains the factual title, case ID, one named owner, status, priority, error type, Case Creation Date and Due Date. Reassignment, status change and closure actions stay at the top. The summary uses the full content width; no separate owner or case-controls sidebar is shown. Titles describe the reported document failure rather than internal workflow phrases such as “Exception requires classification”.

### Summary format

1. Case summary, with cited facts and a separately identified proposed cause requiring human validation
2. Document and processing context, showing only supplied facts
3. Evidence from the original log, quoting actual source lines
4. Open questions, only when the current verified brief contains them, with their source citations
5. Defined resolution and escalation path for the selected error type (Investigation path for manual categories)
6. Similar earlier cases, only when a reviewed match is available
7. Closure record, when recorded

Remove the separate Error assessment and Escalation panels. The authorised latency experiment
retains a concise **Open questions** section when verified questions are present, so shorter
model output does not hide missing evidence or conflicting facts. Each question shows its
source filename and line range; do not add an empty placeholder or an invented blocker.
A fixed “medium” confidence label is unsupported and must not be displayed. Any future
confidence presentation requires a documented basis and evaluation evidence. Keep the cause
hypothesis tentative and uncertainty explicit in the summary.

The two pilot routes must explicitly name responsibilities, approval evidence, the change, reprocessing and successful CFIN posting confirmation. Master data: Maya requests Daniel’s approval, approval is logged with its email, Maya creates data and records evidence/go-ahead, Liam reprocesses and validates posting. Mapping: Maya confirms mapping with Daniel, maintains it and records evidence, Daniel reviews/approves with email evidence, Liam reprocesses and validates posting. Do not add an extra exception-path paragraph or a separate escalation warning panel.

### Progression, ownership and closure

The case chat is the chronological operational record: it explains both where the case is and how it got there. A configured route supplies guidance for the next action, but it does not silently alter the case assignee.

**Master data**: request RTR Process Owner approval → RTR approval → create data and attach evidence → reprocess → validate posting.

**Mapping**: confirm mapping with RTR Process Owner → maintain mapping and attach evidence → RTR approval → reprocess → validate posting.

Each case has exactly one named assignee at a time. The role that owns a configured route action or approval is guidance for the work, not an automatic handover. Only an explicit reassignment by the CFIN Exception Manager changes the named owner, and the reason is recorded in the case chat. Approval is a decision recorded in the chat with its evidence; it is not a case status or a dashboard queue.

The other eight maintained categories and `unclassified` show manual investigation and CFIN Exception Manager coordination instead of an invented remediation route.

## Human actions and audit trail

The interface supports status updates, assignment, reassignment, AI-brief review, approval requests and decisions, remediation evidence, reprocessing outcomes, closure and reopening. The operational statuses are only **Open**, **In progress**, **Blocked** and **Closed**. “Awaiting approval” is an auditable chat event, never a status.

Every event records actor, actor role, time, event type, reason, previous/new values, case/work-cycle context and linked evidence. Comments remain distinct from structured decisions. Any case category can be closed by its named owner or the CFIN Exception Manager after successful document reprocessing and system data validation. The closure record states the resolution, action and target document reference, and includes a PNG or JPEG proof screenshot. In the disconnected SAP demo, a generated screenshot is explicitly labelled synthetic; the saved record never claims that the application verified a real SAP posting. Earlier route steps are guidance and are not fabricated by closure.

### Case chat attachments

Implemented in the local preview on 3 October 2026. Durable file storage, download and access control remain backend work.

The case conversation is a light discussion area based on the user’s work-item reference: a plain comment composer and chronological entries, with author and time. Avoid bubble cards and decorative timeline framing. Every message composer supports one or more file attachments, with selected files visible before sending. Ordinary messages can be sent without files. After sending, each attachment remains associated with its specific message and appears with that message; it is not an unrelated case-level upload.

When approval is received by email, the person recording it must attach the approval email to the message recording the decision. For example, Maya posts that Daniel approved the specified master-data change and attaches his approval email to that message. Maya is recorded as the message author and uploader; Daniel is recorded separately as the external approver. Uploading a file alone does not record an approval or establish its validity.

Preserve the message ID, case ID, author, timestamp and attachment links. Attachment records retain their identity, original filename, uploader and upload timestamp. Attachments are shown on their originating message; the original source remains in the Original log tab. The local preview retains attachment metadata with browser-local case data; production must persist the bytes and enforce access at both case and file level. Manual upload is the MVP flow; automatic email retrieval and approval capture are future work.

The workbench records human-performed SAP work. Controls read “Record reprocessing result”; they never claim to execute SAP reprocessing.

## Personas and permissions

| Role | Permitted work |
| --- | --- |
| MDG Process Owner | Investigate, correct the brief, request RTR approval, record master-data or mapping changes and attach evidence. |
| RTR Process Owner | Confirm requirements and approve or reject requests/mapping changes assigned to them. |
| Data Operations | Record eligible reprocessing attempts and CFIN posting/validation outcomes. |
| CFIN Exception Manager | Coordinate manual investigation, escalation, assignment/reassignment, priority, due date and reopening; set the ideal resolution-time benchmark. |

Role, case assignment and route prerequisites determine availability. Controls can be hidden or disabled for clarity, but the server must enforce permissions and valid transitions for every saved action. Reassigning a case never silently changes the route owner or approval responsibility.

## Acceptance journeys

1. Successful master-data resolution.
2. Successful mapping resolution.
3. RTR approval rejected, then case escalated.
4. Unclassified case assigned for manual investigation.
5. Case reassigned, blocked and reopened with prior history preserved.

The test set additionally covers an unauthorised attempt, skipped prerequisite, incomplete resolution evidence and conflicting edits. All ten categories plus `unclassified` are checked for correct routing.

## Connected metadata and references

The board, search, CSV and case details use a shared projection of the current published
extraction, verified against the saved original. Preserve leading zeroes and source/target
scope. Conflicting supplied identifiers remain visibly conflicting. Unavailable values
say “Not supplied”; do not manufacture values from a stale analysis or unrelated message.
The details screen also renders the saved document-context statements with their citations.

Case references are assigned by the database and remain stable after reload or case updates.
The creation year uses UTC and the numeric suffix comes from a global sequence; gaps are
allowed. Existing UUIDs continue to identify actions, evidence and related records.

At the user's request, the dedicated Value/Amount field and sample document-value KPI are
removed. Monetary text remains intact in original logs and cited source context.
