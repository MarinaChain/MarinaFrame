// Section-area check (Checks tab): the area of each built station plotted along the length,
// the naval architect's sectional-area curve. A fair hull gives a smooth curve, so a station
// whose area is far from the line through its two neighbours is flagged for review. The
// draft waterline is often unknown in a draft, so the person picks the height: deck or a
// part of the depth. Data: get_hull_sections (station curves, half-breadth y and height z).

import { el, svg, fill } from './dom.js';
import * as fmt from './format.js';

/** Heights the area is taken to, as a part of the moulded depth. */
const HEIGHTS = [
  { id: 'deck', label: 'Deck', part: 1 },
  { id: 'three-quarter', label: '¾ depth', part: 0.75 },
  { id: 'half', label: '½ depth', part: 0.5 },
];
/** A station whose area differs from the curve through its neighbours by more than this part of the largest area is flagged. */
const OFF_CURVE_LIMIT = 0.1; // 0.9% to 4.1% on the real DTMB 5415 hull: about 2x margin
/** Chart size in SVG units; it scales to the panel width. */
const CHART = { width: 300, height: 140, left: 34, right: 8, top: 10, bottom: 22 };

/**
 * Area of one full section (both sides) up to height `top`, from a half-section curve given
 * as [y, z] points in metres. Trapezoids over z; the part of a segment above `top` is cut.
 */
export function sectionArea(points, top) {
  const sorted = [...points].sort((a, b) => a[1] - b[1]);
  let half = 0;
  for (let i = 1; i < sorted.length; i += 1) {
    let [y0, z0] = sorted[i - 1];
    let [y1, z1] = sorted[i];
    if (z0 >= top) break;
    if (z1 > top) {
      y1 = y0 + ((y1 - y0) * (top - z0)) / (z1 - z0);
      z1 = top;
    }
    half += ((y0 + y1) / 2) * (z1 - z0);
  }
  return 2 * half;
}

/** Stations with their area, and how far each inner one is from its neighbours' line. */
export function areaCurve(sections, top) {
  const stations = sections
    .filter((s) => s.points_yz_m.length > 1)
    .map((s) => ({ id: s.id, x_m: s.x_m, label: s.source_label, area: sectionArea(s.points_yz_m, top) }))
    .sort((a, b) => a.x_m - b.x_m);
  const peak = Math.max(0, ...stations.map((s) => s.area));
  stations.forEach((station, i) => {
    station.offCurve = null;
    if (!peak || i === 0 || i === stations.length - 1) return;
    // The curve through the neighbours: a cubic through two on each side where they exist,
    // else the straight line through one on each side. A smooth hull bends, so a straight
    // line alone would flag every station near midship.
    const neighbours = [stations[i - 2], stations[i - 1], stations[i + 1], stations[i + 2]].filter(Boolean);
    const used = neighbours.length === 4 ? neighbours : [stations[i - 1], stations[i + 1]];
    station.offCurve = (station.area - lagrange(used, station.x_m)) / peak;
  });
  return stations;
}

/**
 * The numbers a naval architect reads off an area curve, between the end stations only
 * (trapezoids along x, so the ends beyond the first and last station are not counted):
 * volume, the largest area and where it is, the centre of the volume along x, and the
 * prismatic coefficient Cp = volume / (largest area x span). Null when there is no curve.
 */
export function curveSummary(stations) {
  if (stations.length < 2) return null;
  let volume = 0;
  let moment = 0;
  for (let i = 1; i < stations.length; i += 1) {
    const a = stations[i - 1];
    const b = stations[i];
    const width = b.x_m - a.x_m;
    const slice = ((a.area + b.area) / 2) * width;
    volume += slice;
    // Centroid of a trapezoid slice along x.
    const sum = a.area + b.area;
    const centre = sum ? a.x_m + (width * (a.area + 2 * b.area)) / (3 * sum) : (a.x_m + b.x_m) / 2;
    moment += slice * centre;
  }
  const largest = stations.reduce((best, s) => (s.area > best.area ? s : best), stations[0]);
  const span = stations[stations.length - 1].x_m - stations[0].x_m;
  if (!volume || !largest.area || !span) return null;
  return {
    volume_m3: volume,
    largest_area_m2: largest.area,
    largest_x_m: largest.x_m,
    centre_x_m: moment / volume,
    prismatic: volume / (largest.area * span),
  };
}

/** The polynomial through `points` ({ x_m, area }) evaluated at x. */
function lagrange(points, x) {
  let sum = 0;
  points.forEach((pi, i) => {
    let term = pi.area;
    points.forEach((pj, j) => {
      if (i !== j) term *= (x - pj.x_m) / (pi.x_m - pj.x_m);
    });
    sum += term;
  });
  return sum;
}

/**
 * The section-area block. `onSelect(id)` selects a station in the app (strip ids and hull
 * section ids are the same for read stations).
 */
