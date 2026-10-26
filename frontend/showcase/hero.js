/* A separate opening screen; red ink arrives before the glass CTA lights up. */
(function(){
'use strict';
const stage=document.getElementById('hero-art'),cta=document.getElementById('explore-start'),dialog=document.getElementById('launch-screen');
if(!stage||!cta||!dialog)return;
const artwork=stage.querySelector('.hero-love'),pen=artwork.querySelector('.pen-reveal');
const mathInk=artwork.querySelector('.math-ink'),outline=mathInk.cloneNode(false);
outline.setAttribute('class','math-outline');outline.setAttribute('pathLength','1');
outline.style.fill='none';outline.setAttribute('aria-hidden','true');mathInk.before(outline);
const link=stage.querySelector('.hero-ink-link'),stroke=document.getElementById('hero-ink-path');
// A pure-black guard sits between the red strokes and the CTA: anything that
// reaches the button box is covered, so red never paints over the button.
const guard=document.createElement('i');
guard.className='hero-cta-guard';
stage.append(guard);
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let sequence=0,animations=[],resizeFrame=0,resolveEntry=null,entryPromise=null,leaving=false,glass=null,streamCancel=null;
let streaming=[];
function layout(){
 const r=stage.getBoundingClientRect(),b=cta.getBoundingClientRect(),matrix=artwork.getScreenCTM();
 if(!matrix||!r.width||!r.height)return;
 // The tapered end of the red e flourish; the CTA is placed from this point
 // so its left edge receives the stroke on the same baseline.
 const tip=new DOMPoint(663,257).matrixTransform(matrix),x=tip.x-r.left,y=tip.y-r.top;
 const left=Math.min(r.width-b.width,Math.max(x+8,0));
 const top=Math.max(0,Math.min(r.height-b.height,y-b.height/2));
 cta.style.left=`${left}px`;cta.style.top=`${top}px`;cta.style.right='auto';cta.style.bottom='auto';
 const endX=left,endY=top+b.height/2;
 link.setAttribute('viewBox',`0 0 ${r.width} ${r.height}`);
 const reach=Math.max(1,endX-x),bend=Math.min(14,reach*.16);
 stroke.setAttribute('d',`M${x} ${y} C${x+reach*.34} ${y-bend} ${endX-reach*.28} ${endY+bend} ${endX} ${endY}`);
 // The guard covers the button box plus a hair of breathing room.
 guard.style.left=(b.left-r.left-8)+'px';
 guard.style.top=(b.top-r.top-8)+'px';
 guard.style.width=(b.width+16)+'px';
 guard.style.height=(b.height+16)+'px';
}
function restoreCopy(){for(const row of streaming){row.node.replaceChildren(...row.original);row.node.classList.remove('is-streaming','is-stream-current');}streaming=[];}
function stop(){streamCancel?.();streamCancel=null;restoreCopy();for(const animation of animations)animation.cancel();animations=[];}
function finish(){
 restoreCopy();mathInk.style.fillOpacity='1';outline.style.opacity='0';
 pen.style.strokeDashoffset='0';stroke.style.strokeDashoffset='0';
 stage.dataset.phase='ready';cta.classList.add('is-lit');
}
async function streamCopy(run){
 const nodes=[...dialog.querySelectorAll('#launch-title>span,.hero-subtitle,.hero-manifesto>p')];
 const speeds=[20,20,7,8,5];
 streaming=nodes.map((node,index)=>{
  const original=[...node.childNodes],text=Array.from(node.textContent),source=document.createElement('span'),output=document.createElement('span');
  source.className='stream-source';source.textContent=text.join('');output.className='stream-output';output.setAttribute('aria-hidden','true');
  node.classList.add('is-streaming');node.replaceChildren(source,output);
  return {node,original,text,output,duration:Math.max(100,text.length*(speeds[index]||6))};
 });
 for(const row of streaming){
  if(run!==sequence)return;
  row.node.classList.add('is-stream-current');
  await new Promise(resolve=>{
   let frame=0,start=null;
   const done=()=>{cancelAnimationFrame(frame);streamCancel=null;resolve();};streamCancel=done;
   const tick=now=>{
    if(run!==sequence){done();return;}
    if(start===null)start=now;
    const count=Math.min(row.text.length,Math.floor((now-start)/row.duration*row.text.length));
    row.output.textContent=row.text.slice(0,count).join('');
    if(count>=row.text.length){done();return;}frame=requestAnimationFrame(tick);
   };
   frame=requestAnimationFrame(tick);
  });
  if(run!==sequence)return;
  row.node.classList.remove('is-stream-current');
 }
 restoreCopy();
}
async function play(){
 const run=++sequence;stop();layout();cta.classList.remove('is-lit');
 if(reduced.matches||!pen.animate){finish();return;}
 stage.dataset.phase='typing';mathInk.style.fillOpacity='0';outline.style.opacity='0';pen.style.strokeDashoffset='1';stroke.style.strokeDashoffset='1';
 try{
  await streamCopy(run);if(run!==sequence)return;
  stage.dataset.phase='math-writing';outline.style.opacity='1';
  const whiteStroke=outline.animate([{strokeDashoffset:1},{strokeDashoffset:0}],{duration:820,easing:'cubic-bezier(.25,.5,.25,1)',fill:'forwards'});
  const whiteFill=mathInk.animate([{fillOpacity:0,offset:0},{fillOpacity:0,offset:.45},{fillOpacity:1,offset:1}],{duration:820,fill:'forwards'});
  animations.push(whiteStroke,whiteFill);await Promise.all([whiteStroke.finished,whiteFill.finished]);if(run!==sequence)return;
  mathInk.style.fillOpacity='1';outline.style.opacity='0';whiteStroke.cancel();whiteFill.cancel();stage.dataset.phase='writing';
  const lettering=pen.animate([{strokeDashoffset:1},{strokeDashoffset:0}],{duration:1500,easing:'cubic-bezier(.12,.75,.25,1)',fill:'forwards'});
  animations.push(lettering);await lettering.finished;if(run!==sequence)return;
  pen.style.strokeDashoffset='0';lettering.cancel();stage.dataset.phase='connecting';
  const connection=stroke.animate([{strokeDashoffset:1},{strokeDashoffset:0}],{duration:600,easing:'cubic-bezier(.2,.65,.25,1)',fill:'forwards'});
  animations.push(connection);await connection.finished;if(run!==sequence)return;
  stroke.style.strokeDashoffset='0';connection.cancel();finish();
 }catch{if(run===sequence)finish();}
}
if('ResizeObserver'in window){
 const observer=new ResizeObserver(()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(layout);});
 observer.observe(stage);observer.observe(cta);
}else addEventListener('resize',layout,{passive:true});
reduced.addEventListener('change',()=>{if(reduced.matches){sequence++;stop();finish();}});
function completeEntry(){
 // Cleanup must not depend on an open() promise: the inline bootstrap can open
 // the dialog before this module runs, and a skipped cleanup would leave the
 // page scroll-locked.
 const resolve=resolveEntry;resolveEntry=null;entryPromise=null;
 document.body.classList.remove('is-launch-open','is-entering-site');
 dialog.classList.remove('is-leaving');leaving=false;
 const url=new URL(location.href);url.hash='vision';history.replaceState(history.state,'',url);
 document.getElementById('vision')?.scrollIntoView({behavior:'instant',block:'start'});
 document.getElementById('heading-vision')?.focus({preventScroll:true});
 dispatchEvent(new CustomEvent('showcase:entered'));
 resolve?.();
}
function enter(event){
 if(!dialog.open)return;
 if(event?.type==='click'&&(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey))return;
 event?.preventDefault();if(leaving)return;leaving=true;
 sequence++;stop();finish();dialog.classList.add('is-leaving');
 const close=()=>{if(dialog.open)dialog.close();completeEntry();};
 if(reduced.matches||!dialog.animate){close();return;}
 document.body.classList.add('is-entering-site');
 const exit=dialog.animate([{transform:'translate3d(0,0,0)'},{transform:'translate3d(0,-100%,0)'}],{duration:560,easing:'cubic-bezier(.22,.7,.22,1)',fill:'forwards'});
 exit.finished.then(()=>{close();exit.cancel();},close);
}
function initGlass(){
 if(!glass&&window.liquidGlass)glass=window.liquidGlass(cta.querySelector('.explore-glass'),{scale:-55,chroma:2,border:.12,mapBlur:10,blur:2,saturate:1.2,fallbackBlur:14});
 glass?.refresh();
}
function open({skip=false,force=false}={}){
 if(dialog.open)return entryPromise||Promise.resolve();
 if(skip&&!force){finish();return Promise.resolve();}
 entryPromise=new Promise(resolve=>{resolveEntry=resolve;});
 document.body.classList.add('is-launch-open');dialog.showModal();
 layout();
 initGlass();
 void play();document.getElementById('launch-title')?.focus({preventScroll:true});
 return entryPromise;
}
cta.addEventListener('click',enter);
dialog.addEventListener('cancel',enter);
dialog.addEventListener('close',completeEntry);
window.ShowcaseHero={open,enter,replay:play,layout};
// Font loading can move the CTA; keep the guard aligned with it.
document.fonts?.ready.then(()=>layout());
// The welcome screen opens while the document is still parsing (inline
// bootstrap); start its choreography right away instead of after data loads.
if(dialog.open){
 document.body.classList.add('is-launch-open');
 layout();
 initGlass();
 void play();
 document.getElementById('launch-title')?.focus({preventScroll:true});
}
})();
