"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { createLogIntake, type LogIntakeSource } from "@/lib/api";
import { LegacyIntakePanel } from "./legacy-intake-panel";
import { Icon } from "./icon";

const MAX_BYTES = 8192;
const MAX_LINES = 64;
export function originalLines(content: string): string[] {
  if (!content) return [];
  const lines = content.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/);
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}
type PreparedSource = LogIntakeSource & { text: string; bytes: number; lines: number };
export function IntakePanel(props: { workspaceId: string; token: string; canUpload: boolean; syntheticWorkspace?: boolean; onSaved: (caseId: string) => void; onClose: () => void }) {
  const { workspaceId, token, canUpload, onSaved, onClose, syntheticWorkspace } = props;
  const [sources, setSources] = useState<PreparedSource[]>([]);
  const [provenance, setProvenance] = useState<"" | "synthetic" | "user_supplied">("");
  const [routingContext, setRoutingContext] = useState<Record<string, string>>({});
  const [deliveryKey, setDeliveryKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");
  const [legacy, setLegacy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => { setSources([]); setProvenance(""); setRoutingContext({}); setDeliveryKey(crypto.randomUUID()); setError(""); setBusy(false); setReading(false); return () => { request.current?.abort(); generation.current += 1; }; }, [workspaceId, token, canUpload]);
  async function prepare(files: FileList | null) {
    if (!files || !canUpload || busy) return;
    const selected = Array.from(files); const current = ++generation.current;
    setSources([]); setError(""); setReading(true); setDeliveryKey(crypto.randomUUID());
    try {
      if (!selected.length || selected.length > 8) throw new Error("Choose between one and eight original text files.");
      if (selected.reduce((sum, file) => sum + file.size, 0) > MAX_BYTES) throw new Error("These originals exceed the 8,192-byte analysis limit. No files were uploaded or shortened.");
      if (new Set(selected.map(file => file.name)).size !== selected.length) throw new Error("Choose files with distinct names so each original is easy to identify.");
      const prepared = await Promise.all(selected.map(async file => {
        if (!/\.(txt|log|csv|tsv)$/i.test(file.name)) throw new Error(`${file.name}: choose a UTF-8 .txt, .log, .csv or .tsv original. Other file formats are not supported.`);
        const bytes = new Uint8Array(await file.arrayBuffer());
        let text: string;
        try { text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes); } catch { throw new Error(`${file.name} is not valid UTF-8 text. No replacement characters were inserted.`); }
        if (!text.trim()) throw new Error(`${file.name} contains no readable text. Choose a nonempty original.`);
        if (text.includes("\0")) throw new Error(`${file.name} contains binary data. Choose a readable UTF-8 text file.`);
        let binary = ""; for (const byte of bytes) binary += String.fromCharCode(byte);
        return { filename: file.name, content_base64: btoa(binary), text, bytes: bytes.length, lines: originalLines(text).length };
      }));
      if (prepared.reduce((sum, source) => sum + source.lines, 0) > MAX_LINES) throw new Error("These originals exceed the 64-line analysis limit. No files were uploaded or shortened.");
      if (generation.current === current) setSources(prepared);
    } catch (failure) { if (generation.current === current) setError(failure instanceof Error ? failure.message : "The originals could not be read."); }
    finally { if (generation.current === current) setReading(false); }
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!sources.length || !provenance || !canUpload || busy || reading) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError("");
    try {
      const result = await createLogIntake(workspaceId, deliveryKey, provenance, sources.map(({ filename, content_base64 }) => ({ filename, content_base64 })), token, controller.signal, Object.fromEntries(Object.entries(routingContext).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)));
      if (!controller.signal.aborted) onSaved(String(result.case_id));
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The originals could not be saved. Retry with this same delivery reference."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  if (legacy) return <><button className="button button-quiet" type="button" onClick={() => setLegacy(false)}>Back to original logs</button><LegacyIntakePanel {...props} /></>;
  return <section className="intake-panel" aria-label="New private intake">
    <div className="workflow-section-heading"><div><h2>Create a case from original logs</h2><p>Supply the text views you want reviewed. Each original stays unchanged and separate.</p></div><button className="icon-button" type="button" onClick={onClose} disabled={busy} aria-label="Close intake"><Icon name="close" size={16} /></button></div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {!canUpload ? <p className="workflow-notice">A process owner can save an intake.</p> : <form className="workflow-form" onSubmit={save}>
      <p className="workflow-notice">Current analysis capacity: up to 8 UTF-8 text originals, 8,192 bytes and 64 lines in total. Files that exceed these limits are rejected in full.</p>
      <label>Original logs or supplied text views<input type="file" accept=".txt,.log,.csv,.tsv,text/plain,text/csv,text/tab-separated-values" multiple disabled={busy || reading} onChange={event => void prepare(event.target.files)} /></label>
      <p className="field-help">PDFs, screenshots and binary exports are not supported. Document identity and SAP processing times may remain unknown.</p>
      <label>Where did this evidence come from?<select required value={provenance} disabled={busy} onChange={event => setProvenance(event.target.value as typeof provenance)}><option value="">Select provenance</option><option value="user_supplied" disabled={syntheticWorkspace !== false}>Real / user-supplied evidence{syntheticWorkspace !== false ? " (requires a non-synthetic workspace)" : ""}</option><option value="synthetic">Synthetic example or test evidence</option></select></label>
      {syntheticWorkspace !== false && <p className="field-help">This workspace accepts synthetic evidence only. Real evidence requires an administrator-provisioned non-synthetic workspace; do not relabel a real log as synthetic.</p>}
      {reading && <p role="status">Checking all original files…</p>}
      {sources.length > 0 && <><p className="field-help">{sources.length} originals · {sources.reduce((sum, item) => sum + item.bytes, 0).toLocaleString()} bytes · {sources.reduce((sum, item) => sum + item.lines, 0)} lines</p><div className="intake-source-grid">{sources.map(source => <details key={source.filename}><summary>{source.filename} · {source.lines} lines</summary><pre className="source-content">{source.text}</pre></details>)}</div></>}
      <details><summary>Ownership context (optional)</summary><p className="field-help">Supply known context for an exact configured owner match. These administrative fields are separate from facts extracted from your logs. Leave unknown values blank.</p><div className="workflow-field-grid">{["source_system", "target_system", "interface", "company_code"].map(key => <label key={key}>{key.replaceAll("_", " ")}<input value={routingContext[key] || ""} maxLength={120} disabled={busy} onChange={event => setRoutingContext(previous => ({ ...previous, [key]: event.target.value }))} /></label>)}</div></details>
      <details><summary>Delivery reference</summary><p className="field-help">{deliveryKey}. A retry uses this reference to avoid a duplicate case. Changing files creates a new reference.</p></details>
      <div className="workflow-form-footer"><span>Saved privately in this workspace.</span><button className="button button-primary" type="submit" disabled={busy || reading || !sources.length || !provenance}>{busy ? "Saving originals…" : "Save originals and create case"}</button></div>
      <details><summary>Legacy demonstration intake</summary><p className="field-help">Use the earlier structured synthetic bundle workflow to maintain a compatible legacy case.</p><button className="button button-quiet" type="button" disabled={busy} onClick={() => setLegacy(true)}>Open legacy bundle intake</button></details>
    </form>}
  </section>;
}
