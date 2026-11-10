// Fairness view of the hull (js/fairness3d.js) and its test hull in the mock. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from '../ui/vendor/three/three.module.min.js';
import { STLLoader } from '../ui/vendor/three/STLLoader.js';
import {
  createFairness, FAIRNESS_MODES, fullCurvature, nextFairnessMode, patchFairnessShader, useSmoothNormals, zebraValue, ZEBRA_AXIS,
} from '../ui/js/fairness3d.js';

function loadHull(name) {
  const bytes = readFileSync(new URL(`../ui/mock/files/${name}`, import.meta.url));
  return new STLLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
}

/** The (y, z) points of the vertices at one frame x, one per z, starboard side only, sorted up. */
function sectionAt(geometry, x) {
  const position = geometry.getAttribute('position');
  const byZ = new Map();
  for (let i = 0; i < position.count; i += 1) {
    if (Math.abs(position.getX(i) - x) < 1e-4 && position.getY(i) >= 0) byZ.set(position.getZ(i).toFixed(4), [position.getY(i), position.getZ(i)]);
  }
  return [...byZ.values()].sort((a, b) => a[1] - b[1]);
}

/** The x of the mesh ring nearest a wanted x. */
function ringNear(geometry, wanted) {
  const position = geometry.getAttribute('position');
  let best = position.getX(0);
  for (let i = 0; i < position.count; i += 1) if (Math.abs(position.getX(i) - wanted) < Math.abs(best - wanted)) best = position.getX(i);
  return best;
}

function slope([y0, z0], [y1, z1]) {
  return (y1 - y0) / (z1 - z0);
}

test('the button steps off, zebra, curvature, off', () => {
  assert.deepEqual(FAIRNESS_MODES, ['off', 'zebra', 'curvature']);
  assert.equal(nextFairnessMode('off'), 'zebra');
  assert.equal(nextFairnessMode('zebra'), 'curvature');
  assert.equal(nextFairnessMode('curvature'), 'off');
});

test('the view starts with the fairness view off, and a mode sets one shared uniform', () => {
  const fairness = createFairness();
  assert.equal(fairness.mode, 'off');
  assert.equal(fairness.uniforms.fairnessMode.value, 0);
  fairness.setMode('zebra');
  assert.equal(fairness.uniforms.fairnessMode.value, 1);
  fairness.setMode('curvature');
  assert.equal(fairness.uniforms.fairnessMode.value, 2);
  assert.throws(() => fairness.setMode('shiny'), RangeError);
});

test('the curvature map is scaled to the beam of the hull', () => {
  const small = new THREE.Box3(new THREE.Vector3(0, -1, 0), new THREE.Vector3(10, 1, 1));
  const big = new THREE.Box3(new THREE.Vector3(0, -4, 0), new THREE.Vector3(40, 4, 4));
  assert.ok(fullCurvature(small) > fullCurvature(big));
  assert.equal(fullCurvature(new THREE.Box3()), 1);
  const fairness = createFairness();
  fairness.fit(big);
  assert.equal(fairness.uniforms.fairnessCurvature.value, fullCurvature(big));
});

test('the shader patch adds the fairness colour behind the mode uniform, and shares the uniforms', () => {
  const fairness = createFairness();
  const shader = {
    uniforms: {},
    fragmentShader: '#include <common>\nvoid main() {\n#include <dithering_fragment>\n}',
  };
  patchFairnessShader(shader, fairness);
  assert.equal(shader.uniforms.fairnessMode, fairness.uniforms.fairnessMode);
  assert.match(shader.fragmentShader, /uniform float fairnessMode;/);
  assert.match(shader.fragmentShader, /if \( fairnessMode > 0\.5 \) gl_FragColor\.rgb = fairnessColour/);
  // The fairness colour is written last, after tone mapping, so the bands stay black and white.
  assert.ok(shader.fragmentShader.indexOf('dithering_fragment') < shader.fragmentShader.indexOf('gl_FragColor.rgb'));
});

test('zebra bands: a flat surface has one value, a bent one changes along it', () => {
  const view = new THREE.Vector3(0, 1, 0);
  const reflect = (normal) => view.clone().negate().reflect(normal.clone().normalize());
  const flat = [0, 1, 2, 3].map(() => zebraValue(reflect(new THREE.Vector3(0, -1, 0.2))));
  assert.equal(new Set(flat).size, 1);
  const values = new Set();
  for (let tilt = 0; tilt < 1.2; tilt += 0.05) values.add(zebraValue(reflect(new THREE.Vector3(0, -1, tilt))));
  assert.deepEqual([...values].sort(), [0, 1]);
  assert.ok(Math.abs(ZEBRA_AXIS.length() - 1) < 1e-9);
});

