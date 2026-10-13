// Real-browser acceptance of the read-only project showcase and prepared UI.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const server = spawn(process.env.SHOWCASE_PYTHON || 'python3', ['tests/e2e/showcase_server.py'], {
  cwd: new URL('../../', import.meta.url), env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'},
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverOutput = '', browser;
server.stderr.on('data', chunk => { serverOutput += chunk.toString(); });
const port = await new Promise((resolve, reject) => {
  let stdout = '';
  const deadline = setTimeout(() => { server.kill('SIGTERM'); reject(new Error('Showcase server timeout\n' + serverOutput)); }, 20000);
  deadline.unref();
  server.stdout.on('data', chunk => {
    stdout += chunk.toString(); const match = stdout.match(/SHOWCASE_PORT=(\d+)/);
    if (match) { clearTimeout(deadline); resolve(Number(match[1])); }
  });
  server.on('exit', code => { clearTimeout(deadline); reject(new Error('Showcase server exited ' + code + '\n' + serverOutput)); });
});
const base = 'http://127.0.0.1:' + port;
const shots = process.env.SHOWCASE_SHOTS || tmpdir() + '/showcase-shots';
const views = ['overview', 'solution', 'diagnosis', 'teaching', 'geometry', 'pool', 'graph', 'library', 'progress', 'research'];
await mkdir(shots, {recursive: true});

async function ready(page) {
  await page.waitForFunction(() => window.Showcase?.ready);
  const result = await page.evaluate(async () => {
    const data = await window.Showcase.ready;
    return {ok: data?.schema_version === 2, error: window.Showcase.state.loadError};
  });
  assert(result.ok, 'Prepared showcase data failed to initialize: ' + (result.error || 'unknown error'));
}
async function fit(page) {
  await page.waitForTimeout(120);
  const metrics = await page.evaluate(() => ({viewport: innerWidth, width: document.documentElement.scrollWidth}));
  assert(metrics.width <= metrics.viewport + 1, 'Horizontal overflow: ' + JSON.stringify(metrics));
}
async function choose(page, view) {
  const control = page.locator('[data-view="' + view + '"]').first();
  const controlBox = await control.boundingBox(), viewport = page.viewportSize();
  if ((!controlBox || controlBox.x < 0 || controlBox.x + controlBox.width > viewport.width) && await page.locator('#menu-toggle').isVisible())
    await page.locator('#menu-toggle').click();
  await control.click();
  await page.waitForFunction(view => {
    const panel = document.querySelector('[data-panel="' + view + '"]');
    return location.hash === '#' + view && panel && !panel.hidden;
  }, view);
  assert(await page.locator('[data-panel="' + view + '"]').isVisible(), 'Active view is not visible: ' + view);
  for (const other of views.filter(item => item !== view))
    assert.equal(await page.locator('[data-panel="' + other + '"]').isVisible(), false, 'Inactive view leaked: ' + other);
  await fit(page);
}
async function capture(page, view, name) {
  const panel = page.locator('[data-panel="' + view + '"]');
  await panel.screenshot({path: shots + '/' + name + '.png', animations: 'disabled'});
  await fit(page);
}

