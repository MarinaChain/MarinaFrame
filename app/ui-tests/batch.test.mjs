// Batch queue (js/batch.js): the run-slot line. Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { slotLine } from '../ui/js/batch.js';

test('the slot line never says more slots are in use than there are', () => {
  assert.equal(slotLine({ running: 1, slots: 4 }), '1 of 4 run slots in use. The next set starts when a slot is free.');
  // Runs started outside the queue can exceed the limit; they wait for admission in the worker.
  assert.match(slotLine({ running: 6, slots: 4 }), /^4 of 4 /);
});
