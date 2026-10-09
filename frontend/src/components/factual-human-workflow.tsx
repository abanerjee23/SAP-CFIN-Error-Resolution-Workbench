"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { saveProof, type CaseAction, type CaseDetail, type JsonRecord } from "@/lib/api";
import { EvidenceViewer } from "./case-workflow";
import { factualResult } from "./factual-case";

type ActionHandler = (action: CaseAction, role: string, payload: JsonRecord, confirmation: string) => Promise<boolean>;
const ownerRoles = ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"];
const actions: { value: CaseAction; label: string }[] = [
  { value: "review_summary", label: "Review factual summary" },
  { value: "start_investigation", label: "Start investigation" },
  { value: "record_investigation", label: "Record investigation findings" },
  { value: "record_correction", label: "Record authorised corrective work" },
  { value: "complete_work", label: "Mark investigation work complete" },
  { value: "record_reprocessing", label: "Record reprocessing outcome" },
  { value: "record_validation", label: "Record target posting validation" },
  { value: "finish_resolution", label: "Finish resolution record" },
];
const dimensions = ["amount_currency", "company", "accounts", "source_target_reference"];
export function FactualHumanWorkflow({ detail, roles, workspaceId, token, disabled, onAction, onProofSaved, onProofBusy, syntheticWorkspace }: { detail: CaseDetail; roles: string[]; workspaceId: string; token: string; disabled: boolean; onAction: ActionHandler; onProofSaved: () => void; onProofBusy: (busy: boolean) => void; syntheticWorkspace?: boolean }) {
  const [action, setAction] = useState<CaseAction>("review_summary");
  const [actingRole, setActingRole] = useState("");
  const [decision, setDecision] = useState("Accepted");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [entryIds, setEntryIds] = useState<string[]>([]);
  const [proofIds, setProofIds] = useState<string[]>([]);
  const [viewedIds, setViewedIds] = useState<string[]>([]);
  const [activeProof, setActiveProof] = useState("");
  const [provenance, setProvenance] = useState<"" | "synthetic" | "user_supplied">("");
  const [file, setFile] = useState<File | null>(null);
  const [savingProof, setSavingProof] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [authority, setAuthority] = useState(false);
  const [error, setError] = useState("");
  const [checks, setChecks] = useState(dimensions.map(dimension => ({ dimension, expected: "", observed: "", result: "", reason: "" })));
  const request = useRef<AbortController | null>(null);
  const result = factualResult(detail);
  const entries = result?.extraction?.entries || [];
  const published = detail.runs.find(run => run.id === detail.case.requested_run_id && run.state === "failed" && run.attempt_id === detail.case.current_attempt_id && run.input_revision === detail.case.input_revision) || detail.runs.find(run => run.id === detail.case.published_run_id && run.state === "succeeded" && run.attempt_id === detail.case.current_attempt_id && run.input_revision === detail.case.input_revision);
  const eligibleRoles = action === "record_validation" ? roles.filter(role => ["validator", "process_owner"].includes(role)) : roles.filter(role => ownerRoles.includes(role));
  const role = eligibleRoles.includes(actingRole) ? actingRole : eligibleRoles[0] || "";
  const proof = detail.evidence.filter(item => item.kind === "human_proof" || item.kind === "proof" || item.kind === "human_record");
  const selectedProof = proof.find(item => item.id === activeProof);
  const blocked = disabled || savingProof;
  const review = action === "review_summary";
  const start = action === "start_investigation";
  const hasCorrection = detail.milestones.some(item => item.kind === "correction" && item.work_cycle === detail.case.work_cycle);
  const completedWork = detail.milestones.find(item => item.kind === "work_completion" && item.work_cycle === detail.case.work_cycle);
  const completedDetails = completedWork?.details && typeof completedWork.details === "object" ? completedWork.details as JsonRecord : {};
  const completedActionKind = completedDetails.action_kind;
  const needsProof = !review && !start;
  const currentReview = (detail.reviews || []).some(review => review.run_id === published?.id);
  const allowed = (choice: CaseAction) => {
    if (choice === "review_summary") return Boolean(published) && roles.some(role => ownerRoles.includes(role));
    if (choice === "start_investigation") return currentReview && ["created", "owner_notified"].includes(detail.case.status) && roles.some(role => ownerRoles.includes(role));
    if (choice === "record_validation") return detail.case.status === "document_reprocessed" && roles.some(role => ["validator", "process_owner"].includes(role));
    if (!roles.some(role => ownerRoles.includes(role))) return false;
    if (["record_investigation", "record_correction", "complete_work"].includes(choice)) return detail.case.status === "in_progress";
    if (choice === "record_reprocessing") return detail.case.status === "complete";
    return detail.case.status === "document_reprocessed";
  };
  useEffect(() => { setConfirmed(false); setAuthority(false); setError(""); setFields({}); setEntryIds([]); setProofIds([]); setViewedIds([]); }, [action, detail.case.id]);
  useEffect(() => { setConfirmed(false); setAuthority(false); }, [detail.case.version]);
  useEffect(() => () => request.current?.abort(), []);
  function field(name: string, label: string, options: { required?: boolean; type?: string; textarea?: boolean } = {}) {
    const common = { value: fields[name] || "", required: options.required !== false, disabled: blocked, maxLength: 5000, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { setFields(previous => ({ ...previous, [name]: event.target.value })); setConfirmed(false); } };
    return <label key={name}>{label}{options.textarea ? <textarea {...common} rows={3} /> : <input {...common} type={options.type || "text"} />}</label>;
  }
  async function upload() {
    if (!file || !role || !provenance || blocked) return;
    const controller = new AbortController(); request.current = controller; setSavingProof(true); onProofBusy(true); setError("");
    try { const saved = await saveProof(detail.case.id, workspaceId, role, file, token, controller.signal, provenance); if (!controller.signal.aborted) { setFile(null); setActiveProof(String(saved.evidence_id || saved.id || "")); onProofSaved(); } }
    catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Proof could not be saved."); }
    finally { if (!controller.signal.aborted) { setSavingProof(false); onProofBusy(false); } }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!confirmed || blocked || !role || !allowed(action)) return;
    setError("");
    try {
      if (proofIds.some(id => !viewedIds.includes(id))) throw new Error("Open each selected proof attachment before confirming this record.");
      if (needsProof && !proofIds.length) throw new Error("Select the saved evidence supporting this milestone.");
      const gaps = (fields.gaps || "").split("\n").map(item => item.trim()).filter(Boolean);
      if (review && decision === "Insufficient" && !gaps.length) throw new Error("Record at least one missing fact or evidence gap for an insufficient summary.");
      let payload: JsonRecord;
      if (review) {
        if (decision === "Corrected" && (!fields.explanation?.trim() || (!entryIds.length && !proofIds.length))) throw new Error("Explain the corrected fact and select its supporting extracted entries or saved proof.");
        payload = { run_id: published?.id, decision, reason: fields.reason, findings: { explanation: fields.explanation || "", gaps, entry_ids: entryIds, proof_ids: proofIds } };
      } else if (start) payload = { reason: fields.reason, investigation_scope: fields.scope };
      else {
        payload = { human_confirmed: true, findings: fields.findings, action_or_no_change: fields.action_or_no_change, outcome: fields.outcome, scope: fields.scope, gaps, proof_ids: proofIds, ...(fields.proof_reuse_reason?.trim() ? { proof_reuse_reason: fields.proof_reuse_reason.trim() } : {}) };
        if (action === "complete_work" || action === "finish_resolution") {
          if (!["corrective_work", "no_change"].includes(fields.action_kind || "")) throw new Error("Choose whether this work included a corrective change or completed without a change.");
          payload.action_kind = fields.action_kind;
        }
        if (action === "record_correction") { if (!authority) throw new Error("Confirm your authority for the corrective work being recorded."); payload = { ...payload, target_change_authority: true, target_system: fields.target_system, target_object: fields.target_object, occurred_at: new Date(fields.occurred_at).toISOString() }; }
        if (action === "finish_resolution") payload.occurred_at = new Date(fields.occurred_at).toISOString();
        if (action === "record_reprocessing") { if (fields.chronology_confirmed !== "yes") throw new Error("Confirm that evidence establishes this successful attempt occurred after the original attempt."); payload = { ...payload, result: "successful", chronology_confirmed: true, attempt_key: fields.attempt_key, processing_order: Number(fields.processing_order), processing_at: new Date(fields.processing_at).toISOString(), occurred_at: new Date(fields.processing_at).toISOString(), target_document_reference: fields.target_document_reference, correction_applicable: fields.correction_applicable === "yes" }; }
        if (action === "record_validation") {
          if (checks.some(check => !check.result || !check.expected.trim() || !check.observed.trim() || (check.result !== "passed" && !check.reason.trim()))) throw new Error("Record each expected and observed comparison and explain any failure or gap.");
          payload = { ...payload, status: checks.some(check => check.result === "failed") ? "failed" : "passed", checks, occurred_at: new Date(fields.occurred_at).toISOString() };
        }
      }
      if (await onAction(action, role, payload, review ? "Factual review saved." : "Human investigation record saved.")) setConfirmed(false);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review the fields before saving."); }
  }
  return <section className="workflow-action"><h3>Human review and investigation</h3><p>Review observed facts, record what you investigated and preserve supporting evidence at each milestone.</p>{!currentReview && <p className="field-help">Save a review of the current summary or failure before starting investigation.</p>}<form className="workflow-form" onSubmit={submit}>
    {error && <p className="inline-error" role="alert">{error}</p>}
    <label>Record to add<select value={action} disabled={blocked} onChange={event => setAction(event.target.value as CaseAction)}>{actions.map(item => <option key={item.value} value={item.value} disabled={!allowed(item.value)}>{item.label}{!allowed(item.value) ? " (unavailable)" : ""}</option>)}</select></label>
    <label>Acting role<select value={role} disabled={blocked} onChange={event => { setActingRole(event.target.value); setConfirmed(false); }}>{!eligibleRoles.length && <option value="">No permitted role</option>}{eligibleRoles.map(item => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>
    {review ? <><label>Review decision<select value={decision} disabled={blocked} onChange={event => { setDecision(event.target.value); setConfirmed(false); }}><option disabled={!result?.summary && !result?.title}>Accepted</option><option>Corrected</option><option>Insufficient</option></select></label>{field("reason", "Review explanation", { textarea: true })}{decision !== "Accepted" && <>{field("explanation", "Corrected facts or missing evidence", { textarea: true })}{field("gaps", "Remaining gaps (one per line)", { textarea: true, required: decision === "Insufficient" })}<fieldset className="proof-panel"><legend>Supporting extracted entries</legend>{entries.map(entry => <label className="attestation" key={entry.entry_id}><input type="checkbox" checked={entryIds.includes(entry.entry_id)} disabled={blocked} onChange={event => { setEntryIds(previous => event.target.checked ? [...previous, entry.entry_id] : previous.filter(id => id !== entry.entry_id)); setConfirmed(false); }} /><span>{entry.source_id} · v{entry.source_version} · lines {entry.source_span.line_start}–{entry.source_span.line_end}<small>{entry.raw_text}</small></span></label>)}</fieldset></>}</> : start ? <>{field("reason", "Why investigation is needed", { textarea: true })}{field("scope", "Investigation scope and evidence to examine", { textarea: true })}<p className="field-help">Starting investigation records ownership of the work. Authority is checked separately when corrective work is recorded.</p></> : <>{field("findings", "What you found and supporting evidence", { textarea: true })}{field("action_or_no_change", "Action taken, or why no change was needed", { textarea: true })}{field("outcome", "Observed outcome", { textarea: true })}{field("scope", "Systems, documents and scope covered", { textarea: true })}{field("gaps", "Remaining gaps (one per line; leave blank if none)", { textarea: true, required: false })}</>}
    {(action === "complete_work" || action === "finish_resolution") && <><label>Type of completed work<select required value={fields.action_kind || ""} disabled={blocked} onChange={event => { setFields(previous => ({ ...previous, action_kind: event.target.value })); setConfirmed(false); }}><option value="">Choose the recorded outcome</option><option value="corrective_work" disabled={!hasCorrection || (action === "finish_resolution" && completedActionKind !== "corrective_work")}>Authorised corrective work was recorded</option><option value="no_change" disabled={hasCorrection || (action === "finish_resolution" && completedActionKind !== "no_change")}>Investigation completed without a corrective change</option></select></label><p className="field-help">{action === "finish_resolution" ? "The resolution must use the same work type as the completed investigation record." : hasCorrection ? "This work cycle includes a recorded correction. Completion must retain that change and its authority-backed proof." : "To complete corrective work, first record the authorised change and its proof. A no-change outcome must explain why a change was unnecessary."}</p></>}
    {action === "finish_resolution" && field("occurred_at", "When resolution was confirmed", { type: "datetime-local" })}
    {action === "record_correction" && <><div className="workflow-field-grid">{field("target_system", "System changed")}{field("target_object", "Object changed")}{field("occurred_at", "When the change occurred", { type: "datetime-local" })}</div><label className="attestation"><input type="checkbox" required checked={authority} disabled={blocked} onChange={event => { setAuthority(event.target.checked); setConfirmed(false); }} /><span>I had authority for this specific target change and have supplied its proof.</span></label></>}
    {action === "record_reprocessing" && <><div className="workflow-field-grid">{field("attempt_key", "Observed reprocessing attempt")}{field("processing_order", "Confirmed processing order", { type: "number" })}{field("processing_at", "Actual processing time", { type: "datetime-local" })}{field("target_document_reference", "Observed target document reference")}</div><label>Correction applicability<select required value={fields.correction_applicable || ""} disabled={blocked} onChange={event => { setFields(previous => ({ ...previous, correction_applicable: event.target.value })); setConfirmed(false); }}><option value="">Choose a finding</option><option value="yes">Recorded corrective work applies to this attempt</option><option value="no">No corrective work applied; explanation is above</option></select></label><label className="attestation"><input required type="checkbox" disabled={blocked} checked={fields.chronology_confirmed === "yes"} onChange={event => { setFields(previous => ({ ...previous, chronology_confirmed: event.target.checked ? "yes" : "" })); setConfirmed(false); }} /><span>I verified that the evidence shows a successful attempt after the original attempt.</span></label></>}
    {action === "record_validation" && <>{field("occurred_at", "When validation was performed", { type: "datetime-local" })}{checks.map((check, index) => <fieldset className="validation-check" key={check.dimension}><legend>{check.dimension.replaceAll("_", " ")}</legend>{(["expected", "observed", "reason"] as const).map(key => <label key={key}>{key === "reason" ? "Failure or gap explanation" : key === "expected" ? "Expected (human-supplied)" : "Observed in proof"}<textarea required={key !== "reason" || check.result !== "passed"} value={check[key]} disabled={blocked} onChange={event => { setChecks(previous => previous.map((item, i) => i === index ? { ...item, [key]: event.target.value } : item)); setConfirmed(false); }} /></label>)}<label>Comparison outcome<select required value={check.result} disabled={blocked} onChange={event => { setChecks(previous => previous.map((item, i) => i === index ? { ...item, result: event.target.value } : item)); setConfirmed(false); }}><option value="">Choose outcome</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="not_applicable">Not applicable (explain why)</option></select></label></fieldset>)}</>}
    {!start && <fieldset className="proof-panel"><legend>Saved supporting proof {needsProof ? "(required)" : "(optional)"}</legend><label>Upload human evidence<input type="file" disabled={blocked} onChange={event => setFile(event.target.files?.[0] || null)} /></label><label>Proof provenance<select value={provenance} disabled={blocked} onChange={event => setProvenance(event.target.value as typeof provenance)}><option value="">Choose evidence provenance</option><option value="user_supplied" disabled={syntheticWorkspace !== false}>Real / user-supplied evidence{syntheticWorkspace !== false ? " (unavailable in this workspace)" : ""}</option><option value="synthetic">Synthetic example or test evidence</option></select></label><button className="button button-secondary" type="button" disabled={blocked || !file || !role || !provenance} onClick={upload}>{savingProof ? "Saving proof…" : "Store proof attachment"}</button>{proof.map(item => <div className="proof-choice" key={String(item.id)}><label className="attestation"><input type="checkbox" checked={proofIds.includes(String(item.id))} disabled={blocked} onChange={event => { setProofIds(previous => event.target.checked ? [...previous, String(item.id)] : previous.filter(id => id !== item.id)); setActiveProof(String(item.id)); setConfirmed(false); }} /><span>{String(item.filename)} · v{String(item.source_version)}</span></label><button className="button button-quiet" type="button" onClick={() => setActiveProof(String(item.id))}>Inspect</button></div>)}{needsProof && field("proof_reuse_reason", "If reusing proof from another milestone or attempt, explain its applicability", { textarea: true, required: false })}{selectedProof && <EvidenceViewer evidence={selectedProof} workspaceId={workspaceId} token={token} onViewed={id => setViewedIds(previous => [...new Set([...previous, id])])} />}</fieldset>}
    <label className="attestation"><input required type="checkbox" checked={confirmed} disabled={blocked} onChange={event => setConfirmed(event.target.checked)} /><span>I reviewed this record and its evidence. The findings are my attributed human assessment.</span></label><button className="button button-primary" type="submit" disabled={blocked || !confirmed || !role || !allowed(action)}>Save human record</button>
  </form></section>;
}
