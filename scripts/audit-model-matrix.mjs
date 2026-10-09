/** Offline projection of real experiment outputs through the unchanged frontend. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { projectSavedBrief } from '../frontend/src/lib/workbench-connection.ts';
import { mapSavedCase } from '../frontend/src/lib/workbench-mapping.ts';

const suite = process.argv[2] || 'model-matrix-20261009';
assert.match(suite, /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/);
const root = resolve(import.meta.dirname, '..');
const reports = [];
for (const profile of ['compact', 'writer_luna', 'writer_low', 'all_luna']) {
  const path = resolve(root, `.local-runtime/latency-benchmark/${suite}-${profile}-c2/report.json`);
  if (!existsSync(path)) continue;
  const report = JSON.parse(readFileSync(path, 'utf8'));
  for (const row of report.runs.filter(row => row.published)) {
    const result = row.analysis_output, source = result.source_manifest.sources[0];
    const bytes = readFileSync(resolve(root, row.path));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), source.content_sha256);
    assert.equal(bytes.length, source.byte_size);
    const originals = [{ evidenceId: 'offline-verification', sourceId: source.source_id,
      sourceVersion: source.source_version, filename: row.file, text: bytes.toString('utf8') }];
    const brief = projectSavedBrief(result, originals);
    assert.ok(brief);
    const saved = { case: { id: row.case_id, case_number: row.case_number, status: 'created' },
      originals, brief, activity: [], routeMilestones: [], evidence: [], assignments: [],
      resolutions: [], analysisState: 'available', analysisFailure: null };
    const mapped = mapSavedCase(saved), expected = row.metadata;
    const wanted = { document: expected.document_number, company: expected.source_company_code,
      source: `${expected.source_system} / ${expected.source_client}`,
      target: `${expected.target_system} / ${expected.target_client}`, interface: expected.interface };
    const mismatches = Object.keys(wanted).filter(key => mapped[key] !== wanted[key]);
    const context = [...brief.context, ...brief.evidence].map(item => item.text).join('\n');
    const targetCompanyVisible = context.includes(`target_company_code: ${expected.target_company_code}`)
      || context.includes(`target_company_code=${expected.target_company_code}`);
    assert.equal(mapped.caseNumber, row.case_number);
    const visible = [...result.case_content.what_happened, ...result.case_content.original_log_evidence];
    const ids = new Set(visible.flatMap(statement => statement.supporting_entry_ids));
    const entries = result.extraction.entries;
    const uncoveredErrors = originals[0].text.split('\n').flatMap((line, index) => {
      if (!line.includes('severity=error')) return [];
      const represented = entries.some(entry => ids.has(entry.entry_id)
        && entry.source_span.line_start <= index + 1 && entry.source_span.line_end >= index + 1);
      return represented ? [] : [index + 1];
    });
    reports.push({ profile, file: row.file, run_id: row.run_id, metadata_mismatches: mismatches,
      target_company_visible: targetCompanyVisible,
      error_lines_not_in_visible_evidence_or_facts: uncoveredErrors,
      passed: !mismatches.length && !uncoveredErrors.length && targetCompanyVisible });
  }
}
console.log(JSON.stringify({ suite, published_cases_checked: reports.length,
  passed: reports.every(row => row.passed), runs: reports }, null, 2));
if (reports.some(row => !row.passed)) process.exitCode = 1;
