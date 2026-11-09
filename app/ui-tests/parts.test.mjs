// Part list copy (js/parts.js): no spreadsheet formulas from labels or notes. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safeTextCell, partTableText, plainReason, withoutHandles, canRerun, elapsedText, partState, outlinePolygons } from '../ui/js/parts.js';

test('a marked part with a note can be re-run; a hull or a pending revision cannot', () => {
  const marked = { op: 'deckhouse', review: 'marked', review_note: 'Too high', revision_pending: false };
  assert.equal(canRerun(marked), true);
  assert.equal(canRerun({ ...marked, review: 'accepted' }), false);
  assert.equal(canRerun({ ...marked, review_note: null }), false);
  assert.equal(canRerun({ ...marked, op: 'hull' }), false);
  assert.equal(canRerun({ ...marked, revision_pending: true }), false);
});

test('a new revision waits for Keep or Undo, in AI teal and never as approved', () => {
  const state = partState({ review: 'marked', review_note: 'x', revision_pending: true, built: true });
  assert.equal(state.word, 'New revision');
  assert.equal(state.tone, 'ai');
  assert.doesNotMatch(`${state.word} ${state.title}`, /approved|verified/i);
});

test('the re-run clock reads minutes and seconds', () => {
  assert.equal(elapsedText(0), '0:00');
  assert.equal(elapsedText(65_400), '1:05');
  assert.equal(elapsedText(-5), '0:00');
});

test('CAD entity handles are left out of shown text', () => {
  // Made-up handles in the shape of DXF ones.
  assert.equal(withoutHandles('from the plan (1A2B3C4D5E6F, 1A2B3C4D5E70); breadth'), 'from the plan; breadth');
  assert.equal(withoutHandles('the block linework (A$C0000ABCD1) below'), 'the block linework below');
  assert.equal(withoutHandles('stray 0000FFFF1111 handle'), 'stray handle');
  // Plain words, station names and short codes stay.
  assert.equal(withoutHandles('Label MAIN DECK, ST 12, DXF R2018'), 'Label MAIN DECK, ST 12, DXF R2018');
  assert.equal(withoutHandles('BULWARKHEIGHT is not a handle'), 'BULWARKHEIGHT is not a handle');
});

test('ship-cad reasons read as plain sentences', () => {
  assert.equal(plainReason('mast_outline: missing or invalid measurement; mast_height: missing or invalid measurement'),
    'Outline: not read from the drawing. Height: not read from the drawing.');
  assert.equal(plainReason('aft_bulwark_thickness: guessed: GA gives no bulwark thickness'),
    'Thickness: guessed (GA gives no bulwark thickness).');
  assert.equal(plainReason('Component identity needs human review'),
    'Every value was read from the drawing. Check that this is the right part.');
  assert.equal(plainReason('ValueError: invalid or empty CAD solid'), 'ValueError: invalid or empty CAD solid.');
});

test('text cells that a spreadsheet would run as a formula get a leading quote', () => {
  for (const cell of ['=HYPERLINK("x")', '+1', '-2+3', '@SUM(A1)', '\t=1', '\r=1']) {
    assert.ok(safeTextCell(cell).startsWith("'"), cell);
  }
  assert.equal(safeTextCell('Main deck'), 'Main deck');
  assert.equal(safeTextCell('a\tb\nc\r\nd'), 'a b c d'); // one line, no extra columns
  assert.equal(safeTextCell(null), '');
});

test('numbers stay numbers; label and note are made safe', () => {
  const part = {
    label: '=cmd|"/c calc"!A1', op: 'deck', built: true, status: 'draft_guess',
    bbox_m: { min: [-3.2, -3.6, 0], max: [9, 3.6, 3.4] }, volume_m3: 12.5,
    arguments: [{ source: 'traced' }, { source: 'guessed' }],
    review: 'marked', review_note: '-0.1 m lower\tplease',
  };
  const [header, row, stamp] = partTableText([part]).trim().split('\n');
  const cells = row.split('\t');
  assert.equal(cells.length, header.split('\t').length);
  assert.equal(cells[0], `'=cmd|"/c calc"!A1`);
  assert.equal(cells[4], '-3.200'); // a real number keeps its minus sign, unquoted
  assert.equal(cells[13], "'-0.1 m lower please");
  assert.match(stamp, /engineering_approved: false/);
});

test('a sign-off line keeps the fixed words and stays a draft', () => {
  const text = partTableText([], { name: 'A. Architect', time_ms: Date.UTC(2026, 10, 9), statement: 'usable as a starting model' });
  assert.match(text, /Signed off by A\. Architect, 2026-11-09: usable as a starting model\./);
  assert.match(text, /engineering_approved: false/);
  assert.doesNotMatch(text, /approved by|verified/i);
});

test('a tank sketch uses its outline polygons from the run; other parts keep their box', () => {
  const tank = { display: { profile_m: [[[4, 0.2], [7, 0.2], [7, 1.4]], [[1, 1]]], plan_m: [], content_class: 'fresh_water' } };
  assert.deepEqual(outlinePolygons(tank, 2), [[[4, 0.2], [7, 0.2], [7, 1.4]]]);
  assert.equal(outlinePolygons(tank, 1), null);
  assert.equal(outlinePolygons({ bbox_m: {} }, 2), null);
});
