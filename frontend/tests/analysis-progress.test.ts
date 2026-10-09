import { test } from 'node:test';
import assert from 'node:assert/strict';
import { analysisView } from '../src/lib/analysis-progress';
import { mapSavedCase } from '../src/lib/workbench-mapping';
import type { SavedWorkbenchCase } from '../src/lib/workbench-connection';

const saved = (): SavedWorkbenchCase => ({ case: { category: 'cause_not_established' }, originals: [{ evidenceId: 'e', sourceId: 's', sourceVersion: '1', filename: 'log.txt', text: 'Error\n' }], activity: [], assignments: [], evidence: [], resolutions: [], routeMilestones: [], brief: null, analysisState: 'pending', analysisFailure: null });
test('pending and failed analysis cannot become a diagnostic category', () => {
  const item = saved();
  assert.equal(mapSavedCase(item).category, 'Analysis in progress');
  assert.equal(analysisView(item).state, 'queued');
  item.analysisState = 'failed';
  assert.equal(mapSavedCase(item).category, 'Analysis incomplete');
  assert.equal(analysisView(item).active, false);
});
test('retry and stage progress use server facts rather than an invented percentage', () => {
  const item = saved();
  item.progress = { run_id: 'r', status: 'running', stage: 'agent_2', attempt: 2, retrying: true, queued_at: null, stage_started_at: null, completed_stages: ['agent_1'] };
  assert.equal(analysisView(item).state, 'retrying');
  assert.equal(analysisView(item).step, 1);
});
test('available without a current verified brief cannot display successful completion', () => {
  const item = saved(); item.analysisState = 'available';
  assert.equal(analysisView(item).state, 'failed');
  assert.equal(mapSavedCase(item).category, 'Analysis incomplete');
});
