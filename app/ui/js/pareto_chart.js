// Pareto chart of a design project (docs/design/2026-11-14-workbench-ux-plan.md, 4.4): fuel per
// day against cargo capacity, with the band of each value as error bars. The parent is a fixed
// reference (never on the front line); dominated candidates are grey; candidates that fail a
// check are hatched and tagged, never hidden; pairs whose bands overlap get one dashed outline
// and are listed in text. Points with an unknown value are listed under the chart. Geometry is in pareto_layout.js; this module only builds DOM.
import { el, svg } from './dom.js';
import { t, termLabel } from './i18n.js';
import { paretoState, indistinguishablePairs } from './design_compare.js';
import { chartLayout, PAIR_PAD } from './pareto_layout.js';
import { numberFormat } from './design_values.js';

const HEIGHT = 340;
const MIN_WIDTH = 300; // below this the tick labels collide; the box scrolls instead
const MARKER_RADIUS = 7;
const CAP = 4; // half length of an error-bar end cap
let charts = 0; // unique ids for the hatch patterns

function formatValue(value, digits) {
  return numberFormat({ maximumFractionDigits: digits }).format(value);
}

/** "66 ± 1.5 t/day", or "66 t/day, no band". */
function valueText(value, band, unit, digits) {
  if (value === null) return t('status.unknown');
  if (!band) return `${formatValue(value, digits)} ${unit}, ${t('design.chart.noBand')}`;
  const half = (band.high - band.low) / 2;
  return `${formatValue(value, digits)} ± ${formatValue(half, digits)} ${unit}`;
}

function stateText(point, names, checkLabel) {
  const state = paretoState(point);
  const parts = [t(`design.pareto.${state}`)];
  if (point.indistinguishable.length) {
    parts.push(t('design.pareto.near', { names: point.indistinguishable.map((id) => names.get(id)).join(', ') }));
  }
  if (point.fails.length) parts.push(t('design.chart.pointFails', { checks: point.fails.map(checkLabel).join(', ') }));
  return parts.join('. ');
}

