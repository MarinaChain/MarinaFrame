// Tank tables (js/tanks.js) and the tank and steel export rows (js/export.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tankSource, tankNumber, capacityFields, capacityRowOf, groupLine, soundingView, tankDetailBlock, capacityPanel } from '../ui/js/tanks.js';
import { filesSummary, outputsOf } from '../ui/js/export.js';
import { createParts } from '../ui/js/parts.js';

/** A capacity plan row as app/core run_tables.rs gives it (made-up values). */
const ROW = {
  id: 'tank_db1', name: 'No 1 water ballast', content: 'water ballast', frames: '4...8', built: true,
  volume_100_m3: 2, volume_98_m3: 1.96, density_t_m3: 1.025, weight_98_t: 2.009,
  lcg_m: 3, tcg_m: 0, vcg_m: 0.25, notes: '', has_sounding: true,
  sources: { name: 'read', content: 'read', frames: 'read', volume: 'traced', density: 'read', centroid: 'traced', weight: 'traced' },
};

test('every capacity plan value keeps its source label', () => {
  const fields = capacityFields(ROW);
  assert.deepEqual(fields.map((f) => f.name), ['Name', 'Content', 'Frames', 'Volume 100 %', 'Volume 98 %', 'Density', 'Weight 98 %', 'LCG', 'TCG', 'VCG']);
  assert.deepEqual(fields[3], { name: 'Volume 100 %', value: '2.00 m³', source: 'traced' });
  assert.deepEqual(fields[6], { name: 'Weight 98 %', value: '2.01 t', source: 'traced' });
  assert.equal(fields[9].value, '0.250 m');
  assert.ok(fields.every((f) => f.source));
});

test('a tank that is not built shows dashes, not zeros', () => {
  const fields = capacityFields({ ...ROW, built: false, volume_100_m3: null, weight_98_t: null, frames: '', sources: { volume: 'guessed' } });
  assert.equal(fields[2].value, '—');
  assert.equal(fields[3].value, '—');
  assert.equal(fields[3].source, 'guessed');
  assert.equal(fields[2].source, null);
  assert.equal(tankNumber(Number.NaN, 2), '—');
});

test('source labels use the app label styles and never say approved or verified', () => {
  assert.deepEqual([tankSource('traced').word, tankSource('read').word, tankSource('guessed').word], ['Traced', 'Read', 'Guessed']);
  assert.equal(tankSource('guessed').tone, 'draft');
  for (const label of ['traced', 'read', 'guessed']) {
    const { word, title } = tankSource(label);
    assert.doesNotMatch(`${word} ${title}`, /approved|verified/i);
  }
});

test('group totals read as one line per content group', () => {
  assert.equal(groupLine({ content: 'water ballast', tanks: 3, built: 2, volume_100_m3: 62.3, weight_98_t: 63.861 }),
    'Water ballast · 2 of 3 built · 62.30 m³ · 63.86 t');
  assert.equal(capacityRowOf({ rows: [ROW] }, 'tank_db1'), ROW);
  assert.equal(capacityRowOf(null, 'tank_db1'), null);
});

test('the sounding table shows sounding, ullage, volume and fill of the file columns', () => {
  const view = soundingView({
    columns: ['sounding_m', 'ullage_m', 'volume_m3', 'fill_pct', 'lcg_m'],
    rows: [[0, 0.5, 0, 0, null], [0.5, 0, 2, 100, 3]],
  });
  assert.deepEqual(view.headings, ['Sounding (m)', 'Ullage (m)', 'Volume (m³)', 'Fill (%)']);
  assert.deepEqual(view.rows[1], ['0.500', '0.000', '2.000', '100.0']);
  assert.deepEqual(soundingView({ columns: ['volume_m3'], rows: [[1]] }).headings, ['Volume (m³)']);
});

test('tank and steel exports are offered only for runs that have them', () => {
  const kinds = (view, files) => outputsOf(view, files).map((o) => o.kind);
  assert.deepEqual(kinds({}), ['step', 'stl', 'offsets', 'hydrostatics', 'report', 'package']);
  assert.deepEqual(kinds({ tank_model: true, structure_files: [{ file: 'b.3docx' }] }),
    ['step', 'stl', 'offsets', 'hydrostatics', 'report', 'tanks', 'structure', 'package']);
  // Files already exported stay listed.
  assert.ok(kinds({}, [{ kind: 'structure', file: 'x' }]).includes('structure'));
});

