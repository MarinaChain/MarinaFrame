// Pure comparison contract tests, including unknown values and synthetic trade-offs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { designProject, compareRows, constraintChecks, paretoPoints, currentDecisions } from '../ui/js/design_compare.js';

const q = (value, unit, uncertainty = null) => ({ value, unit, uncertainty, sources: [], method_version: '1', status: 'draft' });
function record(id, fuel = 70, cargo = 340000) {
  return { design_id: id, lineage: { parent_design_id: 'parent' },
    main_dimensions: { draft: q(20.8, 'm') }, requirements: { quantities: {} },
    results: { fuel: { value: { kind: 'quantity', value: q(fuel, 't/day', { kind: 'absolute', lower: 2, upper: 2 }) } },
      capacities: { cargo_capacity_m3: { kind: 'quantity', value: q(cargo, 'm3', { kind: 'relative', lower: 0.01, upper: 0.01 }) } } } };
}

test('project resolves a unique parent and direct children only', () => {
  const parent = record('parent');
  const child = record('a');
  const grandchild = record('b'); grandchild.lineage.parent_design_id = 'a';
  assert.deepEqual(designProject([parent, child, grandchild], 'parent'), { parent, candidates: [child] });
  assert.deepEqual(designProject([child], 'missing'), { parent: null, candidates: [] });
  assert.equal(designProject([parent, parent], 'parent').parent, null);
});

test('rows retain quantities, deviations, deltas and unknown states', () => {
  const parent = record('parent'); const candidate = record('a', 63, 350000);
  const rows = compareRows(parent, [candidate]);
  const fuel = rows.find((row) => row.path === 'results.fuel.value').candidates[0];
  assert.equal(fuel.delta, -7); assert.equal(fuel.deltaPercent, -10);
  assert.deepEqual(fuel.band, { low: 61, high: 65 });
  assert.equal(rows.find((row) => row.path === 'results.power.brake_power_kw').parent.state, 'unknown');
  parent.results.fuel.value.value.value = 0;
  assert.equal(compareRows(parent, [candidate]).find((row) => row.path === 'results.fuel.value').candidates[0].deltaPercent, null);
  parent.results.fuel.value.value.unit = 'kg';
  assert.equal(compareRows(parent, [candidate]).find((row) => row.path === 'results.fuel.value').candidates[0].delta, null);
});

test('constraints check each supported quantity and preserve unsupported or missing values', () => {
  const r = record('a');
  r.requirements.quantities = { max_draft: q(20.7, 'm'), min_cargo_volume: q(340000, 'm3'),
    max_fuel_per_day: q(70, 't/day'), other: q(1, 'm') };
  assert.deepEqual(constraintChecks(r).map((check) => check.state), ['fail', 'pass', 'pass', 'unknown']);
  delete r.results.fuel;
  assert.equal(constraintChecks(r)[2].state, 'unknown');
  r.requirements.quantities.max_draft.unit = 't';
  assert.equal(constraintChecks(r)[0].state, 'unknown');
});

test('Pareto reference is fixed; competitors use central values and overlapping bands', () => {
  const parent = record('parent', 60, 360000);
  const points = paretoPoints(parent, [record('a', 65, 345000), record('b', 66, 344000), record('c', 75, 330000)]);
  assert.equal(points[0].reference, true); assert.equal(points[0].dominated, false);
  assert.equal(points[1].dominated, false); assert.equal(points[2].dominated, true);
  assert.deepEqual(points[1].indistinguishable, ['b']);
  assert.deepEqual(points[2].indistinguishable, ['a']);
  const missing = record('missing'); delete missing.results.fuel;
  assert.equal(paretoPoints(parent, [missing])[1].x, null);
  missing.results.fuel = { value: { kind: 'quantity', value: q(1, 'kg') } };
  assert.equal(paretoPoints(parent, [missing])[1].x, null);
});

test('decision views retain the latest per discipline without changing history', () => {
  const d = { candidate_id: 'a', discipline: 'structure', recorded_at: '2026-11-14T00:00:00Z', action: 'deferred' };
  const newer = { ...d, recorded_at: '2026-11-14T01:00:00Z', action: 'accepted' };
  const other = { ...d, discipline: 'machinery' };
  const history = [newer, d, other];
  assert.deepEqual(currentDecisions(history), [newer, other]); assert.equal(history.length, 3);
  assert.equal(currentDecisions([d, { ...d, action: 'rejected' }])[0].action, 'rejected');
});

/* ---------- Project tab views ---------- */

