/* Shared topic handoffs follow native scroll; they never control navigation. */
(function(){
 'use strict';
 const topics=[...document.querySelectorAll('[data-chapter]')];
 if(!topics.length)return;
 const topicNames={vision:'教学愿景',highlights:'亮点',terms:'四个名词介绍',single:'单题能力',time:'时间维度',library:'题库与错题',exam:'考试与复盘',longterm:'长期陪伴',teacher:'教师工作流',school:'学校与教学采用方式',agent:'MCP与Agent能力',evolution:'自进化'};
 const aliases={overview:'highlights',dataset:'highlights',concepts:'terms',diagnosis:'time',routines:'library',career:'longterm',modes:'school',mcp:'agent',solution:'single',grading:'single',teaching:'single',generation:'single',geometry:'single',graph:'library',pool:'library',progress:'evolution',research:'evolution'};
 const byId=new Map(topics.map(topic=>[topic.id,topic]));
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const states=[],visible=new Set(),waiting=new Set(),arriving=new Map();
 let raf=0,firstLayout=true,lastScrollY=scrollY,navigationUntil=0;
 const launchOpen=()=>document.body.classList.contains('is-launch-open');
 const clamp=value=>Math.max(0,Math.min(1,value));
 const smooth=value=>{const p=clamp(value);return p*p*(3-2*p);};
 // Layout offsets stay stable while the complete panel is tilted in perspective.
 // Measuring its transformed bounds would feed the animation back into its scroll target.
 function layoutTop(element){
  let top=0;
  for(let current=element;current;current=current.offsetParent){top+=current.offsetTop;const parent=current.offsetParent;if(parent)top+=parent.clientTop;}
  return top-scrollY;
 }
 function measureTopic(topic){return topic?{top:layoutTop(topic),height:topic.offsetHeight}:null;}
 function node(tag,cls,text){const result=document.createElement(tag);if(cls)result.className=cls;if(text)result.textContent=text;return result;}
 function arrow(cls){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 56 24');svg.setAttribute('aria-hidden','true');svg.classList.add(cls);const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M2 12h50m-8-8 8 8-8 8');svg.append(path);return svg;}
 function resolve(value){const id=String(value||'').replace(/^#/,'');const mapped=aliases[id]||id;return byId.has(mapped)?mapped:null;}
 function label(id){return topicNames[id]||byId.get(id)?.querySelector('h1,h2')?.textContent||'';}
 function topicAt(value){const id=String(value||'').replace(/^#/,'');return document.getElementById(id)?.closest('[data-chapter]')||byId.get(resolve(id));}
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
  topic.dataset.arrivalProgress=reduced.matches?'1':'0';topic.dataset.arrivalTarget=reduced.matches?'1':'0';
  if(!reduced.matches){topic.classList.add('is-arrival-pending');waiting.add(topic);}
 }
 function finishTopic(topic){
  const arrival=arriving.get(topic);
  arrival?.previous?.bridge.classList.remove('is-pushing-out');arrival?.previous?.bridge.style.removeProperty('--handoff-push-y');
  arriving.delete(topic);topic.classList.remove('is-arriving');
  for(const property of ['--topic-arrival-y','--topic-arrival-depth','--topic-arrival-tilt','--topic-arrival-scale','--topic-arrival-edge'])topic.style.removeProperty(property);
  topic.dataset.arrivalState='complete';topic.dataset.arrivalProgress='1';topic.dataset.arrivalTarget='1';
 }
 function arrivalDistance(){return innerWidth<=820?Math.min(145,Math.max(95,innerWidth*.3)):Math.min(235,Math.max(170,innerHeight*.25));}
 function paintArrival(arrival){
  const remaining=1-arrival.progress,mobile=innerWidth<=820;
  arrival.offset=arrivalDistance()*remaining;
  arrival.topic.style.setProperty('--topic-arrival-y',arrival.offset.toFixed(3)+'px');
  arrival.topic.style.setProperty('--topic-arrival-depth',(-(mobile?110:185)*remaining).toFixed(3)+'px');
  arrival.topic.style.setProperty('--topic-arrival-tilt',(-(mobile?4.2:6.5)*remaining).toFixed(3)+'deg');
  arrival.topic.style.setProperty('--topic-arrival-scale',(1-.018*remaining).toFixed(5));
  arrival.topic.style.setProperty('--topic-arrival-edge',(.7*remaining).toFixed(4));
  arrival.topic.dataset.arrivalProgress=arrival.progress.toFixed(4);arrival.topic.dataset.arrivalTarget=arrival.target.toFixed(4);
  // The shared handoff responds gently in the same upward direction, then returns to rest.
  arrival.previous?.bridge.style.setProperty('--handoff-push-y',(-16*Math.sin(arrival.progress*Math.PI)).toFixed(3)+'px');
 }
 function revealTopic(topic,animate){
  // A focused or directly addressed chapter must settle immediately, even mid-push.
  if(!animate&&arriving.has(topic)){finishTopic(topic);return;}
  if(!waiting.has(topic))return;waiting.delete(topic);
  const previous=states.find(state=>state.nextId===topic.id);
  if(previous&&(previous.progress===null||previous.progress<.8))apply(previous,1);
  topic.classList.remove('is-arrival-pending');topic.dataset.arrivalState=animate?'arriving':'complete';
  if(!animate){finishTopic(topic);return;}
  const arrival={topic,previous,progress:0,target:0,offset:0,lastAt:performance.now()};
  arriving.set(topic,arrival);paintArrival(arrival);
  previous?.bridge.classList.add('is-pushing-out');topic.classList.add('is-arriving');
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
  raf=0;if(reduced.matches||launchOpen())return;
  // Deliver while the card is fully readable, using actual navigation geometry.
  const header=document.querySelector('.site-header')?.getBoundingClientRect().bottom||0;
  const switcher=document.querySelector('.perspective-switch');
  const inset=switcher&&getComputedStyle(switcher).display!=='none'?switcher.getBoundingClientRect().bottom:header;
  const start=innerHeight*.96,end=Math.min(start-100,Math.max(inset+24,innerHeight*.5));
  const now=performance.now(),scrollDelta=scrollY-lastScrollY;
  const jumped=Math.abs(scrollDelta)>Math.max(480,innerHeight*.9);lastScrollY=scrollY;
  const positions=[...visible].map(state=>[state,layoutTop(state.bridge)]);
  const arrivalStart=innerHeight*1.08,arrivalEnd=Math.max(inset+70,innerHeight*.54);
  // Read layout before writing transforms. Perspective never changes the scroll geometry.
  const measurements=new Map([...new Set([...waiting,...arriving.keys()])].map(topic=>{
   const heading=topic.querySelector('.topic-heading')||topic,top=layoutTop(heading);
   return [topic,{top,bottom:top+heading.offsetHeight,sectionBottom:layoutTop(topic)+topic.offsetHeight}];
  }));
  let playing=false;
  for(const [state,top]of positions){
   if(top<=start&&state.startedAt===null)state.startedAt=now;
   const elapsed=state.startedAt===null?0:clamp((now-state.startedAt)/1150);
   const inMotion=state.startedAt!==null&&elapsed<1;
   state.bridge.classList.toggle('is-playing',inMotion);playing=playing||inMotion;
   // Keep the handoff legible even when the reader stops scrolling at its entrance.
   apply(state,Math.max((start-top)/(start-end),elapsed));
  }
  for(const topic of [...waiting]){
   const heading=measurements.get(topic);
   if(heading.sectionBottom<=inset||heading.bottom<inset)revealTopic(topic,false);
   else if(heading.top<=arrivalStart){
    // An initially visible or directly restored chapter is readable without a delayed entrance.
    if(firstLayout&&heading.top>innerHeight*.92)continue;
    const entrance=heading.top>Math.max(inset+32,innerHeight*.52);
    revealTopic(topic,!firstLayout&&!jumped&&now>=navigationUntil&&scrollDelta>=-8&&entrance);
   }
  }
  for(const [topic,arrival]of [...arriving]){
   const heading=measurements.get(topic);
   if(jumped||heading.sectionBottom<=inset||heading.bottom<inset){finishTopic(topic);continue;}
   arrival.target=clamp((arrivalStart-heading.top)/(arrivalStart-arrivalEnd));
   // A 210 ms time constant feels weighted at every display refresh rate. Pausing the
   // scroll converges only to its current target; it never runs the rest of the entrance.
   const elapsed=Math.max(0,now-arrival.lastAt);arrival.lastAt=now;
   arrival.progress+=(arrival.target-arrival.progress)*(1-Math.exp(-elapsed/210));
   if(Math.abs(arrival.target-arrival.progress)<.001)arrival.progress=arrival.target;
   if(arrival.target===1&&arrival.progress>=.999){finishTopic(topic);continue;}
   paintArrival(arrival);playing=playing||Math.abs(arrival.target-arrival.progress)>=.001;
  }
  firstLayout=false;
  if(playing)schedule(true);
 }
 function schedule(continuing=false){
  if(raf||reduced.matches||launchOpen())return;
  // A fresh scroll after an idle pause gets the same damping as an ongoing gesture.
  if(continuing!==true)for(const arrival of arriving.values())arrival.lastAt=performance.now();
  raf=requestAnimationFrame(draw);
 }
 const observer=new IntersectionObserver(entries=>{
  for(const entry of entries){const state=states.find(item=>item.bridge===entry.target);if(!state)continue;if(entry.isIntersecting)visible.add(state);else{visible.delete(state);state.bridge.classList.remove('is-playing');if(entry.boundingClientRect.top>0)state.startedAt=null;if(!launchOpen())apply(state,reduced.matches||entry.boundingClientRect.top<0?1:0);}}
  schedule();
 },{rootMargin:'0px 0px 12% 0px',threshold:0});
 for(const state of states){apply(state,reduced.matches?1:0);observer.observe(state.bridge);}
 if('ResizeObserver'in window){const resize=new ResizeObserver(schedule);states.forEach(state=>resize.observe(state.stage));}
 addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule,{passive:true});
 addEventListener('showcase:layout-changed',schedule);
 function navigate(value){const topic=topicAt(value);if(topic)revealTopic(topic,false);navigationUntil=performance.now()+1400;schedule();}
 document.addEventListener('click',event=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;const link=event.target.closest?.('a[href^="#"]');if(link&&!link.hasAttribute('download'))navigate(link.hash);},true);
 document.addEventListener('focusin',event=>{const topic=event.target.closest?.('[data-chapter]');if(topic)revealTopic(topic,false);});
 addEventListener('hashchange',()=>navigate(location.hash));
 addEventListener('showcase:navigate',event=>navigate(event.detail?.to));
 addEventListener('showcase:entered',()=>{lastScrollY=scrollY;for(const arrival of arriving.values())arrival.lastAt=performance.now();schedule();});
 addEventListener('pageshow',()=>{firstLayout=true;lastScrollY=scrollY;for(const topic of [...arriving.keys()])finishTopic(topic);schedule();});
 reduced.addEventListener?.('change',()=>{if(reduced.matches){if(raf)cancelAnimationFrame(raf);raf=0;for(const state of states){state.bridge.classList.remove('is-playing');apply(state,1);}for(const topic of [...waiting])revealTopic(topic,false);for(const topic of [...arriving.keys()])finishTopic(topic);}else schedule();});
 schedule();
 window.ShowcaseTransitions={refresh:schedule,resolveTopic:resolve,measureTopic:topic=>measureTopic(typeof topic==='string'?byId.get(topic):topic)};
})();
