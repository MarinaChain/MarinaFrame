// Run view, geometry first (lane K, docs/plans/2026-11-11-run-view-focus.md): the words of the
// run bar and its drawer, the one-row 3D tool bar, and the "best guess" label kept off it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { statusSentence, reviewWords, errorWords, costWords, problemSheets } from '../ui/js/run_status.js';
import { splitToolbar } from '../ui/js/controls3d.js';
import { labelSpot, GUESS_LABEL_SIZE } from '../ui/js/provenance.js';

const section = (id, state) => ({ id, x_m: 4, state });
const view = (overrides = {}) => ({
  summary: { status: 'draft' },
  sections: [section('st4', 'guessed'), section('st12', 'declined'), section('st20', 'chosen')],
  source_counts: [{ label: 'traced', count: 1 }, { label: 'interpolated', count: 1 }, { label: 'ai_corrected', count: 1 }],
  warnings: ['At 12.0 m: interpolated.', 'At 4.0 m: faired.'],
  sheet_review: { sheets: [
    { id: 'ga', label: 'GA', status: 'ok', reason: '' },
    { id: 'lines', label: 'Lines plan', status: 'unreadable', reason: 'Lines too faint.' },
  ] },
  activity: { requests: 3, list_cost_usd: 0.0121, list_cost_complete: true },
  ...overrides,
});

test('the status sentence says the status, what waits for the person, and the sheet to replace', () => {
  const { parts, action } = statusSentence(view());
  assert.deepEqual(parts, ['Draft', '2 sections need you', 'Lines plan: lines too faint']);
  assert.deepEqual(action, { kind: 'replace', sheetId: 'lines', label: 'Lines plan' });
});

test('one section reads "needs"; more bad sheets are counted; a sheet without a reason names its state', () => {
  const sheets = [
    { id: 'a', label: 'Lines plan', status: 'missing', reason: '' },
    { id: 'b', label: 'GA', status: 'wrong_scale', reason: 'Confirm the scale.' },
  ];
  const { parts, action } = statusSentence(view({ sections: [section('st4', 'guessed')], sheet_review: { sheets } }));
  assert.deepEqual(parts, ['Draft', '1 section needs you', 'Lines plan: missing (+1 more)']);
  assert.equal(action.sheetId, 'a');
  assert.equal(problemSheets(view({ sheet_review: { sheets } })).length, 2);
});

test('a run with nothing to do says so and has no action', () => {
  const { parts, action } = statusSentence(view({ sections: [section('st4', 'chosen')], sheet_review: null }));
  assert.deepEqual(parts, ['Draft', 'nothing to check']);
  assert.equal(action, null);
  assert.deepEqual(statusSentence(null), { parts: [], action: null });
});

test('the review is in words, not glyph codes', () => {
  assert.equal(reviewWords(view()), '1 traced · 1 interpolated · 1 AI corrected · 2 warnings');
  assert.equal(reviewWords(view({ source_counts: [], warnings: ['x'] })), '1 warning');
  assert.equal(reviewWords(view({ source_counts: [], warnings: [] })), '');
});

test('the hull error band reads as a distance from the drawing', () => {
  assert.equal(errorWords('0.8-14 %'), '0.8–14 % from the drawing');
  assert.equal(errorWords('3 %'), '3 % from the drawing');
});

test('costs are words for History and the drawer; none without model activity', () => {
  assert.equal(costWords(view()), '3 model requests · $0.0121 list cost');
  assert.match(costWords(view({ activity: { requests: 1, list_cost_usd: 0.5, list_cost_complete: false } })), /^1 model request · at least /);
  assert.equal(costWords(view({ activity: null })), null);
});

test('the 3D tool bar keeps every group when they fit in one row', () => {
  assert.equal(splitToolbar([200, 80, 150, 180], 640, { gap: 6, moreWidth: 36 }), 4);
});

test('groups that do not fit go to More, which keeps its own room; the first group always stays', () => {
  // 200 + 6 + 80 + 6 + 150 = 442; with More (6 + 36) = 484 <= 500, the fourth group moves.
  assert.equal(splitToolbar([200, 80, 150, 180], 500, { gap: 6, moreWidth: 36 }), 3);
  // 200 + 6 + 80 + (6 + 36) = 328: two groups fit in 330, one in 300.
  assert.equal(splitToolbar([200, 80, 150, 180], 330, { gap: 6, moreWidth: 36 }), 2);
  assert.equal(splitToolbar([200, 80, 150, 180], 300, { gap: 6, moreWidth: 36 }), 1);
  assert.equal(splitToolbar([200, 80, 150, 180], 100, { gap: 6, moreWidth: 36 }), 1);
});

test('a hidden group takes no room in the row', () => {
  assert.equal(splitToolbar([200, 0, 150, 180], 542, { gap: 6, moreWidth: 36 }), 4);
});

test('the best-guess label sits near the part, and slides along its line off the tool bar', () => {
  const from = { x: 100, y: 200 };
  const to = { x: 600, y: 0 };
  const first = labelSpot(from, to, []);
  assert.deepEqual(first, { x: 210, y: 146 });
  const toolbar = { left: 150, top: 100, right: 400, bottom: 160 };
  const moved = labelSpot(from, to, [toolbar]);
  const clear = moved.x - GUESS_LABEL_SIZE.width / 2 >= toolbar.right || moved.y + GUESS_LABEL_SIZE.height / 2 <= toolbar.top
    || moved.y - GUESS_LABEL_SIZE.height / 2 >= toolbar.bottom || moved.x + GUESS_LABEL_SIZE.width / 2 <= toolbar.left;
  assert.ok(clear, `label at ${JSON.stringify(moved)} covers the tool bar`);
  assert.ok(moved.x > first.x, 'the label moved along the line, away from the part');
});

test('with no clear place on the line, the label keeps its first place', () => {
  const everywhere = { left: -1e4, top: -1e4, right: 1e4, bottom: 1e4 };
  assert.deepEqual(labelSpot({ x: 0, y: 0 }, { x: 100, y: 0 }, [everywhere]), { x: 22, y: -10 });
});
