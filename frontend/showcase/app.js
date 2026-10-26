/* Reviewed research chapters, actual saved outputs, local diagram state. */
(function(){
'use strict';
const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
const state={data:null,pipelineData:null,recordings:null,view:'vision',perspective:'teaching',teacher:'xuefeng',example:'national-2023-q17',mode:'solution',caseIndex:0,condition:'basic',sceneTabs:{},teachingIndex:0,geometryStage:0,timestampEvent:0,routineHidden:false,completeMode:true,loadError:null};
const api=window.Showcase={state,ready:null};
const annotations=new Map();let annotationSequence=0,annotationTrigger=null;
const teachers={liangliang:'梁梁',taotao:'韬韬',xuefeng:'雪峰',ji:'鸡'};
const modelPricing={
 'glm-4.7-flash':{tier:'免费',rates:'官方价目：免费',url:'https://docs.bigmodel.cn/cn/guide/start/pricing'},
 'deepseek-flash':{tier:'便宜',rates:'¥1–2 / 百万输入 Token；¥4–8 / 百万输出 Token',url:'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'},
 'glm-5.3-flash':{tier:'便宜',rates:'¥0.8 / 百万输入 Token；¥2.8 / 百万输出 Token',url:'https://docs.bigmodel.cn/cn/guide/start/pricing'},
 'gpt-6-astra':{tier:'昂贵',rates:'$10 / 百万输入 Token；$50 / 百万输出 Token',url:'https://developers.openai.com/api/docs/models/gpt-6-astra'}
};
const USD_TO_CNY=6.67;
const singleModes={solution:'solution',grading:'grading',teaching:'teaching',generation:'generation',geometry:'geometry'};
const perspectives=['teaching','technical'];
const aliases={overview:'highlights',dataset:'highlights',concepts:'terms',diagnosis:'time',routines:'library',career:'longterm',modes:'school',mcp:'agent',solution:'single',grading:'single',teaching:'single',generation:'single',geometry:'single',graph:'library',pool:'library',progress:'evolution',research:'evolution'};
// This tab stores only public presentation choices and a reading position.
const readingKey='studyagent.showcase.reading.v1',initialHash=location.hash;
let savedReading=null,entered=false,uiReady=false,saveTimer,topicFrame=0;
try{const raw=sessionStorage.getItem(readingKey);if(raw&&raw.length<32768){const value=JSON.parse(raw);if([1,2].includes(value?.version)&&typeof value==='object'&&!Array.isArray(value))savedReading=value;}}catch{}
entered=savedReading?.entered===true;
const navigationType=performance.getEntriesByType('navigation')[0]?.type;
const resumeReading=Boolean(savedReading&&['reload','back_forward'].includes(navigationType)&&savedReading.path===location.pathname&&savedReading.hash===initialHash);
if(resumeReading){
 if('scrollRestoration'in history)history.scrollRestoration='manual';
 // Rebuilding the saved workbenches must not also trigger browser scroll anchoring.
 document.documentElement.style.overflowAnchor='none';
}
const requestedPerspectiveRaw=new URLSearchParams(location.search).get('perspective');
const requestedPerspective=requestedPerspectiveRaw==='mechanism'?'technical':requestedPerspectiveRaw;
if(perspectives.includes(requestedPerspective))state.perspective=requestedPerspective;
const initialAnchor=initialHash.slice(1);
const initialTopic=$(initialAnchor)?.closest('[data-chapter]')?.id||aliases[initialAnchor]||initialAnchor;
if(initialTopic&&document.getElementById(initialTopic))state.view=initialTopic;
document.body.dataset.currentTopic=document.getElementById(initialTopic)?.matches('[data-chapter]')?initialTopic:'vision';
function indexValue(value,max,fallback=0){return Number.isInteger(value)&&value>=0&&value<max?value:fallback;}
function restoreChoices(){
 if(!resumeReading)return;
 const choice=savedReading.choices||{};
 const savedPerspective=choice.perspective==='mechanism'?'technical':choice.perspective;
 if(!requestedPerspective&&perspectives.includes(savedPerspective))state.perspective=savedPerspective;
 if(Object.hasOwn(teachers,choice.teacher))state.teacher=choice.teacher;
 if(state.data.examples.some(row=>row.id===choice.example))state.example=choice.example;
 if(Object.hasOwn(singleModes,choice.mode))state.mode=choice.mode;
 state.caseIndex=indexValue(choice.caseIndex,state.recordings?.cases?.length||0);
 if(['basic','same_information'].includes(choice.condition))state.condition=choice.condition;
 state.teachingIndex=indexValue(choice.teachingIndex,state.recordings?.teaching?.frames?.length||0);
 state.geometryStage=indexValue(choice.geometryStage,3);state.timestampEvent=indexValue(choice.timestampEvent,4);
 state.routineHidden=choice.routineHidden===true;state.completeMode=choice.completeMode!==false;
 if(choice.sceneTabs&&typeof choice.sceneTabs==='object'&&!Array.isArray(choice.sceneTabs))for(const id of ['routines','exam','career','agent','teacher','school','mcp','evolution'])state.sceneTabs[id]=indexValue(choice.sceneTabs[id],10);
 setPerspective(state.perspective,false);
}
function readingChapter(){
 const chapters=[...document.querySelectorAll('[data-chapter]')],root=getComputedStyle(document.body);
 const line=Math.max(Number.parseFloat(root.getPropertyValue('--header'))+Number.parseFloat(root.getPropertyValue('--perspective-bar'))+24,innerHeight*.3);
 return chapters.filter(node=>(window.ShowcaseTransitions?.measureTopic(node)?.top??node.getBoundingClientRect().top)<=line).at(-1)||chapters[0];
}
function saveReading(){
 if(!uiReady||!entered||document.body.classList.contains('is-launch-open'))return;
 const chapter=readingChapter();
 document.body.dataset.currentTopic=chapter?.id||'vision';
 const record={version:2,entered:true,path:location.pathname,hash:location.hash,position:{topic:chapter?.id||'vision',offset:chapter?-(window.ShowcaseTransitions?.measureTopic(chapter)?.top??chapter.getBoundingClientRect().top):0,y:scrollY},choices:{perspective:state.perspective,teacher:state.teacher,example:state.example,mode:state.mode,caseIndex:state.caseIndex,condition:state.condition,sceneTabs:state.sceneTabs,teachingIndex:state.teachingIndex,geometryStage:state.geometryStage,timestampEvent:state.timestampEvent,routineHidden:state.routineHidden,completeMode:state.completeMode},bank:window.ShowcaseBank?.snapshot?.()};
 try{sessionStorage.setItem(readingKey,JSON.stringify(record));}catch{}
}
function scheduleReadingSave(){clearTimeout(saveTimer);if(uiReady)saveTimer=setTimeout(saveReading,160);}
function syncCurrentTopic(){if(topicFrame)return;topicFrame=requestAnimationFrame(()=>{topicFrame=0;document.body.dataset.currentTopic=readingChapter()?.id||'vision';});}
async function restoreReadingPosition(){
 if(document.fonts)await document.fonts.ready;
 await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 if(resumeReading&&initialHash===location.hash){
  const position=savedReading.position||{},savedTopic=position.topic||aliases[position.chapter]||position.chapter,chapter=typeof savedTopic==='string'?$(savedTopic):null;
  const top=chapter?.matches('[data-chapter]')&&Number.isFinite(position.offset)?(window.ShowcaseTransitions?.measureTopic(chapter)?.top??chapter.getBoundingClientRect().top)+scrollY+position.offset:Number.isFinite(position.y)?position.y:0;
  scrollTo({top:Math.max(0,Math.min(top,document.documentElement.scrollHeight-innerHeight)),behavior:'instant'});
 }else if(!resumeReading&&initialHash&&initialHash===location.hash){
  // Native fragment positioning ran before saved math and diagrams filled their containers.
  ($(initialHash.slice(1))||$(aliases[initialHash.slice(1)]))?.scrollIntoView({behavior:'instant',block:'start'});
 }
 await new Promise(resolve=>requestAnimationFrame(resolve));
 document.documentElement.style.removeProperty('overflow-anchor');
 uiReady=true;dispatchEvent(new CustomEvent('showcase:reading-ready'));saveReading();
}
api.readingKey=readingKey;
api.saveReading=saveReading;
api.clearReadingState=()=>{entered=false;uiReady=false;clearTimeout(saveTimer);window.ShowcaseVision?.reset();try{sessionStorage.removeItem(readingKey);}catch{}};
addEventListener('scroll',()=>{syncCurrentTopic();scheduleReadingSave();},{passive:true});addEventListener('resize',syncCurrentTopic,{passive:true});addEventListener('pagehide',saveReading);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')saveReading();});
for(const event of ['click','change','input'])document.addEventListener(event,scheduleReadingSave);
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=String(text);return n;}
function setPerspective(name,updateUrl=true){if(name==='mechanism')name='technical';if(!perspectives.includes(name))return;state.perspective=name;document.body.classList.add('reader-ready');document.body.dataset.activePerspective=name;document.querySelectorAll('[data-perspective-cell]').forEach(node=>node.dataset.current=String(node.dataset.perspectiveCell===name));document.querySelectorAll('[data-perspective]').forEach(node=>{node.setAttribute('aria-selected',String(node.dataset.perspective===name));node.tabIndex=node.dataset.perspective===name?0:-1;});if(updateUrl){const url=new URL(location.href);url.searchParams.set('perspective',name);history.replaceState(history.state,'',url);}scheduleReadingSave();}
// Decode a uniform extra JSON-escape layer only in the presentation. Saved raw text stays intact.
function presentationText(text){const source=String(text||'');if(/\\\\(?:triangle|sin|cos|tan|pi|frac|sqrt|begin|end|left|right|quad|cdot|gt|lt)\b/.test(source)&&!/(?<!\\)\\(?:triangle|sin|cos|tan|pi|frac|sqrt|begin|end|left|right|quad|cdot|gt|lt)\b/.test(source))return source.replace(/\\\\/g,'\\').replace(/\\n(?![A-Za-z])/g,'\n');return source;}
function math(node,text){const source=presentationText(text),re=/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]/g;let end=0;for(const m of source.matchAll(re)){node.append(document.createTextNode(source.slice(end,m.index)));const block=m[0].startsWith('$$')||m[0].startsWith('\\['),size=m[0].startsWith('$')&&!block?1:2,n=el('span',block?'math-display':'math-inline');node.append(n);if(window.katex)katex.render(m[0].slice(size,-size),n,{displayMode:block,throwOnError:false,trust:false,strict:'ignore'});else n.textContent=m[0];end=m.index+m[0].length;}node.append(document.createTextNode(source.slice(end)));return node;}
const p=(text,cls)=>math(el('p',cls),text),note=text=>p(Array.isArray(text)?text.join(' '):text,'scene-note');
function button(text,fn,cls=''){const n=el('button',cls,text);n.type='button';n.onclick=fn;return n;}
function details(title,content,cls=''){const n=el('div','contextual-note '+cls),id=String(++annotationSequence),b=button(title,null,'annotation-button'),source=el('div','annotation-source');b.dataset.annotation=id;b.setAttribute('aria-controls','annotation-panel');source.hidden=true;source.append(content);n.append(b,source);annotations.set(id,{title,content});return n;}
function openAnnotation(id,trigger){const value=annotations.get(id);if(!value)return;annotationTrigger=trigger;$('annotation-title').textContent=value.title;$('annotation-body').replaceChildren(value.content.cloneNode(true));$('annotation-panel').hidden=false;$('annotation-close').focus();}
function closeAnnotation(){$('annotation-panel').hidden=true;if(annotationTrigger?.isConnected)annotationTrigger.focus();}
function bar(title,subtitle){const n=el('div','workbench-bar');n.append(el('strong','',title));if(subtitle)n.append(el('span','',subtitle));return n;}
function tabs(rows,active,change,label='切换图解'){const n=el('div','scene-tabs');n.setAttribute('role','group');n.setAttribute('aria-label',label);rows.forEach(([id,title])=>{const b=button(title,()=>change(id));b.setAttribute('aria-pressed',String(id===active));n.append(b);});return n;}
function flow(root,labels,active=0){const n=el('div','flow-strip');labels.forEach((t,i)=>{const b=el('button',i===active?'active':'',t);b.type='button';b.addEventListener('click',()=>{n.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');});n.append(b);});root.append(n);return n;}
function selectView(name){const id=aliases[name]||name;if(!$(id))return;recordOrigin(id);dispatchEvent(new CustomEvent('showcase:navigate',{detail:{from:state.view,to:id}}));state.view=id;if(singleModes[name]){state.mode=singleModes[name];renderSingle();}const url=new URL(location.href);url.hash=id;history.pushState(history.state,'',url);$(id)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});}
api.selectView=selectView;api.focusRoutine=id=>{const r=state.data?.catalog?.routines.find(x=>x.id===id);if(r)$('routine-selection').textContent=r.name;};
function svg(tag,attrs,text){const n=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,String(v)));if(text!=null)n.textContent=text;return n;}
function triangle(stage=0){const s=svg('svg',{viewBox:'0 0 440 390',role:'img','aria-label':'全国卷三角形 ABC，AB长5，高为6，辅助线由步骤控制',class:'triangle-figure'});s.append(svg('path',{d:'M90 330 L340 330 L190 30 Z',fill:'#151515',stroke:'#aaa','stroke-width':2.5}));if(stage>=1)s.append(svg('path',{d:'M190 30 V330 M190 316 H204 V330',fill:'none',stroke:'#bbb','stroke-width':2,'stroke-dasharray':'6 5',class:'construction-line'}));[['A',72,352],['B',348,352],['C',185,20],['AB = 5',180,370],['C = π/4',212,85]].forEach(([t,x,y])=>s.append(svg('text',{x,y},t)));if(stage>=1){s.append(svg('text',{x:174,y:351},'D'));s.append(svg('text',{x:204,y:195,fill:'#ddd'},stage>=2?'h = 6':'h'));}if(stage>=2)s.append(svg('text',{x:36,y:184,transform:'rotate(-72 36 184)'},'AC = 2√10'));return s;}
function handwriting(text){if(window.ShowcaseHandwriting)return window.ShowcaseHandwriting.render(text);const source=String(text||''),paper=el('div','handwriting-sheet'),ink=el('div','paper-ink'),re=/_\(([^)]+)\)|_([A-Za-z0-9]+)|\^\(([^)]+)\)|\^([A-Za-z0-9]+)/g;paper.dataset.source=source;let end=0;for(const m of source.matchAll(re)){ink.append(document.createTextNode(source.slice(end,m.index)));ink.append(el(m[1]||m[2]?'sub':'sup','',m[1]||m[2]||m[3]||m[4]));end=m.index+m[0].length;}ink.append(document.createTextNode(source.slice(end)));paper.append(ink);return paper;}
function renderConcepts(){
 const root=$('scene-concepts'),rows=[['课时','教学内容的组织单位','课时讲授知识点，按前置安排；与知识点不要求一一对应。','三角恒等变换、正弦定理分布在相应教学课时中。'],['知识点','知识理解与运用的评价对象','知识点支撑步骤；一次套路通过不证明全部知识理解。','三角形内角和、两角和差公式、正弦定理与面积。'],['步骤','可以引用和分析的操作','可复用操作与本题实例分开，兼容不同正确解法。','由角关系求 $C$；三角恒等变换；求边长；将面积转为高。'],['套路','适用条件与步骤组合','保存触发条件、关键步骤、排除条件和易混淆方法。','解三角形：先确定角的关系，再联系边长、面积与目标。']];let active=0;
 const draw=()=>{const chain=el('div','concept-chain');chain.setAttribute('aria-label','课时、知识点、步骤与套路的关系');rows.forEach((row,index)=>{const b=button('',()=>{active=index;draw();},'concept-node');b.append(el('strong','',row[0]),el('span','',['教什么','理解什么','怎样操作','怎样组合'][index]));b.setAttribute('aria-pressed',String(index===active));chain.append(b);if(index<3)chain.append(el('span','concept-edge',['讲授','支撑','组合'][index]));});root.replaceChildren(bar('一份共同表示，贯穿不同功能','点选查看全国卷中的对应关系'),chain);const row=rows[active],d=el('div','concept-explanation');d.append(el('h3','',row[1]),p(row[2]),p(row[3],'example-line'));root.append(d);};draw();
}
function richMath(node,text){const source=String(text||''),re=/\*\*([\s\S]+?)\*\*/g;let end=0;for(const match of source.matchAll(re)){math(node,source.slice(end,match.index));const strong=el('strong');math(strong,match[1]);node.append(strong);end=match.index+match[0].length;}return math(node,source.slice(end));}
function readableAnswer(content){const wrap=el('div','record-rendered');for(const text of content.split(/\n\s*\n/)){const source=text.trim();if(!source)continue;let node;if(/^#{1,4}\s/.test(source)){node=el('h5');richMath(node,source.replace(/^#{1,4}\s+/,''));}else if(/^>/.test(source)){node=el('blockquote');richMath(node,source.replace(/^>\s?/gm,''));}else if(source.split('\n').every(line=>/^[-*]\s/.test(line))){node=el('ul');for(const line of source.split('\n'))node.append(richMath(el('li'),line.replace(/^[-*]\s+/,'')));}else{node=richMath(el('p'),source);}wrap.append(node);}return wrap;}
function renderGradeEvidence(block,s){
 if(!s||Array.isArray(s)||typeof s!=='object')return;
 const overall=el('div','grade-overview');if(s.feedback)overall.append(p(s.feedback,'grade-feedback'));
 const verdict=s.is_correct===true?'答案判为正确':s.is_correct===false?'答案判为不正确':'答案结论暂未确定';
 const labels=[['is_correct',verdict],['grading_confidence','判断置信度：'+(s.grading_confidence||'未提供')],['review_required',s.review_required?'建议人工复核':'未标记人工复核']];
 for(const [key,label]of labels)if(s[key]!==undefined)overall.append(el('span','grade-tag'+(key==='is_correct'?' grade-'+(s.is_correct===true?'correct':s.is_correct===false?'incorrect':'unknown'):''),label));
 if(overall.childNodes.length)block.append(overall);
 for(const step of s.step_results||[]){
  const card=el('article','grade-step'),status={correct:'通过',partial:'部分正确',incorrect:'存在错误',missing:'未出现',unknown:'暂不能判断'}[step.status]||step.status||'未标记';
  card.append(el('span','step-number',step.step_number===999?'最终答案':'步骤 '+step.step_number),el('h5','',step.title||'作答步骤'),el('span','grade-tag','系统状态：'+status));
  if(step.comment)card.append(p(step.comment));
  if(step.answer_evidence)card.append(math(el('blockquote','answer-evidence'),step.answer_evidence));
  if(step.error_detail)card.append(p('错误说明：'+step.error_detail,'error-detail'));
  if(step.cause_confidence)card.append(p('原因置信度：'+step.cause_confidence,'cause-confidence'));
  if(step.review_required)card.append(p('该项标记为需要人工复核。','review-flag'));
  block.append(card);
 }
 if(s.missing_steps?.length)block.append(details('未覆盖的步骤',p(s.missing_steps.map(x=>typeof x==='string'?x:JSON.stringify(x)).join('\n'))));
}
function rawOutput(record,title){const block=el('section','record-output');block.append(el('h4','',title));if(!record||record.status!=='recorded'){block.append(p(record?.error||'尚未取得此场景的真实运行记录。','pending-output'));return block;}const summary=record.structured?.overall?.feedback||record.structured?.feedback;if(summary&&!record.structured?.step_results)block.append(p(summary));const content=typeof record.content==='string'?record.content:JSON.stringify(record.content??record.structured,null,2);if(record.structured?.step_results)renderGradeEvidence(block,record.structured);else block.append(readableAnswer(content));block.append(details('完整模型原文（未改写）',el('pre','record-text',content),'original-response'));const meta=el('div','record-metadata');for(const [k,label]of [['model','模型'],['recorded_at','记录时间'],['input_sha256','输入摘要'],['response_sha256','结果摘要']])meta.append(p(label+'：'+(record[k]||'见运行来源')));if(record.config)meta.append(details('模型与运行配置',el('pre','raw-output',JSON.stringify(record.config,null,2))));if(record.prompt)meta.append(details('实际请求提示词',el('pre','raw-output',record.prompt)));if(record.calls)meta.append(details('本次实际请求与返回记录',el('pre','raw-output',JSON.stringify(record.calls,null,2))));block.append(details('运行配置与摘要校验',meta));return block;}
function renderSolution(root){
 const run=state.pipelineData?.examples?.[state.example]?.[state.teacher];if(!run){root.append(note('解析记录正在准备。'));return;}
 const answer=run.answer_json,example=state.data.examples.find(e=>e.id===state.example);root.append(bar('三阶段解题 → 一份结构化参考',teachers[state.teacher]+' · '+(run.stages?.solver?.model||'已保存解析')),p(example.question,'sample-question'));
 const pipeline=el('div','pipeline-map');for(const [i,key,title]of [[0,'solver','Solver · 完整解题'],[1,'verifier','Verifier · 校验与分步'],[2,'formatter','Formatter · 结构与难度']]){const record=run.stages?.[key]||{},body=el('div');body.append(p((record.model||'模型未记录')+' · '+(record.provider==='codex_cli'?'Codex CLI · ':'')+'推理 '+(record.reasoning_effort||'默认')),el('pre','raw-output',record.content||'无记录'));pipeline.append(details(title,body,'pipeline-stage'));if(i<2)pipeline.append(el('span','pipeline-arrow','→'));}root.append(pipeline);
 for(const c of answer.chunk_results||[]){const block=el('section','chunk');block.append(el('h3','','第 '+c.chunk_id+' 问'));for(const step of c.steps||[]){const card=el('article','step');card.append(el('span','step-number','步骤 '+step.step_number),el('h4','',step.title),p(step.standard_writing));if(step.detailed_writing)card.append(details('详细过程',p(step.detailed_writing)));if(step.step_difficulty?.dimensions&&window.renderDimBarsHtml){const d=el('div','dim-chart');d.innerHTML=renderDimBarsHtml(step.step_difficulty.dimensions);card.append(details('本步难度维度',d));}if(step.knowledge_point)card.append(p(step.knowledge_point,'step-kp'));block.append(card);}root.append(block);}
 root.append(apiCostSummary(run));
 const meta=el('div');meta.append(p('运行时间：'+run.run_at),el('pre','raw-output',JSON.stringify({teacher:state.teacher,recorded_at:run.run_at,execution_origin:run.execution_origin,source_commit:run.source_commit,models:Object.fromEntries(Object.entries(run.stages||{}).map(([key,value])=>[key,{model:value.model,resolved_model:value.resolved_model,provider:value.provider,reasoning_effort:value.reasoning_effort}])),fingerprint:run.fingerprint},null,2)));root.append(details('本次解析的运行信息',meta));
}
function apiCostSummary(run){
 const stages=Object.values(run.stages||{}),usages=stages.map(stage=>stage.usage).filter(Boolean),aggregate=run.answer_json?.token_usage||{};
 const input=usages.length?usages.reduce((sum,u)=>sum+(u.prompt_tokens||0),0):(aggregate.prompt_tokens||0),output=usages.length?usages.reduce((sum,u)=>sum+(u.completion_tokens||0),0):(aggregate.completion_tokens||0),cached=Math.min(input,Math.max(0,usages.reduce((sum,u)=>sum+(u.prompt_tokens_details?.cached_tokens??u.prompt_cache_hit_tokens??0),0))),model=run.stages?.solver?.model||'',provider=run.stages?.solver?.provider||'',profile=modelPricing[model];
 if(!input&&!output)return note('本次记录没有可核对的 token 用量，暂不估算 API 成本。');
 let amount=0,currency='CNY',basis='按该模型公开标准价估算';
 if(model==='deepseek-flash'){
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Shanghai',weekday:'short',hour:'numeric',hourCycle:'h23'}).formatToParts(new Date(run.run_at||Date.now())),weekday=parts.find(x=>x.type==='weekday')?.value||'',hour=Number(parts.find(x=>x.type==='hour')?.value||0),peak=['Mon','Tue','Wed','Thu','Fri'].includes(weekday)&&((hour>=9&&hour<12)||(hour>=14&&hour<18)),inputRate=peak?2:1,cachedRate=peak ? .04 : .02,outputRate=peak?8:4;
  amount=((input-cached)*inputRate+cached*cachedRate+output*outputRate)/1_000_000;basis='按该次保存时间对应的'+(peak?'高峰':'低峰')+'时段价估算';
 }else if(model==='glm-5.3-flash')amount=((input-cached)*.8+cached*.23+output*2.8)/1_000_000;
 else if(model==='gpt-6-astra'){currency='CNY';amount=(((input-cached)*10+cached*1+output*50)/1_000_000)*USD_TO_CNY;basis='按 OpenAI API 标准价折算；Codex CLI 执行记录不代表按此价实际扣款';}
 else if(model==='glm-4.7-flash'){amount=0;basis='该模型官方价目当前标为免费';}
 else return note('模型价格未配置，暂不估算本次 API 成本。');
 const panel=el('aside','api-cost-summary');panel.append(el('div','api-cost-heading','本次结构化解答的 API 成本估算'));
 const price=el('strong','api-cost-total',currency==='CNY'?'约 ¥'+amount.toFixed(2):'约 $'+amount.toFixed(4));panel.append(price);
 panel.append(el('p','api-cost-usage','三阶段合计：输入 '+input.toLocaleString()+' · 输出 '+output.toLocaleString()+(cached?' · 缓存命中输入 '+cached.toLocaleString():'')+' Token。'));
 const noteText='价目核对：2026-10-26。'+basis+'；计入三阶段保存用量与缓存命中。估算不等于历史账单，未含税费、缓存存储或供应商优惠。';panel.append(el('p','api-cost-caveat',noteText));
 const link=el('a','api-price-source','官方价格说明 ↗');link.href=profile?.url||'#';link.target='_blank';link.rel='noopener noreferrer';panel.append(link);
 if(model==='gpt-6-astra')panel.append(el('p','api-cost-caveat','折算假设：1 美元 ≈ '+USD_TO_CNY+' 元人民币。'));
 return panel;
}
function renderTeaching(frame){
 const t=state.recordings?.teaching;
 if(t?.status!=='recorded'||!t.frames?.length){frame.append(bar('逐步教学的工作方式','尚未完整录制'),p('围绕当前步骤提问，检查回答，再决定继续、提示或补充验证。'));flow(frame,['本步问题','学生回答','检查依据','继续或补充'],2);frame.append(note('本场景暂无完整真实录制，图解不作为模型输出。'));return;}
 let index=state.teachingIndex;const body=el('div');
 const draw=()=>{state.teachingIndex=index;body.replaceChildren();const f=t.frames[index];body.append(bar('教学过程保存状态',(index+1)+' / '+t.frames.length));if(f.input)body.append(handwriting(f.input));body.append(p(typeof f.output==='string'?f.output:JSON.stringify(f.output,null,2),'teacher-answer'));const ctl=el('div','replay-controls'),prev=button('上一步',()=>{index--;draw();}),next=button('下一状态',()=>{index++;draw();});prev.disabled=index===0;next.disabled=index===t.frames.length-1;ctl.append(prev,next);body.append(ctl,details('本状态完整原始输出',el('pre','raw-output',f.output)));};
 draw();frame.append(body,details('完整教学记录与运行配置',el('pre','raw-output',JSON.stringify(t,null,2))),note('固定输入的真实状态回放，包含错误回答、提示、部分完成及补充完整回答后的推进。'));
}
function renderGeneration(frame){
 const g=state.recordings?.generation;
 if(g?.status!=='recorded'){frame.append(bar('参考题与步骤约束','尚未完整录制'));flow(frame,['参考解析','步骤与错因','候选生成','重解校验','接受或拒绝'],3);frame.append(note('未取得真实结果前，不以手写题目代替实际生成输出。'));return;}
 const accepted=Number(g.structured?.accepted||0);frame.append(bar('依据全国卷参考题生成的变式',accepted?'当次候选通过解题检查':'当次候选未通过检查'));
 if(accepted){frame.append(p(g.question,'sample-question'));for(const c of g.answer_json?.chunk_results||[])for(const s of c.steps||[]){const card=el('article','step');card.append(el('h4','',s.title),p(s.standard_writing));if(s.detailed_writing)card.append(details('详细过程',p(s.detailed_writing)));frame.append(card);}}
 else for(const c of g.structured?.candidates||[])frame.append(p(c.question,'sample-question'),p(c.rejected_reason||'未取得通过的解析。'));
 frame.append(details('完整生成与三阶段校验记录',el('pre','raw-output',JSON.stringify(g,null,2))),note('原创变式，参考 2023 年新课标全国Ⅰ卷第17题的步骤结构。改变条件之后，重新求解并检查目标步骤。'));
}
function renderSingle(){
 const root=$('scene-single');if(!root||!state.data)return;
 root.replaceChildren(tabs([['solution','结构化解题'],['grading','步骤批改'],['teaching','教学过程'],['generation','针对性变式'],['geometry','辅助线与推理']],state.mode,id=>{state.mode=id;renderSingle();},'单题能力'));
 const frame=el('div','native-workbench single-workbench');root.append(frame);
 if(state.mode==='solution'){
  const controls=el('div','solution-controls'),label=el('label','','全国卷案例'),select=el('select');select.id='example-select';for(const e of state.data.examples)select.append(new Option(e.label||e.source?.paper||e.id,e.id));select.value=state.example;select.onchange=()=>{state.example=select.value;renderSingle();};label.append(select);
  const tl=el('label','','解题模型 / 运行记录'),ts=el('select');ts.id='teacher-select';for(const [k,n]of Object.entries(teachers)){const model=state.pipelineData?.examples?.[state.example]?.[k]?.stages?.solver?.model,profile=modelPricing[model];ts.append(new Option(n+(model?' · '+model+' · '+(profile?.tier||'价格待核') :''),k));}ts.value=state.teacher;ts.onchange=()=>{state.teacher=ts.value;renderSingle();};
  const currentModel=state.pipelineData?.examples?.[state.example]?.[state.teacher]?.stages?.solver?.model,profile=modelPricing[currentModel],modelNote=el('small','teacher-model-note');modelNote.append(document.createTextNode((currentModel||'模型未记录')+' · '+(profile?.tier||'价格待核')+(profile?' · '+profile.rates:'')));tl.append(ts,modelNote);controls.append(label,tl);frame.append(controls);renderSolution(frame);
 }else if(state.mode==='grading'){
  const c=state.recordings?.cases?.[0];if(c)frame.append(handwriting(c.student_answer),rawOutput(c.system,'正式批改流程实际输出'),button('比较不同诊断情境',()=>selectView('diagnosis')));else frame.append(note('真实批改记录尚未取得，不展示预制成功输出。'));
 }else if(state.mode==='teaching')renderTeaching(frame);
 else if(state.mode==='generation')renderGeneration(frame);
 else{
  let stage=state.geometryStage;const picture=el('div','geometry-demo'),caption=el('div');
  const draw=()=>{state.geometryStage=stage;picture.replaceChildren(triangle(stage));caption.replaceChildren(el('h3','',['先确定角与边的关系','作高 CD，连接目标与已知量','由面积关系得到高'][stage]),p(['由 $A+B=3C$ 与内角和，得 $C=\\pi/4$。','过 $C$ 作 $CD\\perp AB$，将目标转为直角三角形或面积关系中的高。','$AC=2\\sqrt{10}$，$\\sin A=3\\sqrt{10}/10$，故 $h=AC\\sin A=6$。'][stage]));};
  const ctl=tabs([['0','边角关系'],['1','显示辅助线'],['2','关联推导']],String(stage),id=>{stage=Number(id);draw();ctl.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===stage)));});draw();const layout=el('div','geometry-layout');layout.append(picture,caption);frame.append(ctl,layout,note('全国卷原题的确定性几何图解。'));
 }
}
function timestampDemo(){
 const card=el('section','timestamp-demo');card.append(bar('学生作答时间线','过程回放方案'));
 const events=[['首行作答','00:15',['A+B+C = π','C = π/3'],'可见事实：首行出现错误值。','待核实：角关系没有理解，还是联立时算错？'],['落笔间隔','01:00',['A+B+C = π','C = π/3'],'可见事实：这段时间没有新增笔画。','先查看后续作答，必要时追问这段时间在做什么。'],['继续推导','01:30',['A+B+C = π','C = π/3','B = 2π/3 − A'],'可见事实：后续推导沿用了先前的 C 值。','沿用错误前提时分别检查后续计算，再标记新出现的错误。'],['返回修改','01:50',['A+B+C = π','4C = π，C = π/4','B = 3π/4 − A'],'可见事实：返回前面的区域并改正了角关系。','记录这次修改是否获得提示，再用独立新题检查能否再次完成。']];
 let active=state.timestampEvent;const panel=el('div','timestamp-panel');
 const draw=()=>{state.timestampEvent=active;const event=events[active],sheet=svg('svg',{viewBox:'0 0 420 190',role:'img','aria-label':'学生书写中间状态',class:'timestamp-sheet'});for(let i=0;i<3;i++)sheet.append(svg('path',{d:'M20 '+(52+i*55)+' H400',stroke:'#dbe4ec','stroke-width':1}));event[2].forEach((text,i)=>sheet.append(svg('text',{x:30,y:40+i*55,fill:active===3&&i>0?'#006f72':'#172b43'},text)));const evidence=el('div','timestamp-evidence');evidence.append(el('span','small-label','示意相对时间 '+event[1]),p(event[3]),p(event[4],'scene-note'));panel.replaceChildren(sheet,evidence);};
 const ctl=tabs(events.map((e,i)=>[String(i),e[0]]),String(active),id=>{active=Number(id);draw();ctl.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===active)));},'学生笔迹事件');card.append(ctl,panel,note('沿时间回放书写、停顿、后续推导与返回修改，把最终卷面中消失的过程重新找回来。图中时刻用于说明回放方式。'));draw();return card;
}
function renderDiagnosis(){const root=$('scene-diagnosis'),cases=state.recordings?.cases||[];root.replaceChildren(bar('同题诊断：判断有没有落在作答依据上','六种情境 · 两种对照'));if(!cases.length){root.append(note('暂无录制记录，可先阅读本章的诊断机制与研究对照。'));return;}root.append(tabs(cases.map((c,i)=>[String(i),c.title]),String(state.caseIndex),id=>{state.caseIndex=Number(id);renderDiagnosis();},'诊断情境'));const c=cases[state.caseIndex],input=el('div','comparison-input');input.append(p(c.question,'comparison-question'),el('h3','','学生作答'),handwriting(c.student_answer));if(c.history?.length)input.append(details('可用历史与帮助记录',p(typeof c.history==='string'?c.history:JSON.stringify(c.history,null,2))));root.append(input,tabs([['basic','常见使用方式'],['same_information','同信息条件']],state.condition,id=>{state.condition=id;renderDiagnosis();},'对比条件'),note(state.condition==='basic'?'通用模型获得题目与作答；系统使用其正式工作流。输入和工具差异属于使用方式差异。':'同一基础模型与同样可用信息，比较通用提示词与系统工作流。具体输入和原始输出可核对。'));const grid=el('div','comparison-grid');grid.append(rawOutput(c[state.condition],state.condition==='basic'?'常规模型 · 题目与作答':'常规模型 · 相同可用信息'),rawOutput(c.system,'系统正式批改流程'));root.append(grid);const observation=el('div','observation-box');observation.append(el('h4','','这里重点比较什么'),p(c.observation||c.expected||'检查判断是否有原始作答依据。'));if(c.expected&&c.observation)observation.append(details('比较的判定方法',p(typeof c.expected==='string'?c.expected:JSON.stringify(c.expected,null,2))));root.append(observation,timestampDemo(),details('录制来源与比较边界',note(state.recordings.provenance?.notes||'少量案例用于解释机制，不构成准确率或教学效果结论。')));}
function scenario(id,title,labels,descs){const root=$('scene-'+id),body=el('div','scenario-detail');let active=indexValue(state.sceneTabs[id],labels.length);const draw=()=>{state.sceneTabs[id]=active;body.replaceChildren(el('h3','',labels[active]),p(descs[active]));};const ctl=tabs(labels.map((x,i)=>[String(i),x]),String(active),id=>{active=Number(id);draw();ctl.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===active)));});root.replaceChildren(bar(title,'方案图解'),ctl,body);draw();return root;}
function renderRoutines(){const root=scenario('routines','一个套路内部怎样练',['方法识别','母题学习','分步仿练','无提示重做','变式迁移','延迟复查'],['隐藏标签，解释从题设与目标如何选择方法。','理解步骤为什么成立，以及需要的前置知识。','观察局部卡点，允许回退补练。','记录帮助条件；原题重做与新题迁移分开。','条件变化后，重新核实方法的适用边界。','隔一段时间再做新题，记录是否仍能独立完成。']);const routes=el('div','route-pair');routes.append(el('div','route-line','套路顺序：前置准备 → 当前方法 → 后续方法'),el('div','route-line','知识准备：已有证据 → 局部缺口 → 补充后返回'));root.append(routes);let hidden=state.routineHidden;const label=el('p','method-label',hidden?'请自行判断采用的方法，并解释适用条件。':'方法提示：解三角形与面积关系'),toggle=button(hidden?'显示套路名称':'隐藏套路名称',()=>{hidden=!hidden;state.routineHidden=hidden;label.textContent=hidden?'请自行判断采用的方法，并解释适用条件。':'方法提示：解三角形与面积关系';toggle.textContent=hidden?'显示套路名称':'隐藏套路名称';toggle.setAttribute('aria-pressed',String(hidden));});toggle.setAttribute('aria-pressed',String(hidden));const selection=el('p','routine-selection','方法边界：是否具备边、角与目标之间的可用关系？');selection.id='routine-selection';root.append(toggle,label,selection,note('隐藏名称后，需要从题设和目标中自主选择方法，再解释适用条件。'));}
function renderExam(){
 const root=scenario('exam','一张卷，两个评价对象',['试卷质量','学生作答'],['对照模板，检查知识与套路覆盖、分值和难度安排是否符合本次教学目标。','结合失分步骤、分段用时和历史作答，列出待核实原因，再安排补测。']);
 const t=el('table');t.innerHTML='<caption>两道全国卷案例的考查内容示意</caption><thead><tr><th>全国卷案例</th><th>三角关系</th><th>面积转化</th><th>数列结构</th><th>导数与求和</th></tr></thead><tbody><tr><th>2023 Ⅰ卷 17</th><td>主要</td><td>主要</td><td>—</td><td>—</td></tr><tr><th>2025 一卷 16</th><td>—</td><td>—</td><td>主要</td><td>主要</td></tr></tbody>';const wrap=el('div','table-wrap');wrap.append(t);root.append(wrap);
 const links=el('div','replay-controls');for(const [id,label]of [['national-2023-q17','查看三角形案例的步骤与难度'],['national-2025-q16','查看数列案例的步骤与难度']])links.append(button(label,()=>{state.example=id;state.mode='solution';renderSingle();selectView('single');}));root.append(links,el('h3','','按模板组卷怎样复用单题能力'));flow(root,['模板目标','分配题位','选题 / 出题','单题检查','整卷复核'],3);
 const time=el('div','time-diagram');['首次作答','返回修改','后续题目','未归属时段'].forEach(x=>time.append(el('span','',x)));root.append(time,note('时间轴为事件记录方式示意，未使用这两道题的学生用时数据。未归属时段单列，笔画首末间隔仅表示书写跨度。'));
}
function renderCareer(){const root=scenario('career','同样答对，也要记录是否获得帮助',['提示后完成','无提示新题','出现相反证据'],['记录为提示后完成，后续安排无提示新题检查。','单独记录新题独立作答，并在间隔一段时间后再次检查。','保留前后作答，修订判断，并说明下一次要检查什么。']);const tracks=el('div','evidence-tracks');['课时作业 → 知识理解与应用','考试 / 错题 / 先导测试 → 套路与步骤表现','汇入带来源、帮助条件和版本的长期档案'].forEach(x=>tracks.append(el('div','',x)));root.append(tracks,note('知识理解、方法迁移和复盘能力分别保存，帮助条件随证据保留。'));}
function renderAgent(){const root=scenario('agent','同一业务档案，不同职责视角',['学生助教','教师助理','学校教研'],['今天练什么？查询本人近期作答和可用时间，安排教学、练习或复查。','这一步要不要重讲？核对授权班级记录，准备教案和补练草稿。','本阶段怎样改进？核对学生起点与任务难度，准备教研分析和课程变更草案。']);flow(root,['理解请求','查询证据','调用工具','检查结果','解释跟进'],2);root.append(note('Agent 读取共同档案、调用已有业务，再把依据和任务交给相应角色。'));}
function renderTeacher(){const root=scenario('teacher','同一困难，不同教学范围',['个别补练','小组讲解','全班重讲'],['查看具体作答及已尝试帮助，安排局部训练与新题复测。','核实共同困难，再准备适当的小组讲解和任务。','确认哪些学生存在同一困难，复核批改后调整课堂重点，再检查新题表现。']);flow(root,['备课','演示课件','作业','批改讲评','考试','教学调整','人工关注'],3);root.append(note('个别、小组和全班行动使用同一批作答证据，后续新题检验教学调整的效果。'));}
function renderSchool(){const root=scenario('school','改一项定义，哪些记录受影响',['步骤定义','知识点拆分','课时重排'],['列出相关套路、解析、批改和报告，审核后发布新版本，旧报告保留原版本。','先按新知识点重新对应旧作答，资料不足的项目再安排补充诊断。','检查新课序需要哪些前置知识，再对照学生已有表现安排补充。']);flow(root,['变更草稿','影响分析','教研审核','版本发布','历史保留'],1);root.append(note('教学评价结合学生起点、可比任务、教学行动和多来源证据。'));}
function renderModes(){
 const root=$('scene-modes');let complete=state.completeMode;const body=el('div','mode-comparison'),rows=[['学习','跟随班级课程','结合课序检查前置知识','原课表与按需单题帮助'],['作业','课时统一布置与订正','共同目标下分别安排作业','保留作业，接入批改讲评'],['刷题','按章节或个人经验选题','按套路顺序和知识准备选题','自选套路或错题补练'],['反思','分数、订正与自行总结','根据错误步骤安排新题复测','错题查找与订正'],['考试','统一考试与事后讲评','结合考前记录分析本次考试','分析本次试卷和作答'],['复习','统一进度与经验安排','合并复习与补练，控制总用时','原复习安排中局部补练']];
 const draw=()=>{const t=el('table');t.innerHTML='<caption>当前查看：'+(complete?'完整系统模式':'传统教学增强模式')+'；并排保留另一模式作比较</caption><thead><tr><th>环节</th><th>常见传统安排</th><th class="'+(complete?'selected-mode':'')+'">完整系统</th><th class="'+(!complete?'selected-mode':'')+'">传统教学增强</th></tr></thead><tbody>'+rows.map(r=>'<tr><th scope="row">'+r[0]+'</th><td>'+r[1]+'</td><td class="'+(complete?'selected-mode':'')+'">'+r[2]+'</td><td class="'+(!complete?'selected-mode':'')+'">'+r[3]+'</td></tr>').join('')+'</tbody>';body.replaceChildren(t);};
 const ctl=tabs([['full','完整采用'],['partial','传统教学增强']],complete?'full':'partial',id=>{complete=id==='full';state.completeMode=complete;draw();ctl.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===(complete?0:1))));});root.replaceChildren(bar('同一套能力，两种接入深度','目标流程比较'),ctl,body,note('完整模式需要持续的课程、作答和复核记录；局部模式先使用已提供的材料。功能随数据逐步扩展，两种模式都需通过学生独立表现评价效果。'));draw();
}
function renderMcp(){const root=scenario('mcp','入口不同，教育规则与记录共用',['产品内置 Agent','DeepSeek 官方 DSH','WorkBuddy'],['已有内部搜索、解题、教学、批改、规划与学情查询基础。','计划通过 MCP 调用教学工具；DSH 提供对话，StudyAgent 保存作答和任务结果。','计划通过连接器与技能调用教学工具，制作课件时调用宿主已接入的文档工具。']);const graph=el('div','mcp-topology');['课程 · 步骤 · 题库 · 作答 · 学习记录','共用教育业务与 MCP 适配','内置 Agent　 /　官方 DSH　 /　WorkBuddy'].forEach(x=>graph.append(el('div','',x)));root.append(graph,note('适配后，练习生成和课件素材查询由同一教育服务完成，对话和文件制作使用宿主工具。'));}
function renderEvolution(){const root=scenario('evolution','改进经过验证，再回到系统',['教师反馈','人工维护','新试题与教材','跨学科扩展'],['核实问题与修正内容后，选择更新知识库、个人记忆或模型，并检查更新效果。','修订数据、关系和参数，记录版本，并列出需要重新分析的旧记录。','先核对新题和教材，再判断是否需要新增或修改步骤、套路、知识点及课时。','复用记录和工具，重新定义各学科任务、评分标准和学习效果实验。']);flow(root,['获得反馈','核对来源','离线评价','发布版本','教学再验证'],2);root.append(note('每次修改先重跑固定测试，再用新任务检查迁移，并保留旧版内容和规则。'));}
function navigation(){
 const nav=document.querySelector('.primary-nav'),headerLinks=[...nav.querySelectorAll('a[href^="#"]')],quickJump=$('topic-quick-jump');
 function currentTopic(id){
  const topic=$(id)?.closest('[data-chapter]')?.id||aliases[id]||id;state.view=topic;
  const addressed=location.hash.slice(1),addressedTopic=$(addressed)?.closest('[data-chapter]')?.id||aliases[addressed]||addressed;
  if(uiReady&&$(topic)&&addressedTopic!==topic){const url=new URL(location.href);url.hash=topic;history.replaceState(history.state,'',url);}
  if($(topic)?.matches('[data-chapter]'))document.body.dataset.currentTopic=topic;
  for(const a of headerLinks){if(a.hash==='#'+topic)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');}
  if(quickJump&&quickJump.value!==topic)quickJump.value=topic;
  const selected=headerLinks.find(a=>a.hash==='#'+topic);
  if(selected&&nav.clientWidth){const item=selected.getBoundingClientRect(),box=nav.getBoundingClientRect();let dx=0;if(item.left<box.left+8)dx=item.left-box.left-12;else if(item.right>box.right-8)dx=item.right-box.right+12;if(dx)nav.scrollBy({left:dx,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
 }
 document.addEventListener('click',event=>{
  const trigger=event.target.closest?.('[data-annotation]');if(trigger)openAnnotation(trigger.dataset.annotation,trigger);
  const link=event.target.closest?.('a[href^="#"]');if(link&&singleModes[link.hash.slice(1)]){state.mode=singleModes[link.hash.slice(1)];renderSingle();}
 });
 $('annotation-close').onclick=closeAnnotation;
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('annotation-panel').hidden)closeAnnotation();});
 quickJump?.addEventListener('change',()=>selectView(quickJump.value));
 document.querySelectorAll('[data-perspective]').forEach((tab,index)=>{
  tab.addEventListener('click',()=>setPerspective(tab.dataset.perspective));
  tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?perspectives.length-1:(index+(event.key==='ArrowRight'?1:-1)+perspectives.length)%perspectives.length;document.querySelector('[data-perspective="'+perspectives[next]+'"]')?.focus();setPerspective(perspectives[next]);});
 });
 setPerspective(state.perspective,false);
 function relate(event){
  const key=event.target.closest?.('[data-link-focus]');
  const interactive=event.target.closest?.('.step,.grade-step,.concept-node,.bank-step,[data-routine-step],.scene-tabs button,.solution-controls select');
  const unit=key?.closest('.topic-unit')||interactive?.closest('.topic-unit');
  if(!unit||unit.querySelector('.shared-cell'))return;
  const mobile=matchMedia('(max-width:820px)').matches;
  const selected=!(key?.classList.contains('topic-unit-key')&&!mobile&&unit.classList.contains('is-linked'));
  const label=interactive?.querySelector('h4,h5')?.textContent||interactive?.selectedOptions?.[0]?.textContent||interactive?.textContent.trim()||unit.querySelector('.topic-unit-key strong')?.textContent;
  // Capture the unit before scene rendering replaces a clicked button's parent.
  queueMicrotask(()=>{
   document.querySelectorAll('.topic-unit').forEach(node=>{
    const on=node===unit&&selected;node.classList.toggle('is-linked',on);
    node.querySelectorAll('[data-link-focus]').forEach(trigger=>trigger.setAttribute('aria-pressed',String(on)));
    node.querySelector('[data-relation-anchor]')?.classList.toggle('is-relation-target',on);
    const note=node.querySelector('.relation-focus');if(note){note.hidden=!on;if(on)note.textContent='对应内容：'+label+'；技术依据：'+unit.dataset.relatedProcessing;}
   });

  });
 }
 document.addEventListener('click',relate,true);
 document.addEventListener('change',relate,true);
 let touchStart=null;
 document.addEventListener('touchstart',event=>{
  if(!matchMedia('(max-width: 820px)').matches||event.touches.length!==1)return;
  const target=event.target,topic=target.closest?.('.topic-section');if(!topic||target.closest?.('button,a,input,select,textarea'))return;
  if(['vision','highlights'].includes(topic.id))return;
  let horizontalScroll=false;
  for(let node=target;node&&node!==topic;node=node.parentElement){if(node.scrollWidth>node.clientWidth+5&&/(auto|scroll|overlay)/.test(getComputedStyle(node).overflowX)){horizontalScroll=true;break;}}
  if(!horizontalScroll)touchStart={x:event.touches[0].clientX,y:event.touches[0].clientY};
 },{passive:true});
 document.addEventListener('touchend',event=>{
  if(!touchStart||!matchMedia('(max-width: 820px)').matches)return;
  const dx=event.changedTouches[0].clientX-touchStart.x,dy=event.changedTouches[0].clientY-touchStart.y;touchStart=null;
  if(Math.abs(dx)<58||Math.abs(dx)<Math.abs(dy)*1.35)return;
  const next=(perspectives.indexOf(state.perspective)+(dx<0?1:-1)+perspectives.length)%perspectives.length;setPerspective(perspectives[next]);
 },{passive:true});
 const updateTopic=()=>{const chapter=readingChapter();if(chapter)currentTopic(chapter.id);};
 const observer=new IntersectionObserver(updateTopic,{rootMargin:'-16% 0px -66% 0px'});
 for(const chapter of document.querySelectorAll('[data-chapter]'))observer.observe(chapter);
 addEventListener('showcase:reading-ready',updateTopic);
 const hash=location.hash.slice(1);currentTopic(aliases[hash]||hash||'vision');
 addEventListener('hashchange',()=>{const id=location.hash.slice(1);if(singleModes[id]){state.mode=singleModes[id];renderSingle();}const topic=aliases[id]||id;if($(topic))currentTopic(topic);});
}
// Cross-chapter jumps leave a floating companion for returning to the exact spot.
const originState={y:0};
const returnButton=el('button','return-to-origin');
returnButton.type='button';returnButton.hidden=true;
returnButton.setAttribute('aria-label','回到跳转前的位置');
returnButton.insertAdjacentHTML('afterbegin','<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 14.5 4 9l5.5-5.5"/><path d="M4 9h9.5a6.5 6.5 0 0 1 0 13H10"/></svg>');
returnButton.append(el('span','','回到原处'));
document.body.append(returnButton);
function currentChapterId(){return [...document.querySelectorAll('[data-chapter]')].find(node=>{const r=node.getBoundingClientRect();return r.top<=innerHeight*.45&&r.bottom>innerHeight*.45})?.id||null;}
function recordOrigin(targetId){
 if(!uiReady||!entered||document.body.classList.contains('is-launch-open'))return;
 const resolved=aliases[targetId]||targetId,target=$(resolved)?.closest('[data-chapter]')?.id||resolved,current=currentChapterId();
 if(!current||target===current)return;
 originState.y=scrollY;returnButton.hidden=false;
}
returnButton.onclick=()=>{
 returnButton.hidden=true;
 const top=Math.max(0,Math.min(originState.y,document.documentElement.scrollHeight-innerHeight));
 scrollTo({top,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
};
document.addEventListener('click',event=>{
 if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
 const link=event.target.closest?.('a[href^="#"]');if(!link||link.target==='_blank'||link.hasAttribute('download'))return;
 recordOrigin(link.hash.slice(1));
},true);
api.replayOpening=()=>window.ShowcaseHero?.open({force:true});
function setupMotion(){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 document.body.classList.add('motion-ready');
 const observer=new IntersectionObserver(entries=>{for(const entry of entries){
  // Unit cards re-run their entrance every time they scroll back into view;
  // other blocks animate once and stay.
  if(entry.target.classList.contains('topic-unit')){
   entry.target.classList.toggle('is-inview',entry.isIntersecting);
  }else if(entry.isIntersecting){entry.target.classList.add('is-inview');observer.unobserve(entry.target);}
 }},{rootMargin:'0px 0px -8% 0px',threshold:0});
 document.querySelectorAll('.topic-heading,.pain-point,.topic-unit,.opening-case,.project-architecture,.research-study,.chapter-scene').forEach(node=>observer.observe(node));
}
async function json(name){const r=await fetch('/showcase/'+name,{credentials:'omit'});if(!r.ok)throw Error(name+' 加载失败');return r.json();}
navigation();
const openingFinished=window.ShowcaseHero?.open({skip:resumeReading||Boolean(location.hash)})||Promise.resolve();
api.ready=(async()=>{const results=await Promise.allSettled([json('data.json'),json('pipeline.json'),json('recordings.json')]);if(results[0].status==='rejected'||results[1].status==='rejected')throw Error('全国卷案例数据加载失败，请刷新重试。');state.data=results[0].value;state.pipelineData=results[1].value;state.recordings=results[2].status==='fulfilled'?results[2].value:{cases:[]};restoreChoices();for(const render of [renderConcepts,renderSingle,renderDiagnosis,renderRoutines,renderExam,renderCareer,renderAgent,renderTeacher,renderSchool,renderModes,renderMcp,renderEvolution])render();ShowcaseBank.init(api,{el,p,button,details});if(resumeReading&&savedReading.bank)await ShowcaseBank.restore(savedReading.bank);else await ShowcaseBank.show();document.querySelectorAll('[data-library-tab]').forEach(b=>b.onclick=()=>ShowcaseBank.tab(b.dataset.libraryTab));$('exam-student').onclick=()=>ShowcaseBank.renderExam(false);$('exam-teacher').onclick=()=>ShowcaseBank.renderExam(true);$('exam-print').onclick=()=>window.print();const hash=location.hash.slice(1);if(aliases[hash]&&!resumeReading)selectView(hash);await openingFinished;entered=true;await restoreReadingPosition();setupMotion();return state.data;})().catch(error=>{state.loadError=error.message;$('demo-status').hidden=false;$('demo-status').textContent=error.message+' 正文仍可阅读。';console.error(error);return null;});
})();
