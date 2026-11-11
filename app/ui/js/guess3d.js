// How the 3D view shows the x ranges a draft guessed. Adjacent or overlapping ranges merge into
// one band, so a run of guessed stations is one box, not one box per station. When guesses cover
// most of the hull, boxes would hide it: the view then shows a thin bar along the base line and
// one note instead.

/**
 * Share of the hull length above which the view shows the light form (a base-line bar and a
 * note) instead of boxes. Above half the hull, boxes cover more hull than they leave readable.
 */
export const GUESS_BOX_LIMIT_SHARE = 0.5;

/**
 * Gap in metres up to which two ranges count as adjacent. Per-station ranges meet at the
 * half-way points, but rounding can leave a hair of space between them.
 */
const ADJACENT_GAP_M = 1e-3;

/** The note the light form shows. */
export const MOST_GUESSED_NOTE = 'Most stations are guesses';

/**
 * Merge adjacent or overlapping [x0, x1] ranges. Returns new ranges sorted by x0, each with
 * x0 <= x1. Ranges with a swapped start and end are read the right way round.
 */
export function mergeGuessRanges(ranges) {
  const sorted = ranges
    .filter((range) => Array.isArray(range) && range.length === 2 && range.every(Number.isFinite))
    .map(([a, b]) => [Math.min(a, b), Math.max(a, b)])
    .sort((first, second) => first[0] - second[0]);
  const merged = [];
  for (const [start, end] of sorted) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1] + ADJACENT_GAP_M) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}

/**
 * What the view draws for the guessed `ranges` on a hull from `hullX0` to `hullX1` metres:
 * { mode, ranges, share }. `mode` is "none" (no guesses), "boxes" (one box per merged range) or
 * "bar" (a base-line bar per merged range and the note). `ranges` are merged and clipped to the
 * hull; `share` is the part of the hull length they cover (0 to 1).
 */
export function guessDisplay(ranges, hullX0, hullX1) {
  const length = hullX1 - hullX0;
  const clipped = mergeGuessRanges(ranges)
    .map(([start, end]) => [Math.max(start, hullX0), Math.min(end, hullX1)])
    .filter(([start, end]) => end >= start);
  if (!clipped.length || !(length > 0)) return { mode: 'none', ranges: [], share: 0 };
  const covered = clipped.reduce((sum, [start, end]) => sum + (end - start), 0);
  const share = Math.min(1, covered / length);
  return { mode: share > GUESS_BOX_LIMIT_SHARE ? 'bar' : 'boxes', ranges: clipped, share };
}
