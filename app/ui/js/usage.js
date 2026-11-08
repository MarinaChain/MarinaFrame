// Key usage (Settings > AI): the OpenCode Go meters of each configured key slot, the slot the
// next run will use, and a warning when every key is near or at a limit. Data:
// get_model_usage (APP_SPEC "Key usage"). It is read only when the person asks: a check is a
// network request per key, so there is no timer. Keys are never shown; only slot numbers.

import { el, fill, icon } from './dom.js';

/** A meter at or above this percent is shown in amber (the backend uses the same value). */
const NEAR_LIMIT_PERCENT = 90;
const WINDOW_TEXT = { rolling: 'Rolling', weekly: 'Weekly', monthly: 'Monthly' };

/**
 * When a meter resets, from what the provider gave: an ISO time, or a number of seconds or
 * milliseconds since 1970. Null when it cannot be read.
 */
export function resetTime(value) {
  if (value === null || value === undefined || value === '') return null;
  if (/^\d+(\.\d+)?$/.test(String(value))) {
    const number = Number(value);
    // Below 1e11 the number is seconds (1e11 s is the year 5138), else milliseconds.
    return number < 1e11 ? number * 1000 : number;
  }
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/** "in 3 h", "in 2 days", "now": the time left until a reset, in large steps. */
export function resetIn(resetMs, nowMs) {
  if (resetMs === null) return null;
  const minutes = Math.round((resetMs - nowMs) / 60000);
  if (minutes <= 0) return 'now';
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `in ${hours} h`;
  return `in ${Math.round(hours / 24)} days`;
}

/** The short state word of one slot. */
export function slotState(slot, nextSlot) {
  if (slot.error) return { word: 'Not checked', tone: 'warn' };
  if (!slot.usable) return { word: 'At limit', tone: 'warn' };
  if (slot.highest_percent >= NEAR_LIMIT_PERCENT) return { word: slot.slot === nextSlot ? 'Next, near limit' : 'Near limit', tone: 'warn' };
  if (slot.slot === nextSlot) return { word: 'Next run', tone: 'brand' };
  return { word: 'Ready', tone: '' };
}

export function createUsage({ invoke }) {
  let usage = null;
  let checking = false;
  let failed = '';
  const host = el('div', { class: 'usage', id: 'key-usage', 'aria-live': 'polite' });

  async function check() {
    checking = true;
    failed = '';
    render();
    try {
      usage = await invoke('get_model_usage');
    } catch (error) {
      failed = error?.message || 'The usage could not be read.';
    }
    checking = false;
    render();
  }

  function meter(m) {
    const percent = m.percent;
    const near = percent !== null && percent >= NEAR_LIMIT_PERCENT;
    const resets = resetIn(resetTime(m.resets_at), Date.now());
    const bar = el('span', { class: 'usage-bar', 'aria-hidden': 'true' }, el('span', { class: 'usage-fill' }));
    // The CSP blocks inline style attributes; set the width through the CSSOM.
    bar.firstChild.style.width = `${Math.min(100, Math.max(0, percent ?? 0))}%`;
    return el('div', {
      class: `usage-meter${near ? ' near' : ''}`,
      role: 'group',
      'aria-label': `${WINDOW_TEXT[m.window] || m.window}: ${percent === null ? 'no reading' : `${Math.round(percent)} percent`}${resets ? `, resets ${resets}` : ''}`,
    },
      el('span', { class: 'usage-meter-head' },
        el('span', { class: 'usage-window' }, WINDOW_TEXT[m.window] || m.window),
        el('span', { class: 'usage-percent' }, percent === null ? '—' : `${Math.round(percent)}%`)),
      bar,
      el('span', { class: 'usage-reset', title: m.resets_at || '' }, resets ? `Resets ${resets}` : (m.status && m.status !== 'ok' ? m.status : '')));
  }

  function slotRow(slot) {
    const stateWord = slotState(slot, usage.next_slot);
    return el('li', { class: `usage-slot${slot.slot === usage.next_slot ? ' next' : ''}` },
      el('div', { class: 'usage-slot-head' },
        el('span', { class: 'usage-slot-name' }, `Key ${slot.slot}`),
        el('span', { class: 'badge badge-small', dataset: { tone: stateWord.tone } }, el('span', { class: 'badge-text' }, stateWord.word))),
      slot.error
        ? el('p', { class: 'usage-error' }, slot.error)
        : el('div', { class: 'usage-meters' }, ...slot.meters.map(meter)));
  }

  function render() {
    const button = el('button', { class: 'btn', type: 'button', id: 'check-usage', disabled: checking, onclick: check },
      checking ? 'Checking…' : (usage ? 'Check again' : 'Check usage'));
    const source = usage?.key_source === 'environment' ? 'from the environment' : usage?.key_source === 'key_file' ? 'from the key file' : null;
    const head = el('div', { class: 'setting-row usage-head' },
      el('span', { class: 'setting-label' }, 'Key usage',
        usage?.next_slot ? el('span', { class: 'badge', dataset: { tone: 'brand' }, title: 'The worker uses the key with the most room left on its highest meter.' }, `Next run: key ${usage.next_slot}`) : null),
      button);
    let body;
    if (failed) body = el('p', { class: 'usage-error', role: 'alert' }, failed);
    else if (!usage) body = el('p', { class: 'field-help' }, 'Reads each key’s OpenCode Go meters. It sends no drawing and makes no model request. Keys are never shown.');
    else if (!usage.slots.length) body = el('p', { class: 'field-help' }, 'No key found. Add keys to the key file, one per line.');
    else {
      body = el('div', { class: 'usage-body' },
        usage.warning ? el('p', { class: 'usage-warning', role: 'note' }, icon('warn'), el('span', {}, usage.warning)) : null,
        el('ul', { class: 'usage-slots' }, ...usage.slots.map(slotRow)),
        el('p', { class: 'field-help' }, `${usage.slots.length} ${usage.slots.length === 1 ? 'key' : 'keys'} ${source || ''}. Checked ${new Date(usage.checked_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`));
    }
    fill(host, head, body);
  }

  render();
  return { element: host };
}
