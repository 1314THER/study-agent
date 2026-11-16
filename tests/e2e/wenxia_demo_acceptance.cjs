/* Run against the local read-only preview. No model or production API calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../..');
const baseURL = process.env.WENXIA_BASE_URL || 'http://127.0.0.1:8303/wenxia-demo/index.html';
const artifacts = path.resolve(process.env.WENXIA_ARTIFACT_DIR || path.join(root,'.runtime/wenxia-acceptance'));
const source = JSON.parse(fs.readFileSync(path.join(root,'frontend/showcase/recordings.json'),'utf8'));
const primary = source.cases.find((entry)=>entry.id==='propagation');
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'frontend/wenxia-demo/experience-data.js'),'utf8'),sandbox);
const D=JSON.parse(JSON.stringify(sandbox.window.WENXIA_DEMO));
const txt=(page,selector)=>page.locator(selector).textContent();
const click=(page,selector)=>page.locator(selector).click();
async function screenshot(page,name,id) {
 if(id) await page.evaluate((id)=>scrollTo({top:document.getElementById(id).offsetTop-85,behavior:'instant'}),id);
 await page.screenshot({path:path.join(artifacts,name+'.png')});
}
async function widthCheck(page,width) {
 await page.setViewportSize({width,height:1000});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width,`Global overflow at ${width}`);
 assert.equal(await page.locator('.system-diagram').isVisible(),width>1000);
 assert.equal(await page.locator('.mobile-system').isVisible(),width<=1000);
 const bad = await page.locator('button:visible').evaluateAll((nodes)=>nodes.filter((node)=>node.getBoundingClientRect().height<43).map((node)=>({text:node.textContent,height:node.getBoundingClientRect().height})));
 if(width<760) assert.deepEqual(bad,[],`Small mobile controls at ${width}`);
}
(async()=>{
 fs.mkdirSync(artifacts,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage(); const errors=[]; const requests=[];
  page.on('pageerror',(error)=>errors.push(error.message));
  page.on('console',(message)=>{if(message.type()==='error')errors.push(message.text());});
  page.on('request',(request)=>requests.push({url:request.url(),method:request.method()}));
  await page.goto(baseURL,{waitUntil:'networkidle'});
  await page.locator('#record-player.records-ready').waitFor();
  const order=await page.evaluate(()=>['architecture','vision-goal','scenario','research','benchmark','deployment'].map(id=>document.getElementById(id).offsetTop));
  assert(order.every((value,index)=>index===0||value>order[index-1]),'Narrative order');
  assert.equal(await page.locator('.vision-card').count(),4);
  assert.equal(await page.locator('.system-diagram .map-node').count(),9);
  assert.equal(await page.locator('#evidence .evidence-index td:empty').count(),0,'Source/status index retains content');
  await screenshot(page,'01-overview');
  for(const phase of D.phases) {
   await click(page,`[data-phase="${phase.id}"]`);
   assert((await txt(page,'#flow-detail')).includes(phase.rw));
   for(const id of phase.nodes) assert(await page.locator(`.system-diagram [data-node="${id}"].is-active`).count(),`Missing node highlight ${phase.id}/${id}`);
   for(const id of phase.edges) assert(await page.locator(`.system-diagram [data-edge="${id}"].is-active`).count(),`Missing edge highlight ${phase.id}/${id}`);
  }
  await click(page,'[data-phase="evidence"]');
  await screenshot(page,'02-evidence-flow','architecture');
  await page.locator('[data-phase="overview"]').focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.locator('[data-phase="input"]').getAttribute('aria-pressed'),'true');
  await click(page,'[data-phase="overview"]');
  for(let i=0;i<source.teaching.frames.length;i++) {
   await click(page,`[data-frame="${i}"]`);
   assert.equal(await txt(page,'#record-output'),source.teaching.frames[i].output,'Recorded output is byte-for-byte text');
   if(source.teaching.frames[i].input!==null)assert.equal(await txt(page,'#record-input'),source.teaching.frames[i].input);
   assert.equal(await page.locator('#record-warning').isVisible(),i===2);
  }
  assert(await page.locator('#frame-next').isDisabled());
  await click(page,'#frame-prev');assert((await txt(page,'#frame-count')).startsWith('04'));
  await click(page,'[data-frame="2"]');
  await click(page,'[data-record-format="raw"]');assert(await page.locator('#record-output').isVisible());
  await click(page,'[data-record-format="math"]');assert(await page.locator('#record-rendered').isVisible());
  assert((await txt(page,'#record-meta')).includes(source.teaching.session.session_id));
  await screenshot(page,'03-national-record','record-player');
  for(const condition of ['basic','same_information','system']) {
   await click(page,`[data-condition="${condition}"]`);
   assert.equal(await txt(page,'#comparison-output'),primary[condition].content);
  }
  assert(await page.locator('#comparison-output').isVisible(),'System JSON remains raw');
  for(const evidence of D.evidence) {
   await click(page,`.evidence-source [data-evidence="${evidence.id}"]`);
   assert.equal(await txt(page,'#evidence-record'),evidence.record);
   assert.equal(await page.locator(`.context-citation[data-evidence="${evidence.id}"]`).getAttribute('aria-pressed'),'true');
  }
  await click(page,'.context-citation[data-evidence="db2"]');
  assert((await txt(page,'#evidence-source-meta')).includes('已保存'));
  await screenshot(page,'04-context-evidence','databases');
  for(const [name,trace] of Object.entries(D.traces)) {
   await click(page,`[data-trace="${name}"]`);
   for(let i=0;i<trace.steps.length;i++) {
    assert.equal(await txt(page,'#trace-state'),trace.steps[i].state);
    assert.equal(await txt(page,'#trace-tool'),trace.steps[i].tool);
    assert.equal(await txt(page,'#trace-next-state'),trace.steps[i].next);
    if(i<trace.steps.length-1)await click(page,'#trace-next');
   }
   assert(await page.locator('#trace-next').isDisabled());
  }
  await screenshot(page,'05-teacher-correction','agent');
  for(let i=0;i<D.lora.length;i++) {
   await click(page,`[data-training="${i}"]`);
   assert.equal(await txt(page,'#training-sample'),D.lora[i].sample);
  }
  for(const model of ['4B','9B','27B']) {
   await click(page,`[data-model="${model}"]`);
   assert((await txt(page,'#model-focus-title')).includes(model));
  }
  await click(page,'[data-training="1"]');await click(page,'[data-model="9B"]');
  await screenshot(page,'06-training-review','lora');
  for(const task of D.tasks) {
   await click(page,`[data-task="${task.id}"]`);
   assert.equal(await txt(page,'#task-title'),task.title);
   assert((await txt(page,'#task-fields')).includes(task.cost));
  }
  await screenshot(page,'07-benchmark-task','benchmark');
  for(const width of [1440,1024,390,320]) {
   await widthCheck(page,width);await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
   await screenshot(page,`width-${width}`);
   if(width===390){
    await click(page,'.menu-toggle');assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'),'true');
    await page.keyboard.press('Escape');assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'),'false');
    await screenshot(page,'08-mobile-record','record-player');
   }
  }
  assert.deepEqual(errors,[],'No browser errors in normal operation');
  assert(requests.every((request)=>request.method==='GET'&&new URL(request.url).origin===new URL(baseURL).origin),'Only static same-origin reads');
  await context.close();
  const noJS=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:844}});
  const staticPage=await noJS.newPage();await staticPage.goto(baseURL,{waitUntil:'networkidle'});
  assert.equal(await staticPage.locator('.record-fallback>li').count(),5);
  assert(await staticPage.locator('.record-fallback').isVisible());
  for(let i=0;i<source.teaching.frames.length;i++) {
   assert.equal(await staticPage.locator('.record-fallback>li').nth(i).locator('pre').nth(1).textContent(),source.teaching.frames[i].output);
  }
  assert.equal(await staticPage.locator('.static-phase-list>li').count(),7);
  assert.equal(await staticPage.evaluate(()=>document.documentElement.scrollWidth),390);
  await noJS.close();
  const fallback=await browser.newContext({viewport:{width:1440,height:1000}});
  const failedPage=await fallback.newPage();
  await failedPage.route('**/showcase/recordings.json',route=>route.abort());
  await failedPage.goto(baseURL,{waitUntil:'networkidle'});
  await failedPage.waitForFunction(()=>document.querySelector('#record-load-state').textContent.includes('暂时无法'));
  assert(await failedPage.locator('.record-fallback').isVisible());
  assert(await failedPage.locator('#record-live').isHidden());
  await click(failedPage,'[data-phase="commit"]');assert((await txt(failedPage,'#flow-detail')).includes('outbox'));
  await fallback.close();
  const reduced=await browser.newContext({reducedMotion:'reduce',viewport:{width:390,height:844}});
  const reducedPage=await reduced.newPage();await reducedPage.goto(baseURL,{waitUntil:'networkidle'});
  assert.equal(await reducedPage.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior),'auto');
  await click(reducedPage,'[data-phase="revision"]');assert((await txt(reducedPage,'#flow-detail')).includes('WikiPatch'));
  await reduced.close();
  console.log(JSON.stringify({ok:true,teachingFrames:5,comparisonConditions:3,businessPhases:D.phases.length,agentTraces:Object.keys(D.traces).length,taskPackages:D.tasks.length,widths:[1440,1024,390,320],fallback:true,noJavaScript:true,reducedMotion:true,artifacts},null,2));
 } finally {await browser.close();}
})().catch((error)=>{console.error(error);process.exitCode=1;});
