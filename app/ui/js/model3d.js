// 3D view: the build's STL in an orbit view, with a ground grid and a thin plane at each
// section's x position. The hull frame is x along the length, y across, z up (metres).
// The scene renders only when something changes, so an idle window costs no GPU time.

import * as THREE from '../vendor/three/three.module.min.js';
import { OrbitControls } from '../vendor/three/OrbitControls.js';
import { STLLoader } from '../vendor/three/STLLoader.js';
import { el, icon, prefersReducedMotion } from './dom.js';
import { createSectionGrowth } from './growth3d.js';

/** Extra size of a section plane around the hull, as a fraction of beam and depth. */
const PLANE_MARGIN = 0.25;
/** Space kept around the hull in the home view, as a fraction of the fitted size (10%). */
const FRAME_MARGIN = 1.1;
/** Size of a guessed-range band around the hull, as a fraction of the hull's beam and depth. */
const GUESS_BAND_MARGIN = 0.04;
/** Camera direction for the default view: from forward, starboard and above. */
const HOME_DIRECTION = new THREE.Vector3(1.0, -1.25, 0.75).normalize();

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
    hull: read('--model-hull'),
    plane: read('--text-3'),
    accent: read('--accent'),
    guess: read('--guess-ink'),
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

export function createModelView({ host }) {
  const empty = el('div', { class: 'pane-empty' });
  host.append(empty);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch {
    showEmpty('3D view not available', 'This computer did not allow a WebGL view.');
    return { setModel() {}, setSelected() {}, resetView() {}, refreshTheme() {}, showSections() {}, setFocusSections() {}, setReviewOverlays() {} };
  }
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.domElement.setAttribute('aria-hidden', 'true');
  host.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 2000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !prefersReducedMotion();
  controls.dampingFactor = 0.12;
  // Keep the camera above the ground grid.
  controls.maxPolarAngle = Math.PI * 0.49;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(1, -1.4, 2);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-1.5, 1, 0.6);
  scene.add(key, fill);

  const hullMaterial = new THREE.MeshStandardMaterial({ roughness: 0.62, metalness: 0.0, side: THREE.DoubleSide });
  const content = new THREE.Group();
  scene.add(content);
  // Live section curves stay outside `content`, so a new STL does not remove them.
  const growth = createSectionGrowth({
    scene,
    hullMaterial,
    renderer,
    requestRender: () => requestRender(),
    colours: () => colours,
    onFirstSections: (box) => {
      if (hull) return;
      // No hull yet: show the curves on their own and frame them.
      empty.hidden = true;
      renderer.domElement.hidden = false;
      frameBox = box;
      gridBox = box;
      buildGrid();
      resize();
      resetView();
    },
  });
  /** What the home view frames: the hull, else the live section curves. */
  let frameBox = null;

  let hull = null;
  let grid = null;
  let gridBox = null;
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
  controls.addEventListener('start', () => { cameraAtHome = false; });

  function showEmpty(title, text) {
    empty.replaceChildren(icon('cube'), el('strong', {}, title), el('p', {}, text));
    empty.hidden = false;
  }

  function requestRender() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      // Damping keeps moving after the pointer stops; update() reports when it is still moving.
      if (controls.update()) requestRender();
      renderer.render(scene, camera);
    });
  }
  controls.addEventListener('change', requestRender);

  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (cameraAtHome) resetView();
    requestRender();
  }
  new ResizeObserver(resize).observe(host);

  function applyColours() {
    scene.background = colours.background;
    hullMaterial.color = colours.hull;
    for (const [id, plane] of planes) styleSectionPlane(plane, id === selectedId);
    for (const band of guessBands) styleGuessBand(band);
    if (grid) buildGrid();
    growth.refreshColours();
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
    if (hull) hull.geometry.dispose();
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
    if (!grid) return;
    content.remove(grid);
    grid.geometry.dispose();
    grid.material.dispose();
    grid = null;
  }

  /** Ground grid with 1 m cells under the hull, in the current theme colours. */
  function buildGrid() {
    disposeGrid();
    const size = gridBox.getSize(new THREE.Vector3());
    const centre = gridBox.getCenter(new THREE.Vector3());
    const span = Math.ceil(Math.max(size.x, size.y) * 1.6);
    grid = new THREE.GridHelper(span, span, colours.grid, colours.gridMinor);
    grid.rotation.x = Math.PI / 2; // GridHelper lies in XZ; the hull frame is z up.
    grid.position.set(centre.x, centre.y, gridBox.min.z - 0.001);
    grid.material.transparent = true;
    grid.material.opacity = 0.55;
    content.add(grid);
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

  function resetView({ animate = false } = {}) {
    if (!hull && !frameBox) return;
    cameraAtHome = true;
    // Frame the hull and the section planes around it, which reach past the hull
    // across and up; the hull alone would leave them against the pane edge.
    const box = hull ? new THREE.Box3().setFromObject(hull) : frameBox.clone();
    const hullSize = box.getSize(new THREE.Vector3());
    box.expandByVector(new THREE.Vector3(0, hullSize.y * PLANE_MARGIN, hullSize.z * PLANE_MARGIN));
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    // Fit the bounding sphere inside the narrower of the vertical and horizontal fields of view.
    const halfVertical = THREE.MathUtils.degToRad(camera.fov / 2);
    const halfHorizontal = Math.atan(Math.tan(halfVertical) * camera.aspect);
    const distance = sphere.radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * FRAME_MARGIN;
    const target = sphere.center.clone();
    const position = target.clone().addScaledVector(HOME_DIRECTION, distance);
    if (!animate || prefersReducedMotion()) {
      controls.target.copy(target);
      camera.position.copy(position);
      controls.update();
      requestRender();
      return;
    }
    const fromTarget = controls.target.clone();
    const fromPosition = camera.position.clone();
    const began = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - began) / 360);
      const eased = 1 - (1 - t) ** 4;
      controls.target.lerpVectors(fromTarget, target, eased);
      camera.position.lerpVectors(fromPosition, position, eased);
      controls.update();
      renderer.render(scene, camera);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
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
      clearModel();
      if (!buffer) {
        frameBox = growth.bounds();
        if (frameBox) {
          // Live section curves are on screen: keep them, on their grid.
          gridBox = frameBox;
          buildGrid();
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
      content.add(hull);

      const box = new THREE.Box3().setFromObject(hull);
      const size = box.getSize(new THREE.Vector3());
      dims = size;
      gridBox = box;
      buildGrid();

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
    setSelected(id) {
      selectedId = id;
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
