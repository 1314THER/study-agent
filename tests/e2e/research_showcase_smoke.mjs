// Real-browser checks for the continuous scientific showcase. No live AI calls.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir,readFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {tmpdir} from 'node:os';

const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=new URL('../../',import.meta.url);
const chapters=['overview','concepts','dataset','single','diagnosis','library','routines','exam','career','agent','teacher','school','modes','mcp','evolution'];
const records=JSON.parse(await readFile(new URL('frontend/showcase/recordings.json',root),'utf8'));
const pipeline=JSON.parse(await readFile(new URL('frontend/showcase/pipeline.json',root),'utf8'));
const shots=process.env.RESEARCH_SHOTS||tmpdir()+'/research-showcase-shots';
await mkdir(shots,{recursive:true});
const server=spawn(process.env.SHOWCASE_PYTHON||'python3',['tests/e2e/showcase_server.py'],{
  cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']});
let output='',browser;
server.stderr.on('data',chunk=>{output+=chunk.toString();});
const port=await new Promise((resolve,reject)=>{
  let stdout='';const deadline=setTimeout(()=>{server.kill('SIGTERM');reject(Error('Showcase server startup timed out\n'+output));},20000);
  deadline.unref();server.stdout.on('data',chunk=>{stdout+=chunk.toString();const m=stdout.match(/SHOWCASE_PORT=(\d+)/);if(m){clearTimeout(deadline);resolve(Number(m[1]));}});
  server.on('exit',code=>{clearTimeout(deadline);reject(Error('Showcase server exited '+code+'\n'+output));});
});
const base='http://127.0.0.1:'+port;
const audits=[];
function audit(page){const value={errors:[],console:[],requests:[],failures:[]};audits.push(value);
 page.on('pageerror',error=>value.errors.push(error.message));
 page.on('console',message=>{if(message.type()==='error')value.console.push(message.text());});
 page.on('request',r=>value.requests.push({url:r.url(),method:r.method()}));
 page.on('requestfailed',r=>value.failures.push(r.url()+': '+r.failure()?.errorText));return value;}
async function ready(page){await page.waitForFunction(()=>Boolean(window.Showcase?.ready));if(await page.locator('#opening-dialog').isVisible())await page.locator('#opening-enter').click();const value=await page.evaluate(async()=>{
 const data=await window.Showcase.ready;return {version:data?.schema_version,error:window.Showcase.state.loadError};});
 assert.equal(value.error,null,'Showcase initialization failed: '+value.error);assert.equal(value.version,2);}
async function fit(page,label){const metrics=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth}));
 assert(metrics.width<=metrics.viewport+1,'Horizontal overflow '+label+': '+JSON.stringify(metrics));}
async function checkAudits(context){for(const a of audits){assert.deepEqual(a.errors,[],'Uncaught browser errors');assert.deepEqual(a.console,[],'Console errors');assert.deepEqual(a.failures,[],'Failed resources');
 for(const r of a.requests){if(/^(data:|blob:)/.test(r.url))continue;assert.equal(new URL(r.url).origin,base,'Unexpected external request: '+r.url);assert.equal(r.method,'GET','Unexpected write request');
 assert(!/^\/(?:solve|grade|teach|auth|jobs|questions|patterns|generate)(?:\/|$)/.test(new URL(r.url).pathname),'Unexpected business API request: '+r.url);}}
 assert.deepEqual(await context.cookies(),[],'Showcase created cookies');}
async function choose(page,chapter,label){const button=page.locator('#scene-'+chapter).getByRole('button',{name:label,exact:true});await button.click();await fit(page,chapter+' '+label);}

