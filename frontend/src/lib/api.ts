export type Workspace = {
  id: string;
  name: string;
  roles: string[];
  synthetic?: boolean;
};

export type CaseSummary = {
  id: string;
  title: string;
  description: string;
  priority: "P1" | "P2" | "P3";
  status: string;
  diagnosis_status: string;
  workflow_version?: string;
  result_kind?: "factual" | "legacy" | "error_analysis";
  factual_review_status?: string;
  analysis_status?: string;
  created_at: string;
  due_at: string | null;
  version: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isWorkspace(value: unknown): value is Workspace {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    Array.isArray(value.roles) &&
    value.roles.every((role) => typeof role === "string")
  );
}

function isCaseSummary(value: unknown): value is CaseSummary {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.title === "string" &&
    typeof value.description === "string" &&
    ["P1", "P2", "P3"].includes(String(value.priority)) &&
    typeof value.status === "string" &&
    typeof value.diagnosis_status === "string" &&
    typeof value.created_at === "string" &&
    (value.due_at === null || typeof value.due_at === "string") &&
    typeof value.version === "number"
  );
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    if (typeof window !== "undefined" && [401, 403].includes(status)) window.dispatchEvent(new Event("cfin:access-invalid"));
  }
}

async function request(path: string, token: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
  const origin = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
  const url = new URL(`${origin}${path}`);
  const response = await fetch(url, {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(body === undefined ? 15_000 : 45_000)]),
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new ApiError("Your session could not be verified. Sign out and sign in again.", 401);
    }
    if (response.status === 403) {
      throw new ApiError("Your account cannot perform this action in this workspace. Refresh access or contact the POC administrator.", 403);
    }
    if (response.status === 409) throw new ApiError("This case has changed. Refresh it and review the current version before trying again.", 409);
    const failure = await response.json().catch(() => null);
    const detail = isRecord(failure) && typeof failure.detail === "string" ? failure.detail.slice(0, 500) : isRecord(failure) && Array.isArray(failure.detail) ? failure.detail.filter(isRecord).slice(0, 3).map(item => `${Array.isArray(item.loc) ? item.loc.filter(part => part !== "body").join(" ") : "Field"}: ${String(item.msg || "Invalid value")}`).join(". ").slice(0, 500) : "";
    if (response.status === 503) {
      throw new ApiError(detail || "The case service is not ready. Ask the POC administrator to finish its configuration.", 503);
    }
    throw new ApiError(detail || "The request could not be saved. Check the fields and try again.", response.status);
  }

  return response.json();
}

export async function getWorkspaces(token: string, signal: AbortSignal): Promise<Workspace[]> {
  const data = await request("/api/workspaces", token, signal);
  if (!Array.isArray(data) || !data.every(isWorkspace)) {
    throw new Error("Workspace data could not be read. Ask the POC administrator to check the service.");
  }
  return data;
}

export async function getCases(workspaceId: string, token: string, signal: AbortSignal): Promise<CaseSummary[]> {
  const data = await request(`/api/cases?workspace_id=${encodeURIComponent(workspaceId)}`, token, signal);
  if (!Array.isArray(data) || !data.every(isCaseSummary)) {
    throw new Error("Case data could not be read. Ask the POC administrator to check the service.");
  }
  return data;
}

