// Source view (docs/SOURCE_RECORD.md): point at a part or a section in the 3D model and the
// drawing pane shows the sheet it came from, zoomed to its region, with a line from the part to
// the region. A guess shows a dashed "best guess" line to each input it used (sheet regions and
// other parts). An item without a known source says so and draws no line.
//
// The functions at the top are pure (tested in app/ui-tests/provenance.test.mjs); the view
// below them is DOM only.

import { el, svg, prefersReducedMotion } from './dom.js';
import { gaRecords } from './ga_panel.js';

/** Wait this long on one part before its source shows, so a pointer passing over parts is calm. */
export const HOVER_DELAY_MS = 220;
/** Wait this long after the pointer leaves before the source view closes (time to move onto it). */
export const LEAVE_DELAY_MS = 320;
/** Most sheets shown at once; a record with more lists the rest by name. */
export const MAX_SHEETS = 3;
/** Space around a region when its sheet zooms to it, as a share of the region size. */
const REGION_PADDING = 0.6;
/** A zoomed sheet shows at least this share of the page, so a tiny label keeps its context. */
const MIN_VIEW_SHARE = 0.12;
/** The stacked-sheets animation: paper cards, the stagger between them and one card's time. */
const STACK_CARDS = 4;
const STACK_STAGGER_MS = 60;
const STACK_CARD_MS = 260;

export const NO_RECORD = 'No source record. Run again to record where this came from.';
/** Steel groups: the structure reader does not write records yet (docs/SOURCE_RECORD.md). */
export const STEEL_RECORD = Object.freeze({
  kind: 'unknown', reason: 'The structure reader does not record its source sheets yet.',
});

// ---------------------------------------------------------------- records

const indexes = new WeakMap();

/** Records of a task view by item id, built once per view (a run can have hundreds of parts). */
function indexOf(view) {
  let index = indexes.get(view);
  if (!index) {
    index = { parts: new Map(), sections: new Map(), labels: new Map() };
    for (const row of view?.capacity_plan?.rows || []) {
      if (row.source_record) index.parts.set(row.id, row.source_record);
      index.labels.set(row.id, row.name);
    }
    // A part record wins over its capacity plan row (the part is what the 3D view shows).
    for (const part of view?.components || []) {
      if (part.source_record) index.parts.set(part.id, part.source_record);
      index.labels.set(part.id, part.label);
    }
    for (const section of view?.sections || []) {
      if (section.source_record) index.sections.set(section.id, section.source_record);
    }
    // GA reading rows (particulars, counts, spaces) have their own "ga:" ids (ga_panel.js).
    for (const row of gaRecords(view?.ga_reading)) {
      if (row.record) index.parts.set(row.id, row.record);
      index.labels.set(row.id, row.label);
    }
    indexes.set(view, index);
  }
  return index;
}

/**
 * The source of one item: `{ record, label }`. `record` is null for an item of a run made before
 * source records (the view then says NO_RECORD). Steel groups are always unknown for now.
 */
export function sourceOf(view, item) {
  if (!item) return null;
  const index = indexOf(view);
  if (item.kind === 'section') {
    const section = view?.sections?.find((s) => s.id === item.id);
    const label = section ? `Section at ${section.x_m.toFixed(1)} m` : item.id;
    return { record: index.sections.get(item.id) || null, label };
  }
  if (item.id.startsWith('steel:')) {
    return { record: STEEL_RECORD, label: item.label || `Steel ${item.id.slice(6)}` };
  }
  return { record: index.parts.get(item.id) || null, label: index.labels.get(item.id) || item.label || item.id };
}

/** Regions of a record: the regions read, or the region inputs of a guess. */
function regionsOf(record) {
  if (record?.kind === 'read') return record.regions || [];
  if (record?.kind === 'guessed') return (record.inputs || []).filter((input) => input.sheet);
  return [];
}

/** Other items a guess used: `{ part: id }` inputs. */
export function partInputs(record) {
  return record?.kind === 'guessed' ? (record.inputs || []).filter((input) => input.part).map((input) => input.part) : [];
}

