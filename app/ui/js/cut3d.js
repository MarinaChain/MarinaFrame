// Section cut of the 3D view: one clipping plane at a frame (x), a buttock (y) or a waterline (z),
// with solid cut faces. A cut face ("cap") is drawn with the stencil buffer: the back faces of a
// closed solid behind the plane add one, its front faces take one away, so the pixels where the
// count is not zero are inside the solid, and a plane drawn there in the solid's colour closes
// the cut (the three.js clipping-stencil method). Each capped solid has its own cap, in its colour.
//
// The plane is always on the materials; with no cut it is moved far away, so switching a cut on
// or off does not recompile a shader.
//
// A space (spaces3d.js) clips the model to a box with six more planes, always on the materials in
// the same way. The section cut and a space work together; the cut faces stay inside the space.

import * as THREE from '../vendor/three/three.module.min.js';
import { cutPlane } from './reference3d.js';
import { boxPlanes } from './spaces3d.js';

/** Plane constant with no cut: far beyond any vessel (metres), so nothing is clipped. */
const NO_CUT_CONSTANT = 1e7;
/** Cut faces are a little darker than their solid, so the cut reads as a cut. */
const CAP_SHADE = 0.82;
/** Render order of the first solid's stencil pass; each solid takes the next CAP_ORDER_STEP. */
const CAP_ORDER_START = 100;
const CAP_ORDER_STEP = 1;

/** Material of a stencil pass: no colour or depth, counts faces into the stencil buffer. */
function stencilMaterial(clippingPlanes, side, op) {
  return new THREE.MeshBasicMaterial({
    side,
    clippingPlanes,
    colorWrite: false,
    depthWrite: false,
    depthTest: false,
    stencilWrite: true,
    stencilFunc: THREE.AlwaysStencilFunc,
    stencilFail: op,
    stencilZFail: op,
    stencilZPass: op,
  });
}

