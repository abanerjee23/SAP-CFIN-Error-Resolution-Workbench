import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { projectSavedBrief, WorkbenchConnection, type WorkbenchSession } from '../src/lib/workbench-connection';

const signal = () => new AbortController().signal;
const session: WorkbenchSession = { token: 'local-demo-test', workspace: { id: 'w', name: 'Synthetic', synthetic: true, roles: ['process_owner'] } };
const original = { evidenceId: 'e', sourceId: 's', sourceVersion: '1', filename: 'source.log', text: 'Document 0000123456\r\nError: mapping missing\r\n' };
const statement = { text: 'Mapping failed for the document.', supporting_entry_ids: ['entry'] };
const result = () => ({
  result_kind: 'error_analysis', outcome: 'completed', limitations: [],
  extraction: { entries: [{ entry_id: 'entry', source_id: 's', source_version: '1', source_span: { line_start: 2, line_end: 2 }, raw_text: 'Error: mapping missing\r\n' }] },
  analysis: { category_id: 'mapping', cause_hypothesis: 'Mapping may be absent.', supporting_entry_ids: ['entry'], route: { category_id: 'mapping', steps: [{ step_id: 'unchanged-policy' }] } },
  case_content: { title: statement, what_happened: [statement], document_context: [], original_log_evidence: [statement], related_cases: [] },
});
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

test('projects saved citations with exact CRLF bytes and leaves route policy intact', () => {
  const saved = result(); const view = projectSavedBrief(saved, [original]);
  assert.equal(view?.title.citations[0].lineStart, 2);
  assert.equal(view?.route, saved.analysis.route);
  assert.equal(original.text.startsWith('Document 0000123456'), true);
});
test('does not invent a brief before publication or on failure', () => {
  assert.equal(projectSavedBrief(null, [original]), null);
  assert.equal(projectSavedBrief({ outcome: 'failed' }, [original]), null);
});
test('rejects mismatched evidence text, missing references and inconsistent categories', () => {
  const altered = result(); altered.extraction.entries[0].raw_text = 'Wrong text';
  assert.throws(() => projectSavedBrief(altered, [original]), /differs/);
  const missing = result(); missing.case_content.title = { ...statement, supporting_entry_ids: ['missing'] };
  assert.throws(() => projectSavedBrief(missing, [original]), /cannot be matched/);
  const route = result(); route.analysis.route.category_id = 'master_data';
  assert.throws(() => projectSavedBrief(route, [original]), /does not match/);
});
test('upload retains the same caller-owned receipt on retry and sends unchanged UTF-8 bytes', async () => {
  const sent: Record<string, unknown>[] = [];
  const api = new WorkbenchConnection('http://127.0.0.1:8011', async (_url, init) => {
    sent.push(JSON.parse(String(init?.body))); return json({ case_id: 'c', version: 1, paid_dispatch_enabled: false });
  });
  const file = new File([original.text], 'source.log', { type: 'text/plain' });
  const first = await api.upload(session, file, 'stable-receipt', signal());
  await api.upload(session, file, 'stable-receipt', signal());
  assert.deepEqual(sent[0], sent[1]);
  assert.equal(first.paidDispatchEnabled, false);
  assert.equal(Buffer.from((sent[0].sources as { content_base64: string }[])[0].content_base64, 'base64').toString(), original.text);
});
test('rejects oversized uploads before sending data', async () => {
  const api = new WorkbenchConnection('http://localhost:8011', async () => { throw new Error('Must not send'); });
  await assert.rejects(api.upload(session, new File(['x'.repeat(8193)], 'large.log'), 'receipt', signal()), /8 KB/);
});
test('reads all pages without silently losing cases', async () => {
  let page = 0;
  const api = new WorkbenchConnection('http://localhost:8011', async () => json({ total: 2, items: [{ id: String(++page) }] }));
  assert.equal((await api.listCases(session, signal())).length, 2);
});
test('rejects pagination drift instead of showing an incomplete board', async () => {
  let page = 0;
  const api = new WorkbenchConnection('http://localhost:8011', async () => json({ total: ++page + 1, items: [{ id: String(page) }] }));
  await assert.rejects(api.listCases(session, signal()), /changed while loading/);
});
test('reads private original bytes and keeps an unpublished case explicitly pending', async () => {
  const sha = createHash('sha256').update(original.text).digest('hex');
  const api = new WorkbenchConnection('http://localhost:8011', async (url, init) => {
    assert.equal((init?.headers as Record<string, string>).Authorization, 'Bearer local-demo-test');
    if (String(url).includes('/evidence/')) return new Response(original.text);
    return json({ case: { id: 'c', workspace_id: 'w', workflow_version: 'error-analysis-v1', analysis_status: 'pending' }, evidence: [{ id: 'e', source_id: 's', source_version: '1', filename: 'source.log', kind: 'original_log', case_id: 'c', workspace_id: 'w', byte_size: Buffer.byteLength(original.text), sha256: sha }], activity: [], route_milestones: [] });
  });
  const loaded = await api.readCase(session, 'c', signal());
  assert.equal(loaded.originals[0].text, original.text); assert.equal(loaded.brief, null); assert.equal(loaded.analysisState, 'pending');
});
test('refuses wrong workspace responses and non-synthetic bootstrap', async () => {
  const api = new WorkbenchConnection('http://localhost:8011', async () => json({ case: { id: 'c', workspace_id: 'another' } }));
  await assert.rejects(api.readCase(session, 'c', signal()), /does not match/);
  const other = new WorkbenchConnection('http://localhost:8011', async () => json({ ...session, workspace: { ...session.workspace, synthetic: false } }));
  await assert.rejects(other.connect(signal()), /could not be verified/);
});
test('HTTP failure never becomes a successful save or exposes response content', async () => {
  const api = new WorkbenchConnection('http://localhost:8011', async () => json({ detail: 'private data' }, 503));
  await assert.rejects(api.connect(signal()), error => error instanceof Error && !error.message.includes('private data') && /No successful save/.test(error.message));
});

test('rejects altered original bytes even when the HTTP response succeeds', async () => {
  const api = new WorkbenchConnection('http://localhost:8011', async url => {
    if (String(url).includes('/evidence/')) return new Response('tampered');
    return json({ case: { id: 'c', workspace_id: 'w', workflow_version: 'error-analysis-v1', analysis_status: 'pending' }, evidence: [{ id: 'e', source_id: 's', source_version: '1', filename: 'source.log', kind: 'original_log', case_id: 'c', workspace_id: 'w', byte_size: 8, sha256: 'incorrect' }], activity: [], route_milestones: [] });
  });
  await assert.rejects(api.readCase(session, 'c', signal()), /integrity verification/);
});
test('does not present an older successful run as the current analysis', async () => {
  const sha = createHash('sha256').update(original.text).digest('hex');
  const api = new WorkbenchConnection('http://localhost:8011', async url => {
    if (String(url).includes('/evidence/')) return new Response(original.text);
    return json({ case: { id: 'c', workspace_id: 'w', workflow_version: 'error-analysis-v1', analysis_status: 'needs_refresh', error_analysis_result: result() }, evidence: [{ id: 'e', source_id: 's', source_version: '1', filename: 'source.log', kind: 'original_log', case_id: 'c', workspace_id: 'w', byte_size: Buffer.byteLength(original.text), sha256: sha }], activity: [], route_milestones: [] });
  });
  const saved = await api.readCase(session, 'c', signal());
  assert.equal(saved.brief, null); assert.equal(saved.analysisState, 'needs_refresh');
});
