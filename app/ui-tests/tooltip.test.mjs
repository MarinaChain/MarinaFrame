// Two-stage tooltip (js/tooltip.js): title after a delay, a ring, then the detail. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createTipMachine, TIP_DELAY_MS, RING_MS } from '../ui/js/tooltip.js';
import { reasonFacts, splitStepTitle } from '../ui/js/format.js';

/** A machine on a fake clock. `advance(ms)` runs the timers that fall due. */
function setup({ reduced = false } = {}) {
  let now = 0;
  let timers = [];
  let nextId = 1;
  const renders = [];
  const machine = createTipMachine({
    render: (view) => renders.push(view),
    setTimer: (fn, ms) => { const id = nextId++; timers.push({ id, at: now + ms, fn }); return id; },
    clearTimer: (id) => { timers = timers.filter((t) => t.id !== id); },
    reducedMotion: () => reduced,
  });
  function advance(ms) {
    const end = now + ms;
    for (;;) {
      const due = timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      timers = timers.filter((t) => t !== due);
      now = due.at;
      due.fn();
    }
    now = end;
  }
  return { machine, advance, renders, last: () => renders[renders.length - 1] };
}

const icon = { name: 'AI corrected chip' };

test('hover shows the title after the delay, then the ring, then the detail', () => {
  const { machine, advance, last } = setup();
  machine.enter(icon, { detail: true });
  assert.equal(machine.state, 'pending');
  advance(TIP_DELAY_MS - 1);
  assert.equal(machine.state, 'pending');
  advance(1);
  assert.equal(machine.state, 'ringing');
  assert.equal(last().ring, true);
  advance(RING_MS - 1);
  assert.equal(machine.state, 'ringing');
  advance(1);
  assert.equal(machine.state, 'detail');
});

test('an element without a detail stops at the title, with no ring', () => {
  const { machine, advance, last } = setup();
  machine.enter(icon, { detail: false });
  advance(TIP_DELAY_MS + RING_MS * 2);
  assert.equal(machine.state, 'title');
  assert.equal(last().ring, false);
});

test('leaving before the ring completes cancels it', () => {
  const { machine, advance } = setup();
  machine.enter(icon, { detail: true });
  advance(TIP_DELAY_MS + RING_MS / 2);
  machine.leave();
  assert.equal(machine.state, 'idle');
  advance(RING_MS * 2);
  assert.equal(machine.state, 'idle');
});

test('leaving during the delay shows nothing', () => {
  const { machine, advance, renders } = setup();
  machine.enter(icon, { detail: true });
  advance(TIP_DELAY_MS / 2);
  machine.leave();
  advance(TIP_DELAY_MS * 4);
  assert.ok(renders.every((r) => r.state === 'pending' || r.state === 'idle'));
});

test('Escape closes at any stage', () => {
  const { machine, advance } = setup();
  machine.enter(icon, { detail: true });
  advance(TIP_DELAY_MS + RING_MS);
  assert.equal(machine.state, 'detail');
  machine.escape();
  assert.equal(machine.state, 'idle');
});

test('keyboard focus shows the title at once; Shift shows the detail', () => {
  const { machine } = setup();
  machine.enter(icon, { detail: true, via: 'focus' });
  assert.equal(machine.state, 'ringing');
  machine.expand();
  assert.equal(machine.state, 'detail');
});

test('reduced motion: no ring animation, the detail after the same time', () => {
  const { machine, advance, last } = setup({ reduced: true });
  machine.enter(icon, { detail: true });
  advance(TIP_DELAY_MS);
  assert.equal(last().ring, false);
  advance(RING_MS);
  assert.equal(machine.state, 'detail');
});

test('touch: a tap shows the title, a second tap the detail', () => {
  const { machine, advance } = setup();
  machine.enter(icon, { detail: true, via: 'touch' });
  assert.equal(machine.state, 'title');
  advance(RING_MS * 2);
  assert.equal(machine.state, 'title');
  machine.enter(icon, { detail: true, via: 'touch' });
  assert.equal(machine.state, 'detail');
});

test('moving to another element restarts from the delay', () => {
  const { machine, advance } = setup();
  machine.enter(icon, { detail: true });
  advance(TIP_DELAY_MS + RING_MS);
  const other = { name: 'Traced chip' };
  machine.leave();
  machine.enter(other, { detail: true });
  assert.equal(machine.state, 'pending');
  assert.equal(machine.owner, other);
});

test('a section reason becomes a compact fact; other reasons stay as they are', () => {
  assert.equal(reasonFacts('2 lines found; took the best-supported one (score 0.62).'), '2 lines · best 0.62');
  assert.equal(reasonFacts('1 line found; took the best-supported one (score 0.9).'), '1 line · best 0.9');
  assert.equal(reasonFacts('Picked the outer line.'), null);
});

test('step titles split into a short heading and the rest', () => {
  assert.deepEqual(splitStepTitle({ kind: 'finish', actor: 'model' }, 'Finished: Draft built from traced ink'), ['Finished', 'Draft built from traced ink']);
  assert.deepEqual(splitStepTitle({ kind: 'finish', actor: 'code' }, 'Stopped with a draft to check'), ['Stopped', 'Stopped with a draft to check']);
  assert.deepEqual(splitStepTitle({ kind: 'read' }, 'Read the labels'), ['Read the labels', null]);
});
