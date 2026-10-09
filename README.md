# AIF Resolution Workbench

Turn a supplied SAP AIF log into an exception case that preserves what the log reports, identifies a controlled error category and supported cause hypothesis, proposes the approved remediation route, and keeps the original available for human validation.

**Product goal:** help a CFIN support analyst understand and progress an exception without routinely reconstructing the story from the raw log. The complete original stays embedded in every case for review and validation. Case data and logs must also be available through an authenticated JSON API so other systems, including a future SAP Joule tool, can consume the same evidence. The MVP does not read or write live SAP data. Human reviewers confirm a proposed cause, approve governed changes, and record their work through the existing case controls.

**Repository status — 9 October 2026.** The Error Analysis backend is implemented in source: versioned intake and worker flow, all-category route registry, governed case publication, investigator case rendering, route milestones and deterministic regression coverage. The current `/` page is the Mantine workbench demo, with browser-local cases, simulated personas, message attachment metadata, explicit ownership, approval and closure records, inclusive date filtering and CSV export. It is not yet connected to the authenticated backend or live agents. The additive migration is present; applying it to a cloud database and activating the workflow remain release steps. Paid model execution and workflow cutover default to disabled. Legacy and factual cases retain their earlier workflow. Cloud migration, provider-backed acceptance runs, human semantic review and deployment remain release evidence to obtain; local software checks do not establish the quality of model-generated briefs.

## Who this helps and why AI belongs here

| Product question | Our answer |
| --- | --- |
| **Who is the user?** | CFIN support analysts and process owners reviewing document-processing exceptions. |
| **What is the friction?** | Relevant details are spread across messages, identifiers, payload fields and processing context. People spend time finding and connecting them before they can understand the case. |
| **Why use AI?** | Uploaded logs may vary in wording, layout, completeness and customer-specific content. Agents interpret that variability and prepare an evidence-based brief. Code handles intake, storage, case creation and assignment. |
| **Where is the product's differentiation?** | Faithful, comprehensive extraction followed by evidence-supported error analysis and governed remediation routes. A fluent summary has little value if essential evidence was missed, misread or turned into an unsupported diagnosis. |
| **What does success look like?** | Readers understand the reported exception from the case, with fewer manual log inspections and corrections. Accuracy, reading effort, latency and cost are measured rather than assumed. |

## Workbench interface

The app uses a Mantine component system over Next.js and React for the workbench shell, tables, discussion, dialogs and forms. The detailed frontend design, page content and interaction rules are in [FRONTEND_DESIGN.md](docs/FRONTEND_DESIGN.md). It uses the agreed slate gradient in the product header, a light full-width work surface, consistent dark page-title tiles, and Inter Variable typography. The header shows “AIF Resolution Workbench” without a logo or extra branding labels. Four tabs sit across the top; each opens a separate content view.

| Tab | Content |
| --- | --- |
| **About** | Sharp product purpose, three guiding principles and the CFIN success outcome. |
| **Dashboard** | The **Key Performance Indicators** page names average resolution time, case mix by error type, value of blocked documents and unclassified cases. Its bottom priority list includes only cases explicitly assigned to the active named person that are blocked or past due. An approval is recorded in the case chat with evidence and does not change the named case owner. The resolution-time metric retains its week-over-week callout and compares the current value with an ideal-time benchmark. |
| **Data** | Flat-file AIF log upload and file details. |
| **Case Board** | Case number, title, error type, named owner, status, value, Case Creation Date and Due Date. Three controls—All cases, Assigned to me, Date interval—sit beside search and status filtering. Date interval opens a calendar and filters creation dates inclusively. **Download as CSV** exports the currently filtered rows using the same eight board columns. Case details have Summary, Case chat and Original log tabs, in that order. |

The current unauthenticated frontend preview contains sample cases and explicitly labelled illustrative metrics. Only the CFIN Exception Manager persona can set the ideal resolution-time benchmark; below-target performance is green and above-target performance is red. The preview stores this preference in browser-local storage and gates the control by its simulated persona. Production authentication and server-side permission enforcement remain required. Upload creates a local case; live agent execution and durable storage are not connected to this preview yet.

### Run and test the frontend locally

From the project folder, run:

```bash
bash scripts/frontend-local.sh install
bash scripts/frontend-local.sh dev
```

Open http://127.0.0.1:3000. Keep the terminal running; Ctrl+C stops the preview. The launcher uses Node 22.23.3, pinned in `frontend/.nvmrc`. On Apple Silicon Macs it keeps the checksum-verified Node runtime, locked dependencies and Next.js output in a project-specific OS temporary directory, linked from `frontend/node_modules` and `frontend/.next`. This prevents iCloud from offloading runtime files in the Documents folder and stalling startup. It uses Webpack for these externally linked dependencies. Missing temporary files are restored automatically; the first run or a changed dependency lock requires internet access. `CFIN_FRONTEND_LOCAL_DIR` can select another local, unsynced directory. Other machines can use their own Node 22 installation. Run `bash scripts/frontend-local.sh typecheck` and `bash scripts/frontend-local.sh build` for software checks.

## Repository layout and verification

