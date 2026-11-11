// Docking of the panels over the 3D view (js/dock3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { besideBoxes, cornerBoxes, freeRegion, isCompactHost, overlapArea, placeClear, reachesCovered } from '../ui/js/dock3d.js';

test('a pane under 360 px tall shows the card collapsed', () => {
  assert.equal(isCompactHost(359), true);
  assert.equal(isCompactHost(360), false);
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

// ---- Free-side placement of the hover label and the docked card.

const PANE = { width: 1000, height: 600, size: { width: 240, height: 160 }, insets: { top: 90, right: 12, bottom: 40, left: 12 } };

test('placement takes the first candidate that covers nothing', () => {
  const candidates = [{ left: 0, top: 0, right: 100, bottom: 50, name: 'a' }, { left: 200, top: 0, right: 300, bottom: 50, name: 'b' }];
  assert.equal(placeClear(candidates, [{ left: 50, top: 10, right: 60, bottom: 20 }]).name, 'b');
  assert.equal(placeClear(candidates, []).name, 'a');
});

test('when every candidate covers something, placement takes the one that covers least', () => {
  const candidates = [{ left: 0, top: 0, right: 100, bottom: 100, name: 'a' }, { left: 200, top: 0, right: 300, bottom: 100, name: 'b' }];
  const avoid = [{ left: 0, top: 0, right: 80, bottom: 80 }, { left: 290, top: 90, right: 400, bottom: 200 }];
  assert.equal(placeClear(candidates, avoid).name, 'b');
});

test('an extra cover (a part\'s pixels) counts like a covered box', () => {
  const candidates = [{ left: 0, top: 0, right: 100, bottom: 50, name: 'a' }, { left: 200, top: 0, right: 300, bottom: 50, name: 'b' }];
  assert.equal(placeClear(candidates, [], (c) => (c.name === 'a' ? 10 : 0)).name, 'b');
  assert.equal(placeClear(candidates, [], () => 0).name, 'a');
});

test('boxes that only touch do not overlap', () => {
  assert.equal(overlapArea({ left: 0, top: 0, right: 10, bottom: 10 }, { left: 10, top: 0, right: 20, bottom: 10 }), 0);
  assert.equal(overlapArea({ left: 0, top: 0, right: 10, bottom: 10 }, { left: 5, top: 5, right: 20, bottom: 20 }), 25);
});

test('the docked card tries bottom right, top right, bottom left, then top left, inside the insets', () => {
  const boxes = cornerBoxes(PANE);
  assert.deepEqual(boxes.map((b) => b.corner), ['bottom-right', 'top-right', 'bottom-left', 'top-left']);
  assert.deepEqual(boxes[0], { corner: 'bottom-right', left: 748, top: 400, right: 988, bottom: 560 });
  assert.deepEqual(boxes[3], { corner: 'top-left', left: 12, top: 90, right: 252, bottom: 250 });
});

test('a picked part at the bottom right moves the docked card to the top right', () => {
  assert.equal(placeClear(cornerBoxes(PANE), [{ left: 700, top: 380, right: 900, bottom: 520 }]).corner, 'top-right');
});

test('a part on the right with its source line out to the left: the card takes the corner that covers least', () => {
  const part = { left: 600, top: 300, right: 1000, bottom: 600 };
  const line = { left: 0, top: 120, right: 800, bottom: 420 };
  // Bottom right covers the part; top right 52 x 130 px of line, bottom left 240 x 20, top left 240 x 130.
  const choice = placeClear(cornerBoxes(PANE), [part, line]);
  assert.equal(choice.corner, 'bottom-left');
  assert.equal(overlapArea(choice, part), 0);
});

test('the hover label sits right of the part first (away from the drawing pane), then above, below, left', () => {
  const spots = besideBoxes({ part: { left: 300, top: 200, right: 500, bottom: 300 }, size: { width: 120, height: 24 }, bounds: { width: 1000, height: 600 }, gap: 8 });
  assert.deepEqual(spots.map((s) => s.side), ['right', 'above', 'below', 'left']);
  assert.deepEqual(spots[0], { side: 'right', left: 508, top: 200, right: 628, bottom: 224 });
  assert.deepEqual(spots[1], { side: 'above', left: 300, top: 168, right: 420, bottom: 192 });
});

test('a label beside a part at the pane edge stays inside the pane and off the part', () => {
  const part = { left: 900, top: 2, right: 998, bottom: 40 };
  const spots = besideBoxes({ part, size: { width: 120, height: 24 }, bounds: { width: 1000, height: 600 }, gap: 8 });
  for (const spot of spots) assert.ok(spot.left >= 0 && spot.right <= 1000 && spot.top >= 0 && spot.bottom <= 600, spot.side);
  // No room right of or above the part: clamped, those would cover it, so below wins.
  assert.equal(placeClear(spots, [part]).side, 'below');
});
