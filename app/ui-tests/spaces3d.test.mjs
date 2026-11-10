// Named spaces of the 3D view (js/spaces3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { boxHas, boxPlanes, bulkheadChoices, bulkheadPositions, bulkheadSpace, padBox, tankSpaces, OPEN_CONSTANT } from '../ui/js/spaces3d.js';
import { hullReference } from '../ui/js/reference3d.js';

const keeps = (plane, point) => plane.normal.reduce((sum, n, i) => sum + n * point[i], 0) + plane.constant >= 0;
const REFERENCE = hullReference({ min: [0, -3.6, 0], max: [24, 3.6, 3.4] }, { frameSpacingM: 0.5, frameZeroX: 0 });

/** Two triangles of a plate in the plane x = `x` (it faces along x). */
function plate(x, size = 2) {
  return [x, 0, 0, x, size, 0, x, 0, size, x, size, 0, x, size, size, x, 0, size];
}

test('six planes keep a point exactly when it is inside the box', () => {
  const box = { min: [4, -1.5, 0.2], max: [7, 1.5, 1.4] };
  const planes = boxPlanes(box);
  assert.equal(planes.length, 6);
  const insideAll = (point) => planes.every((plane) => keeps(plane, point));
  assert.ok(insideAll([5, 0, 1]));
  assert.ok(insideAll([4, -1.5, 0.2]));
  for (const outside of [[3.9, 0, 1], [7.1, 0, 1], [5, -1.6, 1], [5, 1.6, 1], [5, 0, 0.1], [5, 0, 1.5]]) {
    assert.ok(!insideAll(outside), `${outside} is outside`);
    assert.ok(!boxHas(box, outside));
  }
});

test('with no box the six planes keep everything', () => {
  const planes = boxPlanes(null);
  assert.ok(planes.every((plane) => plane.constant === OPEN_CONSTANT));
  assert.ok(planes.every((plane) => keeps(plane, [1e5, -1e5, 5e4])));
});

test('a tank space is its box widened a little, one per built tank, named in number order', () => {
  const spaces = tankSpaces([
    { id: 'b', name: 'No 10 ballast', box: { min: [10, -1, 0], max: [12, 1, 1] } },
    { id: 'a', name: 'No 2 ballast', box: { min: [4, -1, 0], max: [7, 1, 1] } },
    { id: 'flat', name: 'Empty', box: { min: [1, 1, 1], max: [1, 2, 2] } },
    { id: 'none', name: 'No box', box: null },
  ]);
  assert.deepEqual(spaces.map((s) => s.name), ['No 2 ballast', 'No 10 ballast']);
  assert.equal(spaces[0].id, 'space:a');
  assert.deepEqual(spaces[0].box, padBox({ min: [4, -1, 0], max: [7, 1, 1] }));
  assert.ok(boxHas(spaces[0].box, [4, -1, 0]));
  assert.equal(spaces[0].detail, '3.00 × 2.00 × 1.00 m');
  assert.equal(spaces[0].custom, false);
});

test('bulkheads are found as plates that face along x, with their x', () => {
  const positions = new Float32Array([...plate(3.5, 6), ...plate(3.512, 6), ...plate(12.5, 6), ...plate(20, 6)]);
  const xs = bulkheadPositions(positions);
  assert.equal(xs.length, 3);
  assert.ok(Math.abs(xs[0] - 3.506) < 0.02);
  assert.ok(Math.abs(xs[1] - 12.5) < 0.02);
  assert.ok(Math.abs(xs[2] - 20) < 0.02);
});

test('faces that do not face along x, and small brackets, are not bulkheads', () => {
  // A deck slab (faces up) and a small bracket plate beside a big bulkhead.
  const deck = [0, 0, 3, 10, 0, 3, 0, 5, 3];
  const positions = new Float32Array([...deck, ...plate(8, 6), ...plate(15, 0.5)]);
  const xs = bulkheadPositions(positions);
  assert.equal(xs.length, 1);
  assert.ok(Math.abs(xs[0] - 8) < 0.02);
});

test('an indexed mesh gives the same plates', () => {
  const positions = new Float32Array([5, 0, 0, 5, 3, 0, 5, 0, 3, 5, 3, 3]);
  const xs = bulkheadPositions(positions, new Uint32Array([0, 1, 2, 1, 3, 2]));
  assert.equal(xs.length, 1);
  assert.ok(Math.abs(xs[0] - 5) < 0.02);
});

test('bulkhead choices carry the frame they stand on', () => {
  const choices = bulkheadChoices([3.5, 12.5], REFERENCE);
  assert.equal(choices[0].label, 'Fr 7 · 3.50 m');
  assert.equal(choices[1].frame, 'Fr 25');
  assert.equal(bulkheadChoices([3.5], null)[0].label, '3.50 m');
});

test('the space between two bulkheads spans the hull beam and depth, in either order', () => {
  const hull = { min: [0, -3.6, 0], max: [24, 3.6, 3.4] };
  const [a, b] = bulkheadChoices([3.5, 12.5], REFERENCE);
  const space = bulkheadSpace(b, a, hull);
  assert.equal(space.name, 'Fr 7 to Fr 25');
  assert.equal(space.kind, 'bulkhead');
  assert.equal(space.custom, true);
  assert.ok(space.box.min[0] < 3.5 && space.box.max[0] > 12.5);
  assert.ok(space.box.min[1] < -3.6 && space.box.max[2] > 3.4);
  assert.equal(space.id, bulkheadSpace(a, b, hull).id);
  assert.equal(bulkheadSpace(a, a, hull), null);
  assert.equal(bulkheadSpace(a, null, hull), null);
});
