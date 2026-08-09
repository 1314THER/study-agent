// 前端端到端冒烟：真实打开首页，走一次 agent 流式对话并渲染题目卡片。
// 需要：后端已启动、Playwright 已安装（Node 运行）。
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });

  await page.goto(`${BASE}/home.html`, { waitUntil: 'load', timeout: 15000 });
  await page.waitForSelector('#agentHome.agent-host', { timeout: 10000 });
  await page.waitForTimeout(500);

  await page.fill('#agentHome .agent-input', '拿3道题练练');
  await page.click('#agentHome .agent-send');
  await page.waitForSelector('#agentHome .agent-qcard', { timeout: 120000 });

  const cards = await page.$$eval('#agentHome .agent-qcard', (els) => els.length);
  const visibleBubbles = await page.$$eval(
    '#agentHome .agent-msg-agent .agent-bubble',
    (els) => els.filter((el) => el.offsetParent !== null).length,
  );

  if (cards === 0) throw new Error('未渲染任何题目卡片');
  if (visibleBubbles < 2) throw new Error('agent 回复气泡未正常显示');
  const fatal = errors.filter((e) => !e.includes('favicon') && !e.includes('Failed to load resource'));
  if (fatal.length) throw new Error(`页面报错：${fatal.join(' | ')}`);

  console.log(`E2E_OK cards=${cards} bubbles=${visibleBubbles}`);
} finally {
  await browser.close();
}
