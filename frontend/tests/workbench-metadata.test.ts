import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { projectSavedBrief, WorkbenchConnection, type SavedWorkbenchCase, type WorkbenchSession } from '../src/lib/workbench-connection';
import { mapSavedCase } from '../src/lib/workbench-mapping';

type Field = { name_as_logged: string; value_as_logged: string; context_as_logged: string | null };
const field = (name: string, value: string, context: string | null = null): Field => ({ name_as_logged: name, value_as_logged: value, context_as_logged: context });
type Line = { raw: string; fields: Field[]; kind?: string };
function fixture(lines: Line[]) {
  const original = { evidenceId: 'e', sourceId: 's', sourceVersion: '1', filename: 'synthetic.log', text: lines.map(line => line.raw).join('') };
  const statement = { text: 'Synthetic document processing stopped.', supporting_entry_ids: ['entry-1'] };
  const result = {
    result_kind: 'error_analysis', outcome: 'completed', limitations: [], workspace_id: 'w', case_id: 'c', run_id: 'run', attempt_id: 'attempt', input_revision: '1',
    extraction: { entries: lines.map((line, index) => ({ entry_id: `entry-${index + 1}`, source_id: 's', source_version: '1', source_span: { line_start: index + 1, line_end: index + 1 }, raw_text: line.raw, fields: line.fields, kind: line.kind || 'metadata' })) },
    analysis: { category_id: 'mapping', cause_hypothesis: 'Mapping may be absent.', supporting_entry_ids: ['entry-1'], route: { category_id: 'mapping' } },
    case_content: { title: statement, what_happened: [statement], document_context: [statement], original_log_evidence: [statement], related_cases: [] },
  };
  const saved = (): SavedWorkbenchCase => ({
    case: { id: 'c', workspace_id: 'w', workflow_version: 'error-analysis-v1', case_number: 'CFIN-2026-000001', source_system: null, source_client: null, source_company_code: null, document_number: null, target_system: null, target_client: null, interface: null, analysis_status: 'available', published_run_id: 'run', current_attempt_id: 'attempt', input_revision: 1 },
    originals: [original], brief: projectSavedBrief(result, [original]), activity: [], routeMilestones: [], evidence: [], assignments: [], resolutions: [], analysisState: 'available', analysisFailure: null,
  });
  return { original, result, saved };
}

// The field spellings and lines below are the shipped synthetic fixtures and saved extraction formats.
const keyValue = () => fixture([
  { raw: 'source_system=ERP-DEMO | source_client=010 | source_company_code=0010\n', fields: [field('source_system', 'ERP-DEMO', 'source'), field('source_client', '010', 'source'), field('source_company_code', '0010', 'source')] },
  { raw: 'fiscal_year=2026 | document_number=0000123456 | source_status=posted\n', kind: 'payload', fields: [field('fiscal_year', '2026'), field('document_number', '0000123456'), field('source_status', 'posted')] },
  { raw: 'target_system=CFIN-DEMO | target_client=100 | target_company_code=0010\n', fields: [field('target_system', 'CFIN-DEMO', 'target'), field('target_client', '100', 'target'), field('target_company_code', '0010', 'target')] },
  { raw: 'interface=DEMO_CFIN_GL | target_chart_of_accounts=SYN1\n', fields: [field('interface', 'DEMO_CFIN_GL'), field('target_chart_of_accounts', 'SYN1')] },
]);

test('projects key=value fixture identity with null legacy columns and preserves leading zeroes', () => {
  const mapped = mapSavedCase(keyValue().saved());
  assert.equal(mapped.document, '0000123456');
  assert.equal(mapped.source, 'ERP-DEMO / 010');
  assert.equal(mapped.company, '0010');
  assert.equal(mapped.target, 'CFIN-DEMO / 100');
  assert.equal(mapped.interface, 'DEMO_CFIN_GL');
  assert.equal(mapped.caseNumber, 'CFIN-2026-000001');
  assert.equal('amount' in mapped, false);
});

test('projects prose/colon fixture fields without conflating source1000 and target2000', () => {
  const saved = fixture([
    { raw: 'Source system: ERP-DEMO; target system: CFIN-DEMO.\r\n', fields: [field('Source system', 'ERP-DEMO'), field('target system', 'CFIN-DEMO')] },
    { raw: 'Source document: 1900000421; fiscal year: 2026; source company: 1000.\r\n', fields: [field('Source document', '1900000421'), field('fiscal year', '2026'), field('source company', '1000')] },
    { raw: 'Target company: 2000; currency: GBP; amount: 1250.00.\r\n', fields: [field('Target company', '2000'), field('currency', 'GBP'), field('amount', '1250.00')] },
    { raw: 'Error Z_DEMO_CFIN 001: G/L account 0000410000 is not maintained in company code 2000.\r\n', kind: 'message', fields: [field('G/L account', '0000410000'), field('company code', '2000')] },
    { raw: 'target document reference: 0099999999.\r\n', fields: [field('target document reference', '0099999999')] },
  ]).saved();
  const mapped = mapSavedCase(saved);
  assert.equal(mapped.source, 'ERP-DEMO'); assert.equal(mapped.target, 'CFIN-DEMO');
  assert.equal(mapped.company, '1000'); assert.equal(mapped.document, '1900000421');
  assert.equal(mapped.interface, 'Not supplied');
  assert.equal(saved.brief?.context.length, 1);
});

