/* Shared topic handoffs follow native scroll; they never control navigation. */
(function(){
 'use strict';
 const topics=[...document.querySelectorAll('[data-chapter]')];
 if(!topics.length)return;
 const topicNames={highlights:'亮点',terms:'四个名词介绍',single:'单题能力',time:'时间维度',library:'题库与错题',exam:'考试与复盘',longterm:'长期陪伴',teacher:'教师工作流',school:'学校与教学采用方式',agent:'MCP与Agent能力',evolution:'自进化'};
 const aliases={overview:'highlights',dataset:'highlights',concepts:'terms',diagnosis:'time',routines:'library',career:'longterm',modes:'school',mcp:'agent',solution:'single',grading:'single',teaching:'single',generation:'single',geometry:'single',graph:'library',pool:'library',progress:'evolution',research:'evolution'};
 const byId=new Map(topics.map(topic=>[topic.id,topic]));
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const states=[],visible=new Set(),waiting=new Set();let raf=0;
 const clamp=value=>Math.max(0,Math.min(1,value));
 const smooth=value=>{const p=clamp(value);return p*p*(3-2*p);};
 function node(tag,cls,text){const result=document.createElement(tag);if(cls)result.className=cls;if(text)result.textContent=text;return result;}
 function arrow(cls){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 56 24');svg.setAttribute('aria-hidden','true');svg.classList.add(cls);const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M2 12h50m-8-8 8 8-8 8');svg.append(path);return svg;}
 function resolve(value){const id=String(value||'').replace(/^#/,'');const mapped=aliases[id]||id;return byId.has(mapped)?mapped:null;}
 function label(id){return topicNames[id]||byId.get(id)?.querySelector('h1,h2')?.textContent||'';}
 for(let index=0;index<topics.length;index++){
  const topic=topics[index],bridge=topic.querySelector('.chapter-bridge'),flow=bridge?.querySelector('.bridge-flow'),link=bridge?.querySelector('.chapter-transition');
  if(!bridge||!flow||!link)continue;
  const nextId=resolve(link.hash)||topics[index+1]?.id||topics[0].id;
  const stage=node('div','handoff-stage'),context=node('div','handoff-context'),from=node('div','handoff-chapter'),to=node('div','handoff-chapter handoff-next');
  from.append(node('span','handoff-label','本主题形成'),node('strong','',label(topic.id)));
  to.append(node('span','handoff-label',index===topics.length-1?'回到问题起点':'接下来进入'),node('strong','',label(nextId)));
  context.append(from,arrow('handoff-context-arrow'),to);
  stage.append(context,flow,link);bridge.append(stage);bridge.classList.add('has-handoff');
  const path=flow.querySelector('.bridge-track path');
  if(path){const base=path.cloneNode(true);base.classList.add('handoff-line-base');path.before(base);path.classList.add('handoff-line-motion');path.setAttribute('pathLength','1');}
  const state={id:topic.id,nextId,bridge,stage,progress:null,startedAt:null};
  bridge.dataset.handoffFrom=topic.id;bridge.dataset.handoffTo=nextId;states.push(state);
 }
 for(const topic of topics.slice(1)){
  topic.dataset.arrivalFrom=states.find(state=>state.nextId===topic.id)?.id||'';
  topic.dataset.arrivalState=reduced.matches?'complete':'pending';
  if(!reduced.matches){topic.classList.add('is-arrival-pending');waiting.add(topic);}
 }
 function revealTopic(topic,animate){
  if(!waiting.has(topic))return;waiting.delete(topic);
  const previous=states.find(state=>state.nextId===topic.id);
  if(previous&&previous.progress<.8)apply(previous,1);
  topic.classList.remove('is-arrival-pending');topic.dataset.arrivalState=animate?'arriving':'complete';
  if(animate){topic.classList.add('is-arriving');const finish=event=>{if(event.target!==topic||event.animationName!=='topic-arrival')return;topic.removeEventListener('animationend',finish);topic.classList.remove('is-arriving');topic.dataset.arrivalState='complete';};topic.addEventListener('animationend',finish);}
 }
 function apply(state,progress){
  const p=clamp(progress);if(state.progress===p)return;state.progress=p;
  const delivery=smooth(p/.72),arrival=smooth((p-.12)/.68),style=state.bridge.style;
  style.setProperty('--handoff-progress',p.toFixed(4));
  style.setProperty('--handoff-line-offset',(1-delivery).toFixed(4));
  style.setProperty('--handoff-marker-position',(delivery*100).toFixed(2)+'%');
  style.setProperty('--handoff-marker-opacity',p>.02&&p<.72?'1':'0');
  style.setProperty('--handoff-target-opacity',(.82+.18*arrival).toFixed(3));
  style.setProperty('--handoff-target-y',(6*(1-arrival)).toFixed(2)+'px');
  style.setProperty('--handoff-arrival-opacity',arrival.toFixed(3));
  state.bridge.dataset.handoffProgress=p.toFixed(3);
  state.bridge.classList.toggle('is-bridging',p>.01&&p<.99);
  state.bridge.classList.toggle('is-delivered',p>=.8);
 }
 function draw(){
  raf=0;if(reduced.matches)return;
  // Deliver while the card is fully readable, using actual navigation geometry.
  const header=document.querySelector('.site-header')?.getBoundingClientRect().bottom||0;
  const switcher=document.querySelector('.perspective-switch');
  const inset=switcher&&getComputedStyle(switcher).display!=='none'?switcher.getBoundingClientRect().bottom:header;
  const start=innerHeight*.96,end=Math.min(start-100,Math.max(inset+24,innerHeight*.5));
  const positions=[...visible].map(state=>[state,state.bridge.getBoundingClientRect().top]);
  const arrivals=[...waiting].map(topic=>({topic,heading:topic.querySelector('.topic-heading').getBoundingClientRect(),section:topic.getBoundingClientRect()}));
  let playing=false;
  for(const [state,top]of positions){
   if(top<=start&&state.startedAt===null)state.startedAt=performance.now();
   const elapsed=state.startedAt===null?0:clamp((performance.now()-state.startedAt)/1150);
   const inMotion=state.startedAt!==null&&elapsed<1;
   state.bridge.classList.toggle('is-playing',inMotion);playing=playing||inMotion;
   // Keep the handoff legible even when the reader stops scrolling at its entrance.
   apply(state,Math.max((start-top)/(start-end),elapsed));
  }
  for(const {topic,heading,section}of arrivals){
   if(section.bottom<=inset||heading.bottom<inset)revealTopic(topic,false);
   else if(heading.top<=innerHeight*.92)revealTopic(topic,true);
  }
  if(playing)schedule();
 }
 function schedule(){if(!raf&&!reduced.matches)raf=requestAnimationFrame(draw);}
 const observer=new IntersectionObserver(entries=>{
  for(const entry of entries){const state=states.find(item=>item.bridge===entry.target);if(!state)continue;if(entry.isIntersecting)visible.add(state);else{visible.delete(state);state.bridge.classList.remove('is-playing');if(entry.boundingClientRect.top>0)state.startedAt=null;apply(state,reduced.matches||entry.boundingClientRect.top<0?1:0);}}
  schedule();
 },{rootMargin:'0px 0px 12% 0px',threshold:0});
 for(const state of states){apply(state,reduced.matches?1:0);observer.observe(state.bridge);}
 if('ResizeObserver'in window){const resize=new ResizeObserver(schedule);states.forEach(state=>resize.observe(state.stage));}
 addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule,{passive:true});
 document.addEventListener('focusin',event=>{const topic=event.target.closest?.('[data-chapter]');if(topic)revealTopic(topic,false);});
 reduced.addEventListener?.('change',()=>{if(reduced.matches){if(raf)cancelAnimationFrame(raf);raf=0;for(const state of states){state.bridge.classList.remove('is-playing');apply(state,1);}for(const topic of [...waiting])revealTopic(topic,false);document.querySelectorAll('.is-arriving').forEach(topic=>{topic.classList.remove('is-arriving');topic.dataset.arrivalState='complete';});}else schedule();});
 schedule();
 window.ShowcaseTransitions={refresh:schedule,resolveTopic:resolve};
})();
