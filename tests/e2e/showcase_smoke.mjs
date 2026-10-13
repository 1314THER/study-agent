// Real browser coverage for the public, fully offline project showcase.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const server = spawn(process.env.SHOWCASE_PYTHON || 'python3', ['tests/e2e/showcase_server.py'], {
  cwd: new URL('../../', import.meta.url),
  env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'},
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverOutput = '', browser;
server.stderr.on('data', chunk => { serverOutput += chunk.toString(); });
const port = await new Promise((resolve, reject) => {
  let stdout = '';
  const deadline = setTimeout(() => {
    server.kill('SIGTERM');
    reject(new Error('Showcase server timed out\n' + serverOutput));
  }, 20000);
  deadline.unref();
  server.stdout.on('data', chunk => {
    stdout += chunk.toString();
    const match = stdout.match(/SHOWCASE_PORT=(\d+)/);
    if (match) { clearTimeout(deadline); resolve(Number(match[1])); }
  });
  server.on('exit', code => {
    clearTimeout(deadline);
    reject(new Error('Showcase server exited ' + code + '\n' + serverOutput));
  });
});
const base = 'http://127.0.0.1:' + port;
const shots = process.env.SHOWCASE_SHOTS || tmpdir() + '/showcase-shots';
await mkdir(shots, {recursive: true});

async function settle(page) {
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true,
    'The page must fit the viewport without horizontal document overflow.');
}
async function awaitReady(page) {
  await page.waitForFunction(() => window.Showcase?.ready);
  const result = await page.evaluate(async () => {
    const data = await window.Showcase.ready;
    return {ready: data?.schema_version === 1, error: window.Showcase.state.loadError};
  });
  assert(result.ready, 'Showcase initialization failed: ' + (result.error || 'no prepared examples'));
}
async function chooseTab(page, name) {
  const tab = page.locator('[data-demo-tab="' + name + '"]');
  await tab.click();
  await page.waitForFunction(name => {
    const tab = document.querySelector('[data-demo-tab="' + name + '"]');
    const panel = document.querySelector('[data-demo-panel="' + name + '"]');
    return tab?.getAttribute('aria-selected') === 'true' && panel && !panel.hidden;
  }, name);
  assert(await page.locator('[data-demo-panel="' + name + '"]').isVisible(), 'Selected demo panel must be visible.');
  for (const other of ['solution', 'diagnosis', 'geometry', 'graph'].filter(value => value !== name)) {
    assert.equal(await page.locator('[data-demo-panel="' + other + '"]').isVisible(), false,
      'Inactive demo panels must stay hidden.');
  }
}
async function assertReadableGraph(page, mobile = false) {
  const metrics = await page.locator('#graph-canvas .graph-node').first().evaluate(node => {
    const title = node.querySelector('.graph-title'), matrix = title.getScreenCTM();
    const scale = Math.hypot(matrix.a, matrix.b);
    return {font: parseFloat(getComputedStyle(title).fontSize) * scale,
      width: node.querySelector('rect').getBoundingClientRect().width};
  });
  assert(metrics.font >= 10, 'Graph text is too small to read: ' + metrics.font + ' rendered pixels.');
  assert(metrics.width >= 180, 'Graph cards must retain a readable screen width.');
  if (mobile) {
    const columns = await page.locator('#graph-canvas .graph-node').evaluateAll(nodes =>
      nodes.slice(0, 2).map(node => node.transform.baseVal.consolidate().matrix.e));
    assert.equal(columns[0], columns[1], 'Narrow mobile graphs must use one readable column.');
  }
}
async function assertOffscreenFocus(page) {
  const graph = page.locator('#graph-canvas'), last = graph.locator('.graph-node').last();
  await last.focus();
  await page.keyboard.press('Enter');
  const viewport = await graph.boundingBox(), node = await last.boundingBox();
  assert(node.x >= viewport.x - 2 && node.x + node.width <= viewport.x + viewport.width + 2
    && node.y >= viewport.y - 2 && node.y + node.height <= viewport.y + viewport.height + 2,
    'Focusing a lower graph node must bring the whole node into the visible canvas.');
  assert.equal(await last.getAttribute('aria-pressed'), 'true');
  await page.locator('#graph-reset').click();
  await graph.locator('.graph-node').first().focus();
  await page.keyboard.press('Enter');
}
async function assertInitialGeometryFits(page) {
  const result = await page.evaluate(() => {
    const player = window.Showcase.state.player, stage = player.stage;
    const bounds = stage.getBoundingClientRect();
    const scene = player.data.geometry.scenes.find(scene => scene.id === player.sceneId);
    const basePoints = scene.objects.filter(object => object.base && object.kind === 'point');
    return basePoints.map(point => {
      const label = [...stage.querySelectorAll('.geometry-label')].find(label => label.textContent === point.label);
      if (!label || label.hidden) return {id: point.id, label: false, vertex: false};
      const rectangle = label.getBoundingClientRect();
      const x = parseFloat(label.style.left) - 5, y = parseFloat(label.style.top) + 18;
      return {id: point.id,
        vertex: x >= 0 && x <= stage.clientWidth && y >= 0 && y <= stage.clientHeight,
        label: rectangle.x >= bounds.x - 2 && rectangle.right <= bounds.right + 2
          && rectangle.y >= bounds.y - 2 && rectangle.bottom <= bounds.bottom + 2};
    });
  });
  assert.equal(result.length, 8, 'The showcase cube must have its eight original vertices.');
  assert(result.every(point => point.vertex && point.label),
    'Initial cube vertices and labels must fit the canvas: ' + JSON.stringify(result));
}

