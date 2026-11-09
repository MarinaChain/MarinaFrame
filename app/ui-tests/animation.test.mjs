// One-at-a-time animation (js/animation.js) and the stage layout rule (styles.css).
// Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createAnimation } from '../ui/js/animation.js';

/** A frame queue the test advances by hand. */
function fakeFrames() {
  const pending = new Map();
  let nextId = 1;
  return {
    requestFrame(callback) {
      pending.set(nextId, callback);
      return nextId++;
    },
    cancelFrame(id) {
      pending.delete(id);
    },
    /** Run every callback that waits now, at time `now`. */
    flush(now) {
      const callbacks = [...pending.values()];
      pending.clear();
      for (const callback of callbacks) callback(now);
    },
    get size() {
      return pending.size;
    },
  };
}

test('an animation runs until its step returns false', () => {
  const frames = fakeFrames();
  const animation = createAnimation(frames);
  const seen = [];
  animation.start((now) => {
    seen.push(now);
    return now < 2;
  });
  assert.equal(animation.running, true);
  frames.flush(1);
  frames.flush(2);
  frames.flush(3);
  assert.deepEqual(seen, [1, 2]);
  assert.equal(animation.running, false);
});

test('a new animation stops the one before it (a closed run must not move the camera)', () => {
  const frames = fakeFrames();
  const animation = createAnimation(frames);
  const steps = [];
  animation.start(() => { steps.push('old'); return true; });
  frames.flush(1);
  animation.start(() => { steps.push('new'); return true; });
  frames.flush(2);
  frames.flush(3);
  assert.deepEqual(steps, ['old', 'new', 'new']);
  assert.equal(frames.size, 1);
});

test('cancel stops the animation before its next frame', () => {
  const frames = fakeFrames();
  const animation = createAnimation(frames);
  let calls = 0;
  animation.start(() => { calls += 1; return true; });
  frames.flush(1);
  animation.cancel();
  frames.flush(2);
  assert.equal(calls, 1);
  assert.equal(animation.running, false);
  assert.equal(frames.size, 0);
});

test('a pane alone fills the stage in the drawing-only and model-only layouts', () => {
  // The split shares are flex-grow values below 1. Alone, such a pane takes only that
  // fraction of the width, so each single-pane layout must reset the pane to flex 1.
  const css = readFileSync(new URL('../ui/styles.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const [view, pane] of [['drawing', 'pane-drawing'], ['model', 'pane-model']]) {
    const selector = `.stage[data-view="${view}"] .${pane}`;
    const rule = css.split('}').find((block) => block.split('{')[0].split(',').some((s) => s.trim() === selector) && /\bflex:\s*1 1 0;/.test(block));
    assert.ok(rule, `${selector} must set flex: 1 1 0`);
  }
});
