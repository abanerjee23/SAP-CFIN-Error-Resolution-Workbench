"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { Alert, Badge, Button, Card, Checkbox, FileInput, Group, Modal, MultiSelect, PasswordInput, Select, Stack, Table, Tabs, Text, Textarea, TextInput, Title } from "@mantine/core";
import { getBrowserClient } from "@/lib/supabase";
import { createLogIntake, getCaseDetail, getCasePage, getEvidence, getMembers, getWorkspaces, performCaseAction, saveProof, type CaseAction, type CaseDetail, type CaseSummary, type FactualEntry, type FactualStatement, type JsonRecord, type Workspace, type WorkspaceMember } from "@/lib/api";
import "./workbench.css";

const label = (value: unknown) => String(value ?? "").replaceAll("_", " ");
const message = (error: unknown) => error instanceof Error ? error.message : "The request failed. Please try again.";
const roleLabel = (role: string) => role === "process_owner" ? "RTR Process Owner" : label(role);
const statusLabel = (value: string) => ({ created: "Open", owner_notified: "Open", in_progress: "In progress", blocked: "Blocked", document_reprocessed: "Ready for validation", complete: "Closed" })[value] ?? label(value);
const signal = () => new AbortController().signal;
type Step = { order: number; step_id: string; kind: string; description: string; required_role: string; requires_evidence: boolean };
type Result = { outcome: string; analysis?: { category_id: string; cause_hypothesis: string; gaps: string[]; competing_explanations: string[]; route: { steps: Step[]; owner_role: string } }; extraction?: { entries: FactualEntry[] }; case_content?: { what_happened: FactualStatement[]; document_context: FactualStatement[]; open_questions: FactualStatement[] }; limitations?: string[]; failure_reason?: string };

export function ConnectedWorkbench() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const client = getBrowserClient();
    if (!client) { setError("Configure the Supabase project before signing in."); setReady(true); return; }
    let active = true;
    const { data } = client.auth.onAuthStateChange((_event, next) => { if (active) { setSession(next); setReady(true); } });
    client.auth.getSession().then(({ data, error }) => { if (active) { setSession(data.session); setReady(true); if (error) setError(error.message); } });
    const invalid = () => { setSession(null); setError("Access changed. Sign in again to refresh your workspace access."); };
    window.addEventListener("cfin:access-invalid", invalid);
    return () => { active = false; data.subscription.unsubscribe(); window.removeEventListener("cfin:access-invalid", invalid); };
  }, []);
  async function signIn(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { const client = getBrowserClient(); if (!client) throw new Error("Supabase is not configured."); const { error } = await client.auth.signInWithPassword({ email, password }); if (error) throw error; setPassword(""); } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <div className="workbench-canvas"><div className="workbench-frame">
    <header className="workbench-header"><div className="workbench-brand"><span>AIF Resolution Workbench</span></div><Group><Text size="sm" c="white">{session?.user.email ?? "Connected pilot"}</Text>{session && <Button size="xs" variant="white" onClick={() => getBrowserClient()?.auth.signOut({ scope: "local" })}>Sign out</Button>}</Group></header>
    {!ready ? <Text p="xl">Restoring your session…</Text> : session ? <WorkspaceApp key={session.user.id} session={session} /> : <main className="page-content"><Stack maw={460} mx="auto" py="xl"><Title order={1}>Sign in to your workbench</Title><Text c="dimmed">Upload a log, review the AI brief and keep approvals and resolution evidence together.</Text>{error && <Alert color="red">{error}</Alert>}<form onSubmit={signIn}><Stack><TextInput label="Email" type="email" required value={email} onChange={e => setEmail(e.currentTarget.value)} /><PasswordInput label="Password" required value={password} onChange={e => setPassword(e.currentTarget.value)} /><Button type="submit" color="teal" loading={busy}>Sign in</Button></Stack></form><Text size="sm" c="dimmed">Use your existing workspace account. <a href="/preview">Explore the sample interface</a></Text></Stack></main>}
  </div></div>;
}

