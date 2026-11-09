// 3D view: the build's STL in an orbit view, with an engineering grid (overlay3d.js) and a thin
// plane at each section's x position. The hull frame is x along the length, y across, z up (metres).
// The scene renders only when something changes, so an idle window costs no GPU time.

import * as THREE from '../vendor/three/three.module.min.js';
import { OrbitControls } from '../vendor/three/OrbitControls.js';
import { STLLoader } from '../vendor/three/STLLoader.js';
import { GLTFLoader } from '../vendor/three/GLTFLoader.js';
import { el, fill as fillNode, icon, prefersReducedMotion } from './dom.js';
import { createSectionGrowth } from './growth3d.js';
import { createAnimation } from './animation.js';
import { placeLabels, steelLegend, steelToken, tankLegend, tankToken } from './tanks.js';
import { createLighting, createPaintMaterial, createSteelMaterial, createTankMaterial, setUpRenderer, stylePaint } from './look3d.js';
import { bootTopBand, fitDistance, frameLabel, frameAt, hullReference, nearestFrameX, pointReadout, STANDARD_VIEWS, viewOfKey } from './reference3d.js';
import { createOverlays } from './overlay3d.js';
import { createBatch, HIDDEN_MATERIAL } from './batch3d.js';
import { createSectionCut } from './cut3d.js';
import { createCutPanel, createToolbar, toolButton } from './controls3d.js';

/** Extra size of a section plane around the hull, as a fraction of beam and depth. */
const PLANE_MARGIN = 0.25;
/** Space kept around the hull in the home view, as a fraction of the fitted size (10%). */
const FRAME_MARGIN = 1.1;
/** Size of a guessed-range band around the hull, as a fraction of the hull's beam and depth. */
const GUESS_BAND_MARGIN = 0.04;
/** Camera direction for the default view: from forward, starboard and above (the iso view). */
const HOME_DIRECTION = new THREE.Vector3(...STANDARD_VIEWS.iso.direction).normalize();
/** Highest pixel ratio the view draws at. */
const MAX_PIXEL_RATIO = 2;
/** A pointer that moves less than this (CSS px) between press and release is a click, not a drag. */
const CLICK_SLOP_PX = 4;
/** The CAD worker's GLB is in millimetres. */
const MM_TO_M = 0.001;
/** Duration of an animated move to the home view. */
const HOME_MOVE_MS = 360;
/** Opacity of the hull and the other parts while tanks or steel show, so what is inside is seen. */
const SHELL_OPACITY_WITH_TANKS = 0.22;
/** Steel shell plating is see-through, so the frames and floors behind it show. */
const STEEL_SHELL_OPACITY = 0.35;
/** Tank edge lines are the tank colour darkened to this share. */
const TANK_EDGE_SHADE = 0.55;
/** Size of a tank name label (CSS px) for the overlap test; long names are cut in CSS. */
const LABEL_BOX = { charWidth: 6.4, padding: 22, height: 20, maxWidth: 180 };

/** Convert any CSS colour (including oklch) to a THREE.Color by painting one pixel. */
const colourProbe = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
function cssColour(value) {
  colourProbe.clearRect(0, 0, 1, 1);
  colourProbe.fillStyle = '#000';
  colourProbe.fillStyle = value;
  colourProbe.fillRect(0, 0, 1, 1);
  const [r, g, b] = colourProbe.getImageData(0, 0, 1, 1).data;
  return new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
}

function themeColours() {
  const style = getComputedStyle(document.documentElement);
  const read = (name) => cssColour(style.getPropertyValue(name).trim());
  return {
    background: read('--model-bg'),
    grid: read('--line-strong'),
    gridMinor: read('--line'),
    water: read('--model-water'),
    edge: read('--ink'),
    hull: read('--model-hull'),
    antifouling: read('--paint-antifouling'),
    bootTop: read('--paint-boottop'),
    plane: read('--text-3'),
    accent: read('--accent'),
    guess: read('--guess-ink'),
    tank: (contentClass) => read(tankToken(contentClass)),
    steel: (group) => read(steelToken(group)),
    // Section source labels, the same palette as the drawing and the section strip.
    source: {
      traced: read('--src-traced'),
      repaired: read('--src-repaired'),
      interpolated: read('--stroke-interpolated'),
      ai_inferred: read('--warn-ink'),
      ai_corrected: read('--stroke-ai_corrected'),
      omitted: read('--muted-line'),
    },
  };
}

/** Scale a mesh in place so its x extent is `lengthM` metres (STL files carry no unit). */
function scaleToMetres(geometry, lengthM) {
  geometry.computeBoundingBox();
  const extent = geometry.boundingBox.max.x - geometry.boundingBox.min.x;
  if (!(lengthM > 0) || !(extent > 0)) return;
  const factor = lengthM / extent;
  if (Math.abs(factor - 1) > 1e-6) geometry.scale(factor, factor, factor);
}

