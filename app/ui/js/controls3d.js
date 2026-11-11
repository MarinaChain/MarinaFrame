// Controls over the 3D view: the tool bar (top left) and the section cut panel. Plain buttons,
// radio inputs and a range slider, so every control works from the keyboard and has a name.

import { el, icon } from './dom.js';
import { tipAttributes } from './tooltip.js';
import { CUT_AXES, cutLabel } from './reference3d.js';

/**
 * How many tool bar groups stay in the one row: the leading groups whose widths, with the gaps
 * between them, fit in `available` px. When not all fit, the row also keeps room for the More
 * button (`moreWidth`). The first group always stays. Hidden groups have width 0 and add no gap.
 */
export function splitToolbar(widths, available, { gap = 6, moreWidth = 36 } = {}) {
  const used = (count) => {
    const shown = widths.slice(0, count).filter((w) => w > 0);
    return shown.reduce((sum, w) => sum + w, 0) + gap * Math.max(0, shown.length - 1);
  };
  if (used(widths.length) <= available) return widths.length;
  let keep = widths.length - 1;
  while (keep > 1 && used(keep) + gap + moreWidth > available) keep -= 1;
  return keep;
}

/**
 * The tool bar: one row of button groups over the 3D view. `add(label, ...nodes)` appends a
 * group. `fit(available)` keeps the row on one line: the groups that do not fit move, in order,
 * into the More menu at the end of the row (the same buttons, so keys and state carry over).
 */
export function createToolbar() {
  const element = el('div', { class: 'model-tools', role: 'group', 'aria-label': '3D view tools' });
  const groups = [];
  const menuId = `model-tools-more-${Math.random().toString(36).slice(2, 8)}`;
  const menu = el('div', { class: 'model-tools-menu', id: menuId, role: 'group', 'aria-label': 'More 3D view tools', hidden: true });
  const moreButton = toolButton({ iconName: 'more', label: 'More tools', onClick: () => setMenu(menu.hidden) });
  moreButton.setAttribute('aria-expanded', 'false');
  moreButton.setAttribute('aria-controls', menuId);
  const more = el('div', { class: 'model-tools-group model-tools-more', hidden: true }, moreButton, menu);
  element.append(more);
  menu.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    setMenu(false);
    moreButton.focus();
  });
  element.addEventListener('focusout', (event) => {
    if (!more.contains(event.relatedTarget)) setMenu(false);
  });

  function setMenu(open) {
    menu.hidden = !open;
    moreButton.setAttribute('aria-expanded', String(open));
    moreButton.setAttribute('aria-pressed', String(open));
  }

  // A group shown or hidden later (Parts and spaces) changes the row: fit it again.
  let lastAvailable = null;
  const refit = new MutationObserver(() => { if (lastAvailable !== null) fit(lastAvailable); });

  function fit(available) {
    lastAvailable = available;
    refit.disconnect();
    for (const group of groups) more.before(group);
    more.hidden = true;
    const gap = parseFloat(getComputedStyle(element).columnGap) || 6;
    const widths = groups.map((group) => (group.hidden ? 0 : group.getBoundingClientRect().width));
    const keep = splitToolbar(widths, available, { gap, moreWidth: 36 });
    const moved = groups.slice(keep);
    menu.replaceChildren(...moved);
    more.hidden = !moved.some((group) => !group.hidden);
    if (more.hidden) setMenu(false);
    for (const group of groups) refit.observe(group, { attributes: true, attributeFilter: ['hidden'] });
  }

  return {
    element,
    add(label, ...nodes) {
      const group = el('div', { class: 'model-tools-group', role: 'group', 'aria-label': label }, ...nodes);
      groups.push(group);
      more.before(group);
      return group;
    },
    fit,
  };
}

/**
 * A tool bar button: an icon or short text, a name, a tooltip title with its key (tooltip.js),
 * an optional tooltip detail, and a click action. `short`: a narrow pane shows the icon only.
 */
export function toolButton({ text, iconName = null, label, keyHint = null, detail = null, onClick, pressed = null, short = false }) {
  const tip = tipAttributes(keyHint ? `${label} (${keyHint})` : label, detail, { label: false });
  const button = el('button', {
    class: 'model-tool',
    type: 'button',
    'aria-label': label,
    ...tip.attrs,
    'aria-pressed': pressed === null ? null : String(pressed),
    'data-short': short && iconName ? '' : null,
    onclick: onClick,
  }, iconName ? icon(iconName) : null, text ? el('span', { class: 'model-tool-text' }, text) : null, tip.describer);
  return button;
}