export type JsonRecord = Record<string, unknown>;
export type FactualEntry = { entry_id: string; source_id: string; source_version: string; source_span: { line_start: number; line_end: number }; raw_text: string; kind: string; fields: { name_as_logged: string; value_as_logged: string; context_as_logged?: string | null }[]; ambiguity?: string | null };
export type FactualStatement = { text: string; supporting_entry_ids: string[] };
export type FactualRelatedCase = { case_id: string; knowledge_id: string; knowledge_version: number; current_entry_ids: string[]; historical_citations: JsonRecord[]; matching_details: string[]; differing_details: string[]; historical_note?: string | null };
export type FactualResult = { result_kind: "factual"; outcome: string; extraction: { entries: FactualEntry[]; extraction_limitations: string[] } | null; summary?: { title: FactualStatement; statements: FactualStatement[]; unresolved_details: FactualStatement[]; related_cases: FactualRelatedCase[] } | null; title?: FactualStatement | null; statements?: FactualStatement[]; unresolved_details?: FactualStatement[]; related_cases?: FactualRelatedCase[]; limitations: string[]; failure_reason?: string | null; history?: { status: string; limitation?: string | null }; history_retrieval_status?: string; history_retrieval_limitation?: string | null };
export type ErrorAnalysisResult = JsonRecord & { result_kind: "error_analysis"; outcome: string };
export type ScenarioInput = { manifest: JsonRecord; original_log: string; sources?: JsonRecord[]; agent_files?: JsonRecord };
export type CaseDetail = {
  case: CaseSummary & JsonRecord;
  evidence: JsonRecord[];
  runs: JsonRecord[];
  references: JsonRecord[];
  attempts: JsonRecord[];
  milestones: JsonRecord[];
  validations: JsonRecord[];
  activity: JsonRecord[];
  notifications?: JsonRecord[];
  resolution_records?: JsonRecord[];
  reviews?: JsonRecord[];
  assignments?: JsonRecord[];
  owner_rule?: JsonRecord | null;
  factual_result?: FactualResult | null;
  error_analysis_result?: ErrorAnalysisResult | null;
  route_milestones?: JsonRecord[];
  validation_comparisons?: Record<string, { expected: string; observed: string }> | null;
};
export type CaseAction = "comment" | "review_summary" | "start_investigation" | "record_investigation" | "approve_reference" | "analyse" | "review_diagnosis" | "start_work" | "record_correction" | "complete_work" | "record_reprocessing" | "record_validation" | "finish_resolution" | "assign" | "owner_rule" | "block" | "resume" | "priority" | "due_date" | "reopen" | "retry_notification" | "link_identity" | "confirm_order" | "record_route_step";

export async function getScenario(workspaceId: string, token: string, signal: AbortSignal, scenarioId: "MD-01" | "MAP-01" = "MD-01"): Promise<ScenarioInput> {
  const data = await request(`/api/scenarios/${scenarioId}?workspace_id=${encodeURIComponent(workspaceId)}`, token, signal);
  if (!isRecord(data) || !isRecord(data.manifest) || typeof data.original_log !== "string") throw new Error("The scenario input could not be read from the service.");
  return { manifest: data.manifest, original_log: data.original_log, sources: Array.isArray(data.sources) ? data.sources.filter(isRecord) : [], ...(isRecord(data.agent_files) ? { agent_files: data.agent_files } : {}) };
}

export async function createIntake(workspaceId: string, deliveryKey: string, input: ScenarioInput, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const identity = isRecord(input.manifest.identity) ? { ...input.manifest.identity, workspace_id: workspaceId } : { workspace_id: workspaceId };
  const manifest = { ...input.manifest, identity, delivery_key: deliveryKey };
  const agentFiles: JsonRecord | undefined = input.agent_files ? { ...input.agent_files, "manifest.json": manifest } : undefined;
  if (agentFiles && isRecord(input.agent_files?.["source-posting.json"])) {
    const posting = input.agent_files["source-posting.json"];
    agentFiles["source-posting.json"] = { ...posting, ...(isRecord(posting.identity) ? { identity: { ...posting.identity, workspace_id: workspaceId } } : {}) };
  }
  const data = await request("/api/intakes", token, signal, { workspace_id: workspaceId, delivery_key: deliveryKey, manifest, original_log: input.original_log, ...(agentFiles ? { agent_files: agentFiles } : {}), acting_role: "process_owner" });
  if (!isRecord(data)) throw new Error("The intake response could not be read. Refresh cases before trying again.");
  return data;
}

export async function getCaseDetail(caseId: string, workspaceId: string, token: string, signal: AbortSignal): Promise<CaseDetail> {
  const data = await request(`/api/cases/${encodeURIComponent(caseId)}?workspace_id=${encodeURIComponent(workspaceId)}`, token, signal);
  const collections = ["evidence", "runs", "references", "attempts", "milestones", "validations", "activity"] as const;
  if (!isRecord(data) || !isCaseSummary(data.case) || !collections.every(key => Array.isArray(data[key]) && data[key].every(isRecord))) throw new Error("The case detail response could not be read. Refresh or contact the POC administrator.");
  return data as CaseDetail;
}

