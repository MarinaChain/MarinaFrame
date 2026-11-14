// Design mapping contract: unknowns, deviations, empty evidence and risk retention.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  designView, designRows, designQuantity, designSections, designMissing, designMissingKey, designDigits,
  designChanges, designParticulars, designWarningGroups,
} from '../ui/js/design_view.js';
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
  const variant = JSON.parse(await readFile(new URL('../ui/mock/files/designs/kvlcc2-candidate-c.json', import.meta.url)));
  assert.equal(variant.lineage.parent_design_id, record.design_id);
  assert.equal(variant.lineage.variation_parameters.cb.value, record.lineage.variation_parameters.cb.value - 0.01);
  assert.ok(designView(variant).warnings.some((row) => String(row.value).includes('not recalculated')));
});

test('main particulars keep every card slot; absent results are not calculated yet', () => {
  const cards = designParticulars(record);
  assert.equal(cards.length, 11);
  const deadweight = cards.find((card) => card.key === 'deadweight');
  assert.equal(deadweight.kind, 'unknown');
  assert.equal(deadweight.missingKey, 'design.pending');
  assert.equal(cards.find((card) => card.key === 'depth').missingKey, 'design.notSupplied');
  assert.deepEqual(designParticulars(record, { lite: true }).map((card) => card.key),
    ['length', 'beam', 'draft', 'deadweight', 'cargo_capacity', 'fuel', 'service_speed']);
});

test('a missing calculation input is not supplied; a missing result is not calculated yet', () => {
  assert.equal(designMissingKey('results.resistance.inputs.aft_draft_m'), 'design.notSupplied');
  assert.equal(designMissingKey('results.stability'), 'design.pending');
  assert.equal(designMissingKey('requirements.flag'), 'design.notSupplied');
});

test('performance sections follow the calculation order and keep methods and unknowns', () => {
  const sections = designSections(designView(record).performance);
  assert.deepEqual([...new Set(sections.map((section) => section.topic))], ['resistance', 'power', 'fuel']);
  const output = sections.find((section) => section.path === 'results.resistance.output');
  assert.ok(output.method);
  assert.ok(output.rows.every((row) => !/validity_warnings|engineering_approved|\.method$/.test(row.path)));
  const inputs = sections.find((section) => section.path === 'results.resistance.inputs');
  assert.ok(inputs.rows.some((row) => row.path.endsWith('aft_draft_m') && row.kind === 'unknown'));
  const empty = designSections(designView(record).weights);
  assert.ok(empty.some((section) => section.path === 'results.stability' && section.rows[0].kind === 'empty'));
});

test('warnings group by topic and none is lost', () => {
  const view = designView(record);
  const groups = designWarningGroups(view.warnings);
  assert.equal(groups.reduce((sum, group) => sum + group.warnings.length, 0), view.warnings.length);
  assert.ok(groups.some((group) => group.topic === 'resistance'));
});

test('missing values list results and inputs once, without empty warning lists', () => {
  const { pending, notSupplied } = designMissing(record);
  const paths = [...pending, ...notSupplied].map((row) => row.path);
  assert.equal(new Set(paths).size, paths.length);
  assert.ok(pending.some((row) => row.key === 'deadweight'));
  assert.ok(notSupplied.some((row) => row.path === 'requirements.flag'));
  assert.ok(!paths.some((path) => /warnings$|hull_variation/.test(path)));
  assert.ok(!paths.includes('results.capacities'), 'its particulars already show it');
});

test('summary digits round for reading, not for evidence', () => {
  assert.equal(designDigits(292003.879), 0);
  assert.equal(designDigits(20.8), 1);
  assert.equal(designDigits(1.143), 2);
  assert.equal(designDigits(0.914), 3);
  assert.equal(designDigits(0.0002), null);
  assert.equal(designDigits(0), 3);
});

test('a change from the parent states the parent value and the signed difference', async () => {
  const variant = JSON.parse(await readFile(new URL('../ui/mock/files/designs/kvlcc2-candidate-c.json', import.meta.url)));
  const [change] = designChanges(variant, record);
  assert.equal(change.key, 'cb');
  assert.equal(change.base.value, record.lineage.variation_parameters.cb.value);
  assert.equal(change.delta, -0.01);
  assert.equal(designChanges(variant, null)[0].delta, null);
});

test('the missing list leaves out record keeping: customer ID and decisions', () => {
  const paths = designMissing(record).notSupplied.map((row) => row.key || row.path);
  assert.ok(!paths.includes('data_scope.customer_id'));
  assert.ok(!paths.includes('designer_decisions'));
  assert.ok(paths.includes('tanks'), 'real design inputs stay listed');
});
