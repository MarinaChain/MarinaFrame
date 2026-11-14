// Dense table helpers (js/data_table.js): sort with unknowns, filter, TSV with units, and the
// Korean locale. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createDataTable, sortRows, filterRows, toTsv } from '../ui/js/data_table.js';
import { setLocale } from '../ui/js/i18n.js';

const COLUMNS = [
  { key: 'name', label: 'Tank' },
  { key: 'volume_98_m3', label: 'Capacity 98 %', unit: 'm³', align: 'end' },
  { key: 'lcg_m', label: 'LCG', unit: 'm', align: 'end' },
];

const ROWS = [
  { id: 'a', name: 'No 2 ballast', volume_98_m3: 9.31, lcg_m: 14.5 },
  { id: 'b', name: 'Fresh water', volume_98_m3: 4.116, lcg_m: null },
  { id: 'c', name: 'Fuel oil', volume_98_m3: null, lcg_m: 18.25 },
  { id: 'd', name: 'Diesel oil', volume_98_m3: 9.8, lcg_m: 12 },
];

test('numbers sort numerically, ascending and descending', () => {
  const byVolume = COLUMNS[1];
  assert.deepEqual(sortRows(ROWS, byVolume, 'asc').map((r) => r.id), ['b', 'a', 'd', 'c']);
  assert.deepEqual(sortRows(ROWS, byVolume, 'desc').map((r) => r.id), ['d', 'a', 'b', 'c']);
});

test('a null or unknown value is always last, in both directions', () => {
  const byLcg = COLUMNS[2];
  assert.deepEqual(sortRows(ROWS, byLcg, 'asc').map((r) => r.id), ['d', 'a', 'c', 'b']);
  assert.deepEqual(sortRows(ROWS, byLcg, 'desc').map((r) => r.id), ['c', 'a', 'd', 'b']);
  const nan = [{ id: 'x', lcg_m: Number.NaN }, { id: 'y', lcg_m: 1 }, { id: 'z', lcg_m: 0 }];
  assert.deepEqual(sortRows(nan, byLcg, 'desc').map((r) => r.id), ['y', 'z', 'x']);
});

test('strings sort with the current locale, and Korean does not throw', () => {
  const byName = COLUMNS[0];
  setLocale('ko');
  const korean = [
    { id: '1', name: '타' },
    { id: '2', name: '가' },
    { id: '3', name: '하' },
    { id: '4', name: null },
  ];
  assert.deepEqual(sortRows(korean, byName, 'asc').map((r) => r.id), ['2', '1', '3', '4']);
  assert.deepEqual(sortRows(korean, byName, 'desc').map((r) => r.id), ['3', '1', '2', '4']);
  setLocale('en');
  assert.deepEqual(sortRows(ROWS, byName, 'asc').map((r) => r.id), ['d', 'b', 'c', 'a']);
});

test('sorting passes the active interface locale to collation', (context) => {
  const Collator = Intl.Collator;
  let receivedLocale;
  context.mock.method(Intl, 'Collator', function (code, options) {
    receivedLocale = code;
    return new Collator(code, options);
  });
  try {
    setLocale('ko');
    sortRows(ROWS, COLUMNS[0]);
    assert.equal(receivedLocale, 'ko');
  } finally { setLocale('en'); }
});

test('the filter matches any visible column, case-insensitively', () => {
  assert.deepEqual(filterRows(ROWS, COLUMNS, 'ballast').map((r) => r.id), ['a']);
  assert.deepEqual(filterRows(ROWS, COLUMNS, 'FRESH').map((r) => r.id), ['b']);
  // A number the format would round still matches its full value.
  assert.deepEqual(filterRows(ROWS, COLUMNS, '4.11').map((r) => r.id), ['b']);
  assert.equal(filterRows(ROWS, COLUMNS, '  ').length, ROWS.length);
  assert.deepEqual(filterRows(ROWS, COLUMNS, 'no such tank'), []);
});

