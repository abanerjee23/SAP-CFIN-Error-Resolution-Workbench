import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile, fr } from "@oai/artifact-tool";

const workspaceDir = "/Users/abhinavbanerjee/Documents/ChatGPT/AI led CFIN document error resolution system";
const SKILL_DIR = "/Users/abhinavbanerjee/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations";
const BUILD_DIR = path.join(workspaceDir, ".codex-build", "business-architecture-slides");
const FINAL_PPTX = path.join(BUILD_DIR, "output", "CFIN_Technical_Architecture_v3.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const RUNTIME_PYTHON = "/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";

const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);

const font = resolvePresentationFont();
const c = {
  page: "#F8FAFC",
  white: "#FFFFFF",
  ink: "#172554",
  body: "#253746",
  muted: "#5D6E7B",
  divider: "#C7D2DD",
  code: "#1D4ED8",
  codeFill: "#DBEAFE",
  agent: "#7C3AED",
  agentFill: "#EDE9FE",
  history: "#0F766E",
  historyFill: "#CCFBF1",
  human: "#B45309",
  humanFill: "#FEF3C7",
  external: "#64748B",
  externalFill: "#F1F5F9",
  route: "#475569",
};

await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

function addText(slide, value, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: font,
    fontSize: options.fontSize ?? 18,
    bold: options.bold ?? false,
    color: options.color ?? c.body,
    autoFit: "shrinkText",
  };
  return shape;
}

function addRule(slide, left, top, width) {
  return slide.shapes.add({
    geometry: "line",
    position: { left, top, width, height: 0 },
    fill: "none",
    line: { style: "solid", fill: c.divider, width: 1 },
  });
}

function node(slide, { x, y, w = 235, h = 122, number, title, owner, body, kind }) {
  const palette = {
    code: [c.code, c.codeFill],
    agent: [c.agent, c.agentFill],
    history: [c.history, c.historyFill],
    human: [c.human, c.humanFill],
    external: [c.external, c.externalFill],
  }[kind];
  const box = slide.shapes.add({
    geometry: "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill: palette[1],
    line: { style: "solid", fill: palette[0], width: 1.5 },
    borderRadius: 14,
  });
  const badge = slide.shapes.add({
    geometry: "ellipse",
    position: { left: x + 13, top: y + 12, width: 28, height: 28 },
    fill: palette[0],
    line: { fill: palette[0], width: 0 },
  });
  addText(slide, String(number), x + 13, y + 16, 28, 16, { fontSize: 11, bold: true, color: c.white });
  addText(slide, title, x + 50, y + 9, w - 62, 24, { fontSize: 16, bold: true, color: palette[0] });
  addText(slide, owner, x + 50, y + 31, w - 62, 18, { fontSize: 11, bold: true, color: c.muted });
  addText(slide, body, x + 15, y + 54, w - 30, h - 64, { fontSize: 13, color: c.body });
  return box;
}

function connect(slide, from, to, options = {}) {
  return slide.shapes.connect(from, to, {
    kind: options.kind ?? "elbow",
    fromSide: options.fromSide ?? "right",
    toSide: options.toSide ?? "left",
    line: {
      style: options.dashed ? "dashed" : "solid",
      fill: options.color ?? c.route,
      width: options.dashed ? 1.5 : 2,
    },
    tail: { type: "arrow", width: "sm", length: "sm" },
  });
}

function heading(slide, title, subtitle) {
  addText(slide, title, 58, 35, 930, 43, { fontSize: 32, bold: true, color: c.body });
  addText(slide, subtitle, 60, 84, 1100, 27, { fontSize: 16, color: c.muted });
  addRule(slide, 58, 124, 1164);
}

