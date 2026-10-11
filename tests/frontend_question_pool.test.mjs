// Intake remains private until explicit preview/confirmation. No server or AI calls.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../frontend/question-pool.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../frontend/question-pool.html', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
async function settle() { for (let i = 0; i < 8; i++) await tick(); }
const plain = value => JSON.parse(JSON.stringify(value));

class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.value = ''; this._text = ''; this.className = ''; this.hidden = false; this.checked = false; this.disabled = false; this.files = []; this.classList = { toggle: (cls, value) => { const current = new Set(this.className.split(' ').filter(Boolean)); if (value === undefined ? !current.has(cls) : value) current.add(cls); else current.delete(cls); this.className = [...current].join(' '); } }; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  dispatch(name, extra = {}) { const event = { target: this, preventDefault() {}, stopPropagation() {}, ...extra }; return Promise.all((this.listeners[name] || []).map(callback => callback(event))); }
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  querySelectorAll(selector) { return this.descendants().filter(el => matches(el, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  scrollIntoView() {}
}
function matches(el, selector) {
  if (selector.includes(',')) return selector.split(',').some(part => matches(el, part.trim()));
  if (selector.startsWith('.')) return el.className.split(' ').includes(selector.slice(1));
  if (selector === '[data-pool-select]') return el.dataset.poolSelect !== undefined;
  if (selector === '[data-close-dialog]') return el.dataset.closeDialog !== undefined;
  return el.tagName.toLowerCase() === selector;
}
function documentMock() {
  const nodes = new Map();
  for (const [, tag, id] of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"/g)) nodes.set(id, new Element(tag));
  const all = () => [...nodes.values()].flatMap(el => [el, ...el.descendants()]);
  return { nodes, listeners: {}, createElement: tag => new Element(tag),
    getElementById: id => nodes.get(id) || all().find(el => el.id === id) || null,
    querySelectorAll: selector => [...new Set(all().filter(el => matches(el, selector)))],
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); },
  };
}
function storageMock(initial = {}) { const values = new Map(Object.entries(initial)); return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, String(value)), values }; }
function item(id, extra = {}) {
  return { id, question: '已知集合 $A=\\{1,2\\}$，求 $A\\cap\\{2,3\\}$。' + id, answer: '$\\{2\\}$', solution: '取公共元素。', categories: ['集合'], question_type: '填空题', completeness: 'complete', status: 'reviewed', year: '2024', version: 1, assignment: { role: 'question' }, prepared: null, answer_check: {status: 'unverified', detail: '尚未生成'}, occurrences: [{source_id: 1, source_name: '题源 A', source_key: 'paper:' + id, question_no: id, page_start: 2, page_end: 3, url: 'https://example.org/paper', license: '待核验', publication_allowed: false}], ...extra };
}
function apiMock() {
  const items = new Map(Array.from({length: 85}, (_, index) => [index + 1, item(index + 1)]));
  items.set(86, item(86, {completeness: 'deferred_graphic', question: '如图所示，求面积。'}));
  const calls = [], sources = [{id: 1, name: '题源 A', kind: 'upload', has_file: true, license: '待核验', publication_allowed: false, stats: {total: 86, unique: 86, collected: 85, duplicates: 0, deferred_graphic: 1, failed: 0}}];
  let loseCommit = false;
  async function fetch(path, opts = {}) {
    const method = opts.method || 'GET', body = opts.body && typeof opts.body === 'string' ? JSON.parse(opts.body) : opts.body;
    calls.push({path, method, body}); const url = new URL(path, 'http://localhost'); let value;
    if (path === '/question-pool/meta') value = {categories: ['集合', '立体几何'], question_types: ['选择题', '填空题', '大题', '未知'], sources, stats: {total: 86, complete: 85, needs_review: 0, imported: 0}, coverage: [{category: '集合', candidates: 85, patterns: 7, mothers: 5, gaps: [{pattern_id: 1, name: '互异性排除参数', mother_missing: true, missing_roles: ['variant1', 'variant3']}]}]};
    else if (path === '/patterns') value = [{id: 1, name: '交并补', category: '集合', mother_id: 100, variant_ids: []}];
    else if (url.pathname === '/question-pool/items') {
      const filters = url.searchParams;
      let rows = [...items.values()];
      if (filters.get('completeness') === 'text_only') rows = rows.filter(row => ['complete', 'needs_review'].includes(row.completeness));
      else if (filters.get('completeness')) rows = rows.filter(row => row.completeness === filters.get('completeness'));
      if (filters.get('keyword')) rows = rows.filter(row => row.question.includes(filters.get('keyword')));
      const page = Number(filters.get('page')), size = Number(filters.get('page_size'));
      value = {data: rows.slice((page - 1) * size, page * size).map(row => ({...row, prepared: null})), total: rows.length, page, page_size: size};
    } else if (/^\/question-pool\/items\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop());
      if (method === 'PATCH') { Object.assign(items.get(id), body); delete items.get(id).expected_version; }
      value = items.get(id);
    } else if (path === '/question-pool/prepare') {
      body.item_ids.forEach(id => { const row = items.get(id); row.status = 'ready'; row.answer_check = {status: 'match', detail: '一致'}; row.prepared = {final_answer: row.answer, chunk_results: [{steps: [{title: '求交集', standard_writing: '取公共元素 $2$。', detailed_writing: '逐项比较。'}], final_answer: row.answer}]}; });
      value = {job_id: 'prepare-job', status: 'done', result: {ready: body.item_ids.length}};
    } else if (path === '/question-pool/preview') {
      value = {items: body.item_ids.map(id => ({item_id: id, question: items.get(id).question, role: items.get(id).assignment.role, can_commit: true, blocking_errors: [], needs_confirmation: ['conflict', 'unverified'].includes(items.get(id).answer_check.status), answer_check: items.get(id).answer_check, action: items.get(id).existing_answer === undefined ? 'create' : 'reuse', question_id: items.get(id).existing_answer === undefined ? null : 999, existing_answer: items.get(id).existing_answer, existing_answer_check: items.get(id).existing_answer_check})), can_commit: true};
    } else if (path === '/question-pool/commit') {
      if (loseCommit) { loseCommit = false; throw new Error('网络中断'); }
      value = {items: body.item_ids.map(id => { Object.assign(items.get(id), {status: 'imported', formal_question_id: id + 1000}); return {item_id: id, status: 'imported', question_id: id + 1000}; })};
    } else if (/^\/question-pool\/sources\/\d+$/.test(path) && method === 'PATCH') { Object.assign(sources[0], body); value = sources[0]; }
    else if (path === '/question-pool/uploads' || /^\/question-pool\/sources\/\d+\/retry$/.test(path)) value = {job_id: 'import-job', status: 'done', result: {}};
    else if (path === '/question-pool/collect') value = {job_id: 'collect-job', kind: 'pool_collect', status: 'queued'};
    else if (path === '/question-pool/collection') value = {stage: 'idle'};
    else if (path.startsWith('/jobs/')) value = {job_id: path.split('/').pop(), status: 'done', result: {}};
    else throw new Error('Unexpected API: ' + path);
    return {ok: true, status: 200, json: async () => structuredClone(value)};
  }
  return {fetch, calls, items, sources, loseNextCommit() { loseCommit = true; }};
}
function runtime({owner = true, storage = storageMock(), server = apiMock()} = {}) {
  const document = documentMock(), auth = {ready: Promise.resolve(), isOwner: () => owner}, context = vm.createContext({document, URL, URLSearchParams, FormData, setTimeout, console, Date, Math, Map, Set});
  context.window = {StudyAuth: auth, innerWidth: 1200, fetch: server.fetch, addEventListener() {}, crypto: {randomUUID: () => 'request-uuid-' + Math.random()}, StudyJobs: {get: async id => ({job_id: id, status: 'done', result: {}}), wait: async (job, progress) => { if (progress) progress(job); return job.result; }}};
  vm.runInContext(source, context);
  const api = context.window.QuestionPool, controller = api.createController({document, storage, auth, fetch: server.fetch});
  return {api, controller, document, storage, server, context, field: id => document.getElementById(id)};
}