test('the written tank and steel files are summarised', () => {
  const files = ['V_capacity_plan.csv', 'V_DRAFT_sounding_db1.csv', 'V_DRAFT_sounding_db2.csv'].map((file) => ({ file }));
  assert.equal(filesSummary('tanks', files), 'Capacity plan and 2 sounding tables');
  const steel = ['V_b_steel_members.csv', 'V_b_steel_totals.csv', 'V_b.3docx'].map((file) => ({ file }));
  assert.equal(filesSummary('structure', steel), '2 steel tables and 1 OCX file');
  assert.equal(filesSummary('offsets', steel), '');
});

/** The least DOM that js/dom.js needs, to render the panels without a browser. */
class FakeNode {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.className = ''; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  contains() { return false; }
  get style() { return { setProperty() {} }; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  get textContent() { return this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join(''); }
  findAll(test) { return [...(test(this) ? [this] : []), ...this.children.filter((c) => typeof c !== 'string').flatMap((c) => c.findAll(test))]; }
}
globalThis.Node = FakeNode;
globalThis.document = { activeElement: null, createElement: (tag) => new FakeNode(tag), createElementNS: (_, tag) => new FakeNode(tag) };

test('the tank detail block lists each value with its label chip', () => {
  const block = tankDetailBlock(ROW);
  const rows = block.findAll((n) => n.tag === 'tr' && n.dataset.source !== undefined && n.children[0]?.tag === 'th' && n.children.length === 3);
  assert.equal(rows.length, 10);
  assert.match(rows[3].textContent, /^Volume 100 %2\.00 m³Traced$/);
  assert.match(tankDetailBlock(null).textContent, /not in the run's capacity plan/);
});

test('the capacity plan panel shows the draft stamp, group totals and the sounding table', () => {
  const plan = { file: 'tank_tables/V_capacity_plan.csv', stamp: ['Draft'], rows: [ROW], engineering_approved: false,
    groups: [{ content: 'water ballast', tanks: 1, built: 1, volume_100_m3: 2, weight_98_t: 2.009 }] };
  let picked = null;
  const sounding = { table: { columns: ['sounding_m', 'ullage_m', 'volume_m3', 'fill_pct'], rows: [[0, 0.5, 0, 0], [0.5, 0, 2, 100]] } };
  const panel = capacityPanel({ plan, selectedId: 'tank_db1', sounding, onPick: (id) => { picked = id; } });
  const text = panel.textContent;
  assert.match(text, /Draft, not for construction\./);
  assert.match(text, /Water ballast · 1 of 1 built · 2\.00 m³ · 2\.01 t/);
  assert.match(text, /Sounding table: No 1 water ballast/);
  assert.match(text, /0\.5000\.0002\.000100\.0/);
  assert.doesNotMatch(text, /approved|verified/i);
  panel.findAll((n) => n.className === 'tank-pick')[0].listeners.click();
  assert.equal(picked, 'tank_db1');
  assert.match(capacityPanel({ plan, selectedId: 'tank_db1', sounding: { loading: true }, onPick: () => {} }).textContent, /Loading/);
  assert.equal(capacityPanel({ plan: null }), null);
});

test('a tank part shows its capacity plan row, and the Parts page the capacity plan', async () => {
  const host = new FakeNode('div');
  const asked = [];
  const parts = createParts({ host, review: async () => {}, showIn3d: () => {}, signOff: async () => {},
    loadSounding: async (id) => { asked.push(id); return { columns: ['sounding_m'], rows: [[0.25]] }; } });
  const tank = { id: 'tank_db1', op: 'tank', label: 'No 1 water ballast', status: 'draft_guess', built: true, reason: '',
    view: 'plan', bbox_m: { min: [2, -1, 0], max: [4, 1, 0.5] }, volume_m3: 2, arguments: [], review: 'open' };
  const plan = { file: 'tank_tables/V_capacity_plan.csv', stamp: [], rows: [ROW], groups: [] };
  parts.show({ components: [tank], capacity_plan: plan });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(asked, ['tank_db1']);
  const text = host.textContent;
  assert.match(text, /Tanks/);
  assert.match(text, /Volume 98 %1\.96 m³Traced/);
  assert.match(text, /Capacity plan/);
  assert.match(text, /0\.250/);
});
