// No browser server or AI calls: exercise upload navigation around async boundaries.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../frontend/jobs.js', import.meta.url), 'utf8');
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = () => new Promise(resolve => setImmediate(resolve));
const accepted = { job_id: 'upload-job', kind: 'parse_file', status: 'done', result: { questions: [] } };

function client({ bytes, response, digest, sharedStorage, page = 'multimodal.html' } = {}) {
  const handlers = new Map();
  const storage = sharedStorage || new Map();
  const calls = [];
  const location = { href: 'http://localhost/' + page, origin: 'http://localhost', pathname: '/' + page };
  const element = tag => ({ tagName: tag, style: {}, children: [], appendChild(child) { this.children.push(child); }, replaceChildren(...children) { this.children = children; } });
  const result = element('div');
  const document = {
    readyState: 'loading',
    addEventListener(name, fn) { handlers.set(name, fn); },
    dispatchEvent() {},
    getElementById(id) { return id === 'studyJobsPanel' ? { hidden: true } : id === 'studyJobsResult' ? result : null; },
    createElement: element,
  };
  const crypto = { randomUUID: () => 'request-id' };
  if (digest) crypto.subtle = { digest };
  const window = {
    crypto,
    fetch(url, options) {
      calls.push({ url, options });
      return typeof response === 'function' ? response(calls.length - 1, url) : response ? response.promise : Promise.resolve({ ok: true, json: async () => accepted });
    },
    addEventListener() {},
    dispatchEvent() {},
  };
  class BrowserEvent { constructor(type, options) { this.type = type; this.detail = options?.detail; } }
  const context = vm.createContext({
    window, document, location, crypto, URL,
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    Event: BrowserEvent, CustomEvent: BrowserEvent,
    setTimeout: () => 1, clearTimeout() {},
  });
  vm.runInContext(source, context);
  const file = { name: 'exam.pdf', size: 20, lastModified: 1, arrayBuffer: () => bytes.promise };
  const form = new Map([['file', file]]);
  return {
    calls, location, storage, result, jobs: window.StudyJobs,
    start: (kind = 'parse_file', options = {}) => window.StudyJobs.upload(kind, form, options),
    navigate() {
      let prevented = false;
      handlers.get('click')({
        target: { closest: () => ({ href: 'http://localhost/history.html', origin: 'http://localhost', hash: '' }) },
        preventDefault() { prevented = true; }, stopImmediatePropagation() {},
      });
      return prevented;
    },
  };
}

{
  const response = deferred();
  const c = client({ response });
  const upload = c.start();
  assert.equal(c.navigate(), true, 'navigation waits during upload');
  assert.equal(c.location.href, 'http://localhost/multimodal.html');
  response.resolve({ ok: true, json: async () => accepted });
  await upload;
  assert.equal(c.location.href, 'http://localhost/history.html', 'accepted upload resumes navigation');
}

{
  const response = deferred();
  const c = client({ response });
  const upload = c.start();
  assert.equal(c.navigate(), true);
  response.resolve({ ok: false, json: async () => ({ detail: 'upload failed' }) });
  await assert.rejects(upload, /upload failed/);
  assert.equal(c.location.href, 'http://localhost/multimodal.html', 'failed upload stays on the page');
  // A later successful retry must not carry the failed attempt's old navigation.
  response.promise = Promise.resolve({ ok: true, json: async () => accepted });
  await c.start();
  assert.equal(c.location.href, 'http://localhost/multimodal.html');
}

{
  const bytes = deferred();
  const digest = deferred();
  const c = client({ bytes, digest: () => digest.promise });
  const upload = c.start();
  assert.equal(c.navigate(), true, 'navigation is protected while reading file bytes');
  assert.equal(c.calls.length, 0);
  bytes.resolve(new ArrayBuffer(0));
  await tick();
  assert.equal(c.navigate(), true, 'navigation is protected while computing the digest');
  assert.equal(c.calls.length, 0);
  digest.resolve(new ArrayBuffer(0));
  await upload;
  assert.equal(c.location.href, 'http://localhost/history.html');
}

{
  const response = deferred();
  const c = client({ response });
  const upload = c.start();
  c.navigate();
  response.resolve({ ok: true, json: async () => ({ status: 'queued' }) });
  await assert.rejects(upload, /服务器未确认/);
  assert.equal(c.location.href, 'http://localhost/multimodal.html', 'missing acceptance ID cannot release navigation');
}

{
  const first = deferred(), second = deferred();
  const c = client({ response: index => [first.promise, second.promise][index] });
  const uploads = [c.start(), c.start()];
  assert.equal(c.navigate(), true);
  first.resolve({ ok: true, json: async () => ({ ...accepted, job_id: 'first-job' }) });
  await tick();
  assert.equal(c.location.href, 'http://localhost/multimodal.html', 'the first accepted file cannot release batch navigation');
  second.resolve({ ok: true, json: async () => ({ ...accepted, job_id: 'second-job' }) });
  await Promise.all(uploads);
  assert.equal(c.location.href, 'http://localhost/history.html', 'all files must be accepted before navigating');
}

{
  const first = deferred(), second = deferred();
  const c = client({ response: index => [first.promise, second.promise][index] });
  const uploads = Promise.allSettled([c.start(), c.start()]);
  c.navigate();
  first.resolve({ ok: false, json: async () => ({ detail: 'one file failed' }) });
  await tick();
  second.resolve({ ok: true, json: async () => accepted });
  const results = await uploads;
  assert.equal(results[0].status, 'rejected');
  assert.equal(results[1].status, 'fulfilled');
  assert.equal(c.location.href, 'http://localhost/multimodal.html', 'partial batch failure keeps the page open');
}

{
  const ocr = { ...accepted, kind: 'ocr_file', result: { text: 'recognized draft' } };
  const response = { promise: Promise.resolve({ ok: true, json: async () => ocr }) };
  const c = client({ page: 'grade.html', response });
  await c.start('ocr_file', { route: { page: 'grade.html', draft: { questionInput: 'question' } } });
  const nextTab = client({ page: 'home.html', response, sharedStorage: c.storage });
  await nextTab.jobs.showResult(ocr.job_id);
  assert.equal(nextTab.result.children.find(child => child.tagName === 'a').href, 'grade.html?job=upload-job', 'OCR opens its source page after reload or in another tab');
  assert.equal(nextTab.jobs.read('route:' + ocr.job_id).draft.questionInput, 'question');
}

console.log('Upload checks passed (success, failure, hashing, invalid confirmation, batch navigation, OCR source restoration).');

{
  const solve = { ...accepted, kind: 'solve', args: { client_page: 'multimodal' } };
  const response = { promise: Promise.resolve({ ok: true, json: async () => solve }) };
  const c = client({ page: 'home.html', response });
  await c.jobs.showResult(solve.job_id);
  assert.equal(c.result.children.find(child => child.tagName === 'a').href, 'multimodal.html?job=upload-job', 'multimodal solves reopen in their source feature');
}