// Default excludes deferred graphics, and explicitly choosing all must survive the query.
const pure = runtime();
assert.equal(new URLSearchParams(pure.api.makeQuery({completeness: 'text_only'}, 1, 40)).get('completeness'), 'text_only');
assert.equal(new URLSearchParams(pure.api.makeQuery({completeness: ''}, 1, 40)).has('completeness'), true);
assert.equal(new URLSearchParams(pure.api.makeQuery({keyword: '$A&B$', completeness: ''}, 2, 80)).get('keyword'), '$A&B$');
assert.equal(pure.api.safeUrl('javascript:alert(1)'), null);
assert.equal(pure.api.safeUrl('data:text/html,<script>alert(1)</script>'), null);
assert.equal(pure.api.safeUrl('https://example.org/a?b=1'), 'https://example.org/a?b=1');
assert.equal(pure.api.sourceLocation({page_start: 3, page_end: 4, question_no: 7}), '第 3–4 页 · 第 7 题');

// Non-owners never load private source text or expose intake controls.
const denied = runtime({owner: false});
await denied.controller.init();
assert.equal(denied.server.calls.length, 0);
assert.equal(denied.field('poolWorkspace').hidden, true);
assert.match(denied.field('poolAccess').textContent, /主人/);

// Collection submits a background intake job with 20 OCR slots and no solver.
const collection = runtime();
await collection.controller.init();
collection.field('poolCollectYears').value = '2026，2025,2026';
collection.field('poolCollectTopics').checked = true;
collection.field('poolCollectOcr').checked = true;
collection.context.window.StudyJobs.get = async id => ({job_id: id, kind: 'pool_collect', status: 'done', result: {
  stage: 'done', message: '采集完成', downloaded: 2, question_records: 38, added_occurrences: 19,
  verified_papers: 1, unverified_papers: 1, completed_pages: 8, cache_page_hits: 7, failed_pages: 1,
  resources: [], failures: [{title: '<不安全来源>', url: 'javascript:alert(1)', error: '需手动获取'}],
  conversion_results: [{title: '待核对卷', url: 'https://example.org/paper', valid: false}]
}});
await collection.controller.collect({preventDefault() {}});
const collectionCall = collection.server.calls.find(call => call.path === '/question-pool/collect');
assert.deepEqual(collectionCall.body, {years: [2026, 2025], topics: true, ocr: true, concurrency: 20});
assert.match(collection.field('poolCollectionReport').textContent, /通过整卷核验 1 份.*缓存命中 7.*失败页 1/);
assert.match(collection.field('poolCollectionReport').textContent, /待核对卷.*尚未通过整卷/);
assert.equal(collection.field('poolCollectionReport').querySelectorAll('a').some(link => link.href.startsWith('javascript:')), false);
assert.equal(collection.server.calls.some(call => /prepare|commit/.test(call.path)), false);
assert.equal(collection.controller.state.pendingJob, null);
collection.field('poolCollectYears').value = '2015';
await collection.controller.collect({preventDefault() {}});
assert.equal(collection.server.calls.filter(call => call.path === '/question-pool/collect').length, 1);
assert.match(collection.field('poolNotice').textContent, /2016/);

