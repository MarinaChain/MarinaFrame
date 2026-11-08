// Section-area check (js/areas.js). Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectionArea, areaCurve } from '../ui/js/areas.js';

test('section area integrates both sides and stops at the height', () => {
  const box = [[2, 0], [2, 3]]; // half-breadth 2 m, 3 m high
  assert.equal(sectionArea(box, 3), 12);
  assert.equal(sectionArea(box, 1.5), 6);
  assert.equal(sectionArea([[0, 0], [2, 2]], 2), 4); // a V section
});

/** Nine stations of a smooth hull whose breadth follows 1 - (2x/L - 1)^2. */
function smoothHull() {
  const length = 24;
  return Array.from({ length: 9 }, (_, i) => {
    const x = 1 + (i * 22) / 8;
    const k = 1 - (2 * x / length - 1) ** 2;
    return { id: `s${i}`, x_m: x, source_label: 'traced', points_yz_m: [[2 * k, 0], [3 * k, 3]] };
  });
}

test('a smooth hull flags no station', () => {
  const stations = areaCurve(smoothHull(), 3);
  for (const station of stations) {
    if (station.offCurve !== null) assert.ok(Math.abs(station.offCurve) < 0.1, `${station.id} ${station.offCurve}`);
  }
});

test('a station 30% too wide is far from the curve', () => {
  const sections = smoothHull();
  sections[4].points_yz_m = sections[4].points_yz_m.map(([y, z]) => [y * 1.3, z]);
  const stations = areaCurve(sections, 3);
  assert.ok(stations[4].offCurve > 0.1, String(stations[4].offCurve));
});
