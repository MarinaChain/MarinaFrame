// Source view (js/provenance.js, docs/SOURCE_RECORD.md): records of a run's items, the sheets
// and boxes to show, and when the view opens. Run: npm run test:ui
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import {
  HOVER_DELAY_MS, LEAVE_DELAY_MS, MAX_SHEETS, NO_RECORD, STEEL_RECORD,
  createSourceController, partInputs, scaleBox, sheetsOf, sourceForSheet, sourceOf, summaryOf, viewBoxFor,
} from '../ui/js/provenance.js';

const region = (sheet, box = [100, 100, 200, 150], page = 0) => ({ sheet, page, view: 'plan', box_px: box, page_px: [1000, 500] });

function view() {
  return {
    sections: [
      { id: 'st4', x_m: 4, source_record: { kind: 'read', regions: [region('lines.pdf')] } },
      { id: 'st12', x_m: 12 },
    ],
    components: [
      { id: 'house', label: 'Deckhouse', source_record: { kind: 'read', regions: [region('ga.pdf')] } },
      { id: 'old', label: 'Old part' },
    ],
    capacity_plan: { rows: [
      { id: 'tank_wb1', name: 'Ballast 1', source_record: { kind: 'unknown', reason: 'not recorded' } },
      { id: 'house', name: 'not a tank', source_record: { kind: 'unknown', reason: 'row record' } },
    ] },
  };
}

test('records come from parts, capacity plan rows and sections; a part record wins over its row', () => {
  const v = view();
  assert.equal(sourceOf(v, { kind: 'part', id: 'house' }).record.kind, 'read');
  assert.equal(sourceOf(v, { kind: 'part', id: 'house' }).label, 'Deckhouse');
  assert.equal(sourceOf(v, { kind: 'part', id: 'tank_wb1' }).record.reason, 'not recorded');
  assert.equal(sourceOf(v, { kind: 'section', id: 'st4' }).label, 'Section at 4.0 m');
  assert.equal(sourceOf(v, { kind: 'section', id: 'st4' }).record.kind, 'read');
});

test('an older run without records says so, and steel groups are unknown for now', () => {
  const v = view();
  assert.equal(sourceOf(v, { kind: 'part', id: 'old' }).record, null);
  assert.equal(sourceOf(v, { kind: 'section', id: 'st12' }).record, null);
  assert.deepEqual(summaryOf(null), { tone: 'none', title: 'No source record', detail: NO_RECORD });
  assert.match(NO_RECORD, /run again/i);
  assert.equal(sourceOf(v, { kind: 'part', id: 'steel:bulkhead' }).record, STEEL_RECORD);
  assert.equal(summaryOf(STEEL_RECORD).tone, 'unknown');
});

test('sheets group regions by file and page; a region without a box still names its sheet', () => {
  const record = { kind: 'guessed', method: 'beam box', inputs: [
    region('ga.pdf'), region('ga.pdf', [300, 100, 400, 200]), { sheet: 'ga.dxf', page: 0, view: 'profile', box_px: null },
    { part: 'main_deck' }, region('ga.pdf', [1, 1, 2, 2], 1)] };
  const { sheets, more } = sheetsOf(record);
  assert.deepEqual(sheets.map((s) => [s.sheet, s.page, s.regions.length]), [['ga.pdf', 0, 2], ['ga.dxf', 0, 0], ['ga.pdf', 1, 1]]);
  assert.equal(more, 0);
  assert.deepEqual(partInputs(record), ['main_deck']);
  assert.equal(summaryOf(record).title, 'Best guess');
  const many = { kind: 'read', regions: Array.from({ length: 5 }, (_, i) => region(`s${i}.pdf`)) };
  assert.equal(sheetsOf(many).sheets.length, MAX_SHEETS);
  assert.equal(sheetsOf(many).more, 2);
  assert.deepEqual(sheetsOf({ kind: 'unknown', reason: 'x' }).sheets, []);
});

test('a box scales to the image shown and the view zooms around it with context', () => {
  // The record box is in a 1000 x 500 frame; the image shown is half that size.
  const box = scaleBox(region('ga.pdf'), { width: 500, height: 250 });
  assert.deepEqual(box, [50, 50, 100, 75]);
  const [x, y, w, h] = viewBoxFor([box], { width: 500, height: 250 });
  assert.ok(x < 50 && y < 50 && x + w > 100 && y + h > 75, 'the region is inside the view');
  assert.ok(w < 500, 'the view zooms in');
  assert.deepEqual(viewBoxFor([], { width: 500, height: 250 }), [0, 0, 500, 250]);
  // A region over most of the page shows the page, not a page shrunk inside empty space.
  const [bx, by, bw, bh] = viewBoxFor([[20, 20, 480, 230]], { width: 500, height: 250 });
  assert.ok(bw <= 520 && bh <= 260 && bx >= -10 && by >= -5 && bx + bw <= 510 && by + bh <= 255);
});

