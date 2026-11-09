// Accuracy summary (js/accuracy.js): the same cases as tests/test_accuracy_summary.py. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { summarise, factsOfView, detailText, band, OUTPUT_ICONS } from '../ui/js/accuracy.js';
import { BANDS } from '../ui/js/accuracy_bands.js';

const CASES = JSON.parse(readFileSync(new URL('../../tests/fixtures/accuracy_summary_cases.json', import.meta.url), 'utf8'));

for (const testCase of CASES) {
  test(`shared case: ${testCase.name}`, () => {
    const result = summarise(testCase.facts);
    for (const [output, expected] of Object.entries(testCase.expected)) {
      assert.equal(result[output].line, expected.line);
      assert.equal(result[output].chip, expected.chip);
      assert.equal(result[output].present, expected.present);
      assert.equal(result[output].caution, expected.caution);
      assert.deepEqual(result[output].detail_ids, expected.detail_ids);
    }
  });
}

test('every band has a source, a set and an N; the unmeasured one says so', () => {
  for (const b of BANDS) {
    assert.ok(b.source && b.section && b.n && b.short && b.chip, b.id);
    assert.ok(['development', 'holdout', 'none'].includes(b.dataset), b.id);
  }
  assert.deepEqual(BANDS.filter((b) => !b.measured).map((b) => b.id), ['steel.weight']);
});

test('the tooltip detail lists each band with its set, N and source, and keeps the draft note', () => {
  const hull = summarise({ hull: { path: 'scanned_body_plan', hull_type: 'round_bilge', labels: { traced: 3 } } }).hull;
  const text = detailText(hull);
  assert.match(text, /holdout; 1 sheet, 37 of 39 cells; docs\/WHOLE_VESSEL_GUNNERUS\.md s\.5\.9/);
  assert.match(text, /PARDON ME/);
  assert.match(text, /engineering_approved stays false/);
  assert.doesNotMatch(text, /verified|approved for/i);
});

test('no wording of any output claims approval or verification', () => {
  for (const testCase of CASES) {
    for (const summary of Object.values(summarise(testCase.facts))) {
      assert.doesNotMatch(summary.line, /approved|verified/i);
    }
  }
});

test('facts come from a task view: source counts, sections to check, tanks and structure files', () => {
  const view = {
    source_counts: [{ label: 'traced', count: 4 }, { label: 'ai_inferred', count: 1 }],
    sections: [{ state: 'chosen' }, { state: 'guessed' }, { state: 'declined' }],
    body_plan_check: { used: true },
    tank_model: true,
    capacity_plan: { rows: [{ built: true, sources: { volume: 'traced' } }, { built: true, sources: {} }, { built: false, sources: {} }] },
    structure_files: [{ role: 'steel_members' }],
  };
  assert.deepEqual(factsOfView(view), {
    hull: { path: 'scanned_body_plan', hull_type: null, labels: { traced: 4, ai_inferred: 1 }, to_check: 2, fit: null },
    tanks: { built: 2, total: 3, path: null, volume_labels: { traced: 1, guessed: 1 } },
    steel: { thickness_labels: null },
  });
  const bare = factsOfView({ source_counts: [], sections: [], structure_files: [] });
  assert.equal(bare.tanks, null);
  assert.equal(bare.steel, null);
  assert.equal(bare.hull.path, 'model_reading');
});

test('each output has a chip icon and a band', () => {
  assert.deepEqual(Object.keys(OUTPUT_ICONS), ['hull', 'tanks', 'steel']);
  assert.equal(band('hull.scanned_bue_girl').chip, '1.4 mm');
});
