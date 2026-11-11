// Orbit controls of the 3D view (js/orbit3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../ui/vendor/three/three.module.min.js';
import { OrbitControls } from '../ui/vendor/three/OrbitControls.js';
import { configureOrbit } from '../ui/js/orbit3d.js';

/** A stand-in for the canvas: it keeps the wheel listener and has a 1000 x 500 box. */
function fakeCanvas() {
  const listeners = {};
  return {
    listeners,
    style: {},
    addEventListener(type, handler) { listeners[type] = handler; },
    removeEventListener() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 500 }),
    setPointerCapture() {},
    releasePointerCapture() {},
    getRootNode: () => ({ addEventListener() {}, removeEventListener() {} }),
    ownerDocument: { addEventListener() {}, removeEventListener() {} },
  };
}

function wheelAt(canvas, clientX, clientY, deltaY) {
  canvas.listeners.wheel({ deltaY, deltaMode: 0, clientX, clientY, ctrlKey: false, preventDefault() {} });
}

function viewFrom() {
  const camera = new THREE.PerspectiveCamera(35, 2, 0.05, 2000);
  camera.up.set(0, 0, 1);
  camera.position.set(20, -30, 15);
  camera.lookAt(0, 0, 0);
  const canvas = fakeCanvas();
  const controls = new OrbitControls(camera, canvas);
  return { camera, canvas, controls };
}

test('the vendored controls support zoom to cursor, and the view turns it on', () => {
  const { controls } = viewFrom();
  assert.equal('zoomToCursor' in controls, true);
  configureOrbit(controls, { reducedMotion: false });
  assert.equal(controls.zoomToCursor, true);
  assert.equal(controls.enableDamping, true);
  assert.equal(controls.maxPolarAngle, Math.PI / 2);
});

test('reduced motion turns damping off', () => {
  const { controls } = viewFrom();
  configureOrbit(controls, { reducedMotion: true });
  assert.equal(controls.enableDamping, false);
});

test('zooming in at an off-centre pointer keeps that point under the pointer', () => {
  const { camera, canvas, controls } = viewFrom();
  configureOrbit(controls, { reducedMotion: true });
  controls.update();
  // The point of the model under the pointer, found on the plane through the target.
  const pointer = new THREE.Vector2((800 / 1000) * 2 - 1, -((150 / 500) * 2 - 1));
  const ray = new THREE.Raycaster();
  ray.setFromCamera(pointer, camera);
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), controls.target);
  const point = ray.ray.intersectPlane(plane, new THREE.Vector3());
  const distanceBefore = camera.position.distanceTo(point);

  wheelAt(canvas, 800, 150, -100);
  controls.update();

  const after = new THREE.Raycaster();
  after.setFromCamera(pointer, camera);
  // The pointer ray still passes through the same model point, and the camera is closer to it.
  assert.ok(after.ray.distanceToPoint(point) < 1e-6, `ray misses the point by ${after.ray.distanceToPoint(point)}`);
  assert.ok(camera.position.distanceTo(point) < distanceBefore);
});

test('without zoom to cursor the same wheel step moves the target nowhere', () => {
  const { canvas, controls } = viewFrom();
  controls.update();
  wheelAt(canvas, 800, 150, -100);
  controls.update();
  assert.deepEqual(controls.target.toArray(), [0, 0, 0]);
});