/**
 * The sheets of a record, in record order: `[{ sheet, page, view, regions: [region] }]`, at most
 * MAX_SHEETS (`more` counts the rest). A region without a box still names its sheet.
 */
export function sheetsOf(record) {
  const sheets = [];
  for (const region of regionsOf(record)) {
    let sheet = sheets.find((s) => s.sheet === region.sheet && s.page === region.page);
    if (!sheet) {
      sheet = { sheet: region.sheet, page: region.page, view: region.view, regions: [] };
      sheets.push(sheet);
    }
    if (region.box_px && region.page_px) sheet.regions.push(region);
  }
  return { sheets: sheets.slice(0, MAX_SHEETS), more: Math.max(0, sheets.length - MAX_SHEETS) };
}

/** The file name of a path ("sources/GA Rev1.pdf" -> "GA Rev1.pdf"). */
export function baseName(path) {
  return String(path || '').split(/[\\/]/).pop();
}

/** The run source whose file is `sheet` (the Sources list names files; records may give paths). */
export function sourceForSheet(sources, sheet) {
  const name = baseName(sheet);
  return sources.find((source) => source.name === sheet) || sources.find((source) => baseName(source.name) === name)
    || sources.find((source) => baseName(source.location) === name) || null;
}

/** A region box in the pixels of the image shown (the record box is in `page_px` pixels). */
export function scaleBox(region, image) {
  const [width, height] = region.page_px;
  const sx = image.width / width;
  const sy = image.height / height;
  const [left, top, right, bottom] = region.box_px;
  return [left * sx, top * sy, right * sx, bottom * sy];
}

/** The part of the image to show for `boxes` (image pixels): their union with space around it. */
export function viewBoxFor(boxes, image) {
  if (!boxes.length) return [0, 0, image.width, image.height];
  let [left, top, right, bottom] = boxes[0];
  for (const box of boxes) {
    left = Math.min(left, box[0]);
    top = Math.min(top, box[1]);
    right = Math.max(right, box[2]);
    bottom = Math.max(bottom, box[3]);
  }
  const width = Math.max(right - left, image.width * MIN_VIEW_SHARE);
  const height = Math.max(bottom - top, image.height * MIN_VIEW_SHARE);
  const cx = (left + right) / 2;
  const cy = (top + bottom) / 2;
  // Never more than the page (with a thin margin), and kept on the page.
  const margin = 0.02;
  const w = Math.min(width * (1 + 2 * REGION_PADDING), image.width * (1 + 2 * margin));
  const h = Math.min(height * (1 + 2 * REGION_PADDING), image.height * (1 + 2 * margin));
  const x = Math.min(Math.max(cx - w / 2, -image.width * margin), image.width * (1 + margin) - w);
  const y = Math.min(Math.max(cy - h / 2, -image.height * margin), image.height * (1 + margin) - h);
  return [x, y, w, h];
}

/** What the view says about a record: tone (read, guess, unknown, none), a title and a detail. */
export function summaryOf(record) {
  if (!record) return { tone: 'none', title: 'No source record', detail: NO_RECORD };
  if (record.kind === 'read') {
    const views = [...new Set(record.regions.map((r) => r.view).filter(Boolean))];
    return { tone: 'read', title: 'Read from the drawing', detail: views.length ? `${views.join(' and ')} view` : '' };
  }
  if (record.kind === 'guessed') return { tone: 'guess', title: 'Best guess', detail: record.method };
  return { tone: 'unknown', title: 'Source not known', detail: record.reason };
}

// ---------------------------------------------------------------- view

/** A smooth line from `a` to `b` (stage pixels) that leaves and arrives horizontally. */
/** Size of the "best guess" label (px), centred on its point. */
export const GUESS_LABEL_SIZE = Object.freeze({ width: 76, height: 20 });
/** Places along the line (fraction from the part) where the label may sit, nearest first. */
const GUESS_LABEL_STOPS = [0.22, 0.35, 0.5, 0.65, 0.8];
/** The label sits this far above its line, so it does not hide the dashes. */
const GUESS_LABEL_LIFT_PX = 10;

