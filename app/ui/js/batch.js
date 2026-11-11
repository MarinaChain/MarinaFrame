// Batch queue (design plan M6). A drop of a folder or of several drawing sets opens a sheet
// that lists the sets found (plan_batch); "Start N runs" queues them (queue_batch). The
// backend starts waiting sets while fewer runs than the native slot limit are running; the
// Queue page shows the waiting sets in order, above the running and ready runs.

import { el, fill, icon } from './dom.js';
import * as fmt from './format.js';

const STATE_TEXT = {
  waiting: { word: 'Waiting', tone: '' },
  starting: { word: 'Starting', tone: 'brand' },
  failed: { word: 'Not started', tone: 'warn' },
};

/** The short line above the waiting sets: how many run, the limit, and what holds them. */
export function slotLine(queue) {
  const inUse = Math.min(queue.running, queue.slots);
  return `${inUse} of ${queue.slots} run slots in use. The next set starts when a slot is free.`;
}

export function createBatch({ invoke, showError, onQueued, aiActive = () => true }) {
  let plan = null;
  const chosen = new Set();
  let busy = false;

  const list = el('ul', { class: 'batch-sets', 'aria-label': 'Drawing sets found' });
  const skipped = el('div', { class: 'batch-skipped' });
  // A set without a spec needs the AI: with AI drafting off or no key the sets only wait.
  const aiNote = el('p', { class: 'batch-ai-note', role: 'note' });
  const startButton = el('button', { class: 'btn btn-primary', type: 'button', onclick: () => queueChosen() }, 'Start runs');
  const dialog = el('dialog', { class: 'batch-sheet', 'aria-labelledby': 'batch-title' },
    el('h2', { id: 'batch-title' }, 'New vessels'),
    el('p', { class: 'batch-intro' }, 'Each set becomes one run with the views the app finds. Runs start as slots free up; the rest wait in the Queue.'),
    aiNote,
    list,
    skipped,
    el('div', { class: 'batch-actions' },
      el('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Cancel'),
      startButton));
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  document.body.append(dialog);

  function setRow(set, index) {
    const id = `batch-set-${index}`;
    const files = set.files.map((f) => f.split(/[\\/]/).pop());
    return el('li', { class: 'batch-set' },
      el('input', {
        type: 'checkbox', id, checked: chosen.has(index),
        onchange: (event) => { if (event.target.checked) chosen.add(index); else chosen.delete(index); render(); },
      }),
      el('label', { for: id, class: 'batch-set-text' },
        el('span', { class: 'batch-set-name' }, set.name),
        el('span', { class: 'batch-set-files', title: files.join('\n') },
          `${fmt.plural(set.files.length, 'sheet file')}: ${files.slice(0, 3).join(', ')}${files.length > 3 ? ', …' : ''}`)));
  }

  function render() {
    if (!plan) return;
    fill(list, ...plan.sets.map(setRow));
    fill(skipped, plan.skipped.length
      ? el('details', {},
        el('summary', {}, icon('warn'), `${fmt.plural(plan.skipped.length, 'item')} left out`),
        el('ul', {}, ...plan.skipped.map((s) => el('li', { title: s.path }, `${s.path.split(/[\\/]/).pop()}: ${s.reason}`))))
      : null);
    const active = aiActive();
    fill(aiNote, active ? null : [icon('warn'), el('span', {}, 'AI drafting is off or has no key. The sets wait in the Queue and start when the AI is on.')]);
    aiNote.hidden = active;
    startButton.textContent = busy ? 'Adding…' : active ? `Start ${fmt.plural(chosen.size, 'run')}` : `Queue ${fmt.plural(chosen.size, 'set')}`;
    startButton.disabled = busy || chosen.size === 0;
  }

  async function queueChosen() {
    const sets = plan.sets.filter((_, index) => chosen.has(index));
    busy = true;
    render();
    try {
      const queue = await invoke('queue_batch', { sets });
      dialog.close();
      onQueued(queue);
    } catch (error) {
      showError(error);
    } finally {
      busy = false;
      render();
    }
  }

  /** The Queue page group of waiting sets, or null when none waits. */
  function waitingGroup(queue, { onChange }) {
    if (!queue?.waiting.length) return null;
    const act = async (command, args) => {
      try {
        onChange(await invoke(command, args));
      } catch (error) {
        showError(error);
      }
    };
    const rows = queue.waiting.map((set, index) => {
      const state = STATE_TEXT[set.state] || { word: set.state, tone: '' };
      const movable = set.state !== 'starting';
      return el('li', { class: 'queue-wait-row', dataset: { state: set.state } },
        el('span', { class: 'queue-wait-order', title: 'Start order' }, String(index + 1)),
        el('span', { class: 'queue-name', title: set.files.join('\n') }, set.name),
        el('span', { class: 'badge badge-small', dataset: { tone: state.tone } }, el('span', { class: 'badge-text' }, state.word)),
        el('span', { class: 'queue-facts' }, set.message ? el('span', { class: 'queue-wait-message', title: set.message }, set.message) : fmt.plural(set.files.length, 'sheet file')),
        el('span', { class: 'queue-wait-actions' },
          el('button', { class: 'btn btn-ghost btn-icon btn-small', type: 'button', title: 'Start earlier', 'aria-label': `Start ${set.name} earlier`, disabled: !movable || index === 0, onclick: () => act('move_queued', { id: set.id, delta: -1 }) }, '↑'),
          el('button', { class: 'btn btn-ghost btn-icon btn-small', type: 'button', title: 'Start later', 'aria-label': `Start ${set.name} later`, disabled: !movable || index === queue.waiting.length - 1, onclick: () => act('move_queued', { id: set.id, delta: 1 }) }, '↓'),
          el('button', { class: 'btn btn-ghost btn-small', type: 'button', 'aria-label': `Remove ${set.name} from the queue`, disabled: !movable, onclick: () => act('remove_queued', { id: set.id }) }, 'Remove')));
    });
    return el('li', { class: 'queue-group queue-group-waiting' },
      el('h2', { class: 'queue-group-title' }, 'Waiting', el('span', { class: 'queue-count' }, String(queue.waiting.length))),
      el('p', { class: queue.held ? 'queue-wait-note held' : 'queue-wait-note' }, queue.held || slotLine(queue)),
      el('ol', { class: 'queue-rows queue-wait-rows' }, ...rows));
  }

  return {
    /** Show the sets a drop or a folder gave. */
    open(nextPlan) {
      plan = nextPlan;
      chosen.clear();
      plan.sets.forEach((_, index) => chosen.add(index));
      render();
      if (!dialog.open) dialog.showModal();
      startButton.focus();
    },
    waitingGroup,
  };
}
