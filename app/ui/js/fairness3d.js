// Fairness view of the hull surface. Two ways to see a kink, a hollow or a flat spot that
// ordinary shading hides:
//   zebra      black and white bands that stand for parallel light strips in the room; the
//              surface reflects them, so a kink breaks a band and a flat spot widens one.
//   curvature  a colour map of how much the surface bends: convex red, concave blue, flat grey.
// Both are drawn by the paint material's own shader (look3d.js), so every hull part, section cuts
// and spaces work as before. A mode change sets one uniform: no new material, no recompile, and
// nothing is allocated per frame.

import * as THREE from '../vendor/three/three.module.min.js';
import { toCreasedNormals } from '../vendor/three/BufferGeometryUtils.js';

/** The modes in the order the toolbar button steps through them. */
export const FAIRNESS_MODES = ['off', 'zebra', 'curvature'];

/** Shader value of each mode (the `fairnessMode` uniform). */
const MODE_VALUE = { off: 0, zebra: 1, curvature: 2 };

/** The mode after `mode` when the toolbar button is pressed: off, zebra, curvature, off. */
export function nextFairnessMode(mode) {
  return FAIRNESS_MODES[(FAIRNESS_MODES.indexOf(mode) + 1) % FAIRNESS_MODES.length];
}

/** Bands of light across the full range of the reflection direction; 2 x this many dark bands. */
export const ZEBRA_BANDS = 7;
/**
 * The direction the bands change along, in world axes (z up): mostly up, so the bands run along
 * the hull like waterlines, and a little forward, so a bend along the length shows too.
 */
export const ZEBRA_AXIS = new THREE.Vector3(0.35, 0, 1).normalize();
/** Crease angle for the smooth normals: a sharper turn is a real chine and stays a hard edge. */
export const SMOOTH_CREASE_ANGLE = THREE.MathUtils.degToRad(50);
/** The curvature map is fully coloured where the surface bends with this radius, as a share of the beam. */
export const FULL_CURVATURE_RADIUS_PER_BEAM = 0.8;

/**
 * The zebra band value (0 dark, 1 light) of a reflection direction. The shader repeats this
 * calculation per pixel; it is here so a test can check the maths without a GPU.
 */
export function zebraValue(reflection, axis = ZEBRA_AXIS, bands = ZEBRA_BANDS) {
  const phase = reflection.dot(axis) * bands;
  return Math.abs((phase - Math.floor(phase)) - 0.5) * 2 >= 0.5 ? 1 : 0;
}

/** Curvature (1 / metre) at which the map is fully coloured, for a hull box (THREE.Box3 in metres). */
export function fullCurvature(box) {
  if (!box || box.isEmpty()) return 1;
  const size = box.getSize(new THREE.Vector3());
  const beam = Math.max(size.y, 1e-3);
  return 1 / (FULL_CURVATURE_RADIUS_PER_BEAM * beam);
}

/**
 * The fairness state of one view: the shader uniforms every paint material shares, and the
 * current mode. `setMode(mode)` changes it; `fit(box)` scales the curvature map to the hull.
 */
export function createFairness() {
  const uniforms = {
    fairnessMode: { value: MODE_VALUE.off },
    fairnessAxis: { value: ZEBRA_AXIS.clone() },
    fairnessBands: { value: ZEBRA_BANDS },
    fairnessCurvature: { value: 1 },
  };
  let mode = 'off';
  return {
    uniforms,
    get mode() {
      return mode;
    },
    setMode(next) {
      if (!(next in MODE_VALUE)) throw new RangeError(`Unknown fairness mode: ${next}`);
      mode = next;
      uniforms.fairnessMode.value = MODE_VALUE[next];
    },
    fit(box) {
      uniforms.fairnessCurvature.value = fullCurvature(box);
    },
  };
}