try {
  let ready = false;
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(base + '/health')).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(ready, 'Showcase health endpoint never became ready: ' + serverOutput);
  const health = await (await fetch(base + '/health')).json();
  assert.match(JSON.stringify(health), /showcase|展示/);
  for (const path of ['/solve', '/teach/session/start', '/questions/upload', '/question-pool/import', '/generate', '/tasks', '/auth/login']) {
    const result = await fetch(base + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    assert([404, 405].includes(result.status), 'Write endpoint remained exposed: ' + path + ' -> ' + result.status);
  }
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || chromium.executablePath(),
    args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const context = await browser.newContext({viewport: {width: 1440, height: 950}});
  const page = await context.newPage(), errors = [], consoleErrors = [], requests = [], failures = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('request', request => requests.push({url: request.url(), method: request.method()}));
  page.on('requestfailed', request => failures.push(request.url() + ': ' + request.failure()?.errorText));
  await page.goto(base + '/', {waitUntil: 'networkidle'});
  await awaitReady(page);
  await page.waitForSelector('#example-select');
  await page.waitForFunction(() => document.querySelector('#example-select').options.length >= 3);
  assert.match(await page.locator('h1').innerText(), /步骤|诊断|迁移/);
  assert.equal(await page.locator('[data-demo-tab]').count(), 4);
  await settle(page);
  await page.screenshot({path: shots + '/desktop-overview.png', fullPage: true});

  const examples = await page.locator('#example-select option').evaluateAll(options => options.map(o => o.value));
  assert.equal(examples.length, 3, 'Showcase must retain all three curated examination examples.');
  for (let index = 0; index < examples.length; index++) {
    await page.locator('#example-select').selectOption(examples[index]);
    await page.waitForFunction(() => document.querySelector('#solution-content .katex'));
    assert(await page.locator('#solution-content').innerText().then(text => text.trim().length > 100));
    const detail = page.locator('#solution-content details').first();
    assert(await detail.count(), 'A solution must offer an expandable detailed step.');
    if ((await detail.getAttribute('open')) === null) await detail.locator('summary').click();
    assert(await detail.innerText().then(text => text.length > 20), 'Expanding a step must reveal detailed reasoning.');
    assert(await page.locator('#solution-content .step-detail .katex').count() > 0,
      'Mathematical expressions in detailed steps must render with the local library.');
    await settle(page);
    await page.locator('[data-demo-panel="solution"]').screenshot({path: shots + '/solution-' + (index + 1) + '.png'});
  }

  const firstTab = page.locator('[data-demo-tab="solution"]');
  await firstTab.focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.locator('[data-demo-tab="diagnosis"]').getAttribute('aria-selected'), 'true');
  await page.keyboard.press('Home');
  assert.equal(await firstTab.getAttribute('aria-selected'), 'true');
  await page.keyboard.press('End');
  assert.equal(await page.locator('[data-demo-tab="graph"]').getAttribute('aria-selected'), 'true');

  await chooseTab(page, 'diagnosis');
  const diagnosisPanel = page.locator('[data-demo-panel="diagnosis"]');
  assert.match(await diagnosisPanel.innerText(), /预制|演示数据|示例/);
  const beforeDiagnosis = await diagnosisPanel.innerText();
  await page.locator('#diagnosis-reveal').click();
  assert.notEqual(await diagnosisPanel.innerText(), beforeDiagnosis, 'Revealing diagnosis must expose its evidence and feedback.');
  assert.match(await diagnosisPanel.innerText(), /错误|条件|依据/);
  await diagnosisPanel.screenshot({path: shots + '/diagnosis.png'});
  await page.locator('#diagnosis-reset').click();
  assert.equal(await diagnosisPanel.innerText(), beforeDiagnosis);

  await chooseTab(page, 'geometry');
  await page.waitForSelector('#geometry-host .geometry-stage canvas');
  await page.waitForTimeout(2500);
  assert.equal(await page.locator('#geometry-host .geometry-note').innerText().then(t => t.includes('不可用')), false);
  const canvas = page.locator('#geometry-host .geometry-stage canvas');
  await canvas.scrollIntoViewIfNeeded();
  await assertInitialGeometryFits(page);
  await page.locator('[data-demo-panel="geometry"]').screenshot({path: shots + '/geometry-initial-desktop.png'});
  const firstCamera = await page.evaluate(() => window.Showcase.state.player.renderer.snapshot().position);
  const canvasBox = await canvas.boundingBox();
  await page.mouse.move(canvasBox.x + canvasBox.width * .4, canvasBox.y + canvasBox.height * .5);
  await page.mouse.down();
  await page.mouse.move(canvasBox.x + canvasBox.width * .65, canvasBox.y + canvasBox.height * .6, {steps: 8});
  await page.mouse.up();
  await page.waitForTimeout(100);
  assert.notDeepEqual(await page.evaluate(() => window.Showcase.state.player.renderer.snapshot().position), firstCamera,
    'Dragging the 3D scene must rotate its view.');
  const slider = page.locator('#geometry-host .geometry-parameter input[type="range"]');
  const sliderMaximum = Number(await slider.getAttribute('max'));
  assert(sliderMaximum > 1, 'The section must have multiple validated parameter frames.');
  const keyboardSliderValue = Number(await slider.inputValue());
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(Number(await slider.inputValue()), keyboardSliderValue + 1,
    'The section parameter must support native keyboard adjustment.');
  await slider.fill(String(Math.floor(sliderMaximum / 2)));
  await page.waitForTimeout(150);
  assert.equal(await slider.inputValue(), String(Math.floor(sliderMaximum / 2)));
  const play = page.locator('#geometry-host .geometry-parameter button');
  const pausedValue = await slider.inputValue();
  await play.click();
  await page.waitForTimeout(350);
  assert.notEqual(await slider.inputValue(), pausedValue, 'Parameter playback must advance the scene.');
  await play.click();
  const geometrySteps = page.locator('#geometry-host .geometry-toolbar select');
  if (await geometrySteps.count()) {
    const values = await geometrySteps.locator('option').evaluateAll(options => options.map(o => o.value));
    await geometrySteps.selectOption(values.at(-1));
  }
  await page.waitForTimeout(2500);
  await settle(page);
  await page.locator('[data-demo-panel="geometry"]').screenshot({path: shots + '/geometry.png'});

  await chooseTab(page, 'graph');
  const graph = page.locator('#graph-canvas');
  const nodes = graph.locator('[data-routine-id], [data-id], [role="button"]');
  assert(await nodes.count() > 10, 'The graph must contain curated existing routine nodes.');
  await nodes.first().click();
  assert(await page.locator('#graph-detail').innerText().then(text => text.trim().length > 20));
  const graphBeforeZoom = await graph.getAttribute('viewBox');
  await page.locator('#graph-zoom-in').click();
  assert.notEqual(await graph.getAttribute('viewBox'), graphBeforeZoom);
  await page.locator('#graph-zoom-out').click();
  await page.locator('#graph-reset').click();
  await graph.focus();
  await page.keyboard.press('ArrowRight');
  assert.notEqual(await graph.getAttribute('viewBox'), graphBeforeZoom, 'The graph must support keyboard panning.');
  await page.locator('#graph-reset').click();
  const categories = await page.locator('#graph-category option').evaluateAll(options => options.map(o => o.value));
  assert(categories.length > 2);
  await page.locator('#graph-category').selectOption(categories[1]);
  const filteredCount = await nodes.count();
  assert(filteredCount > 0);
  await page.locator('#graph-search').fill('___no_matching_routine___');
  await page.waitForTimeout(100);
  assert.equal(await nodes.count(), 0, 'No-result filtering must not retain stale graph nodes.');
  assert.match(await page.locator('#graph-count').innerText(), /当前\s*0/);
  await page.locator('#graph-search').fill('');
  await page.locator('#graph-category').selectOption(categories[0]);
  await page.waitForTimeout(100);
  assert(await nodes.count() > filteredCount);
  await assertReadableGraph(page);
  await assertOffscreenFocus(page);
  const keyboardNode = nodes.first();
  await keyboardNode.focus();
  await page.keyboard.press('Enter');
  assert(await page.locator('#graph-detail').innerText().then(text => text.trim().length > 20));
  await settle(page);
  await page.locator('[data-demo-panel="graph"]').screenshot({path: shots + '/graph.png'});

  for (const width of [390, 360]) {
    await page.setViewportSize({width, height: 844});
    await page.goto(base + '/', {waitUntil: 'networkidle'});
    await awaitReady(page);
    await page.waitForSelector('#example-select');
    await settle(page);
    await page.screenshot({path: shots + '/mobile-' + width + '.png', fullPage: true});
    await page.locator('#menu-toggle').click();
    assert.equal(await page.locator('#menu-toggle').getAttribute('aria-expanded'), 'true');
    assert(await page.locator('#main-nav').isVisible());
    await page.screenshot({path: shots + '/mobile-nav-' + width + '.png'});
    await page.locator('#menu-toggle').click();
    for (const name of ['solution', 'diagnosis', 'geometry', 'graph']) {
      await chooseTab(page, name);
      if (name === 'diagnosis' && await page.locator('#diagnosis-reveal').isVisible()) {
        await page.locator('#diagnosis-reveal').click();
      }
      if (name === 'geometry') {
        await page.waitForSelector('#geometry-host .geometry-stage canvas');
        await page.waitForTimeout(2500);
        await assertInitialGeometryFits(page);
      }
      if (name === 'graph') {
        await assertReadableGraph(page, true);
        await assertOffscreenFocus(page);
      }
      await settle(page);
      await page.locator('[data-demo-panel="' + name + '"]').screenshot({path: shots + '/mobile-' + width + '-' + name + '.png'});
    }
  }
  for (const path of ['/teach.html', '/routine-graph.html', '/question-pool.html', '/calendar.html']) {
    await page.goto(base + path, {waitUntil: 'networkidle'});
    await awaitReady(page);
    assert(await page.locator('#example-select').count(), 'Legacy link did not resolve to showcase: ' + path);
    assert.equal(new URL(page.url()).pathname, '/');
  }
  assert.deepEqual(await context.cookies(), [], 'The public showcase must not create account or visitor cookies.');
  assert.deepEqual(await page.evaluate(() => ({local: Object.keys(localStorage), session: Object.keys(sessionStorage)})),
    {local: [], session: []}, 'The public showcase must not persist visitor sessions or owner data in browser storage.');
  assert.deepEqual(errors, []);
  assert.deepEqual(consoleErrors, []);
  assert.deepEqual(failures, []);
  assert(requests.every(request => request.method === 'GET'), 'Showcase interactions must use static GET requests only.');
  assert(requests.every(request => {
    const url = new URL(request.url);
    return url.origin === base || url.protocol === 'data:';
  }), 'The showcase must use only local or inline assets.');
  assert(!requests.some(request => /\/(auth|teach\/session|solve|tasks|question-pool)\b/.test(new URL(request.url).pathname)
    && !new URL(request.url).pathname.endsWith('.html')), 'The showcase must not call teaching, account, task or owner APIs.');

  const fallbackContext = await browser.newContext({viewport: {width: 390, height: 844}});
  await fallbackContext.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      if (/webgl/i.test(kind)) return null;
      return original.call(this, kind, ...args);
    };
  });
  const fallbackPage = await fallbackContext.newPage(), fallbackErrors = [];
  fallbackPage.on('pageerror', error => fallbackErrors.push(error.message));
  await fallbackPage.goto(base + '/');
  await awaitReady(fallbackPage);
  await fallbackPage.waitForSelector('#example-select');
  await chooseTab(fallbackPage, 'geometry');
  await fallbackPage.waitForFunction(() => document.querySelector('#geometry-host .geometry-note')?.textContent.includes('不可用'));
  assert.match(await fallbackPage.locator('[data-demo-panel="geometry"]').innerText(), /截面|正方体/);
  const fallbackSlider = fallbackPage.locator('#geometry-host .geometry-parameter input[type="range"]');
  assert(!(await fallbackSlider.isVisible()) || !(await fallbackSlider.isEnabled()),
    'Unavailable geometry must hide or disable parameter controls.');
  const fallbackNext = fallbackPage.locator('#geometry-host .geometry-toolbar button').filter({hasText: '下一步'});
  if (await fallbackNext.isVisible() && await fallbackNext.isEnabled()) {
    await fallbackNext.click();
    await fallbackPage.waitForTimeout(200);
  }
  assert.deepEqual(fallbackErrors, []);
  await settle(fallbackPage);
  await fallbackPage.locator('[data-demo-panel="geometry"]').screenshot({path: shots + '/geometry-no-webgl.png'});
  await fallbackContext.close();
  await context.close();
  console.log('Showcase browser checks passed: three local solutions, diagnosis, keyboard tabs, rotating/playable geometry, graph controls, mobile layout, redirects, offline assets and no visitor state. Screenshots: ' + shots);
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  const exitCode = await new Promise(resolve => {
    if (server.exitCode != null) resolve(server.exitCode);
    else server.once('exit', resolve);
  });
  if (exitCode !== 0 && exitCode !== null) throw new Error('Showcase server failed during shutdown: ' + serverOutput);
}
