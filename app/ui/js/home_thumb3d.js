// One offscreen renderer for Home. Jobs are serial, GPU resources are released after each PNG.

import * as THREE from '../vendor/three/three.module.min.js';
import { STLLoader } from '../vendor/three/STLLoader.js';
import { GLTFLoader } from '../vendor/three/GLTFLoader.js';
import { cachedArtifact } from './artifacts.js';
import { thumbnailCacheKey, thumbnailFrame, thumbnailParts } from './home_thumb.js';

const WIDTH = 480;
const HEIGHT = 300; // Match the existing card's 16:10 paper, without cropping the vessel.
const memory = new Map();
let renderer;
let unavailable = false;
let queue = Promise.resolve();

function sharedRenderer() {
  if (unavailable) throw new Error('Thumbnail renderer unavailable');
  if (!renderer) {
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(1);
      renderer.setSize(WIDTH, HEIGHT, false);
      renderer.setClearColor(0, 0);
      renderer.domElement.addEventListener('webglcontextlost', () => { unavailable = true; });
    } catch (error) {
      unavailable = true;
      throw error;
    }
  }
  return renderer;
}

function disposeModel(root) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  root.traverse((object) => {
    if (object.geometry) geometries.add(object.geometry);
    for (const material of [object.material].flat().filter(Boolean)) {
      materials.add(material);
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
    }
  });
  for (const texture of textures) texture.dispose();
  for (const material of materials) material.dispose();
  for (const geometry of geometries) geometry.dispose();
}

function neutralPaint(color) {
  // Fixed neutral shades remain legible on both theme papers; the PNG stays transparent.
  return new THREE.MeshStandardMaterial({ color, roughness: 0.8, side: THREE.DoubleSide });
}

function hullWithParts(buffer, view) {
  const geometry = new STLLoader().parse(buffer);
  // STL has no units. Use the same length-based conversion as the workspace before
  // adding component boxes, which already use metres in the app's Z-up vessel frame.
  geometry.computeBoundingBox();
  const extent = geometry.boundingBox.max.x - geometry.boundingBox.min.x;
  const length = view.model?.length_m;
  if (Number.isFinite(length) && length > 0 && extent > 0) {
    geometry.scale(length / extent, length / extent, length / extent);
  }
  const root = new THREE.Group();
  root.add(new THREE.Mesh(geometry, neutralPaint(0x9aaab4)));
  const parts = thumbnailParts(view);
  if (parts.length) {
    const paint = neutralPaint(0xd5dce0);
    for (const part of parts) {
      const { min, max } = part.bbox_m;
      const dimensions = max.map((value, axis) => value - min[axis]);
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...dimensions), paint);
      mesh.position.set(...min.map((value, axis) => (value + max[axis]) / 2));
      root.add(mesh);
    }
  }
  return root;
}

async function loadModel(task, source, view) {
  const buffer = await cachedArtifact(source.format === 'glb' ? 'model' : 'stl', task, source.path);
  if (source.format === 'stl') return hullWithParts(buffer, view);
  const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(buffer, '', resolve, reject));
  const root = new THREE.Group();
  root.add(gltf.scene);
  root.rotation.x = Math.PI / 2; // Same Y-up to Z-up conversion as the workspace.
  root.scale.setScalar(0.001); // Whole-vessel files use millimetres.
  root.traverse((object) => { if (object.userData.kind === 'tank') object.visible = false; });
  return root;
}

async function render(task, source, view) {
  const gpu = sharedRenderer();
  const root = await loadModel(task, source, view);
  const scene = new THREE.Scene();
  const paint = neutralPaint(0x9aaab4);
  try {
    scene.add(root);
    // Whole-vessel models keep the existing uniform shading. Hull fallbacks carry
    // their own two materials so the lighter superstructure reads as a silhouette.
    if (source.format === 'glb') scene.overrideMaterial = paint;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x364555, 2));
    const light = new THREE.DirectionalLight(0xffffff, 3);
    light.position.set(1, 3, 5);
    scene.add(light);
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3()).length();
    if (!(size > 0) || !Number.isFinite(size)) throw new Error('Empty thumbnail model');
    const center = box.getCenter(new THREE.Vector3());
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, size * 0.01, size * 10);
    camera.up.set(0, 0, 1);
    const elevation = THREE.MathUtils.degToRad(10);
    const oblique = THREE.MathUtils.degToRad(20);
    // Positive Y is port in the app's vessel frame (the workspace profile looks from -Y).
    const direction = new THREE.Vector3(Math.sin(oblique) * Math.cos(elevation), Math.cos(oblique) * Math.cos(elevation), Math.sin(elevation));
    camera.position.copy(center).addScaledVector(direction, size * 3);
    camera.lookAt(center);
    camera.updateMatrixWorld(true);
    const corners = [];
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
      const point = new THREE.Vector3(x, y, z).applyMatrix4(camera.matrixWorldInverse);
      corners.push([point.x, point.y]);
    }
    const frame = thumbnailFrame(corners, WIDTH / HEIGHT);
    camera.left = frame.x - frame.halfHeight * WIDTH / HEIGHT;
    camera.right = frame.x + frame.halfHeight * WIDTH / HEIGHT;
    camera.bottom = frame.y - frame.halfHeight;
    camera.top = frame.y + frame.halfHeight;
    camera.updateProjectionMatrix();
    gpu.render(scene, camera);
    if (unavailable || gpu.getContext().isContextLost()) throw new Error('Thumbnail context lost');
    return gpu.domElement.toDataURL('image/png');
  } finally {
    disposeModel(root);
    paint.dispose();
    gpu.renderLists.dispose();
  }
}

/** Cached PNG per task, revision and model. Storage denial or quota never stops rendering. */
export function modelThumbnail(run, view, source) {
  const key = thumbnailCacheKey(run, view, source);
  if (memory.has(key)) return memory.get(key);
  const job = queue.then(async () => {
    try {
      const stored = localStorage.getItem(key);
      if (stored?.startsWith('data:image/png;base64,iVBORw0KGgo')) return stored;
    } catch { /* Storage can be blocked. */ }
    const url = await render(run.task, source, view);
    try { localStorage.setItem(key, url); } catch { /* Full or blocked storage: memory is enough. */ }
    return url;
  });
  memory.set(key, job);
  queue = job.catch(() => { memory.delete(key); });
  return job;
}