/** GLSL of the fairness colour; `normal` and `viewPosition` are in view space (the fragment's own). */
const FRAGMENT_FUNCTIONS = `
uniform float fairnessMode;
uniform vec3 fairnessAxis;
uniform float fairnessBands;
uniform float fairnessCurvature;

vec3 fairnessZebra( vec3 normal, vec3 toEye ) {
  vec3 reflected = inverseTransformDirection( reflect( -toEye, normal ), viewMatrix );
  float phase = dot( reflected, fairnessAxis ) * fairnessBands;
  float edge = max( fwidth( phase ), 1e-4 );
  float band = smoothstep( 0.5 - edge, 0.5 + edge, abs( fract( phase ) - 0.5 ) * 2.0 );
  return mix( vec3( 0.07, 0.08, 0.10 ), vec3( 0.95, 0.96, 0.97 ), band );
}

vec3 fairnessCurvatureColour( vec3 normal, vec3 toEye, vec3 viewPosition ) {
  // How fast the normal turns along the surface: the change of the normal over the change of
  // the position, along both screen directions. Positive where the surface bulges toward the eye.
  vec3 dpx = dFdx( viewPosition );
  vec3 dpy = dFdy( viewPosition );
  float kx = dot( dFdx( normal ), dpx ) / max( dot( dpx, dpx ), 1e-12 );
  float ky = dot( dFdy( normal ), dpy ) / max( dot( dpy, dpy ), 1e-12 );
  float bend = clamp( 0.5 * ( kx + ky ) / fairnessCurvature, -1.0, 1.0 );
  float strength = pow( abs( bend ), 0.5 );
  vec3 flatGrey = vec3( 0.78, 0.79, 0.80 );
  vec3 convex = vec3( 0.86, 0.26, 0.18 );
  vec3 concave = vec3( 0.17, 0.42, 0.78 );
  vec3 colour = mix( flatGrey, bend > 0.0 ? convex : concave, strength );
  // A little headlight shading keeps the form readable.
  return colour * ( 0.72 + 0.28 * clamp( dot( normal, toEye ), 0.0, 1.0 ) );
}

vec3 fairnessColour( vec3 normal, vec3 viewPosition ) {
  vec3 toEye = normalize( -viewPosition );
  return fairnessMode < 1.5 ? fairnessZebra( normal, toEye ) : fairnessCurvatureColour( normal, toEye, viewPosition );
}
`;

/**
 * Add the fairness colour to a MeshStandardMaterial shader (called from its onBeforeCompile).
 * With the mode off the fragment shader skips it.
 */
export function patchFairnessShader(shader, fairness) {
  Object.assign(shader.uniforms, fairness.uniforms);
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', `#include <common>\n${FRAGMENT_FUNCTIONS}`)
    // After tone mapping and the colour space, so the stripes keep their exact black and white.
    .replace('#include <dithering_fragment>', [
      '#include <dithering_fragment>',
      'if ( fairnessMode > 0.5 ) gl_FragColor.rgb = fairnessColour( normal, - vViewPosition );',
    ].join('\n'));
}

/** The flat and the smooth normals of each geometry made smooth so far. */
const normalSets = new WeakMap();

/**
 * Smooth the shading normals of an STL hull for the fairness view. An STL carries one normal per
 * triangle, which shows as facets in the stripes. The smooth normals are made once per geometry
 * and swapped in and out; the vertices are not touched. Returns true when it changed anything.
 */
export function useSmoothNormals(geometry, on) {
  let normals = normalSets.get(geometry);
  if (!normals) {
    if (!on) return false;
    normals = {
      flat: geometry.getAttribute('normal'),
      smooth: toCreasedNormals(geometry.clone(), SMOOTH_CREASE_ANGLE).getAttribute('normal'),
    };
    normalSets.set(geometry, normals);
  }
  const wanted = on ? normals.smooth : normals.flat;
  if (geometry.getAttribute('normal') === wanted) return false;
  geometry.setAttribute('normal', wanted);
  return true;
}
