// Part list copy (js/parts.js): no spreadsheet formulas from labels or notes. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safeTextCell, partTableText } from '../ui/js/parts.js';

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
