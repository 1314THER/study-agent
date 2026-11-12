/* A compact first reading, with all 63 changes retained in the document. */
(function(){
 'use strict';
 const chapter=document.getElementById('vision');if(!chapter)return;
 // The top-left skip pill belongs to this chapter only.
 if('IntersectionObserver'in window){
  const activeObserver=new IntersectionObserver(entries=>{for(const entry of entries)document.body.classList.toggle('is-vision-active',entry.isIntersecting);},{rootMargin:'-8% 0px -12% 0px'});
  activeObserver.observe(chapter);
 }
 const groups=[...chapter.querySelectorAll('[data-vision-group]')];
 const changes=[...chapter.querySelectorAll('.vision-change')];
 const outline=chapter.querySelector('.vision-outline');
 const media=matchMedia('(prefers-reduced-motion: reduce)');
 const storageKey='studyagent.showcase.vision.v1',disclosures=new Map();
 let raf=0,saved=null;
 try{
  const raw=sessionStorage.getItem(storageKey);
  if(raw&&raw.length<4096){const value=JSON.parse(raw);if(value?.version===1&&value.path===location.pathname&&value.groups&&typeof value.groups==='object'&&!Array.isArray(value.groups))saved=value.groups;}
 }catch{}
 function persist(){
  const values={};for(const [id,row]of disclosures)values[id]=!row.more.hidden;
  try{sessionStorage.setItem(storageKey,JSON.stringify({version:1,path:location.pathname,groups:values}));}catch{}
 }
 function refresh(){
  raf=0;
  const line=(outline?.getBoundingClientRect().bottom||0)+32;
  const active=groups.filter(group=>group.getBoundingClientRect().top<=line).at(-1)||groups[0];
  chapter.querySelectorAll('[data-vision-nav]').forEach(link=>{if(link.dataset.visionNav===active?.dataset.visionGroup)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});
  const current=changes.filter(change=>{const bounds=change.getBoundingClientRect();return bounds.top<innerHeight*.58&&bounds.bottom>line;}).at(-1);
  changes.forEach(change=>change.classList.toggle('is-current',change===current));
  // Floating collapse: only while the active group is expanded and its inline
  // control has scrolled out of the viewport.
  const row=active?disclosures.get(active.dataset.visionGroup):null;
  let show=false;
  if(row&&!row.more.hidden){
   const bounds=row.button.getBoundingClientRect();
   show=bounds.bottom<0||bounds.top>innerHeight;
  }
  floatButton.hidden=!show;
  if(show){
   floatButton.dataset.visionGroup=row.group.dataset.visionGroup;
   floatButton.querySelector('span').textContent='收起'+row.title+'的其余 '+row.remaining+' 项';
  }
  document.body.classList.toggle('has-vision-float',show);
 }
 function schedule(){if(!raf)raf=requestAnimationFrame(refresh);}
 // Collapsing removes everything below the control, so a reader deep inside the
 // list would be stranded. Bring the group's own control back under the sticky
 // bars, which is the point the list started from.
 function anchorAfterCollapse(row){
  if(!row)return;
  const bar=(chapter.querySelector('.vision-outline')?.getBoundingClientRect().bottom||0)+16;
  const rect=row.button.getBoundingClientRect();
  if(rect.top>=bar&&rect.top<=innerHeight*.55)return;
  const top=Math.max(0,scrollY+rect.top-bar);
  scrollTo({top,behavior:media.matches?'instant':'smooth'});
 }
 function setExpanded(id,expanded,{save=true,notify=true}={}){
  const row=disclosures.get(id);if(!row)return false;
  const changed=row.more.hidden===expanded;
  // The control precedes the changing content, so collapsing never removes
  // thousands of pixels above the button the reader is using.
  if(!expanded&&row.more.contains(document.activeElement))row.button.focus({preventScroll:true});
  if(!expanded&&row.more.contains(document.getElementById(location.hash.slice(1)))){
   const url=new URL(location.href);url.hash=row.group.id;history.replaceState(history.state,'',url);
  }
  row.more.hidden=!expanded;
  row.button.setAttribute('aria-expanded',String(expanded));
  row.button.setAttribute('aria-label',(expanded?'收起':'展开')+row.title+'的其余 '+row.remaining+' 项');
  row.button.querySelector('span').textContent=(expanded?'收起其余 ':'展开其余 ')+row.remaining+' 项';
  row.group.dataset.visionExpanded=String(expanded);
  if(!expanded&&notify)anchorAfterCollapse(row);
  if(save)persist();
  if(notify&&changed){
   dispatchEvent(new CustomEvent('showcase:layout-changed',{detail:{source:'vision',group:id,expanded}}));
   window.Showcase?.saveReading?.();
  }
  schedule();return changed;
 }
 for(const group of groups){
  const id=group.dataset.visionGroup,button=group.querySelector('[data-vision-toggle]'),more=group.querySelector('[data-vision-more]');
  if(!button||!more)continue;
  disclosures.set(id,{group,button,more,title:group.querySelector('h2')?.textContent||'',remaining:button.dataset.remaining});
  setExpanded(id,saved?.[id]===true,{save:false,notify:false});
  button.hidden=false;
  button.addEventListener('click',()=>setExpanded(id,button.getAttribute('aria-expanded')!=='true'));
 }
 // Once a group is expanded, a bottom-right companion keeps the collapse
 // control reachable; it hides when the inline control or the group leaves.
 const floatButton=document.createElement('button');
 floatButton.type='button';floatButton.className='vision-float';floatButton.hidden=true;
 floatButton.setAttribute('aria-label','收起当前展开的对照列表');
 floatButton.innerHTML='<span></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
 floatButton.addEventListener('click',()=>{const id=floatButton.dataset.visionGroup;if(id)setExpanded(id,false);});
 document.body.append(floatButton);
 function revealAnchor(hash){
  const target=document.getElementById(String(hash||'').replace(/^#/,''));
  const more=target?.closest('[data-vision-more]');
  return more?setExpanded(more.dataset.visionMore,true):false;
 }
 // This synchronous setup precedes the main reader's hydration and restoration.
 revealAnchor(location.hash);
 document.addEventListener('click',event=>{
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const link=event.target.closest?.('a[href^="#"]');if(link)revealAnchor(link.hash);
 },true);
 // The floating skip link is outside the chapter, but keyboard readers still
 // need focus to follow it to the destination heading.
 document.addEventListener('click',event=>{
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const link=event.target.closest('a[href^="#"]');if(!link)return;
  if(!chapter.contains(link)&&!link.hasAttribute('data-vision-skip'))return;
  const target=document.getElementById(link.hash.slice(1));if(!target)return;
  const heading=link.hasAttribute('data-vision-skip')?document.getElementById('heading-highlights'):target.querySelector('h2');
  if(heading)requestAnimationFrame(()=>heading.focus({preventScroll:true}));
 });
 addEventListener('hashchange',()=>{
  if(revealAnchor(location.hash))document.getElementById(location.hash.slice(1))?.scrollIntoView({behavior:'instant',block:'start'});
 });
 addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule,{passive:true});
 addEventListener('pageshow',schedule);addEventListener('showcase:reading-ready',schedule);
 window.ShowcaseVision={storageKey,setExpanded,reset(){for(const id of disclosures.keys())setExpanded(id,false,{save:false});try{sessionStorage.removeItem(storageKey);}catch{}},snapshot(){return Object.fromEntries([...disclosures].map(([id,row])=>[id,!row.more.hidden]));}};
 refresh();
})();
