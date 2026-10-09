"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { CaseFilters, CaseSummary } from "@/lib/api";
import type { PreviewCase } from "@/lib/design-preview";
import { Icon } from "./icon";

const priorities = { P1: "Low", P2: "Medium", P3: "High" };
const priorityOrder = { P3: 0, P2: 1, P1: 2 };
const statusLabels: Record<string, string> = { created: "Created", owner_notified: "Owner notified", in_progress: "In progress", blocked: "Blocked", complete: "Complete", document_reprocessed: "Document reprocessed" };
const needsReview = (item: CaseSummary) => item.workflow_version === "log-only-v1" ? ["pending_review", "Insufficient", "insufficient"].includes(item.factual_review_status || "pending_review") : item.workflow_version === "error-analysis-v1" ? item.analysis_status !== "available" : item.diagnosis_status === "needs_review";
const diagnosisLabels: Record<string, string> = { ai_supported: "AI-supported", human_confirmed: "Human-confirmed", needs_review: "Needs review" };
type Queue = "all" | "review" | "active";
type DetailTab = "summary" | "evidence" | "activity";

function previewItem(item: CaseSummary): PreviewCase | null {
  return "documentNumber" in item ? item as PreviewCase : null;
}
export function formatTime(value: string | null) {
  if (!value) return "Not set";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" }).format(date);
}

