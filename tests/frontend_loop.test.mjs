// Restore the server's committed loop result without replaying browser writes.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../frontend/loop.html', import.meta.url), 'utf8');
const source = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes('var state ='));
const tick = () => new Promise(resolve => setImmediate(resolve));
const questions = ['mother', 'variant1', 'variant2', 'variant3'].map((role, index) => ({ role, question_id: index + 10, content: 'question ' + index, question_type: '填空题' }));
const queue = questions.map(({ role, question_id }) => ({ role, question_id }));

function page({ storage, result, completed = false, search = '?pattern_id=1' }) {
  const fields = new Map(), calls = [], handlers = new Map();
  const element = id => { if (!fields.has(id)) fields.set(id, { innerHTML: '', textContent: '', value: '', style: {}, classList: { toggle() {} } }); return fields.get(id); };
  let ready;
  const loop = result.loop;
  const job = { job_id: 'loop-job', kind: 'grade', status: 'done', result, args: { question_id: 10, student_answer: '2', loop: { round_id: loop.round_id, pattern_id: 1, queue_index: 0 } } };
  const data = { pattern: { id: 1, name: '恢复测试', max_time_seconds: 120, mastery: { state: completed ? 'second_pass' : 'never' } }, questions };
  const context = vm.createContext({
    window: {}, location: { search }, URLSearchParams, Date, history: { replaceState() {} },
    document: { addEventListener(name, fn) { if (name === 'DOMContentLoaded') ready = fn; else handlers.set(name, fn); }, getElementById: element },
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    StudyJobs: {
      uuid: () => 'fresh-round-id', read: key => JSON.parse(storage.get('study_job_' + key) || 'null'),
      get: async id => { calls.push(['get-job', id]); return job; }, wait: async () => result,
      submit() { throw new Error('Restoration must not submit a new grade'); }, showResult() {},
    },
    fetch: async path => { calls.push(['fetch', path]); return { json: async () => data }; },
    renderMathInElement() {}, clearInterval() {}, setInterval: () => 1, setTimeout: () => 1,
  });
  vm.runInContext(source, context);
  return { context, fields, calls, ready, handlers, job };
}

function draftStorage({ single = false } = {}) {
  const storage = new Map();
  storage.set('loop_draft', JSON.stringify({ patternId: 1, queue: (single ? queue.slice(0, 1) : queue).map(q => q.role), queueIdx: 0,
    questionAttempts: 1, sessionFailed: false, motherOnlyMode: false, allQuestionsPassed: false, viewMode: 'grading',
    roundId: 'persisted-round', pendingGradeId: 'loop-job', appliedGradeIds: [], draftAnswer: '2', timerElapsed: 5 }));
  storage.set('study_job_loop_grade:persisted-round', JSON.stringify({ job_id: 'loop-job', status: 'pending', request_id: 'same-request' }));
  return storage;
}

const resultFor = ({ correct = true, complete = false } = {}) => ({ is_correct: correct, student_answer: '2', feedback: 'try again', loop: {
  round_id: 'persisted-round', pattern_id: 1, queue: complete ? queue.slice(0, 1) : queue,
  queue_index: 0, next_index: correct ? 1 : 0, mother_only: false, session_failed: !correct,
  elapsed_seconds: 5, completed: complete, needs_variants: false,
  mastery: complete ? { state: 'second_pass' } : correct ? null : { state: 'never' },
} });

{
  const storage = draftStorage(), c = page({ storage, result: resultFor() });
  c.ready(); await tick(); await tick();
  assert.equal(c.context.state.queueIdx, 1, 'returning to the page restores the next question');
  assert.equal(c.context.state.currentQuestion.role, 'variant1');
  assert.equal(c.context.state.pendingGradeId, null);
  assert.equal(JSON.parse(storage.get('study_job_loop_grade:persisted-round')).status, 'done');
  c.context.window.restoreLoopJob('loop-job'); await tick();
  assert.equal(c.context.state.queueIdx, 1, 'replaying the same result does not advance twice');
  assert.ok(!c.calls.some(call => call[0] === 'fetch' && /\/(attempt|complete)$/.test(call[1])));
}

{
  const storage = draftStorage({ single: true }), result = resultFor({ complete: true });
  const c = page({ storage, result, completed: true });
  c.ready(); await tick(); await tick();
  assert.equal(c.context.state.allQuestionsPassed, true);
  assert.match(c.fields.get('loopBody').innerHTML, /第二次会/);
  assert.equal(storage.has('loop_draft'), false);
  const reopened = page({ storage, result, completed: true, search: '?pattern_id=1&job=loop-job' });
  reopened.ready(); await tick(); await tick();
  assert.equal(reopened.context.state.allQuestionsPassed, true);
  assert.ok(!reopened.calls.some(call => call[0] === 'fetch' && /\/(attempt|complete)$/.test(call[1])));
}

{
  const storage = draftStorage(), c = page({ storage, result: resultFor({ correct: false }) });
  c.ready(); await tick(); await tick();
  assert.equal(c.context.state.queueIdx, 0);
  assert.equal(c.context.state.viewMode, 'fail');
  assert.equal(c.context.state.sessionFailed, true);
  assert.equal(c.fields.get('userAnswerInput').value, '2');
  assert.equal(JSON.parse(storage.get('study_job_loop_grade:persisted-round')).status, 'done', 'a fresh retry can create a new request');
}

{
  const storage = draftStorage();
  const draft = JSON.parse(storage.get('loop_draft'));draft.pendingGradeId=null;
  storage.set('loop_draft', JSON.stringify(draft));
  storage.set('study_job_loop_grade:persisted-round', JSON.stringify({ status: 'pending', request_id: 'lost-response' }));
  const c = page({ storage, result: resultFor() });
  c.ready();await tick();await tick();
  assert.equal(c.context.state.queueIdx, 0, 'the acceptance response has not returned');
  c.handlers.get('studyjobupdate')({ detail: c.job });
  await tick();await tick();
  assert.equal(c.context.state.queueIdx, 1, 'merged polling discovers a later server acceptance');
}

console.log('Loop restoration checks passed (next question, completion, failure, refresh and no duplicate browser writes).');
