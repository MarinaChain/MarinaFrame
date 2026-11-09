// Reference values of the 3D view: the design waterline, the boot-top band and the frame
// numbering. Plain numbers only (no three.js), so the rules are tested in Node.
//
// A run gives no design draft and no frame spacing to the 3D view yet. Until it does, the view
// guesses both from the hull size and says so: every value has a source, "given" or "guessed".

/**
 * Draft guess as a share of the hull depth above the baseline. Small working vessels float at
 * about 55 % to 65 % of their moulded depth; 60 % is the middle of that range.
 */
const DRAFT_SHARE_OF_DEPTH = 0.6;
/**
 * Frame spacing guess (m): 0.002 L + 0.48, the typical transverse frame spacing of the class
 * rules for small steel ships, rounded to FRAME_SPACING_STEP_M.
 */
const FRAME_SPACING_PER_LENGTH = 0.002;
const FRAME_SPACING_BASE_M = 0.48;
const FRAME_SPACING_STEP_M = 0.05;
/** The boot-top band: this share of the hull depth, but not less than BOOT_TOP_MIN_M. */
const BOOT_TOP_SHARE_OF_DEPTH = 0.05;
const BOOT_TOP_MIN_M = 0.12;
/** Share of the boot-top band below the design waterline (the rest is above it). */
const BOOT_TOP_SHARE_BELOW = 0.3;

const roundTo = (value, step) => Math.round(value / step) * step;

/**
 * The baseline z of a hull: z = 0 when the hull reaches across it (the ship frame puts the
 * baseline at 0), else the lowest point of the hull.
 */
export function baselineZ(minZ, maxZ) {
  return minZ <= 0 && maxZ > 0 ? 0 : minZ;
}

/**
 * Reference values for a hull box { min: [x, y, z], max: [x, y, z] } (metres). `given` holds
 * values the run states ({ designWaterlineZ, frameSpacingM, frameZeroX }); the others are guessed.
 * Each value is { value, source } with source "given" or "guessed".
 */
export function hullReference(box, given = {}) {
  const base = baselineZ(box.min[2], box.max[2]);
  const depth = box.max[2] - base;
  const length = box.max[0] - box.min[0];
  const pick = (key, guess) => (Number.isFinite(given[key])
    ? { value: given[key], source: 'given' }
    : { value: guess, source: 'guessed' });
  const spacingGuess = Math.max(FRAME_SPACING_STEP_M,
    roundTo(FRAME_SPACING_PER_LENGTH * length + FRAME_SPACING_BASE_M, FRAME_SPACING_STEP_M));
  return {
    baselineZ: base,
    depth,
    designWaterlineZ: pick('designWaterlineZ', roundTo(base + DRAFT_SHARE_OF_DEPTH * depth, 0.01)),
    frameSpacingM: pick('frameSpacingM', Number(spacingGuess.toFixed(3))),
    // Frame 0 at x = 0, the aft perpendicular in the ship frame, when the hull reaches it.
    frameZeroX: pick('frameZeroX', box.min[0] <= 0 && box.max[0] >= 0 ? 0 : box.min[0]),
  };
}

/** The boot-top band [lower z, upper z] around a design waterline, for a hull of `depth` metres. */
export function bootTopBand(waterlineZ, depth) {
  const height = Math.max(BOOT_TOP_MIN_M, BOOT_TOP_SHARE_OF_DEPTH * depth);
  return [waterlineZ - height * BOOT_TOP_SHARE_BELOW, waterlineZ + height * (1 - BOOT_TOP_SHARE_BELOW)];
}

/** The paint zone at height z: "antifouling" below the boot top, "boottop" in it, "topside" above. */
export function paintZone(z, band) {
  if (z < band[0]) return 'antifouling';
  if (z <= band[1]) return 'boottop';
  return 'topside';
}

/** The frame number (a decimal) at x, for a spacing and the x of frame 0 (metres). */
export function frameAt(x, spacing, zeroX) {
  return (x - zeroX) / spacing;
}

/** The x of the frame nearest to x (metres). */
export function nearestFrameX(x, spacing, zeroX) {
  return zeroX + Math.round(frameAt(x, spacing, zeroX)) * spacing;
}

/** "Fr 12", or "Fr 12.4" between frames (one decimal; -0 reads as 0). */
export function frameLabel(frame) {
  const rounded = Math.round(frame * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `Fr ${text === '-0' ? '0' : text}`;
}

/**
 * Section cut planes: x is a frame (transverse) cut, y a buttock (longitudinal) cut, z a
 * waterline (horizontal) cut. `keep` is the side the cut keeps when not flipped: aft of a frame
 * cut, port of a buttock cut (the home view looks from starboard), below a waterline cut.
 */
export const CUT_AXES = {
  x: { index: 0, name: 'Frame', keep: -1, word: 'x' },
  y: { index: 1, name: 'Buttock', keep: 1, word: 'y' },
  z: { index: 2, name: 'Waterline', keep: -1, word: 'z' },
};

/**
 * The clipping plane of a cut as { normal: [x, y, z], constant }: the points p kept are those
 * with normal · p + constant >= 0 (the three.js Plane rule).
 */
export function cutPlane(axis, value, flipped = false) {
  const spec = CUT_AXES[axis];
  const sign = flipped ? -spec.keep : spec.keep;
  const normal = [0, 0, 0];
  normal[spec.index] = sign;
  return { normal, constant: -sign * value };
}

/** The readout of a cut position: "Fr 24 · x 13.20 m" for a frame cut, "z 2.57 m" otherwise. */
export function cutLabel(axis, value, reference) {
  const metres = `${CUT_AXES[axis].word} ${value.toFixed(2)} m`;
  if (axis !== 'x' || !reference) return metres;
  return `${frameLabel(frameAt(value, reference.frameSpacingM.value, reference.frameZeroX.value))} · ${metres}`;
}