test('the filter reads the formatted text, not the raw value', () => {
  const columns = [{ key: 'v', label: 'V', format: (value) => `vol ${value.toFixed(1)}` }];
  const rows = [{ id: 'a', v: 1.25 }, { id: 'b', v: 7 }];
  assert.deepEqual(filterRows(rows, columns, 'vol 1.3').map((r) => r.id), ['a']);
  assert.deepEqual(filterRows(rows, columns, '1.25').map((r) => r.id), []);
});

test('TSV has the units in brackets, empty unknowns and plain numbers', () => {
  const tsv = toTsv(COLUMNS, sortRows(ROWS, COLUMNS[1], 'asc'));
  const lines = tsv.split('\n');
  assert.equal(lines[0], 'Tank\tCapacity 98 % [m³]\tLCG [m]');
  assert.equal(lines[1], 'Fresh water\t4.116\t');
  assert.equal(lines[2], 'No 2 ballast\t9.31\t14.5');
  assert.equal(lines[3], 'Diesel oil\t9.8\t12');
  assert.equal(lines[4], 'Fuel oil\t\t18.25');
  assert.equal(lines.length, 5);
});

test('a column without a unit has no brackets, and formatted text copies as it shows', () => {
  const columns = [
    { key: 'name', label: 'Tank' },
    { key: 'state', label: 'State', format: (value) => (value === 'ok' ? 'built' : 'not built') },
  ];
  const tsv = toTsv(columns, [{ name: 'A', state: 'ok' }, { name: null, state: 'x' }]);
  assert.equal(tsv, 'Tank\tState\nA\tbuilt\n\tnot built');
});

// A small DOM double keeps interaction checks in node:test, without a browser.
class TestNode {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.listeners = {}; }
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  focus() { document.activeElement = this; }
  get textContent() { return this.children.map((child) => typeof child === 'string' ? child : child.textContent).join(''); }
  find(tag) { return this.children.filter((child) => typeof child !== 'string').flatMap((child) => [ ...(child.tag === tag ? [child] : []), ...child.find(tag)]); }
}
globalThis.Node = TestNode;
globalThis.document = { activeElement: null, createElement: (tag) => new TestNode(tag), createElementNS: (_, tag) => new TestNode(tag) };

function fixture(options = {}) {
  const table = createDataTable({ columns: COLUMNS, rows: ROWS, caption: 'Tank list', ...options });
  return { ...table, body: table.element.find('tbody')[0], search: table.element.find('input')[0] };
}
function press(body, key) {
  let prevented = false;
  body.listeners.keydown({ key, preventDefault() { prevented = true; } });
  return prevented;
}

test('Node formatters filter and copy their visible text, not object strings', () => {
  const columns = [{ key: 'content', label: 'Content', format: (value) => {
    const node = new TestNode('span'); node.append(value); return node;
  } }];
  const rows = [{ content: 'Ballast' }];
  assert.deepEqual(filterRows(rows, columns, 'ballast'), rows);
  assert.equal(toTsv(columns, rows), 'Content\nBallast');
});

test('empty strings and empty formatted cells show Unknown and copy as empty', () => {
  const columns = [{ key: 'name', label: 'Tank' }, { key: 'source', label: 'Source', format: () => null }];
  const { element } = fixture({ columns, rows: [{ id: 'a', name: '', source: {} }] });
  for (const cell of element.find('td')) {
    assert.equal(cell.textContent, '—');
    assert.equal(cell.attributes.title, 'Unknown');
  }
  assert.equal(toTsv(columns, [{ name: '', source: {} }]), 'Tank\tSource\n\t');
});

test('the focused body selects the first row, clamps arrows and activates with Enter', () => {
  const picked = [];
  const { body } = fixture({ onSelect: (key) => picked.push(key) });
  assert.equal(body.attributes.tabindex, '0');
  body.focus();
  assert.equal(press(body, 'ArrowUp'), true);
  assert.equal(body.children[0].attributes['aria-selected'], 'true');
  assert.equal(press(body, 'Enter'), true);
  assert.deepEqual(picked, ['a']);
  press(body, 'ArrowDown');
  assert.equal(body.children[1].attributes['aria-selected'], 'true');
  assert.deepEqual(picked, ['a']);
  press(body, 'Enter');
  assert.deepEqual(picked, ['a', 'b']);
  for (let index = 0; index < 6; index++) press(body, 'ArrowDown');
  assert.equal(body.children[3].attributes['aria-selected'], 'true');
  assert.equal(press(body, 'ArrowDown'), true);
});

