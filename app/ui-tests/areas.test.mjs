// Section-area check (js/areas.js). Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectionArea, areaCurve, curveSummary } from '../ui/js/areas.js';

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

test('a box hull has Cp 1 and its centre in the middle', () => {
  const box = [0, 5, 10].map((x) => ({ id: `b${x}`, x_m: x, source_label: 'traced', points_yz_m: [[2, 0], [2, 3]] }));
  const summary = curveSummary(areaCurve(box, 3));
  assert.equal(summary.volume_m3, 120); // 12 m² over 10 m
  assert.equal(summary.prismatic, 1);
  assert.equal(summary.centre_x_m, 5);
});

test('a triangular area curve has Cp 0.5 and its centre at the third', () => {
  // Area grows linearly from 0 at x = 0 to 12 m² at x = 12: the centre is 2/3 of the way.
  const wedge = [0, 6, 12].map((x) => ({ id: `w${x}`, x_m: x, source_label: 'traced', points_yz_m: [[x / 6, 0], [x / 6, 3]] }));
  const summary = curveSummary(areaCurve(wedge, 3));
  assert.equal(summary.volume_m3, 72);
  assert.equal(summary.prismatic, 0.5);
  assert.ok(Math.abs(summary.centre_x_m - 8) < 1e-9, String(summary.centre_x_m));
  assert.equal(summary.largest_x_m, 12);
});

test('no curve gives no summary', () => {
  assert.equal(curveSummary([]), null);
});
