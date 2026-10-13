/* Fixed project examples. No learning sessions, model calls or write requests. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const svgNS = 'http://www.w3.org/2000/svg';
  const state = {data:null, tab:'solution', stage:'verifier', selected:null, graphView:null, player:null};
  const api = {ready:null, state};
  window.Showcase = api;
  function el(tag, cls, text) {
    const node=document.createElement(tag); if(cls)node.className=cls; if(text!=null)node.textContent=text; return node;
  }
  function svg(tag, attributes, text) {
    const node=document.createElementNS(svgNS,tag);
    Object.entries(attributes||{}).forEach(([key,value])=>node.setAttribute(key,String(value)));
    if(text!=null)node.textContent=text;return node;
  }
  function math(node, text) {
    const source=String(text||''), pattern=/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]/g;
    let end=0;
    for(const match of source.matchAll(pattern)) {
      node.append(document.createTextNode(source.slice(end,match.index)));
      const block=match[0].startsWith('$$')||match[0].startsWith('\\['), size=match[0].startsWith('$')&&!block?1:2;
      const span=el('span',block?'math-display':'math-inline');node.append(span);
      if(window.katex)window.katex.render(match[0].slice(size,-size),span,{displayMode:block,throwOnError:false,trust:false,strict:'ignore'});
      else span.textContent=match[0];
      end=match.index+match[0].length;
    }
    node.append(document.createTextNode(source.slice(end)));return node;
  }
  function paragraph(text,cls) {return math(el('p',cls),text);}
  function sourceLink(source) {
    const link=el('a','source-link','查看原题出处 ↗');link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';return link;
  }
  function dimensions(values) {
    const bars=el('div','difficulty-bars');bars.setAttribute('aria-label','预制步骤难度标注，单项0至3');
    Object.entries(values||{}).forEach(([name,value])=>{
      const row=el('div','difficulty-row');row.append(el('span','difficulty-label',name));
      const track=el('span','difficulty-track'),bar=el('span','bar');bar.style.width=(Math.max(0,Math.min(3,Number(value)))/3*100)+'%';track.append(bar);
      row.append(track,el('span','difficulty-value',value+' / 3'));bars.append(row);
    });return bars;
  }
  function renderSolution() {
    const root=$('solution-content'), example=state.data.examples.find(item=>item.id===$('example-select').value)||state.data.examples[0];
    root.replaceChildren();
    const heading=el('div','sample-heading');heading.append(el('span','badge','预制解析示例'),sourceLink(example.source));root.append(heading);
    root.append(paragraph(example.question,'sample-question'));
    example.answer_json.chunk_results.forEach(chunk=>{
      const section=el('section','solution-chunk');section.append(el('h3','','第 '+chunk.chunk_id+' 问 · '+chunk.chunk_type));
      chunk.steps.forEach(step=>{
        const card=el('article','step-card');card.dataset.step=step.step_number;
        const title=el('div','step-heading');title.append(el('span','step-number',String(step.step_number).padStart(2,'0')),el('h4','',step.title));card.append(title);
        card.append(paragraph(step.standard_writing,'standard-writing'));
        const detail=el('details','step-detail');detail.append(el('summary','','展开详细推理'),paragraph(step.detailed_writing));card.append(detail);
        const difficulty=el('details','step-detail difficulty-detail');difficulty.append(el('summary','','查看本步难度维度'),dimensions(step.step_difficulty.dimensions));card.append(difficulty);
        section.append(card);
      });
      section.append(paragraph(chunk.final_answer,'sample-answer'));root.append(section);
    });
    renderPipeline(example);
  }
  function renderPipeline(example) {
    let root=$('pipeline-stage');
    if(!root){root=el('div','pipeline-description');root.id='pipeline-stage';$('solution-content').prepend(root);}
    const result=example.answer_json, count=result.chunk_results.reduce((sum,c)=>sum+c.steps.length,0);
    const descriptions={solver:['求解','从题目条件出发形成解法。当前展示的是已准备的数学解析。',result.final_answer],
      verifier:['校验与结构化','整理关键步骤、知识点与条件，供讲解、回看和错因定位使用。',`本例共 ${count} 个步骤，涉及 ${result.knowledge_points.join('、')}。`],
      formatter:['整理输出','将解析整理为一致的字段，让步骤、答案与难度标注能够在同一界面回看。','预制数据包含题干、分问解析、标准过程、详细过程与五维难度。']};
    const chosen=descriptions[state.stage];root.replaceChildren(el('strong','',chosen[0]),paragraph(chosen[1]),paragraph(chosen[2],'pipeline-result'));
    document.querySelectorAll('[data-pipeline]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.pipeline===state.stage)));
  }
  function renderDiagnosis(revealed) {
    const root=$('diagnosis-content'),data=state.data.diagnosis;root.replaceChildren();
    root.append(paragraph(data.question,'sample-question'),el('p','sample-caption',data.student_label));
    data.lines.forEach((line,index)=>{
      const row=el('article','diagnosis-line'+(revealed&&index===data.first_error?' is-error':''));
      row.append(el('span','step-number',String(index+1).padStart(2,'0')),el('div','diagnosis-writing'));
      row.lastChild.append(el('h4','',line.title),paragraph(line.writing));
      if(revealed&&index===data.first_error)row.lastChild.append(el('span','badge warning','需要先确认定义域'));root.append(row);
    });
    if(revealed){
      const feedback=el('div','diagnosis-feedback');feedback.setAttribute('role','status');
      feedback.append(el('span','badge','预制反馈 · 单题批改原型'),el('h3','',data.error_type),paragraph(data.explanation),paragraph(data.evidence,'correction'),paragraph(data.feedback));
      data.corrected_steps.forEach(step=>{const detail=el('details','step-detail');detail.append(el('summary','',step.title),paragraph(step.standard_writing),paragraph(step.detailed_writing));feedback.append(detail);});
      feedback.append(sourceLink(data.source));root.append(feedback);
    }
    $('diagnosis-reveal').hidden=revealed;$('diagnosis-reset').hidden=!revealed;
  }
  function mountGeometry() {
    if(state.player||!state.data)return;
    const root=$('geometry-host');root.replaceChildren();
    root.append(paragraph(state.data.geometry.question,'sample-question'),el('p','sample-caption',state.data.geometry.source));
    if(!window.StudyGeometry){root.append(el('p','demo-error','几何画板未加载，请刷新。上述几何关系仍可阅读。'));return;}
    state.player=window.StudyGeometry.mount(root,state.data.geometry.answer_json);
    if(state.player){state.player.go(0);state.player.panel.open=true;
      const range=state.player.parameter.querySelector('input');if(range)range.setAttribute('aria-label','截面高度参数 t');
      root.append(paragraph('四个截面顶点位于同一高度，连接后得到边长为 2 的正方形。移动截面不改变其面积 4。','geometry-explanation'));
    }
  }
  function selectTab(name,focus) {
    const tabs=[...document.querySelectorAll('[data-demo-tab]')];
    if(!tabs.some(tab=>tab.dataset.demoTab===name))return;
    state.tab=name;
    tabs.forEach(tab=>{const active=tab.dataset.demoTab===name;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;if(active&&focus)tab.focus();});
    document.querySelectorAll('[data-demo-panel]').forEach(panel=>{panel.hidden=panel.dataset.demoPanel!==name;});
    if(state.player&&name!=='geometry'){
      clearInterval(state.player.parameterTimer);state.player.parameterTimer=null;
      const play=state.player.parameter.querySelector('button');if(play)play.textContent='播放';
    }
    if(name==='geometry'){mountGeometry();if(state.player&&state.player.renderer)requestAnimationFrame(()=>state.player.renderer.resize());}
    if(name==='graph')renderGraph();
  }
  function showRoutine(id,focus) {
    const routine=state.data.catalog.routines.find(r=>r.id===id);if(!routine)return;state.selected=id;
    const root=$('graph-detail');root.replaceChildren();
    root.append(el('span','badge',routine.category),el('h3','',routine.name),el('p','sample-caption','参考目录 '+routine.id+' · '+state.data.catalog.version));
    const list=el('ol','routine-steps');routine.key_steps.forEach(step=>list.append(el('li','',step)));root.append(list);
    root.append(el('h4','','适用信号'),el('p','',routine.retrieval_terms.join('、')));
    if(routine.exclusions.length){root.append(el('h4','','边界与排除条件'));routine.exclusions.forEach(text=>root.append(el('p','',text)));}
    root.append(el('h4','','目录已有的易混淆关系'));
    const related=el('div','related-routines');
    routine.confusable_ids.forEach(other=>{const target=state.data.catalog.routines.find(r=>r.id===other);if(!target)return;
      const button=el('button','related-routine',target.name);button.type='button';button.onclick=()=>{
        $('graph-category').value=target.category;$('graph-search').value='';state.selected=other;renderGraph();showRoutine(other,true);
      };related.append(button);});root.append(related);
    root.append(el('p','sample-caption','此处展示固定参考目录。正式母题归属和教学内容仍需审核。'));
    $('graph-canvas').querySelectorAll('[data-routine-id]').forEach(node=>{const selected=node.dataset.routineId===id;node.classList.toggle('is-selected',selected);node.setAttribute('aria-pressed',String(selected));});
    if(focus){const node=$('graph-canvas').querySelector('[data-routine-id="'+id+'"]');if(node)node.focus();}
  }
  function renderGraph() {
    const canvas=$('graph-canvas');if(!canvas||!state.data)return;
    const category=$('graph-category').value,query=$('graph-search').value.trim().toLowerCase();
    const rows=state.data.catalog.routines.filter(r=>(!category||r.category===category)&&(!query||[r.name,r.id,...r.retrieval_terms,...r.aliases,...r.key_steps].join(' ').toLowerCase().includes(query)));
    canvas.replaceChildren();const box=canvas.getBoundingClientRect(),cellWidth=234,cellHeight=94;
    const columns=Math.max(1,Math.min(4,Math.floor((box.width||1000)/cellWidth)));
    const width=Math.max(280,columns*cellWidth+64);
    // Keep each node readable. A large directory extends beyond the viewport
    // and is explored by panning/filtering rather than shrinking every label.
    const height=Math.max(300,Math.round(width*(box.height||480)/(box.width||1000)));
    state.graphBase={x:0,y:0,w:width,h:height};state.graphView={...state.graphBase};applyGraphView();
    const count=$('graph-count');if(count)count.textContent=`当前 ${rows.length} 个节点 · 全目录 ${state.data.catalog.routines.length} 个参考套路 · 拖动空白处或用方向键平移`;
    const headerWidth=Math.min(320,width-32),center=width/2;
    const top=svg('g',{class:'graph-category-node'});top.append(svg('rect',{x:center-headerWidth/2,y:18,width:headerWidth,height:46,rx:16}),svg('text',{x:center,y:47,'text-anchor':'middle'},category||'12 个知识板块 · 参考目录'));canvas.append(top);
    if(!rows.length){canvas.append(svg('text',{x:center,y:180,'text-anchor':'middle',class:'graph-empty'},'没有匹配的套路'));$('graph-detail').replaceChildren(el('p','','没有找到对应节点，换一个关键词试试。'));return;}
    const positions=new Map(rows.map((row,i)=>[row.id,{x:32+(i%columns)*cellWidth,y:112+Math.floor(i/columns)*cellHeight}]));
    const edges=svg('g',{class:'graph-edges','aria-hidden':'true'}),seen=new Set();
    rows.forEach(row=>{
      const p=positions.get(row.id);edges.append(svg('path',{d:`M${center} 64 C${center} 82 ${p.x+106} 82 ${p.x+106} ${p.y}`,class:'graph-edge contains'}));
      row.confusable_ids.forEach(id=>{if(!positions.has(id))return;const key=[row.id,id].sort().join(':');if(seen.has(key))return;seen.add(key);
        const other=positions.get(id);edges.append(svg('path',{d:`M${p.x+106} ${p.y+30} Q${(p.x+other.x)/2+106} ${Math.min(p.y,other.y)-28} ${other.x+106} ${other.y+30}`,class:'graph-edge confusable'}));});
    });canvas.append(edges);
    rows.forEach(row=>{
      const p=positions.get(row.id),group=svg('g',{transform:`translate(${p.x},${p.y})`,class:'graph-node',tabindex:0,role:'button','aria-label':row.name,'aria-pressed':'false','data-routine-id':row.id});
      group.append(svg('rect',{width:212,height:64,rx:13}),svg('text',{x:12,y:18,class:'graph-id'},row.id));
      const title=svg('text',{x:12,y:38,class:'graph-title'});
      const words=Array.from(row.name),line=words.slice(0,14).join('');title.append(svg('tspan',{x:12,y:38},line));
      if(words.length>14)title.append(svg('tspan',{x:12,y:54},words.slice(14,29).join('')+(words.length>29?'…':'')));
      group.append(title,svg('title',{},row.name));group.addEventListener('click',()=>showRoutine(row.id));
      group.addEventListener('focus',()=>{
        const view=state.graphView;
        if(p.x<view.x||p.x+212>view.x+view.w||p.y<view.y||p.y+64>view.y+view.h){
          view.x=p.x+106-view.w/2;view.y=p.y+32-view.h/2;applyGraphView();
        }
      });
      group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showRoutine(row.id);}});canvas.append(group);
    });
    const first=rows.find(r=>r.id===state.selected)||rows[0];showRoutine(first.id);
  }
  function applyGraphView() {const view=state.graphView;if(view)$('graph-canvas').setAttribute('viewBox',[view.x,view.y,view.w,view.h].join(' '));}
  function zoomGraph(factor) {
    const old=state.graphView;if(!old)return;const w=Math.max(240,Math.min(state.graphBase.w*2,old.w*factor)),h=w*old.h/old.w;
    state.graphView={x:old.x+(old.w-w)/2,y:old.y+(old.h-h)/2,w,h};applyGraphView();
  }
  function wireGraph() {
    const select=$('graph-category');state.data.catalog.routines.map(r=>r.category).filter((c,i,a)=>a.indexOf(c)===i).forEach(c=>select.append(new Option(c,c)));
    select.value=state.data.catalog.routines[0].category;
    select.onchange=renderGraph;$('graph-search').oninput=renderGraph;
    $('graph-zoom-in').onclick=()=>zoomGraph(.8);$('graph-zoom-out').onclick=()=>zoomGraph(1.25);$('graph-reset').onclick=()=>{state.graphView={...state.graphBase};applyGraphView();};
    const canvas=$('graph-canvas');let drag=null;
    canvas.addEventListener('pointerdown',event=>{if(event.target.closest('[data-routine-id]'))return;drag={x:event.clientX,y:event.clientY,view:{...state.graphView}};canvas.setPointerCapture(event.pointerId);});
    canvas.addEventListener('pointermove',event=>{if(!drag)return;const box=canvas.getBoundingClientRect();
      state.graphView={...drag.view,x:drag.view.x-(event.clientX-drag.x)*drag.view.w/box.width,y:drag.view.y-(event.clientY-drag.y)*drag.view.h/box.height};applyGraphView();});
    const end=()=>{drag=null;};canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
    canvas.addEventListener('keydown',event=>{
      if(event.target!==canvas)return;const offsets={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
      if(offsets[event.key]){event.preventDefault();state.graphView.x+=offsets[event.key][0]*state.graphView.w*.08;state.graphView.y+=offsets[event.key][1]*state.graphView.h*.08;applyGraphView();}
      else if(event.key==='+'||event.key==='='){event.preventDefault();zoomGraph(.8);}else if(event.key==='-'){event.preventDefault();zoomGraph(1.25);}
    });window.addEventListener('resize',()=>{if(state.tab==='graph')renderGraph();});renderGraph();
  }
  function wireNavigation() {
    const toggle=$('menu-toggle'),nav=$('main-nav');
    const close=()=>{if(toggle)toggle.setAttribute('aria-expanded','false');if(nav)nav.classList.remove('is-open');};
    if(toggle&&nav){toggle.onclick=()=>{const open=toggle.getAttribute('aria-expanded')!=='true';toggle.setAttribute('aria-expanded',String(open));nav.classList.toggle('is-open',open);};
      nav.querySelectorAll('a').forEach(link=>link.addEventListener('click',close));document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});}
    const tabs=[...document.querySelectorAll('[data-demo-tab]')];tabs.forEach(tab=>{
      tab.onclick=()=>selectTab(tab.dataset.demoTab);
      tab.addEventListener('keydown',event=>{let index=tabs.indexOf(tab);if(event.key==='ArrowRight')index=(index+1)%tabs.length;else if(event.key==='ArrowLeft')index=(index-1+tabs.length)%tabs.length;else if(event.key==='Home')index=0;else if(event.key==='End')index=tabs.length-1;else return;event.preventDefault();selectTab(tabs[index].dataset.demoTab,true);});
    });
    document.querySelectorAll('[data-show-demo]').forEach(link=>link.addEventListener('click',()=>{if(state.data)selectTab(link.dataset.showDemo);}));
  }
  async function start() {
    wireNavigation();
    const response=await fetch('/showcase/data.json',{credentials:'omit'});if(!response.ok)throw new Error('展示样例加载失败');
    const data=await response.json();if(data.schema_version!==1||!data.examples.length)throw new Error('展示样例版本不匹配');state.data=data;
    const select=$('example-select');select.replaceChildren();data.examples.forEach(example=>select.append(new Option(example.label,example.id)));select.onchange=renderSolution;
    document.querySelectorAll('[data-pipeline]').forEach(button=>button.onclick=()=>{state.stage=button.dataset.pipeline;renderSolution();});
    $('diagnosis-reveal').onclick=()=>renderDiagnosis(true);$('diagnosis-reset').onclick=()=>renderDiagnosis(false);
    renderSolution();renderDiagnosis(false);wireGraph();selectTab('solution');
    const status=$('demo-status');if(status)status.textContent='预制样例已就绪。点击下方标签，自由查看。';
    document.documentElement.classList.add('showcase-ready');return data;
  }
  api.selectTab=selectTab;api.zoomGraph=zoomGraph;
  api.ready=start().catch(error=>{
    const target=$('demo-status')||$('examples');if(target){target.textContent='展示样例暂未加载，请刷新页面重试。项目介绍和研究规划仍可阅读。';target.setAttribute('role','alert');}
    state.loadError=error.message;return null;
  });
})();
