(() => {
  'use strict';
  document.documentElement.classList.add('js-enabled');
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const fieldList = (items, className = '') => {
    const dl = make('dl', className);
    items.forEach(([name, value]) => {
      const row = make('div');
      row.append(make('dt', '', name), make('dd', '', value));
      dl.append(row);
    });
    return dl;
  };
  const pressed = (selector, predicate) => $$(selector).forEach((button) => {
    const selected = predicate(button);
    button.setAttribute('aria-pressed', String(selected));
    button.classList.toggle('is-selected', selected);
  });
  const dateText = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? String(value || '时间未记录') : date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false});
  };
  function mathText(node, content) {
    node.replaceChildren();
    const expression = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;
    let start = 0;
    for (const match of content.matchAll(expression)) {
      node.append(document.createTextNode(content.slice(start, match.index)));
      const span = make('span');
      if (window.katex) {
        try { window.katex.render(match[1] || match[2], span, {throwOnError:false, displayMode:Boolean(match[1]), trust:false}); }
        catch { span.textContent = match[0]; }
      } else span.textContent = match[0];
      node.append(span);
      start = match.index + match[0].length;
    }
    node.append(document.createTextNode(content.slice(start)));
  }
  $$('.math-text').forEach((node) => mathText(node, node.textContent));

  const menu = $('.menu-toggle');
  const nav = $('#primary-nav');
  function closeMenu() {
    if (!menu || !nav) return;
    menu.setAttribute('aria-expanded','false');
    menu.querySelector('.sr-only').textContent = '打开目录';
    nav.classList.remove('is-open');
  }
  menu?.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open));
    menu.querySelector('.sr-only').textContent = open ? '关闭目录' : '打开目录';
    nav.classList.toggle('is-open',open);
  });
  $$('.primary-nav a').forEach((link) => link.addEventListener('click',closeMenu));
  document.addEventListener('keydown',(event) => { if (event.key === 'Escape') closeMenu(); });
  const navLinks = $$('.primary-nav a');
  const navTargets = navLinks.map((link) => $(link.getAttribute('href')));
  let scrollPending = false;
  function updateReading() {
    const y = window.scrollY + ($('.site-header')?.offsetHeight || 72) + 130;
    let current = 0;
    navTargets.forEach((target,index) => { if (target && target.offsetTop <= y) current=index; });
    navLinks.forEach((link,index) => {
      link.classList.toggle('is-active',index===current);
      if (index===current) link.setAttribute('aria-current','location'); else link.removeAttribute('aria-current');
    });
    const full = document.documentElement.scrollHeight - innerHeight;
    const progress = $('#reading-progress-bar');
    if (progress) progress.style.transform = `scaleX(${full > 0 ? Math.min(1, Math.max(0, window.scrollY/full)) : 0})`;
    scrollPending = false;
  }
  const requestReading = () => { if (!scrollPending) { scrollPending=true; requestAnimationFrame(updateReading); } };
  addEventListener('scroll',requestReading,{passive:true});
  addEventListener('resize',requestReading);
  updateReading();

  // All selectors stay operable with the keyboard; the page retains native scrolling.
  $$('[role="group"]').forEach((group) => group.addEventListener('keydown', (event) => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key) || event.target.tagName !== 'BUTTON') return;
    const buttons = [...group.querySelectorAll('button:not(:disabled)')];
    if (!buttons.length) return;
    let index = buttons.indexOf(event.target);
    if (event.key==='Home') index=0;
    else if (event.key==='End') index=buttons.length-1;
    else index=(index+(event.key==='ArrowRight'?1:buttons.length-1))%buttons.length;
    event.preventDefault(); buttons[index].focus(); buttons[index].click();
  }));

  const D = window.WENXIA_DEMO;
  if (!D) { $('#record-load-state').textContent='交互说明暂时无法载入，仍可阅读本页静态内容与原始材料。'; return; }
  const flow = $('#flow-detail');
  const overview = [...flow.childNodes].map((node) => node.cloneNode(true));
  function selectPhase(id) {
    const stage = D.phases.find((item) => item.id===id);
    pressed('[data-phase]',(button) => button.dataset.phase===id);
    $('.system-map').classList.toggle('is-tracing',Boolean(stage));
    $$('[data-node]').forEach((node) => node.classList.toggle('is-active',Boolean(stage?.nodes.includes(node.dataset.node))));
    $$('[data-edge]').forEach((edge) => edge.classList.toggle('is-active',Boolean(stage?.edges.includes(edge.dataset.edge))));
    if (!stage) { flow.replaceChildren(...overview.map((node) => node.cloneNode(true))); return; }
    const summary = make('div');
    summary.append(make('span','detail-kicker',`教学业务阶段 ${D.phases.indexOf(stage)+1} / 7 · 拟议流程`),make('h3','',stage.label),make('p','',stage.action));
    flow.replaceChildren(summary,fieldList([['责任模块',stage.owner],['输入',stage.input],['输出',stage.output],['数据库读写',stage.rw]],'flow-fields'));
  }
  $$('[data-phase]').forEach((button) => button.addEventListener('click',() => selectPhase(button.dataset.phase)));

  function selectEvidence(id) {
    const entry = D.evidence.find((item) => item.id===id);
    if (!entry) return;
    pressed('[data-evidence]',(button) => button.dataset.evidence===id);
    $('#evidence-title-live').textContent = `${entry.type} · ${entry.title}`;
    $('#evidence-source-meta').textContent = entry.source;
    $('#evidence-record').textContent = entry.record;
    $('#evidence-meaning').textContent = entry.meaning;
  }
  $$('[data-evidence]').forEach((button) => button.addEventListener('click',() => selectEvidence(button.dataset.evidence)));
  selectEvidence('db1');

  // Restore every old-site vision entry in the new site's main reading path.
  const visionMeta = $('#vision-catalog-meta');
  const visionList = $('#vision-catalog-list');
  let visionGroups = [];
  let visionGroupFilter = 'all';
  let visionPhaseFilter = 'all';
  const phaseNames = {'before-class':'课前','class':'课堂','homework':'作业与练习','exam':'考试','review':'复习与接续'};
  const visionPhases = {
    students:{'课前准备':'before-class','课堂跟进':'class','个性化作业':'homework','统一负担预算':'homework','搜题诊断':'homework','卡点讲解':'class','分级提示':'class','步骤批改':'homework','错因分析':'homework','合理刷题':'homework','局部步骤训练':'homework','新题迁移':'homework','知识理解':'class','错题管理':'review','订正复习':'review','学习计划':'review','考试复盘':'exam','成长评价':'review','长期助教':'review','帮助可获得性':'class','自主学习':'review'},
    teachers:{'学情备课依据':'before-class','备课材料':'before-class','PPT':'before-class','课堂演示':'class','理解检查':'class','课堂时间分配':'class','作业分配':'homework','批改复核':'homework','班级学情':'homework','问题讲评':'homework','出卷评卷':'exam','教学调整':'review','个别辅导':'class','干预跟进':'review','学生评价':'review','经验积累':'review','对话式任务协同':'review'},
    schools:{'教学质量':'review','问题早发现':'before-class','问题范围定位':'homework','持续教研':'review','教师评价':'review','资源配置':'before-class','负担管理':'homework','公平支持':'review','校本课程':'before-class','共同标准':'before-class','资源库':'before-class','教材更新':'before-class','经验传承':'review','渐进接入':'before-class','投入评价':'review','数据历史管理':'review','跨学科':'review'},
    society:{'补课依赖':'review','家庭经济负担':'review','城乡区域差异':'review','学习机会公平':'review','家长时间焦虑':'review','减负提质':'homework','校内教育支持':'class','优质经验共享':'review'}
  };
  const newTarget = {'#single':'#scenario','#teacher':'#classroom-demo','#longterm':'#longitudinal-evidence','#library':'#teaching-object','#time':'#diagnostic-cases','#exam':'#benchmark','#school':'#deployment','#agent':'#agent','#terms':'#teaching-object','#evolution':'#research'};
  function renderVisionCatalog() {
    if (!visionList) return;
    visionList.replaceChildren();
    let visible = 0;
    visionGroups.forEach((group) => {
      if (visionGroupFilter !== 'all' && group.id !== visionGroupFilter) return;
      const rows = group.rows.filter((row) => visionPhaseFilter === 'all' || (visionPhases[group.id]?.[row.aspect] || 'review') === visionPhaseFilter);
      if (!rows.length) return;
      const groupSection = make('section','vision-group');
      groupSection.append(make('h3','',`${group.title} · ${rows.length} 条`));
      rows.forEach((row) => {
        visible += 1;
        const phase = visionPhases[group.id]?.[row.aspect] || 'review';
        const detail = make('details','vision-entry');
        const summary = make('summary','vision-entry-summary');
        summary.append(make('span','vision-entry-phase',phaseNames[phase]),make('b','',row.aspect),make('span','',row.short_vision || '查看该项需求与支撑状态'));
        detail.append(summary);
        const body = make('div','vision-entry-body');
        const before = make('p',''); before.append(make('b','','原有困难：'),document.createTextNode(row.before || ''));
        const after = make('p',''); after.append(make('b','','期望变化：'),document.createTextNode(row.after || ''));
        body.append(before,after);
        const states = make('div','vision-feature-list');
        (row.features || []).forEach((feature) => {
          const href = newTarget[feature.target] || '#teaching-object';
          const a = make('a','vision-feature',`${feature.label} · ${feature.status}`);
          a.href = href;
          states.append(a);
        });
        body.append(states);
        detail.append(body);
        groupSection.append(detail);
      });
      visionList.append(groupSection);
    });
    if (visionMeta) visionMeta.textContent = `显示 ${visible} / 63 条 · 按对象与教学过程筛选`;
    $$('.vision-group').forEach((group) => group.hidden = !group.querySelector('.vision-entry'));
    requestReading();
  }
  $$('[data-vision-group]').forEach((button) => button.addEventListener('click',() => {
    visionGroupFilter = button.dataset.visionGroup;
    pressed('[data-vision-group]',(item) => item.dataset.visionGroup === visionGroupFilter);
    renderVisionCatalog();
  }));
  $$('[data-vision-phase]').forEach((button) => button.addEventListener('click',() => {
    visionPhaseFilter = button.dataset.visionPhase;
    pressed('[data-vision-phase]',(item) => item.dataset.visionPhase === visionPhaseFilter);
    renderVisionCatalog();
  }));
  async function loadVisionCatalog() {
    try {
      const source = await readJSON('/showcase/vision-content.json');
      visionGroups = source.groups || [];
      const count = visionGroups.reduce((sum,group) => sum + (group.rows || []).length,0);
      if (count !== 63) throw new Error('愿景条目数不符合 63 项快照');
      renderVisionCatalog();
    } catch {
      if (visionMeta) visionMeta.textContent = '应用愿景暂时无法加载，可打开完整愿景档案查看。';
    }
  }

  const longitudinalData = {
    error:['T0 · 初次作答','当前判断：本题联立求角步骤出现错误','依据：原答片段“C=π/3”。这是一次观察，错误原因未知。','是否会在无提示条件下识别关系；是否能迁移到新题；延迟保持。','必要时用短问题检查概念理解，再安排无提示新题。','DB2 追加本次原答；DB3 只提出有边界的暂定判断。'],
    hint:['T1 · 提示后订正','当前判断：本题在帮助条件下订正正确','依据：学生看过涉及求 C 与两角展开的提示后，完成了同题推导。','能否独立选择方法、迁移至未见题、间隔后保持。','记录帮助等级；选择一道不暴露方法标签的新题。','DB2 新增 HelpExposure 与辅助订正；DB3 不升级为独立掌握。'],
    independent:['T2 · 无提示新题（方案示例）','当前判断：在一个新题上独立完成目标步骤','依据：假设新题未暴露过且无提示，操作正确并引用原答。','是否能迁移至更复杂题族；是否能延迟保持；单题偶然性。','安排不同题族的延迟复测，而不是重复原题。','DB2 新增独立作答事实；DB3 只把判断范围扩到该目标的一次迁移表现。'],
    delayed:['T3 · 延迟复测（方案示例）','当前判断：该目标在一次间隔复测中再次完成','依据：假设延迟新题正确；时间间隔、题族与帮助条件都要入记录。','其他方法、适用条件和整章表现仍需后续观察。','保留低负担的后续抽查；依据课程节奏安排，不持续加题。','DB2 追加延迟事件；DB3 可增强该目标的证据并记录适用范围。'],
    teacher:['T4 · 教师复核（方案示例）','当前判断：撤回由误读原答支持的旧结论','依据：假设教师复核发现学生使用了另一条有效路径，并提供对应原答位置。','复核结论适用于本次作答；后续任务继续通过新证据验证。','撤回相关补救任务，改为一项无提示迁移检查。','DB2 追加教师评分修订；DB3 保留旧版本、撤回无支持主张，重算个人任务和班级汇总。']
  };
  function renderLongitudinal(id) {
    const row = longitudinalData[id]; if (!row) return;
    pressed('[data-longitudinal]',(button) => button.dataset.longitudinal === id);
    ['#longitudinal-time','#longitudinal-claim','#longitudinal-evidence-line','#longitudinal-unknown','#longitudinal-next','#longitudinal-write'].forEach((selector,index) => { if ($(selector)) $(selector).textContent = row[index]; });
  }
  $$('[data-longitudinal]').forEach((button) => button.addEventListener('click',() => renderLongitudinal(button.dataset.longitudinal)));

  const classDemo = {
    before:['4 / 9','有效作答中被归为“联立求角”错误','原答：由另一条有效边角路径求出三角形高。系统初判为关键步骤缺失。','暂记：本题路径需要教师核对；新题迁移未知。','教师复核后，再确定是否需要补充练习。','教师复核前，班级报告按 9 份有效答卷计算。'],
    after:['3 / 9','有效作答中被归为“联立求角”错误','教师定位到 S07 的原答与有效替代路径，改判为本题正确。','撤回“关键步骤缺失”；记录该替代方法本题有效，迁移仍未知。','取消重复补练，安排一题无提示新题检查方法选择。','仅修订 S07 的记录：4/9 → 3/9；1 份识别未知、2 人缺交继续单列，历史报告可回查。']
  };
  function renderClassDemo(id) {
    const row = classDemo[id]; if (!row) return;
    pressed('[data-class-demo]',(button) => button.dataset.classDemo === id);
    ['#class-error-count','#class-error-label','#class-student-answer','#class-student-state','#class-next-task','#class-correction-note'].forEach((selector,index) => { if ($(selector)) $(selector).textContent = row[index]; });
  }
  $$('[data-class-demo]').forEach((button) => button.addEventListener('click',() => renderClassDemo(button.dataset.classDemo)));

  let traceName = 'normal';
  let traceIndex = 0;
  function renderTrace() {
    const trace = D.traces[traceName];
    const item = trace.steps[traceIndex];
    pressed('[data-trace]',(button) => button.dataset.trace===traceName);
    $('#trace-intro').textContent = trace.intro;
    $('#trace-state').textContent = item.state;
    $('#trace-action').textContent = item.action;
    $('#trace-tool').textContent = item.tool;
    $('#trace-check').textContent = item.check;
    $('#trace-next-state').textContent = item.next;
    $('#trace-count').textContent = `${String(traceIndex+1).padStart(2,'0')} / ${String(trace.steps.length).padStart(2,'0')}`;
    $('#trace-prev').disabled = traceIndex===0;
    $('#trace-next').disabled = traceIndex===trace.steps.length-1;
    $$('.loop-flow article').forEach((node,index) => node.classList.toggle('is-current',index===item.phase));
  }
  $$('[data-trace]').forEach((button) => button.addEventListener('click',() => { traceName=button.dataset.trace; traceIndex=0; renderTrace(); }));
  $('#trace-prev').addEventListener('click',() => { if (traceIndex>0) { traceIndex--; renderTrace(); } });
  $('#trace-next').addEventListener('click',() => { if (traceIndex<D.traces[traceName].steps.length-1) { traceIndex++; renderTrace(); } });
  renderTrace();

  function selectTraining(index) {
    const item = D.lora[index];
    if (!item) return;
    pressed('[data-training]',(button) => Number(button.dataset.training)===index);
    $('#training-title').textContent = item.title;
    $('#training-copy').textContent = item.body;
    $('#training-sample').textContent = item.sample;
  }
  $$('[data-training]').forEach((button) => button.addEventListener('click',() => selectTraining(Number(button.dataset.training))));
  const models = {
    '4B':['资源下限档','4B · 低资源能力边界','固定教学任务、数据库和工具，测证据使用、动作遵循与有限提示。报告无法稳定完成的任务和转复核负担；硬件、时延与成功任务成本均待实测。'],
    '9B':['重点适配档','9B · 完整系统的重点研究档','固定系统比较基座与 LoRA，分项报告解题、批改、引导、学情维护和教师协作的质量、重大错误及校内运行资源。计划通过封存任务评测验证。'],
    '27B':['高资源对照档','27B · 质量收益与资源代价','在相同任务和允许信息下，观察复杂解法、开放诊断及长上下文任务是否值得增加资源。分别记录与 4B、9B 的质量差异和资源消耗。']
  };
  $$('[data-model]').forEach((button) => button.addEventListener('click',() => {
    const note=models[button.dataset.model]; if(!note)return;
    pressed('[data-model]',(item)=>item===button);
    $('#model-focus .focus-kicker').textContent=note[0];
    $('#model-focus-title').textContent=note[1];
    $('#model-focus-copy').textContent=note[2];
  }));

  function selectTask(id) {
    const item = D.tasks.find((task)=>task.id===id); if(!item)return;
    pressed('[data-task]',(button)=>button.dataset.task===id);
    $('#task-code').textContent=id; $('#task-title').textContent=item.title;
    const fields=fieldList([['初始材料',item.initial],['运行时允许信息',item.visible],['目标状态',item.target],['失败条件',item.failure],['成本与评价',item.cost]]);
    $('#task-fields').replaceChildren(...fields.childNodes);
  }
  $$('[data-task]').forEach((button)=>button.addEventListener('click',()=>selectTask(button.dataset.task)));
  selectTask('B');

  let recordings = null;
  let diagnosticCase = D.source.case;
  let frameIndex = 0;
  let condition = 'basic';
  let recordFormat = 'math';
  let comparisonFormat = 'math';
  const recordButtons = $$('[data-frame], [data-condition], [data-diagnostic-case], [data-record-format], [data-comparison-format], #frame-prev, #frame-next');
  recordButtons.forEach((button)=>{button.disabled=true;});
  function renderFrame() {
    const teaching=recordings.teaching;
    const frame=teaching.frames[frameIndex];
    $('#record-input').textContent=frame.input===null?'（开始本次教学，无新增学生输入）':frame.input;
    $('#record-output').textContent=frame.output; // Preserve exactly; no response rewriting or JSON unescaping.
    mathText($('#record-rendered'),frame.output);
    $('#record-rendered').hidden=recordFormat==='raw';
    $('#record-output').hidden=recordFormat!=='raw';
    pressed('[data-record-format]',(button)=>button.dataset.recordFormat===recordFormat);
    pressed('[data-frame]',(button)=>Number(button.dataset.frame)===frameIndex);
    $('#frame-count').textContent=`${String(frameIndex+1).padStart(2,'0')} / ${String(teaching.frames.length).padStart(2,'0')}`;
    $('#frame-prev').disabled=frameIndex===0;
    $('#frame-next').disabled=frameIndex===teaching.frames.length-1;
    const info=frame.structured || {};
    const values=[['实际动作',info.action || '未记录'],['当前教学步骤',`${info.current_step ?? '未记录'} / ${info.total_steps ?? '未记录'}`],['修订版本',info.revision ?? '未记录']];
    const state=fieldList(values,'compact-dl');
    $('#record-state').replaceChildren(...state.childNodes);
    const warning=$('#record-warning');
    warning.hidden=frameIndex!==2;
    warning.textContent=frameIndex===2?'此帧提示在“\\tan”处中断。':'';
    $('#record-meta').textContent=`模型 ${teaching.model} · ${dateText(teaching.recorded_at)}（北京时间） · 本地业务流程录制 · 会话 ${teaching.session.session_id}`;
  }
  function renderComparison() {
    const entry=recordings.cases.find((item)=>item.id===diagnosticCase);
    if (!entry) return;
    const result=entry[condition];
    const labels={basic:'普通模型：题目与作答',same_information:'同信息基线：增加相同可用参考与过程信息',system:'正式业务批改：结构检查后的流程返回'};
    $('#diagnostic-case-title').textContent=entry.title;
    $('#diagnostic-case-challenge').textContent=`教学观察：${entry.observation || '请依据原答判断本案例的诊断难点。'}`;
    $('#diagnostic-case-answer').textContent=entry.student_answer;
    $('#diagnostic-case-expected').textContent=entry.expected;
    pressed('[data-diagnostic-case]',(button)=>button.dataset.diagnosticCase===diagnosticCase);
    pressed('[data-condition]',(button)=>button.dataset.condition===condition);
    $('#comparison-output').textContent=result.content;
    mathText($('#comparison-rendered'),result.content);
    const raw = comparisonFormat==='raw' || condition==='system';
    $('#comparison-rendered').hidden=raw;
    $('#comparison-output').hidden=!raw;
    pressed('[data-comparison-format]',(button)=>button.dataset.comparisonFormat===(raw?'raw':'math'));
    $('[data-comparison-format="math"]').disabled=condition==='system';
    $('#comparison-meta').textContent=`${labels[condition]} · ${result.model} · ${dateText(result.recorded_at)} · 示例输入的模型记录`;
  }
  $$('[data-frame]').forEach((button)=>button.addEventListener('click',()=>{if(recordings){frameIndex=Number(button.dataset.frame);renderFrame();}}));
  $('#frame-prev').addEventListener('click',()=>{if(recordings && frameIndex>0){frameIndex--;renderFrame();}});
  $('#frame-next').addEventListener('click',()=>{if(recordings && frameIndex<recordings.teaching.frames.length-1){frameIndex++;renderFrame();}});
  $$('[data-condition]').forEach((button)=>button.addEventListener('click',()=>{if(recordings){condition=button.dataset.condition;renderComparison();}}));
  $$('[data-diagnostic-case]').forEach((button)=>button.addEventListener('click',()=>{if(recordings){diagnosticCase=button.dataset.diagnosticCase;renderComparison();}}));
  $$('[data-record-format]').forEach((button)=>button.addEventListener('click',()=>{if(recordings){recordFormat=button.dataset.recordFormat;renderFrame();}}));
  $$('[data-comparison-format]').forEach((button)=>button.addEventListener('click',()=>{if(recordings){comparisonFormat=button.dataset.comparisonFormat;renderComparison();}}));
  async function readJSON(path) {
    for (let attempt=0; attempt<2; attempt++) {
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),6000);
      try {
        const response=await fetch(path,{credentials:'omit',signal:controller.signal});
        if(!response.ok)throw new Error(`HTTP ${response.status}`);
        return await response.json();
      } catch(error) {
        if(attempt===1)throw error;
      } finally { clearTimeout(timeout); }
    }
  }
  async function loadRecordings() {
    try {
      const json=await readJSON('/showcase/recordings.json');
      if(!Array.isArray(json.teaching?.frames)||json.teaching.frames.length!==5||!Array.isArray(json.cases)||json.cases.length!==6||!json.cases.find((item)=>item.id===D.source.case))throw new Error('录制结构不可识别');
      if(json.teaching.frames.some((frame)=>typeof frame.output!=='string'||!(frame.input===null||typeof frame.input==='string')))throw new Error('录制字段不可识别');
      recordings=json;
      recordButtons.forEach((button)=>{button.disabled=false;});
      renderFrame();renderComparison();
      $('#record-player').classList.add('records-ready');
      $('#record-live').hidden=false;
      $('#record-load-state').hidden=true;
    } catch {
      $('#record-load-state').textContent='交互记录暂时无法载入。下方保留五帧静态原文，也可打开原始 JSON 与旧站回放。';
      $('#record-meta').textContent='静态原文来自同一份保存录制；输入、输出均未改写。';
    }
    requestReading();
  }
  async function loadPipeline() {
    try {
      const json=await readJSON('/showcase/pipeline.json');
      const run=json.examples[D.source.example][D.source.teacher];
      const models=Object.entries(run.teacher_config).map(([role,config])=>`${role}: ${config.model}`).join(' / ');
      const text=`同题解析记录：${dateText(run.run_at)}；${models}。保存的最终答案：${run.answer_json.final_answer}。与教学五帧记录分别运行。`;
      mathText($('#pipeline-summary'),text);
    } catch {
      $('#pipeline-summary').textContent='Solver → Verifier → Formatter 的保存记录可从原始 JSON 或旧站查看；当前摘要暂时无法载入。';
    }
    requestReading();
  }
  Promise.allSettled([loadRecordings(),loadPipeline(),loadVisionCatalog()]);
})();

