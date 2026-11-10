// Docking of the panels over the 3D view (js/dock3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cardMaxHeight, freeRegion, isCompactHost, reachesCovered } from '../ui/js/dock3d.js';

test('a pane under 360 px tall shows the card collapsed', () => {
  assert.equal(isCompactHost(359), true);
  assert.equal(isCompactHost(360), false);
});

test('the card is at most 40 % of the pane', () => {
  assert.equal(cardMaxHeight(500), 200);
  assert.equal(cardMaxHeight(330), 132);
});

test('with nothing covered the whole pane is free and nothing shifts', () => {
  assert.deepEqual(freeRegion({ width: 800, height: 400, occupied: null }), { usableX: 1, usableY: 1, shiftX: 0, shiftY: 0 });
});

test('a card at the bottom right leaves the top left free, and the framed part moves into it', () => {
  const free = freeRegion({ width: 1000, height: 500, occupied: { left: 740, top: 300 } });
  assert.equal(free.usableX, 0.74);
  assert.equal(free.usableY, 0.6);
  assert.ok(Math.abs(free.shiftX - 0.26) < 1e-9);
  assert.ok(Math.abs(free.shiftY - 0.4) < 1e-9);
});

test('a panel that covers nearly everything still leaves a usable share', () => {
  const free = freeRegion({ width: 400, height: 300, occupied: { left: 50, top: 10 } });
  assert.equal(free.usableX, 0.35);
  assert.equal(free.usableY, 0.35);
});

test('a part reaches the covered area only when it passes both its left and its top edge', () => {
  const occupied = { left: 700, top: 300 };
  assert.equal(reachesCovered({ right: 650, bottom: 400 }, occupied), false);
  assert.equal(reachesCovered({ right: 800, bottom: 250 }, occupied), false);
  assert.equal(reachesCovered({ right: 800, bottom: 400 }, occupied), true);
  assert.equal(reachesCovered({ right: 800, bottom: 400 }, null), false);
});
