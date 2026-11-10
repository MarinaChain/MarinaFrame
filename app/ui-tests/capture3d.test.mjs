// Capture of the 3D view for the report (js/capture3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CAPTURE_SIZE, captureFraming, PNG_BASE64_PREFIX, pngBase64 } from '../ui/js/capture3d.js';

test('the report picture has one fixed size', () => {
  assert.deepEqual(CAPTURE_SIZE, { width: 1600, height: 1000 });
});

test('a pane that is wider than the picture widens the field so the sides stay', () => {
  assert.ok(Math.abs(captureFraming(2.4, 1.6) - 1.5) < 1e-12);
  assert.equal(captureFraming(1.6, 1.6), 1);
});

test('a pane that is narrower than the picture needs no change, and a bad aspect is ignored', () => {
  assert.equal(captureFraming(0.7, 1.6), 1);
  assert.equal(captureFraming(0, 1.6), 1);
  assert.equal(captureFraming(NaN, 1.6), 1);
});

test('only PNG data URLs give picture text', () => {
  const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]).toString('base64');
  assert.ok(png.startsWith(PNG_BASE64_PREFIX));
  assert.equal(pngBase64(`data:image/png;base64,${png}`), png);
  assert.equal(pngBase64('data:image/jpeg;base64,/9j/4AAQ'), null);
  assert.equal(pngBase64('data:image/png;base64,AAAA'), null);
  assert.equal(pngBase64(null), null);
});
