#!/usr/bin/env node
/* Render every StressLess view with headless Chromium and fail on client-side errors.
 *
 * Usage: STRESSLESS_EMAIL=… STRESSLESS_PASSWORD=… node tools/screenshots.mjs [--url http://localhost:3000] [--out docs/screenshots] [--theme light] [--mobile]
 * Needs a running app (npm run dev, or a deployment) and a confirmed account. First time: npx playwright install chromium.
 */
import { mkdirSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';

const { values: args } = parseArgs({ options: { url: { type: 'string', default: 'http://localhost:3000' }, out: { type: 'string', default: 'docs/screenshots' }, theme: { type: 'string' }, mobile: { type: 'boolean', default: false } } });
const base = args.url.replace(/\/$/, '');
const email = process.env.STRESSLESS_EMAIL, password = process.env.STRESSLESS_PASSWORD;
if (!email || !password) {
  console.error('Set STRESSLESS_EMAIL and STRESSLESS_PASSWORD to a confirmed account.');
  process.exit(2);
}
mkdirSync(args.out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: args.mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
page.setDefaultTimeout(15000);
let errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push(e.message));
if (args.theme) await page.addInitScript((t) => localStorage.setItem('sl-theme', t), args.theme);

await page.goto(base + '/login');
await page.fill('input[type=email]', email);
await page.fill('input[type=password]', password);
await page.click('button[type=submit]');
await page.waitForURL((u) => !u.pathname.startsWith('/login'));

// "today" as the app sees it: once a view has rendered, the rail's Morning link carries the server's date
await page.locator('main#view .view-head').waitFor();
const href = await page.locator('a.rail-link[data-view="daily"]').getAttribute('href');
const today = href.split('/')[2];
const views = [
  ['daily', `/daily/${today}`, '.ah-report'],
  ['daily-reveal', `/daily/${today}?reveal=1`, '[data-tour="reveal"]'],
  ['weekly', '/weekly', '.c-heat'],
  ['connect', '/connect', '.media-source-bar'],
  ['account', '/account', '#account-details'],
  ['data', '/data', '.v-data-conn'],
];
// The drawer opens only on click and contains exactly the five destinations.
const menu = page.getByRole('button', { name: 'Open navigation', exact: true });
if (!args.mobile) {
  await menu.hover();
  if (await menu.getAttribute('aria-expanded') !== 'false') throw new Error('Hover opened navigation');
  await menu.click();
  const labels = await page.locator('#rail-nav .rail-label').allTextContents();
  if (JSON.stringify(labels) !== JSON.stringify(['Daily Tab', 'Weekly Tab', 'Connect Your Data', 'My Account', 'Data and Privacy'])) throw new Error('Unexpected navigation: ' + labels.join(', '));
  await page.keyboard.press('Escape');
  if (await menu.getAttribute('aria-expanded') !== 'false') throw new Error('Escape did not close navigation');
}
let failures = 0;
for (const [name, path, ready] of views) {
  errors = [];
  await page.goto(base + path);
  try { await page.locator(ready).first().waitFor(); } catch { errors.push('timed out waiting for ' + ready); }
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${args.out}/${name}.png` });
  const bad = await page.locator('.error-card').count();
  if (await page.evaluate(() => document.body.scrollWidth > innerWidth)) errors.push('page overflows the viewport');
  const ok = !errors.length && !bad;
  failures += ok ? 0 : 1;
  console.log(`${name.padEnd(16)} ${ok ? 'ok' : 'FAIL'}${bad ? ' (error card)' : ''}`);
  errors.slice(0, 3).forEach((e) => console.log('    ' + e.slice(0, 200)));
}

// presenter tour, step 3 (the replay playing the evening)
await page.goto(base + `/daily/${today}`);
await page.locator('.ah-report').waitFor();
await page.keyboard.press('t');
await page.locator('.tour-card').waitFor();
await page.keyboard.press('ArrowRight');
await page.waitForTimeout(800);
await page.keyboard.press('ArrowRight');
await page.waitForTimeout(3000);
await page.screenshot({ path: `${args.out}/tour.png` });
console.log('tour             ok');

await browser.close();
console.log(`\n${views.length - failures}/${views.length} views clean -> ${args.out}`);
process.exit(failures ? 1 : 0);
