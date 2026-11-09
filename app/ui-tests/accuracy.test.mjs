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

test('the tooltip detail is at most three lines, names the set, and carries no doc paths', () => {
  for (const testCase of CASES) {
    for (const summary of Object.values(summarise(testCase.facts)).filter((s) => s.present)) {
      const lines = detailText(summary).split('\n');
      assert.ok(lines.length <= 3, `${summary.output}: ${lines.length} lines`);
      assert.doesNotMatch(detailText(summary), /docs\/|\.md|s\.\d/);
      assert.doesNotMatch(detailText(summary), /verified|approved for/i);
    }
  }
  const hull = summarise({ hull: { path: 'scanned_body_plan', hull_type: 'round_bilge', labels: { traced: 3 } } }).hull;
  assert.match(detailText(hull), /holdout/);
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

test('invalid bands never appear in run summaries or chips', () => {
  const invalid = band('hull.scanned_bumble_bee');
  assert.equal(invalid.outcome, 'invalid');
  for (const hull_type of [null, 'round_bilge', 'hard_chine']) {
    for (const summary of Object.values(summarise({ hull: { path: 'scanned_body_plan', hull_type } }))) {
      assert.ok(![...summary.head_ids, ...summary.detail_ids].includes(invalid.id));
      assert.ok(!summary.line.includes(invalid.short));
      assert.ok(!summary.chip.includes(invalid.chip));
      assert.ok(!detailText(summary).includes(invalid.short));
    }
  }
});

test('each output has a chip icon and a band', () => {
  assert.deepEqual(Object.keys(OUTPUT_ICONS), ['hull', 'tanks', 'steel']);
  assert.equal(band('hull.scanned_bue_girl').chip, '1.4 mm');
});
