// Where the part list and the fact card sit over the 3D view, and what that leaves free for the
// model. The column of panels is docked at the right, the fact card at its bottom. No DOM here, so
// the rules are tested alone (ui-tests/dock3d.test.mjs).

/** A pane shorter than this (CSS px) shows the fact card collapsed to its title row. */
export const COMPACT_HOST_PX = 360;
/** The part of the pane's width and height a framed part may use is never smaller than this. */
const MIN_USABLE = 0.35;

/** True when the pane is short enough that the card starts collapsed. */
export function isCompactHost(height) {
  return height < COMPACT_HOST_PX;
}

/**
 * What a framed part may use of the pane. `occupied` is { left, top } (CSS px from the pane's top
 * left): the panels cover everything right of `left` and below `top`; null means nothing is
 * covered. Returns { usableX, usableY, shiftX, shiftY }: the shares of the pane's width and height
 * left free at the top left, and how far (as shares of the half width and half height) the middle
 * of the framed part moves toward that free area.
 */
export function freeRegion({ width, height, occupied }) {
  if (!occupied || !(width > 0) || !(height > 0)) return { usableX: 1, usableY: 1, shiftX: 0, shiftY: 0 };
  const clamp = (value) => Math.min(1, Math.max(MIN_USABLE, value));
  const usableX = clamp(occupied.left / width);
  const usableY = clamp(occupied.top / height);
  return { usableX, usableY, shiftX: 1 - usableX, shiftY: 1 - usableY };
}

/** True when a screen box { right, bottom } reaches into the covered area. */
export function reachesCovered(box, occupied) {
  return Boolean(occupied) && box.right > occupied.left && box.bottom > occupied.top;
}

// ---------------------------------------------------------------- free-side placement
// The hover label and the docked fact card must not cover the part they describe, the source
// lines to the drawing (js/provenance.js) or an open part list. Boxes are { left, top, right,
// bottom } in CSS px from the pane's top left.

/** The area two boxes share (0 when they only touch or are apart). */
export function overlapArea(a, b) {
  const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return width > 0 && height > 0 ? width * height : 0;
}

/**
 * The first candidate that covers none of the `avoid` boxes; when each covers something, the one
 * that covers least (the earlier one on a tie). Candidates are in order of preference.
 * `extraCover(candidate)` adds covered area that boxes do not describe well (the pixels of a
 * part, which its screen box overstates).
 */
export function placeClear(candidates, avoid, extraCover = () => 0) {
  let best = null;
  let bestCovered = Infinity;
  for (const candidate of candidates) {
    const covered = avoid.reduce((sum, box) => sum + overlapArea(candidate, box), 0) + extraCover(candidate);
    if (covered === 0) return candidate;
    if (covered < bestCovered) {
      best = candidate;
      bestCovered = covered;
    }
  }
  return best;
}

/**
 * The corners where the docked card can sit, in order of preference: the right side first (the
 * drawing pane and the source lines are to the left of the 3D pane), bottom before top (the
 * tool bar is at the top). `insets` keep the card off the tool bar and the pane's edge marks.
 */
export function cornerBoxes({ width, height, size, insets }) {
  const left = insets.left;
  const right = width - insets.right - size.width;
  const top = insets.top;
  const bottom = height - insets.bottom - size.height;
  const box = (corner, x, y) => ({ corner, left: x, top: y, right: x + size.width, bottom: y + size.height });
  return [
    box('bottom-right', right, bottom),
    box('top-right', right, top),
    box('bottom-left', left, bottom),
    box('top-left', left, top),
  ];
}

/**
 * Spots for a label beside a part's screen box, in order of preference: right of it (away from
 * the drawing pane), above, below, then left. Each is moved inside `bounds`; a spot moved back
 * onto the part then covers it, and placeClear passes over it.
 */
export function besideBoxes({ part, size, bounds, gap }) {
  const clampX = (x) => Math.min(Math.max(0, x), Math.max(0, bounds.width - size.width));
  const clampY = (y) => Math.min(Math.max(0, y), Math.max(0, bounds.height - size.height));
  const spot = (side, x, y) => {
    const left = clampX(x);
    const top = clampY(y);
    return { side, left, top, right: left + size.width, bottom: top + size.height };
  };
  return [
    spot('right', part.right + gap, part.top),
    spot('above', part.left, part.top - gap - size.height),
    spot('below', part.left, part.bottom + gap),
    spot('left', part.left - gap - size.width, part.top),
  ];
}
