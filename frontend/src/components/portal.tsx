"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Session, SupabaseClient } from "@supabase/supabase-js";
import { getCaseDetail, getCasePage, getWorkspaces, type CaseFilters, type CaseSummary, type Workspace } from "@/lib/api";
import { getBrowserClient } from "@/lib/supabase";
import { WorkspaceShell } from "./workspace-shell";
import { CaseWorklist } from "./case-worklist";
import { CaseWorkflowPanel } from "./case-workflow";
import { IntakePanel } from "./intake-panel";
import { Icon } from "./icon";
import { OperationsOverview, SnapshotGroup } from "./operations-overview";
import { KnowledgePanel } from "./knowledge-panel";
import { EvaluationsPanel } from "./evaluations-panel";

type LoadState<T> = {
  phase: "idle" | "loading" | "ready" | "error";
  items: T[];
  error: string;
  scope: string;
};
const emptyState = { phase: "idle" as const, items: [], error: "", scope: "" };
function errorMessage(error: unknown): string {
  if (error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")) {
    return "The case service could not be reached. Check the connection and try refreshing.";
  }
  return error instanceof Error ? error.message : "The request failed. Try again.";
}

export default function Portal({ page = "cases" }: { page?: "cases" | "access" | "groups" }) {
  const [client, setClient] = useState<SupabaseClient | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [configError, setConfigError] = useState("");
  const [authError, setAuthError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signingIn, setSigningIn] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [workspaceResult, setWorkspaces] = useState<LoadState<Workspace>>(emptyState);
  const [caseResult, setCases] = useState<LoadState<CaseSummary>>(emptyState);
  const [workspaceId, setWorkspaceId] = useState("");
  const [workspaceRefresh, setWorkspaceRefresh] = useState(0);
  const [caseRefresh, setCaseRefresh] = useState(0);
  const [intakeOpen, setIntakeOpen] = useState(false);
  const [preferredCaseId, setPreferredCaseId] = useState("");
  const [intakeNotice, setIntakeNotice] = useState("");
  const [view, setView] = useState<"cases" | "overview" | "knowledge" | "evaluations">("cases");
  const [casePage, setCasePage] = useState(1);
  const [caseTotal, setCaseTotal] = useState(0);
  const [caseFilters, setCaseFilters] = useState<CaseFilters>({});
  const [deepLink, setDeepLink] = useState({ workspaceId: "", caseId: "", snapshotId: "", groupId: "" });
  const [directCase, setDirectCase] = useState<CaseSummary | null>(null);
  const [directError, setDirectError] = useState("");
  const [returnPath, setReturnPath] = useState("/");
  const [accessPath, setAccessPath] = useState("/access");
  useEffect(() => { const query = new URLSearchParams(window.location.search); const next = query.get("next"); if (next) { try { const target = new URL(next, window.location.origin); if (target.origin === window.location.origin && ["/", "/groups"].includes(target.pathname)) setReturnPath(target.pathname + target.search); } catch {} } if (query.has("case_id") || query.has("snapshot_id")) setAccessPath(`/access?${new URLSearchParams({ next: window.location.pathname + window.location.search })}`); setDeepLink({ workspaceId: query.get("workspace_id") || "", caseId: query.get("case_id") || "", snapshotId: query.get("snapshot_id") || "", groupId: query.get("group_id") || "" }); }, []);
  const accessToken = session?.access_token;
  const workspaces = workspaceResult.scope === accessToken ? workspaceResult : emptyState;
  const permissionScope = workspaces.items.find(item => item.id === workspaceId)?.roles.join(",") || "";
  const caseScope = `${accessToken || ""}:${workspaceId}:${permissionScope}`;
  const filterKey = JSON.stringify(caseFilters);
  const cases = caseResult.scope === caseScope ? caseResult : emptyState;

  const accessInvalidated = useRef(false);
  useEffect(() => { if (workspaces.phase === "ready") accessInvalidated.current = false; }, [workspaces.phase]);
  useEffect(() => {
    function invalidateAccess() { if (accessInvalidated.current) return; accessInvalidated.current = true; setCases(emptyState); setWorkspaces(emptyState); setDirectCase(null); setIntakeOpen(false); setPreferredCaseId(""); setIntakeNotice(""); setWorkspaceRefresh(value => value + 1); }
    window.addEventListener("cfin:access-invalid", invalidateAccess);
    return () => window.removeEventListener("cfin:access-invalid", invalidateAccess);
  }, []);

  useEffect(() => { setIntakeOpen(false); setPreferredCaseId(""); setIntakeNotice(""); setCasePage(1); setCaseFilters({}); setCaseTotal(0); setDirectCase(null); }, [workspaceId, permissionScope]);

  useEffect(() => {
    let currentClient: SupabaseClient | null;
    try {
      currentClient = getBrowserClient();
    } catch {
      setConfigError("The sign-in configuration is invalid. Ask the POC administrator to check the project URL and publishable key.");
      setAuthReady(true);
      return;
    }
    setClient(currentClient);
    if (!currentClient) {
      setAuthReady(true);
      return;
    }

    let active = true;
    const { data: { subscription } } = currentClient.auth.onAuthStateChange((_event, nextSession) => {
      if (active) {
        setSession(nextSession);
        setAuthReady(true);
      }
    });

    currentClient.auth.getSession().then(({ data, error }) => {
      if (!active) return;
      setSession(data.session);
      if (error) setAuthError("Your saved session could not be restored. Sign in again.");
      setAuthReady(true);
    }).catch(() => {
      if (active) {
        setAuthError("Your saved session could not be restored. Sign in again.");
        setAuthReady(true);
      }
    });

    return () => { active = false; subscription.unsubscribe(); };
  }, []);

  useEffect(() => {
    if (!accessToken) {
      setWorkspaces(emptyState);
      setWorkspaceId("");
      return;
    }
    const controller = new AbortController();
    setWorkspaces({ phase: "loading", items: [], error: "", scope: accessToken });
    getWorkspaces(accessToken, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setWorkspaces({ phase: "ready", items, error: "", scope: accessToken });
      setWorkspaceId((previous) => items.some((item) => item.id === previous) ? previous : items.some(item => item.id === deepLink.workspaceId) ? deepLink.workspaceId : (items[0]?.id || ""));
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setWorkspaces({ phase: "error", items: [], error: errorMessage(error), scope: accessToken });
        setWorkspaceId("");
      }
    });
    return () => controller.abort();
  }, [accessToken, workspaceRefresh, deepLink.workspaceId]);

  useEffect(() => {
    if (!accessToken || !workspaceId || workspaces.phase !== "ready") {
      setCases(emptyState);
      return;
    }
    const controller = new AbortController();
    setCases({ phase: "loading", items: [], error: "", scope: caseScope });
    getCasePage(workspaceId, casePage, caseFilters, accessToken, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setCases({ phase: "ready", items: result.items, error: "", scope: caseScope }); setCaseTotal(result.total); }
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setCases({ phase: "error", items: [], error: errorMessage(error), scope: caseScope });
    });
    return () => controller.abort();
  }, [accessToken, workspaceId, workspaces.phase, caseRefresh, caseScope, casePage, filterKey]);

  useEffect(() => {
    setDirectCase(null); setDirectError("");
    if (!deepLink.caseId || !accessToken || !workspaceId || workspaces.phase !== "ready") return;
    const controller = new AbortController();
    getCaseDetail(deepLink.caseId, workspaceId, accessToken, controller.signal).then(result => { if (!controller.signal.aborted) setDirectCase(result.case); }).catch(failure => { if (!controller.signal.aborted) setDirectError(errorMessage(failure)); });
    return () => controller.abort();
  }, [deepLink.caseId, workspaceId, accessToken, workspaces.phase, permissionScope]);

  const selectedWorkspace = workspaces.items.find((item) => item.id === workspaceId);

  function updateSummary(item: CaseSummary) {
    setCases(previous => previous.scope === caseScope ? { ...previous, items: previous.items.map(existing => existing.id === item.id ? item : existing) } : previous);
  }

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!client || signingIn) return;
    setSigningIn(true);
    setAuthError("");
    try {
      const { data, error } = await client.auth.signInWithPassword({ email: email.trim(), password });
      if (error) {
        setAuthError("Sign-in failed. Check your email and password, or ask the POC administrator to confirm your invitation.");
      } else {
        setSession(data.session);
        setPassword("");
      }
    } catch {
      setAuthError("The sign-in service could not be reached. Check the connection and try again.");
    } finally {
      setSigningIn(false);
    }
  }

  async function signOut() {
    if (!client || signingOut) return;
    setSigningOut(true);
    setAuthError("");
    try {
      const { error } = await client.auth.signOut({ scope: "local" });
      if (error) setAuthError("Sign-out failed. Try again before leaving this device.");
      else {
        setSession(null);
        setCases(emptyState);
        setWorkspaces(emptyState);
        setWorkspaceId("");
        setIntakeOpen(false); setPreferredCaseId(""); setIntakeNotice("");
      }
    } catch {
      setAuthError("Sign-out failed. Try again before leaving this device.");
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <WorkspaceShell active={page === "groups" ? "cases" : page} account={session ? <div className="account-controls"><span className="account-email">{session.user.email || "Workspace member"}</span><button className="button button-quiet" type="button" onClick={signOut} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button></div> : undefined}>
      {page === "access" ? <>
        <div className="page-heading"><div><div className="breadcrumb">Workspace <span>/</span> Access</div><h1>Workspace access</h1><p>Sign in to load your private case records.</p></div><Link className="button button-secondary" href="/preview">View design preview<Icon name="arrow" size={16} /></Link></div>
        {authError && <p className="inline-error" role="alert">{authError}</p>}
        <section className="access-layout" aria-label="Workspace sign-in">
          <div className="access-context"><span className="access-symbol"><Icon name="lock" size={26} /></span><h2>Your private operations workspace</h2><p>Use your invited account to access the cases available to your team.</p><ul><li><Icon name="check" size={17} />Access limited to your workspace</li><li><Icon name="check" size={17} />Original evidence stays private</li><li><Icon name="check" size={17} />Human review controls corrections</li></ul><div className="access-preview-note"><strong>Reviewing the interface?</strong><p>The design preview is available without signing in. Its six synthetic examples are never saved as cloud cases.</p><Link href="/preview">Open design preview<Icon name="arrow" size={15} /></Link></div></div>
          <div className="access-panel">
            {!authReady ? <><h2>Checking your session</h2><p>Restoring access to your workspace.</p></> : session ? <><h2>You’re signed in</h2><p>{session.user.email || "Workspace member"}</p><Link className="button button-primary" href={returnPath}>Open workspace<Icon name="arrow" size={16} /></Link></> : !client || configError ? <><span className="access-status"><span />Not connected</span><h2>Connect your workspace</h2><p>The private workspace hasn’t been configured yet. You can still explore sample cases in the design preview.</p>{configError && <p className="inline-error" role="alert">{configError}</p>}<Link className="button button-primary" href="/preview">View design preview<Icon name="arrow" size={16} /></Link><details className="setup-details"><summary>Administrator setup</summary><p>Set the Supabase project URL and browser publishable key in the portal environment, then restart. Follow the local development guide before applying the migration. No case data is loaded until sign-in and workspace membership are verified.</p></details></> : <><h2>Sign in</h2><p>Use the account invited by your administrator.</p><form onSubmit={signIn}><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" placeholder="you@company.com" required value={email} onChange={event => setEmail(event.target.value)} disabled={signingIn} /><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} disabled={signingIn} /><button className="button button-primary" type="submit" disabled={signingIn}>{signingIn ? "Signing in…" : "Sign in"}<Icon name="arrow" size={16} /></button></form><p className="invitation-note">Access is by invitation. Contact your administrator if you need an account.</p></>}
          </div>
        </section>
      </> : <>
        <div className="page-heading"><div><div className="breadcrumb">Operations <span>/</span> Cases</div><h1>{page === "groups" ? "Snapshot cases" : view === "overview" ? "Backlog overview" : view === "knowledge" ? "Reviewed knowledge" : view === "evaluations" ? "Evaluations" : "Case board"}</h1><p>Review document exceptions and coordinate the next action.</p></div><Link className="button button-secondary" href="/preview"><Icon name="preview" size={17} />View design preview</Link></div>
        {authError && <p className="inline-error" role="alert">{authError}</p>}
        {!session ? <>
          <div className="connection-banner"><Icon name="info" size={19} /><p><strong>{!authReady ? "Checking workspace access" : !client || configError ? "Workspace not connected" : "Sign in to load your cases"}</strong><span>{configError || "Private case records appear after sign-in. Explore sample cases in the design preview."}</span></p><Link href={accessPath} className="banner-link">{client ? "Sign in" : "Workspace access"}<Icon name="arrow" size={16} /></Link></div>
          <CaseWorklist items={[]} phase="disconnected" message="Connect your workspace or open the design preview to explore a sample case and its evidence." />
        </> : <>
          <div className="workspace-bar"><label htmlFor="workspace">Workspace</label><select id="workspace" value={workspaceId} disabled={workspaces.phase !== "ready" || !workspaces.items.length} onChange={event => { setWorkspaceId(event.target.value); setIntakeOpen(false); setPreferredCaseId(""); setIntakeNotice(""); }}>{!workspaces.items.length && <option value="">{workspaces.phase === "loading" ? "Loading workspaces…" : "No workspace selected"}</option>}{workspaces.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><span>{selectedWorkspace ? "Member access verified" : "Workspace membership required"}</span><button className="button button-quiet" type="button" onClick={() => setWorkspaceRefresh(value => value + 1)} disabled={workspaces.phase === "loading"}><Icon name="refresh" size={16} />Refresh workspaces</button>{selectedWorkspace?.roles.includes("process_owner") && <button className="button button-primary" type="button" onClick={() => { setIntakeOpen(open => !open); setIntakeNotice(""); setView("cases"); }} aria-expanded={intakeOpen}>New intake</button>}</div>
          {page !== "groups" && <div className="workspace-tabs" role="tablist" aria-label="Workspace views">{([ ["cases", "Cases"], ["overview", "Overview"], ["knowledge", "Knowledge"], ["evaluations", "Evaluations"] ] as const).map(([value, label]) => <button key={value} role="tab" type="button" aria-selected={view === value} onClick={() => { setView(value); setIntakeOpen(false); }} disabled={!selectedWorkspace}>{label}</button>)}</div>}
          {intakeNotice && <p className="workflow-success intake-saved-notice" role="status"><Icon name="check" size={16} />{intakeNotice}</p>}
          {intakeOpen && selectedWorkspace && accessToken && <IntakePanel key={caseScope} workspaceId={workspaceId} token={accessToken} canUpload={selectedWorkspace.roles.includes("process_owner")} syntheticWorkspace={selectedWorkspace.synthetic} onClose={() => setIntakeOpen(false)} onSaved={caseId => { setIntakeOpen(false); setPreferredCaseId(caseId); setIntakeNotice("Private intake saved. Open the case to review its evidence and analysis state."); setCaseRefresh(value => value + 1); }} />}
          {selectedWorkspace && accessToken && page === "groups" ? deepLink.snapshotId && deepLink.groupId ? <SnapshotGroup key={caseScope} workspaceId={workspaceId} token={accessToken} snapshotId={deepLink.snapshotId} groupId={deepLink.groupId} onAccessFailure={() => setWorkspaceRefresh(value => value + 1)} /> : <p className="inline-error" role="alert">This link is missing a snapshot or group. Open a group from the overview.</p> : selectedWorkspace && accessToken && view === "overview" ? <OperationsOverview key={caseScope} workspaceId={workspaceId} token={accessToken} onAccessFailure={() => setWorkspaceRefresh(value => value + 1)} /> : selectedWorkspace && accessToken && view === "knowledge" ? <KnowledgePanel key={caseScope} workspaceId={workspaceId} token={accessToken} roles={selectedWorkspace.roles} onAccessFailure={() => setWorkspaceRefresh(value => value + 1)} /> : selectedWorkspace && accessToken && view === "evaluations" ? <EvaluationsPanel key={caseScope} workspaceId={workspaceId} token={accessToken} roles={selectedWorkspace.roles} onAccessFailure={() => setWorkspaceRefresh(value => value + 1)} /> : deepLink.caseId && selectedWorkspace && accessToken ? <section className="standalone-case"><button type="button" className="button button-quiet" onClick={() => { setDeepLink(previous => ({ ...previous, caseId: "" })); window.history.replaceState(null, "", "/"); }}>Back to case board</button>{directError ? <p className="inline-error" role="alert">{directError}</p> : directCase ? <CaseWorkflowPanel key={caseScope + directCase.id} selected={directCase} workspaceId={workspaceId} token={accessToken} roles={selectedWorkspace.roles} syntheticWorkspace={selectedWorkspace.synthetic} onUpdated={item => { setDirectCase(item); updateSummary(item); }} /> : <p className="section-intro" role="status">Loading the linked case…</p>}</section> : <CaseWorklist key={caseScope} items={cases.items} phase={workspaces.phase === "loading" || (selectedWorkspace && (cases.phase === "idle" || cases.phase === "loading")) ? "loading" : workspaces.phase === "error" || cases.phase === "error" ? "error" : !selectedWorkspace ? "disconnected" : "ready"} error={workspaces.error || cases.error} message={!selectedWorkspace ? "Your account has no selected workspace. Ask the administrator to add you to the synthetic workspace, then refresh." : undefined} onRefresh={selectedWorkspace ? () => setCaseRefresh(value => value + 1) : undefined} pagination={selectedWorkspace ? { page: casePage, total: caseTotal, pageSize: 25, onPage: setCasePage } : undefined} onFilterChange={selectedWorkspace ? filters => { if (JSON.stringify(filters) !== filterKey) { setCaseFilters(filters); setCasePage(1); } } : undefined} preferredCaseId={preferredCaseId} detailRenderer={selectedWorkspace && accessToken ? item => <CaseWorkflowPanel key={caseScope + item.id} selected={item} workspaceId={workspaceId} token={accessToken} roles={selectedWorkspace.roles} syntheticWorkspace={selectedWorkspace.synthetic} onUpdated={updateSummary} /> : undefined} />}
        </>}
      </>}
    </WorkspaceShell>
  );
}
