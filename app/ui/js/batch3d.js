// Batched drawing for the 3D view: many small solids (the tanks of a vessel) drawn as one
// THREE.BatchedMesh, so they cost one draw call however many there are, with a colour per
// solid. The source meshes stay in the scene for picking, labels and cut faces; they draw
// nothing themselves.

import * as THREE from '../vendor/three/three.module.min.js';

/** The source meshes draw nothing; the batch draws them. Raycasts still hit them. */
export const HIDDEN_MATERIAL = new THREE.MeshBasicMaterial({ visible: false });

/** A geometry with only the attributes a batch shares (position, normal), indexed. */
function batchGeometry(source) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', source.getAttribute('position'));
  if (!source.getAttribute('normal')) source.computeVertexNormals();
  geometry.setAttribute('normal', source.getAttribute('normal'));
  if (source.index) {
    geometry.setIndex(source.index);
  } else {
    const count = source.getAttribute('position').count;
    geometry.setIndex([...Array(count).keys()]);
  }
  return geometry;
}

/**
 * Draw `meshes` (placed in the world; their world matrices are read now) as one batch with
 * `material`. Returns { mesh, setColour(source, colour), setVisible(source, shown), dispose() }.
 */
export function createBatch(meshes, material) {
  const geometries = meshes.map((mesh) => batchGeometry(mesh.geometry));
  const vertexCount = geometries.reduce((sum, g) => sum + g.getAttribute('position').count, 0);
  const indexCount = geometries.reduce((sum, g) => sum + g.index.count, 0);
  const batch = new THREE.BatchedMesh(meshes.length, vertexCount, indexCount, material);
  const instanceOf = new Map();
  meshes.forEach((mesh, i) => {
    mesh.updateWorldMatrix(true, false);
    const instance = batch.addInstance(batch.addGeometry(geometries[i]));
    batch.setMatrixAt(instance, mesh.matrixWorld);
    instanceOf.set(mesh, instance);
  });
  // The batch is for drawing only: picking uses the source meshes.
  batch.raycast = () => {};
  return {
    mesh: batch,
    setColour(source, colour) {
      batch.setColorAt(instanceOf.get(source), colour);
    },
    /** Draw one solid or not (a hidden or ghost part leaves the batch). */
    setVisible(source, shown) {
      batch.setVisibleAt(instanceOf.get(source), shown);
    },
    dispose() {
      // The batch copied the geometries into its own buffers; the wrappers above share the
      // source attributes and were never drawn, so only the batch has GPU memory to free.
      batch.dispose();
    },
  };
}
