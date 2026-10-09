// Test the shipped tutorial controller with a small DOM, no browser or AI.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const script = readFileSync(new URL('../frontend/demo-session.js', import.meta.url), 'utf8');
const controller = script.slice(script.indexOf("    var tourKey ="), script.indexOf('    function displayCategory'));
const home = readFileSync(new URL('../frontend/demo-home.html', import.meta.url), 'utf8');
assert.match(home, /id="demo-enter-multimodal" href="multimodal.html"/);
assert.doesNotMatch(home, /href="index.html"/);
assert.match(home, /nav-init/);
assert.doesNotMatch(script, /addPresetCards|study:solve-ready/);

function page(storage = new Map(), pathname = '/home.html') {
  const nodes = [];
  const listeners = new Map();
  function element(tag = 'div') {
    const node = { tag, children: [], listeners: {}, hidden: false, style: {},
      classList: { add() {}, remove() {} }, setAttribute() {},
      append(...items) { this.children.push(...items); }, appendChild(item) { this.children.push(item); },
      replaceChildren(...items) { this.children = items; },
      addEventListener(type, callback) { this.listeners[type] = callback; },
      getBoundingClientRect: () => ({ height: 200, left: 20, right: 400, top: 20, bottom: 220, width: 380 }),
      getClientRects: () => [{}], matches: () => false, scrollIntoView() {}, contains: item => item === node,
    };
    nodes.push(node); return node;
  }
  const body = element('body'), intro = element('section'), entry = element('a'), complete = element('section');
  const storageApi = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) };
  const context = vm.createContext({
    window: { localStorage: storageApi, innerWidth: 1280, innerHeight: 800, setInterval: () => 1, addEventListener() {} },
    location: { pathname }, prefix: '', getComputedStyle: () => ({ visibility: 'visible' }),
    document: {
      body, createElement: element,
      getElementById: id => id === 'demo-home-complete' ? complete : null,
      querySelectorAll: selector => selector === '#demo-intro' ? [intro] : selector === '#demo-enter-multimodal' ? [entry] : [],
      addEventListener: (type, callback) => listeners.set(type, callback),
    },
  });
  vm.runInContext(controller, context);
  context.initializeTour();
  return { context, storage, body, complete, nodes, listeners };
}
const initial = page();
assert.equal(initial.context.tourState.active, true, 'tutorial starts automatically on entering demo homepage');
assert.equal(initial.context.tourState.step, 'welcome');
assert.equal(initial.context.window.StudyDemoTour.stop(), false, 'first visit cannot end before finishing');
assert.equal(initial.context.tourState.active, true);
assert.ok(initial.context.tourPanel.children.some(child => child.children.some(button => button.textContent === '跳过这步')));
assert.ok(!initial.nodes.some(node => /结束引导|收起教程/.test(node.textContent || '')));
initial.context.window.StudyDemoTour.skip();
assert.equal(initial.context.tourState.step, 'open-solve');
initial.context.window.StudyDemoTour.skip();
assert.equal(initial.context.tourState.step, 'preset');
const second = page(initial.storage, '/multimodal.html');
assert.equal(second.context.tourState.step, 'preset', 'step survives a page navigation and refresh');
assert.equal(second.context.tourState.active, true);
second.context.window.StudyDemoTour.emit('study:preset-selected', { client_index: 2 });
assert.equal(second.context.tourState.step, 'save');
assert.equal(second.context.tourState.client_index, 2);
assert.equal(second.context.mmTarget('.demo-auto-save'), '#session_2 .demo-auto-save');
second.context.window.StudyDemoTour.skip();
assert.equal(second.context.tourState.step, 'submit');
second.context.window.StudyDemoTour.emit('studyjobsubmitted', { job_id: 'job-2', kind: 'solve', status: 'queued', args: { client_index: 2 } });
assert.equal(second.context.tourState.step, 'wait-library');
assert.equal(second.context.tourState.job_id, 'job-2');
second.context.window.StudyDemoTour.emit('study:multimodal-solve-ready', { client_index: 1, result: { saved_question_id: 90 } });
assert.equal(second.context.tourState.result_ready, false, 'a different card cannot finish the selected tutorial task');
second.context.window.StudyDemoTour.emit('study:multimodal-solve-ready', { client_index: 2, result: { saved_question_id: 91 } });
assert.equal(second.context.tourState.result_ready, true);
assert.equal(second.context.tourState.question_id, 91);
while (second.context.tourState.step !== 'finished') second.context.window.StudyDemoTour.skip();
const finishActions = second.context.tourPanel.children.find(child => child.className === 'demo-tour-actions');
assert.ok(finishActions.children.some(child => child.href === 'https://150.chat/'), 'completion has direct owner-site CTA on every page');
assert.equal(second.context.tourState.completed, undefined);
finishActions.children.find(child => child.textContent === '完成教程，自由体验').listeners.click();
assert.equal(second.context.tourState.completed, true);
assert.equal(second.context.tourState.active, false);
const done = page(second.storage);
assert.equal(done.context.tourState.active, false, 'completed tutorial does not force a second run');
assert.equal(done.complete.hidden, false);
done.context.window.StudyDemoTour.restart();
assert.equal(done.context.tourState.step, 'welcome');
assert.equal(done.context.tourState.completed, false);
assert.equal(done.complete.hidden, true, 'restarting hides the previous completion entry');
assert.equal(done.context.window.StudyDemoTour.stop(), false);

// Demo category alias changes presentation only; form business values remain in the app.
const alias = vm.runInNewContext('(' + script.match(/function displayCategory\(value\)\{([^]*?)\}/)[0] + ')');
assert.equal(alias('指对幂耐克函数'), '指数、对数与幂函数');
assert.match(script, /parent\.tagName==='OPTION'&&!parent\.hasAttribute\('value'\)/);
console.log('Demo tutorial checks passed (homepage entry, automatic start, no early exit, skipping, cross-page state, card matching, complete CTA, restart, display alias).');
