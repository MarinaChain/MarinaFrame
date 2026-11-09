// Live hull growth in the 3D view: the section curves of a build, each at its x, coloured and
// patterned by source label (the same rules as the drawing and the section strip), and the
// skin fading in between the stations that have arrived. Motion only explains a change:
// curves slide in when a first hull arrives, and morph and flash when a build changes them.

import * as THREE from '../vendor/three/three.module.min.js';
import { prefersReducedMotion } from './dom.js';

/** Skin opacity while section curves are shown, so the curves read in front of it. */
const SKIN_OPACITY = 0.85;
/** Delay between stations when a first hull grows, aft to fore. */
const STAGGER_MS = 80;
/** Slide-in of one station, and the morph of a changed one. */
const CURVE_MS = 400;
/** Skin fade after the last station arrives. */
const SKIN_FADE_MS = 500;
/** Flash of a section that a new build changed. */
const FLASH_MS = 900;
/** Distance a curve slides along x, as a fraction of the hull length (0.3 m on a 24 m hull). */
const SLIDE_FRACTION = 0.0125;
/** Size of pattern marks (ticks, diamonds) and dashes, as a fraction of the hull depth. */
const MARK_FRACTION = 0.035;
/** Opacity of the curves the agent is not working on while it works on others. */
const UNFOCUSED_OPACITY = 0.5;
/** Two curves are the same when no point moved more than this (metres). */
const SAME_POINT_M = 1e-4;

const easeOut = (t) => 1 - (1 - t) ** 3;

/** Tube radius of a section curve, as a fraction of the hull depth (WebGL lines are 1 px). */
const TUBE_FRACTION = 0.011;

/**
 * Stroke pattern per source label, in units of the mark size. Colour is never the only
 * signal: `dash` is [on, off] along the curve (null: solid), `dots` draws beads instead of a
 * line, `deco` adds ticks across the curve or diamonds on it.
 */
const PATTERNS = {
  traced: {},
  repaired: { deco: 'ticks' },
  interpolated: { dash: [3.2, 1.6] }, // long dash
  ai_inferred: { dots: 1.4 }, // dotted
  ai_corrected: { deco: 'diamonds' },
  omitted: { dash: [0.8, 2] },
};

function sameCurve(a, b) {
  if (a.length !== b.length) return false;
  return a.every((p, i) => Math.abs(p[0] - b[i][0]) < SAME_POINT_M && Math.abs(p[1] - b[i][1]) < SAME_POINT_M);
}

/** Both halves of a section as one line: starboard keel-to-deck reversed, then port. */
function fullSection(points) {
  const starboard = points.slice().reverse().map(([y, z]) => [-y, z]);
  const port = points[0][0] === 0 ? points.slice(1) : points;
  return starboard.concat(port);
}

/**
 * Split a polyline (THREE.Vector3[]) into pieces by arc length: [on, off] lengths repeat.
 * Returns the "on" pieces, each a polyline.
 */
function dashPieces(points, on, off) {
  const pieces = [];
  let piece = [points[0]];
  let drawing = true;
  let left = on;
  for (let i = 1; i < points.length; i += 1) {
    let from = points[i - 1];
    const to = points[i];
    let span = from.distanceTo(to);
    while (span > left) {
      const cut = from.clone().lerp(to, left / span);
      if (drawing) {
        piece.push(cut);
        pieces.push(piece);
      } else {
        piece = [cut];
      }
      span -= left;
      from = cut;
      drawing = !drawing;
      left = drawing ? on : off;
    }
    left -= span;
    if (drawing) piece.push(to);
  }
  if (drawing && piece.length > 1) pieces.push(piece);
  return pieces;
}

/** Points every `spacing` metres along a polyline. */
function beads(points, spacing) {
  return dashPieces(points, 1e-6, spacing).map((piece) => piece[0]);
}

