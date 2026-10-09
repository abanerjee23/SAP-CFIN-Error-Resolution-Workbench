import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile, fr } from "@oai/artifact-tool";

const workspaceDir = "/Users/abhinavbanerjee/Documents/ChatGPT/AI led CFIN document error resolution system";
const SKILL_DIR = "/Users/abhinavbanerjee/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations";
const TMP_DIR = path.join(workspaceDir, ".codex-build", "business-architecture-slides");
const FINAL_PPTX = path.join(TMP_DIR, "output", "CFIN_Business_Architecture_v2.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const RUNTIME_PYTHON = "/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";

const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);

const font = resolvePresentationFont();
const colors = {
  navy: "#0D1B2A",
  navy2: "#13283B",
  ink: "#142735",
  muted: "#5B6B78",
  white: "#FFFFFF",
  soft: "#F7FAFC",
  line: "#C9D6E2",
  code: "#2D6EA3",
  codeLight: "#DCEEFF",
  agent: "#6A56C8",
  agentLight: "#EEEAFE",
  history: "#0E7C72",
  historyLight: "#DDF6F1",
  people: "#B85C10",
  peopleLight: "#FFF0DB",
  red: "#9D3B4A",
};

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

function text(slide, value, left, top, width, height, options = {}) {
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
    color: options.color ?? colors.ink,
    autoFit: "shrinkText",
    breakLine: false,
  };
  return shape;
}

function rule(slide, left, top, width, color = colors.line) {
  return slide.shapes.add({
    geometry: "line",
    position: { left, top, width, height: 0 },
    fill: "none",
    line: { style: "solid", fill: color, width: 1 },
  });
}

function stage(slide, { x, y, w, h, number, title, body, kind }) {
  const palette = {
    code: [colors.code, colors.codeLight],
    agent: [colors.agent, colors.agentLight],
    history: [colors.history, colors.historyLight],
    people: [colors.people, colors.peopleLight],
  }[kind];
  const card = slide.shapes.add({
    geometry: "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill: palette[1],
    line: { style: "solid", fill: palette[0], width: 1.5 },
    borderRadius: 16,
  });
  const circle = slide.shapes.add({
    geometry: "ellipse",
    position: { left: x + 16, top: y + 15, width: 30, height: 30 },
    fill: palette[0],
    line: { fill: palette[0], width: 0 },
  });
  circle.text = String(number);
  circle.text.style = { typeface: font, fontSize: 14, bold: true, color: colors.white, autoFit: "shrinkText" };
  text(slide, title, x + 55, y + 12, w - 70, 29, { fontSize: 18, bold: true, color: palette[0] });
  text(slide, body, x + 18, y + 52, w - 36, h - 65, { fontSize: 14, color: colors.ink });
  return card;
}

function arrow(slide, from, to, fromSide = "right", toSide = "left", dashed = false) {
  return slide.shapes.connect(from, to, {
    kind: "elbow",
    fromSide,
    toSide,
    line: { style: dashed ? "dashed" : "solid", fill: dashed ? colors.history : "#6F8292", width: dashed ? 1.5 : 2 },
    tail: { type: "arrow", width: dashed ? "sm" : "med", length: dashed ? "sm" : "med" },
  });
}

// Slide 1: business architecture
{
  const slide = deck.slides.add();
  slide.background.fill = colors.soft;
  text(slide, "CFIN document error-management flow", 64, 42, 850, 48, { fontSize: 34, bold: true });
  text(slide, "How an AIF error becomes a reviewable case and a validated CFIN outcome", 66, 93, 950, 28, { fontSize: 17, color: colors.muted });
  rule(slide, 64, 132, 1152, "#B7C5D1");

  const intake = stage(slide, {
    x: 60, y: 185, w: 220, h: 150, number: 1, kind: "code",
    title: "Ingestion", body: "Code preserves the original AIF log and opens a traceable case.",
  });
  const extraction = stage(slide, {
    x: 350, y: 185, w: 230, h: 150, number: 2, kind: "agent",
    title: "Extraction Agent", body: "GPT-6 Luna\nCaptures the log as structured facts with source references.",
  });
  const analysis = stage(slide, {
    x: 650, y: 185, w: 230, h: 150, number: 3, kind: "agent",
    title: "Error Analysis", body: "GPT-6.1 Sol\nUses structured extraction only to propose type, hypothesis and gaps.",
  });
  const route = stage(slide, {
    x: 950, y: 185, w: 270, h: 150, number: 4, kind: "code",
    title: "Route lookup", body: "Code returns the maintained owner, approval route and escalation path.",
  });
  arrow(slide, intake, extraction);
  arrow(slide, extraction, analysis);
  arrow(slide, analysis, route);

  const history = stage(slide, {
    x: 60, y: 457, w: 220, h: 132, number: "", kind: "history",
    title: "Reviewed case history", body: "Eligible past cases provide bounded, cited context.",
  });
  const summary = stage(slide, {
    x: 375, y: 430, w: 290, h: 160, number: 5, kind: "agent",
    title: "Summary Agent", body: "GPT-6.1 Sol\nWrites the readable case using analysis, cited original-log facts and relevant prior cases.",
  });
  const caseBoard = stage(slide, {
    x: 760, y: 430, w: 220, h: 160, number: 6, kind: "code",
    title: "Case board", body: "Shows evidence, owner, route, similar cases and case activity.",
  });
  const human = stage(slide, {
    x: 1050, y: 430, w: 170, h: 160, number: 7, kind: "people",
    title: "Human review", body: "Review, remediation and evidence capture.\n\nSuccessful CFIN posting confirmed.",
  });

  arrow(slide, route, summary, "bottom", "top");
  arrow(slide, summary, caseBoard);
  arrow(slide, caseBoard, human);
  arrow(slide, history, summary, "right", "left", true);
  arrow(slide, intake, summary, "bottom", "top", true);

  text(slide, "Dotted paths: original evidence and authorised history feed Summary only", 372, 614, 600, 24, { fontSize: 13, color: colors.history, bold: true });
  text(slide, "Error Analysis cannot access raw logs, case history or SAP", 672, 153, 430, 20, { fontSize: 13, color: colors.red, bold: true });
  slide.speakerNotes.textFrame.setText("Source: CFIN technical architecture and agreed leadership design, 2 October 2026.");
}

