// The fact card of a picked part (js/factcard3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cardFor, dominantSource, framesText, KEY_FACTS, keyFacts, sizeText, thicknessText } from '../ui/js/factcard3d.js';
import { hullReference } from '../ui/js/reference3d.js';

const REFERENCE = hullReference({ min: [0, -3.6, 0], max: [24, 3.6, 3.4] }, { frameSpacingM: 0.5, frameZeroX: 0 });
const BOX = { min: [4, -1.5, 0.2], max: [7, 1.5, 1.4] };
const ROW = {
  id: 'tank_fw1', name: 'No 1 fresh water', content: 'fresh water', frames: '6...10', volume_100_m3: 4.2, volume_98_m3: 4.116,
  density_t_m3: 1, weight_98_t: 4.116, lcg_m: 5.5, tcg_m: 0, vcg_m: 0.83, notes: '',
  sources: { name: 'read', content: 'read', frames: 'read', volume: 'guessed', density: 'read', centroid: 'guessed', weight: 'guessed' },
};
const TANK = { id: 'tank_fw1', name: 'No 1 fresh water', kind: 'tank', detail: 'Fresh water', contentClass: 'fresh_water', group: null };

test('a tank card reuses the capacity plan row with units and a source on each value', () => {
  const card = cardFor({ entry: TANK, box: BOX, reference: REFERENCE, context: { row: ROW } });
  assert.equal(card.kindWord, 'Tank');
  assert.equal(card.source, 'guessed');
  const byName = Object.fromEntries(card.facts.map((fact) => [fact.name, fact]));
  assert.equal(byName['Volume 100 %'].value, '4.20 m³');
  assert.equal(byName['Volume 100 %'].source, 'guessed');
  assert.equal(byName.Content.source, 'read');
  assert.equal(byName['Weight 98 %'].value, '4.12 t');
  assert.equal(byName.Size.value, '3.00 × 3.00 × 1.20 m');
  assert.ok(!('Name' in byName));
});

test('a tank outside the capacity plan says so and shows what the file holds', () => {
  const card = cardFor({ entry: TANK, extras: { content_label: 'Fresh water', source_labels: { content_class: 'read' } }, box: BOX, reference: REFERENCE });
  assert.match(card.note, /not in the run/);
  assert.equal(card.facts[0].value, 'Fresh water');
  assert.equal(card.source, 'read');
  assert.equal(card.facts[1].value, 'Fr 8 to Fr 14');
});

test('a steel group card gives members, thickness with its source and the frames it spans', () => {
  const members = [{ thickness_mm: 8, thickness_source: 'guessed' }, { thickness_mm: 10, thickness_source: 'read' }, { thickness_mm: 8, thickness_source: 'guessed' }];
  const entry = { id: 'steel:deck', name: 'Decks', kind: 'steel', group: 'deck', detail: '3 members' };
  const card = cardFor({ entry, extras: { members }, box: { min: [1, -3, 3], max: [23, 3, 3.2] }, reference: REFERENCE });
  assert.equal(card.source, 'guessed');
  assert.deepEqual(card.facts.slice(0, 2).map((f) => [f.name, f.value, f.source]), [['Members', '3', null], ['Thickness', '8 to 10 mm', 'guessed']]);
  assert.equal(card.facts[2].value, 'Fr 2 to Fr 46');
});

test('a hull card lists the part record values with their labels and the link to its source', () => {
  const component = { arguments: [{ name: 'length', value: '24.00 m', source: 'traced' }, { name: 'depth', value: '3.40 m', source: 'guessed' }] };
  const source = { label: 'Profile view', open() {} };
  const card = cardFor({ entry: { id: 'hull', name: 'Hull', kind: 'hull', detail: '' }, box: { min: [0, -3.6, 0], max: [24, 3.6, 3.4] }, reference: REFERENCE, context: { component, source } });
  assert.deepEqual(card.facts.slice(0, 2).map((f) => [f.name, f.value, f.source]), [['Length', '24.00 m', 'traced'], ['Depth', '3.40 m', 'guessed']]);
  assert.equal(card.source, 'guessed');
  assert.equal(card.link.label, 'Profile view');
});

test('a hull with no part record shows its size and no source', () => {
  const card = cardFor({ entry: { id: 'hull', name: 'Hull', kind: 'hull', detail: '' }, box: { min: [0, -3.6, 0], max: [24, 3.6, 3.4] }, reference: REFERENCE });
  assert.equal(card.source, null);
  assert.equal(card.link, null);
  assert.equal(card.facts.at(-1).value, '24.00 × 7.20 × 3.40 m');
});

test('small formatters', () => {
  assert.equal(thicknessText([]), '—');
  assert.equal(thicknessText([{ thickness_mm: 8 }]), '8 mm');
  assert.equal(dominantSource([{ thickness_source: 'read' }, { thickness_source: 'guessed' }]), 'guessed');
  assert.equal(framesText(5, 5.1, REFERENCE), 'Fr 10');
  assert.equal(framesText(0, 1, null), '—');
  assert.equal(sizeText(null), '—');
});

test('a docked card shows the first 3 facts with a value and counts the rest', () => {
  const card = cardFor({ entry: TANK, box: BOX, reference: REFERENCE, context: { row: ROW } });
  const { facts, more } = keyFacts(card);
  assert.equal(KEY_FACTS, 3);
  assert.equal(facts.length, 3);
  assert.deepEqual(facts.map((fact) => fact.name), card.facts.slice(0, 3).map((fact) => fact.name));
  assert.equal(more, card.facts.length - 3);
});

test('key facts skip facts without a value, and a short pane can show none', () => {
  const card = { facts: [{ name: 'Frames', value: '—' }, { name: 'Top', value: '3.40 m' }, { name: 'Size', value: '1 × 2 × 3 m' }] };
  assert.deepEqual(keyFacts(card).facts.map((fact) => fact.name), ['Top', 'Size']);
  assert.equal(keyFacts(card).more, 1);
  assert.deepEqual(keyFacts(card, 0), { facts: [], more: 3 });
});
