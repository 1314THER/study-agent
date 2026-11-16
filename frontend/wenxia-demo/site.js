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
    if (progress) progress.style.width = `${full > 0 ? Math.min(100, Math.max(0, window.scrollY/full*100)) : 0}%`;
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
    if (visionMeta) visionMeta.textContent = `显示 ${visible} / 63 条 · 按对象与教学过程筛选；条目原状态沿用 2026-10-26 快照。映射入口指向新版说明，不表示该功能已完成。`;
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
      if (visionMeta) visionMeta.textContent = '旧站愿景数据暂时无法载入；可以从旧站档案核对全部 63 项。';
    }
  }

  const longitudinalData = {
    error:['T0 · 初次作答','当前判断：本题联立求角步骤出现错误','依据：原答片段“C=π/3”。这是一次观察，错误原因未知。','是否会在无提示条件下识别关系；是否能迁移到新题；延迟保持。','必要时用短问题检查概念理解，再安排无提示新题。','DB2 追加本次原答；DB3 只提出有边界的暂定判断。'],
    hint:['T1 · 提示后订正','当前判断：本题在帮助条件下订正正确','依据：学生看过涉及求 C 与两角展开的提示后，完成了同题推导。','能否独立选择方法、迁移至未见题、间隔后保持。','记录帮助等级；选择一道不暴露方法标签的新题。','DB2 新增 HelpExposure 与辅助订正；DB3 不升级为独立掌握。'],
    independent:['T2 · 无提示新题（方案示例）','当前判断：在一个新题上独立完成目标步骤','依据：假设新题未暴露过且无提示，操作正确并引用原答。','是否能迁移至更复杂题族；是否能延迟保持；单题偶然性。','安排不同题族的延迟复测，而不是重复原题。','DB2 新增独立作答事实；DB3 只把判断范围扩到该目标的一次迁移表现。'],
    delayed:['T3 · 延迟复测（方案示例）','当前判断：该目标在一次间隔复测中再次完成','依据：假设延迟新题正确；时间间隔、题族与帮助条件都要入记录。','不能据两次表现推断整章掌握；其他方法和条件仍未观察。','保留低负担的后续抽查；依据课程节奏安排，不持续加题。','DB2 追加延迟事件；DB3 可增强该目标的证据并记录适用范围。'],
    teacher:['T4 · 教师反证（方案示例）','当前判断：撤回由误读原答支持的旧结论','依据：假设教师复核发现学生使用了另一条有效路径，并提供对应原答位置。','该纠正不证明后续所有任务均正确；教师反证也需限于所指对象。','撤回相关补救任务，改为一项无提示迁移检查。','DB2 追加教师评分修订；DB3 保留旧版本、撤回无支持主张，重算个人任务和班级汇总。']
  };
  function renderLongitudinal(id) {
    const row = longitudinalData[id]; if (!row) return;
    pressed('[data-longitudinal]',(button) => button.dataset.longitudinal === id);
    ['#longitudinal-time','#longitudinal-claim','#longitudinal-evidence-line','#longitudinal-unknown','#longitudinal-next','#longitudinal-write'].forEach((selector,index) => { if ($(selector)) $(selector).textContent = row[index]; });
  }
  $$('[data-longitudinal]').forEach((button) => button.addEventListener('click',() => renderLongitudinal(button.dataset.longitudinal)));

  const classDemo = {
    before:['4 / 9','有效作答中被归为“联立求角”错误','原答：由另一条有效边角路径求出三角形高。系统初判为关键步骤缺失。','暂记：本题路径需要教师核对；新题迁移未知。','待教师确认；不得在疑点未清时追加重复补练。','教师复核前，班级报告按 9 份有效答卷计算。'],
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
    '9B':['重点适配档','9B · 完整系统的重点研究档','固定系统比较基座与 LoRA，分项报告解题、批改、引导、学情维护和教师协作的质量、重大错误及校内运行资源。当前尚无这套新架构的封存任务成绩。'],
    '27B':['高资源对照档','27B · 质量收益与资源代价','在相同任务和允许信息下，观察复杂解法、开放诊断及长上下文任务是否值得增加资源。与 4B、9B 分别计量，其他档位不作为隐藏兜底。']
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
    warning.textContent=frameIndex===2?'这一帧的提示在保存记录中不完整，原文保持不变。新方案需要在交付前检查内容完整性，不能把本帧视为合格提示。':'';
    $('#record-meta').textContent=`模型 ${teaching.model} · ${dateText(teaching.recorded_at)}（北京时间） · local_production_code / 真实模型 API · 会话 ${teaching.session.session_id}`;
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
    $('#comparison-meta').textContent=`${labels[condition]} · ${result.model} · ${dateText(result.recorded_at)} · 构造输入的单例实录；完整输出按录制原文展示，不作为胜负统计。`;
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
