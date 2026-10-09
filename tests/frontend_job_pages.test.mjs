// Confirm OCR restoration fills its source draft without submitting an answer.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../frontend/job-pages.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const job = { job_id: 'ocr-job', kind: 'ocr_file', status: 'done', result: { text: 'recognized answer' } };
const draft = { questionInput: 'the original question', qSelect: '8', fullScore: '12', teacher: 'liangliang', viewedAnswer: true };

async function restore(page, search) {
  const fields = new Map();
  const field = id => { if (!fields.has(id)) fields.set(id, { value: '', type: id === 'viewedAnswer' ? 'checkbox' : 'text', dispatchEvent() {} }); return fields.get(id); };
  let ready;
  let submitted = 0;
  const context = vm.createContext({
    location: { pathname: '/' + page, search }, URLSearchParams, Event,
    document: { addEventListener(name, callback) { if (name === 'DOMContentLoaded') ready = callback; }, getElementById: field },
    StudyJobs: {
      read: key => key === 'route:ocr-job' ? { page: 'grade.html', draft } : key.endsWith('/ocr/answer') ? { job_id: 'ocr-job' } : null,
      get: async () => job,
      wait: async () => job.result,
      submit: () => { submitted++; },
    },
    toggleQuestionMode() {},
  });
  vm.runInContext(source, context);
  ready();
  await tick();
  return { fields, submitted };
}

for (const search of ['', '?job=ocr-job']) {
  const grade = await restore('grade.html', search);
  assert.equal(grade.fields.get('answerInput').value, 'recognized answer');
  assert.equal(grade.fields.get('questionInput').value, 'the original question');
  assert.equal(grade.fields.get('qSelect').value, '8');
  assert.equal(grade.fields.get('fullScore').value, '12');
  assert.equal(grade.fields.get('viewedAnswer').checked, true);
  assert.equal(grade.submitted, 0, 'OCR must only restore a draft');
}
const teaching = await restore('teach.html', '?job=ocr-job');
assert.equal(teaching.fields.get('teachChatInput').value, 'recognized answer');
assert.equal(teaching.submitted, 0);

console.log('OCR page checks passed (grade context, refresh, explicit task, teaching draft, no automatic submission).');
