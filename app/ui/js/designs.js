// Read-only design list and candidate pages, using the shared table and quantity display.
import { el, fill } from './dom.js';
import { t, locale, termLabel } from './i18n.js';
import { chip } from './ui_kit.js';
import { listDesignRecords, openDesignRecord } from './api.js';
import { createDataTable } from './data_table.js';
import { valueDisplay } from './value_display.js';
import { designView, designQuantity, designRows } from './design_view.js';
import { applyInterfaceMode } from './app_state.js';

const TABS = ['overview', 'requirements', 'arrangement', 'weights', 'performance', 'provenance'];
let request = 0;

function fieldLabel(path) {
  const terms = { beam: 'breadth_moulded', draft: 'design_draft', cb: 'block_coefficient' };
  return path.split('.').map((part) => {
    if (terms[part]) return termLabel(terms[part]);
    const key = `design.${part}`;
    return t(key) === key ? part : t(key);
  }).join(' › ');
}

function quantityCell(quantity) {
  return el('div', { class: 'design-value' }, valueDisplay(designQuantity(quantity)),
    el('span', { class: 'design-evidence' }, quantity.uncertainty
      ? quantity.uncertainty.basis : t('design.noBand', { reason: quantity.uncertainty_reason || t('status.unknown') })));
}

function rowValue(row, emptyKey) {
  if (row.path.endsWith('engineering_approved')) return t('design.draft');
  if (row.kind === 'quantity') return quantityCell(row.quantity);
  if (row.kind === 'unknown') return t('status.unknown');
  if (row.kind === 'empty') return t(emptyKey);
  if (typeof row.value === 'boolean') return t(row.value ? 'design.yes' : 'design.no');
  return String(row.value);
}

function rowsTable(rows, caption, emptyKey = 'design.notSupplied') {
  // Data-table formatters receive nonempty values, including unknown and empty-state rows.
  return createDataTable({
    caption, rows: rows.map((row) => ({ id: row.path, label: fieldLabel(row.path), evidence: row })),
    columns: [
      { key: 'label', label: t('design.field') },
      { key: 'evidence', label: t('design.value'), sortable: false, format: (row) => rowValue(row, emptyKey) },
    ], emptyText: t(emptyKey),
  }).element;
}

function warningPanel(rows) {
  return el('section', { class: 'design-warnings', 'aria-label': t('design.warnings') },
    el('h2', {}, t('design.warnings')),
    rows.length ? el('ul', {}, ...rows.map((row) => el('li', {},
      el('strong', {}, fieldLabel(row.path)), ': ', rowValue(row, 'design.notSupplied'))))
      : el('p', {}, t('design.noWarnings')));
}

function provenance(view) {
  return el('div', {}, rowsTable(designRows({ lineage: view.lineage, data_scope: view.scope }), t('design.lineage')),
    createDataTable({ caption: t('design.provenance'), rows: view.provenance.map((row) => ({
      id: row.path, label: fieldLabel(row.path), quantity: row.quantity,
      method: row.quantity.method, version: row.quantity.method_version,
      sources: row.quantity.sources.join('\n') || t('design.notSupplied'),
    })), columns: [
      { key: 'label', label: t('design.field') },
      { key: 'quantity', label: t('design.value'), format: quantityCell, sortable: false },
      { key: 'method', label: t('design.method') },
      { key: 'version', label: t('design.method_version') },
      { key: 'sources', label: t('design.sources') },
    ] }).element);
}

