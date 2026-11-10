// Named spaces of the 3D view: a box the model is clipped to. One space per built tank (from the
// tank's bounds) and one box between two bulkhead frames of the steel model. No DOM and no
// three.js here, so the rules are tested alone (ui-tests/spaces3d.test.mjs).
//
// A box is { min: [x, y, z], max: [x, y, z] } in metres, ship frame (x forward, y to port, z up).

import { frameAt, frameLabel } from './reference3d.js';

/** A tank's box is widened by this much (m) so its own walls are not cut away by the clip. */
export const SPACE_PAD_M = 0.03;
/** Bulkhead detection: face areas are summed in x bins of this width (m)... */
const BIN_M = 0.05;
/** ...bins this close (m) are one plate (a plate and its stiffeners, or both faces of a slab)... */
const MERGE_GAP_M = 0.15;
/** ...a plate must hold this share of the biggest plate's area, so a small bracket is not a bulkhead... */
const MIN_AREA_SHARE = 0.25;
/** ...and a face counts as transverse when its normal is this close to the x axis. */
const TRANSVERSE_COSINE = 0.9;

/** The box widened by `pad` metres on every side. */
export function padBox(box, pad = SPACE_PAD_M) {
  return { min: box.min.map((v) => v - pad), max: box.max.map((v) => v + pad) };
}

/** Length, breadth and height of a box as "3.00 × 3.00 × 1.20 m". */
export function boxSizeText(box) {
  return `${[0, 1, 2].map((k) => (box.max[k] - box.min[k]).toFixed(2)).join(' × ')} m`;
}

/**
 * One space per tank: `tanks` is [{ id, name, box }] (box in metres). Sorted by name, numbers
 * in order ("No 2" before "No 10"). A tank with an empty box has no space.
 */
export function tankSpaces(tanks) {
  return tanks
    .filter((tank) => tank.box && tank.box.max.every((v, k) => v > tank.box.min[k]))
    .map((tank) => ({
      id: `space:${tank.id}`, name: tank.name, kind: 'tank', detail: boxSizeText(tank.box), box: padBox(tank.box), custom: false,
    }))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
}

/**
 * The x positions (m) of the transverse plates in a mesh: `positions` is a flat array of world
 * x, y, z, `index` the triangle indices (or null for a plain triangle list). A plate is a
 * cluster of faces that face along x; clusters with little area are left out. Sorted by x.
 */
export function bulkheadPositions(positions, index = null) {
  const triangles = index ? index.length / 3 : positions.length / 9;
  const areaByBin = new Map();
  const vertex = (n) => (index ? index[n] : n) * 3;
  for (let t = 0; t < triangles; t += 1) {
    const a = vertex(t * 3);
    const b = vertex(t * 3 + 1);
    const c = vertex(t * 3 + 2);
    const ux = positions[b] - positions[a];
    const uy = positions[b + 1] - positions[a + 1];
    const uz = positions[b + 2] - positions[a + 2];
    const vx = positions[c] - positions[a];
    const vy = positions[c + 1] - positions[a + 1];
    const vz = positions[c + 2] - positions[a + 2];
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz);
    if (!length || Math.abs(nx) / length < TRANSVERSE_COSINE) continue;
    const x = (positions[a] + positions[b] + positions[c]) / 3;
    const bin = Math.round(x / BIN_M);
    const area = length / 2;
    const entry = areaByBin.get(bin) || { area: 0, moment: 0 };
    entry.area += area;
    entry.moment += area * x;
    areaByBin.set(bin, entry);
  }
  const bins = [...areaByBin.entries()].sort((a, b) => a[0] - b[0]);
  const plates = [];
  for (const [bin, entry] of bins) {
    const last = plates[plates.length - 1];
    if (last && (bin - last.lastBin) * BIN_M <= MERGE_GAP_M) {
      last.area += entry.area;
      last.moment += entry.moment;
      last.lastBin = bin;
    } else {
      plates.push({ area: entry.area, moment: entry.moment, lastBin: bin });
    }
  }
  const biggest = Math.max(0, ...plates.map((plate) => plate.area));
  return plates.filter((plate) => plate.area >= biggest * MIN_AREA_SHARE).map((plate) => plate.moment / plate.area);
}

/** A bulkhead's menu entry: its x and the frame it stands on ("Fr 7 · 3.50 m"). */
export function bulkheadChoices(xs, reference) {
  return xs.map((x) => {
    const frame = reference ? frameLabel(Math.round(frameAt(x, reference.frameSpacingM.value, reference.frameZeroX.value) * 10) / 10) : null;
    return { x, label: frame ? `${frame} · ${x.toFixed(2)} m` : `${x.toFixed(2)} m`, frame };
  });
}

/**
 * The space between two bulkheads: the full beam and depth of the hull box between their x.
 * The order of the two does not matter. Returns null for the same bulkhead twice.
 */
export function bulkheadSpace(first, second, hullBox) {
  if (!first || !second || Math.abs(first.x - second.x) < BIN_M) return null;
  const [low, high] = first.x < second.x ? [first, second] : [second, first];
  const box = padBox({ min: [low.x, hullBox.min[1], hullBox.min[2]], max: [high.x, hullBox.max[1], hullBox.max[2]] });
  const from = low.frame || `${low.x.toFixed(1)} m`;
  const to = high.frame || `${high.x.toFixed(1)} m`;
  return { id: `space:bulkheads:${low.x.toFixed(2)}:${high.x.toFixed(2)}`, name: `${from} to ${to}`, kind: 'bulkhead', detail: boxSizeText(box), box, custom: true };
}

/**
 * The six planes that keep what is inside a box: { normal: [x, y, z], constant } each (a point is
 * kept when normal . point + constant >= 0, the rule of the section cut). Null gives six planes
 * that keep everything: far beyond any vessel.
 */
export const OPEN_CONSTANT = 1e7;
export function boxPlanes(box) {
  const planes = [];
  for (let axis = 0; axis < 3; axis += 1) {
    const normal = [0, 0, 0];
    normal[axis] = 1;
    planes.push({ normal, constant: box ? -box.min[axis] : OPEN_CONSTANT });
    const back = [0, 0, 0];
    back[axis] = -1;
    planes.push({ normal: back, constant: box ? box.max[axis] : OPEN_CONSTANT });
  }
  return planes;
}

/** True when a point is inside a box (the kept side of all six planes). */
export function boxHas(box, point) {
  return point.every((v, k) => v >= box.min[k] && v <= box.max[k]);
}
