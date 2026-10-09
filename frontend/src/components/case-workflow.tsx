"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, controlIntake, getCaseDetail, getEvidence, performCaseAction, saveProof, simulateProof, type CaseAction, type CaseDetail, type CaseSummary, type JsonRecord } from "@/lib/api";
import { formatTime } from "./case-worklist";
import { CaseControls, type IntakeControlHandler } from "./case-controls";
import { CitationPicker } from "./citation-picker";
import { Icon } from "./icon";
import { FactualCaseContent, isFactualCase } from "./factual-case";
import { FactualHumanWorkflow } from "./factual-human-workflow";
import { ErrorAnalysisCaseContent, isErrorAnalysisCase } from "./error-analysis-case";
import { originalLines } from "./intake-panel";

const statusLabels: Record<string, string> = { created: "Created", owner_notified: "Owner notified", in_progress: "In progress", blocked: "Blocked", complete: "Complete", document_reprocessed: "Document reprocessed" };
const diagnosisLabels: Record<string, string> = { ai_supported: "AI-supported", human_confirmed: "Human-confirmed", needs_review: "Needs review" };
const roleLabels: Record<string, string> = { process_owner: "Process owner", mapping_owner: "Mapping owner", master_data_owner: "Master data owner", validator: "Validator", finance_owner: "Finance owner", mdg_process_owner: "MDG Process Owner", data_operations: "Data Operations", cfin_exception_manager: "CFIN Exception Manager" };
const priorityLabels = { P1: "Low", P2: "Medium", P3: "High" };
type Tab = "case" | "evidence" | "actions" | "activity";
function record(value: unknown): JsonRecord { return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {}; }
function value(value: unknown, fallback = "Not recorded"): string { return typeof value === "string" || typeof value === "number" ? String(value) : fallback; }
function localInputTime(instant: string): string {
  const date = new Date(instant); if (Number.isNaN(date.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
function message(error: unknown): string {
  if (error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")) return "The connection was interrupted. Refresh the case to check saved progress before trying again.";
  return error instanceof Error ? error.message : "The request could not be completed. Refresh and try again.";
}

export function EvidenceViewer({ evidence, workspaceId, token, onViewed, lineRange, previewContent }: { evidence: JsonRecord; workspaceId: string; token: string; onViewed?: (id: string) => void; lineRange?: { start: number; end: number; navigationKey?: number }; previewContent?: string }) {
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const evidenceId = value(evidence.id, "");
  const callback = useRef(onViewed); callback.current = onViewed;
  const highlighted = useRef<HTMLSpanElement | null>(null);
  const viewer = useRef<HTMLElement | null>(null);
  useEffect(() => { if (!loading && lineRange) (highlighted.current ?? viewer.current)?.scrollIntoView({ behavior: "instant", block: "center" }); }, [loading, lineRange?.start, lineRange?.end, lineRange?.navigationKey]);
  useEffect(() => {
    const controller = new AbortController(); let objectUrl = "";
    setLoading(true); setContent(""); setUrl(""); setError("");
    const source = previewContent === undefined ? getEvidence(evidenceId, workspaceId, token, controller.signal) : Promise.resolve(new Blob([previewContent], { type: "text/plain" }));
    source.then(async blob => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
      const text = String(evidence.content_type).startsWith("text/") || evidence.content_type === "application/json" ? new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await blob.arrayBuffer()) : "";
      if (controller.signal.aborted) return;
      setContent(text);
      setLoading(false); callback.current?.(evidenceId);
    }).catch(failure => { if (!controller.signal.aborted) { setError(message(failure)); setLoading(false); } });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [evidenceId, workspaceId, token, evidence.content_type, previewContent]);
  return <section ref={viewer} className="evidence-viewer private-evidence" aria-busy={loading}>
    <div className="workflow-section-heading"><h3>{value(evidence.filename, "Saved evidence")}</h3>{url && <a className="button button-quiet" href={url} download={value(evidence.filename, "evidence")}>Download</a>}</div>
    <p className="field-help">Evidence ID {evidenceId} · {value(evidence.source_id)} · version {value(evidence.source_version)} · unchanged private source</p>
    {loading ? <p role="status">Opening private evidence…</p> : error ? <p className="inline-error" role="alert">{error}</p> : content ? <pre className="source-content numbered-source">{originalLines(content).map((line, index) => <span key={index} className={lineRange && index + 1 >= lineRange.start && index + 1 <= lineRange.end ? "source-line highlighted" : "source-line"} ref={lineRange && index + 1 === lineRange.start ? highlighted : undefined}><span className="line-number" aria-hidden="true">{index + 1}</span><span>{line || " "}</span>{"\n"}</span>)}</pre> : url ? <a className="button button-secondary" href={url} target="_blank" rel="noopener noreferrer">Open saved attachment</a> : <p>No readable content was returned.</p>}
  </section>;
}

export function CaseWorkflowPanel({ selected, workspaceId, token, roles, onUpdated, syntheticWorkspace }: { selected: CaseSummary; workspaceId: string; token: string; roles: string[]; syntheticWorkspace?: boolean; onUpdated: (item: CaseSummary) => void }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [tab, setTab] = useState<Tab>("case");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [conflictNotice, setConflictNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedEvidence, setSelectedEvidence] = useState("");
  const mutation = useRef<AbortController | null>(null);
  const updateCallback = useRef(onUpdated); updateCallback.current = onUpdated;
  const caseId = selected.id;
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    getCaseDetail(caseId, workspaceId, token, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      setDetail(data); setLoading(false); updateCallback.current(data.case);
      const params = new URLSearchParams(window.location.search);
      if (params.get("case_id") === data.case.id && params.get("source_id")) {
        const source = data.evidence.find(item => item.source_id === params.get("source_id") && item.source_version === params.get("source_version"));
        if (source) { setSelectedEvidence(String(source.id)); setTab("evidence"); }
      }
    }).catch(failure => { if (!controller.signal.aborted) { setError(message(failure)); setDetail(null); setSelectedEvidence(""); setLoading(false); } });
    return () => controller.abort();
  }, [caseId, workspaceId, token, refresh]);
  useEffect(() => {
    const recheck = () => { if (document.visibilityState === "visible") setRefresh(current => current + 1); };
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", recheck);
    return () => { window.removeEventListener("focus", recheck); document.removeEventListener("visibilitychange", recheck); };
  }, [caseId, workspaceId]);
  const hasActiveRun = detail?.runs.some(run => run.evaluation_only !== true && (run.state === "queued" || run.state === "running")) || false;
  useEffect(() => {
    if (!hasActiveRun || busy) return;
    const interval = window.setInterval(() => setRefresh(current => current + 1), 5000);
    return () => window.clearInterval(interval);
  }, [hasActiveRun, busy]);

  async function act(action: CaseAction, actingRole: string, payload: JsonRecord, confirmation: string) {
    if (!detail || busy || loading) return false;
    const controller = new AbortController(); mutation.current = controller;
    setBusy(true); setError(""); setSuccess(""); setConflictNotice("");
    try {
      await performCaseAction(caseId, workspaceId, detail.case.version, action, actingRole, payload, token, controller.signal);
      if (controller.signal.aborted) return false;
      setSuccess(confirmation); setRefresh(current => current + 1);
      return true;
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(message(failure));
        if (failure instanceof ApiError && [401, 403].includes(failure.status)) { setDetail(null); setSelectedEvidence(""); }
        if (failure instanceof ApiError && failure.status === 409) { setConflictNotice("This case changed. Review its current version and confirm the action again."); setRefresh(current => current + 1); }
      }
      return false;
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  const intakeAction: IntakeControlHandler = async (action, reason, payload) => {
    if (!detail || busy || loading) return false;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError(""); setSuccess("");
    try {
      const result = await controlIntake(caseId, workspaceId, detail.case.version, action, reason, payload, token, controller.signal);
      if (controller.signal.aborted) return false;
      setSuccess(typeof result.next_step === "string" ? `Intake decision saved. ${result.next_step}` : "Intake decision saved. Refreshing the current case."); setRefresh(current => current + 1); return true;
    } catch (failure) {
      if (!controller.signal.aborted) { setError(message(failure)); if (failure instanceof ApiError && [401, 403].includes(failure.status)) setDetail(null); if (failure instanceof ApiError && failure.status === 409) setRefresh(current => current + 1); }
      return false;
    } finally { if (!controller.signal.aborted) setBusy(false); }
  };

  const current: CaseSummary & JsonRecord = detail?.case || { ...selected };
  const activeAttempt = detail?.attempts.find(attempt => attempt.id === current.current_attempt_id);
  const evidence = detail?.evidence.find(item => item.id === selectedEvidence);
  const latestRun = detail?.runs.find(run => run.id === current.published_run_id) || detail?.runs[0];
  const factual = detail ? isFactualCase(detail) : current.workflow_version === "log-only-v1";
  const errorAnalysis = detail ? isErrorAnalysisCase(detail) : current.workflow_version === "error-analysis-v1";
  const tabs: Tab[] = ["case", "evidence", "actions", "activity"];
  return <>
    <div className="detail-heading"><div className="detail-eyebrow"><span><Icon name="document" size={16} />Private case</span><button type="button" className="icon-button" onClick={() => setRefresh(current => current + 1)} aria-label="Refresh case detail" disabled={loading || busy}><Icon name="refresh" size={15} /></button></div><h2>{current.title}</h2><p>{errorAnalysis ? "Error Analysis case · governed human route" : factual ? `Factual case · ${value(current.factual_review_status, "Pending review").replaceAll("_", " ")}` : `Legacy diagnosis · ${diagnosisLabels[current.diagnosis_status] || current.diagnosis_status}`}</p><div className="detail-badges"><span className={`work-status status-${current.status}`}><span />{statusLabels[current.status] || current.status}</span><span className="priority-inline">{current.priority} · {priorityLabels[current.priority]}</span></div></div>
    <div className="detail-tabs workflow-tabs" role="tablist" aria-label="Private case information">{tabs.map(item => <button type="button" role="tab" key={item} id={`workflow-tab-${item}`} aria-selected={tab === item} aria-controls="workflow-content" tabIndex={tab === item ? 0 : -1} onClick={() => setTab(item)} onKeyDown={event => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); const next = tabs[(tabs.indexOf(item) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]; setTab(next); document.getElementById(`workflow-tab-${next}`)?.focus(); } }}>{item === "case" ? "Case" : item === "evidence" ? "Evidence" : item === "actions" ? "Actions" : "Activity"}</button>)}</div>
    <div className="detail-content workflow-content" id="workflow-content" role="tabpanel" aria-labelledby={`workflow-tab-${tab}`} aria-busy={loading || busy}>
      {error && <p className="inline-error" role="alert">{error}</p>}{conflictNotice && <p className="workflow-notice" role="status">{conflictNotice}</p>}{success && <p className="workflow-success" role="status"><Icon name="check" size={15} />{success}</p>}
      {loading && !detail ? <p className="section-intro" role="status">Loading private case details…</p> : !detail ? <p className="section-intro">Refresh to load the latest saved case and its evidence.</p> : <>
        {hasActiveRun && <div className="workflow-notice" role="status"><strong>{detail.runs.some(run => run.state === "running") ? "Analysis running" : "Analysis queued"}</strong><p>The saved run is refreshed automatically. Human milestones remain separate.</p></div>}
        {tab === "case" ? errorAnalysis ? <ErrorAnalysisCaseContent detail={detail} /> : factual ? <FactualCaseContent key={detail.case.id} detail={detail} workspaceId={workspaceId} token={token} /> : <>
          <section className="detail-section"><h3>Diagnosis and review</h3><p className="detail-description">{current.description || "Analysis has not supplied a description yet."}</p><dl className="context-grid"><div><dt>Analysis</dt><dd>{value(current.analysis_status, "Not recorded").replaceAll("_", " ")}</dd></div><div><dt>Current attempt</dt><dd>{value(activeAttempt?.attempt_key, "Not selected")}</dd></div><div><dt>Posting validation</dt><dd>{value(activeAttempt?.validation_status, "Pending")}</dd></div><div><dt>Resolution</dt><dd>{current.resolved === true ? "Resolved" : "Not resolved"}</dd></div></dl></section>
          <section className="detail-section"><h3>Document context</h3><dl className="context-grid">{([ ["Source company", current.source_company_code], ["Document number", current.document_number], ["Source system", current.source_system], ["Target system", current.target_system], ["Due date", formatTime(current.due_at)], ["Record version", current.version] ] as [string, unknown][]).map(([label, data]) => <div key={label}><dt>{label}</dt><dd>{value(data)}</dd></div>)}</dl></section>
          <section className="detail-section"><h3>Saved analysis</h3>{latestRun ? <><p className="section-intro">Run {value(latestRun.state)} · {formatTime(typeof latestRun.created_at === "string" ? latestRun.created_at : null)}</p>{Boolean(latestRun.error_code) && <p className="workflow-notice">{value(latestRun.error_code)}</p>}{latestRun.output ? <details className="analysis-output"><summary>Inspect structured findings and citations</summary><pre className="source-content">{JSON.stringify(latestRun.output, null, 2)}</pre></details> : <p className="field-help">No model output has been saved for this run.</p>}{Boolean(latestRun.output) && <div className="citation-navigation">{savedCitations(latestRun.output).map(citation => { const source = detail.evidence.find(item => item.source_id === citation.source_id && item.source_version === citation.source_version); return source ? <button className="button button-quiet" type="button" key={JSON.stringify(citation)} onClick={() => { setSelectedEvidence(value(source.id)); setTab("evidence"); }}>{value(citation.source_id)} · v{value(citation.source_version)} · {citation.record_id ? value(citation.record_id) : `lines ${value(citation.line_start)}–${value(citation.line_end)}`}</button> : null; })}</div>}</> : <p className="section-intro">No analysis run has been saved. Review reference versions in Actions before requesting an eligible brief.</p>}</section>
          <section className="detail-section"><h3>Human progress</h3>{detail.milestones.length ? <ul className="source-file-list">{detail.milestones.map((item, index) => <li key={value(item.id, String(index))}>{value(item.kind).replaceAll("_", " ")}<span>{formatTime(typeof item.action_at === "string" ? item.action_at : null)}</span></li>)}</ul> : <p className="section-intro">No human milestone has been recorded.</p>}{Array.isArray(detail.resolution_records) && detail.resolution_records.length > 0 && <details className="analysis-output"><summary>Resolution record IDs and reuse state</summary><pre className="source-content">{JSON.stringify(detail.resolution_records, null, 2)}</pre></details>}{Array.isArray(detail.reviews) && detail.reviews.length > 0 && <details className="analysis-output"><summary>Saved human diagnosis reviews</summary><pre className="source-content">{JSON.stringify(detail.reviews, null, 2)}</pre></details>}</section>
        </> : tab === "evidence" ? <>
          <p className="section-intro">Open the preserved original, references or human proof. Access is checked for this workspace.</p>
          <div className="evidence-list">{detail.evidence.map(item => <button key={value(item.id)} type="button" className={item.id === selectedEvidence ? "evidence-item selected" : "evidence-item"} onClick={() => setSelectedEvidence(value(item.id))} aria-expanded={item.id === selectedEvidence}><Icon name="document" size={18} /><span><strong>{value(item.filename)}</strong><small>{value(item.kind).replaceAll("_", " ")} · version {value(item.source_version)}</small></span><Icon name="chevron" size={14} /></button>)}</div>
          {!detail.evidence.length && <p className="section-intro">No evidence is registered for this case.</p>}{evidence && <EvidenceViewer key={value(evidence.id)} evidence={evidence} workspaceId={workspaceId} token={token} lineRange={(() => { const query = new URLSearchParams(window.location.search); const start = Number(query.get("line_start")); const end = Number(query.get("line_end")); return query.get("source_id") === evidence.source_id && query.get("source_version") === evidence.source_version && start > 0 && end >= start ? { start, end } : undefined; })()} />}
        </> : tab === "actions" ? <>
          <p className="section-intro">Actions record your signed-in account and acting role. No approval or human proof is completed automatically.</p>
          {!factual && !errorAnalysis && <ReferenceReview detail={detail} roles={roles} workspaceId={workspaceId} token={token} disabled={busy || loading} onAction={act} />}
          {errorAnalysis && <ErrorRouteWorkflow detail={detail} roles={roles} workspaceId={workspaceId} token={token} disabled={busy || loading} onAction={act} onProofBusy={setBusy} onProofSaved={() => setRefresh(current => current + 1)} />}
          {roles.includes("process_owner") && !errorAnalysis && <section className="workflow-action"><h3>Analysis</h3><p>{factual ? "Read all originals, select essential evidence and prepare a factual summary. Any available reviewed history is shown separately." : "Queue the legacy diagnostic analysis and its conditional brief."}</p><button className="button button-secondary" type="button" disabled={busy || loading || hasActiveRun} onClick={() => act("analyse", "process_owner", {}, "Analysis request saved.")}>{hasActiveRun ? "Analysis already queued" : "Request analysis"}</button></section>}
          {!errorAnalysis && <CaseControls detail={detail} roles={roles} workspaceId={workspaceId} token={token} disabled={busy || loading} onAction={act} onIntakeControl={intakeAction} />}
          {!errorAnalysis && (factual ? <FactualHumanWorkflow syntheticWorkspace={syntheticWorkspace} detail={detail} roles={roles} workspaceId={workspaceId} token={token} disabled={busy || loading} onAction={act} onProofBusy={setBusy} onProofSaved={() => setRefresh(current => current + 1)} /> : <HumanWorkflow detail={detail} roles={roles} workspaceId={workspaceId} token={token} disabled={busy || loading} onAction={act} onProofBusy={setBusy} onProofSaved={() => setRefresh(current => current + 1)} />)}
        </> : <>
          <p className="section-intro">Saved case activity, including actual account and acting role.</p>{detail.activity.length ? <ol className="activity-list">{detail.activity.map((event, index) => <li key={value(event.id, String(index))}><span className="activity-dot" /><time>{formatTime(typeof event.created_at === "string" ? event.created_at : null)}</time><strong>{value(event.event_type).replaceAll("_", " ")}</strong><p>{value(event.reason, "")}<span className="activity-actor">{roleLabels[value(event.acting_role)] || value(event.acting_role)} · {value(event.actor_id, "System event")}</span></p></li>)}</ol> : <p className="section-intro">No activity has been recorded.</p>}
        </>}
      </>}
    </div>
  </>;
}

