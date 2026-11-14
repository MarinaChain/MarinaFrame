// GA reading of a commercial ship (docs/plans/2026-11-12-ga-commercial.md): principal
// particulars, counts (cargo holds, hatches, cranes, tanks) and the spaces read from the general
// arrangement. Each row has a source record; pointing at a row (or focusing it) shows its region
// on the GA in the drawing pane, the same source view as a 3D part (provenance.js).
//
// `gaRows` is pure (tested in app/ui-tests/ga_panel.test.mjs); the panel below it is DOM only.

import { el } from './dom.js';
import { t, termLabel } from './i18n.js';
import { valueDisplay } from './value_display.js';
import { chip } from './ui_kit.js';

/** Item ids of GA rows in the source index (provenance.js); no 3D part uses this prefix. */
export const GA_PREFIX = 'ga:';

// Labels come from the glossary (i18n.js): particulars by glossary id, counts by i18n key.
const PARTICULARS = [
  ['loa_m', 'loa', 'm'], ['lbp_m', 'lbp', 'm'],
  ['breadth_m', 'breadth_moulded', 'm'], ['depth_m', 'depth_moulded', 'm'],
  ['draft_m', 'design_draft', 'm'], ['scantling_draft_m', 'scantling_draft', 'm'],
  ['deadweight_t', 'deadweight', 't'],
];
const COUNTS = [
  ['cargo_holds', 'terms.cargo_hold'], ['cargo_hatches', 'terms.cargo_hatch'], ['cargo_cranes', 'terms.cargo_crane'],
  ['cargo_tanks', 'terms.cargo_tank'], ['slop_tanks', 'terms.slop_tank'], ['container_bays', 'terms.container_bay'],
];
/** Space kinds in display order; each is a glossary id. */
const KINDS = [
  'cargo_hold', 'cargo_hatch', 'cargo_crane', 'cargo_tank', 'slop_tank', 'ballast_tank', 'fuel_tank', 'other_tank',
  'engine_room', 'accommodation_deck', 'container_bay', 'other_space',
];
const SHIP_TYPES = ['bulk_carrier', 'tanker', 'container_ship', 'general_cargo'];
/** Statuses with a word; the words are in the string tables and never say "approved" or "verified". */
export const STATUSES = [
  'read', 'guessed', 'unknown',
  // Values measured on the drawing with its frame scale (never printed particulars).
  'measured_from_scale', 'derived_from_space_tops', 'unconfirmed_from_uncertain_boxes',
];

/** The word for a status in the current locale, or the status itself when it has none. */
export function statusWord(status) {
  return STATUSES.includes(status) ? t(`status.${status}`) : status;
}
const MEASURED = [
  ['lbp_m', 'lbp'], ['loa_m', 'loa'],
  ['breadth_m', 'breadth_moulded'], ['depth_m', 'depth_moulded'],
];

function number(value, unit) {
  if (value === null || value === undefined) return '—';
  const text = unit === 't' ? Math.round(value).toLocaleString('en-GB') : Number(value).toFixed(2);
  return `${text} ${unit}`;
}

// Source text complements the drawing-region preview retained on each row button.
function quantity(item, unit, digits, method, source = '') {
  const value = item.value === null || item.value === undefined || item.value === '' ? null : Number(item.value);
  const record = item.source_record;
  const regions = record?.regions || record?.inputs || [];
  const sheets = [...new Set(regions.map((region) => region.sheet).filter(Boolean))];
  return {
    value: Number.isFinite(value) ? value : null, unit, digits,
    uncertainty: item.uncertainty || null, status: item.status || 'unknown',
    method: method || (['read', 'guessed'].includes(item.status) ? 'read_from_ga' : null),
    source: [source, record?.reason, ...sheets].filter(Boolean).join(' · ') || null,
  };
}

/**
 * The rows of a GA reading, in display order: `{ shipType, particulars, counts, groups }`. Each row
 * is `{ id, label, value, status, note, record, quantity }`; `groups` are spaces by kind. Null without a
 * reading. Fields the drawing does not print are kept as "Not read" rows (an abstention is shown).
 */
