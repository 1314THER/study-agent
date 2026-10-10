/* Private intake workbench. Original text and AI drafts stay outside the formal bank. */
(function () {
  'use strict';
  var STORAGE_KEY = 'question_pool_workbench_v1';
  var STATUS = {unreviewed: '未筛选', reviewed: '已筛选', preparing: '准备解析中', ready: '可预览入库', needs_review: '解析待复核', imported: '已入库'};
  var COMPLETENESS = {complete: '文字完整', needs_review: '待确认', deferred_graphic: '暂缓图形题', failed: '提取失败'};
  var ROLES = {question: '普通题库题', mother: '母题', variant1: '变式 1', variant2: '变式 2', variant3: '变式 3'};
  var DEFAULT_FILTERS = {category: '', source_id: '', year: '', question_type: '', keyword: '', completeness: 'text_only', status: ''};
  var FILTER_IDS = {category: 'poolCategory', source_id: 'poolSource', year: 'poolYear', question_type: 'poolType', keyword: 'poolKeyword', completeness: 'poolCompleteness', status: 'poolStatus'};

  function safeUrl(value) {
    if (!value) return null;
    try { var parsed = new URL(String(value)); return /^https?:$/.test(parsed.protocol) ? parsed.href : null; } catch (_) { return null; }
  }
  function makeQuery(filters, page, pageSize) {
    var params = new URLSearchParams();
    Object.keys(DEFAULT_FILTERS).forEach(function (key) { if (filters[key] || key === 'completeness') params.set(key, String(filters[key] || '').trim()); });
    params.set('page', Math.max(1, Number(page) || 1)); params.set('page_size', Number(pageSize) === 80 ? 80 : 40);
    return params.toString();
  }
  function restoreState(storage) {
    var value;
    try { value = JSON.parse(storage.getItem(STORAGE_KEY) || 'null'); } catch (_) {}
    value = value && typeof value === 'object' ? value : {};
    var filters = Object.assign({}, DEFAULT_FILTERS);
    Object.keys(DEFAULT_FILTERS).forEach(function (key) { if (value.filters && typeof value.filters[key] === 'string') filters[key] = value.filters[key]; });
    return {filters: filters, page: Math.max(1, Number(value.page) || 1), pageSize: Number(value.pageSize) === 80 ? 80 : 40,
      activeId: Number(value.activeId) || null, selected: Array.from(new Set((Array.isArray(value.selected) ? value.selected : []).map(Number).filter(function (id) { return Number.isInteger(id) && id > 0; }))),
      teacher: ['liangliang', 'xuefeng', 'taotao', 'ji'].includes(value.teacher) ? value.teacher : 'liangliang', pendingJob: value.pendingJob || null, commitIntent: value.commitIntent || null};
  }
  function finalAnswer(prepared) {
    if (!prepared) return '';
    if (prepared.final_answer) return String(prepared.final_answer);
    return (prepared.chunk_results || []).map(function (chunk) { return chunk.final_answer || ''; }).filter(Boolean).join('\n');
  }
  function sourceLocation(source) {
    var bits = [];
    if (source.page_start) bits.push('第 ' + source.page_start + (source.page_end && source.page_end !== source.page_start ? '–' + source.page_end : '') + ' 页');
    if (source.question_no) bits.push('第 ' + source.question_no + ' 题');
    if (source.source_key) bits.push(source.source_key);
    return bits.join(' · ');
  }
  function blockingErrors(item) { return Array.isArray(item.blocking_errors) ? item.blocking_errors : (item.can_commit ? [] : item.errors || ['尚不可入库']); }
  function needsConfirmation(item) { return !!item.needs_confirmation || !!(item.answer_check && ['conflict', 'unverified'].includes(item.answer_check.status)) || !!(item.existing_answer_check && ['conflict', 'unverified'].includes(item.existing_answer_check.status)); }
  function eligiblePreview(items, confirmations) {
    return items.filter(function (item) { return item.can_commit && !blockingErrors(item).length && (!needsConfirmation(item) || confirmations.has(Number(item.item_id))); });
  }

  function createController(options) {
    options = options || {};
    var doc = options.document || document, storage = options.storage || localStorage;
    var auth = options.auth || window.StudyAuth, fetcher = options.fetch || window.fetch.bind(window);
    var saved, state = {items: [], total: 0, meta: {}, patterns: [], cache: new Map(), selected: new Set(), activeId: null, busy: false, loading: false, preview: [], confirmations: new Set(), listSequence: 0, detailSequence: 0, editorDirty: false, pendingNavigation: null};
    function el(id) { return doc.getElementById(id); }
    function node(tag, text, cls) { var n = doc.createElement(tag); if (text !== undefined) n.textContent = String(text); if (cls) n.className = cls; return n; }
    function button(text, action, cls) { var n = node('button', text, cls || 'pool-btn'); n.type = 'button'; n.addEventListener('click', action); return n; }
    function setOptions(select, entries, value) { select.replaceChildren(); entries.forEach(function (entry) { var option = node('option', entry[1]); option.value = String(entry[0]); select.appendChild(option); }); if (value !== undefined) select.value = String(value); }
    function persist() {
      var value = {filters: state.filters, page: state.page, pageSize: state.pageSize, activeId: state.activeId, selected: Array.from(state.selected), teacher: el('poolTeacher').value, pendingJob: state.pendingJob, commitIntent: state.commitIntent};
      try { storage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch (_) {}
    }
    function notice(message, error) { var box = el('poolNotice'); box.textContent = message || ''; box.classList.toggle('error', !!error); box.hidden = !message; }
    function math(target, text, cls) {
      var box = node('div', text || '', cls || 'pool-math'); target.appendChild(box);
      if (window.PoolMath) {
        window.PoolMath.render(box, text || '', {document: doc});
      } else if (window.renderMathInElement) {
        try { window.renderMathInElement(box, {delimiters: [{left: '$$', right: '$$', display: true}, {left: '\\[', right: '\\]', display: true}, {left: '$', right: '$', display: false}, {left: '\\(', right: '\\)', display: false}], throwOnError: false, trust: false, strict: 'ignore'}); } catch (_) {}
      }
      return box;
    }
    async function api(path, method, body) {
      if (!auth || !auth.isOwner()) throw new Error('原题池仅供主人账号维护。');
      var opts = {method: method || 'GET', credentials: 'same-origin', cache: 'no-store'};
      if (body !== undefined) { if (typeof FormData !== 'undefined' && body instanceof FormData) opts.body = body; else { opts.headers = {'Content-Type': 'application/json'}; opts.body = JSON.stringify(body); } }
      var response = await fetcher(path, opts), data;
      try { data = await response.json(); } catch (_) { throw new Error('服务器未返回可读取的结果，请稍后重试。'); }
      if (!response.ok || data.error) {
        var detail = data.detail || data.error;
        var error = new Error(typeof detail === 'string' ? detail : detail && detail.message || '请求未完成（HTTP ' + response.status + '）'); error.status = response.status; throw error;
      }
      return data;
    }
    function syncFilters() {
      Object.keys(FILTER_IDS).forEach(function (key) { el(FILTER_IDS[key]).value = state.filters[key]; });
      el('poolPageSize').value = String(state.pageSize);
    }
    async function loadMeta() {
      var results = await Promise.all([api('/question-pool/meta'), api('/patterns')]);
      state.meta = results[0]; state.patterns = Array.isArray(results[1]) ? results[1] : results[1].data || results[1].patterns || [];
      setOptions(el('poolCategory'), [['', '全部板块'], ['待分类', '待分类']].concat((state.meta.categories || []).map(function (v) { return [v, v]; })), state.filters.category);
      setOptions(el('poolType'), [['', '全部题型']].concat((state.meta.question_types || []).map(function (v) { return [v, v]; })), state.filters.question_type);
      setOptions(el('poolSource'), [['', '全部题源']].concat((state.meta.sources || []).map(function (v) { return [v.id, v.name]; })), state.filters.source_id);
      renderStats(); renderCoverage(); renderSources();
    }
    function renderStats() {
      var stats = state.meta.stats || {}, box = el('poolStats'); box.replaceChildren();
      function stat(label, keys, subtitle) { var n = node('div', undefined, 'pool-stat'), value = 0; for (var key of keys) if (stats[key] !== undefined) { value = Number(stats[key]) || 0; break; } n.append(node('strong', value.toLocaleString()), node('span', label), node('small', subtitle)); box.appendChild(n); }
      stat('原题总量', ['total', 'total_items', 'items'], '去重后 · 保留全部出处');
      stat('文字完整', ['complete', 'text_complete'], '文字条件足以作答');
      stat('待复核', ['needs_review', 'review_pending'], '题干或答案需要确认');
      stat('已入库', ['imported'], '已确认并保留独立出处');
    }
    function renderCoverage() {
      var box = el('poolCoverage'); box.replaceChildren();
      (state.meta.coverage || []).forEach(function (entry) {
        var row = node('div', undefined, 'pool-coverage-row'); row.appendChild(node('strong', entry.category || entry.name || '待分类'));
        var parts = [];
        [['candidates', '候选'], ['candidate_count', '候选'], ['pool_count', '候选'], ['patterns', '套路'], ['pattern_count', '套路'], ['mothers', '母题'], ['mother_count', '母题'], ['missing_mothers', '缺母题']].forEach(function (pair) { if (entry[pair[0]] !== undefined) parts.push(pair[1] + ' ' + entry[pair[0]]); });
        row.appendChild(node('span', parts.join(' · ') || entry.detail || '等待来源采集'));
        if (entry.gaps && entry.gaps.length) {
          var gaps = node('details', undefined, 'pool-coverage-gaps'); gaps.appendChild(node('summary', entry.gaps.length + ' 个套路有空角色'));
          entry.gaps.forEach(function (gap) {
            if (typeof gap === 'string') { gaps.appendChild(node('p', gap, 'pool-coverage-gap')); return; }
            var missing = [];
            if (gap.mother_missing) missing.push('缺母题');
            (gap.missing_roles || []).forEach(function (role) { if (role !== 'mother' || !gap.mother_missing) missing.push('缺' + (ROLES[role] || role)); });
            var line = node('div', undefined, 'pool-coverage-gap'); line.append(node('strong', gap.name || '套路 #' + gap.pattern_id), node('span', missing.join(' · '))); gaps.appendChild(line);
          }); row.appendChild(gaps);
        }
        box.appendChild(row);
      });
      if (!box.children.length) box.appendChild(node('p', '导入题源后查看候选与已有套路覆盖。', 'pool-muted'));
    }
    function invalidatePreview() { state.preview = []; state.confirmations.clear(); state.commitIntent = null; persist(); }
    function toggleSelection(id, force) {
      id = Number(id); if (force === undefined ? state.selected.has(id) : !force) state.selected.delete(id); else state.selected.add(id);
      invalidatePreview(); renderQueue(); renderSelectionState();
    }
    function renderSelectionState() {
      var selectable = state.items.filter(function (item) { return item.status !== 'imported'; });
      el('poolSelectPage').checked = !!selectable.length && selectable.every(function (item) { return state.selected.has(Number(item.id)); });
      el('poolSelectPage').indeterminate = selectable.some(function (item) { return state.selected.has(Number(item.id)); }) && !el('poolSelectPage').checked;
      doc.querySelectorAll('[data-pool-select]').forEach(function (input) { input.checked = state.selected.has(Number(input.dataset.poolSelect)); });
      var active = state.cache.get(state.activeId);
      if (active && el('poolSelectDetail')) el('poolSelectDetail').textContent = state.selected.has(active.id) ? '移出选择队列' : '加入选择队列';
    }
    function renderQueue() {
      el('poolSelectedCount').textContent = state.selected.size; var box = el('poolSelected'); box.replaceChildren();
      if (!state.selected.size) box.appendChild(node('p', '勾选候选题，逐题确定套路与角色。跨页选择会保留。', 'pool-muted'));
      state.selected.forEach(function (id) {
        var item = state.cache.get(id), chip = node('span', undefined, 'pool-selected-chip');
        var label = '#' + id + (item && item.assignment && item.assignment.role ? ' · ' + (ROLES[item.assignment.role] || item.assignment.role) : '');
        chip.appendChild(button(label, function () { selectItem(id, true).catch(function (e) { notice(e.message, true); }); }));
        var remove = button('×', function () { toggleSelection(id, false); }, 'remove'); remove.setAttribute('aria-label', '移出第 ' + id + ' 题'); chip.appendChild(remove); box.appendChild(chip);
      });
      updateBusy();
    }
    function updateBusy() {
      ['poolPrepare', 'poolPreview'].forEach(function (id) { el(id).disabled = state.busy || !state.selected.size; });
      el('poolUploadButton').disabled = state.busy; el('poolRefresh').disabled = state.busy;
      el('poolCommit').disabled = state.busy || !eligiblePreview(state.preview, state.confirmations).length;
    }
    function badge(text, style) { return node('span', text, 'pool-badge' + (style ? ' ' + style : '')); }
    function renderList() {
      var box = el('poolList'); box.replaceChildren(); box.setAttribute('aria-busy', 'false');
      el('poolResultCount').textContent = state.total.toLocaleString() + ' 道原题';
      if (!state.items.length) {
        var empty = node('div', undefined, 'pool-empty'); empty.appendChild(node('p', state.meta.sources && state.meta.sources.length ? '没有符合条件的原题。' : '原题池还没有题目。'));
        empty.appendChild(button(state.meta.sources && state.meta.sources.length ? '重置筛选' : '导入题源', function () { if (state.meta.sources && state.meta.sources.length) resetFilters(); else showDialog('poolSourcesDialog'); })); box.appendChild(empty);
      }
      state.items.forEach(function (item) {
        var card = node('article', undefined, 'pool-card' + (item.id === state.activeId ? ' active' : '')); card.tabIndex = 0; card.dataset.poolItem = item.id; card.setAttribute('aria-label', '查看原题 ' + item.id);
        var check = node('input'); check.type = 'checkbox'; check.dataset.poolSelect = item.id; check.checked = state.selected.has(Number(item.id)); check.disabled = item.status === 'imported'; check.setAttribute('aria-label', '选择原题 ' + item.id);
        check.addEventListener('click', function (event) { event.stopPropagation(); }); check.addEventListener('change', function () { toggleSelection(item.id, check.checked); }); card.appendChild(check);
        var head = node('div', undefined, 'pool-card-head'); head.appendChild(node('strong', '#' + item.id));
        (item.categories || []).forEach(function (category) { head.appendChild(badge(category, 'blue')); });
        head.appendChild(badge(STATUS[item.status] || item.status, item.status === 'imported' ? 'green' : item.status === 'needs_review' ? 'orange' : ''));
        if (item.completeness !== 'complete') head.appendChild(badge(COMPLETENESS[item.completeness] || item.completeness, 'orange')); card.appendChild(head);
        math(card, item.question, 'pool-card-question');
        var occurrence = (item.occurrences || [])[0], sourceText = [item.year, item.region, item.question_type, occurrence && occurrence.source_name, occurrence && sourceLocation(occurrence)].filter(Boolean).join(' · ');
        card.appendChild(node('span', sourceText || '出处待确认', 'pool-card-source'));
        card.addEventListener('click', function () { selectItem(item.id).catch(function (e) { notice(e.message, true); }); });
        card.addEventListener('keydown', function (event) { if (event.key === 'Enter' && event.target === card) { event.preventDefault(); selectItem(item.id).catch(function (e) { notice(e.message, true); }); } });
        box.appendChild(card);
      });
      var pages = Math.max(1, Math.ceil(state.total / state.pageSize)); el('poolPageLabel').textContent = state.page + ' / ' + pages;
      el('poolPrev').disabled = state.page <= 1; el('poolNext').disabled = state.page >= pages;
      renderSelectionState();
    }
    async function loadItems() {
      var sequence = ++state.listSequence; state.loading = true; el('poolList').setAttribute('aria-busy', 'true');
      try {
        var result = await api('/question-pool/items?' + makeQuery(state.filters, state.page, state.pageSize));
        if (sequence !== state.listSequence) return;
        state.total = Number(result.total) || 0; var pages = Math.max(1, Math.ceil(state.total / state.pageSize));
        if (state.page > pages) { state.page = pages; return loadItems(); }
        state.items = result.data || []; state.items.forEach(function (item) { state.cache.set(Number(item.id), item); });
        renderList(); renderQueue(); persist();
        if (state.activeId) await selectItem(state.activeId, false);
        else if (state.items.length) await selectItem(state.items[0].id, false);
        else { el('poolDetail').replaceChildren(node('p', '当前筛选没有原题。调整条件或导入题源后继续。', 'pool-empty')); el('poolPreviousItem').disabled = true; el('poolNextItem').disabled = true; }
      } catch (error) {
        if (sequence !== state.listSequence) return;
        el('poolList').replaceChildren(node('p', '读取失败。点击刷新重新连接。', 'pool-empty')); notice(error.message, true);
      } finally { if (sequence === state.listSequence) { state.loading = false; el('poolList').setAttribute('aria-busy', 'false'); } }
    }
    function fold(title, text) { var details = node('details', undefined, 'pool-fold'); details.appendChild(node('summary', title)); math(details, text || '题源未提供'); return details; }
    function renderCheck(target, check, existing) {
      if (!check) return;
      var labels = existing ? {match: '原答案与已有正式答案一致', conflict: '原答案与已有正式答案存在冲突 · 需复核', unverified: '已有正式答案尚未确认 · 需人工核对'} : {match: '原答案与 AI 答案一致', conflict: '答案存在冲突 · 入库前需复核', unverified: '答案尚未确认 · 入库前需人工核对'};
      var label = labels[check.status] || '等待核对';
      target.appendChild(node('p', label + (check.detail ? '\n' + check.detail : ''), 'pool-check ' + check.status));
    }
    function renderPrepared(target, item) {
      if (!item.prepared) { target.appendChild(node('p', item.status === 'preparing' ? 'AI 正在后台准备解析，完成后会更新。' : '尚未准备 AI 解析。先加入选择队列，再启动解析。', 'pool-muted')); return; }
      renderCheck(target, item.answer_check);
      var compare = node('div', undefined, 'pool-answer-grid');
      [['原题答案', item.answer], ['AI 答案', finalAnswer(item.prepared)]].forEach(function (pair) { var cell = node('div', undefined, 'pool-answer-cell'); cell.appendChild(node('h3', pair[0])); math(cell, pair[1] || '未提供'); compare.appendChild(cell); }); target.appendChild(compare);
      var details = node('details', undefined, 'pool-fold'); details.appendChild(node('summary', 'AI 解析'));
      var chunks = item.prepared.chunk_results || [];
      if (chunks.length) chunks.forEach(function (chunk, index) {
        if (chunks.length > 1) details.appendChild(node('h3', '第 ' + (index + 1) + ' 部分'));
        if (chunk.content || chunk.solution || chunk.explanation) math(details, chunk.content || chunk.solution || chunk.explanation);
        (chunk.steps || []).forEach(function (step, stepIndex) {
          details.appendChild(node('h4', (step.step_number || stepIndex + 1) + '. ' + (step.title || '解题步骤'), 'pool-step-title'));
          math(details, step.standard_writing || step.content || '');
          if (step.detailed_writing && step.detailed_writing !== step.standard_writing) details.appendChild(fold('详细说明', step.detailed_writing));
        });
      });
      else math(details, item.prepared.content || item.prepared.solution || item.prepared.explanation || '暂无分步解析'); target.appendChild(details);
    }
    function renderProvenance(target, item) {
      var details = node('details', undefined, 'pool-fold'); details.appendChild(node('summary', '出处 · ' + (item.occurrences || []).length + ' 条记录'));
      (item.occurrences || []).forEach(function (source) {
        var ref = node('div', undefined, 'pool-source-ref'); ref.append(node('strong', source.source_name || '未命名题源'), node('p', sourceLocation(source)));
        ref.appendChild(node('p', (source.license ? '许可：' + source.license : '许可待核验') + ' · ' + (source.publication_allowed ? '已允许公开所选题目' : '仅主人核对')));
        var url = safeUrl(source.url); if (url) { var link = node('a', '来源链接 ↗'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; ref.appendChild(link); }
        var sourceMeta = (state.meta.sources || []).find(function (entry) { return Number(entry.id) === Number(source.source_id); });
        if (source.source_id && sourceMeta && sourceMeta.has_file) { var fileLink = node('a', '查看原文件 ↗'); fileLink.href = '/question-pool/sources/' + encodeURIComponent(source.source_id) + '/file'; if (source.page_start) fileLink.href += '#page=' + source.page_start; fileLink.target = '_blank'; fileLink.rel = 'noopener noreferrer'; ref.appendChild(fileLink); }
        if (source.original_answer && source.original_answer !== item.answer) ref.appendChild(fold('该出处的原答案', source.original_answer));
        if (source.original_solution && source.original_solution !== item.solution) ref.appendChild(fold('该出处的原解析', source.original_solution));
        details.appendChild(ref);
      }); target.appendChild(details);
    }
    function markDirty() { state.editorDirty = true; invalidatePreview(); }
    function editorNavigation() {
      if (!state.editorDirty) return true;
      notice('当前修改尚未保存。请保存或取消编辑后继续切题。', true); return false;
    }
    async function selectItem(id, scroll) {
      id = Number(id); if (!editorNavigation()) return;
      var sequence = ++state.detailSequence, data = await api('/question-pool/items/' + id);
      if (sequence !== state.detailSequence) return;
      // A draft can change while a request is in flight, including a background refresh.
      if (!editorNavigation()) return;
      state.activeId = id; state.cache.set(id, data); state.editorDirty = false; renderDetail(data); renderList(); renderQueue(); persist();
      if (scroll && window.innerWidth <= 760) el('poolDetail').scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    function createLabel(text, field) { var label = node('label', text); label.appendChild(field); return label; }
    function lockForm(form) {
      var fields = Array.from(form.querySelectorAll('input, textarea, select, button')).map(function (field) { var previous = field.disabled; field.disabled = true; return [field, previous]; });
      return function () { fields.forEach(function (entry) { entry[0].disabled = entry[1]; }); };
    }
    function renderEditor(target, item) {
      var form = node('form', undefined, 'pool-editor'); form.appendChild(node('h3', '修正原题与分类'));
      var fields = {};
      [['question', '题干'], ['answer', '原答案'], ['solution', '原解析']].forEach(function (pair) { var input = node('textarea'); input.value = item[pair[0]] || ''; input.className = pair[0]; fields[pair[0]] = input; form.appendChild(createLabel(pair[1], input)); });
      var categoryBox = node('div', undefined, 'pool-categories'), categories = [];
      (state.meta.categories || []).forEach(function (category) { var check = node('input'); check.type = 'checkbox'; check.checked = (item.categories || []).includes(category); check.value = category; categories.push(check); var label = node('label'); label.append(check, node('span', category)); categoryBox.appendChild(label); });
      form.append(createLabel('所属大板块（可多选）', categoryBox));
      var type = node('select'); setOptions(type, (state.meta.question_types || []).map(function (value) { return [value, value === '未知' ? '未确定题型' : value]; }), item.question_type || '未知'); fields.question_type = type; form.appendChild(createLabel('题型', type));
      var completeness = node('select'); setOptions(completeness, Object.entries(COMPLETENESS), item.completeness); fields.completeness = completeness; form.appendChild(createLabel('题干完整性', completeness));
      var reason = node('textarea'); reason.value = item.reason || ''; fields.reason = reason; form.appendChild(createLabel('复核说明 / 暂缓原因', reason));
      var actions = node('div', undefined, 'pool-detail-actions'), save = button('保存修正', function () {}, 'pool-btn primary'); save.type = 'submit';
      actions.append(save, button('取消编辑', function () { state.editorDirty = false; renderDetail(item); notice('已取消未保存的修改。'); })); form.appendChild(actions);
      form.addEventListener('input', markDirty); form.addEventListener('change', markDirty);
      form.addEventListener('submit', async function (event) {
        event.preventDefault(); if (!fields.question.value.trim()) return notice('题干不能为空。', true);
        var payload = {expected_version: item.version}; Object.keys(fields).forEach(function (key) { payload[key] = fields[key].value; }); payload.categories = categories.filter(function (check) { return check.checked; }).map(function (check) { return check.value; }); payload.status = 'reviewed';
        var unlock = lockForm(form);
        try { await api('/question-pool/items/' + item.id, 'PATCH', payload); state.editorDirty = false; invalidatePreview(); await refresh(); notice('原题修正已保存；影响答案的修改需要重新准备解析。'); }
        catch (error) { notice(error.message, true); } finally { unlock(); }
      }); target.appendChild(form);
    }
    function renderAssignment(target, item) {
      var form = node('form', undefined, 'pool-assignment'), assignment = item.assignment || {role: 'question'}; form.appendChild(node('h3', '确定入库角色'));
      var role = node('select'), pattern = node('select'); setOptions(role, Object.entries(ROLES), assignment.role || 'question');
      var patternEntries = [['', '选择已有套路'], ['new', '+ 新建套路']].concat(state.patterns.map(function (p) { return [p.id, p.category + ' · ' + p.name]; })); setOptions(pattern, patternEntries, assignment.new_pattern ? 'new' : assignment.pattern_id || '');
      var row = node('div', undefined, 'pool-assignment-row'); row.append(createLabel('角色', role), createLabel('所属套路', pattern)); form.appendChild(row);
      var newBox = node('div', undefined, 'pool-new-pattern'), name = node('input'), category = node('select'), difficulty = node('select'), description = node('textarea'), values = assignment.new_pattern || {};
      name.value = values.name || ''; name.placeholder = '如：二次方程退化与判别式'; category.value = values.category || '';
      setOptions(category, [['', '选择板块']].concat((state.meta.categories || []).map(function (v) { return [v, v]; })), values.category || (item.categories || [])[0] || '');
      setOptions(difficulty, [['0', '0 · 送分'], ['1', '1 · 常规'], ['2', '2 · 难题'], ['3', '3 · 压轴']], values.difficulty === undefined ? 1 : values.difficulty); description.value = values.description || '';
      newBox.append(createLabel('套路名', name), createLabel('板块', category), createLabel('难度', difficulty), createLabel('套路说明', description)); form.appendChild(newBox);
      var slot = node('p', '', 'pool-slot-note'); form.appendChild(slot);
      function controls() {
        pattern.disabled = role.value === 'question'; newBox.hidden = role.value === 'question' || pattern.value !== 'new';
        var p = state.patterns.find(function (entry) { return String(entry.id) === pattern.value; }), bound;
        if (p) { var q = (p.questions || []).find(function (entry) { return entry.role === role.value; }); bound = q && q.question_id || (role.value === 'mother' ? p.mother_id : null); }
        slot.hidden = !bound; slot.textContent = bound ? '这个角色已关联题目 #' + bound + '。入库预览会显示冲突，请选择空角色或其他套路。' : '';
      }
      role.addEventListener('change', controls); pattern.addEventListener('change', controls); controls();
      var save = button('保存角色与套路', function () {}, 'pool-btn'); save.type = 'submit';
      var actions = node('div', undefined, 'pool-detail-actions'); actions.append(save, button('取消修改', function () { state.editorDirty = false; renderDetail(item); notice('已取消未保存的归类修改。'); })); form.appendChild(actions);
      form.addEventListener('input', markDirty); form.addEventListener('change', markDirty);
      form.addEventListener('submit', async function (event) {
        event.preventDefault(); var next = {role: role.value, pattern_id: null, new_pattern: null};
        if (role.value !== 'question') {
          if (pattern.value === 'new') { if (!name.value.trim() || !category.value) return notice('新套路需要填写板块和名称。', true); next.new_pattern = {name: name.value.trim(), category: category.value, description: description.value, difficulty: Number(difficulty.value)}; }
          else { if (!pattern.value) return notice('请为母题或变式选择一个套路。', true); next.pattern_id = Number(pattern.value); }
        }
        var unlock = lockForm(form);
        try { var changes = {assignment: next, expected_version: item.version}; if (item.status === 'unreviewed') changes.status = 'reviewed'; await api('/question-pool/items/' + item.id, 'PATCH', changes); state.editorDirty = false; invalidatePreview(); await selectItem(item.id, false); notice('角色与套路已保存，正式关联将在确认入库时建立。'); }
        catch (error) { notice(error.message, true); } finally { unlock(); }
      }); target.appendChild(form);
    }
    function renderDetail(item) {
      var box = el('poolDetail'); box.replaceChildren(); var head = node('div', undefined, 'pool-detail-head'); head.append(node('strong', '原题 #' + item.id), badge(COMPLETENESS[item.completeness] || item.completeness, item.completeness === 'complete' ? 'green' : 'orange'), badge(STATUS[item.status] || item.status)); box.appendChild(head);
      math(box, item.question, 'pool-detail-question');
      if (item.reason) box.appendChild(node('p', item.reason, 'pool-check'));
      if (item.prepare_error) box.appendChild(node('p', '解析失败：' + item.prepare_error + '\n加入选择队列后可单独重试。', 'pool-check conflict'));
      if (item.completeness === 'failed') {
        var retrySource = (item.occurrences || []).find(function (origin) { return (state.meta.sources || []).some(function (source) { return Number(source.id) === Number(origin.source_id) && source.has_file; }); });
        if (retrySource) box.appendChild(button('重试此题的提取', async function () {
          if (state.busy) return; state.busy = true; updateBusy();
          try { var job = await api('/question-pool/sources/' + retrySource.source_id + '/retry', 'POST', {item_ids: [item.id]}); await trackJob(job); }
          catch (error) { notice(error.message, true); } finally { state.busy = false; updateBusy(); }
        }));
      }
      var actions = node('div', undefined, 'pool-detail-actions');
      if (item.status !== 'imported') { var select = button(state.selected.has(item.id) ? '移出选择队列' : '加入选择队列', function () { toggleSelection(item.id); }); select.id = 'poolSelectDetail'; actions.appendChild(select); actions.appendChild(button('修正题干 / 分类', function () { if (box.querySelector('.pool-editor')) return; if (!editorNavigation()) return; var assignment = box.querySelector('.pool-assignment'); if (assignment) assignment.hidden = true; renderEditor(box, item); })); }
      else if (item.formal_question_id) { var link = node('a', '已入库 #' + item.formal_question_id, 'pool-btn'); link.href = 'history.html?question_id=' + encodeURIComponent(item.formal_question_id); actions.appendChild(link); }
      box.appendChild(actions); box.append(fold('原答案', item.answer), fold('原解析', item.solution)); renderPrepared(box, item); renderProvenance(box, item);
      if (item.status !== 'imported') renderAssignment(box, item);
      var index = state.items.findIndex(function (entry) { return Number(entry.id) === Number(item.id); });
      el('poolPreviousItem').disabled = index < 0 || state.page === 1 && index === 0; el('poolNextItem').disabled = index < 0 || index === state.items.length - 1 && state.page * state.pageSize >= state.total;
    }
    async function moveItem(direction) {
      if (!editorNavigation()) return;
      var index = state.items.findIndex(function (item) { return Number(item.id) === state.activeId; });
      if (index < 0) { if (state.items.length) return selectItem(state.items[0].id); return; }
      var next = index + direction;
      if (next >= 0 && next < state.items.length) return selectItem(state.items[next].id);
      var page = state.page + direction, maxPage = Math.max(1, Math.ceil(state.total / state.pageSize));
      if (page < 1 || page > maxPage) return; state.page = page; state.activeId = null; await loadItems();
      if (state.items.length) await selectItem(state.items[direction > 0 ? 0 : state.items.length - 1].id);
    }
    function showDialog(id) { var dialog = el(id); if (dialog.showModal) { if (!dialog.open) dialog.showModal(); } else { dialog.hidden = false; dialog.open = true; } }
    function closeDialog(id) { var dialog = el(id); if (dialog.close) dialog.close(); else { dialog.hidden = true; dialog.open = false; } }
    function renderSources() {
      var box = el('poolSourcesList'); box.replaceChildren();
      (state.meta.sources || []).forEach(function (source) {
        var card = node('section', undefined, 'pool-source-card'); card.appendChild(node('h3', source.name));
        var stats = source.stats || {}, parts = [];
        if (source.expected_count !== undefined && source.expected_count !== null) parts.push('应处理 ' + source.expected_count);
        [['expected', '应处理'], ['expected_count', '应处理'], ['total', '已处理'], ['unique', '独立题'], ['processed', '已处理'], ['collected', '已采集'], ['imported', '已采集'], ['duplicates', '重复'], ['deferred_graphic', '暂缓图形'], ['needs_review', '待修正'], ['failed', '失败']].forEach(function (pair) { if (stats[pair[0]] !== undefined) parts.push(pair[1] + ' ' + stats[pair[0]]); });
        card.appendChild(node('p', parts.join(' · ') || '尚未处理', 'pool-source-stats'));
        if (source.detail || source.error) card.appendChild(node('p', source.detail || source.error, 'pool-muted'));
        if (source.import_status && source.import_status !== 'ready') card.appendChild(node('p', '导入状态：' + ({queued: '等待处理', running: '处理中', error: '提取失败', interrupted: '提取已中断', done: '完成'}[source.import_status] || source.import_status), 'pool-source-stats'));
        if (source.import_error) card.appendChild(node('p', source.import_error, 'pool-preview-error'));
        var form = node('form', undefined, 'pool-source-edit'), name = node('input'), license = node('input'), allowed = node('input'); name.value = source.name || ''; name.setAttribute('aria-label', '题源名称'); license.value = source.license || ''; license.placeholder = '许可说明 / 使用范围'; license.setAttribute('aria-label', '许可说明'); allowed.type = 'checkbox'; allowed.checked = !!source.publication_allowed;
        var label = node('label'); label.append(allowed, node('span', '允许将选中题目公开为共享母题或变式（原文件仍仅主人可见）'));
        form.append(name, license, label); var save = button('保存题源信息', function () {}); save.type = 'submit'; form.appendChild(save);
        if (source.has_file) {
          var link = node('a', '查看原文件 ↗', 'pool-text-btn'); link.href = '/question-pool/sources/' + encodeURIComponent(source.id) + '/file'; link.target = '_blank'; link.rel = 'noopener noreferrer'; form.appendChild(link);
          form.appendChild(button('重新提取 / 重试失败项', async function () { if (state.busy) return; state.busy = true; updateBusy(); try { var job = await api('/question-pool/sources/' + source.id + '/retry', 'POST', {}); closeDialog('poolSourcesDialog'); await trackJob(job); } catch (error) { notice(error.message, true); } finally { state.busy = false; updateBusy(); } }));
        }
        form.addEventListener('submit', async function (event) { event.preventDefault(); save.disabled = true; try { await api('/question-pool/sources/' + source.id, 'PATCH', {name: name.value.trim(), license: license.value.trim(), publication_allowed: allowed.checked}); invalidatePreview(); await loadMeta(); notice('题源信息已更新。'); } catch (error) { notice(error.message, true); } finally { save.disabled = false; } });
        card.appendChild(form); box.appendChild(card);
      });
      if (!box.children.length) box.appendChild(node('p', '还没有题源。上传文件，或由采集脚本接入公开题库。', 'pool-empty'));
    }
    async function trackJob(job) {
      var id = job.job_id || job.id; if (!id) throw new Error('服务器未确认任务，请重试。');
      state.pendingJob = id; persist(); el('poolJobProgress').hidden = false;
      function progress(current) { var labels = {queued: '等待执行', running: '进行中', done: '完成', error: '失败', interrupted: '任务已中断'}; el('poolJobProgress').textContent = '后台任务 · ' + (labels[current.status] || current.status || '已提交') + (current.detail || current.stage ? ' · ' + (current.detail || current.stage) : '') + (current.progress ? ' · ' + current.progress + '%' : ''); }
      progress(job);
      try {
        var result;
        if (window.StudyJobs) { var current = await window.StudyJobs.get(id); result = await window.StudyJobs.wait(current, progress); }
        else { var currentJob = job; while (!['done', 'error', 'interrupted'].includes(currentJob.status)) { await new Promise(function (resolve) { setTimeout(resolve, 2200); }); currentJob = await api('/jobs/' + encodeURIComponent(id)); progress(currentJob); } if (currentJob.status !== 'done') throw new Error(currentJob.error && currentJob.error.detail || currentJob.error || '后台任务未完成'); result = currentJob.result; }
        state.pendingJob = null; persist(); await refresh();
        var failed = result && Number(result.failed) || 0;
        notice(failed ? '本次 ' + (Number(result.ready) || 0) + ' 题已准备，' + failed + ' 题失败。失败项可逐题查看原因并单独重试。' : '后台处理完成。请逐题核对原题与 AI 解析，再预览入库。', !!failed);
      } catch (error) { if (error.job && ['error', 'interrupted'].includes(error.job.status)) { state.pendingJob = null; persist(); } await refresh(); throw error; }
    }
    async function prepare() {
      if (!editorNavigation() || !state.selected.size || state.busy) return;
      if (state.selected.size > 200) return notice('每批最多处理 200 道题，请缩小本次选择队列。', true);
      state.busy = true; invalidatePreview(); updateBusy();
      try { var job = await api('/question-pool/prepare', 'POST', {item_ids: Array.from(state.selected), teacher: el('poolTeacher').value}); notice('已提交选中题的解析任务，切换页面后仍会继续。'); await trackJob(job); }
      catch (error) { notice(error.message, true); } finally { state.busy = false; updateBusy(); }
    }
    function renderPreview() {
      var box = el('poolPreviewItems'); box.replaceChildren();
      state.preview.forEach(function (item) {
        var card = node('section', undefined, 'pool-preview-item'); card.appendChild(node('h3', '#' + item.item_id + ' · ' + (ROLES[item.role] || item.role || '普通题库题') + (item.pattern_name ? ' · ' + item.pattern_name : ''))); math(card, item.question);
        var original = state.cache.get(Number(item.item_id));
        if (original && (original.prepared || item.existing_answer !== undefined)) {
          var compare = node('div', undefined, 'pool-answer-grid'), answers = [['原答案', original.answer], ['AI 答案', finalAnswer(original.prepared)]];
          if (item.existing_answer !== undefined && item.existing_answer !== null) answers.push(['正式题 #' + item.question_id + ' 的已有答案', typeof item.existing_answer === 'object' ? finalAnswer(item.existing_answer) : item.existing_answer]);
          answers.forEach(function (pair) { var cell = node('div', undefined, 'pool-answer-cell'); cell.appendChild(node('h3', pair[0])); math(cell, pair[1] || '未提供'); compare.appendChild(cell); }); card.appendChild(compare);
        }
        renderCheck(card, item.answer_check);
        if (item.existing_answer_check) renderCheck(card, item.existing_answer_check, true);
        var errors = blockingErrors(item); if (errors.length) card.appendChild(node('p', errors.join('\n'), 'pool-preview-error'));
        if (item.can_commit && !errors.length && needsConfirmation(item)) {
          var label = node('label', undefined, 'pool-confirm-conflict'), check = node('input'); check.type = 'checkbox'; check.checked = state.confirmations.has(Number(item.item_id)); check.setAttribute('aria-label', '确认原题 ' + item.item_id + ' 的答案');
          check.addEventListener('change', function () { if (check.checked) state.confirmations.add(Number(item.item_id)); else state.confirmations.delete(Number(item.item_id)); updatePreviewSummary(); });
          label.append(check, node('span', item.action === 'reuse' ? '我已核对原题、AI 解析与已有正式答案，确认沿用正式答案并补充出处及关联。' : item.answer_check && item.answer_check.status === 'conflict' ? '我已核对原答案与 AI 解析，确认按当前 AI 解析入库。' : '我已人工核对题干与 AI 解析，确认可以入库。')); card.appendChild(label);
        }
        if (item.action) card.appendChild(node('p', item.action === 'already_imported' ? '此前已入库，重复提交不会新增题目。' : item.action === 'reuse' ? '沿用正式题 #' + item.question_id + ' 的已有答案与解析，补充本次出处及套路关联。' : '新建正式题目并保存当前解析与出处。', 'pool-muted'));
        box.appendChild(card);
      }); updatePreviewSummary();
    }
    function updatePreviewSummary() { var eligible = eligiblePreview(state.preview, state.confirmations); el('poolPreviewSummary').textContent = '共 ' + state.preview.length + ' 题 · 本次可提交 ' + eligible.length + ' 题'; el('poolCommit').textContent = '确认入库 ' + eligible.length + ' 题'; updateBusy(); }
    async function preview() {
      if (!editorNavigation() || !state.selected.size || state.busy) return;
      if (state.selected.size > 200) return notice('每批最多处理 200 道题，请缩小本次选择队列。', true);
      state.busy = true; updateBusy();
      try {
        var ids = Array.from(state.selected), data = await api('/question-pool/preview', 'POST', {item_ids: ids});
        for (var start = 0; start < ids.length; start += 12) {
          await Promise.all(ids.slice(start, start + 12).map(async function (id) { state.cache.set(id, await api('/question-pool/items/' + id)); }));
        }
        state.preview = data.items || []; state.confirmations.clear(); renderPreview(); showDialog('poolPreviewDialog');
      } catch (error) { notice(error.message, true); } finally { state.busy = false; updateBusy(); }
    }
    async function commit() {
      var entries = eligiblePreview(state.preview, state.confirmations); if (!entries.length || state.busy) return;
      state.busy = true; updateBusy();
      var ids = entries.map(function (entry) { return Number(entry.item_id); }), confirmed = Array.from(state.confirmations).filter(function (id) { return ids.includes(id); }).sort(function (a, b) { return a - b; });
      var signature = ids.slice().sort(function (a, b) { return a - b; }).join(',') + '|confirmed:' + confirmed.join(',');
      if (!state.commitIntent || state.commitIntent.signature !== signature) state.commitIntent = {signature: signature, request_id: window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : 'pool-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)};
      persist();
      try {
        var data = await api('/question-pool/commit', 'POST', {item_ids: ids, request_id: state.commitIntent.request_id, confirmed_conflicts: confirmed});
        var done = (data.items || []).filter(function (entry) { return entry.status === 'imported'; }), errors = (data.items || []).filter(function (entry) { return entry.status !== 'imported'; });
        done.forEach(function (entry) { state.selected.delete(Number(entry.item_id)); }); state.preview = []; state.commitIntent = null; state.confirmations.clear(); persist(); closeDialog('poolPreviewDialog'); await refresh();
        notice('已入库 ' + done.length + ' 题。' + (errors.length ? '\n' + errors.map(function (entry) { return '#' + entry.item_id + '：' + (entry.error || '未完成'); }).join('\n') : '出处已保留，可在题库与母题看板查看。'), !!errors.length);
      } catch (error) { notice(error.message + '；可重试本次提交，已成功的题不会重复入库。', true); }
      finally { state.busy = false; updateBusy(); }
    }
    async function upload(event) {
      event.preventDefault(); if (state.busy) return; var file = el('poolUploadFile').files[0]; if (!file) return notice('请选择题源文件。', true);
      var form = new FormData(); form.append('file', file); form.append('source_name', el('poolUploadName').value.trim() || file.name); var ocr = el('poolUploadOcr'); form.append('ocr', String(!ocr || ocr.checked));
      state.busy = true; updateBusy();
      try { notice('正在上传题源文件，请等待服务器确认。'); var job = await api('/question-pool/uploads', 'POST', form); closeDialog('poolSourcesDialog'); el('poolUploadFile').value = ''; await trackJob(job); }
      catch (error) { notice(error.message, true); } finally { state.busy = false; updateBusy(); }
    }
    async function refresh() { if (!editorNavigation()) return; await loadMeta(); await loadItems(); }
    async function resetFilters() { if (!editorNavigation()) return; state.filters = Object.assign({}, DEFAULT_FILTERS); state.page = 1; state.activeId = null; syncFilters(); persist(); await loadItems(); }
    function listen(id, event, handler) { el(id).addEventListener(event, function (e) { Promise.resolve(handler(e)).catch(function (error) { notice(error.message, true); }); }); }
    function bind() {
      listen('poolFilters', 'submit', async function (event) { event.preventDefault(); if (!editorNavigation()) return; Object.keys(FILTER_IDS).forEach(function (key) { state.filters[key] = el(FILTER_IDS[key]).value.trim(); }); state.page = 1; state.activeId = null; persist(); await loadItems(); });
      listen('poolPageSize', 'change', async function () { if (!editorNavigation()) return; state.pageSize = Number(el('poolPageSize').value) === 80 ? 80 : 40; state.page = 1; state.activeId = null; persist(); await loadItems(); });
      listen('poolPrev', 'click', async function () { if (!editorNavigation()) return; if (state.page > 1) { state.page--; state.activeId = null; await loadItems(); } });
      listen('poolNext', 'click', async function () { if (!editorNavigation()) return; if (state.page * state.pageSize < state.total) { state.page++; state.activeId = null; await loadItems(); } });
      listen('poolRefresh', 'click', refresh); listen('poolReset', 'click', resetFilters); listen('poolPreviousItem', 'click', function () { return moveItem(-1); }); listen('poolNextItem', 'click', function () { return moveItem(1); });
      listen('poolSelectPage', 'change', function () { var selected = el('poolSelectPage').checked; state.items.forEach(function (item) { if (item.status !== 'imported') { if (selected) state.selected.add(Number(item.id)); else state.selected.delete(Number(item.id)); } }); invalidatePreview(); renderQueue(); renderSelectionState(); });
      listen('poolClearSelection', 'click', function () { state.selected.clear(); invalidatePreview(); renderQueue(); renderSelectionState(); }); listen('poolTeacher', 'change', persist);
      listen('poolPrepare', 'click', prepare); listen('poolPreview', 'click', preview); listen('poolCommit', 'click', commit); listen('poolSourcesButton', 'click', function () { renderSources(); showDialog('poolSourcesDialog'); }); listen('poolUploadForm', 'submit', upload);
      doc.querySelectorAll('[data-close-dialog]').forEach(function (entry) { entry.addEventListener('click', function () { closeDialog(entry.dataset.closeDialog); }); });
      doc.addEventListener('keydown', function (event) {
        if (!auth || !auth.isOwner() || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
        if (/^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(event.target && event.target.tagName) || event.target && event.target.isContentEditable || el('poolSourcesDialog').open || el('poolPreviewDialog').open) return;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); moveItem(event.key === 'ArrowLeft' ? -1 : 1).catch(function (error) { notice(error.message, true); }); }
        if ((event.key === 's' || event.key === 'S') && state.activeId) { var item = state.cache.get(state.activeId); if (!item || item.status !== 'imported') { event.preventDefault(); toggleSelection(state.activeId); } }
      });
      if (window.addEventListener) window.addEventListener('beforeunload', function (event) { if (state.editorDirty || state.busy && !state.pendingJob) { event.preventDefault(); event.returnValue = ''; } });
    }
    async function init() {
      if (auth) await auth.ready;
      if (!auth || !auth.isOwner()) { el('poolWorkspace').hidden = true; el('poolAccess').hidden = false; el('poolAccess').textContent = '原题池由主人账号维护。你可以在母题看板查看已确认的共享母题。'; el('poolSourcesButton').hidden = true; el('poolRefresh').hidden = true; return; }
      saved = restoreState(storage);
      var routeJob = window.location && new URLSearchParams(window.location.search || '').get('job');
      Object.assign(state, {filters: saved.filters, page: saved.page, pageSize: saved.pageSize, activeId: saved.activeId, selected: new Set(saved.selected), pendingJob: routeJob || saved.pendingJob, commitIntent: saved.commitIntent});
      el('poolTeacher').value = saved.teacher; syncFilters(); bind(); el('poolWorkspace').hidden = false; renderQueue();
      try { await refresh(); if (state.pendingJob) { state.busy = true; updateBusy(); try { await trackJob(await api('/jobs/' + encodeURIComponent(state.pendingJob))); } finally { state.busy = false; updateBusy(); } } }
      catch (error) { if (error.status === 404 && state.pendingJob) { state.pendingJob = null; persist(); } notice(error.message, true); }
    }
    return {init: init, state: state, loadItems: loadItems, refresh: refresh, selectItem: selectItem, toggleSelection: toggleSelection, prepare: prepare, preview: preview, commit: commit, moveItem: moveItem, upload: upload};
  }
  window.QuestionPool = {createController: createController, makeQuery: makeQuery, restoreState: restoreState, safeUrl: safeUrl, finalAnswer: finalAnswer, sourceLocation: sourceLocation, eligiblePreview: eligiblePreview, storageKey: STORAGE_KEY};
  document.addEventListener('DOMContentLoaded', function () { window.QuestionPool.controller = createController(); window.QuestionPool.controller.init(); });
})();
