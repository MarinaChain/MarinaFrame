// Shared quantity formatting and GA quantity adapters (no DOM required).
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { formatQuantity, valueDisplay } from '../ui/js/value_display.js';
import { setLocale } from '../ui/js/i18n.js';
import { gaRows } from '../ui/js/ga_panel.js';

// Minimal DOM surface used by dom.el and ui_kit.chip; no browser dependency for unit tests.
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

test('DOM keeps reading order, source accessibility, compact status and warning tones', () => {
  const oldDocument = globalThis.document;
  const oldNode = globalThis.Node;
  globalThis.Node = TestNode;
  globalThis.document = { createElement: (tag) => new TestNode(tag) };
  try {
    const display = valueDisplay({ value: 12, unit: 'm', uncertainty: { plusMinus: 1 }, method: 'empirical', status: 'draft', source: 'Synthetic source' });
    assert.deepEqual(display.children.map((node) => node.className), ['vd-value', 'vd-unit', 'vd-unc', 'badge badge-nodot badge-small vd-method', 'badge badge-small vd-status']);
    assert.equal(display.attributes.tabindex, '0');
    assert.equal(display.attributes.title, 'Synthetic source');
    assert.equal(display.attributes['aria-description'], 'Synthetic source');
    assert.equal(display.children.at(-1).dataset.tone, 'draft');
    const compact = valueDisplay({ value: 1, method: 'cfd', status: 'needs_review' }, { compact: true });
    assert.equal(compact.children.length, 4);
    assert.equal(compact.attributes.tabindex, undefined);
    assert.equal(compact.children.at(-1).dataset.tone, 'warn');
    assert.equal(valueDisplay({ value: null }).children.at(-1).dataset.tone, 'warn');
    assert.equal(valueDisplay({ value: 1, status: 'read' }).children.at(-1).dataset.tone, 'brand');
  } finally {
    globalThis.document = oldDocument;
    globalThis.Node = oldNode;
  }
});

const statuses = ['draft', 'needs_review', 'unknown', 'read', 'guessed', 'measured_from_scale', 'derived_from_space_tops', 'unconfirmed_from_uncertain_boxes'];
const methods = ['empirical', 'thin_ship', 'cfd', 'read_from_ga', 'measured', 'hydrostatics'];
afterEach(() => setLocale('en'));

test('formats grouped values, fixed digits, units and source separately', () => {
  assert.deepEqual(formatQuantity({ value: 12345.678, digits: 2, unit: 'm', method: 'read_from_ga', status: 'read', source: 'Synthetic drawing' }), {
    text: '12,345.68', unitText: 'm', uncertaintyText: '', methodText: 'Read from GA', statusText: 'Read', isUnknown: false, sourceText: 'Synthetic drawing',
  });
  assert.equal(formatQuantity({ value: 0, digits: 2 }).text, '0.00');
  assert.equal(formatQuantity({ value: 1234.6, digits: 0 }).text, '1,235');
  assert.equal(formatQuantity({ value: 12.345 }).text, '12.345');
  assert.equal(formatQuantity({ value: 1 }).statusText, 'Draft');
});

test('formats plus-minus uncertainty and bands with the same precision', () => {
  assert.equal(formatQuantity({ value: 1000, digits: 2, uncertainty: { plusMinus: 12.5 } }).uncertaintyText, '± 12.50');
  assert.equal(formatQuantity({ value: 1000, digits: 1, uncertainty: { low: 900, high: 1100 } }).uncertaintyText, '900.0–1,100.0');
  assert.equal(formatQuantity({ value: 0, uncertainty: { plusMinus: 0 } }).uncertaintyText, '± 0');
});

test('null is Unknown, even with a previous status or uncertainty', () => {
  const result = formatQuantity({ value: null, unit: 'm', status: 'read', uncertainty: { plusMinus: 1 } });
  assert.equal(result.text, '—');
  assert.equal(result.unitText, 'm');
  assert.equal(result.statusText, 'Unknown');
  assert.equal(result.uncertaintyText, '');
  assert.equal(result.isUnknown, true);
  assert.equal(result.sourceText, '');
});

test('Korean uses grouped numbers and Korean status and method words', () => {
  setLocale('ko');
  assert.equal(formatQuantity({ value: 12345.678, digits: 2 }).text, new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(12345.678));
  assert.equal(formatQuantity({ value: null }).statusText, '알 수 없음');
  assert.equal(formatQuantity({ value: 1, status: 'needs_review' }).statusText, '검토 필요');
  assert.deepEqual(methods.map((method) => formatQuantity({ value: 1, method }).methodText), ['경험식', '박선 이론', 'CFD', 'GA 판독', '도면 측정', '정수역학 계산']);
});

test('all supported words are translated and keep draft-only wording in both locales', () => {
  for (const language of ['en', 'ko']) {
    setLocale(language);
    for (const status of statuses) {
      const text = formatQuantity({ value: 1, status }).statusText;
      assert.doesNotMatch(text, /approv|verif|승인|검증|status\./i);
    }
    for (const method of methods) {
      const text = formatQuantity({ value: 1, method }).methodText;
      assert.doesNotMatch(text, /approv|verif|승인|검증|method\./i);
    }
  }
});

test('GA rows add numeric quantities without changing existing display fields', () => {
  const rows = gaRows({
    particulars: { loa_m: { value: 123.45, status: 'read', printed: '123.45 m' } },
    counts: { cargo_holds: { value: 0, status: 'guessed', evidence: 'Synthetic evidence' } },
    measured: { lbp_m: { value: 120, status: 'measured_from_scale', note: 'Synthetic scale' } },
    spaces: [{ id: 'hold-1', kind: 'cargo_hold', number: '1', status: 'read' }],
  });
  assert.equal(rows.particulars[0].value, '123.45 m');
  assert.equal(rows.particulars[0].quantity.value, 123.45);
  assert.equal(rows.particulars[0].quantity.method, 'read_from_ga');
  assert.equal(rows.counts[0].quantity.value, 0);
  assert.equal(rows.counts[0].quantity.source, 'Synthetic evidence');
  assert.equal(rows.measured[0].quantity.method, 'measured');
  assert.equal(rows.groups[0].rows[0].quantity, null);
  assert.equal(rows.groups[0].rows[0].value, 'No. 1');
  assert.equal(rows.particulars[1].quantity.value, null);
});
