// Reference values of the 3D view (js/reference3d.js): design waterline, boot top, frames.
// Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { baselineZ, bootTopBand, cutLabel, cutPlane, frameAt, frameLabel, frameLabelStep, hullReference, nearestFrameX, niceAtLeast, niceAtMost, paintZone, pointReadout, referenceLine, scaleBar } from '../ui/js/reference3d.js';

/** The Gunnerus hull part of the whole-vessel GLB (metres, ship frame; skegs reach below z = 0). */
const GUNNERUS = { min: [-1, -4.8, -0.517], max: [34, 4.8, 4.287] };

test('the baseline is z = 0 when the hull crosses it, else the lowest point', () => {
  assert.equal(baselineZ(-0.5, 4.3), 0);
  assert.equal(baselineZ(0, 3.4), 0);
  assert.equal(baselineZ(1.2, 4), 1.2);
});

test('a hull without given values gets guessed ones, each marked guessed', () => {
  const ref = hullReference(GUNNERUS);
  assert.equal(ref.baselineZ, 0);
  assert.deepEqual(ref.designWaterlineZ, { value: 2.57, source: 'guessed' });
  // 0.002 x 35 m + 0.48 = 0.55 m.
  assert.deepEqual(ref.frameSpacingM, { value: 0.55, source: 'guessed' });
  assert.deepEqual(ref.frameZeroX, { value: 0, source: 'guessed' });
});

test('given values win over the guesses', () => {
  const ref = hullReference(GUNNERUS, { designWaterlineZ: 2.7, frameSpacingM: 0.6, frameZeroX: -0.6 });
  assert.deepEqual(ref.designWaterlineZ, { value: 2.7, source: 'given' });
  assert.deepEqual(ref.frameSpacingM, { value: 0.6, source: 'given' });
  assert.deepEqual(ref.frameZeroX, { value: -0.6, source: 'given' });
});

test('the boot top straddles the waterline and the paint zones follow height', () => {
  const band = bootTopBand(2.5, 4.3);
  assert.ok(band[0] < 2.5 && band[1] > 2.5);
  assert.ok(band[1] - band[0] >= 0.12);
  assert.equal(paintZone(0.5, band), 'antifouling');
  assert.equal(paintZone(2.5, band), 'boottop');
  assert.equal(paintZone(4, band), 'topside');
  // A small hull still gets a visible band.
  const small = bootTopBand(0.6, 1);
  assert.ok(small[1] - small[0] >= 0.12 - 1e-9);
});

test('frame numbers count from frame 0 at the spacing', () => {
  assert.equal(frameAt(5.5, 0.55, 0), 10);
  assert.equal(nearestFrameX(5.7, 0.55, 0).toFixed(2), '5.50');
  assert.equal(frameLabel(10), 'Fr 10');
  assert.equal(frameLabel(10.04), 'Fr 10');
  assert.equal(frameLabel(10.44), 'Fr 10.4');
  assert.equal(frameLabel(-0.02), 'Fr 0');
  assert.equal(frameLabel(-3), 'Fr -3');
});

test('a cut keeps aft of a frame, port of a buttock and below a waterline, and flips', () => {
  const keeps = (plane, point) => plane.normal.reduce((sum, n, i) => sum + n * point[i], 0) + plane.constant >= 0;
  const frame = cutPlane('x', 10);
  assert.ok(keeps(frame, [9, 0, 0]));
  assert.ok(!keeps(frame, [11, 0, 0]));
  assert.ok(keeps(cutPlane('x', 10, true), [11, 0, 0]));
  assert.ok(keeps(cutPlane('y', 0), [0, 1, 0]));
  assert.ok(!keeps(cutPlane('y', 0), [0, -1, 0]));
  assert.ok(keeps(cutPlane('z', 2), [0, 0, 1]));
  assert.ok(!keeps(cutPlane('z', 2), [0, 0, 3]));
});

test('a frame cut reads its frame number and its x', () => {
  const ref = hullReference(GUNNERUS);
  assert.equal(cutLabel('x', 5.5, ref), 'Fr 10 · x 5.50 m');
  assert.equal(cutLabel('z', 2.571, ref), 'z 2.57 m');
});

test('1-2-5 steps round up and down', () => {
  assert.deepEqual([0.3, 1, 1.5, 3, 7, 12].map(niceAtLeast), [0.5, 1, 2, 5, 10, 20]);
  assert.deepEqual([0.3, 1, 1.5, 3, 7, 12].map(niceAtMost), [0.2, 1, 1, 2, 5, 10]);
});

test('frame numbers thin out as the frames get close on screen', () => {
  assert.equal(frameLabelStep(60), 1);
  assert.equal(frameLabelStep(30), 2);
  assert.equal(frameLabelStep(10), 5);
  assert.equal(frameLabelStep(3), 20);
  assert.equal(frameLabelStep(0), Infinity);
});

test('the scale bar is a round length that fits', () => {
  assert.deepEqual(scaleBar(0.05, 120), { metres: 5, px: 100, text: '5 m' });
  const small = scaleBar(0.002, 120);
  assert.equal(small.text, '20 cm');
  assert.ok(small.px <= 120);
});

test('a point reads in metres with its frame, and the reference says its source', () => {
  const ref = hullReference(GUNNERUS);
  assert.equal(pointReadout([12.1, -1.2, 2], ref), 'x 12.10 m · y −1.20 m · z 2.00 m · Fr 22');
  assert.equal(referenceLine(ref), 'DWL z 2.57 m (guessed) · frames 0.55 m (guessed)');
  assert.equal(referenceLine(hullReference(GUNNERUS, { designWaterlineZ: 2.7, frameSpacingM: 0.6 })), 'DWL z 2.70 m · frames 0.60 m');
});