try{
 for(let attempt=0;attempt<60;attempt++){try{if((await fetch(base+'/health')).ok)break;}catch{}
  if(attempt===59)throw Error('Showcase did not become healthy\n'+output);await new Promise(r=>setTimeout(r,100));}
 assert.deepEqual(await(await fetch(base+'/health')).json(),{ok:true,mode:'demo',demo_mode:'showcase',ai_enabled:false});
 const configured=process.env.CHROME_PATH||chromium.executablePath();
 const executable=existsSync(configured)?configured:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
 assert(existsSync(executable),'A local Chromium or Chrome executable is required');
 browser=await chromium.launch({headless:true,executablePath:executable});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 await context.addInitScript(()=>{window.print=()=>{window.__printed=true;};});
 const page=await context.newPage();audit(page);await page.goto(base+'/',{waitUntil:'networkidle'});await ready(page);
 assert.deepEqual(await page.locator('[data-chapter]').evaluateAll(nodes=>nodes.map(n=>n.id)),chapters);
 assert(!/上海|shanghai/i.test(await page.locator('body').innerText()),'Retired regional example is visible');
 assert.equal(await page.locator('h1').count(),1);
 assert.equal(await page.locator('.primary-nav a[href="#dataset"]').innerText(),'数据集');
 assert.equal(await page.locator('#dataset .dataset-metric').count(),5,'The dataset should be embedded between concepts and single-question workflows');
 assert.equal(await page.locator('#dataset .inline-dataset-goals article').count(),4);
 assert.deepEqual(await page.locator('body').evaluate(n=>({background:getComputedStyle(n).backgroundColor,color:getComputedStyle(n).color})),{background:'rgb(8, 8, 8)',color:'rgb(245, 245, 245)'});
 assert.equal(await page.locator('details').count(),0,'Reader-facing content should use notes and the annotation panel');
 assert.equal(await page.locator('.source-reading').count(),0,'Internal source-document lists should not appear in the public story');
 assert.equal(await page.locator('.chapter-bridge').count(),15,'Each chapter must pass a specific output to its successor');
 assert.equal(await page.locator('.pain-point').count(),15,'Each module must explain a practical problem');
 assert.equal(await page.locator('.research-logic').count(),14,'Related work must have a presentation-style logic diagram');
 assert.equal(await page.locator('.research-source-links a').count(),28,'Each related work needs a website and a primary document link');
 assert.equal(await page.locator('#reading-progress,#opening-skip').count(),0);
 assert((await page.locator('.project-architecture .architecture-node').count())>=12,'A connected project structure must be visible in the introduction');
 await page.evaluate(()=>document.fonts.ready);
 assert(await page.evaluate(()=>document.fonts.check('22px "StudyAgent Handwriting"')),'The local handwriting webfont did not load');
 await fit(page,'desktop overview');await page.screenshot({path:shots+'/desktop-overview.png'});
 await page.locator('.project-architecture').screenshot({path:shots+'/system-architecture.png'});
 // The chapter menu works from the keyboard, and Escape restores focus.
 const contents=page.locator('#contents-toggle');await contents.focus();await page.keyboard.press('Enter');
 assert.equal(await contents.getAttribute('aria-expanded'),'true');assert.equal(await page.locator('#chapter-contents a').count(),15);
 await page.keyboard.press('Escape');assert.equal(await contents.getAttribute('aria-expanded'),'false');
 assert.equal(await contents.evaluate(n=>n===document.activeElement),true);
 for(const id of chapters){await page.locator('#'+id).scrollIntoViewIfNeeded();assert(await page.locator('#heading-'+id).isVisible());await fit(page,'chapter '+id);}
 assert.equal(await page.locator('#system-trail a').count(),7,'The shared system path must remain available across chapters');
 // Both questions and all four genuine saved runs must be selectable.
 await choose(page,'single','结构化解题');assert.equal(await page.locator('#example-select option').count(),2);assert.equal(await page.locator('#teacher-select option').count(),4);
 for(const example of ['national-2023-q17','national-2025-q16'])for(const teacher of ['liangliang','taotao','xuefeng','ji']){
  await page.locator('#example-select').selectOption(example);await page.locator('#teacher-select').selectOption(teacher);
  const run=pipeline.examples[example][teacher];
  assert.equal(await page.locator('#scene-single .step').count(),run.answer_json.chunk_results.reduce((n,c)=>n+c.steps.length,0));
  assert.equal(await page.locator('#scene-single .step h4').first().innerText(),run.answer_json.chunk_results[0].steps[0].title);
  assert((await page.locator('#scene-single .annotation-source').allTextContents()).join(' ').includes(run.run_at),'The original run timestamp should remain in the source panel');
  assert((await page.locator('#scene-single .katex').count())>0,'Math rendering missing');await fit(page,example+' '+teacher);
 }
 await page.locator('#single').scrollIntoViewIfNeeded();await page.screenshot({path:shots+'/desktop-solution.png'});
 const explanation=page.locator('#scene-single .step .annotation-button').first();await explanation.click();
 assert(await page.locator('#annotation-panel').isVisible());
 assert((await page.locator('#annotation-body').innerText()).length>50,'Detailed solution did not open in the side panel');
 await page.screenshot({path:shots+'/desktop-annotation.png'});
 await page.keyboard.press('Escape');assert(!(await page.locator('#annotation-panel').isVisible()));
 await page.locator('#single .research-study').first().screenshot({path:shots+'/research-comparison.png'});
 // Geometry should reveal the altitude only after an explicit action.
 await choose(page,'single','辅助线与推理');assert.equal(await page.locator('#scene-single .construction-line').count(),0);
 await choose(page,'single','显示辅助线');assert.equal(await page.locator('#scene-single .construction-line').count(),1);
 await choose(page,'single','关联推导');assert((await page.locator('#scene-single svg.triangle-figure').textContent()).includes('h = 6'));
 // All six predetermined inputs and both information conditions are visible.
 assert.equal(records.cases.length,6,'There must be six predetermined diagnostic scenarios');
 for(let i=0;i<records.cases.length;i++){
  const c=records.cases[i];await page.locator('#scene-diagnosis [aria-label="诊断情境"] button').nth(i).click();
  assert.equal(await page.locator('#scene-diagnosis .handwriting-sheet').getAttribute('data-source'),c.student_answer,'Handwriting presentation lost the original test input');
  for(const [condition,label] of [['basic','常见使用方式'],['same_information','同信息条件']]){
   await choose(page,'diagnosis',label);assert.equal(await page.locator('#scene-diagnosis .comparison-grid .record-output').count(),2);
   for(const [value,column] of [[c[condition],0],[c.system,1]]){
    const block=page.locator('#scene-diagnosis .comparison-grid .record-output').nth(column);
    if(value.status==='recorded'){
     const expected=typeof value.content==='string'?value.content:JSON.stringify(value.content??value.structured,null,2);
     assert.equal(await block.locator('.record-text').textContent(),expected,'Displayed response differs from saved output');
    }else assert((await block.locator('.pending-output').count())===1,'Unrecorded case should not show a fabricated success');
    if(process.env.REQUIRE_RECORDINGS==='1')assert.equal(value.status,'recorded','Incomplete actual recording: '+c.id+' '+condition);
   }
   await fit(page,'diagnosis '+i+' '+condition);
  }
 }
 await page.locator('#diagnosis').scrollIntoViewIfNeeded();await page.screenshot({path:shots+'/desktop-comparison.png'});
 await choose(page,'diagnosis','返回修改');
 assert((await page.locator('#scene-diagnosis .timestamp-evidence').innerText()).includes('返回前面的区域'));
 // Saved teaching frames and generated result are navigable when actually recorded.
 await choose(page,'single','教学过程');if(records.teaching?.status==='recorded'&&records.teaching.frames?.length>1){
  const before=await page.locator('#scene-single .teacher-answer').textContent();await choose(page,'single','下一状态');
  assert.notEqual(await page.locator('#scene-single .teacher-answer').textContent(),before);await choose(page,'single','上一步');}
 await choose(page,'single','针对性变式');if(records.generation?.status==='recorded'){
  assert(await page.locator('#scene-single .sample-question').count());
  assert.equal(await page.locator('#scene-single .sample-question .katex-error').count(),0,'Generated question formula rendering failed');
  assert(!(await page.locator('#scene-single .sample-question').innerText()).includes('\\n'),'Escaped JSON newline leaked into presentation');
 }
 // National-only library filtering, selected-question paper, teacher answers and print.
 await page.locator('#bank-workbench').scrollIntoViewIfNeeded();await page.waitForFunction(()=>window.ShowcaseBank?.state.index?.length===2);
 assert.equal(await page.locator('#library-list .bank-row').count(),2);
 await page.locator('#bank-search').fill('数列');await page.waitForFunction(()=>window.ShowcaseBank.state.rows.length===1);
 assert((await page.locator('#library-list').innerText()).includes('数列'));await fit(page,'filtered bank');
 await page.locator('#bank-search').fill('');await page.waitForFunction(()=>window.ShowcaseBank.state.rows.length===2);
 for(const checkbox of await page.locator('#library-list input[type="checkbox"]').all())await checkbox.check();
 await page.locator('#bank-build-exam').click();await page.waitForFunction(()=>document.querySelectorAll('#exam-preview .exam-question').length===2);
 assert(!(await page.locator('#exam-preview').innerText()).includes('上海'));
 assert.equal(await page.locator('#exam-preview .bank-chunk').count(),0);
 await page.locator('#exam-teacher').click();await page.waitForFunction(()=>document.querySelectorAll('#exam-preview .bank-chunk').length===4);
 await page.locator('#exam-print').click();assert.equal(await page.evaluate(()=>window.__printed),true);await fit(page,'national paper');
 // Planned interactions must switch real local state rather than dead controls.
 await choose(page,'routines','隐藏套路名称');assert((await page.locator('#scene-routines .method-label').innerText()).includes('自行判断'));
 await choose(page,'routines','显示套路名称');await choose(page,'career','出现相反证据');
 assert((await page.locator('#scene-career .scenario-detail').innerText()).includes('修订'));
 await choose(page,'agent','教师助理');assert((await page.locator('#scene-agent .scenario-detail').innerText()).includes('班级'));
 await choose(page,'modes','传统教学增强');assert((await page.locator('#scene-modes caption').innerText()).includes('传统教学增强'));
 await choose(page,'mcp','WorkBuddy');await choose(page,'evolution','跨学科扩展');
 // Reload resumes the public presentation, its selected examples, and the reading position.
 await choose(page,'single','结构化解题');await page.locator('#example-select').selectOption('national-2025-q16');await page.locator('#teacher-select').selectOption('liangliang');
 await page.locator('[data-library-tab="library"]').click();await page.locator('#bank-search').fill('数列');await page.waitForFunction(()=>window.ShowcaseBank.state.rows.length===1);
 await page.evaluate(()=>window.Showcase.selectView('career'));await page.evaluate(()=>window.scrollBy(0,180));
 const beforeReload=await page.evaluate(()=>({y:scrollY,caseIndex:Showcase.state.caseIndex,condition:Showcase.state.condition}));
 await page.reload({waitUntil:'networkidle'});assert(!(await page.locator('#opening-dialog').isVisible()),'Reload must not replay the welcome');await ready(page);
 const restored=await page.evaluate(()=>({y:scrollY,caseIndex:Showcase.state.caseIndex,condition:Showcase.state.condition,example:Showcase.state.example,teacher:Showcase.state.teacher,career:Showcase.state.sceneTabs.career,selected:ShowcaseBank.state.selected.size}));
 assert(Math.abs(restored.y-beforeReload.y)<8,'Reading position changed after reload: '+JSON.stringify({beforeReload,restored}));
 assert.equal(restored.caseIndex,beforeReload.caseIndex);assert.equal(restored.condition,beforeReload.condition);assert.equal(restored.example,'national-2025-q16');assert.equal(restored.teacher,'liangliang');assert.equal(restored.career,2);assert.equal(restored.selected,2);assert.equal(await page.locator('#bank-search').inputValue(),'数列');
 assert.equal(await page.locator('.site-registration a').innerText(),'渝ICP备2026024246号-1');assert.equal(await page.locator('.site-registration a').getAttribute('href'),'https://beian.miit.gov.cn/');
 await checkAudits(context);
 // Phone widths remain within the viewport.
 await page.evaluate(()=>window.Showcase.clearReadingState());
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/',{waitUntil:'networkidle'});
 assert(await page.locator('#opening-dialog').isVisible(),'Reduced motion should preserve the welcome and explicit entry');
 assert.equal(await page.evaluate(()=>document.activeElement.id),'opening-title');
 const mobileEntry=await page.locator('#opening-enter').boundingBox();assert(mobileEntry.y+mobileEntry.height<=844,'The phone entry should fit above the viewport edge');
 await page.screenshot({path:shots+'/opening-mobile.png'});await page.keyboard.press('Tab');
 assert.equal(await page.evaluate(()=>document.activeElement.id),'opening-enter');await page.keyboard.press('Enter');
 await page.waitForFunction(()=>!document.getElementById('opening-dialog').open);await ready(page);
 for(const id of chapters){await page.locator('#'+id).scrollIntoViewIfNeeded();await fit(page,'mobile '+id);}
 await choose(page,'single','辅助线与推理');await choose(page,'single','显示辅助线');
 await choose(page,'diagnosis','同信息条件');await fit(page,'mobile comparison');
 await page.locator('#diagnosis').scrollIntoViewIfNeeded();await page.screenshot({path:shots+'/mobile-comparison.png'});
 await choose(page,'single','结构化解题');await page.locator('#scene-single .step .annotation-button').first().click();
 await fit(page,'mobile annotation panel');await page.screenshot({path:shots+'/mobile-annotation.png'});
 await page.keyboard.press('Escape');
 await page.setViewportSize({width:320,height:740});await fit(page,'320px viewport');
 await page.goto(base+'/#overview',{waitUntil:'networkidle'});await ready(page);await page.screenshot({path:shots+'/mobile-overview.png'});
 // The separate dataset page exposes audited aggregates and explicitly labeled scale scenarios.
 await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/showcase/dataset.html',{waitUntil:'networkidle'});
 assert.equal(await page.locator('h1').innerText(),'数据集详细统计');assert.equal(await page.locator('.atlas-node').count(),5);
 assert.deepEqual(await page.locator('.scenario-equation strong').allTextContents(),['116,305','93,044','69,783','4,076']);
 assert.equal(await page.locator('.scenario .status-target').count(),4,'Projected quantities need visible planning labels');
 assert.equal(await page.locator('details,.source-list,.source-hash').count(),0,'The public dataset page should not expose internal audit lists');
 await fit(page,'dataset desktop');await page.screenshot({path:shots+'/dataset-desktop.png'});
 await page.getByRole('link',{name:'全量图景',exact:true}).click();await page.screenshot({path:shots+'/dataset-target.png'});
 for(const width of [390,320]){await page.setViewportSize({width,height:844});await fit(page,'dataset '+width);}
 await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:shots+'/dataset-mobile.png'});
 assert.equal(await page.locator('.site-registration a').innerText(),'渝ICP备2026024246号-1');
 await checkAudits(context);await context.close();
 // The scientific text and citations remain available without any JavaScript.
 const plain=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:844}});const nojs=await plain.newPage();audit(nojs);
 await nojs.goto(base+'/',{waitUntil:'networkidle'});assert.equal(await nojs.locator('[data-chapter]').count(),15);
 for(const id of chapters){const text=await nojs.locator('#'+id+' .chapter-prose').innerText();assert(text.length>80,'Missing no-JS chapter text: '+id);}
 assert((await nojs.locator('.research-notes a[href^="https://"]').count())>=6,'Research sources unavailable without JS');
 assert(!/上海|shanghai/i.test(await nojs.locator('body').innerText()));await fit(nojs,'no JavaScript');await checkAudits(plain);await plain.close();
 // The decelerating welcome page remains until entry; chapter bridges animate once as they enter view.
 const motion=await browser.newContext({viewport:{width:1440,height:950},reducedMotion:'no-preference'});
 const animated=await motion.newPage();audit(animated);await animated.goto(base+'/',{waitUntil:'domcontentloaded'});
 await animated.locator('#opening-dialog').waitFor({state:'visible',timeout:1500});
 await animated.waitForTimeout(200);await animated.screenshot({path:shots+'/opening-animation.png'});
 await animated.waitForTimeout(1900);assert(await animated.locator('#opening-dialog').isVisible(),'The welcome page should wait for the entry button');
 assert.equal(await animated.locator('#opening-title').innerText(),'study-agent项目介绍页面');
 assert.equal(await animated.evaluate(()=>document.activeElement.id),'opening-title','Initial focus should identify the cover rather than highlight the entry');
 await animated.screenshot({path:shots+'/opening-home.png'});await animated.locator('#opening-enter').click();
 await animated.waitForFunction(()=>!document.getElementById('opening-dialog').open,{timeout:1000});await ready(animated);
 assert.equal(await animated.locator('.chapter-bridge.has-handoff').count(),15,'All chapter handoffs should be enhanced');
 const handoff=animated.locator('#single .chapter-bridge');
 await handoff.evaluate(n=>scrollTo({top:n.getBoundingClientRect().top+scrollY-500,behavior:'instant'}));
 await animated.waitForFunction(()=>Number(document.querySelector('#single .chapter-bridge').dataset.handoffProgress)>0);
 const early=Number(await handoff.getAttribute('data-handoff-progress'));
 await handoff.evaluate(n=>scrollTo({top:n.getBoundingClientRect().top+scrollY-160,behavior:'instant'}));
 await animated.waitForFunction(p=>Number(document.querySelector('#single .chapter-bridge').dataset.handoffProgress)>p+.15,early);
 assert(await handoff.evaluate(n=>n.classList.contains('is-bridging')),'Native scroll should visibly advance the handoff');
 assert(Number.parseFloat(await animated.locator('#single .handoff-line-motion').evaluate(n=>getComputedStyle(n).strokeDashoffset))<1);
 await animated.screenshot({path:shots+'/chapter-transition.png'});
 await animated.locator('.primary-nav a[href="#concepts"]').click();
 await animated.waitForFunction(()=>!document.querySelector('.chapter-transit-overlay').hidden);
 assert.equal(await animated.locator('.chapter-transit-overlay').getAttribute('data-to'),'concepts');
 await animated.screenshot({path:shots+'/chapter-navigation.png'});
 await animated.waitForFunction(()=>document.querySelector('.chapter-transit-overlay').hidden);
 await checkAudits(motion);await motion.close();
 const recorded=records.cases.reduce((n,c)=>n+['basic','same_information','system'].filter(k=>c[k]?.status==='recorded').length,0);
 console.log(JSON.stringify({ok:true,chapters:15,nationalQuestions:2,savedPipelineRuns:8,diagnosticInputs:6,recordedResponses:recorded,conditions:2,viewports:[1440,390,320],noJavaScript:true,network:'same-origin GET only, no cookies',screenshots:shots}));
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
