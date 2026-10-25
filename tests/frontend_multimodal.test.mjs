// Restore file recognition from a mocked ledger without a server or AI calls.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../frontend/multimodal.html', import.meta.url), 'utf8');
assert.match(html, /识题与默认解题老师/);
assert.match(html, /GLM-4\.6V-Flash/);
const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');
const tick = () => new Promise(resolve => setImmediate(resolve));

function page(storage = new Map(), ledger = {}) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { style: {}, textContent: '', innerHTML: '', value: '', files: [], getBoundingClientRect: () => ({ top: 0 }), scrollTop: 0, scrollTo() {}, querySelector: () => null, classList: { add() {}, remove() {} } });
    return elements.get(id);
  };
  const context = vm.createContext({
    console,
    window: { addEventListener() {} },
    location: { pathname: '/multimodal.html', search: '' }, URLSearchParams, URL, CustomEvent: class { constructor(type, options) { this.type=type;this.detail=options.detail; } },
    document: {
      documentElement: { style: {}, classList: { add() {} } }, addEventListener() {}, dispatchEvent() {},
      getElementById: element, querySelector: element, querySelectorAll: () => [],
    },
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key) },
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    StudyJobs: {
      uuid: () => 'new-group', read: () => null,
      get: async id => { if (!ledger[id]) throw new Error('task unavailable'); return ledger[id]; },
      wait: async job => { if (job.status === 'error') throw Object.assign(new Error(job.error.detail), { job }); return job.result; },
    },
    fetch: async () => ({ ok: true, json: async () => ({ jobs: Object.values(ledger) }) }),
  });
  vm.runInContext(source, context);
  // Rendering has separate browser coverage; keep the real persistence/merge logic.
  context.renderQuestionList = () => {};
  context.createSessionEl = () => {};
  return { context, storage, elements };
}

const ledger = {
  first: { job_id: 'first', kind: 'parse_file', status: 'done', result: { questions: [{ latex: 'x=1' }, { latex: 'x=1' }] } },
  second: { job_id: 'second', kind: 'parse_file', status: 'done', result: { questions: [{ latex: 'y=2' }] } },
  failed: { job_id: 'failed', kind: 'parse_file', status: 'error', error: { detail: 'unreadable image' } },
};
const firstPage = page(undefined, ledger);
const p = firstPage.context;
p.localStorage.setItem('mm_parse_current', 'batch');
p.writeParseGroup({ id: 'batch', teacher: 'taotao', files: [
  { name: 'one.pdf', job_id: 'first', status: 'running' },
  { name: 'two.pdf', job_id: 'second', status: 'queued' },
  { name: 'bad.png', job_id: 'failed', status: 'running' },
] });
p._questions = [{ latex: 'existing edited question' }];
p._sessions = { 0: { done: true, data: { answer: 'kept' } } };
await p.restoreMultiJobs();
await tick();
assert.deepEqual([...p._questions].map(question => question.latex), ['existing edited question', 'x=1', 'y=2']);
assert.equal(p._questions[1].recommended_teacher, 'taotao', 'parsed questions inherit the selected recognition teacher');
assert.equal(p._sessions[0].data.answer, 'kept', 'merging recognized files preserves solved state');
assert.match(firstPage.elements.get('mmParseStatus').textContent, /bad.png：识别失败 · unreadable image/);

// An edit must survive re-reading the same completed task and a page reload.
p._questions[1].latex = 'x=1, edited';
p.saveState();
p.restoreParseResult(ledger.first.result, ledger.first);
assert.equal(p._questions.length, 3);
assert.equal(p._questions[1].latex, 'x=1, edited');
const reloaded = page(firstPage.storage, ledger);
assert.equal(reloaded.context.restoreState(), true);
await reloaded.context.restoreMultiJobs();
await tick();
assert.deepEqual([...reloaded.context._questions].map(question => question.latex), ['existing edited question', 'x=1, edited', 'y=2']);
assert.equal(reloaded.context._sessions[0].data.answer, 'kept');
assert.match(reloaded.elements.get('mmParseStatus').textContent, /one.pdf：识别完成/);
assert.match(reloaded.elements.get('mmParseStatus').textContent, /two.pdf：识别完成/);
assert.match(reloaded.elements.get('mmParseStatus').textContent, /bad.png：识别失败/);