export async function performCaseAction(caseId: string, workspaceId: string, version: number, action: CaseAction, actingRole: string, payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request(`/api/cases/${encodeURIComponent(caseId)}/actions`, token, signal, { workspace_id: workspaceId, expected_version: version, action, acting_role: actingRole, payload });
  if (!isRecord(data)) throw new Error("The saved action response could not be read. Refresh before making another change.");
  return data;
}

export async function getEvidence(evidenceId: string, workspaceId: string, token: string, signal: AbortSignal): Promise<Blob> {
  const origin = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
  const response = await fetch(`${origin}/api/evidence/${encodeURIComponent(evidenceId)}?workspace_id=${encodeURIComponent(workspaceId)}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.any([signal, AbortSignal.timeout(15_000)]) });
  if (!response.ok) throw new ApiError(response.status === 403 ? "You cannot access this evidence in the selected workspace." : "The private evidence could not be opened. Refresh and try again.", response.status);
  return response.blob();
}

export async function saveProof(caseId: string, workspaceId: string, actingRole: string, file: File, token: string, signal: AbortSignal, provenance?: "synthetic" | "user_supplied"): Promise<JsonRecord> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  const contentType = file.type || (file.name.toLowerCase().endsWith(".json") ? "application/json" : "text/plain");
  const data = await request(`/api/cases/${encodeURIComponent(caseId)}/evidence`, token, signal, { workspace_id: workspaceId, acting_role: actingRole, filename: file.name, content_type: contentType, content_base64: btoa(binary), ...(provenance ? { provenance } : {}) });
  if (!isRecord(data)) throw new Error("The proof response could not be read. Refresh the evidence list before uploading again.");
  return data;
}

export async function simulateProof(caseId: string, workspaceId: string, actingRole: string, kind: "correction" | "reprocessing" | "validation", payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request(`/api/cases/${encodeURIComponent(caseId)}/simulation`, token, signal, { workspace_id: workspaceId, acting_role: actingRole, kind, human_confirmed: true, payload });
  if (!isRecord(data)) throw new Error("The simulation response could not be read. Refresh evidence before trying again.");
  return data;
}

export type CaseFilters = { workflow_version?: string; analysis_status?: string; factual_review_status?: string; q?: string; priority?: string; category?: string; status?: string; diagnosis_status?: string; affected_object?: string };
export type CasePage = { items: CaseSummary[]; total: number; page: number; page_size: number };
export async function getCasePage(workspaceId: string, page: number, filters: CaseFilters, token: string, signal: AbortSignal): Promise<CasePage> {
  const query = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: "25" });
  Object.entries(filters).forEach(([key, data]) => { if (data) query.set(key, data); });
  const data = await request(`/api/cases/page?${query}`, token, signal);
  if (!isRecord(data) || !Array.isArray(data.items) || !data.items.every(isCaseSummary) || typeof data.total !== "number" || typeof data.page !== "number" || typeof data.page_size !== "number") throw new Error("The case page could not be read. Refresh the list.");
  return data as CasePage;
}

export type WorkspaceMember = { user_id: string; roles: string[] };
export async function getMembers(workspaceId: string, token: string, signal: AbortSignal): Promise<WorkspaceMember[]> {
  const data = await request(`/api/workspaces/${encodeURIComponent(workspaceId)}/members`, token, signal);
  if (!Array.isArray(data) || !data.every(item => isRecord(item) && typeof item.user_id === "string" && Array.isArray(item.roles) && item.roles.every(role => typeof role === "string"))) throw new Error("Workspace members could not be read.");
  return data as WorkspaceMember[];
}

export async function controlIntake(caseId: string, workspaceId: string, version: number, action: "complete_identity" | "review_attempt_order" | "link_case", reason: string, payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request(`/api/cases/${encodeURIComponent(caseId)}/intake-controls`, token, signal, { workspace_id: workspaceId, expected_version: version, acting_role: "process_owner", action, reason, payload });
  if (!isRecord(data)) throw new Error("The intake decision response could not be read. Refresh before making another change.");
  return data;
}

export type OverviewFilters = { workflow_version?: string; analysis_status?: string; factual_review_status?: string; category?: string; priority?: string; affected_object?: string; diagnosis_status?: string; status?: string; company_code?: string; target_system?: string };
export type OverviewGroup = { id: string; dimension: string; value: string; count: number; unit: string; drilldown_url: string };
export type Overview = { snapshot: JsonRecord & { id: string; as_of: string; expires_at: string; stale: boolean }; metrics: { unresolved_known_cases: number; provisional_cases: number; attempts: number }; groups: OverviewGroup[]; narrative: JsonRecord & { status: string; text?: string } };
function overview(data: unknown): Overview {
  if (!isRecord(data) || !isRecord(data.snapshot) || typeof data.snapshot.id !== "string" || !isRecord(data.metrics) || !["unresolved_known_cases", "provisional_cases", "attempts"].every(key => typeof (data.metrics as JsonRecord)[key] === "number") || !Array.isArray(data.groups) || !data.groups.every(item => isRecord(item) && typeof item.id === "string" && typeof item.dimension === "string" && typeof item.value === "string" && typeof item.count === "number") || !isRecord(data.narrative)) throw new Error("The overview could not be read. Refresh the workspace.");
  return data as Overview;
}
export async function getOverview(workspaceId: string, filters: OverviewFilters, refresh: boolean, token: string, signal: AbortSignal): Promise<Overview> {
  return overview(await request("/api/overview", token, signal, { workspace_id: workspaceId, filters, refresh }));
}
export async function explainOverview(snapshotId: string, workspaceId: string, token: string, signal: AbortSignal): Promise<Overview> {
  return overview(await request(`/api/overview/${encodeURIComponent(snapshotId)}/explain`, token, signal, { workspace_id: workspaceId }));
}
export type GroupPage = { snapshot: JsonRecord; group: JsonRecord; items: (JsonRecord & { id: string; title: string; priority: string; status: string; version: number; snapshot_version: number; changed_since_snapshot: boolean })[]; total: number; page: number; page_size: number };
export async function getGroupPage(snapshotId: string, groupId: string, workspaceId: string, page: number, token: string, signal: AbortSignal): Promise<GroupPage> {
  const query = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: "25" });
  const data = await request(`/api/overview/${encodeURIComponent(snapshotId)}/groups/${encodeURIComponent(groupId)}?${query}`, token, signal);
  if (!isRecord(data) || !isRecord(data.snapshot) || !isRecord(data.group) || !Array.isArray(data.items) || !data.items.every(item => isRecord(item) && typeof item.id === "string" && typeof item.title === "string") || typeof data.total !== "number") throw new Error("The snapshot case group could not be read.");
  return data as GroupPage;
}

export async function getEvaluationBatches(workspaceId: string, token: string, signal: AbortSignal): Promise<JsonRecord[]> {
  const data = await request(`/api/evaluations?workspace_id=${encodeURIComponent(workspaceId)}`, token, signal);
  const items = Array.isArray(data) ? data : isRecord(data) && Array.isArray(data.batches) ? data.batches : isRecord(data) && Array.isArray(data.items) ? data.items : null;
  if (!items || !items.every(isRecord)) throw new Error("Evaluation batches could not be read.");
  const runs = isRecord(data) && Array.isArray(data.runs) ? data.runs.filter(isRecord) : [];
  return items.map(item => ({ ...item, runs: runs.filter(run => run.evaluation_batch_id === item.id) }));
}
export type EvaluationPage = { batches: JsonRecord[]; runs: JsonRecord[]; stage_calls: JsonRecord[]; total_runs: number; page: number; page_size: number; has_more_runs: boolean; has_more_batches: boolean; scope: string };
export async function getEvaluationPage(workspaceId: string, batchId: string, page: number, token: string, signal: AbortSignal): Promise<EvaluationPage> {
  const query = new URLSearchParams({ workspace_id: workspaceId, page: String(page), page_size: "25", ...(batchId ? { batch_id: batchId } : {}) });
  const data = await request(`/api/evaluations?${query}`, token, signal);
  if (!isRecord(data) || !["batches", "runs", "stage_calls"].every(key => Array.isArray(data[key]) && (data[key] as unknown[]).every(isRecord)) || typeof data.total_runs !== "number" || typeof data.page !== "number" || typeof data.page_size !== "number") throw new Error("The evaluation page could not be read. Refresh the saved results.");
  return data as EvaluationPage;
}
export async function createEvaluationBatch(workspaceId: string, caseIds: string[], repeats: number, reason: string, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request("/api/evaluations", token, signal, { workspace_id: workspaceId, case_ids: caseIds, repeats, reason });
  if (!isRecord(data)) throw new Error("The evaluation request response could not be read. Refresh batches before retrying.");
  return data;
}

export type KnowledgeResult = { items: JsonRecord[]; feedback?: JsonRecord[]; evaluation_attestations?: JsonRecord[]; retrieval_method?: string; publication_policy: JsonRecord };
function knowledgeResult(data: unknown): KnowledgeResult {
  if (!isRecord(data) || !Array.isArray(data.items) || !data.items.every(isRecord) || !isRecord(data.publication_policy)) throw new Error("Knowledge records could not be read.");
  return data as KnowledgeResult;
}
export async function searchKnowledge(workspaceId: string, query: string, token: string, signal: AbortSignal): Promise<KnowledgeResult> {
  return knowledgeResult(await request(`/api/knowledge?${new URLSearchParams({ workspace_id: workspaceId, q: query, limit: "10" })}`, token, signal));
}
export async function getKnowledgeReviews(workspaceId: string, token: string, signal: AbortSignal): Promise<KnowledgeResult> {
  return knowledgeResult(await request(`/api/knowledge/reviews?${new URLSearchParams({ workspace_id: workspaceId })}`, token, signal));
}
export async function saveKnowledgeDraft(workspaceId: string, payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request("/api/knowledge/drafts", token, signal, { ...payload, workspace_id: workspaceId, acting_role: "process_owner" });
  if (!isRecord(data)) throw new Error("The draft response could not be read. Refresh before trying again."); return data;
}
export async function reviewKnowledge(id: string, workspaceId: string, version: number, decision: string, reason: string, evaluationEvidenceId: string, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request(`/api/knowledge/${encodeURIComponent(id)}/review`, token, signal, { workspace_id: workspaceId, acting_role: "process_owner", expected_version: version, decision, reason, ...(evaluationEvidenceId ? { evaluation_evidence_id: evaluationEvidenceId } : {}) });
  if (!isRecord(data)) throw new Error("The review response could not be read. Refresh before trying again."); return data;
}
export async function saveKnowledgeFeedback(workspaceId: string, role: string, payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request("/api/knowledge/feedback", token, signal, { ...payload, workspace_id: workspaceId, acting_role: role });
  if (!isRecord(data)) throw new Error("The feedback response could not be read. Refresh before trying again."); return data;
}
export async function savePublicationPolicy(workspaceId: string, payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request("/api/knowledge/publication-policy", token, signal, { ...payload, workspace_id: workspaceId, acting_role: "process_owner", maximum_critical_failures: 0, require_human_review: true });
  if (!isRecord(data)) throw new Error("The publication criteria response could not be read. Refresh before trying again."); return data;
}
export async function saveEvaluationAttestation(workspaceId: string, payload: JsonRecord, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request("/api/knowledge/evaluation-attestations", token, signal, { ...payload, workspace_id: workspaceId, acting_role: "process_owner", human_reviewed: true });
  if (!isRecord(data)) throw new Error("The evaluation review response could not be read. Refresh before trying again."); return data;
}
export async function reviewFeedback(id: string, workspaceId: string, decision: string, reason: string, token: string, signal: AbortSignal): Promise<JsonRecord> {
  const data = await request(`/api/knowledge/feedback/${encodeURIComponent(id)}/review`, token, signal, { workspace_id: workspaceId, acting_role: "process_owner", decision, reason });
  if (!isRecord(data)) throw new Error("The feedback review response could not be read. Refresh before trying again."); return data;
}

export type LogIntakeSource = { filename: string; content_base64: string };
export async function createLogIntake(workspaceId: string, deliveryKey: string, provenance: "synthetic" | "user_supplied", sources: LogIntakeSource[], token: string, signal: AbortSignal, routingContext?: Record<string, string>): Promise<JsonRecord> {
  const data = await request("/api/intakes/error-analysis", token, signal, { workspace_id: workspaceId, delivery_key: deliveryKey, provenance, sources, acting_role: "process_owner", ...(routingContext && Object.keys(routingContext).length ? { routing_context: routingContext } : {}) });
  if (!isRecord(data) || typeof data.case_id !== "string") throw new Error("The intake response could not be read. Refresh cases before retrying the same delivery.");
  return data;
}
