import { el, fill } from './dom.js';
import { tipAttributes } from './tooltip.js';

const rendered = new WeakMap();

/** A worker's current work and the actions that apply to its live supervisor. */
export function workerProgressView(inFlight, elapsedMs) {
  if (inFlight?.kind !== 'worker') return null;
  const progress = inFlight.progress;
  const stage = progress?.stage || ((inFlight.operation || '').includes('hull') ? 'Building the hull' : 'Working');
  const part = progress?.total ? `: ${progress.unit} ${progress.part} of ${progress.total}` : '';
  const seconds = Math.max(0, Math.floor((elapsedMs - inFlight.since_ms) / 1000));
  const duration = seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min`;
  return {
    text: `${inFlight.stalled ? 'No progress: ' : ''}${stage}${part} · ${duration}`,
    actions: inFlight.stalled ? [
      { label: 'Keep waiting', command: 'resume_task', title: 'Keep waiting',
        detail: 'Continue this step. Ask again after five minutes without progress.' },
      { label: 'Stop', command: 'cancel_task', title: 'Stop this step',
        detail: 'Stop the running worker. Keep completed results.' },
    ] : [],
  };
}

/** Use the same accessible, two-stage tooltip structure as other run actions. */
export function renderWorkerProgress(strip, view, onAction) {
  const actionKey = view.actions.map((action) => action.command).join(',');
  const previous = rendered.get(strip);
  if (previous?.actionKey === actionKey && strip.children[1] === previous.text) {
    // Polling must not remove keyboard focus from the person's choice.
    previous.text.textContent = view.text;
    previous.onAction = onAction;
    return;
  }
  const text = el('span', { class: 'narration-text' }, view.text);
  const state = { actionKey, text, onAction };
  rendered.set(strip, state);
  fill(strip, el('span', { class: 'narration-dot', 'aria-hidden': 'true' }),
    text,
    ...view.actions.map((action) => {
      const tip = tipAttributes(action.title, action.detail);
      return el('button', { class: 'btn', type: 'button', ...tip.attrs,
        onclick: (event) => state.onAction(action.command, event.currentTarget),
      }, action.label, tip.describer);
    }));
}