// Server pagination covers every text candidate without loading the whole corpus.
const workbench = runtime();
await workbench.controller.init();
assert.equal(workbench.controller.state.items.length, 40);
assert.equal(workbench.controller.state.total, 85);
assert.match(workbench.field('poolCoverage').textContent, /候选 85.*套路 7.*母题 5/);
assert.match(workbench.field('poolCoverage').textContent, /互异性排除参数缺母题.*缺变式 1.*缺变式 3/);
assert.equal(workbench.field('poolCoverage').textContent.includes('[object Object]'), false);
assert.equal(workbench.controller.state.activeId, 1, workbench.field('poolNotice').textContent);
workbench.controller.toggleSelection(2, true);
await workbench.field('poolNext').dispatch('click'); await settle();
assert.equal(workbench.controller.state.page, 2);
assert.equal(workbench.controller.state.items[0].id, 41);
workbench.controller.toggleSelection(41, true);
assert.deepEqual(plain([...workbench.controller.state.selected]), [2, 41]);
await workbench.field('poolNext').dispatch('click'); await settle();
assert.deepEqual(plain(workbench.controller.state.items.map(row => row.id)), [81, 82, 83, 84, 85]);
assert.equal(workbench.field('poolNext').disabled, true);

// Browser refresh restores selection, filters and focus; it does not start an AI task.
const restored = runtime({storage: workbench.storage, server: workbench.server});
await restored.controller.init();
assert.equal(restored.controller.state.page, 3);
assert.equal(restored.controller.state.activeId, 81);
assert.deepEqual(plain([...restored.controller.state.selected]), [2, 41]);
assert.equal(restored.server.calls.filter(call => call.path === '/question-pool/prepare').length, 0);