// The legacy showcase brings the entire chapter forward with native scrolling.
// Keep its perspective, scroll geometry and damping; the article stays in the DOM.
(() => {
  'use strict';
  const chapters = [...document.querySelectorAll('main > section')];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const header = document.querySelector('.site-header');
  const states = chapters.map((chapter, index) => {
    chapter.classList.add('showcase-chapter');
    const heading = chapter.querySelector('h1,h2');
    const next = chapters[index + 1];
    if (next) {
      const turn = document.createElement('a');
      turn.className = 'chapter-turn';
      turn.href = `#${next.id}`;
      const label = document.createElement('span');
      label.textContent = '接下来';
      const title = document.createElement('strong');
      title.textContent = next.querySelector('h1,h2')?.textContent || '';
      const arrow = document.createElement('span');
      arrow.className = 'chapter-turn-arrow';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '↗';
      turn.append(label, title, arrow);
      chapter.append(turn);
    }
    return {chapter, heading, mode:'idle', progress:0, target:0, lastAt:0};
  });
  let frame = 0;
  let firstLayout = true;
  let lastY = scrollY;
  let navigationUntil = 0;
  const clamp = value => Math.max(0, Math.min(1, value));
  function layoutTop(element) {
    let top = 0;
    for (let node = element; node; node = node.offsetParent) top += node.offsetTop;
    return top;
  }
  function settle(state) {
    state.mode = 'complete';
    state.progress = state.target = 1;
    state.chapter.dataset.arrivalState = 'complete';
    state.chapter.classList.remove('is-arriving');
    for (const name of ['y','depth','tilt','scale']) state.chapter.style.removeProperty(`--chapter-${name}`);
  }
  function paint(state) {
    const rest = 1 - state.progress;
    const mobile = innerWidth <= 820;
    const distance = mobile ? Math.min(145, Math.max(95, innerWidth * .3)) : Math.min(235, Math.max(170, innerHeight * .25));
    state.chapter.style.setProperty('--chapter-y', `${(distance * rest).toFixed(2)}px`);
    state.chapter.style.setProperty('--chapter-depth', `${(-(mobile ? 110 : 185) * rest).toFixed(2)}px`);
    state.chapter.style.setProperty('--chapter-tilt', `${(-(mobile ? 4.2 : 6.5) * rest).toFixed(3)}deg`);
    state.chapter.style.setProperty('--chapter-scale', (1 - .018 * rest).toFixed(5));
  }
  function draw() {
    frame = 0;
    const now = performance.now();
    const delta = scrollY - lastY;
    lastY = scrollY;
    const inset = header?.offsetHeight || 72;
    const start = innerHeight * 1.08;
    const end = Math.max(inset + 70, innerHeight * .54);
    const jumped = Math.abs(delta) > Math.max(480, innerHeight * .9);
    // Read untransformed layout once, then write. Transforms cannot move the target.
    const positions = states.map(state => ({
      state, top:layoutTop(state.heading || state.chapter) - scrollY,
      bottom:layoutTop(state.chapter) + state.chapter.offsetHeight - scrollY
    }));
    let playing = false;
    for (const {state, top, bottom} of positions) {
      if (reduced.matches) { if (state.mode !== 'complete') settle(state); continue; }
      if (state.mode === 'complete' && top > start + 80) state.mode = 'idle';
      if (top > start || bottom <= inset) {
        if (state.mode === 'arriving') settle(state);
        continue;
      }
      if (firstLayout || jumped || now < navigationUntil || top <= end || delta < -8) {
        if (state.mode !== 'complete') settle(state);
        continue;
      }
      if (state.mode === 'idle') {
        state.mode = 'arriving';
        state.progress = 0;
        state.lastAt = now;
        state.chapter.dataset.arrivalState = 'arriving';
        state.chapter.classList.add('is-arriving');
      }
      if (state.mode !== 'arriving') continue;
      state.target = clamp((start - top) / (start - end));
      const speed = Math.abs(delta);
      const tau = speed > 160 ? 55 : speed > 60 ? 110 : 210;
      state.progress += (state.target - state.progress) * (1 - Math.exp(-(now - state.lastAt) / tau));
      state.lastAt = now;
      if (Math.abs(state.target - state.progress) < .001) state.progress = state.target;
      if (state.progress >= .999) settle(state);
      else {
        paint(state);
        playing ||= Math.abs(state.target - state.progress) >= .001;
      }
    }
    firstLayout = false;
    if (playing) schedule(true);
  }
  function schedule(continuing = false) {
    if (frame) return;
    if (continuing !== true) for (const state of states) state.lastAt = performance.now();
    frame = requestAnimationFrame(draw);
  }
  function navigate(target) {
    const state = states.find(item => item.chapter === target?.closest('.showcase-chapter'));
    if (state) settle(state);
    navigationUntil = performance.now() + 1400;
    schedule();
  }
  document.addEventListener('click', event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.('a[href^="#"]');
    if (link) navigate(document.getElementById(link.hash.slice(1)));
  }, true);
  document.addEventListener('focusin', event => navigate(event.target));
  addEventListener('hashchange', () => navigate(document.getElementById(location.hash.slice(1))));
  addEventListener('scroll', schedule, {passive:true});
  addEventListener('resize', schedule, {passive:true});
  addEventListener('pageshow', () => { firstLayout = true; schedule(); });
  reduced.addEventListener('change', schedule);
  if ('ResizeObserver' in window) {
    const resize = new ResizeObserver(() => schedule());
    chapters.forEach(chapter => resize.observe(chapter));
  }
  const handoffs = new IntersectionObserver(entries => {
    entries.forEach(entry => entry.target.classList.toggle('is-in-view', entry.isIntersecting));
  }, {threshold:.4});
  document.querySelectorAll('.chapter-turn').forEach(turn => handoffs.observe(turn));
  // Chapter controls and math fonts change the layout after the browser's first
  // fragment jump. Align a newly opened deep link once that layout is ready.
  const initialHash = location.hash;
  const freshNavigation = performance.getEntriesByType('navigation')[0]?.type === 'navigate';
  let userMoved = false;
  for (const name of ['wheel','touchstart','pointerdown','keydown']) {
    addEventListener(name, () => { userMoved = true; }, {once:true, passive:true});
  }
  const loaded = document.readyState === 'complete' ? Promise.resolve() : new Promise(resolve => addEventListener('load', resolve, {once:true}));
  Promise.all([loaded, document.fonts?.ready]).then(() => {
    if (!initialHash || !freshNavigation || userMoved || location.hash !== initialHash) return;
    const target = document.getElementById(decodeURIComponent(initialHash.slice(1)));
    if (!target) return;
    navigate(target);
    requestAnimationFrame(() => {
      if (!userMoved) target.scrollIntoView({block:'start', behavior:'instant'});
    });
  });
  schedule();
})();
