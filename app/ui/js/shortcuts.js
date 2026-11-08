// Keyboard shortcut sheet: "?" (or the palette) shows every key the app answers to.
// Keep this list in step with the keydown handlers in js/app.js, js/mark.js and js/live.js.

import { el } from './dom.js';

/** Platform modifier: ⌘ on macOS, Ctrl elsewhere. */
const MOD = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+';

const GROUPS = [
  ['Anywhere', [
    [`${MOD}K`, 'Go to a vessel, a station or an action'],
    [`${MOD}N`, 'New vessel from drawings'],
    [`${MOD},`, 'Settings'],
    [`${MOD}\\`, 'Show or hide the sidebar'],
    ['?', 'This list'],
  ]],
  ['Review a draft', [
    ['N', 'Next section to check'],
    ['A', 'Accept the guessed line'],
    ['O', 'Use the other line'],
    ['M', 'Mark the drawing and say what to fix'],
    ['[ ]', 'Previous or next section'],
  ]],
  ['Views', [
    [`${MOD}1`, 'Drawing only'],
    [`${MOD}2`, 'Drawing and model'],
    [`${MOD}3`, 'Model only'],
    ['R', 'Reset the 3D view'],
    ['+ − 0', 'Zoom the drawing in, out, to fit (click the drawing first)'],
    ['← → ↑ ↓', 'Pan the drawing (click the drawing first)'],
  ]],
  ['Review parts (Parts tab)', [
    ['A', 'Accept the part as a draft part'],
    ['M', 'Mark the part and say what to change'],
    ['N', 'Next part to review'],
  ]],
  ['New vessel (pages)', [
    ['[ ]', 'Previous or next page'],
    ['S', 'Skip or keep the page shown'],
  ]],
  ['Replay a run', [
    ['Space', 'Play or pause'],
    ['← →', 'Previous or next AI step'],
  ]],
];

export function createShortcutSheet() {
  const close = el('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Close');
  const dialog = el('dialog', { class: 'shortcuts', 'aria-labelledby': 'shortcuts-title' },
    el('h2', { id: 'shortcuts-title' }, 'Keyboard shortcuts'),
    el('div', { class: 'shortcut-groups' }, ...GROUPS.map(([title, keys]) => el('section', { class: 'shortcut-group' },
      el('h3', {}, title),
      el('dl', {}, ...keys.flatMap(([key, what]) => [
        el('dt', {}, ...key.split(' ').map((part) => el('kbd', { class: 'key-hint' }, part))),
        el('dd', {}, what),
      ]))))),
    el('div', { class: 'shortcuts-actions' }, close));
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  document.body.append(dialog);
  return {
    open() {
      if (!dialog.open) dialog.showModal();
      close.focus();
    },
  };
}
