/** Data transport for the existing workbench. This module contains no UI or route policy. */
export type WorkbenchSession = {
  token: string;
  workspace: { id: string; name: string; synthetic: true; roles: string[] };
};
type RecordValue = Record<string, unknown>;
export type SavedOriginal = {
  evidenceId: string; sourceId: string; sourceVersion: string; filename: string; text: string;
};
export type CitedText = { text: string; citations: { filename: string; lineStart: number; lineEnd: number }[] };
export type SavedBrief = {
  title: CitedText; facts: CitedText[]; context: CitedText[]; evidence: CitedText[];
  hypothesis: CitedText; category: string; route: RecordValue;
  relatedCases: RecordValue[]; limitations: string[];
};
export type SavedWorkbenchCase = {
  case: RecordValue; originals: SavedOriginal[]; brief: SavedBrief | null;
  activity: RecordValue[]; routeMilestones: RecordValue[];
  evidence: RecordValue[]; assignments: RecordValue[]; resolutions: RecordValue[];
  analysisState: string; analysisFailure: string | null;
};

function record(value: unknown): value is RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function records(value: unknown, label: string): RecordValue[] {
  if (!Array.isArray(value) || !value.every(record)) throw new Error(`${label} could not be read.`);
  return value;
}
function text(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} could not be read.`);
  return value;
}
function stringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || !value.every(item => typeof item === "string")) throw new Error(`${label} could not be read.`);
  return value;
}

/** Use only a published result and citations that resolve to the exact saved original. */
export function projectSavedBrief(result: unknown, originals: SavedOriginal[]): SavedBrief | null {
  if (!record(result) || result.outcome !== "completed") return null;
  if (result.result_kind !== "error_analysis" || !record(result.case_content) || !record(result.analysis) || !record(result.extraction)) {
    throw new Error("The published analysis is incomplete. The original remains available.");
  }
  const entries = records(result.extraction.entries, "Extracted evidence");
  const byId = new Map(entries.map(entry => [text(entry.entry_id, "Evidence identity"), entry]));
  if (byId.size !== entries.length) throw new Error("The analysis contains duplicate evidence identities.");
  const cite = (value: unknown): CitedText => {
    if (!record(value)) throw new Error("The cited statement could not be read.");
    const ids = stringList(value.supporting_entry_ids, "Statement citations");
    if (!ids.length) throw new Error("The published statement has no source citation.");
    return { text: text(value.text, "Statement"), citations: ids.map(id => {
      const entry = byId.get(id);
      const source = entry && originals.find(item => item.sourceId === entry.source_id && item.sourceVersion === entry.source_version);
      const span = entry?.source_span;
      if (!entry || !source || !record(span) || !Number.isInteger(span.line_start) || !Number.isInteger(span.line_end)) {
        throw new Error("A published citation cannot be matched to its original.");
      }
      const start = span.line_start as number, end = span.line_end as number;
      // split with line endings retained: extraction raw_text is an exact source slice.
      const lines = source.text.match(/[^\n]*\n|[^\n]+$/g) || [];
      if (start < 1 || end < start || end > lines.length || lines.slice(start - 1, end).join("") !== entry.raw_text) {
        throw new Error("A published citation differs from its saved original.");
      }
      return { filename: source.filename, lineStart: start, lineEnd: end };
    }) };
  };
  const content = result.case_content, analysis = result.analysis;
  if (!record(analysis.route)) throw new Error("The saved route is unavailable.");
  const category = text(analysis.category_id, "Category");
  if (analysis.route.category_id !== category) throw new Error("The saved route does not match its category.");
  return {
    title: cite(content.title),
    facts: records(content.what_happened, "Case facts").map(cite),
    context: records(content.document_context, "Document context").map(cite),
    evidence: records(content.original_log_evidence, "Original evidence").map(cite),
    hypothesis: cite({ text: analysis.cause_hypothesis, supporting_entry_ids: analysis.supporting_entry_ids }),
    category, route: analysis.route,
    relatedCases: records(content.related_cases, "Related cases"),
    limitations: stringList(result.limitations, "Analysis limitations"),
  };
}

export class WorkbenchConnection {
  constructor(readonly origin: string, private readonly fetcher: typeof fetch = fetch) {
    const url = new URL(origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
      throw new Error("Use a plain API origin without credentials or a path.");
    }
    if (url.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
      throw new Error("Remote API connections require HTTPS.");
    }
    this.origin = url.origin;
  }

  private async send(path: string, signal: AbortSignal, session?: WorkbenchSession, body?: unknown): Promise<Response> {
    const response = await this.fetcher(`${this.origin}${path}`, {
      method: body === undefined ? "GET" : "POST", cache: "no-store", redirect: "error",
      headers: { Accept: "application/json", ...(session ? { Authorization: `Bearer ${session.token}` } : {}), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.any([signal, AbortSignal.timeout(body === undefined ? 15_000 : 45_000)]),
    });
    if (!response.ok) {
      // No raw API response or uploaded text is echoed into the UI.
      const message = response.status === 401 ? "The demo session expired. Reconnect before saving."
        : response.status === 403 ? "This persona or workspace cannot perform this action."
        : response.status === 409 ? "The saved record changed. Reload it before retrying."
        : response.status === 422 ? "The supplied data could not be accepted. Check the file or action."
        : "The case service is unavailable. No successful save has been confirmed.";
      throw new Error(message);
    }
    return response;
  }

  async connect(signal: AbortSignal): Promise<WorkbenchSession> {
    const value: unknown = await (await this.send('/api/demo/session', signal, undefined, {})).json();
    if (!record(value) || typeof value.token !== "string" || !value.token.startsWith("local-demo-") || !record(value.workspace) || value.workspace.synthetic !== true) {
      throw new Error("The local synthetic workspace could not be verified.");
    }
    return { token: value.token, workspace: {
      id: text(value.workspace.id, "Workspace"), name: text(value.workspace.name, "Workspace name"),
      synthetic: true, roles: stringList(value.workspace.roles, "Workspace roles"),
    } };
  }

  async listCases(session: WorkbenchSession, signal: AbortSignal): Promise<RecordValue[]> {
    const items: RecordValue[] = [], ids = new Set<string>();
    let expectedTotal: number | undefined;
    for (let page = 1; page <= 100; page++) {
      const query = new URLSearchParams({ workspace_id: session.workspace.id, workflow_version: "error-analysis-v1", page: String(page), page_size: "25" });
      const value: unknown = await (await this.send(`/api/cases/page?${query}`, signal, session)).json();
      if (!record(value) || !Number.isInteger(value.total) || (value.total as number) < 0) throw new Error("The case list could not be read.");
      const total = value.total as number;
      if (expectedTotal !== undefined && total !== expectedTotal) throw new Error("The case list changed while loading. Refresh the list.");
      expectedTotal = total;
      for (const item of records(value.items, "Cases")) {
        const id = text(item.id, "Case identity");
        if (ids.has(id)) throw new Error("The case list changed while loading. Refresh the list.");
        ids.add(id); items.push(item);
      }
      if (items.length === total) return items;
      if (items.length > total || !(value.items as unknown[]).length) throw new Error("The case list is incomplete. Refresh the list.");
    }
    throw new Error("The case list exceeds the supported loading limit. No partial list was accepted.");
  }

  async upload(session: WorkbenchSession, file: File, deliveryKey: string, signal: AbortSignal): Promise<{ caseId: string; version: number; paidDispatchEnabled: boolean }> {
    if (!deliveryKey.trim()) throw new Error("A stable upload receipt is required.");
    if (!/\.(txt|log|csv|tsv)$/i.test(file.name) || file.size === 0 || file.size > 8192) throw new Error("Select a non-empty text log up to 8 KB for the existing analysis service.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const value: unknown = await (await this.send('/api/intakes/error-analysis', signal, session, {
      workspace_id: session.workspace.id, delivery_key: deliveryKey, acting_role: "process_owner",
      provenance: "synthetic", sources: [{ filename: file.name, content_base64: btoa(String.fromCharCode(...bytes)) }],
    })).json();
    if (!record(value) || typeof value.case_id !== "string" || !Number.isInteger(value.version)) throw new Error("The upload receipt could not be read. Retry using the same receipt.");
    return { caseId: value.case_id, version: value.version as number, paidDispatchEnabled: value.paid_dispatch_enabled === true };
  }

  private uploadedFiles = new WeakMap<File, Map<string, RecordValue>>();

  async saveEvidence(session: WorkbenchSession, caseId: string, role: string, file: File, signal: AbortSignal): Promise<RecordValue> {
    const key = `${session.workspace.id}/${caseId}/${role}`;
    const cached = this.uploadedFiles.get(file)?.get(key);
    if (cached) return cached;
    if (!file.size || file.size > 10 * 1024 * 1024) throw new Error("Evidence must be non-empty and at most 10 MB.");
    const extensions: Record<string, string> = { eml: "message/rfc822", txt: "text/plain", log: "text/plain", json: "application/json", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", pdf: "application/pdf" };
    const contentType = extensions[file.name.split('.').pop()?.toLowerCase() || ''] || file.type;
    if (!Object.values(extensions).includes(contentType)) throw new Error("Use PNG, JPEG, PDF, email (.eml), JSON or text evidence.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    const value: unknown = await (await this.send(`/api/cases/${encodeURIComponent(caseId)}/evidence`, signal, session, {
      workspace_id: session.workspace.id, acting_role: role, filename: file.name,
      content_type: contentType, content_base64: btoa(binary), provenance: "synthetic",
    })).json();
    if (!record(value) || typeof value.id !== "string") throw new Error("The evidence receipt could not be read.");
    const cache = this.uploadedFiles.get(file) || new Map<string, RecordValue>();
    cache.set(key, value); this.uploadedFiles.set(file, cache);
    return value;
  }

  async action(session: WorkbenchSession, caseId: string, version: number, role: string, action: string, payload: RecordValue, signal: AbortSignal): Promise<void> {
    const body = { workspace_id: session.workspace.id, expected_version: version, acting_role: role, action, payload };
    const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify({ caseId, ...body }))));
    const requestKey = Array.from(hash, byte => byte.toString(16).padStart(2, "0")).join("");
    await this.send(`/api/cases/${encodeURIComponent(caseId)}/actions`, signal, session, { ...body, request_key: requestKey });
  }

  async download(session: WorkbenchSession, evidenceId: string, signal: AbortSignal): Promise<Blob> {
    const query = new URLSearchParams({ workspace_id: session.workspace.id });
    return (await this.send(`/api/evidence/${encodeURIComponent(evidenceId)}?${query}`, signal, session)).blob();
  }

  async readCase(session: WorkbenchSession, caseId: string, signal: AbortSignal): Promise<SavedWorkbenchCase> {
    const query = new URLSearchParams({ workspace_id: session.workspace.id });
    const value: unknown = await (await this.send(`/api/cases/${encodeURIComponent(caseId)}?${query}`, signal, session)).json();
    if (!record(value) || !record(value.case) || value.case.id !== caseId || value.case.workspace_id !== session.workspace.id || value.case.workflow_version !== "error-analysis-v1") {
      throw new Error("The saved case does not match the selected workspace.");
    }
    const originals: SavedOriginal[] = [];
    for (const source of records(value.evidence, "Case evidence").filter(item => item.kind === "original_log")) {
      if (source.case_id !== caseId || source.workspace_id !== session.workspace.id) throw new Error("An original does not belong to this case.");
      const id = text(source.id, "Original identity");
      const response = await this.send(`/api/evidence/${encodeURIComponent(id)}?${query}`, signal, session);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const sha = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      if (source.byte_size !== bytes.length || source.sha256 !== sha) throw new Error("The original file failed integrity verification.");
      originals.push({ evidenceId: id, sourceId: text(source.source_id, "Source identity"), sourceVersion: text(source.source_version, "Source version"), filename: text(source.filename, "Original filename"), text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes) });
    }
    if (!originals.length) throw new Error("The original log is unavailable. The case is not ready for review.");
    const result = value.error_analysis_result ?? value.case.error_analysis_result;
    const currentResult = value.case.analysis_status === "available" && record(result)
      && result.workspace_id === session.workspace.id && result.case_id === caseId
      && result.run_id === value.case.published_run_id && result.attempt_id === value.case.current_attempt_id
      && String(result.input_revision) === String(value.case.input_revision);
    return {
      case: value.case, originals, brief: currentResult ? projectSavedBrief(result, originals) : null,
      activity: records(value.activity, "Case activity"), routeMilestones: records(value.route_milestones, "Route milestones"),
      evidence: records(value.evidence, "Evidence"), assignments: records(value.assignments ?? [], "Assignments"),
      resolutions: records(value.resolution_records ?? [], "Closure records"),
      analysisState: text(value.case.analysis_status, "Analysis state"),
      analysisFailure: record(result) && typeof result.failure_reason === "string" ? result.failure_reason : null,
    };
  }
}