/**
 * Where the "best guess" label sits on the line from `from` (the part) to `to` (the sheet): the
 * first stop whose label box is clear of every `avoid` box (the 3D tool bar), else the first stop.
 * Boxes are { left, top, right, bottom } in the same coordinates as the points.
 */
export function labelSpot(from, to, avoid = [], size = GUESS_LABEL_SIZE) {
  const spotAt = (t) => ({ x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t - GUESS_LABEL_LIFT_PX });
  const covers = (spot, box) => spot.x + size.width / 2 > box.left && spot.x - size.width / 2 < box.right
    && spot.y + size.height / 2 > box.top && spot.y - size.height / 2 < box.bottom;
  for (const t of GUESS_LABEL_STOPS) {
    const spot = spotAt(t);
    if (!avoid.some((box) => covers(spot, box))) return spot;
  }
  return spotAt(GUESS_LABEL_STOPS[0]);
}

function linkPath(a, b) {
  const bend = Math.max(40, Math.abs(b.x - a.x) * 0.45);
  const direction = b.x < a.x ? -1 : 1;
  return `M ${a.x} ${a.y} C ${a.x + direction * bend} ${a.y}, ${b.x - direction * bend} ${b.y}, ${b.x} ${b.y}`;
}

const centre = (rect) => ({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });

/**
 * The source view. `pane` is the drawing pane (the view covers it), `stage` holds both panes
 * (the lines cross it). `anchorOf(item)` gives an item's point in 3D in client pixels, or null.
 * `loadSheet(sheet, page)` resolves `{ url, width, height }` or null when the run lacks the file.
 * `labelOf(id)` names another part a guess used.
 */
