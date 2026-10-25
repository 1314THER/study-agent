import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../frontend/settings.html', import.meta.url), 'utf8');
const source = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
class Element {
  constructor() { this.children = []; this.attrs = {}; this.value = ''; this.classList = {add() {}}; }
  set innerHTML(value) { this.children = []; }
  appendChild(child) { this.children.push(child); if (child.selected) this.value = child.value; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener() {}
}
const elements = new Map();
const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const descendants = el => [el, ...el.children.flatMap(descendants)];
let data = {
  teachers: Object.fromEntries(Object.entries({liangliang:'glm-4.7-flash',taotao:'deepseek-flash',xuefeng:'glm-5.3-flash',ji:'gpt-6-astra'}).map(([t, model]) =>
    [t, Object.fromEntries(['solver','verifier','formatter','grade'].map(s => [s, {model, reasoning_effort:'medium'}]))])),
  api: {deepseek:{has_key:true,base_url:'https://api.deepseek.com/v1'},zhipu:{has_key:false,base_url:'https://open.bigmodel.cn/api/paas/v4'}},
};
const submitted = [];
const context = vm.createContext({
  document: {documentElement:new Element(),getElementById:get,createElement:() => new Element(),addEventListener() {},
    querySelectorAll: () => descendants(get('teacherGrid')).filter(el => el.attrs['data-t'])},
  window: {},
  fetch: async (url, opts) => {
    if (opts?.method === 'PUT') {
      const body = JSON.parse(opts.body); submitted.push(body);
      data = {...data, teachers: body.teachers, api: {...data.api,zhipu:{...data.api.zhipu,has_key:!!body.api.zhipu.api_key}}};
    }
    return {ok:true,json:async () => data};
  },
});
vm.runInContext(source, context);
context.recomputePreview = () => {};
await context.loadSettings();
assert.equal(get('glmKey').value, '');
assert.match(get('glmKey').placeholder, /未配置/);
let inputs = descendants(get('teacherGrid')).filter(el => el.attrs['data-t']);
assert.equal(inputs.length, 32);
assert.equal(inputs.filter(el => el.attrs['data-f'] === 'reasoning_effort' && el.value === 'medium').length, 16);
get('glmKey').value = 'glm-new-test-key';
inputs.find(el => el.attrs['data-t'] === 'ji' && el.attrs['data-s'] === 'solver' && el.attrs['data-f'] === 'reasoning_effort').value = 'high';
await context.saveSettings();
assert.equal(submitted[0].api.zhipu.api_key, 'glm-new-test-key');
assert.equal(Object.hasOwn(submitted[0].api.deepseek, 'api_key'), false, 'blank DS input preserves existing credential');
assert.equal(submitted[0].teachers.ji.solver.reasoning_effort, 'high');
assert.equal(get('glmKey').value, '', 'clear key after save without echoing it');
assert.match(get('glmKey').placeholder, /已配置/);
assert.equal(Object.hasOwn(context.collectSettings().api.zhipu, 'api_key'), false, 'blank GLM input preserves saved credential');
console.log('Settings checks passed: 16 model/effort stages, GLM key roundtrip and DS key preservation.');