function hatchPattern(id, tone) {
  return svg('pattern', { id, width: 4, height: 4, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
    svg('rect', { width: 4, height: 4, class: `pareto-hatch-bg pareto-hatch-${tone}` }),
    svg('line', { x1: 0, y1: 0, x2: 0, y2: 4, class: 'pareto-hatch-line' }));
}

function axes(layout, titles) {
  const { plot, xTicks, yTicks, scaleX, scaleY } = layout;
  const parts = [];
  for (const tick of xTicks.ticks) {
    const x = scaleX(tick);
    parts.push(svg('line', { x1: x, x2: x, y1: plot.top, y2: plot.bottom, class: 'pareto-grid' }),
      svg('text', { x, y: plot.bottom + 18, class: 'pareto-tick', 'text-anchor': 'middle' }, formatValue(tick, xTicks.digits)));
  }
  for (const tick of yTicks.ticks) {
    const y = scaleY(tick);
    parts.push(svg('line', { x1: plot.left, x2: plot.right, y1: y, y2: y, class: 'pareto-grid' }),
      svg('text', { x: plot.left - 8, y: y + 4, class: 'pareto-tick', 'text-anchor': 'end' }, formatValue(tick, yTicks.digits)));
  }
  parts.push(svg('rect', { x: plot.left, y: plot.top, width: plot.right - plot.left, height: plot.bottom - plot.top, class: 'pareto-frame' }),
    svg('text', { x: (plot.left + plot.right) / 2, y: plot.bottom + 42, class: 'pareto-axis-title', 'text-anchor': 'middle' }, titles.x),
    svg('text', { x: 0, y: 0, class: 'pareto-axis-title', 'text-anchor': 'middle',
      transform: `translate(16 ${(plot.top + plot.bottom) / 2}) rotate(-90)` }, titles.y));
  return svg('g', { 'aria-hidden': 'true' }, ...parts);
}

/** A dashed rounded box around two points whose bands overlap on both axes. */
function pairOutline(box) {
  return svg('rect', { class: 'pareto-pair', x: box.left, y: box.top, rx: PAIR_PAD,
    width: box.right - box.left, height: box.bottom - box.top });
}

/**
 * The front line joins the candidates on the front in order of fuel. The parent is a fixed
 * reference, not a competitor, so the line never passes through it.
 */
function frontLine(points) {
  const front = points.filter((point) => paretoState(point) === 'front').sort((a, b) => a.x - b.x);
  if (front.length < 2) return null;
  return svg('polyline', { class: 'pareto-front', points: front.map((point) => `${point.px},${point.py}`).join(' ') });
}

function errorBars(point, layout) {
  const { scaleX, scaleY } = layout;
  const bars = [];
  if (point.xBand) {
    const [x1, x2] = [scaleX(point.xBand.low), scaleX(point.xBand.high)];
    bars.push(svg('line', { x1, x2, y1: point.py, y2: point.py }),
      svg('line', { x1, x2: x1, y1: point.py - CAP, y2: point.py + CAP }),
      svg('line', { x1: x2, x2, y1: point.py - CAP, y2: point.py + CAP }));
  }
  if (point.yBand) {
    const [y1, y2] = [scaleY(point.yBand.low), scaleY(point.yBand.high)];
    bars.push(svg('line', { x1: point.px, x2: point.px, y1, y2 }),
      svg('line', { x1: point.px - CAP, x2: point.px + CAP, y1, y2: y1 }),
      svg('line', { x1: point.px - CAP, x2: point.px + CAP, y1: y2, y2 }));
  }
  return svg('g', { class: 'pareto-bar' }, ...bars);
}

function marker(point, patterns) {
  const state = paretoState(point);
  if (state === 'reference') {
    const r = MARKER_RADIUS + 1;
    return svg('path', { class: 'pareto-marker', d: `M${point.px} ${point.py - r}l${r} ${r}l${-r} ${r}l${-r} ${-r}z` });
  }
  // Inline style, not the fill attribute: the stylesheet's fill would win over an attribute.
  const style = point.fails.length ? { fill: `url(#${patterns[state]})` } : null;
  return svg('circle', { class: 'pareto-marker', cx: point.px, cy: point.py, r: MARKER_RADIUS, style });
}

/**
 * The chart for `points` (paretoPoints) at `width` pixels. `info` maps each id to its
 * { letter, name }; `onOpen(id)` opens a candidate on click or Enter.
 */
function chartSvg(points, width, { info, checkLabel, onOpen, patternIds }) {
  // A candidate that fails a check carries a tag in its label ("D · 1 fail"): hatching alone is
  // easy to miss at this size.
  const tagOf = (point) => (point.fails.length ? t('design.check.fail', { count: point.fails.length }) : '');
  const labelled = points.map((point) => {
    const name = point.reference ? t('design.chart.parent') : info.get(point.id).letter;
    return { ...point, name, tag: tagOf(point), label: tagOf(point) ? `${name} · ${tagOf(point)}` : name };
  });
  const layout = chartLayout(labelled, { width, height: HEIGHT, pairs: indistinguishablePairs(points) });
  const titles = {
    x: t('design.chart.axis', { label: termLabel('daily_fuel'), unit: 't/day' }),
    y: t('design.chart.axis', { label: termLabel('cargo_capacity'), unit: 'm3' }),
  };
  const names = new Map(points.map((point) => [point.id, info.get(point.id).name]));
  const pairs = layout.pairBoxes.map(pairOutline);
  const marks = layout.points.map((point) => {
    const label = t('design.chart.point', {
      name: names.get(point.id),
      fuel: valueText(point.x, point.xBand, 't/day', layout.xTicks.digits + 1),
      cargo: valueText(point.y, point.yBand, 'm3', 0),
      state: stateText(point, names, checkLabel),
    });
    const state = paretoState(point);
    const group = svg('g', {
      class: 'pareto-point', 'data-state': state, 'data-fails': point.fails.length ? 'true' : null,
      tabindex: '0', role: point.reference ? 'img' : 'link',
      'aria-label': point.reference ? label : `${label} ${t('design.chart.open')}`,
    },
    svg('title', {}, label),
    errorBars(point, layout),
    svg('circle', { class: 'pareto-focus', cx: point.px, cy: point.py, r: MARKER_RADIUS + 5 }),
    marker(point, patternIds),
    svg('text', { class: 'pareto-label', x: point.labelAt.x, y: point.labelAt.y, 'text-anchor': point.labelAt.anchor },
      point.name, point.tag ? svg('tspan', { class: 'pareto-fail-tag' }, ` · ${point.tag}`) : null));
    if (!point.reference) {
      group.addEventListener('click', () => onOpen(point.id));
      group.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(point.id); }
      });
    }
    return group;
  });
  // Draw the parent last among the points so its diamond stays on top of nearby bars.
  marks.sort((a, b) => (a.dataset.state === 'reference') - (b.dataset.state === 'reference'));
  return svg('svg', { class: 'pareto-svg', width, height: HEIGHT, viewBox: `0 0 ${width} ${HEIGHT}`, role: 'group',
    'aria-label': t('design.chart.title') },
  svg('defs', {}, hatchPattern(patternIds.front, 'front'), hatchPattern(patternIds.dominated, 'dominated')),
  axes(layout, titles), svg('g', { 'aria-hidden': 'true' }, frontLine(layout.points), ...pairs), ...marks);
}

