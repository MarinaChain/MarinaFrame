// The part list of the 3D view: a search box, Show all, and one row per part (name, Hide,
// Isolate). Rows are built once for a model and updated in place, so a click never loses the
// keyboard focus. The rules for what hide and isolate do are in visibility3d.js.

import { el, icon } from './dom.js';
import { tipAttributes } from './tooltip.js';
import { steelToken, tankToken } from './tanks.js';
import { filterParts, kindWord, PART_STATES } from './visibility3d.js';

/** The design token whose colour is a part's swatch (tank content, steel group, else the hull). */
export function swatchToken(entry) {
  if (entry.kind === 'tank') return tankToken(entry.contentClass);
  if (entry.kind === 'steel') return steelToken(entry.group);
  return '--model-hull';
}

function iconButton({ iconName, label, detail, onClick, pressed = null }) {
  const tip = tipAttributes(label, detail);
  return el('button', {
    class: 'model-part-tool', type: 'button', ...tip.attrs,
    'aria-pressed': pressed === null ? null : String(pressed), onclick: onClick,
  }, icon(iconName), tip.describer);
}

/**
 * `onHide(id)`, `onIsolate(id)` and `onShowAll()` change what shows; `onPick(id)` selects a part
 * (its fact card opens). The panel starts hidden.
 */
export function createPartsPanel({ onHide, onIsolate, onShowAll, onPick }) {
  const id = `parts-${Math.random().toString(36).slice(2, 8)}`;
  /** Row record per part id: { entry, row, pick, hide, isolate }. */
  let rows = new Map();
  let query = '';
  let ordered = [];

  const search = el('input', {
    type: 'search', class: 'model-part-search', placeholder: 'Search', 'aria-label': 'Search parts', autocomplete: 'off',
    oninput: () => { query = search.value; applyFilter(); },
  });
  const showAllTip = tipAttributes('Show all', 'End every Hide and Isolate, and show the tanks and steel layers.', { label: false });
  const showAll = el('button', { class: 'model-tool', type: 'button', ...showAllTip.attrs, 'aria-label': 'Show all', disabled: true, onclick: () => onShowAll() },
    icon('eye'), el('span', {}, 'Show all'), showAllTip.describer);
  const list = el('ul', { class: 'model-part-list', 'aria-label': 'Parts' });
  const none = el('p', { class: 'model-part-none', hidden: true }, 'No part matches.');
  const summary = el('p', { class: 'model-part-summary', role: 'status' });
  const element = el('div', { class: 'model-panel-body', role: 'group', 'aria-label': 'Parts', hidden: true },
    el('div', { class: 'model-panel-head' }, search, showAll), list, none, summary);
  // Escape in the search box clears it first; the 3D view's own keys stay out of a text box.
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && search.value) {
      search.value = '';
      query = '';
      applyFilter();
      event.stopPropagation();
    }
  });

  function applyFilter() {
    const keep = new Set(filterParts(ordered, query).map((entry) => entry.id));
    for (const [partId, record] of rows) record.row.hidden = !keep.has(partId);
    none.hidden = keep.size > 0 || !ordered.length;
  }

  return {
    element,
    id,
    /** Build the rows for a model: entries from describeParts (visibility3d.js). */
    setParts(entries) {
      ordered = entries;
      rows = new Map();
      list.replaceChildren();
      for (const entry of entries) {
        const swatch = el('span', { class: 'model-swatch', style: { background: `var(${swatchToken(entry)})` }, 'aria-hidden': 'true' });
        const pick = el('button', { class: 'model-part-main', type: 'button', onclick: () => onPick(entry.id) },
          swatch, el('span', { class: 'model-part-name' }, entry.name),
          entry.detail || kindWord(entry.kind).toLowerCase() !== entry.name.toLowerCase()
            ? el('span', { class: 'model-part-detail' }, entry.detail || kindWord(entry.kind)) : null);
        const hide = iconButton({ iconName: 'hide', label: 'Hide', detail: 'Take this part out of the view. It cannot be picked.', pressed: false, onClick: () => onHide(entry.id) });
        const isolate = iconButton({ iconName: 'isolate', label: 'Isolate', detail: 'Keep this part and make every other part faint.', pressed: false, onClick: () => onIsolate(entry.id) });
        hide.setAttribute('aria-label', `Hide ${entry.name}`);
        isolate.setAttribute('aria-label', `Isolate ${entry.name}`);
        const row = el('li', { class: 'model-part', dataset: { state: PART_STATES.shown, kind: entry.kind } }, pick, hide, isolate);
        rows.set(entry.id, { entry, row, pick, hide, isolate });
        list.append(row);
      }
      applyFilter();
    },
    /** Show the state of every row: `stateOf(id)`, the isolated id and the picked id (or null). */
    setStates(stateOf, isolatedId, pickedId) {
      let hidden = 0;
      for (const [partId, { row, pick, hide, isolate }] of rows) {
        const state = stateOf(partId);
        if (state === PART_STATES.hidden) hidden += 1;
        row.dataset.state = state;
        hide.setAttribute('aria-pressed', String(state === PART_STATES.hidden));
        isolate.setAttribute('aria-pressed', String(partId === isolatedId));
        pick.setAttribute('aria-current', partId === pickedId ? 'true' : 'false');
        row.classList.toggle('is-picked', partId === pickedId);
      }
      showAll.disabled = false;
      const words = [];
      if (hidden) words.push(`${hidden} hidden`);
      if (isolatedId !== null && rows.has(isolatedId)) words.push(`${rows.get(isolatedId).entry.name} isolated`);
      summary.textContent = words.join(' · ');
    },
    /** Scroll a part's row into view (a pick in 3D). */
    reveal(partId) {
      const record = rows.get(partId);
      if (record && !record.row.hidden) record.row.scrollIntoView({ block: 'nearest' });
    },
    focusSearch() {
      search.focus();
    },
  };
}
