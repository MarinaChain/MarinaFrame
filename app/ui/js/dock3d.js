// Where the part list and the fact card sit over the 3D view, and what that leaves free for the
// model. The column of panels is docked at the right, the fact card at its bottom. No DOM here, so
// the rules are tested alone (ui-tests/dock3d.test.mjs).

/** A pane shorter than this (CSS px) shows the fact card collapsed to its title row. */
export const COMPACT_HOST_PX = 360;
/** The fact card is at most this share of the pane's height. */
export const CARD_MAX_SHARE = 0.4;
/** The part of the pane's width and height a framed part may use is never smaller than this. */
const MIN_USABLE = 0.35;

/** True when the pane is short enough that the card starts collapsed. */
export function isCompactHost(height) {
  return height < COMPACT_HOST_PX;
}

/** The tallest the fact card may be (CSS px) in a pane of this height. */
export function cardMaxHeight(height) {
  return Math.round(height * CARD_MAX_SHARE);
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