test('projects the simple unclassified fixture and leaves genuinely missing fields explicit', () => {
  const mapped = mapSavedCase(fixture([
    { raw: 'Document 0000123458\n', fields: [field('Document', '0000123458')] },
    { raw: 'Source system: ERP-DEMO\n', fields: [field('Source system', 'ERP-DEMO')] },
    { raw: 'Company code: 0010\n', fields: [field('Company code', '0010')] },
  ]).saved());
  assert.equal(mapped.document, '0000123458'); assert.equal(mapped.company, '0010');
  assert.equal(mapped.target, 'Not supplied'); assert.equal(mapped.interface, 'Not supplied');
});

test('retains same-scope conflicts, deduplicates repeats and matches only exact normalized labels', () => {
  const mapped = mapSavedCase(fixture([
    { raw: 'Source-System: ERP-A\n', fields: [field('Source-System', 'ERP-A')] },
    { raw: 'source_system=ERP-B\n', fields: [field('source_system', 'ERP-B')] },
    { raw: 'source_system=ERP-A\n', fields: [field('source_system', 'ERP-A')] },
    { raw: 'backup_source_system=ARCHIVE | source_company_code_hint=9999\n', fields: [field('backup_source_system', 'ARCHIVE'), field('source_company_code_hint', '9999')] },
    { raw: 'target_company_code=2000 | target_document_number=9999999999\n', fields: [field('target_company_code', '2000'), field('target_document_number', '9999999999')] },
    { raw: 'Company code: 2000\n', fields: [field('Company code', '2000', 'target')] },
    { raw: 'constructor=ignored\n', fields: [field('constructor', 'ignored')] },
  ]).saved());
  assert.equal(mapped.source, 'Conflicting values: ERP-A, ERP-B');
  assert.equal(mapped.company, 'Not supplied'); assert.equal(mapped.document, 'Not supplied');
});

test('rejects stripped target scope in otherwise genuine metadata labels and spans', () => {
  const mapped = mapSavedCase(fixture([
    { raw: 'target document number=0099999999\n', kind: 'payload', fields: [field('document number', '0099999999')] },
    { raw: 'Target company code: 2000\n', fields: [field('company code', '2000')] },
    { raw: 'previous source system: ERP-OLD\n', fields: [field('source system', 'ERP-OLD')] },
  ]).saved());
  assert.equal(mapped.document, 'Not supplied'); assert.equal(mapped.company, 'Not supplied');
  assert.equal(mapped.source, 'Not supplied');
});

test('does not accept invented, truncated, swapped or mislabeled field values from a genuine span', () => {
  for (const fields of [
    [field('source_system', 'INVENTED')],
    [field('source_client', '01')],
    [field('source_company_code', '1000')],
    [field('source_company_code', '2000')],
    [field('source_system', 'CFIN-DEMO')],
    [field('company_code', '0010')],
    [field('source_system', 'ERP-DEMO', 'target')],
  ]) {
    const { saved } = fixture([{ raw: 'source_system=ERP-DEMO | source_client=010 | source_company_code=0010 | target_company_code=2000 | target_system=CFIN-DEMO\n', fields }]);
    assert.deepEqual(saved().brief?.metadata, {});
  }
});

test('verifies a metadata entry even when no summary statement cites it', () => {
  const f = keyValue();
  f.result.extraction.entries[1].raw_text = 'document_number=9999999999\n';
  f.result.extraction.entries[1].fields = [field('document_number', '9999999999')];
  assert.throws(() => f.saved(), /differs from its saved original/);
});

test('accepts line-number context only when the field is present on that cited source line', () => {
  const f = fixture([
    { raw: 'source_system=ERP-DEMO | source_company_code=0010\n', fields: [] },
    { raw: 'document_number=0000123600\n', fields: [] },
    { raw: 'target_system=CFIN-DEMO | target_company_code=2000\n', fields: [] },
  ]);
  f.result.extraction.entries = [{
    ...f.result.extraction.entries[0], raw_text: f.original.text,
    source_span: { line_start: 1, line_end: 3 },
    fields: [field('source_system', 'ERP-DEMO', 'line 1'), field('source_company_code', '0010', 'line 1'),
      field('document_number', '0000123600', 'line 2'), field('target_system', 'CFIN-DEMO', 'line 3'),
      field('company_code', '2000', 'line 3')],
  }];
  const mapped = mapSavedCase(f.saved());
  assert.equal(mapped.document, '0000123600'); assert.equal(mapped.source, 'ERP-DEMO');
  assert.equal(mapped.company, '0010'); assert.equal(mapped.target, 'CFIN-DEMO');
  for (const context of ['line 2', 'line 999', 'target record']) {
    f.result.extraction.entries[0].fields = [field('source_system', 'ERP-DEMO', context)];
    assert.deepEqual(f.saved().brief?.metadata, {});
  }
});