export function createSectionCut({ scene }) {
  const plane = new THREE.Plane(new THREE.Vector3(1, 0, 0), NO_CUT_CONSTANT);
  /** The six planes of the space box; open (far away) with no space. */
  const spacePlanes = boxPlanes(null).map((spec) => new THREE.Plane(new THREE.Vector3(...spec.normal), spec.constant));
  /** The shared clipping planes of every model material (seven planes, always present). */
  const planes = [plane, ...spacePlanes];
  let spaceBox = null;
  const backMaterial = stencilMaterial(planes, THREE.BackSide, THREE.IncrementWrapStencilOp);
  const frontMaterial = stencilMaterial(planes, THREE.FrontSide, THREE.DecrementWrapStencilOp);
  const capGroup = new THREE.Group();
  capGroup.visible = false;
  scene.add(capGroup);
  /** One record per capped solid: { mesh, back, front, cap, colour() }. */
  let solids = [];
  let state = { axis: null, value: 0, flipped: false };
  let capSize = 100;

  function placeCaps() {
    const centre = plane.coplanarPoint(new THREE.Vector3());
    for (const solid of solids) {
      solid.cap.position.copy(centre);
      solid.cap.lookAt(centre.clone().sub(plane.normal));
      solid.cap.scale.setScalar(capSize);
    }
  }

  function updateVisibility() {
    const on = Boolean(state.axis);
    capGroup.visible = on;
    for (const solid of solids) {
      let shown = solid.mesh.visible;
      solid.mesh.traverseAncestors((node) => { if (!node.visible) shown = false; });
      const show = on && shown && solid.capped();
      solid.back.visible = show;
      solid.front.visible = show;
      solid.cap.visible = show;
    }
  }

  /** Draw the cut face of one solid in its colour (stencil not zero), then clear the stencil. */
  function makeCap(order) {
    const material = new THREE.MeshStandardMaterial({
      roughness: 0.7,
      metalness: 0,
      side: THREE.DoubleSide,
      clippingPlanes: spacePlanes,
      stencilWrite: true,
      stencilRef: 0,
      stencilFunc: THREE.NotEqualStencilFunc,
      stencilFail: THREE.ReplaceStencilOp,
      stencilZFail: THREE.ReplaceStencilOp,
      stencilZPass: THREE.ReplaceStencilOp,
    });
    const cap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
    cap.renderOrder = order + 0.5;
    cap.onAfterRender = (renderer) => renderer.clearStencil();
    return cap;
  }

  return {
    planes,
    get state() {
      return { ...state };
    },
    get active() {
      return Boolean(state.axis);
    },
    /** True when a world point is on the kept side of the cut and inside the space (true with neither). */
    keeps(point) {
      for (const each of planes) if (each.distanceToPoint(point) < 0) return false;
      return true;
    },
    /** The box the model is clipped to ({ min, max } in metres), or null. */
    get space() {
      return spaceBox;
    },
    /** Clip the model to a box (a space), or end the clip with null. */
    setSpace(box) {
      spaceBox = box;
      boxPlanes(box).forEach((spec, i) => {
        spacePlanes[i].normal.fromArray(spec.normal);
        spacePlanes[i].constant = spec.constant;
      });
    },
    /** Set the cut: `axis` "x", "y", "z" or null (off), `value` in metres, `flipped` keeps the other side. */
    set({ axis = state.axis, value = state.value, flipped = state.flipped } = {}) {
      state = { axis, value, flipped };
      if (axis) {
        const spec = cutPlane(axis, value, flipped);
        plane.normal.fromArray(spec.normal);
        plane.constant = spec.constant;
      } else {
        plane.normal.set(1, 0, 0);
        plane.constant = NO_CUT_CONSTANT;
      }
      placeCaps();
      updateVisibility();
    },
    /** Size the cap planes for a model box (THREE.Box3), so a cap covers every cut solid. */
    fit(box) {
      capSize = box && !box.isEmpty() ? box.getSize(new THREE.Vector3()).length() * 2 : 100;
      placeCaps();
    },
    /**
     * Cap a closed solid mesh, placed where it is now (its world matrix; models do not move).
     * `colour()` gives its colour (THREE.Color); `capped()` says whether it shows a cut face now
     * (a see-through shell does not, or its face would hide the inside). The solid shows a cap
     * only while the mesh is visible (a layer switched off hides it).
     */
    addSolid(mesh, { colour, capped = () => true }) {
      const order = CAP_ORDER_START + solids.length * CAP_ORDER_STEP;
      mesh.updateWorldMatrix(true, false);
      const pass = (material) => {
        const helper = new THREE.Mesh(mesh.geometry, material);
        helper.matrixAutoUpdate = false;
        helper.matrix.copy(mesh.matrixWorld);
        helper.renderOrder = order;
        helper.raycast = () => {};
        // The stencil passes never cast or take shadows, and are outside the model's tree, so
        // they still draw when the model draws its solid another way (a batch).
        capGroup.add(helper);
        return helper;
      };
      const back = pass(backMaterial);
      const front = pass(frontMaterial);
      const cap = makeCap(order);
      capGroup.add(cap);
      solids.push({ mesh, back, front, cap, colour, capped });
      placeCaps();
      updateVisibility();
    },
    /** Forget the solids under `root` (removed from the scene), or every solid with no root. */
    removeSolids(root = null) {
      const keep = [];
      for (const solid of solids) {
        let inside = !root;
        solid.mesh.traverseAncestors((node) => { if (node === root) inside = true; });
        if (solid.mesh === root) inside = true;
        if (!inside) {
          keep.push(solid);
          continue;
        }
        capGroup.remove(solid.back, solid.front, solid.cap);
        solid.cap.geometry.dispose();
        solid.cap.material.dispose();
      }
      solids = keep;
    },
    /** Colour the caps (after a theme or a style change) and show only the caps that apply. */
    refresh() {
      for (const solid of solids) solid.cap.material.color.copy(solid.colour()).multiplyScalar(CAP_SHADE);
      updateVisibility();
    },
  };
}