test('Enter on an unselected focused body opens the first row', () => {
  const picked = [];
  const { body } = fixture({ onSelect: (key) => picked.push(key) });
  body.focus();
  press(body, 'Enter');
  assert.deepEqual(picked, ['a']);
});

test('selection updates keep focused rows in place and click activates the tank', () => {
  const picked = [];
  const { body, select } = fixture({ onSelect: (key) => picked.push(key) });
  const first = body.children[0];
  first.focus();
  first.listeners.click();
  assert.equal(body.children[0], first);
  assert.equal(document.activeElement, first);
  assert.equal(first.attributes['aria-selected'], 'true');
  select('b');
  assert.equal(first.attributes['aria-selected'], 'false');
  assert.equal(body.children[1].attributes['aria-selected'], 'true');
  assert.deepEqual(picked, ['a']);
});

test('headers toggle aria-sort and filtering counts and copies only visible rows', async (context) => {
  const { element, body, search } = fixture();
  const headers = element.find('th');
  headers[1].children[0].listeners.click();
  assert.equal(headers[1].attributes['aria-sort'], 'ascending');
  assert.match(body.children[0].textContent, /Fresh water/);
  headers[1].children[0].listeners.click();
  assert.equal(headers[1].attributes['aria-sort'], 'descending');
  headers[0].children[0].listeners.click();
  assert.equal(headers[1].attributes['aria-sort'], 'none');
  search.listeners.input({ target: { value: 'oil' } });
  assert.match(element.textContent, /2 of 4 rows/);
  let copied;
  context.mock.method(globalThis, 'setTimeout', () => 0);
  context.mock.getter(globalThis, 'navigator', () => ({ clipboard: { writeText: async (text) => { copied = text; } } }));
  const copy = element.find('button').find((button) => button.textContent === 'Copy');
  await copy.listeners.click();
  assert.equal(copied, toTsv(COLUMNS, [ROWS[3], ROWS[2]]));
});

test('setRows keeps sort, filter and visible selection, and empty views ignore keys', () => {
  const { element, body, search, select, setRows } = fixture();
  element.find('th')[0].children[0].listeners.click();
  search.listeners.input({ target: { value: 'oil' } });
  select('c');
  setRows([...ROWS, { id: 'e', name: 'Heavy oil', volume_98_m3: 20, lcg_m: 5 }]);
  assert.match(element.textContent, /3 of 5 rows/);
  assert.match(body.children[0].textContent, /Diesel oil/);
  assert.equal(body.children[1].attributes['aria-selected'], 'true');
  search.listeners.input({ target: { value: 'missing' } });
  assert.match(element.textContent, /0 of 5 rows/);
  assert.match(body.textContent, /No rows match the filter/);
  assert.equal(press(body, 'Enter'), false);
  search.listeners.input({ target: { value: '' } });
  press(body, 'ArrowDown');
  assert.equal(body.children[0].attributes['aria-selected'], 'true');
});

test('dense table styles match sort state and override base numeric alignment', async () => {
  const css = await readFile(new URL('../ui/styles.css', import.meta.url), 'utf8');
  assert.match(css, /\.table-sort\[data-active="true"\] \.icon\s*\{[^}]*visibility: visible/);
  assert.match(css, /\.data-table td\.table-num\s*\{[^}]*text-align: right/);
  assert.match(css, /\.table-body:focus-visible/);
});

test('Copy reports unavailable and rejected clipboard access without throwing', async (context) => {
  context.mock.method(globalThis, 'setTimeout', () => 0);
  for (const navigator of [undefined, {}, { clipboard: { writeText: async () => { throw new Error('denied'); } } }]) {
    context.mock.getter(globalThis, 'navigator', () => navigator);
    const { element } = fixture();
    const copy = element.find('button').find((button) => button.textContent === 'Copy');
    await copy.listeners.click();
    assert.equal(copy.textContent, 'Copy failed');
  }
});
