// Reference values of the 3D view (js/reference3d.js): design waterline, boot top, frames.
// Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { baselineZ, bootTopBand, hullReference, paintZone } from '../ui/js/reference3d.js';

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
