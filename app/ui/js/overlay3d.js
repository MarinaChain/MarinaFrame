// Engineering overlays of the 3D view, as on a lines plan: a reference grid on the base plane
// (stations by frame, buttocks, the centreline), the baseline and waterlines on the centreline
// plane, the design waterline plane, frame ticks with frame numbers along the hull, feature
// edges for a crisp CAD look, and screen overlays: a scale bar, an axis triad, the reference
// values with their source, the draft stamp and the pointer readout.

import * as THREE from '../vendor/three/three.module.min.js';
import { el, svg } from './dom.js';
import { frameAt, frameLabel, frameLabelStep, guessedReferences, niceAtLeast, referenceLine, scaleBar } from './reference3d.js';

/** The grid reaches this share of the hull size past the hull on each side. */
const GRID_MARGIN = 0.15;
/** Frame ticks: every frame a short tick, every MAJOR_FRAME_EVERY frames a long one. */
const MAJOR_FRAME_EVERY = 5;
/** Tick lengths as a share of the beam. */
const TICK_SHARE = 0.025;
const MAJOR_TICK_SHARE = 0.06;
/** Feature edges: a face angle above this (degrees) draws an edge. */
export const FEATURE_EDGE_ANGLE_DEG = 30;
/** Opacity of the feature edges, light and dark theme. */
const EDGE_OPACITY = { light: 0.38, dark: 0.45 };
/** Opacity of the design waterline plane. */
const WATER_OPACITY = 0.16;
/** Size of the axis triad (CSS px) and the length of an axis in it. */
const TRIAD_SIZE = 64;
const TRIAD_AXIS = 22;
/** Axis names in the triad: x toward the bow, y to port, z up (the ship frame). */
const AXES = [
  { key: 'x', vector: new THREE.Vector3(1, 0, 0), title: 'x: forward' },
  { key: 'y', vector: new THREE.Vector3(0, 1, 0), title: 'y: to port' },
  { key: 'z', vector: new THREE.Vector3(0, 0, 1), title: 'z: up' },
];

function lines(points, material) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
  return new THREE.LineSegments(geometry, material);
}

