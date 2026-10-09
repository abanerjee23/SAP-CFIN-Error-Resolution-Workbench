import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';

const workspaceDir = '/Users/abhinavbanerjee/Documents/ChatGPT/AI led CFIN document error resolution system';
const buildDir = path.join(workspaceDir, '.codex-build/cfin-leadership');
const outputDir = path.join(workspaceDir, 'artifacts/presentations');
const skillDir = '/Users/abhinavbanerjee/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const python = '/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
process.env.RUNTIME_NODE_MODULES = '/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
process.env.RUNTIME_NODE = '/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node';
process.env.RUNTIME_PYTHON = python;
const { resolvePresentationFont, finalizePresentation } = await import(pathToFileURL(path.join(skillDir, 'container_tools/artifact_tool_utils.mjs')).href);
const family = resolvePresentationFont();
const fontPolicy = { basis: 'design', families: [family] };
const C = { bg:'#F7F5F0', ink:'#15333E', muted:'#536872', teal:'#08766C', blue:'#E4EEF5', blueInk:'#25526A', violet:'#EEE8F7', violetInk:'#675088', amber:'#F4EBDD', amberInk:'#775A2D', history:'#E0EEE7', white:'#FFFFFF', line:'#8B9BA0' };
const p = Presentation.create({slideSize:{width:1600,height:900}});

function text(slide, name, value, x, y, w, h, size=30, opts={}) {
  const s = slide.shapes.add({geometry:'textbox', name, position:{left:x,top:y,width:w,height:h}, fill:'none', line:{fill:'none',width:0}});
  s.text = value;
  s.text.style = {typeface:family,fontSize:size,color:opts.color??C.ink,bold:opts.bold??false,alignment:opts.align??'left',verticalAlignment:'top',wrap:'square',autoFit:'none',insets:{top:0,right:0,bottom:0,left:0},...opts};
  return s;
}
function rect(slide, name, x,y,w,h,fill,stroke='none') {
  return slide.shapes.add({geometry:'rect',name,position:{left:x,top:y,width:w,height:h},fill,line:{fill:stroke,width:stroke==='none'?0:2}});
}
function flow(slide, from, to, options={}) {
  return slide.shapes.connect(from,to,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:C.line,width:2.5},tail:{type:'triangle',width:'sm',length:'sm'},...options});
}
function slide(title, subtitle) {
  const s=p.slides.add(); s.background.fill=C.bg;
  text(s,'slide-title',title,80,66,1440,82,60,{bold:true});
  if (subtitle) text(s,'subtitle',subtitle,80,164,1440,74,29,{color:C.muted});
  return s;
}

// 1 — product scope, exclusions and the hypothesis to validate.
{
  const s=slide('CFIN exception case assistant','A clearer starting point for investigation, grounded in the supplied evidence');
  text(s,'does-heading','What the app does',80,280,830,52,35,{bold:true,color:C.teal});
  text(s,'does-brief','Creates a factual brief of reported errors,\naffected records and processing outcomes.',80,351,850,92,31);
  text(s,'does-evidence','Links statements to evidence and keeps\nmissing or conflicting information visible.',80,463,850,92,31);
  text(s,'does-history','Shows reviewed historical cases separately.',80,574,850,56,31);
  text(s,'does-not-heading','What it does not do',1020,280,500,52,35,{bold:true});
  text(s,'no-diagnosis','No root-cause diagnosis\nor fix recommendations.',1020,351,500,103,31);
  text(s,'no-sap-actions','No live SAP lookup,\ndata changes or reprocessing.',1020,485,500,128,31);
  text(s,'assumption-heading','Working assumption',80,705,370,52,32,{bold:true,color:C.teal});
  text(s,'assumption','Supplied logs contain enough evidence for a useful brief.\nReal samples and analyst review must validate this.',490,704,1030,112,29);
  s.speakerNotes.textFrame.setText('The first job is to make the exception understandable. Analysts currently connect log messages, identifiers and payload details themselves. The app prepares a factual brief with the complete original available for validation. People retain investigation and resolution responsibility. Analysis is limited to what the supplied evidence supports. Faster understanding is an intended benefit, and we will measure it through representative samples and analyst review. Historical records remain separate from present-case evidence.\n\nSources: README.md (product goal, user value and evidence boundaries), docs/mvp-brief.md (agreed scope), docs/md01-walkthrough.md (illustrative case experience). Local project baseline: 2 October 2026.');
}