import {
  candidateLetter, variationChanges, deltaTone, checkCounts, paretoState, indistinguishablePairs,
  defaultComparison, decisionGrid, decisionLog, FUEL, CARGO,
} from '../ui/js/design_compare.js';

test('candidate letters come from the name, else from the position', () => {
  assert.equal(candidateLetter({ name: 'Candidate B: B +1 m' }, 0), 'B');
  assert.equal(candidateLetter({ name: 'candidate c2 — lower Cb' }, 0), 'C2');
  assert.equal(candidateLetter({ name: 'Wider hull' }, 3), 'D');
});

test('variation changes read the parent dimension, its own variation or its Cb', () => {
  const parent = record('parent');
  parent.main_dimensions.length = q(320, 'm');
  parent.results.hydrostatics = { cb: { kind: 'quantity', value: q(0.8, '1') } };
  const child = record('a');
  child.lineage.variation_parameters = { length: q(326.4, 'm'), cb: q(0.79, '1'), depth: q(30, 'm') };
  const [length, cb, depth] = variationChanges(child, parent);
  assert.ok(Math.abs(length.delta - 6.4) < 1e-9); assert.ok(Math.abs(length.deltaPercent - 2) < 1e-9);
  assert.ok(Math.abs(cb.delta + 0.01) < 1e-9);
  assert.equal(depth.base, null); assert.equal(depth.delta, null);
  assert.deepEqual(variationChanges(record('b'), parent), []);
});

test('only fuel and cargo deltas have a better direction', () => {
  assert.equal(deltaTone(FUEL, -3), 'better'); assert.equal(deltaTone(FUEL, 2), 'worse');
  assert.equal(deltaTone(CARGO, 10), 'better'); assert.equal(deltaTone(CARGO, -10), 'worse');
  assert.equal(deltaTone('main_dimensions.length', 5), null);
  assert.equal(deltaTone(FUEL, 0), null); assert.equal(deltaTone(FUEL, null), null);
});

test('check counts and Pareto states keep unknown visible', () => {
  assert.deepEqual(checkCounts([{ state: 'pass' }, { state: 'fail' }, { state: 'unknown' }, { state: 'fail' }]),
    { pass: 1, fail: 2, unknown: 1 });
  assert.equal(paretoState({ reference: true, x: 1, y: 1 }), 'reference');
  assert.equal(paretoState({ x: null, y: 1 }), 'unknown');
  assert.equal(paretoState({ x: 1, y: 1, dominated: true }), 'dominated');
  assert.equal(paretoState({ x: 1, y: 1, dominated: false }), 'front');
});

test('pairs are listed once and the default comparison prefers the front', () => {
  const parent = record('parent', 60, 360000);
  const missing = record('m'); delete missing.results.fuel;
  const points = paretoPoints(parent, [record('a', 65, 345000), record('b', 66, 344000), record('c', 75, 330000), missing]);
  assert.deepEqual(indistinguishablePairs(points), [['a', 'b']]);
  // Only "a" is on the front, so one dominated candidate is added to compare two.
  assert.deepEqual(defaultComparison(points), ['a', 'b']);
  const many = paretoPoints(parent, ['a', 'b', 'c', 'd', 'e'].map((id, index) => record(id, 60 + index, 340000 + index * 1000)));
  assert.deepEqual(defaultComparison(many), ['a', 'b', 'c', 'd']);
  assert.deepEqual(defaultComparison(paretoPoints(parent, [missing])), ['m']);
});

test('the decision grid shows the current decision and leaves others undecided', () => {
  const old = { candidate_id: 'a', discipline: 'structure', action: 'deferred', recorded_at: '2026-11-13T00:00:00Z' };
  const now = { ...old, action: 'accepted', recorded_at: '2026-11-14T00:00:00Z' };
  const stray = { ...old, candidate_id: 'zz' };
  const grid = decisionGrid(['a', 'b'], [old, now, stray]);
  assert.equal(grid.get('a').structure, now);
  assert.equal(grid.get('a').machinery, null);
  assert.equal(grid.get('b').basic_design, null);
  assert.equal(grid.has('zz'), false);
});

test('the decision log is newest first without changing the history', () => {
  const a = { id: 1, recorded_at: '2026-11-13T00:00:00Z' };
  const b = { id: 2, recorded_at: '2026-11-14T00:00:00Z' };
  const c = { id: 3, recorded_at: '2026-11-14T00:00:00Z' };
  const history = [a, b, c];
  assert.deepEqual(decisionLog(history).map((entry) => entry.id), [3, 2, 1]);
  assert.deepEqual(history.map((entry) => entry.id), [1, 2, 3]);
});
