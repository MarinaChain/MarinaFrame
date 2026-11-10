// The hideable run-details column (js/details.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DETAILS_KEY, isDetailsOpen, storedDetails, reviewBadge, toggleNames } from '../ui/js/details.js';

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
  assert.match(read('../ui/js/app.js'), /event\.key === DETAILS_KEY/);
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