// 2 — native, editable process diagram with inputs and outputs.
{
  const s=slide('Architecture, inputs and outputs','Three AI stages prepare the brief. Code preserves evidence and manages the case.');
  text(s,'input-heading','INPUT',80,254,580,38,23,{bold:true,color:C.blueInk});
  text(s,'input','Supplied AIF logs and their available context',80,295,665,50,29);
  text(s,'output-heading','OUTPUT',835,254,685,38,23,{bold:true,color:C.teal});
  text(s,'output','Case brief, evidence links, uncertainties,\noriginals and separately cited related cases',835,295,685,84,28);
  const y=410, w=264, h=156, xs=[80,374,668,962,1256];
  const specs=[
    ['Code','Preserve original\nand queue',C.blue,C.blueInk],
    ['Agent 1','Extract entries\nand fields',C.violet,C.violetInk],
    ['Agent 2','Select essential\nevidence',C.violet,C.violetInk],
    ['Agent 3','Write factual\ncase brief',C.violet,C.violetInk],
    ['Code','Save case and\nroute ownership',C.blue,C.blueInk],
  ];
  const nodes=specs.map((a,i)=>{
    const node=rect(s,`stage-${i+1}`,xs[i],y,w,h,a[2]);
    text(s,`stage-${i+1}-owner`,a[0],xs[i]+20,y+17,w-40,40,26,{bold:true,color:a[3]});
    text(s,`stage-${i+1}-task`,a[1],xs[i]+20,y+67,w-40,78,29);
    return node;
  });
  for(let i=0;i<nodes.length-1;i++) flow(s,nodes[i],nodes[i+1]);
  text(s,'original-preservation','The complete original and full extraction\nremain available for review.',80,626,555,94,28,{color:C.muted});
  const human=rect(s,'human-findings',668,653,264,82,C.amber);
  text(s,'human-label','Human findings',688,677,224,44,27,{bold:true,color:C.amberInk});
  const history=rect(s,'reviewed-history',962,653,264,82,C.history);
  text(s,'history-label','Reviewed history',982,677,224,44,27,{bold:true,color:C.teal});
  flow(s,human,history);
  flow(s,history,nodes[3],{fromSide:'top',toSide:'bottom'});
  text(s,'history-control','Approved, authorised records only',1256,651,264,89,25,{color:C.muted});
  text(s,'delivery-status','Status: execution foundation built; intake, storage, case display and history integration remain.',80,808,1440,51,25,{color:C.muted});
  s.speakerNotes.textFrame.setText('Code receives the supplied evidence and preserves it unchanged. Agent 1 captures the supplied entries and fields, Agent 2 selects the essential evidence, and Agent 3 writes a factual brief. Reviewed history feeds Agent 3 only, with past findings attributed to their earlier cases. Code saves and routes the result using available context and valid ownership configuration. The full extraction and original remain available. People record findings through the case workflow, and approved records may become eligible history. The factual contracts, prompts, executor and SDK adapter are implemented with software tests; operational database, intake, portal and history integration remain pending. The diagram is the target architecture, not proof of a completed end-to-end deployment. Model quality, reading time, essential omissions, unsupported claims, latency and cost still require a reviewed baseline.\n\nSources: README.md (revised architecture, structured handoffs and case experience); BUILD.md (current implementation and remaining work); docs/implementation-log.md (2 October 2026 rebuild record). Model baseline in project materials: Agent 1 GPT-6 Luna; Agents 2 and 3 GPT-6.1 Sol. No model superiority or measured benefit is assumed.');
}