function project(host, record) {
  const view = designView(record);
  const parent = view.lineage.parent_design_id;
  let active = 'overview';
  const content = el('div', { id: 'design-tab-panel', role: 'tabpanel', tabindex: '0' });
  const tabs = el('div', { class: 'design-tabs', role: 'tablist', 'aria-label': t('design.details') });
  function selectTab(tab, focus = false) {
    active = tab;
    for (const button of tabs.children) {
      const selected = button.dataset.tab === tab;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    }
    content.setAttribute('aria-labelledby', `design-tab-${tab}`);
    fill(content, tab === 'provenance' ? provenance(view)
      : rowsTable(view[tab], t(`design.${tab}`), tab === 'weights' ? 'design.notCalculated' : 'design.notSupplied'));
  }
  for (const tab of TABS) tabs.append(el('button', {
    id: `design-tab-${tab}`, class: 'btn', type: 'button', role: 'tab', dataset: { tab },
    'aria-controls': 'design-tab-panel', onclick: () => selectTab(tab),
    onkeydown: (event) => {
      let next;
      if (event.key === 'ArrowRight') next = (TABS.indexOf(active) + 1) % TABS.length;
      if (event.key === 'ArrowLeft') next = (TABS.indexOf(active) + TABS.length - 1) % TABS.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = TABS.length - 1;
      if (next !== undefined) { event.preventDefault(); selectTab(TABS[next], true); }
    },
  }, t(`design.${tab}`)));
  const detail = el('div', { class: 'design-advanced' }, tabs, content);
  const summary = el('section', { class: 'design-lite', 'aria-label': t('design.summary') },
    el('h2', {}, t('design.summary')), rowsTable(view.lite, t('design.summary')),
    el('button', { class: 'btn', type: 'button', onclick: () => {
      applyInterfaceMode('advanced', { remember: true });
      selectTab('overview', true);
    } }, t('design.showDetail')));
  fill(host, el('header', { class: 'design-header' },
    el('a', { href: '#designs' }, t('design.title')),
    el('h1', {}, record.name), chip(t('status.draft'), { tone: 'draft' }),
    record.status === 'review_required' ? chip(t('status.needs_review'), { tone: 'warn' }) : null,
    el('p', {}, t('design.draft')),
    el('button', { class: 'btn design-advanced', type: 'button', onclick: () => {
      applyInterfaceMode('lite', { remember: true });
      summary.querySelector('button').focus();
    } }, t('settings.lite')),
    parent ? el('a', { href: `#design/${encodeURIComponent(parent)}` }, t('design.parent', { name: parent })) : null),
  warningPanel(view.warnings), summary, detail);
  selectTab(active);
}

async function list(host, current) {
  const records = await listDesignRecords();
  if (current !== request) return;
  const rows = records.map((record, index) => ({ ...record, rowId: index,
    length: record.main_dimensions.length?.value ?? t('status.unknown'),
    beam: record.main_dimensions.beam?.value ?? t('status.unknown'),
    draft: record.main_dimensions.draft?.value ?? t('status.unknown'),
  }));
  const columns = [
    { key: 'name', label: t('design.name') },
    { key: 'ship_type', label: t('design.shipType') },
    ...['length', 'beam', 'draft'].map((key) => ({ key, label: fieldLabel(key), unit: 'm',
      format: (_, row) => row.main_dimensions[key] ? quantityCell(row.main_dimensions[key]) : t('status.unknown') })),
    { key: 'status', label: t('design.status'), format: (status) => status === 'review_required'
      ? `${t('design.draft')} · ${t('status.needs_review')}` : status === 'draft' ? t('design.draft') : t('status.unknown') },
    { key: 'updated_ms', label: t('design.updated'), format: (time) => typeof time === 'number' ? new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(time) : time },
    { key: 'validation_error', label: t('design.error') },
  ];
  // Missing type and timestamps are explicit values, not inferred from the vessel name.
  for (const row of rows) {
    row.ship_type ||= t('status.unknown');
    row.updated_ms ??= t('status.unknown');
    row.status ||= t('status.unknown');
    row.validation_error ||= t('design.noError');
  }
  fill(host, el('h1', {}, t('design.title')), el('p', {}, t('design.draft')),
    createDataTable({ rows, columns, caption: t('design.title'), rowKey: (row) => row.rowId,
      emptyText: t('design.notSupplied'), onSelect: (key) => {
        const record = records[key];
        if (record.id && !record.validation_error) location.hash = `design/${encodeURIComponent(record.id)}`;
      },
    }).element);
}

/** Load a list or validated record. A request token prevents stale loads replacing a newer route. */
export async function renderDesignRoute(route) {
  const current = ++request;
  const host = document.getElementById('view-designs');
  fill(host, el('p', { role: 'status' }, t('design.loading')));
  try {
    if (route === 'designs') await list(host, current);
    else {
      const record = await openDesignRecord(decodeURIComponent(route.slice('design/'.length)));
      if (current === request) project(host, record);
    }
  } catch (error) {
    if (current === request) fill(host, el('h1', {}, t('design.title')),
      el('p', { role: 'alert' }, t('design.loadError', { reason: error.message || String(error) })),
      el('a', { href: '#designs' }, t('design.title')));
  }
}
