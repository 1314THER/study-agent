(function () {
  'use strict';
  var exams = [], attempts = [], current = null, activeReport = null, pollTimer = null, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function endpoint(path) { return '/student-analysis' + path; }
  function errorFrom(data, status) { var e = new Error(typeof data.detail === 'string' ? data.detail : data.detail ? JSON.stringify(data.detail) : data.error || ('HTTP ' + status)); e.status = status; return e; }
  async function request(path, options) {
    options = options || {};
    var response = await fetch(endpoint(path), options), data = {};
    try { data = await response.json(); } catch (ignore) {}
    if (!response.ok) throw errorFrom(data, response.status);
    return data;
  }
  function dateText(value) { return String(value || '').slice(0, 10) || '日期未填'; }
  function timeText(value) { if (!value) return ''; try { return new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(Number(value)*1000)); } catch(ignore) { return ''; } }
  function statusText(value) { return ({created:'待补录作答',extracting:'正在识别答卷',extract_partial:'部分页面待重试',awaiting_review:'等待核对作答',grading:'逐题批改中',awaiting_grade_review:'等待复核批改',awaiting_questionnaire:'等待完成考后回顾',complete:'考试已确认',error:'处理失败'})[value] || value || '待处理'; }
  function badge(text, tone) { return '<span class="sa-badge '+(tone||'')+'">'+esc(text)+'</span>'; }
  function htmlMath(node) { if (window.renderMathInElement && node) { try { window.renderMathInElement(node,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false}); } catch(ignore) {} } }
  function showStatus(text, error) { var node=$('intakeStatus'); node.textContent=text; node.classList.toggle('error',!!error); }
  function selectedCompleted() { return attempts.filter(function(a){return a.status==='complete';}).slice().sort(function(a,b){return (a.exam_date||'').localeCompare(b.exam_date||'') || a.created_at-b.created_at;}); }
  async function loadExams() {
    var data=await fetch('/exam/analyses?limit=100');
    var body={}; try { body=await data.json(); } catch(ignore) {}
    if(!data.ok) throw errorFrom(body,data.status);
    exams=(body.analyses||[]).filter(function(a){return a.status==='complete'&&a.review_confirmed;});
    $('examSelect').innerHTML='<option value="">请选择已核对的试卷</option>'+exams.map(function(a){return '<option value="'+esc(a.id)+'">'+esc(a.title)+' · '+esc(dateText(a.created_at?new Date(Number(a.created_at)*1000).toISOString().slice(0,10):''))+'</option>';}).join('');
  }
  async function loadAttempts(keepId) {
    var data=await request('/attempts?limit=100'); attempts=data.attempts||[];
    attempts.sort(function(a,b){return (b.exam_date||'').localeCompare(a.exam_date||'') || b.created_at-a.created_at;});
    renderAttemptList();
    if(keepId&&attempts.some(function(a){return a.id===keepId;})) await openAttempt(keepId,false);
    return attempts;
  }
  function renderAttemptList() {
    var completed=selectedCompleted(), cap=parseInt($('reportLimit').value,10)||5;
    $('attemptCount').textContent=attempts.length+' 次考试 · 可勾选比较范围';
    if(!attempts.length){$('attemptList').innerHTML='<p class="sa-muted" style="padding:12px">还没有考试记录。</p>';return;}
    var selected=new Set(completed.slice(-cap).map(function(a){return a.id;}));
    $('attemptList').innerHTML=attempts.map(function(a){
      var canCompare=a.status==='complete';
      return '<button type="button" class="sa-history-item '+(current&&current.id===a.id?'active':'')+'" data-open-attempt="'+esc(a.id)+'">'+
        '<input type="checkbox" data-compare="'+esc(a.id)+'" aria-label="加入比较范围" '+(canCompare?'':'disabled')+' '+(selected.has(a.id)?'checked':'')+'>'+
        '<span><strong>'+esc(a.title||a.exam_title||'考试记录')+'</strong><small>'+esc(dateText(a.exam_date))+' · '+esc(a.attempt_type==='retake'?'重做/复测':'首次')+'</small></span>'+badge(statusText(a.status),a.status==='complete'?'good':a.status==='extracting'||a.status==='grading'?'warn':'')+'</button>';
    }).join('');
  }
  async function loadReports(openId) {
    var result=await request('/reports?limit=30'), list=result.reports||[];
    $('reportList').innerHTML=list.length?list.map(function(r){return '<button class="sa-history-item" type="button" data-open-report="'+esc(r.id)+'"><span></span><span><strong>'+(r.report_type==='single'?'单卷学情报告':'跨卷学情报告')+'</strong><small>'+esc(timeText(r.created_at))+' · '+esc(r.window_exam_count)+' 次 · '+esc(r.finding_count)+' 条线索</small></span>'+badge(r.stale?'已过期':'可回看',r.stale?'stale':'good')+'</button>';}).join(''):'<p class="sa-muted" style="padding:12px">暂无报告版本。</p>';
    if(openId) await openReport(openId);
  }
  function qLink(id) { return '#sa-question-'+encodeURIComponent(id); }
  function renderSingleSummary(a) {
    var known=a.questions.filter(function(q){return q.earned_score!=null&&q.full_score!=null&&q.paper_quality==='valid';});
    var earned=known.reduce(function(n,q){return n+Number(q.earned_score||0);},0), full=known.reduce(function(n,q){return n+Number(q.full_score||0);},0);
    var confirmed=a.questions.filter(function(q){return q.response.review_status==='confirmed'||q.response.review_status==='blank';}).length;
    return '<div class="sa-report-metrics"><span class="sa-metric">作答已核对 '+confirmed+'/'+a.questions.length+'</span><span class="sa-metric">已确认计分 '+known.length+' 题</span><span class="sa-metric">有效分数 '+(known.length?esc(earned.toFixed(2))+' / '+esc(full.toFixed(2)):'暂不可汇总')+'</span><span class="sa-metric">需复核题 '+a.questions.filter(function(q){return q.grade_review_status==='pending'||q.paper_quality==='pending';}).length+'</span></div>';
  }
  function stepsFor(q) {
    var out=[],used={};
    (q.answer_result&&q.answer_result.chunk_results||[]).forEach(function(chunk){
      var cid=chunk.chunk_id==null?1:chunk.chunk_id;
      (chunk.steps||[]).forEach(function(step,index){
        var base=step.step_number||index+1,id=cid+'-'+base,n=2;
        while(used[id]){id=cid+'-'+base+'-'+n;n++;} used[id]=true;
        out.push({id:id,step_number:base,title:step.title||step.step_level1||'步骤',writing:step.standard_writing||step.detailed_writing||''});
      });
      if(chunk.final_answer) out.push({id:cid+'-999',step_number:999,title:'最终答案',writing:chunk.final_answer});
    });
    return out;
  }
  function renderResult(q) {
    var r=q.grade_result; if(!r) return '';
    var score=r.earned_score==null?'暂定分数未确认':r.earned_score+(r.full_score==null?'':' / '+r.full_score);
    var confidence=r.grading_confidence?(' · 信心 '+r.grading_confidence):'';
    var text=(r.feedback||r.detail||'批改已完成')+'\n分数：'+score+confidence;
    var errors=r.error_suggestions||[];
    return '<div class="sa-grade-result">'+esc(text)+'</div>'+(errors.length?'<ul class="sa-errors">'+errors.map(function(e){return '<li>'+esc(e.step_number?'步骤 '+e.step_number+' · ':'')+esc(e.mistake_type||'待核错因')+'：'+esc(e.answer_evidence||e.mistake_detail||e.detail||'请复核作答证据')+'</li>';}).join('')+'</ul>':'')+
      (q.grade_review_status==='pending'&&q.grade_status==='done'?'<div class="sa-card-actions"><button class="sa-button sa-button-primary" data-confirm-grade="'+esc(q.id)+'" type="button">确认本题批改</button><span class="sa-muted">核对分数、错误位置和参考答案后确认</span></div>':'');
  }
  function errorRowHtml(error,steps) {
    var types=['符号错误','计算错误','公式记错','知识性错误','审题错误','思路错误','其他'];
    return '<div class="sa-error-edit" data-error-row><div class="sa-error-edit-grid"><label>错误类型<select data-error-type><option value="">请选择</option>'+types.map(function(t){return '<option value="'+t+'" '+(error.mistake_type===t?'selected':'')+'>'+t+'</option>';}).join('')+'</select></label><label>对应步骤<select data-error-step><option value="">未定位</option>'+steps.map(function(s){return '<option value="'+esc(s.id)+'" '+(error.step_id===s.id?'selected':'')+'>步 '+esc(s.step_number)+' · '+esc(s.title)+'</option>';}).join('')+'</select></label><button type="button" class="sa-button" data-remove-error aria-label="删除此错误记录">删除</button></div><label>具体观察<input data-error-detail value="'+esc(error.detail||error.mistake_detail||'')+'" placeholder="只写作答中能观察到的问题"></label><label>学生原文依据<textarea data-error-quote>'+esc(error.answer_evidence||'')+'</textarea></label><label class="sa-error-dependent"><input type="checkbox" data-error-dependent '+(error.depends_on_error?'checked':'')+'>这是前面错误导致的后续影响，不单独计数</label></div>';
  }
  function renderErrorEditor(q,steps) {
    var response=q.response||{},manual=response.manual_error_evidence||[],grade=q.grade_result||{},source=manual.length?manual:(grade.error_suggestions||[]);
    if(!source.length)source=[{}];
    return '<details class="sa-rubric sa-error-editor"><summary>错因与错误位置 · 可按原文证据人工修订</summary><p class="sa-muted">步骤缺失不自动归为思路错误。仅当勾选覆盖时，人工记录才替代 AI 错误标签参与跨卷统计。</p><label class="sa-rubric-confirm"><input type="checkbox" data-use-manual-errors '+(manual.length?'checked':'')+'>使用下方人工错误记录（未勾选时保留 AI 批改结果）</label><div data-error-list>'+source.map(function(e){return errorRowHtml(e,steps);}).join('')+'</div><button type="button" class="sa-button" data-add-error>＋ 添加错误记录</button></details>';
  }
  function renderQuestion(q,index,a) {
    var response=q.response||{},steps=stepsFor(q),rubric=q.rubric||[],stored=Object.create(null);
    rubric.forEach(function(row){stored[row.step_id]=row.max_points;});
    var tags=(q.knowledge_core||[]).map(function(x){return '<span class="sa-tag '+(q.labels_reviewed?'':'candidate')+'">'+esc(x)+'</span>';}).join('');
    var sources=(response.source_pages||[]).map(function(p){return '第 '+p+' 页';}).join('、');
    var full=q.full_score==null?'':q.full_score,earned=q.score_source==='manual'&&q.earned_score!=null?q.earned_score:'';
    var basicItem=q.basic_item==null?!!(q.difficulty&&q.difficulty.level==='容易'):q.basic_item===true;
    var objectiveRule=q.objective_rule||{mode:'all_or_nothing',wrong_option_penalty:0};
    return '<article id="sa-question-'+esc(q.id)+'" class="sa-card" data-question="'+esc(q.id)+'">'+
      '<div class="sa-card-head"><span class="sa-q-no">Q'+esc(q.question_no==null?index+1:q.question_no)+'</span><strong>'+esc(q.question_type||'题目')+' · '+esc(q.difficulty&&q.difficulty.level||'难度未确认')+'</strong><div class="sa-tags">'+tags+'</div></div>'+
      '<div class="sa-question-text">'+esc(q.question||'（题面为空）')+'</div>'+
      '<div class="sa-answer-meta"><span>识别来源：'+esc(response.source||'手动录入')+'</span><span>识别清晰度：'+esc(response.ocr_confidence||'未评估')+'</span><span>'+esc(sources||'未关联扫描页')+'</span><span>核对：'+esc(({pending:'待核对',confirmed:'已确认作答',blank:'已确认空白',unrecognized:'识别不清'})[response.review_status]||response.review_status||'待核对')+'</span></div>'+
      '<label for="sa-answer-'+esc(q.id)+'">学生作答原文（保留错写内容，可跨页合并或手动补录）</label><textarea id="sa-answer-'+esc(q.id)+'" data-answer>'+esc(response.student_answer||'')+'</textarea>'+
      '<div class="sa-card-grid"><label>作答核对状态<select data-review><option value="confirmed" '+(response.review_status==='confirmed'?'selected':'')+'>确认有作答</option><option value="blank" '+(response.review_status==='blank'?'selected':'')+'>确认空白</option><option value="unrecognized" '+(response.review_status==='unrecognized'?'selected':'')+'>识别不清，待补录</option></select></label><label>题目满分<input data-full-score type="number" min="0" max="1000" step="0.5" value="'+esc(full)+'" placeholder="未知可留空"></label><label>人工确认实得分<input data-earned-score type="number" min="0" max="1000" step="0.5" value="'+esc(earned)+'" placeholder="不手动改分可留空"></label><label>试题质量<select data-paper-quality><option value="valid" '+(q.paper_quality==='valid'?'selected':'')+'>题目有效</option><option value="pending" '+(q.paper_quality==='pending'?'selected':'')+'>待复核</option><option value="problem" '+(q.paper_quality==='problem'?'selected':'')+'>题目/答案有问题</option></select></label><label style="grid-column:span 2">题目复核说明<input data-paper-note value="'+esc(q.paper_note||'')+'" placeholder="例如：原题条件缺失、答案版本不一致"></label><label class="sa-basic-toggle"><input type="checkbox" data-basic-item '+(basicItem?'checked':'')+'>纳入基础题对照（可调整）</label>'+((q.question_type||'').indexOf('多选')>=0?'<label>多选计分方式<select data-objective-mode><option value="all_or_nothing" '+(objectiveRule.mode==='all_or_nothing'?'selected':'')+'>全对得分</option><option value="per_option" '+(objectiveRule.mode==='per_option'?'selected':'')+'>按正确选项给分</option></select></label><label>每个错选扣分<input data-objective-penalty type="number" min="0" max="1000" step="0.5" value="'+esc(objectiveRule.wrong_option_penalty||0)+'"></label>':'')+'</div>'+
      (steps.length?'<details class="sa-rubric"><summary>评分标准 · 设置并确认步骤分</summary><p class="sa-muted">评分点总和必须等于满分；不设置时 AI 给出的分数仅作为待核草稿。</p>'+steps.map(function(step){return '<label class="sa-rubric-row"><span>'+esc(step.title)+' · '+esc(step.writing.slice(0,90))+'</span><input type="number" data-rubric-step="'+esc(step.id)+'" min="0" max="1000" step="0.5" value="'+(stored[step.id]==null?'':esc(stored[step.id]))+'" placeholder="分值"></label>';}).join('')+'<label class="sa-rubric-confirm"><input type="checkbox" data-rubric-confirm '+(q.rubric_confirmed?'checked':'')+'>我已核对并确认以上评分点</label></details>':'<p class="sa-muted" style="margin-top:8px">无可用分步参考解答；本题将按总分或答案比对进行暂定批改。</p>')+renderErrorEditor(q,steps)+
      '<div class="sa-card-actions"><button class="sa-button sa-button-primary" data-save-question="'+esc(q.id)+'" type="button">保存并确认作答</button><span class="sa-muted">修改作答或评分后，旧批改和报告会保留为历史依据并标记过期。</span></div>'+renderResult(q)+
      (a.status==='complete'?'<div class="sa-practice-link"><label>关联新题复测记录编号 <input type="number" min="1" data-practice-id placeholder="练习记录 ID"><button class="sa-button" data-followup="'+esc(q.id)+'" type="button">关联复测</button></label><small class="sa-muted">原题重做不计作独立复测；练习记录可在个人题库中查看编号。</small></div>':'')+'</article>';
  }
  function renderQuestionnaire(a) {
    var q=a.questionnaire||{};
    function select(id,label,options){return '<label>'+label+'<select data-survey="'+id+'">'+options.map(function(x){return '<option value="'+x[0]+'" '+((q[id]||'unknown')===x[0]?'selected':'')+'>'+x[1]+'</option>';}).join('')+'</select></label>';}
    var options={unknown:'不记得/不确定',yes:'是',no:'否'};
    return '<section class="sa-questionnaire"><h3>考后回顾 · 时间来自学生自述</h3><div class="sa-questionnaire-grid">'+
      select('completion','完成情况',[['unknown','不确定'],['completed','完成全卷'],['not_completed','未完成']])+select('stuck_period','主要卡题时段',[['unknown','不确定'],['none','没有明显卡题'],['early','前段'],['middle','中段'],['late','后段']])+select('stuck_duration_range','卡题大致耗时区间',[['unknown','不确定'],['none','没有明显卡题'],['under_5m','少于 5 分钟'],['5_15m','5–15 分钟'],['15_30m','15–30 分钟'],['over_30m','超过 30 分钟']])+select('skipped_and_returned','是否跳题后回做',Object.keys(options).map(function(k){return [k,options[k]];}))+select('checked_work','是否留时间检查',Object.keys(options).map(function(k){return [k,options[k]];}))+select('confidence','答题把握',[['unknown','不确定'],['mostly_sure','大多有把握'],['mixed','把握不一'],['mostly_unsure','大多没把握']])+select('condition','明显状态变化',[['unknown','不确定'],['calm','平稳'],['tense','紧张'],['tired','疲劳'],['distracted','走神'],['other','其他']])+
      '<label>卡住的题号（逗号分隔）<input data-survey-numbers value="'+esc((q.stuck_question_numbers||[]).join(', '))+'" placeholder="例：8, 12"></label><label style="grid-column:span 2">补充自述<textarea data-survey-note>'+esc(q.note||'')+'</textarea></label></div><div class="sa-card-actions"><button class="sa-button" data-save-survey type="button">保存考后回顾</button><span class="sa-muted">状态描述仅作为情境记录，不单独解释失分。</span></div></section>';
  }
  function pageHtml(page,a) {
    var unmatched=(page.unmatched_fragments||[]).map(function(f){return '<div class="sa-unmatched"><span>'+esc(f.text||'（明确空白片段）')+' · '+esc(f.confidence||'')+'</span><select data-map-question><option value="">关联题号…</option>'+a.questions.map(function(q){return '<option value="'+esc(q.id)+'">第 '+esc(q.question_no)+' 题</option>';}).join('')+'</select><button type="button" class="sa-button" data-map-fragment="'+esc(f.id)+'" data-page="'+esc(page.page_no)+'">关联</button></div>';}).join('');
    return '<section class="sa-page"><div class="sa-page-head"><strong>答卷第 '+esc(page.page_no)+' 页</strong>'+badge(page.status==='done'?'已识别':page.status==='error'?'识别失败':'待识别',page.status==='done'?'good':'warn')+'</div><img loading="lazy" src="'+endpoint('/attempts/'+encodeURIComponent(a.id)+'/pages/'+page.page_no+'/image')+'" alt="答卷扫描第 '+esc(page.page_no)+' 页"><div class="sa-page-fragments">'+(unmatched||'')+'</div>'+(page.error?'<p class="sa-error">'+esc(page.error)+'</p>':'')+'</section>';
  }
  function renderAttempt(a) {
    current=a;
    var task=a.status==='extracting'||a.status==='grading', done=a.pages.filter(function(p){return p.status==='done';}).length;
    var responsesReviewed=a.questions.every(function(q){return ['confirmed','blank'].indexOf((q.response||{}).review_status)>=0;});
    var gradingPending=a.questions.some(function(q){return q.grade_status==='pending'||q.grade_status==='error';});
    var actions='';
    if(task) actions+='<button class="sa-button" data-cancel-attempt type="button">停止任务</button>';
    if(a.status==='extract_partial') actions+='<button class="sa-button" data-retry-attempt type="button">重试失败页面</button>';
    if(a.status==='complete') actions+='<button class="sa-button" data-single-report type="button">生成本次单卷报告</button>';
    if(responsesReviewed&&gradingPending&&['created','awaiting_review','extract_partial','awaiting_grade_review'].indexOf(a.status)>=0) actions+='<button class="sa-button sa-button-primary" data-start-grade type="button">开始批改</button>';
    var pageMarkup=(a.pages||[]).map(function(p){return pageHtml(p,a);}).join('');
    var questions=(a.questions||[]).map(function(q,i){return renderQuestion(q,i,a);}).join('');
    $('attemptPanel').innerHTML='<header class="sa-attempt-head"><div><div class="sa-kicker">'+esc(a.exam_title||'试卷')+' · '+esc(a.exam_date)+'</div><h2>'+esc(a.title||a.exam_title)+'</h2><p>'+esc(statusText(a.status))+' · '+(a.attempt_type==='retake'?'重做/复测':'首次独立作答')+(a.viewed_answer?' · 看过答案':'')+' · '+esc(a.questions.length)+' 道题</p></div><div class="sa-attempt-actions">'+actions+'</div></header><div class="sa-attempt-content">'+
      (task?'<div class="sa-progress"><span>'+esc(a.status==='extracting'?'正在逐页识别':('已处理 '+done+'/'+a.pages.length+' 页'))+'</span><progress max="'+Math.max(a.pages.length,1)+'" value="'+done+'"></progress><span>核对后才能批改</span></div>':'')+
      (a.error?'<div class="sa-notice">'+esc(a.error)+'</div>':'')+renderSingleSummary(a)+pageMarkup+questions+renderQuestionnaire(a)+'</div>';
    renderAttemptList(); htmlMath($('attemptPanel'));
  }
  async function openAttempt(id, refresh) {
    if(refresh===false&&current&&current.id===id) return;
    current=await request('/attempts/'+encodeURIComponent(id)); renderAttempt(current); clearTimeout(pollTimer);
    if(current.status==='extracting'||current.status==='grading') pollTimer=setTimeout(function(){openAttempt(id,true).catch(function(e){showStatus(e.message,true);});},1800);
  }
  async function refreshAll(keepId) { await loadAttempts(keepId||current&&current.id); await loadReports(); }
  async function createAttempt() {
    if(busy)return; busy=true; $('createAttempt').disabled=true;
    try {
      var analysisId=$('examSelect').value;
      if(!analysisId)throw new Error('请先选择一份已完成核对的试卷。');
      var payload={exam_analysis_id:analysisId,exam_date:$('examDate').value||new Date().toISOString().slice(0,10),
        attempt_type:$('attemptType').value,viewed_answer:$('viewedAnswer').checked,title:$('attemptTitle').value.trim()||undefined,
        time_limit_minutes:$('timeLimit').value?Number($('timeLimit').value):null};
      var attempt=await request('/attempts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var files=$('answerFiles').files;
      if(files&&files.length){showStatus('正在上传并按页准备答卷…');var form=new FormData();Array.from(files).forEach(function(file){form.append('files',file,file.name);});var answer=await request('/attempts/'+encodeURIComponent(attempt.id)+'/answers',{method:'POST',body:form});attempt=answer.attempt||attempt;}
      $('answerFiles').value='';$('selectedFiles').textContent='尚未选择答卷文件，可在记录中逐题补录。';$('attemptTitle').value='';
      await loadAttempts(attempt.id); showStatus('考试记录已建立。识别结果为草稿，需逐题核对后再批改。');
    } catch(e) { showStatus(e.message,true); } finally {busy=false;$('createAttempt').disabled=false;}
  }
  function collectRubric(card, fullScore) {
    var checked=card.querySelector('[data-rubric-confirm]');
    if(!checked||!checked.checked)return {rubric:[],confirmed:false};
    var rows=Array.from(card.querySelectorAll('[data-rubric-step]')).map(function(input){return {step_id:input.dataset.rubricStep,max_points:input.value===''?NaN:Number(input.value)};});
    if(rows.some(function(r){return !Number.isFinite(r.max_points)||r.max_points<0;}))throw new Error('请为每个评分点填写有效分值；无分值步骤可填 0。');
    var total=rows.reduce(function(s,r){return s+r.max_points;},0);
    if(fullScore==null||Math.abs(total-fullScore)>.01)throw new Error('评分点合计须等于题目满分。');
    return {rubric:rows,confirmed:true};
  }
  async function saveQuestion(button) {
    var card=button.closest('[data-question]'),id=button.dataset.saveQuestion,answer=card.querySelector('[data-answer]').value,
      status=card.querySelector('[data-review]').value,fullValue=card.querySelector('[data-full-score]').value,
      earnedValue=card.querySelector('[data-earned-score]').value,full=fullValue===''?null:Number(fullValue),rubric=collectRubric(card,full);
    if(status==='confirmed'&&!answer.trim())throw new Error('作答为空时请选择“确认空白”。');
    if(status==='blank'&&answer.trim())throw new Error('已有作答内容，请清空后再确认为空白。');
    var payload={student_answer:answer,review_status:status,full_score:full,rubric:rubric.rubric,rubric_confirmed:rubric.confirmed,
      paper_quality:card.querySelector('[data-paper-quality]').value,paper_note:card.querySelector('[data-paper-note]').value,
      basic_item:card.querySelector('[data-basic-item]').checked};
    var objectiveMode=card.querySelector('[data-objective-mode]');
    if(objectiveMode)payload.objective_rule={mode:objectiveMode.value,wrong_option_penalty:Number(card.querySelector('[data-objective-penalty]').value||0)};
    var manualErrors=card.querySelector('[data-use-manual-errors]');
    if(manualErrors&&manualErrors.checked){
      payload.manual_error_evidence=Array.from(card.querySelectorAll('[data-error-row]')).map(function(row){return {
        mistake_type:row.querySelector('[data-error-type]').value,
        step_id:row.querySelector('[data-error-step]').value||null,
        detail:row.querySelector('[data-error-detail]').value,
        answer_evidence:row.querySelector('[data-error-quote]').value,
        depends_on_error:row.querySelector('[data-error-dependent]').checked};
      }).filter(function(row){return row.mistake_type;});
      if(payload.manual_error_evidence.some(function(row){return !row.answer_evidence&&!row.detail;}))throw new Error('人工错因需填写原文依据或具体观察。');
    }
    if(earnedValue!=='')payload.earned_score=Number(earnedValue);
    button.disabled=true;
    try { await request('/attempts/'+encodeURIComponent(current.id)+'/questions/'+encodeURIComponent(id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); await openAttempt(current.id,true); }
    finally {button.disabled=false;}
  }
  async function saveSurvey(button) {
    var panel=button.closest('.sa-questionnaire'),numbers=panel.querySelector('[data-survey-numbers]').value.split(/[,，\s]+/).map(function(x){return x.trim();}).filter(Boolean);
    var parsed=numbers.map(Number); if(parsed.some(function(x){return !Number.isInteger(x)||x<1;}))throw new Error('卡题题号请用正整数，以逗号分开。');
    var body={};panel.querySelectorAll('[data-survey]').forEach(function(input){body[input.dataset.survey]=input.value;});
    body.stuck_question_numbers=parsed;body.note=panel.querySelector('[data-survey-note]').value;
    button.disabled=true;try {await request('/attempts/'+encodeURIComponent(current.id)+'/questionnaire',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});await openAttempt(current.id,true);showStatus('考后回顾已保存。');}finally{button.disabled=false;}
  }
  async function createReport() {
    var selected=Array.from(document.querySelectorAll('[data-compare]:checked')).map(function(x){return x.dataset.compare;});
    var payload=selected.length?{attempt_ids:selected}:{limit:Number($('reportLimit').value)||5};
    if(!selected.length&&!selectedCompleted().length)throw new Error('至少需要一份已确认的考试记录。');
    $('createReport').disabled=true;
    try {activeReport=await request('/reports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});renderReport(activeReport);await loadReports();}
    finally {$('createReport').disabled=false;}
  }
  function evidenceLabel(e) { return [e.exam_date||'',e.attempt_title||e.attempt_title||'',e.question_no!=null?'第 '+e.question_no+' 题':'',e.mistake_type||'',e.answer_evidence||e.student_answer||e.detail||''].filter(Boolean).join(' · '); }
  function renderReport(snapshot) {
    var data=snapshot.data||{}, findings=data.findings||[], priorities=data.priority_recommendations||[], timeline=data.timeline||[];
    var recommendations=priorities.length?'<section class="sa-recommendations"><h3>优先建议 · 最多三项</h3>'+priorities.map(function(r,i){return '<div class="sa-rec-row"><span class="sa-rec-rank">0'+(i+1)+'</span><div><strong>'+esc(r.title)+'</strong><p>'+esc(r.recommendation)+'</p><p>复测目标：'+esc(r.validation_target)+'</p><span class="sa-badge '+(r.evidence_level==='repeated'||r.evidence_level==='followup'?'good':'warn')+'">'+esc(({initial:'初步线索',repeated:'重复出现',followup:'补测支持'})[r.evidence_level]||r.evidence_level)+'</span><div class="sa-rec-actions"><button type="button" data-open-finding="'+esc(r.finding_id)+'">查看支持证据</button><a href="/grade.html">单题批改</a><a href="/mother.html">母题看板</a></div></div></div>';}).join('')+'</section>':'<section class="sa-recommendations"><h3>优先建议</h3><div class="sa-rec-row"><div><p>目前证据不足以形成优先训练建议。补充并确认更多考试作答后再比较。</p></div></div></section>';
    var findingHtml=findings.length?findings.map(function(f){
      var level=({initial:'初步线索',repeated:'重复出现',followup:'补测支持'})[f.evidence_level]||f.evidence_level;
      function evidence(rows){return (rows||[]).map(function(e){var label=evidenceLabel(e);return '<div class="sa-evidence">'+esc(label||'已记录证据')+(e.attempt_id&&e.question_id?'<button type="button" data-evidence-attempt="'+esc(e.attempt_id)+'" data-evidence-question="'+esc(e.question_id)+'">回到作答</button>':'')+'</div>';}).join('')||'<div class="sa-evidence">暂无可展开的反向证据</div>';}
      var causes=(f.possible_causes||[]).map(function(c){return Array.isArray(c)?c[0]+'（'+c[1]+' 次）':c;}).join('、');
      return '<article class="sa-finding" data-finding-id="'+esc(f.id)+'"><div class="sa-finding-head"><h4>'+esc(f.title)+'</h4>'+badge(level,f.evidence_level==='repeated'||f.evidence_level==='followup'?'good':'warn')+'</div><p>'+esc(f.observation)+'</p><p><strong>可能原因（待验证）：</strong>'+esc(causes||'无明确原因归因')+'</p><p><strong>训练建议：</strong>'+esc(f.recommendation||'')+'</p><p><strong>复测目标：</strong>'+esc(f.validation_target||'')+'</p><details><summary>支持证据（'+(f.supporting_evidence||[]).length+'）</summary>'+evidence(f.supporting_evidence)+'</details><details><summary>相反证据（'+(f.counter_evidence||[]).length+'）</summary>'+evidence(f.counter_evidence)+'</details></article>';
    }).join(''):'<p class="sa-muted" style="padding:12px">当前记录没有形成足够明确的能力结论。未知分数不补零，未确认标签不会作为确定结论。</p>';
    var timelineHtml=timeline.map(function(t){return '<tr><td>'+esc(t.exam_date)+'</td><td>'+esc(t.title)+'</td><td>'+esc(t.attempt_type==='retake'?'复测':'首次')+'</td><td>'+(t.score==null?'—':esc(t.score)+' / '+esc(t.full_score))+'</td><td>'+esc(t.scored_questions)+' 题</td><td>'+esc(t.confirmed_blank_questions)+' 题</td><td>'+(t.time_limit_minutes?esc(t.time_limit_minutes)+' 分':'—')+'</td></tr>';}).join('');
    $('reportPanel').innerHTML=(snapshot.stale?'<div class="sa-stale-note">此版本的输入数据已修订，仍可回看。请重新生成报告以使用最新证据。</div>':'')+
      '<div class="sa-report-metrics"><span class="sa-metric">比较考试 '+esc(data.window_exam_count||0)+' 次</span><span class="sa-metric">独立题目 '+esc(data.independent_question_count||0)+' 道</span><span class="sa-metric">重做/看过答案 '+esc(data.practice_attempt_question_count||0)+' 道（单独展示）</span><span class="sa-metric">规则版本 '+esc(data.rules_version||'1')+'</span></div>'+recommendations+
      '<div class="sa-report-columns"><section class="sa-findings"><h3>发现与证据</h3>'+findingHtml+'</section><section class="sa-timeline"><h3>考试表现与问卷时间线</h3><table><thead><tr><th>日期</th><th>试卷</th><th>类型</th><th>确认分数</th><th>计分题</th><th>确认空白</th><th>限时</th></tr></thead><tbody>'+timelineHtml+'</tbody></table><p class="sa-muted" style="padding:8px">'+esc(data.score_note||'分数统计只包括已确认有效且分数已知的题目。')+'</p>'+(data.time_evidence&&data.time_evidence.length?'<details style="padding:8px"><summary>查看自述时间证据</summary><pre style="white-space:pre-wrap;font-size:9px">'+esc(JSON.stringify(data.time_evidence,null,2))+'</pre></details>':'')+(data.paper_issues&&data.paper_issues.length?'<details style="padding:8px"><summary>试题待复核（'+data.paper_issues.length+'）</summary>'+data.paper_issues.map(function(x){return '<p class="sa-muted">'+esc(x.exam_date)+' · 第 '+esc(x.question_no)+' 题：'+esc(x.note)+'</p>';}).join('')+'</details>':'')+'</section></div>';
    htmlMath($('reportPanel'));
  }
  async function openReport(id) { activeReport=await request('/reports/'+encodeURIComponent(id));renderReport(activeReport); }
  async function doAction(button, action) {
    if(action==='start-grade') {var result=await request('/attempts/'+encodeURIComponent(current.id)+'/grade',{method:'POST'});await openAttempt(current.id,true);showStatus('已开始批改；完成后需要复核低置信度结果。');return result;}
    if(action==='retry-attempt') {await request('/attempts/'+encodeURIComponent(current.id)+'/retry',{method:'POST'});await openAttempt(current.id,true);return;}
    if(action==='cancel-attempt') {await request('/attempts/'+encodeURIComponent(current.id)+'/cancel',{method:'POST'});await openAttempt(current.id,true);return;}
    if(action==='save-survey') return saveSurvey(button);
  }
  document.addEventListener('click',function(event){
    var open=event.target.closest('[data-open-attempt]');if(open&&!event.target.closest('[data-compare]')){openAttempt(open.dataset.openAttempt,true).catch(function(e){showStatus(e.message,true);});return;}
    var reportButton=event.target.closest('[data-open-report]');if(reportButton){openReport(reportButton.dataset.openReport).catch(function(e){showStatus(e.message,true);});return;}
    var openFinding=event.target.closest('[data-open-finding]');if(openFinding){var targetFinding=Array.from(document.querySelectorAll('[data-finding-id]')).find(function(x){return x.dataset.findingId===openFinding.dataset.openFinding;});if(targetFinding){var evidenceDetails=targetFinding.querySelector('details');if(evidenceDetails)evidenceDetails.open=true;targetFinding.scrollIntoView({behavior:'smooth',block:'center'});}return;}
    var single=event.target.closest('[data-single-report]');if(single){request('/attempts/'+encodeURIComponent(current.id)+'/report',{method:'POST'}).then(function(report){activeReport=report;renderReport(report);return loadReports();}).then(function(){$('reportPanel').scrollIntoView({behavior:'smooth',block:'start'});}).catch(function(e){showStatus(e.message,true);});return;}
    var save=event.target.closest('[data-save-question]');if(save){saveQuestion(save).catch(function(e){showStatus(e.message,true);});return;}
    var addError=event.target.closest('[data-add-error]');if(addError){var errorCard=addError.closest('[data-question]'),errorList=errorCard.querySelector('[data-error-list]');errorList.insertAdjacentHTML('beforeend',errorRowHtml({},stepsFor(current.questions.find(function(q){return q.id===errorCard.dataset.question;}))));return;}
    var removeError=event.target.closest('[data-remove-error]');if(removeError){removeError.closest('[data-error-row]').remove();return;}
    var confirm=event.target.closest('[data-confirm-grade]');if(confirm){request('/attempts/'+encodeURIComponent(current.id)+'/questions/'+encodeURIComponent(confirm.dataset.confirmGrade),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({grade_review_status:'confirmed'})}).then(function(){return openAttempt(current.id,true);}).catch(function(e){showStatus(e.message,true);});return;}
    var survey=event.target.closest('[data-save-survey]');if(survey){saveSurvey(survey).catch(function(e){showStatus(e.message,true);});return;}
    var action=event.target.closest('[data-start-grade],[data-retry-attempt],[data-cancel-attempt]');if(action){var name=action.hasAttribute('data-start-grade')?'start-grade':action.hasAttribute('data-retry-attempt')?'retry-attempt':'cancel-attempt';doAction(action,name).catch(function(e){showStatus(e.message,true);});return;}
    var map=event.target.closest('[data-map-fragment]');if(map){var row=map.closest('.sa-unmatched'),qid=row.querySelector('[data-map-question]').value;if(!qid){showStatus('请先选择需要关联的题目。',true);return;}request('/attempts/'+encodeURIComponent(current.id)+'/unmatched',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({mappings:[{page_no:Number(map.dataset.page),fragment_id:map.dataset.mapFragment,question_id:qid}]})}).then(function(){return openAttempt(current.id,true);}).catch(function(e){showStatus(e.message,true);});return;}
    var followup=event.target.closest('[data-followup]');if(followup){var id=followup.dataset.followup,card=followup.closest('[data-question]'),input=card.querySelector('[data-practice-id]');if(!input.value){showStatus('请填写单题练习记录编号。',true);return;}var findingId=activeReport&&(activeReport.data.findings||[]).find(function(f){return (f.supporting_evidence||[]).some(function(e){return e.attempt_id===current.id&&e.question_id===id;});});request('/attempts/'+encodeURIComponent(current.id)+'/questions/'+encodeURIComponent(id)+'/followup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({practice_record_id:Number(input.value),finding_id:findingId&&findingId.id||null})}).then(function(){return loadAttempts(current.id);}).then(function(){showStatus('复测记录已关联。');}).catch(function(e){showStatus(e.message,true);});return;}
    var evidence=event.target.closest('[data-evidence-attempt]');if(evidence){openAttempt(evidence.dataset.evidenceAttempt,true).then(function(){var target=document.getElementById('sa-question-'+CSS.escape(evidence.dataset.evidenceQuestion));if(target)target.scrollIntoView({behavior:'smooth',block:'center'});}).catch(function(e){showStatus(e.message,true);});return;}
    if(event.target.closest('#createReport'))createReport().catch(function(e){showStatus(e.message,true);});
  });
  document.addEventListener('change',function(event){
    if(event.target.matches('[data-compare]')){event.stopPropagation();return;}
    if(event.target.id==='reportLimit')renderAttemptList();
    if(event.target.id==='answerFiles'){var files=Array.from(event.target.files||[]);$('selectedFiles').textContent=files.length?files.map(function(f,i){return (i+1)+'. '+f.name+' ('+Math.ceil(f.size/1024)+' KB)';}).join(' · '):'尚未选择答卷文件，可创建记录后手动录入。';}
  });
  $('createAttempt').addEventListener('click',createAttempt);
  async function init() {
    $('examDate').value=new Date().toISOString().slice(0,10);
    try {await Promise.all([loadExams(),loadAttempts(),loadReports()]);} catch(e) {showStatus(e.message,true);}
  }
  document.addEventListener('DOMContentLoaded',init);
})();
