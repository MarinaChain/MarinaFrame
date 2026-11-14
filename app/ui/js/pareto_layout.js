// Pure geometry of the Pareto chart (docs/design/2026-11-14-workbench-ux-plan.md, 4.4): axis
// ranges that hold every point and its band, round tick values, pixel positions and label
// places that do not overlap. No DOM; tested in app/ui-tests/pareto_layout.test.mjs.

// Space around the plot for tick labels and axis titles, in pixels.
export const MARGIN = { top: 16, right: 24, bottom: 52, left: 84 };
const MARKER_RADIUS = 7;
const LABEL_HEIGHT = 14;
const LABEL_GAP = 6; // between a marker's edge and its label
export const PAIR_PAD = 13; // space between a marker and the dashed outline of its pair

/** A step of 1, 2 or 5 × 10^n that splits `span` into about `count` parts. */
function niceStep(span, count) {
  const raw = span / Math.max(count, 1);
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const factor = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return factor * power;
}

/**
 * Round ticks that cover [min, max]. A range of one value gets space on both sides, so a lone
 * point is not on the frame. `digits` is the number of fraction digits a tick label needs.
 */
export function niceTicks(min, max, count = 5) {
  let low = min;
  let high = max;
  if (!(high > low)) {
    const pad = Math.abs(low) * 0.05 || 1;
    low -= pad;
    high += pad;
  }
  const step = niceStep(high - low, count);
  const start = Math.floor(low / step) * step;
  const end = Math.ceil(high / step) * step;
  const ticks = [];
  // Rounding keeps 0.1 + 0.2 from printing as 0.30000000000000004.
  for (let value = start; value <= end + step / 2; value += step) ticks.push(Number(value.toPrecision(12)));
  const digits = Math.max(0, -Math.floor(Math.log10(step)));
  return { min: ticks[0], max: ticks.at(-1), step, ticks, digits };
}

/** The lowest and highest value of one axis over the points and their bands. */
function extent(points, axis) {
  const values = points.flatMap((point) => {
    const band = point[`${axis}Band`];
    return [point[axis], band?.low, band?.high];
  }).filter(Number.isFinite);
  return values.length ? [Math.min(...values), Math.max(...values)] : [0, 1];
}

function overlaps(a, b) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/**
 * A label place beside each marker, the first one that stays in the plot and does not cover
 * another label or marker. Diagonal places come first: the error bars run straight through the
 * marker, so a label at a corner does not sit on a bar. When none is free, the first place is
 * used (the text then overlaps, but it is never dropped).
 */
export function placeLabels(items, plot, charWidth = 7.5, obstacles = []) {
  const markers = items.map((item) => ({
    left: item.px - MARKER_RADIUS, right: item.px + MARKER_RADIUS,
    top: item.py - MARKER_RADIUS, bottom: item.py + MARKER_RADIUS,
  }));
  const taken = [];
  return items.map((item, index) => {
    const width = item.text.length * charWidth;
    const offset = MARKER_RADIUS + LABEL_GAP;
    const corner = offset - 3; // a diagonal place sits a little closer than a side place
    const options = [
      { anchor: 'start', x: item.px + corner, y: item.py - corner },
      { anchor: 'end', x: item.px - corner, y: item.py - corner },
      { anchor: 'start', x: item.px + corner, y: item.py + corner + LABEL_HEIGHT - 3 },
      { anchor: 'end', x: item.px - corner, y: item.py + corner + LABEL_HEIGHT - 3 },
      { anchor: 'start', x: item.px + offset, y: item.py + 4 },
      { anchor: 'end', x: item.px - offset, y: item.py + 4 },
      // Further out: clear of an outline drawn around a pair of close points.
      { anchor: 'end', x: item.px - offset, y: item.py - offset * 2 },
      { anchor: 'start', x: item.px + offset, y: item.py - offset * 2 },
      { anchor: 'end', x: item.px - offset, y: item.py + offset * 2 + LABEL_HEIGHT },
      { anchor: 'start', x: item.px + offset, y: item.py + offset * 2 + LABEL_HEIGHT },
    ];
    const boxOf = ({ anchor, x, y }) => {
      const left = anchor === 'start' ? x : anchor === 'end' ? x - width : x - width / 2;
      return { left, right: left + width, top: y - LABEL_HEIGHT + 3, bottom: y + 3 };
    };
    const inside = (box) => box.left >= plot.left && box.right <= plot.right && box.top >= plot.top && box.bottom <= plot.bottom;
    // An outline keeps a few pixels of air: text that touches a dashed line is hard to read.
    const air = (other) => ({ left: other.left - 4, right: other.right + 4, top: other.top - 4, bottom: other.bottom + 4 });
    const free = (box) => !taken.some((other) => overlaps(box, other)) && !obstacles.some((other) => overlaps(box, air(other)))
      && !markers.some((marker, other) => other !== index && overlaps(box, marker));
    const chosen = options.find((option) => inside(boxOf(option)) && free(boxOf(option)))
      || options.find((option) => inside(boxOf(option))) || options[0];
    taken.push(boxOf(chosen));
    return { x: chosen.x, y: chosen.y, anchor: chosen.anchor };
  });
}

/** The box of the dashed outline drawn around two close points (the chart draws the same box). */
export function pairBox(a, b) {
  return { left: Math.min(a.px, b.px) - PAIR_PAD, right: Math.max(a.px, b.px) + PAIR_PAD,
    top: Math.min(a.py, b.py) - PAIR_PAD, bottom: Math.max(a.py, b.py) + PAIR_PAD };
}

/**
 * Pixel layout for a chart `width` × `height`. Points with an unknown axis value are left out
 * of `plotted` (the chart lists them in text). x grows to the right, y grows upwards. `pairs`
 * ([idA, idB]) get an outline box that labels keep clear of.
 */
export function chartLayout(points, { width, height, pairs = [] }) {
  const plotted = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  const plot = { left: MARGIN.left, top: MARGIN.top, right: width - MARGIN.right, bottom: height - MARGIN.bottom };
  const xTicks = niceTicks(...extent(plotted, 'x'));
  const yTicks = niceTicks(...extent(plotted, 'y'));
  const scaleX = (value) => plot.left + (value - xTicks.min) / (xTicks.max - xTicks.min) * (plot.right - plot.left);
  const scaleY = (value) => plot.bottom - (value - yTicks.min) / (yTicks.max - yTicks.min) * (plot.bottom - plot.top);
  const placed = plotted.map((point) => ({ ...point, px: scaleX(point.x), py: scaleY(point.y) }));
  const byId = new Map(placed.map((point) => [point.id, point]));
  const boxes = pairs.filter(([a, b]) => byId.has(a) && byId.has(b)).map(([a, b]) => pairBox(byId.get(a), byId.get(b)));
  const labels = placeLabels(placed.map((point) => ({ px: point.px, py: point.py, text: point.label || '' })), plot, undefined, boxes);
  return {
    plot, xTicks, yTicks, scaleX, scaleY, pairBoxes: boxes,
    points: placed.map((point, index) => ({ ...point, labelAt: labels[index] })),
  };
}