// Only the selected IDs reach AI; steps in the actual solver schema are visible.
await restored.controller.prepare();
const preparation = restored.server.calls.find(call => call.path === '/question-pool/prepare');
assert.deepEqual(preparation.body.item_ids, [2, 41]);
assert.equal(preparation.body.teacher, 'liangliang');
assert.equal(restored.server.calls.filter(call => call.path === '/question-pool/commit').length, 0);
await restored.controller.selectItem(2);
assert.match(restored.field('poolDetail').textContent, /求交集/);
assert.match(restored.field('poolDetail').textContent, /逐项比较/);
assert.equal(JSON.parse(restored.storage.getItem(restored.api.storageKey)).pendingJob, null);

// Text/TeX use text nodes and unsafe source links never become anchors.
restored.server.items.get(2).question = '<img src=x onerror=alert(1)> $A$';
restored.server.items.get(2).occurrences[0].url = 'javascript:alert(1)';
await restored.controller.selectItem(2);
assert.match(restored.field('poolDetail').textContent, /<img src=x onerror=alert\(1\)>/);
assert.equal(restored.field('poolDetail').querySelectorAll('img').length, 0);
assert.equal(restored.field('poolDetail').querySelectorAll('a').filter(link => link.href && link.href.startsWith('javascript:')).length, 0);
assert.equal(restored.field('poolDetail').querySelectorAll('a').some(link => link.href.includes('/sources/1/file#page=2')), true);

// Dirty text edits cannot be silently lost through keyboard or pointer navigation.
const editButton = restored.field('poolDetail').querySelectorAll('button').find(button => button.textContent === '修正题干 / 分类');
await editButton.dispatch('click');
const editor = restored.field('poolDetail').querySelector('.pool-editor');
assert.ok(editor);
await editor.dispatch('input');
await restored.controller.selectItem(41);
assert.equal(restored.controller.state.activeId, 2);
assert.match(restored.field('poolNotice').textContent, /尚未保存/);
const cancel = editor.querySelectorAll('button').find(button => button.textContent === '取消编辑');
await cancel.dispatch('click');
await restored.controller.selectItem(41);
assert.equal(restored.controller.state.activeId, 41);

// Save a reviewed role on a ready candidate without downgrading its prepared state.
const assignment = restored.field('poolDetail').querySelector('.pool-assignment');
const role = assignment.querySelectorAll('select')[0], pattern = assignment.querySelectorAll('select')[1];
role.value = 'mother'; pattern.value = '1';
await assignment.dispatch('change');
await assignment.dispatch('submit'); await settle();
const assignmentPatch = restored.server.calls.findLast(call => call.method === 'PATCH' && call.path === '/question-pool/items/41');
assert.equal(assignmentPatch.body.assignment.role, 'mother');
assert.equal(assignmentPatch.body.assignment.pattern_id, 1);
assert.equal(assignmentPatch.body.expected_version, 1);
assert.equal(assignmentPatch.body.status, undefined);
assert.equal(restored.server.calls.some(call => call.method === 'POST' && call.path === '/patterns/mother'), false);

