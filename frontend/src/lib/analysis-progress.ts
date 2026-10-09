import type { SavedWorkbenchCase } from './workbench-connection';

export type AnalysisProgress = {
  run_id: string | null; status: 'queued' | 'running' | 'ready' | 'failed';
  stage: string | null; attempt: number; retrying: boolean;
  queued_at: string | null; stage_started_at: string | null; completed_stages: string[];
};

export function analysisView(saved?: SavedWorkbenchCase) {
  if (!saved) return { state: 'ready', label: 'Ready for review', detail: '', step: 3, active: false };
  const progress = saved.progress;
  if (saved.analysisState === 'available' && saved.brief) return {
    state: 'ready', label: 'Ready for review', detail: 'Your analysis and source evidence are saved.', step: 3, active: false,
  };
  if (progress?.status === 'failed' || ['failed', 'unavailable'].includes(saved.analysisState)
      || (saved.analysisState === 'available' && !saved.brief)) return {
    state: 'failed', label: 'Analysis needs attention',
    detail: 'We could not complete the analysis. Your original file is safe. Open the case to review it or retry.', step: 0, active: false,
  };
  const step = ({ agent_1: 0, agent_2: 1, agent_3: 2 } as Record<string, number>)[progress?.stage || ''] ?? 0;
  if (progress?.retrying) return {
    state: 'retrying', label: 'Retrying analysis',
    detail: 'The previous attempt did not finish successfully. We are trying this step once more.', step, active: true,
  };
  const running = progress?.status === 'running' || saved.analysisState === 'running';
  return {
    state: running ? 'running' : 'queued',
    label: running ? ['Reading your log', 'Investigating the errors', 'Preparing your case'][step] : 'Waiting to start',
    detail: 'You can browse the app or leave and return. We will keep your progress here.', step, active: true,
  };
}
