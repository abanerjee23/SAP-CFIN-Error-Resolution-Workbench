"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { explainOverview, getGroupPage, getOverview, type GroupPage, type Overview, type OverviewFilters, type OverviewGroup } from "@/lib/api";
import { formatTime } from "./case-worklist";
import { Icon } from "./icon";

const labels: Record<string, string> = { category: "Legacy primary cause", priority: "Priority", affected_object: "Affected object", diagnosis_status: "Legacy diagnosis", analysis_status: "Analysis availability", factual_review_status: "Factual review", workflow_version: "Case type", factual: "Factual summary", legacy: "Legacy diagnosis", status: "Work state", company_code: "Company", target_system: "Target system", missing_target_gl_master_data: "Missing master data", missing_gl_mapping: "Missing mapping", closed_target_posting_period: "Period not open", multiple_blockers: "Multiple blockers", cause_not_established: "Cause not established", gl_account: "G/L account", ai_supported: "AI supported", human_confirmed: "Human confirmed", needs_review: "Needs review" };
const label = (value: string) => labels[value] || value.replaceAll("_", " ");
export function groupLink(workspaceId: string, snapshotId: string, group: OverviewGroup) { return `/groups?${new URLSearchParams({ workspace_id: workspaceId, snapshot_id: snapshotId, group_id: group.id })}`; }
export function caseLink(workspaceId: string, caseId: string) { return `/?${new URLSearchParams({ workspace_id: workspaceId, case_id: caseId })}`; }

