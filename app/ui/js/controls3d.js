// Controls over the 3D view: the tool bar (top left) and the section cut panel. Plain buttons,
// radio inputs and a range slider, so every control works from the keyboard and has a name.

import { el, icon } from './dom.js';
import { CUT_AXES, cutLabel } from './reference3d.js';

/** The tool bar: a row of button groups. `add(...nodes)` appends a group. */
export function createToolbar() {
  const element = el('div', { class: 'model-tools', role: 'group', 'aria-label': '3D view tools' });
  return {
    element,
    add(label, ...nodes) {
      const group = el('div', { class: 'model-tools-group', role: 'group', 'aria-label': label }, ...nodes);
      element.append(group);
      return group;
    },
  };
}

/** A tool bar button: an icon or short text, a name, a title with its key, and a click action. */
export function toolButton({ text, iconName = null, label, keyHint = null, onClick, pressed = null }) {
  const button = el('button', {
    class: 'model-tool',
    type: 'button',
    'aria-label': label,
    title: keyHint ? `${label} (${keyHint})` : label,
    'aria-pressed': pressed === null ? null : String(pressed),
    onclick: onClick,
  }, iconName ? icon(iconName) : null, text ? el('span', {}, text) : null);
  return button;
}

/**
 * The section cut panel. `onChange({ axis, value, flipped })` applies a cut (axis null: off);
 * `onCutAtSelection()` cuts at the frame of the selected part. `setRanges({ x, y, z })` takes
 * [min, max, step] per axis (metres) and the hull reference, for the frame readout.
 */
export function createCutPanel({ onChange, onCutAtSelection }) {
  let state = { axis: null, value: 0, flipped: false };
  let ranges = { x: [0, 1, 0.01], y: [-1, 1, 0.01], z: [0, 1, 0.01] };
  let reference = null;
  /** The value each axis had last, so switching between axes keeps each place. */
  const lastValue = {};
  const id = `cut-${Math.random().toString(36).slice(2, 8)}`;

  const radios = [['', 'Off'], ...Object.entries(CUT_AXES).map(([axis, spec]) => [axis, `${spec.name} (${axis})`])]
    .map(([axis, text]) => el('label', { class: 'model-cut-choice' },
      el('input', { type: 'radio', name: `${id}-axis`, value: axis, onchange: () => choose(axis || null) }), text));
  const slider = el('input', { type: 'range', class: 'model-cut-slider', 'aria-label': 'Cut position', oninput: () => move(Number(slider.value)) });
  const readout = el('output', { class: 'model-cut-readout', 'aria-live': 'polite' });
  const flip = el('button', { type: 'button', class: 'btn btn-ghost btn-small', 'aria-pressed': 'false', onclick: () => apply({ ...state, flipped: !state.flipped }) }, 'Flip side');
  const atSelection = el('button', { type: 'button', class: 'btn btn-ghost btn-small', hidden: true, onclick: () => onCutAtSelection() }, 'Cut at selection');
  const element = el('div', { class: 'model-cut', id, role: 'group', 'aria-label': 'Section cut', hidden: true },
    el('fieldset', { class: 'model-cut-axes' }, el('legend', {}, 'Section cut'), ...radios),
    el('div', { class: 'model-cut-row' }, slider, readout),
    el('div', { class: 'model-cut-row' }, flip, atSelection));

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
    flip.disabled = !on;
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
      readout.textContent = 'No cut';
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
    /** Offer "Cut at …" for a selection (text such as "Cut at Fr 12"), or hide it with null. */
    setSelection(text) {
      atSelection.hidden = !text;
      if (text) atSelection.textContent = text;
    },
  };
}
