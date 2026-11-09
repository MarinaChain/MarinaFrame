// A calibration correction is a person’s choice, never an automatic repair.
import { el } from './dom.js';
import { tipAttributes } from './tooltip.js';

export function calibrationChoice({ check = {}, onSave, onCancel }) {
  const suggested = (check.flags || []).some((flag) => /^sides:.*disagree/i.test(flag));
  const kind = el('select', { 'aria-label': 'What is wrong', onchange: update },
    el('option', { value: '' }, 'Choose a problem'),
    el('option', { value: 'swap_sides' }, 'Bow/stern swapped'),
    el('option', { value: 'reverse_order' }, 'Station order'),
    el('option', { value: 'other' }, 'Other'));
  kind.value = suggested ? 'swap_sides' : '';
  const half = el('select', { 'aria-label': 'Half' },
    el('option', { value: 'fore' }, 'Bow half'), el('option', { value: 'aft' }, 'Stern half'));
  half.value = 'fore';
  const note = el('textarea', { 'aria-label': 'What is wrong (note)', rows: 2, maxlength: 2000 });
  const apply = el('button', { type: 'button', class: 'btn', 'aria-label': 'Apply correction', onclick: async () => {
    if (!kind.value || (kind.value === 'other' && !note.value.trim())) return;
    const fix = { kind: kind.value };
    if (kind.value === 'reverse_order') fix.half = half.value;
    if (kind.value === 'other') fix.text = note.value.trim();
    apply.disabled = true;
    try { await onSave(fix); } finally { apply.disabled = false; }
  }, ...tipAttributes('Apply correction', 'Re-read and rebuild for a known correction. Other records your note and uses the model path.', { label: false }).attrs }, '↻ Apply');
  function update() {
    half.hidden = kind.value !== 'reverse_order';
    note.hidden = kind.value !== 'other';
    apply.disabled = !kind.value;
  }
  update();
  return el('div', { class: 'calibration-choice', 'aria-label': 'Calibration correction' },
    suggested ? el('span', { ...tipAttributes('Suggested: swap halves', 'The automatic side checks disagree. Apply only if the bow and stern halves are swapped.', { label: false }).attrs }, '↔ Suggested') : null,
    kind, half, note, apply,
    el('button', { type: 'button', class: 'btn', onclick: onCancel }, 'Cancel'));
}
