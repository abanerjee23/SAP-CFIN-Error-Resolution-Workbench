"use client";

import { useEffect, useState, type FormEvent } from "react";
import { getMembers, type CaseAction, type CaseDetail, type JsonRecord, type WorkspaceMember } from "@/lib/api";
import { formatTime } from "./case-worklist";

const ownerRoles = ["process_owner", "master_data_owner", "mapping_owner", "finance_owner"];
const roleLabel = (role: string) => role.replaceAll("_", " ");
const text = (item: unknown) => typeof item === "string" ? item : "";
const dayAfter = (days: number) => { const date = new Date(); date.setUTCDate(date.getUTCDate() + days); return date.toISOString().slice(0, 10); };
export type IntakeControlHandler = (action: "complete_identity" | "review_attempt_order" | "link_case", reason: string, payload: JsonRecord) => Promise<boolean>;

export function CaseControls({ detail, roles, workspaceId, token, disabled, onAction, onIntakeControl }: { detail: CaseDetail; roles: string[]; workspaceId: string; token: string; disabled: boolean; onAction: (action: CaseAction, role: string, payload: JsonRecord, confirmation: string) => Promise<boolean>; onIntakeControl: IntakeControlHandler }) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [memberError, setMemberError] = useState("");
  const [action, setAction] = useState<CaseAction>("assign");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [saveOwnerRule, setSaveOwnerRule] = useState(false);
  const [ownerRuleReviewDue, setOwnerRuleReviewDue] = useState(() => dayAfter(90));
  const [controlConfirmed, setControlConfirmed] = useState(false);
  const [localError, setLocalError] = useState("");
  const [identity, setIdentity] = useState<Record<string, string>>({});
  const [ordered, setOrdered] = useState<string[]>([]);
  const [control, setControl] = useState<"complete_identity" | "review_attempt_order" | "link_case">("complete_identity");
  const canOwn = roles.some(item => ownerRoles.includes(item));
  const canManage = roles.includes("process_owner");
  const factual = detail.case.workflow_version === "log-only-v1";
  const routingContext = (detail.case.business_context as JsonRecord | undefined)?.routing_context && typeof (detail.case.business_context as JsonRecord).routing_context === "object" ? (detail.case.business_context as JsonRecord).routing_context as JsonRecord : {};
  const businessContext = detail.case.business_context && typeof detail.case.business_context === "object" && !Array.isArray(detail.case.business_context) ? detail.case.business_context as JsonRecord : {};
  const ruleRole = factual ? text(detail.owner_rule?.owner_role) || fields.owner_role || "process_owner" : detail.case.category === "missing_target_gl_master_data" ? "master_data_owner" : detail.case.category === "missing_gl_mapping" ? "mapping_owner" : "";
  const selectedRole = fields.owner_role || (factual ? "process_owner" : "master_data_owner");
  const selectedMember = members.find(member => member.user_id === fields.assigned_user_id && member.roles.includes(selectedRole));
  const currentPublishedRun = detail.runs.find(run => run.id === detail.case.published_run_id && run.state === "succeeded" && run.attempt_id === detail.case.current_attempt_id && run.input_revision === detail.case.input_revision);
  const contextScope = { source_system: fields.context_source_system ?? text(routingContext.source_system), target_system: fields.context_target_system ?? text(routingContext.target_system), interface: fields.context_interface ?? text(routingContext.interface), company_code: fields.context_company_code ?? text(routingContext.company_code) };
  const canSaveOwnerRule = factual ? canManage && Boolean(selectedMember) && Boolean(contextScope.interface && contextScope.company_code && (contextScope.source_system || contextScope.target_system)) : canManage && detail.case.analysis_status === "available" && Boolean(currentPublishedRun) && Boolean(ruleRole) && selectedRole === ruleRole && Boolean(selectedMember) && [detail.case.target_system, detail.case.target_client, detail.case.interface, businessContext.company_code, businessContext.chart_of_accounts].every(item => Boolean(text(item)));
  const ruleScope = [text(detail.case.target_system), text(detail.case.target_client), text(detail.case.interface), text(businessContext.company_code), text(businessContext.chart_of_accounts)].join(" · ");
  const ownerRuleVersion = Number(detail.owner_rule?.version || 0);
  useEffect(() => {
    setMembers([]); setMemberError("");
    if (!roles.includes("process_owner")) return;
    const controller = new AbortController();
    getMembers(workspaceId, token, controller.signal).then(data => { if (!controller.signal.aborted) setMembers(data); }).catch(error => { if (!controller.signal.aborted) setMemberError(error instanceof Error ? error.message : "Members could not be loaded."); });
    return () => controller.abort();
  }, [roles.join(","), workspaceId, token]);
  useEffect(() => { setConfirmed(false); setControlConfirmed(false); setFields({}); setLocalError(""); }, [action, detail.case.version]);
  useEffect(() => {
    const keys = ["source_system", "source_client", "source_company_code", "fiscal_year", "document_number", "target_system", "target_client", "interface"];
    setIdentity(Object.fromEntries(keys.map(key => [key, text(detail.case[key])])));
    setOrdered([...detail.attempts].sort((a, b) => Number(a.processing_order || 0) - Number(b.processing_order || 0)).map(item => text(item.id)));
  }, [detail.case.version]);
  useEffect(() => { setConfirmed(false); setControlConfirmed(false); }, [JSON.stringify(fields)]);
  useEffect(() => { setSaveOwnerRule(false); setOwnerRuleReviewDue(dayAfter(90)); setConfirmed(false); }, [action, detail.case.id, detail.case.version, detail.case.category, ownerRuleVersion, ruleScope, fields.owner_role, fields.assigned_user_id, roles.join(","), canSaveOwnerRule]);
  function field(name: string, label: string, type = "text") { return <label>{label}<input type={type} required value={fields[name] || ""} onChange={event => setFields(previous => ({ ...previous, [name]: event.target.value }))} disabled={disabled} maxLength={2000} /></label>; }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!confirmed || disabled) return;
    setLocalError("");
    const reason = fields.reason?.trim() || "";
    try {
      let payload: JsonRecord = { reason };
      if (action === "assign") {
        const saveRule = canSaveOwnerRule && saveOwnerRule;
        if (saveOwnerRule && !canSaveOwnerRule) throw new Error("Complete the owner scope and choose an eligible member before saving a default.");
        if (saveRule && (ownerRuleReviewDue < dayAfter(1) || ownerRuleReviewDue > dayAfter(90))) throw new Error("Choose a review date after today and within 90 days.");
        payload = { ...payload, assigned_user_id: fields.assigned_user_id || null, owner_role: selectedRole, save_owner_rule: saveRule, ...(saveRule ? { expected_owner_rule_version: ownerRuleVersion, owner_rule_review_due: ownerRuleReviewDue, ...(factual ? { context: Object.fromEntries(Object.entries(contextScope).filter(([, value]) => value.trim())), review_due: ownerRuleReviewDue } : {}) } : {}) };
      }
      if (action === "owner_rule") payload = { ...payload, assigned_user_id: null, owner_role: ruleRole, expected_owner_rule_version: ownerRuleVersion };
      if (action === "priority") payload.priority = fields.priority || detail.case.priority;
      if (action === "due_date") { const date = new Date(fields.due_at || ""); if (Number.isNaN(date.getTime())) throw new Error("Enter a valid due date in your local timezone."); payload.due_at = date.toISOString(); }
      if (action === "resume" && factual && !detail.case.work_started_at) payload.investigation_scope = fields.investigation_scope || "";
      if (action === "resume" && !factual) { payload.target_change_authority = true; payload.approved_attributes = fields.approved_attributes || ""; }
      if (action === "reopen") payload.status = fields.status || "in_progress";
      const role = roles.includes("process_owner") ? "process_owner" : roles.find(item => ownerRoles.includes(item)) || "";
      const saved = await onAction(action, role, payload, action === "owner_rule" ? "Default owner rule cleared." : "Case control saved."); if (saved) setConfirmed(false);
    } catch (error) { setLocalError(error instanceof Error ? error.message : "The action fields could not be read."); }
  }
  function move(index: number, direction: number) { setControlConfirmed(false); setOrdered(previous => { const next = [...previous]; const target = index + direction; if (target < 0 || target >= next.length) return previous; [next[index], next[target]] = [next[target], next[index]]; return next; }); }
  async function submitControl(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!controlConfirmed || disabled) return;
    const payload: JsonRecord = control === "complete_identity" ? { identity: { ...identity, workspace_id: workspaceId } } : control === "review_attempt_order" ? { ordered_attempt_ids: ordered } : { target_case_id: fields.target_case_id, expected_target_version: Number(fields.expected_target_version) };
    const saved = await onIntakeControl(control, fields.reason?.trim() || "", payload); if (saved) setControlConfirmed(false);
  }
  const choices: { value: CaseAction; label: string; available: boolean }[] = [
    { value: "assign", label: "Assign or reassign owner", available: canManage }, { value: "priority", label: "Change priority", available: canManage }, { value: "due_date", label: "Change due date", available: canManage },
    { value: "owner_rule", label: "Clear default owner", available: canManage && detail.owner_rule?.active === true && Boolean(ruleRole) },
    { value: "block", label: "Block work", available: canOwn && ["created", "owner_notified", "in_progress"].includes(detail.case.status) }, { value: "resume", label: "Resume work", available: canOwn && detail.case.status === "blocked" }, { value: "reopen", label: "Reopen work cycle", available: canManage },
  ];
  return <>
    <section className="workflow-action"><h3>Ownership and work controls</h3><p>Review the current version before saving. Each change records your account, role and reason.</p>
      {detail.owner_rule ? <p className="field-help">Current default: {text(detail.owner_rule.assigned_user_id)} · {roleLabel(text(detail.owner_rule.owner_role))}. {factual ? `Context: ${Object.values((detail.owner_rule.context as JsonRecord) || {}).join(" · ")}` : `Legacy cause: ${roleLabel(text(detail.owner_rule.category))}`}. Review by {text(detail.owner_rule.review_due) || "not recorded"} · version {ownerRuleVersion} · {detail.owner_rule.active === true ? "active" : "inactive"}.</p> : <p className="field-help">No default owner rule is configured for this scope.</p>}
      {!canOwn ? <p className="field-help">A process owner or assigned owner can change work controls.</p> : <form className="workflow-form" onSubmit={submit}>
        {memberError && <p className="inline-error" role="alert">{memberError}</p>}{localError && <p className="inline-error" role="alert">{localError}</p>}
        <label>Control<select value={action} disabled={disabled} onChange={event => setAction(event.target.value as CaseAction)}>{choices.filter(item => item.value !== "owner_rule" || item.available).map(item => <option key={item.value} value={item.value} disabled={!item.available}>{item.label}{!item.available ? " (unavailable)" : ""}</option>)}</select></label>
        {action === "owner_rule" && <p className="field-help">Clearing stops future automatic assignments for this default scope. The current case keeps its assigned owner.</p>}
        {action === "assign" ? <><label>Owner role<select value={selectedRole} onChange={event => { setFields(previous => ({ ...previous, owner_role: event.target.value, assigned_user_id: "" })); setConfirmed(false); }} disabled={disabled}>{ownerRoles.map(role => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></label><label>Workspace member<select value={fields.assigned_user_id || ""} onChange={event => setFields(previous => ({ ...previous, assigned_user_id: event.target.value }))} disabled={disabled || Boolean(memberError)}><option value="">Leave unassigned</option>{members.filter(member => member.roles.includes(selectedRole)).map(member => <option key={member.user_id} value={member.user_id}>{member.user_id}</option>)}</select></label><p className="field-help">Members are identified by their account ID. The server rechecks the selected member and role.</p></> : action === "priority" ? <label>Priority<select value={fields.priority || detail.case.priority} disabled={disabled} onChange={event => setFields(previous => ({ ...previous, priority: event.target.value }))}><option value="P3">P3 · High</option><option value="P2">P2 · Medium</option><option value="P1">P1 · Low</option></select></label> : action === "due_date" ? field("due_at", "New due date (your local timezone)", "datetime-local") : action === "resume" && factual && !detail.case.work_started_at ? field("investigation_scope", "Investigation scope") : action === "resume" && !factual ? field("approved_attributes", "Approved target attributes and scope") : action === "reopen" ? <label>Reopened work state<select value={fields.status || "in_progress"} disabled={disabled} onChange={event => setFields(previous => ({ ...previous, status: event.target.value }))}><option value="in_progress">In progress</option><option value="blocked">Blocked</option></select></label> : null}
        {action === "assign" && factual && <details><summary>Default owner scope (optional)</summary><p className="field-help">Enter the exact system, interface and company scope for future assignment. This administrative context is separate from observed log facts.</p><div className="workflow-field-grid">{Object.entries(contextScope).map(([key, value]) => <label key={key}>{roleLabel(key)}<input value={value} disabled={disabled} maxLength={150} onChange={event => { setFields(previous => ({ ...previous, [`context_${key}`]: event.target.value })); setConfirmed(false); }} /></label>)}</div></details>}
        {action === "assign" && canSaveOwnerRule && <>
          <label className="attestation"><input type="checkbox" checked={saveOwnerRule} disabled={disabled} onChange={event => { setSaveOwnerRule(event.target.checked); setConfirmed(false); }} /><span>{factual ? "Use as default owner for this exact context" : "Use as default owner for this legacy cause, target and company"}</span></label>
          {saveOwnerRule && <><p className="field-help">Future matching cases will use account {fields.assigned_user_id} as {roleLabel(selectedRole)}. {factual ? `Context: ${Object.values(contextScope).filter(Boolean).join(" · ")}.` : `Legacy cause: ${roleLabel(text(detail.case.category))}. Target: ${text(detail.case.target_system)}/${text(detail.case.target_client)} · company ${text(businessContext.company_code)} · interface ${text(detail.case.interface)} · chart ${text(businessContext.chart_of_accounts)}.`} Saving records your account and reason. Automatic assignment requires the rule to remain active, in date and applicable.</p><label>Review default by<input type="date" required min={dayAfter(1)} max={dayAfter(90)} value={ownerRuleReviewDue} disabled={disabled} onChange={event => { setOwnerRuleReviewDue(event.target.value); setConfirmed(false); }} /></label></>}
        </>}
        <label>Reason<textarea required rows={3} maxLength={2000} disabled={disabled} value={fields.reason || ""} onChange={event => setFields(previous => ({ ...previous, reason: event.target.value }))} /></label>
        <label className="attestation"><input type="checkbox" checked={confirmed} required disabled={disabled} onChange={event => setConfirmed(event.target.checked)} /><span>{action === "resume" && !factual ? "I confirm the approved target scope and my authority to resume this simulated work." : action === "owner_rule" ? "I reviewed the default owner scope and confirm clearing this default." : "I reviewed the current case and confirm this change."}</span></label><button className="button button-primary" type="submit" disabled={disabled || !confirmed || !choices.find(item => item.value === action)?.available}>{action === "owner_rule" ? "Clear default" : "Save control"}</button>
      </form>}
    </section>
    <section className="workflow-action"><h3>Simulated notifications</h3><p>Delivery records refer to the current assignment. Delivery success does not confirm work or analysis quality.</p>{(detail.notifications || []).length ? <ul className="notification-list">{detail.notifications?.map(item => <li key={text(item.id)}><div><strong>{text(item.state) || "Pending"}</strong><span>{formatTime(text(item.created_at) || null)}</span>{Boolean(item.error_code) && <p>{text(item.error_code)}</p>}</div>{canManage && item.state === "failed" && <button className="button button-secondary" type="button" disabled={disabled} onClick={() => onAction("retry_notification", "process_owner", { notification_id: item.id, reason: "Process owner requested simulated delivery retry." }, "Simulated notification retry requested.")}>Retry delivery</button>}</li>)}</ul> : <p className="field-help">No delivery record has been created.</p>}</section>
    {canManage && <section className="workflow-action"><h3>Document identity and attempt order</h3><p>Complete missing identity, confirm the sequence or link a provisional case. Original evidence and earlier history remain preserved.</p><form className="workflow-form" onSubmit={submitControl}>
      <label>Intake decision<select value={control} disabled={disabled} onChange={event => { setControl(event.target.value as typeof control); setControlConfirmed(false); setFields({}); }}><option value="complete_identity">Complete document identity</option><option value="review_attempt_order">Review attempt order</option><option value="link_case">Link provisional case</option></select></label>
      {control === "complete_identity" ? <div className="workflow-field-grid">{Object.entries(identity).map(([key, data]) => <label key={key}>{roleLabel(key)}<input required maxLength={150} value={data} disabled={disabled || Boolean(detail.case[key])} onChange={event => { setIdentity(previous => ({ ...previous, [key]: event.target.value })); setControlConfirmed(false); }} /></label>)}</div> : control === "review_attempt_order" ? <ol className="attempt-order">{ordered.map((id, index) => { const attempt = detail.attempts.find(item => item.id === id); return <li key={id}><span>{text(attempt?.attempt_key) || id}<small>{formatTime(text(attempt?.processing_at) || null)}</small></span><button type="button" className="button button-quiet" disabled={disabled || index === 0} onClick={() => move(index, -1)} aria-label={`Move ${text(attempt?.attempt_key) || id} earlier`}>Earlier</button><button type="button" className="button button-quiet" disabled={disabled || index === ordered.length - 1} onClick={() => move(index, 1)} aria-label={`Move ${text(attempt?.attempt_key) || id} later`}>Later</button></li>; })}</ol> : <>{field("target_case_id", "Canonical target case ID")}{field("expected_target_version", "Target case version", "number")}</>}
      <label>Decision reason<textarea required rows={3} maxLength={2000} value={fields.reason || ""} disabled={disabled} onChange={event => setFields(previous => ({ ...previous, reason: event.target.value }))} /></label><label className="attestation"><input type="checkbox" checked={controlConfirmed} required disabled={disabled} onChange={event => setControlConfirmed(event.target.checked)} /><span>I verified this identity or sequence against the source evidence and confirm the decision.</span></label><button className="button button-primary" type="submit" disabled={disabled || !controlConfirmed}>Save intake decision</button>
    </form></section>}
  </>;
}