/** A tube along a polyline. */
function tube(points, radius) {
  const path = new THREE.CurvePath();
  for (let i = 1; i < points.length; i += 1) path.add(new THREE.LineCurve3(points[i - 1], points[i]));
  return new THREE.TubeGeometry(path, Math.max(1, points.length - 1), radius, 6, false);
}

/**
 * `setSkinClip(planes)` sets the skin's clipping planes (null: none); the 3D view adds its section
 * cut to them. Without it the planes go on the hull material as they are.
 */
export function createSectionGrowth({ scene, hullMaterial, renderer, requestRender, colours, onFirstSections,
  setSkinClip = (planes) => { hullMaterial.clippingPlanes = planes; } }) {
  const group = new THREE.Group();
  group.renderOrder = 10;
  scene.add(group);
  renderer.localClippingEnabled = true;

  /** id -> { id, x, label, points, mesh, material, opacity, slide, flash } */
  const curves = new Map();
  let focus = new Set();
  let markSize = 0.1;
  let tubeRadius = 0.01;
  /** One bead geometry for every dotted curve; rebuilt when the hull size changes. */
  let sharedBead = new THREE.SphereGeometry(1, 8, 6);
  let tweens = [];
  let frame = 0;
  // Skin clipping: only the hull between the first and the newest arrived station shows.
  const clipLow = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);
  const clipHigh = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);

  // ---------------------------------------------------------------- tweens

  function tween(duration, update, delay = 0) {
    const start = performance.now() + delay;
    tweens.push({ start, duration, update });
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function tick(now) {
    frame = 0;
    tweens = tweens.filter((t) => {
      if (now < t.start) return true;
      const progress = Math.min(1, (now - t.start) / t.duration);
      t.update(progress);
      return progress < 1;
    });
    requestRender();
    if (tweens.length) frame = requestAnimationFrame(tick);
  }

  function stopTweens() {
    tweens = [];
    cancelAnimationFrame(frame);
    frame = 0;
  }

  // ---------------------------------------------------------------- skin

  function setSkin(opacity, clip = null) {
    const transparent = opacity < 1;
    hullMaterial.visible = opacity > 0 || Boolean(clip);
    if (hullMaterial.transparent !== transparent) hullMaterial.needsUpdate = true;
    hullMaterial.transparent = transparent;
    hullMaterial.depthWrite = !transparent;
    hullMaterial.opacity = opacity;
    if (clip) {
      clipLow.constant = -clip[0];
      clipHigh.constant = clip[1];
      setSkinClip([clipLow, clipHigh]);
    } else {
      setSkinClip(null);
    }
  }

  // ---------------------------------------------------------------- curves

  function curveColour(curve) {
    const palette = colours();
    const base = (palette.source[curve.label] || palette.source.omitted).clone();
    return curve.flash > 0 ? base.lerp(palette.accent, curve.flash) : base;
  }

  function curveOpacity(curve) {
    const dim = focus.size && !focus.has(curve.id) ? UNFOCUSED_OPACITY : 1;
    return curve.opacity * dim;
  }

  function disposeCurve(curve) {
    if (!curve.mesh) return;
    group.remove(curve.mesh);
    curve.mesh.traverse((node) => {
      if (node.geometry && node.geometry !== sharedBead) node.geometry.dispose();
    });
    curve.material.dispose();
    curve.mesh = null;
  }

  /** Rebuild a curve's tubes and pattern marks from its points, label and state. */
  function drawCurve(curve) {
    disposeCurve(curve);
    const pattern = PATTERNS[curve.label] || PATTERNS.omitted;
    curve.material = new THREE.MeshBasicMaterial({ color: curveColour(curve), transparent: true, opacity: curveOpacity(curve) });
    const x = curve.x - curve.slide;
    const path = fullSection(curve.points).map(([y, z]) => new THREE.Vector3(x, y, z));
    const mesh = new THREE.Group();
    const add = (geometry, position = null) => {
      const part = new THREE.Mesh(geometry, curve.material);
      part.renderOrder = 10;
      if (position) part.position.copy(position);
      mesh.add(part);
    };
    if (pattern.dots) {
      for (const point of beads(path, pattern.dots * markSize)) add(sharedBead, point);
    } else if (pattern.dash) {
      for (const piece of dashPieces(path, pattern.dash[0] * markSize, pattern.dash[1] * markSize)) add(tube(piece, tubeRadius));
    } else {
      add(tube(path, tubeRadius));
    }
    if (pattern.deco === 'ticks') {
      for (const [a, b] of tickSegments(curve.points, x)) add(tube([a, b], tubeRadius * 0.8));
    } else if (pattern.deco === 'diamonds') {
      const diamond = new THREE.OctahedronGeometry(markSize * 0.55);
      for (const point of everyNth(path, 9)) add(diamond, point);
    }
    curve.mesh = mesh;
    group.add(mesh);
  }

  /** Short ticks across both halves of a section, every 6th point. */
  function tickSegments(points, x) {
    const segments = [];
    for (const sign of [1, -1]) {
      for (let i = 6; i < points.length - 1; i += 6) {
        const [y, z] = points[i];
        const ty = sign * (points[i + 1][0] - points[i - 1][0]);
        const tz = points[i + 1][1] - points[i - 1][1];
        const length = Math.hypot(ty, tz) || 1;
        const ny = (-tz / length) * markSize * 0.6;
        const nz = (ty / length) * markSize * 0.6;
        segments.push([new THREE.Vector3(x, sign * y - ny, z - nz), new THREE.Vector3(x, sign * y + ny, z + nz)]);
      }
    }
    return segments;
  }

  function everyNth(points, n) {
    return points.filter((_, i) => i > 0 && i < points.length - 1 && i % n === 0);
  }

  /** Only colour and opacity changed: update the material in place. */
  function restyleCurve(curve) {
    if (!curve.material) return;
    curve.material.color = curveColour(curve);
    curve.material.opacity = curveOpacity(curve);
  }

  function removeAll() {
    for (const curve of curves.values()) disposeCurve(curve);
    curves.clear();
  }

  function bounds() {
    if (!curves.size) return null;
    const box = new THREE.Box3();
    for (const curve of curves.values()) {
      for (const [y, z] of curve.points) {
        box.expandByPoint(new THREE.Vector3(curve.x, y, z));
        box.expandByPoint(new THREE.Vector3(curve.x, -y, z));
      }
    }
    return box;
  }

  function measure(sections) {
    const depth = Math.max(...sections.flatMap((s) => s.points_yz_m.map((p) => p[1])), 0.1);
    markSize = depth * MARK_FRACTION;
    const radius = depth * TUBE_FRACTION;
    if (Math.abs(radius - tubeRadius) > tubeRadius * 0.01) {
      // Curves already drawn keep the old bead until they are drawn again.
      tubeRadius = radius;
      sharedBead = new THREE.SphereGeometry(tubeRadius * 1.5, 8, 6);
    }
    const xs = sections.map((s) => s.x_m);
    return { length: Math.max(...xs) - Math.min(...xs) || 1 };
  }

  function newCurve(section, { opacity = 1, slide = 0 } = {}) {
    return {
      id: section.id,
      x: section.x_m,
      label: section.source_label || 'omitted',
      points: section.points_yz_m,
      mesh: null,
      material: null,
      opacity,
      slide,
      flash: 0,
    };
  }

  // ---------------------------------------------------------------- modes

  function showInstant(sections) {
    removeAll();
    for (const section of sections) {
      const curve = newCurve(section);
      curves.set(curve.id, curve);
      drawCurve(curve);
    }
    setSkin(SKIN_OPACITY);
  }

  /** First hull: stations slide in aft to fore; the skin shows between arrived stations. */
  function showGrowth(sections) {
    removeAll();
    const { length } = measure(sections);
    const slide = length * SLIDE_FRACTION;
    const firstX = sections[0].x_m;
    setSkin(0, [firstX, firstX]);
    sections.forEach((section, index) => {
      const curve = newCurve(section, { opacity: 0, slide });
      curves.set(curve.id, curve);
      drawCurve(curve);
      tween(CURVE_MS, (t) => {
        const eased = easeOut(t);
        curve.opacity = eased;
        curve.slide = slide * (1 - eased);
        drawCurve(curve);
        if (t < 1) return;
        // The skin now reaches this station; after the last one it is whole.
        if (index === sections.length - 1) setSkinClip(null);
        else clipHigh.constant = section.x_m;
      }, index * STAGGER_MS);
    });
    // The skin fades in while the stations arrive and settles when the last one lands.
    const total = sections.length * STAGGER_MS + CURVE_MS;
    tween(total + SKIN_FADE_MS, (t) => {
      hullMaterial.visible = true;
      hullMaterial.opacity = SKIN_OPACITY * easeOut(t);
      hullMaterial.transparent = true;
      hullMaterial.depthWrite = false;
    });
  }

  /** A new build: changed curves morph to their new shape and flash; others stay still. */
  function showUpdate(sections) {
    const incoming = new Set(sections.map((s) => s.id));
    for (const [id, curve] of curves) {
      if (incoming.has(id)) continue;
      tween(CURVE_MS, (t) => {
        curve.opacity = 1 - t;
        restyleCurve(curve);
        if (t === 1) {
          disposeCurve(curve);
          curves.delete(id);
        }
      });
    }
    for (const section of sections) {
      const old = curves.get(section.id);
      if (!old) {
        const curve = newCurve(section, { opacity: 0 });
        curves.set(curve.id, curve);
        drawCurve(curve);
        tween(CURVE_MS, (t) => {
          curve.opacity = t;
          restyleCurve(curve);
        });
        continue;
      }
      const label = section.source_label || 'omitted';
      if (sameCurve(old.points, section.points_yz_m) && old.label === label) continue;
      const from = old.points;
      const to = section.points_yz_m;
      old.label = label;
      const morph = from.length === to.length;
      if (!morph) old.points = to;
      tween(CURVE_MS, (t) => {
        if (morph) {
          const eased = easeOut(t);
          old.points = from.map((p, i) => [p[0] + (to[i][0] - p[0]) * eased, p[1] + (to[i][1] - p[1]) * eased]);
        }
        drawCurve(old);
      });
      tween(FLASH_MS, (t) => {
        old.flash = Math.sin(Math.PI * t);
        restyleCurve(old);
      });
    }
    setSkin(SKIN_OPACITY);
  }

  return {
    /**
     * Show the section curves of one build. `sections`: SectionCurve[] with points.
     * `mode`: "grow", "update" or "instant". Null or [] clears the curves and the skin rules.
     */
    show(sections, { mode = 'instant', hideSkin = false } = {}) {
      stopTweens();
      const drawable = (sections || []).filter((s) => s.points_yz_m?.length > 1).sort((a, b) => a.x_m - b.x_m);
      if (!drawable.length) {
        removeAll();
        setSkin(hideSkin ? 0 : 1);
        requestRender();
        return;
      }
      const hadCurves = curves.size > 0;
      measure(drawable);
      const reduced = prefersReducedMotion();
      if (reduced || mode === 'instant') showInstant(drawable);
      else if (mode === 'grow' || !hadCurves) showGrowth(drawable);
      else showUpdate(drawable);
      if (!hadCurves) onFirstSections(bounds());
      requestRender();
    },
    setFocus(ids) {
      focus = new Set(ids || []);
      for (const curve of curves.values()) restyleCurve(curve);
      requestRender();
    },
    refreshColours() {
      for (const curve of curves.values()) restyleCurve(curve);
    },
    bounds,
  };
}