export function createSourceView({ stage, pane, anchorOf, loadSheet, labelOf = (id) => id }) {
  const peek = el('section', { class: 'source-peek', hidden: true, 'aria-live': 'polite', 'aria-label': 'Source of the part' });
  const links = svg('svg', { class: 'source-links', 'aria-hidden': 'true' });
  pane.append(peek);
  stage.append(links);

  let shown = null; // { key, item, record, tiles: [{ node, targets: [Element] }] }
  let frame = 0;
  let generation = 0;

  function close() {
    generation += 1;
    shown = null;
    peek.hidden = true;
    peek.replaceChildren();
    links.replaceChildren();
    cancelAnimationFrame(frame);
  }

  /** The stacked-sheets animation: paper cards fan out and away, then the sheets settle. */
  function ruffle(body) {
    if (prefersReducedMotion() || typeof body.animate !== 'function') return Promise.resolve();
    const cards = Array.from({ length: STACK_CARDS }, () => el('div', { class: 'source-paper' }));
    const stack = el('div', { class: 'source-stack' }, ...cards);
    body.append(stack);
    const runs = cards.map((card, i) => card.animate([
      { transform: `translate(${i * 3}px, ${i * 3}px) rotate(${(i - 1.5) * 1.6}deg)`, opacity: 1 },
      { transform: `translate(${-60 + i * 8}px, ${-26 - i * 6}px) rotate(${-9 + i * 2}deg)`, opacity: 0 },
    ], { duration: STACK_CARD_MS, delay: (STACK_CARDS - 1 - i) * STACK_STAGGER_MS, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', fill: 'forwards' }).finished);
    return Promise.all(runs).catch(() => {}).then(() => stack.remove());
  }

  function tileFor(sheet, image, tone) {
    const head = el('div', { class: 'source-tile-head' },
      el('span', { class: 'source-tile-name', title: sheet.sheet }, baseName(sheet.sheet)),
      el('span', { class: 'source-tile-meta' }, [sheet.page ? `page ${sheet.page + 1}` : null, sheet.view].filter(Boolean).join(' · ')));
    if (!image) {
      const note = el('div', { class: 'source-tile-note' }, 'This sheet is not in the run’s sources.');
      return { node: el('div', { class: 'source-tile' }, head, note), targets: [note] };
    }
    const boxes = sheet.regions.map((region) => scaleBox(region, image));
    const [x, y, w, h] = viewBoxFor(boxes, image);
    const outlines = boxes.map(([left, top, right, bottom]) => svg('rect', {
      class: `source-region ${tone}`, x: left, y: top, width: right - left, height: bottom - top, 'vector-effect': 'non-scaling-stroke',
    }));
    const picture = svg('svg', { class: 'source-sheet', viewBox: `${x} ${y} ${w} ${h}`, role: 'img',
      'aria-label': `${baseName(sheet.sheet)}${boxes.length ? ', region outlined' : ''}` },
    svg('rect', { x: 0, y: 0, width: image.width, height: image.height, class: 'source-sheet-paper' }),
    svg('image', { href: image.url, x: 0, y: 0, width: image.width, height: image.height, preserveAspectRatio: 'none' }),
    ...outlines);
    const note = boxes.length ? null : el('div', { class: 'source-tile-note floating' }, 'Region not recorded on this sheet.');
    return { node: el('div', { class: 'source-tile' }, head, el('div', { class: 'source-tile-body' }, picture, note)), targets: outlines.length ? outlines : [picture] };
  }

  /**
   * Draw the lines from the item to each target. It runs once a frame while the view shows (the
   * camera or the panes may move) but changes the DOM only when a point moved.
   */
  function drawLinks() {
    if (!shown) return;
    frame = requestAnimationFrame(drawLinks);
    const box = stage.getBoundingClientRect();
    const local = (p) => ({ x: Math.round(p.x - box.left), y: Math.round(p.y - box.top) });
    const start = anchorOf(shown.item);
    const guess = shown.record?.kind === 'guessed';
    if (!start || !shown.record || shown.record.kind === 'unknown') {
      if (shown.drawn !== '') links.replaceChildren();
      shown.drawn = '';
      return;
    }
    const from = local(start);
    const ends = shown.tiles.flatMap((tile) => tile.targets.map((target) => local(centre(target.getBoundingClientRect()))));
    const rings = [];
    for (const id of shown.partInputs) {
      const point = anchorOf({ kind: 'part', id }) || anchorOf({ kind: 'section', id });
      if (point) rings.push(local(point));
    }
    const signature = JSON.stringify([box.width, box.height, from, ends, rings]);
    if (signature === shown.drawn) return;
    shown.drawn = signature;
    links.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
    const tone = guess ? 'guess' : 'read';
    const nodes = [...ends, ...rings].map((to) => svg('path', { class: `source-link ${tone}`, d: linkPath(from, to) }));
    nodes.push(...rings.map((to) => svg('circle', { class: 'source-part-ring', cx: to.x, cy: to.y, r: 9 })));
    nodes.push(svg('circle', { class: `source-dot ${tone}`, cx: from.x, cy: from.y, r: 4 }));
    const first = ends[0] || rings[0];
    if (guess && first) {
      // The label sits on the first line, a little way from the part, and off the 3D tool bar.
      const avoid = [...stage.querySelectorAll('.model-tools-group:not([hidden])')]
        .map((node) => node.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0)
        .map((rect) => ({ left: rect.left - box.left, top: rect.top - box.top, right: rect.right - box.left, bottom: rect.bottom - box.top }));
      const at = labelSpot(from, first, avoid);
      nodes.push(svg('g', { class: 'source-guess-label', transform: `translate(${at.x} ${at.y})` },
        svg('rect', { x: -GUESS_LABEL_SIZE.width / 2, y: -11, width: GUESS_LABEL_SIZE.width, height: GUESS_LABEL_SIZE.height, rx: 10 }),
        svg('text', { x: 0, y: 3, 'text-anchor': 'middle' }, 'best guess')));
    }
    links.replaceChildren(...nodes);
  }

  async function show(item, source) {
    const key = `${item.kind}:${item.id}`;
    if (shown?.key === key) return;
    const record = source?.record || null;
    const summary = summaryOf(record);
    const { sheets, more } = sheetsOf(record);
    const sameSheets = shown && shown.sheetKey === sheets.map((s) => `${s.sheet}#${s.page}`).join('|');
    const run = ++generation;
    cancelAnimationFrame(frame);
    links.replaceChildren();
    shown = { key, item, record, tiles: [], partInputs: partInputs(record), sheetKey: sheets.map((s) => `${s.sheet}#${s.page}`).join('|') };

    const head = el('header', { class: 'source-head' },
      el('span', { class: `source-chip ${summary.tone}` }, summary.title),
      el('strong', { class: 'source-label' }, source?.label || item.id),
      summary.detail ? el('p', { class: 'source-detail' }, summary.detail) : null,
      shown.partInputs.length ? el('p', { class: 'source-detail' }, `Also used: ${shown.partInputs.map(labelOf).join(', ')}`) : null,
      more ? el('p', { class: 'source-detail' }, `${more} more sheet${more === 1 ? '' : 's'} not shown.`) : null);
    const body = el('div', { class: 'source-body', 'data-count': String(Math.max(1, sheets.length)) });
    peek.replaceChildren(head, body);
    peek.dataset.tone = summary.tone;
    peek.dataset.sheets = String(sheets.length);
    peek.hidden = false;
    if (!sheets.length) {
      // Unknown or no record: a note, no line. A guess from other parts only: lines to those parts.
      if (shown.partInputs.length) drawLinks();
      return;
    }

    const loading = Promise.all(sheets.map((sheet) => loadSheet(sheet.sheet, sheet.page).catch(() => null)));
    if (!sameSheets) await ruffle(body);
    const images = await loading;
    if (run !== generation) return;
    shown.tiles = sheets.map((sheet, i) => tileFor(sheet, images[i], summary.tone));
    body.replaceChildren(...shown.tiles.map((tile) => tile.node));
    if (!sameSheets && !prefersReducedMotion() && typeof body.animate === 'function') {
      body.animate([{ opacity: 0, transform: 'scale(0.97)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: 'ease-out' });
    }
    drawLinks();
  }

  return {
    show,
    close,
    get shownKey() {
      return shown?.key || null;
    },
    /** True when the pointer is on the view (the controller keeps it open then). */
    contains: (node) => peek.contains(node),
    element: peek,
  };
}

/**
 * When the source view shows: after a short hover on an item in 3D, or while a part is selected
 * (the selected part is keyboard reachable from the part list). `canShow()` is false when the
 * drawing pane is hidden.
 */
export function createSourceController({ view, sourceView, canShow }) {
  let hovered = null;
  let selected = null;
  let hoverTimer = 0;
  let leaveTimer = 0;
  let pointerOnPeek = false;

  sourceView.element.addEventListener('pointerenter', () => { pointerOnPeek = true; clearTimeout(leaveTimer); });
  sourceView.element.addEventListener('pointerleave', () => { pointerOnPeek = false; settle(); });

  function showItem(item) {
    if (!item || !canShow()) {
      sourceView.close();
      return;
    }
    sourceView.show(item, sourceOf(view(), item));
  }

  /** Show the hovered item, else the selected one, else nothing. */
  function settle() {
    clearTimeout(leaveTimer);
    if (hovered) return showItem(hovered);
    if (pointerOnPeek) return undefined;
    leaveTimer = setTimeout(() => showItem(selected), selected ? 0 : LEAVE_DELAY_MS);
    return undefined;
  }

  return {
    /** The item under the pointer in 3D ({ kind: 'part' | 'section', id }) or null. */
    hover(item) {
      const same = (item && hovered && item.kind === hovered.kind && item.id === hovered.id) || (!item && !hovered);
      if (same) return;
      clearTimeout(hoverTimer);
      if (!item) {
        hovered = null;
        settle();
        return;
      }
      clearTimeout(leaveTimer);
      hoverTimer = setTimeout(() => {
        hovered = item;
        settle();
      }, HOVER_DELAY_MS);
    },
    /** The selected part (null: none). */
    select(item) {
      selected = item;
      if (!hovered) showItem(selected);
    },
    /** Close until the next hover or selection (Escape). */
    dismiss() {
      clearTimeout(hoverTimer);
      hovered = null;
      sourceView.close();
    },
    /** The run changed: show the current item again from the new records. */
    refresh() {
      sourceView.close();
      showItem(hovered || selected);
    },
  };
}