// Slide 1: full architecture from the README.
{
  const slide = deck.slides.add();
  slide.background.fill = c.page;
  heading(
    slide,
    "Technical architecture",
    "The system preserves source evidence, constrains each agent and keeps approvals with people",
  );

  const intake = node(slide, {
    x: 42, y: 152, number: 1, title: "Ingestion", owner: "CODE",
    body: "Preserves the supplied log, records its version and queues analysis.", kind: "code",
  });
  const extraction = node(slide, {
    x: 337, y: 152, number: 2, title: "Extraction", owner: "AGENT 1 · GPT-6 LUNA",
    body: "Captures every supplied entry, field and source reference.", kind: "agent",
  });
  const analysis = node(slide, {
    x: 632, y: 152, number: 3, title: "Error Analysis", owner: "AGENT 2 · GPT-6.1 SOL",
    body: "Classifies the extracted error and forms a supported cause hypothesis.", kind: "agent",
  });
  const route = node(slide, {
    x: 927, y: 152, number: "R", title: "Controlled route lookup", owner: "CODE TOOL",
    body: "Returns the maintained owner, approval steps, remediation route and escalation.", kind: "code",
  });

  const history = node(slide, {
    x: 42, y: 358, number: 7, title: "Reviewed case history", owner: "CONTROLLED KNOWLEDGE",
    body: "Retains approved findings and supplies eligible prior-case evidence.", kind: "history",
  });
  const summary = node(slide, {
    x: 337, y: 358, number: 4, title: "Summary", owner: "AGENT 3 · GPT-6.1 SOL",
    body: "Writes the cited case brief, uncertainty and relevant historical comparison.", kind: "agent",
  });
  const caseCreation = node(slide, {
    x: 632, y: 358, number: 5, title: "Case creation and routing", owner: "CODE",
    body: "Compiles the case, embeds the original and assigns the configured owner.", kind: "code",
  });
  const human = node(slide, {
    x: 927, y: 358, number: 6, title: "Human review", owner: "PEOPLE",
    body: "Reviews the case and records approvals, evidence, findings and outcomes.", kind: "human",
  });

  const api = node(slide, {
    x: 632, y: 558, number: 8, title: "Case JSON API", owner: "CODE · READ ONLY",
    body: "Serves authorised saved case facts, state and original logs.", kind: "code", h: 105,
  });
  const joule = node(slide, {
    x: 927, y: 558, number: 9, title: "SAP Joule", owner: "FUTURE CONNECTION",
    body: "Reads the case through a configured tool under customer access controls.", kind: "external", h: 105,
  });

  connect(slide, intake, extraction);
  connect(slide, extraction, analysis);
  connect(slide, analysis, route);
  connect(slide, route, summary, { fromSide: "bottom", toSide: "top" });
  connect(slide, history, summary, { dashed: true, color: c.history });
  connect(slide, summary, caseCreation);
  connect(slide, caseCreation, human);
  connect(slide, human, history, { fromSide: "bottom", toSide: "bottom", dashed: true, color: c.history });
  connect(slide, caseCreation, api, { fromSide: "bottom", toSide: "top" });
  slide.shapes.connect(api, joule, {
    kind: "straight",
    fromSide: "right",
    toSide: "left",
    line: { style: "dashed", fill: c.external, width: 1.5 },
    head: { type: "arrow", width: "sm", length: "sm" },
    tail: { type: "arrow", width: "sm", length: "sm" },
  });

  addText(slide, "structured extraction", 502, 284, 160, 18, { fontSize: 11, color: c.muted });
  addText(slide, "governed route", 746, 320, 145, 18, { fontSize: 11, color: c.code, bold: true });
  addText(slide, "eligible history", 216, 393, 116, 18, { fontSize: 11, color: c.history, bold: true });
  addText(slide, "approved learning", 380, 517, 140, 18, { fontSize: 11, color: c.history, bold: true });
  addText(slide, "authorised JSON", 828, 595, 100, 18, { fontSize: 11, color: c.external, bold: true });

  slide.speakerNotes.textFrame.setText("Source: README revised architecture and docs/technical-architecture.md, 2 October 2026. Target Error Analysis architecture. Current runtime remains factual-only until implemented and enabled.");
}

function styleTable(table, rowCount, typeColumn = 0) {
  table.styleOptions = { headerRow: true, bandedRows: false };
  table.borders.assign({ style: "solid", fill: c.divider, width: 1 });
  for (let col = 0; col < 2; col += 1) {
    table.getCell(0, col).fill = c.ink;
    table.getCell(0, col).text.style = { typeface: font, fontSize: 14, bold: true, color: c.white, autoFit: "shrinkText" };
  }
  table.rows[0].height = 43;
  for (let row = 1; row < rowCount; row += 1) {
    table.rows[row].height = 83;
    table.getCell(row, typeColumn).text.style = { typeface: font, fontSize: 14, bold: true, color: c.body, autoFit: "shrinkText" };
    table.getCell(row, 1).text.style = { typeface: font, fontSize: 13, color: c.body, autoFit: "shrinkText" };
  }
}

