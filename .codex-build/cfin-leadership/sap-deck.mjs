import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const workspaceDir='/Users/abhinavbanerjee/Documents/ChatGPT/AI led CFIN document error resolution system';
const dir=path.join(workspaceDir,'.codex-build/cfin-leadership/sap-focused');
const skill='/Users/abhinavbanerjee/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const python='/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
process.env.RUNTIME_NODE_MODULES='/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
process.env.RUNTIME_NODE='/Users/abhinavbanerjee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node';
process.env.RUNTIME_PYTHON=python;
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const p=await PresentationFile.importPptx(await FileBlob.load(path.join(workspaceDir,'artifacts/presentations/CFIN_Leadership_Overview_Redesigned_Final.pptx')));
await fs.mkdir(dir,{recursive:true});
await fs.writeFile(path.join(dir,'source.inspect.ndjson'),(await p.inspect({kind:'slide,layout,table,shape',maxChars:80000})).ndjson);
for(const s of [...p.slides.items])s.delete();
for(let i=0;i<6;i++)p.slides.add({width:1600,height:900});
const C={bg:'#F3F6FB',ink:'#15304C',white:'#FFFFFF',muted:'#52677F',blue:'#E3EEFA',blueInk:'#2F6095',purple:'#EEE8FA',purpleInk:'#654D94',teal:'#E0F1ED',tealInk:'#0B7870',amber:'#FFF0D8',amberInk:'#8A6025',line:'#8097B1'};
function text(s,name,value,x,y,w,h,size=28,o={}){
 const q=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 q.text=value;q.text.style={typeface:o.font??'Helvetica Neue',fontSize:size,color:o.color??C.ink,bold:o.bold??false,autoFit:'none',wrap:'square',insets:{top:0,right:0,bottom:0,left:0},alignment:o.align??'left'};return q;
}
function box(s,name,x,y,w,h,fill){return s.shapes.add({geometry:'rect',name,position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0},borderRadius:12});}
function arrow(s,a,b,o={}){return s.shapes.connect(a,b,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:C.line,width:3},tail:{type:'triangle',width:'med',length:'med'},...o});}
function base(i,title,subtitle){const s=p.slides.items[i];s.background.fill=C.bg;text(s,'title',title,56,42,1488,75,54,{bold:true});if(subtitle)text(s,'subtitle',subtitle,56,126,1488,55,28,{color:C.muted});return s;}
function table(s,name,x,y,w,h,widths,values,opts={}){
 const t=s.tables.add({rows:values.length,columns:widths.length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
 t.styleOptions={headerRow:false,bandedRows:false};
 for(let r=0;r<values.length;r++){
  if(opts.heights)t.rows[r].height=opts.heights[r];
  for(let c=0;c<widths.length;c++){
   const head=opts.header&&r===0;const cell=t.getCell(r,c);
   cell.fill=head||c===0?C.ink:r%2?C.white:'#EAF0F8';
   cell.text.style={typeface:'Helvetica Neue',fontSize:head?(opts.headerSize??25):(c===0?(opts.labelSize??28):(opts.size??28)),bold:head||c===0,color:head||c===0?C.white:C.ink,wrap:'square',autoFit:'none'};
   const b={width:opts.border??6,color:opts.borderColor??C.bg,style:'solid'};
   t.cells.block({row:r,column:c,rowCount:1,columnCount:1}).assign({margins:{left:opts.marginX??20,right:opts.marginX??20,top:opts.marginY??8,bottom:opts.marginY??8},anchor:'center',borders:{top:b,bottom:b,left:b,right:b}});
  }
 }return t;
}
const local='Sources: README.md, BUILD.md and the AIF example in README.md, reviewed 2 October 2026. Synthetic data does not establish real-client accuracy or time savings. The app has no SAP integration today.';

// 1: Concrete product scope.
{
 const s=base(2,'CFIN exception case from AIF evidence','The product removes routine log reconstruction while preserving the evidence an analyst needs to validate the case.');
 table(s,'product-scope',56,211,1488,479,[372,1116],[
  ['Uploaded AIF evidence','Data Messages, Log Messages, Data Structure, Data Content and any supplied message details. The app keeps the supplied original as the record of evidence.'],
  ['Factual case brief','Reported error, document and source or target context, affected items, reported outcome, explicit gaps and links back to the source.'],
  ['Human led Review','Checks or corrects the brief, investigates in SAP, then records the finding, action, outcome and proof.'],
  ['Reusable case data','The saved case appears in the portal and through a versioned, authenticated, read-only JSON API for authorised consumers.'],
  ['Product boundary','The app does not retrieve live SAP data, diagnose a root cause, recommend a fix or run SAP transactions.'],
 ],{heights:[96,96,96,96,95],size:26,labelSize:26,border:7,marginY:6,marginX:18});
 box(s,'key-things',56,728,1488,128,C.teal);
 text(s,'key-things-heading','Key things to note',84,748,320,38,28,{bold:true,color:C.tealInk});
 text(s,'synthetic-note','Built on synthetic AIF data',436,748,484,38,26,{bold:true});
 text(s,'no-sap-note','No SAP integration today',1018,748,442,38,26,{bold:true});
 text(s,'key-things-detail','Real AIF samples and human semantic acceptance remain the evidence needed before claims about production quality or time saved.',84,802,1372,31,22,{color:C.ink});
 s.speakerNotes.textFrame.setText('The product turns an uploaded AIF evidence package into a factual exception case. The case shows what the supplied evidence reports, source and target context, affected items, reported outcome and gaps, with source references back to the original. Human led Review remains responsible for investigation in SAP, a correction where needed and the resulting record. The saved case can be read through the portal or authorised, versioned JSON API. The product does not connect to SAP, diagnose root cause, recommend a fix or execute SAP work. The current product uses synthetic AIF data, so real samples and human semantic acceptance are still needed before any production-quality or time-saving claim.\n\n'+local);
}

// 2: User-requested architecture: input, code-led ingestion/storage, agent workflow and human review.
{
 const s=base(0,'CFIN case-creation architecture','Raw AIF evidence becomes a routed case. Human led Review validates the root cause in SAP and creates the history used in later summaries.');
 const rawInput=box(s,'raw-aif-input',56,230,300,160,C.blue);
 text(s,'raw-aif-input-title','Raw AIF log',80,250,252,36,28,{bold:true,color:C.blueInk});
 text(s,'raw-aif-input-owner','Input data',80,295,252,28,21,{bold:true,color:C.blueInk});
 text(s,'raw-aif-input-detail','Flat file, AIF integration\nor supplied export',80,330,252,45,22);
 const ingestion=box(s,'ingestion-code',56,440,300,176,C.blue);
 text(s,'ingestion-title','Ingestion',80,460,252,36,28,{bold:true,color:C.blueInk});
 text(s,'ingestion-owner','Code led',80,505,252,28,21,{bold:true,color:C.blueInk});
 text(s,'ingestion-detail','Accept the log, capture metadata\nand start the workflow',80,540,252,55,20);
 const rawStore=box(s,'raw-log-store',56,670,300,130,C.blue);
 text(s,'raw-store-title','Raw log storage',80,689,252,34,27,{bold:true,color:C.blueInk});
 text(s,'raw-store-detail','Original file and metadata\nkept unchanged',80,734,252,44,22);
 const extraction=box(s,'agent-extraction',440,266,330,180,C.purple);
 text(s,'extraction-title','Extraction',464,287,282,36,29,{bold:true,color:C.purpleInk});
 text(s,'extraction-owner','Agent led',464,332,282,28,21,{bold:true,color:C.purpleInk});
 text(s,'extraction-detail','Extract every supplied detail\nand structure it for the next agent',464,370,282,56,22);
 const analysis=box(s,'agent-error-analysis',440,540,330,196,C.purple);
 text(s,'analysis-title','Error Analysis',464,561,282,36,29,{bold:true,color:C.purpleInk});
 text(s,'analysis-owner','Agent led',464,606,282,28,21,{bold:true,color:C.purpleInk});
 text(s,'analysis-detail','Identify likely cause and\nsupporting evidence for\nHuman led Review',464,643,282,72,22);
 const summary=box(s,'agent-summary',850,258,330,190,C.purple);
 text(s,'summary-title','Summary',874,279,282,36,29,{bold:true,color:C.purpleInk});
 text(s,'summary-owner','Agent led',874,324,282,28,21,{bold:true,color:C.purpleInk});
 text(s,'summary-detail','Summarise the analysis, cite\nthe raw log and add similar\nhistorical cases for reference',874,361,282,74,22);
 const caseCreate=box(s,'case-creation',1238,258,306,190,C.blue);
 text(s,'case-creation-title','Case creation + API',1262,279,258,36,27,{bold:true,color:C.blueInk});
 text(s,'case-creation-owner','Code led',1262,324,258,28,21,{bold:true,color:C.blueInk});
 text(s,'case-creation-detail','Create the case, route the owner\nand expose it to other systems',1262,361,258,64,22);
 const humanReview=box(s,'human-review',1238,520,306,216,C.amber);
 text(s,'human-review-title','Human led Review',1262,541,258,36,27,{bold:true,color:C.amberInk});
 text(s,'human-review-detail','Review the case and raw log\nValidate in SAP and confirm\nthe root cause\nLog meaningful comments',1262,592,258,100,20);
 const history=box(s,'case-log-board',850,566,330,146,C.teal);
 text(s,'case-log-title','Case log board',874,587,282,36,28,{bold:true,color:C.tealInk});
 text(s,'case-log-detail','Meaningful review comments\nand similar historical cases',874,634,282,49,22);
 arrow(s,rawInput,ingestion,{kind:'elbow',fromSide:'bottom',toSide:'top'});
 arrow(s,ingestion,rawStore,{kind:'elbow',fromSide:'bottom',toSide:'top'});
 arrow(s,rawStore,extraction,{kind:'elbow',fromSide:'right',toSide:'left'});
 arrow(s,extraction,analysis,{kind:'elbow',fromSide:'bottom',toSide:'top'});
 arrow(s,analysis,summary,{kind:'elbow',fromSide:'right',toSide:'left'});
 arrow(s,summary,caseCreate);
 arrow(s,caseCreate,humanReview,{kind:'elbow',fromSide:'bottom',toSide:'top'});
 arrow(s,humanReview,history,{fromSide:'left',toSide:'right'});
 arrow(s,history,summary,{kind:'elbow',fromSide:'top',toSide:'bottom'});
 text(s,'history-summary-label','Historical cases feed Summary',872,514,300,29,20,{bold:true,color:C.tealInk});
 text(s,'architecture-legend','Blue = code led   Purple = agent led   Amber = Human led Review   Teal = reviewed case history',56,840,1488,28,20,{color:C.muted});
 s.speakerNotes.textFrame.setText('This is the intended case-creation architecture. Raw AIF evidence may arrive as a flat file, through an AIF integration or as another supplied export. Code-led ingestion captures metadata and starts the workflow. Code stores the original raw log and metadata unchanged. The Extraction agent turns the supplied detail into structured information. The Error Analysis agent identifies root-cause hypotheses and the supporting evidence needed for a person to investigate. The Summary agent makes this readable, cites the raw source for validation and adds relevant historical cases from the case log board. Code creates a routed case and provides an API export for other authorised systems. Human led Review cross-references the raw evidence, validates the case in SAP, confirms the root cause and records meaningful comments. Those reviewed records populate the case log board for later summaries.\n\n'+local);
}

// 3: Detailed table that explains the requested architecture.
{
 const s=base(1,'Architecture explained','The flow separates machine preparation from the human confirmation required before a case becomes reusable knowledge.');
 table(s,'stage-explanation',56,198,1488,610,[220,410,418,440],[
  ['Stage','Input','Output','What happens next'],
  ['1. Raw AIF log','Flat file, AIF integration or other\nsupplied export.','Source file or payload.','Ingestion accepts the supplied evidence.'],
  ['2. Ingestion\nCode led','Raw AIF log.','Original reference plus metadata.','The app stores the raw log unchanged\nand starts the agent workflow.'],
  ['3. Raw log storage\nCode led','Raw file plus metadata.','Traceable original evidence.','Extraction receives the original content\nand source reference.'],
  ['4. Extraction\nAgent led','Raw log and metadata.','Structured details, values, messages,\ncontext and limitations.','Error Analysis receives the structured\nrecord rather than a loose log.'],
  ['5. Error Analysis\nAgent led','Structured extraction.','Root-cause hypothesis plus supporting\nevidence for investigation.','Summary receives the analysis and the\nevidence it needs to cite.'],
  ['6. Summary\nAgent led','Error analysis, raw-log references\nand case log board history.','Readable case summary with source\ncitations and related cases.','Case creation saves, routes and exports\nthe case through the API.'],
  ['7. Case creation\nCode led','Summary and evidence references.','Routed case, assigned owner and\nexportable API record.','Human led Review receives the case.'],
  ['8. Human led Review\nand case log board','Case summary, raw log and live\nSAP validation.','Confirmed root cause and meaningful\ncomments, outcomes and evidence.','Reviewed cases become future context\nfor the Summary agent.'],
 ],{header:true,heights:[46,68,68,68,72,72,72,72,72],labelSize:18,size:18,headerSize:22,border:4,marginY:3,marginX:13});
 text(s,'architecture-note','The case log board stores reviewed history for future reference. Humans in the loop validate root cause in SAP before that history informs another case.',56,826,1488,34,20,{color:C.muted});
 s.speakerNotes.textFrame.setText('The table explains every handoff. The input can be a flat file, an AIF integration or another supplied export. Code-led ingestion stores the raw evidence and metadata. The Extraction agent turns the raw content into structured detail. The Error Analysis agent prepares a root-cause hypothesis and evidence for investigation. The Summary agent cites raw evidence and adds relevant reviewed historical cases. Code creates and routes the case, and makes it exportable through the API. Human led Review validates the case in SAP, confirms the root cause and records meaningful comments and outcome. Humans in the loop control which reviewed cases become available to the Summary agent later.\n\n'+local);
}

// 4: SAP-focused future with the requested human-review wording.
{
 const s=base(3,'Future: Joule agents use the app in SAP','Reuse the app. Set up Joule agents for each customer’s SAP process.');
 const app=box(s,'future-app',56,218,442,360,C.ink);
 text(s,'future-app-title','CFIN app + API',82,248,390,54,37,{bold:true,color:C.white});
 ['Case summary','Original AIF log','Related cases','Review findings'].forEach((v,i)=>text(s,'future-app-data-'+i,v,82,333+i*51,390,42,30,{color:'#E6F0F8'}));
 const joule=box(s,'future-joule',574,218,450,360,C.purple);
 text(s,'future-joule-title','Joule agents',600,248,398,54,37,{bold:true});
 text(s,'future-joule-detail','Read case data\nCheck live SAP data\nApply customer rules\nChoose the next step',600,333,398,211,30);
 arrow(s,app,joule,{head:{type:'triangle',width:'med',length:'med'}});
 const sap=box(s,'future-sap',1100,218,444,163,C.blue);
 text(s,'future-sap-title','Actions in SAP',1124,240,396,43,31,{bold:true,color:C.blueInk});
 text(s,'future-sap-detail','Run permitted SAP steps\nRecord the result',1124,302,396,68,28);
 const human=box(s,'future-human',1100,415,444,163,C.amber);
 text(s,'future-human-title','Human led Review',1124,438,396,43,31,{bold:true,color:C.amberInk});
 text(s,'future-human-detail','Humans in the loop approve\nor carry out the SAP work.',1124,496,396,76,27);
 arrow(s,joule,sap,{kind:'elbow'});arrow(s,joule,human,{kind:'elbow'});
 table(s,'reuse-client-setup',56,638,1488,176,[320,1168],[
  ['Reuse across clients','The app, API, case format and evaluation checks.'],
  ['Set up per customer','SAP connections, tools, permissions, approval rules and reviewed case history.'],
 ],{heights:[88,88],size:29,labelSize:28,border:6});
 text(s,'future-boundary','Joule integration is future work. SAP actions need current checks and customer approval rules.',56,852,1488,36,23,{color:C.muted});
 s.speakerNotes.textFrame.setText('A customer-configured Joule agent could call the app API, read the saved case and original evidence, and check current information in the customer SAP system. It could then run a permitted SAP step or send the work to Human led Review. Humans in the loop approve or carry out actions where the customer workflow requires it. The reusable asset remains the CFIN app, case format, API and evaluation checks; SAP tools, permissions, approval rules and reviewed history are configured per customer. Customer data remains separate. Joule integration and SAP actions are future work, and app API read access grants no SAP write authority. The app has no SAP integration today.\n\nSources: README.md case JSON API and Joule integration sections; BUILD.md. Official SAP example of agents using skills as tools, actions and destinations: https://developers.sap.com/tutorials/joulestudio-agent-create/ (reviewed 2 October 2026).');
}

// 5: the full previously discussed fictional AIF views and concrete values.
{
 const s=base(4,'AIF example: document, messages and values','Document 1900000421. All values, message codes and field paths below are fictional.');
 box(s,'aif-data-messages',56,207,650,298,C.white);
 text(s,'aif-data-messages-title','Data Messages',78,227,606,43,30,{bold:true,color:C.blueInk});
 table(s,'aif-data-message-fields',78,275,606,216,[258,348],[['Source document','1900000421'],['Source company','1000'],['Fiscal year','2026'],['Target / client','CFIN-DEMO / 100'],['Attempt','1'],['Reported status','Error']],{heights:[36,36,36,36,36,36],size:23,labelSize:23,border:2,borderColor:C.white,marginY:3,marginX:12});
 box(s,'aif-data-content',56,527,650,319,C.white);
 text(s,'aif-data-content-title','Data Content',78,547,606,43,30,{bold:true,color:C.blueInk});
 table(s,'aif-data-content-fields',78,596,606,230,[258,348],[['Item','0001'],['Source G/L account','0000400000'],['Attempted target G/L','0000410000'],['Target company','2000'],['Debit','GBP 1,250.00']],{heights:[46,46,46,46,46],size:25,labelSize:23,border:2,borderColor:C.white,marginY:4,marginX:12});
 box(s,'aif-log-messages',730,207,814,224,C.white);
 text(s,'aif-log-messages-title','Log Messages',754,227,766,43,30,{bold:true,color:C.blueInk});
 text(s,'aif-reported-error','“G/L account 0000410000 is not maintained\nin company code 2000.”',754,284,766,76,28);
 text(s,'aif-reported-outcome','Posting stopped for attempt 1.\nNo target document reference was returned.',754,367,766,64,25);
 box(s,'aif-data-structure',730,449,814,114,C.white);
 text(s,'aif-data-structure-title','Data Structure: error field link',754,467,766,40,28,{bold:true,color:C.blueInk});
 text(s,'aif-field-path','Items[1].target_gl_account',754,514,766,39,27,{font:'Courier New'});
 box(s,'aif-error-details',730,581,814,265,C.white);
 text(s,'aif-error-details-title','Error details',754,600,766,42,30,{bold:true,color:C.blueInk});
 table(s,'aif-message-fields',754,650,766,148,[218,548],[['MSGTY','E (Error)'],['MSGID','Z_DEMO_CFIN'],['MSGNO','001'],['Message values','Account 0000410000, company 2000']],{heights:[37,37,37,37],size:23,labelSize:23,border:2,borderColor:C.white,marginY:3,marginX:12});
 text(s,'aif-template-note','Exact template and MSGV1–MSGV4 order are not shown here.',754,816,766,27,20,{color:C.muted});
 text(s,'aif-example-limit','Synthetic teaching example, not an SAP export. Error details are message metadata, not a universal fifth tab.',56,869,1488,28,19,{color:C.muted});
 s.speakerNotes.textFrame.setText('This is the same fictional multi-view AIF teaching example in README.md, now shown with its concrete values rather than only view descriptions. Data Messages identifies source document 1900000421, company 1000, fiscal year 2026, target CFIN-DEMO/100 and error attempt 1. Log Messages reports an account-maintenance error for G/L 0000410000 and company 2000, stopped posting, and no returned target document reference. Data Structure supplies the explicit link Items[1].target_gl_account. Data Content retains item 0001, source account 0000400000, attempted target 0000410000, company 2000 and GBP 1,250.00 debit. Error details preserves fictional MSGID Z_DEMO_CFIN, MSGNO 001 and MSGTY E. The example associates the account and company with message values but does not show the exact template or ordered MSGV1–MSGV4 slots, so these are not invented. AIF can include long text and message details, but none is invented for this example. The log describes what was reported for this attempt; it does not independently establish root cause, mapping correctness, a fix, current SAP state or a later outcome.\n\nLocal source: README.md, Understanding the AIF log and How the views fit together: one fictional error. Official sources for AIF view concepts: https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/4ff5e0047b0a4351bd963640c680caec.html?version=latest ; https://help.sap.com/docs/SAP_APPLICATION_INTERFACE_FRAMEWORK/1cefaed5b7a3471cb08564e54d5ba866/2e733c049ad7445584ae7adbc7900c69.html ; https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/ed18d1cc52c447f78a2e26195f7cb450.html?locale=en-US&state=PRODUCTION&version=202110.002 ; https://help.sap.com/docs/ABAP_PLATFORM_NEW/4db1676c3f114f119b500bd80ccd944d/73ac69e929734790ab6c554c30f14e0f.html?locale=en-US&state=PRODUCTION&version=202310.002 ; https://help.sap.com/docs/SAP_NETWEAVER_750/addb96cd90c945dfb3182865363bbc47/4e2106b735d44180e10000000a15822b.html?locale=en-US&state=PRODUCTION&version=7.5.27 . Sources span releases and were reviewed 2 October 2026.');
}

// 6: the complete actual synthetic development fixture, without omitted lines.
{
 const original=await fs.readFile(path.join(workspaceDir,'fixtures/MD-01/agent-visible/original-log.txt'),'utf8');
 const s=base(5,'AIF example: full log used in development','MD-01, document 0000123456. Synthetic application log, not an SAP export.');
 box(s,'full-original-log',56,205,1488,637,C.ink);
 text(s,'full-original-log-text',original.trimEnd(),80,224,1440,600,23,{font:'Courier New',color:'#E5F0FA'});
 text(s,'full-log-note','Complete original shown. This is a different synthetic example from the multi-view case on the previous slide.',56,861,1488,31,21,{color:C.muted});
 s.speakerNotes.textFrame.setText('This is the complete 17-line MD-01 synthetic development log from fixtures/MD-01/agent-visible/original-log.txt. No source lines have been omitted. It is a fictional application log, not a verified SAP AIF export. It is separate from the preceding teaching case. It contains the attempt and timestamp, source and target identifiers, source posting state, chart, both accounting lines and amounts, the reported lookup error, requested company and target line, stopped posting, and the explicit limit to this attempt. The original is preserved unchanged in the application. Missing SAP release semantics, real message class/number, template, long text or mapping evidence must not be inferred from this fixture. Human led Review can inspect this original when checking the summary. Humans in the loop record later investigation and outcomes separately.\n\nSource: fixtures/MD-01/agent-visible/original-log.txt, complete content, reviewed 2 October 2026.');
}

const finalPath=path.join(workspaceDir,'artifacts/presentations',process.env.CFIN_FINAL_NAME??'CFIN_SAP_Leadership.pptx');
const candidatePath=path.join(dir,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const result=await finalizePresentation({workspaceDir,candidatePath,finalPath,pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-heading-fit','--require-native-table-slide','2','--require-native-table-slide','3','--require-native-table-slide','4','--require-native-table-slide','5'],explicitTotalSlideCount:6,requiredNativeTableOwnerSlides:[2,3,4,5],requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'design',families:['Helvetica Neue','Courier New']},verifyArtifactToolImport:true,receiptPath:path.join(dir,path.basename(finalPath)+'.validation.json')});
const f=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<6;i++){const blob=await f.export({slide:f.slides.items[i],format:'png',scale:1});await fs.writeFile(path.join(dir,'slide-'+(i+1)+'.png'),new Uint8Array(await blob.arrayBuffer()));}
console.log(JSON.stringify({finalPath,slides:6,findings:result.presentationLayout.findings,warnings:result.presentationLayout.warnings},null,2));