// Clearing a batch must prevent old completed files from reappearing on refresh.
reloaded.context.resetAll();
const cleared = page(firstPage.storage, ledger);
await cleared.context.restoreMultiJobs();
await tick();
assert.equal(cleared.context._questions.length, 0);

console.log('Multifile restoration checks passed (merge, deduplication, edited data, solved state, partial failure, reload, clear).');

// Fresh demo sessions start with the three current medium questions, without AI.
const catalog = { default_id: 'national-2025-q16', presets: [
  { id: 'national-2025-q16', label: '2025 全国一卷 · 第 16 题 · 数列与导数', question: 'sequence question', source: { paper: '全国一卷', year: 2025, question_number: 16, url: 'https://example.org/paper.pdf' } },
  { id: 'national-2023-q17', label: '2023 第 17 题 · 解三角形', question: 'triangle question', source: { paper: '全国Ⅰ卷', year: 2023, question_number: 17, url: 'https://example.org/triangle.pdf' } },
  { id: 'shanghai-2024-q18', label: '2024 上海卷 · 对数函数', question: 'logarithm question', source: { paper: '上海卷', year: 2024, question_number: 18, url: 'https://example.org/log.pdf' } },
] };
function demoPage(storage, ledger) {
  const result = page(storage, ledger);
  result.context.window.STUDY_DEMO = { session_id: 'a'.repeat(32) };
  result.context.window.StudyDemoPresets = { load: async () => catalog, idForQuestion: question => catalog.presets.find(preset => preset.question === String(question).trim())?.id || null };
  result.context.StudyJobs.submit = () => { throw new Error('initialization must not call AI'); };
  return result;
}
const fresh = demoPage();
assert.equal(await fresh.context.initializeDemoQuestions(), true);
assert.equal(fresh.context._questions.length, 3);
assert.equal(fresh.context._questions[fresh.context._selectedIdx].demo_preset_id, catalog.default_id);
assert.equal(fresh.context._questions[0].recommended_teacher, 'liangliang');
assert.equal(fresh.context.multiArgs(0).preset_id, catalog.default_id);
assert.match(fresh.context.demoSourceHtml(fresh.context._questions[0]), /查看原题出处/);
assert.match(fresh.context.demoSourceHtml(fresh.context._questions[0]), /https:\/\/example.org\/paper.pdf/);
fresh.context._questions[0].latex += ' user edit';
assert.equal(fresh.context.multiArgs(0).preset_id, undefined, 'edited text must never use a preset cache');
fresh.context.saveState();
assert.equal(await fresh.context.initializeDemoQuestions(), false);
assert.match(fresh.context._questions[0].latex, /user edit/);
const reloadDemo = demoPage(fresh.storage);
reloadDemo.context.restoreState();
assert.equal(await reloadDemo.context.initializeDemoQuestions(), false);
assert.match(reloadDemo.context._questions[0].latex, /user edit/);
const active = demoPage(undefined, { pending: { job_id: 'pending', kind: 'solve', status: 'running', created_at: Date.now()/1000, args: { client_page: 'multimodal', question: 'existing task' } } });
assert.equal(await active.context.initializeDemoQuestions(), false, 'background tasks prevent preset injection');
assert.equal(active.context._questions.length, 0);
const formal = page();
assert.equal(await formal.context.initializeDemoQuestions(), false);
assert.equal(formal.context._questions.length, 0, 'formal default behavior remains empty');
assert.equal(formal.context.timerText(0, 181), '已等待 181s');
assert.match(fresh.context.timerText(1, 299), /300 秒/);
assert.doesNotMatch(fresh.context.timerText(1, 299), /180|你做不过/);

