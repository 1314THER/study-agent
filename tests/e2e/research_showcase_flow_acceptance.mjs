// Focused acceptance for synchronized text glow and a continuous return trip.
import assert from 'node:assert/strict';
import {spawn,execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';

const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=new URL('../../',import.meta.url),revision=execFileSync('git',['rev-parse','--short','HEAD'],{cwd:root,encoding:'utf8'}).trim();
const dirty=Boolean(execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim());
const label=revision+(dirty?'-working':''),stamp=new Date().toISOString().replace(/[:.]/g,'-');
const shots=process.env.RESEARCH_SHOTS||`${tmpdir()}/demo-flow-${label}-${stamp}`;
await mkdir(shots,{recursive:true});
let server,browser,page,base=process.env.SHOWCASE_BASE;
const evidence={revision,dirty,capturedAt:new Date().toISOString(),viewports:[],lifecycle:{},screenshots:[]},errors=[];
const streamSelector='#scene-school .flow-stream';
const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
async function ready(){await page.waitForFunction(()=>window.Showcase?.ready);await page.evaluate(()=>Showcase.ready);}
async function running(){await page.waitForFunction(selector=>{const n=document.querySelector(selector),animations=n?.getAnimations({subtree:true})||[];return n?.dataset.flowRunning==='true'&&animations.length>0&&animations.every(a=>a.startTime!==null);},streamSelector);}
async function stopped(){await page.waitForFunction(selector=>{const n=document.querySelector(selector);return n?.dataset.flowRunning==='false'&&!n.getAnimations({subtree:true}).length;},streamSelector);}
async function enter(){await page.goto(base+'/#school',{waitUntil:'networkidle'});await ready();await page.locator(streamSelector).scrollIntoViewIfNeeded();await running();}
async function capture(name){const file=`${name}-${label}.png`;await page.locator(streamSelector).screenshot({path:shots+'/'+file});evidence.screenshots.push(file);}
async function sample(time,local=null){
 return await page.locator(streamSelector).evaluate((n,{time,local})=>{
  const animations=n.getAnimations({subtree:true});animations.forEach(a=>{a.pause();a.currentTime=time;});
  const beam=n.querySelector('.flow-beam'),style=getComputedStyle(beam),origin=style.transformOrigin.split(' ').map(Number.parseFloat);
  const matrix=new DOMMatrix().translate(beam.offsetLeft+origin[0],beam.offsetTop+origin[1]).multiply(new DOMMatrix(style.transform)).translate(-origin[0],-origin[1]);
  const path=n.querySelector('.flow-route path'),length=path.getTotalLength(),start=path.getPointAtLength(0),end=path.getPointAtLength(length);
  // Track the segment's anchor on the route, accounting for its half-pixel
  // painted thickness and transform origin even when the tangent points left.
  if(!local){const point=new DOMPoint(start.x+origin[0],start.y+origin[1]).matrixTransform(matrix.inverse());local={x:point.x,y:point.y};}
  const painted=new DOMPoint(local.x,local.y).matrixTransform(matrix),head={x:painted.x-origin[0],y:painted.y-origin[1]};let pathDistance=Infinity;
  for(let i=0;i<=1200;i++){const p=path.getPointAtLength(length*i/1200);pathDistance=Math.min(pathDistance,Math.hypot(p.x-head.x,p.y-head.y));}
  return {time,local,head:{x:head.x,y:head.y},start:{x:start.x,y:start.y},end:{x:end.x,y:end.y},length,pathDistance,beamOpacity:Number(style.opacity),glow:[...n.querySelectorAll('.flow-label-glow')].map(g=>Number(getComputedStyle(g).opacity)),pressed:[...n.querySelectorAll('button')].map(b=>b.getAttribute('aria-pressed')),focus:document.activeElement?.getAttribute('aria-label')||document.activeElement?.id||document.activeElement?.tagName};
 },{time,local});
}

try{
 if(!base){
  server=spawn(process.env.SHOWCASE_PYTHON||'python3',['-B','tests/e2e/showcase_server.py'],{cwd:root,stdio:['ignore','pipe','pipe']});
  const port=await new Promise((resolve,reject)=>{let out='',err='';const timer=setTimeout(()=>reject(Error('Showcase startup timeout '+err)),20000);server.stderr.on('data',chunk=>{err+=chunk;});server.stdout.on('data',chunk=>{out+=chunk;const match=out.match(/SHOWCASE_PORT=(\d+)/);if(match){clearTimeout(timer);resolve(match[1]);}});server.on('exit',code=>{clearTimeout(timer);reject(Error('Showcase exited '+code+' '+err));});});base='http://127.0.0.1:'+port;
 }
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
 for(const width of [1440,390,600]){
  await page.setViewportSize({width,height:1000});await enter();
  const stream=page.locator(streamSelector),buttons=stream.locator('button');assert.equal(await buttons.count(),5);
  assert.deepEqual(await buttons.evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label'))),['变更草稿','影响分析','教研审核','版本发布','历史保留']);
  assert.equal(await stream.locator('.flow-label-glow[aria-hidden=true]').count(),5);
  const clocks=await stream.evaluate(n=>n.getAnimations({subtree:true}).map(a=>({start:a.startTime,duration:a.effect.getTiming().duration})));
  assert(clocks.every(a=>a.duration===4000&&Math.abs(a.start-clocks[0].start)<.01),'Beam and text must share a clock: '+JSON.stringify(clocks));
  assert.notEqual(await stream.locator('.flow-label-glow').first().evaluate(n=>getComputedStyle(n).textShadow),'none','The travelling label needs a visible glow');
  await buttons.nth(2).click();assert.equal(await buttons.nth(2).getAttribute('aria-pressed'),'true');
  const samples=[];let local=null;
  for(const time of [0,1000,2000,3000,3990]){const value=await sample(time,local);local=value.local;samples.push(value);await capture(`flow-${width}-${time}`);}
  const [first,forward,last,reverse,wrap]=samples;
  assert(distance(first.head,first.start)<1&&distance(last.head,last.end)<1,'The head must reach both endpoints: '+JSON.stringify({width,first,last}));
  assert(distance(forward.head,reverse.head)<1,'The return trip must retrace the same path');
  assert(distance(wrap.head,first.start)<=first.length*.01+2,'A new trip must join the previous one without teleporting');
  assert(samples.every(s=>s.pathDistance<2&&s.beamOpacity>.8),'The bright head must stay visible on the route');
  assert(first.glow[0]>.9&&last.glow.at(-1)>.9&&last.glow[0]<.1,'The light must pass from the first label to the last');
  assert(forward.glow.every((opacity,i)=>Math.abs(opacity-reverse.glow[i])<.02),'Text must respond to position in either direction');
  assert(samples.every(s=>s.pressed[2]==='true'&&s.pressed.filter(v=>v==='true').length===1),'Motion must preserve the clicked selection');
  assert(samples.every(s=>s.focus===samples[0].focus),'Autoplay must not steal focus');
  if(width<760)assert(last.end.y-first.start.y>40,'Mobile playback must traverse the snake, not a straight chord');else assert(last.end.x-first.start.x>100);
  evidence.viewports.push({width,clocks,samples});
 }
 // Reload after deterministic sampling: WAAPI pause overrides must not leak
 // into the native visibility, dialog and reduced-motion lifecycle assertions.
 await page.setViewportSize({width:1440,height:1000});await page.reload({waitUntil:'networkidle'});await ready();await page.locator(streamSelector).scrollIntoViewIfNeeded();await running();
 const stream=page.locator(streamSelector),firstBeam=stream.locator('.flow-beam').first();
 const initial=await firstBeam.evaluate(n=>n.getAnimations()[0].currentTime);await page.waitForTimeout(180);assert(await firstBeam.evaluate(n=>n.getAnimations()[0].currentTime)>initial+90);
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));});await stopped();
 await page.evaluate(()=>{delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'));});await running();assert(await firstBeam.evaluate(n=>n.getAnimations()[0].currentTime)<500,'Returning from the background starts at the left');evidence.lifecycle.background=true;
 await page.evaluate(()=>{const p=document.createElement('p');p.textContent='流程动画暂停检查';window.openShowcasePanel('动画检查',p);});await stopped();await page.locator('.research-modal-close').click();await running();evidence.lifecycle.dialog=true;
 await page.emulateMedia({reducedMotion:'reduce'});await stopped();assert(await stream.locator('.flow-label-base').first().isVisible(),'Reduced motion retains readable labels');await page.emulateMedia({reducedMotion:'no-preference'});await running();evidence.lifecycle.reducedMotion=true;
 await page.locator('#vision').scrollIntoViewIfNeeded();await stopped();await stream.scrollIntoViewIfNeeded();await running();assert(await firstBeam.evaluate(n=>n.getAnimations()[0].currentTime)<500,'Re-entry starts at the left');evidence.lifecycle.offscreen=true;
 assert.deepEqual(errors,[],'Uncaught browser errors');await writeFile(shots+'/acceptance.json',JSON.stringify(evidence,null,2)+'\n');console.log(JSON.stringify({ok:true,revision,dirty,viewports:[1440,390,600],screenshots:evidence.screenshots.length,lifecycle:evidence.lifecycle,shots}));
}catch(error){if(page&&!page.isClosed())await page.screenshot({path:shots+'/failure.png'}).catch(()=>{});throw error;}
finally{if(browser)await browser.close();server?.kill('SIGTERM');}
