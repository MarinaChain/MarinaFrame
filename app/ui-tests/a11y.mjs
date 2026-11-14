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
async function prepare({ vessel, tab, vesselTab, open, designTab }) {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (designTab) { document.getElementById(`design-tab-${designTab}`).click(); await wait(300); }
  if (open === 'decision-errors') { document.querySelector('.decision-form button[type="submit"]').click(); await wait(200); }
  if (open === 'design-warnings') { document.querySelector('.design-advanced .design-warning-toggle').click(); await wait(200); }
  if (vessel) {
    const card = [...document.querySelectorAll('#vessel-grid > *')].find((c) => c.textContent.includes(vessel));
    (card.querySelector('button, a') || card).click();
    await wait(2000);
  }
  if (tab) { document.getElementById(`tab-${tab}`).click(); await wait(1200); }
  if (vesselTab) { document.querySelector(`[data-vtab="${vesselTab}"]`).click(); await wait(800); }
  if (open === 'intake') { document.getElementById('drop-choose').click(); await wait(2000); }
  if (open === 'palette') { document.getElementById('open-palette').click(); await wait(300); }
  if (open === 'batch' || open === 'batch-queue') { document.getElementById('drop-choose-folder').click(); await wait(700); }
  if (open === 'batch-queue') { document.querySelector('.batch-actions .btn-primary').click(); await wait(900); }
  if (open === 'usage') { document.getElementById('check-usage').click(); await wait(900); }
  if (open === 'part-rerun' || open === 'part-revision') {
    // Mark the wheelhouse with a note, then re-run it (the mock takes 3 s).
    const button = (text) => [...document.querySelectorAll('.parts-page button')].find((b) => b.textContent.startsWith(text));
    button('Wheelhouse').click(); await wait(200);
    button('Mark').click(); await wait(200);
    const note = document.querySelector('.parts-mark textarea');
    note.value = 'Too high: the roof is at 8.0 m';
    note.dispatchEvent(new Event('input'));
    document.querySelector('.parts-mark .btn-primary').click(); await wait(900);
    button('Re-run with this note').click();
    await wait(open === 'part-rerun' ? 500 : 4000);
  }
  if (open === 'tank') {
    // Select the mock tank: its capacity plan row and its sounding table show.
    [...document.querySelectorAll('.parts-page .parts-row')].find((b) => b.textContent.includes('fresh water')).click();
    await wait(400);
  }
  if (open === 'value-display') {
    const { valueDisplay } = await import('/js/value_display.js');
    const { createGaPanel } = await import('/js/ga_panel.js');
    const panel = createGaPanel({ onHover() {}, onSelect() {} });
    panel.set({
      particulars: { loa_m: { value: 123.45, status: 'read', printed: '123.45 m' } },
      counts: { cargo_holds: { value: 0, status: 'guessed' } },
      measured: { lbp_m: { value: 120, status: 'unconfirmed_from_uncertain_boxes' } },
    });
    const main = document.querySelector('main');
    main.replaceChildren(main.querySelector('h1'), panel.element,
      valueDisplay({ value: 1234.5, unit: 'm', uncertainty: { plusMinus: 2 }, method: 'empirical', status: 'needs_review', source: 'Synthetic source' }),
      valueDisplay({ value: null, unit: 'm', method: 'cfd' }));
  }
  if (open === 'shortcuts') { document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true })); await wait(300); }
}