/**
 * The section cut panel. `onChange({ axis, value, flipped })` applies a cut (axis null: off);
 * `onCutAtSelection()` cuts at the frame of the selected part. `setRanges({ x, y, z })` takes
 * [min, max, step] per axis (metres) and the hull reference, for the frame readout.
 */
export function createCutPanel({ onChange, onCutAtSelection, onClose }) {
  let state = { axis: null, value: 0, flipped: false };
  let ranges = { x: [0, 1, 0.01], y: [-1, 1, 0.01], z: [0, 1, 0.01] };
  let reference = null;
  /** The value each axis had last, so switching between axes keeps each place. */
  const lastValue = {};
  const id = `cut-${Math.random().toString(36).slice(2, 8)}`;

  // A segmented control of native radio inputs (arrow keys move between them).
  const radios = Object.entries(CUT_AXES).map(([axis, spec]) => el('label', { class: 'model-cut-choice', 'data-tip-title': `${spec.name} cut (${axis})` },
    el('input', { type: 'radio', class: 'visually-hidden', name: `${id}-axis`, value: axis, 'aria-label': `${spec.name} cut`, onchange: () => choose(axis) }),
    el('span', { 'aria-hidden': 'true' }, spec.short)));
  const slider = el('input', { type: 'range', class: 'model-cut-slider', 'aria-label': 'Cut position', oninput: () => move(Number(slider.value)) });
  const readout = el('output', { class: 'model-cut-readout' });
  const flip = toolButton({ iconName: 'flip', label: 'Flip the kept side', pressed: false, onClick: () => apply({ ...state, flipped: !state.flipped }) });
  const atSelection = el('button', { type: 'button', class: 'model-tool', hidden: true, onclick: () => onCutAtSelection() });
  const close = toolButton({ iconName: 'close', label: 'End the section cut', keyHint: 'Esc', onClick: () => onClose() });
  const element = el('div', { class: 'model-cut', id, role: 'group', 'aria-label': 'Section cut', hidden: true },
    el('div', { class: 'model-cut-axes', role: 'radiogroup', 'aria-label': 'Cut plane' }, ...radios),
    slider, readout, flip, atSelection, close);

  function defaultValue(axis) {
    if (lastValue[axis] !== undefined) return lastValue[axis];
    const [min, max] = ranges[axis];
    if (axis === 'y') return Math.min(max, Math.max(min, 0));
    if (axis === 'z' && reference) return reference.designWaterlineZ.value;
    return (min + max) / 2;
  }

  function choose(axis) {
    apply({ ...state, axis, value: axis ? defaultValue(axis) : state.value });
  }

  function move(value) {
    apply({ ...state, value });
  }

  function apply(next) {
    state = next;
    if (state.axis) lastValue[state.axis] = state.value;
    render();
    onChange({ ...state });
  }

  function render() {
    for (const label of radios) {
      const input = label.querySelector('input');
      input.checked = (input.value || null) === state.axis;
    }
    const on = Boolean(state.axis);
    slider.disabled = !on;
    flip.setAttribute('aria-pressed', String(state.flipped));
    if (on) {
      const [min, max, step] = ranges[state.axis];
      slider.min = String(min);
      slider.max = String(max);
      slider.step = String(step);
      slider.value = String(state.value);
      const text = cutLabel(state.axis, state.value, reference);
      slider.setAttribute('aria-valuetext', text);
      readout.textContent = text;
    } else {
      readout.textContent = '';
      slider.removeAttribute('aria-valuetext');
    }
  }
  render();

  return {
    element,
    id,
    get state() {
      return { ...state };
    },
    setRanges(next, nextReference) {
      ranges = next;
      reference = nextReference;
      for (const key of Object.keys(lastValue)) delete lastValue[key];
      render();
    },
    /** Set the cut from outside (a quick cut or a key), as if chosen here. */
    set(next) {
      const axis = next.axis === undefined ? state.axis : next.axis;
      // A new axis with no value starts at that axis's last or default place.
      const value = next.value ?? (axis && axis !== state.axis ? defaultValue(axis) : state.value);
      apply({ ...state, ...next, axis, value });
    },
    /** Offer a quick cut at a selection (a frame label such as "Fr 12"), or hide it with null. */
    setSelection(frame) {
      atSelection.hidden = !frame;
      if (!frame) return;
      atSelection.textContent = `At ${frame}`;
      atSelection.dataset.tipTitle = `Cut at ${frame}, the frame of the selected part`;
      atSelection.setAttribute('aria-label', `Cut at ${frame}, the frame of the selected part`);
    },
  };
}