export function createAreas({ invoke, onSelect }) {
  let height = HEIGHTS[0];
  let key = null;
  let sections = null;
  let depth = null;
  let selectedId = null;
  const host = el('section', { class: 'areas', 'aria-labelledby': 'areas-title' });

  async function load(task, view) {
    const revision = view?.revision;
    const nextKey = revision ? `${task}|${revision}` : null;
    if (nextKey === key) return;
    key = nextKey;
    sections = null;
    depth = view?.model?.depth_m || null;
    render();
    if (!revision) return;
    try {
      const result = await invoke('get_hull_sections', { task, revision });
      if (key !== nextKey) return;
      sections = result.sections;
      if (!depth) depth = Math.max(0, ...sections.flatMap((s) => s.points_yz_m.map((p) => p[1])));
    } catch {
      if (key === nextKey) sections = [];
    }
    render();
  }

  function chart(stations) {
    const { width, height: h, left, right, top, bottom } = CHART;
    const xs = stations.map((s) => s.x_m);
    const x0 = Math.min(...xs);
    const x1 = Math.max(...xs);
    const peak = Math.max(...stations.map((s) => s.area)) || 1;
    const px = (x) => left + ((x - x0) / (x1 - x0 || 1)) * (width - left - right);
    const py = (a) => top + (1 - a / peak) * (h - top - bottom);
    const line = stations.map((s, i) => `${i ? 'L' : 'M'}${px(s.x_m).toFixed(1)} ${py(s.area).toFixed(1)}`).join(' ');
    return svg('svg', { class: 'areas-chart', viewBox: `0 0 ${width} ${h}`, role: 'img', 'aria-label': 'Section area along the length' },
      svg('line', { class: 'areas-axis', x1: left, y1: h - bottom, x2: width - right, y2: h - bottom }),
      svg('line', { class: 'areas-axis', x1: left, y1: top, x2: left, y2: h - bottom }),
      svg('text', { class: 'areas-tick', x: left - 4, y: top + 4, 'text-anchor': 'end' }, peak.toFixed(1)),
      svg('text', { class: 'areas-tick', x: left - 4, y: h - bottom, 'text-anchor': 'end' }, '0'),
      svg('text', { class: 'areas-tick', x: left, y: h - 6 }, fmt.metres(x0)),
      svg('text', { class: 'areas-tick', x: width - right, y: h - 6, 'text-anchor': 'end' }, fmt.metres(x1)),
      svg('path', { class: 'areas-line', d: line }),
      ...stations.map((s) => {
        const flagged = s.offCurve !== null && Math.abs(s.offCurve) > OFF_CURVE_LIMIT;
        const dot = svg('circle', {
          class: `areas-dot${flagged ? ' flagged' : ''}${s.id === selectedId ? ' selected' : ''}`,
          'data-source': s.label,
          cx: px(s.x_m).toFixed(1), cy: py(s.area).toFixed(1), r: s.id === selectedId ? 5 : 3.5,
        });
        dot.append(svg('title', {}, `${fmt.metres(s.x_m)}: ${s.area.toFixed(2)} m²${flagged ? `, ${Math.round(Math.abs(s.offCurve) * 100)}% off the curve` : ''}`));
        dot.addEventListener('click', () => onSelect(s.id));
        return dot;
      }));
  }

  function summaryList(summary) {
    if (!summary) return null;
    const item = (term, value, title) => el('div', { class: 'areas-stat', title },
      el('dt', {}, term), el('dd', {}, value));
    return el('dl', { class: 'areas-stats' },
      item('Volume', `${fmt.decimal(summary.volume_m3, 1)} m³`, 'Volume under the curve, between the end stations'),
      item('Largest', `${fmt.decimal(summary.largest_area_m2, 2)} m² at ${fmt.metres(summary.largest_x_m)}`, 'The largest section area and where it is'),
      item('Centre', fmt.metres(summary.centre_x_m), 'Centre of the volume along the length, from the aft end'),
      item('Cp', fmt.decimal(summary.prismatic, 2), 'Prismatic coefficient: volume / (largest area × length between the end stations)'));
  }

  function render() {
    const heightChips = el('div', { class: 'segmented segmented-small', role: 'radiogroup', 'aria-label': 'Area up to' },
      ...HEIGHTS.map((h) => el('button', {
        type: 'button', role: 'radio', 'aria-checked': String(h === height),
        onclick: () => { height = h; render(); },
      }, h.label)));
    const head = el('div', { class: 'areas-head' },
      el('h3', { id: 'areas-title' }, 'Section areas'), heightChips);
    if (!key) {
      fill(host, head, el('p', { class: 'panel-empty' }, 'Section areas show when the run has a build.'));
      return;
    }
    if (!sections) {
      fill(host, head, el('p', { class: 'panel-empty' }, 'Reading the built sections…'));
      return;
    }
    const stations = areaCurve(sections, (depth || 0) * height.part);
    if (stations.length < 3) {
      fill(host, head, el('p', { class: 'panel-empty' }, 'Too few built sections for a curve.'));
      return;
    }
    const flagged = stations.filter((s) => s.offCurve !== null && Math.abs(s.offCurve) > OFF_CURVE_LIMIT);
    fill(host, head, chart(stations), summaryList(curveSummary(stations)),
      flagged.length
        ? el('ul', { class: 'areas-flags' }, ...flagged.map((s) => el('li', {},
          el('button', { class: 'areas-flag', type: 'button', onclick: () => onSelect(s.id) },
            el('span', { class: 'change-x' }, fmt.metres(s.x_m)),
            `${Math.round(Math.abs(s.offCurve) * 100)}% ${s.offCurve > 0 ? 'above' : 'below'} the curve`))))
        : el('p', { class: 'areas-note' }, 'The curve is smooth: no station is far from its neighbours.'),
      // Say what the stations are compared with. No worker step reads an area curve printed
      // on a drawing yet, so the only reference is the hull's own fair curve.
      el('p', { class: 'areas-note' },
        `Each station is compared with the fair curve through its neighbours; the drawings give no area curve to compare with. Up to ${fmt.metres((depth || 0) * height.part, 2)} above the keel, between the end stations. A draft check, not a hydrostatic result.`));
  }

  return {
    element: host,
    /** Show the areas of the run's current build; `selected` is the selected section id. */
    show(task, view, selected) {
      selectedId = selected;
      load(task, view);
      render();
    },
  };
}