const SCREENS = [
  { name: 'designs', path: '/#designs' },
  { name: 'design overview', path: '/#design/public-kvlcc2-example' },
  { name: 'design performance', path: '/#design/public-kvlcc2-example', steps: { designTab: 'performance' } },
  { name: 'design provenance', path: '/#design/public-kvlcc2-example', steps: { designTab: 'provenance' } },
  { name: 'design variant (change from parent)', path: '/#design/synthetic-kvlcc2-candidate-c' },
  { name: 'design all warnings', path: '/#design/public-kvlcc2-example', steps: { open: 'design-warnings' } },
  { name: 'design requirements', path: '/#design/public-kvlcc2-example', steps: { designTab: 'requirements' } },
  { name: 'design weights (empty sections)', path: '/#design/public-kvlcc2-example', steps: { designTab: 'weights' } },
  // Phase 2: a project's tabs open from a deep link (#design/<id>/<tab>).
  { name: 'design candidates', path: '/#design/public-kvlcc2-example/candidates' },
  { name: 'design compare (Pareto chart)', path: '/#design/public-kvlcc2-example/compare' },
  { name: 'design decisions', path: '/#design/public-kvlcc2-example/decisions' },
  { name: 'design decisions (form errors)', path: '/#design/public-kvlcc2-example/decisions', steps: { open: 'decision-errors' } },
  { name: 'design compare (Korean)', path: '/#design/public-kvlcc2-example/compare', prefs: { language: 'ko' } },
  { name: 'design decisions (Korean)', path: '/#design/public-kvlcc2-example/decisions', prefs: { language: 'ko' } },
  { name: 'design Lite', path: '/#design/public-kvlcc2-example', prefs: { interfaceMode: 'lite' } },
  { name: 'design Lite (Korean)', path: '/#design/public-kvlcc2-example', prefs: { language: 'ko', interfaceMode: 'lite' } },
  { name: 'welcome', path: '/?mocknokey#home', seen: false },
  { name: 'home', path: '/#home' },
  { name: 'value display and GA rows', path: '/#home', steps: { open: 'value-display' } },
  { name: 'value display and GA rows (Korean)', path: '/#home', prefs: { language: 'ko' }, steps: { open: 'value-display' } },
  { name: 'home (first start)', path: '/?mockempty#home' },
  { name: 'queue', path: '/#queue' },
  { name: 'batch sheet', path: '/#home', steps: { open: 'batch' } },
  { name: 'queue (waiting sets)', path: '/?mockbatchfail#home', steps: { open: 'batch-queue' } },
  { name: 'settings', path: '/#settings' },
  { name: 'settings (Korean, Lite)', path: '/#settings', prefs: { language: 'ko', interfaceMode: 'lite' } },
  { name: 'settings (key usage)', path: '/?mockusagefull#settings', steps: { open: 'usage' } },
  { name: 'intake', path: '/#home', steps: { open: 'intake' } },
  { name: 'intake (10 sheets)', path: '/?mockset=10#home', steps: { open: 'intake' } },
  { name: 'intake (drawing set, one required drawing missing)', path: '/?mockdrawings#home', steps: { open: 'intake' } },
  { name: 'run (draft)', path: '/#home', steps: { vessel: 'Survey' } },
  { name: 'run (declined)', path: '/#home', steps: { vessel: 'Passenger' } },
  { name: 'checks', path: '/#home', steps: { vessel: 'Survey', tab: 'checks' } },
  { name: 'export', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'export' } },
  { name: 'history', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'history' } },
  { name: 'parts', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'parts' } },
  { name: 'parts (re-run)', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'parts', open: 'part-rerun' } },
  { name: 'parts (new revision)', path: '/#home', steps: { vessel: 'Survey', vesselTab: 'parts', open: 'part-revision' } },
  { name: 'parts (tank tables)', path: '/?mocktanks#home', steps: { vessel: 'Survey', vesselTab: 'parts', open: 'tank' } },
  { name: 'export (tank tables)', path: '/?mocktanks#home', steps: { vessel: 'Survey', vesselTab: 'export' } },
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
      if (screen.seen !== false) {
        await page.addInitScript((prefs) => localStorage.setItem('marinaframe.ui', JSON.stringify({ setupSeen: true, ...prefs })), screen.prefs || {});
      }
      await page.goto(base + screen.path);
      await page.waitForTimeout(1500);
      if (screen.name.startsWith('design')) {
        const selector = screen.path.endsWith('#designs') ? '#view-designs tbody tr' : '#design-tab-overview';
        await page.waitForSelector(selector, { state: 'attached' });
        if (await page.locator('#view-designs [role="alert"]').count()) throw new Error('Design did not load');
      }
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
