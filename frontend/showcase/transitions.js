/* Chapter handoffs follow native scroll; this layer never controls navigation. */
(function(){
 'use strict';
 const chapters=[...document.querySelectorAll('[data-chapter]')];
 if(!chapters.length)return;
 const shortNames={overview:'项目总览',concepts:'基础表示',dataset:'数据集',single:'单题能力',diagnosis:'过程诊断',library:'错题与题库',routines:'套路训练',exam:'整卷分析',career:'长期学习',agent:'教学协同 Agent',teacher:'教师教学',school:'学校教研',modes:'教学模式',mcp:'MCP 与宿主',evolution:'系统演进'};
 const aliases={solution:'single',grading:'single',teaching:'single',generation:'single',geometry:'single',graph:'routines',pool:'library',progress:'evolution',research:'evolution'};
 const chapterMap=new Map(chapters.map(chapter=>[chapter.id,chapter]));
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const items=[],visible=new Set();
 let active=null,frame=0,ready=false,overlayTimer=0,lastRoute='',lastRouteAt=0;
 const clamp=value=>Math.max(0,Math.min(1,value));
 const smooth=value=>{const p=clamp(value);return p*p*(3-2*p);};
 function node(tag,cls,text){const result=document.createElement(tag);if(cls)result.className=cls;if(text)result.textContent=text;return result;}
 function arrow(cls){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 56 24');svg.setAttribute('aria-hidden','true');svg.classList.add(cls);const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M2 12h50m-8-8 8 8-8 8');svg.append(path);return svg;}
 function resolveId(value){const clean=String(value||'').replace(/^#/,'');const id=aliases[clean]||clean;return chapterMap.has(id)?id:null;}
 function label(id){return shortNames[id]||chapterMap.get(id)?.querySelector('h1,h2')?.textContent||'';}
 function currentId(){const saved=resolveId(window.Showcase?.state?.view);if(saved)return saved;return chapters.find(chapter=>{const r=chapter.getBoundingClientRect();return r.top<=innerHeight*.45&&r.bottom>innerHeight*.45;})?.id||chapters[0].id;}

 for(let index=0;index<chapters.length;index++){
  const chapter=chapters[index],bridge=chapter.querySelector('.chapter-bridge');
  if(!bridge)continue;
  const flow=bridge.querySelector('.bridge-flow'),link=bridge.querySelector('.chapter-transition');
  if(!flow||!link)continue;
  const nextId=resolveId(link.hash)||chapters[(index+1)%chapters.length].id;
  const stage=node('div','handoff-stage'),context=node('div','handoff-context');
  const from=node('div','handoff-chapter'),to=node('div','handoff-chapter handoff-next');
  from.append(node('span','handoff-label','从这一章'),node('strong','',label(chapter.id)));
  to.append(node('span','handoff-label',index===chapters.length-1?'回到起点':'走向下一章'),node('strong','',label(nextId)));
  context.append(from,arrow('handoff-context-arrow'),to);
  const arrivalTitle=node('p','handoff-arrival-title',chapterMap.get(nextId)?.querySelector('h1,h2')?.textContent||label(nextId));
  arrivalTitle.setAttribute('aria-hidden','true');
  stage.append(context,flow,arrivalTitle,link);bridge.append(stage);bridge.classList.add('has-handoff');
  const path=flow.querySelector('.bridge-track path');
  if(path){const base=path.cloneNode(true);base.classList.add('handoff-line-base');path.before(base);path.classList.add('handoff-line-motion');path.setAttribute('pathLength','1');}
  const item={id:chapter.id,nextId,bridge,stage,ratio:0,stageHeight:0};
  bridge.dataset.handoffFrom=chapter.id;bridge.dataset.handoffTo=nextId;items.push(item);
 }

 // All measurements happen before style writes; only the active bridge is read on scroll.
 function applyProgress(item,progress){
  const p=clamp(progress),delivery=smooth((p-.2)/.5),arrival=smooth((p-.48)/.43),departure=smooth((p-.6)/.4);
  const style=item.bridge.style;
  style.setProperty('--handoff-progress',p.toFixed(4));
  style.setProperty('--handoff-line-offset',(1-delivery).toFixed(4));
  style.setProperty('--handoff-marker-position',(delivery*100).toFixed(2)+'%');
  style.setProperty('--handoff-marker-opacity',p>.15&&p<.86?'1':'0');
  style.setProperty('--handoff-source-opacity',(1-.25*departure).toFixed(3));
  style.setProperty('--handoff-source-y',(-5*departure).toFixed(2)+'px');
  style.setProperty('--handoff-source-scale',(1-.025*departure).toFixed(4));
  style.setProperty('--handoff-target-opacity',(.74+.26*arrival).toFixed(3));
  style.setProperty('--handoff-target-y',(16*(1-arrival)).toFixed(2)+'px');
  style.setProperty('--handoff-target-scale',(.97+.03*arrival).toFixed(4));
  style.setProperty('--handoff-arrival-opacity',arrival.toFixed(3));
  style.setProperty('--handoff-title-opacity',smooth((p-.6)/.36).toFixed(3));
  style.setProperty('--handoff-title-y',(14*(1-smooth((p-.6)/.36))).toFixed(2)+'px');
  item.bridge.dataset.handoffProgress=p.toFixed(3);
  item.bridge.classList.toggle('is-bridging',p>.01&&p<.99);
  item.bridge.classList.toggle('is-delivered',p>=.94);
 }
 function draw(){
  frame=0;if(reduced.matches||!active)return;
  const item=active,rect=item.bridge.getBoundingClientRect();
  const stageHeight=item.stageHeight||280;
  const start=innerHeight*.62;
  const stickyTop=Math.min(150,Math.max(100,innerHeight*.16));
  const end=stickyTop+stageHeight-rect.height;
  const progress=(start-rect.top)/Math.max(180,start-end);
  applyProgress(item,progress);
 }
 function schedule(){if(!frame&&!reduced.matches)frame=requestAnimationFrame(draw);}
 const observer=new IntersectionObserver(entries=>{
  for(const entry of entries){const item=items.find(value=>value.bridge===entry.target);if(!item)continue;item.ratio=entry.intersectionRatio;if(entry.isIntersecting)visible.add(item);else visible.delete(item);}
  const next=[...visible].sort((a,b)=>b.ratio-a.ratio)[0]||null;
  if(next!==active)active=next;schedule();
 },{threshold:[0,.1,.25,.4,.5,.65,.8,1]});
 for(const item of items){applyProgress(item,reduced.matches?1:0);observer.observe(item.bridge);}
 if('ResizeObserver'in window){const resize=new ResizeObserver(entries=>{for(const entry of entries){const item=items.find(value=>value.stage===entry.target);if(item)item.stageHeight=entry.borderBoxSize?.[0]?.blockSize||entry.contentRect.height;}schedule();});for(const item of items)resize.observe(item.stage);}
 addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule,{passive:true});

 const overlay=node('div','chapter-transit-overlay');overlay.hidden=true;overlay.setAttribute('aria-hidden','true');
 const transit=node('div','chapter-transit-card'),route=node('div','chapter-transit-route'),fromText=node('span','chapter-transit-from'),toText=node('strong','chapter-transit-to'),relation=node('div','chapter-transit-relation');
 route.append(fromText,arrow('chapter-transit-arrow'),toText);transit.append(route,relation);overlay.append(transit);document.body.append(overlay);
 function hideOverlay(){clearTimeout(overlayTimer);overlay.hidden=true;overlay.classList.remove('is-crossing');overlay.getAnimations().forEach(animation=>animation.cancel());}
 function navigate(detail){
  if(!ready||reduced.matches||document.getElementById('opening-dialog')?.open)return;
  const from=resolveId(detail?.from)||currentId(),to=resolveId(detail?.to);if(!from||!to||from===to)return;
  const key=from+'>'+to,now=performance.now();if(key===lastRoute&&now-lastRouteAt<220)return;
  lastRoute=key;lastRouteAt=now;clearTimeout(overlayTimer);
  fromText.textContent=label(from);toText.textContent=label(to);relation.replaceChildren();
  const item=items.find(value=>value.id===from);
  if(item?.nextId===to){relation.append(node('span','',item.bridge.querySelector('.bridge-output strong')?.textContent||''),arrow('chapter-transit-evidence-arrow'),node('span','',item.bridge.querySelector('.bridge-input strong')?.textContent||''));}
  else relation.append(node('span','',chapterMap.get(to).querySelector('.chapter-thesis')?.textContent||''));
  overlay.dataset.from=from;overlay.dataset.to=to;overlay.hidden=false;
  // A fresh animation object restarts fast repeated navigation without a forced layout read.
  overlay.getAnimations().forEach(animation=>animation.cancel());
  overlay.classList.add('is-crossing');
  if(overlay.animate)overlay.animate([{opacity:0},{opacity:1,offset:.16},{opacity:1,offset:.64},{opacity:0}],{duration:900,easing:'linear',fill:'forwards'});
  overlayTimer=setTimeout(hideOverlay,910);
 }
 document.addEventListener('click',event=>{
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const link=event.target.closest?.('a[href^="#"]');if(!link||link.target==='_blank'||link.hasAttribute('download'))return;
  const to=resolveId(link.hash);if(to)navigate({from:currentId(),to});
 },true);
 addEventListener('showcase:navigate',event=>navigate(event.detail));
 reduced.addEventListener?.('change',()=>{hideOverlay();if(reduced.matches){if(frame)cancelAnimationFrame(frame);frame=0;for(const item of items)applyProgress(item,1);}else schedule();});
 Promise.resolve(window.Showcase?.ready).then(()=>{ready=true;schedule();});
 window.ShowcaseTransitions={navigate,refresh:schedule};
})();