function legendSwatch(kind, patternIds) {
  const shapes = {
    front: svg('circle', { cx: 8, cy: 8, r: 5, class: 'pareto-marker' }),
    dominated: svg('circle', { cx: 8, cy: 8, r: 5, class: 'pareto-marker' }),
    fails: svg('circle', { cx: 8, cy: 8, r: 5, class: 'pareto-marker', style: { fill: `url(#${patternIds.front})` } }),
    reference: svg('path', { class: 'pareto-marker', d: 'M8 2l6 6l-6 6l-6 -6z' }),
    near: svg('rect', { x: 1, y: 3, width: 14, height: 10, rx: 5, class: 'pareto-pair' }),
    line: svg('line', { x1: 1, y1: 8, x2: 15, y2: 8, class: 'pareto-front' }),
  };
  const state = ['fails', 'line', 'near'].includes(kind) ? 'front' : kind;
  return svg('svg', { class: 'pareto-swatch', width: 16, height: 16, viewBox: '0 0 16 16', 'aria-hidden': 'true' },
    svg('g', { class: 'pareto-point', 'data-state': state, 'data-fails': kind === 'fails' ? 'true' : null }, shapes[kind]));
}

function legend(patternIds) {
  const items = [['front', 'legendFront'], ['dominated', 'legendDominated'], ['fails', 'legendFails'],
    ['reference', 'legendParent'], ['near', 'legendNear'], ['line', 'legendFrontLine']];
  return el('ul', { class: 'pareto-legend', 'aria-label': t('design.chart.legend') },
    ...items.map(([kind, key]) => el('li', {}, legendSwatch(kind, patternIds), t(`design.chart.${key}`))));
}

/** Text under the chart: pairs that cannot be told apart and points with an unknown value. */
function notes(points, info) {
  const name = (id) => info.get(id).letter;
  const pairs = indistinguishablePairs(points);
  const unknown = points.filter((point) => paretoState(point) === 'unknown');
  return el('div', { class: 'pareto-notes' },
    el('p', {}, pairs.length
      ? t('design.chart.pairs', { pairs: pairs.map(([a, b]) => t('design.chart.pair', { a: name(a), b: name(b) })).join('; ') })
      : t('design.chart.noPairs')),
    unknown.length ? el('p', { class: 'pareto-unknown' },
      t('design.chart.unplotted', { names: unknown.map((point) => info.get(point.id).name).join(', ') })) : null);
}

function summary(points, info) {
  const competitors = points.filter((point) => !point.reference);
  const list = (filter) => competitors.filter(filter).map((point) => info.get(point.id).letter).join(', ') || t('design.chart.none');
  return t('design.chart.summary', {
    count: competitors.length,
    front: list((point) => paretoState(point) === 'front'),
    dominated: list((point) => paretoState(point) === 'dominated'),
    fails: list((point) => point.fails.length > 0),
  });
}

/**
 * The chart as a figure: caption, plot (redrawn when its box changes width, so text keeps its
 * size), legend, notes and a text summary for screen readers.
 */
export function paretoChart(points, { info, checkLabel, onOpen }) {
  const id = ++charts;
  const patternIds = { front: `pareto-hatch-front-${id}`, dominated: `pareto-hatch-dominated-${id}` };
  const plot = el('div', { class: 'pareto-plot' });
  let drawnWidth = 0;
  const draw = () => {
    const width = Math.max(MIN_WIDTH, Math.floor(plot.clientWidth || 640));
    if (Math.abs(width - drawnWidth) < 8) return;
    drawnWidth = width;
    // Keep keyboard focus on the same point across a redraw.
    const focused = plot.contains(document.activeElement) ? document.activeElement.getAttribute('aria-label') : null;
    plot.replaceChildren(chartSvg(points, width, { info, checkLabel, onOpen, patternIds }));
    if (focused) [...plot.querySelectorAll('.pareto-point')].find((node) => node.getAttribute('aria-label') === focused)?.focus();
  };
  const titleId = `pareto-title-${id}`;
  const figure = el('figure', { class: 'pareto', 'aria-labelledby': titleId },
    el('figcaption', {}, el('h2', { id: titleId }, t('design.chart.title')), el('p', {}, t('design.chart.help'))),
    el('div', { class: 'pareto-body' }, plot, legend(patternIds)), notes(points, info),
    el('p', { class: 'visually-hidden' }, summary(points, info)));
  if (typeof ResizeObserver === 'function') new ResizeObserver(draw).observe(plot);
  queueMicrotask(draw);
  return figure;
}