export function OperationsOverview({ workspaceId, token, onAccessFailure }: { workspaceId: string; token: string; onAccessFailure: () => void }) {
  const [filters, setFilters] = useState<OverviewFilters>({});
  const [draft, setDraft] = useState<OverviewFilters>({});
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const request = useRef<AbortController | null>(null);
  const filtersKey = JSON.stringify(filters);
  useEffect(() => {
    const controller = new AbortController(); request.current = controller; setLoading(true); setError(""); setData(null);
    getOverview(workspaceId, filters, revision > 0, token, controller.signal).then(result => { if (!controller.signal.aborted) { setData(result); setLoading(false); } }).catch(failure => { if (!controller.signal.aborted) { setData(null); setLoading(false); setError(failure instanceof Error ? failure.message : "The overview could not be loaded."); if (failure && typeof failure === "object" && "status" in failure && [401, 403].includes(Number(failure.status))) onAccessFailure(); } });
    return () => controller.abort();
  }, [workspaceId, token, filtersKey, revision]);
  useEffect(() => () => request.current?.abort(), []);
  async function explain() {
    if (!data || explaining || loading) return;
    const controller = new AbortController(); request.current = controller; setExplaining(true); setError("");
    try { const result = await explainOverview(data.snapshot.id, workspaceId, token, controller.signal); if (!controller.signal.aborted) setData(result); }
    catch (failure) { if (!controller.signal.aborted) { setError(failure instanceof Error ? failure.message : "The explanation could not be generated."); if (failure && typeof failure === "object" && "status" in failure && [401, 403].includes(Number(failure.status))) { setData(null); onAccessFailure(); } } }
    finally { if (!controller.signal.aborted) setExplaining(false); }
  }
  function apply(event: FormEvent<HTMLFormElement>) { event.preventDefault(); request.current?.abort(); setExplaining(false); setFilters(Object.fromEntries(Object.entries(draft).filter(([, value]) => value?.trim()))); }
  function select(key: keyof OverviewFilters, title: string, values: string[]) { return <label>{title}<select value={draft[key] || ""} disabled={loading || explaining} onChange={event => setDraft(previous => ({ ...previous, [key]: event.target.value }))}><option value="">All</option>{values.map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label>; }
  const dimensions = [...new Set(data?.groups.map(item => item.dimension) || [])];
  return <section className="operations-section" aria-busy={loading}>
    <div className="section-header"><div><h2>Backlog overview</h2><p>Unresolved known documents and provisional cases. Factual summaries and legacy diagnoses retain separate review states.</p></div><button className="button button-secondary" type="button" disabled={loading || explaining} onClick={() => setRevision(value => value + 1)}><Icon name="refresh" size={16} />Refresh snapshot</button></div>
    <form className="overview-filters" onSubmit={apply}>{select("priority", "Priority", ["P3", "P2", "P1"])}{select("workflow_version", "Case type", ["log-only-v1", "legacy-v1"])}{select("analysis_status", "Analysis", ["pending", "running", "available", "unavailable", "needs_refresh"])}{select("factual_review_status", "Factual review", ["pending_review", "Accepted", "Corrected", "Insufficient"])}{select("category", "Legacy primary cause", ["missing_target_gl_master_data", "missing_gl_mapping", "closed_target_posting_period", "multiple_blockers", "cause_not_established"])}{select("affected_object", "Object", ["gl_account", "cost_center", "profit_center", "asset", "unknown"])}{select("diagnosis_status", "Legacy diagnosis", ["needs_review", "ai_supported", "human_confirmed"])}<label>Company<input value={draft.company_code || ""} maxLength={150} disabled={loading || explaining} onChange={event => setDraft(previous => ({ ...previous, company_code: event.target.value }))} /></label><label>Target system<input value={draft.target_system || ""} maxLength={150} disabled={loading || explaining} onChange={event => setDraft(previous => ({ ...previous, target_system: event.target.value }))} /></label><button className="button button-primary" type="submit" disabled={loading || explaining}>Apply filters</button></form>
    {error && <p className="inline-error" role="alert">{error}</p>}{loading && <p className="section-intro" role="status">Reading the authorised backlog…</p>}
    {data && <>
      <div className="overview-metrics"><div><strong>{data.metrics.unresolved_known_cases}</strong><span>Unresolved known documents</span></div><div><strong>{data.metrics.provisional_cases}</strong><span>Provisional cases</span></div><div><strong>{data.metrics.attempts}</strong><span>Processing attempts</span></div></div>
      <div className="snapshot-caption"><span>As of {formatTime(data.snapshot.as_of)} · counts use case units unless labelled attempts</span><span>{data.snapshot.stale ? "Snapshot changed or expired. Refresh to update membership." : `Snapshot expires ${formatTime(data.snapshot.expires_at)}`}</span></div>
      <div className="overview-charts">{dimensions.map(dimension => { const groups = data.groups.filter(item => item.dimension === dimension); const max = Math.max(1, ...groups.map(item => item.count)); return <section className="overview-chart" key={dimension}><h3>{label(dimension)}</h3><ul>{groups.map(group => <li key={group.id}><a href={groupLink(workspaceId, data.snapshot.id, group)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${label(group.value)}: ${group.count} ${group.unit || "cases"} in a new tab`}><div className="chart-label"><span>{label(group.value)}</span><strong>{group.count}</strong></div><span className="chart-track"><span style={{ width: `${group.count / max * 100}%` }} /></span></a></li>)}</ul></section>; })}</div>
      {!data.groups.length && <p className="workflow-notice">No matching unresolved cases. Change the filters or add an intake.</p>}
      <section className="insight-narrative"><div className="section-header"><div><h3>Backlog explanation</h3><p>Charts remain available when analysis is unavailable.</p></div><button className="button button-secondary" type="button" onClick={explain} disabled={loading || explaining || data.snapshot.stale}>{explaining ? "Generating…" : "Request explanation"}</button></div>{data.narrative.text ? <p>{data.narrative.text}</p> : <p className="field-help">{data.narrative.status === "models_disabled" ? "Model execution is disabled. The saved snapshot and its case links are available." : `No explanation saved (${label(data.narrative.status || "pending")}).`}</p>}{Array.isArray(data.narrative.claims) && <ul className="source-file-list">{data.narrative.claims.map((claim, index) => { if (!claim || typeof claim !== "object" || Array.isArray(claim)) return null; const item = claim as Record<string, unknown>; const group = data.groups.find(group => group.id === item.group_id); return <li key={index}><span>{String(item.observation || item.text || item.claim || "Saved claim")}</span>{group && <a href={groupLink(workspaceId, data.snapshot.id, group)} target="_blank" rel="noopener noreferrer">Open supporting cases ({group.count})</a>}</li>; })}</ul>}</section>
    </>}
  </section>;
}

export function SnapshotGroup({ workspaceId, token, snapshotId, groupId, onAccessFailure }: { workspaceId: string; token: string; snapshotId: string; groupId: string; onAccessFailure: () => void }) {
  const [page, setPage] = useState(1); const [data, setData] = useState<GroupPage | null>(null); const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setData(null); setError("");
    getGroupPage(snapshotId, groupId, workspaceId, page, token, controller.signal).then(result => { if (!controller.signal.aborted) { setData(result); setLoading(false); } }).catch(failure => { if (!controller.signal.aborted) { setLoading(false); setData(null); setError(failure instanceof Error ? failure.message : "This group could not be loaded."); if (failure && typeof failure === "object" && "status" in failure && [401, 403].includes(Number(failure.status))) onAccessFailure(); } });
    return () => controller.abort();
  }, [workspaceId, token, snapshotId, groupId, page, refresh]);
  return <section className="operations-section"><div className="section-header"><div><h2>{data ? label(String(data.group.value || "Case group")) : "Snapshot case group"}</h2><p>Saved membership with current case access. Open a case to inspect live details.</p></div><button className="button button-secondary" type="button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>Refresh access</button></div>{error && <p className="inline-error" role="alert">{error}</p>}{loading && <p className="section-intro" role="status">Loading snapshot cases…</p>}{data && <><p className="snapshot-caption">As of {formatTime(typeof data.snapshot.as_of === "string" ? data.snapshot.as_of : null)} · {data.total} cases · highest priority first</p><div className="table-scroll"><table className="case-table"><thead><tr><th>Case</th><th>Priority</th><th>Work state</th><th>Snapshot version</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id}><td><a className="case-name" href={caseLink(workspaceId, item.id)} target="_blank" rel="noopener noreferrer">{item.title}</a>{item.changed_since_snapshot && <span className="review-indicator">Changed since snapshot. Review current details.</span>}</td><td>{item.priority}</td><td>{label(item.status)}</td><td>{item.snapshot_version} → {item.version}</td></tr>)}</tbody></table></div>{!data.items.length && <p className="workflow-notice">No accessible cases in this page.</p>}<div className="pagination"><button className="button button-secondary" disabled={page <= 1 || loading} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page} of {Math.max(1, Math.ceil(data.total / data.page_size))}</span><button className="button button-secondary" disabled={page * data.page_size >= data.total || loading} onClick={() => setPage(value => value + 1)}>Next</button></div></>}</section>;
}
