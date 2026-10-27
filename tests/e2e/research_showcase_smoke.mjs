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
const chapters=['vision','highlights','terms','single','time','library','exam','longterm','teacher','school','agent','evolution'];
const records=JSON.parse(await readFile(new URL('frontend/showcase/recordings.json',root),'utf8'));
const vision=JSON.parse(await readFile(new URL('frontend/showcase/vision-content.json',root),'utf8'));
const pipeline=JSON.parse(await readFile(new URL('frontend/showcase/pipeline.json',root),'utf8'));
const shots=process.env.RESEARCH_SHOTS||tmpdir()+'/research-showcase-shots';
await mkdir(shots,{recursive:true});
const server=spawn(process.env.SHOWCASE_PYTHON||'python3',['tests/e2e/showcase_server.py'],{
  cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']});
let output='',browser,lastPage;
server.stderr.on('data',chunk=>{output+=chunk.toString();});
const port=await new Promise((resolve,reject)=>{
  let stdout='';const deadline=setTimeout(()=>{server.kill('SIGTERM');reject(Error('Showcase server startup timed out\n'+output));},20000);
  deadline.unref();server.stdout.on('data',chunk=>{stdout+=chunk.toString();const m=stdout.match(/SHOWCASE_PORT=(\d+)/);if(m){clearTimeout(deadline);resolve(Number(m[1]));}});
  server.on('exit',code=>{clearTimeout(deadline);reject(Error('Showcase server exited '+code+'\n'+output));});
});
const base='http://127.0.0.1:'+port;
const audits=[];
// Opt-in diagnostics isolate only the icon URLs explicitly excluded from this repair.
// Default runs remain strict and reject their 404s, along with every other resource error.
const allowExcludedIcon404=process.env.RESEARCH_ALLOW_EXCLUDED_ICON_404==='1',excludedIcon404=new Map();
function excludedIcon(entry){
 if(!allowExcludedIcon404||entry.status!==404)return false;
 let url;try{url=new URL(entry.url);}catch{return false;}
 if(url.origin!==base||!['/showcase/assets/fudan-favicon.png','/showcase/assets/fudan-favicon-180.png'].includes(url.pathname))return false;
 const key=entry.url+' '+entry.message;if(!excludedIcon404.has(key)){excludedIcon404.set(key,entry);console.warn('Diagnostic exclusion for unchanged icon 404: '+entry.url);}
 return true;
}
function audit(page){lastPage=page;const value={errors:[],console:[],requests:[],failures:[],httpErrors:[]};audits.push(value);
 page.on('pageerror',error=>value.errors.push(error.message));
 page.on('console',message=>{if(message.type()==='error')value.console.push({message:message.text(),url:message.location().url,status:/server responded with a status of 404/.test(message.text())?404:null});});
 page.on('request',r=>value.requests.push({url:r.url(),method:r.method()}));
 page.on('response',r=>{if(r.status()>=400)value.httpErrors.push({url:r.url(),status:r.status(),message:'HTTP response'});});
 page.on('requestfailed',r=>value.failures.push(r.url()+': '+r.failure()?.errorText));return value;}
async function ready(page){const launch=page.locator('#launch-screen');if(await launch.isVisible().catch(()=>false))await page.locator('#explore-start').click();await page.waitForFunction(()=>Boolean(window.Showcase?.ready));const value=await page.evaluate(async()=>{
 const data=await window.Showcase.ready;return {version:data?.schema_version,error:window.Showcase.state.loadError};});
 assert.equal(value.error,null,'Showcase initialization failed: '+value.error);assert.equal(value.version,2);}
async function fit(page,label){const metrics=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth}));
 assert(metrics.width<=metrics.viewport+1,'Horizontal overflow '+label+': '+JSON.stringify(metrics));}
async function checkAudits(context){for(const a of audits){assert.deepEqual(a.errors,[],'Uncaught browser errors');assert.deepEqual(a.console.filter(entry=>!excludedIcon(entry)),[],'Console errors');assert.deepEqual(a.failures,[],'Failed resources');assert.deepEqual(a.httpErrors.filter(entry=>!excludedIcon(entry)),[],'HTTP resource errors');
 for(const r of a.requests){if(/^(data:|blob:)/.test(r.url))continue;assert.equal(new URL(r.url).origin,base,'Unexpected external request: '+r.url);assert.equal(r.method,'GET','Unexpected write request');
 assert(!/^\/(?:solve|grade|teach|auth|jobs|questions|patterns|generate)(?:\/|$)/.test(new URL(r.url).pathname),'Unexpected business API request: '+r.url);}}
 assert.deepEqual(await context.cookies(),[],'Showcase created cookies');}