test('a sheet is found among the run sources by its file name', () => {
  const sources = [{ id: 'a', name: 'survey-launch-lines.pdf' }, { id: 'b', name: 'GA Rev1.pdf', location: 'input/GA Rev1.pdf' }];
  assert.equal(sourceForSheet(sources, 'survey-launch-lines.pdf').id, 'a');
  assert.equal(sourceForSheet(sources, 'polarkonsult/GA Rev1.pdf').id, 'b');
  assert.equal(sourceForSheet(sources, 'missing.pdf'), null);
});

/** A controller on a fake source view and mocked timers. */
function controller({ split = true } = {}) {
  const calls = [];
  const listeners = {};
  const sourceView = {
    element: { addEventListener: (type, fn) => { listeners[type] = fn; } },
    show: (item, source) => calls.push(['show', item.id, source.record?.kind ?? null]),
    close: () => calls.push(['close']),
  };
  const c = createSourceController({ view: () => view(), sourceView, canShow: () => split });
  return { c, calls, listeners };
}

test('hover shows the source after a short pause; a pointer passing over parts shows nothing', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { c, calls } = controller();
  c.hover({ kind: 'part', id: 'old' });
  t.mock.timers.tick(HOVER_DELAY_MS / 2);
  c.hover({ kind: 'part', id: 'house' });
  t.mock.timers.tick(HOVER_DELAY_MS - 1);
  assert.deepEqual(calls, []);
  t.mock.timers.tick(1);
  assert.deepEqual(calls, [['show', 'house', 'read']]);
  // Leaving closes it after a pause (time to move onto the sheet view).
  c.hover(null);
  t.mock.timers.tick(LEAVE_DELAY_MS);
  assert.deepEqual(calls.at(-1), ['close']);
});

test('the selected part shows at once and comes back when the hover ends (keyboard path)', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { c, calls } = controller();
  c.select({ kind: 'part', id: 'house' });
  assert.deepEqual(calls, [['show', 'house', 'read']]);
  c.hover({ kind: 'section', id: 'st12' });
  t.mock.timers.tick(HOVER_DELAY_MS);
  assert.deepEqual(calls.at(-1), ['show', 'st12', null]);
  c.hover(null);
  t.mock.timers.tick(0);
  assert.deepEqual(calls.at(-1), ['show', 'house', 'read']);
  c.select(null);
  assert.deepEqual(calls.at(-1), ['close']);
});

test('the pointer on the sheet view keeps it open; nothing shows when the drawing pane is hidden', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { c, calls, listeners } = controller();
  c.hover({ kind: 'part', id: 'house' });
  t.mock.timers.tick(HOVER_DELAY_MS);
  c.hover(null);
  listeners.pointerenter();
  t.mock.timers.tick(LEAVE_DELAY_MS * 2);
  assert.deepEqual(calls, [['show', 'house', 'read']]);
  listeners.pointerleave();
  t.mock.timers.tick(LEAVE_DELAY_MS);
  assert.deepEqual(calls.at(-1), ['close']);

  const hidden = controller({ split: false });
  hidden.c.select({ kind: 'part', id: 'house' });
  assert.deepEqual(hidden.calls, [['close']]);
});

test('a source view lookup is fast on a run with many sections and parts', () => {
  const big = {
    sections: Array.from({ length: 80 }, (_, i) => ({ id: `s${i}`, x_m: i, source_record: { kind: 'read', regions: [region('l.pdf')] } })),
    components: Array.from({ length: 600 }, (_, i) => ({ id: `p${i}`, label: `P${i}`, source_record: { kind: 'unknown', reason: 'x' } })),
  };
  const started = performance.now();
  for (let i = 0; i < 5000; i += 1) sourceOf(big, { kind: 'part', id: `p${i % 600}` });
  assert.ok(performance.now() - started < 200);
  assert.equal(sourceOf(big, { kind: 'part', id: 'p599' }).label, 'P599');
  mock.reset();
});