type ActionHandler = (action: CaseAction, role: string, payload: JsonRecord, confirmation: string) => Promise<boolean>;
function ReferenceReview({ detail, roles, workspaceId, token, disabled, onAction }: { detail: CaseDetail; roles: string[]; workspaceId: string; token: string; disabled: boolean; onAction: ActionHandler }) {
  const [selectedId, setSelectedId] = useState("");
  const [viewedId, setViewedId] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const references = detail.references;
  const selected = references.find(item => item.evidence_id === selectedId);
  const evidence = detail.evidence.find(item => item.id === selectedId);
  const role = selected?.reference_kind === "mapping" || selected?.kind === "reference" ? "mapping_owner" : "process_owner";
  useEffect(() => { setConfirmed(false); }, [detail.case.version, selected?.review_version]);
  async function approve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected || !confirmed || viewedId !== selectedId) return;
    const saved = await onAction("approve_reference", role, { evidence_id: selected.evidence_id, expected_review_version: selected.review_version, decision: "approved", reason: reason.trim() }, "Reference approval saved for the selected version.");
    if (saved) { setConfirmed(false); setReason(""); }
  }
  return <section className="workflow-action"><h3>Review references</h3><p>Inspect the exact preserved source before approving its synthetic scope. An approved reference does not confirm the diagnosis or authorise a target change.</p>
    <div className="reference-list">{references.map(item => <button type="button" className={selectedId === item.evidence_id ? "reference-choice selected" : "reference-choice"} key={value(item.evidence_id)} disabled={disabled} onClick={() => { setSelectedId(value(item.evidence_id)); setViewedId(""); setConfirmed(false); setReason(""); }}><span>{value(item.source_id)}<small>Version {value(item.source_version)}</small></span><span>{value(item.reuse_status, "pending_review").replaceAll("_", " ")}</span></button>)}</div>
    {!references.length && <p className="field-help">No governed references are registered.</p>}
    {selected && evidence && <><EvidenceViewer key={value(evidence.id)} evidence={evidence} workspaceId={workspaceId} token={token} onViewed={setViewedId} /><details className="reference-scope"><summary>Declared scope</summary><pre className="source-content">{JSON.stringify(selected.scope, null, 2)}</pre></details>{selected.reuse_status === "approved" ? <p className="workflow-notice">This version has an approval record. The original evidence remains unchanged.</p> : !roles.includes(role) ? <p className="workflow-notice">A {roleLabels[role].toLowerCase()} must review and approve this reference.</p> : <form className="workflow-form" onSubmit={approve}><label>Review reason<textarea required value={reason} onChange={event => { setReason(event.target.value); setConfirmed(false); }} rows={3} maxLength={2000} disabled={disabled} /></label><label className="attestation"><input type="checkbox" required checked={confirmed} disabled={disabled || viewedId !== selectedId} onChange={event => setConfirmed(event.target.checked)} /><span>I have reviewed this exact version and approve the stated synthetic scope as {roleLabels[role].toLowerCase()}.</span></label><button className="button button-primary" type="submit" disabled={disabled || !confirmed || viewedId !== selectedId || selected.review_version === undefined}>Approve reference version</button></form>}</>}
  </section>;
}