// Public-use permission is an explicit source edit, and retry uses the kept private file.
const sourceCard = restored.field('poolSourcesList').querySelector('.pool-source-card');
const sourceForm = sourceCard.querySelector('form'), sourceInputs = sourceForm.querySelectorAll('input');
sourceInputs[2].checked = true;
await sourceForm.dispatch('submit'); await settle();
const sourcePatch = restored.server.calls.find(call => call.method === 'PATCH' && call.path === '/question-pool/sources/1');
assert.equal(sourcePatch.body.publication_allowed, true);
assert.equal(restored.server.sources[0].publication_allowed, true);
const retry = restored.field('poolSourcesList').querySelectorAll('button').find(button => /重试失败/.test(button.textContent));
await retry.dispatch('click'); await settle();
assert.ok(restored.server.calls.some(call => call.path === '/question-pool/sources/1/retry'));

// Match rows commit directly; conflict/unverified rows require individual confirmation.
restored.server.items.get(2).answer_check = {status: 'conflict', detail: '原答案不同'};
restored.server.items.get(41).answer_check = {status: 'unverified', detail: '等价性未确认'};
await restored.controller.preview();
assert.equal(restored.field('poolCommit').disabled, true);
assert.equal(restored.field('poolPreviewDialog').open, true);
const confirmations = restored.field('poolPreviewItems').querySelectorAll('input');
assert.equal(confirmations.length, 2);
confirmations[0].checked = true; await confirmations[0].dispatch('change');
assert.equal(restored.field('poolCommit').disabled, false);
assert.match(restored.field('poolCommit').textContent, /1 题/);
const beforeCommit = restored.server.calls.filter(call => call.path === '/question-pool/commit').length;
assert.equal(beforeCommit, 0);
restored.server.loseNextCommit();
await restored.controller.commit();
assert.match(restored.field('poolNotice').textContent, /可重试/);
const intent = JSON.parse(restored.storage.getItem(restored.api.storageKey)).commitIntent;
assert.ok(intent.request_id);
await restored.controller.commit();
const commits = restored.server.calls.filter(call => call.path === '/question-pool/commit');
assert.equal(commits.length, 2);
assert.equal(commits[0].body.request_id, commits[1].body.request_id, 'lost response retries reuse the same request ID');
assert.deepEqual(commits[1].body.item_ids, [2]);
assert.deepEqual(commits[1].body.confirmed_conflicts, [2]);
assert.deepEqual(plain([...restored.controller.state.selected]), [41]);
assert.equal(restored.server.items.get(2).status, 'imported');
assert.equal(restored.field('poolPreviewDialog').open, false);

// Switching to all explicitly reveals deferred items; uploaded extraction honors OCR.
restored.field('poolCompleteness').value = '';
await restored.field('poolFilters').dispatch('submit'); await settle();
assert.equal(restored.controller.state.total, 86);
const allQuery = restored.server.calls.findLast(call => call.path.includes('/question-pool/items?'));
assert.equal(new URL(allQuery.path, 'http://localhost').searchParams.has('completeness'), true);
assert.equal(new URL(allQuery.path, 'http://localhost').searchParams.get('completeness'), '');
restored.field('poolUploadFile').files = [new File(['{"question":"集合文字题"}'], 'book.json', {type: 'application/json'})];
restored.field('poolUploadName').value = '集合教辅';
restored.field('poolUploadOcr').checked = false;
await restored.controller.upload({preventDefault() {}});
const uploadCall = restored.server.calls.find(call => call.path === '/question-pool/uploads');
assert.equal(uploadCall.body.get('source_name'), '集合教辅');
assert.equal(uploadCall.body.get('ocr'), 'false');
assert.equal(uploadCall.body.get('file').name, 'book.json');

