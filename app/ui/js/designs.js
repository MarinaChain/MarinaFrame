// Read-only designer workbench: summary cards, grouped risks and evidence on demand.
import { el, fill } from './dom.js';
import { t, locale, termLabel } from './i18n.js';
import { chip } from './ui_kit.js';
import { listDesignRecords, openDesignRecord } from './api.js';
import { createDataTable } from './data_table.js';
import { valueDisplay } from './value_display.js';
import { designView, designQuantity, designParticulars, designWarningGroups, designChanges } from './design_view.js';
import { applyInterfaceMode } from './app_state.js';

const TABS = ['overview', 'requirements', 'arrangement', 'weights', 'performance', 'provenance'];
let request = 0;

function fieldLabel(path) {
  const terms = { length: 'length', beam: 'breadth_moulded', draft: 'design_draft', depth: 'depth_moulded',
    cb: 'block_coefficient', displacement: 'displacement', deadweight: 'deadweight',
    cargo_capacity: 'cargo_capacity', service_speed: 'service_speed', brake_power: 'brake_power', fuel: 'daily_fuel' };
  const parts = path.split('.').filter((part) => !/^\d+$/.test(part));
  if (parts.at(-1) === 'value' || parts.at(-1) === 'kn') parts.pop();
  const key = parts.at(-1);
  if (terms[key]) return termLabel(terms[key]);
  const label = t(`design.${key}`);
  return label === `design.${key}` ? t('design.otherField') : label;
}

function quantityCell(quantity) {
  const display = valueDisplay(designQuantity(quantity));
  if (!quantity.uncertainty) {
    const reason = t('design.noBand', { reason: quantity.uncertainty_reason || t('design.notSupplied') });
    display.querySelector('.vd-unc').append(el('span', {
      class: 'design-no-band', tabindex: '0', title: reason, 'aria-label': reason,
    }, t('design.noBandMark')));
  }
  return el('div', { class: 'design-value' }, display,
    quantity.uncertainty ? el('span', { class: 'design-evidence' }, quantity.uncertainty.basis) : null);
}

function rowValue(row, emptyKey = 'design.notSupplied') {
  if (row.path.endsWith('engineering_approved')) return t('design.draft');
  if (row.kind === 'quantity') return quantityCell(row.quantity);
  if (row.kind === 'unknown' || row.kind === 'empty') return t(row.missingKey || emptyKey);
  if (typeof row.value === 'boolean') return t(row.value ? 'design.yes' : 'design.no');
  const translated = t(`design.enum.${row.value}`);
  return translated === `design.enum.${row.value}` ? String(row.value) : translated;
}

function rowsTable(rows, caption, { rawPaths = false, emptyKey = 'design.notSupplied' } = {}) {
  return createDataTable({
    caption, rows: rows.map((row) => ({ id: row.path, label: fieldLabel(row.path), evidence: row })),
    columns: [
      { key: 'label', label: t('design.field'), format: (label, row) => rawPaths
        ? el('div', {}, label, el('small', { class: 'design-path' }, row.id)) : label },
      { key: 'evidence', label: t('design.value'), sortable: false, format: (row) => rowValue(row, emptyKey) },
    ], emptyText: t(emptyKey),
  }).element;
}

function warningPanel(rows) {
  const groups = designWarningGroups(rows);
  const preview = el('div', { class: 'design-warning-preview' }, ...groups.flatMap(({ topic, warnings }) =>
    warnings.map((row) => el('p', {}, el('strong', {}, t(`design.${topic}`)), ': ', rowValue(row)))));
  const full = el('div', { hidden: true }, ...groups.map(({ topic, warnings }) => el('section', {},
    el('h3', {}, t(`design.${topic}`)), el('ul', {}, ...warnings.map((row) => el('li', {}, rowValue(row)))))));
  const toggle = el('button', { class: 'btn btn-quiet', type: 'button', 'aria-expanded': 'false', onclick: () => {
    const expanded = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(expanded));
    full.hidden = !expanded;
    preview.hidden = expanded;
    toggle.textContent = t(expanded ? 'design.fewerWarnings' : 'design.allWarnings', { count: rows.length });
  } }, t('design.allWarnings', { count: rows.length }));
  return el('section', { class: 'design-warnings', 'aria-label': t('design.checks') },
    el('h2', {}, t('design.checks')), rows.length ? [preview, full, toggle] : el('p', {}, t('design.noWarnings')));
}

function particulars(cards) {
  return el('section', { class: 'design-particulars', 'aria-label': t('design.particulars') },
    el('h2', {}, t('design.particulars')), el('dl', { class: 'design-card-grid' }, ...cards.map((card) =>
      el('div', { class: 'design-card' }, el('dt', {}, fieldLabel(card.key)), el('dd', {}, rowValue(card))))));
}

function changes(record, parent) {
  const items = designChanges(record, parent);
  if (!items.length) return null;
  return el('section', { class: 'design-changes' }, el('h2', {}, t('design.changes')),
    el('ul', {}, ...items.map(({ key, quantity, delta }) => el('li', {}, fieldLabel(key), ' ',
      delta === null ? [quantityCell(quantity), el('span', {}, t('design.parentUnavailable'))]
        : new Intl.NumberFormat(locale(), { signDisplay: 'always', maximumSignificantDigits: 12 }).format(delta)))));
}

