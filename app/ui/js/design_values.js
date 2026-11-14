// Shared DOM pieces of the design screens: field labels, numbers and the quantity display.
// designs.js (one design), design_project.js (Candidates, Compare, Decisions) and
// pareto_chart.js read the same labels and the same value display.
import { el } from './dom.js';
import { t, locale, termLabel } from './i18n.js';
import { chip } from './ui_kit.js';
import { formatQuantity } from './value_display.js';
import { designQuantity, designDigits, designMissingKey } from './design_view.js';

// Record keys that are ship terms read from the glossary (Korean adds the abbreviation).
const TERMS = {
  length: 'length', beam: 'breadth_moulded', draft: 'design_draft', depth: 'depth_moulded',
  cb: 'block_coefficient', displacement: 'displacement', deadweight: 'deadweight', deadweight_t: 'deadweight',
  cargo_capacity: 'cargo_capacity', cargo_capacity_m3: 'cargo_capacity',
  service_speed: 'service_speed', brake_power: 'brake_power', fuel: 'daily_fuel',
};

export function keyLabel(key) {
  if (TERMS[key]) return termLabel(TERMS[key]);
  if (key === 'weights') return t('design.weightItems'); // design.weights names the tab
  const label = t(`design.${key}`);
  return label === `design.${key}` ? null : label;
}

/** A human label for a record path: its own key, else the nearest labelled section above it. */
export function fieldLabel(path) {
  const keys = path.split('.').filter((key) => !/^\d+$/.test(key));
  if (keys.at(-1) === 'value' || keys.at(-1) === 'kn') keys.pop();
  for (let index = keys.length - 1; index >= 0; index -= 1) {
    const label = keyLabel(keys[index]);
    if (label) return label;
  }
  return t('design.otherField');
}

export function numberFormat(options) {
  return new Intl.NumberFormat(locale() === 'ko' ? 'ko-KR' : 'en-GB', options);
}

/**
 * Fraction digits for a summary value. A length in metres keeps two places: a 0.4 m change of
 * a 320 m hull is the change the designer made, so it must not round away.
 */
export function summaryDigits(value, unit) {
  return unit === 'm' ? 2 : designDigits(value);
}

export function numberText(value, { compact, unit = null }) {
  const digits = summaryDigits(value, unit);
  let options = { maximumFractionDigits: 12 };
  if (compact) options = digits === null ? { maximumSignificantDigits: 4 } : { maximumFractionDigits: digits };
  return numberFormat(options).format(value);
}

/**
 * A quantity: number, unit, then its band or a quiet "no band" mark. The reason for a missing
 * band is the mark's title; `focusable` also shows it on keyboard focus. Every value is a draft
 * (the page header says so); only "Needs review" adds a chip here.
 */
export function quantityValue(quantity, { compact = false, focusable = false } = {}) {
  const shown = designQuantity(quantity);
  const formatted = formatQuantity(shown);
  const unit = quantity.unit === '1' ? '' : quantity.unit;
  const full = `${numberText(quantity.value, { compact: false })} ${unit}`.trim();
  let band;
  if (quantity.uncertainty) {
    band = el('span', { class: 'dv-band', title: quantity.uncertainty.basis || null }, formatted.uncertaintyText);
  } else {
    const reason = quantity.uncertainty_reason || t('design.notSupplied');
    band = el('span', { class: 'dv-noband', title: reason, tabindex: focusable ? '0' : null, dataset: { reason } },
      t('design.noBandMark'), el('span', { class: 'visually-hidden' }, `: ${reason}`));
  }
  return el('span', { class: compact ? 'dv dv-compact' : 'dv', title: full },
    el('span', { class: 'dv-num' }, formatted.isUnknown ? '—' : numberText(quantity.value, { compact, unit: quantity.unit })),
    unit ? el('span', { class: 'dv-unit' }, unit) : null,
    band,
    shown.status === 'needs_review' ? chip(t('status.needs_review'), { tone: 'warn', small: true }) : null);
}

/** "Not calculated yet" for a missing result, "Not supplied" for a missing input. */
export function missingText(row) {
  const key = row.missingKey || designMissingKey(row.path);
  return el('span', { class: 'design-missing' }, t(key));
}
