import { test } from 'node:test';
import assert from 'node:assert/strict';
import { closureReference, mapSavedCase } from '../src/lib/workbench-mapping';
import type { SavedWorkbenchCase } from '../src/lib/workbench-connection';

function saved(): SavedWorkbenchCase {
  return { case: { id: 'c', category: 'tax', status: 'complete', work_cycle: 1 }, originals: [{ evidenceId: 'e', sourceId: 's', sourceVersion: '1', filename: 'original.log', text: 'Document 0000123456\nError: tax unavailable\n' }], brief: null, activity: [], routeMilestones: [], evidence: [], assignments: [], resolutions: [], analysisState: 'pending', analysisFailure: null };
}
test('only a saved closure for this work cycle produces Closed', () => {
  const value = saved();
  assert.notEqual(mapSavedCase(value).status, 'Closed');
  value.resolutions = [{ work_cycle: 0 }];
  assert.notEqual(mapSavedCase(value).status, 'Closed');
  value.resolutions = [{ work_cycle: 1 }];
  assert.equal(mapSavedCase(value).status, 'Closed');
});
test('does not turn a route role into an explicit handover', () => {
  const value = saved(); value.case.category = 'master_data';
  assert.equal(mapSavedCase(value).assignee, 'Unassigned');
  value.assignments = [{ version: 1, owner_role: 'data_operations' }, { version: 2, owner_role: 'mdg_process_owner' }];
  const mapped = mapSavedCase(value);
  assert.equal(mapped.assignee, 'Maya Shah'); assert.equal(mapped.document, '0000123456');
});
test('approval author and external approver are separate and evidence stays message-linked', () => {
  const value = saved();
  value.evidence = [{ id: 'proof', filename: 'approval.eml', byte_size: 100, content_type: 'message/rfc822' }];
  value.activity = [{ id: 'event', event_type: 'case_record_approval', acting_role: 'mdg_process_owner', created_at: '2026-10-09T10:00:00Z', reason: 'Approval received', new_value: { external_approver_role: 'process_owner', evidence_ids: ['proof'] } }];
  const entry = mapSavedCase(value).activity[0];
  assert.equal(entry.actor, 'Maya Shah'); assert.equal(entry.externalApprover, 'Daniel Ross');
  assert.equal(entry.attachments?.[0].name, 'approval.eml');
});
test('closure needs the explicitly recorded target reference, not a guessed source number', () => {
  assert.equal(closureReference('Reprocessed and validated. Target document: DEMO-1234'), 'DEMO-1234');
  assert.throws(() => closureReference('Document 0000123456 has a screenshot'), /Target document/);
});
