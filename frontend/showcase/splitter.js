/* One column ratio for the whole document; vertical scrolling remains shared. */
(function(){
 'use strict';
 const body=document.body,wide=matchMedia('(min-width:821px)'),key='studyagent.showcase.split.v1';
 const controls=[...document.querySelectorAll('[data-split-control]')];
 if(!controls.length)return;
 let requested=.6,applied=.6,drag=null,frame=0,pending=.6;
 try{const value=Number(sessionStorage.getItem(key));if(value>=.35&&value<=.75)requested=value;}catch{}
 function limits(grid){
  const width=grid?.getBoundingClientRect().width||document.querySelector('main').clientWidth;
  const gap=Number.parseFloat(getComputedStyle(body).getPropertyValue('--lane-gap'))||36;
  const available=Math.max(1,width-gap);
  return {min:Math.max(.35,Math.min(.5,300/available)),max:Math.min(.75,1-Math.min(.5,280/available)),available,gap};
 }
 function apply(value,save=false){
  const grid=document.querySelector('.topic-unit-grid:not(.topic-unit-shared)'),range=limits(grid);
  applied=wide.matches?Math.max(range.min,Math.min(range.max,value)):value;
  body.style.setProperty('--teaching-fr',applied+'fr');
  body.style.setProperty('--technical-fr',(1-applied)+'fr');
  const percent=Math.round(applied*100);
  for(const control of controls){control.setAttribute('aria-valuenow',String(percent));control.setAttribute('aria-valuemin',String(Math.round(range.min*100)));control.setAttribute('aria-valuemax',String(Math.round(range.max*100)));control.setAttribute('aria-valuetext','教学应用 '+percent+'%，技术实现 '+(100-percent)+'%');}
  if(save){requested=applied;try{sessionStorage.setItem(key,String(requested));}catch{}window.Showcase?.saveReading?.();}
  window.ShowcaseTransitions?.refresh();
 }
 function finish(event){
  if(!drag||event.pointerId!==drag.pointerId)return;
  if(frame){cancelAnimationFrame(frame);frame=0;apply(pending);}
  const control=drag.control;drag=null;body.classList.remove('is-resizing-lanes');
  if(control.hasPointerCapture(event.pointerId))control.releasePointerCapture(event.pointerId);
  apply(applied,true);
 }
 for(const control of controls){
  const divider=control.closest('[data-lane-divider]');
  divider.addEventListener('pointerdown',event=>{
   if(!wide.matches||event.button!==0||event.target.closest('button'))return;event.preventDefault();
   const grid=control.closest('.topic-unit-grid'),range=limits(grid);
   drag={pointerId:event.pointerId,control,left:grid.getBoundingClientRect().left,...range};
   control.setPointerCapture(event.pointerId);control.focus({preventScroll:true});body.classList.add('is-resizing-lanes');
  });
  control.addEventListener('pointermove',event=>{
   if(!drag||event.pointerId!==drag.pointerId)return;
   pending=(event.clientX-drag.left-drag.gap/2)/drag.available;
   if(!frame)frame=requestAnimationFrame(()=>{frame=0;apply(pending);});
  });
  for(const name of ['pointerup','pointercancel','lostpointercapture'])control.addEventListener(name,finish);
  divider.addEventListener('dblclick',event=>{if(!event.target.closest('button'))apply(.6,true);});
  control.addEventListener('keydown',event=>{
   const delta=event.shiftKey ? .1 : .02;
   if(!['ArrowLeft','ArrowRight','Home','End','Enter'].includes(event.key))return;event.preventDefault();
   const range=limits(control.closest('.topic-unit-grid'));
   apply(event.key==='Home'?range.min:event.key==='End'?range.max:event.key==='Enter' ? .6 : applied+(event.key==='ArrowRight'?delta:-delta),true);
  });
 }
 addEventListener('resize',()=>apply(requested),{passive:true});
 apply(requested);
 window.ShowcaseSplit={get ratio(){return applied;},reset(){apply(.6,true);}};
})();
