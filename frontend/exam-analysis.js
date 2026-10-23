(function () {
  'use strict';
  var meta = null, templates = [], current = null, selectedFiles = [], pollTimer = null, busy = false;
  var el = function (id) { return document.getElementById(id); };
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function apiError(data, status) {
    var detail = data && data.detail;
    var error = new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : (data && data.error) || ('HTTP ' + status));
    error.status = status; error.detail = detail; return error;
  }
  async function request(path, options) {
    options = options || {};
    var response = await fetch(path, options), data = {};
    try { data = await response.json(); } catch (ignore) {}
    if (!response.ok) throw apiError(data, response.status);
    return data;
  }
  function selectedTemplate() { return templates.find(function (item) { return item.id === el('templateSelect').value; }) || templates[0]; }
  function showMessage(text, error) {
    el('uploadHint').textContent = text;
    el('uploadHint').classList.toggle('ea-error', !!error);
  }
  function formatDate(value) {
    try { return new Intl.DateTimeFormat('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(Number(value) * 1000)); }
    catch (ignore) { return ''; }
  }
  function fmt(value, digits) { return value == null ? '—' : Number(value).toFixed(digits == null ? 0 : digits); }
  function statusText(status) {
    return ({extracting:'正在识别题目',awaiting_review:'等待核对',solving:'逐题解答中',complete:'分析完成',partial:'部分完成',
      extract_error:'识别失败',extract_interrupted:'识别任务中断',cancelled:'已停止',interrupted:'服务重启后待恢复',error:'任务失败'})[status] || status || '处理中';
  }
  function sortQuestions(questions) {
    return (questions || []).slice().sort(function (a,b) {
      if (a.question_no == null) return 1; if (b.question_no == null) return -1; return a.question_no - b.question_no;
    });
  }
  function sourcePageLabel(q) {
    var details=q.source_page_details||[];
    if(details.length) return details.map(function(page){return 'P'+page.page_no+(page.filename?' · '+page.filename:'')+
      (page.file_page&&page.file_page!==1?' 第'+page.file_page+'页':'');}).join(' / ');
    return (q.source_pages||[]).map(function(p){return 'P'+p;}).join('、')||'待核';
  }
  function sourceImagesHtml(q) {
    var refs=[];
    (q.source_page_details||[]).forEach(function(page){(page.asset_refs||[]).forEach(function(ref){if(!refs.some(function(x){return x.ref===ref;}))refs.push({ref:ref,page:page.page_no});});});
    if(!refs.length)(q.asset_refs||[]).forEach(function(ref){if(!refs.some(function(x){return x.ref===ref;}))refs.push({ref:ref,page:null});});
    if(!refs.length)return '';
    return '<details class="ea-source-images"><summary>查看原卷扫描图 · '+refs.length+' 页</summary><div>'+refs.map(function(item){
      var url='/question-assets/'+encodeURIComponent(item.ref);
      return '<a href="'+esc(url)+'" target="_blank" rel="noopener"><img src="'+esc(url)+'" alt="原卷第 '+esc(item.page||'')+' 页扫描图"><span>原卷第 '+esc(item.page||'?')+' 页</span></a>';
    }).join('')+'</div></details>';
  }
  async function loadMeta() {
    meta = await request('/exam/templates'); templates = meta.templates || [];
    el('templateSelect').innerHTML = templates.map(function (t) {
      return '<option value="' + esc(t.id) + '">' + esc(t.name) + ' · v' + esc(t.version) + '</option>';
    }).join('');
    el('teacherSelect').innerHTML = (meta.teachers || ['liangliang']).map(function (teacher) {
      var labels = {liangliang:'亮亮老师',taotao:'涛涛老师',xuefeng:'雪峰老师',ji:'季老师'};
      return '<option value="' + esc(teacher) + '">' + esc(labels[teacher] || teacher) + '</option>';
    }).join('');
    el('templateEditor').hidden = !meta.can_edit;
    el('templateSelect').addEventListener('change', onTemplateChange);
    onTemplateChange();
  }
  function onTemplateChange() {
    var template = selectedTemplate(), lesson = template && template.exam_type === 'lesson';
    el('knowledgeSelect').hidden = !lesson;
    el('knowledgeOptions').innerHTML = (meta.knowledge_catalog || []).map(function (item) {
      return '<label><input type="checkbox" value="' + esc(item.id) + '"><span>' + esc(item.name) + '</span></label>';
    }).join('');
    if (meta.can_edit && template) el('templateJson').value = JSON.stringify(template, null, 2);
    refreshUploadButton();
  }
  function refreshUploadButton() {
    el('uploadButton').disabled = busy || selectedFiles.length === 0;
    if (selectedFiles.length) showMessage(selectedFiles.length === 1 && /\.pdf$/i.test(selectedFiles[0].name)
      ? '已选择 PDF。' : '图片将按下方顺序作为试卷页。', false);
  }
  function formatBytes(bytes) { return bytes < 1024 * 1024 ? Math.ceil(bytes / 1024) + ' KB' : (bytes / 1024 / 1024).toFixed(1) + ' MB'; }
  function renderFiles() {
    el('fileList').innerHTML = selectedFiles.map(function (file,index) {
      return '<li class="ea-file-row"><span class="ea-file-order">PAGE ' + String(index+1).padStart(2,'0') + '</span>' +
        '<span class="ea-file-name">' + esc(file.name) + '<span class="ea-file-size">' + formatBytes(file.size) + '</span></span>' +
        '<span class="ea-file-controls"><button type="button" data-action="move-file" data-index="' + index + '" data-delta="-1" aria-label="上移" ' + (index===0?'disabled':'') + '>↑</button>' +
        '<button type="button" data-action="move-file" data-index="' + index + '" data-delta="1" aria-label="下移" ' + (index===selectedFiles.length-1?'disabled':'') + '>↓</button>' +
        '<button type="button" data-action="remove-file" data-index="' + index + '" aria-label="移除">×</button></span></li>';
    }).join('');
    refreshUploadButton();
  }
  function addFiles(list) {
    var incoming = Array.prototype.slice.call(list || []);
    if (!incoming.length) return;
    if (selectedFiles.length && (incoming.some(function(f){return /\.pdf$/i.test(f.name);}) || selectedFiles.some(function(f){return /\.pdf$/i.test(f.name);})) ) {
      selectedFiles = [];
    }
    incoming.forEach(function (file) {
      if (!selectedFiles.some(function (item) { return item.name === file.name && item.size === file.size && item.lastModified === file.lastModified; })) selectedFiles.push(file);
    });
    if (selectedFiles.some(function(f){return /\.pdf$/i.test(f.name);}) && selectedFiles.length > 1) selectedFiles = [selectedFiles.find(function(f){return /\.pdf$/i.test(f.name);})];
    renderFiles();
  }
  function moveFile(index, delta) {
    var target = index + delta; if (target < 0 || target >= selectedFiles.length) return;
    var item = selectedFiles.splice(index,1)[0]; selectedFiles.splice(target,0,item); renderFiles();
  }
  async function upload() {
    if (busy || !selectedFiles.length) return;
    var template = selectedTemplate();
    if (!template) return;
    var selected = Array.from(el('knowledgeOptions').querySelectorAll('input:checked')).map(function(x){return x.value;});
    if (template.exam_type === 'lesson' && !selected.length) { showMessage('请先选择本课二级知识点。', true); return; }
    busy = true; el('uploadButton').disabled = true; el('uploadButton').textContent = '正在上传…';
    var body = new FormData();
    selectedFiles.forEach(function(file){body.append('files',file,file.name);});
    body.append('template_id',template.id); body.append('teacher',el('teacherSelect').value);
    body.append('title',el('analysisTitle').value.trim()); body.append('selected_knowledge_ids',JSON.stringify(selected));
    try {
      var analysis = await request('/exam/analyses',{method:'POST',body:body});
      selectedFiles=[]; renderFiles(); el('analysisTitle').value='';
      await refreshHistory(); await openAnalysis(analysis.id);
    } catch (error) { showMessage(error.message, true); }
    finally { busy=false; el('uploadButton').textContent='上传并识别'; refreshUploadButton(); }
  }
  async function refreshHistory() {
    var result = await request('/exam/analyses?limit=60');
    var items = result.analyses || [];
    if (!items.length) { el('historyList').innerHTML='<p class="ea-muted" style="padding:14px">还没有分析记录。</p>'; return; }
    el('historyList').innerHTML = items.map(function (item) {
      return '<button class="ea-history-item ' + (current && current.id === item.id ? 'active' : '') + '" data-action="open-analysis" data-id="' + esc(item.id) + '">' +
        '<strong>' + esc(item.title) + '</strong><span>' + esc(statusText(item.status)) + ' · ' + esc(formatDate(item.created_at)) + '</span></button>';
    }).join('');
  }
  function extractionIssues(analysis) {
    var issues = analysis.report && analysis.report.extraction_issues;
    if (!issues) return '';
    var parts=[];
    if ((issues.missing_question_numbers||[]).length) parts.push('模板要求题号缺少：'+issues.missing_question_numbers.join('、'));
    if ((issues.duplicate_question_numbers||[]).length) parts.push('识别到重复题号：'+issues.duplicate_question_numbers.join('、'));
    if ((issues.unassigned_question_ids||[]).length) parts.push('有 '+issues.unassigned_question_ids.length+' 道题未识别到原题号');
    if ((issues.incomplete_question_numbers||[]).length) parts.push('疑似不完整：'+issues.incomplete_question_numbers.join('、'));
    return parts.length ? '<div class="ea-anomalies"><strong>识别核对提示</strong><br>' + parts.map(esc).join('<br>') + '</div>' : '';
  }
  async function openAnalysis(id) {
    clearTimeout(pollTimer);
    try {
      current = await request('/exam/analyses/' + encodeURIComponent(id));
      var url = new URL(location.href); url.searchParams.set('analysis',id); history.replaceState(null,'',url);
      await renderCurrent(); await refreshHistory();
      if (['extracting','solving'].includes(current.status)) schedulePoll(id);
    } catch (error) { el('reportPanel').innerHTML='<div class="ea-notice">' + esc(error.message) + '</div>'; }
  }
  function schedulePoll(id) {
    clearTimeout(pollTimer); pollTimer=setTimeout(async function(){
      if (!current || current.id!==id) return;
      try { current=await request('/exam/analyses/'+encodeURIComponent(id)); await renderCurrent(); await refreshHistory();
        if (['extracting','solving'].includes(current.status)) schedulePoll(id);
      } catch (ignore) { schedulePoll(id); }
    },2500);
  }
  function metricsHtml(report) {
    if (!report) return '<div class="ea-notice">解题尚未完成评分。识别结果确认后开始逐题解答。</div>';
    var d=report.difficulty_fit||{}, c=report.coverage||{};
    return '<div class="ea-metrics"><div class="ea-metric"><div class="ea-metric-label">逐题难度适配</div><div class="ea-metric-number">' +
      (d.score==null?'待补':fmt(d.score,2)) + ' <small>/ 15</small></div><div class="ea-metric-note">' + (d.rmse==null?'有题目未取得 0–15 难度分。':'RMSE ' + fmt(d.rmse,3) + ' · 按题号逐题平方差计算') +
      '</div></div><div class="ea-metric"><div class="ea-metric-label">知识点与属性覆盖</div><div class="ea-metric-number">' +
      (c.score==null?'待核对':fmt(c.score,0)) + ' <small>/ ' + fmt(c.maximum,0) + '</small></div><div class="ea-metric-note">扣分 ' + fmt(c.penalty,0) + ' · ' + esc(c.provisional_reason || '知识点与属性分别计数，同题重复只计一次。') +
      ' 虚线属性标签是 AI 候选，当前覆盖数按候选结果统计。' + '</div></div></div>';
  }
  function difficultyTable(report) {
    if (!report) return '';
    var d=report.difficulty_fit||{};
    var rows=(d.questions||[]).map(function(q){
      var diff=q.difference==null?'—':(q.difference>0?'+'+q.difference:String(q.difference));
      var cls=q.direction==='匹配'?'ea-ok':q.direction==='待完成'?'ea-pending':'ea-gap';
      var sub=q.subquestions&&q.subquestions.length?' · 小问 '+q.subquestions.map(function(s){return s.label+': '+(s.actual==null?'待补':s.actual);}).join(' / '):'';
      return '<tr><td class="num">' + esc(q.question_no==null?'?':q.question_no) + '</td><td class="num">' + fmt(q.target) + '</td><td class="num">' + fmt(q.actual) + '</td><td class="num ' + cls + '">' + esc(diff) + ' ' + esc(q.direction) + '</td><td class="num">' + fmt(q.squared_error) + '</td><td>' + esc(sub || '整题作为一个题位计入') + '</td></tr>';
    }).join('');
    return '<section class="ea-table-section"><div class="ea-table-title"><h3>逐题难度对照</h3><span>差值 = 实际分 − 目标分；平方差为该题扣差</span></div><div class="ea-table-wrap"><table class="ea-table"><thead><tr><th>题号</th><th>目标分</th><th>实际分</th><th>差值与方向</th><th>平方差</th><th>小问难度 / 计分口径</th></tr></thead><tbody>' + rows + '</tbody></table></div></section>';
  }
  function coverageTable(report, key, title, note) {
    if (!report) return '';
    var rows=(report.coverage && report.coverage[key] || []).map(function(row){
      var gap=row.pending_review?'待核对':row.gap_type==='符合'?'符合':(row.gap_type+' '+row.gap);
      var cls=row.pending_review?'ea-pending':row.gap_type==='符合'?'ea-ok':'ea-gap';
      return '<tr><td>' + esc(row.name) + '</td><td class="num">' + esc(row.minimum+'–'+row.maximum) + '</td><td class="num">' + esc(row.actual_count) + '</td><td class="qnums">' + (row.question_numbers.length?row.question_numbers.map(esc).join('、'):'—') + '</td><td class="' + cls + '">' + esc(gap) + '</td><td class="num">' + fmt(row.penalty) + '</td></tr>';
    }).join('');
    return '<section class="ea-table-section"><div class="ea-table-title"><h3>' + esc(title) + '</h3><span>' + esc(note) + '</span></div><div class="ea-table-wrap"><table class="ea-table"><thead><tr><th>目标</th><th>题数范围</th><th>实际题数</th><th>题号</th><th>偏差</th><th>平方扣分</th></tr></thead><tbody>' + (rows||'<tr><td colspan="6">模板没有设置此类覆盖目标。</td></tr>') + '</tbody></table></div></section>';
  }
  function answerHtml(result) {
    if (!result) return '<span class="ea-muted">解析待生成</span>';
    var chunks=result.chunk_results||[], html='';
    chunks.forEach(function(chunk,index){
      var d=chunk.difficulty||{};
      html+='<h4>' + esc(chunk.chunk_type||('解答部分 '+(index+1))) + ' · ' + (d.total_score==null?'难度待核':esc(d.total_score)+' 分') + '</h4>';
      if (chunk.final_answer) html+='<div class="ea-answer-text">' + esc(chunk.final_answer) + '</div>';
      (chunk.steps||[]).forEach(function(step){
        var text=step.detailed_writing||step.standard_writing||step.content||'';
        if (text) html+='<p class="ea-answer-text">' + esc((step.title?step.title+'：':'')+text) + '</p>';
      });
    });
    if (!chunks.length) html='<div class="ea-answer-text">' + esc(result.final_answer||result.content||'暂无解析文本') + '</div>';
    return html;
  }
  function knowledgeSelect(q, field) {
    var ids=q[field]||[];
    return '<select multiple size="5" data-label-select="' + field + '" data-qid="' + esc(q.id) + '">' + (meta.knowledge_catalog||[]).map(function(k){
      return '<option value="' + esc(k.id) + '" ' + (ids.includes(k.id)?'selected':'') + '>' + esc(k.name) + '</option>';
    }).join('') + '</select>';
  }
  function labelEditor(q, includeText) {
    return (includeText?'<label>核对或修改题干（改动会清除旧解析）</label><textarea data-latex="'+esc(q.id)+'">'+esc(q.latex)+'</textarea>':'')+
      '<div class="ea-label-editor"><div><label>核心考查知识点 · 多选</label>'+knowledgeSelect(q,'knowledge_core')+
      '<label>前置知识 · 多选</label>'+knowledgeSelect(q,'knowledge_prerequisites')+'</div><div><label>套路属性 · 多选</label>'+
      '<select multiple size="6" data-label-select="attributes" data-qid="'+esc(q.id)+'">'+(meta.attributes||[]).map(function(a){return '<option value="'+esc(a.id)+'" '+((q.attributes||[]).includes(a.id)?'selected':'')+'>'+esc(a.name)+'</option>';}).join('')+'</select>'+
      '</div></div>';
  }
  function questionDetail(q, editable) {
    var labels=(q.knowledge_core||[]).map(function(id){return (meta.knowledge_catalog||[]).find(function(k){return k.id===id;})||{name:id};});
    var prerequisites=(q.knowledge_prerequisites||[]).map(function(id){return (meta.knowledge_catalog||[]).find(function(k){return k.id===id;})||{name:id};});
    var attrs=(q.attributes||[]).map(function(id){return (meta.attributes||[]).find(function(a){return a.id===id;})||{name:id};});
    var tags=labels.map(function(x){return '<span class="ea-tag ' + (q.labels_source==='candidate'?'candidate':'') + '">' + esc(x.name) + '</span>';}).join('')+
      attrs.map(function(x){return '<span class="ea-tag ' + (q.labels_source==='candidate'?'candidate':'') + '">' + esc(x.name) + '</span>';}).join('');
    var status=q.solve_status==='done'?'解析完成':q.solve_status==='error'?'解答失败':q.solve_status==='solving'?'解答中':'待解答';
    var html='<div class="ea-question-meta">来源页：' + esc(sourcePageLabel(q)) + ' · ' + esc(status) +
      (q.confidence<0.6?' · 识别置信度偏低，请优先核对':'') + '</div>';
    html+=sourceImagesHtml(q);
    if (q.unmapped_knowledge&&q.unmapped_knowledge.length) html+='<div class="ea-unmapped">待核知识点：' + q.unmapped_knowledge.map(function(x){return esc(x.text);}).join('、') + '（未计作确定缺失）</div>';
    if (editable) {
      html+='<div class="ea-q-editor"><label>原题内容（保留题目原文，修改后旧解析会失效）</label><textarea data-latex="' + esc(q.id) + '">' + esc(q.latex) + '</textarea>'+
        '<div class="ea-label-editor"><div><label>核心考查知识点 · 多选</label>' + knowledgeSelect(q,'knowledge_core') + '<label>前置知识 · 多选</label>' + knowledgeSelect(q,'knowledge_prerequisites') + '</div>'+
        '<div><label>套路属性候选 · 多选</label><select multiple size="6" data-label-select="attributes" data-qid="' + esc(q.id) + '">' + (meta.attributes||[]).map(function(a){return '<option value="'+esc(a.id)+'" '+((q.attributes||[]).includes(a.id)?'selected':'')+'>'+esc(a.name)+'</option>';}).join('') + '</select>'+
        '<label class="ea-label-confirm"><input type="checkbox" data-label-confirm="' + esc(q.id) + '">我已核对并确认这题的标签</label></div></div></div>';
    } else {
      html+='<div class="ea-question-text" data-math>' + esc(q.latex) + '</div>';
      html+='<h4>知识点与属性' + (q.labels_source==='candidate'?' · AI 候选':' · 人工确认') + '</h4><div class="ea-tagline" style="justify-content:flex-start">' + (tags||'<span class="ea-muted">暂无确定标签</span>') + '</div>';
      html+='<h4>前置知识 · 不计入覆盖分</h4><div class="ea-tagline" style="justify-content:flex-start">'+(prerequisites.map(function(x){return '<span class="ea-tag ea-prerequisite">'+esc(x.name)+'</span>';}).join('')||'<span class="ea-muted">暂无前置知识标注</span>')+'</div>';
      if(q.attribute_evidence&&Object.keys(q.attribute_evidence).length) html+='<p class="ea-question-meta">候选依据：'+Object.entries(q.attribute_evidence).map(function(pair){var a=(meta.attributes||[]).find(function(x){return x.id===pair[0];});return esc((a&&a.name||pair[0])+'：'+pair[1]);}).join('；')+'</p>';
      html+='<details class="ea-q-editor"><summary>核对并修正知识点与属性</summary>'+labelEditor(q,true)+'<button type="button" class="ea-button ea-button-secondary" data-action="save-labels" data-id="'+esc(q.id)+'">保存本题修正</button></details>';
      html+=answerHtml(q.answer_result);
      if(q.error) html+='<div class="ea-notice">' + esc(q.error) + '</div>';
      if(q.solve_status!=='done') html+='<button type="button" class="ea-button ea-button-secondary" data-action="retry-question" data-id="'+esc(q.id)+'">重试本题</button>';
      if(q.solve_status==='done') html+='<button type="button" class="ea-button ea-button-secondary" data-action="add-bank" data-number="'+esc(q.question_no)+'">加入个人题库</button>';
    }
    return html;
  }
  function reviewHtml(analysis, questions) {
    var issues=analysis.report&&analysis.report.extraction_issues||{};
    var missing=issues.missing_question_numbers||[],duplicates=issues.duplicate_question_numbers||[];
    var issueParts=[];
    if(missing.length) issueParts.push('模板要求但未识别到的题号：'+missing.join('、'));
    if(duplicates.length) issueParts.push('重复题号：'+duplicates.join('、'));
    if((issues.unassigned_question_ids||[]).length) issueParts.push('题号待补题目：'+issues.unassigned_question_ids.length+' 道');
    if((issues.incomplete_question_numbers||[]).length) issueParts.push('识别提示不完整：'+issues.incomplete_question_numbers.join('、'));
    var html='<div class="ea-notice">核对题号、每题内容和来源页。跨页题应合并为同一个题号；所有异常都可在下方编辑。</div>';
    if(issueParts.length) html+='<div class="ea-anomalies"><strong>切题检查</strong><br>'+issueParts.map(esc).join('<br>')+'</div>';
    html+='<div class="ea-question-ledger"><h3>已识别 '+questions.length+' 道题 · 核对原题号与题干</h3>';
    html+=questions.map(function(q){
      return '<details class="ea-question" open><summary><span class="ea-question-number">第 '+esc(q.question_no==null?'?':q.question_no)+' 题</span><span class="ea-question-diff">'+esc(sourcePageLabel(q))+'</span><span class="ea-question-title">'+esc((q.latex||'').slice(0,90))+'</span><span class="ea-small-note">'+(q.is_complete?'完整':'待确认')+'</span></summary>'+
        '<div class="ea-question-detail"><div class="ea-q-editor"><label>卷面原题号</label><input type="number" min="1" max="999" data-qno="'+esc(q.id)+'" value="'+esc(q.question_no==null?'':q.question_no)+'" style="width:100px;padding:7px;border:1px solid #d5dedb">'+
        '<label>题目完整</label><label class="ea-label-confirm"><input type="checkbox" data-complete="'+esc(q.id)+'" '+(q.is_complete?'checked':'')+'>我已确认题干、选项和小问完整；跨页内容已合并</label></div>'+questionDetail(q,true)+'</div></details>';
    }).join('')+'</div>'+
      '<label class="ea-review-confirm"><input type="checkbox" id="reviewConfirm">我已按原卷核对全部题号、页码、跨页合并与题目完整性，确认开始逐题解答。</label>'+
      '<div class="ea-report-actions"><button class="ea-button ea-button-secondary" data-action="save-review">保存核对</button><button class="ea-button ea-button-primary" data-action="start-analysis">核对完成并开始解答</button></div>';
    return html;
  }
  function questionsHtml(analysis, questions) {
    var editable=['awaiting_review','cancelled','extract_error','interrupted'].includes(analysis.status) && !analysis.review_confirmed;
    var ordered=sortQuestions(questions);
    return '<div class="ea-question-ledger"><h3>逐题记录 · '+(analysis.report?analysis.report.completed_questions:'0')+' / '+ordered.length+' 道已完成</h3>' + ordered.map(function(q){
      var difficulty=(q.answer_result&&q.answer_result.overall_difficulty)||{};
      var target=analysis.report&&analysis.report.difficulty_fit&&analysis.report.difficulty_fit.questions.find(function(row){return row.question_no===q.question_no;});
      var title=(q.latex||'').replace(/\s+/g,' ').slice(0,110);
      return '<details class="ea-question"><summary><span class="ea-question-number">第 '+esc(q.question_no==null?'?':q.question_no)+' 题</span><span class="ea-question-diff">目标 '+fmt(target&&target.target)+' · 实际 '+fmt(difficulty.total_score)+'</span><span class="ea-question-title">'+esc(title)+'</span><span class="ea-tagline">'+esc(q.solve_status||'')+'</span></summary><div class="ea-question-detail">'+questionDetail(q,editable)+'</div></details>';
    }).join('')+'</div>';
  }
  function reportActions(analysis) {
    var matching=templates.filter(function(t){return t.exam_type===analysis.exam_type;});
    return '<div class="ea-report-actions">'+
      (['extracting','solving'].includes(analysis.status)?'<button class="ea-button ea-button-secondary" data-action="cancel-analysis">停止任务</button>':'')+
      (analysis.status==='partial'||analysis.status==='cancelled'||analysis.status==='interrupted'||analysis.status==='extract_error'||analysis.status==='extract_interrupted'?'<button class="ea-button ea-button-secondary" data-action="retry-analysis">'+(analysis.questions&&analysis.questions.length?'重试未完成题目':'重新识别')+'</button>':'')+
      (analysis.review_confirmed?'<select id="rescoreTemplateSelect" aria-label="重新评分模板">'+matching.map(function(t){return '<option value="'+esc(t.id)+'" '+(t.id===analysis.template_id?'selected':'')+'>'+esc(t.name)+' v'+esc(t.version)+'</option>';}).join('')+'</select><button class="ea-button ea-button-secondary" data-action="rescore">重新评分</button>':'')+
      '</div>';
  }
  function renderCurrent() {
    if (!current) return;
    var analysis=current, questions=sortQuestions(current.questions||[]), report=current.report;
    var active=['extracting','solving'].includes(analysis.status), job=analysis.job||{};
    var progress=active?'<div class="ea-progress"><div class="ea-progress-top"><span>'+esc(job.detail||statusText(analysis.status))+'</span><span>'+esc(job.progress||0)+' / 100</span></div><progress max="100" value="'+esc(job.progress||0)+'"></progress></div>':'';
    var reportSection=analysis.status==='awaiting_review'?reviewHtml(analysis,questions):'';
    if (['extract_error','extract_interrupted','cancelled'].includes(analysis.status)&&!questions.length) reportSection='<div class="ea-notice">'+esc(statusText(analysis.status))+'：'+esc(analysis.error||'可以重新识别，已上传的原卷仍保留。')+'</div>';
    if (analysis.status!=='awaiting_review'&&questions.length) {
      reportSection=metricsHtml(report)+difficultyTable(report)+coverageTable(report,'knowledge','知识点覆盖','每个目标的实际题号；同题重复只计一次')+coverageTable(report,'attributes','套路属性覆盖','属性允许多标签；虚线标签为候选')+questionsHtml(analysis,questions);
      if(report&&report.coverage&&report.coverage.unmapped_knowledge&&report.coverage.unmapped_knowledge.length)
        reportSection=reportSection.replace('<div class="ea-metrics">','<div class="ea-notice">有未能映射到分类目录的知识点，暂不把相应目标记作确定缺失：'+report.coverage.unmapped_knowledge.map(function(x){return esc(x.text);}).join('、')+'</div><div class="ea-metrics">');
    }
    var warning=analysis.error&&analysis.status!=='extract_error'?'<div class="ea-notice">'+esc(analysis.error)+'</div>':'';
    var versions=analysis.report_versions&&analysis.report_versions.length?'<details><summary>查看报告版本快照（'+analysis.report_versions.length+'）</summary><ol class="ea-version-list">'+analysis.report_versions.map(function(v){return '<li>第 '+esc(v.version)+' 版 · '+esc(v.template_id)+' v'+esc(v.template_version)+' · '+esc(formatDate(v.created_at))+'</li>';}).join('')+'</ol></details>':'';
    el('reportPanel').innerHTML='<div class="ea-report-header"><div class="ea-report-title"><h2>'+esc(analysis.title)+'</h2><p>'+esc(analysis.template.name)+' · 模板 v'+esc(analysis.template_version)+' · '+esc(analysis.source_files.map(function(f){return f.filename;}).join('、'))+'</p></div><span class="ea-status '+esc(analysis.status)+'">'+esc(statusText(analysis.status))+'</span>'+reportActions(analysis)+'</div>'+progress+'<div class="ea-report-body">'+warning+reportSection+versions+'</div>';
    if(window.renderMathInElement) {
      try { window.renderMathInElement(el('reportPanel'),{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\(',right:'\\)',display:false}],ignoredTags:['textarea','script','noscript','style']}); } catch(ignore) {}
    }
  }
  function readQuestionPatches() {
    if (!current) return [];
    return sortQuestions(current.questions||[]).map(function(q){
      var patch={id:q.id};
      var number=el('reportPanel').querySelector('[data-qno="'+q.id+'"]');
      if(number&&number.value!=='') patch.question_no=Number(number.value);
      var latex=el('reportPanel').querySelector('[data-latex="'+q.id+'"]');
      if(latex) patch.latex=latex.value;
      var complete=el('reportPanel').querySelector('[data-complete="'+q.id+'"]');
      if(complete) patch.is_complete=complete.checked;
      var confirm=el('reportPanel').querySelector('[data-label-confirm="'+q.id+'"]');
      if(confirm&&confirm.checked) {
        patch.knowledge_core=Array.from(el('reportPanel').querySelector('[data-label-select="knowledge_core"][data-qid="'+q.id+'"]').selectedOptions).map(function(o){return o.value;});
        patch.knowledge_prerequisites=Array.from(el('reportPanel').querySelector('[data-label-select="knowledge_prerequisites"][data-qid="'+q.id+'"]').selectedOptions).map(function(o){return o.value;});
        patch.attributes=Array.from(el('reportPanel').querySelector('[data-label-select="attributes"][data-qid="'+q.id+'"]').selectedOptions).map(function(o){return o.value;});
      }
      return patch;
    });
  }
  async function saveReview() {
    var questions=readQuestionPatches();
    current=await request('/exam/analyses/'+current.id+'/questions',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({questions:questions})});
    await renderCurrent(); await refreshHistory();
  }
  async function startAnalysis() {
    var confirm=el('reviewConfirm');
    if(!confirm||!confirm.checked) { alert('请确认已核对原题号、页码、跨页合并和题目完整性。'); return; }
    try { await saveReview(); await request('/exam/analyses/'+current.id+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm_review:true})}); await openAnalysis(current.id); }
    catch(error) { renderActionError(error); }
  }
  function renderActionError(error) {
    var box=el('reportPanel').querySelector('.ea-report-body')||el('reportPanel');
    var notice=document.createElement('div'); notice.className='ea-notice'; notice.textContent=error.message; box.prepend(notice);
  }
  async function retryAnalysis() {
    try { await request('/exam/analyses/'+current.id+'/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})}); await openAnalysis(current.id); }
    catch(error) { renderActionError(error); }
  }
  async function retryQuestion(id) {
    try { await request('/exam/analyses/'+current.id+'/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question_ids:[id]})}); await openAnalysis(current.id); }
    catch(error) { renderActionError(error); }
  }
  async function cancelAnalysis() {
    try { current=await request('/exam/analyses/'+current.id+'/cancel',{method:'POST'}); await renderCurrent(); await refreshHistory(); }
    catch(error) { renderActionError(error); }
  }
  async function rescore() {
    try { var id=el('rescoreTemplateSelect').value; await request('/exam/analyses/'+current.id+'/rescore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template_id:id})}); await openAnalysis(current.id); }
    catch(error) { renderActionError(error); }
  }
  async function addToBank(number, button) {
    try { var result=await request('/exam/analyses/'+current.id+'/add-to-bank',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question_numbers:[Number(number)]})});
      button.textContent='已加入题库 · '+result.saved[0].id; button.disabled=true;
    } catch(error) { renderActionError(error); }
  }
  async function saveLabels(id) {
    try {
      var q=(current.questions||[]).find(function(item){return item.id===id;});
      if(!q) throw new Error('题目记录不存在');
      var patch={id:id};
      var text=el('reportPanel').querySelector('[data-latex="'+id+'"]');
      if(text&&text.value!==q.latex) patch.latex=text.value;
      else ['knowledge_core','knowledge_prerequisites','attributes'].forEach(function(field){
          var select=el('reportPanel').querySelector('[data-label-select="'+field+'"][data-qid="'+id+'"]');
          patch[field]=Array.from(select.selectedOptions).map(function(option){return option.value;});
        });
      current=await request('/exam/analyses/'+current.id+'/questions',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({questions:[patch]})});
      if(!patch.latex) await request('/exam/analyses/'+current.id+'/rescore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({template_id:current.template_id})});
      await openAnalysis(current.id);
    } catch(error) { renderActionError(error); }
  }
  async function saveTemplate() {
    var status=el('templateSaveStatus');
    try {
      var data=JSON.parse(el('templateJson').value), selected=selectedTemplate();
      var result=await request('/exam/templates/'+encodeURIComponent(selected.id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      status.textContent='已发布 v'+result.version; await loadMeta();
      el('templateSelect').value=result.id; onTemplateChange();
    } catch(error) { status.textContent=error.message; status.className='ea-error'; }
  }
  function newAnalysis() {
    current=null; clearTimeout(pollTimer); history.replaceState(null,'',location.pathname);
    el('reportPanel').innerHTML='<div class="ea-empty-report"><span class="ea-empty-glyph">01—19</span><h2>逐题看清这张卷子</h2><p>上传一份新试卷，系统会先识别题目并保留原题号与页码。</p></div>';
    refreshHistory(); el('uploadPanel').scrollIntoView({behavior:'smooth',block:'start'});
  }
  document.addEventListener('click',function(event){
    var button=event.target.closest('[data-action]'); if(!button)return;
    var action=button.getAttribute('data-action');
    if(action==='move-file') moveFile(Number(button.dataset.index),Number(button.dataset.delta));
    if(action==='remove-file') { selectedFiles.splice(Number(button.dataset.index),1);renderFiles(); }
    if(action==='open-analysis') openAnalysis(button.dataset.id);
    if(action==='save-review') saveReview().catch(renderActionError);
    if(action==='start-analysis') startAnalysis();
    if(action==='retry-analysis') retryAnalysis();
    if(action==='retry-question') retryQuestion(button.dataset.id);
    if(action==='cancel-analysis') cancelAnalysis();
    if(action==='rescore') rescore();
    if(action==='add-bank') addToBank(button.dataset.number,button);
    if(action==='save-labels') saveLabels(button.dataset.id);
  });
  el('chooseFilesButton').addEventListener('click',function(event){event.stopPropagation();el('fileInput').click();});
  el('dropzone').addEventListener('click',function(event){if(event.target.closest('button'))return;el('fileInput').click();});
  el('dropzone').addEventListener('keydown',function(event){if(event.key==='Enter'||event.key===' '){event.preventDefault();el('fileInput').click();}});
  el('dropzone').addEventListener('dragover',function(event){event.preventDefault();el('dropzone').classList.add('drag-over');});
  el('dropzone').addEventListener('dragleave',function(){el('dropzone').classList.remove('drag-over');});
  el('dropzone').addEventListener('drop',function(event){event.preventDefault();el('dropzone').classList.remove('drag-over');addFiles(event.dataTransfer.files);});
  el('fileInput').addEventListener('change',function(event){addFiles(event.target.files);event.target.value='';});
  el('uploadButton').addEventListener('click',upload);
  el('newAnalysisButton').addEventListener('click',newAnalysis);
  el('saveTemplateButton').addEventListener('click',saveTemplate);
  window.addEventListener('beforeunload',function(event){if(busy){event.preventDefault();event.returnValue='';}});
  document.addEventListener('DOMContentLoaded',async function(){
    try { await StudyAuth.ready; await loadMeta(); await refreshHistory();
      var id=new URLSearchParams(location.search).get('analysis'); if(id) await openAnalysis(id);
    } catch(error) { el('historyList').innerHTML='<p class="ea-error" style="padding:14px">'+esc(error.message)+'</p>'; }
  });
})();