export function CaseWorklist({ items, preview = false, phase = "ready", message, error, onRefresh, detailRenderer, preferredCaseId, pagination, onFilterChange }: {
  items: CaseSummary[]; preview?: boolean; phase?: "ready" | "loading" | "error" | "disconnected"; message?: string; error?: string; onRefresh?: () => void; detailRenderer?: (item: CaseSummary) => ReactNode; preferredCaseId?: string; pagination?: { page: number; total: number; pageSize: number; onPage: (page: number) => void }; onFilterChange?: (filters: CaseFilters) => void;
}) {
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("all");
  const [analysisStatus, setAnalysisStatus] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [workflowVersion, setWorkflowVersion] = useState("");
  const [category, setCategory] = useState("");
  const [object, setObject] = useState("");
  const [status, setStatus] = useState("");
  const [queue, setQueue] = useState<Queue>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [tab, setTab] = useState<DetailTab>("summary");
  const [evidenceIndex, setEvidenceIndex] = useState<number | null>(null);
  const caseButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const backButton = useRef<HTMLButtonElement | null>(null);
  const preferredHandled = useRef("");
  const loaded = phase === "ready";
  const preferredPresent = loaded && items.some(item => item.id === preferredCaseId);
  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return items.filter(item => {
      const sample = previewItem(item);
      return (priority === "all" || item.priority === priority) &&
        (queue !== "review" || needsReview(item)) &&
        (queue !== "active" || item.status === "in_progress" || item.status === "blocked") &&
        (!query || Boolean(onFilterChange) || `${item.title} ${item.description} ${sample?.documentNumber || ""} ${sample?.reference || ""} ${sample?.owner || ""}`.toLowerCase().includes(query));
    }).sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority] || b.created_at.localeCompare(a.created_at));
  }, [items, search, priority, queue]);
  // MD-01 stays the initial selected example even when another example sorts first.
  const selected = loaded ? visible.find(item => item.id === selectedId) || (preview && !selectedId ? visible.find(item => previewItem(item)?.reference === "MD-01") : undefined) || visible[0] : undefined;
  const sample = selected ? previewItem(selected) : null;
  const tabs: DetailTab[] = ["summary", "evidence", "activity"];
  const counts = { all: items.length, review: items.filter(item => needsReview(item)).length, active: items.filter(item => item.status === "in_progress" || item.status === "blocked").length };
  const filterCallback = useRef(onFilterChange); filterCallback.current = onFilterChange;
  useEffect(() => {
    if (!filterCallback.current) return;
    const timeout = window.setTimeout(() => filterCallback.current?.({ ...(search.trim() ? { q: search.trim() } : {}), ...(priority !== "all" ? { priority } : {}), ...(category ? { category } : {}), ...(object ? { affected_object: object } : {}), ...(status ? { status } : {}), ...(workflowVersion ? { workflow_version: workflowVersion } : {}), ...(analysisStatus ? { analysis_status: analysisStatus } : {}), ...(reviewStatus ? { factual_review_status: reviewStatus } : {}) }), 300);
    return () => window.clearTimeout(timeout);
  }, [search, priority, category, object, status, workflowVersion, analysisStatus, reviewStatus]);

  useEffect(() => {
    if (!selected) { setShowDetail(false); return; }
    if (showDetail && backButton.current && window.getComputedStyle(backButton.current).display !== "none") backButton.current.focus();
  }, [showDetail, selected?.id]);

  useEffect(() => {
    if (!preferredCaseId || !preferredPresent || preferredHandled.current === preferredCaseId) return;
    preferredHandled.current = preferredCaseId;
    setSelectedId(preferredCaseId); setShowDetail(true); setSearch(""); setPriority("all"); setQueue("all");
  }, [preferredCaseId, preferredPresent]);

  function select(item: CaseSummary) { setSelectedId(item.id); setShowDetail(true); setTab("summary"); setEvidenceIndex(null); }
  function resetFilters() { setSearch(""); setPriority("all"); setQueue("all"); setCategory(""); setObject(""); setStatus(""); setAnalysisStatus(""); setReviewStatus(""); setWorkflowVersion(""); }
  function chooseQueue(value: Queue) { setQueue(value); setEvidenceIndex(null); }
  function backToCases() { setShowDetail(false); requestAnimationFrame(() => { if (selected) caseButtons.current[selected.id]?.focus(); }); }

  return (
    <section className={`worklist-layout${showDetail && selected ? " detail-open" : ""}`} aria-label="Cases and selected case">
      <div className="worklist-panel">
        <div className="queue-bar" aria-label="Case groups">
          {([ ["all", "All cases"], ["review", "Needs review"], ["active", "Active work"] ] as [Queue, string][]).map(([value, label]) => <button type="button" key={value} className={queue === value ? "queue selected" : "queue"} aria-pressed={queue === value} onClick={() => chooseQueue(value)} disabled={!loaded}>{label}<span>{loaded ? counts[value] : "—"}</span></button>)}
          {onRefresh && <button className="icon-button refresh-button" type="button" title="Refresh cases" aria-label="Refresh cases" onClick={onRefresh} disabled={phase === "loading"}><Icon name="refresh" size={17} /></button>}
        </div>
        <div className="filter-bar">
          <div className="search-field"><Icon name="search" size={17} /><input aria-label="Search cases" type="search" placeholder={preview ? "Search document, case or owner" : pagination ? "Search all workspace cases" : "Search title or description"} value={search} onChange={event => setSearch(event.target.value)} disabled={phase === "disconnected"} /></div>
          <select aria-label="Filter priority" value={priority} onChange={event => setPriority(event.target.value)} disabled={!loaded}><option value="all">All priorities</option><option value="P3">P3 · High</option><option value="P2">P2 · Medium</option><option value="P1">P1 · Low</option></select>
        </div>
        {onFilterChange && <div className="filter-bar advanced-case-filters"><select aria-label="Filter case type" value={workflowVersion} onChange={event => setWorkflowVersion(event.target.value)} disabled={phase === "disconnected"}><option value="">All case types</option><option value="error-analysis-v1">Error Analysis cases</option><option value="log-only-v1">Factual cases</option><option value="legacy-v1">Legacy cases</option></select><select aria-label="Filter analysis availability" value={analysisStatus} onChange={event => setAnalysisStatus(event.target.value)} disabled={phase === "disconnected"}><option value="">All analysis states</option>{["pending", "running", "available", "unavailable", "needs_refresh"].map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select><select aria-label="Filter factual review" value={reviewStatus} onChange={event => setReviewStatus(event.target.value)} disabled={phase === "disconnected"}><option value="">All factual review states</option><option value="pending_review">Pending review</option><option>Accepted</option><option>Corrected</option><option>Insufficient</option></select><select aria-label="Filter error type" value={category} disabled={phase === "disconnected"} onChange={event => setCategory(event.target.value)}><option value="">All error types</option>{["master_data", "mapping", "integration_mapping", "master_data_restriction", "posting_period", "tax", "currency", "document_splitting", "account_assignment", "technical_interface", "unclassified"].map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select><select aria-label="Filter legacy affected object" value={object} disabled={phase === "disconnected"} onChange={event => setObject(event.target.value)}><option value="">Legacy affected objects</option>{["gl_account", "cost_center", "profit_center", "asset", "posting_period", "unknown"].map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select><select aria-label="Filter work state" value={status} disabled={phase === "disconnected"} onChange={event => setStatus(event.target.value)}><option value="">All work states</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>}
        <div className="list-caption"><span>{loaded ? `${visible.length} ${visible.length === 1 ? "case" : "cases"}${search || priority !== "all" || queue !== "all" ? ` of ${items.length}` : ""}` : "Cases"}</span><span>Highest priority first</span></div>
        <div className="table-scroll" aria-busy={phase === "loading"}>
          <table className="case-table"><thead><tr><th scope="col">Case / document</th><th scope="col">Priority</th><th scope="col">Work status</th><th scope="col">{preview ? "Assigned to" : "Due date"}</th></tr></thead><tbody>
            {phase === "loading" ? Array.from({ length: 5 }, (_, index) => <tr key={index} className="skeleton-row" aria-hidden="true"><td><span /><span /></td><td><span /></td><td><span /></td><td><span /></td></tr>) : visible.map(item => {
              const details = previewItem(item);
              const isSelected = selected?.id === item.id;
              return <tr key={item.id} className={isSelected ? "selected-row" : ""}>
                <td><button className="case-select" type="button" ref={node => { caseButtons.current[item.id] = node; }} onClick={() => select(item)} aria-pressed={isSelected} aria-label={`Open ${details?.reference || item.title}`}><span className="case-reference">{details?.reference || (item.workflow_version === "error-analysis-v1" ? "Error Analysis case" : item.workflow_version === "log-only-v1" ? "Factual case" : "Legacy case")}{isSelected && <Icon name="chevron" size={14} />}</span><span className="case-name">{item.title}</span>{details && <span className="case-context">{details.documentNumber} <span>·</span> {details.companyCode}</span>}</button></td>
                <td><span className={`priority-badge priority-${item.priority.toLowerCase()}`}><span />{item.priority}<small>{priorities[item.priority]}</small></span></td>
                <td><span className={`work-status status-${item.status}`}><span />{statusLabels[item.status] || item.status}</span>{item.workflow_version === "log-only-v1" && <span className="review-indicator">{(item.analysis_status || "pending").replaceAll("_", " ")} · {(item.factual_review_status || "pending_review").replaceAll("_", " ")}</span>}{needsReview(item) && item.workflow_version !== "log-only-v1" && <span className="review-indicator">Legacy diagnosis needs review</span>}</td>
                <td>{preview ? <span className={details?.owner ? "owner-name" : "unassigned"}>{details?.owner || "Unassigned"}</span> : <span className="table-date">{formatTime(item.due_at)}</span>}</td>
              </tr>;
            })}
          </tbody></table>
          {phase !== "loading" && !visible.length && <div className="worklist-empty" role={phase === "error" ? "alert" : "status"}><span className="empty-icon"><Icon name={phase === "error" ? "info" : "cases"} size={27} /></span><h2>{phase === "error" ? "Cases couldn’t be loaded" : phase === "disconnected" ? "Your case workspace is ready to connect" : items.length ? "No cases match" : "No saved cases yet"}</h2><p>{error || message || (items.length ? "Try another search or clear the filters." : "Saved document exceptions will appear in this worklist.")}</p>{items.length > 0 && <button className="button button-secondary" type="button" onClick={resetFilters}>Clear filters</button>}</div>}
        </div>
        {pagination && <div className="pagination"><button className="button button-secondary" type="button" disabled={phase === "loading" || pagination.page <= 1} onClick={() => pagination.onPage(pagination.page - 1)}>Previous</button><span>Page {pagination.page} of {Math.max(1, Math.ceil(pagination.total / pagination.pageSize))} · {pagination.total} matching cases</span><button className="button button-secondary" type="button" disabled={phase === "loading" || pagination.page * pagination.pageSize >= pagination.total} onClick={() => pagination.onPage(pagination.page + 1)}>Next</button></div>}
        <div className="worklist-footnote"><Icon name={preview ? "preview" : "lock"} size={14} /><span>{preview ? `${items.length} illustrative ${items.length === 1 ? "case" : "cases"} · not cloud records` : pagination ? "Groups count the loaded page · filters search all accessible cases · London time" : "Latest 100 saved cases · London time"}</span></div>
      </div>

      <aside className="detail-panel" aria-label="Selected case details">
        {selected && detailRenderer ? <><button type="button" className="button button-quiet detail-back workflow-back" ref={backButton} onClick={backToCases}>Back to cases</button>{detailRenderer(selected)}</> : selected ? <>
          <div className="detail-heading"><button type="button" className="button button-quiet detail-back" ref={backButton} onClick={backToCases}>Back to cases</button><div className="detail-eyebrow"><span><Icon name="document" size={16} />{sample?.reference || "Case details"}</span><span className="read-only-tag">Read-only</span></div><h2>{sample ? `Document ${sample.documentNumber}` : selected.title}</h2><p>{sample ? `${sample.sourceSystem} to ${sample.targetSystem}` : diagnosisLabels[selected.diagnosis_status] || selected.diagnosis_status}</p><div className="detail-badges"><span className={`work-status status-${selected.status}`}><span />{statusLabels[selected.status] || selected.status}</span><span className={`priority-inline priority-${selected.priority.toLowerCase()}`}>{selected.priority} · {priorities[selected.priority]}</span></div></div>
          <div className="detail-tabs" role="tablist" aria-label="Case information">{tabs.map(value => <button type="button" role="tab" key={value} id={`tab-${value}`} aria-selected={tab === value} aria-controls="detail-content" tabIndex={tab === value ? 0 : -1} onClick={() => { setTab(value); setEvidenceIndex(null); }} onKeyDown={event => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); const next = tabs[(tabs.indexOf(value) + (event.key === "ArrowRight" ? 1 : 2)) % 3]; setTab(next); setEvidenceIndex(null); document.getElementById(`tab-${next}`)?.focus(); } }}>{value === "summary" ? "Summary" : value === "evidence" ? `Evidence${sample ? ` (${sample.evidence.length})` : ""}` : "Activity"}</button>)}</div>
          <div className="detail-content" id="detail-content" role="tabpanel" aria-labelledby={`tab-${tab}`} key={selected.id + tab}>
            {tab === "summary" ? <>
              <section className="detail-section"><h3>Diagnosis</h3><div className="diagnosis-notice"><Icon name="info" size={18} /><div><strong>{sample?.category || diagnosisLabels[selected.diagnosis_status] || selected.diagnosis_status}</strong><p>{sample?.reviewReason || selected.description}</p></div></div></section>
              <section className="detail-section"><h3>{sample ? "Document context" : "Case information"}</h3><dl className="context-grid">{sample ? <><div><dt>Company code</dt><dd>{sample.companyCode}</dd></div><div><dt>Document amount</dt><dd>{sample.amount}</dd></div><div><dt>Target G/L account</dt><dd>{sample.targetAccount || "Not established"}</dd></div><div><dt>Processing attempt</dt><dd>{sample.attempt}</dd></div></> : <><div><dt>Created</dt><dd>{formatTime(selected.created_at)}</dd></div><div><dt>Due date</dt><dd>{formatTime(selected.due_at)}</dd></div><div><dt>Record version</dt><dd>{selected.version}</dd></div><div><dt>Diagnosis status</dt><dd>{diagnosisLabels[selected.diagnosis_status] || selected.diagnosis_status}</dd></div></>}</dl></section>
              <section className="detail-section"><h3>{sample ? "Next review" : "Description"}</h3><p className="detail-description">{sample ? "Confirm the applicable mapping and reference versions before establishing the cause. Corrective steps remain withheld while that review is pending." : selected.description}</p>{sample && <div className="review-assignment"><span className="person-avatar">{sample.owner ? "D" : "?"}</span><div><strong>{sample.owner || "Owner assignment required"}</strong><span>{sample.owner ? "Fictional demo role" : "No owner has been assigned"}</span></div></div>}</section>
              <div className="detail-record"><span>Created {formatTime(selected.created_at)}</span><span>{sample ? "Synthetic design example" : `Version ${selected.version}`}</span></div>
            </> : tab === "evidence" ? sample ? <>
              <p className="section-intro">{sample.reference === "MD-01" ? "Original fixture sources. Pending references do not establish an approved cause." : "Illustrative evidence labels for this design example."}</p>
              <div className="evidence-list">{sample.evidence.map((entry, index) => <button key={entry.name} type="button" className={evidenceIndex === index ? "evidence-item selected" : "evidence-item"} onClick={() => setEvidenceIndex(evidenceIndex === index ? null : index)} aria-expanded={evidenceIndex === index}><Icon name="document" size={19} /><span><strong>{entry.name}</strong><small>{entry.detail}</small></span><span className={`evidence-state ${entry.state}`}>{entry.state === "pending" ? "Pending review" : "Available"}</span><Icon name="chevron" size={14} /></button>)}</div>
              {evidenceIndex !== null && sample.evidence[evidenceIndex] && <section className="evidence-viewer"><h3>{sample.evidence[evidenceIndex].name}</h3><pre>{sample.evidence[evidenceIndex].content}</pre></section>}
            </> : <div className="tab-empty"><Icon name="lock" size={25} /><h3>Evidence viewer is being prepared</h3><p>Private evidence access will be added after the cloud integration checkpoint.</p></div> : sample ? <><p className="section-intro">{sample.reference === "MD-01" ? "Fixture events, not a cloud audit trail." : "Illustrative activity for this design example."}</p><ol className="activity-list">{sample.activity.map((event, index) => <li key={index}><span className="activity-dot" /><time>{event.time}</time><strong>{event.title}</strong><p>{event.detail}</p></li>)}</ol></> : <div className="tab-empty"><Icon name="clock" size={25} /><h3>Case created</h3><p>{formatTime(selected.created_at)}</p><p>The full activity history is not available in this view yet.</p></div>}
          </div>
        </> : <div className="detail-placeholder"><span className="empty-icon"><Icon name="document" size={28} /></span><h2>Case details</h2><p>Select a document exception to review its factual summary, context and supporting evidence.</p><div className="detail-placeholder-list"><span>Analysis & human review</span><span>Document context</span><span>Evidence & activity</span></div></div>}
      </aside>
    </section>
  );
}
