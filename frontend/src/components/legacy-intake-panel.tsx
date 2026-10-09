"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { createIntake, getScenario, type JsonRecord, type ScenarioInput } from "@/lib/api";
import { Icon } from "./icon";

function isRecord(value: unknown): value is JsonRecord { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function parseBundle(text: string): ScenarioInput {
  const data: unknown = JSON.parse(text);
  if (!isRecord(data) || !isRecord(data.manifest) || typeof data.original_log !== "string" || !data.original_log.trim() || !isRecord(data.agent_files)) throw new Error("Choose a JSON bundle containing manifest, original_log and agent_files. Download the starter bundle for its structure.");
  if (Object.keys(data).some(key => !["manifest", "original_log", "agent_files", "sources"].includes(key))) throw new Error("Remove fields outside manifest, original_log, agent_files and sources. Expected answers and later human proof are separate from intake.");
  return { manifest: data.manifest, original_log: data.original_log, agent_files: data.agent_files, ...(Array.isArray(data.sources) ? { sources: data.sources.filter(isRecord) } : {}) };
}

export function LegacyIntakePanel({ workspaceId, token, canUpload, onSaved, onClose }: {
  workspaceId: string; token: string; canUpload: boolean; onSaved: (caseId: string) => void; onClose: () => void;
}) {
  const [input, setInput] = useState<ScenarioInput | null>(null);
  const [deliveryKey, setDeliveryKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"new" | "revision" | "attempt">("new");
  const [fileName, setFileName] = useState("");
  const [scenario, setScenario] = useState<"MD-01" | "MAP-01">("MD-01");
  const request = useRef<AbortController | null>(null);
  const uploadScope = useRef(0);
  useEffect(() => () => { request.current?.abort(); uploadScope.current += 1; }, []);
  useEffect(() => { request.current?.abort(); uploadScope.current += 1; setInput(null); setError(""); setBusy(false); }, [workspaceId, token, canUpload]);

  async function loadInput() {
    if (busy || !canUpload) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError("");
    try {
      const data = await getScenario(workspaceId, token, controller.signal, scenario);
      if (controller.signal.aborted) return;
      setInput(data); setFileName(`${scenario} starter`); setDeliveryKey(typeof data.manifest.delivery_key === "string" ? data.manifest.delivery_key : "md01-original-delivery-v1");
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The starter could not be loaded."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function upload(file: File | undefined) {
    if (!file || busy || !canUpload) return;
    const scope = ++uploadScope.current;
    setError(""); setInput(null);
    if (!file.size || file.size > 10 * 1024 * 1024 || !file.name.toLowerCase().endsWith(".json")) { setError("Choose a nonempty JSON bundle no larger than 10 MiB."); return; }
    try {
      const parsed = parseBundle(await file.text());
      if (scope !== uploadScope.current) return;
      setInput(parsed); setFileName(file.name); setDeliveryKey(typeof parsed.manifest.delivery_key === "string" ? parsed.manifest.delivery_key : "");
    } catch (failure) { if (scope === uploadScope.current) setError(failure instanceof SyntaxError ? "The bundle is not valid JSON. Check its syntax and upload it again." : failure instanceof Error ? failure.message : "The bundle could not be read."); }
  }
  function downloadBundle() {
    if (!input) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(input, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "cfin-intake-bundle.json"; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!input || !canUpload || busy) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError("");
    try {
      const result = await createIntake(workspaceId, deliveryKey.trim(), input, token, controller.signal);
      if (controller.signal.aborted) return;
      if (typeof result.case_id !== "string") throw new Error("Refresh the case board to verify whether this intake was saved.");
      onSaved(result.case_id);
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The intake could not be saved. Refresh before trying again."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  const identity = isRecord(input?.manifest.identity) ? input.manifest.identity : {};
  return <section className="intake-panel" aria-label="New private intake">
    <div className="workflow-section-heading"><div><h2>Save document evidence</h2><p>Load the starter or upload a prepared synthetic evidence bundle.</p></div><button className="icon-button" type="button" onClick={onClose} disabled={busy} aria-label="Close intake"><Icon name="close" size={16} /></button></div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {!canUpload ? <p className="workflow-notice">A process owner can save an intake.</p> : <>
      <div className="intake-tools"><label className="file-label">Starter family<select value={scenario} disabled={busy} onChange={event => { setScenario(event.target.value as typeof scenario); setInput(null); setError(""); }}><option value="MD-01">MD-01 · Missing target G/L master</option><option value="MAP-01">MAP-01 · Missing G/L mapping</option></select></label><button className="button button-secondary" type="button" onClick={loadInput} disabled={busy}>{busy ? "Loading…" : "Load starter bundle"}</button><label className="file-label">Upload evidence bundle<input type="file" accept=".json,application/json" disabled={busy} onChange={event => void upload(event.target.files?.[0])} /></label>{input && <button className="button button-quiet" type="button" onClick={downloadBundle} disabled={busy}>Download editable bundle</button>}</div>
      <p className="field-help">The bundle preserves the original log and structured records with their source catalogue. Edit the downloaded JSON to supply another document, revised evidence or a new failed attempt. Reference approval is a separate human decision.</p>
      {input && <form className="workflow-form" onSubmit={save}>
        <div className="workflow-field-grid"><label>Intake purpose<select value={mode} onChange={event => setMode(event.target.value as typeof mode)} disabled={busy}><option value="new">New document</option><option value="revision">Revised evidence for the same attempt</option><option value="attempt">Another failed attempt</option></select></label><label>Delivery key<input name="delivery_key" value={deliveryKey} onChange={event => setDeliveryKey(event.target.value)} required maxLength={150} disabled={busy} /></label></div>
        <p className="workflow-notice">{mode === "revision" ? "Keep the same document identity and attempt metadata; increment changed source versions and use a new delivery key in the bundle." : mode === "attempt" ? "Keep document identity; supply a new attempt ID, processing time/order, attempt-specific evidence and source catalogue." : "Supplied identity and attempt metadata determine whether this creates a case, adds evidence or returns an existing delivery."} Missing identity creates a provisional case for review.</p>
        <dl className="context-grid intake-context"><div><dt>Prepared file</dt><dd>{fileName}</dd></div><div><dt>Document</dt><dd>{String(identity.document_number || "Provisional")}</dd></div><div><dt>Source → target</dt><dd>{String(identity.source_system || "Unknown")} → {String(identity.target_system || "Unknown")}</dd></div><div><dt>Attempt</dt><dd>{String(input.manifest.attempt_id || "Unknown")}</dd></div></dl>
        <div className="intake-source-grid"><details open><summary>Preserved original log</summary><pre className="source-content">{input.original_log}</pre></details><details><summary>Manifest and structured pack</summary><pre className="source-content">{JSON.stringify(input.manifest, null, 2)}</pre><ul className="source-file-list">{Object.keys(input.agent_files || {}).map(name => <li key={name}>{name}</li>)}</ul></details></div>
        <p className="field-help">The server validates identity, provenance, processing order and declared source versions. Repeat the same delivery key to retrieve the saved intake; conflicting content under that key is rejected.</p>
        <div className="workflow-form-footer"><span>Saved privately in this workspace.</span><button className="button button-primary" type="submit" disabled={busy}>{busy ? "Saving intake…" : "Save private intake"}</button></div>
      </form>}
    </>}
  </section>;
}
