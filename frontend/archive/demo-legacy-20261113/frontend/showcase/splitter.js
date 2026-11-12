/* Lane ratios are tuned per unit and remembered independently per visitor. */
(function(){
 'use strict';
 const body=document.body,wide=matchMedia('(min-width:821px)'),key='studyagent.showcase.split.v2';
 const controls=[...document.querySelectorAll('[data-split-control]')];
 if(!controls.length)return;
 // Content-aware defaults: visual-heavy units give the teaching lane more room,
 // text-heavy units lean slightly toward the technical side.
 const DEFAULTS={concepts:.55,single:.66,diagnosis:.66,library:.68,routines:.6,exam:.62,
                 career:.58,teacher:.56,school:.54,modes:.6,agent:.6,mcp:.56,evolution:.58};
 const grids=[...document.querySelectorAll('.topic-unit-grid:not(.topic-unit-shared):not(.is-single)')]
   .map(grid=>({grid,unit:grid.closest('[data-source-id]')?.dataset.sourceId||''}));
 let saved={};
 try{const raw=sessionStorage.getItem(key);if(raw){const value=JSON.parse(raw);if(value&&typeof value==='object'&&!Array.isArray(value))saved=value;}}catch{}
 const ratioFor=unit=>{const fallback=DEFAULTS[unit]??.6,value=Number(saved[unit]);return value>=.35&&value<=.75?value:fallback;};
 const ratios=new Map(grids.map(row=>[row.unit,ratioFor(row.unit)]));
 function limits(grid){
  const width=grid?.getBoundingClientRect().width||document.querySelector('main').clientWidth;
  const gap=Number.parseFloat(getComputedStyle(body).getPropertyValue('--lane-gap'))||36;
  const available=Math.max(1,width-gap);
  return {min:Math.max(.35,Math.min(.5,300/available)),max:Math.min(.75,1-Math.min(.5,280/available)),available,gap};
 }
 function syncHeadings(){
  // Column headings follow the first unit of their topic.
  for(const section of document.querySelectorAll('.topic-section')){
   const heading=section.querySelector('.perspective-headings');
   const first=section.querySelector('.topic-unit-grid:not(.topic-unit-shared)');
   if(!heading||!first)continue;
   heading.style.setProperty('--teaching-fr',first.style.getPropertyValue('--teaching-fr')||'');
   heading.style.setProperty('--technical-fr',first.style.getPropertyValue('--technical-fr')||'');
  }
 }
 function applyUnit(unit,value,save=false){
  const row=grids.find(item=>item.unit===unit);if(!row)return;
  const range=limits(row.grid);
  const applied=wide.matches?Math.max(range.min,Math.min(range.max,value)):value;
  ratios.set(unit,applied);
  row.grid.style.setProperty('--teaching-fr',applied+'fr');
  row.grid.style.setProperty('--technical-fr',(1-applied)+'fr');
  const percent=Math.round(applied*100);
  const control=row.grid.querySelector('[data-split-control]');
  if(control){
   control.setAttribute('aria-valuenow',String(percent));
   control.setAttribute('aria-valuemin',String(Math.round(range.min*100)));
   control.setAttribute('aria-valuemax',String(Math.round(range.max*100)));
   control.setAttribute('aria-valuetext','教学应用 '+percent+'%，技术实现 '+(100-percent)+'%');
  }
  syncHeadings();
  if(save){saved[unit]=applied;try{sessionStorage.setItem(key,JSON.stringify(saved));}catch{}window.Showcase?.saveReading?.();}
  window.ShowcaseTransitions?.refresh();
 }
 let drag=null,frame=0,pending=.6;
 function finish(event){
  if(!drag||event.pointerId!==drag.pointerId)return;
  const unit=drag.unit,control=drag.control;
  if(frame){cancelAnimationFrame(frame);frame=0;applyUnit(unit,pending);}
  drag=null;body.classList.remove('is-resizing-lanes');
  if(control.hasPointerCapture(event.pointerId))control.releasePointerCapture(event.pointerId);
  applyUnit(unit,ratios.get(unit)||pending,true);
 }
 function dragUnitFromControl(control){
  return control.closest('.topic-unit-grid')?.closest('[data-source-id]')?.dataset.sourceId
      ||control.closest('[data-source-id]')?.dataset.sourceId||'';
 }
 for(const control of controls){
  const divider=control.closest('[data-lane-divider]');
  divider.addEventListener('pointerdown',event=>{
   if(!wide.matches||event.button!==0||event.target.closest('button'))return;event.preventDefault();
   const unit=dragUnitFromControl(control),row=grids.find(item=>item.unit===unit);if(!row)return;
   const grid=row.grid,range=limits(grid);
   drag={pointerId:event.pointerId,control,unit,left:grid.getBoundingClientRect().left,...range};
   control.setPointerCapture(event.pointerId);control.focus({preventScroll:true});body.classList.add('is-resizing-lanes');
  });
  control.addEventListener('pointermove',event=>{
   if(!drag||event.pointerId!==drag.pointerId)return;
   pending=(event.clientX-drag.left-drag.gap/2)/drag.available;
   if(!frame)frame=requestAnimationFrame(()=>{frame=0;applyUnit(drag.unit,pending);});
  });
  for(const name of ['pointerup','pointercancel','lostpointercapture'])control.addEventListener(name,finish);
  divider.addEventListener('dblclick',event=>{
   if(!event.target.closest('button')){const unit=dragUnitFromControl(control);applyUnit(unit,DEFAULTS[unit]??.6,true);}
  });
  control.addEventListener('keydown',event=>{
   const unit=dragUnitFromControl(control),current=ratios.get(unit)??.6;
   const delta=event.shiftKey ? .1 : .02;
   if(!['ArrowLeft','ArrowRight','Home','End','Enter'].includes(event.key))return;event.preventDefault();
   const range=limits(control.closest('.topic-unit-grid'));
   applyUnit(unit,event.key==='Home'?range.min:event.key==='End'?range.max:event.key==='Enter'?(DEFAULTS[unit]??.6):current+(event.key==='ArrowRight'?delta:-delta),true);
  });
 }
 addEventListener('resize',()=>{for(const row of grids)applyUnit(row.unit,ratios.get(row.unit));},{passive:true});
 for(const row of grids)applyUnit(row.unit,ratios.get(row.unit));
 window.ShowcaseSplit={ratio:unit=>ratios.get(unit),reset:unit=>{for(const row of grids)if(!unit||row.unit===unit)applyUnit(row.unit,DEFAULTS[row.unit]??.6,true);}};
})();
