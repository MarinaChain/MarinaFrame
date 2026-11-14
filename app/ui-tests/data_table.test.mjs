// Dense table helpers (js/data_table.js): sort with unknowns, filter, TSV with units, and the
// Korean locale. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sortRows, filterRows, toTsv } from '../ui/js/data_table.js';
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