The repository is [SAP-CFIN-Error-Resolution-Workbench](https://github.com/abanerjee23/SAP-CFIN-Error-Resolution-Workbench). `README.md` is the only root-level Markdown document. Current design and rebuild notes live in `docs/`; dated change records in `enhancements/`; earlier documentation in `archive/`. Backend code and regression tests are in `backend/`, the workbench in `frontend/`, database migrations and probes in `supabase/`, synthetic examples in `fixtures/`, and evaluation providers and expectations in `evals/`. Deployment recipes are in `deploy/` and `.railway/`; presentations and screenshots are retained with the project.

Use Python 3.11+ with `uv` and Node 22. Set up locked dependencies and run the standard checks:

```bash
make setup
make check
```

`make check` runs Python lint, backend regression tests, example-client tests, frontend typechecking, an optimized frontend build and offline Railway configuration validation. GitHub Actions runs the corresponding checks plus executable database verification. To exercise migrations and transaction guards locally, use a disposable pgvector/PostgreSQL container:

```bash
docker run --detach --rm --name cfin-verification \
  -e POSTGRES_PASSWORD=cfin-local-only pgvector/pgvector:0.8.6-pg17
cd backend
CFIN_POSTGRES_CONTAINER=cfin-verification LOG_ONLY_ENABLED=false \
  PAID_MODELS_ENABLED=false uv run pytest -q tests/test_log_only_migration.py
cd ..
docker stop cfin-verification
```

The zero-cost Error Analysis policy suite runs with `make eval-error-analysis` when Promptfoo is installed. Local `.env` files, dependencies, caches and evaluation outputs are excluded from Git. Copy the checked-in `.env.example` files when configuring a new environment. A copied Python virtual environment must be recreated with `uv sync --locked --group dev`, because its executable paths can refer to the previous folder. See the [repository validation record](docs/repository-validation.md) for checks run before the initial push and their limits.

## Revised architecture

This README is the authoritative product, technical-architecture and policy record for the Error Analysis pilot. The [rebuild plan](docs/RE-BUILD.md) translates it into implementation phases. Archived material may describe earlier factual-only designs or implementation checkpoints and does not override this document.

**Enhancement logging.** Going forward, record implemented enhancements in `enhancements/enhancement_DDMMYYYY.md`, using the implementation date in Europe/London (for example, `enhancement_03102026.md`). Keep exactly one file per date and append separate entries for changes made on that date. At the user’s request, all work from the 3 October session, including its overnight refinements, is consolidated in `enhancement_03102026.md`. Each entry records what changed, why, affected components, validation and any remaining limitations. Agreed designs may be recorded in the same daily file but must be clearly marked as pending implementation. Update this README and the frontend design document when the enhancement changes their design decisions; the enhancement log records the change history and does not replace the authoritative design.

**Colour key:** blue `#DBEAFE` = code; purple `#EDE9FE` = agents; teal `#CCFBF1` = reviewed history; amber `#FEF3C7` = people; grey `#F1F5F9` = future external consumer. Each block includes its responsibility; colours indicate ownership, not risk or confidence.

```mermaid
flowchart TD
    I["1. INGESTION · CODE<br/>Receive the supplied log, preserve the original<br/>and queue analysis"]
    A1["2. EXTRACTION · AGENT 1<br/>GPT-6 Luna<br/>Capture all supplied entries, fields and source references"]
    A2["3. ERROR ANALYSIS · AGENT 2<br/>GPT-6.1 Sol<br/>Classify the extracted error and form a supported cause hypothesis"]
    R["CONTROLLED ROUTE LOOKUP · CODE TOOL<br/>Return the selected category's owner,<br/>remediation path and escalation rule"]
    A3["4. SUMMARY · AGENT 3<br/>GPT-6.1 Sol<br/>Write the case brief, cited analysis and Related cases section"]
    C["5. CASE CREATION AND ROUTING · CODE<br/>Compile the case, embed the original log<br/>and assign ownership"]
    H["6. HUMAN REVIEW AND FEEDBACK<br/>Review the case and record corrections,<br/>findings and outcomes"]
    K["7. REVIEWED CASE HISTORY<br/>Retain approved, versioned learnings<br/>and retrieve relevant past case evidence"]
    API["8. CASE JSON API · CODE<br/>Serve authorised case facts, state and original logs<br/>through a versioned read contract"]
    J["9. SAP JOULE · FUTURE CONNECTION<br/>Call the API through a configured tool<br/>under the customer's access controls"]

    I -->|"Saved source and readable content"| A1
    A1 -->|"Structured extraction and limitations"| A2
    A2 -->|"Category and extracted evidence references"| R
    R -->|"Governed route and escalation"| A2
    A2 -->|"Structured analysis and governed route"| A3
    I -.->|"Original log for citations"| A3
    A3 -->|"Structured user-facing content"| C
    I -.->|"Unchanged original log"| C
    C --> H
    H -->|"Existing review and approval process"| K
    K -.->|"Past cases, logs and learnings for reference"| A3
    C -->|"Saved case and evidence"| API
    J -.->|"Authenticated read request"| API
    API -.->|"Permitted JSON response"| J

    classDef code fill:#DBEAFE,stroke:#1D4ED8,color:#172554
    classDef agent fill:#EDE9FE,stroke:#7C3AED,color:#2E1065
    classDef history fill:#CCFBF1,stroke:#0F766E,color:#134E4A
    classDef human fill:#FEF3C7,stroke:#B45309,color:#451A03
    classDef external fill:#F1F5F9,stroke:#64748B,color:#0F172A
    class I,C,API,R code
    class A1,A2,A3 agent
    class K history
    class H human
    class J external
```

| Block / colour | Receives | What happens | Output and user value |
| --- | --- | --- | --- |
| **1. Ingestion — code** · Blue `#DBEAFE` | The uploaded log and any included views or sections. | Save the original unchanged, record its identity/version and receipt details, identify duplicate deliveries, and queue processing. Any readable working representation stays linked to the original. | A traceable source ready for extraction. Ingestion receives and preserves evidence; it does not interpret the error. |
| **2. Extraction — Agent 1** · Purple `#EDE9FE` | The supplied content and its source references. | Extract all supplied entries and fields into the agreed schema. Retain exact wording, identifiers, unfamiliar content and ambiguity. Flag unreadable or incomplete extraction. | A comprehensive structured representation for Agent 2. Relevant information should not disappear because the layout or wording is unfamiliar. |
| **3. Error analysis — Agent 2** · Purple `#EDE9FE` | Agent 1's structured extraction only. It does not receive the raw original or historical cases. | Apply one of the ten maintained category tags when the extraction supports it; identify a cause hypothesis, retain supporting extracted references, and state confidence and gaps. It returns `unclassified` only when no category is supported. | A Pydantic-validated analysis package: category, hypothesis, evidence references, uncertainty, owner route, remediation route and escalation state. A hypothesis is never treated as a confirmed root cause. |
| **Controlled route lookup — code tool** · Blue `#DBEAFE` | The category selected by Agent 2 and relevant extracted context. | Return the selected category's maintained policy: a full approval/remediation route for a pilot-active category, or the manual-investigation route for a known category outside the pilot. The tool does not expose a general SAP action or let the model invent an owner or procedure. | A governed route that Agent 3 can explain and the case workflow can enforce. |
| **4. Summary — Agent 3** · Purple `#EDE9FE` | Agent 2's structured analysis, governed route, original-log references and authorised historical material retrieved from the existing case library. | Write concise, friendly case content. Keep log facts, the agent's cause hypothesis, the proposed route, and human decisions visibly distinct. Read relevant prior case content/logs and cite similarities and important differences in a separate section. | A readable case brief, explicit uncertainties, traceable historical references and an actionable route that still requires human approval. |
| **5. Case creation and routing — code** · Blue `#DBEAFE` | The summary, analysis package, governed route, limitations and preserved original. | Compile and save the case, embed the complete original, build valid reference links, assign the configured role, and record the approval/escalation state. | One case containing evidence, analysis, ownership and next action. Known manual-route categories and unclassified cases remain visibly assigned to human review. |
| **6. Human review and feedback** · Amber `#FEF3C7` | The case and embedded evidence. | Review or correct the brief where needed; record investigation findings and outcomes through existing case controls. | Traceable feedback and better evaluation examples. Human review remains available without making routine raw-log reading the intended workflow. |
| **7. Reviewed case history** · Teal `#CCFBF1` | Case findings and feedback approved through the existing knowledge process. | Retain eligible versions and retrieve relevant previous cases, logs and learnings. Apply existing access, review and withdrawal controls. | Historical context feeds **Agent 3 only**. Learning happens through retrieval of reviewed material; it does not require automatic model retraining. |
| **8. Case JSON API — code** · Blue `#DBEAFE` | An authenticated request for saved case data or evidence. | Check the caller's permitted workspace/cases, then return versioned structured content and authorised original-log access. | Reusable case intelligence for external tools. Reads do not rerun agents or change case state. This is implemented as a versioned read-only contract; release checks remain explicit. |
| **9. SAP Joule — future connection** · Grey `#F1F5F9` | A user request and an explicitly configured tool. | Call the case API and use the permitted response within the customer's SAP workflow. | A future consumption channel. Customer-specific connection and any actions are separate from the factual analysis pipeline. |

The normal path is extraction, error analysis, governed-route lookup and summary. The Error Analysis Agent may apply any of the ten maintained category tags, or return `unclassified` when none is supported. Only two categories have pilot-active remediation routes; known non-pilot categories use the manual route. The agent cannot create SAP data, alter mapping or authorise reprocessing. Ordinary code checks still protect the handoffs, access and case records.

## Error taxonomy, ownership and escalation

The product maintains all ten agreed error families in the route registry from the first build. They are the common vocabulary for reporting, filtering and evaluation, not a claim that every family has automated remediation. The pilot activates a detailed remediation route only for the first two categories. A known category outside the pilot keeps its tag and takes the manual route. `unclassified` is reserved for evidence that does not support any of the ten categories.

| # | Category ID | Error family | Pilot route state | Initial route owner | Escalation |
| --- | --- | --- | --- | --- | --- |
| 1 | `master_data` | Master-data failure | Pilot active | MDG Process Owner | CFIN Exception Manager assigns a human investigation owner when the defined route fails. |
| 2 | `mapping` | Mapping failure | Pilot active | MDG Process Owner | CFIN Exception Manager assigns a human investigation owner when the defined route fails. |
| 3 | `integration_mapping` | Integration or organisational mapping discrepancy | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 4 | `master_data_restriction` | Master-data validity, restriction or block | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 5 | `posting_period` | Posting-period failure | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 6 | `tax` | Tax failure | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 7 | `currency` | Currency or exchange-rate failure | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 8 | `document_splitting` | Document-splitting failure | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 9 | `account_assignment` | Account-assignment failure | Manual route | CFIN Exception Manager | Manual investigation and assignment. |
| 10 | `technical_interface` | Technical or interface failure | Manual route | CFIN Exception Manager | Manual investigation and assignment. |

`CFIN Exception Manager` is a proposed coordination role for the pilot. It owns escalation and manual assignment when the correct specialist, category or approval is unavailable; it does not approve a business change in place of the relevant Process Owner.

### Active pilot route: master data

**Owner:** MDG Process Owner.

1. Agent 2 classifies the extracted evidence as `master_data` and returns a supported cause hypothesis.
2. The MDG Process Owner asks the relevant Process Owner for approval by tagging that person in the case-log conversation.
3. The relevant Process Owner approves or rejects in the same case-log conversation. The approval is retained in the case history.
4. After recorded approval, the MDG Process Owner creates the required data, uploads implementation evidence to the case history, and records that the document can be reprocessed.
5. The Data Operations team reprocesses the document and records whether posting to CFIN succeeded, with the returned reference or failure evidence.

**Definite escalation:** absent/rejected Process Owner approval, insufficient change evidence, or a failed reprocessing result leaves the case open and escalates to the CFIN Exception Manager. The manager assigns the next human investigation owner; no agent or tool bypasses approval or retries a business change automatically.

### Active pilot route: mapping

**Owner:** MDG Process Owner.

1. Agent 2 classifies the extracted evidence as `mapping` and returns a supported cause hypothesis.
2. The MDG Process Owner confirms the correct mapping with the relevant Process Owner in the case-log conversation.
3. The MDG Process Owner maintains the mapping and records the changed scope and supporting evidence in the case history.
4. The relevant Process Owner reviews and approves that mapping change in the case-log conversation.
5. The Data Operations team reprocesses the document and records the posting result.

**Definite escalation:** if the correct mapping cannot be confirmed, the Process Owner does not approve, or reprocessing still fails, the case stays open and escalates to the CFIN Exception Manager for human investigation and reassignment. No model chooses a mapping value or declares the result resolved.

### Pilot evaluation rule

All ten tags are maintained in the registry. For a reviewed pilot evaluation example whose expected tag is `master_data` or `mapping`, an Agent 2 result of `unclassified` is a **classification failure**. This keeps `unclassified` meaningful rather than allowing the model to avoid a pilot decision. In a live case with genuinely insufficient evidence, `unclassified` remains an honest result and routes to the CFIN Exception Manager without starting a remediation route.

The README is the product-policy record for this pilot. The runtime implementation should mirror all ten categories in a versioned database registry, with two pilot-active routes and eight manual routes. Agent 2 receives the maintained taxonomy through its system instructions and calls a route-lookup tool after classification. The prompt guides classification; the registry controls ownership, required approvals and remediation steps.

## Case data as a JSON API

**The case is both a human-readable page and a reusable data product.** An authorised system must be able to retrieve its facts, state and original evidence as JSON without scraping the UI or asking an agent to rewrite the case. The API serves saved records; the three-agent architecture and model baseline stay unchanged.

| Available information | Business value and interpretation |
| --- | --- |
| **Case identity and operational state** | Case/workspace IDs, supplied document context, owner, priority, lifecycle and human review state. A case's operational status is distinct from the processing status reported in its uploaded log. |
| **Factual brief and evidence** | Title, summary bullets, selected evidence, full extraction and source references. Consumers can inspect the underlying evidence rather than depend on prose alone. |
| **Original logs and supplied views** | A manifest of every accepted original, with exact text available through authenticated JSON source reads for supported text inputs and unchanged-file download access. Large results use explicit pagination or source retrieval; content is never silently shortened. |
| **Uncertainty and freshness** | Missing details, contradictions, analysis status, case/source/run versions and timestamps. A caller can distinguish an older brief from the latest case activity and an unavailable result from an empty one. |
| **Related cases and human records** | Separately attributed historical references, review decisions, meaningful comments and recorded outcomes, subject to access. Human findings and past outcomes remain separate from current-log facts. |

Deliver a documented, versioned JSON contract with an **OpenAPI specification**, predictable errors and bounded paginated reads. Preserve source versions across related requests so a consumer does not accidentally combine evidence from different analyses. Access to one case does not grant access to every case it cites.

### How SAP Joule could use it

For example, a user asks Joule to explain an exception. A configured tool retrieves the case brief and its evidence, and Joule presents that context inside the customer's SAP experience. SAP documents both [Joule skills used as tools with configured destinations](https://developers.sap.com/tutorials/joulestudio-agent-create?embed=full) and [external MCP server connections](https://help.sap.com/docs/Joule_Studio/45f9d2b8914b4f0ba731570ff9a85313/3d9dfad0bc39468292d508f0808a12fe.html). Our JSON API is the reusable foundation; the exact skill/action or MCP adapter depends on the customer's Joule edition, entitlements and connection setup. JSON availability alone does not establish a working Joule integration.

| Capability | Scope |
| --- | --- |
| **Read cases and logs through JSON** | Required for the rebuild, including an authorised machine caller and documented contract. |
| **Connect a Joule tool** | Later integration against a customer's supported SAP setup; no change to the three analysis agents. |
| **Update this app's case state** | Later, separately permissioned commands for comments or allowed transitions. Require a meaningful record, actor attribution, duplicate protection and rejection of stale updates. Existing review, proof and resolution requirements still apply. |
| **Change SAP data or trigger SAP processing** | Separate future automation owned and authorised within the customer's SAP environment. Reading our API grants no SAP write authority. Any result returned to the case is new attributed evidence; it does not replace the original log. |

Running Joule in a customer's SAP environment can keep SAP actions under that customer's controls, but it does **not** eliminate security risk at the API boundary. SAP's [external-tool guidance](https://help.sap.com/docs/Joule_Studio/45f9d2b8914b4f0ba731570ff9a85313/3d9dfad0bc39468292d508f0808a12fe.html) calls for authenticated, secure connections and restricted access. Our contract therefore requires HTTPS, narrowly scoped read credentials, workspace/case/evidence authorisation, revocation and access audit. Source text remains untrusted data; instructions inside a log cannot authorise tool actions. A machine identity does not automatically inherit the requesting person's SAP or app permissions.

**Implementation status:** the versioned external JSON contract and scoped, revocable machine reads are implemented alongside portal reads. Saved snapshots and source versions bind paginated retrieval; GET requests neither invoke models nor change business state. Actual deployment/access verification is recorded in the archived [build ledger](archive/BUILD.md). Customer-specific Joule configuration remains future integration work; JSON availability does not claim a working Joule connection.

## Model baseline

| Agent | Starting model | Responsibility |
| --- | --- | --- |
| **Agent 1 — Extraction** | **GPT-6 Luna** (`gpt-6-luna`) | Faithfully capture the supplied log into a structured representation. |
| **Agent 2 — Error Analysis** | **GPT-6.1 Sol** (`gpt-6.1-sol`) | Analyse the structured extraction, apply one maintained category tag or `unclassified`, identify a supported cause hypothesis, and retrieve its governed route. |
| **Agent 3 — Summary** | **GPT-6.1 Sol** (`gpt-6.1-sol`) | Produce the case brief with separately labelled log facts, analysis, proposed route and cited historical references. |

These are the agreed starting models, not a claim of proven superiority. Compare additional models later using the same representative inputs and quality criteria, measuring accuracy, omissions, consistency, latency and cost. The architecture stays the same during those comparisons.

## Understanding the AIF log

### What “the log” means in this product

SAP Application Interface Framework (AIF) presents processing information through several views. Its Monitoring and Error Handling screen includes **Data Messages, Log Messages, Data Structure and Data Content**. Our earlier walkthrough also showed **Error details** as a convenient view of message metadata and explanatory text; it is not a promise of a universal fifth tab. See SAP's [error-handling overview](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/19d48293097f4a2589433856b034dfa5/0e8f002ea0894c51bd957168699669c5.html?locale=en-US&state=PRODUCTION&version=2023.latest).

For this MVP, **the log is the complete evidence package actually supplied to the app**, including any exported views and details. We have no SAP connection to retrieve omitted content. The original is the golden record for what was supplied, rather than independent confirmation of the system's current state.

AIF is not simply a paragraph of English: it can expose identifiers, statuses, message records and payload fields alongside natural-language text. That does **not** establish a fixed structure for an uploaded export. SAP supports customer-specific labels, hidden fields/structures and replacement message text. Our working assumption remains that the input is not reliably uniform; real samples will determine how the schema evolves. See [SAP's customisation description](https://help.sap.com/docs/SAP_APPLICATION_INTERFACE_FRAMEWORK/1cefaed5b7a3471cb08564e54d5ba866/626bf6fa28a14c1b8873231acebc5fe7.html).

One distinction matters: a **data message** is a processing record; a **log message** is an individual entry emitted while processing it. Several error entries do not automatically mean several affected accounting documents.

### What each view gives us

The table describes information to preserve **when it is present**. It is a reading guide, not a mandatory export specification.

| View / part | What it contains or helps locate | What our agents can take from it | What it does not establish |
| --- | --- | --- | --- |
| **[Data Messages](https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/4ff5e0047b0a4351bd963640c680caec.html?version=latest) — which processing record?** | A selected data message and its processing status, with the key fields available for that interface. Supplied identity/context may include interface, namespace/version, message identifier, timestamps and document references. | Identify the record under discussion and retain its scope. Keep source and target identities separate; retain attempt context only when supplied. | That every identity field is available, that one row equals one unique accounting document, or that the displayed status is still current. |
| **[Log Messages](https://help.sap.com/docs/SAP_APPLICATION_INTERFACE_FRAMEWORK/1cefaed5b7a3471cb08564e54d5ba866/2e733c049ad7445584ae7adbc7900c69.html) — what was reported?** | Individual messages produced during processing, with their text and status/type. Available details may include time, message identifiers, data links and long text. | Preserve the exact reported errors, warnings and outcomes. Connect messages to the same record and relevant field where the source explicitly supplies that relationship. | That the first error is the root cause, that repeated messages represent different failed documents, or that this view contains every historical attempt. |
| **[Data Structure](https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/ed18d1cc52c447f78a2e26195f7cb450.html?locale=en-US&state=PRODUCTION&version=202110.002) — where does the data sit?** | The hierarchy of structures and tables in the message's raw data; selecting a structure leads to its data content. Labels and visible structures may be customised. | Retain the relationship between headers, items and fields. A supplied field/row link can locate which part of the payload an error concerns. | That a field is incorrect simply because it is highlighted, or that all interfaces use the same hierarchy and names. |
| **[Data Content](https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/73ac69e929734790ab6c554c30f14e0f.html?locale=en-US&state=PRODUCTION&version=202310.002) — what values were supplied?** | Field values for the selected structure or table. Depending on the interface and export, these may include company, account, document, item, date, amount or currency values. | Preserve actual values with their labels and scope, including leading zeroes. Keep source values and attempted target values distinct if both are supplied. | That the attempted target value is the intended business value, that a mapping is correct, or that a referenced master-data record currently exists. |
| **Error details — what does this message specifically refer to?** | Message type, class/number, substitution values and explanatory text where included. These details may be accessed from a message rather than delivered as a separate tab. | Preserve technical identity alongside readable wording. Associate values with their meanings only when the supplied text or labels support that interpretation. | That every error has detailed metadata or long text, or that troubleshooting guidance in the text proves the cause or authorises an action. |

The linked SAP descriptions cover different releases; they explain the concepts, not one guaranteed customer layout. The exact fields present in our input remain subject to real-sample validation.

### Reading message details without overinterpreting them

Some supplied technical details may use the following SAP-style field names. They are useful signals when present, not fields we assume every export includes. SAP documents these core fields in its [application-log message data reference](https://help.sap.com/docs/SAP_NETWEAVER_750/addb96cd90c945dfb3182865363bbc47/4e2106b735d44180e10000000a15822b.html?locale=en-US&state=PRODUCTION&version=7.5.27).

| Detail | Plain-language meaning | Extraction principle |
| --- | --- | --- |
| **Message type / `MSGTY`** | The message's reported type, such as an error or warning. | Preserve the supplied value. Message severity is separate from business priority. |
| **Message class / `MSGID`** | The family or catalogue to which a message belongs. | Preserve it exactly; do not infer a class from familiar wording. |
| **Message number / `MSGNO`** | The identifier within that class. | Keep it together with the class, including leading zeroes. The number alone is insufficient context. |
| **Message variables / `MSGV1`–`MSGV4`** | Values inserted into a message's text, potentially an account, company or another object. | Preserve their order and values. Variable 1 is not universally an account; its meaning depends on that message. |
| **Rendered text / template** | The readable error statement, possibly with placeholders replaced by values. | Preserve the original wording and any supplied template separately. Do not reconstruct a missing template from memory. |
| **Long text / custom hint** | Additional explanation or guidance associated with the message. | Retain supplied content during extraction. The summary states the reported facts without turning embedded advice into a proposed fix. |
| **Field or row link** | A supplied association between the message and a part of its data. | Preserve the association where explicit. A nearby row or matching value alone is not a reliable link. |

### How the views fit together: one fictional error

This example revisits the earlier teaching scenario. **All values, message codes, layouts and field paths below are fictional; this is not an SAP export or a verified standard SAP message.**

| View | Illustrative evidence | What it adds to the case |
| --- | --- | --- |
| **Data message** | Source document `1900000421`, company `1000`, fiscal year `2026`; target `CFIN-DEMO / 100`; attempt `1` reports an error. | Identifies the supplied document and processing context. |
| **Log messages** | “G/L account 0000410000 is not maintained in company code 2000.” A further entry says posting stopped and no target document reference was returned. | Records the specific reported failure and the reported processing outcome. |
| **Data structure** | The message explicitly links to `Items[1].target_gl_account`. | Connects that reported failure to a particular item and field. |
| **Data content** | Item `0001` has source account `0000400000`, attempted target account `0000410000`, requested target company `2000` and debit `GBP 1,250.00`. | Supplies the values and business context attached to that item. |
| **Error details** | Fictional class `Z_DEMO_CFIN`, number `001`, type `E`; supplied template and variables associate `0000410000` with the account and `2000` with the company. | Preserves the message's technical identity and explains the values used in its wording. |

Together these views support a factual description: **the log reports an account-maintenance error for the attempted account/company combination and says posting stopped for this attempt.** They do not independently establish why that state arose, whether the mapping was correct, or what someone should change.

The earlier teaching walkthrough also explored hypothetical external checks. Those checks are outside this MVP: the current log is the only source of current-case facts.

### Variability and missing information

- **Only uploaded content is available.** A missing view, cropped screenshot, truncated export or filtered set of messages cannot be reconstructed reliably. Make those limitations visible.
- **Attempts must remain distinct.** After a restart, the Log Messages view can contain only messages from that restart. Do not assume the upload contains a complete chronology or that an absent success message proves no later success occurred. See [SAP's Log Messages description](https://help.sap.com/docs/SAP_APPLICATION_INTERFACE_FRAMEWORK/1cefaed5b7a3471cb08564e54d5ba866/2e733c049ad7445584ae7adbc7900c69.html).
- **Names and wording may change.** Preserve customer-specific labels and messages. Unknown content belongs in an unclassified entry rather than being silently discarded.
- **A blank is not a confirmed absence.** An empty field, an unavailable section and an explicit “not found” statement have different meanings.
- **Conflicting details stay visible.** Do not silently choose between inconsistent statuses, identifiers or timestamps to produce a cleaner story.

## Extraction, evidence and structured handoffs

**Extraction captures breadth; error analysis works only from that structured output; summarisation makes the resulting case readable.** Agent 2 does not receive the raw original, investigate SAP or search historical cases. It can cite extraction references, apply one maintained category tag, and state a supported cause hypothesis with uncertainty. It cannot confirm a root cause or choose a remediation outside the route returned by the tool.

Every agent returns structured output defined with **Pydantic**, giving the next step predictable fields. These are our application contracts, not a claim that SAP exports follow that schema.

| Handoff | What we preserve | Why it matters |
| --- | --- | --- |
| **Agent 1: extracted log** | Source identity/version; original text and location; metadata, messages, payload fields and unfamiliar entries; exact values, context, ambiguity and extraction limitations. | Retains the supplied evidence even when a new customer or interface introduces unexpected content. |
| **Agent 2: error analysis** | One maintained category tag or `unclassified`; cause hypothesis; confidence; supporting extraction references; competing explanations or gaps; maintained owner, route and escalation identifiers. | Keeps analysis traceable to the structured extraction and prevents a free-form owner or remediation recommendation. |
| **Agent 3: case content** | A title; cited log facts; clearly labelled hypothesis, category, owner and proposed route; unresolved details; history-search status; related cases with cited similarities and differences. | Produces content the case page can display consistently and the user can validate before a human approves a change. |

The versioned contracts are in [log_only_contracts.py](backend/src/cfin/log_only_contracts.py). They support several preserved text originals, exact source line references and application-computed coverage limitations. They are connected to the [factual executor](backend/src/cfin/log_only_workflow.py), versioned worker snapshots, database publication and the portal. New-flow dispatch remains behind the explicit rollout switch. Real export formats may require different locations or additional fields; we will adjust after inspecting real samples.

Pydantic checks output structure. Code checks source identities and reference validity. **Neither guarantees that an agent captured everything or interpreted it correctly.** We measure those qualities with reviewed examples. If extraction or a handoff fails, the case must show the limitation or analysis failure rather than an apparently complete brief.

## What the user sees in each case

| Case section | Reader experience |
| --- | --- |
| **Title and summary** | A short factual title followed by scannable log facts, then separately labelled category, cause hypothesis, owner, proposed route and approval state. |
| **Unclear or missing details** | Material ambiguity, contradictions and extraction limitations are visible in plain language. |
| **Related cases** | Separate references to actual retrieved cases, explaining why they are similar and what differs. Any past findings or outcomes are clearly attributed to that earlier case. |
| **Original log** | The complete, unchanged supplied log is embedded in the case, including every supplied view or attachment. Evidence references lead back to the relevant source location. |
| **Ownership and activity** | The configured owner, case-log approval tags, evidence uploads, reprocessing result, escalation state, review feedback and case updates remain in the existing case experience. |

### Summary Agent case format

The Summary Agent creates the investigator-facing case content. It does not expose a raw machine payload, invent operational state, or replace the case board's activity controls. Code renders the sections below as a case page and stores the category, owner, route and state as structured fields for filtering, routing and API use.

| Case section | Summary Agent responsibility | System or human responsibility |
| --- | --- | --- |
| **Case header and controls** | Write a factual title tied to the supplied failure. | Code displays ID, title, named owner, status, priority, error type, Case Creation Date and Due Date at the top, with reassignment, status change and closure controls. |
| **Case summary** | Explain the reported exception and any supported cause hypothesis together, keeping facts and proposed cause visibly distinct. | Cite the original. The proposed cause requires human validation; do not display an unsupported confidence label or duplicate Error assessment panel. |
| **Document and processing context** | Present every relevant extracted detail, including document number, source/target system, client, company, interface, affected object, attempt, timestamp and outcome when supplied. | Code preserves source/version references and does not manufacture an absent value. |
| **Evidence from the original log** | Select the most relevant factual evidence and cite its precise original-log location. | The complete original remains available for cross-validation. |
| **Defined resolution and escalation path** | Explicitly list the error type’s governed route, responsible people/roles, approval evidence, remediation, reprocessing and confirmation of CFIN posting. | Show the agreed route without additional exception-path text or a separate Escalation panel. Case ownership changes only through an explicit handover. |
| **Similar earlier cases** | Explain why an eligible prior case is similar and what differs, with a case/evidence citation. | Retrieval is authorised, bounded and separately attributed; earlier findings do not prove the current cause. |
| **Case chat and original** | No generated activity narrative. | A plain chronological discussion preserves comments, approvals and their message-specific files. The complete unchanged source is only in Original log, the third tab. No separate Evidence tab or case-owner sidebar. Closure remains an attributed record with supporting files. |

The rendered case uses this format:

> **Case header:** factual title, case number, one named owner, status, priority, error type, Case Creation Date and Due Date, plus case actions.
>
> **Tabs:** Summary · Case chat · Original log
>
> ## Case summary
>
> The supplied log reports that target G/L account `0041001000` could not be located for chart `SYN1`. Posting stopped and no CFIN document reference was returned. Cite the actual source lines.
>
> **Proposed cause — requires human validation:** Required target master data may be unavailable. A reviewer must validate the target-system state before confirming the cause.
>
> ## Document and processing context
>
> Include document number, source system/client, target system/client, company, amount/currency, interface, affected object, timestamp, attempt and outcome where supplied. Absent values say “Not supplied”.
>
> ## Evidence from the original log
>
> Quote the relevant actual source lines with precise references. The complete original stays in the third tab.
>
> ## Defined resolution and escalation path
>
> **Master data:** route to Maya Shah (MDG Process Owner) → Maya requests Daniel Ross’s RTR approval → approval and its email evidence are recorded in Case chat → Maya creates the data, attaches change evidence and gives the go-ahead → Liam Carter (Data Operations) reprocesses → Liam confirms successful CFIN posting and attaches validation evidence.
>
> **Mapping:** Maya confirms the correct mapping with Daniel → Maya maintains the mapping and attaches evidence → Daniel reviews and approves, with the approval email attached to its message → Liam reprocesses → Liam confirms successful CFIN posting and attaches validation evidence.
>
> ## Similar earlier cases
>
> Cite only relevant reviewed matches retrieved using the error type. When none is available, say so.
>
> ## Closure record, when closed
>
> Preserve the resolution, scope, action, outcome, author, timestamp and supporting attachments.

### How the Summary Agent finds similar cases

The Error Analysis `category_id` is the **primary** case-board query filter. It is not sufficient on its own: a master-data case from another interface, company or system may be misleading. Code therefore builds a bounded, authorised query using the category together with available extracted context:

1. Exact maintained error category, for example `master_data`, `mapping` or `tax`.
2. Affected object and message identity, when supplied: object type, message class/number or error code.
3. Source system, target/CFIN system, interface, company code and relevant organisational context.
4. Document attributes that are safe and useful for similarity, such as account, chart of accounts or processing outcome.
5. Only reviewed/eligible prior cases in the same authorised workspace; exclude the current case, withdrawn material and records the caller cannot access.

The retrieval service returns a small ranked candidate set. The Summary Agent may cite a candidate only after comparing it with the current case's original-log facts and must state material differences. It can return no similar cases. Owner tags help route the current case, but are not a similarity signal because the same owner can handle unrelated failures.

The factual-only [versioned system prompt](backend/src/cfin/log_only_prompts.py) remains pinned for existing cases. The Error Analysis prompts in [error_analysis_prompts.py](backend/src/cfin/error_analysis_prompts.py) use the same source-citation requirements while keeping the Error Analysis hypothesis and code-owned route separate. They preserve uncertainty, prevent an invented category, owner or remediation, and keep historical material separate. For the fictional example above, a suitable case brief would be:

> **Posting stopped for document 1900000421**
>
> - The supplied log reports an error for attempt 1 of source document `1900000421`, company `1000`, fiscal year `2026`.
> - It reports that attempted target G/L account `0000410000` is not maintained in company `2000`, linked to item `0001`.
> - Posting stopped for that attempt, and the log says no target document reference was returned.
>
> **Analysis and route**
>
> - Category: `master_data` — hypothesis pending Process Owner validation.
> - Owner: MDG Process Owner. The next step is to request Process Owner approval in the case-log conversation before any data creation.
>
> **Unclear or missing details**
>
> - The supplied evidence does not show later attempts or independently verify the current target-system state.
>
> **Related cases**
>
> - No historical search was performed for this illustration.

The rendered case also includes evidence references for its factual statements. The original remains accessible for validation; the product succeeds when routine understanding comes from the brief.

## How feedback improves future cases

### Meaningful human updates are required

The case page must capture useful human findings at key milestones. A comment such as “fixed” or “done” is insufficient as a completion or resolution record. The existing requirements remain:

| When | What the person must record |
| --- | --- |
| **Correcting the AI brief or marking it insufficient** | What is incorrect or missing, with supporting evidence for corrected facts. |
| **Blocking or reopening work** | The specific blocker or reason for returning the case to active work. |
| **Completing work** | What changed, which object/system was affected, and supporting evidence; explain explicitly if no change was needed. |
| **Recording resolution** | Findings and their evidence; confirmed cause or explicit uncertainty; action taken; outcome and proof; relevant scope and remaining gaps. |

Reuse information already captured on the case so people do not repeat it in a separate comment. Attribute updates to the person and time, and keep human findings distinct from the original AI brief. Required fields establish that information was supplied; human review establishes whether it is meaningful and supported. A case must not be treated as resolved while its required resolution record is incomplete.

**Case chat attachments — implemented in the local preview on 3 October 2026.** Every case message supports one or more file attachments, displayed on that specific message in the chronological conversation. Attachments are optional for ordinary messages; when recording approval received by email, the approval email must be uploaded and linked to the message recording that decision. The approval action stays disabled until supporting evidence is selected. Record the message author and time, filenames and upload attribution, and identify the external approver separately from the person uploading the email. The Case chat displays message-specific attachments; the complete source stays in the Original log tab. The local preview persists attachment metadata in browser storage; durable file bytes, access controls and virus scanning require the production storage service. Email capture is manual for this MVP; automatic email ingestion is future work.

These are records of human investigation and work. Agent 2 proposes only a maintained category and route, while people validate the cause, approve a change and record the outcome. Useful human updates provide the substance for future historical references.

### Reviewed learning feeds the Summary Agent

Human corrections, findings and outcomes enter the **existing reviewed knowledge process**. Eligible case versions can then be retrieved by the Summary Agent for future cases. Internal read-only access means reading authorised case records, logs and learnings already held by this app; it does not mean connecting to SAP.

For each relevant prior case, Agent 3 should:

1. Read the retrieved case evidence rather than relying on a title or similarity score alone.
2. Identify the specific shared details and important differences.
3. Cite the actual prior case and supporting material in **Related cases**.
4. Attribute recorded findings and outcomes to that historical case without treating them as the current cause or suggesting the same fix.

A completed search with no relevant result is different from an unavailable search or one that was not performed. The case should show the correct state. Corrections, withdrawn knowledge and access changes continue to use the existing controls.

## How we will know it works

Real AIF sample collection is the next evidence-gathering priority. Existing fixtures are synthetic, so they cannot establish coverage of customer formats or production reliability. Start with a reviewed sample set, retain unseen variations for comparison, and evaluate each stage as well as the complete case.

| Product measure | What we assess |
| --- | --- |
| **Extraction completeness** | Which supplied messages, fields and relationships were captured or missed? Are unfamiliar sections retained and limitations reported? |
| **Factual fidelity** | Are identifiers, amounts, source/target scope and attempts preserved? Are there unsupported statements or altered meanings? |
| **Error-analysis quality** | Did Agent 2 choose the correct maintained category, retain the supporting extracted evidence, and expose competing explanations? For reviewed `master_data` and `mapping` pilot examples, did it avoid the evaluation failure of returning `unclassified`? |
| **Summary usefulness** | Can an analyst accurately understand the exception from the brief? Measure reading time, corrections and how often the original must be opened to recover omitted information. |
| **Historical reference quality** | Are cited cases relevant and correctly represented, with useful differences and valid links? Is historical context kept separate from current facts? |
| **Behavioural boundaries** | Does the output avoid unsupported categories, invented owners or remediation, preserve uncertainty, require recorded human approval, and treat instructions inside logs or past cases as source content rather than commands? |
| **Reliability and economics** | Track completion and retry rates, latency, model usage and cost per completed case. Preserve visible failures and existing access controls. |

Model and prompt comparisons use the same inputs and scoring criteria. Include custom wording, missing sections, long logs, multiple messages/items, repeated attempts, misleading historical similarities and contradictions. Keep expected answers and a test case's later findings out of its inputs and retrievable history. Agree acceptance thresholds after establishing a measured baseline; no accuracy or time-saving claim is assumed today.

## Delivery status and next increment

This is a focused revision of the analysis flow within the existing product. Reuse the case portal, storage, ownership controls, processing infrastructure, feedback lifecycle and observability. Existing backlog capabilities remain separate from this three-agent case-analysis flow.

| Area | Current position |
| --- | --- |
| **Product direction and models** | Agreed in this README. Existing model defaults already match the selected baseline. |
| **Current workbench** | The root page renders `WorkbenchApp`: a browser-local Mantine demo with four operational statuses, one explicit named owner, message attachment metadata, evidence-backed simulated approval and closure controls, creation/due dates, inclusive filtering and CSV export. Authenticated backend integration, durable attachment bytes and live agent execution remain pending. |
| **Structured handoffs and summary behaviour** | Versioned Error Analysis contracts, source checks, three prompts, enforced Agent 2 input boundary and durable SDK checkpoints are implemented with software tests. |
| **Running workflow** | Immutable original intake, Extraction → Error Analysis → code-owned route lookup → Summary, recovery and rendered cases are wired under `error-analysis-v1`. Cloud activation remains gated until the additive migration is verified; legacy and factual jobs remain pinned to their earlier workflow. |
| **Historical evidence access** | Bounded eligible reviewed prior case/log content reaches Agent 3 only, with precise versions, access checks and withdrawal handling. |
| **Human controls and ownership** | The two pilot routes enforce ordered MDG Process Owner, Process Owner and Data Operations milestones, approvals and proof records. The other eight maintained tags and `unclassified` route to CFIN Exception Manager; legacy human records remain unchanged. |
| **External JSON API** | Versioned read-only projections, complete originals, OpenAPI and scoped revocable machine access are implemented. Customer-specific Joule integration and external writes remain later work. |
| **Evaluation and real-input evidence** | The initial text envelope is 8 originals / 8,192 bytes / 64 lines. Contract tests and a five-case zero-cost Promptfoo policy gate pass, including the pilot `unclassified` failure rule. Representative AIF samples, human-reviewed expectations, provider-backed semantic acceptance and user-comprehension measurements remain release evidence to obtain. |

The remaining release work is evidence-driven: validate actual database/provider journeys and deployment, have people review model quality and measure comprehension before widening capacity or claiming user benefit. The historical [build ledger](archive/BUILD.md) retains earlier verification evidence and rollback gates.

## Archived supporting material

Earlier product briefs, implementation plans, technical guides, evaluation notes and package documentation are retained in [archive/README.md](archive/README.md). They are historical reference material only and do not define the current product direction.