// Slide 2: plain-language data flow for every block.
{
  const slide = deck.slides.add();
  slide.background.fill = c.white;
  heading(
    slide,
    "What each block receives and produces",
    "Inputs stay bounded. Outputs remain versioned and traceable to the preserved original log.",
  );

  addText(slide, "Analysis path", 58, 143, 540, 28, { fontSize: 20, bold: true, color: c.agent });
  addText(slide, "Case lifecycle and access", 658, 143, 560, 28, { fontSize: 20, bold: true, color: c.code });

  const leftValues = [
    ["Block and owner", "Data flow and result"],
    ["1. Ingestion\nCode", "Receives the AIF log. Saves the immutable original and metadata, then queues analysis."],
    ["2. Extraction\nAgent 1 · GPT-6 Luna", "Receives original content. Returns a comprehensive structured extraction with source references and limitations."],
    ["3. Error Analysis\nAgent 2 · GPT-6.1 Sol", "Receives structured extraction only. Returns an active category or unclassified, a cause hypothesis, evidence references and gaps."],
    ["Route lookup\nCode tool", "Receives the category. Returns the maintained owner, approval sequence, remediation steps and escalation."],
    ["4. Summary\nAgent 3 · GPT-6.1 Sol", "Receives the analysis and route, original citations and authorised history. Returns the readable case brief."],
  ];
  const leftTable = slide.tables.add({
    rows: leftValues.length,
    columns: 2,
    left: 58,
    top: 180,
    width: 555,
    height: 458,
    columnTracks: [fr(1.05), fr(2.15)],
    values: leftValues,
  });
  styleTable(leftTable, leftValues.length);
  leftTable.getCell(1, 0).fill = c.codeFill;
  leftTable.getCell(2, 0).fill = c.agentFill;
  leftTable.getCell(3, 0).fill = c.agentFill;
  leftTable.getCell(4, 0).fill = c.codeFill;
  leftTable.getCell(5, 0).fill = c.agentFill;

  const rightValues = [
    ["Block and owner", "Data flow and result"],
    ["5. Case creation\nCode", "Receives the brief, analysis, route and original. Saves the case, evidence links and ownership state."],
    ["6. Human review\nPeople", "Receives the case and evidence. Records corrections, approvals, implementation evidence and the reprocessing outcome."],
    ["7. Reviewed history\nPeople and code", "Receives approved findings. Publishes eligible, versioned evidence for future Summary Agent runs."],
    ["8. Case JSON API\nCode · read only", "Receives an authenticated request. Returns saved case facts and authorised original-log access."],
    ["9. SAP Joule\nFuture connection", "Receives permitted JSON through a configured tool. This channel has no SAP write authority."],
  ];
  const rightTable = slide.tables.add({
    rows: rightValues.length,
    columns: 2,
    left: 658,
    top: 180,
    width: 564,
    height: 458,
    columnTracks: [fr(1.05), fr(2.15)],
    values: rightValues,
  });
  styleTable(rightTable, rightValues.length);
  rightTable.getCell(1, 0).fill = c.codeFill;
  rightTable.getCell(2, 0).fill = c.humanFill;
  rightTable.getCell(3, 0).fill = c.historyFill;
  rightTable.getCell(4, 0).fill = c.codeFill;
  rightTable.getCell(5, 0).fill = c.externalFill;

  addText(slide, "Key boundary", 58, 662, 95, 19, { fontSize: 13, bold: true, color: c.human });
  addText(slide, "Error Analysis sees structured extraction only. Summary receives the original for citations and only authorised related cases.", 156, 660, 1045, 23, { fontSize: 13, color: c.body });

  slide.speakerNotes.textFrame.setText("Source: README revised architecture and docs/technical-architecture.md, 2 October 2026. The route registry, human approval and saved-case API are code-controlled boundaries.");
}

const candidatePath = path.join(stagingDir, "cfin-technical-architecture-v3-candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);

const finalization = await finalizePresentation({
  explicitTotalSlideCount: 2,
  requiredNativeTableOwnerSlides: [2],
  requiredNativeChartOwnerSlides: [],
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
    "--require-native-table-slide", "2",
  ],
  fontPolicy: { basis: "design", families: [font] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "CFIN_Technical_Architecture_v3.validation.json"),
});

console.log(JSON.stringify({ finalPath: FINAL_PPTX, finalization }, null, 2));
