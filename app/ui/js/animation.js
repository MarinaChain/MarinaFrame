// One animation at a time, run on animation frames. Starting a new animation or calling
// cancel() stops the one before it, so an old animation cannot finish later and
// overwrite newer state (for example a camera move toward the hull of a run that is closed).

/**
 * `requestFrame` and `cancelFrame` default to the browser's animation-frame functions;
 * tests pass their own.
 */
export function createAnimation({
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (id) => cancelAnimationFrame(id),
} = {}) {
  let frameId = 0;

  function cancel() {
    if (frameId) cancelFrame(frameId);
    frameId = 0;
  }

  /**
   * Run `step(now)` on each animation frame until it returns false. Stops the
   * animation that runs now, if there is one.
   */
  function start(step) {
    cancel();
    const tick = (now) => {
      frameId = 0;
      if (step(now)) frameId = requestFrame(tick);
    };
    frameId = requestFrame(tick);
  }

  return {
    start,
    cancel,
    get running() {
      return frameId !== 0;
    },
  };
}
