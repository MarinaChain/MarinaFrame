// Read-only designer workbench: the Designs list and one design's page. The overview shows
// main particulars as cards, grouped warnings and the change from the parent; the tabs show
// sections of labelled values; the Provenance tab keeps every record field and its evidence.
// Pure mapping is in design_view.js; this module only builds DOM.
import { el, fill, icon } from './dom.js';
import { t, locale } from './i18n.js';
import { chip } from './ui_kit.js';
import { listDesignRecords, openDesignRecord } from './api.js';
import { createDataTable } from './data_table.js';
import {
  designView, designParticulars, designWarningGroups, designChanges,
  designSections, designMissing, designTopic,
} from './design_view.js';
import { keyLabel, fieldLabel, numberText, quantityValue, missingText } from './design_values.js';
import { applyInterfaceMode } from './app_state.js';

const TABS = ['overview', 'requirements', 'arrangement', 'weights', 'performance', 'provenance'];
const WARNING_PREVIEW = 3; // warnings shown before "Show all N warnings"
let request = 0;
let warningPanels = 0; // unique ids for aria-controls

/** "Resistance · Inputs": the section path without the "results" level. */
function sectionLabel(path) {
  return path.split('.').filter((key) => key !== 'results').map((key) => keyLabel(key) || key).join(' · ');
}

function rowValue(row, options) {
  if (row.path.endsWith('engineering_approved')) return t('design.draft');
  if (row.kind === 'quantity') return quantityValue(row.quantity, options);
  if (row.kind === 'unknown' || row.kind === 'empty') return missingText(row);
  if (typeof row.value === 'boolean') return t(row.value ? 'design.yes' : 'design.no');
  const translated = t(`design.enum.${row.value}`);
  return translated === `design.enum.${row.value}` ? String(row.value) : translated;
}

/* ---------- Warnings ---------- */

function warningItem({ topic, row }) {
  return el('li', {}, el('span', { class: 'design-warning-topic' }, t(`design.topic.${topic}`)),
    el('span', { class: 'design-warning-text' }, String(row.value)));
}

/**
 * Checks and warnings: the first few in one line each, then "Show all N warnings" opens every
 * warning grouped by topic. Shown in Lite and Advanced; a design with none says so.
 */
function warningPanel(rows) {
  const heading = el('h2', {}, icon('warn'), t('design.checks'),
    rows.length ? el('span', { class: 'design-count' }, String(rows.length)) : null);
  if (!rows.length) {
    return el('section', { class: 'design-warnings design-warnings-none' }, heading, el('p', {}, t('design.noWarnings')));
  }
  const groups = designWarningGroups(rows);
  const flat = groups.flatMap(({ topic, warnings }) => warnings.map((row) => ({ topic, row })));
  const preview = el('ul', { class: 'design-warning-preview' }, ...flat.slice(0, WARNING_PREVIEW).map(warningItem));
  const full = el('div', { class: 'design-warning-full', id: `design-warnings-${++warningPanels}`, hidden: true },
    ...groups.map(({ topic, warnings }) => el('section', {},
      el('h3', {}, t(`design.topic.${topic}`), el('span', { class: 'design-count' }, String(warnings.length))),
      el('ul', {}, ...warnings.map((row) => el('li', {}, String(row.value)))))));
  const toggle = flat.length > WARNING_PREVIEW ? el('button', {
    class: 'btn btn-small btn-ghost design-warning-toggle', type: 'button',
    'aria-expanded': 'false', 'aria-controls': full.id,
    onclick: () => {
      const expanded = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(expanded));
      full.hidden = !expanded;
      preview.hidden = expanded;
      toggle.textContent = t(expanded ? 'design.fewerWarnings' : 'design.allWarnings', { count: rows.length });
    },
  }, t('design.allWarnings', { count: rows.length })) : null;
  return el('section', { class: 'design-warnings', 'aria-label': t('design.checks') }, heading, preview, full, toggle);
}

/* ---------- Overview ---------- */

function particularCard(card) {
  const missing = card.kind !== 'quantity';
  const method = missing ? null : card.quantity.method;
  return el('div', { class: 'design-card', dataset: { state: missing ? 'missing' : 'value' } },
    el('dt', {}, fieldLabel(card.key)),
    el('dd', {}, missing ? [el('span', { class: 'dv-num dv-none', 'aria-hidden': 'true' }, '—'), missingText(card)]
      : quantityValue(card.quantity, { compact: true, focusable: true })),
    method ? el('dd', { class: 'design-card-method', title: method }, method) : null);
}

