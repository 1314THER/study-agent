/* Desktop teaching galaxies; narrow screens use native, manually paged slides. */
(()=>{
 'use strict';
 const chapter=document.getElementById('vision');if(!chapter)return;
 const dialog=document.getElementById('vision-dialog'),body=dialog.querySelector('.vision-dialog-body'),title=dialog.querySelector('h2');
 const mobile=matchMedia('(max-width:1099px)'),reduced=matchMedia('(prefers-reduced-motion: reduce)'),ns='http://www.w3.org/2000/svg';
 let ready=false,frame=0,opened=null,layoutFrame=0,returnFocus=null;
 const groups=[...chapter.querySelectorAll('[data-vision-group]')].map(group=>({group,id:group.dataset.visionGroup,viewport:group.querySelector('.vision-viewport'),world:group.querySelector('.vision-world'),svg:group.querySelector('svg'),nodes:[...group.querySelectorAll('.vision-change')],index:0,scrollFrame:0,requestedIndex:null,userScroll:false}));
 const aspectMap=new Map();
 const ellipse=(ring,t)=>({x:ring.cx+ring.rx*Math.cos(t),y:ring.cy+ring.ry*Math.sin(t)});
 function mark(row,manual=false){
  row.nodes.forEach((node,index)=>{const b=node.querySelector('.vision-card');b.tabIndex=mobile.matches&&index!==row.index?-1:0;b.setAttribute('aria-current',String(index===row.index));});
  row.group.querySelector('.vision-camera-count').textContent=(row.index+1)+' / '+row.nodes.length;
  row.group.querySelector('[data-camera-step="-1"]').disabled=mobile.matches&&row.index===0;
  row.group.querySelector('[data-camera-step="1"]').disabled=mobile.matches&&row.index===row.nodes.length-1;
  if(manual)row.group.querySelector('[role=status]').textContent=row.nodes[row.index].dataset.aspect;
 }
 function position(row,behavior='instant'){
  row.world.style.transform='';
  if(!mobile.matches)return;
  const node=row.nodes[row.index],left=node.offsetLeft+node.offsetWidth/2-row.viewport.clientWidth/2;
  row.viewport.scrollTo({left,behavior});
 }
 function choose(row,index,manual=false){
  row.index=Math.max(0,Math.min(row.nodes.length-1,index));row.userScroll=false;
  const smooth=manual&&!reduced.matches&&!dialog.open;row.requestedIndex=smooth?row.index:null;mark(row,manual);position(row,smooth?'smooth':'instant');
 }
 function syncSlide(row){
  row.scrollFrame=0;if(!mobile.matches||dialog.open)return;
  const middle=row.viewport.scrollLeft+row.viewport.clientWidth/2;
  if(row.requestedIndex!==null){const target=row.nodes[row.requestedIndex];if(Math.abs(target.offsetLeft+target.offsetWidth/2-middle)>1)return;row.requestedIndex=null;}
  const index=row.nodes.reduce((best,node,i)=>Math.abs(node.offsetLeft+node.offsetWidth/2-middle)<Math.abs(row.nodes[best].offsetLeft+row.nodes[best].offsetWidth/2-middle)?i:best,0);
  if(row.index!==index){row.index=index;mark(row);}
 }
 function refresh(){frame=0;document.body.classList.toggle('is-vision-active',chapter.getBoundingClientRect().bottom>innerHeight*.12&&chapter.getBoundingClientRect().top<innerHeight*.92);}
 function schedule(){if(!frame)frame=requestAnimationFrame(refresh);}
 function syncModalMotion(){dialog.dataset.motion=dialog.open&&document.visibilityState==='visible'&&!reduced.matches?'running':'stopped';}
 function layout(row){
  const phone=mobile.matches,social=row.id==='society',student=row.id==='students';row.requestedIndex=null;
  row.group.dataset.visionCarousel=String(phone);row.group.querySelector('.vision-camera-controls').hidden=!phone;
  if(phone){
   const width=row.viewport.clientWidth,card=Math.min(390,width-36);
   row.group.style.setProperty('--slide-w',card+'px');row.group.style.setProperty('--slide-edge',(width-card)/2+'px');
   row.world.style.width='';row.world.style.height='';row.world.style.transform='';row.svg.replaceChildren();
   row.group.setAttribute('aria-roledescription','愿景轮播');
   mark(row);position(row);return;
  }
  row.group.removeAttribute('aria-roledescription');row.viewport.scrollLeft=0;
  const w=Math.min(1200,row.viewport.clientWidth),h=social?520:student?760:660,cw=Math.max(140,Math.min(164,w*.1+44)),ch=88,margin=16;
  row.group.style.setProperty('--world-w',w+'px');row.group.style.setProperty('--world-h',h+'px');row.group.style.setProperty('--card-w',cw+'px');row.group.style.setProperty('--card-h',ch+'px');row.group.style.setProperty('--center-w',Math.min(240,w*.22)+'px');
  row.world.style.width=w+'px';row.world.style.height=h+'px';row.world.style.transform='';row.svg.setAttribute('viewBox','0 0 '+w+' '+h);row.svg.replaceChildren();
  const outer={cx:w/2,cy:h/2,rx:(w-cw)/2-margin,ry:(h-ch)/2-margin},inner={cx:w/2,cy:h/2,rx:w*(student?.215:.21),ry:h*(student?.26:.22)};
  const outerCount=social?8:row.id==='students'?13:11;
  (social?[outer]:[outer,inner]).forEach(r=>{const e=document.createElementNS(ns,'ellipse');for(const key of ['cx','cy','rx','ry'])e.setAttribute(key,r[key]);row.svg.append(e);});
  row.nodes.forEach((node,i)=>{const ring=i<outerCount?outer:inner,start=i<outerCount?0:outerCount,count=i<outerCount?outerCount:row.nodes.length-outerCount,angle=-Math.PI/2+(i-start+(i<outerCount?0:.5))*Math.PI*2/count;const point=ellipse(ring,angle);node.style.setProperty('--node-x',point.x+'px');node.style.setProperty('--node-y',point.y+'px');});
  mark(row);
 }
 function relayout(){cancelAnimationFrame(layoutFrame);layoutFrame=requestAnimationFrame(()=>{groups.forEach(layout);schedule();});}
 // A later group navigation must take precedence over the closing dialog's focus return.
 function restoreFocus(){const saved=returnFocus;if(!saved||aspectMap.has(location.hash.slice(1)))return;returnFocus=null;requestAnimationFrame(()=>requestAnimationFrame(()=>{if(!dialog.open&&saved.node.isConnected&&saved.hashes.includes(location.hash)){scrollTo({top:saved.y,behavior:'instant'});saved.node.querySelector('.vision-card').focus({preventScroll:true});}}));}
 function closePanel(updateUrl=true,restore=true){
  if(!opened)return;const saved=opened;opened=null;returnFocus=restore?{node:saved.node,y:saved.returnY,hashes:[saved.returnHash,'#vision-'+saved.row.id]}:null;dialog.close();syncModalMotion();body.replaceChildren();
  if(updateUrl&&location.hash==='#'+saved.node.id){if(history.state?.visionDialog===saved.node.id)history.back();else{const u=new URL(location.href);u.hash='vision-'+saved.row.id;history.replaceState(null,'',u);}}
  restoreFocus();schedule();
 }
 function openPanel(row,index,push=false){
  returnFocus=null;const node=row.nodes[index];choose(row,index);if(opened?.node===node)return;
  const returnY=scrollY,returnHash=location.hash;
  if(push&&location.hash!=='#'+node.id){const u=new URL(location.href);u.hash=node.id;history.pushState({...history.state,visionDialog:node.id,visionReturn:location.hash||'#vision-'+row.id},'',u);}
  const clone=node.querySelector('.vision-detail').cloneNode(true);
  clone.querySelectorAll('[id]').forEach(el=>{const old=el.id;el.id=old+'-modal';clone.querySelectorAll('[stroke]').forEach(path=>{if(path.getAttribute('stroke')==='url(#'+old+')')path.setAttribute('stroke','url(#'+el.id+')');});});
  title.textContent=row.group.querySelector('h2').textContent+' · '+node.dataset.aspect;body.replaceChildren(clone);opened={row,node,returnY,returnHash};if(!dialog.open)dialog.showModal();syncModalMotion();schedule();
 }
 function resolveAnchor(hash){const value=aspectMap.get(String(hash).replace(/^#/,''));if(!value)return null;choose(value.row,value.index);return mobile.matches?value.row.group:value.node;}
 function hashChanged(){const value=aspectMap.get(location.hash.slice(1));if(value){resolveAnchor(location.hash);if(ready)openPanel(value.row,value.index);}else if(opened)closePanel(false,location.hash===opened.returnHash||location.hash==='#vision-'+opened.row.id);restoreFocus();schedule();}
 groups.forEach(row=>{
  row.nodes.forEach((node,index)=>{aspectMap.set(node.id,{row,index});const b=node.querySelector('.vision-card');b.hidden=false;node.querySelector('details').hidden=true;b.addEventListener('click',()=>openPanel(row,index,true));b.addEventListener('focus',()=>{if(mobile.matches&&index!==row.index)choose(row,index);schedule();});});
  row.group.querySelectorAll('[data-camera-step]').forEach(b=>b.addEventListener('click',()=>{choose(row,row.index+Number(b.dataset.cameraStep),true);schedule();}));
  row.viewport.addEventListener('scroll',()=>{if(!row.scrollFrame)row.scrollFrame=requestAnimationFrame(()=>syncSlide(row));},{passive:true});
  row.viewport.addEventListener('scrollend',()=>{syncSlide(row);if(row.userScroll){row.group.querySelector('[role=status]').textContent=row.nodes[row.index].dataset.aspect;row.userScroll=false;}});
  for(const event of ['pointerdown','wheel'])row.viewport.addEventListener(event,()=>{row.requestedIndex=null;row.userScroll=true;},{passive:true});
  row.group.addEventListener('keydown',event=>{if(!mobile.matches||!event.target.closest('.vision-card')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?row.nodes.length-1:row.index+(event.key==='ArrowRight'?1:-1);choose(row,index,true);row.nodes[row.index].querySelector('.vision-card').focus({preventScroll:true});});
 });
 chapter.classList.add('vision-enhanced');groups.forEach(layout);
 dialog.querySelector('.vision-dialog-close').addEventListener('click',()=>closePanel());dialog.addEventListener('cancel',e=>{e.preventDefault();closePanel();});
 dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closePanel();}const link=event.target.closest('a[href^="#"]');if(link){const returnHash=history.state?.visionReturn||'#vision-'+opened.row.id;history.replaceState(null,'',returnHash);closePanel(false,false);}});
 chapter.addEventListener('focusin',schedule);chapter.addEventListener('focusout',()=>setTimeout(schedule,0));
 document.querySelectorAll('[data-vision-skip]').forEach(link=>link.addEventListener('click',()=>requestAnimationFrame(()=>document.getElementById('heading-highlights')?.focus({preventScroll:true}))));
 addEventListener('showcase:reading-ready',()=>{ready=true;hashChanged();schedule();});addEventListener('hashchange',hashChanged);addEventListener('popstate',hashChanged);
 addEventListener('pageshow',schedule);addEventListener('resize',relayout,{passive:true});addEventListener('scroll',schedule,{passive:true});document.addEventListener('visibilitychange',()=>{syncModalMotion();if(document.visibilityState!=='visible'&&mobile.matches)groups.forEach(row=>{row.requestedIndex=null;position(row);});schedule();});
 reduced.addEventListener('change',()=>{syncModalMotion();if(reduced.matches&&mobile.matches)groups.forEach(row=>{row.requestedIndex=null;position(row);});schedule();});mobile.addEventListener('change',relayout);
 new MutationObserver(schedule).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
 window.ShowcaseVision={resolveAnchor,reset(){groups.forEach(row=>choose(row,0));closePanel(false,false);try{sessionStorage.removeItem('studyagent.showcase.vision.v1');}catch{}},snapshot(){return Object.fromEntries(groups.map(r=>[r.id,r.index]));}};
 resolveAnchor(location.hash);schedule();
})();
