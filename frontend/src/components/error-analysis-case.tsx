"use client";

import type { CaseDetail, FactualEntry, FactualStatement, JsonRecord } from "@/lib/api";

type Route = { category_id: string; owner_role: string; route_kind: string; escalation_role: string; steps: { order: number; step_id: string; description: string; required_role?: string }[] };
type Result = { outcome: string; extraction?: { entries: FactualEntry[] }; analysis?: { category_id: string; cause_hypothesis: string; confidence: string; gaps: string[]; competing_explanations: string[]; route: Route }; case_content?: { title: FactualStatement; what_happened: FactualStatement[]; document_context: FactualStatement[]; original_log_evidence: FactualStatement[]; open_questions: FactualStatement[]; related_cases: { case_id: string; matching_details: string[]; differing_details: string[] }[] }; limitations: string[]; failure_reason?: string };

function isRecord(value: unknown): value is JsonRecord { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function result(detail: CaseDetail): Result | null {
  const candidate = detail.error_analysis_result ?? detail.case.error_analysis_result;
  return isRecord(candidate) && candidate.result_kind === "error_analysis" ? candidate as Result : null;
}
function label(value: string) { return value.replaceAll("_", " ").replace(/\b\w/g, char => char.toUpperCase()); }
function facts(items: FactualStatement[]) { return <ul className="factual-statements">{items.map((item, index) => <li key={index}>{item.text}{item.supporting_entry_ids.length > 0 && <small className="field-help"> Original log: {item.supporting_entry_ids.join(", ")}</small>}</li>)}</ul>; }

export function isErrorAnalysisCase(detail: CaseDetail): boolean { return detail.case.workflow_version === "error-analysis-v1"; }

export function ErrorAnalysisCaseContent({ detail }: { detail: CaseDetail }) {
  const value = result(detail);
  const content = value?.case_content;
  const analysis = value?.analysis;
  if (!value || !content || !analysis) return <section className="detail-section"><h3>Error Analysis</h3><p className="section-intro">{value?.failure_reason || "The Error Analysis case has not been published yet. The original logs remain available."}</p></section>;
  return <>
    <section className="detail-section factual-brief"><h3>{content.title.text}</h3><p className="field-help">{label(analysis.category_id)} · proposed owner: {label(analysis.route.owner_role)} · human validation required</p><h4>What happened</h4>{facts(content.what_happened)}<h4>Document and processing context</h4>{content.document_context.length ? facts(content.document_context) : <p className="field-help">No additional context was supplied in the original log.</p>}<h4>Evidence from the original log</h4>{facts(content.original_log_evidence)}</section>
    <section className="detail-section"><h3>Error assessment</h3><p><strong>Category:</strong> {label(analysis.category_id)}</p><p><strong>Cause hypothesis:</strong> {analysis.cause_hypothesis}</p><p><strong>Confidence:</strong> {label(analysis.confidence)}. This is pending human validation.</p>{analysis.competing_explanations.length > 0 && <><h4>Competing explanations</h4><ul>{analysis.competing_explanations.map((item, index) => <li key={index}>{item}</li>)}</ul></>}{analysis.gaps.length > 0 && <><h4>Evidence gaps</h4><ul>{analysis.gaps.map((item, index) => <li key={index}>{item}</li>)}</ul></>}</section>
    <section className="detail-section"><h3>Required next steps</h3><p className="field-help">Configured route · {label(analysis.route.route_kind)} · escalation: {label(analysis.route.escalation_role)}</p><ol>{analysis.route.steps.map(step => <li key={step.step_id}>{step.description}</li>)}</ol></section>
    <section className="detail-section"><h3>Similar earlier cases</h3>{content.related_cases.length ? content.related_cases.map(item => <article className="related-case" key={item.case_id}><a href={`/?case_id=${encodeURIComponent(item.case_id)}`}>Open reviewed case {item.case_id}</a><p><strong>Similar:</strong> {item.matching_details.join("; ")}</p><p><strong>Different:</strong> {item.differing_details.join("; ")}</p></article>) : <p className="field-help">No authorised similar case is cited for this case.</p>}</section>
    <section className="detail-section"><h3>Open questions and blockers</h3>{content.open_questions.length ? facts(content.open_questions) : <p className="field-help">No additional blocker is recorded.</p>}{value.limitations.length > 0 && <ul className="factual-limitations">{value.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}</section>
  </>;
}
