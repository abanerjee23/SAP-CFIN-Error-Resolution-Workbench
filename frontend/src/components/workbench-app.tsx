"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon,
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Divider,
  FileButton,
  Group,
  Modal,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  BriefcaseBusiness,
  Check,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  CalendarDays,
  Download,
  CircleAlert,
  Clock3,
  FileSearch,
  FileText,
  FolderUp,
  MessageSquare,
  PencilLine,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
  UserRoundCheck,
  UsersRound,
  WalletCards,
  XCircle,
} from "lucide-react";
import "./workbench.css";
import { serializeCaseBoardCsv } from "../lib/case-board-csv";

type Page = "about" | "dashboard" | "data" | "cases";
type CaseStatus = "Open" | "In progress" | "Blocked" | "Closed";
type Role = "MDG Process Owner" | "RTR Process Owner" | "Data Operations" | "CFIN Exception Manager";
type CaseAttachment = { id: string; name: string; size: number; mimeType: string; uploader: string; uploadedAt: string };
type CaseRecord = {
  id: string;
  title: string;
  category: string;
  source: string;
  company: string;
  createdAt: string;
  document: string;
  amount: string;
  priority: "P1" | "P2" | "P3";
  status: CaseStatus;
  assignee: string;
  assigneeRole: Role;
  updated: string;
  dueAt: string;
  routeKind: "master_data" | "mapping" | "manual";
  currentStep: number;
  originalLog: string;
  originalFilename?: string;
  activity: Activity[];
};
type Activity = { id: string; kind: "system" | "ai" | "comment" | "approval" | "evidence" | "assignment" | "outcome"; actor: string; role: string; time: string; title: string; detail: string; attachments?: CaseAttachment[]; externalApprover?: string };

const roles: { value: Role; person: string; initials: string; description: string }[] = [
  { value: "MDG Process Owner", person: "Maya Shah", initials: "MS", description: "Investigates, requests approval and records remediation evidence." },
  { value: "RTR Process Owner", person: "Daniel Ross", initials: "DR", description: "Confirms requirements and approves or rejects governed changes." },
  { value: "Data Operations", person: "Liam Carter", initials: "LC", description: "Records reprocessing and CFIN posting outcomes." },
  { value: "CFIN Exception Manager", person: "Olivia Grant", initials: "OG", description: "Coordinates escalation, manual investigation and reassignment." },
];

const routeSteps = {
  master_data: [
    { label: "Route to MDG Process Owner and request RTR approval", owner: "MDG Process Owner", approval: false },
    { label: "RTR decision", owner: "RTR Process Owner", approval: true },
    { label: "Create data and attach evidence", owner: "MDG Process Owner", approval: false },
    { label: "Reprocess document", owner: "Data Operations", approval: false },
    { label: "Validate CFIN posting", owner: "Data Operations", approval: false },
  ],
  mapping: [
    { label: "Confirm mapping", owner: "MDG Process Owner", approval: false },
    { label: "Maintain mapping and attach evidence", owner: "MDG Process Owner", approval: false },
    { label: "RTR approval", owner: "RTR Process Owner", approval: true },
    { label: "Reprocess document", owner: "Data Operations", approval: false },
    { label: "Validate CFIN posting", owner: "Data Operations", approval: false },
  ],
  manual: [
    { label: "Assign investigation owner", owner: "CFIN Exception Manager", approval: false },
    { label: "Investigate and record findings", owner: "CFIN Exception Manager", approval: false },
    { label: "Agree next action", owner: "CFIN Exception Manager", approval: false },
    { label: "Record outcome", owner: "CFIN Exception Manager", approval: false },
  ],
} satisfies Record<CaseRecord["routeKind"], { label: string; owner: Role; approval: boolean }[]>;

const originalMasterLog = `AIF processing log · original-log.txt · version 1
09:00:12  Data message: source document 0000123456 / company 0010
09:00:13  Source system: ERP-DEMO, client 010
09:00:15  Interface: DEMO_CFIN_GL
09:00:17  Target system: CFIN-DEMO, client 100
09:00:22  Item 0001: target G/L account 0041001000
09:00:24  Error: G/L account 0041001000 could not be located for chart SYN1 in CFIN.
09:00:26  Target posting stopped for this attempt.
09:00:27  No target document reference was returned.`;

const seededCases: CaseRecord[] = [
  {
    id: "CFIN-2026-0148", createdAt: "2026-09-30T09:14:00.000Z", title: "Posting stopped: target G/L account issue", category: "Master data", source: "ERP-DEMO / 010", company: "0010", document: "0000123456", amount: "1,250.00 GBP", priority: "P2", status: "In progress", assignee: "Maya Shah", assigneeRole: "MDG Process Owner", updated: "12 min ago", dueAt: "2026-10-01T17:00:00.000Z", routeKind: "master_data", currentStep: 1, originalLog: originalMasterLog,
    activity: [
      { id: "a1", kind: "ai", actor: "Error Analysis workflow", role: "System", time: "09:14", title: "Case brief prepared", detail: "Master-data hypothesis published with cited source evidence. Human validation is required." },
      { id: "a2", kind: "assignment", actor: "Olivia Grant", role: "CFIN Exception Manager", time: "09:18", title: "Assigned to Maya Shah", detail: "MDG Process Owner assigned to progress the master-data route." },
      { id: "a3", kind: "comment", actor: "Maya Shah", role: "MDG Process Owner", time: "09:28", title: "Approval requested from Daniel Ross", detail: "The master-data route assigns the required RTR Process Owner approval to Daniel before any target master-data change.", attachments: [{ id: "a3-request", name: "approval-request-to-daniel.eml", size: 18422, mimeType: "message/rfc822", uploader: "Maya Shah", uploadedAt: "09:28" }] },
    ],
  },
  {
    id: "CFIN-2026-0147", createdAt: "2026-10-03T08:31:00.000Z", title: "Source-to-target mapping needs review", category: "Mapping", source: "AIF / 010", company: "0010", document: "0000123452", amount: "820.00 GBP", priority: "P2", status: "In progress", assignee: "Maya Shah", assigneeRole: "MDG Process Owner", updated: "34 min ago", dueAt: "2026-10-03T17:00:00.000Z", routeKind: "mapping", currentStep: 1, originalLog: "AIF processing log\nMapping key 0087 could not be resolved for source account 41001000.\nTarget posting stopped; no target document was returned.",
    activity: [{ id: "b1", kind: "system", actor: "System", role: "Ingestion", time: "08:31", title: "Original log preserved", detail: "AIF source attached to the case." }, { id: "b2", kind: "comment", actor: "Maya Shah", role: "MDG Process Owner", time: "10:07", title: "Mapping scope confirmed", detail: "Confirmed mapping context with RTR Process Owner; change evidence is being prepared." }],
  },
  {
    id: "CFIN-2026-0146", createdAt: "2026-10-01T10:00:00.000Z", title: "Posting period exception requires investigation", category: "Posting period", source: "S/4HANA / 030", company: "0030", document: "0000123441", amount: "76,400.00 EUR", priority: "P1", status: "In progress", assignee: "Olivia Grant", assigneeRole: "CFIN Exception Manager", updated: "1h ago", dueAt: "2026-10-01T17:00:00.000Z", routeKind: "manual", currentStep: 1, originalLog: "Posting period error: document date falls outside an open target period. No target document reference returned.",
    activity: [{ id: "c1", kind: "ai", actor: "Error Analysis workflow", role: "System", time: "Yesterday", title: "Manual route selected", detail: "Posting period is maintained as a known category but has no pilot remediation route." }, { id: "c2", kind: "assignment", actor: "Olivia Grant", role: "CFIN Exception Manager", time: "Yesterday", title: "Escalation accepted", detail: "Manual investigation is underway." }],
  },
  {
    id: "CFIN-2026-0142", createdAt: "2026-09-29T09:00:00.000Z", title: "Tax determination mismatch", category: "Tax", source: "AIF / 020", company: "0020", document: "0000123389", amount: "4,900.00 GBP", priority: "P3", status: "Closed", assignee: "Liam Carter", assigneeRole: "Data Operations", updated: "Yesterday", dueAt: "2026-10-01T17:00:00.000Z", routeKind: "manual", currentStep: 3, originalLog: "Tax determination mismatch. Reprocessing later returned target document 1900000714.",
    activity: [{ id: "d1", kind: "outcome", actor: "Liam Carter", role: "Data Operations", time: "Yesterday", title: "CFIN posting validated", detail: "Target document 1900000714 recorded with supporting validation evidence." }],
  },
  {
    id: "CFIN-2026-0141", createdAt: "2026-10-03T10:22:00.000Z", title: "Document 0000123387 — processing failure", category: "Unclassified", source: "ERP-DEMO / 010", company: "0010", document: "0000123387", amount: "18,220.00 GBP", priority: "P2", status: "Blocked", assignee: "Olivia Grant", assigneeRole: "CFIN Exception Manager", updated: "24 min ago", dueAt: "2026-10-03T17:00:00.000Z", routeKind: "manual", currentStep: 0, originalLog: "The supplied message does not match a maintained category. Investigation owner required.",
    activity: [{ id: "e1", kind: "system", actor: "Error Analysis workflow", role: "System", time: "10:22", title: "Classified as unclassified", detail: "The extraction did not support one of the maintained categories. No remediation was proposed." }],
  },
];