// 3 — native, editable future integration and reuse diagram.
{
  const s=slide('Future direction: a reusable app with Joule','The app supplies case evidence. Each client configures how its SAP workflow uses it.');
  const app=rect(s,'reusable-platform',80,329,380,278,C.ink);
  text(s,'reusable-label','REUSABLE CORE',108,355,324,35,23,{bold:true,color:'#A5DCD3'});
  text(s,'app-name','Case platform\nand versioned API',108,405,324,99,37,{bold:true,color:C.white});
  text(s,'app-content','Facts and evidence\nGaps and human records',108,526,324,70,27,{color:'#D9E8E9'});
  const joule=rect(s,'client-joule',605,329,430,278,C.violet);
  text(s,'client-label','CLIENT CONFIGURATION',635,355,370,35,23,{bold:true,color:C.violetInk});
  text(s,'joule-name','Joule agents',635,407,370,60,39,{bold:true});
  text(s,'joule-content','SAP tools and rules\nPermissions and approvals',635,485,370,98,29);
  flow(s,app,joule,{head:{type:'triangle',width:'sm',length:'sm'}});
  text(s,'api-call-label','API reads\nCase data',470,389,125,65,23,{align:'center',color:C.muted});
  const sap=rect(s,'sap-actions',1160,278,360,168,C.blue);
  text(s,'sap-heading','Actions inside SAP',1186,302,308,45,31,{bold:true});
  text(s,'sap-detail','Validate SAP state\nand act with permission',1186,362,308,72,27);
  const people=rect(s,'human-workflow',1160,512,360,168,C.amber);
  text(s,'people-heading','Human workflows',1186,536,308,45,31,{bold:true});
  text(s,'people-detail','Route investigation,\napproval or execution',1186,596,308,72,27);
  flow(s,joule,sap,{kind:'elbow',fromSide:'right',toSide:'left'});
  flow(s,joule,people,{kind:'elbow',fromSide:'right',toSide:'left'});
  text(s,'reuse-statement','Reuse the platform and API contract. Configure tools and controls for each client.',80,730,1440,55,31,{bold:true,color:C.teal});
  text(s,'future-status','Future integration: external API and Joule connection remain to be delivered; each client retains its own data.',80,816,1440,49,24,{color:C.muted});
  s.speakerNotes.textFrame.setText('The reusable asset is the app core and versioned API contract. Customer-specific Joule agents could retrieve authorised case facts, original evidence, uncertainties and permitted human records, then combine that context with current SAP information. Depending on the client workflow, the agent could perform a permitted SAP action or route work to a person for investigation, approval or execution. Case reads do not grant SAP write authority. We reuse the platform while configuring customer connections, tools, ownership rules and controls; each client retains its own data and reviewed history. The external API contract and Joule connection remain future delivery work. Representative client logs and the supported SAP environment determine integration needs. A sensible next step is to validate the core and then pilot one customer-specific Joule workflow.\n\nSources: README.md, section "Case data as a JSON API" and "How SAP Joule could use it"; BUILD.md, external JSON API and hosting/later rollout. SAP documentation confirms that Joule agents can use skills as tools backed by actions and configured destinations: https://developers.sap.com/tutorials/joulestudio-agent-create/ (reviewed 2 October 2026). This supports the proposed tool pattern; it does not establish a working connection to this app.');
}

await fs.mkdir(buildDir,{recursive:true});
await fs.mkdir(outputDir,{recursive:true});
const candidatePath=path.join(buildDir,'candidate.pptx');
const finalPath=path.join(outputDir,process.env.CFIN_FINAL_NAME??'CFIN_Leadership_Overview.pptx');
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const result=await finalizePresentation({
  workspaceDir,candidatePath,finalPath,pythonExecutable:python,
  integrityValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit'],
  explicitTotalSlideCount:3,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],fontPolicy,
  verifyArtifactToolImport:true,receiptPath:path.join(buildDir,`${path.basename(finalPath)}.validation.json`),
});
const finalP=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<3;i++) {
  const s=finalP.slides.items[i];
  const preview=await finalP.export({slide:s,format:'png',scale:1});
  await fs.writeFile(path.join(buildDir,`slide-${i+1}.png`),new Uint8Array(await preview.arrayBuffer()));
  const layout=await s.export({format:'layout'});
  await fs.writeFile(path.join(buildDir,`slide-${i+1}.layout.json`),await layout.text());
}
await fs.writeFile(path.join(buildDir,'inspect.ndjson'),(await finalP.inspect({kind:'slide,textbox,shape,notes',maxChars:100000})).ndjson);
console.log(JSON.stringify({finalPath,font:family,validation:result},null,2));
