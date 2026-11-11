// GA reading of a commercial ship (docs/plans/2026-11-12-ga-commercial.md): principal
// particulars, counts (cargo holds, hatches, cranes, tanks) and the spaces read from the general
// arrangement. Each row has a source record; pointing at a row (or focusing it) shows its region
// on the GA in the drawing pane, the same source view as a 3D part (provenance.js).
//
// `gaRows` is pure (tested in app/ui-tests/ga_panel.test.mjs); the panel below it is DOM only.

import { el } from './dom.js';

/** Item ids of GA rows in the source index (provenance.js); no 3D part uses this prefix. */
export const GA_PREFIX = 'ga:';

const PARTICULARS = [
  ['loa_m', 'Length overall', 'm'], ['lbp_m', 'Length between perpendiculars', 'm'],
  ['breadth_m', 'Breadth (moulded)', 'm'], ['depth_m', 'Depth (moulded)', 'm'],
  ['draft_m', 'Design draft', 'm'], ['scantling_draft_m', 'Scantling draft', 'm'],
  ['deadweight_t', 'Deadweight', 't'],
];
const COUNTS = [
  ['cargo_holds', 'Cargo holds'], ['cargo_hatches', 'Cargo hatches'], ['cargo_cranes', 'Cargo cranes'],
  ['cargo_tanks', 'Cargo tanks'], ['slop_tanks', 'Slop tanks'], ['container_bays', 'Container bays'],
];
const KIND_NAMES = {
  cargo_hold: 'Cargo holds', cargo_hatch: 'Cargo hatches', cargo_crane: 'Cargo cranes', cargo_tank: 'Cargo tanks',
  slop_tank: 'Slop tanks', ballast_tank: 'Ballast tanks', fuel_tank: 'Fuel tanks', other_tank: 'Other tanks',
  engine_room: 'Engine room', accommodation_deck: 'Accommodation decks', container_bay: 'Container bays',
  other_space: 'Other spaces',
};
const SHIP_TYPES = {
  bulk_carrier: 'Bulk carrier', tanker: 'Tanker', container_ship: 'Container ship', general_cargo: 'General cargo ship',
  other: 'Other ship type',
};
/** Words for a status; never "approved" or "verified". */
export const STATUS_WORDS = { read: 'Read', guessed: 'Best guess', unknown: 'Not read' };

function number(value, unit) {
  if (value === null || value === undefined) return '—';
  const text = unit === 't' ? Math.round(value).toLocaleString('en-GB') : Number(value).toFixed(2);
  return `${text} ${unit}`;
}

/**
 * The rows of a GA reading, in display order: `{ shipType, particulars, counts, groups }`. Each row
 * is `{ id, label, value, status, note, record }`; `groups` are spaces by kind. Null without a
 * reading. Fields the drawing does not print are kept as "Not read" rows (an abstention is shown).
 */
export function gaRows(reading) {
  if (!reading) return null;
  const particulars = PARTICULARS.map(([key, label, unit]) => {
    const item = reading.particulars?.[key] || {};
    return {
      id: `${GA_PREFIX}particular:${key}`, label, value: number(item.value, unit), status: item.status || 'unknown',
      note: item.value === null || item.value === undefined ? (item.reason || '') : (item.printed ? `Printed “${item.printed}”` : ''),
      record: item.source_record || null,
    };
  });
  const counts = COUNTS.map(([key, label]) => {
    const item = reading.counts?.[key] || {};
    const known = item.value !== null && item.value !== undefined;
    return {
      id: `${GA_PREFIX}count:${key}`, label, value: known ? String(item.value) : '—', status: item.status || 'unknown',
      note: known ? (item.evidence || '') : (item.reason || ''), record: item.source_record || null,
    };
  });
  const groups = [];
  // A numbered hold or tank is listed once per view it is labelled in; the note names the view.
  const viewNames = new Map((reading.views || []).map((v) => [v.view_id, [v.kind.replace(/_/g, ' '), v.title].filter(Boolean).join(' ')]));
  for (const space of reading.spaces || []) {
    let group = groups.find((g) => g.kind === space.kind);
    if (!group) {
      group = { kind: space.kind, label: KIND_NAMES[space.kind] || space.kind, rows: [] };
      groups.push(group);
    }
    group.rows.push({
      id: `${GA_PREFIX}space:${space.id}`, label: space.label || `Unlabelled ${space.kind.replace(/_/g, ' ')}`,
      value: space.number ? `No. ${space.number}` : '', status: space.status,
      note: viewNames.get(space.view_id) ? `In ${viewNames.get(space.view_id)}` : '', record: space.source_record,
    });
  }
  const order = Object.keys(KIND_NAMES);
  groups.sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  const type = reading.ship_type || {};
  return {
    shipType: type.value ? (SHIP_TYPES[type.value] || type.value) : 'Ship type not read',
    particulars, counts, groups,
  };
}

/** Every GA row with its record and label, for the source index (provenance.js). */
export function gaRecords(reading) {
  const rows = gaRows(reading);
  if (!rows) return [];
  return [...rows.particulars, ...rows.counts, ...rows.groups.flatMap((g) => g.rows)]
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
    const button = el('button', {
      class: `ga-row ga-${item.status}`, type: 'button', 'data-ga-id': item.id, 'aria-pressed': 'false',
      title: item.note || null,
      onpointerenter: () => onHover(sourceItem), onpointerleave: () => onHover(null),
      onfocus: () => onHover(sourceItem), onblur: () => onHover(null),
      onclick: () => {
        selected = selected === item.id ? null : item.id;
        for (const other of element.querySelectorAll('.ga-row')) other.setAttribute('aria-pressed', String(other.dataset.gaId === selected));
        onSelect(selected ? sourceItem : null);
      },
    },
    el('span', { class: 'ga-row-label' }, item.label),
    el('span', { class: 'ga-row-value' }, item.value),
    el('span', { class: 'ga-row-status' }, STATUS_WORDS[item.status] || item.status));
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
          el('h2', { class: 'ga-title' }, 'GA reading'),
          el('p', { class: 'ga-meta' }, `${rows.shipType} · a reading of the drawing for engineers to check; not approved`)),
        section('Principal particulars', rows.particulars),
        section('Counts', rows.counts),
        ...rows.groups.map((group) => section(`${group.label} (${group.rows.length})`, group.rows)));
    },
  };
}
