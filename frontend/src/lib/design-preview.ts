import type { CaseSummary } from "@/lib/api";

/** Static synthetic content for the design-preview route only. Never use as API fallback data. */
export type PreviewCase = CaseSummary & {
  reference: string;
  documentNumber: string;
  companyCode: string;
  sourceSystem: string;
  targetSystem: string;
  targetAccount: string | null;
  owner: string | null;
  category: string;
  amount: string;
  attempt: string;
  reviewReason: string;
  evidence: {
    name: string;
    detail: string;
    state: "available" | "pending";
    content: string;
  }[];
  activity: { time: string; title: string; detail: string }[];
};

// MD-01 mirrors agent-visible fixture evidence. VIS-02–VIS-06 are illustrative UI records only.
// No oracle or simulated resolution proof is included, and no AI run or human approval is claimed.
export const previewCases: PreviewCase[] = [
  {
    "id": "preview-md-01",
    "reference": "MD-01",
    "documentNumber": "0000123456",
    "companyCode": "0010",
    "sourceSystem": "ERP-DEMO",
    "targetSystem": "CFIN-DEMO",
    "targetAccount": "0041001000",
    "owner": null,
    "category": "Cause not established",
    "amount": "1,250.00 GBP",
    "attempt": "MD01-0001",
    "title": "Target G/L account unavailable",
    "description": "Synthetic MD-01 fixture. The source document is posted; target replication failed. The candidate mapping and playbook await actual human review.",
    "priority": "P2",
    "status": "created",
    "diagnosis_status": "needs_review",
    "created_at": "2026-09-30T09:00:00Z",
    "due_at": null,
    "version": 1,
    "reviewReason": "The failure-time lookup confirms account 0041001000 is absent, but the intended target mapping remains Pending review. The cause is not established and actionable guidance is withheld. No owner or deadline has been recorded.",
    "evidence": [
      {
        "name": "Original log",
        "detail": "Exact UTF-8 synthetic original · MD01-log v1",
        "state": "available",
        "content": "SYNTHETIC FIXTURE — MD-01; fictional application log, not an SAP export.\nNo SAP release, message class, message number, or product-specific interface semantics are asserted.\n2026-09-30T09:00:00Z | attempt_id=MD01-0001 | processing_order=1 | event=replication_started\nsource_system=ERP-DEMO | source_client=010 | source_company_code=0010\nfiscal_year=2026 | document_number=0000123456 | source_status=posted\nsource_posting_date=2026-09-30 | source_posted_at=2026-09-30T08:45:00Z\ntarget_system=CFIN-DEMO | target_client=100 | target_company_code=0010\ninterface=DEMO_CFIN_GL | target_chart_of_accounts=SYN1\nsource_line=0001 | source_account=0000400000 | debit=1250.00 | credit=0.00 | currency=GBP\nsource_line=0002 | source_account=0000200000 | debit=0.00 | credit=1250.00 | currency=GBP\n2026-09-30T09:00:00Z | synthetic_message_id=DEMO_GL_LOOKUP_FAILURE | severity=error\nObserved target lookup: G/L account 0041001000 could not be located for chart SYN1 in CFIN-DEMO/100.\nRequested posting company code: 0010. Requested target line: 0001.\n2026-09-30T09:00:00Z | synthetic_message_id=DEMO_POSTING_STOPPED | severity=error\nTarget posting stopped for this attempt; no target document reference was returned.\n2026-09-30T09:00:00Z | event=replication_finished | result=failed\nEvidence is limited to this attempt. Error wording alone does not establish an approved diagnosis.\n"
      },
      {
        "name": "Posted source document",
        "detail": "Balanced GBP posting · MD01-source-posting v1",
        "state": "available",
        "content": "{\n  \"synthetic\": true,\n  \"source_id\": \"MD01-source-posting\",\n  \"source_version\": \"1\",\n  \"kind\": \"records\",\n  \"observed_at\": \"2026-09-30T08:45:01Z\",\n  \"attempt_id\": \"MD01-0001\",\n  \"provenance\": \"Authored fictional source business-record snapshot. No live SAP lookup was performed.\",\n  \"identity\": {\n    \"workspace_id\": \"synthetic-cfin-demo\",\n    \"source_system\": \"ERP-DEMO\",\n    \"source_client\": \"010\",\n    \"source_company_code\": \"0010\",\n    \"fiscal_year\": \"2026\",\n    \"document_number\": \"0000123456\",\n    \"target_system\": \"CFIN-DEMO\",\n    \"target_client\": \"100\",\n    \"interface\": \"DEMO_CFIN_GL\"\n  },\n  \"records\": [\n    {\n      \"record_id\": \"source-header\",\n      \"posting_status\": \"posted\",\n      \"posted_at\": \"2026-09-30T08:45:00Z\",\n      \"posting_date\": \"2026-09-30\",\n      \"currency\": \"GBP\",\n      \"debit_total\": \"1250.00\",\n      \"credit_total\": \"1250.00\",\n      \"source_document_number\": \"0000123456\",\n      \"source_company_code\": \"0010\",\n      \"fiscal_year\": \"2026\"\n    },\n    {\n      \"record_id\": \"source-line-0001\",\n      \"line_number\": \"0001\",\n      \"source_account\": \"0000400000\",\n      \"debit\": \"1250.00\",\n      \"credit\": \"0.00\",\n      \"currency\": \"GBP\"\n    },\n    {\n      \"record_id\": \"source-line-0002\",\n      \"line_number\": \"0002\",\n      \"source_account\": \"0000200000\",\n      \"debit\": \"0.00\",\n      \"credit\": \"1250.00\",\n      \"currency\": \"GBP\"\n    }\n  ]\n}\n"
      },
      {
        "name": "Mapping reference",
        "detail": "Candidate rows · Pending review · No reviewer recorded",
        "state": "pending",
        "content": "{\n  \"synthetic\": true,\n  \"source_id\": \"MD01-mapping\",\n  \"source_version\": \"1\",\n  \"kind\": \"records\",\n  \"observed_at\": \"2026-09-30T09:00:00Z\",\n  \"attempt_id\": null,\n  \"provenance\": \"Authored fictional applicable mapping reference for the failure-time snapshot. Its approval is required and has not occurred.\",\n  \"owner_role\": \"Demo Mapping Owner\",\n  \"review\": {\n    \"reuse_status\": \"pending_review\",\n    \"approved_version\": null,\n    \"reviewer\": null,\n    \"reviewed_at\": null,\n    \"review_rationale\": null,\n    \"effective_from\": \"2026-09-01\",\n    \"review_due\": \"2026-12-30\",\n    \"expires_on\": \"2027-03-31\",\n    \"withdrawn_at\": null,\n    \"approval_required\": true,\n    \"approval_note\": \"Generated synthetic draft. An actual authenticated reviewer must approve this exact version and scope; no human approval has been recorded.\"\n  },\n  \"query_scope\": {\n    \"source_system\": \"ERP-DEMO\",\n    \"source_client\": \"010\",\n    \"source_company_code\": \"0010\",\n    \"target_system\": \"CFIN-DEMO\",\n    \"target_client\": \"100\",\n    \"company_code\": \"0010\",\n    \"chart_of_accounts\": \"SYN1\",\n    \"interface\": \"DEMO_CFIN_GL\"\n  },\n  \"scope_complete\": true,\n  \"state\": \"found\",\n  \"records\": [\n    {\n      \"record_id\": \"mapping-0001\",\n      \"source_account\": \"0000400000\",\n      \"target_account\": \"0041001000\",\n      \"effective_from\": \"2026-09-01\",\n      \"expires_on\": \"2027-03-31\",\n      \"posting_date_in_scope\": \"2026-09-30\",\n      \"scope\": {\n        \"source_system\": \"ERP-DEMO\",\n        \"source_client\": \"010\",\n        \"source_company_code\": \"0010\",\n        \"target_system\": \"CFIN-DEMO\",\n        \"target_client\": \"100\",\n        \"company_code\": \"0010\",\n        \"chart_of_accounts\": \"SYN1\",\n        \"interface\": \"DEMO_CFIN_GL\"\n      }\n    },\n    {\n      \"record_id\": \"mapping-0002\",\n      \"source_account\": \"0000200000\",\n      \"target_account\": \"0021000000\",\n      \"effective_from\": \"2026-09-01\",\n      \"expires_on\": \"2027-03-31\",\n      \"posting_date_in_scope\": \"2026-09-30\",\n      \"scope\": {\n        \"source_system\": \"ERP-DEMO\",\n        \"source_client\": \"010\",\n        \"source_company_code\": \"0010\",\n        \"target_system\": \"CFIN-DEMO\",\n        \"target_client\": \"100\",\n        \"company_code\": \"0010\",\n        \"chart_of_accounts\": \"SYN1\",\n        \"interface\": \"DEMO_CFIN_GL\"\n      }\n    }\n  ],\n  \"limitations\": [\n    \"A found draft row is not an approved intended target.\",\n    \"Applicability is limited to the supplied fictional source and target scope and date.\",\n    \"No customer policy or real SAP configuration is asserted.\"\n  ]\n}\n"
      },
      {
        "name": "Target account lookup",
        "detail": "Complete scoped synthetic lookup at 09:00 UTC",
        "state": "available",
        "content": "[\n  {\n    \"lookup_id\": \"md01-required-chart-account\",\n    \"state\": \"confirmed_absent\",\n    \"query_scope\": {\n      \"target_system\": \"CFIN-DEMO\",\n      \"target_client\": \"100\",\n      \"company_code\": \"0010\",\n      \"target_account\": \"0041001000\",\n      \"missing_component\": \"chart_account\",\n      \"chart_of_accounts\": \"SYN1\"\n    },\n    \"scope_complete\": true,\n    \"records\": [],\n    \"source\": {\n      \"source_id\": \"MD01-target-master-snapshot\",\n      \"source_version\": \"1\",\n      \"kind\": \"records\",\n      \"observed_at\": \"2026-09-30T09:00:00Z\",\n      \"attempt_id\": \"MD01-0001\",\n      \"synthetic\": true,\n      \"record_ids\": [\n        \"lookup-required-chart-complete\"\n      ]\n    },\n    \"citations\": [\n      {\n        \"source_id\": \"MD01-target-master-snapshot\",\n        \"source_version\": \"1\",\n        \"attempt_id\": \"MD01-0001\",\n        \"record_id\": \"lookup-required-chart-complete\"\n      }\n    ],\n    \"detail\": \"Completed exact-key query over the full fictional snapshot for this scope. Zero rows returned. The citation identifies the query-completion audit record, not an invented account row.\"\n  },\n  {\n    \"lookup_id\": \"md01-required-company-extension\",\n    \"state\": \"confirmed_absent\",\n    \"query_scope\": {\n      \"target_system\": \"CFIN-DEMO\",\n      \"target_client\": \"100\",\n      \"company_code\": \"0010\",\n      \"target_account\": \"0041001000\",\n      \"missing_component\": \"company_code_extension\",\n      \"chart_of_accounts\": \"SYN1\"\n    },\n    \"scope_complete\": true,\n    \"records\": [],\n    \"source\": {\n      \"source_id\": \"MD01-target-master-snapshot\",\n      \"source_version\": \"1\",\n      \"kind\": \"records\",\n      \"observed_at\": \"2026-09-30T09:00:00Z\",\n      \"attempt_id\": \"MD01-0001\",\n      \"synthetic\": true,\n      \"record_ids\": [\n        \"lookup-required-extension-complete\"\n      ]\n    },\n    \"citations\": [\n      {\n        \"source_id\": \"MD01-target-master-snapshot\",\n        \"source_version\": \"1\",\n        \"attempt_id\": \"MD01-0001\",\n        \"record_id\": \"lookup-required-extension-complete\"\n      }\n    ],\n    \"detail\": \"Completed exact-key query over the full fictional snapshot for this scope. Zero rows returned. The citation identifies the query-completion audit record, not an invented account row.\"\n  },\n  {\n    \"lookup_id\": \"md01-counterpart-chart-account\",\n    \"state\": \"found\",\n    \"query_scope\": {\n      \"target_system\": \"CFIN-DEMO\",\n      \"target_client\": \"100\",\n      \"company_code\": \"0010\",\n      \"target_account\": \"0021000000\",\n      \"missing_component\": \"chart_account\",\n      \"chart_of_accounts\": \"SYN1\"\n    },\n    \"scope_complete\": true,\n    \"records\": [\n      {\n        \"record_id\": \"counterpart-chart-account\",\n        \"chart_of_accounts\": \"SYN1\",\n        \"target_account\": \"0021000000\",\n        \"posting_blocked\": false\n      }\n    ],\n    \"source\": {\n      \"source_id\": \"MD01-target-master-snapshot\",\n      \"source_version\": \"1\",\n      \"kind\": \"records\",\n      \"observed_at\": \"2026-09-30T09:00:00Z\",\n      \"attempt_id\": \"MD01-0001\",\n      \"synthetic\": true,\n      \"record_ids\": [\n        \"counterpart-chart-account\"\n      ]\n    },\n    \"citations\": [\n      {\n        \"source_id\": \"MD01-target-master-snapshot\",\n        \"source_version\": \"1\",\n        \"attempt_id\": \"MD01-0001\",\n        \"record_id\": \"counterpart-chart-account\"\n      }\n    ],\n    \"detail\": \"Completed exact-key query over the full fictional snapshot for this scope. One matching record returned.\"\n  },\n  {\n    \"lookup_id\": \"md01-counterpart-company-extension\",\n    \"state\": \"found\",\n    \"query_scope\": {\n      \"target_system\": \"CFIN-DEMO\",\n      \"target_client\": \"100\",\n      \"company_code\": \"0010\",\n      \"target_account\": \"0021000000\",\n      \"missing_component\": \"company_code_extension\",\n      \"chart_of_accounts\": \"SYN1\"\n    },\n    \"scope_complete\": true,\n    \"records\": [\n      {\n        \"record_id\": \"counterpart-company-extension\",\n        \"chart_of_accounts\": \"SYN1\",\n        \"company_code\": \"0010\",\n        \"target_account\": \"0021000000\",\n        \"posting_blocked\": false\n      }\n    ],\n    \"source\": {\n      \"source_id\": \"MD01-target-master-snapshot\",\n      \"source_version\": \"1\",\n      \"kind\": \"records\",\n      \"observed_at\": \"2026-09-30T09:00:00Z\",\n      \"attempt_id\": \"MD01-0001\",\n      \"synthetic\": true,\n      \"record_ids\": [\n        \"counterpart-company-extension\"\n      ]\n    },\n    \"citations\": [\n      {\n        \"source_id\": \"MD01-target-master-snapshot\",\n        \"source_version\": \"1\",\n        \"attempt_id\": \"MD01-0001\",\n        \"record_id\": \"counterpart-company-extension\"\n      }\n    ],\n    \"detail\": \"Completed exact-key query over the full fictional snapshot for this scope. One matching record returned.\"\n  }\n]\n"
      },
      {
        "name": "Missing-master playbook",
        "detail": "SYN-MD-GL-001 v1 · Pending review",
        "state": "pending",
        "content": "{\n  \"synthetic\": true,\n  \"guidance_id\": \"SYN-MD-GL-001\",\n  \"source_id\": \"MD01-playbook\",\n  \"source_version\": \"1\",\n  \"title\": \"Fictional target G/L master-data restoration playbook\",\n  \"scope\": {\n    \"target_system\": \"CFIN-DEMO\",\n    \"target_client\": \"100\",\n    \"company_code\": \"0010\",\n    \"chart_of_accounts\": \"SYN1\"\n  },\n  \"reuse_status\": \"pending_review\",\n  \"approved_version\": null,\n  \"reviewer\": null,\n  \"reviewed_at\": null,\n  \"owner_role\": \"Demo Master Data Owner\",\n  \"effective_from\": \"2026-09-01\",\n  \"review_due\": \"2026-12-30\",\n  \"expires_on\": \"2027-03-31\",\n  \"provenance\": \"Generated draft for a synthetic demonstration. These are candidate human procedures pending approval of this exact version; they are not real SAP instructions or an enacted correction.\"\n}"
      }
    ],
    "activity": [
      {
        "time": "10:00 BST",
        "title": "Failure snapshot prepared",
        "detail": "Synthetic fixture MD01-0001 at 09:00 UTC. This preview is not a persisted operational case."
      },
      {
        "time": "Review pending",
        "title": "Reference approval required",
        "detail": "Mapping and playbook have no actual reviewer or approved version. No AI analysis or human correction has been executed."
      }
    ]
  },
  {
    "id": "preview-vis-02",
    "reference": "VIS-02",
    "documentNumber": "0000123481",
    "companyCode": "0020",
    "sourceSystem": "ERP-DEMO",
    "targetSystem": "CFIN-DEMO",
    "targetAccount": "0041202000",
    "owner": "Demo Master Data Owner (fictional)",
    "category": "Cause not established",
    "amount": "8,420.00 GBP",
    "attempt": "VIS02-0001",
    "title": "Company extension needs investigation",
    "description": "Illustrative synthetic design example. Company extension needs investigation. This is not a fixture result or a live persisted case.",
    "priority": "P3",
    "status": "in_progress",
    "diagnosis_status": "needs_review",
    "created_at": "2026-09-30T08:40:00Z",
    "due_at": "2026-10-01T08:40:00Z",
    "version": 1,
    "reviewReason": "Illustrative synthetic visual record. Company-code extension evidence would need a complete scoped lookup and approved mapping. P3 and the owner represent a hypothetical human choice; no review or AI diagnosis has occurred.",
    "evidence": [
      {
        "name": "Company extension evidence",
        "detail": "Illustrative pending lookup · No executed query",
        "state": "pending",
        "content": "ILLUSTRATIVE SYNTHETIC DESIGN RECORD — VIS-02\n\nVisual example only. The required company extension has not been looked up. Absence cannot be established from this design record.\n\nNot a persisted case, actual fixture result, executed AI output or human proof."
      }
    ],
    "activity": [
      {
        "time": "Visual example",
        "title": "Investigation state illustrated",
        "detail": "The In Progress state and fictional owner illustrate how a case could appear after a human starts work. No operational action is recorded."
      }
    ]
  },
  {
    "id": "preview-vis-03",
    "reference": "VIS-03",
    "documentNumber": "0000123512",
    "companyCode": "0010",
    "sourceSystem": "ERP-DEMO",
    "targetSystem": "CFIN-DEMO",
    "targetAccount": "0041403000",
    "owner": "Demo Master Data Owner (fictional)",
    "category": "Cause not established",
    "amount": "980.00 GBP",
    "attempt": "VIS03-0002",
    "title": "Account lookup unavailable",
    "description": "Illustrative synthetic design example. Account lookup unavailable. This is not a fixture result or a live persisted case.",
    "priority": "P2",
    "status": "blocked",
    "diagnosis_status": "needs_review",
    "created_at": "2026-09-30T08:25:00Z",
    "due_at": "2026-10-02T08:25:00Z",
    "version": 1,
    "reviewReason": "Illustrative synthetic visual record. A target lookup access gap would block investigation. Unavailable evidence does not confirm an absent account; no actual lookup failure or corrective work is asserted.",
    "evidence": [
      {
        "name": "Target lookup access",
        "detail": "Illustrative access gap · Confirmation required",
        "state": "pending",
        "content": "ILLUSTRATIVE SYNTHETIC DESIGN RECORD — VIS-03\n\nVisual example only. Target lookup access is represented as unavailable. No query was performed and no target account state is established.\n\nNot a persisted case, actual fixture result, executed AI output or human proof."
      }
    ],
    "activity": [
      {
        "time": "Visual example",
        "title": "Blocked state illustrated",
        "detail": "The hypothetical blocker is target evidence access. This visual state does not record an executed retry or human status change."
      }
    ]
  },
  {
    "id": "preview-vis-04",
    "reference": "VIS-04",
    "documentNumber": "0000123598",
    "companyCode": "0030",
    "sourceSystem": "ERP-DEMO",
    "targetSystem": "CFIN-DEMO",
    "targetAccount": "0041504000",
    "owner": "Demo Process Owner (fictional)",
    "category": "Cause not established",
    "amount": "3,100.00 GBP",
    "attempt": "VIS04-0001",
    "title": "G/L evidence awaiting owner review",
    "description": "Illustrative synthetic design example. G/L evidence awaiting owner review. This is not a fixture result or a live persisted case.",
    "priority": "P2",
    "status": "owner_notified",
    "diagnosis_status": "needs_review",
    "created_at": "2026-09-29T14:10:00Z",
    "due_at": "2026-10-01T14:10:00Z",
    "version": 1,
    "reviewReason": "Illustrative synthetic visual record. The Owner Notified state is a UI example; no notification was sent. Mapping applicability and target state remain unverified, so the cause needs review.",
    "evidence": [
      {
        "name": "Mapping scope review",
        "detail": "Illustrative pending reference · No approval",
        "state": "pending",
        "content": "ILLUSTRATIVE SYNTHETIC DESIGN RECORD — VIS-04\n\nVisual example only. Source-to-target mapping scope still needs review. No applicable approved mapping or actionable playbook is supplied.\n\nNot a persisted case, actual fixture result, executed AI output or human proof."
      }
    ],
    "activity": [
      {
        "time": "Visual example",
        "title": "Owner notification state illustrated",
        "detail": "A fictional process owner demonstrates the assigned display. No message delivery or authenticated assignment occurred."
      }
    ]
  },
  {
    "id": "preview-vis-05",
    "reference": "VIS-05",
    "documentNumber": "0000123604",
    "companyCode": "0010",
    "sourceSystem": "ERP-DEMO",
    "targetSystem": "CFIN-DEMO",
    "targetAccount": "0041605000",
    "owner": null,
    "category": "Cause not established",
    "amount": "450.00 GBP",
    "attempt": "VIS05-0001",
    "title": "Target master record needs review",
    "description": "Illustrative synthetic design example. Target master record needs review. This is not a fixture result or a live persisted case.",
    "priority": "P1",
    "status": "created",
    "diagnosis_status": "needs_review",
    "created_at": "2026-09-30T07:55:00Z",
    "due_at": "2026-10-02T07:55:00Z",
    "version": 1,
    "reviewReason": "Illustrative synthetic visual record. P1 shows a hypothetical lower-urgency human override and preserves a two-business-day deadline. Master-data evidence and ownership remain unconfirmed.",
    "evidence": [
      {
        "name": "Master-data review request",
        "detail": "Illustrative evidence placeholder · Not a lookup",
        "state": "pending",
        "content": "ILLUSTRATIVE SYNTHETIC DESIGN RECORD — VIS-05\n\nVisual example only. No target account lookup, approved reference, human finding or correction proof exists for this example.\n\nNot a persisted case, actual fixture result, executed AI output or human proof."
      }
    ],
    "activity": [
      {
        "time": "Visual example",
        "title": "New case state illustrated",
        "detail": "This example shows an unassigned case awaiting evidence review. The display is not a saved upload or completed analysis."
      }
    ]
  },
  {
    "id": "preview-vis-06",
    "reference": "VIS-06",
    "documentNumber": "Not supplied",
    "companyCode": "Unknown",
    "sourceSystem": "ERP-DEMO",
    "targetSystem": "CFIN-DEMO",
    "targetAccount": null,
    "owner": "Demo Process Owner (fictional)",
    "category": "Cause not established",
    "amount": "Unknown",
    "attempt": "VIS06-0001",
    "title": "Document identity needs completion",
    "description": "Illustrative synthetic design example. Document identity needs completion. This is not a fixture result or a live persisted case.",
    "priority": "P3",
    "status": "created",
    "diagnosis_status": "needs_review",
    "created_at": "2026-09-30T07:35:00Z",
    "due_at": "2026-10-01T07:35:00Z",
    "version": 1,
    "reviewReason": "Illustrative synthetic visual record. Document number, company and target account are unknown. Correlation and diagnosis would pause until a human supplies identity. P3 is a hypothetical display choice, not an AI urgency decision.",
    "evidence": [
      {
        "name": "Incomplete intake context",
        "detail": "Illustrative identity gap · Human input required",
        "state": "pending",
        "content": "ILLUSTRATIVE SYNTHETIC DESIGN RECORD — VIS-06\n\nVisual example only. Document number, source company and target account have not been supplied. Do not infer or merge an identity from similar wording.\n\nNot a persisted case, actual fixture result, executed AI output or human proof."
      }
    ],
    "activity": [
      {
        "time": "Visual example",
        "title": "Identity review state illustrated",
        "detail": "The fictional process-owner label shows where investigation could be coordinated. No actual assignment, merge or diagnosis occurred."
      }
    ]
  }
];