function auditPage(page) {
  const audit = {errors: [], console: [], requests: [], failures: []};
  page.on('pageerror', error => audit.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') audit.console.push(message.text()); });
  page.on('request', request => audit.requests.push({url: request.url(), method: request.method()}));
  page.on('requestfailed', request => {
    // Navigating a fixed PDF into the download manager may be reported aborted.
    if (!(request.url().endsWith('-paper.pdf') && request.failure()?.errorText === 'net::ERR_ABORTED'))
      audit.failures.push(request.url() + ': ' + request.failure()?.errorText);
  });
  return audit;
}
async function verifyAudit(context, audit) {
  assert.deepEqual(audit.errors, [], 'Uncaught browser errors');
  assert.deepEqual(audit.console, [], 'Browser console errors');
  assert.deepEqual(audit.failures, [], 'Failed static resources');
  for (const request of audit.requests) {
    if (/^(blob:|data:)/.test(request.url)) continue;
    assert.equal(new URL(request.url).origin, base, 'Automatic external request: ' + request.url);
    assert.equal(request.method, 'GET', 'Showcase invoked a write endpoint: ' + JSON.stringify(request));
    assert(!/\/(?:solve|teach|questions|question-pool|jobs|auth|patterns|generate)(?:\/|\?|$)/.test(new URL(request.url).pathname),
      'Showcase invoked a business API: ' + request.url);
  }
  assert.deepEqual(await context.cookies(), [], 'Showcase must not create an account or visitor cookie.');
}
async function checkGraphKeyboard(page) {
  const last = page.locator('#graph-canvas .graph-node').last();
  await last.focus(); await page.keyboard.press('Enter');
  assert.equal(await last.getAttribute('aria-pressed'), 'true');
  assert((await page.locator('#graph-detail').innerText()).trim().length > 30);
  const box = await page.locator('#graph-canvas').boundingBox(), card = await last.boundingBox();
  assert(card.x >= box.x - 2 && card.x + card.width <= box.x + box.width + 2
    && card.y >= box.y - 2 && card.y + card.height <= box.y + box.height + 2,
    'Keyboard focus did not reveal the complete graph node.');
}

try {
  let live = false;
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(base + '/health')).ok) { live = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(live, 'Isolated showcase did not start: ' + serverOutput);
  assert.deepEqual(await (await fetch(base + '/health')).json(),
    {ok: true, mode: 'demo', demo_mode: 'showcase', ai_enabled: false});
  for (const path of ['/solve', '/teach/session/start', '/questions/upload', '/question-pool/import', '/jobs', '/auth/login']) {
    const response = await fetch(base + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    assert([404, 405].includes(response.status), 'Business endpoint remained exposed: ' + path);
  }
  browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || chromium.executablePath(),
    args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const context = await browser.newContext({viewport: {width: 1440, height: 950}, acceptDownloads: true});
  const page = await context.newPage(), audit = auditPage(page);
  await page.goto(base + '/', {waitUntil: 'networkidle'}); await ready(page);
  assert(await page.locator('#opening-dialog').isVisible(), 'A normal-motion entrance must play the fullscreen opening.');
  await page.locator('#opening-skip').click();
  assert.equal(await page.locator('#opening-dialog').isVisible(), false, 'The opening must be immediately skippable.');
  await fit(page);
  assert.equal(await page.locator('[data-panel]').count(), 10, 'All ten prepared panels must exist.');
  await choose(page, 'overview');
  assert.equal(await page.locator('[data-panel="overview"] .project-lettering').count(), 0, 'Opening lettering must not duplicate the overview headline.');
  await capture(page, 'overview', 'desktop-overview');
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({path: shots + '/desktop-frame.png'});
  assert.equal(await page.locator('#main-nav [data-view] .nav-label').count(), 10);
  for (const label of await page.locator('#main-nav [data-view] .nav-label').all()) assert(await label.isVisible(), 'Sidebar labels must stay visible.');
  await choose(page, 'solution');
  const teachers = page.locator('[data-teacher]');
  assert.equal(await teachers.count(), 4, 'All four teacher themes must be available.');
  for (let i = 0; i < 4; i++) {
    await teachers.nth(i).click();
    assert.equal(await teachers.nth(i).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('[data-teacher][aria-pressed="true"]').count(), 1);
    const theme = await teachers.nth(i).getAttribute('data-teacher');
    assert(await page.evaluate(theme => document.body.classList.contains('theme-' + theme), theme));
    await capture(page, 'solution', 'teacher-' + (i + 1));
  }

  await choose(page, 'solution');
  const examples = await page.locator('#example-select option').evaluateAll(options => options.map(option => option.value));
  assert.equal(examples.length, 3);
  for (let i = 0; i < examples.length; i++) {
    await page.locator('#example-select').selectOption(examples[i]);
    await page.waitForFunction(() => document.querySelector('#solution-content .katex'));
    const detail = page.locator('#solution-content details').first();
    assert(await detail.count(), 'Solutions must have detailed steps.');
    if ((await detail.getAttribute('open')) === null) await detail.locator('summary').click();
    await page.waitForFunction(() => {const d=document.querySelector('#solution-content details');return d?.open && getComputedStyle(d.querySelector('.detail-content')).display !== 'none';});
    assert((await detail.innerText()).length > 30);
    assert.equal(await page.locator('#solution-content .katex-error').count(), 0);
    if (examples[i] === 'national-2023-q17') assert.match(await page.locator('#solution-content').innerText(), /π/);
    await capture(page, 'solution', 'solution-' + (i + 1));
  }

  await choose(page, 'diagnosis');
  const before = await page.locator('#diagnosis-content').innerText();
  await page.locator('#diagnosis-reveal').click();
  assert.notEqual(await page.locator('#diagnosis-content').innerText(), before);
  assert.match(await page.locator('#diagnosis-content').innerText(), /错误|条件|依据/);
  await capture(page, 'diagnosis', 'diagnosis-evidence');
  await page.locator('#diagnosis-corrected').click();
  assert(await page.locator('#diagnosis-content .is-correct').count() > 0);
  await capture(page, 'diagnosis', 'diagnosis-corrected');
  await page.locator('#diagnosis-reset').click();
  assert.equal(await page.locator('#diagnosis-content').innerText(), before);

  await choose(page, 'teaching');
  await page.locator('#teaching-hint').click();
  assert.match(await page.locator('#teaching-chat').innerText(), /提示|条件|思考/);
  await page.locator('#teaching-wrong').click();
  assert.match(await page.locator('#teaching-chat').innerText(), /错误|真数|条件|遗漏/);
  await capture(page, 'teaching', 'teaching-hint-wrong');
  await page.locator('#teaching-right').click();
  assert(await page.evaluate(() => window.Showcase.state.teaching.complete.includes(0)));
  assert.equal(await page.locator('#teaching-next').isDisabled(), false);
  await page.locator('#teaching-next').click();
  await page.locator('#teaching-variant').click();
  assert.match(await page.locator('#teaching-chat').innerText(), /变式|仿练|换/);
  await capture(page, 'teaching', 'teaching-variant');
  await page.locator('#teaching-reset').click();

  await choose(page, 'geometry');
  const scenes = await page.locator('#geometry-select option').evaluateAll(options => options.map(option => option.value));
  assert(scenes.length >= 3, 'At least three 2D/3D geometry examples are required.');
  for (let i = 0; i < scenes.length; i++) {
    await page.locator('#geometry-select').selectOption(scenes[i]);
    await page.waitForFunction(() => window.Showcase.state.player?.stage?.querySelector('canvas,svg'));
    const step = page.locator('#geometry-steps .geometry-step');
    assert(await step.count() > 1, 'Geometry must offer a step-linked construction.');
    await step.first().click();
    assert.equal(await page.evaluate(() => window.Showcase.state.player.index), -1, 'The original scene must be available before auxiliary constructions.');
    await step.last().click();
    assert.match(await step.last().getAttribute('class'), /active/);
    assert.equal(await page.evaluate(() => window.Showcase.state.player.index), await step.count() - 2);
    await page.waitForTimeout(2600);
    const parameter = page.locator('#geometry-host input[type="range"]');
    if (await parameter.count()) {
      const maximum = await parameter.first().getAttribute('max');
      await parameter.first().fill(maximum);
      await page.waitForTimeout(300);
      assert.equal(await parameter.first().inputValue(), maximum);
    }
    const stage = page.locator('#geometry-host .geometry-stage');
    const bounds = await stage.boundingBox();
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await page.mouse.down(); await page.mouse.move(bounds.x + bounds.width / 2 + 35, bounds.y + bounds.height / 2 + 10, {steps: 8});
    await page.mouse.up();
    await capture(page, 'geometry', 'geometry-' + scenes[i]);
  }

  await choose(page, 'pool');
  assert(await page.locator('#pool-list').getByRole('button').count() >= 3);
  for (const filter of ['matched', 'incomplete', 'all']) {
    await page.locator('#pool-filter').selectOption(filter);
    assert((await page.locator('#pool-list').innerText()).trim().length > 0);
  }
  await page.locator('#pool-search').fill('椭圆');
  assert.match(await page.locator('#pool-list').innerText(), /椭圆/);
  await page.locator('#pool-list').getByRole('button').first().click();
  assert(await page.locator('#pool-detail img').count() >= 1);
  const evidence = page.locator('#pool-detail a');
  assert(await evidence.count() >= 1, 'Pool sample must expose its document/source evidence.');
  const originalPage = page.locator('#pool-detail a[href^="/showcase/assets/"]').first();
  assert(await originalPage.count(), 'The self-authored sample must expose its complete demonstration page.');
  const popupPromise = page.waitForEvent('popup'); await originalPage.click();
  const popup = await popupPromise; await popup.waitForLoadState('networkidle');
  assert.equal(new URL(popup.url()).origin, base);
  assert(await popup.locator('svg').count() > 0); await popup.close();
  await capture(page, 'pool', 'pool-evidence');
  await page.locator('#pool-search').fill('');

  await choose(page, 'graph');
  assert.equal(await page.locator('#graph-category option').count(), 13, 'Graph must cover twelve categories plus all.');
  assert.match(await page.locator('#graph-count').innerText(), /288/);
  assert.equal(await page.locator('#graph-library .graph-category').count(), 12);
  await page.locator('#graph-category').selectOption('');
  const firstPage = await page.locator('#graph-page-label').innerText();
  await page.locator('#graph-page-next').click();
  assert.notEqual(await page.locator('#graph-page-label').innerText(), firstPage);
  await page.locator('#graph-page-prev').click();
  assert.equal(await page.locator('#graph-page-label').innerText(), firstPage);
  await page.locator('#graph-search').fill('三角');
  assert(await page.locator('#graph-canvas .graph-node').count() > 0);
  assert.match(await page.locator('#graph-canvas').textContent(), /三角/);
  const linkedId = await page.evaluate(() => window.Showcase.state.data.pool_examples.find(example => example.routine_id)?.routine_id);
  assert(linkedId, 'A public sample must link a routine to a review example.');
  await page.locator('#graph-search').fill(linkedId);
  await page.locator('#graph-canvas .graph-node').first().click();
  assert(await page.locator('#graph-detail .detail-review').count() > 0);
  await page.locator('#graph-detail .detail-review').first().click();
  await page.waitForFunction(() => location.hash === '#pool');
  assert(await page.locator('#pool-detail .pool-evidence').isVisible());
  await capture(page, 'pool', 'graph-linked-review');
  await choose(page, 'graph');
  await page.locator('#graph-search').fill('');
  await checkGraphKeyboard(page);
  await page.locator('#graph-reset').click();
  await page.locator('#graph-canvas .graph-node').first().focus();
  const node = page.locator('#graph-canvas .graph-node').first(), transform = await node.getAttribute('transform');
  const bounds = await node.boundingBox();
  await page.mouse.move(bounds.x + 40, bounds.y + 25); await page.mouse.down();
  await page.mouse.move(bounds.x + 105, bounds.y + 50, {steps: 8}); await page.mouse.up();
  assert.notEqual(await node.getAttribute('transform'), transform, 'Dragging a node must change its local layout.');
  assert.match(await page.locator('#graph-save-status').innerText(), /保存|本机|本地/);
  const movedId = await node.getAttribute('data-routine-id');
  const movedTransform = await node.getAttribute('transform');
  assert.deepEqual(await page.evaluate(() => Object.keys(localStorage)), ['study-showcase-layout-v2']);
  await page.reload({waitUntil: 'networkidle'}); await ready(page); await choose(page, 'graph');
  await page.locator('#graph-category').selectOption('');
  assert.equal(await page.locator('#graph-canvas [data-routine-id="' + movedId + '"]').getAttribute('transform'), movedTransform);
  await page.locator('#graph-add').click();
  await page.locator('#add-name').fill('浏览器验收自拟套路');
  await page.locator('#add-category').selectOption({index: 1});
  await page.locator('#add-signals').fill('自拟演示特征'); await page.locator('#add-steps').fill('自拟演示步骤');
  await page.locator('#add-submit').click();
  await page.locator('#graph-search').fill('浏览器验收自拟套路');
  assert.match(await page.locator('#graph-canvas').textContent(), /浏览器验收自拟套路/);
  assert.equal(await page.locator('#graph-canvas .confusable').count(), 0, 'A local new routine must not acquire invented links.');
  await capture(page, 'graph', 'graph-local-routine');
  await page.locator('#tour-reset').click(); await choose(page, 'graph');
  await page.locator('#graph-search').fill('浏览器验收自拟套路');
  assert.equal(await page.locator('#graph-canvas .graph-node').count(), 0, 'Demo reset must remove temporary local routines.');
  await page.locator('#graph-reset').click();
  await page.locator('#graph-search').fill('');
  await capture(page, 'graph', 'graph-three-column');

  await choose(page, 'library');
  assert.equal(await page.locator('#library-list input[type="checkbox"]').count(), 6);
  await page.locator('[data-library-tab="exam"]').click();
  await page.locator('#exam-student').click();
  assert.match(await page.locator('#exam-preview').innerText(), /学生|试卷/);
  for (const mode of ['student', 'teacher']) {
    await page.locator('#exam-' + mode).click();
    const downloadEvent = page.waitForEvent('download'); await page.locator('#exam-download').click();
    const download = await downloadEvent;
    assert.equal(await download.failure(), null);
    const path = await download.path(); assert((await readFile(path)).subarray(0, 5).toString() === '%PDF-', 'Prepared paper download must be a PDF.');
  }
  await capture(page, 'library', 'library-paper');
  await page.locator('[data-library-tab="calendar"]').click();
  assert((await page.locator('#calendar-content').innerText()).trim().length > 30);
  await capture(page, 'library', 'library-calendar');
  const calendarDestination = await page.evaluate(() => window.Showcase.state.data.library.calendar[0].view);
  await page.locator('#calendar-content button').first().click();
  await page.waitForFunction(view => location.hash === '#' + view, calendarDestination);

  await choose(page, 'progress');
  assert.match(await page.locator('[data-panel="progress"]').innerText(), /快照|研发|原型|进展/);
  await capture(page, 'progress', 'development-snapshots');
  await choose(page, 'research');
  assert.match(await page.locator('[data-panel="research"]').innerText(), /研究目标|目标|Benchmark|评测/);
  assert.match(await page.locator('[data-panel="research"]').innerText(), /95|90|300/);
  await capture(page, 'research', 'research-goals');

  await page.locator('#tour-play').click(); await page.locator('#tour-pause').click();
  assert.equal(await page.evaluate(() => window.Showcase.state.tour.playing), false);
  assert.equal(await page.evaluate(() => window.Showcase.state.tour.timer), null);
  await page.locator('#tour-next').click(); await page.locator('#tour-reset').click();
  assert.equal(await page.evaluate(() => window.Showcase.state.tour.index), -1);
  await choose(page, 'solution'); await page.locator('#tour-play').click();
  await choose(page, 'pool');
  assert.equal(await page.evaluate(() => window.Showcase.state.tour.playing), false);

  await page.setViewportSize({width: 1440, height: 520}); await choose(page, 'research');
  const lastNavigation = page.locator('[data-view="research"]').first();
  await lastNavigation.focus();
  assert(await lastNavigation.isVisible(), 'Low-height sidebar must retain the final navigation item.');
  const navigationBox = await lastNavigation.boundingBox();
  assert(navigationBox.y >= 0 && navigationBox.y + navigationBox.height <= 520, 'The last sidebar entry must scroll into the short viewport.');
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({path: shots + '/low-height-sidebar.png'});
  await verifyAudit(context, audit); await context.close();

  const mobileContext = await browser.newContext({viewport: {width: 390, height: 844}, reducedMotion: 'reduce'});
  const mobile = await mobileContext.newPage(), mobileAudit = auditPage(mobile);
  await mobile.goto(base + '/', {waitUntil: 'networkidle'}); await ready(mobile);
  assert.equal(await mobile.locator('#opening-dialog').isVisible(), false, 'Reduced-motion entrance must not force an animation.');
  for (const width of [390, 360]) {
    await mobile.setViewportSize({width, height: 844});
    for (const view of views) {
      await choose(mobile, view);
      if (['overview', 'teaching', 'geometry', 'pool', 'graph'].includes(view)) await capture(mobile, view, 'mobile-' + width + '-' + view);
    }
  }
  await choose(mobile, 'solution');
  const keyboardControl = mobile.locator('[data-view="diagnosis"]').first();
  if (await mobile.locator('#menu-toggle').getAttribute('aria-expanded') !== 'true') await mobile.locator('#menu-toggle').click();
  await keyboardControl.focus(); await mobile.keyboard.press('Enter');
  await mobile.waitForFunction(() => location.hash === '#diagnosis');
  await fit(mobile);
  await verifyAudit(mobileContext, mobileAudit); await mobileContext.close();

  const openingContext = await browser.newContext({viewport: {width: 1440, height: 950}});
  const opening = await openingContext.newPage();
  await opening.goto(base + '/', {waitUntil: 'networkidle'}); await ready(opening);
  assert(await opening.locator('#opening-dialog').isVisible());
  await opening.screenshot({path: shots + '/fullscreen-opening.png'});
  await opening.waitForFunction(() => !document.querySelector('#opening-dialog').open, null, {timeout: 6000});
  await openingContext.close();

  const fallbackContext = await browser.newContext({viewport: {width: 390, height: 844}});
  await fallbackContext.addInitScript(() => {
    const native = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, ...args) {
      return /^webgl/.test(String(type)) ? null : native.call(this, type, ...args);
    };
  });
  const fallback = await fallbackContext.newPage();
  await fallback.goto(base + '/#geometry', {waitUntil: 'networkidle'}); await ready(fallback);
  assert.match(await fallback.locator('#geometry-host').innerText(), /文字|WebGL|不支持|不可用/);
  await capture(fallback, 'geometry', 'geometry-no-webgl');
  await fallbackContext.close();
  console.log(JSON.stringify({ok: true, views: views.length, screenshot_directory: shots}));
} finally {
  await browser?.close();
  const exit = new Promise(resolve => {
    if (server.exitCode !== null) return resolve(server.exitCode);
    server.once('exit', code => resolve(code));
  });
  server.kill('SIGTERM');
  const code = await exit;
  assert.equal(code, 0, 'The isolated server failed its no-owner-data boundary: ' + serverOutput);
}