test('smooth normals are made once, swapped in and out, and leave the vertices alone', () => {
  const geometry = loadHull('model.stl');
  const flat = geometry.getAttribute('normal');
  const positions = geometry.getAttribute('position').array.slice();
  assert.equal(useSmoothNormals(geometry, false), false, 'nothing to switch back before the first switch on');
  assert.equal(useSmoothNormals(geometry, true), true);
  const smooth = geometry.getAttribute('normal');
  assert.notEqual(smooth, flat);
  assert.equal(useSmoothNormals(geometry, true), false, 'a second call changes nothing');
  assert.equal(useSmoothNormals(geometry, false), true);
  assert.equal(geometry.getAttribute('normal'), flat);
  assert.equal(useSmoothNormals(geometry, true), true);
  assert.equal(geometry.getAttribute('normal'), smooth, 'the smooth normals are kept, not made again');
  assert.deepEqual(geometry.getAttribute('position').array, positions);
});

test('smooth normals of a faceted hull differ less between neighbours than the flat ones', () => {
  const geometry = loadHull('model.stl');
  const flat = geometry.getAttribute('normal');
  useSmoothNormals(geometry, true);
  const smooth = geometry.getAttribute('normal');
  // Two triangles of one quad share two corners; the flat normals of the triangles are equal,
  // but across a quad edge a flat hull jumps while a smooth one does not.
  const jump = (attribute, a, b) => new THREE.Vector3().fromBufferAttribute(attribute, a).angleTo(new THREE.Vector3().fromBufferAttribute(attribute, b));
  // Vertex 0 of the first triangle and the first vertex of the second triangle share the position.
  const position = geometry.getAttribute('position');
  let checked = 0;
  for (let i = 0; i < 60 && checked < 5; i += 1) {
    for (let j = i + 3; j < 60; j += 1) {
      if (position.getX(i) === position.getX(j) && position.getY(i) === position.getY(j) && position.getZ(i) === position.getZ(j)) {
        assert.ok(jump(smooth, i, j) < 1e-6, 'one shared point has one normal');
        assert.ok(jump(smooth, i, j) <= jump(flat, i, j));
        checked += 1;
      }
    }
  }
  assert.ok(checked > 0);
});

test('the fairness test hull has a kink and a flat spot, the plain mock hull has neither', () => {
  const faulty = loadHull('model-fair.stl');
  const plain = loadHull('model.stl');
  // The kink: the half-breadth slope over z steps by 0.25 x window at z = 1.6.
  const kinkX = ringNear(faulty, 11.5);
  const section = sectionAt(faulty, kinkX);
  const at = section.findIndex(([, z]) => Math.abs(z - 1.6) < 1e-3);
  assert.ok(at > 0 && at < section.length - 1, 'the section has a point on the kink line');
  const step = slope(section[at], section[at + 1]) - slope(section[at - 1], section[at]);
  assert.ok(Math.abs(step) > 0.2, `slope step ${step}`);
  const plainSection = sectionAt(plain, ringNear(plain, 11.5));
  const plainSteps = plainSection.slice(2).map((point, i) => Math.abs(slope(plainSection[i + 1], point) - slope(plainSection[i], plainSection[i + 1])));
  assert.ok(Math.max(...plainSteps.filter((_, i) => plainSection[i + 1][1] > 1.2 && plainSection[i + 1][1] < 2.0)) < 0.2);

  // The flat spot: the points between z = 0.5 and 1.5 lie on one straight line.
  const flatX = ringNear(faulty, 19);
  const patch = sectionAt(faulty, flatX).filter(([, z]) => z >= 0.5 - 1e-3 && z <= 1.5 + 1e-3);
  assert.ok(patch.length > 3);
  const chord = slope(patch[0], patch[patch.length - 1]);
  for (let i = 1; i < patch.length; i += 1) assert.ok(Math.abs(slope(patch[i - 1], patch[i]) - chord) < 0.02, 'a straight patch');
  const bent = sectionAt(plain, ringNear(plain, 19)).filter(([, z]) => z >= 0.5 && z <= 1.5);
  assert.ok(Math.abs(slope(bent[0], bent[1]) - slope(bent[bent.length - 2], bent[bent.length - 1])) > 0.1, 'the plain hull curves there');
});