test('projects exact identity pairs from a compact header with a verified attempt scope', () => {
  const context = 'attempt_id=BENCH-1-1-A1';
  const f = fixture([
    { raw: `2026-10-09T15:00:00Z | ${context} | event=replication_started\n`, fields: [] },
    { raw: 'source_system=ERP-DEMO | source_client=010 | source_company_code=0010\n', fields: [field('source_system', 'ERP-DEMO', context), field('source_client', '010', context), field('source_company_code', '0010', context)] },
    { raw: 'fiscal_year=2026 | document_number=0000123511 | source_status=posted\n', fields: [field('document_number', '0000123511', context)] },
    { raw: 'target_system=CFIN-DEMO | target_client=100 | target_company_code=2000\n', fields: [field('target_system', 'CFIN-DEMO', context), field('target_client', '100', context), field('target_company_code', '2000', context)] },
    { raw: 'interface=DEMO_CFIN_GL\n', fields: [field('interface', 'DEMO_CFIN_GL', context)] },
  ]);
  f.result.extraction.entries = [{
    ...f.result.extraction.entries[0], raw_text: f.original.text,
    source_span: { line_start: 1, line_end: 5 },
    fields: f.result.extraction.entries.flatMap(entry => entry.fields),
  }];
  const mapped = mapSavedCase(f.saved());
  assert.equal(mapped.document, '0000123511'); assert.equal(mapped.source, 'ERP-DEMO / 010');
  assert.equal(mapped.company, '0010'); assert.equal(mapped.target, 'CFIN-DEMO / 100');
  assert.equal(mapped.interface, 'DEMO_CFIN_GL');
  for (const unsupported of [
    field('document_number', '0000123511', 'attempt_id=BENCH-1-1-A2'),
    field('document_number', '0000123511', 'attempt_id=BENCH-1-1-A'),
    field('document_number', '000012351', context),
    field('source_company_code', '2000', context),
    field('source_system', 'CFIN-DEMO', context),
  ]) {
    f.result.extraction.entries[0].fields = [unsupported];
    assert.deepEqual(f.saved().brief?.metadata, {});
  }
});

test('does not accept unlogged or ambiguous attempt context for an otherwise exact field', () => {
  for (const raw of [
    'document_number=0000123511\n',
    'attempt_id=A1 | document_number=0000123511 | attempt_id=A2\n',
  ]) {
    const f = fixture([{ raw, fields: [field('document_number', '0000123511', 'attempt_id=A1')] }]);
    assert.deepEqual(f.saved().brief?.metadata, {});
  }
});

test('pending and stale analyses do not supply metadata or use raw-log number matching', () => {
  const saved = keyValue().saved();
  saved.analysisState = 'needs_refresh';
  const mapped = mapSavedCase(saved);
  assert.equal(mapped.source, 'Not supplied'); assert.equal(mapped.document, 'Not supplied');
  saved.brief = null; saved.analysisState = 'pending';
  assert.equal(mapSavedCase(saved).company, 'Not supplied');
});

test('readCase requires a current published run, attempt and input revision before projecting identity', async () => {
  const f = keyValue();
  const session: WorkbenchSession = { token: 'local-demo-test', workspace: { id: 'w', name: 'Synthetic', synthetic: true, roles: [] } };
  const evidence = { id: 'e', source_id: 's', source_version: '1', filename: 'synthetic.log', kind: 'original_log', case_id: 'c', workspace_id: 'w', byte_size: Buffer.byteLength(f.original.text), sha256: createHash('sha256').update(f.original.text).digest('hex') };
  for (const change of [{}, { analysis_status: 'pending' }, { published_run_id: 'different' }, { current_attempt_id: 'different' }, { input_revision: 2 }, { published_run_id: null }]) {
    const api = new WorkbenchConnection('http://localhost:8011', async url => {
      if (String(url).includes('/evidence/')) return new Response(f.original.text);
      return Response.json({ case: { ...f.saved().case, ...change }, error_analysis_result: f.result, evidence: [evidence], activity: [], route_milestones: [] });
    });
    const loaded = await api.readCase(session, 'c', new AbortController().signal);
    assert.equal(mapSavedCase(loaded).document, Object.keys(change).length ? 'Not supplied' : '0000123456');
  }
});