async function keyboardActivate(page,button){await button.focus();await page.keyboard.press('Enter');assert(await button.evaluate(n=>n===document.activeElement),'Re-rendering lost the activated control: '+await button.innerText());}
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
 const page=await context.newPage();audit(page);await page.goto(base+'/',{waitUntil:'networkidle'});
 const launch=page.locator('#launch-screen'),hero=launch.locator('#hero-art'),cta=launch.locator('#explore-start');
 assert(await launch.isVisible(),'A first visit without a deep anchor should show the launch dialog');
 assert(await page.locator('body').evaluate(n=>n.classList.contains('is-launch-open')));
 assert.equal(await launch.locator('#launch-title').evaluate(n=>n.tagName),'H2');
 assert.equal(await launch.locator('.launch-contact').count(),1);
 assert((await launch.locator('.launch-contact').innerText()).includes('施棋智'));
 assert.equal(await launch.locator('.launch-contact a[href="mailto:qzshi25@m.fudan.edu.cn"]').count(),1);
 assert.equal(await launch.locator('.launch-footer a[href="https://150.chat/"]').count(),1);
 assert.equal(await launch.locator('.launch-footer a[href="https://150.chat/"]').innerText(),'正式站（正在开发中）');
 assert.equal(await page.locator('#heading-highlights').evaluate(n=>n.tagName),'H2');
 assert.equal(await page.locator('h1').count(),1);
 assert.equal(await page.locator('#heading-vision').evaluate(n=>n.tagName),'H1');
 assert.equal(await page.locator('.site-author').count(),1);
 assert((await page.locator('.site-author').innerText()).includes('施棋智'));
 assert.equal(await page.locator('.site-author a[href="mailto:qzshi25@m.fudan.edu.cn"]').count(),1);
 assert.equal(await page.locator('.site-footer a[href="https://150.chat/"]').count(),1);
 assert.equal(await page.locator('.site-footer a[href="https://150.chat/"]').innerText(),'正式站（正在开发中）');
 assert.equal(await cta.getAttribute('href'),'#vision');assert(await cta.isVisible());assert(await cta.isEnabled());
 assert.equal(await hero.getAttribute('data-phase'),'ready','Reduced motion should complete the hero immediately');
 assert(await cta.evaluate(n=>n.classList.contains('is-lit')),'Reduced motion should finish the red glass edge immediately');
 const inkGeometry=await launch.evaluate(dialog=>{const button=dialog.querySelector('#explore-start'),path=dialog.querySelector('#hero-ink-path'),length=path.getTotalLength(),matrix=path.ownerSVGElement.getScreenCTM(),start=path.getPointAtLength(0),middle=path.getPointAtLength(length/2),end=path.getPointAtLength(length),b=button.getBoundingClientRect(),lineMid={x:(start.x+end.x)/2,y:(start.y+end.y)/2};return {start:{x:start.x,y:start.y},middle:{x:middle.x,y:middle.y},end:{x:end.x,y:end.y},button: new DOMPoint(b.left,b.top+b.height/2).matrixTransform(matrix.inverse()) ,bend:Math.hypot(middle.x-lineMid.x,middle.y-lineMid.y)};});
 assert(Math.abs(inkGeometry.end.x-inkGeometry.button.x)<2&&Math.abs(inkGeometry.end.y-inkGeometry.button.y)<2,'The final ink stroke should meet the CTA left edge at its vertical midpoint: '+JSON.stringify(inkGeometry));
 assert(inkGeometry.bend<15,'The CTA connector should use a very slight curve: '+JSON.stringify(inkGeometry));
 await page.evaluate(()=>{window.__entered=0;window.addEventListener('showcase:entered',()=>window.__entered++);});
 await cta.focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>location.hash==='#vision'&&!document.body.classList.contains('is-launch-open')&&window.__entered===1);
 await ready(page);
 assert.equal(await page.evaluate(()=>window.__entered),1,'Entering must dispatch exactly once after the native close event');
 assert.equal(await launch.isVisible(),false,'The launch dialog should close on entry');
 assert.equal(await page.locator('.vision-card').count(),63);
 assert.deepEqual(await page.locator('[data-vision-group]').evaluateAll(nodes=>nodes.map(n=>n.querySelectorAll('.vision-card').length)),[21,17,17,8]);
 assert.equal(await page.locator('[data-vision-toggle]').count(),0);
 assert.equal(await page.locator('.vision-chapter-name').innerText(),'教学愿景');
 for(const group of vision.groups)for(let index=0;index<group.rows.length;index++){
  const source=group.rows[index],card=page.locator('#vision-change-'+group.id+'-'+(index+1)+' .vision-card');
  const cardText=await card.innerText();assert(cardText.includes(source.aspect)&&cardText.includes(source.short_vision),'A galaxy node needs both its aspect and summary');await card.scrollIntoViewIfNeeded();await card.evaluate(n=>n.addEventListener('click',()=>{window.__visionOpeningY=scrollY;},{once:true,capture:true}));await card.click();const originY=await page.evaluate(()=>window.__visionOpeningY);
  assert(await page.locator('#vision-dialog').isVisible());
  const text=await page.locator('.vision-dialog-body').innerText();assert(text.includes(source.before)&&text.includes(source.after));
  for(const feature of source.features)assert.equal(await page.locator('.vision-dialog-body a[href="'+feature.target+'"]').filter({hasText:feature.label}).count(),1);
  await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.getElementById('vision-dialog').open&&!location.hash.startsWith('#vision-change-'));
  await page.waitForFunction(id=>document.activeElement===document.querySelector('#'+id+' .vision-card'),'vision-change-'+group.id+'-'+(index+1));assert(Math.abs(await page.evaluate(()=>scrollY)-originY)<3,'Closing a detail must retain its reading position: '+JSON.stringify({originY,after:await page.evaluate(()=>scrollY),aspect:source.aspect}));
 }
 await page.goto(base+'/#vision-change-students-3',{waitUntil:'networkidle'});await ready(page);
 assert(await page.locator('#vision-dialog').isVisible(),'An old aspect deep link must open its detail');
 await page.reload({waitUntil:'networkidle'});await ready(page);assert(await page.locator('#vision-dialog').isVisible());
 await page.locator('.vision-dialog-close').click();await page.waitForFunction(()=>!document.getElementById('vision-dialog').open);
 for(const branch of ['students','teachers','schools','society']){
  await page.locator('.vision-outline a[href="#vision-'+branch+'"]').click();
  await page.waitForFunction(id=>document.activeElement?.id==='vision-title-'+id,branch);
  assert.equal(await page.locator('#topic-quick-jump').inputValue(),'vision');
 }
 await page.locator('.vision-skip').focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.activeElement?.id==='heading-highlights'&&location.hash==='#highlights');
 await page.goto(base+'/#vision',{waitUntil:'networkidle'});await ready(page);
 assert((await page.locator('.vision-cost-result').innerText()).includes('0.0136'));
 assert((await page.locator('.vision-cost-result').innerText()).includes('16.32'));

 await page.evaluate(()=>{window.__replayed=0;window.addEventListener('showcase:entered',()=>window.__replayed++,{once:true});void Showcase.replayOpening();});await page.waitForFunction(()=>document.body.classList.contains('is-launch-open'));
 await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.body.classList.contains('is-launch-open')&&window.__replayed===1);
 assert.equal(await page.locator('.highlight-point').count(),7);assert.equal(await page.locator('#highlights .topic-unit').count(),0);
 assert.equal(await page.locator('#highlights .dataset-metric').count(),4);
 assert.deepEqual(await page.locator('#highlights .dataset-metric dd').allTextContents(),['541','359','1,019','23,261']);
 assert.equal(await page.locator('#scene-overview .architecture-node').count(),13);
 assert.deepEqual(await page.locator('#scene-overview .architecture-node').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href'))),['#terms','#terms','#terms','#terms','#single','#time','#library','#exam','#longterm','#teacher','#school','#agent','#evolution']);
 assert.deepEqual(await page.locator('#highlights [data-hx-motion]').evaluateAll(nodes=>nodes.map(n=>n.dataset.hxMotion)),['system','method','time','ability','data','participation','evolution']);
 assert.equal(await page.locator('#scene-overview .system-people').count(),0,'The retired people diagram should not return');
 assert.equal(await page.locator('.primary-nav a span').evaluateAll(nodes=>nodes.filter(n=>/^\s*\d+/.test(n.textContent)).length),0,'Primary navigation should not show decorative numbering');
 assert.equal(await page.locator('.highlight-index').evaluateAll(nodes=>nodes.filter(n=>/^\s*0?\d+[/、.]/.test(n.textContent)).length),0,'Highlight labels should not contain decorative numbers');
 assert.equal(await page.locator('body').evaluate(n=>/\bU01\b|批注号/.test(n.innerText)),false,'Removed annotation identifiers should not appear publicly');
 assert.equal(await page.locator('.dataset-metric').filter({hasText:'359'}).locator('dt').innerText(),'二级步骤');
 assert.equal(await page.locator('body').evaluate(n=>n.innerText.includes('保留题型与父步骤作用域')),false,'The old concrete step description should not appear publicly');
 const methodFigure=page.locator('[data-hx-motion="method"]'),methodButtons=methodFigure.locator('[data-hx-method]');
 await methodButtons.nth(2).click();assert.equal(await methodFigure.getAttribute('data-hx-stage'),'2');assert.equal(await methodButtons.nth(2).getAttribute('aria-pressed'),'true');
 await page.waitForTimeout(3300);assert.equal(await methodFigure.getAttribute('data-hx-stage'),'2','Manual method selection should stop automatic stage rotation');
 const ability=page.locator('[data-hx-motion="ability"]'),profileButtons=ability.locator('[data-hx-profile-button]'),radar=ability.locator('[data-hx-radar-shape]');assert.equal(await profileButtons.count(),2);
 const initialRadar=await radar.getAttribute('points');await profileButtons.nth(1).click();
 assert.equal(await profileButtons.nth(1).getAttribute('aria-pressed'),'true');assert.notEqual(await radar.getAttribute('points'),initialRadar,'Profile control should change the radar polygon');
 const profileB=await radar.getAttribute('points');await page.waitForTimeout(700);assert.equal(await radar.getAttribute('points'),profileB,'Reduced motion should disable automatic radar morphing');
 await profileButtons.nth(0).click();assert.equal(await profileButtons.nth(0).getAttribute('aria-pressed'),'true');assert.equal(await radar.getAttribute('points'),initialRadar,'The second profile should toggle back to the first polygon');
 const dimensionButtons=ability.locator('[data-hx-dimension]');await dimensionButtons.nth(4).click();
 assert.equal(await dimensionButtons.nth(4).getAttribute('aria-pressed'),'true');
 assert(await ability.locator('[data-hx-evidence="4"]').evaluate(n=>n.classList.contains('is-selected')));
 assert(await ability.locator('[data-hx-axis="4"]').evaluate(n=>n.classList.contains('is-selected')));
 assert.equal(await ability.locator('[data-hx-evidence].is-selected').count(),1);assert.equal(await ability.locator('[data-hx-axis].is-selected').count(),1);
 const radarDots=ability.locator('[data-hx-dot-dimension]');
 assert.equal(await radarDots.count(),6);
 await radarDots.nth(2).focus();await page.keyboard.press('Enter');
 assert.equal(await ability.getAttribute('data-hx-dimension-active'),'2');
 assert.equal(await radarDots.nth(2).getAttribute('aria-pressed'),'true');
 await page.keyboard.press('ArrowRight');
 assert(await radarDots.nth(3).evaluate(n=>n===document.activeElement));
 assert.equal(await ability.getAttribute('data-hx-dimension-active'),'3');
 await radarDots.nth(5).focus();await page.keyboard.press('Space');
 assert.equal(await ability.getAttribute('data-hx-dimension-active'),'5');
 await page.keyboard.press('Home');assert(await radarDots.first().evaluate(n=>n===document.activeElement));
 assert.equal(await ability.getAttribute('data-hx-dimension-active'),'0');
 assert.equal(await ability.locator('[data-hx-motion-toggle]').count(),0,'Reduced-motion readers do not need animation controls');
 assert.equal(await page.locator('#highlight-system').count(),1);
 await page.goto(base+'/',{waitUntil:'networkidle'});await ready(page);
 assert.deepEqual(await page.locator('[data-chapter]').evaluateAll(nodes=>nodes.map(n=>n.id)),chapters);
 assert(!/上海|shanghai/i.test(await page.locator('body').innerText()),'Retired regional example is visible');
 assert.equal(await page.locator('h1').count(),1);
 assert((await page.locator('.primary-nav a[href="#highlights"]').innerText()).includes('亮点'));
 assert.equal(await page.locator('#highlights #scene-dataset .dataset-metric').count(),4,'The dataset should be embedded in the highlights topic');
 assert.equal(await page.locator('#highlights .inline-dataset-goals').count(),0);
 assert.deepEqual(await page.locator('body').evaluate(n=>({background:getComputedStyle(n).backgroundColor,color:getComputedStyle(n).color})),{background:'rgb(8, 8, 8)',color:'rgb(245, 245, 245)'});
 assert.equal(await page.locator('.brand-emblem').getAttribute('src'),'/showcase/assets/fudan-emblem-white.png');
 assert(await page.locator('.brand-emblem').evaluate(img=>img.complete&&img.naturalWidth>0),'The Fudan emblem should load as a local asset');
 assert.equal(await page.locator('.perspective-switch').isVisible(),false,'The reading-view switch belongs only on narrow screens');
 assert.equal(await page.locator('details.vision-fallback').count(),63,'All aspects retain a native no-JS fallback');
 assert.equal(await page.locator('details.unit-tech-fold').count(),0,'Technical notes stay visible as accepted on main');
 assert.equal(await page.locator('.source-reading').count(),0,'Internal source-document lists should not appear in the public story');
 assert.equal(await page.locator('.perspective-cell').count(),19,'All current merged and parallel lanes are retained');
 assert.equal(await page.locator('.shared-cell').count(),0,'Highlights should not use generic shared cells');
 assert.equal(await page.locator('.highlight-pain').count(),6,'Six highlights carry a practical pain point');
 assert.equal(await page.locator('.perspective-cell').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none').length),19,'Desktop should expose every merged or parallel content lane');
 assert.equal(await page.locator('.perspective-headings').count(),4,'Only topics with distinct reading lanes need column headings');
 assert((await page.locator('.research-scope').count())>0,'Research limitations should be visibly identified');
 assert((await page.locator('.pain-point').first().evaluate(n=>getComputedStyle(n).borderLeftColor)).includes('255, 146, 156'),'Real-world pain points should use the red accent');
 assert.equal(await page.locator('.brand-emblem').evaluate(n=>getComputedStyle(n).backgroundColor),'rgba(0, 0, 0, 0)','The white emblem should retain the black page background');
 assert((await page.locator('.research-gap').count())>10,'Only concrete research limitations should carry caution emphasis');
 // A medium desktop must keep both lanes, with the same usable connection as a wide desktop.
 await page.setViewportSize({width:980,height:900});
 assert.equal(await page.locator('.perspective-cell').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none').length),19);
 assert.equal(await page.locator('.perspective-switch').isVisible(),false);await fit(page,'980px two lanes');
 await page.setViewportSize({width:1440,height:1000});
 assert.equal(await page.locator('.chapter-bridge').count(),12,'Each topic must pass a specific output to its successor');
 assert.equal(await page.locator('.pain-point').count(),13,'Generic topic modules should explain practical problems');
 assert.equal(await page.locator('.research-logic').count(),18,'Related work must have a presentation-style logic diagram');
 assert.equal(await page.locator('.research-source-links a').count(),36,'Each related work needs a website and a primary document link');
 assert.equal(await page.locator('#reading-progress,#opening-skip').count(),0);
 assert.equal(await page.locator('#scene-overview .architecture-node').count(),13,'The highlight system map should cover all ten functional topics');
 await page.evaluate(()=>document.fonts.ready);
 assert(await page.evaluate(()=>document.fonts.check('22px "StudyAgent Handwriting"')),'The local handwriting webfont did not load');
 await fit(page,'desktop overview');await page.screenshot({path:shots+'/desktop-overview.png'});
 await page.locator('.project-architecture').screenshot({path:shots+'/system-architecture.png'});
 // Each unmerged unit remembers its own gutter while preserving a single reading surface.
 await page.locator('#single').scrollIntoViewIfNeeded();
 const divider=page.locator('#single [data-split-control]');await divider.scrollIntoViewIfNeeded();
 assert.equal(await divider.getAttribute('aria-valuenow'),'66','Teaching should receive the larger default share');
 await divider.focus();await page.keyboard.press('ArrowLeft');assert.equal(await divider.getAttribute('aria-valuenow'),'64');
 await page.keyboard.press('Enter');assert.equal(await divider.getAttribute('aria-valuenow'),'66');
 const otherDivider=page.locator('#library [data-split-control]').first(),otherRatio=await otherDivider.getAttribute('aria-valuenow');
 const grip=await divider.boundingBox(),gripY=Math.min(850,Math.max(170,grip.y+25));await page.mouse.move(grip.x+grip.width/2,gripY);await page.mouse.down();
 await page.mouse.move(grip.x+grip.width/2+100,gripY,{steps:8});await page.mouse.up();
 assert(Number(await divider.getAttribute('aria-valuenow'))>66,'Dragging should enlarge the teaching lane');
 assert.equal(await otherDivider.getAttribute('aria-valuenow'),otherRatio,'Resizing one unit must preserve another unit’s chosen width');
 await divider.focus();await page.keyboard.press('Enter');
 const sizes=await page.locator('#single .perspective-cell').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().width));
 assert(sizes[0]>sizes[1]*1.4,'Content should have more horizontal space than technical notes');
 // The single header navigation maps directly to the shared 12-topic sequence.
 assert.equal(await page.locator('.primary-nav a').count(),12);
 await page.locator('.primary-nav a[href="#terms"]').focus();await page.keyboard.press('Enter');
 await page.waitForFunction(()=>location.hash==='#terms');
 for(const id of chapters){await page.locator('#'+id).scrollIntoViewIfNeeded();assert(await page.locator('#heading-'+id).isVisible());await fit(page,'chapter '+id);}
 assert.equal(await page.locator('#system-trail,.system-trail').count(),0,'The redundant second navigation row should be removed');
 assert.deepEqual(await page.locator('.primary-nav a').evaluateAll(nodes=>nodes.map(n=>n.hash.slice(1))),chapters,'The single header must map directly to all topics');
 // Re-rendered controls must keep keyboard focus at the same semantic action.
 await keyboardActivate(page,page.locator('#scene-concepts .concept-node').nth(2));
 for(const label of ['教学过程','步骤批改','结构化解题'])await keyboardActivate(page,page.locator('#scene-single').getByRole('button',{name:label,exact:true}));
 await page.locator('#example-select').focus();await page.locator('#example-select').selectOption('national-2025-q16');
 assert.equal(await page.evaluate(()=>document.activeElement?.id),'example-select');
 await page.locator('#teacher-select').focus();await page.locator('#teacher-select').selectOption('xuefeng');
 assert.equal(await page.evaluate(()=>document.activeElement?.id),'teacher-select');
 await page.locator('#scene-single .solution-more').first().click();
 assert.equal(await page.locator('#research-modal [data-math-erratum="geometric-tail"]').count(),1,'The saved second-part explanation needs its separate erratum');
 assert((await page.locator('#research-modal [data-math-erratum]').innerText()).includes('应单列'));
 await page.locator('#research-modal [data-math-erratum]').screenshot({path:shots+'/math-erratum.png'});await page.locator('.research-modal-close').click();
 await keyboardActivate(page,page.locator('#scene-diagnosis [aria-label="诊断情境"] button').nth(1));
 await keyboardActivate(page,page.locator('#scene-diagnosis [aria-label="对比条件"] button').nth(1));
 // Both questions and all four genuine saved runs must be selectable.
 await choose(page,'single','结构化解题');assert.equal(await page.locator('#example-select option').count(),2);assert.equal(await page.locator('#teacher-select option').count(),4);
 for(const example of ['national-2023-q17','national-2025-q16'])for(const teacher of ['liangliang','taotao','xuefeng','ji']){
  await page.locator('#example-select').selectOption(example);await page.locator('#teacher-select').selectOption(teacher);
  const run=pipeline.examples[example][teacher];
  assert.equal(await page.locator('#scene-single .step').count(),run.answer_json.chunk_results[0].steps.length);
  assert.equal(await page.locator('#scene-single .step h4').first().innerText(),run.answer_json.chunk_results[0].steps[0].title);
  for(const chunk of run.answer_json.chunk_results.slice(1)){await page.locator('#scene-single .solution-more').filter({hasText:'第 '+chunk.chunk_id+' 问'}).click();assert.equal(await page.locator('#research-modal .step').count(),chunk.steps.length);await page.locator('.research-modal-close').click();}
  const model=run.stages.solver.model,tier={'glm-4.7-flash':'免费','deepseek-flash':'便宜','glm-5.3-flash':'便宜','gpt-6-astra':'昂贵'}[model];
  assert((await page.locator('#teacher-select option:checked').innerText()).includes(model),'Teacher selector should identify the model used for the current saved answer');
  assert((await page.locator('.teacher-model-note').innerText()).includes(tier),'The selected model should show its price tier');
  assert((await page.locator('.api-cost-total').innerText()).startsWith('约 ¥'),'Each answer should show a three-stage API cost estimate');
  assert((await page.locator('.api-cost-usage').innerText()).includes('输入'),'The estimate should expose its saved token basis');
  assert((await page.locator('#scene-single .annotation-source').allTextContents()).join(' ').includes(run.run_at),'The original run timestamp should remain in the source panel');
  assert((await page.locator('#scene-single .katex').count())>0,'Math rendering missing');await fit(page,example+' '+teacher);
 }
 await page.locator('#single').scrollIntoViewIfNeeded();await page.screenshot({path:shots+'/desktop-solution.png'});
 await page.locator('#single .step').first().click();
 assert(await page.locator('#single .technical-summary').evaluate(n=>n.classList.contains('is-relation-target')),'Selecting a step should identify its actual technical target');
 assert.equal(await page.locator('.relation-focus').count(),0,'Content linking must not create a floating technical banner');
 const explanation=page.locator('#scene-single .step .annotation-button').first();await explanation.click();
 assert(await page.locator('#annotation-panel').isVisible());
 assert((await page.locator('#annotation-body').innerText()).length>50,'Detailed solution did not open in the side panel');
 await page.screenshot({path:shots+'/desktop-annotation.png'});
 await page.keyboard.press('Escape');assert(!(await page.locator('#annotation-panel').isVisible()));
 await page.locator('#single .research-notes-trigger').first().click();await page.locator('#research-modal .research-study').screenshot({path:shots+'/research-comparison.png'});await page.locator('.research-modal-close').click();
 // Geometry should reveal the altitude only after an explicit action.
 await choose(page,'single','辅助线与推理');assert.equal(await page.locator('#scene-single .construction-line').count(),0);
 await choose(page,'single','显示辅助线');assert.equal(await page.locator('#scene-single .construction-line').count(),1);
 await choose(page,'single','关联推导');assert((await page.locator('#scene-single svg.triangle-figure').textContent()).includes('h = 6'));
 // All six predetermined inputs and both information conditions are visible.
 assert.equal(records.cases.length,6,'There must be six predetermined diagnostic scenarios');
 for(let i=0;i<records.cases.length;i++){
  const c=records.cases[i];await page.locator('#scene-diagnosis [aria-label="诊断情境"] button').nth(i).click();
  assert.equal(await page.locator('#scene-diagnosis .handwriting-sheet').getAttribute('data-source'),c.student_answer,'Handwriting presentation lost the original test input');
  assert((await page.locator('#scene-diagnosis .handwriting-sheet .paper-math .katex').count())>0,'Mathematical expressions should be typeset independently of handwritten prose');
  assert.equal(await page.locator('#scene-diagnosis .handwriting-sheet .katex-error').count(),0);
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
 await page.locator('#time').scrollIntoViewIfNeeded();await page.screenshot({path:shots+'/desktop-comparison.png'});
 await choose(page,'diagnosis','返回修改');
 assert((await page.locator('#scene-diagnosis .timestamp-evidence').innerText()).includes('返回前面的区域'));
 // Saved teaching frames and generated result are navigable when actually recorded.
 await choose(page,'single','教学过程');if(records.teaching?.status==='recorded'&&records.teaching.frames?.length>1){
  const before=await page.locator('#scene-single .teacher-answer').textContent();await keyboardActivate(page,page.locator('#scene-single').getByRole('button',{name:'下一状态',exact:true}));
  assert.notEqual(await page.locator('#scene-single .teacher-answer').textContent(),before);await choose(page,'single','上一步');}
 await choose(page,'single','针对性变式');if(records.generation?.status==='recorded'){
  assert(await page.locator('#scene-single .sample-question').count());
  assert.equal(await page.locator('#scene-single .sample-question .katex-error').count(),0,'Generated question formula rendering failed');
  assert(!(await page.locator('#scene-single .sample-question').innerText()).includes('\\n'),'Escaped JSON newline leaked into presentation');
 }
 // National-only library filtering, selected-question paper, teacher answers and print.
 await page.locator('#bank-workbench').scrollIntoViewIfNeeded();await page.waitForFunction(()=>window.ShowcaseBank?.state.index?.length===2);
 assert.equal(await page.locator('#library-list .bank-row').count(),2);
 const libraryTabs=page.locator('[data-library-tab]');
 await libraryTabs.nth(0).focus();await page.keyboard.press('ArrowRight');
 assert.equal(await libraryTabs.nth(1).getAttribute('aria-selected'),'true');
 assert(await libraryTabs.nth(1).evaluate(n=>n===document.activeElement));
 await page.keyboard.press('End');assert.equal(await libraryTabs.nth(2).getAttribute('aria-selected'),'true');
 assert(await page.locator('[data-calendar-empty]').isVisible());
 assert((await page.locator('[data-calendar-empty]').innerText()).includes('暂无复查任务'));
 await page.locator('[data-calendar-empty]').screenshot({path:shots+'/calendar-empty.png'});
 assert.equal(await page.locator('#library-layout').getAttribute('role'),'tabpanel');
 assert.equal(await page.locator('#library-layout').getAttribute('aria-labelledby'),'library-tab-calendar');
 await page.locator('[data-calendar-empty]').getByRole('button',{name:'查看公开题库',exact:true}).click();
 assert.equal(await libraryTabs.nth(0).getAttribute('aria-selected'),'true');
 assert.equal(await page.evaluate(()=>document.activeElement?.id),'bank-search');
 await libraryTabs.nth(2).focus();await page.keyboard.press('Home');
 assert(await libraryTabs.nth(0).evaluate(n=>n===document.activeElement));

 await page.locator('#bank-search').fill('数列');await page.waitForFunction(()=>window.ShowcaseBank.state.rows.length===1);
 assert((await page.locator('#library-list').innerText()).includes('数列'));await fit(page,'filtered bank');
 await page.locator('#bank-search').fill('');await page.waitForFunction(()=>window.ShowcaseBank.state.rows.length===2);
 for(const checkbox of await page.locator('#library-list input[type="checkbox"]').all())await checkbox.check();
 await page.locator('#bank-build-exam').click();await page.waitForFunction(()=>document.querySelectorAll('#exam-preview .exam-question').length===2);
 assert(!(await page.locator('#exam-preview').innerText()).includes('上海'));
 assert.equal(await page.locator('#exam-preview .bank-chunk').count(),0);
 await page.locator('#exam-teacher').click();await page.waitForFunction(()=>document.querySelectorAll('#exam-preview .bank-chunk').length===4);
 assert.equal(await page.locator('#exam-preview [data-math-erratum="geometric-tail"]').count(),1,'Teacher print must also show the sequence erratum');
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
 await page.evaluate(()=>{window.Showcase.selectView('agent');const topic=document.querySelector('#agent');window.scrollTo({top:topic.getBoundingClientRect().top+scrollY-110,behavior:'instant'});});
 await page.evaluate(()=>{document.querySelector('[data-perspective="technical"]').click();window.scrollBy({top:180,behavior:'instant'});});await page.waitForTimeout(220);
 await page.locator('#unit-anchor-agent [data-split-control]').focus();await page.keyboard.press('ArrowRight');
 // Let the resized columns finish laying out before capturing a reading position.
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const savedSplit=await page.evaluate(()=>ShowcaseSplit.ratio('agent'));
 const beforeReload=await page.evaluate(()=>({y:scrollY,caseIndex:Showcase.state.caseIndex,condition:Showcase.state.condition,perspective:Showcase.state.perspective}));
 await page.reload({waitUntil:'networkidle'});assert.equal(await page.locator('#launch-screen').isVisible(),false,'Reloading an established reading session should skip the launch dialog');await ready(page);
 const restored=await page.evaluate(()=>({y:scrollY,caseIndex:Showcase.state.caseIndex,condition:Showcase.state.condition,perspective:Showcase.state.perspective,example:Showcase.state.example,teacher:Showcase.state.teacher,career:Showcase.state.sceneTabs.career,selected:ShowcaseBank.state.selected.size}));
 assert(Math.abs(restored.y-beforeReload.y)<8,'Reading position changed after reload: '+JSON.stringify({beforeReload,restored}));
 assert(Math.abs((await page.evaluate(()=>ShowcaseSplit.ratio('agent')))-savedSplit)<.001,'The chosen column width should survive refresh');
 assert.equal(restored.caseIndex,beforeReload.caseIndex);assert.equal(restored.condition,beforeReload.condition);assert.equal(restored.perspective,'technical');assert.equal(restored.example,'national-2025-q16');assert.equal(restored.teacher,'liangliang');assert.equal(restored.career,2);assert.equal(restored.selected,2);assert.equal(await page.locator('#bank-search').inputValue(),'数列');
 await page.goto(base+'/?perspective=mechanism#single',{waitUntil:'networkidle'});await ready(page);assert.equal(await page.locator('#launch-screen').isVisible(),false,'Deep links should skip the launch screen');assert.equal(await page.evaluate(()=>Showcase.state.perspective),'technical','Legacy mechanism-view links should map to technical implementation');
 assert.equal(await page.locator('.site-registration a').innerText(),'渝ICP备2026024246号-1');assert.equal(await page.locator('.site-registration a').getAttribute('href'),'https://beian.miit.gov.cn/');
 await checkAudits(context);

 for(const width of [1440,1100,1099,980,768,390,320]){
  await page.setViewportSize({width,height:1000});await page.goto(base+'/#vision-students',{waitUntil:'networkidle'});await ready(page);await fit(page,'vision '+width);
  const layout=await page.locator('[data-vision-group]').evaluateAll(groups=>groups.map(g=>{
   const buttons=[...g.querySelectorAll('.vision-card')],cards=buttons.map(n=>n.getBoundingClientRect()),viewport=g.querySelector('.vision-viewport').getBoundingClientRect(),heading=g.querySelector('.vision-group-heading').getBoundingClientRect();let collisions=0;
   const overlaps=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
   if(innerWidth>=1100){for(let i=0;i<cards.length;i++){if(overlaps(cards[i],heading))collisions++;for(let j=i+1;j<cards.length;j++)if(overlaps(cards[i],cards[j]))collisions++;}}
   return {id:g.id,collisions,clipped:buttons.some(b=>b.scrollHeight>b.clientHeight+1||b.scrollWidth>b.clientWidth+1),centerDelta:Math.abs((cards[0].left+cards[0].right-viewport.left-viewport.right)/2),camera:!g.querySelector('.vision-camera-controls').hidden};
  }));assert(layout.every(g=>g.collisions===0&&!g.clipped),'Galaxy nodes and center descriptions must fit: '+JSON.stringify({width,layout}));assert(layout.every(g=>g.camera===(width<1100)));if(width<1100)assert(layout.every(g=>g.centerDelta<2));
  await page.locator('#vision-students').screenshot({path:shots+'/vision-'+width+'.png'});
  await page.locator('#vision-change-students-1 .vision-card').click();await page.locator('#vision-dialog').screenshot({path:shots+'/vision-comparison-'+width+'.png'});await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.getElementById('vision-dialog').open);
 }
 await page.locator('.vision-outline a[href="#vision-teachers"]').click();
 await page.evaluate(()=>{scrollBy({top:180,behavior:'instant'});Showcase.saveReading();});
 const visionReading=await page.evaluate(()=>({y:scrollY,hash:location.hash}));
 await page.reload({waitUntil:'networkidle'});await ready(page);
 assert.equal(await page.locator('#launch-screen').isVisible(),false);
 assert.equal(await page.locator('#topic-quick-jump').inputValue(),'vision');
 const restoredVision=await page.evaluate(()=>({y:scrollY,hash:location.hash}));
 assert.equal(restoredVision.hash,visionReading.hash);
 assert(Math.abs(restoredVision.y-visionReading.y)<8,'Vision reading should survive refresh: '+JSON.stringify({visionReading,restoredVision}));
 // Phone widths remain within the viewport.
 await page.evaluate(()=>window.Showcase.clearReadingState());
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/',{waitUntil:'networkidle'});
 assert(await page.locator('#launch-screen').isVisible(),'A cleared mobile session should show the launch dialog');
 assert.equal(await page.locator('#launch-screen #hero-art').getAttribute('data-phase'),'ready','Mobile reduced motion should complete the hero immediately');
 assert(await page.locator('#launch-screen #explore-start').isEnabled(),'The phone CTA should always be clickable');
 assert.equal(await page.locator('#launch-screen #explore-start').getAttribute('href'),'#vision');
 const mobileEntry=await page.locator('#launch-screen #explore-start').boundingBox();assert(mobileEntry.y+mobileEntry.height<=844,'The phone CTA should fit above the viewport edge');
 await page.screenshot({path:shots+'/hero-mobile.png'});
 await page.locator('#launch-screen #explore-start').click();await ready(page);
 assert.equal(await page.evaluate(()=>Showcase.state.perspective),'teaching','Phone should default to the teaching view');
 assert.equal(await page.locator('.perspective-switch').isVisible(),false,'Shared highlights do not need a perspective switch');
 await page.locator('#single').scrollIntoViewIfNeeded();
 await page.waitForFunction(()=>document.body.dataset.currentTopic==='single'&&document.body.classList.contains('reader-ready'));
 assert.equal(await page.locator('.perspective-switch').isVisible(),true,'Narrow screens should expose the view switch for two-lane topics');
 assert.equal(await page.locator('#single [data-split-control]').isVisible(),false,'Phone reading should not expose an unusable two-column drag handle');
 assert.equal(await page.locator('.perspective-cell').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none').length),13,'Phone should show one perspective per generic content unit');
 await page.locator('[data-perspective="technical"]').click();assert.equal(await page.evaluate(()=>Showcase.state.perspective),'technical');assert.match(page.url(),/perspective=technical/);
 const touchSection=page.locator('#single');await touchSection.evaluate(node=>{const start=new Touch({identifier:1,target:node,clientX:320,clientY:350});node.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,touches:[start],changedTouches:[start]}));const end=new Touch({identifier:1,target:node,clientX:220,clientY:350});node.dispatchEvent(new TouchEvent('touchend',{bubbles:true,touches:[],changedTouches:[end]}));});
 assert.equal(await page.evaluate(()=>Showcase.state.perspective),'teaching','A horizontal swipe should advance between the two phone perspectives');
 await page.locator('[data-perspective="teaching"]').click();
 for(const id of chapters){await page.locator('#'+id).scrollIntoViewIfNeeded();await fit(page,'mobile '+id);}
 await choose(page,'single','辅助线与推理');await choose(page,'single','显示辅助线');
 await choose(page,'diagnosis','同信息条件');await fit(page,'mobile comparison');
 await page.locator('#time').scrollIntoViewIfNeeded();await page.screenshot({path:shots+'/mobile-comparison.png'});
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
 await nojs.goto(base+'/',{waitUntil:'networkidle'});assert.equal(await nojs.locator('[data-chapter]').count(),12);
 for(const id of chapters){const text=['vision','highlights'].includes(id)?await nojs.locator('#'+id).innerText():(await nojs.locator('#'+id+' .chapter-prose').allTextContents()).join(' ');assert(text.length>80,'Missing no-JS chapter text: '+id);}
 assert.equal(await nojs.locator('#launch-screen #explore-start').getAttribute('href'),'#vision');
 assert.equal(await nojs.locator('.perspective-cell').count(),19,'No-JS reading should retain every current generic lane');
 assert.equal(await nojs.locator('.perspective-cell').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none').length),19,'No-JS reading should expose all generic content');
 assert((await nojs.locator('.research-notes a[href^="https://"]').count())>=6,'Research sources unavailable without JS');
 assert(!/上海|shanghai/i.test(await nojs.locator('body').innerText()));await fit(nojs,'no JavaScript');await checkAudits(plain);await plain.close();
 const deepContext=await browser.newContext({viewport:{width:1440,height:950}}),deepPage=await deepContext.newPage();audit(deepPage);
 await deepPage.goto(base+'/#single',{waitUntil:'networkidle'});assert.equal(await deepPage.locator('#launch-screen').isVisible(),false,'A fresh deep link should skip the launch dialog');await ready(deepPage);
 assert.equal(await deepPage.evaluate(()=>location.hash),'#single');await checkAudits(deepContext);await deepContext.close();
 // Camera touring and decorative flow share visibility/reduced-motion lifecycles.
 const tourContext=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'no-preference'}),tour=await tourContext.newPage();audit(tour);
 await tour.goto(base+'/#vision-students',{waitUntil:'networkidle'});await ready(tour);
 const galaxy=tour.locator('#vision-students'),counter=galaxy.locator('.vision-camera-count');await galaxy.scrollIntoViewIfNeeded();
 await tour.waitForFunction(()=>document.querySelector('#vision-students .vision-camera-count').textContent.startsWith('2 /'),{},{timeout:5000});
 await galaxy.locator('[data-camera-step="1"]').click();await galaxy.locator('h2').click();
 const selected=await counter.innerText();await tour.waitForTimeout(1400);assert.equal(await counter.innerText(),selected,'Each camera stop must remain readable before moving');
 await tour.waitForFunction(old=>document.querySelector('#vision-students .vision-camera-count').textContent!==old,selected,{timeout:2200});
 await tour.emulateMedia({reducedMotion:'reduce'});const settled=await counter.innerText();await tour.waitForTimeout(2800);assert.equal(await counter.innerText(),settled);
 await galaxy.locator('[data-camera-step="1"]').click();assert.notEqual(await counter.innerText(),settled,'Manual navigation remains available with reduced motion');
 await galaxy.locator('.vision-card[aria-current=true]').click();assert(await tour.locator('#vision-dialog').isVisible());await tour.goBack();await tour.waitForFunction(()=>!document.getElementById('vision-dialog').open);
 await tour.goto(base+'/#vision-change-teachers-3',{waitUntil:'networkidle'});await ready(tour);assert(await tour.locator('#vision-dialog').isVisible());
 const destination=await tour.locator('.vision-dialog-body a').first().getAttribute('href');await tour.locator('.vision-dialog-body a').first().click();await tour.waitForFunction(hash=>location.hash===hash&&!document.getElementById('vision-dialog').open,destination);
 await tour.emulateMedia({reducedMotion:'no-preference'});await tour.goto(base+'/#vision-students',{waitUntil:'networkidle'});await ready(tour);await galaxy.scrollIntoViewIfNeeded();
 await galaxy.locator('[data-camera-step="1"]').click();await galaxy.locator('h2').click();
 await galaxy.locator('.vision-card[aria-current=true]').click();const modalIndex=await counter.innerText();await tour.waitForTimeout(2800);assert.equal(await counter.innerText(),modalIndex,'An open detail freezes its camera');await tour.locator('.vision-dialog-close').click();
 await tour.locator('#terms').scrollIntoViewIfNeeded();await tour.waitForFunction(()=>!document.querySelector('#vision-students .vision-world').getAnimations().length);const offscreen=await galaxy.locator('.vision-world').evaluate(n=>getComputedStyle(n).transform);await tour.waitForTimeout(2800);assert.equal(await galaxy.locator('.vision-world').evaluate(n=>getComputedStyle(n).transform),offscreen,'An offscreen galaxy must stop');
 await tour.setViewportSize({width:1440,height:950});await tour.locator('#teacher').scrollIntoViewIfNeeded();const stream=tour.locator('#scene-teacher .flow-stream');await stream.scrollIntoViewIfNeeded();
 await tour.waitForFunction(()=>document.querySelector('#scene-teacher .flow-stream').dataset.flowRunning==='true');
 assert.equal(await stream.locator('button').first().getAttribute('aria-pressed'),'true','The first visible step starts at the left');
 const beam=await stream.locator('.flow-beam').first().evaluate(n=>({duration:n.getAnimations()[0].effect.getTiming().duration,first:n.getAnimations()[0].effect.getKeyframes()[0].transform}));assert.equal(beam.duration,2000);
 const startX=await stream.evaluate(n=>{const b=n.querySelector('button');return b.offsetLeft+b.offsetWidth/2;});assert(Math.abs(Number(beam.first.match(/translate3d\(([-.\d]+)/)[1])-startX)<1,'A flow starts at the first step, never a restored middle index');
 await stream.locator('button').nth(3).click();assert.equal(await stream.getAttribute('data-flow-running'),'true','Choosing a step does not stop the decorative flow');await stream.evaluate(n=>n.querySelectorAll('.flow-beam').forEach(b=>b.getAnimations().forEach(a=>a.currentTime=900)));await stream.screenshot({path:shots+'/flow-stream.png'});
 await tour.emulateMedia({reducedMotion:'reduce'});await tour.waitForFunction(()=>document.querySelector('#scene-teacher .flow-stream').dataset.flowRunning==='false');await tour.emulateMedia({reducedMotion:'no-preference'});await tour.waitForFunction(()=>document.querySelector('#scene-teacher .flow-stream').dataset.flowRunning==='true');
 await tour.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));});assert.equal(await stream.getAttribute('data-flow-running'),'false','Background pages stop their flows');await tour.evaluate(()=>{delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'));});await tour.waitForFunction(()=>document.querySelector('#scene-teacher .flow-stream').dataset.flowRunning==='true');
 await tour.locator('#vision').scrollIntoViewIfNeeded();await tour.waitForFunction(()=>document.querySelector('#scene-teacher .flow-stream').dataset.flowRunning==='false');
 await checkAudits(tourContext);await tourContext.close();

// The opening copy, white math, red lettering, and connector play before entry; topic handoffs remain readable.
 const motion=await browser.newContext({viewport:{width:1440,height:950},reducedMotion:'no-preference'});
 const animated=await motion.newPage();audit(animated);await animated.goto(base+'/',{waitUntil:'domcontentloaded'});
 await animated.waitForFunction(()=>Boolean(window.Showcase)&&document.querySelector('#launch-screen')?.open);
 const animatedLaunch=animated.locator('#launch-screen'),animatedCTA=animatedLaunch.locator('#explore-start');
 assert(await animatedCTA.isVisible());assert(await animatedCTA.isEnabled(),'CTA remains clickable during ink animation');
 await animated.waitForFunction(()=>{const output=document.querySelector('#launch-screen .is-stream-current .stream-output'),source=output?.parentElement.querySelector('.stream-source');return output&&source&&output.textContent.length>0&&output.textContent.length<source.textContent.length;},{timeout:3000});
 assert.equal(await animatedLaunch.locator('#hero-art').getAttribute('data-phase'),'typing');
 await animated.screenshot({path:shots+'/hero-typing.png'});
 await animated.waitForFunction(()=>document.querySelector('#launch-screen #hero-art').dataset.phase==='math-writing',{timeout:3000});
 await animated.screenshot({path:shots+'/hero-math-writing.png'});
 await animated.waitForFunction(()=>document.querySelector('#launch-screen #hero-art').dataset.phase==='writing',{timeout:3000});
 await animated.screenshot({path:shots+'/hero-love.png'});
 await animated.waitForFunction(()=>document.querySelector('#launch-screen #hero-art').dataset.phase==='connecting',{timeout:3000});
 assert.equal(await animated.locator('#explore-start').evaluate(n=>n.classList.contains('is-lit')),false,'The CTA should remain dark until the connecting stroke arrives');
 await animated.screenshot({path:shots+'/hero-connecting.png'});
 await animated.waitForFunction(()=>document.querySelector('#launch-screen #hero-art').dataset.phase==='ready',{timeout:3000});
 assert(await animated.locator('#explore-start').evaluate(n=>n.classList.contains('is-lit')),'The CTA should receive its red glass edge when the ink arrives');
 await animatedCTA.evaluate(n=>Promise.all(n.getAnimations().map(a=>a.finished)));
 const edge=await animatedCTA.evaluate(n=>getComputedStyle(n).borderColor.match(/[0-9.]+/g).map(Number));
 assert(edge[0]>edge[1]*2&&edge[0]>edge[2]*2,'The glass rim should glow red');
 await animated.screenshot({path:shots+'/hero-ready.png'});
 // Readers can start before the writing finishes; no animation may gate entry.
 await animated.evaluate(()=>{void Showcase.replayOpening();});
 await animated.waitForFunction(()=>document.querySelector('#launch-screen')?.open&&document.body.classList.contains('is-launch-open'));
 await animatedCTA.click();await animated.waitForFunction(()=>location.hash==='#vision'&&!document.body.classList.contains('is-launch-open'));
 await ready(animated);
 assert.equal(await animatedLaunch.locator('#hero-art').getAttribute('data-phase'),'ready');
 const animatedMethod=animated.locator('[data-hx-motion="method"]');await animatedMethod.scrollIntoViewIfNeeded();
 const animatedMethodButtons=animatedMethod.locator('[data-hx-method]');await animatedMethodButtons.nth(2).click();
 assert.equal(await animatedMethodButtons.nth(2).getAttribute('aria-pressed'),'true');
 await animated.waitForTimeout(3400);assert.equal(await animatedMethod.getAttribute('data-hx-stage'),'2','A manual method selection should stop automatic rotation');
 // Markers must remain on the polygon during interpolation and keep their DOM identity.
 const animatedAbility=animated.locator('[data-hx-motion="ability"]');await animatedAbility.scrollIntoViewIfNeeded();
 await animated.waitForFunction(()=>document.querySelector('[data-hx-motion="ability"]').classList.contains('is-hx-visible'));
 await animatedAbility.evaluate(n=>{window.__firstRadarDot=n.querySelector('[data-hx-dot-dimension="0"]');});
 await animatedAbility.locator('[data-hx-profile-button="b"]').click();
 const morphSamples=await animatedAbility.evaluate(async n=>{
  const rows=[];
  for(let i=0;i<8;i++){
   await new Promise(requestAnimationFrame);
   const shape=n.querySelector('[data-hx-radar-shape]').getAttribute('points').trim().split(/\s+/).map(p=>p.split(',').map(Number));
   const dots=[...n.querySelectorAll('[data-hx-dot-dimension]')].map(dot=>[Number(dot.getAttribute('cx')),Number(dot.getAttribute('cy'))]);
   rows.push({points:shape,delta:Math.max(...shape.flatMap((point,j)=>point.map((v,k)=>Math.abs(v-dots[j][k]))))});
  }
  return {rows,sameNode:window.__firstRadarDot===n.querySelector('[data-hx-dot-dimension="0"]')};
 });
 assert(morphSamples.sameNode,'Morphing must not replace a focused marker node');
 assert(morphSamples.rows.every(row=>row.delta<.02),'Radar markers detached during morph: '+JSON.stringify(morphSamples));
 assert(morphSamples.rows.every(row=>row.points[0][1]===139),'Radar geometry should switch once while opacity crossfades');
 assert.equal(await animated.locator('[data-hx-motion-toggle]').count(),0,'The requested design has no pause buttons');
 const motionTime=animated.locator('[data-hx-motion="time"]');await motionTime.scrollIntoViewIfNeeded();
 await animated.waitForFunction(()=>getComputedStyle(document.querySelector('.hx-time-cursor')).animationPlayState==='running');
 const evolving=animated.locator('[data-hx-motion="evolution"]');await evolving.scrollIntoViewIfNeeded();
 const stage=await evolving.getAttribute('data-hx-stage');await animated.waitForFunction(old=>document.querySelector('[data-hx-motion="evolution"]').dataset.hxStage!==old,stage,{timeout:6500});
 await animated.emulateMedia({reducedMotion:'reduce'});const reducedStage=await evolving.getAttribute('data-hx-stage');await animated.waitForTimeout(3250);assert.equal(await evolving.getAttribute('data-hx-stage'),reducedStage);
 assert.equal(await motionTime.locator('.hx-time-cursor').evaluate(n=>getComputedStyle(n).animationName),'none');
 await animated.emulateMedia({reducedMotion:'no-preference'});
 await animated.locator('#terms').evaluate(n=>scrollTo({top:ShowcaseTransitions.measureTopic(n).top+scrollY+ n.querySelector('.topic-heading').offsetTop-innerHeight*1.3,behavior:'instant'}));
 await animated.waitForTimeout(1500);
 await animated.locator('#terms').evaluate(n=>scrollTo({top:ShowcaseTransitions.measureTopic(n).top+scrollY+n.querySelector('.topic-heading').offsetTop-innerHeight*.82,behavior:'instant'}));
 await animated.waitForFunction(()=>document.querySelector('#terms').dataset.arrivalState==='arriving'&&Number(document.querySelector('#terms').dataset.arrivalTarget)>.4);
 assert.equal(await animated.locator('#terms').getAttribute('data-arrival-from'),'highlights','The whole-topic reveal should be linked to the preceding handoff');
 const arrivalMotion=await animated.locator('#terms').evaluate(n=>({progress:Number(n.dataset.arrivalProgress),target:Number(n.dataset.arrivalTarget),transform:getComputedStyle(n).transform}));
 assert(arrivalMotion.progress<arrivalMotion.target-.03,'The chapter surface should lag behind its scroll target: '+JSON.stringify(arrivalMotion));
 assert.match(arrivalMotion.transform,/^matrix3d\(/,'The complete chapter should use a perspective transform');
 const panelDepth=await animated.locator('#terms').evaluate(n=>({depth:parseFloat(n.style.getPropertyValue('--topic-arrival-depth')),tilt:parseFloat(n.style.getPropertyValue('--topic-arrival-tilt')),heading:getComputedStyle(n.querySelector('.topic-heading')).transform,unit:getComputedStyle(n.querySelector('.topic-unit')).transform}));
 assert(panelDepth.depth<0&&panelDepth.tilt<0,'The incoming panel should pull forward from a recessed tilted plane: '+JSON.stringify(panelDepth));
 assert.equal(panelDepth.heading,'none');assert.equal(panelDepth.unit,'none','The card should move as a whole, without individual content transforms');
 assert(Number(await animated.locator('#highlights .chapter-bridge').getAttribute('data-handoff-progress'))>=.8);
 await animated.screenshot({path:shots+'/topic-arrival.png'});
 await animated.waitForTimeout(1300);
 const settledArrival=await animated.locator('#terms').evaluate(n=>({state:n.dataset.arrivalState,progress:Number(n.dataset.arrivalProgress),target:Number(n.dataset.arrivalTarget)}));
 assert.equal(settledArrival.state,'arriving','A paused reader should not finish the remaining entrance');
 assert(settledArrival.target<1&&Math.abs(settledArrival.progress-settledArrival.target)<.01,'The paused chapter should settle at its partial scroll target: '+JSON.stringify(settledArrival));
 await animated.locator('#terms').evaluate(n=>scrollTo({top:ShowcaseTransitions.measureTopic(n).top+scrollY+n.querySelector('.topic-heading').offsetTop-innerHeight*.48,behavior:'instant'}));
 await animated.waitForFunction(()=>document.querySelector('#terms').dataset.arrivalState==='complete');
 assert.equal(await animated.locator('#terms').evaluate(n=>getComputedStyle(n).opacity),'1');
 assert.equal(await animated.locator('#terms').getAttribute('data-arrival-progress'),'1');
 assert.deepEqual(await animated.locator('.chapter-bridge.has-handoff').evaluateAll(nodes=>nodes.map(n=>n.closest('[data-chapter]').id)),chapters.slice(0,-1),'All eleven structured handoffs must be enhanced; the closing invitation is a separate link');
 const handoff=animated.locator('#single .chapter-bridge');
 await handoff.evaluate(n=>scrollTo({top:n.getBoundingClientRect().top+scrollY-innerHeight*.88,behavior:'instant'}));
 await animated.waitForFunction(()=>Number(document.querySelector('#single .chapter-bridge').dataset.handoffProgress)>0);
 assert(Number(await handoff.getAttribute('data-handoff-progress'))>0,'The visible handoff should make progress');
 assert(await handoff.evaluate(n=>n.classList.contains('is-playing')),'Entering the handoff should start a visible transfer');
 await animated.screenshot({path:shots+'/transition-in-motion.png'});
 await handoff.evaluate(n=>scrollTo({top:n.getBoundingClientRect().top+scrollY-innerHeight*.5,behavior:'instant'}));
 // Geometry or elapsed time can already put early progress at 1; require the
 // actual delivered state and completed stroke rather than an impossible +0.15.
 await animated.waitForFunction(()=>{
  const bridge=document.querySelector('#single .chapter-bridge'),line=bridge.querySelector('.handoff-line-motion');
  return bridge.classList.contains('is-delivered')&&Number(bridge.dataset.handoffProgress)>=.8&&Math.abs(Number.parseFloat(getComputedStyle(line).strokeDashoffset))<.02;
 });
 assert(await handoff.evaluate(n=>n.classList.contains('is-delivered')),'The handoff should arrive by the viewport midpoint, before the reader passes it');
 assert(Number.parseFloat(await animated.locator('#single .handoff-line-motion').evaluate(n=>getComputedStyle(n).strokeDashoffset))<1);
 await animated.screenshot({path:shots+'/chapter-transition.png'});
 for(const width of [1440,390]){
  await animated.setViewportSize({width,height:950});
  for(const id of chapters.slice(0,-1)){
   await animated.locator('#'+id+' .chapter-bridge').evaluate(n=>scrollTo({top:n.getBoundingClientRect().top+scrollY-innerHeight*.5,behavior:'instant'}));
   await animated.waitForFunction(id=>document.querySelector('#'+id+' .chapter-bridge').classList.contains('is-delivered'),id);
   assert.equal(await animated.locator('#'+id).evaluate(n=>getComputedStyle(n).opacity),'1','A deep-linked or passed topic must remain readable');
   await fit(animated,'handoff '+id+' '+width);
  }
 }
 await animated.setViewportSize({width:1440,height:950});
 const closingInvitation=animated.locator('.chapter-transition-closing');
 assert.equal(await closingInvitation.count(),1);
 assert.equal(await closingInvitation.getAttribute('href'),'#vision');
 await closingInvitation.focus();await animated.keyboard.press('Enter');
 await animated.waitForFunction(()=>location.hash==='#vision'&&document.querySelector('#heading-vision').getBoundingClientRect().top>=0&&document.querySelector('#heading-vision').getBoundingClientRect().top<innerHeight/2);
 await animated.screenshot({path:shots+'/closing-return.png'});
 await animated.locator('.primary-nav a[href="#terms"]').click();
 await animated.waitForFunction(()=>location.hash==='#terms');
 await animated.screenshot({path:shots+'/chapter-navigation.png'});
 assert.equal(await animated.locator('.chapter-transit-overlay').count(),0,'Topic navigation should use natural scrolling without a blocking overlay');
 await checkAudits(motion);await motion.close();
 const recorded=records.cases.reduce((n,c)=>n+['basic','same_information','system'].filter(k=>c[k]?.status==='recorded').length,0);
 console.log(JSON.stringify({ok:true,mode:allowExcludedIcon404?'diagnostic_excluding_icons':'strict',excludedIcon404:[...excludedIcon404.values()],topics:12,contentUnits:13,highlights:7,nationalQuestions:2,savedPipelineRuns:8,diagnosticInputs:6,recordedResponses:recorded,conditions:2,viewports:[1440,1100,1099,980,768,390,320],resizableLanes:true,allTopicHandoffs:true,noJavaScript:true,visionGalaxies:true,visionDialogs:63,mobileCamera:true,wholePanel3D:true,network:'same-origin GET only, no cookies',screenshots:shots}));
}catch(error){
 if(lastPage&&!lastPage.isClosed()){
  await lastPage.screenshot({path:shots+'/failure.png'}).catch(()=>{});
  const checkpoint=await lastPage.evaluate(()=>({url:location.href,focus:{id:document.activeElement?.id,tag:document.activeElement?.tagName,text:document.activeElement?.textContent?.slice(0,100)}})).catch(()=>null);
  console.error('Browser checkpoint: '+JSON.stringify(checkpoint));
 }
 throw error;
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
