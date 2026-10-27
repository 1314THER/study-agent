/* Fixed teaching galaxies, with a translated camera on narrow screens. */
(()=>{
 'use strict';
 const chapter=document.getElementById('vision');if(!chapter)return;
 const dialog=document.getElementById('vision-dialog'),body=dialog.querySelector('.vision-dialog-body'),title=dialog.querySelector('h2');
 const mobile=matchMedia('(max-width:719px)'),reduced=matchMedia('(prefers-reduced-motion: reduce)'),ns='http://www.w3.org/2000/svg';
 let ready=false,active=null,frame=0,opened=null,layoutFrame=0,returnFocus=null;
 const groups=[...chapter.querySelectorAll('[data-vision-group]')].map(group=>({group,id:group.dataset.visionGroup,viewport:group.querySelector('.vision-viewport'),world:group.querySelector('.vision-world'),svg:group.querySelector('svg'),nodes:[...group.querySelectorAll('.vision-change')],index:0,timer:0,animation:null,points:[],segments:[]}));
 const aspectMap=new Map();
 const ellipse=(ring,t)=>({x:ring.cx+ring.rx*Math.cos(t),y:ring.cy+ring.ry*Math.sin(t)});
 const cubic=(a,b,t)=>{const y=Math.min(a.y,b.y)-65,u=1-t;return {x:u*u*u*a.x+3*u*u*t*a.x+3*u*t*t*b.x+t*t*t*b.x,y:u*u*u*a.y+3*u*u*t*y+3*u*t*t*y+t*t*t*b.y};};
 function stop(row){clearTimeout(row.timer);row.timer=0;if(row.animation){row.animation.cancel();row.animation=null;}if(mobile.matches&&row.points.length)position(row,row.points[row.index]);}
 function position(row,point){row.world.style.transform=mobile.matches?'translate3d('+(row.viewport.clientWidth/2-point.x)+'px,'+(row.viewport.clientHeight/2-point.y)+'px,0)':'';}
 function mark(row,manual=false){row.nodes.forEach((node,index)=>{const b=node.querySelector('.vision-card');b.tabIndex=mobile.matches&&index!==row.index?-1:0;b.setAttribute('aria-current',String(index===row.index));});row.group.querySelector('.vision-camera-count').textContent=(row.index+1)+' / '+row.nodes.length;if(manual)row.group.querySelector('[role=status]').textContent=row.nodes[row.index].dataset.aspect;}
 function choose(row,index,manual=false){stop(row);row.index=(index+row.nodes.length)%row.nodes.length;position(row,row.points[row.index]);mark(row,manual);}
 function eligible(row){return ready&&mobile.matches&&!reduced.matches&&active===row&&document.visibilityState==='visible'&&!document.querySelector('dialog[open]')&&!row.group.querySelector(':focus-visible');}
 function start(row){if(row.timer||row.animation||!eligible(row))return;row.timer=setTimeout(()=>{
  row.timer=0;if(!eligible(row))return;
  const points=row.segments[row.index],width=row.viewport.clientWidth,height=row.viewport.clientHeight;
  row.animation=row.world.animate(points.map(p=>({transform:'translate3d('+(width/2-p.x)+'px,'+(height/2-p.y)+'px,0)'})),{duration:600,easing:'ease-in-out',fill:'forwards'});
  const animation=row.animation;
  animation.finished.then(()=>{if(row.animation!==animation)return;row.index=(row.index+1)%row.nodes.length;position(row,row.points[row.index]);row.animation=null;animation.cancel();mark(row);start(row);}).catch(()=>{});
 },2000);}
 function refresh(){frame=0;
  const candidates=groups.map(row=>({row,rect:row.viewport.getBoundingClientRect()})).filter(x=>x.rect.bottom>0&&x.rect.top<innerHeight);
  active=candidates.sort((a,b)=>Math.abs((a.rect.top+a.rect.bottom)/2-innerHeight/2)-Math.abs((b.rect.top+b.rect.bottom)/2-innerHeight/2))[0]?.row||null;
  document.body.classList.toggle('is-vision-active',chapter.getBoundingClientRect().bottom>innerHeight*.12&&chapter.getBoundingClientRect().top<innerHeight*.92);
  chapter.querySelectorAll('[data-vision-nav]').forEach(link=>{if(link.dataset.visionNav===active?.id)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});
  groups.forEach(row=>{if(eligible(row))start(row);else stop(row);});
 }
 function schedule(){if(!frame)frame=requestAnimationFrame(refresh);}
 function layout(row){
  stop(row);const phone=mobile.matches,band=phone||innerWidth>=1100?0:innerWidth>=900?1:2,social=row.id==='society';
  const w=phone?1200:Math.min(1200,row.viewport.clientWidth),h=(social?[460,480,520]:[600,640,720])[band],cw=[144,124,108][band],ch=[56,52,48][band],margin=[16,14,12][band];
  row.group.style.setProperty('--world-w',w+'px');row.group.style.setProperty('--world-h',h+'px');row.group.style.setProperty('--card-w',cw+'px');row.group.style.setProperty('--card-h',ch+'px');row.group.style.setProperty('--card-font',[14,13,12.5][band]+'px');
  row.world.style.width=w+'px';row.world.style.height=h+'px';row.svg.setAttribute('viewBox','0 0 '+w+' '+h);row.svg.replaceChildren();
  const outer={cx:w/2,cy:h/2,rx:(w-cw)/2-margin,ry:(h-ch)/2-margin},inner={cx:w/2,cy:h/2,rx:w*[.25,.24,.21][band],ry:h*(row.id==='students'?[.23,.27,.31]:[.22,.22,.23])[band]};
  const outerCount=social?8:row.id==='students'?13:11;
  const rings=social?[outer]:[outer,inner];
  rings.forEach(r=>{const e=document.createElementNS(ns,'ellipse');for(const key of ['cx','cy','rx','ry'])e.setAttribute(key,r[key]);row.svg.append(e);});
  const entries=row.nodes.map((node,i)=>{const ring=i<outerCount?outer:inner,start=i<outerCount?0:outerCount,count=i<outerCount?outerCount:row.nodes.length-outerCount,angle=-Math.PI/2+(i-start)*Math.PI*2/count;const point=ellipse(ring,angle);node.style.setProperty('--node-x',point.x+'px');node.style.setProperty('--node-y',point.y+'px');return {ring,angle,count,point};});
  row.points=entries.map(e=>e.point);row.segments=entries.map((entry,i)=>{
   const next=entries[(i+1)%entries.length],same=entry.ring===next.ring;
   const points=Array.from({length:33},(_,k)=>same?ellipse(entry.ring,entry.angle+(Math.PI*2/entry.count)*k/32):cubic(entry.point,next.point,k/32));
   if(!same){const p=document.createElementNS(ns,'path');p.setAttribute('d',points.map((v,j)=>(j?'L':'M')+v.x+' '+v.y).join(' '));row.svg.append(p);}return points;
  });
  row.group.querySelector('.vision-camera-controls').hidden=!phone;position(row,row.points[row.index]);mark(row);
 }
 function relayout(){cancelAnimationFrame(layoutFrame);layoutFrame=requestAnimationFrame(()=>{groups.forEach(layout);schedule();});}
 function restoreFocus(){const saved=returnFocus;if(!saved||aspectMap.has(location.hash.slice(1)))return;returnFocus=null;requestAnimationFrame(()=>requestAnimationFrame(()=>{if(!dialog.open&&saved.node.isConnected){scrollTo({top:saved.y,behavior:'instant'});saved.node.querySelector('.vision-card').focus({preventScroll:true});}}));}
 function closePanel(updateUrl=true,restore=true){
  if(!opened)return;const saved=opened;opened=null;returnFocus=restore?{node:saved.node,y:saved.returnY}:null;dialog.close();body.replaceChildren();
  if(updateUrl&&location.hash==='#'+saved.node.id){if(history.state?.visionDialog===saved.node.id)history.back();else{const u=new URL(location.href);u.hash='vision-'+saved.row.id;history.replaceState(null,'',u);}}
  restoreFocus();schedule();
 }
 function openPanel(row,index,push=false){
  returnFocus=null;const node=row.nodes[index];choose(row,index);if(opened?.node===node)return;
  const returnY=scrollY,returnHash=location.hash||'#vision-'+row.id;
  if(push&&location.hash!=='#'+node.id){const u=new URL(location.href);u.hash=node.id;history.pushState({...history.state,visionDialog:node.id,visionReturn:location.hash||'#vision-'+row.id},'',u);}
  const clone=node.querySelector('.vision-detail').cloneNode(true);
  clone.querySelectorAll('[id]').forEach(el=>{const old=el.id;el.id=old+'-modal';clone.querySelectorAll('[stroke]').forEach(path=>{if(path.getAttribute('stroke')==='url(#'+old+')')path.setAttribute('stroke','url(#'+el.id+')');});});
  title.textContent=row.group.querySelector('h2').textContent+' · '+node.dataset.aspect;body.replaceChildren(clone);opened={row,node,returnY,returnHash};if(!dialog.open)dialog.showModal();schedule();
 }
 function resolveAnchor(hash){const value=aspectMap.get(String(hash).replace(/^#/,''));if(!value)return null;choose(value.row,value.index);return mobile.matches?value.row.group:value.node;}
 function hashChanged(){const value=aspectMap.get(location.hash.slice(1));if(value){resolveAnchor(location.hash);if(ready)openPanel(value.row,value.index);}else if(opened)closePanel(false,location.hash===opened.returnHash||location.hash==='#vision-'+opened.row.id);restoreFocus();schedule();}
 groups.forEach(row=>{
  row.nodes.forEach((node,index)=>{aspectMap.set(node.id,{row,index});const b=node.querySelector('.vision-card');b.hidden=false;node.querySelector('details').hidden=true;b.addEventListener('click',()=>openPanel(row,index,true));b.addEventListener('focus',()=>{if(mobile.matches&&index!==row.index)choose(row,index);schedule();});});
  row.group.querySelectorAll('[data-camera-step]').forEach(b=>b.addEventListener('click',()=>{choose(row,row.index+Number(b.dataset.cameraStep),true);schedule();}));
 });
 chapter.classList.add('vision-enhanced');groups.forEach(layout);
 dialog.querySelector('.vision-dialog-close').addEventListener('click',()=>closePanel());dialog.addEventListener('cancel',e=>{e.preventDefault();closePanel();});
 dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closePanel();}const link=event.target.closest('a[href^="#"]');if(link){const returnHash=history.state?.visionReturn||'#vision-'+opened.row.id;history.replaceState(null,'',returnHash);closePanel(false,false);}});
 chapter.addEventListener('focusin',schedule);chapter.addEventListener('focusout',()=>setTimeout(schedule,0));
 chapter.querySelectorAll('[data-vision-nav]').forEach(link=>link.addEventListener('click',()=>requestAnimationFrame(()=>document.querySelector(link.hash+' h2')?.focus({preventScroll:true}))));
 document.querySelectorAll('[data-vision-skip]').forEach(link=>link.addEventListener('click',()=>requestAnimationFrame(()=>document.getElementById('heading-highlights')?.focus({preventScroll:true}))));
 addEventListener('showcase:reading-ready',()=>{ready=true;hashChanged();schedule();});addEventListener('hashchange',hashChanged);addEventListener('popstate',hashChanged);
 addEventListener('pageshow',schedule);addEventListener('resize',relayout,{passive:true});addEventListener('scroll',schedule,{passive:true});document.addEventListener('visibilitychange',schedule);
 reduced.addEventListener('change',schedule);mobile.addEventListener('change',relayout);
 new MutationObserver(schedule).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
 window.ShowcaseVision={resolveAnchor,reset(){groups.forEach(row=>choose(row,0));closePanel(false,false);try{sessionStorage.removeItem('studyagent.showcase.vision.v1');}catch{}},snapshot(){return Object.fromEntries(groups.map(r=>[r.id,r.index]));}};
 resolveAnchor(location.hash);schedule();
})();