export function createModelView({ host, onPick = null }) {
  const empty = el('div', { class: 'pane-empty' });
  host.append(empty);

  let renderer;
  try {
    // The stencil buffer draws the cut faces of a section cut (cut3d.js).
    renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true });
  } catch {
    showEmpty('3D view not available', 'This computer did not allow a WebGL view.');
    return { setModel() {}, setSelected() {}, resetView() {}, refreshTheme() {}, showSections() {}, setFocusSections() {}, setReviewOverlays() {}, setHighlightBox() {}, setWholeVessel: () => Promise.reject(new Error('3D view not available')), setStructure: () => Promise.resolve(), highlightPart() {}, showsWholeVessel: false, hasTanks: false };
  }
  /** Pixel ratio cap: a 3x screen draws at 2x, which looks the same and costs 2.25 times less. */
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO));
  setUpRenderer(renderer);
  renderer.domElement.setAttribute('aria-hidden', 'true');
  host.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  // Two cameras share one place: perspective, and orthographic for true-scale profile, plan and
  // body plan views. `camera` is the one in use; the orbit controls drive it.
  const perspective = new THREE.PerspectiveCamera(35, 1, 0.05, 2000);
  const orthographic = new THREE.OrthographicCamera(-1, 1, 1, -1, -2000, 4000);
  perspective.up.set(0, 0, 1);
  orthographic.up.set(0, 0, 1);
  let camera = perspective;
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !prefersReducedMotion();
  controls.dampingFactor = 0.12;
  // Down to the horizon, so the profile and body plan views are level; never below the ground.
  controls.maxPolarAngle = Math.PI / 2;

  const lighting = createLighting({ renderer, scene });
  /** The section cut: one clipping plane on every model material, with solid cut faces. */
  const cut = createSectionCut({ scene });
  /** Paint of the hull: antifouling, boot top and topside by height (look3d.js). */
  const hullMaterial = createPaintMaterial();
  /** Clipping planes of the live growth's skin; the hull material has them and the cut plane. */
  let skinPlanes = [];
  function clipHull() {
    hullMaterial.clippingPlanes = [...skinPlanes, ...cut.planes];
  }
  clipHull();
  hullMaterial.clipShadows = true;
  /** Put the section cut on a model material (and on its shadow). */
  function clip(material) {
    material.clippingPlanes = cut.planes;
    material.clipShadows = true;
    return material;
  }
  /** Design waterline, baseline and frame numbering of the model shown (reference3d.js). */
  let reference = null;
  const content = new THREE.Group();
  /** The outline of a whole-vessel part picked on the Parts tab, or null. */
  let highlight = null;
  /** The whole-vessel model (GLB, one group per part) when shown instead of the hull, or null. */
  let wholeVessel = null;
  /** Meshes of the whole vessel: tanks (GLB extras kind "tank") and the other parts (the shell). */
  let tankMeshes = [];
  let shellMeshes = [];
  /** The tanks drawn as one batch (batch3d.js), or null. */
  let tankBatch = null;
  /** Steel structure (a second GLB, one mesh per member group), or null. */
  let structure = null;
  let steelMeshes = [];
  /** The part tinted in the selection blue, and the tank under the pointer (part ids). */
  let highlightedId = null;
  let hoveredTankId = null;
  /** Layer switches of the whole-vessel view (the legend panel holds them). */
  const layers = { tanks: true, names: false, structure: true };
  /** Overlays: tank name labels, and the legend with the layer switches. */
  const labelLayer = el('div', { class: 'model-labels', 'aria-hidden': 'true' });
  const legend = el('div', { class: 'model-legend', id: `legend-${Math.random().toString(36).slice(2, 8)}`, role: 'group', 'aria-label': 'Tanks and steel' });
  legend.hidden = true;
  host.append(labelLayer, legend);

  // ---- Tool bar and section cut. The cut panel opens under the tool bar.
  const toolbar = createToolbar();
  const cutPanel = createCutPanel({
    onChange: (state) => {
      cut.set(state);
      cutButton.setAttribute('aria-pressed', String(Boolean(state.axis)));
      requestRender();
    },
    onCutAtSelection: () => cutAtSelection(),
    onClose: () => toggleCutPanel(false),
  });
  const cutButton = toolButton({ text: 'Section', iconName: 'cut', label: 'Section cut', keyHint: 'C', pressed: false, onClick: () => toggleCutPanel() });
  cutButton.setAttribute('aria-expanded', 'false');
  cutButton.setAttribute('aria-controls', cutPanel.id);
  const viewButtons = {};
  for (const [name, view] of Object.entries(STANDARD_VIEWS)) {
    viewButtons[name] = toolButton({ iconName: view.icon, label: view.label, keyHint: view.key, pressed: name === 'iso', onClick: () => showView(name) });
  }
  const orthoButton = toolButton({ iconName: 'ortho', label: 'Orthographic camera', keyHint: 'P', pressed: false, onClick: () => setOrthographic(!camera.isOrthographicCamera) });
  const fitButton = toolButton({ iconName: 'fit', label: 'Fit the selection', keyHint: 'F', onClick: () => fitSelection() });
  toolbar.add('Views', ...Object.values(viewButtons), orthoButton, fitButton);
  /** Mark the standard view shown (null: the camera has moved off every one). */
  function markView(name) {
    for (const [key, button] of Object.entries(viewButtons)) button.setAttribute('aria-pressed', String(key === name));
  }
  toolbar.add('Section', cutButton);
  // The cut panel opens under the tool bar, however many rows the tool bar wraps to.
  host.append(el('div', { class: 'model-controls' }, toolbar.element, cutPanel.element));

  // ---- Engineering overlays and the switches for them.
  const overlays = createOverlays({ scene, host, clip });
  const overlaySwitches = {};
  function overlaySwitch(key, iconName, label, keyHint) {
    const button = toolButton({ iconName, label, keyHint, pressed: overlays.shown[key], onClick: () => setOverlay(key, !overlays.shown[key]) });
    overlaySwitches[key] = button;
    return button;
  }
  function setOverlay(key, on) {
    overlays.set({ [key]: on });
    overlaySwitches[key].setAttribute('aria-pressed', String(on));
    requestRender();
  }
  toolbar.add('Show',
    overlaySwitch('grid', 'grid', 'Reference grid', 'G'),
    overlaySwitch('waterline', 'waterline', 'Design waterline plane', 'W'),
    overlaySwitch('frames', 'frames', 'Frame numbers', null),
    overlaySwitch('edges', 'edges', 'Feature edges', 'E'));
  const OVERLAY_KEYS = { g: 'grid', w: 'waterline', e: 'edges' };
  /** The x of the selected part's middle (Parts tab), or null. */
  let selectionX = null;

  /** Open the section strip with a cut (a frame cut first), or close it and end the cut. */
  function toggleCutPanel(open = cutPanel.element.hidden) {
    cutPanel.element.hidden = !open;
    cutButton.setAttribute('aria-expanded', String(open));
    if (open && !cut.active) cutPanel.set({ axis: 'x' });
    if (!open && cut.active) cutPanel.set({ axis: null });
  }

  /** Slider ranges of the cut panel for a model box: x by frames, y and z by centimetres. */
  function updateCutRanges(box) {
    if (!box || box.isEmpty()) return;
    const spacing = reference?.frameSpacingM.value || 0.01;
    const zero = reference?.frameZeroX.value || 0;
    const firstFrame = nearestFrameX(box.min.x, spacing, zero);
    cutPanel.setRanges({
      x: [firstFrame, nearestFrameX(box.max.x, spacing, zero), spacing],
      y: [Number(box.min.y.toFixed(2)), Number(box.max.y.toFixed(2)), 0.01],
      z: [Number(box.min.z.toFixed(2)), Number(box.max.z.toFixed(2)), 0.01],
    }, reference);
    if (cut.active) cutPanel.set({});
  }

  /** The x a quick cut uses: the selected part's middle, else the selected section's station. */
  function selectedCutX() {
    if (selectionX !== null) return selectionX;
    const plane = selectedId ? planes.get(selectedId) : null;
    return plane ? plane.position.x : null;
  }

  function offerCutAtSelection() {
    const x = selectedCutX();
    if (x === null || !reference) {
      cutPanel.setSelection(null);
      return;
    }
    const frame = frameAt(x, reference.frameSpacingM.value, reference.frameZeroX.value);
    cutPanel.setSelection(frameLabel(Math.round(frame)));
  }

  /** Cut at the frame nearest the selection (a part, else a section station). */
  function cutAtSelection() {
    const x = selectedCutX();
    if (x === null || !reference) return;
    toggleCutPanel(true);
    cutPanel.set({ axis: 'x', value: nearestFrameX(x, reference.frameSpacingM.value, reference.frameZeroX.value) });
  }

  host.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || event.target.closest('input, select, textarea')) return;
    const overlayKey = OVERLAY_KEYS[event.key.toLowerCase()];
    const view = viewOfKey(event.key);
    if (view) {
      showView(view);
      event.preventDefault();
    } else if (event.key === 'p' || event.key === 'P') {
      setOrthographic(!camera.isOrthographicCamera);
      event.preventDefault();
    } else if (event.key === 'f' || event.key === 'F') {
      fitSelection();
      event.preventDefault();
    } else if (event.key === 'c' || event.key === 'C') {
      toggleCutPanel();
      event.preventDefault();
    } else if (overlayKey) {
      setOverlay(overlayKey, !overlays.shown[overlayKey]);
      event.preventDefault();
    } else if (event.key === 'Escape' && !cutPanel.element.hidden) {
      toggleCutPanel(false);
      event.preventDefault();
    }
  });
  scene.add(content);
  // Live section curves stay outside `content`, so a new STL does not remove them.
  const growth = createSectionGrowth({
    scene,
    hullMaterial,
    renderer,
    requestRender: () => requestRender(),
    colours: () => colours,
    setSkinClip: (planes) => {
      skinPlanes = planes || [];
      clipHull();
    },
    onFirstSections: (box) => {
      if (hull) return;
      // No hull yet: show the curves on their own and frame them.
      empty.hidden = true;
      renderer.domElement.hidden = false;
      frameBox = box;
      gridBox = box;
      setHullBox(box);
      buildGrid();
      resize();
      resetView();
    },
  });
  /** What the home view frames: the hull, else the live section curves. */
  let frameBox = null;

  let hull = null;
  /** True while the overlays are built; the box they are built for and the hull box in it. */
  let grid = null;
  let gridBox = null;
  let hullBoxShown = null;
  let planes = new Map();
  let guessBands = [];
  /** Review overlays (guessed ranges) show only for the run's current state, not mid-replay. */
  let reviewOverlays = true;
  let dims = null;
  let selectedId = null;
  let colours = themeColours();
  let frame = 0;
  /** True until the user moves the camera; a resize then re-fits the default view. */
  let cameraAtHome = true;
  /** The animated move to the home view. A new home view or a person's drag stops it. */
  const cameraMove = createAnimation();
  controls.addEventListener('start', () => {
    cameraMove.cancel();
    cameraAtHome = false;
    markView(null);
  });

  function showEmpty(title, text) {
    empty.replaceChildren(icon('cube'), el('strong', {}, title), el('p', {}, text));
    empty.hidden = false;
  }

  /** Render one frame and move the tank labels with it. */
  function draw() {
    renderer.render(scene, camera);
    updateLabels();
    overlays.update(camera, renderer.domElement.clientWidth, renderer.domElement.clientHeight, metresPerPixel());
  }

  /** Metres per CSS pixel at the orbit target (the scale bar's length). */
  function metresPerPixel() {
    const height = renderer.domElement.clientHeight;
    if (!height) return 0;
    if (camera.isOrthographicCamera) return (camera.top - camera.bottom) / camera.zoom / height;
    const distance = camera.position.distanceTo(controls.target);
    return 2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / height;
  }

  /** Draw the next frame for a camera move (the shadows stay as they are). */
  function requestFrame() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      // Damping keeps moving after the pointer stops; update() reports when it is still moving.
      if (controls.update()) requestFrame();
      draw();
    });
  }

  /** Draw the next frame after a scene change: the shadows are drawn again too. */
  function requestRender() {
    lighting.markShadows();
    requestFrame();
  }
  controls.addEventListener('change', requestFrame);

  // ---- Picking: a click (not a drag) on a section plane picks that section. A pointer over
  // a plane shows the hand cursor. A drag still rotates the view.
  const raycaster = new THREE.Raycaster();
  let pressedAt = null;

  /** The id of the section plane under the pointer, nearest first, or null. */
  function planeAt(event) {
    if (!planes.size) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const faces = [...planes].map(([id, group]) => {
      group.children[0].userData.sectionId = id;
      return group.children[0];
    });
    const hit = raycaster.intersectObjects(faces, false).find((h) => cut.keeps(h.point));
    return hit ? hit.object.userData.sectionId : null;
  }
  renderer.domElement.addEventListener('pointerdown', (event) => { pressedAt = [event.clientX, event.clientY]; });
  renderer.domElement.addEventListener('pointerup', (event) => {
    const moved = pressedAt ? Math.hypot(event.clientX - pressedAt[0], event.clientY - pressedAt[1]) : Infinity;
    pressedAt = null;
    if (moved > CLICK_SLOP_PX || !onPick) return;
    const id = planeAt(event);
    if (id) onPick(id);
  });
  renderer.domElement.addEventListener('pointermove', (event) => {
    if (event.buttons) return;
    const tank = tankAt(event);
    if (tank !== hoveredTankId) {
      hoveredTankId = tank;
      requestFrame();
    }
    if (onPick) renderer.domElement.style.cursor = planeAt(event) ? 'pointer' : '';
  });
  // ---- Pointer readout: x, y, z and the frame of the model point under the pointer, once a frame.
  let readoutEvent = null;
  renderer.domElement.addEventListener('pointermove', (event) => {
    if (event.buttons) return;
    if (!readoutEvent) requestAnimationFrame(updateReadout);
    readoutEvent = event;
  });
  function updateReadout() {
    const event = readoutEvent;
    readoutEvent = null;
    if (!event) return;
    const targets = pickTargets();
    if (!targets.length) {
      overlays.setReadout(null);
      return;
    }
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1), camera);
    const hit = raycaster.intersectObjects(targets, false).find((h) => cut.keeps(h.point));
    if (!hit) {
      overlays.setReadout(null);
      return;
    }
    const name = hit.object.userData.label || hit.object.userData.group_label || hit.object.userData.partId;
    overlays.setReadout(`${pointReadout(hit.point.toArray(), reference)}${name ? ` · ${name}` : ''}`);
  }
  /** The model meshes the readout can point at: what shows now. */
  function pickTargets() {
    if (wholeVessel) {
      const meshes = [...shellMeshes];
      if (layers.tanks) meshes.push(...tankMeshes);
      if (layers.structure) meshes.push(...steelMeshes);
      return meshes;
    }
    return hull && hull.visible && hullMaterial.visible ? [hull] : [];
  }
  renderer.domElement.addEventListener('pointerleave', () => {
    readoutEvent = null;
    overlays.setReadout(null);
  });
  renderer.domElement.addEventListener('pointerleave', () => {
    if (!hoveredTankId) return;
    hoveredTankId = null;
    requestFrame();
  });

  /** The part id of the shown tank under the pointer, or null. */
  function tankAt(event) {
    if (!wholeVessel || !layers.tanks || !tankMeshes.length) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(tankMeshes, false).find((h) => cut.keeps(h.point));
    return hit ? hit.object.userData.partId : null;
  }

  // ---- Whole-vessel tanks: colours by content, translucent shell, labels and legend.

  /** Colour the whole vessel: tanks by content (capacity-plan tokens), the shell translucent
   * while tanks show, the highlighted part in the selection blue. */
  function styleWholeVessel() {
    // The shell turns translucent while tanks or steel inside it show.
    const seeInside = shellSeeThrough();
    for (const mesh of shellMeshes) {
      const material = mesh.material;
      paintHull(material);
      // A selected part keeps its paint and glows in the selection blue.
      material.emissive = mesh.userData.partId === highlightedId ? colours.accent.clone().multiplyScalar(0.45) : new THREE.Color(0x000000);
      if (material.transparent !== seeInside) material.needsUpdate = true;
      material.transparent = seeInside;
      material.opacity = seeInside ? SHELL_OPACITY_WITH_TANKS : 1;
      material.depthWrite = !seeInside;
      // A see-through shell casts no shadow, or the tanks and steel inside it would be dark.
      mesh.castShadow = !seeInside;
      mesh.receiveShadow = !seeInside;
    }
    for (const mesh of tankMeshes) {
      mesh.visible = layers.tanks;
      const colour = colours.tank(mesh.userData.content_class);
      // A selected tank keeps a share of its content colour and turns toward the selection blue.
      if (mesh.userData.partId === highlightedId) colour.lerp(colours.accent, 0.45);
      tankBatch.setColour(mesh, colour);
    }
    if (tankBatch) tankBatch.mesh.visible = layers.tanks;
    overlays.setEdgesLayer('tanks', layers.tanks);
    overlays.recolourEdges('tanks');
    overlays.setEdgesLayer('steel', layers.structure);
    for (const mesh of steelMeshes) {
      mesh.visible = layers.structure;
      mesh.material.color = colours.steel(mesh.userData.group);
      const shell = mesh.userData.group === 'shell';
      mesh.material.transparent = shell;
      mesh.material.opacity = shell ? STEEL_SHELL_OPACITY : 1;
      mesh.material.depthWrite = !shell;
    }
    cut.refresh();
    renderLegend();
  }

  /** True while the whole-vessel shell is see-through (tanks or steel show inside it). */
  function shellSeeThrough() {
    return (layers.tanks && tankMeshes.length > 0) || (layers.structure && steelMeshes.length > 0);
  }

  /** Which colour keys of the legend are open (the legend starts as one row of chips). */
  const legendOpen = { tanks: false, structure: false };
  const LEGEND_NOTE = 'Tanks by content (capacity plan), steel by member group. Draft, not for construction.';

  /**
   * The legend: one row of chips (Tanks, Steel: show or hide the layer; ▾ opens its colour key;
   * Names), hidden without tanks or steel. The colour keys and the note show only when opened.
   */
  function renderLegend() {
    legend.hidden = !wholeVessel || (!tankMeshes.length && !steelMeshes.length);
    if (legend.hidden) return;
    // A chip press redraws the legend; the focus stays on the same control.
    const focusKey = legend.contains(document.activeElement) ? document.activeElement.dataset.legendKey : null;
    const listId = (key) => `${legend.id}-${key}`;
    const chip = (key, text, keyLabel) => el('span', { class: 'model-chip' },
      el('button', {
        type: 'button', class: 'model-chip-toggle', dataset: { legendKey: `${key}-toggle` },
        'aria-pressed': String(layers[key]), title: `Show or hide the ${keyLabel}`, onclick: () => setLayer(key, !layers[key]),
      }, text),
      key in legendOpen ? el('button', {
        type: 'button', class: 'model-chip-open', dataset: { legendKey: `${key}-open` },
        'aria-expanded': String(legendOpen[key]), 'aria-controls': listId(key), 'aria-label': `Colour key of the ${keyLabel}`, title: `Colour key of the ${keyLabel}`,
        onclick: () => { legendOpen[key] = !legendOpen[key]; renderLegend(); },
      }, icon('chevron')) : null);
    const list = (key, rows) => el('ul', { class: 'model-legend-rows', id: listId(key) }, ...rows.map((row) => el('li', {},
      el('span', { class: 'model-swatch', style: { background: `var(${row.token})` } }),
      el('span', {}, row.label), el('span', { class: 'model-legend-count' }, String(row.count)))));
    const steelRows = steelLegend(steelMeshes.map((mesh) => mesh.userData));
    const steelCount = steelRows.reduce((sum, row) => sum + row.count, 0);
    const tanksOpen = tankMeshes.length && legendOpen.tanks;
    const steelOpen = steelMeshes.length && legendOpen.structure;
    fillNode(legend,
      el('div', { class: 'model-legend-head' },
        tankMeshes.length ? chip('tanks', `Tanks ${tankMeshes.length}`, 'tanks') : null,
        steelMeshes.length ? chip('structure', `Steel ${steelCount}`, 'steel members') : null,
        tankMeshes.length ? chip('names', 'Names', 'tank names') : null),
      tanksOpen ? list('tanks', tankLegend(tankMeshes.map((mesh) => mesh.userData))) : null,
      steelOpen ? list('structure', steelRows) : null,
      tanksOpen || steelOpen ? el('p', { class: 'model-legend-note' }, LEGEND_NOTE) : null);
    legend.title = LEGEND_NOTE;
    if (focusKey) legend.querySelector(`[data-legend-key="${focusKey}"]`)?.focus();
  }


  function setLayer(key, on) {
    layers[key] = on;
    if (key === 'tanks' && !on) hoveredTankId = null;
    styleWholeVessel();
    requestRender();
  }

  /** Tank name labels: the hovered and the selected tank, or every tank with Names on (labels
   * that would overlap are left out; the hovered one wins). */
  function updateLabels() {
    if (!wholeVessel || !layers.tanks || !tankMeshes.length) {
      if (labelLayer.childElementCount) labelLayer.replaceChildren();
      return;
    }
    const width = renderer.domElement.clientWidth;
    const height = renderer.domElement.clientHeight;
    const candidates = [];
    for (const mesh of tankMeshes) {
      const id = mesh.userData.partId;
      const priority = id === hoveredTankId ? 2 : id === highlightedId ? 1 : 0;
      if (!layers.names && !priority) continue;
      const point = mesh.userData.labelAnchor.clone().project(camera);
      if (point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1) continue;
      // The GLB extras "label" (GLTFLoader keeps userData.name for the node name).
      const name = mesh.userData.label || id;
      candidates.push({
        id, name, priority, contentClass: mesh.userData.content_class,
        x: (point.x + 1) / 2 * width, y: (1 - point.y) / 2 * height,
        width: Math.min(LABEL_BOX.maxWidth, name.length * LABEL_BOX.charWidth + LABEL_BOX.padding), height: LABEL_BOX.height,
      });
    }
    const shown = placeLabels(candidates);
    labelLayer.replaceChildren(...candidates.filter((c) => shown.has(c.id)).map((c) => el('span', {
      class: `model-label${c.priority ? ' is-strong' : ''}`,
      style: { left: `${c.x.toFixed(1)}px`, top: `${c.y.toFixed(1)}px` },
    }, el('span', { class: 'model-swatch', style: { background: `var(${tankToken(c.contentClass)})` } }), c.name)));
  }

  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height);
    perspective.aspect = width / height;
    perspective.updateProjectionMatrix();
    setOrthoHeight(orthographic.top);
    if (cameraAtHome) fitView({ direction: viewDirection });
    requestRender();
  }
  new ResizeObserver(resize).observe(host);

  /** Paint a hull material: topside in the theme's hull colour, the boot top at the design waterline. */
  function paintHull(material) {
    const band = reference ? bootTopBand(reference.designWaterlineZ.value, reference.depth) : [-1e6, -1e6];
    stylePaint(material, { band, antifouling: colours.antifouling, bootTop: colours.bootTop, topside: colours.hull });
  }

  /**
   * The model's hull box sets the design waterline (paint) and the frame numbering; the box of
   * everything shown sets the lights and the ground shadow. Both are THREE.Box3 in metres.
   */
  function setHullBox(hullBox, sceneBox = hullBox) {
    reference = hullBox ? hullReference({ min: hullBox.min.toArray(), max: hullBox.max.toArray() }) : null;
    hullBoxShown = hullBox;
    gridBox = sceneBox;
    buildGrid();
    lighting.fit(sceneBox);
    cut.fit(sceneBox);
    updateCutRanges(sceneBox);
    paintHull(hullMaterial);
    for (const mesh of shellMeshes) paintHull(mesh.material);
  }

  function applyColours() {
    scene.background = colours.background;
    lighting.setTheme(colours.background.getHSL({}).l < 0.5);
    paintHull(hullMaterial);
    for (const [id, plane] of planes) styleSectionPlane(plane, id === selectedId);
    for (const band of guessBands) styleGuessBand(band);
    overlays.setColours({ grid: colours.grid, gridMinor: colours.gridMinor, water: colours.water, edge: colours.edge, dark: colours.background.getHSL({}).l < 0.5 });
    growth.refreshColours();
    if (wholeVessel) styleWholeVessel();
    cut.refresh();
    requestRender();
  }

  function styleSectionPlane(plane, selected) {
    const [face, edge] = plane.children;
    const colour = selected ? colours.accent : colours.plane;
    face.material.color = colour;
    face.material.opacity = selected ? 0.16 : 0.06;
    edge.material.color = colour;
    edge.material.opacity = selected ? 1 : 0.55;
  }

  function styleGuessBand(band) {
    const [face, edge] = band.children;
    // Faint: a draft can have a guess at every station, and strong boxes then hide the hull.
    face.material.color = colours.guess;
    face.material.opacity = 0.06;
    edge.material.color = colours.guess;
    edge.material.opacity = 0.22;
  }

  /** A translucent amber box over a guessed x range, so gaps and guesses show on the hull. */
  function buildGuessBand([x0, x1], box) {
    const size = box.getSize(new THREE.Vector3());
    const geometry = new THREE.BoxGeometry(
      Math.max(x1 - x0, 0.02),
      size.y * (1 + 2 * GUESS_BAND_MARGIN),
      size.z * (1 + 2 * GUESS_BAND_MARGIN),
    );
    const face = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }));
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ transparent: true }));
    const group = new THREE.Group();
    group.add(face, edge);
    const centre = box.getCenter(new THREE.Vector3());
    group.position.set((x0 + x1) / 2, centre.y, centre.z);
    return group;
  }

  function clearModel() {
    content.clear();
    for (const band of guessBands) {
      for (const child of band.children) {
        child.geometry.dispose();
        child.material.dispose();
      }
    }
    guessBands = [];
    if (hull) {
      cut.removeSolids(hull);
      overlays.removeEdges('hull');
      hull.geometry.dispose();
    }
    for (const plane of planes.values()) {
      for (const child of plane.children) {
        child.geometry.dispose();
        child.material.dispose();
      }
    }
    disposeGrid();
    hull = null;
    grid = null;
    planes = new Map();
  }

  function disposeGrid() {
    overlays.hide();
    grid = null;
  }

  /** The engineering overlays for the box shown (overlay3d.js), in the current theme colours. */
  function buildGrid() {
    if (!gridBox) return;
    overlays.build(gridBox, reference, hullBoxShown || gridBox);
    grid = true;
  }

  function buildSectionPlane(xMid, box) {
    const size = box.getSize(new THREE.Vector3());
    const width = size.y * (1 + 2 * PLANE_MARGIN);
    const height = size.z * (1 + 2 * PLANE_MARGIN);
    const geometry = new THREE.PlaneGeometry(width, height);
    // PlaneGeometry lies in XY; turn it to face along x.
    geometry.rotateY(Math.PI / 2);
    const face = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }));
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ transparent: true }));
    const group = new THREE.Group();
    group.add(face, edge);
    const centre = box.getCenter(new THREE.Vector3());
    group.position.set(xMid, centre.y, centre.z);
    return group;
  }

  /** What the views frame: the whole vessel, else the hull, else the live section curves. */
  function modelBox() {
    if (!hull && !frameBox && !wholeVessel) return null;
    // Frame the hull and the section planes around it, which reach past the hull
    // across and up; the hull alone would leave them against the pane edge.
    const box = wholeVessel ? new THREE.Box3().setFromObject(wholeVessel) : hull ? new THREE.Box3().setFromObject(hull) : frameBox.clone();
    const hullSize = box.getSize(new THREE.Vector3());
    box.expandByVector(new THREE.Vector3(0, hullSize.y * PLANE_MARGIN, hullSize.z * PLANE_MARGIN));
    return box;
  }

  /** The orthographic camera's half height (metres at zoom 1) and its width from the pane. */
  function setOrthoHeight(halfHeight) {
    const aspect = perspective.aspect || 1;
    orthographic.top = halfHeight;
    orthographic.bottom = -halfHeight;
    orthographic.left = -halfHeight * aspect;
    orthographic.right = halfHeight * aspect;
    orthographic.updateProjectionMatrix();
  }

  const halfFov = () => THREE.MathUtils.degToRad(perspective.fov / 2);

  /** The perspective distance that shows what the camera in use shows at the target. */
  function viewDistance() {
    if (camera.isOrthographicCamera) return orthographic.top / orthographic.zoom / Math.tan(halfFov());
    return camera.position.distanceTo(controls.target);
  }

  /**
   * Put both cameras at `distance` from `target` along `direction`. The orthographic one shows
   * `orthoHalfHeight` metres above and below the target (by default what the perspective shows there).
   */
  function placeCameras(target, direction, distance, orthoHalfHeight = distance * Math.tan(halfFov())) {
    controls.target.copy(target);
    perspective.position.copy(target).addScaledVector(direction, distance);
    orthographic.position.copy(perspective.position);
    orthographic.zoom = 1;
    setOrthoHeight(orthoHalfHeight);
    controls.update();
  }

  /**
   * Camera distance that fits a box seen from `direction` (zoom to extents): the box corners are
   * measured across and up the screen, so a profile or a plan fills the pane, not a sphere.
   */
  function boxFitDistance(box, direction) {
    const centre = box.getCenter(new THREE.Vector3());
    const worldUp = Math.abs(direction.z) > 0.99 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, 1);
    const up = worldUp.clone().addScaledVector(direction, -worldUp.dot(direction)).normalize();
    const right = new THREE.Vector3().crossVectors(up, direction).normalize();
    let halfWidth = 0;
    let halfHeight = 0;
    let halfDepth = 0;
    const corner = new THREE.Vector3();
    for (let i = 0; i < 8; i += 1) {
      corner.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(centre);
      halfWidth = Math.max(halfWidth, Math.abs(corner.dot(right)));
      halfHeight = Math.max(halfHeight, Math.abs(corner.dot(up)));
      halfDepth = Math.max(halfDepth, Math.abs(corner.dot(direction)));
    }
    // The radius that fits both screen extents, as fitDistance takes it (a sphere seen edge on).
    const aspect = perspective.aspect || 1;
    const tanHalf = Math.tan(halfFov());
    const fit = Math.max(halfHeight, halfWidth / aspect) / tanHalf * FRAME_MARGIN;
    // Perspective stands back by the box depth too; orthographic shows exactly the screen extent.
    return { distance: Math.max(fit + halfDepth, fitDistance(1e-3, perspective.fov, aspect)), orthoHalfHeight: fit * tanHalf };
  }

  /** The direction the camera looks from now (target to camera, unit length). */
  function currentDirection() {
    return camera.position.clone().sub(controls.target).normalize();
  }

  /**
   * Turn and move the camera to look from `direction` at `box` (THREE.Box3; the model by
   * default), fitted to the pane. Animated unless the person prefers reduced motion. The turn
   * goes the short way round the sphere; a half turn goes round the vertical.
   */
  function fitView({ direction, box = modelBox(), animate = false }) {
    // An older animated move would aim at the old target and overwrite this view.
    cameraMove.cancel();
    if (!box || box.isEmpty()) return;
    const toDirection = direction.clone().normalize();
    const centre = box.getCenter(new THREE.Vector3());
    const { distance, orthoHalfHeight } = boxFitDistance(box, toDirection);
    if (!animate || prefersReducedMotion()) {
      placeCameras(centre, toDirection, distance, orthoHalfHeight);
      requestFrame();
      return;
    }
    const fromTarget = controls.target.clone();
    const fromDirection = currentDirection();
    const fromDistance = viewDistance();
    const fromHalfHeight = camera.isOrthographicCamera ? orthographic.top / orthographic.zoom : fromDistance * Math.tan(halfFov());
    const turn = fromDirection.dot(toDirection) < -0.999
      ? new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI)
      : new THREE.Quaternion().setFromUnitVectors(fromDirection, toDirection);
    const step = new THREE.Quaternion();
    const target = new THREE.Vector3();
    const began = performance.now();
    cameraMove.start((now) => {
      const t = Math.min(1, (now - began) / HOME_MOVE_MS);
      const eased = 1 - (1 - t) ** 4;
      step.identity().slerp(turn, eased);
      target.lerpVectors(fromTarget, centre, eased);
      const along = t < 1 ? fromDirection.clone().applyQuaternion(step) : toDirection;
      placeCameras(target, along, fromDistance + (distance - fromDistance) * eased,
        fromHalfHeight + (orthoHalfHeight - fromHalfHeight) * eased);
      draw();
      return t < 1;
    });
  }

  /** The direction of the last standard view; a resize re-fits it while the camera stays there. */
  let viewDirection = HOME_DIRECTION.clone();

  function resetView({ animate = false } = {}) {
    showView('iso', { animate });
  }

  /** Show a standard view (reference3d.js STANDARD_VIEWS) of the whole model. */
  function showView(name, { animate = true } = {}) {
    if (!modelBox()) return;
    viewDirection = new THREE.Vector3(...STANDARD_VIEWS[name].direction).normalize();
    cameraAtHome = true;
    fitView({ direction: viewDirection, animate });
    markView(name);
  }

  /** Switch between the perspective and the orthographic camera, keeping the view. */
  function setOrthographic(on) {
    if (on === camera.isOrthographicCamera) return;
    const target = controls.target.clone();
    const direction = currentDirection();
    const distance = viewDistance();
    camera = on ? orthographic : perspective;
    controls.object = camera;
    placeCameras(target, direction, distance);
    orthoButton.setAttribute('aria-pressed', String(on));
    requestRender();
  }

  /** Frame the selection (the outlined part, else the tinted part) from the current direction. */
  function fitSelection() {
    let box = null;
    if (highlight) box = new THREE.Box3().setFromObject(highlight);
    else if (highlightedId && wholeVessel) {
      box = new THREE.Box3();
      for (const mesh of [...shellMeshes, ...tankMeshes]) if (mesh.userData.partId === highlightedId) box.expandByObject(mesh);
    }
    if (!box || box.isEmpty()) box = modelBox();
    if (!box) return;
    cameraAtHome = false;
    markView(null);
    fitView({ direction: currentDirection(), box, animate: true });
  }


  return {
    /**
     * Show a model. `buffer` is the STL as an ArrayBuffer, or null for the empty state.
     * `stations` is [{ id, x_m }]. The camera is kept when `keepCamera` is true.
     * `lengthM` is the model length in metres. The CAD export writes STL in millimetres,
     * so the mesh is scaled to make its x extent equal `lengthM`.
     * `guessedRanges` is [[x0_m, x1_m]], the x ranges a draft guessed; each is shaded amber.
     */
    setModel(buffer, stations, { keepCamera = false, lengthM = null, guessedRanges = [], emptyTitle, emptyText } = {}) {
      // A move toward the previous model must not finish over this one.
      if (!keepCamera) cameraMove.cancel();
      clearModel();
      if (!buffer) {
        frameBox = growth.bounds();
        if (frameBox) {
          // Live section curves are on screen: keep them, on their grid.
          setHullBox(frameBox);
          requestRender();
          return;
        }
        showEmpty(emptyTitle || 'No 3D model yet', emptyText || 'The model appears here after the run builds it.');
        renderer.domElement.hidden = true;
        return;
      }
      empty.hidden = true;
      renderer.domElement.hidden = false;
      const geometry = new STLLoader().parse(buffer);
      scaleToMetres(geometry, lengthM);
      geometry.computeVertexNormals();
      hull = new THREE.Mesh(geometry, hullMaterial);
      hull.castShadow = true;
      hull.receiveShadow = true;
      content.add(hull);
      cut.addSolid(hull, { colour: () => colours.hull });

      const box = new THREE.Box3().setFromObject(hull);
      const size = box.getSize(new THREE.Vector3());
      dims = size;
      overlays.setEdges('hull', [hull]);
      overlays.setEdgesLayer('hull', !wholeVessel);
      // With the whole vessel shown, the overlays stay on the whole vessel.
      if (!wholeVessel) setHullBox(box);
      else buildGrid();

      for (const station of stations) {
        const plane = buildSectionPlane(station.x_m, box);
        planes.set(station.id, plane);
        content.add(plane);
      }
      for (const range of guessedRanges) {
        const band = buildGuessBand(range, box);
        band.visible = reviewOverlays;
        guessBands.push(band);
        content.add(band);
      }
      applyColours();
      resize();
      if (!keepCamera) resetView();
    },
    /**
     * Outline one whole-vessel part (APP_SPEC "Whole-vessel parts") as a box in the selection
     * blue; null removes it. `bbox` is { min: [x, y, z], max: [x, y, z] } in metres.
     */
    /**
     * Show the whole-vessel model (a GLB with one node per part, named by the part id) in place
     * of the hull, or go back to the hull with null. The GLB from the CAD worker is Y-up in
     * millimetres (glTF convention); the app's frame is Z-up in metres, so it is turned back
     * and scaled. Resolves when it shows; rejects when the file cannot be read.
     */
    setWholeVessel(buffer) {
      const showedWholeVessel = Boolean(wholeVessel);
      if (wholeVessel) {
        cut.removeSolids(wholeVessel);
        for (const key of ['tanks', 'shell', 'steel']) overlays.removeEdges(key);
        if (tankBatch) {
          scene.remove(tankBatch.mesh);
          tankBatch.dispose();
          tankBatch = null;
        }
        scene.remove(wholeVessel);
        wholeVessel.traverse((o) => {
          if (o.isMesh || o.isLineSegments) {
            o.geometry.dispose();
            if (o.material !== HIDDEN_MATERIAL) o.material.dispose();
          }
        });
        wholeVessel = null;
        structure = null;
        tankMeshes = [];
        shellMeshes = [];
        steelMeshes = [];
        hoveredTankId = null;
        renderLegend();
        updateLabels();
      }
      if (hull) hull.visible = true;
      overlays.setEdgesLayer('hull', true);
      if (!buffer) {
        // Back to the hull: move to its home view. With no whole vessel shown, the view
        // is already the hull's (and a run that is closing must not start a move).
        if (hull) setHullBox(new THREE.Box3().setFromObject(hull));
        if (showedWholeVessel) resetView({ animate: true });
        requestRender();
        return Promise.resolve();
      }
      return new Promise((resolve, reject) => {
        new GLTFLoader().parse(buffer, '', (gltf) => {
          const group = new THREE.Group();
          group.add(gltf.scene);
          group.rotation.x = Math.PI / 2; // glTF Y-up -> the app's Z-up
          group.scale.setScalar(MM_TO_M);
          // Each top node is one part; its meshes carry the part id for highlighting.
          const root = gltf.scene.children.length === 1 && !gltf.scene.children[0].isMesh ? gltf.scene.children[0] : gltf.scene;
          const parts = [];
          for (const node of root.children) node.traverse((o) => { if (o.isMesh) parts.push([node, o]); });
          for (const [node, o] of parts) {
            o.userData.partId = node.name;
            // Tanks carry their name and content class as GLB extras (display_mesh.tank_style).
            if (o.userData.kind === 'tank') {
              // The tank batch draws the tanks; each tank mesh stays for picking and its cut face.
              o.material = HIDDEN_MATERIAL;
              tankMeshes.push(o);
            } else {
              o.material = clip(createPaintMaterial());
              o.castShadow = true;
              o.receiveShadow = true;
              shellMeshes.push(o);
            }
          }
          scene.add(group);
          wholeVessel = group;
          group.updateMatrixWorld(true);
          if (tankMeshes.length) {
            tankBatch = createBatch(tankMeshes, clip(createTankMaterial()));
            tankBatch.mesh.castShadow = true;
            tankBatch.mesh.receiveShadow = true;
            scene.add(tankBatch.mesh);
          }
          for (const mesh of tankMeshes) cut.addSolid(mesh, { colour: () => colours.tank(mesh.userData.content_class) });
          // A see-through shell shows no cut face, or the face would hide what is inside.
          for (const mesh of shellMeshes) cut.addSolid(mesh, { colour: () => colours.hull, capped: () => !shellSeeThrough() });
          overlays.setEdges('shell', shellMeshes);
          overlays.setEdges('tanks', tankMeshes, {
            colourOf: (mesh) => colours.tank(mesh.userData.content_class).multiplyScalar(TANK_EDGE_SHADE),
            always: true,
          });
          overlays.setEdgesLayer('hull', false);
          // Tank labels sit on the middle of the tank top (world coordinates, metres).
          // The paint and the frame numbers follow the hull part (else every part that is not a tank).
          const hullParts = shellMeshes.filter((mesh) => /(^|_)hull($|_)/.test(mesh.userData.partId || ''));
          const hullBox = new THREE.Box3();
          for (const mesh of hullParts.length ? hullParts : shellMeshes) hullBox.expandByObject(mesh);
          setHullBox(hullBox.isEmpty() ? null : hullBox, new THREE.Box3().setFromObject(group));
          for (const mesh of tankMeshes) {
            const box = new THREE.Box3().setFromObject(mesh);
            mesh.userData.labelAnchor = new THREE.Vector3((box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, box.max.z);
          }
          styleWholeVessel();
          if (hull) hull.visible = false;
          empty.hidden = true;
          renderer.domElement.hidden = false;
          resize();
          resetView();
          requestRender();
          resolve();
        }, reject);
      });
    },
    /** Tint one part of the whole-vessel model in the selection blue (null: none). */
    highlightPart(id) {
      highlightedId = id;
      if (!wholeVessel) return;
      styleWholeVessel();
      requestRender();
    },
    get showsWholeVessel() {
      return Boolean(wholeVessel);
    },
    /**
     * Add the run's steel structure (a GLB from structure/display.py: one mesh per member group,
     * extras kind "structure") to the whole vessel shown, or remove it with null. Same axes and
     * units as the whole vessel. Resolves when it shows.
     */
    setStructure(buffer) {
      if (structure) {
        cut.removeSolids(structure);
        overlays.removeEdges('steel');
        structure.parent?.remove(structure);
        structure.traverse((o) => {
          if (o.isMesh) {
            o.geometry.dispose();
            o.material.dispose();
          }
        });
        structure = null;
        steelMeshes = [];
      }
      if (!buffer || !wholeVessel) {
        if (wholeVessel) styleWholeVessel();
        requestRender();
        return Promise.resolve();
      }
      return new Promise((resolve, reject) => {
        new GLTFLoader().parse(buffer, '', (gltf) => {
          if (!wholeVessel) {
            resolve();
            return;
          }
          const members = [];
          gltf.scene.traverse((o) => { if (o.isMesh && o.userData.kind === 'structure') members.push(o); });
          members.forEach((o) => {
            o.material = clip(createSteelMaterial());
            o.castShadow = true;
            o.receiveShadow = true;
            steelMeshes.push(o);
          });
          structure = gltf.scene;
          // The whole-vessel group turns glTF Y-up into the app's Z-up and scales mm to m.
          wholeVessel.add(structure);
          wholeVessel.updateMatrixWorld(true);
          // See-through shell plating shows no cut face; the other members are solid plate.
          for (const o of members) cut.addSolid(o, { colour: () => colours.steel(o.userData.group), capped: () => o.userData.group !== 'shell' });
          overlays.setEdges('steel', members);
          lighting.fit(new THREE.Box3().setFromObject(wholeVessel));
          styleWholeVessel();
          requestRender();
          resolve();
        }, reject);
      });
    },
    /** True when the whole vessel shown has tanks (its legend shows). */
    get hasTanks() {
      return Boolean(wholeVessel) && tankMeshes.length > 0;
    },
    setHighlightBox(bbox) {
      selectionX = bbox ? (bbox.min[0] + bbox.max[0]) / 2 : null;
      offerCutAtSelection();
      if (highlight) {
        content.remove(highlight);
        highlight.geometry.dispose();
        highlight = null;
      }
      if (bbox) {
        const size = bbox.max.map((v, i) => Math.max(v - bbox.min[i], 0.02));
        const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(...size));
        highlight = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: colours.accent }));
        highlight.position.set(...bbox.min.map((v, i) => v + size[i] / 2));
        content.add(highlight);
      }
      requestRender();
    },
    setSelected(id) {
      selectedId = id;
      offerCutAtSelection();
      for (const [planeId, plane] of planes) styleSectionPlane(plane, planeId === id);
      requestRender();
    },
    resetView: () => resetView({ animate: true }),
    /**
     * HOOK(M3 live): section curves of a build, coloured and patterned by source label.
     * `mode`: "grow" (slide in station by station, then the skin fades in between them),
     * "update" (changed sections morph and flash) or "instant". Null clears them.
     */
    showSections: (sections, options) => growth.show(sections, options),
    /** HOOK(M3 live): show or hide the review overlays (guessed ranges) during a replay. */
    setReviewOverlays(visible) {
      reviewOverlays = visible;
      for (const band of guessBands) band.visible = visible;
      requestRender();
    },
    /** HOOK(M3 live): the section ids the agent works on now (drawn brighter). */
    setFocusSections: (ids) => growth.setFocus(ids),
    refreshTheme() {
      colours = themeColours();
      applyColours();
    },
    get dimensions() {
      return dims;
    },
  };
}
