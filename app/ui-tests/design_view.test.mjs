// Design mapping contract: unknowns, deviations, empty evidence and risk retention.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { designView, designRows, designQuantity } from '../ui/js/design_view.js';
import { formatQuantity } from '../ui/js/value_display.js';
const record = JSON.parse(await readFile(new URL('../../tests/fixtures/design_record/kvlcc2.json', import.meta.url)));

test('public record retains unknowns, empty lists and lineage', () => {
  const view = designView(record);
  assert.equal(view.lineage.parent_design_id, 'public-kvlcc2-retained');
  assert.deepEqual(view.scope.permitted_uses, ['development']);
  assert.ok(view.unknowns.some((row) => row.path === 'requirements.flag'));
  assert.ok(view.unknowns.some((row) => row.kind === 'unknown' && row.path.startsWith('results.')));
  assert.deepEqual(view.arrangement.map((row) => row.kind), ['empty', 'empty']);
  assert.ok(view.weights.some((row) => row.path === 'results.stability' && row.kind === 'empty'));
  for (const row of view.unknowns) assert.ok(view.lite.some((item) => item.path === row.path));
});
test('all validity warnings survive and inputs remain visible', () => {
  const view = designView(record);
  assert.ok(view.warnings.some((row) => String(row.value).includes('auxiliary')));
  assert.ok(view.performance.some((row) => row.path === 'results.fuel.inputs.sfoc_g_per_kwh'));
  assert.equal(view.provenance.length, designRows(record).filter((row) => row.kind === 'quantity').length);
});
test('absolute and relative uncertainties are deviations, not endpoints', () => {
  const quantity = { ...record.main_dimensions.length, value: 100, uncertainty: { kind: 'absolute', lower: 2, upper: 3 } };
  assert.deepEqual(designQuantity(quantity).uncertainty, { low: 98, high: 103 });
  quantity.uncertainty = { kind: 'relative', lower: 0.02, upper: 0.03 };
  assert.deepEqual(designQuantity(quantity).uncertainty, { low: 98, high: 103 });
  assert.equal(designQuantity(record.main_dimensions.length).uncertainty, null);
});
test('free-text methods use a short readable label', () => {
  const method = record.main_dimensions.length.method;
  const formatted = formatQuantity({ value: 1, method });
  assert.ok(formatted.methodText.length <= 24);
  assert.ok(formatted.methodText.startsWith('public KVLCC2'));
  assert.equal(formatQuantity({ value: 1, method: 'empirical' }).methodText, 'Empirical');
});
test('mapping preserves zero, review status and the input record', () => {
  const source = structuredClone(record);
  source.main_dimensions.length.value = 0;
  source.main_dimensions.length.status = 'review_required';
  const before = JSON.stringify(source);
  const view = designView(source);
  const length = view.overview.find((row) => row.path === 'main_dimensions.length');
  assert.equal(length.kind, 'quantity');
  assert.equal(designQuantity(length.quantity).value, 0);
  assert.equal(designQuantity(length.quantity).status, 'needs_review');
  assert.equal(JSON.stringify(source), before);
});

test('synthetic variant keeps its parent and states inherited evidence limits', async () => {
  const variant = JSON.parse(await readFile(new URL('../ui/mock/files/designs/kvlcc2-cb-variant.json', import.meta.url)));
  assert.equal(variant.lineage.parent_design_id, record.design_id);
  assert.equal(variant.lineage.variation_parameters.cb.value, record.lineage.variation_parameters.cb.value + 0.01);
  assert.ok(designView(variant).warnings.some((row) => String(row.value).includes('not recalculated')));
});
