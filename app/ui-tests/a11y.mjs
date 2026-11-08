// Accessibility check of the UI on its mock backend: serves app/ui, opens each screen in
// Chrome (light and dark) and runs axe-core. Fails on any violation.
//
//   cd app && npm run test:a11y
//
// Needs Google Chrome installed (playwright-core uses it; no browser download). Set
// CHROME_PATH to use another Chromium build.

import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { chromium } from 'playwright-core';

const require = createRequire(import.meta.url);
const UI_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', 'ui');
const AXE_PATH = require.resolve('axe-core/axe.min.js');
const VIEWPORT = { width: 1440, height: 900 };
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.stl': 'model/stl' };

/** A static file server for app/ui on a free port. */
function serve() {
  const server = http.createServer(async (request, response) => {
    const path = normalize(decodeURIComponent(new URL(request.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
    try {
      const file = path === '/' ? 'index.html' : path;
      const body = await readFile(join(UI_ROOT, file));
      response.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
      response.end(body);
    } catch {
      response.writeHead(404).end();
    }
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

// ---- Screens. `prepare` runs in the page (it is serialised, so it uses only its argument).
async function prepare({ vessel, tab, vesselTab, open }) {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (vessel) {
    const card = [...document.querySelectorAll('#vessel-grid > *')].find((c) => c.textContent.includes(vessel));
    (card.querySelector('button, a') || card).click();
    await wait(2000);
  }
  if (tab) { document.getElementById(`tab-${tab}`).click(); await wait(1200); }
  if (vesselTab) { document.querySelector(`[data-vtab="${vesselTab}"]`).click(); await wait(800); }
  if (open === 'intake') { document.getElementById('drop-choose').click(); await wait(2000); }
  if (open === 'palette') { document.getElementById('open-palette').click(); await wait(300); }
  if (open === 'shortcuts') { document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true })); await wait(300); }
}

const SCREENS = [
  { name: 'welcome', path: '/?mocknokey#home', seen: false },
  { name: 'home', path: '/#home' },
  { name: 'home (first start)', path: '/?mockempty#home' },
  { name: 'queue', path: '/#queue' },
  { name: 'settings', path: '/#settings' },
  { name: 'intake', path: '/#home', steps: { open: 'intake' } },
  { name: 'run (draft)', path: '/#home', steps: { vessel: 'Survey' } },
  { name: 'run (declined)', path: '/#home', steps: { vessel: 'Passenger' } },
  { name: 'checks', path: '/#home', steps: { vessel: 'Survey', tab: 'checks' } },
  { name: 'export', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'export' } },
  { name: 'history', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'history' } },
  { name: 'parts', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'parts' } },
  { name: 'palette', path: '/#home', steps: { vessel: 'Survey', open: 'palette' } },
  { name: 'shortcuts', path: '/#queue', steps: { open: 'shortcuts' } },
];
const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' });
let failures = 0;
try {
  for (const scheme of ['light', 'dark']) {
    for (const screen of SCREENS) {
      const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: scheme, bypassCSP: true });
      const page = await context.newPage();
      if (screen.seen !== false) await page.addInitScript(() => localStorage.setItem('marinaframe.ui', JSON.stringify({ setupSeen: true })));
      await page.goto(base + screen.path);
      await page.waitForTimeout(1500);
      if (screen.steps) await page.evaluate(prepare, screen.steps);
      await page.addScriptTag({ path: AXE_PATH });
      const violations = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ['violations'] })).violations
        .map((v) => `${v.impact} ${v.id}: ${v.help} (${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join('; ')})`));
      const label = `${screen.name}, ${scheme}`;
      if (violations.length) {
        failures += violations.length;
        console.log(`✖ ${label}`);
        for (const line of violations) console.log(`    ${line}`);
      } else {
        console.log(`✔ ${label}`);
      }
      await context.close();
    }
  }
} finally {
  await browser.close();
  server.close();
}
if (failures) {
  console.log(`${failures} accessibility violation(s).`);
  process.exit(1);
}
console.log('No accessibility violations.');
