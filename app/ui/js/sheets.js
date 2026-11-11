// Sheet recovery stays separate from drawing-set intake and sheet typing.
import { el } from './dom.js';
import { glyphChip } from './glyphs.js';
import { tipAttributes } from './tooltip.js';

const STATES = {
  ok: ['st-chosen', 'Readable', null],
  unreadable: ['st-declined', 'Unreadable', 'warn'],
  wrong_scale: ['flag', 'Wrong scale', 'warn'],
  missing: ['not-built', 'Missing', 'warn'],
  replaced: ['read', 'Replaced', 'draft'],
};

export function renderSheetReview(review, { onReplace, busy = false } = {}) {
  const sheets = review?.sheets || [];
  if (!sheets.length) return null;
  const requests = review.requests || [];
  const stale = (review.outputs || []).filter(o => o.status === 'stale' || o.status === 'failed').length;
  return el('section', { class: 'sheet-review', 'aria-label': 'Sheets and requests' },
    el('div', { class: 'sheet-strip', 'aria-label': 'Sheets' }, ...sheets.map(sheet => {
      const [glyph, word, tone] = STATES[sheet.status] || STATES.unreadable;
      const needsFile = sheet.status !== 'ok';
      return el('div', { class: 'sheet-item', dataset: { state: sheet.status } },
        glyphChip(glyph, `${sheet.label}: ${word}`, { tone, detail: sheet.reason || word }),
        el('span', { class: 'sheet-name' }, sheet.label),
        sheet.reason ? el('span', { class: 'sheet-reason' }, sheet.reason) : null,
        needsFile ? el('button', { type: 'button', class: 'btn btn-ghost btn-small write-action', disabled: busy,
          ...tipAttributes(`Replace ${sheet.label}`, 'Keep the draft and retry this sheet’s outputs.').attrs,
          onclick: () => onReplace?.(sheet.id) }, 'Replace') : null);
    })),
    stale ? el('p', { class: 'sheet-draft-note', role: 'status' }, `Draft · ${stale} ${stale === 1 ? 'output needs' : 'outputs need'} input`) : null,
    requests.length ? el('details', { class: 'sheet-requests', open: requests.some(r => r.status === 'open') },
      el('summary', {}, `Requests · ${requests.filter(r => r.status === 'open').length} open`),
      el('ul', {}, ...requests.map(request => el('li', {},
        glyphChip(request.status === 'answered' ? 'st-chosen' : 'flag', request.status === 'answered' ? 'Answered' : 'Open',
          { tone: request.status === 'answered' ? null : 'warn' }),
        el('span', {}, request.text),
        el('small', {}, `${request.who} · ${request.output_id} · ${request.status === 'answered' ? 'Answered' : 'Open'}`)))),
      el('p', { class: 'sheet-draft-note' }, 'Send later: keep this draft; replace the sheet when it arrives.')) : null);
}

export function renderSheetHistory(history = []) {
  if (!history.length) return null;
  return el('section', { class: 'sheet-history', 'aria-label': 'Sheet replacements' },
    el('h2', { class: 'page-subtitle' }, 'Sheet replacements'),
    el('ul', {}, ...[...history].reverse().map(entry => el('li', {},
      el('strong', {}, `${entry.label || entry.sheet_id} · ${entry.revision_id}`),
      el('span', {}, `${entry.previous_revision_id} kept · ${entry.status === 'draft' ? 'Draft' : 'Needs input'}`),
      el('small', {}, `Retried: ${(entry.stages || []).join(', ') || 'none'}`),
      entry.pixel_scale_factor && entry.pixel_scale_factor !== 1
        ? el('small', {}, `Pixel scale ×${entry.pixel_scale_factor}`) : null))));
}