const statusColor: Record<CaseStatus, string> = { Open: "blue", "In progress": "teal", Blocked: "red", Closed: "green" };
const eventIcon = { system: FileText, ai: Sparkles, comment: MessageSquare, approval: ShieldCheck, evidence: FileSearch, assignment: UsersRound, outcome: BadgeCheck };

function avatarFor(role: Role) { return roles.find((item) => item.value === role) ?? roles[0]; }
function routeFor(item: CaseRecord) { return routeSteps[item.routeKind].map((step) => step.label); }
function routeStepFor(item: CaseRecord) { return routeSteps[item.routeKind][item.currentStep]; }
function personForRole(role: Role) { return avatarFor(role).person; }
function isPastDue(item: CaseRecord) { const due = Date.parse(item.dueAt); return Number.isFinite(due) && due < Date.now() && item.status !== "Closed"; }
function formatDueDate(value: string) { const due = new Date(value); return Number.isFinite(due.getTime()) ? due.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Not set"; }
function dateKey(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function formatCaseDate(value: string) { const date = new Date(value); return Number.isFinite(date.getTime()) ? date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "Not recorded"; }
function isDashboardPriority(item: CaseRecord, persona: Role) {
  const activePerson = personForRole(persona);
  if (item.status === "Closed" || item.assignee !== activePerson) return false;
  return item.status === "Blocked" || isPastDue(item);
}
function priorityRank(a: CaseRecord, b: CaseRecord) {
  const statusRank = (item: CaseRecord) => item.status === "Blocked" ? 0 : 1;
  const priorityValue = (item: CaseRecord) => item.priority === "P1" ? 0 : item.priority === "P2" ? 1 : 2;
  const dueDate = (item: CaseRecord) => Number.isFinite(Date.parse(item.dueAt)) ? Date.parse(item.dueAt) : Infinity;
  return statusRank(a) - statusRank(b) || priorityValue(a) - priorityValue(b) || dueDate(a) - dueDate(b) || a.id.localeCompare(b.id);
}
function isSimulatedAction(role: Role, action: "approval" | "remediation" | "reprocess" | "manage") {
  return (action === "approval" && role === "RTR Process Owner") || (action === "remediation" && role === "MDG Process Owner") || (action === "reprocess" && role === "Data Operations") || (action === "manage" && role === "CFIN Exception Manager");
}
function formatFileSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`; }

export function WorkbenchApp() {
  const [page, setPage] = useState<Page>("dashboard");
  const [persona, setPersona] = useState<Role>("MDG Process Owner");
  const [cases, setCases] = useState<CaseRecord[]>(seededCases);
  const [selectedId, setSelectedId] = useState(seededCases[0].id);
  const [notice, setNotice] = useState("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("cfin-workbench-demo-v3");
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as CaseRecord[];
        if (Array.isArray(parsed) && parsed.length) {
          const fallbackDueAt = new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString();
          setCases(parsed.map((savedCase) => ({ ...savedCase, title: savedCase.title === "Exception requires classification" ? `Document ${savedCase.document} — processing failure` : savedCase.title, createdAt: savedCase.id === "CFIN-2026-0148" && savedCase.createdAt === "2026-10-02T09:14:00.000Z" ? "2026-09-30T09:14:00.000Z" : savedCase.createdAt || seededCases.find((seed) => seed.id === savedCase.id)?.createdAt || "", dueAt: savedCase.dueAt || fallbackDueAt })));
        }
      } catch { /* Local demo data is optional. */ }
    }
    setHydrated(true);
  }, []);
  useEffect(() => { if (hydrated) window.localStorage.setItem("cfin-workbench-demo-v3", JSON.stringify(cases)); }, [cases, hydrated]);

  const currentUser = avatarFor(persona);
  const selected = cases.find((item) => item.id === selectedId) ?? cases[0];
  function updateCase(next: CaseRecord) { setCases((previous) => previous.map((item) => item.id === next.id ? next : item)); setNotice("Saved in this local demo. The activity record is retained after refresh."); }
  function addCase(item: CaseRecord) { setCases((previous) => [item, ...previous]); setSelectedId(item.id); setPage("cases"); setNotice("Original file staged as a local case. Live analysis is not enabled in this preview."); }

  return <div className="workbench-canvas">
    <div className="workbench-frame">
      <header className="workbench-header">
        <div className="workbench-brand"><span>AIF Resolution Workbench</span></div>
        <div className="workbench-user"><span className="demo-label">Local demo</span><Avatar color="teal" radius="xl" size={30}>{currentUser.initials}</Avatar><Select aria-label="Select local demo persona" value={persona} onChange={(value) => setPersona((value as Role) || "MDG Process Owner")} data={roles.map((item) => ({ value: item.value, label: `${item.person} · ${item.value}` }))} className="persona-select" allowDeselect={false} /></div>
      </header>
      <Tabs value={page} onChange={(value) => setPage((value as Page) || "dashboard")} className="workbench-tabs" keepMounted={false}>
        <Tabs.List><Tabs.Tab value="about">About</Tabs.Tab><Tabs.Tab value="dashboard">Dashboard</Tabs.Tab><Tabs.Tab value="data">Data</Tabs.Tab><Tabs.Tab value="cases">Case Board</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="about"><AboutPage onOpenCases={() => setPage("cases")} /></Tabs.Panel>
        <Tabs.Panel value="dashboard"><DashboardPage cases={cases} persona={persona} onOpenCases={() => setPage("cases")} onOpenCase={(id) => { setSelectedId(id); setPage("cases"); }} onUpload={() => setPage("data")} /></Tabs.Panel>
        <Tabs.Panel value="data"><DataPage onAddCase={addCase} /></Tabs.Panel>
        <Tabs.Panel value="cases"><CasesPage cases={cases} selected={selected} selectedId={selectedId} onSelect={setSelectedId} persona={persona} onUpdate={updateCase} /></Tabs.Panel>
      </Tabs>
      {notice && <div className="save-notice" role="status"><CheckCircle2 size={16} />{notice}<button onClick={() => setNotice("")} aria-label="Dismiss saved notice">×</button></div>}
    </div>
  </div>;
}

function PageHeading({ title, description, action, context }: { title: string; description: string; action?: React.ReactNode; context?: React.ReactNode }) {
  return <section className="page-heading"><div className="page-heading-copy"><Title order={1}>{title}</Title><Text>{description}</Text></div>{action || (context && <div className="page-heading-context">{context}</div>)}</section>;
}

function AboutPage({ onOpenCases }: { onOpenCases: () => void }) {
  const principles = [
    { title: "Evidence stays intact", copy: "The original AIF log is retained unchanged. Extracted facts and citations stay traceable to their source.", icon: FileSearch },
    { title: "Automation stays bounded", copy: "The agent uses the maintained taxonomy and proposes only an approved pilot route. Unclear cases remain unclassified for investigation.", icon: Sparkles },
    { title: "People own outcomes", copy: "Process owners approve governed changes. Data Operations records reprocessing, evidence and validated CFIN posting.", icon: ShieldCheck },
  ];
  return <main className="page-content"><PageHeading title="About the workbench" description="AI structures the facts and proposes a route. People validate findings, approve governed changes and confirm CFIN posting. The original AIF log and decision history stay with every case." action={<Button color="teal" rightSection={<ArrowRight size={16} />} onClick={onOpenCases}>Open the Case Board</Button>} />
    <section className="principles-section" aria-labelledby="principles-title">
      <div className="principles-heading"><div><Title id="principles-title" order={2}>Guiding principles</Title><Text c="dimmed">How the workbench earns trust while moving exceptions toward resolution.</Text></div></div>
      <SimpleGrid className="principles-grid" cols={{ base: 1, md: 3 }} spacing="lg">{principles.map(({ title, copy, icon: Icon }) => <Card key={title} className="principle-card" radius="lg"><ThemeIcon className="principle-icon" color="teal" variant="light" size={48} radius="md"><Icon size={22} /></ThemeIcon><Title order={3}>{title}</Title><Text c="dimmed">{copy}</Text></Card>)}</SimpleGrid>
    </section>
    <div className="about-outcome"><Badge color="green" variant="light" leftSection={<CheckCircle2 size={14} />}>Success outcome</Badge><Text>A document successfully posted and validated in CFIN.</Text></div>
  </main>;
}

function DashboardPage({ cases, persona, onOpenCases, onOpenCase, onUpload }: { cases: CaseRecord[]; persona: Role; onOpenCases: () => void; onOpenCase: (id: string) => void; onUpload: () => void }) {
  const open = cases.filter((item) => item.status !== "Closed");
  const unclassified = cases.filter((item) => item.category === "Unclassified").length;
  const bars = [["Master data", 40, "teal"], ["Mapping", 28, "violet"], ["Other maintained categories", 20, "gray"], ["Unclassified", 12, "red"]] as const;
  const priorityCases = open.filter((item) => isDashboardPriority(item, persona)).sort(priorityRank);
  const [idealDays, setIdealDays] = useState(2);
  const [idealInput, setIdealInput] = useState<number | string>(2);
  const [targetOpen, setTargetOpen] = useState(false);
  const [targetLoaded, setTargetLoaded] = useState(false);
  useEffect(() => {
    const stored = window.localStorage.getItem("aif-resolution-ideal-days-v1");
    const parsed = stored === null ? NaN : Number(stored);
    if (Number.isFinite(parsed) && parsed > 0) setIdealDays(parsed);
    setTargetLoaded(true);
  }, []);
  useEffect(() => {
    if (targetLoaded) window.localStorage.setItem("aif-resolution-ideal-days-v1", String(idealDays));
  }, [idealDays, targetLoaded]);
  function openTargetSettings() { if (persona !== "CFIN Exception Manager") return; setIdealInput(idealDays); setTargetOpen(true); }
  function saveTarget() {
    if (persona !== "CFIN Exception Manager" || typeof idealInput !== "number" || !Number.isFinite(idealInput) || idealInput <= 0) return;
    setIdealDays(idealInput);
    setTargetOpen(false);
  }
  return <main className="page-content"><PageHeading title="Key Performance Indicators" description="Operational metrics covering average resolution time, case mix by error type, value of blocked documents and unclassified cases." action={<Button color="teal" leftSection={<FolderUp size={16} />} onClick={onUpload}>Add case data</Button>} />
    <Text className="illustrative-note" size="sm"><span />Illustrative metrics for the local preview</Text>
    <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }} spacing="md" mt="md">
      <ResolutionTimeCard currentDays={1.8} idealDays={idealDays} canSetIdeal={persona === "CFIN Exception Manager"} onSetIdeal={openTargetSettings} />
      <Card className="metric-card metric-violet" radius="lg" padding="lg"><Group justify="space-between" align="start"><Text fw={600}>Cases by error type</Text><ThemeIcon variant="light" color="violet" radius="md"><BriefcaseBusiness size={18} /></ThemeIcon></Group><Stack gap={9} mt="md">{bars.map(([label, value, color]) => <div key={label}><Group justify="space-between" mb={4}><Text size="xs" c="dimmed">{label}</Text><Text size="xs" fw={700}>{value}%</Text></Group><Progress value={value} color={color} size="sm" radius="xl" /></div>)}</Stack></Card>
      <MetricCard title="Document value held up" value="£146k" copy={`${open.length} open cases · GBP sample`} icon={<WalletCards size={19} />} tone="amber" />
      <MetricCard title="Unclassified cases" value={String(unclassified)} copy="Requires manual investigation" icon={<CircleAlert size={19} />} tone="red" />
    </SimpleGrid>
    <Paper className="dashboard-work" radius="lg" p="lg" mt="lg"><Group justify="space-between" align="start"><div><Title order={2}>{personForRole(persona)}'s Priorities</Title><Text c="dimmed" mt={4}>Only cases explicitly assigned to you that are blocked or past due.</Text></div><Button variant="subtle" color="teal" rightSection={<ChevronRight size={16} />} onClick={onOpenCases}>View all cases</Button></Group><div className="attention-list">{priorityCases.map((item) => {
      const label = item.status === "Blocked" ? "Blocked" : "Past due";
      return <button key={item.id} onClick={() => onOpenCase(item.id)}><span className={`priority-dot ${item.priority.toLowerCase()}`} /><div><strong>{item.title}</strong><Text size="sm" c="dimmed">{item.id} · Assigned to {item.assignee}</Text></div><Group gap={6} wrap="nowrap"><Badge color={item.status === "Blocked" ? "red" : "amber"} variant="light">{label}</Badge><StatusBadge status={item.status} /></Group></button>;
    })}{priorityCases.length === 0 && <div className="empty-row"><CheckCircle2 size={22} /><Text>No urgent cases or open actions for this persona.</Text></div>}</div></Paper>
    <Modal opened={targetOpen} onClose={() => setTargetOpen(false)} title="Set ideal resolution time" centered size="sm">
      <Stack gap="md"><Text size="sm" c="dimmed">The current average is compared with this target. Set the ideal average resolution time in days.</Text><NumberInput label="Ideal resolution time" description="Used to show whether current performance is ahead of or over target." value={idealInput} onChange={setIdealInput} min={0.1} max={365} decimalScale={1} step={0.1} suffix=" days" allowDecimal /><Group justify="flex-end"><Button variant="default" onClick={() => setTargetOpen(false)}>Cancel</Button><Button color="teal" disabled={typeof idealInput !== "number" || !Number.isFinite(idealInput) || idealInput <= 0} onClick={saveTarget}>Save target</Button></Group></Stack>
    </Modal>
  </main>;
}

function ResolutionTimeCard({ currentDays, idealDays, canSetIdeal, onSetIdeal }: { currentDays: number; idealDays: number; canSetIdeal: boolean; onSetIdeal: () => void }) {
  const state = currentDays < idealDays ? "good" : currentDays > idealDays ? "bad" : "equal";
  const difference = Math.abs(currentDays - idealDays).toFixed(1);
  const comparison = state === "good" ? `${difference} days under ideal` : state === "bad" ? `${difference} days over ideal` : "At the ideal target";
  const color = state === "good" ? "green" : state === "bad" ? "red" : "gray";
  return <Card className={`metric-card metric-${state}`} radius="lg" padding="lg"><div className="resolution-metric-heading"><Text className="resolution-metric-title" fw={600}>Average resolution time</Text><ThemeIcon className="resolution-metric-icon" variant="light" color={color} radius="md"><Clock3 size={19} /></ThemeIcon></div><Group gap={6} align="baseline" mt={26}><Text className="metric-value">{currentDays.toFixed(1)}</Text><Text c="dimmed" size="sm">days</Text>{canSetIdeal && <Button className="resolution-target-action" variant="subtle" color="teal" size="compact-sm" onClick={onSetIdeal}>Set Ideal?</Button>}</Group><Group justify="space-between" align="center" gap="xs" mt={10}><Text size="sm" c="dimmed">12% lower than last week</Text><Text size="xs" c="dimmed">Ideal {idealDays.toFixed(1)} days</Text></Group><Group gap={7} mt={8}><Badge color={color} variant="light">{comparison}</Badge></Group><div className="metric-rule" /></Card>;
}

function MetricCard({ title, value, suffix, copy, icon, tone }: { title: string; value: string; suffix?: string; copy: string; icon: React.ReactNode; tone: "teal" | "amber" | "red" }) {
  return <Card className={`metric-card metric-${tone}`} radius="lg" padding="lg"><Group justify="space-between" align="start"><Text fw={600}>{title}</Text><ThemeIcon variant="light" color={tone} radius="md">{icon}</ThemeIcon></Group><Group gap={6} align="baseline" mt={26}><Text className="metric-value">{value}</Text>{suffix && <Text c="dimmed" size="sm">{suffix}</Text>}</Group><Text size="sm" c="dimmed" mt={8}>{copy}</Text><div className="metric-rule" /></Card>;
}

function DataPage({ onAddCase }: { onAddCase: (item: CaseRecord) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [raw, setRaw] = useState("");
  const [error, setError] = useState("");
  async function choose(next: File | null) { setFile(next); setError(""); if (!next) { setRaw(""); return; } try { setRaw(await next.text()); } catch { setError("The selected file could not be read as text."); } }
  function create() {
    if (!file || !raw) return;
    const document = raw.match(/\b\d{6,}\b/)?.[0] || "Not found";
    onAddCase({ id: `CFIN-LOCAL-${String(Date.now()).slice(-5)}`, title: document === "Not found" ? "Uploaded document error log" : `Document ${document} — error log`, category: "Unclassified", source: "Flat file", company: "Not found", createdAt: new Date().toISOString(), document, amount: "Not supplied", priority: "P2", status: "In progress", assignee: "Olivia Grant", assigneeRole: "CFIN Exception Manager", updated: "Now", dueAt: new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString(), routeKind: "manual", currentStep: 0, originalLog: raw, originalFilename: file.name, activity: [{ id: "local-intake", kind: "system", actor: "Local demo", role: "Ingestion", time: "Now", title: "Original file preserved", detail: `${file.name} was added as an immutable local source. Analysis has not run in this preview.` }] }); setFile(null); setRaw(""); }
  return <main className="page-content"><PageHeading title="Add case data" description="Upload and review document error logs." />
    <Paper className="upload-panel" radius="lg" p="xl">
      <div className="upload-panel-copy"><Title order={2}>Upload error logs</Title><Text c="dimmed">Upload data using the following supported file types: .txt, .log, .csv and .tsv.</Text></div>
      <div className="upload-panel-picker"><FileButton accept=".txt,.log,.csv,.tsv,text/plain,text/csv" onChange={choose}>{(props) => <Button {...props} color="teal" variant="filled" size="md" leftSection={<Upload size={17} />}>Browse your computer</Button>}</FileButton><Group gap="xs" mt="sm" wrap="nowrap"><Text size="sm" c={file ? "dark" : "dimmed"} className="selected-file-name">{file?.name || "No file selected"}</Text>{file && <Button variant="subtle" color="gray" size="compact-sm" onClick={() => void choose(null)}>Clear</Button>}</Group></div>
      {error && <Alert className="upload-panel-error" color="red">{error}</Alert>}
      {file && <div className="file-facts"><Fact label="File" value={file.name} /><Fact label="Size" value={`${file.size.toLocaleString()} bytes`} /><Fact label="Lines" value={String(raw.split(/\r?\n/).filter(Boolean).length)} /><Fact label="Detected document" value={raw.match(/\b\d{6,}\b/)?.[0] || "Not found"} /></div>}
      <Group className="upload-panel-footer" justify="space-between"><Text size="sm" c="dimmed">The selected file is retained in this browser demo.</Text><Button color="teal" size="md" disabled={!raw} onClick={create}>Create local case <ChevronRight size={16} /></Button></Group>
    </Paper></main>;
}

function DateIntervalCalendar({ opened, onClose, value, onApply }: { opened: boolean; onClose: () => void; value: { start: string; end: string }; onApply: (value: { start: string; end: string }) => void }) {
  const [start, setStart] = useState(value.start);
  const [end, setEnd] = useState(value.end);
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  useEffect(() => {
    if (!opened) return;
    setStart(value.start); setEnd(value.end);
    const initial = value.start ? new Date(`${value.start}T12:00:00`) : new Date();
    setMonth(new Date(initial.getFullYear(), initial.getMonth(), 1));
  }, [opened, value]);
  function choose(day: string) {
    if (!start || end) { setStart(day); setEnd(""); }
    else if (day < start) { setEnd(start); setStart(day); }
    else setEnd(day);
  }
  return <Modal opened={opened} onClose={onClose} title="Date interval" centered size="lg"><Stack gap="md">
    <Text size="sm" c="dimmed">Filter by Case Creation Date. Select the first and last day; both dates are included.</Text>
    <Group justify="space-between"><ActionIcon variant="default" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft size={18} /></ActionIcon><Text fw={650}>{start && !end ? "Select the end date" : "Select the start date"}</Text><ActionIcon variant="default" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight size={18} /></ActionIcon></Group>
    <div className="calendar-months">{[0, 1].map((offset) => {
      const shown = new Date(month.getFullYear(), month.getMonth() + offset, 1);
      const padding = (shown.getDay() + 6) % 7;
      const days = new Date(shown.getFullYear(), shown.getMonth() + 1, 0).getDate();
      return <div className="calendar-month" key={shown.toISOString()}><Text ta="center" fw={650} mb="sm">{shown.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</Text><div className="calendar-grid">{["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((day) => <span className="calendar-weekday" key={day}>{day}</span>)}{Array.from({ length: padding }, (_, index) => <span key={`empty-${index}`} />)}{Array.from({ length: days }, (_, index) => {
        const date = new Date(shown.getFullYear(), shown.getMonth(), index + 1);
        const key = dateKey(date.toISOString());
        const boundary = key === start || key === end;
        const inside = start && end && key > start && key < end;
        return <button type="button" key={key} aria-label={date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })} aria-pressed={boundary || !!inside} className={boundary ? "calendar-day selected" : inside ? "calendar-day in-range" : "calendar-day"} onClick={() => choose(key)}>{index + 1}</button>;
      })}</div></div>;
    })}</div>
    <Text size="sm">{start ? `${formatCaseDate(`${start}T12:00:00`)}${end ? ` – ${formatCaseDate(`${end}T12:00:00`)}` : " – select an end date"}` : "No dates selected"}</Text>
    <Group justify="space-between"><Button variant="subtle" color="gray" onClick={() => onApply({ start: "", end: "" })}>Clear interval</Button><Button color="teal" disabled={!start || !end} onClick={() => onApply({ start, end })}>Apply interval</Button></Group>
  </Stack></Modal>;
}

function CasesPage({ cases, selected, selectedId, onSelect, persona, onUpdate }: { cases: CaseRecord[]; selected: CaseRecord; selectedId: string; onSelect: (id: string) => void; persona: Role; onUpdate: (item: CaseRecord) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [quickView, setQuickView] = useState("All cases");
  const [dateRange, setDateRange] = useState({ start: "", end: "" });
  const [calendarOpen, setCalendarOpen] = useState(false);
  const filtered = useMemo(() => cases.filter((item) => {
    const text = `${item.id} ${item.title} ${item.document} ${item.category} ${item.assignee}`.toLowerCase();
    const queue = quickView !== "Assigned to me" || item.assignee === personForRole(persona);
    const created = dateKey(item.createdAt);
    const inInterval = (!dateRange.start || (created !== "" && created >= dateRange.start)) && (!dateRange.end || (created !== "" && created <= dateRange.end));
    return queue && inInterval && (!status || item.status === status) && text.includes(query.toLowerCase());
  }), [cases, persona, query, quickView, status, dateRange]);
  function downloadCsv() {
    if (!filtered.length) return;
    const rows = [
      ["Case number", "Title", "Error type", "Assigned to", "Status", "Value", "Case Creation Date", "Due Date"],
      ...filtered.map((item) => [item.id, item.title, item.category, `${item.assignee} (${item.assigneeRole})`, item.status, item.amount, formatCaseDate(item.createdAt), formatCaseDate(item.dueAt)]),
    ];
    const url = URL.createObjectURL(new Blob([serializeCaseBoardCsv(rows)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `case-board-${dateKey(new Date().toISOString())}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const [openDetail, setOpenDetail] = useState(false);
  return <main className="page-content"><PageHeading title="Case Board" description="Track ownership, open the case conversation and preserve every decision with its evidence." context={<div className="case-count-context"><strong>{cases.length}</strong><span>{cases.length === 1 ? "case" : "cases"}</span></div>} />
    <div className="board-layout"><section className="case-table-panel"><Paper radius="lg" p={0} className="case-table-paper"><div className="case-table-tools"><div className="quick-views">{["All cases", "Assigned to me"].map((view) => <button key={view} className={quickView === view ? "active" : ""} onClick={() => setQuickView(view)}>{view}</button>)}<button className={dateRange.start ? "active date-filter-button" : "date-filter-button"} onClick={() => setCalendarOpen(true)}><CalendarDays size={15} />Date interval{dateRange.start && <span className="date-filter-dot" />}</button></div><Group gap="sm"><TextInput aria-label="Search cases" placeholder="Search case, document or owner" leftSection={<Search size={16} />} value={query} onChange={(event) => setQuery(event.currentTarget.value)} /><Select aria-label="Filter by status" placeholder="Status" clearable value={status} onChange={setStatus} data={["Open", "In progress", "Blocked", "Closed"]} w={170} /><Button variant="default" leftSection={<Download size={16} />} onClick={downloadCsv} disabled={!filtered.length}>Download as CSV</Button></Group></div>{dateRange.start && <div className="date-interval-summary"><Text size="sm">Created between {formatCaseDate(`${dateRange.start}T00:00:00`)} and {formatCaseDate(`${dateRange.end}T00:00:00`)}</Text><Button variant="subtle" size="compact-sm" color="gray" onClick={() => setDateRange({ start: "", end: "" })}>Clear interval</Button></div>}<ScrollArea><Table className="case-table" highlightOnHover><Table.Thead><Table.Tr><Table.Th>Case number</Table.Th><Table.Th>Title</Table.Th><Table.Th>Error type</Table.Th><Table.Th>Assigned to</Table.Th><Table.Th>Status</Table.Th><Table.Th>Value</Table.Th><Table.Th>Case Creation Date</Table.Th><Table.Th>Due Date</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{filtered.map((item) => <Table.Tr key={item.id} className={item.id === selectedId ? "selected-row" : ""} onClick={() => { onSelect(item.id); setOpenDetail(true); }}><Table.Td><Text fw={700} size="sm">{item.id}</Text><Text size="xs" c="dimmed">Document {item.document}</Text></Table.Td><Table.Td><Text fw={700} size="sm">{item.title}</Text></Table.Td><Table.Td><CategoryBadge value={item.category} /></Table.Td><Table.Td><OwnerChip compact role={item.assigneeRole} name={item.assignee} /></Table.Td><Table.Td><StatusBadge status={item.status} /></Table.Td><Table.Td><Text size="sm" fw={600}>{item.amount}</Text></Table.Td><Table.Td><Text size="sm" className="table-date">{formatCaseDate(item.createdAt)}</Text></Table.Td><Table.Td><Text size="sm" className="table-date" c={isPastDue(item) ? "red" : undefined}>{formatCaseDate(item.dueAt)}</Text></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>{!filtered.length && <div className="empty-row"><Search size={22} /><Text>No cases match these filters.</Text></div>}</Paper></section>
    </div>
    <DateIntervalCalendar opened={calendarOpen} onClose={() => setCalendarOpen(false)} value={dateRange} onApply={(range) => { setDateRange(range); setCalendarOpen(false); }} />
    <Modal opened={openDetail} onClose={() => setOpenDetail(false)} size="calc(100vw - 48px)" classNames={{ content: "case-modal", body: "case-modal-body" }} withCloseButton={false}><CaseWorkspace item={selected} persona={persona} onUpdate={onUpdate} onClose={() => setOpenDetail(false)} /></Modal>
  </main>;
}

function CaseWorkspace({ item, persona, onUpdate, onClose }: { item: CaseRecord; persona: Role; onUpdate: (item: CaseRecord) => void; onClose: () => void }) {
  const [tab, setTab] = useState("summary");
  const [statusOpen, setStatusOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [closureOpen, setClosureOpen] = useState(false);
  const [statusChoice, setStatusChoice] = useState<CaseStatus>(item.status);
  const [reason, setReason] = useState("");
  const [assigneeRole, setAssigneeRole] = useState<Role>(item.assigneeRole);
  const [closureDetail, setClosureDetail] = useState("");
  const [closureFiles, setClosureFiles] = useState<File[]>([]);
  const actor = avatarFor(persona);
  const canManage = isSimulatedAction(persona, "manage");
  const canChangeStatus = canManage || actor.person === item.assignee;
  const canClose = canManage || actor.person === item.assignee;
  function addEvent(kind: Activity["kind"], title: string, detail: string, patch: Partial<CaseRecord> = {}, eventDetails: Pick<Partial<Activity>, "attachments" | "externalApprover"> = {}) {
    onUpdate({ ...item, ...patch, updated: "Now", activity: [...item.activity, { id: `${Date.now()}-${kind}`, kind, actor: actor.person, role: persona, time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), title, detail, ...eventDetails }] });
  }
  function saveStatus() { if (!reason.trim() || statusChoice === "Closed") return; addEvent("outcome", `Status changed to ${statusChoice}`, reason, { status: statusChoice }); setReason(""); setStatusOpen(false); }
  function reassign() { const target = avatarFor(assigneeRole); if (!reason.trim()) return; addEvent("assignment", `Reassigned to ${target.person}`, reason, { assignee: target.person, assigneeRole: target.value }); setReason(""); setAssignOpen(false); }
  function addClosureFiles(selected: File | File[] | null) { const files = Array.isArray(selected) ? selected : selected ? [selected] : []; setClosureFiles((current) => [...current, ...files]); }
  function closeCase() {
    if (!closureDetail.trim() || closureFiles.length === 0) return;
    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const attachments = closureFiles.map((file, index) => ({ id: `${Date.now()}-closure-${index}`, name: file.name, size: file.size, mimeType: file.type || "application/octet-stream", uploader: actor.person, uploadedAt: now }));
    addEvent("outcome", "Case closed", closureDetail.trim(), { status: "Closed", currentStep: routeFor(item).length - 1 }, { attachments });
    setClosureDetail(""); setClosureFiles([]); setClosureOpen(false);
  }
  return <div className="case-workspace"><header className="case-workspace-header">
    <div className="case-header-top"><button className="back-button" onClick={onClose}>← Back to Case Board</button><Text size="sm" c="dimmed">{item.id}</Text></div>
    <Title order={1}>{item.title}</Title>
    <div className="case-header-controls">
      <div className="header-control"><Text size="xs" c="dimmed">Assigned to</Text><OwnerChip compact role={item.assigneeRole} name={item.assignee} /></div>
      <div className="header-control"><Text size="xs" c="dimmed">Status</Text><StatusBadge status={item.status} /></div>
      <div className="header-control"><Text size="xs" c="dimmed">Priority</Text><Text fw={650} size="sm">{item.priority}</Text></div>
      <div className="header-control"><Text size="xs" c="dimmed">Error type</Text><CategoryBadge value={item.category} /></div>
      <div className="header-control"><Text size="xs" c="dimmed">Case Creation Date</Text><Text size="sm" fw={600}>{formatDueDate(item.createdAt)}</Text></div>
      <div className="header-control"><Text size="xs" c="dimmed">Due Date</Text><Text size="sm" fw={600} c={isPastDue(item) ? "red" : undefined}>{formatDueDate(item.dueAt)}</Text></div>
    </div>
    <div className="case-header-footer"><Text size="sm" c="dimmed">Document {item.document} · {item.source} · Company {item.company}</Text><div className="header-actions"><Group mt="md" justify="end"><Tooltip label={canManage ? "Record an attributed case handover" : "Only the CFIN Exception Manager can reassign this case"}><Button variant="default" onClick={() => setAssignOpen(true)} leftSection={<UsersRound size={16} />} disabled={!canManage}>Reassign</Button></Tooltip><Tooltip label={canChangeStatus ? "Record a reason for the status change" : "Only the named owner or CFIN Exception Manager can update this status"}><Button color="teal" onClick={() => setStatusOpen(true)} leftSection={<PencilLine size={16} />} disabled={!canChangeStatus || item.status === "Closed"}>Update status</Button></Tooltip><Tooltip label={canClose ? "Record the closure outcome and attach evidence" : "Only the named owner or CFIN Exception Manager can close this case"}><Button color="green" variant="light" onClick={() => setClosureOpen(true)} leftSection={<CheckCircle2 size={16} />} disabled={!canClose || item.status === "Closed"}>Close case</Button></Tooltip></Group></div></div>
  </header>
    <Tabs value={tab} onChange={(value) => setTab(value || "summary")} className="case-content-tabs"><Tabs.List><Tabs.Tab value="summary" leftSection={<FileText size={15} />}>Summary</Tabs.Tab><Tabs.Tab value="journey" leftSection={<MessageSquare size={15} />}>Case chat</Tabs.Tab><Tabs.Tab value="original" leftSection={<FileSearch size={15} />}>Original log</Tabs.Tab></Tabs.List>
      <Tabs.Panel value="summary"><div className="case-main-grid"><SummaryContent item={item} /></div></Tabs.Panel>
      <Tabs.Panel value="original"><OriginalLog item={item} /></Tabs.Panel>
      <Tabs.Panel value="journey"><JourneyConversation item={item} persona={persona} onPost={(kind, title, detail, attachments, externalApprover) => { const step = routeStepFor(item); const advancesRoute = item.status !== "Closed" && kind === "approval" && step?.approval && externalApprover === personForRole(step.owner); addEvent(kind, title, detail, advancesRoute ? { currentStep: Math.min(item.currentStep + 1, routeFor(item).length - 1), status: "In progress" } : {}, { attachments, externalApprover }); }} /></Tabs.Panel>
    </Tabs>
    <Modal opened={statusOpen} onClose={() => setStatusOpen(false)} title="Update case status" centered><Stack><Text size="sm" c="dimmed">Status changes are recorded in the case chat. Approval is an evidence-backed chat entry, not a status.</Text><Select value={statusChoice} onChange={(value) => setStatusChoice((value as CaseStatus) || item.status)} data={["Open", "In progress", "Blocked"]} label="New status" /><Textarea label="Reason and supporting context" value={reason} onChange={(event) => setReason(event.currentTarget.value)} required minRows={3} /><Button color="teal" onClick={saveStatus} disabled={!reason.trim()}>Save status change</Button></Stack></Modal>
    <Modal opened={assignOpen} onClose={() => setAssignOpen(false)} title="Reassign case" centered><Stack><Text size="sm" c="dimmed">The governed route and RTR approval responsibility remain unchanged. This records a case handover.</Text><Select value={assigneeRole} onChange={(value) => setAssigneeRole((value as Role) || item.assigneeRole)} data={roles.map((role) => ({ value: role.value, label: `${role.person} · ${role.value}` }))} label="New assignee" /><Textarea label="Handover reason" value={reason} onChange={(event) => setReason(event.currentTarget.value)} required minRows={3} /><Button color="teal" onClick={reassign} disabled={!reason.trim()}>Record reassignment</Button></Stack></Modal>
    <Modal opened={closureOpen} onClose={() => setClosureOpen(false)} title="Close case" centered><Stack><Text size="sm" c="dimmed">Create a complete closure record for future audit: what was resolved, the action taken, the CFIN outcome and the supporting proof.</Text><Textarea label="Closure record" description="Include resolution, scope, reprocessing outcome and target document reference where available." value={closureDetail} onChange={(event) => setClosureDetail(event.currentTarget.value)} required minRows={5} /><FileButton multiple onChange={addClosureFiles}>{(props) => <Button {...props} variant="default" leftSection={<Upload size={16} />}>Attach closure evidence</Button>}</FileButton>{closureFiles.length > 0 && <div className="composer-files">{closureFiles.map((file, index) => <div className="composer-file" key={`${file.name}-${index}`}><FileText size={15} /><Text size="sm">{file.name}</Text><Text size="xs" c="dimmed">{formatFileSize(file.size)}</Text><ActionIcon aria-label={`Remove ${file.name}`} variant="subtle" color="gray" size="sm" onClick={() => setClosureFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))}><XCircle size={16} /></ActionIcon></div>)}</div>}<Text size="xs" c={closureFiles.length ? "dimmed" : "red"}>At least one supporting file is required to close a case.</Text><Button color="green" onClick={closeCase} disabled={!closureDetail.trim() || closureFiles.length === 0}>Record closure</Button></Stack></Modal>
  </div>;
}

function SummaryContent({ item }: { item: CaseRecord }) {
  const lines = item.originalLog.split("\n");
  const evidence = lines.map((text, index) => ({ text, line: index + 1 })).filter(({ text }) => /error|stopped|mapping|could not|returned|reference|period|tax|does not match/i.test(text));
  const supplied = (pattern: RegExp) => item.originalLog.match(pattern)?.[1]?.trim() || "Not supplied";
  const report = evidence[0]?.text.replace(/^\d{2}:\d{2}:\d{2}\s+/, "") || "The supplied log requires human review before a specific cause can be established.";
  const hypothesis = item.routeKind === "master_data" ? "The reported target-account lookup failure may indicate missing target master data. A reviewer must check the target system to establish the cause." : item.routeKind === "mapping" ? "The unresolved mapping key may indicate an absent or incorrect source-to-target mapping. A reviewer must confirm the correct mapping with the RTR Process Owner." : "The supplied evidence has not established a confirmed root cause. Record the investigation findings in Case chat.";
  const closure = item.activity.findLast((event) => event.title === "Case closed");
  return <Stack gap="md" className="summary-content">
    <Section title="Case summary"><Text>Document <mark>{item.document}</mark> · {item.source}</Text><Text mt="sm">{report}</Text><FactMarker>Original log · {evidence[0] ? `line ${evidence[0].line}` : "human review required"}</FactMarker><Text size="sm" mt="md"><strong>Proposed cause — requires human validation:</strong> {hypothesis}</Text></Section>
    <Section title="Document and processing context"><div className="context-grid"><Fact label="Source document" value={item.document} /><Fact label="Source system" value={item.source} /><Fact label="Company code" value={item.company} /><Fact label="Amount" value={item.amount} /><Fact label="Target system" value={supplied(/Target system:\s*([^\n]+)/i)} /><Fact label="Interface" value={supplied(/Interface:\s*([^\n]+)/i)} /></div></Section>
    <Section title="Evidence from the original log">{evidence.length ? evidence.map(({ text, line }) => <EvidenceQuote key={line} line={`Original log · line ${line}`} text={text} />) : <Text size="sm">No specific error statement has been isolated. Review the complete Original log.</Text>}</Section>
    <Section title={item.routeKind === "manual" ? "Investigation path" : "Defined resolution and escalation path"}>
      <Text size="sm" c="dimmed" mb="md">{item.routeKind === "manual" ? "This error type has no pilot remediation route. The CFIN Exception Manager coordinates human investigation." : `The maintained ${item.category.toLowerCase()} route defines responsibilities and approval requirements. Case ownership changes only through an explicit handover.`}</Text>
      <ol className="route-list">{routeFor(item).map((step, index) => <li key={step}><span>{index + 1}</span><div><strong>{step}</strong><Text size="sm" c="dimmed">{stepCopy(item.routeKind, index)}</Text></div></li>)}</ol>
    </Section>
    <Section title="Similar earlier cases"><Text size="sm" c="dimmed">No reviewed historical match is available in this local preview.</Text></Section>
    {closure && <Section title="Closure record"><Text size="sm" c="dimmed">Recorded by {closure.actor} · {closure.time}</Text><Text mt="sm">{closure.detail}</Text>{closure.attachments?.map((file) => <Text key={file.id} size="sm" mt="xs">{file.name} · {formatFileSize(file.size)}</Text>)}</Section>}
  </Stack>;
}

function OriginalLog({ item }: { item: CaseRecord }) { return <div className="source-layout"><Paper radius="lg" p="lg" className="source-meta"><Badge color="teal" variant="light" leftSection={<FileText size={13} />}>Immutable original</Badge><Title order={2}>Original AIF log</Title><Text c="dimmed">This source is preserved unchanged. Cited lines are highlighted for cross-validation.</Text><Divider my="lg" /><Fact label="Source" value={item.originalFilename || "Supplied log"} /><Fact label="Version" value="1" /><Fact label="Case Creation Date" value={formatDueDate(item.createdAt)} /><Fact label="Lines" value={String(item.originalLog.split("\n").length)} /></Paper><Paper radius="lg" p={0} className="source-code"><ScrollArea h={460}>{item.originalLog.split("\n").map((line, index) => <div key={`${line}-${index}`} className={/error|stopped|mapping|could not|returned|reference|period|tax|does not match/i.test(line) ? "source-line cited" : "source-line"}><span>{String(index + 1).padStart(2, "0")}</span><code>{line || " "}</code></div>)}</ScrollArea></Paper></div>; }

function JourneyConversation({ item, persona, onPost }: { item: CaseRecord; persona: Role; onPost: (kind: Activity["kind"], title: string, detail: string, attachments: CaseAttachment[], externalApprover?: string) => void }) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"update" | "approval">("update");
  const [approverRole, setApproverRole] = useState<Role>("RTR Process Owner");
  const [files, setFiles] = useState<File[]>([]);
  const actor = avatarFor(persona);
  const isApproval = mode === "approval";
  const addFiles = (selected: File | File[] | null) => {
    const incoming = Array.isArray(selected) ? selected : selected ? [selected] : [];
    setFiles((current) => [...current, ...incoming]);
  };
  const removeFile = (index: number) => setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index));
  const submit = () => {
    if (!message.trim() || (isApproval && files.length === 0)) return;
    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const attachments = files.map((file, index) => ({ id: `${Date.now()}-${index}`, name: file.name, size: file.size, mimeType: file.type || "application/octet-stream", uploader: actor.person, uploadedAt: now }));
    const approver = isApproval ? avatarFor(approverRole).person : undefined;
    onPost(isApproval ? "approval" : "comment", isApproval ? `Approval recorded from ${approver}` : "Case update", message.trim(), attachments, approver);
    setMessage("");
    setFiles([]);
    setMode("update");
  };
  return <div className="conversation-layout">
    <Paper radius="lg" p="lg" className="case-chat-panel">
      <div className="case-chat-heading"><div><Title order={2}>Discussion</Title><Text c="dimmed" size="sm" mt={4}>Updates, decisions and their supporting files.</Text></div><Badge variant="light" color="teal">{item.activity.length} messages</Badge></div>
      <div className="chat-thread">{item.activity.map((event) => { const Icon = eventIcon[event.kind]; const messageActor = roles.find((role) => role.person === event.actor); return <article className={`case-message ${event.kind === "approval" ? "approval-message" : ""}`} key={event.id}><Avatar color={messageActor?.value === "RTR Process Owner" ? "violet" : messageActor?.value === "CFIN Exception Manager" ? "red" : "teal"} radius="xl" size={34}>{messageActor?.initials || <Icon size={16} />}</Avatar><div className="case-message-body"><div className="case-message-meta"><Text fw={700} size="sm">{event.actor}</Text><Text size="xs" c="dimmed">{event.role} · {event.time}</Text></div><Text fw={650} size="sm" mt={4}>{event.title}</Text><Text size="sm" c="dimmed" mt={3}>{event.detail}</Text>{event.externalApprover && <Badge className="external-approver" color="violet" variant="light" mt="sm">External approver: {event.externalApprover}</Badge>}{event.attachments && event.attachments.length > 0 && <div className="message-attachments">{event.attachments.map((attachment) => <div className="message-attachment" key={attachment.id}><FileText size={16} /><div><Text size="sm" fw={650}>{attachment.name}</Text><Text size="xs" c="dimmed">{formatFileSize(attachment.size)} · uploaded by {attachment.uploader} at {attachment.uploadedAt}</Text></div></div>)}</div>}</div></article>; })}</div>
      <Divider my="lg" />
      <div className="message-composer"><Group justify="space-between" align="start" gap="md"><Group gap="sm" wrap="nowrap"><Avatar color="teal" radius="xl" size={34}>{actor.initials}</Avatar><div><Text fw={700} size="sm">Add a comment</Text><Text size="xs" c="dimmed">You are posting as {actor.person}.</Text></div></Group><Select aria-label="Message type" value={mode} onChange={(value) => setMode(value === "approval" ? "approval" : "update")} data={[{ value: "update", label: "Case update" }, { value: "approval", label: "Record approval" }]} w={180} allowDeselect={false} /></Group>
        {isApproval && <div className="approval-composer-fields"><Select aria-label="External approver" label="External approver" description="Attach the email or other approval evidence to this message." value={approverRole} onChange={(value) => setApproverRole((value as Role) || "RTR Process Owner")} data={roles.map((role) => ({ value: role.value, label: `${role.person} · ${role.value}` }))} /></div>}
        <Textarea aria-label="Case message" placeholder={isApproval ? "State what was approved and the scope of that approval…" : "Add an update, decision, blocker or handover…"} minRows={4} mt="md" value={message} onChange={(event) => setMessage(event.currentTarget.value)} />
        {files.length > 0 && <div className="composer-files">{files.map((file, index) => <div className="composer-file" key={`${file.name}-${index}`}><FileText size={15} /><Text size="sm">{file.name}</Text><Text size="xs" c="dimmed">{formatFileSize(file.size)}</Text><ActionIcon aria-label={`Remove ${file.name}`} variant="subtle" color="gray" size="sm" onClick={() => removeFile(index)}><XCircle size={16} /></ActionIcon></div>)}</div>}
        <Group justify="space-between" mt="md" align="center"><FileButton multiple onChange={addFiles}>{(props) => <Button {...props} variant="default" leftSection={<Upload size={16} />}>Attach files</Button>}</FileButton><Group gap="sm"><Text size="xs" c={isApproval && files.length === 0 ? "red" : "dimmed"}>{isApproval ? files.length === 0 ? "Attach the approval email before recording." : "Approval evidence attached." : "Files are optional for a case update."}</Text><Button color="teal" leftSection={<Send size={16} />} onClick={submit} disabled={!message.trim() || (isApproval && files.length === 0)}>{isApproval ? "Record approval" : "Post update"}</Button></Group></Group>
      </div>
    </Paper>
  </div>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <Paper className="summary-section" radius="lg" p="lg"><Title order={2}>{title}</Title><div className="summary-section-body">{children}</div></Paper>; }
