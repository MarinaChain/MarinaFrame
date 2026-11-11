// How a run first shows (js/presentation.js): the web demo's manifest, else the run's own file.
// Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { presentationOf } from '../ui/js/presentation.js';

const fromRun = { concept: false, credit: 'Drawings: NTNU.', note: null, whole_vessel_first: true, section_lines: false, see_through: false };
const fromDemo = { concept: true, credit: null, note: null, whole_vessel_first: true, section_lines: false, see_through: true };

test('the desktop app uses the run file', () => {
  assert.deepEqual(presentationOf({ presentation: fromRun }), fromRun);
});

test('the web demo manifest wins over the run file', () => {
  assert.deepEqual(presentationOf({ demo: fromDemo, presentation: fromRun }), fromDemo);
});

test('a run without either has none', () => {
  assert.equal(presentationOf({}), null);
  assert.equal(presentationOf(null), null);
});
