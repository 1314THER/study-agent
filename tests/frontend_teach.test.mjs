// Restore the newest teaching initialization without calling paid AI.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../frontend/teach.html', import.meta.url), 'utf8');
const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { resolve, promise }; };
const sessionA = { session_id: 'A', question: 'old question', step_errors: { old: 'error' } };
const sessionB = { session_id: 'B', question: 'new question' };

function page({ saved = sessionA, job, pending, storage: shared, search = '', submission } = {}) {
  const storage = shared || new Map();
  if (!shared && saved) storage.set('_teach_session_v2', JSON.stringify(saved));
  const elements = new Map(), applied = [], fetched = [];
  const el = id => {
    if (!elements.has(id)) elements.set(id, { style: {}, value: '', disabled: false, classList: { add() {}, remove() {} } });
    return elements.get(id);
  };
  const record = job ? { job_id: job.job_id, request_id: 'request-' + job.job_id } : null;
  const context = vm.createContext({
    console, URLSearchParams,
    window: {}, location: { search },
    document: { documentElement: { classList: { add() {} } }, getElementById: el, addEventListener() {} },
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    StudyJobs: {
      read: () => record,
      get: async id => { fetched.push('job:' + id); return job; },
      wait: async (j, progress) => { if (progress) progress(j); return pending ? pending.promise : j.result; },
      submit: async () => submission ? submission.promise : { session_id: 'B' },
    },
    fetch: async url => {
      fetched.push(url);
      const state = url.endsWith('/A') ? sessionA : url.endsWith('/B') ? sessionB : null;
      return { ok: !!state, json: async () => state };
    },
    setInterval: () => 1, clearInterval() {}, setTimeout: () => 1, clearTimeout() {},
  });
  vm.runInContext(source, context);
  context.applyTeachState = state => { applied.push(state); context._sessionId = state.session_id; context._isWaiting = false; };
  return { context, storage, elements, applied, fetched, record };
}

{
  const pending = deferred();
  const p = page({ job: { job_id: 'new-start', kind: 'teach_start', status: 'running', args: { question: 'new question' } }, pending });
  const restore = p.context.restoreTeachingWork();
  await tick();
  assert.equal(p.context._sessionId, null);
  assert.equal(p.storage.has('_teach_session_v2'), false, 'old session cannot supersede pending initialization');
  assert.equal(p.elements.get('teachQuestionInput').value, 'new question');
  assert.equal(p.elements.get('teachStartBtn').disabled, true);
  assert.equal(p.fetched.includes('/teach/session/A'), false);
  pending.resolve({ session_id: 'B' });
  await restore;
  assert.equal(p.context._sessionId, 'B');
  assert.equal(p.applied[0].question, 'new question');
  assert.equal(Object.keys(p.context._stepErrorData).length, 0);
}

{
  const job = { job_id: 'new-start', kind: 'teach_start', status: 'done', args: { question: 'new question' }, result: { session_id: 'B' } };
  const p = page({ job });
  await p.context.restoreTeachingWork();
  assert.equal(p.context._sessionId, 'B', 'completed newest initialization replaces an old saved session');
  const same = page({ job, saved: { ...sessionB, step_errors: { current: 'kept' } } });
  await same.context.restoreTeachingWork();
  assert.equal(same.context._stepErrorData.current, 'kept');
}

{
  const p = page();
  await p.context.restoreTeachingWork();
  assert.equal(p.context._sessionId, 'A', 'ordinary refresh still restores its saved session');
}

{
  const job = { job_id: 'old-start', kind: 'teach_start', status: 'done', args: {}, result: { session_id: 'A' } };
  const p = page({ job });
  p.context._sessionId = 'A';
  p.context.cancelTeaching();
  const reloaded = page({ job, storage: p.storage });
  await reloaded.context.restoreTeachingWork();
  assert.equal(reloaded.context._sessionId, null, 'cancelled teaching does not reappear on refresh');
  assert.equal(reloaded.fetched.length, 0);
  const explicit = page({ job, storage: p.storage, search: '?job=old-start' });
  await explicit.context.restoreTeachingWork();
  assert.equal(explicit.context._sessionId, 'A', 'explicitly opening a task restores it');
}

{
  const submission = deferred();
  const p = page({ submission });
  p.context._sessionId = 'A';
  p.elements.set('teachQuestionInput', { value: 'new question', style: {} });
  p.storage.set('teach_start_ignored', 'old-request');
  const start = p.context.startTeaching();
  assert.equal(p.context._sessionId, null);
  assert.equal(p.storage.has('_teach_session_v2'), false, 'starting a new question clears old browser recovery data before waiting');
  assert.equal(p.storage.has('teach_start_ignored'), false);
  submission.resolve({ session_id: 'B' });
  await start;
  assert.equal(p.context._sessionId, 'B');
}

{
  const stale = page({ saved: { session_id: 'missing' } });
  assert.equal(await stale.context.restoreSession(), false);
  assert.equal(stale.context._sessionId, null);
  assert.equal(stale.storage.has('_teach_session_v2'), false);
}

console.log('Teaching restore checks passed (pending and completed new question, saved session, cancellation, explicit task, stale session).');