function provenance(view) {
  return el('div', {}, rowsTable(view.all, t('design.allFields'), { rawPaths: true }),
    createDataTable({ caption: t('design.provenance'), rows: view.provenance.map((row) => ({
      id: row.path, label: fieldLabel(row.path), quantity: row.quantity,
      method: row.quantity.method, version: row.quantity.method_version,
      sources: row.quantity.sources.join('\n') || t('design.notSupplied'),
    })), columns: [
      { key: 'label', label: t('design.field'), format: (label, row) => el('div', {}, label, el('small', { class: 'design-path' }, row.id)) },
      { key: 'quantity', label: t('design.value'), format: quantityCell, sortable: false },
      { key: 'method', label: t('design.method') },
      { key: 'version', label: t('design.method_version') },
      { key: 'sources', label: t('design.sources') },
    ] }).element);
}

function modeControl(onChange) {
  return el('div', { class: 'segmented segmented-text', role: 'radiogroup', 'aria-label': t('design.mode') },
    ...['lite', 'advanced'].map((mode) => el('label', {}, el('input', {
      type: 'radio', name: 'design-mode', value: mode, checked: document.body.dataset.interface === mode,
      onchange: () => { applyInterfaceMode(mode, { remember: true }); onChange(mode); },
    }), el('span', {}, t(`settings.${mode}`)))));
}

function project(host, record, parentRecord) {
  const view = designView(record);
  const parent = view.lineage.parent_design_id;
  let active = 'overview';
  const content = el('div', { id: 'design-tab-panel', role: 'tabpanel', tabindex: '0' });
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
    fill(content, tab === 'overview' ? el('div', {}, particulars(view.particulars), warningPanel(view.warnings), changes(record, parentRecord))
      : tab === 'provenance' ? provenance(view)
        : el('div', {}, warningPanel(view.warnings), rowsTable(view[tab], t(`design.${tab}`), {
          emptyKey: tab === 'weights' ? 'design.pending' : 'design.notSupplied',
        })));
  }
  for (const tab of TABS) tabs.append(el('button', {
    id: `design-tab-${tab}`, type: 'button', role: 'tab', dataset: { tab },
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
  const mode = modeControl(() => {});
  const unknowns = [...new Map([...view.particulars.filter((row) => row.kind === 'unknown' || row.kind === 'empty'),
    ...view.unknowns].map((row) => [row.path, row])).values()];
  const summary = el('section', { class: 'design-lite', 'aria-label': t('design.summary') },
    particulars(designParticulars(record, { lite: true })), warningPanel(view.warnings),
    el('section', {}, el('h2', {}, t('design.unknownValues')), unknowns.length
      ? el('ul', {}, ...unknowns.map((row) => el('li', {}, fieldLabel(row.key || row.path), ': ', rowValue(row))))
      : el('p', {}, t('design.noUnknowns'))),
    el('button', { class: 'btn', type: 'button', onclick: () => {
      applyInterfaceMode('advanced', { remember: true });
      mode.querySelector('[value="advanced"]').checked = true;
      selectTab('overview', true);
    } }, t('design.showDetail')));
  fill(document.getElementById('crumbs'), el('a', { class: 'crumb crumb-link', href: '#designs' }, t('design.title')),
    el('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, '›'),
    el('span', { class: 'crumb crumb-current', 'aria-current': 'page' }, record.name));
  fill(host, el('header', { class: 'page-head design-header' },
    el('div', { class: 'design-heading' }, el('h1', {}, record.name), el('p', {}, t('design.constructionNotice'))),
    chip(t('status.draft'), { tone: 'draft', title: t('design.draft') }),
    record.status === 'review_required' ? chip(t('status.needs_review'), { tone: 'warn' }) : null,
    parent ? el('a', { class: 'design-parent', href: `#design/${encodeURIComponent(parent)}` },
      t('design.parentLink', { name: parentRecord?.name || t('design.unavailableParent') })) : null,
    mode), summary, detail);
  selectTab(active);
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
    const cards = designParticulars(detail || { main_dimensions: record.main_dimensions });
    return { ...record, rowId: index, detail, cards, validation_error: error || t('design.noError'),
      ...Object.fromEntries(cards.map((card) => [card.key, card.quantity?.value ?? t('status.unknown')])),
      updated_ms: record.updated_ms ?? t('status.unknown') };
  }));
  if (current !== request) return;
  const names = new Map(records.map((record) => [record.id, record.name]));
  for (const row of rows) {
    const parent = row.detail?.lineage.parent_design_id;
    row.parent = parent ? names.get(parent) || t('design.unavailableParent') : t('design.notSupplied');
  }
  const columns = [
    { key: 'name', label: t('design.name') },
    { key: 'parent', label: t('design.parentColumn') },
    ...['length', 'beam', 'draft', 'cb', 'fuel'].map((key) => ({ key, label: fieldLabel(key),
      format: (_, row) => rowValue(row.cards.find((card) => card.key === key)) })),
    { key: 'status', label: t('design.status'), format: (status) => status === 'review_required'
      ? `${t('status.draft')} · ${t('status.needs_review')}` : status === 'draft' ? t('status.draft') : t('status.unknown') },
    { key: 'updated_ms', label: t('design.updated'), format: (time) => typeof time === 'number' ? new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(time) : time },
    { key: 'validation_error', label: t('design.error') },
  ];
  fill(host, el('header', { class: 'page-head design-header' }, el('h1', {}, t('design.title'))), el('p', {}, t('design.draft')),
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
      let parent;
      if (record.lineage.parent_design_id) {
        try { parent = await openDesignRecord(record.lineage.parent_design_id); } catch { /* An external parent can be unavailable. */ }
      }
      if (current === request) project(host, record, parent);
    }
  } catch (error) {
    if (current === request) fill(host, el('h1', {}, t('design.title')),
      el('p', { role: 'alert' }, t('design.loadError', { reason: error.message || String(error) })),
      el('a', { href: '#designs' }, t('design.title')));
  }
}
