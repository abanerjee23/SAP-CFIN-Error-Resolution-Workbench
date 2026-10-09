import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';

const workspaceDir='/Users/abhinavbanerjee/Documents/ChatGPT/AI led CFIN document error resolution system';
const buildDir=path.join(workspaceDir,'.codex-build/cfin-leadership/redesign');
const skillDir='/Users/abhinavbanerjee/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const python='/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
process.env.RUNTIME_NODE_MODULES='/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
process.env.RUNTIME_NODE='/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node';
process.env.RUNTIME_PYTHON=python;
const {finalizePresentation}=await import(pathToFileURL(path.join(skillDir,'container_tools/artifact_tool_utils.mjs')).href);
const source=path.join(workspaceDir,'artifacts/presentations/CFIN_Leadership_Overview_v2.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(source));
await fs.mkdir(buildDir,{recursive:true});
await fs.writeFile(path.join(buildDir,'source.inspect.ndjson'),(await p.inspect({kind:'slide,layout,shape,textbox',maxChars:100000})).ndjson);
for(let i=0;i<3;i++) {
  const s=p.slides.items[i];
  const preview=await p.export({slide:s,format:'png',scale:1});
  await fs.writeFile(path.join(buildDir,`source-${i+1}.png`),new Uint8Array(await preview.arrayBuffer()));
  s.shapes.deleteAll();
}
p.slides.add();
const family='Helvetica Neue';
const C={bg:'#F3F5FA',white:'#FFFFFF',ink:'#152E49',muted:'#53657C',teal:'#087A79',tealLight:'#E0F0EF',blue:'#E4ECFA',blueInk:'#305B92',purple:'#EEE8F9',purpleInk:'#644E94',amber:'#FFF0DC',amberInk:'#906525',line:'#8C9FB8'};

function txt(s,name,value,x,y,w,h,size=27,opts={}) {
  const q=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  q.text=value;q.text.style={typeface:family,fontSize:size,color:opts.color??C.ink,bold:opts.bold??false,alignment:opts.align??'left',verticalAlignment:'top',autoFit:'none',wrap:'square',insets:{top:0,right:0,bottom:0,left:0},...opts};return q;
}
function box(s,name,x,y,w,h,fill,stroke='none',round=12) {
  return s.shapes.add({geometry:'rect',name,position:{left:x,top:y,width:w,height:h},fill,line:{fill:stroke,width:stroke==='none'?0:1.5},borderRadius:round});
}
function arrow(s,a,b,opts={}) {
  return s.shapes.connect(a,b,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:C.line,width:3},tail:{type:'triangle',width:'med',length:'sm'},...opts});
}
function base(i,title,subtitle) {
  const s=p.slides.items[i];s.background.fill=C.bg;
  txt(s,'slide-title',title,56,40,1488,74,54,{bold:true});
  if(subtitle)txt(s,'subtitle',subtitle,56,121,1488,56,28,{color:C.muted});
  return s;
}
function table(s,name,x,y,w,h,widths,values,opts={}) {
  const t=s.tables.add({rows:values.length,columns:widths.length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
  t.styleOptions={headerRow:false,bandedRows:false,firstColumn:false};
  t.borders.assign({fill:C.bg,width:opts.gap??8,style:'solid'});
  for(let r=0;r<values.length;r++) {
    if(opts.rowHeights)t.rows[r].height=opts.rowHeights[r];
    for(let c=0;c<widths.length;c++) {
      const cell=t.getCell(r,c);
      cell.fill=(opts.header&&r===0)?C.ink:c===0?(opts.leftFill??C.ink):(r%2?C.white:'#EAF0F8');
      cell.text.style={typeface:family,fontSize:(opts.header&&r===0)?24:(c===0?(opts.leftSize??28):(opts.bodySize??27)),bold:c===0||(opts.header&&r===0),color:(c===0||(opts.header&&r===0))?C.white:C.ink,autoFit:'none',wrap:'square',verticalAlignment:'middle'};
      const border={width:opts.gap??6,color:C.bg,style:'solid'};
      t.cells.block({row:r,column:c,rowCount:1,columnCount:1}).assign({margins:{left:22,right:22,top:opts.marginY??10,bottom:opts.marginY??10},anchor:'center',borders:{top:border,bottom:border,left:border,right:border}});
    }
  }
  return t;
}

// Slide 1: a native PowerPoint table styled as paired topic/detail tiles.
{
  const s=base(0,'CFIN exception management','Factual case briefs that help support teams understand the reported exception');
  table(s,'scope-topic-detail',56,203,1488,420,[294,1194],[
    ['Purpose and users','Help CFIN support analysts and process owners understand supplied logs before investigation.'],
    ['What the app does','Extracts facts, selects key evidence and summarises reported errors, outcomes and uncertainty. Keeps originals and cites reviewed related cases separately.'],
    ['What it does not do','Does not diagnose root causes, recommend fixes, read live SAP data, change records or reprocess documents.'],
    ['Human controls','People review the brief, record investigation findings and outcomes, and approve what becomes reusable case history.'],
  ],{rowHeights:[98,118,100,104],bodySize:28,leftSize:29,gap:6});
  box(s,'assumptions-block',56,658,1488,194,C.tealLight);
  txt(s,'assumptions-heading','Assumptions and validation',82,677,1436,38,28,{bold:true,color:C.teal});
  const columns=[
    [82,'Built on synthetic AIF data','Representative client logs and analyst\nreview must validate fidelity and value.'],
    [565,'Supplied evidence sets the scope','Missing views and later processing\nattempts remain unknown.'],
    [1048,'Client formats can vary','Customer wording, layouts and fields\nwill shape input support and evaluations.'],
  ];
  for(const [x,title,description] of columns) {
    txt(s,`assumption-${x}-title`,title,x,731,450,34,25,{bold:true});
    txt(s,`assumption-${x}-detail`,description,x,772,450,66,24,{color:C.muted});
  }
  s.speakerNotes.textFrame.setText('The app helps CFIN support teams understand a reported exception before they investigate it. It prepares a factual brief, preserves complete originals and provides traceable evidence. The AI does not diagnose a root cause, recommend a fix or act inside SAP. People retain investigation and resolution responsibility. The application has been built using synthetic AIF examples, not representative client exports. Customer formats, essential-fact retention, unsupported claims, reading effort, latency and cost need representative data and analyst review. Missing uploaded content stays unknown.\n\nSources: current README.md, docs/mvp-brief.md, BUILD.md and synthetic fixture materials, reviewed 2 October 2026.');
}

// Slide 2: detailed editable architecture with explicit stage outputs.
{
  const s=base(1,'Architecture: supplied evidence to a reusable case','Three AI stages, with code handling intake, storage, routing and access controls');
  box(s,'architecture-input',56,187,1488,100,C.blue);
  txt(s,'input-label','WHAT GOES IN',80,210,248,38,25,{bold:true,color:C.blueInk});
  txt(s,'input-details','Supplied AIF text logs: messages, identifiers, payload fields and processing context.\nInitial envelope: 1–8 originals, 8,192 total bytes and 64 lines. Unsupported input is rejected.',344,206,1172,73,26);
  const xs=[56,358,660,962,1264], y=316,w=280,h=295;
  const stages=[
    ['1  Intake','Code','Preserve originals.\nVersion sources.\nQueue processing.','Originals and\nsource references',C.blue,C.blueInk],
    ['2  Extract','Agent 1: GPT-6 Luna','Capture entries,\nfields, exact values\nand limitations.','Full extraction\nwith source links',C.purple,C.purpleInk],
    ['3  Evidence','Agent 2: GPT-6.1 Sol','Select key errors,\ncontext, outcomes\nand gaps.','Selected facts\nand source links',C.purple,C.purpleInk],
    ['4  Summarise','Agent 3: GPT-6.1 Sol','Write factual brief.\nUse reviewed history.\nAttribute past cases.','Brief, gaps and\nrelated cases',C.purple,C.purpleInk],
    ['5  Save case','Code','Save case and links.\nApply owner rules.\nKeep originals.','Case page and\nJSON read API',C.blue,C.blueInk],
  ];
  const nodes=stages.map((a,i)=>{
    const b=box(s,`architecture-stage-${i+1}`,xs[i],y,w,h,a[4]);
    txt(s,`stage-${i+1}-heading`,a[0],xs[i]+20,y+17,w-40,42,28,{bold:true,color:a[5]});
    txt(s,`stage-${i+1}-owner`,a[1],xs[i]+20,y+67,w-40,32,23,{color:a[5]});
    txt(s,`stage-${i+1}-action`,a[2],xs[i]+20,y+112,w-40,104,25);
    txt(s,`stage-${i+1}-outlabel`,'OUT',xs[i]+20,y+217,w-40,28,22,{bold:true,color:a[5]});
    txt(s,`stage-${i+1}-output`,a[3],xs[i]+20,y+248,w-40,63,24);
    return b;
  });
  // Keep the stage outputs within their native editable diagram nodes.
  for(const b of nodes)b.position={...b.position,height:322};
  for(let i=0;i<nodes.length-1;i++)arrow(s,nodes[i],nodes[i+1]);
  txt(s,'history-explanation','Human findings enter reusable history\nthrough review and approval.',56,674,570,78,26,{color:C.muted});
  const review=box(s,'human-review',660,670,280,76,C.amber);
  txt(s,'human-review-text','Human review',680,692,240,36,27,{bold:true,color:C.amberInk});
  const history=box(s,'reviewed-history',962,670,280,76,C.tealLight);
  txt(s,'reviewed-history-text','Reviewed history',982,680,240,34,27,{bold:true,color:C.teal});
  txt(s,'history-agent3-only','Agent 3 only',982,714,240,29,22,{color:C.teal});
  arrow(s,review,history);
  arrow(s,history,nodes[3],{fromSide:'top',toSide:'bottom'});
  txt(s,'original-access','Complete originals and\nfull extraction stay available.',1264,674,280,78,25,{color:C.muted});
  box(s,'architecture-output',56,777,1488,90,C.tealLight);
  txt(s,'output-label','WHAT COMES OUT',80,798,254,37,25,{bold:true,color:C.teal});
  txt(s,'output-details','Factual brief, source links, uncertainties, reviewed related cases and complete originals.\nPeople use the case page; authorised tools consume the same saved data through the JSON API.',344,794,1172,73,25);
  s.speakerNotes.textFrame.setText('The input is supplied UTF-8 AIF evidence, not live SAP data. The initial envelope is one to eight originals, at most 8,192 aggregate bytes and 64 lines; unsupported inputs are rejected without silent truncation. Code preserves originals and source versions. GPT-6 Luna extracts the full supplied content. GPT-6.1 Sol selects evidence, then a separate Sol stage writes the factual brief and reads eligible reviewed history. History reaches Agent 3 only. Code compiles the case, builds source links and applies valid ownership configuration; an unmatched owner remains visibly unassigned. The case page and scoped versioned JSON API serve saved records. API reads do not invoke models or mutate business state. Full originals and extraction remain available. The current factual workflow, portal, history access and machine reads are implemented and locally verified. Intended-environment release checks, semantic/model-quality acceptance and hosted recovery remain distinct gates.\n\nSources: current README.md architecture/model baseline/case JSON API, BUILD.md delivered implementation and verification ledger, reviewed 2 October 2026. The models are a starting benchmark, not proven quality superiority.');
}

// Slide 3: substantial reusable core / client configuration / outcome tiles.
{
  const s=base(2,'Future direction: reusable core, client-specific Joule','A shared app and API supply case evidence for each customer’s SAP workflows');
  const app=box(s,'reusable-core',56,214,440,414,C.ink);
  txt(s,'reusable-core-label','REUSABLE CORE',82,237,388,36,23,{bold:true,color:'#B3E7E0'});
  txt(s,'reusable-core-title','CFIN case platform\nand read API',82,285,388,99,36,{bold:true,color:C.white});
  ['Case briefs and source links','Originals and full extraction','Uncertainty and case state','Reviewed historical references','Human records and audit'].forEach((a,i)=>txt(s,`core-feature-${i}`,a,82,410+i*40,388,37,26,{color:'#E7F0F8'}));
  const joule=box(s,'client-joule',562,214,458,414,C.purple);
  txt(s,'client-joule-label','CUSTOMER CONFIGURATION',590,237,402,36,23,{bold:true,color:C.purpleInk});
  txt(s,'client-joule-title','Joule agents',590,289,402,59,38,{bold:true});
  ['Retrieve case context via API','Check current SAP state','Apply customer business rules','Use permitted SAP tools','Escalate for human approval'].forEach((a,i)=>txt(s,`joule-feature-${i}`,a,590,371+i*46,402,39,27));
  arrow(s,app,joule,{head:{type:'triangle',width:'med',length:'sm'}});
  const sap=box(s,'sap-outcome',1086,214,458,190,C.blue);
  txt(s,'sap-outcome-title','Actions inside SAP',1114,239,402,48,32,{bold:true,color:C.blueInk});
  txt(s,'sap-outcome-description','Check current SAP state.\nExecute permitted steps.\nRetain audit evidence.',1114,295,402,101,26);
  const human=box(s,'human-outcome',1086,438,458,190,C.amber);
  txt(s,'human-outcome-title','Human workflows',1114,464,402,48,32,{bold:true,color:C.amberInk});
  txt(s,'human-outcome-description','Route investigation or approval\nwith evidence and ownership.',1114,526,402,87,27);
  arrow(s,joule,sap,{kind:'elbow',fromSide:'right',toSide:'left'});
  arrow(s,joule,human,{kind:'elbow',fromSide:'right',toSide:'left'});
  box(s,'reuse-configuration-band',56,665,1488,163,C.tealLight);
  txt(s,'reuse-config-title','Reuse and client configuration',82,684,1436,43,29,{bold:true,color:C.teal});
  txt(s,'reuse-description','Reuse the application, case schema,\nAPI contract and evaluation framework.',82,741,668,73,27);
  txt(s,'configure-description','Configure SAP connections, tools, rules and approvals.\nKeep each client’s data and reviewed history separate.',810,741,708,73,26);
  txt(s,'future-boundary','Joule integration and SAP actions are future work. Reading case evidence grants no SAP write authority.',56,850,1488,39,23,{color:C.muted});
  s.speakerNotes.textFrame.setText('The reusable asset is the app core, case schema, evidence controls, evaluation framework and versioned API. The read API is implemented and locally verified; it is the customer Joule connection that remains future integration work. A client-specific Joule agent could read authorised case context and combine it with current SAP checks and customer business rules. Its permitted tools could execute SAP steps or route work to a human for investigation, approval or execution. SAP changes require separate authority and current-state validation. We reuse software and contracts across clients, while each deployment configures its connectors, permissions, ownership, approval rules and reviewed history. Each client retains its own data. This is a proposed integration pattern, not a claim of a working Joule deployment.\n\nSources: current README.md, "Case data as a JSON API" and "How SAP Joule could use it"; BUILD.md delivered machine reads and release gates. SAP documents agents using skills as tools backed by actions and destinations: https://developers.sap.com/tutorials/joulestudio-agent-create/ (reviewed 2 October 2026). Customer-supported edition, entitlements and connection setup determine the exact skill/action or MCP adapter.');
}

// Slide 4: detailed AIF appendix with the previously discussed fictional example.
{
  const s=base(3,'Appendix: reading an AIF log across its views',null);
  box(s,'synthetic-example-disclosure',56,127,1488,55,C.amber);
  txt(s,'synthetic-example-disclosure-text','SYNTHETIC EXAMPLE: fictional values, message codes and field paths. This is not a verified SAP export.',78,139,1444,34,24,{bold:true,color:C.amberInk});
  table(s,'aif-example-table',56,206,1488,540,[222,402,864],[
    ['AIF part','What it gives us','Evidence in the same fictional case'],
    ['Data Messages','Which processing record?\nIdentity, context and status.','Source document 1900000421, company 1000, fiscal year 2026.\nTarget CFIN-DEMO / 100. Attempt 1 reports an error.'],
    ['Log Messages','What was reported?\nMessages, errors and outcomes.','“G/L account 0000410000 is not maintained in company code 2000.”\nPosting stopped. No target document reference was returned.'],
    ['Data Structure','Where does the data sit?\nPayload hierarchy and field links.','The message explicitly links to Items[1].target_gl_account.\nThis locates the reported failure within item 0001.'],
    ['Data Content','What values were supplied?\nFields, labels and leading zeroes.','Item 0001: source account 0000400000, attempted target 0000410000.\nRequested target company 2000, debit GBP 1,250.00.'],
    ['Error details*','What does this refer to?\nIdentity, variables and explanation.','Fictional MSGID Z_DEMO_CFIN, MSGNO 001, MSGTY E.\nSupplied variables identify account 0000410000 and company 2000.'],
  ],{header:true,rowHeights:[50,98,98,98,98,98],leftSize:26,bodySize:23,gap:3,marginY:6});
  box(s,'aif-factual-brief',56,791,1488,67,C.ink);
  txt(s,'aif-factual-brief-label','FACTUAL BRIEF',78,807,229,35,24,{bold:true,color:'#B3E7E0'});
  txt(s,'aif-factual-brief-text','The log reports an account-maintenance error for G/L 0000410000 in company 2000. It says posting stopped.\nOnly attempt 1 is covered. Cause, mapping correctness and later outcome remain unconfirmed.',324,799,1198,56,23,{color:C.white});
  txt(s,'aif-footnote','*Error details are message-level metadata, not a universal fifth tab. Available views, labels and fields vary by configuration.',56,869,1488,27,19,{color:C.muted});
  s.speakerNotes.textFrame.setText('SAP Application Interface Framework, or AIF, presents processing evidence across several views. A data message is a processing record; a log message is an entry emitted while processing it. Several entries do not establish several affected accounting documents. Data Structure locates nested structures and fields, and Data Content shows supplied values. Message details preserve technical identity and variables when present. Error details is a convenient label for metadata associated with a message, not a guaranteed fifth tab. The example here is exactly the fictional teaching scenario in README.md, not the distinct MD-01 fixture. All values, codes, layouts and field paths are fictional. The account/company association is supplied by the example; we do not invent the literal template or MSGV1/MSGV2 order. The evidence supports a reported account-maintenance error and stopped posting for attempt 1. It does not prove root cause, mapping correctness, a suitable fix, current SAP state or later outcome. No returned target reference does not establish that no target document exists. Customer layouts may hide or relabel content; a restart may display only the latest restart messages. The app analyses only the uploaded evidence.\n\nLocal source: README.md, "How the views fit together: one fictional error" and "Understanding the AIF log". Official SAP source links (definitions verified 2 October 2026; sources span releases):\nData Messages: https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/4ff5e0047b0a4351bd963640c680caec.html?version=latest\nLog Messages: https://help.sap.com/docs/SAP_APPLICATION_INTERFACE_FRAMEWORK/1cefaed5b7a3471cb08564e54d5ba866/2e733c049ad7445584ae7adbc7900c69.html\nData Structure: https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/ed18d1cc52c447f78a2e26195f7cb450.html?locale=en-US&state=PRODUCTION&version=202110.002\nData Content: https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/73ac69e929734790ab6c554c30f14e0f.html?locale=en-US&state=PRODUCTION&version=202310.002\nMessage metadata: https://help.sap.com/docs/SAP_NETWEAVER_750/addb96cd90c945dfb3182865363bbc47/4e2106b735d44180e10000000a15822b.html?locale=en-US&state=PRODUCTION&version=7.5.27');
}

const candidatePath=path.join(buildDir,'candidate.pptx');
const finalPath=path.join(workspaceDir,'artifacts/presentations',process.env.CFIN_FINAL_NAME??'CFIN_Leadership_Overview_Redesigned.pptx');
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const result=await finalizePresentation({workspaceDir,candidatePath,finalPath,pythonExecutable:python,integrityValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','1','--require-native-table-slide','4'],explicitTotalSlideCount:4,requiredNativeTableOwnerSlides:[1,4],requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'design',families:[family]},verifyArtifactToolImport:true,receiptPath:path.join(buildDir,`${path.basename(finalPath)}.validation.json`)});
const finalP=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<4;i++) {
  const s=finalP.slides.items[i];const png=await finalP.export({slide:s,format:'png',scale:1});
  await fs.writeFile(path.join(buildDir,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
  const layout=await s.export({format:'layout'});await fs.writeFile(path.join(buildDir,`slide-${i+1}.layout.json`),await layout.text());
}
await fs.writeFile(path.join(buildDir,'final.inspect.ndjson'),(await finalP.inspect({kind:'slide,table,shape,textbox,notes',maxChars:120000})).ndjson);
console.log(JSON.stringify({finalPath,slideCount:4,findings:result.presentationLayout.findingCount,warnings:result.presentationLayout.warnings,integrity:result.packageIntegrity.status},null,2));
