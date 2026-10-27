// Focused visual acceptance for the October 27 refinement. No live AI calls.
import assert from 'node:assert/strict';
import {spawn,execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=new URL('../../',import.meta.url),revision=execFileSync('git',['rev-parse','--short','HEAD'],{cwd:root,encoding:'utf8'}).trim();
const dirty=Boolean(execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim());
const stamp=new Date().toISOString().replace(/[:.]/g,'-'),label=revision+(dirty?'-working':'');
const shots=process.env.RESEARCH_SHOTS||`${tmpdir()}/demo-visual-${label}-${stamp}`;
await mkdir(shots,{recursive:true});
let server,browser,base=process.env.SHOWCASE_BASE;
const evidence={revision,dirty,capturedAt:new Date().toISOString(),screenshots:[],motion:{},research:[]};
async function capture(page,name,target=page){const file=`${name}-${label}.png`;await target.screenshot({path:shots+'/'+file});evidence.screenshots.push(file);}
async function ready(page){await page.waitForFunction(()=>window.Showcase?.ready);await page.evaluate(()=>Showcase.ready);}
try{
 if(!base){
  server=spawn(process.env.SHOWCASE_PYTHON||'python3',['-B','tests/e2e/showcase_server.py'],{cwd:root,stdio:['ignore','pipe','pipe']});
  const port=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Showcase startup timeout')),20000);server.stdout.on('data',v=>{output+=v;const m=output.match(/SHOWCASE_PORT=(\d+)/);if(m){clearTimeout(timer);resolve(m[1]);}});server.on('exit',code=>reject(Error('Showcase exit '+code)));});base='http://127.0.0.1:'+port;
 }
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),page=await context.newPage();
 await page.goto(base+'/',{waitUntil:'networkidle'});await ready(page);
 assert.equal(await page.evaluate(()=>document.activeElement.id),'launch-title','Opening title retains screen-reader focus');
 assert.equal(await page.locator('#launch-title').evaluate(n=>getComputedStyle(n).outlineStyle),'none','Reading title must not show a giant outline');
 await capture(page,'opening');await page.keyboard.press('Tab');
 assert(await page.evaluate(()=>{const n=document.activeElement,s=getComputedStyle(n);return n.matches('a,button,input')&&s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>0;}),'Keyboard controls still need a visible focus ring');
 await page.locator('#explore-start').click();
 assert.equal(await page.locator('.relation-focus').count(),0);
 const research=page.locator('.topic-unit.is-merged .research-notes');assert.equal(await research.count(),7);
 for(const width of [599,600]){
  await research.evaluateAll((nodes,w)=>nodes.forEach(n=>n.style.width=w+'px'),width);
  const results=await research.evaluateAll(nodes=>nodes.map(n=>({unit:n.closest('[data-source-id]').dataset.sourceId,width:n.clientWidth,columns:getComputedStyle(n.querySelector('.research-list')).gridTemplateColumns.split(' ').length,items:n.querySelectorAll('.research-notes-trigger').length,singleton:n.querySelector('.research-notes-trigger:only-child')?.getBoundingClientRect().width,list:n.querySelector('.research-list').clientWidth})));
  assert(results.every(r=>r.columns===(width>=600?2:1)),JSON.stringify({width,results}));assert(results.every(r=>r.items!==1||Math.abs(r.singleton-r.list)<1));evidence.research.push({width,results});
 }
 await research.evaluateAll(nodes=>nodes.forEach(n=>n.style.removeProperty('width')));
 await capture(page,'research-two-columns',page.locator('#unit-anchor-diagnosis .research-notes'));
 const exam=page.locator('#scene-exam');
 await exam.getByRole('button',{name:'试卷评价与生成',exact:true}).click();assert.equal(await exam.locator('.time-diagram').count(),0);assert.equal(await exam.locator('table').count(),1);
 assert.deepEqual(await exam.locator('.flow-stream button').allTextContents(),['确定教学目标','安排卷面结构','选题或出题','逐题解析核验','检查覆盖与难度']);await capture(page,'exam-paper',exam);
 await exam.getByRole('button',{name:'学生作答复盘',exact:true}).click();assert.equal(await exam.locator('.time-diagram').count(),1);assert.equal(await exam.locator('table,.flow-stream').count(),0);assert((await exam.innerText()).includes('未使用两道全国卷的真实学生用时'));await capture(page,'exam-student',exam);
 const evolution=page.locator('#scene-evolution');await evolution.getByRole('button',{name:'联网找题与教材更新',exact:true}).click();
 assert((await evolution.locator('.scenario-detail').innerText()).includes('指定公开题源联网发现、下载、识别和切题'));
 assert.deepEqual(await evolution.locator('.flow-stream button').allTextContents(),['收集反馈与新题','核对与去重','整理更新草稿','独立测试','审核发布','跟踪学习效果']);await capture(page,'evolution-online',evolution);
 for(const width of [320,390,768,980,1099,1100,1440]){
  await page.setViewportSize({width,height:1000});await page.goto(base+'/#vision-students',{waitUntil:'networkidle'});await ready(page);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Page overflow at '+width);
  const layout=await page.locator('[data-vision-group]').evaluateAll(groups=>groups.map(g=>{
   const cards=[...g.querySelectorAll('.vision-card')],rects=cards.map(n=>n.getBoundingClientRect()),center=g.querySelector('header').getBoundingClientRect(),v=g.querySelector('.vision-viewport').getBoundingClientRect();
   const overlaps=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
   return {id:g.id,camera:!g.querySelector('.vision-camera-controls').hidden,collides:innerWidth>=1100&&rects.some((r,i)=>overlaps(r,center)||rects.slice(i+1).some(s=>overlaps(r,s))),clips:cards.some(n=>n.scrollWidth>n.clientWidth+1||n.scrollHeight>n.clientHeight+1),centerDelta:Math.abs((rects[0].left+rects[0].right-v.left-v.right)/2),height:rects[0].height};
  }));assert(layout.every(g=>!g.collides&&!g.clips&&g.camera===(width<1100)&&Math.abs(g.height-88)<1&&(width>=1100||g.centerDelta<2)),JSON.stringify({width,layout}));
  await capture(page,'galaxy-'+width,page.locator('#vision-students'));
 }
 // Sample actual computed light positions/colors, then confirm that time advances on its own.
 await page.emulateMedia({reducedMotion:'no-preference'});
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:width===390?844:1000});await page.goto(base+'/#vision-change-students-1',{waitUntil:'networkidle'});await ready(page);
  const dialog=page.locator('#vision-dialog');await page.waitForFunction(()=>document.getElementById('vision-dialog').dataset.motion==='running');
  await page.waitForTimeout(150);assert(await dialog.locator('.vision-transition-beam').evaluate(n=>n.getAnimations()[0].playState==='running'),'Modal light must survive the background animation suspension');
  const samples=[];
  for(const time of [240,960,1800,2200]){
   const sample=await dialog.evaluate((d,t)=>{d.getAnimations({subtree:true}).forEach(a=>{a.pause();a.currentTime=t;});const beam=d.querySelector('.vision-transition-beam'),r=beam.getBoundingClientRect();return {time:t,x:r.x,y:r.y,red:Number(getComputedStyle(d.querySelector('.vision-beam-red')).opacity),blue:Number(getComputedStyle(d.querySelector('.vision-beam-blue')).opacity),arrival:Number(getComputedStyle(d.querySelector('.vision-change-result'),'::before').opacity)};},time);samples.push(sample);await capture(page,`light-${width}-${time}`,dialog);
  }
  const [red,,blue]=samples;assert(red.red>red.blue&&blue.blue>blue.red&&blue.arrival>.8);assert(width===390?blue.y-red.y>50&&Math.abs(blue.x-red.x)<1:blue.x-red.x>50&&Math.abs(blue.y-red.y)<1,'Light must move along its arrow');evidence.motion[width]=samples;
  // Recreate native CSS animations: WAAPI pause/play overrides CSS play-state,
  // so staged sampling must not contaminate the lifecycle assertions below.
  await page.reload({waitUntil:'networkidle'});await ready(page);
  const before=await dialog.locator('.vision-transition-beam').evaluate(n=>n.getAnimations()[0].currentTime);await page.waitForTimeout(180);assert(await dialog.locator('.vision-transition-beam').evaluate(n=>n.getAnimations()[0].currentTime)>before+90,'Light advances without test-driven time changes');
  await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));});await page.waitForTimeout(50);assert.equal(await dialog.locator('.vision-transition-beam').evaluate(n=>n.getAnimations()[0].playState),'paused');await page.evaluate(()=>{delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'));});
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await dialog.locator('.vision-transition-beam').evaluate(n=>getComputedStyle(n).display),'none');await page.emulateMedia({reducedMotion:'no-preference'});
  await dialog.locator('.vision-dialog-close').click();assert.equal(await dialog.locator('.vision-transition-beam').count(),0);await page.waitForFunction(()=>!document.getElementById('vision-dialog').open);
 }
 // Capture live Chrome screencast frames, then encode them using MediaRecorder.
 await page.setViewportSize({width:1100,height:760});await page.goto(base+'/#vision-change-students-1',{waitUntil:'networkidle'});await ready(page);
 const cdp=await context.newCDPSession(page),frames=[];
 cdp.on('Page.screencastFrame',frame=>{frames.push({data:frame.data,time:frame.metadata.timestamp});void cdp.send('Page.screencastFrameAck',{sessionId:frame.sessionId});});
 await cdp.send('Page.startScreencast',{format:'jpeg',quality:85,maxWidth:1100,maxHeight:760,everyNthFrame:2});await page.waitForTimeout(4900);await cdp.send('Page.stopScreencast');assert(frames.length>=20,'A live motion recording needs enough frames');
 const encoder=await context.newPage();
 const encoded=await encoder.evaluate(async frames=>{
  const images=await Promise.all(frames.map(f=>new Promise(resolve=>{const image=new Image();image.onload=()=>resolve(image);image.src='data:image/jpeg;base64,'+f.data;})));
  const canvas=document.createElement('canvas');canvas.width=images[0].width;canvas.height=images[0].height;const draw=canvas.getContext('2d'),stream=canvas.captureStream(30),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp9'}),chunks=[];
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};const stopped=new Promise(resolve=>recorder.onstop=resolve);draw.drawImage(images[0],0,0);recorder.start();let previous=frames[0].time;
  for(let i=0;i<images.length;i++){await new Promise(resolve=>setTimeout(resolve,Math.max(0,(frames[i].time-previous)*1000)));draw.drawImage(images[i],0,0);previous=frames[i].time;}await new Promise(resolve=>setTimeout(resolve,50));recorder.stop();await stopped;stream.getTracks().forEach(t=>t.stop());
  return await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.readAsDataURL(new Blob(chunks,{type:'video/webm'}));});
 },frames);
 evidence.video=`red-blue-live-${label}.webm`;evidence.videoFrames=frames.length;await writeFile(shots+'/'+evidence.video,Buffer.from(encoded,'base64'));
 await writeFile(shots+'/acceptance.json',JSON.stringify(evidence,null,2)+'\n');console.log(JSON.stringify({ok:true,revision,dirty,screenshots:evidence.screenshots.length,video:evidence.video,shots}));
}finally{if(browser)await browser.close();server?.kill('SIGTERM');}
