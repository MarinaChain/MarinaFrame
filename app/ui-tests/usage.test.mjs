// Key usage (js/usage.js): reset times and slot words. Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resetTime, resetIn, slotState } from '../ui/js/usage.js';

test('a reset time is read from an ISO time, seconds or milliseconds', () => {
  assert.equal(resetTime('2030-01-01T00:00:00Z'), Date.UTC(2030, 0, 1));
  assert.equal(resetTime(1_900_000_000), 1_900_000_000_000);
  assert.equal(resetTime('1900000000000'), 1_900_000_000_000);
  assert.equal(resetTime('soon'), null);
  assert.equal(resetTime(null), null);
});

test('the time left is said in large steps', () => {
  const now = 0;
  assert.equal(resetIn(now - 1, now), 'now');
  assert.equal(resetIn(now + 25 * 60_000, now), 'in 25 min');
  assert.equal(resetIn(now + 3 * 3_600_000, now), 'in 3 h');
  assert.equal(resetIn(now + 72 * 3_600_000, now), 'in 3 days');
  assert.equal(resetIn(null, now), null);
});

test('each slot gets one short word', () => {
  const slot = (number, highest, extra = {}) => ({ slot: number, usable: highest !== null, highest_percent: highest, error: null, ...extra });
  assert.equal(slotState(slot(2, 20), 2).word, 'Next run');
  assert.equal(slotState(slot(1, 40), 2).word, 'Ready');
  assert.equal(slotState(slot(1, 95), 2).word, 'Near limit');
  assert.equal(slotState(slot(2, 95), 2).word, 'Next, near limit');
  assert.equal(slotState(slot(3, null), 2).word, 'At limit');
  assert.equal(slotState(slot(3, null, { error: 'x' }), 2).word, 'Not checked');
});