function WorkspaceApp({ session }: { session: Session }) {
  const token = session.access_token;
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getWorkspaces(token, controller.signal).then(items => { setWorkspaces(items); setWorkspaceId(previous => items.some(x => x.id === previous) ? previous : items[0]?.id ?? ""); }).catch(error => { if (!controller.signal.aborted) { setWorkspaces([]); setWorkspaceId(""); setError(message(error)); } });
    return () => controller.abort();
  }, [token]);
  const workspace = workspaces.find(x => x.id === workspaceId);
  return <><Group p="lg" justify="space-between"><Select label="Workspace" value={workspaceId} data={workspaces.map(x => ({ value: x.id, label: x.name }))} onChange={value => setWorkspaceId(value ?? "")} allowDeselect={false} /><Badge color={workspace?.synthetic ? "orange" : "teal"}>{workspace?.synthetic ? "Synthetic pilot · no SAP connection" : "Human-controlled workflow"}</Badge></Group>{error && <Alert color="red">{error}</Alert>}{workspace ? <SavedWorkbench key={workspace.id} workspace={workspace} token={token} /> : <Text p="xl">No accessible workspace loaded.</Text>}</>;
}

function SavedWorkbench({ workspace, token }: { workspace: Workspace; token: string }) {
  const [page, setPage] = useState<string | null>("cases");
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [pageNumber, setPageNumber] = useState(1);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  // A retry of the same upload keeps its delivery key, preventing duplicate cases.
  const deliveryKey = useRef("");
  useEffect(() => { const controller = new AbortController(); getCasePage(workspace.id, pageNumber, { workflow_version: "error-analysis-v1", q: query }, token, controller.signal).then(data => { setCases(data.items); setTotal(data.total); setError(""); }).catch(error => { if (!controller.signal.aborted) { setCases([]); setError(message(error)); } }); return () => controller.abort(); }, [workspace.id, token, pageNumber, query, revision]);
  async function upload() {
    setBusy(true); setError("");
    try {
      if (!files.length || files.length > 8 || files.reduce((sum, f) => sum + f.size, 0) > 8192) throw new Error("Choose 1–8 text files, totalling at most 8 KB and 64 lines.");
      const sources = await Promise.all(files.map(async file => { const bytes = new Uint8Array(await file.arrayBuffer()); return { filename: file.name, content_base64: btoa(String.fromCharCode(...bytes)) }; }));
      deliveryKey.current ||= crypto.randomUUID();
      const result = await createLogIntake(workspace.id, deliveryKey.current, workspace.synthetic ? "synthetic" : "user_supplied", sources, token, signal());
      setFiles([]); deliveryKey.current = ""; setRevision(x => x + 1); setSelected(String(result.case_id)); setPage("cases"); setNotice("Original saved. Analysis will appear when the worker completes.");
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <><Tabs value={page} onChange={setPage} className="workbench-tabs" keepMounted={false}><Tabs.List><Tabs.Tab value="about">About</Tabs.Tab><Tabs.Tab value="data">Data</Tabs.Tab><Tabs.Tab value="cases">Case Board</Tabs.Tab></Tabs.List>
    <Tabs.Panel value="about"><main className="page-content"><Title order={1}>From an error log to a reviewed resolution</Title><Text mt="md">Finance and master-data teams spend time translating SAP errors, finding the right owner and following up on changes. This workbench brings the original log, an AI-assisted explanation and the human decisions into one case.</Text><Text mt="md">AI extracts the supplied facts and proposes a maintained route. People approve changes, carry out work in SAP and record posting and validation evidence. This pilot uses synthetic examples; it does not change SAP data.</Text><Button mt="lg" color="teal" onClick={() => setPage("data")}>Upload a log</Button></main></Tabs.Panel>
    <Tabs.Panel value="data"><main className="page-content"><Title order={1}>Create a case</Title><Text c="dimmed" mt="sm">Upload the original text exports. The combined upload can contain up to 8 KB and 64 lines across at most 8 files.</Text><Stack maw={600} mt="xl"><FileInput label="Original logs" multiple accept=".txt,.log,.csv,.tsv" value={files} onChange={next => { setFiles(next); deliveryKey.current = ""; }} disabled={busy} /><Text size="sm">{workspace.synthetic ? "Only use fictional data in this synthetic workspace. SAP outcomes are recorded as simulation evidence." : "Use logs authorised for this workspace."}</Text><Button color="teal" loading={busy} disabled={!files.length || !workspace.roles.includes("process_owner")} onClick={upload}>Save and analyse</Button>{!workspace.roles.includes("process_owner") && <Text size="sm">An RTR Process Owner creates new cases.</Text>}</Stack></main></Tabs.Panel>
    <Tabs.Panel value="cases"><main className="page-content"><Group justify="space-between"><div><Title order={1}>Case Board</Title><Text c="dimmed">{total} saved cases · open a case to review its evidence and next step.</Text></div><Button variant="light" color="teal" onClick={() => setRevision(x => x + 1)}>Refresh</Button></Group><TextInput mt="lg" mb="lg" label="Search cases" value={query} onChange={event => { setQuery(event.currentTarget.value); setPageNumber(1); }} /><Table.ScrollContainer minWidth={750}><Table highlightOnHover><Table.Thead><Table.Tr>{["Case", "Status", "Analysis", "Priority", "Created", "Due"].map(h => <Table.Th key={h}>{h}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{cases.map(c => <Table.Tr key={c.id}><Table.Td><Button variant="subtle" color="teal" onClick={() => setSelected(c.id)} styles={{ label: { whiteSpace: "normal", textAlign: "left" } }}>{c.title}</Button><Text size="xs" c="dimmed">{c.id.slice(0, 8)}</Text></Table.Td><Table.Td>{statusLabel(c.status)}</Table.Td><Table.Td>{label(c.analysis_status)}</Table.Td><Table.Td>{c.priority}</Table.Td><Table.Td>{new Date(c.created_at).toLocaleDateString()}</Table.Td><Table.Td>{c.due_at ? new Date(c.due_at).toLocaleDateString() : "—"}</Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer>{!cases.length && <Text py="xl">No cases match. Upload a log to start a new case.</Text>}<Group mt="lg"><Button variant="default" disabled={pageNumber === 1} onClick={() => setPageNumber(x => x - 1)}>Previous</Button><Text>Page {pageNumber}</Text><Button variant="default" disabled={pageNumber * 25 >= total} onClick={() => setPageNumber(x => x + 1)}>Next</Button></Group></main></Tabs.Panel>
  </Tabs>{error && <Alert color="red" m="lg">{error}</Alert>}{notice && <Alert color="teal" m="lg" withCloseButton onClose={() => setNotice("")}>{notice}</Alert>}<Modal opened={Boolean(selected)} onClose={() => { setSelected(null); setRevision(x => x + 1); }} title="Saved case" size="90%">{selected && <SavedCase key={selected} caseId={selected} workspace={workspace} token={token} />}</Modal></>;
}

function SavedCase({ caseId, workspace, token }: { caseId: string; workspace: Workspace; token: string }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [role, setRole] = useState(workspace.roles[0] ?? "");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<string | null>(null);
  const [reference, setReference] = useState("");
  const [evidenceIds, setEvidenceIds] = useState<string[]>([]);
  const [proof, setProof] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [originals, setOriginals] = useState<Record<string, string>>({});
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [ownerRole, setOwnerRole] = useState<string | null>(null);
  const refresh = useCallback(async (abort: AbortSignal) => { const data = await getCaseDetail(caseId, workspace.id, token, abort); setDetail(data); }, [caseId, workspace.id, token]);
  useEffect(() => { const controller = new AbortController(); refresh(controller.signal).catch(error => { if (!controller.signal.aborted) setError(message(error)); }); return () => controller.abort(); }, [refresh]);
  const analysing = detail?.case.analysis_status === "pending" || detail?.case.analysis_status === "running";
  useEffect(() => { if (!analysing) return; const controller = new AbortController(); const timer = setInterval(() => refresh(controller.signal).catch(error => { if (!controller.signal.aborted) setError(message(error)); }), 4000); return () => { clearInterval(timer); controller.abort(); }; }, [analysing, refresh]);
  useEffect(() => { if (!workspace.roles.includes("cfin_exception_manager")) return; const controller = new AbortController(); getMembers(workspace.id, token, controller.signal).then(setMembers).catch(error => { if (!controller.signal.aborted) setError(message(error)); }); return () => controller.abort(); }, [workspace.id, workspace.roles, token]);
  const result = detail?.case.error_analysis_result as Result | undefined;
  const steps = result?.analysis?.route.steps ?? [];
  const milestones = detail?.route_milestones ?? [];
  const nextStep = steps[milestones.length];
  const closed = Boolean(detail?.resolution_records?.length);
  const routeOpen = detail && !["completed", "escalated"].includes(String(detail.case.route_state));
  const approvalStep = nextStep && ["record_process_owner_decision", "review_and_approve_mapping"].includes(nextStep.kind);
  const postingStep = nextStep?.kind === "record_posting_outcome";
  async function action(action: CaseAction) {
    if (!detail) return; setBusy(true); setError(""); setNotice("");
    try {
      await performCaseAction(caseId, workspace.id, detail.case.version, action, role, { note, ...(action === "record_route_step" ? { decision: approvalStep || postingStep ? decision : null, evidence_ids: evidenceIds, posting_reference: reference } : {}), ...(action === "finish_resolution" ? { evidence_ids: evidenceIds, human_confirmed: confirmed, posting_reference: reference } : {}), ...(action === "assign" ? { assigned_user_id: ownerId, owner_role: ownerRole } : {}) }, token, signal());
      await refresh(signal()); setNote(""); setDecision(null); setEvidenceIds([]); setConfirmed(false); setNotice("Saved to the case history.");
    } catch (error) { setError(message(error)); await refresh(signal()).catch(() => {}); } finally { setBusy(false); }
  }
  async function uploadProof() {
    if (!proof) return; setBusy(true); setError("");
    try { const saved = await saveProof(caseId, workspace.id, role, proof, token, signal(), workspace.synthetic ? "synthetic" : "user_supplied"); await refresh(signal()); const id = String(saved.evidence_id ?? saved.id ?? ""); if (id) setEvidenceIds(current => [...current, id]); setProof(null); setNotice("Evidence saved. Select it for the relevant route step or validation."); } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function openEvidence(evidence: JsonRecord, inline = false) {
    setError(""); try { const blob = await getEvidence(String(evidence.id), workspace.id, token, signal()); if (inline) { setOriginals(current => ({ ...current, [String(evidence.id)]: "Loading…" })); const text = await blob.text(); setOriginals(current => ({ ...current, [String(evidence.id)]: text })); } else { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = String(evidence.filename); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); } } catch (error) { setError(message(error)); }
  }
  if (!detail) return <Stack>{error && <Alert color="red">{error}</Alert>}<Text>Loading saved case…</Text></Stack>;
  const proofs = detail.evidence.filter(x => x.kind === "proof");
  return <Stack><Group justify="space-between"><div><Title order={2}>{detail.case.title}</Title><Text size="sm" c="dimmed">{caseId} · {statusLabel(detail.case.status)} · version {detail.case.version}</Text></div><Button variant="default" disabled={busy} onClick={() => refresh(signal()).catch(e => setError(message(e)))}>Refresh case</Button></Group>{error && <Alert color="red">{error}</Alert>}{notice && <Alert color="teal">{notice}</Alert>}{analysing && <Alert color="blue">Analysis is {label(detail.case.analysis_status)}. This case refreshes automatically. If it remains queued, the analysis worker needs to be started.</Alert>}{detail.case.analysis_status === "unavailable" && <Alert color="orange">Analysis could not complete. The original is saved. The run failure is retained for investigation.{workspace.roles.includes("process_owner") && <Button ml="md" size="xs" disabled={busy || role !== "process_owner"} onClick={() => action("analyse")}>Retry analysis</Button>}</Alert>}
    <Tabs defaultValue="summary" keepMounted={false}><Tabs.List><Tabs.Tab value="summary">Summary</Tabs.Tab><Tabs.Tab value="original">Original log</Tabs.Tab><Tabs.Tab value="journey">Case history and actions</Tabs.Tab></Tabs.List>
    <Tabs.Panel value="summary" pt="lg"><Stack>{result?.case_content ? <><Title order={3}>What happened</Title><Facts items={result.case_content.what_happened} entries={result.extraction?.entries ?? []} /><Title order={3}>Document context</Title><Facts items={result.case_content.document_context} entries={result.extraction?.entries ?? []} /><Card withBorder><Badge color="teal">{label(result.analysis?.category_id)}</Badge><Text mt="sm">{result.analysis?.cause_hypothesis}</Text><Text size="sm" c="dimmed" mt="xs">AI assessment · review against the original evidence before acting.</Text></Card>{Boolean(result.case_content.open_questions.length || result.analysis?.gaps.length || result.limitations?.length) && <><Title order={3}>Unclear or missing details</Title><Facts items={result.case_content.open_questions} entries={result.extraction?.entries ?? []} />{[...(result.analysis?.gaps ?? []), ...(result.limitations ?? [])].map((x, i) => <Text key={i}>{x}</Text>)}</>}</> : <Text>The AI brief has not been published yet.</Text>}<Title order={3}>Required route</Title>{steps.length ? steps.map(step => <Card withBorder key={step.step_id}><Group><Badge variant="light" color={milestones.some(x => x.step_id === step.step_id) ? "teal" : "gray"}>{step.order}</Badge><Text fw={500}>{step.description}</Text></Group><Text size="sm" c="dimmed">{roleLabel(step.required_role)}</Text></Card>) : <Text>A route will appear after analysis.</Text>}</Stack></Tabs.Panel>
    <Tabs.Panel value="original" pt="lg"><Stack>{detail.evidence.filter(x => x.kind !== "proof").map(e => <Card withBorder key={String(e.id)}><Group justify="space-between"><Text fw={500}>{String(e.filename)}</Text><Group><Button variant="light" onClick={() => openEvidence(e, true)}>Read original</Button><Button variant="default" onClick={() => openEvidence(e)}>Download</Button></Group></Group>{originals[String(e.id)] && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13 }}>{originals[String(e.id)]}</pre>}</Card>)}</Stack></Tabs.Panel>
    <Tabs.Panel value="journey" pt="lg"><Stack><Select label="Acting role" data={workspace.roles.map(r => ({ value: r, label: roleLabel(r) }))} value={role} onChange={value => { setRole(value ?? ""); setDecision(null); }} allowDeselect={false} /><Text size="sm" c="dimmed">Only roles assigned to your signed-in account are available. {workspace.synthetic ? "One test account may hold several roles for the walkthrough." : ""}</Text>
    {detail.case.route_state === "escalated" && <Alert color="orange">This route is escalated to the CFIN Exception Manager. Keep the case open, record findings and assign a follow-up investigator.</Alert>}
    {!closed && <><Card withBorder><Stack><Title order={3}>Save evidence</Title><FileInput label="Evidence file" accept=".txt,.json,.pdf,.png,.jpg,.jpeg" value={proof} onChange={setProof} /><Button variant="light" color="teal" onClick={uploadProof} disabled={!proof || busy}>Upload evidence</Button></Stack></Card><MultiSelect label="Evidence for this action" data={proofs.map(e => ({ value: String(e.id), label: String(e.filename) }))} value={evidenceIds} onChange={setEvidenceIds} /><Textarea label="Case note" description="Explain what was checked, decided or changed." minRows={3} value={note} onChange={e => setNote(e.currentTarget.value)} />
    {routeOpen && nextStep && <Card withBorder><Stack><Text fw={600}>Step {nextStep.order}: {nextStep.description}</Text><Text size="sm">Required role: {roleLabel(nextStep.required_role)}</Text>{approvalStep && <Select label="Approval decision" placeholder="Choose a decision" data={[{ value: "approved", label: "Approve" }, { value: "rejected", label: "Reject and escalate" }]} value={decision} onChange={setDecision} />}{postingStep && <><Select label="Posting outcome" placeholder="Choose the recorded outcome" data={[{ value: "completed", label: "Posting succeeded" }, { value: "failed", label: "Posting failed — escalate" }]} value={decision} onChange={setDecision} /><TextInput label="Posting reference" value={reference} onChange={e => setReference(e.currentTarget.value)} /></>}<Button color="teal" loading={busy} disabled={role !== nextStep.required_role || !note.trim() || ((approvalStep || postingStep) && !decision) || ((nextStep.requires_evidence || approvalStep || postingStep) && !evidenceIds.length) || analysing} onClick={() => action("record_route_step")}>Record route step</Button></Stack></Card>}
    {detail.case.route_state === "completed" && <Card withBorder><Stack><Title order={3}>Validate and close</Title><Text>Confirm the posted document matches the intended result and attach the validation evidence.</Text><TextInput label="Validated posting reference" value={reference} onChange={e => setReference(e.currentTarget.value)} /><Checkbox label={workspace.synthetic ? "I checked the synthetic posting result and validation evidence." : "I checked the posting result and validation evidence."} checked={confirmed} onChange={e => setConfirmed(e.currentTarget.checked)} /><Button color="teal" loading={busy} disabled={!confirmed || !note.trim() || !reference.trim() || !evidenceIds.length || !["data_operations", "process_owner"].includes(role)} onClick={() => action("finish_resolution")}>Close case</Button></Stack></Card>}
    <Button variant="default" disabled={busy || !note.trim()} onClick={() => action("comment")}>Save comment</Button>
    {role === "cfin_exception_manager" && <Card withBorder><Stack><Title order={3}>Assign an owner</Title><Select label="Workspace member" data={members.map(m => ({ value: m.user_id, label: m.user_id }))} value={ownerId} onChange={value => { setOwnerId(value); setOwnerRole(null); }} /><Select label="Owner role" data={(members.find(m => m.user_id === ownerId)?.roles ?? []).map(r => ({ value: r, label: roleLabel(r) }))} value={ownerRole} onChange={setOwnerRole} /><Button disabled={busy || !ownerId || !ownerRole || !note.trim()} onClick={() => action("assign")}>Save assignment</Button></Stack></Card>}</>}
    {closed && <Alert color="teal">Closed with human validation. The original evidence, decisions and resolution remain saved.</Alert>}
    <Title order={3}>Saved history</Title>{detail.resolution_records?.map(r => <Card key={String(r.id)} withBorder><Text fw={600}>Resolution · {String(r.resolved_at)}</Text><Text>{String((r.record as JsonRecord)?.note ?? "")}</Text></Card>)}{detail.activity.map(a => <Card withBorder key={String(a.id)}><Group justify="space-between"><Text fw={600}>{label(a.event_type)}</Text><Text size="xs" c="dimmed">{new Date(String(a.created_at)).toLocaleString()}</Text></Group><Text>{String(a.reason ?? "")}</Text>{Boolean((a.new_value as JsonRecord)?.decision) && <Text size="sm">Decision: {label((a.new_value as JsonRecord).decision)}</Text>}{Boolean((a.new_value as JsonRecord)?.posting_reference) && <Text size="sm">Posting reference: {String((a.new_value as JsonRecord).posting_reference)}</Text>}{Array.isArray((a.new_value as JsonRecord)?.evidence_ids) && ((a.new_value as JsonRecord).evidence_ids as string[]).map(id => { const evidence = detail.evidence.find(e => e.id === id); return evidence ? <Button key={id} size="xs" variant="subtle" onClick={() => openEvidence(evidence)}>{String(evidence.filename)}</Button> : null; })}<Text size="xs" c="dimmed">{roleLabel(String(a.acting_role))} · {String(a.actor_id ?? "system")}</Text></Card>)}<Title order={3}>Saved evidence</Title>{proofs.map(e => <Button variant="subtle" key={String(e.id)} onClick={() => openEvidence(e)}>{String(e.filename)}</Button>)}</Stack></Tabs.Panel></Tabs>
  </Stack>;
}

function Facts({ items, entries }: { items: FactualStatement[]; entries: FactualEntry[] }) {
  return <Stack gap="xs">{items.map((fact, i) => <div key={i}><Text>{fact.text}</Text>{fact.supporting_entry_ids.map(id => { const entry = entries.find(e => e.entry_id === id); return entry ? <details key={id}><summary style={{ cursor: "pointer", color: "#0f766e", fontSize: 12 }}>Source {entry.source_id} · lines {entry.source_span.line_start}–{entry.source_span.line_end}</summary><pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{entry.raw_text}</pre></details> : <Text size="xs" c="dimmed" key={id}>Source reference: {id}</Text>; })}</div>)}</Stack>;
}