type HumanAction = "review_diagnosis" | "start_work" | "record_correction" | "complete_work" | "record_reprocessing" | "record_validation" | "finish_resolution";
const humanActions: { value: HumanAction; label: string; roles: string[] }[] = [
  { value: "review_diagnosis", label: "Review diagnosis", roles: ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"] },
  { value: "start_work", label: "Start work", roles: ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"] },
  { value: "record_correction", label: "Record correction and proof", roles: ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"] },
  { value: "complete_work", label: "Mark work complete", roles: ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"] },
  { value: "record_reprocessing", label: "Record successful reprocessing", roles: ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"] },
  { value: "record_validation", label: "Validate target posting", roles: ["validator"] },
  { value: "finish_resolution", label: "Finish resolution record", roles: ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"] },
];
const checkDimensions = [ ["amount_currency", "Amounts and currency"], ["company", "Company code"], ["accounts", "Target accounts"], ["source_target_reference", "Source-to-target reference"] ] as const;
type Check = { dimension: string; result: string; expected: string; observed: string; reason: string };
function initialChecks(): Check[] { return checkDimensions.map(([dimension]) => ({ dimension, result: "", expected: "", observed: "", reason: "" })); }
function savedCitations(output: unknown): JsonRecord[] {
  const results = new Map<string, JsonRecord>();
  function visit(node: unknown, depth: number) {
    if (depth > 20 || !node || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(child => visit(child, depth + 1)); return; }
    const item = record(node);
    if (typeof item.source_id === "string" && typeof item.source_version === "string" && (typeof item.record_id === "string" || (typeof item.line_start === "number" && typeof item.line_end === "number"))) {
      const citation = { source_id: item.source_id, source_version: item.source_version, attempt_id: item.attempt_id ?? null, ...(typeof item.record_id === "string" ? { record_id: item.record_id } : { line_start: item.line_start, line_end: item.line_end }) };
      results.set(JSON.stringify(citation), citation);
    }
    Object.values(item).forEach(child => visit(child, depth + 1));
  }
  visit(output, 0); return [...results.values()];
}

function ErrorRouteWorkflow({ detail, roles, workspaceId, token, disabled, onAction, onProofBusy, onProofSaved }: { detail: CaseDetail; roles: string[]; workspaceId: string; token: string; disabled: boolean; onAction: ActionHandler; onProofBusy: (busy: boolean) => void; onProofSaved: () => void }) {
  const result = record(detail.error_analysis_result ?? detail.case.error_analysis_result);
  const analysis = record(result.analysis);
  const route = record(analysis.route);
  const steps = Array.isArray(route.steps) ? route.steps.map(record) : [];
  const completed = detail.route_milestones?.length || 0;
  const step = steps[completed];
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState("approved");
  const [file, setFile] = useState<File | null>(null);
  const [proofId, setProofId] = useState("");
  const [uploadError, setUploadError] = useState("");
  const routeClosed = detail.case.route_state === "completed" || detail.case.route_state === "escalated";
  const requiredRole = value(step?.required_role, "");
  const approval = step?.requires_approval === true;
  const evidenceRequired = step?.requires_evidence === true;
  const mayAct = Boolean(step) && roles.includes(requiredRole);
  async function uploadProof() {
    if (!file || !mayAct) return;
    const controller = new AbortController(); onProofBusy(true); setUploadError("");
    try {
      const saved = await saveProof(String(detail.case.id), workspaceId, requiredRole, file, token, controller.signal, "user_supplied");
      setProofId(value(saved.id, "")); setFile(null); onProofSaved();
    } catch (failure) { setUploadError(message(failure)); }
    finally { onProofBusy(false); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!step || !mayAct || (evidenceRequired && !proofId)) return;
    const saved = await onAction("record_route_step", requiredRole, { note: note.trim(), ...(approval ? { decision } : {}), evidence_ids: proofId ? [proofId] : [] }, `Saved route step: ${value(step.description)}.`);
    if (saved) { setNote(""); setProofId(""); setDecision("approved"); }
  }
  return <section className="workflow-action">
    <h3>Governed route activity</h3>
    <p>Record the next case-log step after completing it. The service enforces the configured role, order, approval gate and required evidence.</p>
    {detail.route_milestones?.length ? <ul className="source-file-list">{detail.route_milestones.map(item => <li key={value(item.id)}>{value(item.step_id).replaceAll("_", " ")} · {value(item.decision)}</li>)}</ul> : <p className="field-help">No route activity has been recorded.</p>}
    {routeClosed ? <p className="workflow-notice">This route is {value(detail.case.route_state)}. The configured escalation owner must decide any follow-up.</p> : !step ? <p className="workflow-success">All configured route steps are recorded.</p> : <>
      <h4>Next: {value(step.description)}</h4>
      <p className="field-help">Required role: {roleLabels[requiredRole] || requiredRole}</p>
      {!mayAct ? <p className="workflow-notice">Switch to a signed-in account with the required role to record this step.</p> : <form className="workflow-form" onSubmit={submit}>
        <label>Case-log note<textarea required rows={3} maxLength={10000} value={note} onChange={event => setNote(event.target.value)} disabled={disabled} placeholder="Record the completed action, scope, owner discussion or posting result." /></label>
        {approval && <label>Decision<select value={decision} disabled={disabled} onChange={event => setDecision(event.target.value)}><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label>}
        {evidenceRequired && <>
          <label>Evidence file<input type="file" required={!proofId} disabled={disabled || Boolean(proofId)} onChange={event => setFile(event.target.files?.[0] || null)} /></label>
          {proofId ? <p className="workflow-success">Saved proof {proofId}</p> : <button type="button" className="button button-secondary" disabled={disabled || !file} onClick={uploadProof}>Save evidence before recording step</button>}
          {uploadError && <p className="inline-error" role="alert">{uploadError}</p>}
        </>}
        <button type="submit" className="button button-primary" disabled={disabled || !note.trim() || (evidenceRequired && !proofId)}>Record route step</button>
      </form>}
    </>}
  </section>;
}

function HumanWorkflow({ detail, roles, workspaceId, token, disabled, onAction, onProofSaved, onProofBusy }: { detail: CaseDetail; roles: string[]; workspaceId: string; token: string; disabled: boolean; onAction: ActionHandler; onProofSaved: () => void; onProofBusy: (busy: boolean) => void }) {
  const [selectedAction, setSelectedAction] = useState<HumanAction>("review_diagnosis");
  const [actingRole, setActingRole] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [decision, setDecision] = useState("Accepted");
  const [causeConfirmed, setCauseConfirmed] = useState(false);
  const [humanConfirmed, setHumanConfirmed] = useState(false);
  const [authority, setAuthority] = useState(false);
  const [correctionApplicable, setCorrectionApplicable] = useState(false);
  const [proofIds, setProofIds] = useState<string[]>([]);
  const [viewedProofIds, setViewedProofIds] = useState<string[]>([]);
  const [proofBusy, setProofBusy] = useState(false);
  const [checks, setChecks] = useState<Check[]>(initialChecks);
  const [validationStatus, setValidationStatus] = useState("");
  const [causeStatus, setCauseStatus] = useState("not_confirmed");
  const [citationKeys, setCitationKeys] = useState<string[]>([]);
  const [addedCitations, setAddedCitations] = useState<JsonRecord[]>([]);
  const [localError, setLocalError] = useState("");
  const latestFailed = detail.runs.find(run => run.id === detail.case.requested_run_id && run.state === "failed" && run.attempt_id === detail.case.current_attempt_id && run.input_revision === detail.case.input_revision && run.snapshot);
  const published = detail.runs.find(run => run.id === detail.case.published_run_id && run.output && run.state === "succeeded");
  const reviewableRuns = latestFailed ? [latestFailed] : published ? [published] : [];
  const currentAttempt = detail.attempts.find(item => item.id === detail.case.current_attempt_id);
  function available(action: HumanAction) {
    const status = detail.case.status;
    if (action === "review_diagnosis") return reviewableRuns.length > 0;
    if (action === "start_work") return ["created", "owner_notified"].includes(status);
    if (action === "record_correction") return status === "in_progress";
    if (action === "complete_work") return status === "in_progress" && detail.milestones.some(item => item.kind === "correction" && item.attempt_id === detail.case.current_attempt_id && item.work_cycle === detail.case.work_cycle);
    if (action === "record_reprocessing") return status === "complete";
    if (action === "record_validation") return status === "document_reprocessed";
    return status === "document_reprocessed" && currentAttempt?.validation_status === "passed";
  }
  const permitted = humanActions.filter(item => item.roles.some(role => roles.includes(role)));
  const nextAction: HumanAction = detail.case.status === "in_progress" ? available("complete_work") ? "complete_work" : "record_correction" : detail.case.status === "complete" ? "record_reprocessing" : detail.case.status === "document_reprocessed" ? available("finish_resolution") ? "finish_resolution" : "record_validation" : detail.case.diagnosis_status === "needs_review" && reviewableRuns.length ? "review_diagnosis" : "start_work";
  const action = permitted.find(item => item.value === selectedAction && available(item.value))?.value || permitted.find(item => item.value === nextAction && available(item.value))?.value || permitted.find(item => available(item.value))?.value;
  const allowedRoles = humanActions.find(item => item.value === action)?.roles.filter(role => roles.includes(role)) || [];
  const role = allowedRoles.includes(actingRole) ? actingRole : allowedRoles[0] || "";
  const needsProof = action === "record_correction" || action === "record_reprocessing" || action === "record_validation" || action === "finish_resolution";
  const proofReady = proofIds.length > 0 && proofIds.every(id => viewedProofIds.includes(id));
  const citations = [...new Map([...savedCitations(record(reviewableRuns[0]?.output).diagnosis), ...savedCitations(detail.reviews), ...addedCitations].map(citation => [JSON.stringify(citation), citation])).values()];
  const blocked = disabled || proofBusy;
  const simulationKind = action === "record_correction" ? "correction" : action === "record_reprocessing" ? "reprocessing" : action === "record_validation" ? "validation" : undefined;
  const processingDate = new Date(fields.processing_at || "");
  const simulationReady = simulationKind === "correction" ? Boolean(fields.explanation?.trim()) : simulationKind === "reprocessing" ? Boolean(fields.attempt_key?.trim() && fields.target_document_reference?.trim() && Number(fields.processing_order) > 0 && !Number.isNaN(processingDate.getTime())) : simulationKind === "validation" ? Boolean(validationStatus && checks.every(check => check.result && check.expected.trim() && check.observed.trim() && (check.result === "passed" || check.reason.trim()))) : false;
  const simulationPayload: JsonRecord = simulationKind === "correction" ? { explanation: fields.explanation } : simulationKind === "reprocessing" ? { attempt_key: fields.attempt_key, processing_order: Number(fields.processing_order), processing_at: Number.isNaN(processingDate.getTime()) ? "" : processingDate.toISOString(), target_document_reference: fields.target_document_reference } : { checks: checks.map(check => ({ ...check, reason: check.reason.trim() || null })), status: validationStatus };
  const comparisonFingerprint = JSON.stringify(detail.validation_comparisons);
  useEffect(() => { setHumanConfirmed(false); setCauseConfirmed(false); setAuthority(false); setCorrectionApplicable(false); }, [JSON.stringify(fields), decision, validationStatus, JSON.stringify(checks), causeStatus]);

  useEffect(() => {
    setFields({ target_system: value(detail.case.target_system, ""), target_object: value(record(detail.case.business_context).target_account, ""), company_code: value(detail.case.source_company_code, ""), run_id: value(reviewableRuns[0]?.id, "") });
    setHumanConfirmed(false); setAuthority(false); setCorrectionApplicable(false); setCauseConfirmed(false); setProofIds([]); setViewedProofIds([]); setChecks(initialChecks()); setValidationStatus(""); setCitationKeys([]); setAddedCitations([]); setCauseStatus("not_confirmed"); setLocalError("");
  // An action change starts a fresh human attestation. Actual times are never prefilled.
  }, [action, reviewableRuns[0]?.id]);
  useEffect(() => { setHumanConfirmed(false); setCauseConfirmed(false); setAuthority(false); setCorrectionApplicable(false); }, [detail.case.version]);
  useEffect(() => { if (!reviewableRuns[0]?.output) setDecision("Insufficient"); }, [reviewableRuns[0]?.id]);
  useEffect(() => {
    if (action !== "record_validation") return;
    setChecks(initialChecks().map(check => ({ ...check, expected: detail.validation_comparisons?.[check.dimension]?.expected || "", observed: detail.validation_comparisons?.[check.dimension]?.observed || "" })));
  }, [action, comparisonFingerprint]);

  function field(name: string, label: string, options: { textarea?: boolean; required?: boolean; type?: string; placeholder?: string; min?: number } = {}) {
    const props = { name, value: fields[name] || "", onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setFields(previous => ({ ...previous, [name]: event.target.value })), required: options.required !== false, disabled: blocked, placeholder: options.placeholder, maxLength: 5000 };
    return <label key={name}>{label}{options.textarea ? <textarea {...props} rows={3} /> : <input {...props} type={options.type || "text"} min={options.min} step={options.type === "number" || options.type === "datetime-local" ? 1 : undefined} />}</label>;
  }
  function iso(name: string) { const date = new Date(fields[name]); if (Number.isNaN(date.getTime())) throw new Error("Enter a valid action or processing time."); return date.toISOString(); }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!action || blocked || (needsProof && (!humanConfirmed || !proofReady))) return;
    setLocalError(""); let payload: JsonRecord;
    try {
      const human = needsProof ? { proof_ids: proofIds, human_confirmed: humanConfirmed } : {};
      if (action === "review_diagnosis") {
        const selectedCitations = citations.filter(citation => citationKeys.includes(JSON.stringify(citation)));
        if (decision === "Corrected" && causeConfirmed && !selectedCitations.length) throw new Error("Select the saved evidence that supports your corrected cause.");
        payload = { run_id: fields.run_id || reviewableRuns[0]?.id, decision, cause_confirmed: causeConfirmed, reason: fields.reason || "", ...(decision === "Corrected" ? { findings: { cause_label: fields.cause_label, explanation: fields.explanation, gaps: (fields.gaps || "").split("\n").map(gap => gap.trim()).filter(Boolean), citations: selectedCitations }, cause_evidence: selectedCitations } : {}) };
      }
      else if (action === "start_work") payload = { reason: fields.reason, target_change_authority: authority, approved_attributes: fields.approved_attributes };
      else if (action === "record_correction") payload = { ...human, explanation: fields.explanation, target_system: fields.target_system, target_object: fields.target_object, occurred_at: iso("occurred_at") };
      else if (action === "complete_work") payload = { reason: fields.reason };
      else if (action === "record_reprocessing") payload = { ...human, attempt_key: fields.attempt_key, processing_order: Number(fields.processing_order), processing_at: iso("processing_at"), occurred_at: iso("occurred_at"), target_document_reference: fields.target_document_reference, correction_applicable: correctionApplicable };
      else if (action === "record_validation") {
        if (validationStatus === "failed" && !checks.some(check => check.result === "failed")) throw new Error("Failed validation needs at least one failed comparison.");
        if (validationStatus === "passed" && checks.some(check => check.result === "failed")) throw new Error("Passed validation cannot contain a failed comparison.");
        payload = { ...human, status: validationStatus, checks: checks.map(check => ({ ...check, ...(check.reason.trim() ? { reason: check.reason.trim() } : { reason: null }) })), occurred_at: iso("occurred_at") };
      } else {
        if (causeStatus === "confirmed" && !citationKeys.length) throw new Error("Select the saved citations that support the confirmed cause.");
        payload = { ...human, cause_status: causeStatus, cause: causeStatus === "confirmed" ? fields.confirmed_cause : null, cause_evidence: causeStatus === "confirmed" ? citations.filter(citation => citationKeys.includes(JSON.stringify(citation))) : [], unresolved_gaps: causeStatus === "not_confirmed" ? (fields.unresolved_gaps || "").split("\n").map(gap => gap.trim()).filter(Boolean) : [], correction_or_no_change: fields.correction_or_no_change, scope: { target_system: fields.target_system, target_object: fields.target_object, company_code: fields.company_code, reuse_limitations: fields.reuse_limitations }, outcome: fields.outcome, occurred_at: iso("occurred_at") };
      }
      const saved = await onAction(action, role, payload, `${humanActions.find(item => item.value === action)?.label || "Human action"} saved.`);
      if (saved) { setHumanConfirmed(false); setCauseConfirmed(false); setAuthority(false); setCorrectionApplicable(false); }
    } catch (failure) { setLocalError(message(failure)); }
  }

  return <section className="workflow-action"><h3>Human resolution</h3><p>Current work status: {statusLabels[detail.case.status] || detail.case.status}. Stored proof and your confirmation are required for milestones.</p>
    {!permitted.length ? <p className="workflow-notice">Your current role can inspect this case. A configured owner and validator perform the human resolution steps.</p> : !action ? <p className="workflow-notice">No action is available for your role at the current milestone. Refresh after the responsible owner or validator records the next step.</p> : <>
      <div className="workflow-form"><label>Human action<select value={action} disabled={blocked} onChange={event => setSelectedAction(event.target.value as HumanAction)}>{permitted.map(item => <option value={item.value} key={item.value} disabled={!available(item.value)}>{item.label}{!available(item.value) ? " (not available yet)" : ""}</option>)}</select></label></div>
      <form className="workflow-form" onSubmit={submit}>
        {localError && <p className="inline-error" role="alert">{localError}</p>}
        <label>Acting role<select value={role} disabled={blocked} onChange={event => { setActingRole(event.target.value); setHumanConfirmed(false); setAuthority(false); setCauseConfirmed(false); }}>{allowedRoles.map(item => <option value={item} key={item}>{roleLabels[item]}</option>)}</select></label>
        {action === "review_diagnosis" ? <>
          <label>Saved analysis run<select value={fields.run_id || value(reviewableRuns[0]?.id, "")} disabled={blocked} onChange={event => setFields(previous => ({ ...previous, run_id: event.target.value }))}>{reviewableRuns.map(run => <option key={value(run.id)} value={value(run.id)}>{formatTime(typeof run.created_at === "string" ? run.created_at : null)} · {value(run.state)}</option>)}</select></label>
          <label>Review decision<select value={decision} disabled={blocked} onChange={event => setDecision(event.target.value)}><option value="Accepted" disabled={!reviewableRuns[0]?.output}>Accepted</option><option value="Corrected">Corrected</option><option value="Insufficient">Insufficient</option></select></label>
          {field("reason", "Review findings or reason", { textarea: true, required: decision !== "Accepted" })}
          {decision === "Corrected" && <>{field("cause_label", "Corrected cause label")}{field("explanation", "Corrected findings", { textarea: true })}{field("gaps", "Remaining gaps (one per line)", { textarea: true, required: false })}<fieldset className="citation-choices"><legend>Evidence for corrected findings</legend>{citations.map(citation => { const key = JSON.stringify(citation); return <label className="attestation" key={key}><input type="checkbox" disabled={blocked} checked={citationKeys.includes(key)} onChange={event => { setCitationKeys(previous => event.target.checked ? [...previous, key] : previous.filter(item => item !== key)); setCauseConfirmed(false); }} /><span>{value(citation.source_id)} · version {value(citation.source_version)} · {citation.record_id ? value(citation.record_id) : `lines ${value(citation.line_start)}–${value(citation.line_end)}`}</span></label>; })}{!citations.length && <p className="field-help">No saved citations are available. Record the gaps and leave the cause unconfirmed.</p>}</fieldset>{reviewableRuns[0] && <CitationPicker detail={detail} run={reviewableRuns[0]} workspaceId={workspaceId} token={token} disabled={blocked} onAdd={citation => { setAddedCitations(previous => [...previous, citation]); setCitationKeys(previous => [...new Set([...previous, JSON.stringify(citation)])]); setCauseConfirmed(false); }} />}</>}
          <label className="attestation"><input type="checkbox" checked={causeConfirmed} disabled={blocked} onChange={event => setCauseConfirmed(event.target.checked)} /><span>I explicitly confirm the cause and its supporting evidence. Accepting the presentation alone does not confirm the cause.</span></label>
        </> : action === "start_work" ? <>{field("reason", "Work reason", { textarea: true })}{field("approved_attributes", "Approved target attributes and scope", { textarea: true })}<label className="attestation"><input type="checkbox" checked={authority} required disabled={blocked} onChange={event => setAuthority(event.target.checked)} /><span>I hold the authority required for this simulated target change. Reference approval alone does not grant that authority.</span></label></> : action === "record_correction" ? <>{field("explanation", "Correction or no-change explanation", { textarea: true })}<div className="workflow-field-grid">{field("target_system", "Target system")}{field("target_object", "Target object")}</div>{field("occurred_at", "Actual simulated action time (your local timezone)", { type: "datetime-local" })}</> : action === "complete_work" ? <>{field("reason", "Completion reason", { textarea: true })}<p className="field-help">The service checks that an applicable correction and human-confirmed stored proof exist.</p></> : action === "record_reprocessing" ? <>
          {field("attempt_key", "New attempt key", { placeholder: "MD01-0002" })}<div className="workflow-field-grid">{field("processing_order", "New processing order", { type: "number", min: 1 })}{field("target_document_reference", "Target document reference")}</div>{field("processing_at", "Simulated processing observation time (your local timezone)", { type: "datetime-local" })}{field("occurred_at", "Actual human reprocessing confirmation time (your local timezone)", { type: "datetime-local" })}
          <p className="field-help">Saved JSON result proof must identify this successful attempt, its order, target reference and matching document identity.</p>
          <label className="attestation"><input type="checkbox" checked={correctionApplicable} required disabled={blocked} onChange={event => setCorrectionApplicable(event.target.checked)} /><span>I confirm the earlier correction proof is applicable to this new attempt in the current work cycle.</span></label>
        </> : action === "record_validation" ? <>
          <p className="field-help">{detail.validation_comparisons ? "Expected and observed values come from the saved source and simulated target proof. Inspect each comparison and explicitly choose its result." : "Compare the latest successful target posting with the source and approved mapping. Enter each expected and observed result."}</p>
          {checks.map((check, index) => <fieldset className="validation-check" key={check.dimension}><legend>{checkDimensions[index][1]}</legend><label>Comparison result<select required value={check.result} disabled={blocked} onChange={event => setChecks(previous => previous.map((item, itemIndex) => itemIndex === index ? { ...item, result: event.target.value } : item))}><option value="">Select result</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="not_applicable">Not applicable</option></select></label><label>Expected<textarea rows={2} required disabled={blocked} readOnly={Boolean(detail.validation_comparisons)} value={check.expected} onChange={event => setChecks(previous => previous.map((item, itemIndex) => itemIndex === index ? { ...item, expected: event.target.value } : item))} /></label><label>Observed<textarea rows={2} required disabled={blocked} readOnly={Boolean(detail.validation_comparisons)} value={check.observed} onChange={event => setChecks(previous => previous.map((item, itemIndex) => itemIndex === index ? { ...item, observed: event.target.value } : item))} /></label>{check.result && check.result !== "passed" && <label>Discrepancy or applicability reason<textarea rows={2} required disabled={blocked} value={check.reason} onChange={event => setChecks(previous => previous.map((item, itemIndex) => itemIndex === index ? { ...item, reason: event.target.value } : item))} /></label>}</fieldset>)}
          <label>Validation decision<select value={validationStatus} required disabled={blocked} onChange={event => setValidationStatus(event.target.value)}><option value="">Select decision</option><option value="passed">Passed</option><option value="failed">Failed</option></select></label>{field("occurred_at", "Actual validation time (your local timezone)", { type: "datetime-local" })}
        </> : <>
          <label>Cause status<select value={causeStatus} disabled={blocked} onChange={event => { setCauseStatus(event.target.value); setCitationKeys([]); }}><option value="not_confirmed">Not confirmed — record remaining gaps</option><option value="confirmed">Confirmed — select cause and evidence</option></select></label>
          {causeStatus === "confirmed" && <label>Confirmed cause<select required value={fields.confirmed_cause || ""} disabled={blocked} onChange={event => setFields(previous => ({ ...previous, confirmed_cause: event.target.value }))}><option value="">Select cause</option><option value="missing_target_gl_master_data">Missing target G/L master data</option><option value="missing_gl_mapping">Missing G/L mapping</option></select></label>}{causeStatus === "not_confirmed" ? field("unresolved_gaps", "Unresolved cause gaps (one per line)", { textarea: true }) : <fieldset className="citation-choices"><legend>Supporting saved citations</legend>{citations.map(citation => { const key = JSON.stringify(citation); return <label className="attestation" key={key}><input type="checkbox" checked={citationKeys.includes(key)} disabled={blocked} onChange={event => setCitationKeys(previous => event.target.checked ? [...previous, key] : previous.filter(item => item !== key))} /><span>{value(citation.source_id)} · version {value(citation.source_version)} · {citation.record_id ? value(citation.record_id) : `lines ${value(citation.line_start)}–${value(citation.line_end)}`}</span></label>; })}</fieldset>}
          {causeStatus === "confirmed" && reviewableRuns[0] && <CitationPicker detail={detail} run={reviewableRuns[0]} workspaceId={workspaceId} token={token} disabled={blocked} onAdd={citation => { setAddedCitations(previous => [...previous, citation]); setCitationKeys(previous => [...new Set([...previous, JSON.stringify(citation)])]); setHumanConfirmed(false); }} />}{field("correction_or_no_change", "Correction or no-change outcome", { textarea: true })}<div className="workflow-field-grid">{field("target_system", "Target system")}{field("target_object", "Target object")}{field("company_code", "Company code")}</div>{field("reuse_limitations", "Scope and reuse limitations", { textarea: true })}{field("outcome", "Validated outcome", { textarea: true })}{field("occurred_at", "Actual resolution record time (your local timezone)", { type: "datetime-local" })}<p className="workflow-notice">Knowledge reuse remains Pending review. Completing this record does not publish a precedent.</p>
        </>}
        {needsProof && <ProofPicker caseId={detail.case.id} detail={detail} workspaceId={workspaceId} token={token} actingRole={role} disabled={disabled} ids={proofIds} simulationKind={simulationKind} simulationPayload={simulationPayload} simulationReady={simulationReady} onSelection={ids => { setProofIds(ids); setHumanConfirmed(false); }} onViewed={id => setViewedProofIds(previous => previous.includes(id) ? previous : [...previous, id])} onBusy={busy => { setProofBusy(busy); onProofBusy(busy); }} onSimulated={instant => setFields(previous => ({ ...previous, occurred_at: localInputTime(instant) }))} onSaved={onProofSaved} />}
        {needsProof && <label className="attestation"><input type="checkbox" checked={humanConfirmed} required disabled={blocked || !proofReady} onChange={event => setHumanConfirmed(event.target.checked)} /><span>I performed this simulated human step and reviewed the selected saved proof for the current attempt and work cycle.</span></label>}
        <button className="button button-primary" type="submit" disabled={blocked || (needsProof && (!humanConfirmed || !proofReady)) || (action === "start_work" && !authority) || (action === "record_reprocessing" && !correctionApplicable)}>{disabled ? "Saving…" : humanActions.find(item => item.value === action)?.label}</button>
      </form>
    </>}
  </section>;
}

function ProofPicker({ caseId, detail, workspaceId, token, actingRole, disabled, ids, simulationKind, simulationPayload, simulationReady, onSelection, onViewed, onBusy, onSimulated, onSaved }: { caseId: string; detail: CaseDetail; workspaceId: string; token: string; actingRole: string; disabled: boolean; ids: string[]; simulationKind?: "correction" | "reprocessing" | "validation"; simulationPayload: JsonRecord; simulationReady: boolean; onSelection: (ids: string[]) => void; onViewed: (id: string) => void; onBusy: (busy: boolean) => void; onSimulated: (instant: string) => void; onSaved: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeId, setActiveId] = useState("");
  const [simulationConfirmed, setSimulationConfirmed] = useState(false);
  const request = useRef<AbortController | null>(null);
  const proof = detail.evidence.filter(item => item.kind === "proof");
  const active = proof.find(item => item.id === activeId);
  const simulationFingerprint = JSON.stringify(simulationPayload);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { setSimulationConfirmed(false); setNotice(""); setError(""); setActiveId(""); }, [simulationKind]);
  useEffect(() => { setSimulationConfirmed(false); }, [simulationFingerprint]);
  async function simulate() {
    if (!simulationKind || !simulationConfirmed || !simulationReady || disabled || saving) return;
    const controller = new AbortController(); request.current = controller;
    setSaving(true); onBusy(true); setError(""); setNotice("");
    try {
      const result = await simulateProof(caseId, workspaceId, actingRole, simulationKind, simulationPayload, token, controller.signal);
      if (controller.signal.aborted) return;
      const id = value(result.evidence_id, value(result.id, ""));
      if (id) setActiveId(id);
      const confirmedAt = record(record(result.provenance).verified_observation).confirmed_at;
      if (typeof confirmedAt === "string") onSimulated(confirmedAt);
      setSimulationConfirmed(false); setNotice("Synthetic simulation proof stored. Inspect it, select it and confirm the separate milestone action."); onSaved();
    } catch (failure) { if (!controller.signal.aborted) setError(message(failure)); }
    finally { if (!controller.signal.aborted) { setSaving(false); onBusy(false); } }
  }
  async function upload() {
    if (!file || disabled || saving) return;
    if (!file.size || file.size > 10 * 1024 * 1024) { setError("Choose a nonempty proof file no larger than 10 MiB."); return; }
    if (file.name.length > 150) { setError("Use a proof filename with no more than 150 characters."); return; }
    const controller = new AbortController(); request.current = controller;
    setSaving(true); onBusy(true); setError(""); setNotice("");
    try {
      await saveProof(caseId, workspaceId, actingRole, file, token, controller.signal);
      if (controller.signal.aborted) return;
      setFile(null); setNotice("Proof stored. Select it below and inspect its saved contents before confirming a milestone."); onSaved();
    } catch (failure) { if (!controller.signal.aborted) setError(message(failure)); }
    finally { if (!controller.signal.aborted) { setSaving(false); onBusy(false); } }
  }
  return <fieldset className="proof-picker"><legend>Saved human proof</legend><p className="field-help">Uploading a file records evidence. Your milestone confirmation remains a separate action.</p>
    {error && <p className="inline-error" role="alert">{error}</p>}{notice && <p className="workflow-success" role="status">{notice}</p>}
    {simulationKind && <div className="simulation-proof"><p className="field-help">Create deterministic synthetic proof from this case and the values entered above. This performs no SAP action.</p><label className="attestation"><input type="checkbox" checked={simulationConfirmed} disabled={disabled || saving || !simulationReady} onChange={event => setSimulationConfirmed(event.target.checked)} /><span>I am performing this {simulationKind} simulation now and want to store its synthetic result as my signed-in account.</span></label><button className="button button-secondary" type="button" disabled={disabled || saving || !simulationReady || !simulationConfirmed} onClick={simulate}>{saving ? "Storing proof…" : `Simulate ${simulationKind}`}</button>{!simulationReady && <p className="field-help">Enter the {simulationKind === "correction" ? "correction explanation" : simulationKind === "reprocessing" ? "new attempt, order, processing time and target reference" : "four comparisons and validation decision"} above to enable the simulation.</p>}</div>}
    <details className="manual-proof"><summary>Upload an existing proof file</summary>
    <label>Choose proof file<input type="file" accept=".txt,.json,.pdf,.png,.jpg,.jpeg" disabled={disabled || saving} onChange={event => { setFile(event.target.files?.[0] || null); setError(""); setNotice(""); }} /></label><button className="button button-secondary" type="button" disabled={disabled || saving || !file} onClick={upload}>{saving ? "Storing proof…" : file ? `Store ${file.name}` : "Store proof file"}</button>
    </details>
    {!proof.length ? <p className="field-help">No proof attachment has been saved yet.</p> : <div className="proof-choices">{proof.map(item => { const id = value(item.id); const observation = record(record(item.provenance).verified_observation); return <div className="proof-choice" key={id}><label className="attestation"><input type="checkbox" checked={ids.includes(id)} disabled={disabled || saving} onChange={event => { onSelection(event.target.checked ? [...ids, id] : ids.filter(existing => existing !== id)); setActiveId(id); }} /><span>{value(item.filename)}<small>{value(observation.kind, value(item.content_type))}{observation.attempt_key ? ` · ${value(observation.attempt_key)}` : ""} · saved version {value(item.source_version)}</small></span></label><button className="button button-quiet" type="button" disabled={disabled || saving} onClick={() => setActiveId(id)}>Inspect</button></div>; })}</div>}
    {active && <EvidenceViewer key={value(active.id)} evidence={active} workspaceId={workspaceId} token={token} onViewed={onViewed} />}
  </fieldset>;
}
