// The space list of the 3D view: one row per space (a tank, or a box between two bulkheads), and,
// when the steel model has two or more bulkheads, a row to add a box between two of them. A click
// on a space clips the model to it (model3d.js); "Exit space" ends it.

import { el, icon } from './dom.js';
import { tipAttributes } from './tooltip.js';

/**
 * `onEnter(id)` clips to a space, `onExit()` ends it, `onAdd(fromX, toX)` adds a box between two
 * bulkheads, `onRemove(id)` removes an added box.
 */
export function createSpacesPanel({ onEnter, onExit, onAdd, onRemove }) {
  /** Row record per space id: { space, row, main }. */
  let rows = new Map();
  let choices = [];
  const list = el('ul', { class: 'model-part-list', 'aria-label': 'Spaces' });
  const noneTitle = el('strong', {}, 'No spaces yet.');
  const noneText = el('span', {}, 'A space comes from each built tank.');
  const none = el('p', { class: 'model-part-none model-space-none' }, noneTitle, noneText);
  const exitTip = tipAttributes('Exit space', 'Show the whole model again and return the camera.', { label: false });
  const exit = el('button', { class: 'model-tool', type: 'button', ...exitTip.attrs, 'aria-label': 'Exit space', disabled: true, onclick: () => onExit() },
    icon('close'), el('span', {}, 'Exit space'), exitTip.describer);
  const from = el('select', { class: 'model-space-select', 'aria-label': 'From bulkhead' });
  const to = el('select', { class: 'model-space-select', 'aria-label': 'To bulkhead' });
  const addTip = tipAttributes('Add a space', 'A box between the two bulkheads, over the full beam and depth.', { label: false });
  const add = el('button', { class: 'model-tool', type: 'button', ...addTip.attrs, 'aria-label': 'Add a space between the two bulkheads', onclick: () => {
    const a = choices[Number(from.value)];
    const b = choices[Number(to.value)];
    if (a && b) onAdd(a, b);
  } }, icon('plus'), el('span', {}, 'Add'), addTip.describer);
  const builder = el('div', { class: 'model-space-builder', role: 'group', 'aria-label': 'Space between bulkheads', hidden: true },
    el('span', { class: 'model-space-label' }, 'Between'), from, el('span', { class: 'model-space-label' }, 'and'), to, add);
  const element = el('div', { class: 'model-panel-body', role: 'group', 'aria-label': 'Spaces', hidden: true },
    el('div', { class: 'model-panel-head' }, exit), list, none, builder);

  function fillSelect(select, selectedIndex) {
    select.replaceChildren(...choices.map((choice, index) => el('option', { value: String(index), selected: index === selectedIndex ? true : null }, choice.label)));
  }

  return {
    element,
    /** Build the rows: [{ id, name, detail, kind, custom }]. */
    setSpaces(spaces) {
      rows = new Map();
      list.replaceChildren();
      for (const space of spaces) {
        const main = el('button', { class: 'model-part-main', type: 'button', 'aria-pressed': 'false', onclick: () => onEnter(space.id) },
          el('span', { class: 'model-space-glyph', 'aria-hidden': 'true' }, icon('space')),
          el('span', { class: 'model-part-name' }, space.name), el('span', { class: 'model-part-detail' }, space.detail));
        const remove = space.custom
          ? el('button', { class: 'model-part-tool', type: 'button', 'aria-label': `Remove ${space.name}`, onclick: () => onRemove(space.id), ...tipAttributes('Remove').attrs }, icon('close'))
          : null;
        const row = el('li', { class: 'model-part' }, main, remove);
        rows.set(space.id, { space, row, main });
        list.append(row);
      }
      none.hidden = spaces.length > 0;
    },
    /** Why the list is empty: { title, text } (spaces3d.js spacesEmptyReason). */
    setEmptyReason({ title, text }) {
      noneTitle.textContent = title;
      noneText.textContent = text;
    },
    /** The bulkheads of the steel model: [{ x, label }]; fewer than two hides the row to add a box. */
    setBulkheads(next) {
      choices = next;
      builder.hidden = next.length < 2;
      fillSelect(from, 0);
      fillSelect(to, Math.min(1, next.length - 1));
    },
    /** Mark the space the model is clipped to (an id, or null). */
    setActive(activeId) {
      for (const [id, { row, main }] of rows) {
        main.setAttribute('aria-pressed', String(id === activeId));
        row.classList.toggle('is-picked', id === activeId);
      }
      exit.disabled = activeId === null;
    },
  };
}
