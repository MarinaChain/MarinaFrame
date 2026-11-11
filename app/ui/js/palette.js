// Command palette (⌘K / Ctrl+K): type a few letters to go to a place, a vessel or a station,
// or to run an action. The app gives the list of commands each time the palette opens, so
// the list always fits the screen the person is on.

import { el, fill } from './dom.js';

/** Most rows shown at once; more letters narrow the list. */
const MAX_ROWS = 12;

/** True when every word of the query starts a word of the text, or is inside it. */
function matches(text, query) {
  const haystack = text.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
}

/**
 * `commands()` returns `{ group, title, hint?, keys?, run }[]` for the current screen.
 */
export function createPalette({ commands }) {
  let all = [];
  let shown = [];
  let active = 0;

  const input = el('input', {
    class: 'palette-input',
    type: 'text',
    placeholder: 'Go to a vessel, a station or an action…',
    'aria-label': 'Command',
    'aria-controls': 'palette-list',
    autocomplete: 'off',
    spellcheck: 'false',
  });
  // Focusable so the list can also scroll from the keyboard; arrows in the input move the choice.
  const list = el('ul', { class: 'palette-list', id: 'palette-list', role: 'listbox', 'aria-label': 'Commands', tabindex: '0' });
  const dialog = el('dialog', { class: 'palette', 'aria-label': 'Command palette' },
    input, list,
    el('p', { class: 'palette-foot' }, '↑↓ to move · Enter to run · Esc to close'));
  document.body.append(dialog);

  function render() {
    shown = all.filter((c) => matches(`${c.group} ${c.title} ${c.hint || ''}`, input.value)).slice(0, MAX_ROWS);
    active = Math.min(active, Math.max(0, shown.length - 1));
    if (!shown.length) {
      fill(list, el('li', { class: 'palette-empty' }, 'Nothing matches.'));
      return;
    }
    let lastGroup = null;
    const rows = [];
    shown.forEach((command, index) => {
      if (command.group !== lastGroup) {
        rows.push(el('li', { class: 'palette-group', role: 'presentation' }, command.group));
        lastGroup = command.group;
      }
      rows.push(el('li', {
        class: 'palette-row',
        role: 'option',
        id: `palette-${index}`,
        'aria-selected': String(index === active),
        onmousemove: () => { if (active !== index) { active = index; render(); } },
        onclick: () => run(index),
      },
      el('span', { class: 'palette-title' }, command.title),
      command.hint ? el('span', { class: 'palette-hint' }, command.hint) : null,
      command.keys ? el('kbd', { class: 'key-hint' }, command.keys) : null));
    });
    fill(list, ...rows);
    input.setAttribute('aria-activedescendant', `palette-${active}`);
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }

  function run(index) {
    const command = shown[index];
    if (!command) return;
    dialog.close();
    command.run();
  }

  input.addEventListener('input', () => { active = 0; render(); });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') active = Math.min(shown.length - 1, active + 1);
    else if (event.key === 'ArrowUp') active = Math.max(0, active - 1);
    else if (event.key === 'Enter') { event.preventDefault(); run(active); return; }
    else return;
    event.preventDefault();
    render();
  });
  // A click on the backdrop (outside the box) closes the palette.
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });

  return {
    open() {
      all = commands();
      active = 0;
      input.value = '';
      render();
      if (!dialog.open) dialog.showModal();
      input.focus();
    },
    toggle() {
      if (dialog.open) dialog.close();
      else this.open();
    },
  };
}
