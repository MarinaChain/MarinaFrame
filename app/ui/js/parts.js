// Parts tab (whole vessel, APP_SPEC "Whole-vessel parts"): the component tree of a run, a
// profile and a plan sketch of the parts' boxes, and each part's values with the source of
// every value (read from the drawing, read by the AI, or guessed). A part is a draft like the
// hull; the person can accept it as a draft part. Nothing here is "approved".

import { el, svg, icon, fill } from './dom.js';

/** Tree groups (ship-cad ops) in the order a naval architect reads a general arrangement. */
const GROUPS = [
  ['hull', 'Hull'],
  ['deck', 'Decks'],
  ['deckhouse', 'Deckhouses'],
  ['bulwark', 'Bulwarks'],
  ['appendage', 'Appendages'],
  ['other', 'Other'],
];
const KNOWN_OPS = new Set(GROUPS.map(([op]) => op));
const SOURCE_WORD = { traced: 'Read', ai_inferred: 'AI read', guessed: 'Guessed' };
const SOURCE_TONE = { traced: '', ai_inferred: 'ai', guessed: 'draft' };
/** Sketch size in SVG units (it scales to the panel). */
const SKETCH = { width: 900, height: 160, pad: 14 };

/** One state word per part: the review wins, then what the build could do. */
function partState(part) {
  if (part.review === 'accepted') return { word: 'Accepted', tone: 'brand', title: 'You accepted this part as a draft part.' };
  if (!part.built) return { word: 'Not built', tone: 'warn', title: part.reason };
  if (part.status === 'draft_guess') return { word: 'Guessed', tone: 'draft', title: 'One or more values were guessed. Check them.' };
  return { word: 'To check', tone: '', title: 'Every value was read from the drawing. Check what the part is.' };
}

function chip(text, tone, title) {
  return el('span', { class: 'badge badge-small', dataset: { tone }, title }, el('span', { class: 'badge-text' }, text));
}

/**
 * `review(id, decision)` saves a review (review_component) and resolves when done;
 * `showIn3d(part)` switches to the Run tab with the part outlined.
 */