function Fact({ label, value }: { label: string; value: string }) { return <div className="fact"><Text size="xs" c="dimmed">{label}</Text><Text fw={600} size="sm">{value}</Text></div>; }
function FactMarker({ children }: { children: React.ReactNode }) { return <Text className="fact-marker" size="xs"><FileText size={12} />{children}</Text>; }
function EvidenceQuote({ line, text }: { line: string; text: string }) { return <div className="evidence-quote"><Text size="xs" c="dimmed">{line}</Text><Text size="sm">“{text}”</Text></div>; }
function OwnerChip({ role, name, compact = false }: { role: Role; name: string; compact?: boolean }) { const owner = avatarFor(role); return <Group gap={8} mt={compact ? 0 : "md"} wrap="nowrap" className="owner-chip"><Avatar color={role === "RTR Process Owner" ? "violet" : role === "CFIN Exception Manager" ? "red" : "teal"} radius="xl" size={27}>{owner.initials}</Avatar><div><Text size="sm" fw={700}>{name}</Text><Text size="xs" c="dimmed">{role}</Text></div></Group>; }
function StatusBadge({ status }: { status: CaseStatus }) { return <Badge color={statusColor[status]} variant="light" radius="sm">{status}</Badge>; }
function CategoryBadge({ value }: { value: string }) { return <Badge color={value === "Unclassified" ? "red" : value === "Mapping" ? "violet" : "teal"} variant="light" radius="sm">{value}</Badge>; }
function stepCopy(kind: CaseRecord["routeKind"], index: number) { const copy = kind === "master_data" ? ["Maya Shah, MDG Process Owner, requests approval from Daniel Ross, RTR Process Owner. The request and supporting files stay in Case chat.", "Daniel Ross approves or rejects the request. If approval is received by email, attach that email to the message recording the decision.", "After approval, Maya Shah creates the data, attaches implementation evidence in Case chat and gives the go-ahead for document reprocessing.", "Liam Carter, Data Operations, reprocesses the document and records the returned CFIN posting result.", "Liam Carter confirms successful posting in CFIN, records the target document reference and attaches validation evidence."] : kind === "mapping" ? ["Maya Shah, MDG Process Owner, confirms the intended mapping with Daniel Ross, RTR Process Owner.", "Maya Shah maintains the agreed mapping and attaches the changed scope and supporting evidence in Case chat.", "Daniel Ross reviews and approves the mapping change. Attach the approval email to the message recording the decision.", "Liam Carter, Data Operations, reprocesses the document and records the returned CFIN posting result.", "Liam Carter confirms successful posting in CFIN, records the target document reference and attaches validation evidence."] : ["CFIN Exception Manager assigns a human investigation owner.", "Record factual findings and their supporting evidence.", "Agree and record a controlled next action.", "Record the outcome, evidence and any remaining gaps."]; return copy[index] || "Review the case journey."; }