function particulars(cards, { lite = false } = {}) {
  const id = lite ? 'design-particulars-lite' : 'design-particulars-title';
  return el('section', { class: 'design-particulars', 'aria-labelledby': id },
    el('h2', { id }, t('design.particulars')),
    el('dl', { class: lite ? 'design-card-grid design-card-grid-lite' : 'design-card-grid' }, ...cards.map(particularCard)));
}

function changes(record, parent) {
  const items = designChanges(record, parent);
  if (!items.length) return null;
  const signed = new Intl.NumberFormat(locale() === 'ko' ? 'ko-KR' : 'en-GB', { signDisplay: 'always', maximumSignificantDigits: 6 });
  return el('section', { class: 'design-changes' }, el('h2', {}, t('design.changes')),
    el('ul', {}, ...items.map(({ key, quantity, base, delta }) => el('li', {},
      el('span', { class: 'design-change-label' }, fieldLabel(key)),
      base ? [quantityValue(base, { compact: true }), el('span', { class: 'design-arrow', 'aria-hidden': 'true' }, '→'), el('span', { class: 'visually-hidden' }, t('design.changedTo'))] : null,
      quantityValue(quantity, { compact: true }),
      delta === null
        ? el('span', { class: 'design-missing' }, t('design.parentUnavailable'))
        : el('span', { class: 'design-delta' }, signed.format(delta))))));
}

function scopeFacts(record) {
  const scope = record.data_scope || {};
  const uses = (scope.permitted_uses || []).map((use) => rowValue({ path: '', kind: 'text', value: use })).join(', ');
  return [
    scope.kind ? t('design.dataKind', { kind: rowValue({ path: '', kind: 'text', value: scope.kind }) }) : null,
    uses ? t('design.permittedUse', { uses }) : null,
  ].filter(Boolean);
}

/* ---------- Detail tabs ---------- */

function section(sectionData, { focusable = false } = {}) {
  const reasons = new Set(sectionData.rows.filter((row) => row.kind === 'quantity' && !row.quantity.uncertainty)
    .map((row) => row.quantity.uncertainty_reason || t('design.notSupplied')));
  const sharedReason = reasons.size === 1 ? [...reasons][0] : null;
  const [only] = sectionData.rows;
  if (sectionData.rows.length === 1 && only.path === sectionData.path && only.kind !== 'quantity' && only.kind !== 'text') {
    return el('section', { class: 'design-section design-section-empty' },
      el('h2', {}, sectionLabel(sectionData.path)), missingText(only));
  }
  return el('section', { class: 'design-section' },
    el('h2', {}, sectionLabel(sectionData.path)),
    sectionData.method ? el('p', { class: 'design-section-method' }, el('span', {}, t('design.method')), ' ', sectionData.method) : null,
    el('dl', { class: 'design-props' }, ...sectionData.rows.map((row) => el('div', {},
      el('dt', {}, fieldLabel(row.path)), el('dd', {}, rowValue(row, { compact: true, focusable }))))),
    sharedReason ? el('p', { class: 'design-section-note' }, t('design.noBand', { reason: sharedReason })) : null);
}

function detailTab(view, tab) {
  const warnings = tab === 'performance' ? view.warnings.filter((row) => designTopic(row.path) !== 'hull') : [];
  return el('div', { class: 'design-tab-body' },
    warnings.length ? warningPanel(warnings) : null,
    el('div', { class: 'design-sections' }, ...designSections(view[tab]).map((data) => section(data))));
}

function pathCell(label, row) {
  return el('div', {}, label, el('small', { class: 'design-path' }, row.id));
}

function provenance(view) {
  return el('div', { class: 'design-tab-body' }, el('section', {},
    el('h2', {}, t('design.provenanceQuantities')),
    createDataTable({ caption: t('design.provenanceQuantities'), rows: view.provenance.map((row) => ({
      id: row.path, label: fieldLabel(row.path), quantity: row.quantity,
      method: row.quantity.method, version: row.quantity.method_version,
      sources: row.quantity.sources.join('\n') || t('design.notSupplied'),
    })), columns: [
      { key: 'label', label: t('design.field'), format: pathCell },
      { key: 'quantity', label: t('design.value'), format: (quantity) => quantityValue(quantity), sortable: false },
      { key: 'method', label: t('design.method') },
      { key: 'version', label: t('design.method_version') },
      { key: 'sources', label: t('design.sources') },
    ] }).element), el('section', {},
    el('h2', {}, t('design.allFields')),
    createDataTable({ caption: t('design.allFields'),
      rows: view.all.map((row) => ({ id: row.path, label: fieldLabel(row.path), evidence: row })),
      columns: [
        { key: 'label', label: t('design.field'), format: pathCell },
        { key: 'evidence', label: t('design.value'), sortable: false, format: (row) => rowValue(row) },
      ], emptyText: t('design.notSupplied') }).element));
}