export function gaRows(reading) {
  if (!reading) return null;
  const particulars = PARTICULARS.map(([key, termId, unit]) => {
    const item = reading.particulars?.[key] || {};
    return {
      id: `${GA_PREFIX}particular:${key}`, label: termLabel(termId), value: number(item.value, unit), status: item.status || 'unknown',
      note: item.value === null || item.value === undefined ? (item.reason || '') : (item.printed ? t('ga.printed', { text: item.printed }) : ''),
      record: item.source_record || null,
      quantity: quantity(item, unit, unit === 't' ? 0 : 2, null, item.printed ? t('ga.printed', { text: item.printed }) : item.reason),
    };
  });
  const counts = COUNTS.map(([key, labelKey]) => {
    const item = reading.counts?.[key] || {};
    const known = item.value !== null && item.value !== undefined;
    return {
      id: `${GA_PREFIX}count:${key}`, label: t(labelKey), value: known ? String(item.value) : '—', status: item.status || 'unknown',
      note: known ? (item.evidence || '') : (item.reason || ''), record: item.source_record || null,
      quantity: quantity(item, '', 0, null, item.evidence || item.reason),
    };
  });
  const groups = [];
  // A numbered hold or tank is listed once per view it is labelled in; the note names the view.
  const viewNames = new Map((reading.views || []).map((v) => [v.view_id, [v.kind.replace(/_/g, ' '), v.title].filter(Boolean).join(' ')]));
  for (const space of reading.spaces || []) {
    let group = groups.find((g) => g.kind === space.kind);
    if (!group) {
      group = { kind: space.kind, label: KINDS.includes(space.kind) ? t(`terms.${space.kind}`) : space.kind, rows: [] };
      groups.push(group);
    }
    group.rows.push({
      id: `${GA_PREFIX}space:${space.id}`, label: space.label || t('ga.unlabelled', { kind: KINDS.includes(space.kind) ? t(`term.${space.kind}`).toLowerCase() : space.kind.replace(/_/g, ' ') }),
      value: space.number ? t('ga.number', { number: space.number }) : '', status: space.status,
      note: viewNames.get(space.view_id) ? t('ga.inView', { view: viewNames.get(space.view_id) }) : '', record: space.source_record,
      // Space numbers identify spaces; they are labels, not measured quantities.
      quantity: null,
    });
  }
  // Measured on the drawing (the frame-scale pass): shown only when the pass ran.
  const measured = reading.measured ? MEASURED.map(([key, termId]) => {
    const item = reading.measured[key] || {};
    const known = item.value !== null && item.value !== undefined;
    return {
      id: `${GA_PREFIX}measured:${key}`, label: termLabel(termId), value: number(item.value, 'm'), status: known ? item.status : 'unknown',
      note: known ? (item.note || item.method || '') : (item.reason || ''), record: item.source_record || null,
      quantity: quantity(item, 'm', 2, 'measured', item.note || item.method || item.reason),
    };
  }) : [];
  const order = KINDS;
  groups.sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  const type = reading.ship_type || {};
  return {
    shipType: type.value ? shipTypeName(type.value) : t('ga.shipTypeUnknown'),
    particulars, counts, measured, groups,
  };
}

function shipTypeName(value) {
  if (SHIP_TYPES.includes(value)) return t(`term.${value}`);
  return value === 'other' ? t('ga.otherShipType') : value;
}

/** Every GA row with its record and label, for the source index (provenance.js). */
export function gaRecords(reading) {
  const rows = gaRows(reading);
  if (!rows) return [];
  return [...rows.particulars, ...rows.counts, ...rows.measured, ...rows.groups.flatMap((g) => g.rows)]
    .map((row) => ({ id: row.id, label: row.label, record: row.record }));
}

/**
 * The GA panel. `onHover(item | null)` and `onSelect(item | null)` take `{ kind: 'part', id }`
 * (the source controller of workspace.js).
 */
export function createGaPanel({ onHover, onSelect }) {
  const element = el('section', { class: 'ga-panel', 'aria-label': 'GA reading', hidden: true });
  let selected = null;

  function row(item) {
    const sourceItem = { kind: 'part', id: item.id };
    const status = chip(statusWord(item.status), { tone: item.status === 'read' ? 'brand' : item.status === 'unknown' ? 'warn' : 'draft', small: true });
    status.classList.add('vd-status');
    const display = item.quantity ? valueDisplay(item.quantity, { compact: true })
      : el('span', { class: 'vd' }, el('span', { class: 'vd-value' }, item.value), status);
    // The row is already a source-focus control; do not add a nested tab stop.
    display.removeAttribute('tabindex');
    const button = el('button', {
      class: `ga-row ga-${item.status}`, type: 'button', 'data-ga-id': item.id, 'aria-pressed': 'false',
      title: item.quantity?.source || item.note || null,
      'aria-description': item.quantity?.source || item.note || null,
      onpointerenter: () => onHover(sourceItem), onpointerleave: () => onHover(null),
      onfocus: () => onHover(sourceItem), onblur: () => onHover(null),
      onclick: () => {
        selected = selected === item.id ? null : item.id;
        for (const other of element.querySelectorAll('.ga-row')) other.setAttribute('aria-pressed', String(other.dataset.gaId === selected));
        onSelect(selected ? sourceItem : null);
      },
    },
    el('span', { class: 'ga-row-label' }, item.label),
    display);
    return el('li', {}, button);
  }

  function section(title, items) {
    return el('div', { class: 'ga-section' }, el('h3', { class: 'ga-section-title' }, title),
      el('ul', { class: 'ga-list' }, ...items.map(row)));
  }

  return {
    element,
    /** Show a run's GA reading, or hide the panel (null). */
    set(reading) {
      const rows = gaRows(reading);
      element.hidden = !rows;
      if (!rows) {
        element.replaceChildren();
        return;
      }
      selected = null;
      element.replaceChildren(
        el('header', { class: 'ga-head' },
          el('h2', { class: 'ga-title' }, t('ga.title')),
          el('p', { class: 'ga-meta' }, t('ga.meta', { shipType: rows.shipType }))),
        section(t('ga.particulars'), rows.particulars),
        section(t('ga.counts'), rows.counts),
        ...(rows.measured.length ? [section(t('ga.measured'), rows.measured)] : []),
        ...rows.groups.map((group) => section(`${group.label} (${group.rows.length})`, group.rows)));
    },
  };
}
