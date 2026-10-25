(function () {
  'use strict';
  const base='/showcase/question-bank/', $=id=>document.getElementById(id);
  const state={meta:null,index:null,loading:null,parts:new Map(),selected:new Map(),page:1,rows:[],question:null,sequence:0,routine:null,teacher:false,tab:'library'};
  let api, h, detailReady=Promise.resolve();
  async function json(name){const response=await fetch(base+name,{credentials:'omit'});if(!response.ok)throw new Error('题库加载失败，请重试。');return response.json();}
  function option(select,value,label){select.append(new Option(label,value));}
  async function load(){
    if(state.index)return;
    if(!state.loading)state.loading=Promise.all([json('manifest.json'),json('index.json')]).then(([meta,index])=>{
      state.meta=meta;state.index=index;
      for(const category of meta.categories)option($('bank-category'),category,category);
      for(const year of meta.years)option($('bank-year'),year,year+'年');
      for(const type of meta.types)option($('bank-type'),type,type);
      for(const source of meta.sources)option($('bank-source'),String(source.id),source.name);
      $('bank-total').textContent=meta.count.toLocaleString('zh-CN')+' 道题';
    }).catch(error=>{state.loading=null;throw error;});
    await state.loading;
  }
  async function detail(id){
    const filename=state.meta.parts[id];
    if(!filename)throw new Error('没有找到这道题。');
    if(!state.parts.has(filename))state.parts.set(filename,json(filename));
    try{return (await state.parts.get(filename))[id];}
    catch(error){state.parts.delete(filename);throw error;}
  }
  function labels(row){const names=row.source_ids.map(id=>state.meta.sources.find(source=>source.id===id)?.name).filter(Boolean);return [row.year&&row.year+'年',row.type,...row.categories.slice(0,2),names[0]].filter(Boolean).join(' / ');}
  function filter(){
    const words=$('bank-search').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const category=$('bank-category').value,year=$('bank-year').value,type=$('bank-type').value,source=$('bank-source').value;
    state.rows=state.index.filter(row=>(!category||row.categories.includes(category))&&(!year||row.year===year)&&(!type||row.type===type)&&(!source||row.source_ids.includes(Number(source)))&&(!state.routine||row.routine===state.routine)&&words.every(word=>(row.question+' '+labels(row)).toLowerCase().includes(word)));
    state.page=Math.min(state.page,Math.max(1,Math.ceil(state.rows.length/20)));
    render();
  }
  function render(){
    const root=$('library-list');root.replaceChildren();
    const page=state.rows.slice((state.page-1)*20,state.page*20);
    for(const row of page){
      const item=h.el('article','bank-row'+(row.id===state.question?' is-selected':''));
      const input=h.el('input');input.type='checkbox';input.checked=state.selected.has(row.id);input.setAttribute('aria-label','选入试卷：题目 '+row.id);
      input.onchange=()=>{if(input.checked){if(state.selected.size>=50){input.checked=false;$('bank-selection').textContent='一次最多选择50道题';return;}state.selected.set(row.id,row);}else state.selected.delete(row.id);selection();};
      const open=h.button('',()=>showQuestion(row.id),'bank-open');
      open.append(h.el('span','bank-row-meta',labels(row)),h.p(row.question,'bank-row-question'));
      item.append(input,open);root.append(item);
    }
    if(!page.length)root.append(h.el('p','bank-empty','没有找到题目，请调整筛选条件。'));
    const count=state.rows.length,pages=Math.max(1,Math.ceil(count/20));
    $('bank-result-count').textContent='找到 '+count.toLocaleString('zh-CN')+' 道题';
    $('bank-page-label').textContent=state.page+' / '+pages;
    $('bank-prev').disabled=state.page===1;$('bank-next').disabled=state.page>=pages;
    $('bank-clear-routine').hidden=!state.routine;selection();
    if(page.length&&!state.rows.some(row=>row.id===state.question))detailReady=showQuestion(page[0].id);
    if(!page.length)$('bank-detail').replaceChildren(h.el('p','bank-empty','没有匹配的题目。'));
  }
  function selection(){const count=state.selected.size;$('bank-selection').textContent=count?'已选 '+count+' 道题':'选择题目后可组卷';$('bank-build-exam').disabled=!count;$('bank-clear-selection').disabled=!count;}
  function explanation(root,item){
    const result=item.answer_json;
    if(result?.chunk_results?.length){
      for(const chunk of result.chunk_results){
        const block=h.el('section','bank-chunk');block.append(h.el('h4','','第 '+chunk.chunk_id+' 问'));
        for(const step of chunk.steps){
          const card=h.el('article','bank-step');card.append(h.el('h4','','步骤 '+step.step_number+'：'+step.title),h.p(step.standard_writing));
          if(step.detailed_writing)card.append(h.details('详细过程',h.p(step.detailed_writing,'detail-content'),'step-detail'));
          block.append(card);
        }
        root.append(block);
      }
    }else if(item.solution)root.append(h.p(item.solution,'bank-solution'));
  }
  function images(root,item){
    const seen=new Set();
    for(const source of item.sources)for(const asset of source.images){
      if(seen.has(asset.ref))continue;seen.add(asset.ref);
      const figure=h.el('figure','bank-figure'),image=h.el('img');image.src=base+'images/'+asset.ref;image.alt=asset.label;image.loading='lazy';image.width=700;
      figure.append(image,h.el('figcaption','',asset.label));root.append(figure);
    }
  }
  async function showQuestion(id){
    const sequence=++state.sequence;state.question=id;
    const root=$('bank-detail');root.replaceChildren(h.el('p','bank-empty','正在加载题目…'));
    $('library-list').querySelectorAll('.bank-row').forEach((row,i)=>row.classList.toggle('is-selected',state.rows[(state.page-1)*20+i]?.id===id));
    try{
      const item=await detail(id);if(sequence!==state.sequence)return;
      root.replaceChildren(h.el('div','bank-detail-meta',[item.year&&item.year+'年',item.type,...item.categories].filter(Boolean).join(' / ')),h.p(item.question,'bank-question'));
      images(root,item);
      const answer=h.el('div','detail-content');answer.append(h.p(item.answer||'题源未附答案。','bank-original-answer'));
      explanation(answer,item);
      root.append(h.details('答案与解析',answer,'step-detail bank-answer'));
      const origins=h.el('section','bank-sources');origins.append(h.el('h3','','题目出处'));
      for(const source of item.sources){
        const line=h.el('p');let caption=source.name+(source.question_no?' / 第'+source.question_no+'题':'')+(source.page_start?' / 第'+source.page_start+'页':'');
        if(source.url){const link=h.el('a','',caption);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';line.append(link);}else line.textContent=caption;
        origins.append(line);
      }
      root.append(origins);
      if(item.method)root.append(h.el('h3','','方法'),h.el('p','',item.method));
      if(item.match.primary){
        const routine=api.state.data.catalog.routines.find(row=>row.id===item.match.primary);
        const section=h.el('section','bank-method');section.append(h.el('h3','','套路归类'),h.el('p','bank-review-status','待审核'));
        if(routine)section.append(h.button(routine.name,()=>{api.selectView('graph');api.focusRoutine(routine.id);},'button'));
        root.append(section);
      }
    }catch(error){if(sequence===state.sequence)root.replaceChildren(h.el('p','bank-empty',error.message),h.button('重试',()=>showQuestion(id),'button'));}
  }
  async function show(){
    try{await load();filter();if(state.question===null&&state.rows[0])detailReady=showQuestion(state.rows[0].id);await detailReady;}
    catch(error){$('library-list').replaceChildren(h.el('p','bank-empty',error.message),h.button('重试',show,'button'));}
  }
  function tab(name){
    state.tab=name;
    document.querySelectorAll('[data-library-tab]').forEach(button=>{const selected=button.dataset.libraryTab===name;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;});
    document.querySelectorAll('[data-library-panel]').forEach(panel=>panel.hidden=panel.dataset.libraryPanel!==name);
    $('bank-toolbar').hidden=name!=='library';$('bank-actions').hidden=name!=='library';
    $('library-layout').classList.toggle('is-library',name==='library');
    if(name==='exam')return renderExam(state.teacher);
    if(name==='library'&&api.state.view==='library')return show();
  }
  async function renderExam(teacher){
    if(typeof teacher==='boolean')state.teacher=teacher;
    $('exam-student').setAttribute('aria-pressed',String(!state.teacher));$('exam-teacher').setAttribute('aria-pressed',String(state.teacher));
    $('exam-student').classList.toggle('active',!state.teacher);$('exam-teacher').classList.toggle('active',state.teacher);
    const root=$('exam-preview'),ids=[...state.selected.keys()];
    root.replaceChildren(h.el('p','bank-empty',ids.length?'正在整理试卷…':'先从题库选择题目。'));
    const version=++state.examVersion||1;state.examVersion=version;
    try{
      const items=await Promise.all(ids.map(detail));if(version!==state.examVersion)return;
      root.replaceChildren();
      if(!items.length){root.append(h.el('p','bank-empty','先从题库选择题目。'));return;}
      const paper=h.el('div','exam-paper');paper.append(h.el('h3','','数学练习卷'),h.el('p','exam-meta',(state.teacher?'教师版':'学生版')+' / '+items.length+'题'));
      items.forEach((item,i)=>{const section=h.el('section','exam-question');section.append(h.el('h4','','第'+(i+1)+'题'),h.p(item.question));images(section,item);if(state.teacher){section.append(h.p('答案：'+(item.answer||'题源未附答案。')));explanation(section,item);}else section.append(h.el('div','answer-space'));paper.append(section);});
      root.append(paper);
    }catch(error){root.replaceChildren(h.el('p','bank-empty',error.message));}
  }
  async function openRoutine(id){await load();state.routine=id;state.page=1;state.question=null;$('bank-search').value='';for(const field of ['category','year','type','source'])$('bank-'+field).value='';api.selectView('library');tab('library');filter();}
  function reset(){state.selected.clear();state.routine=null;state.question=null;state.page=1;state.sequence++;for(const field of ['search','category','year','type','source'])$('bank-'+field).value='';if(state.index)filter();tab('library');}
  function snapshot(){
    const filters={};for(const field of ['search','category','year','type','source'])filters[field]=$('bank-'+field).value.slice(0,300);
    return {filters,selected:[...state.selected.keys()],page:state.page,question:state.question,routine:state.routine,teacher:state.teacher,tab:state.tab};
  }
  async function restore(saved){
    if(!saved||typeof saved!=='object'||Array.isArray(saved))return show();
    try{
      await load();const byId=new Map(state.index.map(row=>[String(row.id),row]));
      for(const field of ['search','category','year','type','source']){
        const input=$('bank-'+field),value=saved.filters?.[field];
        if(typeof value==='string'&&value.length<=300&&(field==='search'||[...input.options].some(option=>option.value===value)))input.value=value;
      }
      state.selected.clear();if(Array.isArray(saved.selected))for(const id of saved.selected.slice(0,50)){const row=byId.get(String(id));if(row)state.selected.set(row.id,row);}
      state.page=Number.isInteger(saved.page)&&saved.page>0&&saved.page<10000?saved.page:1;
      state.routine=typeof saved.routine==='string'&&state.index.some(row=>row.routine===saved.routine)?saved.routine:null;
      state.teacher=saved.teacher===true;const chosen=byId.get(String(saved.question));state.question=chosen?.id??null;
      filter();await detailReady;
      if(state.question!==null&&state.rows.some(row=>row.id===state.question))await showQuestion(state.question);
      const name=['library','exam','calendar'].includes(saved.tab)?saved.tab:'library';await tab(name);
    }catch(error){$('library-list').replaceChildren(h.el('p','bank-empty',error.message),h.button('重试',show,'button'));}
  }
  function init(showcase,helpers){
    api=showcase;h=helpers;api.state.bank=state;
    let debounce;$('bank-search').oninput=()=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.page=1;filter();},180);};
    for(const field of ['category','year','type','source'])$('bank-'+field).onchange=()=>{state.page=1;filter();};
    $('bank-prev').onclick=()=>{state.page--;render();};$('bank-next').onclick=()=>{state.page++;render();};
    $('bank-clear-routine').onclick=()=>{state.routine=null;state.page=1;filter();};
    $('bank-clear-selection').onclick=()=>{state.selected.clear();render();};
    $('bank-build-exam').onclick=()=>tab('exam');
    const calendar=$('calendar-content');calendar.replaceChildren();
    for(const entry of api.state.data.library.calendar){const day=h.button('',()=>api.selectView(entry.view),'calendar-day');day.append(h.el('strong','',entry.date),h.el('span','',entry.title),h.el('small','',entry.method));calendar.append(day);}
    tab('library');
  }
  window.ShowcaseBank={init,show,tab,renderExam,openRoutine,reset,snapshot,restore,state};
})();