export function createParts({ host, review, showIn3d }) {
  let parts = [];
  let selectedId = null;
  let busy = false;

  function sketch(vertical, title) {
    const built = parts.filter((p) => p.bbox_m);
    if (!built.length) return null;
    const lo = [0, 1, 2].map((k) => Math.min(...built.map((p) => p.bbox_m.min[k])));
    const hi = [0, 1, 2].map((k) => Math.max(...built.map((p) => p.bbox_m.max[k])));
    const scale = Math.min((SKETCH.width - 2 * SKETCH.pad) / (hi[0] - lo[0] || 1), (SKETCH.height - 2 * SKETCH.pad) / (hi[vertical] - lo[vertical] || 1));
    const px = (x) => SKETCH.pad + (x - lo[0]) * scale;
    const py = (v) => SKETCH.height - SKETCH.pad - (v - lo[vertical]) * scale;
    // The selected part is drawn last, on top.
    const order = [...built].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId));
    return el('figure', { class: 'parts-sketch' },
      el('figcaption', {}, title),
      svg('svg', { viewBox: `0 0 ${SKETCH.width} ${SKETCH.height}`, role: 'img', 'aria-label': `${title} sketch of the parts` },
        ...order.map((p) => {
          const { min, max } = p.bbox_m;
          const rect = svg('rect', {
            class: `parts-box${p.id === selectedId ? ' selected' : ''}`,
            'data-status': p.status,
            x: px(min[0]).toFixed(1), y: py(max[vertical]).toFixed(1),
            width: Math.max(1, (max[0] - min[0]) * scale).toFixed(1),
            height: Math.max(1, (max[vertical] - min[vertical]) * scale).toFixed(1),
          });
          rect.append(svg('title', {}, p.label));
          rect.addEventListener('click', () => select(p.id));
          return rect;
        })));
  }

  function treeRow(part) {
    const state = partState(part);
    return el('li', {},
      el('button', { class: 'parts-row', type: 'button', 'aria-pressed': String(part.id === selectedId), onclick: () => select(part.id) },
        el('span', { class: 'parts-name' }, part.label),
        chip(state.word, state.tone, state.title)));
  }

  async function decide(part, decision) {
    if (busy) return;
    busy = true;
    render();
    try {
      try {
        await review(part.id, decision);
      } catch {
        return; // the app showed the error; the part keeps its review
      }
      part.review = decision;
      // After an accept, the next part with guesses opens: a review is a short run of keys.
      if (decision === 'accepted') {
        const next = parts.find((p) => p.review !== 'accepted' && p.built && p.status === 'draft_guess');
        if (next) selectedId = next.id;
      }
    } finally {
      busy = false;
      render();
    }
  }

  function actions(part) {
    const accepted = part.review === 'accepted';
    return el('div', { class: 'decision-bar' },
      part.built ? el('button', {
        class: accepted ? 'btn' : 'btn btn-primary',
        type: 'button',
        disabled: busy,
        title: accepted ? 'Open this part again for review' : 'Accept this part as a draft part (A)',
        onclick: () => decide(part, accepted ? 'open' : 'accepted'),
      }, accepted ? 'Reopen' : 'Accept', accepted ? null : el('kbd', { class: 'key-hint' }, 'A')) : null,
      part.bbox_m ? el('button', { class: 'btn', type: 'button', onclick: () => showIn3d(part) }, icon('cube'), 'Show in 3D') : null);
  }

  function detail(part) {
    if (!part) return el('p', { class: 'panel-empty' }, 'Pick a part.');
    const state = partState(part);
    const guessed = part.arguments.filter((a) => a.source === 'guessed').length;
    const box = part.bbox_m;
    return el('section', { class: 'parts-detail', 'aria-labelledby': 'parts-detail-title' },
      el('header', { class: 'parts-detail-head' },
        el('h2', { id: 'parts-detail-title' }, part.label),
        chip(state.word, state.tone, state.title),
        part.view ? chip(`From the ${part.view}`, '', 'The drawing view this part was read from') : null),
      actions(part),
      el('p', { class: 'parts-reason' }, part.reason),
      box ? el('p', { class: 'parts-box-line' },
        `x ${box.min[0].toFixed(2)} to ${box.max[0].toFixed(2)} m · breadth ${(box.max[1] - box.min[1]).toFixed(2)} m · `
        + `z ${box.min[2].toFixed(2)} to ${box.max[2].toFixed(2)} m`
        + (part.volume_m3 !== null && part.volume_m3 !== undefined ? ` · ${part.volume_m3.toFixed(1)} m³` : '')) : null,
      part.arguments.length
        ? el('table', { class: 'parts-args' },
          el('caption', { class: 'visually-hidden' }, `Values of ${part.label}`),
          el('thead', {}, el('tr', {},
            el('th', { scope: 'col' }, 'Item'), el('th', { scope: 'col' }, 'Value'), el('th', { scope: 'col' }, 'Source'), el('th', { scope: 'col' }, 'Basis'))),
          el('tbody', {}, ...part.arguments.map((a) => el('tr', { dataset: { source: a.source } },
            el('th', { scope: 'row' }, a.name),
            el('td', { class: 'parts-value' }, a.value || '—'),
            el('td', {}, chip(SOURCE_WORD[a.source] || a.source, SOURCE_TONE[a.source] || '', a.basis || '')),
            el('td', { class: 'parts-basis' }, a.basis || '')))))
        : null,
      guessed ? el('p', { class: 'parts-note' }, icon('warn'), `${guessed} ${guessed === 1 ? 'value is' : 'values are'} guessed. Check them before you use this part.`) : null);
  }

  function render() {
    const built = parts.filter((p) => p.built).length;
    const accepted = parts.filter((p) => p.review === 'accepted').length;
    const selected = parts.find((p) => p.id === selectedId) || null;
    fill(host, el('div', { class: 'page-body parts-page' },
      el('header', { class: 'page-head' },
        el('h1', { id: 'parts-title' }, 'Parts'),
        el('span', { class: 'page-head-meta' }, `${built} of ${parts.length} built · ${accepted} accepted`)),
      el('div', { class: 'parts-layout' },
        el('nav', { class: 'parts-tree', 'aria-label': 'Parts' },
          ...GROUPS.map(([op, title]) => {
            const items = parts.filter((p) => (KNOWN_OPS.has(p.op) ? p.op : 'other') === op);
            return items.length ? el('section', { class: 'parts-group' }, el('h2', {}, title), el('ul', {}, ...items.map(treeRow))) : null;
          })),
        el('div', { class: 'parts-main' },
          el('div', { class: 'parts-sketches' }, sketch(2, 'Profile'), sketch(1, 'Plan')),
          detail(selected)))));
  }

  function select(id) {
    selectedId = id;
    render();
  }

  return {
    /** Show the parts of a TaskView (`view.components`). */
    show(view) {
      parts = view?.components || [];
      if (!parts.some((p) => p.id === selectedId)) {
        selectedId = (parts.find((p) => p.built && p.status === 'draft_guess') || parts[0])?.id || null;
      }
      render();
    },
    /** Key A on the Parts tab: accept the selected part. Returns true when it acted. */
    acceptSelected() {
      const part = parts.find((p) => p.id === selectedId);
      if (!part?.built || part.review === 'accepted' || busy) return false;
      decide(part, 'accepted');
      return true;
    },
  };
}
