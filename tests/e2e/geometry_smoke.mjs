// Full local renderer + persisted teaching API, using a separate temporary server.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const server=spawn(process.env.GEOMETRY_PYTHON||'python3',['tests/e2e/geometry_server.py'],{cwd:new URL('../../',import.meta.url),env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']});
let output='';server.stderr.on('data',chunk=>{output+=chunk.toString();});
const port=await new Promise((resolve,reject)=>{
  let text='';server.stdout.on('data',chunk=>{text+=chunk.toString();const m=text.match(/GEOMETRY_PORT=(\d+)/);if(m)resolve(Number(m[1]));});
  server.on('exit',code=>reject(new Error('Test server exited '+code+'\n'+output)));setTimeout(()=>reject(new Error('Server timed out\n'+output)),15000).unref();
});
const base='http://127.0.0.1:'+port,shots=process.env.GEOMETRY_SHOTS||tmpdir()+'/study-geometry-shots';await mkdir(shots,{recursive:true});
let browser;
try{
  for(let i=0;i<50;i++){try{if((await fetch(base+'/__geometry-fixtures')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||chromium.executablePath(),args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1100,height:800}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/__geometry-smoke.html');
  const fixtures=await (await fetch(base+'/__geometry-fixtures')).json();
  for(const name of ['ellipse','pyramid','section','fold','locus']){
    await page.evaluate(({answer})=>{window.player=StudyGeometry.mount(document.getElementById('result'),answer);player.go(0);},fixtures[name]);
    await page.waitForFunction(()=>window.player&&player.renderer&&player.stage.querySelector('svg,canvas'));
    await page.waitForTimeout(1600);
    assert.equal(await page.locator('.geometry-note').textContent().then(t=>t.includes('不可用')),false,name);
    if(name==='ellipse')assert(await page.locator('.geometry-stage svg path').count()>0);
    if(['fold','section','locus'].includes(name)){
      await page.locator('.geometry-parameter input').fill('40');await page.waitForTimeout(250);
      assert.equal(await page.evaluate(()=>player.frame),40);
    }
    await page.screenshot({path:shots+'/'+name+'.png'});
  }
  await page.goto(base+'/teach.html?standalone=1');
  await page.waitForFunction(()=>typeof applyTeachState==='function');
  const start=await (await fetch(base+'/teach/session/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:fixtures.pyramid.question})})).json();
  const sid=start.session_id;assert(sid);
  let state=await (await fetch(base+'/teach/session/'+sid)).json();
  await page.evaluate(d=>applyTeachState(d),state);
  await page.waitForFunction(()=>document.querySelector('#teachGeometry canvas'));
  assert.deepEqual(state.geometry_state.released,{});
  // Real UI sends a durable background teaching job.
  await page.locator('#teachChatInput').fill('提示');await page.evaluate(()=>sendMessage());
  await page.waitForFunction(()=>window.studyTeachGeometryState?.released?.['1-1']===1);
  await page.waitForTimeout(1000);
  assert.equal(await page.evaluate(()=>StudyGeometry.viewFor(studyTeachGeometry,studyTeachGeometryState,'1-1',0,true).visible.has('CE')),false);
  await page.screenshot({path:shots+'/teaching-hint.png'});
  await page.reload();await page.waitForFunction(()=>window.studyTeachGeometryState?.released?.['1-1']===1);
  await page.locator('#teachChatInput').fill('提示');await page.evaluate(()=>sendMessage());
  await page.waitForFunction(()=>window.studyTeachGeometryState?.released?.['1-1']===2);
  await page.evaluate(()=>showAnswer());await page.waitForFunction(()=>window.studyTeachGeometryState?.completed?.includes('1-1'));
  assert.equal(await page.evaluate(()=>StudyGeometry.viewFor(studyTeachGeometry,studyTeachGeometryState,'1-2',0,true).visible.has('CE')),true);
  const response=await fetch(base+'/teach/session/'+sid+'/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:'提示',expected_revision:0})});
  assert.equal(response.status,409);
  await page.evaluate(()=>skipStep());await page.waitForFunction(()=>_currentStepIndex===1);
  state=await (await fetch(base+'/teach/session/'+sid)).json();assert(!state.geometry_state.completed.includes('1-2'));
  await page.evaluate(()=>skipStep());await page.waitForFunction(()=>document.querySelector('#teachSummaryGeometry .geometry-panel'));
  await page.waitForTimeout(1500);
  assert.equal(await page.locator('#teachSummaryGeometry select').isVisible(),true);
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:shots+'/teaching-mobile.png'});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  const mobile=await browser.newPage({viewport:{width:390,height:844}});
  await mobile.goto(base+'/teach.html?standalone=1');
  await mobile.waitForFunction(()=>typeof applyTeachState==='function');
  const mobileStart=await (await fetch(base+'/teach/session/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:fixtures.pyramid.question})})).json();
  const mobileState=await (await fetch(base+'/teach/session/'+mobileStart.session_id)).json();
  await mobile.evaluate(d=>applyTeachState(d),mobileState);
  assert.equal(await mobile.locator('#teachGeometry details').getAttribute('open'),null);
  await mobile.locator('#teachGeometry summary').click();await mobile.waitForFunction(()=>document.querySelector('#teachGeometry canvas'));
  assert.equal(await mobile.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  await mobile.screenshot({path:shots+'/teaching-mobile-active.png'});await mobile.close();
  assert.deepEqual(errors,[]);
  console.log('Geometry browser smoke passed: five scenes, two hints, answer, revision conflict, skip, refresh, mobile review. Screenshots: '+shots);
}finally{
  if(browser)await browser.close();server.kill('SIGTERM');
}