// Slide 2: editable tabular flow
{
  const slide = deck.slides.add();
  slide.background.fill = colors.white;
  text(slide, "Flow, responsibilities and controls", 64, 42, 850, 48, { fontSize: 34, bold: true });
  text(slide, "The model prepares evidence and analysis. Code enforces policy. People own the outcome.", 66, 94, 1010, 28, { fontSize: 17, color: colors.muted });
  rule(slide, 64, 132, 1152, "#B7C5D1");

  const values = [
    ["Stage", "Lead", "What enters", "What the stage produces", "Control that protects the case"],
    ["1. Ingestion", "Code", "AIF error log", "Immutable original and queued case", "Hash, source version and duplicate check"],
    ["2. Extraction", "GPT-6 Luna", "Original log", "Structured facts with source references", "Unfamiliar or missing content remains visible"],
    ["3. Error Analysis", "GPT-6.1 Sol", "Structured extraction only", "Error type, tentative hypothesis and gaps", "No raw log, history, SAP or model-selected remediation"],
    ["4. Route lookup", "Code", "Active error type", "Owner role, approval path and escalation", "Versioned policy registry controls the route"],
    ["5. Summary", "GPT-6.1 Sol", "Analysis, original citations and authorised related cases", "Readable, cited investigator case", "Similar cases support context, never prove the current cause"],
    ["6. Resolution", "People", "Case evidence and governed route", "Approval, change evidence and reprocessing result", "Successful CFIN posting confirmed by people"],
  ];
  const table = slide.tables.add({
    rows: values.length,
    columns: values[0].length,
    left: 64,
    top: 170,
    width: 1152,
    height: 420,
    columnTracks: [fr(1.22), fr(0.92), fr(1.55), fr(1.85), fr(2.18)],
    values,
  });
  table.styleOptions = { headerRow: true, bandedRows: true, firstColumn: false };
  table.borders.assign({ style: "solid", fill: "#C7D3DD", width: 1 });
  for (let c = 0; c < values[0].length; c += 1) {
    table.getCell(0, c).fill = colors.navy;
    table.getCell(0, c).text.style = { typeface: font, fontSize: 14, bold: true, color: colors.white, autoFit: "shrinkText" };
  }
  for (let r = 1; r < values.length; r += 1) {
    const lead = values[r][1];
    const shade = lead === "Code" ? colors.codeLight : lead === "People" ? colors.peopleLight : colors.agentLight;
    table.getCell(r, 1).fill = shade;
    for (let c = 0; c < values[0].length; c += 1) {
      table.getCell(r, c).text.style = { typeface: font, fontSize: 13, color: colors.ink, autoFit: "shrinkText" };
    }
    table.getCell(r, 0).text.style = { typeface: font, fontSize: 13, bold: true, color: colors.ink, autoFit: "shrinkText" };
    table.rows[r].height = 60;
  }
  table.rows[0].height = 52;

  text(slide, "Pilot route: only Master Data and Mapping receive a maintained automated route. All other categories go to the CFIN Exception Manager for manual assignment.", 66, 622, 1135, 38, { fontSize: 15, color: colors.people, bold: true });
  slide.speakerNotes.textFrame.setText("Source: CFIN technical architecture and agreed leadership design, 2 October 2026.");
}

const candidatePath = path.join(stagingDir, "cfin-business-architecture-v2-candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);

const requirements = {
  explicitTotalSlideCount: 2,
  requiredNativeTableOwnerSlides: [2],
  requiredNativeChartOwnerSlides: [],
};
const fontPolicy = { basis: "design", families: [font] };
const finalization = await finalizePresentation({
  ...requirements,
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
  requiredNativeTableOwnerSlides: [2],
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "CFIN_Business_Architecture_v2.validation.json"),
});

console.log(JSON.stringify({ candidatePath, finalPath: FINAL_PPTX, finalization }, null, 2));
