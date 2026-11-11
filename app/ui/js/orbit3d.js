// Settings of the orbit controls of the 3D view, kept apart from the view so a test can check them.

/** Damping share per frame; a higher value stops the view sooner after a drag. */
const DAMPING_FACTOR = 0.12;

/**
 * Set up the orbit controls: the wheel zooms toward the pointer (the point under the pointer
 * stays under it, as in CAD viewers), the view eases to a stop unless the user asks for reduced
 * motion, and the camera never goes below the horizon, so the profile and body plan views are level.
 */
export function configureOrbit(controls, { reducedMotion = false } = {}) {
  controls.zoomToCursor = true;
  controls.enableDamping = !reducedMotion;
  controls.dampingFactor = DAMPING_FACTOR;
  controls.maxPolarAngle = Math.PI / 2;
  return controls;
}
