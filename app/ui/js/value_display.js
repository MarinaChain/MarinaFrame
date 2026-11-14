// Shared quantity display: pure locale-aware formatting, with a separate accessible DOM view.
import { el } from './dom.js';
import { locale, t } from './i18n.js';
import { chip } from './ui_kit.js';

function methodLabel(method) {
  const translated = t(`method.${method}`);
  if (translated !== `method.${method}`) return translated;
  if (method.length <= 24) return method;
  const words = method.slice(0, 23).replace(/\s+\S*$/, '').trim();
  return `${words || method.slice(0, 23)}…`;
}

/** Format a quantity without reading or changing the DOM. Omitted status means Draft. */
export function formatQuantity(q) {
  const isUnknown = q.value === null || q.value === undefined;
  const options = q.digits === undefined ? {} : {
    minimumFractionDigits: q.digits, maximumFractionDigits: q.digits,
  };
  const numbers = new Intl.NumberFormat(locale() === 'ko' ? 'ko-KR' : 'en-GB', options);
  let uncertaintyText = '';
  if (!isUnknown && q.uncertainty) {
    uncertaintyText = 'plusMinus' in q.uncertainty
      ? `± ${numbers.format(q.uncertainty.plusMinus)}`
      : `${numbers.format(q.uncertainty.low)}–${numbers.format(q.uncertainty.high)}`;
  }
  return {
    text: isUnknown ? '—' : numbers.format(q.value),
    unitText: q.unit || '',
    uncertaintyText,
    methodText: q.method ? methodLabel(q.method) : '',
    statusText: t(`status.${isUnknown ? 'unknown' : (q.status || 'draft')}`),
    isUnknown,
    sourceText: q.source || '',
  };
}

/** Value, unit, uncertainty, method and status, in reading order. A source adds a focus stop. */
export function valueDisplay(q, { compact = false } = {}) {
  const formatted = formatQuantity(q);
  const status = formatted.isUnknown ? 'unknown' : (q.status || 'draft');
  const tones = {
    unknown: 'warn', needs_review: 'warn', draft: 'draft', read: 'brand',
    guessed: 'draft', measured_from_scale: 'brand', derived_from_space_tops: 'draft',
    unconfirmed_from_uncertain_boxes: 'warn',
  };
  const method = !compact && formatted.methodText
    ? chip(formatted.methodText, { small: true, dot: false }) : null;
  if (method) {
    method.classList.add('vd-method');
    method.title = q.method;
  }
  const statusChip = chip(formatted.statusText, { tone: tones[status] || 'draft', small: true });
  statusChip.classList.add('vd-status');
  return el('span', {
    class: 'vd', tabindex: formatted.sourceText ? '0' : null,
    title: formatted.sourceText || null, 'aria-description': formatted.sourceText || null,
  },
  el('span', { class: 'vd-value' }, formatted.text),
  el('span', { class: 'vd-unit' }, formatted.unitText),
  el('span', { class: 'vd-unc' }, formatted.uncertaintyText),
  method, statusChip);
}