// A page refresh reconnects to a pending accepted job instead of submitting it again.
const pendingStorage = storageMock({[restored.api.storageKey]: JSON.stringify({selected: [41], pendingJob: 'accepted-job'})});
const pending = runtime({storage: pendingStorage});
await pending.controller.init();
assert.ok(pending.server.calls.some(call => call.path === '/jobs/accepted-job'));
assert.equal(pending.server.calls.filter(call => call.path === '/question-pool/prepare').length, 0);
assert.equal(JSON.parse(pendingStorage.getItem(pending.api.storageKey)).pendingJob, null);

// Reusing a formal question shows and confirms the answer that will actually be kept.
const reuse = runtime();
await reuse.controller.init();
Object.assign(reuse.server.items.get(1), {status: 'ready', prepared: {final_answer: '2', chunk_results: [{steps: [{title: '计算', standard_writing: '得 $2$'}]}]}, answer_check: {status: 'match'}, existing_answer: '3', existing_answer_check: {status: 'conflict', detail: '正式答案为 3'}});
reuse.controller.toggleSelection(1, true);
await reuse.controller.preview();
assert.match(reuse.field('poolPreviewItems').textContent, /正式题 #999 的已有答案3/);
assert.match(reuse.field('poolPreviewItems').textContent, /确认沿用正式答案/);
assert.equal(reuse.field('poolCommit').disabled, true);
const keepAnswer = reuse.field('poolPreviewItems').querySelector('input');
keepAnswer.checked = true; await keepAnswer.dispatch('change');
assert.equal(reuse.field('poolCommit').disabled, false);

// Slot conflicts are structural blockers even if an answer is explicitly confirmed.
const rows = [{item_id: 1, can_commit: false, blocking_errors: ['角色已占用'], needs_confirmation: true}, {item_id: 2, can_commit: true, blocking_errors: [], needs_confirmation: true}, {item_id: 3, can_commit: true, blocking_errors: [], answer_check: {status: 'match'}}];
assert.deepEqual(plain(pure.api.eligiblePreview(rows, new Set([1, 2])).map(row => row.item_id)), [2, 3]);

// Last-issued pagination request wins when an earlier network response arrives late.
const race = runtime();
await race.controller.init();
let release;
const originalFetch = race.server.fetch;
const slowServer = {fetch: async (path, opts) => {
  if (path.includes('/items?') && path.includes('page=2&')) await new Promise(resolve => { release = resolve; });
  return originalFetch(path, opts);
}};
const racing = race.api.createController({document: race.document, storage: storageMock(), auth: {ready: Promise.resolve(), isOwner: () => true}, fetch: slowServer.fetch});
await racing.init();
racing.state.page = 2;
const second = racing.loadItems(); await tick();
racing.state.page = 3;
await racing.loadItems();
release(); await second;
assert.equal(racing.state.items[0].id, 81);
assert.equal(racing.state.total, 85);

// Drafts entered during a slow detail request survive the eventual response.
const editingRace = runtime();
let releaseDetail;
const pendingDetailFetch = async (path, opts) => {
  if (path === '/question-pool/items/2') await new Promise(resolve => { releaseDetail = resolve; });
  return editingRace.server.fetch(path, opts);
};
const protectedController = editingRace.api.createController({document: editingRace.document, storage: storageMock(), auth: {ready: Promise.resolve(), isOwner: () => true}, fetch: pendingDetailFetch});
await protectedController.init();
const pendingDetail = protectedController.selectItem(2); await tick();
const activeAssignment = editingRace.field('poolDetail').querySelector('.pool-assignment');
activeAssignment.querySelector('select').value = 'mother';
await activeAssignment.dispatch('input');
releaseDetail(); await pendingDetail;
assert.equal(protectedController.state.activeId, 1);
assert.equal(protectedController.state.editorDirty, true);
assert.equal(editingRace.field('poolDetail').querySelector('.pool-assignment'), activeAssignment);
assert.match(editingRace.field('poolNotice').textContent, /尚未保存/);

console.log('Question pool checks passed: owner access, server pagination, persistence, selected-only AI, step rendering, safe text, edit protection including in-flight navigation, source permission/retry, answer confirmations, idempotent commits, stale response protection.');