export function createOverlays({ scene, host, clip }) {
  const group = new THREE.Group();
  scene.add(group);
  const minorMaterial = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.5, depthWrite: false });
  const majorMaterial = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.9, depthWrite: false });
  const waterMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: WATER_OPACITY, depthWrite: false, side: THREE.DoubleSide });
  const waterEdgeMaterial = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.8 });
  /** One material for every feature edge, so a theme change is one colour change. */
  const edgeMaterial = clip(new THREE.LineBasicMaterial({ transparent: true, opacity: EDGE_OPACITY.light, depthWrite: false }));
  const parts = { grid: new THREE.Group(), waterline: new THREE.Group(), frames: new THREE.Group() };
  group.add(parts.grid, parts.waterline, parts.frames);
  /** Which overlays show (the tool bar switches them). */
  const shown = { grid: true, waterline: false, frames: true, edges: true };
  /**
   * Feature edges, one merged line set per kind of part ("hull", "shell", "steel", "tanks"), in
   * world space: one draw call each, however many parts. key -> { lines, layer, always, ranges }.
   */
  const edgeSets = new Map();
  let frameLine = null; // { reference, y, z, first, last }

  // ---- Screen overlays.
  const frameLabels = el('div', { class: 'model-frame-labels', 'aria-hidden': 'true' });
  const readout = el('div', { class: 'model-readout', 'aria-hidden': 'true', hidden: true });
  const triad = svg('svg', { class: 'model-triad', viewBox: `${-TRIAD_SIZE / 2} ${-TRIAD_SIZE / 2} ${TRIAD_SIZE} ${TRIAD_SIZE}`, width: TRIAD_SIZE, height: TRIAD_SIZE, role: 'img', 'aria-label': 'Axes: x forward, y to port, z up' });
  const triadAxes = AXES.map((axis) => {
    const line = svg('line', { class: `model-triad-${axis.key}`, x1: 0, y1: 0, x2: 0, y2: 0 });
    const label = svg('text', { class: `model-triad-${axis.key}`, 'text-anchor': 'middle', 'dominant-baseline': 'central' }, axis.key);
    const node = svg('g', {}, svg('title', {}, axis.title), line, label);
    triad.append(node);
    return { axis, node, line, label };
  });
  const scaleLine = el('span', { class: 'model-scale-bar' });
  const scaleText = el('span', { class: 'model-scale-text' });
  const scale = el('div', { class: 'model-scale', role: 'img', 'aria-label': 'Scale' }, scaleLine, scaleText);
  const referenceText = el('span', { class: 'model-reference-text' });
  const guessedMark = el('span', { class: 'model-badge', dataset: { tone: 'guess' }, hidden: true }, 'guessed');
  const corner = el('div', { class: 'model-corner' },
    el('div', { class: 'model-corner-row' }, scale, triad),
    el('div', { class: 'model-corner-row' },
      el('span', { class: 'model-reference' }, referenceText, guessedMark),
      el('span', { class: 'model-badge', dataset: { tone: 'draft' }, title: 'Draft, not for construction', 'aria-label': 'Draft, not for construction' }, 'Draft')));
  corner.hidden = true;
  host.append(frameLabels, readout, corner);

  function clearGroup(target) {
    for (const child of [...target.children]) {
      target.remove(child);
      child.geometry?.dispose();
    }
  }

  /** Build the grid, the waterline plane and the frame ticks for a scene box and a hull reference. */
  function build(sceneBox, reference, hullBox = sceneBox) {
    for (const target of Object.values(parts)) clearGroup(target);
    frameLine = null;
    if (!sceneBox || sceneBox.isEmpty()) {
      corner.hidden = true;
      return;
    }
    const size = sceneBox.getSize(new THREE.Vector3());
    const z0 = sceneBox.min.z - 0.001;
    const x0 = sceneBox.min.x - size.x * GRID_MARGIN;
    const x1 = sceneBox.max.x + size.x * GRID_MARGIN;
    const halfY = Math.max(Math.abs(sceneBox.min.y), Math.abs(sceneBox.max.y)) + size.y * GRID_MARGIN * 2;
    const minor = [];
    const major = [];
    // Stations: one line per frame (or per metre with no reference), every fifth frame stronger.
    const spacing = reference?.frameSpacingM.value || 1;
    const zeroX = reference?.frameZeroX.value || 0;
    const firstFrame = Math.ceil(frameAt(x0, spacing, zeroX));
    const lastFrame = Math.floor(frameAt(x1, spacing, zeroX));
    // Very dense frames (a long hull) are drawn every few frames so the grid stays a grid.
    const frameStep = niceAtLeast(Math.max(1, (lastFrame - firstFrame) / 120));
    for (let n = Math.ceil(firstFrame / frameStep) * frameStep; n <= lastFrame; n += frameStep) {
      const x = zeroX + n * spacing;
      (n % (MAJOR_FRAME_EVERY * frameStep) === 0 ? major : minor).push(x, -halfY, z0, x, halfY, z0);
    }
    // Buttocks: a round step about a tenth of the beam; the centreline is drawn strong.
    const buttockStep = niceAtLeast(size.y / 10);
    for (let y = buttockStep; y <= halfY; y += buttockStep) minor.push(x0, y, z0, x1, y, z0, x0, -y, z0, x1, -y, z0);
    major.push(x0, 0, z0, x1, 0, z0);
    // Centreline plane: the baseline strong and waterlines at a round step up to the hull top.
    const base = reference?.baselineZ ?? hullBox.min.z;
    const top = hullBox.max.z;
    major.push(hullBox.min.x, 0, base, hullBox.max.x, 0, base);
    const waterStep = niceAtLeast((top - base) / 6);
    for (let z = base + waterStep; z <= top + 1e-6; z += waterStep) minor.push(hullBox.min.x, 0, z, hullBox.max.x, 0, z);
    parts.grid.add(lines(minor, minorMaterial), lines(major, majorMaterial));

    if (reference) {
      // Design waterline plane, a little larger than the hull, with its outline.
      const hullSize = hullBox.getSize(new THREE.Vector3());
      const width = hullSize.x * 1.08;
      const depth = hullSize.y * 1.25;
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), waterMaterial);
      const centre = hullBox.getCenter(new THREE.Vector3());
      plane.position.set(centre.x, centre.y, reference.designWaterlineZ.value);
      plane.renderOrder = 2;
      const outline = new THREE.LineSegments(new THREE.EdgesGeometry(plane.geometry), waterEdgeMaterial);
      outline.position.copy(plane.position);
      parts.waterline.add(plane, outline);

      // Frame ticks on the base plane along the starboard edge of the hull (the home view side).
      const y = hullBox.min.y - hullSize.y * 0.08;
      const ticks = [];
      const first = Math.ceil(frameAt(hullBox.min.x, spacing, zeroX));
      const last = Math.floor(frameAt(hullBox.max.x, spacing, zeroX));
      for (let n = first; n <= last; n += 1) {
        const x = zeroX + n * spacing;
        const length = hullSize.y * (n % MAJOR_FRAME_EVERY === 0 ? MAJOR_TICK_SHARE : TICK_SHARE);
        ticks.push(x, y, z0, x, y - length, z0);
      }
      ticks.push(zeroX + first * spacing, y, z0, zeroX + last * spacing, y, z0);
      parts.frames.add(lines(ticks, majorMaterial));
      frameLine = { reference, y: y - hullSize.y * MAJOR_TICK_SHARE * 1.6, z: z0, first, last };
      referenceText.textContent = referenceLine(reference);
      const guessed = guessedReferences(reference);
      guessedMark.hidden = !guessed.length;
      guessedMark.title = guessed.length ? `Guessed from the hull size (the run does not give it): ${guessed.join(' and ')}.` : '';
      guessedMark.setAttribute('aria-label', guessedMark.title);
    } else {
      referenceText.textContent = '';
      guessedMark.hidden = true;
    }
    corner.hidden = false;
    applyVisibility();
  }

  function applyVisibility() {
    parts.grid.visible = shown.grid;
    parts.waterline.visible = shown.waterline;
    parts.frames.visible = shown.frames;
    for (const set of edgeSets.values()) set.lines.visible = set.layer && (set.always || shown.edges);
    if (!shown.frames) frameLabels.replaceChildren();
  }

  const projected = new THREE.Vector3();
  /** Screen position (CSS px) of a world point, or null behind the camera or off screen. */
  function toScreen(point, camera, width, height) {
    projected.copy(point).project(camera);
    if (projected.z > 1 || Math.abs(projected.x) > 1.05 || Math.abs(projected.y) > 1.05) return null;
    return { x: (projected.x + 1) / 2 * width, y: (1 - projected.y) / 2 * height };
  }

  function updateFrameLabels(camera, width, height) {
    if (!frameLine || !shown.frames) {
      if (frameLabels.childElementCount) frameLabels.replaceChildren();
      return;
    }
    const { reference, y, z, first, last } = frameLine;
    const spacing = reference.frameSpacingM.value;
    const zeroX = reference.frameZeroX.value;
    // Screen length of one frame at the middle of the hull sets how many numbers fit.
    const middle = Math.round((first + last) / 2);
    const a = toScreen(new THREE.Vector3(zeroX + middle * spacing, y, z), camera, width, height);
    const b = toScreen(new THREE.Vector3(zeroX + (middle + 1) * spacing, y, z), camera, width, height);
    const step = a && b ? frameLabelStep(Math.hypot(b.x - a.x, b.y - a.y)) : Infinity;
    const nodes = [];
    if (Number.isFinite(step)) {
      for (let n = Math.ceil(first / step) * step; n <= last; n += step) {
        const at = toScreen(new THREE.Vector3(zeroX + n * spacing, y, z), camera, width, height);
        if (!at) continue;
        nodes.push(el('span', { class: 'model-frame-label', style: { left: `${at.x.toFixed(1)}px`, top: `${at.y.toFixed(1)}px` } }, frameLabel(n).replace('Fr ', '')));
      }
    }
    if (nodes.length) nodes[0].textContent = `Fr ${nodes[0].textContent}`;
    frameLabels.replaceChildren(...nodes);
  }

  function updateTriad(camera) {
    for (const { axis, line, label } of triadAxes) {
      const v = axis.vector.clone().transformDirection(camera.matrixWorldInverse);
      const x = v.x * TRIAD_AXIS;
      const y = -v.y * TRIAD_AXIS;
      line.setAttribute('x2', x.toFixed(1));
      line.setAttribute('y2', y.toFixed(1));
      label.setAttribute('x', (x * 1.32).toFixed(1));
      label.setAttribute('y', (y * 1.32).toFixed(1));
    }
    // Axes pointing away from the viewer are drawn first, so the nearer ones are on top.
    const order = [...triadAxes].sort((p, q) => p.axis.vector.clone().transformDirection(camera.matrixWorldInverse).z
      - q.axis.vector.clone().transformDirection(camera.matrixWorldInverse).z);
    for (const { node } of order) triad.append(node);
  }

  return {
    build,
    /** Show or hide overlays: { grid, waterline, frames, edges } (missing keys keep their state). */
    set(next) {
      Object.assign(shown, next);
      applyVisibility();
    },
    get shown() {
      return { ...shown };
    },
    /**
     * Draw the feature edges of `meshes` as one line set under `key` (replacing the old one).
     * Meshes keep their place (world matrices are read now; models do not move). With
     * `colourOf(mesh)` each part's edges take that colour; `always` keeps them on when the
     * Edges switch is off (tank outlines belong to the capacity-plan look).
     */
    setEdges(key, meshes, { colourOf = null, always = false } = {}) {
      this.removeEdges(key);
      if (!meshes.length) return;
      const positions = [];
      const ranges = [];
      for (const mesh of meshes) {
        mesh.updateWorldMatrix(true, false);
        const edges = new THREE.EdgesGeometry(mesh.geometry, FEATURE_EDGE_ANGLE_DEG);
        edges.applyMatrix4(mesh.matrixWorld);
        const array = edges.getAttribute('position').array;
        ranges.push({ mesh, start: positions.length / 3, count: array.length / 3 });
        for (let i = 0; i < array.length; i += 1) positions.push(array[i]);
        edges.dispose();
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      let material = edgeMaterial;
      if (colourOf) {
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(positions.length), 3));
        material = clip(new THREE.LineBasicMaterial({ vertexColors: true }));
      }
      const lines = new THREE.LineSegments(geometry, material);
      lines.raycast = () => {};
      // Edges of a part lie on its faces: draw them after the faces, so they win the depth tie.
      lines.renderOrder = 1;
      group.add(lines);
      const set = { lines, layer: true, always, ranges, colourOf };
      edgeSets.set(key, set);
      if (colourOf) this.recolourEdges(key);
      applyVisibility();
    },
    /** Colour a coloured edge set again (after a theme change). */
    recolourEdges(key) {
      const set = edgeSets.get(key);
      if (!set?.colourOf) return;
      const colours = set.lines.geometry.getAttribute('color');
      for (const { mesh, start, count } of set.ranges) {
        const colour = set.colourOf(mesh);
        for (let i = start; i < start + count; i += 1) colours.setXYZ(i, colour.r, colour.g, colour.b);
      }
      colours.needsUpdate = true;
    },
    /** Show or hide one edge set with its layer (tanks, steel). */
    setEdgesLayer(key, visible) {
      const set = edgeSets.get(key);
      if (!set) return;
      set.layer = visible;
      applyVisibility();
    },
    removeEdges(key) {
      const set = edgeSets.get(key);
      if (!set) return;
      group.remove(set.lines);
      set.lines.geometry.dispose();
      if (set.lines.material !== edgeMaterial) set.lines.material.dispose();
      edgeSets.delete(key);
    },
    /** Move the screen overlays with the camera. `metresPerPixel` is at the orbit target. */
    update(camera, width, height, metresPerPixel) {
      updateFrameLabels(camera, width, height);
      updateTriad(camera);
      if (metresPerPixel > 0) {
        const bar = scaleBar(metresPerPixel, 110);
        scaleLine.style.setProperty('width', `${bar.px.toFixed(1)}px`);
        scaleText.textContent = bar.text;
        scale.setAttribute('aria-label', `Scale: the bar is ${bar.text} at the centre of the view`);
      }
    },
    /** Show a pointer readout line, or hide it with null. */
    setReadout(text) {
      readout.hidden = !text;
      if (text) readout.textContent = text;
    },
    setColours({ grid, gridMinor, water, edge, dark }) {
      minorMaterial.color.copy(gridMinor);
      majorMaterial.color.copy(grid);
      waterMaterial.color.copy(water);
      waterEdgeMaterial.color.copy(water);
      edgeMaterial.color.copy(edge);
      edgeMaterial.opacity = dark ? EDGE_OPACITY.dark : EDGE_OPACITY.light;
    },
    hide() {
      for (const target of Object.values(parts)) clearGroup(target);
      frameLine = null;
      frameLabels.replaceChildren();
      corner.hidden = true;
    },
  };
}
