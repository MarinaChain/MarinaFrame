// The hideable run-details column (js/details.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DETAILS_KEY, isDetailsOpen, storedDetails, reviewBadge, toggleNames } from '../ui/js/details.js';
import { shortcutCommand } from '../ui/js/keymap.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('the column is open by default and after broken storage', () => {
  assert.equal(isDetailsOpen(undefined), true);
  assert.equal(isDetailsOpen(null), true);
  assert.equal(isDetailsOpen('open'), true);
  assert.equal(isDetailsOpen('garbage'), true);
});

test('a hidden column is remembered', () => {
  assert.equal(storedDetails(false), 'closed');
  assert.equal(isDetailsOpen(storedDetails(false)), false);
  assert.equal(isDetailsOpen(storedDetails(true)), true);
});

test('the shortcut is the next free key after the layout keys', () => {
  assert.equal(DETAILS_KEY, '4');
  assert.match(read('../ui/js/shortcuts.js'), /\$\{MOD\}4`, 'Show or hide the details column'/);
  assert.deepEqual(shortcutCommand({ key: DETAILS_KEY, metaKey: true }), { command: 'details' });
  assert.deepEqual(shortcutCommand({ key: DETAILS_KEY, ctrlKey: true }), { command: 'details' });
  assert.equal(shortcutCommand({ key: DETAILS_KEY }), null, 'without ⌘ the key is free');
  for (const [key, layout] of [['1', 'drawing'], ['2', 'split'], ['3', 'model']]) {
    assert.deepEqual(shortcutCommand({ key, metaKey: true }), { command: 'layout', layout });
  }
});

test('the badge counts open review items and hides at zero', () => {
  assert.deepEqual(reviewBadge(0), { hidden: true, text: '0', items: 0 });
  assert.deepEqual(reviewBadge(3), { hidden: false, text: '3', items: 3 });
  assert.equal(reviewBadge(250).text, '99+');
  assert.equal(reviewBadge(undefined).hidden, true);
  assert.equal(reviewBadge(-2).hidden, true);
});

test('the toggle names say the action and the shortcut; the spoken name carries the count', () => {
  assert.deepEqual(toggleNames(true, 0), { title: 'Hide details (⌘4)', spoken: 'Hide details' });
  assert.deepEqual(toggleNames(false, 2), { title: 'Show details (⌘4)', spoken: 'Show details, 2 to check' });
});

test('the page has the toggle, the edge handle and a named column', () => {
  const html = read('../ui/index.html');
  for (const id of ['details-toggle', 'details-edge', 'details-count', 'inspector']) assert.ok(html.includes(`id="${id}"`), id);
  assert.match(html, /id="details-toggle"[^>]*data-tip-title="Hide details \(⌘4\)"/);
  assert.match(html, /id="details-edge"[^>]*hidden/);
});

test('the transition is short and off under reduced motion', () => {
  const css = read('../ui/styles.css');
  const ms = Number(css.match(/--dur-details:\s*(\d+)ms/)[1]);
  assert.ok(ms <= 150);
  assert.match(css, /prefers-reduced-motion: reduce\) \{\s*\.view-run, :root\[data-details="closed"\] \.inspector \{ transition: none/);
});

// ---- run-detail tabs as icons
import { TAB_META, TABS, tabAfter, tabName } from '../ui/js/details.js';

const TAB_IDS = ['thinking', 'timeline', 'checks', 'model', 'evidence', 'sources'];

test('every tab has an icon in the sprite, its word as title and a one-line detail', () => {
  const html = read('../ui/index.html');
  assert.deepEqual(Object.keys(TAB_META), TAB_IDS);
  for (const tab of TAB_IDS) {
    const meta = TAB_META[tab];
    assert.ok(html.includes(`<symbol id="i-${meta.icon}"`), `sprite icon ${meta.icon}`);
    assert.ok(meta.detail.length > 10 && meta.detail.length < 70 && !meta.detail.includes('\n'), `${tab} detail`);
  }
  assert.deepEqual(TAB_IDS.map((tab) => TAB_META[tab].word), ['Thinking', 'Steps', 'Checks', 'Calls', 'Evidence', 'Sources']);
});

test('the tab buttons keep their roles and carry no text in the page', () => {
  const html = read('../ui/index.html');
  for (const tab of TAB_IDS) assert.match(html, new RegExp(`role="tab"[^>]*data-tab="${tab}"></button>`));
});

test('the spoken name of a tab keeps the word and adds the count', () => {
  assert.equal(tabName('thinking'), 'Thinking');
  assert.equal(tabName('checks', 0, { failing: true }), 'Checks');
  assert.equal(tabName('checks', 2, { failing: true }), 'Checks, 2 failing');
  assert.equal(tabName('model', 5), 'Calls, 5');
});

test('the tab arrows still walk the six tabs', () => {
  assert.deepEqual(TABS, TAB_IDS);
  const walked = [TABS[0]];
  for (let i = 0; i < TABS.length; i += 1) walked.push(tabAfter(walked.at(-1), 'ArrowRight'));
  assert.deepEqual(walked, [...TAB_IDS, TAB_IDS[0]], 'ArrowRight walks every tab and wraps');
  assert.equal(tabAfter('thinking', 'ArrowLeft'), 'sources', 'ArrowLeft wraps to the last tab');
  assert.equal(tabAfter('checks', 'ArrowLeft'), 'timeline');
  assert.equal(tabAfter('checks', 'ArrowUp'), null, 'other keys do not move');
});
