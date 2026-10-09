"use client";

import { useEffect, useState } from "react";
import { getEvidence, type CaseDetail, type JsonRecord } from "@/lib/api";
import { EvidenceViewer } from "./case-workflow";

const record = (value: unknown): JsonRecord => value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
const text = (value: unknown) => typeof value === "string" ? value : "";
export function CitationPicker({ detail, run, workspaceId, token, disabled, onAdd }: { detail: CaseDetail; run: JsonRecord; workspaceId: string; token: string; disabled: boolean; onAdd: (citation: JsonRecord) => void }) {
  const [catalogue, setCatalogue] = useState<JsonRecord[]>([]); const [sourceKey, setSourceKey] = useState(""); const [recordId, setRecordId] = useState(""); const [lineStart, setLineStart] = useState(""); const [lineEnd, setLineEnd] = useState(""); const [viewedId, setViewedId] = useState(""); const [error, setError] = useState(""); const [loading, setLoading] = useState(true);
  const snapshot = record(run.snapshot); const sources = Array.isArray(snapshot.sources) ? snapshot.sources.map(record) : [];
  const catalogueEvidence = sources.map(source => record(source.evidence)).find(evidence => evidence.filename === "source-catalogue.json");
  const catalogueId = text(catalogueEvidence?.id);
  useEffect(() => {
    const controller = new AbortController(); setCatalogue([]); setLoading(true); setError("");
    if (!catalogueId) { setError("The saved run source catalogue is unavailable. Use its existing citations or record the gap."); setLoading(false); return; }
    getEvidence(catalogueId, workspaceId, token, controller.signal).then(async blob => {
      const rows: unknown = JSON.parse(await blob.text());
      if (!Array.isArray(rows) || !rows.every(item => typeof record(item).source_id === "string" && typeof record(item).source_version === "string")) throw new Error("The saved source catalogue could not be read.");
      if (!controller.signal.aborted) { setCatalogue(rows.map(record)); setLoading(false); }
    }).catch(failure => { if (!controller.signal.aborted) { setError(failure instanceof Error ? failure.message : "Source catalogue unavailable."); setLoading(false); } });
    return () => controller.abort();
  }, [catalogueId, workspaceId, token]);
  const selected = catalogue.find(item => `${item.source_id}:${item.source_version}` === sourceKey);
  const sourceEvidence = detail.evidence.find(item => item.source_id === selected?.source_id && item.source_version === selected?.source_version);
  const recordIds = Array.isArray(selected?.record_ids) ? selected.record_ids.filter(id => typeof id === "string") as string[] : [];
  const validRange = Number(lineStart) >= 1 && Number(lineEnd) >= Number(lineStart) && Number(lineEnd) <= Number(selected?.line_count);
  const ready = selected && sourceEvidence && viewedId === sourceEvidence.id && (selected.kind === "records" ? recordIds.includes(recordId) : validRange);
  function add() {
    if (!selected || !ready || disabled) return;
    onAdd({ source_id: selected.source_id, source_version: selected.source_version, attempt_id: selected.attempt_id ?? null, ...(selected.kind === "records" ? { record_id: recordId } : { line_start: Number(lineStart), line_end: Number(lineEnd) }) });
  }
  return <details className="citation-editor"><summary>Add a citation from preserved evidence</summary>{loading ? <p className="field-help" role="status">Loading the saved run source catalogue…</p> : error ? <p className="inline-error" role="alert">{error}</p> : <div className="workflow-form"><label>Saved source version<select disabled={disabled} value={sourceKey} onChange={event => { setSourceKey(event.target.value); setViewedId(""); setRecordId(""); setLineStart(""); setLineEnd(""); }}><option value="">Choose source</option>{catalogue.map(item => <option key={`${item.source_id}:${item.source_version}`} value={`${item.source_id}:${item.source_version}`}>{text(item.source_id)} · version {text(item.source_version)}</option>)}</select></label>{selected && sourceEvidence && <EvidenceViewer key={text(sourceEvidence.id)} evidence={sourceEvidence} workspaceId={workspaceId} token={token} onViewed={setViewedId} />}{selected?.kind === "records" ? <label>Preserved record<select disabled={disabled} value={recordId} onChange={event => setRecordId(event.target.value)}><option value="">Choose record</option>{recordIds.map(id => <option value={id} key={id}>{id}</option>)}</select></label> : selected ? <div className="workflow-field-grid"><label>First original line<input type="number" min={1} max={Number(selected.line_count)} value={lineStart} disabled={disabled} onChange={event => setLineStart(event.target.value)} /></label><label>Last original line<input type="number" min={1} max={Number(selected.line_count)} value={lineEnd} disabled={disabled} onChange={event => setLineEnd(event.target.value)} /></label></div> : null}<button className="button button-secondary" type="button" disabled={disabled || !ready} onClick={add}>Add supporting citation</button><p className="field-help">The server checks exact source/version, record or inclusive original line range and attempt applicability.</p></div>}</details>;
}