// Rendering a returned prepared result always shows its true source and stays open in demo.
const rendered = demoPage();
rendered.context._questions = [{ ...fresh.context._questions[1] }];
rendered.context._sessions = { 0: {} };
rendered.context.renderDifficultyRadar = () => {};
rendered.context.getDifficultyDims = () => ({});
rendered.context.renderSessionResult(0, { source: 'prepared_cache', chunk_results: [], knowledge_points: [] });
assert.match(rendered.elements.get('session_body_0').innerHTML, /预先准备的示例解析/);
assert.match(rendered.elements.get('session_body_0').innerHTML, /data-demo-teach/);
assert.equal(rendered.context._sessions[0].collapsed, false);
console.log('Demo multimodal checks passed (default presets, source, no calls, edited drafts, existing jobs, formal isolation, timers, prepared source).');

const coach = demoPage(fresh.storage);
coach.context.restoreState();
coach.context.localStorage.setItem('_mm_coach_input', ' coach custom question ');
assert.equal(coach.context.consumeDemoCoachInput(), true);
assert.equal(coach.context._questions.length, 4);
assert.equal(coach.context._questions[0].latex, 'sequence question user edit');
assert.equal(coach.context._questions[3].latex, 'coach custom question');
assert.equal(coach.context._selectedIdx, 3);
assert.equal(coach.context.localStorage.getItem('_mm_coach_input'), null);
assert.equal(coach.context.multiArgs(3).preset_id, undefined);
assert.equal(coach.context.consumeDemoCoachInput(), false, 'consumed coach draft cannot be appended twice');
assert.equal(formal.context.consumeDemoCoachInput(), false);
console.log('Coach draft checks passed (append, preserve, select, remove, custom-only, no automatic AI).');

const inheritedTeacher = demoPage(new Map([['teacher', 'ji']]));
assert.equal(await inheritedTeacher.context.initializeDemoQuestions(), true);
assert.equal(inheritedTeacher.context._questions[0].recommended_teacher, 'ji', 'multimodal defaults inherit the teacher selected on other solving pages');

// Returning to pending solves restores card progress and ignores older results.
const recover = page(undefined, {
  old: { job_id: 'old', kind: 'solve', status: 'done', created_at: 1, args: { client_page: 'multimodal', question: 'same question' }, result: { answer: 'old' } },
  latest: { job_id: 'latest', kind: 'solve', status: 'running', progress: 35, detail: 'Verifier', created_at: 2, args: { client_page: 'multimodal', question: 'same question' } },
});
let finish;
const progress = [], results = [];
recover.context.StudyJobs.wait = (_job, update) => new Promise(resolve => { finish = resolve; update(_job); });
recover.context.renderProgress = (idx, pct, message) => progress.push({ idx, pct, message });
recover.context.renderSessionResult = (idx, result) => results.push({ idx, result });
await recover.context.restoreMultiJobs();
await tick();
assert.equal(recover.context._questions.length, 1);
assert.equal(recover.context._sessions[0].solving, true);
assert.equal(progress.at(-1).pct, 35);
assert.equal(results.length, 0, 'historical completed result cannot overwrite a newer pending task');
finish({ answer: 'new', saved_question_id: 101 });
await tick();
assert.equal(recover.context._sessions[0].solving, false);
assert.equal(recover.context._sessions[0].data.answer, 'new');
assert.equal(results.length, 1);

const batchRecover = page(undefined, {
  batch: { job_id: 'batch', kind: 'batch_solve', status: 'done', created_at: 3, args: { client_page: 'multimodal', questions: [{ question: 'first item' }, { question: 'second item' }] }, result: { items: [{ index: 0, status: 'done', result: { answer: 'kept success' } }, { index: 1, status: 'error', error: { detail: 'item failed' } }] } },
});
batchRecover.context.renderSessionResult = () => {};
await batchRecover.context.restoreMultiJobs();await tick();
assert.equal(batchRecover.context._questions.length, 2);
assert.equal(batchRecover.context._sessions[0].data.answer, 'kept success');
assert.equal(batchRecover.context._sessions[1].done, false);
assert.match(batchRecover.elements.get('session_body_1').innerHTML, /item failed/);
console.log('Solve restoration checks passed (pending progress, newest result ownership, accumulated state, batch partial errors).');
