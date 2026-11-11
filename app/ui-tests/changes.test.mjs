// Changes in a run (js/changes.js): Mark and revise passes. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildChanges } from '../ui/js/changes.js';
import { withPlaces } from '../ui/js/format.js';

test('step texts name sections by place, not by id', () => {
  const places = new Map([['st1', '1.0 m'], ['st12', '12.0 m']]);
  assert.equal(withPlaces('Drew the section at st12', places), 'Drew the section at 12.0 m');
  assert.equal(withPlaces('Read the candidate lines of st1 and st12', places), 'Read the candidate lines of 1.0 m and 12.0 m');
  // Only whole ids: "st123" and "first1" are not sections.
  assert.equal(withPlaces('st123 first1 st1-a', places), 'st123 first1 st1-a');
  assert.equal(withPlaces('No sections here', new Map()), 'No sections here');
});

const box = { shape: 'box', tone: 'person', points_px: [[10, 20], [90, 80]] };

test('a Mark and revise pass is one entry with its instruction, edit and result', () => {
  const entries = buildChanges([
    { kind: 'revise', actor: 'person', title: 'Marked for revision', text: 'Too fine near the keel', marks: [box], targets: [{ kind: 'section', id: 'st12' }] },
    { kind: 'look', actor: 'code', title: 'Cropped the marked region', text: '' },
    { kind: 'propose_section', actor: 'model', title: 'Drew section st12', text: 'I redrew st12.', tool: { kept: false, text: 'Not kept: the fit got worse' } },
    { kind: 'revise', actor: 'code', title: 'Not kept: worse by 0.004', tool: { kept: false, text: 'Combined fit 0.931 -> 0.927' },
      mark_revision: { revision_id: 'r9', outcome: 'not_kept', fit_change: 0, not_kept_fit_change: -0.004, can_keep_anyway: true, operator_forced: false } },
  ]);
  assert.equal(entries.length, 1); // the not-kept edit is told in the pass, not twice
  const [pass] = entries;
  assert.equal(pass.kind, 'mark');
  assert.equal(pass.instruction, 'Too fine near the keel');
  assert.deepEqual(pass.sections, ['st12']);
  assert.equal(pass.why, 'I redrew st12.');
  assert.equal(pass.result.outcome, 'not_kept');
  assert.equal(pass.result.detail, 'Combined fit 0.931 -> 0.927');
  assert.equal(pass.forced, false);
});

test('Keep anyway marks the last pass as forced', () => {
  const entries = buildChanges([
    { kind: 'revise', actor: 'person', title: 'Marked for revision', text: 'Wrong line', marks: [box], targets: [] },
    { kind: 'revise', actor: 'code', title: 'Not kept', mark_revision: { outcome: 'not_kept', operator_forced: false } },
    { kind: 'revise', actor: 'person', title: 'Kept anyway', text: '', marks: [], targets: [] },
  ]);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].forced, true);
});

test('bare-number section ids never change dimensions in free text', () => {
  const places = new Map([['5', '50.1 m'], ['7', '70.1 m'], ['8', '80.1 m']]);
  assert.equal(withPlaces('LOA 99.76 m, beam 12.72 m, depth 7.63 m', places), 'LOA 99.76 m, beam 12.72 m, depth 7.63 m');
  assert.equal(withPlaces('Stations 3-8 carry authored sections', places), 'Stations 3-8 carry authored sections');
  assert.equal(withPlaces('Drew the section at 5', places), 'Drew the section at 50.1 m');
  assert.equal(withPlaces('Picked the line for 8', places), 'Picked the line for 80.1 m');
  assert.equal(withPlaces('Drew the section at 7.5 m', places), 'Drew the section at 7.5 m');
});
