(function () {
  'use strict';
  const $=id=>document.getElementById(id);
  const state={revision:0,overview:null,entities:[],lessons:[],detail:null,edit:null,dirty:false,listToken:0,detailToken:0,action:null};
  const statusNames={draft:'待审核',confirmed:'已确认',deferred:'暂缓',rejected:'已排除'};
  const relationNames={prerequisite:'前置课时',requires:'需要知识',teaches:'首次引入',practices:'安排练习',routine_candidate:'套路候选',related:'相关联系',covers:'内容安排'};
  const readingNames={entry_only:'仅有入口',directory_pending:'目录待核',directory_read:'已读目录',partial:'部分已读',read:'已读指定范围',authored:'原创整理',failed:'读取失败'};
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=text;if(cls)n.className=cls;return n;}
  function button(text,fn,cls){const n=el('button',text,cls);n.type='button';n.addEventListener('click',()=>Promise.resolve(fn()).catch(fail));return n;}
  function link(text,url){const n=el('a',text);if(/^https?:\/\//.test(url)||url.startsWith('/'))n.href=url;else return el('span',text);n.target='_blank';n.rel='noopener noreferrer';return n;}
  function math(text,cls){const n=el('div',null,cls||'cw-body');if(window.PoolMath)window.PoolMath.render(n,text||'');else n.textContent=text||'';return n;}
  function tag(text,cls){return el('span',text,'cw-tag '+(cls||''));}
  function message(text,error){$('wikiMessage').textContent=text||'';$('wikiMessage').className='cw-message '+(error?'cw-error':'cw-success');}
  function fail(e){message(e.message||String(e),true);}
  function find(id){return state.entities.find(x=>x.id===id);}
  function name(id){const n=find(id);return n?n.title:id;}
  async function api(path,method,body){
    const r=await fetch('/curriculum-wiki'+path,{method:method||'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
    const d=await r.json();if(!r.ok){const e=new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||d));e.status=r.status;throw e;}return d;
  }
  function safeToLeave(){return !state.dirty||window.confirm('编辑尚未保存。确定放弃当前输入吗？');}
  function pane(value){document.querySelector('.cw-workspace').dataset.pane=value;}
  async function loadData(){
    const [o,e]=await Promise.all([api('/overview'),api('/entities')]);
    state.overview=o;state.revision=o.revision;state.entities=e.items;
    const cov=o.coverage;
    $('coverageStrip').replaceChildren(
      el('span','课时 '+o.counts.lessons+' · 知识 '+o.counts.knowledge),
      el('span','教材安排 '+cov.textbook.covered+'/'+cov.textbook.total),
      el('span','解法匹配 '+cov.matching.mapped+'/'+cov.matching.total),
      el('span','人工确认 '+cov.human.confirmed+'/'+cov.human.total));
    const bookValue=$('bookFilter').value;
    $('bookFilter').replaceChildren(new Option('全部教材与复习',''),...o.books.map(n=>new Option(n.title,n.id)),new Option('高三复习与综合','review'));$('bookFilter').value=bookValue;
    const sourceValue=$('sourceFilter').value;
    $('sourceFilter').replaceChildren(new Option('全部资料',''),...state.entities.filter(x=>x.kind==='source').map(n=>new Option(n.title,n.id)));$('sourceFilter').value=sourceValue;
  }
  async function listLessons(){
    const token=++state.listToken;const p=new URLSearchParams({page_size:'500',query:$('wikiSearch').value,book:$('bookFilter').value,status:$('statusFilter').value,source:$('sourceFilter').value,only_gaps:$('gapsOnly').checked});
    const d=await api('/lessons?'+p);if(token!==state.listToken)return;
    state.lessons=d.items;$('lessonCount').textContent=d.total+' 课 · 编排与匹配仍需教师审核';$('lessonList').replaceChildren();
    let previous='';
    d.items.forEach(n=>{
      const chapterId=n.section_id.includes(':ch:')?n.section_id:n.book_id+':ch:'+n.section_id.split(':')[1]?.split('.')[0];
      const chapter=n.book_id==='review'?'高三专题与综合':name(n.book_id)+' / '+name(chapterId);
      if(chapter!==previous){$('lessonList').append(el('p',chapter,'cw-chapter-label'));previous=chapter;}
      const index=state.entities.filter(x=>x.kind==='lesson'&&x.active).sort((a,b)=>a.position-b.position).findIndex(x=>x.id===n.id)+1;
      const b=button('',()=>selectLesson(n.id),'cw-lesson-link'+(state.detail?.entity.id===n.id?' active':''));
      b.dataset.lesson=n.id;b.append(el('span',String(index).padStart(3,'0'),'cw-number'));
      const title=el('span',n.title);title.append(el('small',n.data.lesson_type+' · '+statusNames[n.status]));b.append(title);$('lessonList').append(b);
    });
    if(!d.items.length)$('lessonList').append(el('p','没有匹配的课时。可清空筛选，或在资料面板补充来源。','cw-empty'));
  }
  async function selectLesson(id,options){
    if(!(options&&options.force)&&!safeToLeave())return;
    const token=++state.detailToken;const d=await api('/lessons/'+encodeURIComponent(id));if(token!==state.detailToken)return;
    state.detail=d;state.revision=d.revision;state.dirty=false;
    const url=new URL(location.href);url.searchParams.set('entity',id);history.replaceState(null,'',url);
    renderDetail(d);pane('lesson');
    document.querySelectorAll('[data-lesson]').forEach(b=>b.classList.toggle('active',b.dataset.lesson===id));
  }
  function heading(parent,title){parent.append(el('h3',title));}
  function bullets(parent,items){const ul=el('ul');(items||[]).forEach(x=>{const li=el('li');li.append(math(x));ul.append(li);});parent.append(ul);}
  function renderDetail(d){
    const n=d.entity,data=n.data,main=$('lessonPane');main.replaceChildren();
    const trail=el('p',name(n.book_id)+' / '+(data.locator||n.section_id),'cw-muted');main.append(trail);
    const tags=el('div',null,'cw-tags');tags.append(tag(data.lesson_type||n.kind),tag(statusNames[n.status],n.status));
    if(n.kind==='lesson')tags.append(tag((data.duration_minutes||45)+' 分钟'),tag({system_proposed:'系统建议拆分',textbook_explicit:'教材明示',workbook_explicit:'教辅明示',human:'人工编排'}[data.allocation]||'拆分待核'));
    main.append(tags,el('h2',n.title));
    if(n.kind==='lesson'){
      const nav=el('div',null,'cw-actions');
      if(d.previous)nav.append(button('上一课',()=>selectLesson(d.previous)));
      if(d.next)nav.append(button('下一课',()=>selectLesson(d.next)));
      nav.append(button('校正本课',()=>openEdit(n),'cw-primary'));
      main.append(nav);
      heading(main,'本课学什么');bullets(main,data.objectives);
    }
    heading(main,'内容与方法');main.append(math(data.body||data.method||'请补充研究说明。'));
    if(data.formula){heading(main,'公式与适用条件');main.append(math(data.formula));}
    if(data.foundations?.length){heading(main,'初中基础与已有知识');bullets(main,data.foundations);}
    const prerequisites=d.relations.filter(e=>e.source===n.id&&e.kind==='prerequisite'&&e.status!=='rejected');
    heading(main,'先学什么');const pre=el('div',null,'cw-step-list');
    prerequisites.forEach(e=>pre.append(button(name(e.target),()=>selectLesson(e.target))));
    main.append(pre);if(!prerequisites.length)main.append(el('p','此课未设置高中前置课时，请核对上方基础要求。','cw-muted'));
    const kps=d.relations.filter(e=>e.source===n.id&&['teaches','requires'].includes(e.kind)&&e.status!=='rejected');
    if(kps.length){heading(main,'知识点：首次引入与复用');kps.forEach(e=>{const p=el('div',null,'cw-relation-row');p.append(tag(e.kind==='teaches'?'本课引入':'前置复用'),el('span',' '+name(e.target)+' '),button('查看与校正',()=>openEdit(find(e.target))));main.append(p);});}
    if(data.pitfalls?.length){heading(main,'易错点与边界');bullets(main,data.pitfalls);}
    if(data.integrated_readings?.length){heading(main,'本课融入的阅读、探究与建模');data.integrated_readings.forEach(r=>{
      const section=el('details',null,'cw-relation-row');section.append(el('summary',r.title+' · 印刷第'+r.printed_page+'页'),math(r.body));
      section.append(link('核对原页','/curriculum-wiki/sources/'+encodeURIComponent(data.source_id)+'/file#page='+r.pdf_page));main.append(section);
    });}
    if(data.practice_stage)main.append(el('p','建议练习顺序：'+data.practice_stage,'cw-guidance'));
    const routines=d.relations.filter(e=>e.source===n.id&&e.kind==='routine_candidate'&&e.status!=='rejected');
    heading(main,'方法与套路候选');
    if(!routines.length)main.append(el('p','尚无可靠课程关联。可在右侧添加关系；空缺不会自动解释为没有适用方法。','cw-muted'));
    routines.forEach(e=>{
      const r=find(e.target),section=el('details',null,'cw-relation-row');section.append(el('summary',(r?.data.external_id||'')+' '+name(e.target)+' · '+statusNames[e.status]));
      if(r){bullets(section,r.data.key_steps);section.append(el('p','适用边界：'+r.data.exclusions.join('；')));}
      section.append(el('p',e.evidence.reason,'cw-muted'),button('校正关系',()=>relationEditor(e)));main.append(section);
    });
    heading(main,'对应题目与解法');
    const attach=el('div',null,'cw-actions');if(n.kind==='lesson')attach.append(button('关联真实题目',()=>questionDialog(n)));main.append(attach);
    if(!d.solutions.length)main.append(el('p','本课尚无已关联的真实题目。教辅页码与题号待补；不会使用虚构题目填充。','cw-guidance cw-warning'));
    const stages=['例题','基础','巩固','变式','综合'];
    [...d.solutions].sort((a,b)=>{
      const rank=s=>{const i=stages.indexOf(s.data.stage);return i<0?2:i;};
      return rank(a)-rank(b)||(Number(a.data.practice_order)||0)-(Number(b.data.practice_order)||0)||
        String(a.data.source_id).localeCompare(String(b.data.source_id))||
        String(a.data.source_locator?.source_key||a.title).localeCompare(String(b.data.source_locator?.source_key||b.title),'zh-CN',{numeric:true})||a.id.localeCompare(b.id);
    }).forEach(sol=>renderSolution(main,sol));
    const later=d.relations.filter(e=>e.target===n.id&&e.kind==='prerequisite'&&e.status!=='rejected');
    if(later.length){heading(main,'后续用途');const next=el('div',null,'cw-step-list');later.forEach(e=>next.append(button(name(e.source),()=>selectLesson(e.source))));main.append(next);}
    renderEvidence(d);
  }
  function renderSolution(parent,sol){
    const d=sol.data,item=sol.freshness.item,box=el('section',null,'cw-question');box.append(el('h4',d.subquestion+' · '+sol.title));
    box.append(el('p',(name(d.source_id)||'原题池')+' / '+(d.source_locator?.source_key||'定位待核')+(d.source_locator?.page_start?' / 第'+d.source_locator.page_start+'页':'')+' / 原题版本 '+d.item_version,'cw-question-origin'));
    box.append(tag(statusNames[sol.status],sol.status),tag(d.completeness==='complete'?'源内容完整':'内容需核对'),tag((d.stage||'巩固')+'练习'+(d.practice_order?' · 顺位 '+d.practice_order:'')));
    if(sol.freshness.stale)box.append(el('p',sol.freshness.reason,'cw-guidance cw-warning'));
    if(d.mapping_note)box.append(el('p',d.mapping_note,'cw-guidance'));
    if(sol.stage?.earliest_lesson_id)box.append(button('按已声明前置，最早在“'+name(sol.stage.earliest_lesson_id)+'”后使用',()=>selectLesson(sol.stage.earliest_lesson_id)));
    box.append(math(d.question_snapshot||item?.question));
    const details=el('details');details.append(el('summary','原答案、原解析与本解法步骤'));
    details.append(math('原答案：'+(d.answer_snapshot||'未取得')),math(d.solution_snapshot||'原题源没有解析，不能仅凭题干确认完整套路。'));
    if(d.editorial_answer)details.append(el('h4','研究推导答案（待审核，非原书参考答案）'),math(d.editorial_answer));
    if(d.steps?.length){details.append(el('h4','本条解法的步骤（研究草稿）'));bullets(details,d.steps);}
    if(d.classification_evidence?.length){details.append(el('h4','原分类引用依据'));d.classification_evidence.forEach(e=>details.append(math(e.quote)));}
    const reqs=(sol.relations||[]).filter(e=>e.kind==='requires'&&e.status!=='rejected');
    details.append(el('p','解法需要：'+(reqs.length?reqs.map(e=>name(e.target)).join('；'):'尚未核实，不能判定适合本课。')));
    (sol.relations||[]).filter(e=>e.kind==='routine_candidate'&&e.status!=='rejected').forEach(e=>{details.append(el('p','套路：'+name(e.target)+'；依据：'+e.evidence.reason),button('校正套路关联',()=>relationEditor(e)));});
    box.append(details);const actions=el('div',null,'cw-actions');
    actions.append(button('校正解法',()=>openEdit(sol)),button('请求套路匹配',()=>startRun('routine_match',[sol.id])));
    actions.append(link('原题池回看','/question-pool.html?item='+d.pool_item_id));
    const src=find(d.source_id);
    if(src?.data.pool_source_id&&item?.occurrences.some(o=>o.source_id===src.data.pool_source_id&&o.filename))actions.append(link('原文件','/question-pool/sources/'+src.data.pool_source_id+'/file'+(d.source_locator.page_start?'#page='+d.source_locator.page_start:'')));
    if(d.source_locator?.url)actions.append(link('来源页面',d.source_locator.url));
    box.append(actions);parent.append(box);
    fetch('/question-pool/items/'+d.pool_item_id+'/assets').then(r=>r.ok?r.json():null).then(assets=>{
      if(!assets||!box.isConnected)return;
      (assets.assets||[]).forEach(a=>{if(!a.ref)return;const img=el('img');img.src='/question-assets/'+encodeURIComponent(a.ref);img.alt=a.label||'原题图形';img.loading='lazy';box.insertBefore(img,details);});
      if(assets.required&&assets.missing?.length)box.insertBefore(el('p','题图仍缺失，需核对原文件。','cw-error'),details);
    }).catch(()=>{if(box.isConnected)box.append(el('p','题图暂未读取，可到原题池核对。','cw-muted'));});
  }
  function renderEvidence(d){
    const box=$('evidencePane'),n=d.entity;box.replaceChildren(el('h2','证据与校正'),el('p','原文证据、系统推断和人工结论分别保留。','cw-muted'));
    d.warnings.forEach(w=>box.append(el('p',w.message+(w.missing_knowledge?' '+w.missing_knowledge.map(name).join('；'):''),'cw-guidance cw-warning')));
    const src=find(n.data.source_id);
    if(src){const p=el('div',null,'cw-source');p.append(el('h3',src.title),el('p',n.data.locator||'定位待核'),tag(readingNames[src.data.reading_status]||'待核'),el('p',src.data.edition||'版次未核实','cw-muted'));
      if(src.data.url)p.append(link('查看来源',src.data.url));
      if(src.data.evidence_file)p.append(link('教材原页','/curriculum-wiki/sources/'+encodeURIComponent(src.id)+'/file'+(n.data.pdf_page?'#page='+n.data.pdf_page:'')));
      p.append(button('校正资料',()=>openEdit(src)));box.append(p);}
    heading(box,'待补与待审');box.append(el('p',d.solutions.length?'本课已关联 '+d.solutions.length+' 条解法草稿；仍需逐条审核，原书其余练习与教辅版本继续补充。':n.data.gap||'请结合原书核查本课内容和练习。'));
    if(n.kind==='lesson'){
      const a=el('div',null,'cw-actions');a.append(button('添加关系',()=>relationEditor()),button('拆分课时',()=>splitDialog(n)),button('合并课时',()=>mergeDialog(n)));
      a.append(button('新增本课知识点',()=>knowledgeDialog(n)));
      a.append(button('上移一课',()=>moveLesson(-1)),button('下移一课',()=>moveLesson(1)),button('根据资料整理草稿',()=>startRun('lesson_draft',[n.id])));box.append(a);
    }
    heading(box,'本课关系');
    d.relations.filter(e=>e.status!=='rejected').forEach(e=>{const row=el('div',null,'cw-relation-row');const label=e.target===n.id&&e.kind==='prerequisite'?'后续课时':e.target===n.id&&e.kind==='covers'?'教材内容归属':relationNames[e.kind];row.append(el('span',label+'：'+name(e.source===n.id?e.target:e.source)),el('p',e.evidence.reason,'cw-muted'),button('校正',()=>relationEditor(e)));box.append(row);});
    box.append(el('p','目录编号：'+n.id+' · 数据版本：'+d.revision,'cw-muted'));
  }
  function field(parent,label,name,value,options){
    const l=el('label',label);let input;
    if(options?.choices){input=el('select');if(options.multiple)input.multiple=true;options.choices.forEach(([v,t])=>input.append(new Option(t,v)));input.value=value||'';if(options.multiple){input.size=6;const selected=new Set(value||[]);[...input.options].forEach(o=>o.selected=selected.has(o.value));}}
    else if(options?.area){input=el('textarea');input.rows=options.rows||4;input.value=Array.isArray(value)?value.join('\n'):value||'';}
    else{input=el('input');input.value=value||'';}
    input.name=name;if(options?.required)input.required=true;l.append(input);parent.append(l);return input;
  }
  function values(form,name){return [...form.elements[name].selectedOptions].map(o=>o.value);}
  function lines(value){return value.split('\n').map(s=>s.trim()).filter(Boolean);}
  function openEdit(n){
    if(!n)return;state.edit=deepCopy(n);state.editRevision=state.revision;state.dirty=false;$('editHeading').textContent='校正：'+n.title;
    const form=$('editForm');form.elements.title.value=n.title;form.elements.status.value=n.status;form.elements.reason.value='';$('editError').textContent='';
    const p=$('editorFields');p.replaceChildren();
    if(n.kind==='source'){
      field(p,'版次（不确定时留空）','edition',n.data.edition);field(p,'ISBN（未核实留空）','isbn',n.data.isbn);
      field(p,'已读范围与缺口','scope',n.data.scope,{area:true});
      field(p,'资料读取状态','reading_status',n.data.reading_status,{choices:Object.entries(readingNames)});
      field(p,'原文片段定位','excerpt_locator','');field(p,'添加原文片段（会与已存片段合并）','excerpt_text','',{area:true});
    }else{
      field(p,'正文或知识说明','body',n.data.body||n.data.method||'',{area:true,rows:8,required:n.kind==='lesson'});
      if(n.kind==='lesson')field(p,'学习目标（每行一项）','objectives',n.data.objectives,{area:true,required:true});
      if(['lesson','knowledge'].includes(n.kind)){field(p,'公式与条件','formula',n.data.formula,{area:true,rows:3});field(p,'易错点（每行一项）','pitfalls',n.data.pitfalls||[n.data.conditions||''],{area:true,rows:3});}
      if(n.kind==='solution'){
        field(p,'练习阶段','stage',n.data.stage||'巩固',{choices:['例题','基础','巩固','变式','综合'].map(s=>[s,s])});
        const order=field(p,'阶段内顺位（同顺位按出处题号排序）','practice_order',n.data.practice_order||0);order.type='number';order.min='0';order.step='1';
        field(p,'解法步骤（每行一步）','steps',n.data.steps,{area:true});field(p,'前置知识核实状态','requirements_status',n.data.requirements_status,{choices:[['unknown','尚未核实'],['declared','已列出前置知识'],['verified','已人工核实完整']]});
      }
    }
    $('editDialog').showModal();
  }
  function deepCopy(x){return JSON.parse(JSON.stringify(x));}
  $('editForm').addEventListener('input',()=>state.dirty=true);
  $('editForm').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,n=state.edit,d={};const controls=form.elements;
    for(const key of ['body','formula','edition','isbn','scope','reading_status','requirements_status','stage'])if(controls[key])d[key]=controls[key].value;
    if(controls.practice_order)d.practice_order=Number(controls.practice_order.value);
    for(const key of ['objectives','pitfalls','steps'])if(controls[key])d[key]=lines(controls[key].value);
    if(controls.excerpt_text?.value.trim()){
      if(!controls.excerpt_locator.value.trim()){$('editError').textContent='请给原文片段填写页码或章节定位。';return;}
      d.excerpts=[...(n.data.excerpts||[]),{text:controls.excerpt_text.value,locator:controls.excerpt_locator.value,verification:'human_supplied'}];
    }
    try{
      await api('/entities/'+encodeURIComponent(n.id),'PATCH',{expected_revision:state.editRevision,reason:controls.reason.value,changes:{title:controls.title.value,status:controls.status.value,data:d}});
      state.dirty=false;$('editDialog').close();await refresh();message('校正已保存，历史版本仍可回看。');
    }catch(e){$('editError').textContent=e.message;}
  });
  function showAction(title,build,submit,submitLabel){
    $('actionHeading').textContent=title;$('actionFields').replaceChildren();$('actionError').textContent='';$('actionSubmit').textContent=submitLabel||'保存';
    state.action={submit,revision:state.revision};build($('actionFields'));state.dirty=false;$('actionDialog').showModal();
  }
  $('actionForm').addEventListener('input',()=>state.dirty=true);
  $('actionForm').addEventListener('submit',async event=>{event.preventDefault();const b=$('actionSubmit');b.disabled=true;try{await state.action.submit(event.currentTarget,state.action.revision);state.dirty=false;$('actionDialog').close();await refresh();message('操作已保存。');}catch(e){$('actionError').textContent=e.message;}finally{b.disabled=false;}});
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>{if(safeToLeave()){state.dirty=false;b.closest('dialog').close();}}));
  document.querySelectorAll('dialog').forEach(d=>d.addEventListener('cancel',event=>{if(!safeToLeave())event.preventDefault();else state.dirty=false;}));
  window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
  function reasonField(p){field(p,'修改或审核理由','reason','',{area:true,rows:2,required:true});}
  function relationEditor(existing){
    const n=state.detail.entity;
    showAction(existing?'校正关系':'添加关系',p=>{
      field(p,'起点','source',existing?.source||n.id,{choices:state.entities.filter(x=>['lesson','knowledge','solution','section','outline'].includes(x.kind)&&x.active).map(x=>[x.id,x.title+' ['+x.id+']'])});
      field(p,'关系类型','kind',existing?.kind||'prerequisite',{choices:Object.entries(relationNames)});
      field(p,'目标课时、知识点或套路','target',existing?.target||'',{choices:[['','请选择'],...state.entities.filter(x=>x.active&&x.id!==n.id).map(x=>[x.id,x.title+' ['+x.id+']'])]});
      field(p,'证据资料','source_id',existing?.evidence.source_id||'source:editorial',{choices:state.entities.filter(x=>x.kind==='source').map(x=>[x.id,x.title])});
      field(p,'证据定位与说明','locator',existing?.evidence.locator||'',{area:true,rows:2});
      field(p,'审核状态','status',existing?.status||'draft',{choices:Object.entries(statusNames)});reasonField(p);
    },(form,rev)=>{const v=new FormData(form);return api('/relations','POST',{expected_revision:rev,reason:v.get('reason'),relation:{...(existing?{id:existing.id}:{}),source:v.get('source'),target:v.get('target'),kind:v.get('kind'),status:v.get('status'),evidence:{source_id:v.get('source_id'),locator:v.get('locator'),reason:v.get('reason'),origin:'human'}}});});
  }
  function splitDialog(n){
    showAction('将课时拆成两课',p=>{
      p.append(el('p','前置要求会保留，后续课时改为依赖拆分后的最后一课；原课时归档。','cw-muted'));
      for(let i=1;i<=2;i++){const part=el('div',null,'cw-part');part.append(el('h3','第 '+i+' 课'));field(part,'标题','title'+i,n.title+'（'+i+'）',{required:true});field(part,'学习目标（每行一项）','objectives'+i,n.data.objectives,{area:true,required:true});field(part,'具体内容','body'+i,n.data.body,{area:true,required:true});p.append(part);}reasonField(p);
    },(form,rev)=>api('/lessons/'+encodeURIComponent(n.id)+'/split','POST',{expected_revision:rev,reason:form.elements.reason.value,parts:[1,2].map(i=>({title:form.elements['title'+i].value,body:form.elements['body'+i].value,objectives:lines(form.elements['objectives'+i].value)}))}).then(r=>{state.afterSelect=r.result[0];}));
  }
  function knowledgeDialog(n){
    showAction('新增本课引入的知识点',p=>{
      field(p,'知识点名称','title','',{required:true});field(p,'定义与具体说明','body','',{area:true,required:true});
      field(p,'公式','formula','',{area:true,rows:2});field(p,'适用条件与边界','conditions','',{area:true,rows:2});
      p.append(el('p','本课将成为此知识点的引入课时。若应在其他课首次学习，请先选择那一课。','cw-muted'));reasonField(p);
    },(form,rev)=>api('/knowledge','POST',{expected_revision:rev,reason:form.elements.reason.value,title:form.elements.title.value,
      body:form.elements.body.value,formula:form.elements.formula.value,conditions:form.elements.conditions.value,introducing_lesson_id:n.id}));
  }
  function mergeDialog(n){
    showAction('合并课时',p=>{
      field(p,'合并后的标题','title',n.title,{required:true});
      field(p,'同册其他课时（选择一至七课）','other',[],{choices:state.entities.filter(x=>x.kind==='lesson'&&x.active&&x.book_id===n.book_id&&x.id!==n.id).sort((a,b)=>a.position-b.position).map(x=>[x.id,x.title]),multiple:true});reasonField(p);
      p.append(el('p','原课时归档，知识关系保留。合并后的课时显示总时长，可再次拆分。','cw-muted'));
    },(form,rev)=>api('/merge','POST',{expected_revision:rev,reason:form.elements.reason.value,title:form.elements.title.value,lesson_ids:[n.id,...values(form,'other')]}).then(r=>{state.afterSelect=r.result;}));
  }
  async function moveLesson(delta){
    const all=state.entities.filter(x=>x.kind==='lesson'&&x.active).sort((a,b)=>a.position-b.position).map(x=>x.id),i=all.indexOf(state.detail.entity.id),j=i+delta;
    if(j<0||j>=all.length)return;[all[i],all[j]]=[all[j],all[i]];
    const d=await api('/order','PUT',{expected_revision:state.revision,reason:delta<0?'主人将课时上移一位':'主人将课时下移一位',lesson_ids:all});
    await refresh();message('课时顺序已更新。'+(d.warnings.length?'检查发现 '+d.warnings.length+' 处顺序问题，请在右侧核对。':'前置顺序检查通过。'));
  }
  function questionDialog(lesson){
    let selected=null,selectionToken=0;
    showAction('关联真实原题与解法',p=>{
      const search=field(p,'检索原题池','pool_query','');const results=el('div'),preview=el('div',null,'cw-pool-preview');p.append(results,preview);
      const origin=field(p,'原题出处','occurrence_id','',{choices:[['','先选择原题']]});
      const searchButton=button('查找原题',async()=>{
        const token=++selectionToken;const r=await fetch('/question-pool/items?'+new URLSearchParams({keyword:search.value,page_size:'12'}));const data=await r.json();if(token!==selectionToken)return;if(!r.ok)throw new Error(data.detail||'原题读取失败');
        results.replaceChildren();(data.items||[]).forEach(item=>results.append(button('#'+item.id+' '+item.question.slice(0,100),async()=>{
          const chosen=++selectionToken;const response=await fetch('/question-pool/items/'+item.id);const full=await response.json();if(chosen!==selectionToken)return;if(!response.ok)throw new Error(full.detail||'题目读取失败');
          selected=full;preview.replaceChildren(math(full.question));origin.replaceChildren(...full.occurrences.map(o=>new Option((o.source_name||'来源')+' / '+o.source_key,o.id)));
        },'cw-pool-result')));if(!(data.items||[]).length)results.append(el('p','没有匹配题目，可修改关键词或先到原题池导入。'));
      });search.after(searchButton);
      field(p,'小问','subquestion','整题');field(p,'本解法名称与主要方法','method','',{required:true});field(p,'步骤（每行一步）','steps','',{area:true});
      field(p,'本解法完整前置知识（可多选）','knowledge_ids',[],{choices:state.entities.filter(x=>x.kind==='knowledge').map(x=>[x.id,x.title]),multiple:true});
      field(p,'已有套路候选（可多选）','routine_ids',[],{choices:state.entities.filter(x=>x.kind==='routine').map(x=>[x.id,x.data.external_id+' '+x.title]),multiple:true});
      reasonField(p);p.append(link('原题池导入资料','/question-pool.html'));
    },(form,rev)=>{if(!selected)throw new Error('先选择真实原题及出处。');return api('/questions','POST',{expected_revision:rev,reason:form.elements.reason.value,lesson_id:lesson.id,pool_item_id:selected.id,occurrence_id:Number(form.elements.occurrence_id.value),subquestion:form.elements.subquestion.value,method:form.elements.method.value,steps:lines(form.elements.steps.value),knowledge_ids:values(form,'knowledge_ids'),routine_ids:values(form,'routine_ids')});});
  }
  async function refresh(){
    const id=state.afterSelect||state.detail?.entity.id;state.afterSelect=null;
    await loadData();await listLessons();if(id)await selectLesson(id,{force:true});
  }
  function utility(title){$('utilityPanel').hidden=false;$('utilityTitle').textContent=title;$('utilityBody').replaceChildren();return $('utilityBody');}
  async function sourcesPanel(){
    await loadData();const p=utility('资料范围与覆盖缺口'),c=state.overview.coverage;
    p.append(el('p','课时安排覆盖、原书读取、题目匹配和人工审核分别统计。目录已安排课时不代表内容已经教师确认。','cw-muted'));
    const actions=el('div',null,'cw-actions');actions.append(button('导入资料片段',sourceDialog),link('导入PDF、Word或图片到原题池','/question-pool.html'),link('导出只读Wiki','/curriculum-wiki/export?format=markdown'));p.append(actions);
    const grid=el('div',null,'cw-source-grid');state.entities.filter(x=>x.kind==='source').forEach(s=>{
      const box=el('div',null,'cw-source');box.append(el('h3',s.title),tag(readingNames[s.data.reading_status]||'待核'),el('p',s.data.edition||'版次未核实'),el('p','ISBN：'+(s.data.isbn||'未核实'),'cw-muted'),el('p',s.data.scope||'读取范围待补'),el('p','读取量：'+(s.data.read_units??0)+' / '+(s.data.total_units??'总量未知'),'cw-muted'));
      if(s.data.gap)box.append(el('p',s.data.gap,'cw-guidance cw-warning'));
      const a=el('div',null,'cw-actions');a.append(button('校正',()=>openEdit(s)));if(s.data.url)a.append(link('来源',s.data.url));box.append(a);grid.append(box);
    });p.append(grid);
    const gaps=el('details');gaps.append(el('summary','尚无课程关联的套路：'+state.overview.routine_gaps.length));state.overview.routine_gaps.forEach(r=>gaps.append(el('p',r.id+' '+r.title+'：'+r.reason,'cw-muted')));p.append(gaps);
    const checks=await api('/checks');const warning=el('details');warning.append(el('summary','顺序与解法检查：'+checks.warnings.length+' 项'));checks.warnings.forEach(w=>warning.append(button(name(w.lesson_id)+'：'+w.message,()=>selectLesson(w.lesson_id))));p.append(warning);
    p.append(el('p','教材目录已核实节点 '+c.textbook.verified+'/'+c.textbook.total+'；课程安排 '+c.textbook.covered+'/'+c.textbook.total+'；人工确认 '+c.human.confirmed+'/'+c.human.total));
  }
  function sourceDialog(){
    showAction('导入资料原文与定位',p=>{
      field(p,'资料名称','title','',{required:true});field(p,'资料类型','source_type','workbook',{choices:[['workbook','教辅'],['textbook','教材'],['editorial','原创研究']]});
      field(p,'版次','edition','');field(p,'ISBN','isbn','');field(p,'公开来源链接','url','');field(p,'原文定位（册、章、页码）','locator','',{required:true});
      field(p,'已导入原题池的题源编号（可选，供题目自动对应到本版本）','pool_source_id','');
      field(p,'实际读取的原文片段','text','',{area:true,rows:9,required:true});reasonField(p);
    },(form,rev)=>{const v=new FormData(form);return api('/sources/import','POST',{expected_revision:rev,reason:v.get('reason'),source:{title:v.get('title'),source_type:v.get('source_type'),edition:v.get('edition')||null,isbn:v.get('isbn')||null,url:v.get('url'),scope:v.get('locator'),reading_status:'partial',read_units:1,total_units:null,...(v.get('pool_source_id')?{pool_source_id:Number(v.get('pool_source_id'))}:{})},excerpts:[{text:v.get('text'),locator:v.get('locator'),verification:'human_supplied'}]});});
  }
  async function startRun(kind,ids){
    showAction(kind==='lesson_draft'?'根据原文生成课时草稿':'按原解析匹配套路',p=>{
      p.append(el('p','此操作在点击“创建并运行”后调用已配置模型。结果进入建议队列，保留人工内容。','cw-guidance'));
      field(p,'补充参考资料（可多选）','source_ids',[],{choices:state.entities.filter(x=>x.kind==='source').map(x=>[x.id,x.title]),multiple:true});reasonField(p);
    },async(form,rev)=>{
      const run=await api('/runs','POST',{expected_revision:rev,reason:form.elements.reason.value,kind,entity_ids:ids,source_ids:values(form,'source_ids'),request_id:crypto.randomUUID()});
      await api('/runs/'+run.id+'/control','POST',{expected_revision:run.revision,reason:'主人启动整理任务',action:'resume'});await tasksPanel();
    },'创建并运行');
  }
  async function tasksPanel(){
    const [runs,suggestions]=await Promise.all([api('/runs'),api('/suggestions')]);const p=utility('整理任务与修改建议');
    p.append(el('p','运行只产生建议；应用建议是单独的人工操作。暂停会在当前请求结束后生效，已保存项可续跑。','cw-muted'),button('刷新进度',tasksPanel));
    if(!runs.items.length)p.append(el('p','还没有整理任务。在课时右侧选择“根据资料整理草稿”，或在题目处请求套路匹配。','cw-empty'));
    runs.items.forEach(run=>{
      const box=el('div',null,'cw-run');box.append(el('h3',(run.kind==='lesson_draft'?'课时整理':'套路匹配')+' · '+run.status),el('p',run.done+'/'+run.total+' 项已保存'));
      if(run.error)box.append(el('pre',run.error,'cw-error'));
      const action=['running','queued'].includes(run.status)?'pause':'resume';box.append(button(action==='pause'?'暂停':'续跑或重试',async()=>{await api('/runs/'+run.id+'/control','POST',{expected_revision:run.revision,reason:'主人调整整理任务',action});await tasksPanel();}));p.append(box);
    });
    heading(p,'建议队列');
    suggestions.items.forEach(s=>{
      const box=el('details',null,'cw-run');box.append(el('summary',name(s.entity_id)+' · '+s.status+(s.stale?' · 原内容已变更':'')),el('pre',JSON.stringify(s.payload,null,2),'cw-body'));
      if(s.status==='pending')box.append(button('对照并应用',()=>suggestionDecision(s,'apply')),button('排除此建议',()=>suggestionDecision(s,'reject')));
      p.append(box);
    });
  }
  function suggestionDecision(s,action){
    showAction(action==='apply'?'审核并应用建议':'排除建议',p=>{p.append(el('pre',JSON.stringify(s.payload,null,2),'cw-body'));reasonField(p);},async(form,rev)=>{await api('/suggestions/'+s.id+'/'+action,'POST',{expected_revision:rev,reason:form.elements.reason.value});await tasksPanel();});
  }
  async function historyPanel(){
    const data=await api('/history'),p=utility('修订历史');
    if(!data.items.length)p.append(el('p','尚无人工修订。初始课程内容保留为待审核。','cw-empty'));
    data.items.forEach(row=>{const box=el('details');box.append(el('summary','版本 '+row.revision+' · '+row.reason+' · '+new Date(row.created_at*1000).toLocaleString('zh-CN')));let loaded=false;box.addEventListener('toggle',async()=>{
      if(!box.open||loaded)return;try{const d=await api('/history/'+row.revision);loaded=true;const diff=el('div',null,'cw-diff');diff.append(el('pre','修改前\n'+JSON.stringify(d.before,null,2)),el('pre','修改后\n'+JSON.stringify(d.after,null,2)));box.append(diff,button('恢复修改前内容',()=>showAction('恢复版本 '+row.revision+' 修改前的内容',p=>{p.append(el('p','若相关内容已有后续修改，系统会阻止直接恢复，需手动合并。'));reasonField(p);},async(form,rev)=>{await api('/history/'+row.revision+'/restore','POST',{expected_revision:rev,reason:form.elements.reason.value});await historyPanel();})));}catch(e){fail(e);}
    });p.append(box);});
  }
  $('openSources').addEventListener('click',()=>sourcesPanel().catch(fail));$('openTasks').addEventListener('click',()=>tasksPanel().catch(fail));$('openHistory').addEventListener('click',()=>historyPanel().catch(fail));$('closeUtility').addEventListener('click',()=>$('utilityPanel').hidden=true);
  document.querySelectorAll('[data-pane]').forEach(b=>{if(b.tagName==='BUTTON')b.addEventListener('click',()=>pane(b.dataset.pane));});
  let timer;['wikiSearch','bookFilter','statusFilter','sourceFilter','gapsOnly'].forEach(id=>$(id).addEventListener(id==='wikiSearch'?'input':'change',()=>{clearTimeout(timer);timer=setTimeout(()=>listLessons().catch(fail),160);}));
  async function boot(){
    try{
      if(window.StudyAuth){await window.StudyAuth.ready;if(!window.StudyAuth.isOwner()){$('accessMessage').textContent='数学课时库仅供主人研究与校正。';return;}}
      await loadData();await listLessons();$('wikiApp').hidden=false;$('accessMessage').hidden=true;
      const id=new URLSearchParams(location.search).get('entity')||state.lessons[0]?.id;if(id)await selectLesson(id);
      if(new URLSearchParams(location.search).get('panel')==='tasks')await tasksPanel();
    }catch(e){$('accessMessage').textContent=e.message;fail(e);}
  }
  boot();
})();
