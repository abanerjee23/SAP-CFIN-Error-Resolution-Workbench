import type { Activity, CaseAttachment, CaseRecord, Role } from '../components/workbench-app';
import type { SavedWorkbenchCase } from './workbench-connection';
import { analysisView } from './analysis-progress';

const people: Record<string, { name: string; role: Role }> = {
  mdg_process_owner: { name: 'Maya Shah', role: 'MDG Process Owner' },
  process_owner: { name: 'Daniel Ross', role: 'RTR Process Owner' },
  data_operations: { name: 'Liam Carter', role: 'Data Operations' },
  cfin_exception_manager: { name: 'Olivia Grant', role: 'CFIN Exception Manager' },
};
export function roleCode(role: Role): string {
  const code = Object.entries(people).find(([, person]) => person.role === role)?.[0];
  if (!code) throw new Error('Select an existing workbench persona.');
  return code;
}
export function closureReference(note: string): string {
  const reference = note.match(/Target document(?: reference)?\s*:\s*([A-Za-z0-9][A-Za-z0-9_/-]{0,149})/i)?.[1];
  if (!reference) throw new Error('Include "Target document: <reference>" in the closure record.');
  return reference;
}
function string(value: unknown, fallback = '') { return typeof value === 'string' && value ? value : fallback; }
function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }

export function mapSavedCase(saved: SavedWorkbenchCase): CaseRecord {
  if (saved.originals.length !== 1) throw new Error('This workbench upload screen supports one original log per case.');
  const item = saved.case, original = saved.originals[0];
  const assignment = [...saved.assignments].sort((a, b) => Number(b.version) - Number(a.version))[0];
  const owner = people[string(assignment?.owner_role)] || { name: 'Unassigned', role: 'CFIN Exception Manager' as Role };
  const closure = saved.resolutions.find(row => row.work_cycle === item.work_cycle);
  const attachments = (ids: unknown, role: string, at: string): CaseAttachment[] => {
    if (!Array.isArray(ids)) return [];
    return ids.map(id => {
      const file = saved.evidence.find(e => e.id === id);
      if (!file) throw new Error('A message attachment is missing from the saved case.');
      return { id: String(id), name: string(file.filename), size: Number(file.byte_size), mimeType: string(file.content_type), uploader: people[role]?.name || 'Recorded user', uploadedAt: at };
    });
  };
  const activity: Activity[] = saved.activity.filter(row => row.event_type !== 'evidence_registered').map(row => {
    const body = object(row.new_value), role = string(row.acting_role), event = string(row.event_type);
    const at = string(row.created_at);
    const kind: Activity['kind'] = event === 'case_assign' ? 'assignment' : event === 'case_record_approval' ? 'approval' : event === 'case_finish_resolution' || event === 'case_set_status' ? 'outcome' : event === 'case_comment' ? 'comment' : event.includes('analysis') ? 'ai' : 'system';
    const title = event === 'case_assign' ? `Reassigned to ${people[string(body.owner_role)]?.name || 'workspace member'}` : event === 'case_record_approval' ? `Approval recorded from ${people[string(body.external_approver_role)]?.name || 'external approver'}` : event === 'case_finish_resolution' ? 'Case closed' : event === 'case_set_status' ? `Status changed to ${{ created: 'Open', in_progress: 'In progress', blocked: 'Blocked' }[string(body.status)] || body.status}` : event === 'case_comment' ? 'Case update' : event.replaceAll('_', ' ');
    return { id: string(row.id), kind, actor: people[role]?.name || 'System', role: people[role]?.role || role, time: at ? new Date(at).toLocaleString() : 'Not recorded', title, detail: string(row.reason, string(body.note)).replace(/^\[Simulated demo persona: [^\]]+\] /, ''), attachments: attachments(body.evidence_ids, role, at), ...(body.external_approver_role ? { externalApprover: people[string(body.external_approver_role)]?.name || 'External approver' } : {}) };
  });
  activity.sort((a, b) => {
    const first = saved.activity.find(row => row.id === a.id), second = saved.activity.find(row => row.id === b.id);
    return string(first?.created_at).localeCompare(string(second?.created_at));
  });
  const brief = saved.analysisState === 'available' ? saved.brief : null;
  const categoryId = brief?.category || string(item.category, 'unclassified');
  const progress = analysisView(saved);
  const category = !brief ? (progress.active ? 'Analysis in progress' : 'Analysis incomplete') : ({ master_data: 'Master data', mapping: 'Mapping', unclassified: 'Unclassified', posting_period: 'Posting period' } as Record<string, string>)[categoryId] || categoryId.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  const routeKind = categoryId === 'master_data' || categoryId === 'mapping' ? categoryId : 'manual';
  const metadata = brief?.metadata || {};
  const identity = (value: string | undefined, canonical: unknown) => value || string(canonical);
  const system = (name: string, client: string) => name ? `${name}${client ? ` / ${client}` : ''}` : client ? `Client ${client}` : 'Not supplied';
  return {
    id: string(item.id), caseNumber: string(item.case_number, 'Not assigned'), title: brief?.title.text || string(item.title, 'Uploaded document error log'), category,
    source: system(identity(metadata.sourceSystem, item.source_system), identity(metadata.sourceClient, item.source_client)),
    target: system(identity(metadata.targetSystem, item.target_system), identity(metadata.targetClient, item.target_client)),
    company: identity(metadata.company, item.source_company_code) || 'Not supplied',
    document: identity(metadata.document, item.document_number) || 'Not supplied',
    interface: identity(metadata.interface, item.interface) || 'Not supplied',
    priority: item.priority === 'P1' || item.priority === 'P3' ? item.priority : 'P2',
    status: closure ? 'Closed' : item.status === 'blocked' ? 'Blocked' : item.status === 'created' ? 'Open' : 'In progress',
    createdAt: string(item.created_at), dueAt: string(item.due_at), updated: 'Saved',
    assignee: owner.name, assigneeRole: owner.role, routeKind, currentStep: 0,
    originalLog: original.text, originalFilename: original.filename, activity, remote: saved,
  };
}
