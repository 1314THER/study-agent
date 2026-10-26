/* Progressive enhancement for the first chapter; all explanations are static HTML. */
(()=>{
 'use strict';
 const root=document.getElementById('highlights');
 if(!root)return;
 const figures=[...root.querySelectorAll('[data-hx-motion]')];
 if(!figures.length)return;
 const media=matchMedia('(prefers-reduced-motion: reduce)');
 const ns='http://www.w3.org/2000/svg';
 const motionEnabled=()=>!media.matches&&document.visibilityState!=='hidden'&&!document.body.classList.contains('is-launch-open');
 const active=new Set();
 const states=new Map(figures.map(figure=>[figure,{elapsed:0,manual:false,lastStage:-1,profile:'a',morph:null}]));
 const profiles={
  a:[[300,81],[410,152],[414,281],[300,250],[274,230],[264,194]],
  b:[[300,139],[360,181],[360,250],[300,284],[234,253],[186,150]],
 };
 let frame=0,lastTime=0,layoutFrame=0,ticking=false;
 const points=value=>value.map(pair=>pair.map(n=>Math.round(n*100)/100).join(',')).join(' ');
 const parsePoints=value=>(value||'').trim().split(/\s+/).map(pair=>pair.split(',').map(Number));
 function pressed(container,selector,selected){
  container.querySelectorAll(selector).forEach(button=>button.setAttribute('aria-pressed',String(button===selected)));
 }
 function setStage(figure,index){
  const state=states.get(figure);
  if(state.lastStage===index)return;
  state.lastStage=index;
  figure.dataset.hxStage=String(index);
  if(figure.dataset.hxMotion==='method'){
   const button=figure.querySelector('[data-hx-method="'+index+'"]');
   pressed(figure,'[data-hx-method]',button);
  }
 }
 function setProfile(figure,key,animate=true){
  const state=states.get(figure),shape=figure.querySelector('[data-hx-radar-shape]');
  if(!shape||!profiles[key])return;
  state.profile=key;
  figure.dataset.hxProfile=key;
  pressed(figure,'[data-hx-profile-button]',figure.querySelector('[data-hx-profile-button="'+key+'"]'));
  const ghost=figure.querySelector('.hx-radar-ghost');
  if(ghost)ghost.setAttribute('points',points(profiles[key==='a'?'b':'a']));
  if(animate&&!media.matches&&active.has(figure)&&document.visibilityState!=='hidden'){
   state.morph={from:parsePoints(shape.getAttribute('points')),to:profiles[key],elapsed:0};
   start();
  }else{
   state.morph=null;
   shape.setAttribute('points',points(profiles[key]));
  }
  syncRadarDots(figure);
 }
 function syncRadarDots(figure){
  const state=states.get(figure),group=figure.querySelector('[data-hx-radar-dots]');
  if(!group)return;
  const target=profiles[state.profile]||profiles.a;
  group.replaceChildren(...target.map((point,index)=>{
   const dot=document.createElementNS(ns,'circle');
   dot.setAttribute('cx',String(point[0]));dot.setAttribute('cy',String(point[1]));dot.setAttribute('r','5.5');
   dot.setAttribute('class','hx-radar-dot'+(String(index)===figure.dataset.hxDimensionActive?' is-selected':''));
   dot.dataset.hxDotDimension=String(index);
   dot.setAttribute('tabindex','0');dot.setAttribute('role','button');
   dot.setAttribute('aria-label','第'+(index+1)+'个维度，点击查看判断依据');
   return dot;
  }));
 }
 function flashRadarDot(dot){
  if(media.matches||!dot.animate)return;
  dot.animate([{transform:'scale(1)'},{transform:'scale(2.1)'},{transform:'scale(1)'}],{duration:480,easing:'cubic-bezier(.22,1,.36,1)'});
  const ripple=document.createElementNS(ns,'circle');
  ripple.setAttribute('cx',dot.getAttribute('cx'));ripple.setAttribute('cy',dot.getAttribute('cy'));ripple.setAttribute('r','6');
  ripple.setAttribute('class','hx-radar-ripple');
  dot.after(ripple);
  ripple.animate([{transform:'scale(1)',opacity:.75},{transform:'scale(3.6)',opacity:0}],{duration:640,easing:'ease-out'}).finished.then(()=>ripple.remove()).catch(()=>ripple.remove());
 }
 function selectDimension(figure,index){
  figure.dataset.hxDimensionActive=String(index);
  pressed(figure,'[data-hx-dimension]',figure.querySelector('[data-hx-dimension="'+index+'"]'));
  figure.querySelectorAll('[data-hx-evidence]').forEach(row=>row.classList.toggle('is-selected',Number(row.dataset.hxEvidence)===index));
  figure.querySelectorAll('[data-hx-axis]').forEach(axis=>axis.classList.toggle('is-selected',Number(axis.dataset.hxAxis)===index));
  figure.querySelectorAll('[data-hx-radar-dots] .hx-radar-dot').forEach(dot=>dot.classList.toggle('is-selected',Number(dot.dataset.hxDotDimension)===index));
 }
 function keyboardGroup(group,selector,activate){
  group.addEventListener('keydown',event=>{
   if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
   const buttons=[...group.querySelectorAll(selector)],index=buttons.indexOf(event.target);
   if(index<0)return;
   event.preventDefault();event.stopPropagation();
   const direction=['ArrowRight','ArrowDown'].includes(event.key)?1:-1;
   const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+direction+buttons.length)%buttons.length;
   buttons[next].focus({preventScroll:true});activate(buttons[next]);
  });
 }
 figures.forEach(figure=>{
  const state=states.get(figure);
  figure.querySelectorAll('[data-hx-controls]').forEach(group=>{
   group.hidden=false;
   // Keep local taps and swipes local, including on browsers with global gestures.
   group.addEventListener('touchstart',event=>event.stopPropagation(),{passive:true});
   group.addEventListener('touchend',event=>event.stopPropagation(),{passive:true});
  });
  if(figure.dataset.hxMotion==='method'){
   const choose=button=>{state.manual=true;setStage(figure,Number(button.dataset.hxMethod));};
   figure.querySelectorAll('[data-hx-method]').forEach(button=>button.addEventListener('click',()=>choose(button)));
   const group=figure.querySelector('.hx-method-controls');
   if(group)keyboardGroup(group,'[data-hx-method]',choose);
  }
  if(figure.dataset.hxMotion==='ability'){
   const choose=button=>{state.manual=true;setProfile(figure,button.dataset.hxProfileButton);};
   figure.querySelectorAll('[data-hx-profile-button]').forEach(button=>button.addEventListener('click',()=>choose(button)));
   const profilesGroup=figure.querySelector('.hx-profile-controls');
   if(profilesGroup)keyboardGroup(profilesGroup,'[data-hx-profile-button]',choose);
   const chooseDimension=button=>selectDimension(figure,Number(button.dataset.hxDimension));
   figure.querySelectorAll('[data-hx-dimension]').forEach(button=>button.addEventListener('click',()=>chooseDimension(button)));
   const dimensionsGroup=figure.querySelector('.hx-dimension-controls');
   if(dimensionsGroup)keyboardGroup(dimensionsGroup,'[data-hx-dimension]',chooseDimension);
   selectDimension(figure,0);
   syncRadarDots(figure);
   const dotsGroup=figure.querySelector('[data-hx-radar-dots]');
   dotsGroup?.addEventListener('click',event=>{
    const dot=event.target.closest?.('.hx-radar-dot');
    if(!dot)return;
    selectDimension(figure,Number(dot.dataset.hxDotDimension));
    flashRadarDot(dot);
   });
  }
 });
 function hasWork(){
  if(!motionEnabled())return false;
  return [...active].some(figure=>{
   const state=states.get(figure),type=figure.dataset.hxMotion;
   return Boolean(state.morph)||(!state.manual&&['method','ability','participation','evolution'].includes(type));
  });
 }
 function start(){if(!frame&&!ticking&&hasWork()){lastTime=0;frame=requestAnimationFrame(tick);}}
 function tick(now){
  frame=0;
  if(!hasWork())return;
  ticking=true;
  const delta=lastTime?Math.min(64,now-lastTime):0;
  lastTime=now;
  active.forEach(figure=>{
   const state=states.get(figure),type=figure.dataset.hxMotion;
   if(!state.manual){
    state.elapsed+=delta;
    if(type==='method')setStage(figure,Math.floor(state.elapsed/3200)%3);
    else if(type==='participation')setStage(figure,Math.floor(state.elapsed/3600)%3);
    else if(type==='evolution')setStage(figure,Math.floor(state.elapsed/3000)%4);
    else if(type==='ability'){
     const key=Math.floor(state.elapsed/6500)%2?'b':'a';
     if(state.profile!==key)setProfile(figure,key,true);
    }
   }
   if(state.morph){
    state.morph.elapsed+=delta;
    const t=Math.min(1,state.morph.elapsed/950),ease=1-Math.pow(1-t,3);
    const value=state.morph.from.map((pair,index)=>pair.map((n,axis)=>n+(state.morph.to[index][axis]-n)*ease));
    figure.querySelector('[data-hx-radar-shape]').setAttribute('points',points(value));
    if(t===1)state.morph=null;
   }
  });
  ticking=false;
  if(hasWork())frame=requestAnimationFrame(tick);
 }
 function pathNode(path,className,marker){
  const node=document.createElementNS(ns,'path');
  node.setAttribute('d',path);node.setAttribute('class',className);
  if(marker)node.setAttribute('marker-end','url(#'+marker+')');
  return node;
 }
 function renderGraph(graph){
  const svg=graph.querySelector('[data-hx-wires]');
  if(!svg)return;
  let edges;
  try{edges=JSON.parse(svg.dataset.hxEdges);}catch{return;}
  const box=graph.getBoundingClientRect();
  if(box.width<1||box.height<1)return;
  const ports={};
  graph.querySelectorAll('[data-hx-port]').forEach(port=>{
   const rect=port.getBoundingClientRect();
   ports[port.dataset.hxPort]={left:rect.left-box.left,right:rect.right-box.left,top:rect.top-box.top,bottom:rect.bottom-box.top,width:rect.width,height:rect.height};
  });
  const paths=[];
  edges.forEach(([from,to,kind],index)=>{
   const a=ports[from],b=ports[to];if(!a||!b)return;
   let path;
   if(kind==='return'){
    const sy=a.top+a.height/2,ey=b.top+b.height/2;
    path=`M${a.left},${sy}H6V${ey}H${b.left-1}`;
   }else if(kind==='merge'){
    const sx=a.left+a.width/2,sy=a.bottom+1,ex=b.left+b.width*(.3+index*.2),ey=b.top-3,mid=sy+(ey-sy)*.52;
    path=`M${sx},${sy}C${sx},${mid} ${ex},${mid} ${ex},${ey}`;
   }else{
    // The main architecture uses one quiet connector between each layer.
    const sx=a.left+15,sy=a.bottom+2,ex=b.left+15,ey=b.top-3;
    path=`M${sx},${sy}C${sx},${(sy+ey)/2} ${ex},${(sy+ey)/2} ${ex},${ey}`;
   }
   paths.push({path,kind,index});
  });
  svg.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);
  const group=document.createElementNS(ns,'g');group.setAttribute('data-hx-path-group','');
  paths.forEach(({path,kind,index})=>{
   group.append(pathNode(path,'hx-wire'+(kind==='return'?' hx-wire-return':''),svg.dataset.hxMarker));
   const signal=pathNode(path,'hx-wire-signal');
   signal.style.animationDelay=String(index*-.73)+'s';group.append(signal);
  });
  svg.querySelector('[data-hx-path-group]')?.remove();svg.append(group);
  graph.classList.add('hx-connected');
 }
 const graphs=[...root.querySelectorAll('[data-hx-graph]')];
 function queueLayout(){
  if(layoutFrame)return;
  layoutFrame=requestAnimationFrame(()=>{layoutFrame=0;graphs.forEach(renderGraph);});
 }
 if('ResizeObserver' in window){
  const resizeObserver=new ResizeObserver(queueLayout);
  graphs.forEach(graph=>resizeObserver.observe(graph));
 }else addEventListener('resize',queueLayout,{passive:true});
 document.fonts?.ready.then(queueLayout);
 queueLayout();
 if('IntersectionObserver' in window){
  const observer=new IntersectionObserver(entries=>{
   entries.forEach(({target,isIntersecting,intersectionRatio})=>{
    const visible=isIntersecting&&intersectionRatio>0;
    target.classList.toggle('is-hx-visible',visible&&motionEnabled());
    if(visible){
     active.add(target);target.classList.add('is-hx-revealed');target.classList.remove('hx-reveal-pending');
    }else active.delete(target);
   });
   start();
  },{threshold:[0,.08,.25],rootMargin:'0px 0px -3% 0px'});
  figures.forEach(figure=>{if(!media.matches)figure.classList.add('hx-reveal-pending');observer.observe(figure);});
 }else figures.forEach(figure=>{active.add(figure);figure.classList.add('is-hx-visible','is-hx-revealed');});
 function updateMotion(){
  const enabled=motionEnabled();
  figures.forEach(figure=>{
   figure.classList.toggle('is-hx-visible',enabled&&active.has(figure));
   if(media.matches){figure.classList.remove('hx-reveal-pending');figure.classList.add('is-hx-revealed');}
   const state=states.get(figure);
   if(!enabled&&state.morph){
    figure.querySelector('[data-hx-radar-shape]')?.setAttribute('points',points(profiles[state.profile]));state.morph=null;
   }
  });
  if(!enabled&&frame){cancelAnimationFrame(frame);frame=0;lastTime=0;}
  start();
 }
 const features=[...root.querySelectorAll('.highlight-feature')];
 const pendingFeatures=new Set(features);
 function revealFeature(feature){
  if(!pendingFeatures.has(feature))return;
  pendingFeatures.delete(feature);feature.classList.remove('hx-feature-pending');feature.classList.add('hx-feature-revealed');
 }
 function syncFeatures(){
  if(document.body.classList.contains('is-launch-open'))return;
  for(const feature of pendingFeatures){const r=feature.getBoundingClientRect();if(media.matches||r.top<innerHeight*.94)revealFeature(feature);}
 }
 if('IntersectionObserver'in window){
  const featureObserver=new IntersectionObserver(entries=>{if(document.body.classList.contains('is-launch-open'))return;for(const entry of entries)if(entry.isIntersecting||entry.boundingClientRect.bottom<0)revealFeature(entry.target);},{rootMargin:'0px 0px -6% 0px'});
  features.forEach(feature=>{if(!media.matches)feature.classList.add('hx-feature-pending');featureObserver.observe(feature);});
 }else features.forEach(revealFeature);
 addEventListener('showcase:entered',syncFeatures);media.addEventListener?.('change',syncFeatures);syncFeatures();
 media.addEventListener?.('change',updateMotion);
 document.addEventListener('visibilitychange',updateMotion);
 addEventListener('showcase:entered',updateMotion);
 start();
})();