/* ---------- Page ---------- */

function modeControl() {
  return el('div', { class: 'segmented segmented-text design-mode', role: 'radiogroup', 'aria-label': t('design.mode') },
    ...['lite', 'advanced'].map((mode) => el('label', {}, el('input', {
      type: 'radio', name: 'design-mode', value: mode, checked: document.body.dataset.interface === mode,
      onchange: () => applyInterfaceMode(mode, { remember: true }),
    }), el('span', {}, t(`settings.${mode}`)))));
}

function header(record, parentRecord, mode) {
  const parent = record.lineage?.parent_design_id;
  const facts = [t('design.constructionNotice'), ...scopeFacts(record)];
  return el('header', { class: 'design-head' },
    el('div', { class: 'page-head' },
      el('h1', {}, record.name),
      chip(t('status.draft'), { tone: 'draft', title: t('design.draft') }),
      record.status === 'review_required' ? chip(t('status.needs_review'), { tone: 'warn' }) : null,
      parent ? (parentRecord
        ? el('a', { class: 'design-parent', href: `#design/${encodeURIComponent(parent)}` }, t('design.parentLink', { name: parentRecord.name }))
        : el('span', { class: 'design-parent' }, t('design.parentLink', { name: t('design.unavailableParent') })))
        : null,
      mode),
    el('p', { class: 'design-facts' }, facts.join(' · ')));
}

function missingList(record) {
  const { pending, notSupplied } = designMissing(record);
  const group = (key, rows) => rows.length ? el('div', { class: 'design-missing-group' },
    el('h3', {}, t(key), el('span', { class: 'design-count' }, String(rows.length))),
    el('ul', { class: 'chip-row' }, ...[...new Set(rows.map((row) => fieldLabel(row.key || row.path)))]
      .map((label) => el('li', { class: 'design-missing-chip' }, label)))) : null;
  return el('section', { class: 'design-unknowns' }, el('h2', {}, t('design.unknownValues')),
    pending.length || notSupplied.length ? [group('design.pending', pending), group('design.notSupplied', notSupplied)]
      : el('p', {}, t('design.noUnknowns')));
}

