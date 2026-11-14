// Pareto chart geometry: round ticks, points inside the plot and labels that do not overlap.
import test from 'node:test';
import assert from 'node:assert/strict';
import { niceTicks, placeLabels, chartLayout, MARGIN } from '../ui/js/pareto_layout.js';

test('ticks are round and cover the range', () => {
  const fuel = niceTicks(64.5, 73.5);
  assert.deepEqual(fuel.ticks, [64, 66, 68, 70, 72, 74]);
  assert.equal(fuel.digits, 0);
  const cargo = niceTicks(329000, 358000);
  assert.equal(cargo.min <= 329000 && cargo.max >= 358000, true);
  assert.equal(cargo.step, 10000);
  const small = niceTicks(0.1, 0.3);
  assert.equal(small.digits, 2);
  assert.ok(small.ticks.every((tick) => String(tick).length < 6));
});

test('one value gets space on both sides', () => {
  const ticks = niceTicks(70, 70);
  assert.ok(ticks.min < 70 && ticks.max > 70);
});

test('labels avoid each other and the markers, and stay in the plot', () => {
  const plot = { left: 0, top: 0, right: 400, bottom: 300 };
  // Two markers almost on top of each other, as two candidates with close values.
  const labels = placeLabels([{ px: 200, py: 150, text: 'A' }, { px: 212, py: 146, text: 'B' }], plot);
  assert.notDeepEqual([labels[0].x, labels[0].y], [labels[1].x, labels[1].y]);
  assert.equal(labels[0].anchor, 'end'); // the right side is B's marker
  // A marker at the right edge puts its label on the left.
  const [edge] = placeLabels([{ px: 398, py: 150, text: 'Parent' }], plot);
  assert.equal(edge.anchor, 'end');
});

test('the layout leaves out unknown points and keeps bands inside the axes', () => {
  const points = [
    { id: 'p', x: 69.1, y: 340000, xBand: null, yBand: { low: 337000, high: 343000 }, label: 'Parent' },
    { id: 'a', x: 66, y: 350000, xBand: { low: 64.5, high: 67.5 }, yBand: { low: 347000, high: 353000 }, label: 'A' },
    { id: 'u', x: null, y: 345000, label: 'U' },
  ];
  const layout = chartLayout(points, { width: 640, height: 360 });
  assert.deepEqual(layout.points.map((point) => point.id), ['p', 'a']);
  assert.ok(layout.xTicks.min <= 64.5 && layout.xTicks.max >= 69.1);
  assert.ok(layout.yTicks.min <= 337000 && layout.yTicks.max >= 353000);
  for (const point of layout.points) {
    assert.ok(point.px >= MARGIN.left && point.px <= 640 - MARGIN.right);
    assert.ok(point.py >= MARGIN.top && point.py <= 360 - MARGIN.bottom);
  }
  // More cargo is higher on the chart (a smaller pixel y).
  assert.ok(layout.points[1].py < layout.points[0].py);
});
