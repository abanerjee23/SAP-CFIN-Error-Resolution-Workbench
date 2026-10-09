"use client";

import { useEffect, useState } from 'react';
import { Alert, Button } from '@mantine/core';
import { ArrowRight, CheckCircle2, FileSearch, RotateCw, TriangleAlert } from 'lucide-react';
import type { CaseRecord } from './workbench-app';
import { analysisView } from '../lib/analysis-progress';

function elapsed(item: CaseRecord, now: number) {
  const start = Date.parse(item.remote?.progress?.queued_at || item.createdAt);
  const seconds = Number.isFinite(start) ? Math.max(0, Math.floor((now - start) / 1000)) : 0;
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function AnalysisInbox({ cases, refreshError, onOpenCase, onRetry }: {
  cases: CaseRecord[]; refreshError: boolean; onOpenCase: (id: string) => void;
  onRetry: (item: CaseRecord) => Promise<void>;
}) {
  const [now, setNow] = useState(Date.now());
  const [retrying, setRetrying] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const active = cases.filter(item => analysisView(item.remote).active);
  useEffect(() => {
    if (!active.length) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active.length]);
  if (!cases.length) return null;
  const ordered = [...active, ...cases.filter(item => !analysisView(item.remote).active)];
  return <div className="analysis-inbox">
    <div className="analysis-inbox-heading"><h3>Recent analyses</h3><span>{active.length ? `${active.length} in progress` : 'Saved to your workspace'}</span></div>
    {refreshError && <Alert color="orange" mb="sm">Progress updates are reconnecting. Your saved upload is safe; this does not mean the analysis has stopped.</Alert>}
    {(expanded ? ordered : ordered.slice(0, 3)).map(item => {
      const view = analysisView(item.remote);
      const Icon = view.active ? FileSearch : view.state === 'failed' ? TriangleAlert : CheckCircle2;
      const start = Date.parse(item.remote?.progress?.queued_at || item.createdAt);
      const waitingLong = view.state === 'queued' && now - start > 60_000;
      return <article className={`analysis-item analysis-${view.state}`} key={item.id}>
        <div className="analysis-item-heading"><span className={`analysis-symbol ${view.active ? 'is-active' : ''}`}><Icon size={19} /></span><div><strong>{item.originalFilename || item.caseNumber}</strong><span>{item.caseNumber}</span></div>{view.active && <time aria-label="Time since upload">{elapsed(item, now)}</time>}</div>
        <div className="analysis-message" role="status" aria-live="polite" aria-atomic="true"><strong>{refreshError && view.active ? 'Checking progress…' : waitingLong ? 'Still waiting to start' : view.label}</strong><p>{waitingLong ? 'Your log is saved. Analysis has not started yet; the service may be busy or paused. You can leave and return.' : view.detail}</p></div>
        {view.active && <ol className="analysis-steps" aria-label="Analysis stages">{['Read log', 'Investigate', 'Prepare case'].map((label, index) => <li key={label} className={view.state === 'queued' ? 'waiting' : index < view.step ? 'done' : index === view.step ? 'current' : 'waiting'} aria-current={index === view.step && view.state !== 'queued' ? 'step' : undefined}><span />{label}</li>)}</ol>}
        {!view.active && <div className="analysis-actions"><Button size="xs" variant={view.state === 'ready' ? 'filled' : 'light'} color="teal" rightSection={<ArrowRight size={14} />} onClick={() => onOpenCase(item.id)}>{view.state === 'ready' ? 'Open case' : 'Review original'}</Button>{view.state === 'failed' && <Button size="xs" variant="subtle" color="teal" leftSection={<RotateCw size={13} />} loading={retrying === item.id} disabled={retrying !== null} onClick={async () => { setRetrying(item.id); try { await onRetry(item); } catch { /* Parent displays the service error. */ } finally { setRetrying(null); } }}>Retry analysis</Button>}</div>}
      </article>;
    })}
    {ordered.length > 3 && <Button variant="subtle" color="teal" size="xs" fullWidth onClick={() => setExpanded(!expanded)}>{expanded ? 'Show fewer' : `Show all ${ordered.length} analyses`}</Button>}
  </div>;
}

export function AnalysisDock({ cases, refreshError, onOpen, onOpenCase }: {
  cases: CaseRecord[]; refreshError: boolean; onOpen: () => void; onOpenCase: (id: string) => void;
}) {
  const active = cases.filter(item => analysisView(item.remote).active);
  const latest = active[0] || cases[0];
  if (!latest) return null;
  const view = analysisView(latest.remote);
  return <aside className="analysis-dock" aria-label="Analysis updates"><span className={`analysis-symbol ${view.active ? 'is-active' : ''}`}>{view.active ? <FileSearch size={19} /> : <CheckCircle2 size={19} />}</span><div role="status"><strong>{refreshError ? 'Reconnecting progress' : view.active ? `${active.length} ${active.length === 1 ? 'analysis' : 'analyses'} in progress` : view.label}</strong><span>{view.active ? 'You can keep working.' : latest.caseNumber}</span></div><Button size="xs" variant="light" color="teal" onClick={() => view.state === 'ready' ? onOpenCase(latest.id) : onOpen()}>{view.state === 'ready' ? 'Open case' : 'View progress'}</Button></aside>;
}