function project(host, record, parentRecord) {
  const view = designView(record);
  let active = 'overview';
  const content = el('div', { id: 'design-tab-panel', class: 'design-tab-panel', role: 'tabpanel', tabindex: '0' });
  const tabs = el('div', { class: 'vessel-tabs design-tabs', role: 'tablist', 'aria-label': t('design.details') });
  function selectTab(tab, focus = false) {
    active = tab;
    for (const button of tabs.children) {
      const selected = button.dataset.tab === tab;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    }
    content.setAttribute('aria-labelledby', `design-tab-${tab}`);
    if (tab === 'overview') {
      fill(content, el('div', { class: 'design-tab-body' }, particulars(view.particulars),
        el('div', { class: 'design-overview-lower' }, warningPanel(view.warnings), changes(record, parentRecord))));
    } else if (tab === 'provenance') fill(content, provenance(view));
    else fill(content, detailTab(view, tab));
  }
  for (const tab of TABS) tabs.append(el('button', {
    id: `design-tab-${tab}`, type: 'button', role: 'tab', dataset: { tab },
    'aria-controls': 'design-tab-panel', onclick: () => selectTab(tab),
    onkeydown: (event) => {
      const moves = { ArrowRight: 1, ArrowLeft: TABS.length - 1 };
      let next;
      if (event.key in moves) next = (TABS.indexOf(active) + moves[event.key]) % TABS.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = TABS.length - 1;
      if (next !== undefined) { event.preventDefault(); selectTab(TABS[next], true); }
    },
  }, t(`design.${tab}`)));
  const mode = modeControl();
  const summary = el('div', { class: 'design-lite design-tab-body' },
    particulars(designParticulars(record, { lite: true }), { lite: true }), warningPanel(view.warnings), missingList(record),
    el('div', {}, el('button', { class: 'btn', type: 'button', onclick: () => {
      applyInterfaceMode('advanced', { remember: true });
      mode.querySelector('[value="advanced"]').checked = true;
      selectTab('overview', true);
    } }, t('design.showDetail'))));
  fill(document.getElementById('crumbs'), el('a', { class: 'crumb crumb-link', href: '#designs' }, t('design.title')),
    el('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, '›'),
    el('span', { class: 'crumb crumb-current', 'aria-current': 'page' }, record.name));
  fill(host, el('div', { class: 'page-body design-body' },
    header(record, parentRecord, mode), summary, el('div', { class: 'design-advanced' }, tabs, content)));
  selectTab(active);
}

/* ---------- List ---------- */

const LIST_KEYS = ['length', 'beam', 'draft', 'cb', 'fuel'];

/** One list column per particular. Values sort as numbers; the unit is in the header. */
function particularColumn(key, rows) {
  const units = new Set(rows.map((row) => row.cards[key]?.quantity?.unit).filter(Boolean));
  const unit = units.size === 1 ? [...units][0] : null;
  return {
    key, label: t(`design.col.${key}`), unit: unit && unit !== '1' ? unit : undefined, align: 'end',
    format: (_, row) => {
      const quantity = row.cards[key].quantity;
      const text = numberText(quantity.value, { compact: true });
      return unit ? text : `${text} ${quantity.unit}`;
    },
  };
}

async function list(host, current) {
  const records = await listDesignRecords();
  // The list command is deliberately small. Read detail through the existing API, not a new schema.
  const rows = await Promise.all(records.map(async (record, index) => {
    let detail;
    let error = record.validation_error;
    if (record.id && !error) {
      try { detail = await openDesignRecord(record.id); } catch (failure) { error = failure.message; }
    }
    const cards = Object.fromEntries(designParticulars(detail || { main_dimensions: record.main_dimensions })
      .map((card) => [card.key, card]));
    return { ...record, rowId: index, detail, cards, validation_error: error || null,
      ...Object.fromEntries(LIST_KEYS.map((key) => [key, cards[key].quantity?.value ?? null])) };
  }));
  if (current !== request) return;
  const names = new Map(records.map((record) => [record.id, record.name]));
  for (const row of rows) {
    const parent = row.detail?.lineage.parent_design_id;
    row.parent = parent ? names.get(parent) || t('design.unavailableParent') : t('design.noParent');
  }
  const columns = [
    { key: 'name', label: t('design.name'), format: (name) => el('span', { class: 'design-list-name' }, name) },
    { key: 'parent', label: t('design.parentColumn') },
    ...LIST_KEYS.map((key) => particularColumn(key, rows)),
    { key: 'status', label: t('design.status'), format: (status) => el('span', { class: 'chip-row' },
      chip(t('status.draft'), { tone: 'draft', small: true }),
      status === 'review_required' ? chip(t('status.needs_review'), { tone: 'warn', small: true }) : null) },
    { key: 'updated_ms', label: t('design.updated'), format: (time) => new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(time) },
  ];
  if (rows.some((row) => row.validation_error)) columns.push({ key: 'validation_error', label: t('design.error') });
  fill(document.getElementById('crumbs'), el('span', { class: 'crumb crumb-current', 'aria-current': 'page' }, t('design.title')));
  fill(host, el('div', { class: 'page-body design-body' },
    el('header', { class: 'design-head' },
      el('div', { class: 'page-head' }, el('h1', {}, t('design.title')),
        el('span', { class: 'page-head-meta' }, t('design.count', { count: rows.length }))),
      el('p', { class: 'design-facts' }, t('design.listLead'))),
    createDataTable({ rows, columns, caption: t('design.title'), rowKey: (row) => row.rowId,
      emptyText: t('design.noDesigns'), onSelect: (key) => {
        const record = records[key];
        if (record.id && !record.validation_error) location.hash = `design/${encodeURIComponent(record.id)}`;
      },
    }).element));
}

/** Load a list or validated record. A request token prevents stale loads replacing a newer route. */
export async function renderDesignRoute(route) {
  const current = ++request;
  const host = document.getElementById('view-designs');
  fill(host, el('p', { class: 'page-body', role: 'status' }, t('design.loading')));
  try {
    if (route === 'designs') await list(host, current);
    else {
      const record = await openDesignRecord(decodeURIComponent(route.slice('design/'.length)));
      let parent;
      if (record.lineage.parent_design_id) {
        try { parent = await openDesignRecord(record.lineage.parent_design_id); } catch { /* An external parent can be unavailable. */ }
      }
      if (current === request) project(host, record, parent);
    }
  } catch (error) {
    if (current === request) fill(host, el('div', { class: 'page-body design-body' }, el('h1', {}, t('design.title')),
      el('p', { role: 'alert' }, t('design.loadError', { reason: error.message || String(error) })),
      el('a', { href: '#designs' }, t('design.title'))));
  }
}
