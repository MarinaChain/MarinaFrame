// Parts and Export quantity adapters: preserve evidence and do not turn labels into values.
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { partQuantity } from '../ui/js/parts.js';
import { bandQuantity, band, accuracyBlock } from '../ui/js/accuracy.js';
import { formatQuantity } from '../ui/js/value_display.js';
import { setLocale } from '../ui/js/i18n.js';

afterEach(() => setLocale('en'));

test('part quantities keep units, precision, source and full basis', () => {
  const quantity = partQuantity({ value: '-1234.500 m', source: 'traced', basis: 'Synthetic profile (A1234567890)' });
  assert.deepEqual(quantity, {
    value: -1234.5, unit: 'm', digits: 3, status: 'read',
    source: 'Read · Synthetic profile (A1234567890)',
  });
  assert.equal(formatQuantity(quantity).text, '-1,234.500');
  assert.equal(partQuantity({ value: '0.000 m', source: 'guessed' }).status, 'guessed');
  assert.equal(partQuantity({ value: '2 mm', source: 'ai_inferred' }).status, 'draft');
  assert.equal(partQuantity({ value: '2 mm', source: 'custom' }).source, 'custom');
  setLocale('ko');
  assert.equal(partQuantity({ value: '0 m', source: 'ai_inferred', basis: 'Synthetic' }).source, 'AI 판독 · Synthetic');
});

test('part labels, ranges, outlines and missing values are not scalar quantities', () => {
  for (const value of [null, undefined, '', 'No. 1P', '3 points', '1.000 to 2.000 m', '4 points, 0 to 2 m by 0 to 1 m', 'NaN m', 'Infinity m', '1 m extra']) {
    assert.equal(partQuantity({ value, source: 'traced' }), null, String(value));
  }
});

test('measured band scalars retain their evidence without inventing uncertainty', () => {
  for (const id of ['hull.scanned_bue_girl', 'hull.vector_gunnerus', 'tanks.vector_gunnerus', 'steel.positions']) {
    const measurement = band(id);
    const quantity = bandQuantity(measurement);
    assert.ok(Number.isFinite(quantity.value), id);
    assert.equal(quantity.status, 'draft');
    assert.equal(quantity.uncertainty, undefined);
    for (const evidence of [measurement.short, measurement.scope, measurement.source, measurement.section, measurement.n, measurement.caveat]) {
      assert.ok(quantity.source.includes(evidence), evidence);
    }
  }
  assert.equal(bandQuantity(band('steel.positions')).value, 0);
  assert.equal(bandQuantity(band('hull.vector_gunnerus')).unit, 'mm');
});

test('compound, invalid and unmeasured bands are not scalar quantities', () => {
  for (const id of ['hull.model_reading_clean', 'hull.scanned_thayer', 'hull.scanned_bumble_bee', 'hull.scanned_pardon_me', 'tanks.raster_dev', 'steel.weight']) {
    assert.equal(bandQuantity(band(id)), null, id);
  }
});

class TestNode {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.className = '';
    this.classList = { add: (name) => { this.className += ` ${name}`; } };
  }
  append(child) { this.children.push(child); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}

function descendants(node) {
  return [node, ...node.children.filter((child) => child instanceof TestNode).flatMap(descendants)];
}

test('Export renders measured scalars with focusable sources and keeps compound bands', () => {
  const oldDocument = globalThis.document;
  const oldNode = globalThis.Node;
  globalThis.Node = TestNode;
  globalThis.document = {
    createElement: (tag) => new TestNode(tag),
    createElementNS: (_namespace, tag) => new TestNode(tag),
  };
  try {
    const block = accuracyBlock({ body_plan_check: { used: true }, tank_model: true, structure_files: [{}] });
    const nodes = descendants(block);
    const quantities = nodes.filter((node) => node.className === 'vd');
    assert.equal(quantities.length, 3); // Scanned hull RMS, vector-plan tank error and steel position.
    for (const quantity of quantities) {
      assert.equal(quantity.attributes.tabindex, '0');
      assert.match(quantity.attributes['aria-description'], /docs\//);
      assert.equal(quantity.children.at(-1).children[0].children[0], 'Draft');
    }
    assert.ok(nodes.some((node) => node.children.includes('missed')));
    assert.ok(nodes.some((node) => node.children.includes('wt n/m')));
  } finally {
    globalThis.document = oldDocument;
    globalThis.Node = oldNode;
  }
});
