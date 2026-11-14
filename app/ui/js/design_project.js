// A design project: a record with direct children (docs/design/2026-11-14-workbench-ux-plan.md,
// 4.1). Adds the Candidates, Compare and Decisions tabs, and the Lite candidate summary.
// Every value is a draft; unknown values and failed checks stay visible in every view.
// Pure views are in design_compare.js; the chart is pareto_chart.js; this module builds DOM.
import { el, fill } from './dom.js';
import { t, locale } from './i18n.js';
import { chip } from './ui_kit.js';
import { prefs } from './app_state.js';
import { listDesignRecords, openDesignRecord, listDesignDecisions, appendDesignDecision } from './api.js';
import { createDataTable } from './data_table.js';
import { designParticulars, designMissingKey } from './design_view.js';
import {
  designProject, compareRows, constraintChecks, paretoPoints, candidateLetter, variationChanges,
  deltaTone, checkCounts, paretoState, defaultComparison, decisionGrid, decisionLog,
  DISCIPLINES, DECISION_ACTIONS, CARGO, FUEL,
} from './design_compare.js';
import { fieldLabel, numberFormat, numberText, summaryDigits, quantityValue, missingText } from './design_values.js';
import { paretoChart } from './pareto_chart.js';

export const PROJECT_TABS = ['candidates', 'compare', 'decisions'];
const COMPARE_LIMIT = 4;
// Standard abbreviations: English in every locale (docs/design/2026-11-14-workbench-ux-plan.md, 7).
const ABBREVIATIONS = { length: 'L', beam: 'B', draft: 'T', depth: 'D', cb: 'Cb' };
let forms = 0; // unique ids for form fields

/* ---------- Loading ---------- */

/**
 * The project whose parent is `record`, or null when it has no direct children. Reads every
 * record (the list command is deliberately small), then the decision log of the project.
 */
export async function loadProject(record) {
  const listed = await listDesignRecords();
  const others = await Promise.all(listed
    .filter((item) => item.id && !item.validation_error && item.id !== record.design_id)
    .map((item) => openDesignRecord(item.id).catch(() => null)));
  const { parent, candidates } = designProject([record, ...others.filter(Boolean)], record.design_id);
  if (!parent || !candidates.length) return null;
  const project = { parent, candidates, decisions: [], decisionsError: null };
  project.info = new Map([[parent.design_id, { letter: t('design.chart.parent'), name: parent.name }],
    ...candidates.map((candidate, index) => [candidate.design_id,
      { letter: candidateLetter(candidate, index), name: candidate.name }])]);
  project.points = paretoPoints(parent, candidates);
  project.checks = new Map([parent, ...candidates].map((item) => [item.design_id, constraintChecks(item)]));
  await refreshDecisions(project);
  return project;
}

async function refreshDecisions(project) {
  try {
    project.decisions = await listDesignDecisions(project.parent.design_id);
    project.decisionsError = null;
  } catch (error) {
    project.decisionsError = error.message || String(error);
  }
}

/* ---------- Shared pieces ---------- */

const openDesign = (id) => { location.hash = `design/${encodeURIComponent(id)}`; };

function checkLabel(check) {
  const label = t(`design.constraint.${check.key}`);
  return label === `design.constraint.${check.key}` ? t('design.constraint.other', { key: check.key }) : label;
}

/** "Draft limit ≤ 21 m": the requirement as a short rule. */
function checkRule(check) {
  const { requirement } = check;
  if (!Number.isFinite(requirement?.value)) return checkLabel(check);
  const value = `${numberText(requirement.value, { compact: true })} ${requirement.unit === '1' ? '' : requirement.unit}`.trim();
  const limit = t(check.key.startsWith('min_') ? 'design.constraint.min' : 'design.constraint.max', { value });
  return t('design.constraint.limit', { label: checkLabel(check), limit });
}

/** Pass, fail and unknown counts as chips; a record with no checkable requirement says so. */
function checkChips(checks) {
  if (!checks.length) return chip(t('design.check.none'), { tone: 'warn', small: true, title: t('design.check.noneTitle') });
  const counts = checkCounts(checks);
  const titleOf = (state) => checks.filter((check) => check.state === state).map(checkRule).join('\n');
  return el('span', { class: 'chip-row' },
    counts.fail ? chip(t('design.check.fail', { count: counts.fail }), { tone: 'fail', small: true, title: titleOf('fail') }) : null,
    counts.unknown ? chip(t('design.check.unknown', { count: counts.unknown }), { tone: 'warn', small: true, title: titleOf('unknown') }) : null,
    counts.pass ? chip(t('design.check.pass', { count: counts.pass }), { tone: 'pass', small: true, title: titleOf('pass') }) : null);
}

/** The Pareto state as a chip. `compact` (dense table) writes "≈ B" for "not distinguishable from B". */
function paretoCell(project, point, { compact = false } = {}) {
  const state = paretoState(point);
  const tones = { front: 'brand', dominated: null, unknown: 'warn' };
  const near = point.indistinguishable.map((id) => project.info.get(id).letter).join(', ');
  const nearText = t('design.pareto.near', { names: near });
  let nearNode = null;
  if (near) {
    nearNode = compact
      ? el('span', { class: 'design-near', title: nearText }, el('span', { 'aria-hidden': 'true' }, `≈ ${near}`),
        el('span', { class: 'visually-hidden' }, nearText))
      : el('span', { class: 'design-near' }, nearText);
  }
  return el('span', { class: 'chip-row' }, chip(t(`design.pareto.${state}`), { tone: tones[state], small: true }), nearNode);
}

let tips = 0; // unique ids for decision tooltips

/**
 * One decision as a chip: Accepted (outline), Deferred (amber), Rejected (grey, struck through).
 * The reason, reviewer and time show in the shared tooltip on hover and on keyboard focus,
 * and screen readers read them as the chip's description. `discipline` adds the discipline.
 */
function decisionChip(decision, { discipline = false, tip = true } = {}) {
  const action = t(`design.action.${decision.action}`);
  const text = discipline ? `${t(`design.discipline.${decision.discipline}`)}: ${action}` : action;
  const chipNode = el('span', { class: 'decision-chip', dataset: { action: decision.action } }, text);
  if (!tip) return chipNode;
  const detail = t('design.dec.chipDetail', { reason: decision.reason,
    by: t('design.dec.by', { reviewer: decision.designer_id, time: timeText(decision.recorded_at) }) });
  const id = `decision-tip-${++tips}`;
  chipNode.tabIndex = 0;
  chipNode.dataset.tipTitle = detail;
  chipNode.setAttribute('aria-describedby', id);
  return el('span', { class: 'decision-chip-wrap' }, chipNode, el('span', { id, class: 'visually-hidden' }, detail));
}

function notDecidedChip() {
  return el('span', { class: 'decision-chip', dataset: { action: 'none' } }, t('design.dec.notDecided'));
}

/** The current decisions of one candidate, or "Not decided". */
function decisionChips(project, candidateId) {
  const current = Object.values(decisionGrid([candidateId], project.decisions).get(candidateId)).filter(Boolean);
  if (project.decisionsError) return el('span', { class: 'design-missing' }, t('status.unknown'));
  return current.length
    ? el('span', { class: 'chip-row design-decision-chips' }, ...current.map((decision) => decisionChip(decision, { discipline: true })))
    : notDecidedChip();
}

function signedText(value, digits) {
  return numberFormat({ signDisplay: 'exceptZero', maximumFractionDigits: digits }).format(value);
}

/** "+6.4 (+2 %)", or "+6.4" when the parent value is zero. */
function deltaText(delta, deltaPercent, reference, unit) {
  const digits = summaryDigits(reference, unit) ?? 4;
  const percent = deltaPercent === null ? '' : ` (${signedText(deltaPercent, 1)} %)`;
  return `${signedText(delta, digits)}${percent}`;
}

function timeText(iso) {
  const time = Date.parse(iso);
  return Number.isFinite(time) ? new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(time) : iso;
}

/* ---------- Candidates ---------- */

/** "L +6.4 m (+2.0 %)" per variation parameter. */
function changeText(change) {
  const label = ABBREVIATIONS[change.key] || fieldLabel(change.key);
  const unit = change.quantity.unit === '1' ? '' : ` ${change.quantity.unit}`;
  if (change.delta === null) return `${label} ${numberText(change.quantity.value, { compact: true, unit: change.quantity.unit })}${unit}`;
  const digits = summaryDigits(change.base.value, change.quantity.unit) ?? 4;
  const percent = change.deltaPercent === null ? '' : ` (${signedText(change.deltaPercent, 1)} %)`;
  return `${label} ${signedText(change.delta, digits)}${unit}${percent}`;
}

/** A number with its band as "± 3,000" (or "no band") for a dense cell; the unit is in the header. */
function bandedNumber(quantity) {
  return el('span', { class: 'dv dv-compact' }, el('span', { class: 'dv-num' }, numberText(quantity.value, { compact: true })),
    quantity.uncertainty
      ? el('span', { class: 'dv-band' }, `± ${numberText(Math.max(quantity.uncertainty.lower, quantity.uncertainty.upper)
        * (quantity.uncertainty.kind === 'relative' ? Math.abs(quantity.value) : 1), { compact: true })}`)
      : el('span', { class: 'dv-noband', title: quantity.uncertainty_reason || t('design.notSupplied') }, t('design.noBandMark')));
}

function candidateRows(project) {
  return project.candidates.map((candidate) => {
    const cards = Object.fromEntries(designParticulars(candidate).map((card) => [card.key, card]));
    const point = project.points.find((item) => item.id === candidate.design_id);
    const counts = checkCounts(project.checks.get(candidate.design_id));
    const value = (key) => cards[key].quantity?.value ?? null;
    return {
      id: candidate.design_id, cards, point,
      name: `${project.info.get(candidate.design_id).letter} · ${candidate.name}`,
      change: variationChanges(candidate, project.parent).map(changeText).join(', ') || null,
      length: value('length'), beam: value('beam'), draft: value('draft'), cb: value('cb'),
      cargo: value('cargo_capacity'), fuel: value('fuel'),
      // Sorting puts failed checks last, then unknown ones.
      checks: counts.fail * 1000 + counts.unknown,
      pareto: ['front', 'dominated', 'unknown'].indexOf(paretoState(point)),
      decisions: Object.values(decisionGrid([candidate.design_id], project.decisions).get(candidate.design_id))
        .filter(Boolean).map((decision) => t(`design.action.${decision.action}`)).join(' '),
    };
  });
}

function unitOf(rows, key) {
  const units = new Set(rows.map((row) => row.cards[key].quantity?.unit).filter(Boolean));
  return units.size === 1 && !units.has('1') ? [...units][0] : undefined;
}

export function candidatesTab(project) {
  const rows = candidateRows(project);
  const numberColumn = (key, card, label) => ({
    key, label, unit: unitOf(rows, card), align: 'end',
    unknownText: t(designMissingKey(rows[0]?.cards[card].path || 'results.')),
    format: (_, row) => (key === 'cargo' || key === 'fuel' ? bandedNumber(row.cards[card].quantity)
      : numberText(row.cards[card].quantity.value, { compact: true, unit: row.cards[card].quantity.unit })),
  });
  const columns = [
    { key: 'name', label: t('design.name'), format: (name) => el('span', { class: 'design-list-name design-cand-name' }, name) },
    { key: 'change', label: t('design.cand.change'), unknownText: t('design.cand.noChange') },
    numberColumn('length', 'length', 'L'), numberColumn('beam', 'beam', 'B'), numberColumn('draft', 'draft', 'T'),
    numberColumn('cb', 'cb', 'Cb'),
    numberColumn('cargo', 'cargo_capacity', fieldLabel(CARGO)),
    numberColumn('fuel', 'fuel', fieldLabel(FUEL)),
    { key: 'checks', label: t('design.cand.checks'), format: (_, row) => checkChips(project.checks.get(row.id)) },
    { key: 'pareto', label: t('design.cand.pareto'), format: (_, row) => paretoCell(project, row.point, { compact: true }) },
    { key: 'decisions', label: t('design.cand.decisions'), sortable: false, format: (_, row) => decisionChips(project, row.id),
      unknownText: project.decisionsError ? t('status.unknown') : t('design.dec.notDecided') },
  ];
  return el('div', { class: 'design-tab-body' },
    el('section', { class: 'design-project-section' },
      el('div', { class: 'design-section-head' }, el('h2', {}, t('design.candidates')),
        el('span', { class: 'page-head-meta' }, t('design.cand.count', { count: rows.length }))),
      el('p', { class: 'design-facts' }, t('design.cand.lead')),
      createDataTable({ rows, columns, caption: t('design.cand.caption'), rowKey: (row) => row.id, onSelect: openDesign }).element));
}

/* ---------- Compare ---------- */

function chartFor(project) {
  return paretoChart(project.points, { info: project.info, checkLabel, onOpen: openDesign });
}

/** The value cell and, for a candidate, the delta cell beside it. Unknown is written out. */
function compareCells(row, entry, isParent) {
  const value = entry.state === 'unknown'
    ? el('td', { class: 'compare-value' }, missingText({ path: row.path }))
    : el('td', { class: 'table-num compare-value' }, quantityValue(entry.quantity, { compact: true }));
  if (isParent) return [value];
  const tone = deltaTone(row.path, entry.delta);
  let delta;
  if (entry.state === 'unknown') delta = el('span', { 'aria-hidden': 'true' }, '–');
  else if (entry.delta === null) delta = el('span', { class: 'design-missing' }, t('design.compare.noParentValue'));
  else {
    delta = el('span', { dataset: tone ? { tone } : {} },
      deltaText(entry.delta, entry.deltaPercent, row.parent.value ?? entry.value, entry.unit),
      tone ? el('span', { class: 'visually-hidden' }, ` (${t(`design.compare.${tone}`)})`) : null);
  }
  return [value, el('td', { class: 'table-num compare-delta' }, delta)];
}

/** "Fail (21.1 m)": the state chip and the value that was checked. */
function checkCell(check, colspan) {
  const tones = { pass: 'pass', fail: 'fail', unknown: 'warn' };
  const state = check?.state || 'unknown';
  const actual = check?.actual && Number.isFinite(check.actual.value)
    ? `(${numberText(check.actual.value, { compact: true, unit: check.actual.unit })} ${check.actual.unit === '1' ? '' : check.actual.unit})`.replace(' )', ')')
    : `(${t('design.pending')})`;
  return el('td', { colspan: colspan > 1 ? String(colspan) : null },
    el('span', { class: 'compare-check' }, chip(t(`design.check.state.${state}`), { tone: tones[state], small: true }),
      el('span', { class: 'compare-check-value' }, actual)));
}

// Main dimensions read in the order designers write them: L, B, T, D.
const DIMENSION_ORDER = ['length', 'beam', 'draft', 'depth'].map((key) => `main_dimensions.${key}`);
const rowRank = (row) => (DIMENSION_ORDER.includes(row.path) ? DIMENSION_ORDER.indexOf(row.path) : DIMENSION_ORDER.length);

function compareHead(project, design, isParent) {
  const fails = checkCounts(project.checks.get(design.design_id)).fail > 0;
  return el('th', { scope: 'colgroup', colspan: isParent ? null : '2', title: design.name,
    class: 'compare-design-head', dataset: fails ? { fails: 'true' } : {} },
  el('span', { class: 'compare-letter' }, isParent ? t('design.compare.parentHead') : project.info.get(design.design_id).letter),
  fails ? el('span', { class: 'compare-fails' }, t('design.compare.failsHeader')) : null,
  el('span', { class: 'compare-name' }, design.name));
}

function compareTable(project, chosenIds) {
  const chosen = chosenIds.map((id) => project.candidates.find((candidate) => candidate.design_id === id));
  const rows = compareRows(project.parent, chosen).map((row, index) => ({ row, index }))
    .sort((a, b) => rowRank(a.row) - rowRank(b.row) || a.index - b.index).map(({ row }) => row);
  const designs = [project.parent, ...chosen];
  const columnCount = 2 + chosen.length * 2;
  const checkKeys = [...new Set(designs.flatMap((design) => project.checks.get(design.design_id).map((check) => check.key)))];
  const head = el('tr', {}, el('th', { scope: 'col' }, t('design.compare.field')),
    ...designs.map((design, index) => compareHead(project, design, index === 0)));
  // The two Pareto axes (cargo and fuel) have a light tint: the rows the chart is about.
  const valueRows = rows.map((row) => el('tr', { class: row.path === CARGO || row.path === FUEL ? 'compare-axis' : null },
    el('th', { scope: 'row' }, fieldLabel(row.path)),
    ...compareCells(row, row.parent, true), ...row.candidates.flatMap((entry) => compareCells(row, entry, false))));
  const checkRows = checkKeys.map((key) => {
    const first = designs.map((design) => project.checks.get(design.design_id).find((check) => check.key === key)).find(Boolean);
    return el('tr', {}, el('th', { scope: 'row' }, checkRule(first)),
      ...designs.map((design, index) => checkCell(project.checks.get(design.design_id).find((check) => check.key === key), index ? 2 : 1)));
  });
  return el('div', { class: 'table-scroll compare-scroll' }, el('table', { class: 'data-table compare-table' },
    el('caption', { class: 'visually-hidden' }, t('design.compare.caption')),
    el('thead', {}, head),
    el('tbody', {}, ...valueRows),
    el('tbody', { class: 'compare-checks' },
      el('tr', {}, el('th', { scope: 'colgroup', colspan: String(columnCount) }, t('design.compare.checks'))),
      ...(checkRows.length ? checkRows : [el('tr', {}, el('td', { colspan: String(columnCount) },
        el('span', { class: 'design-missing' }, t('design.compare.noChecks'))))]))));
}

/** Chosen candidates as chips with a remove button, and a "+" list to add one. */
function compareChooser(project, chosen, onChange) {
  const info = (id) => project.info.get(id);
  const left = project.candidates.filter((candidate) => !chosen.includes(candidate.design_id));
  const add = el('select', { class: 'compare-add', 'aria-label': t('design.compare.add'),
    disabled: chosen.length >= COMPARE_LIMIT || !left.length,
    onchange: (event) => { if (event.target.value) onChange([...chosen, event.target.value]); } },
  el('option', { value: '' }, t('design.compare.addPlaceholder')),
  ...left.map((candidate) => el('option', { value: candidate.design_id }, `${info(candidate.design_id).letter} · ${candidate.name}`)));
  return el('div', { class: 'compare-chooser', role: 'group', 'aria-label': t('design.compare.choose') },
    el('span', { class: 'field-label' }, t('design.compare.choose')),
    el('ul', { class: 'compare-chips' },
      ...chosen.map((id) => el('li', {}, el('span', { class: 'compare-chip', title: info(id).name },
        el('span', { class: 'compare-letter' }, info(id).letter),
        el('button', { type: 'button', class: 'compare-remove', disabled: chosen.length <= 1,
          'aria-label': t('design.compare.remove', { name: `${info(id).letter} · ${info(id).name}` }),
          onclick: () => onChange(chosen.filter((other) => other !== id)) }, '×')))),
      el('li', {}, add)));
}

export function compareTab(project) {
  let chosen = defaultComparison(project.points, COMPARE_LIMIT);
  const host = el('div', { class: 'design-project-section' });
  function render(focusAdd = false) {
    fill(host, el('h2', {}, t('design.compare')),
      compareChooser(project, chosen, (next) => { chosen = next; render(true); }),
      chosen.length < 2 ? el('p', { class: 'design-facts', role: 'status' }, t('design.compare.chooseMore')) : null,
      el('p', { class: 'design-facts' }, t('design.compare.colourNote')),
      compareTable(project, chosen));
    // The chooser is rebuilt; keep the keyboard on it.
    if (focusAdd) (host.querySelector('.compare-add:not(:disabled)') || host.querySelector('.compare-remove:not(:disabled)'))?.focus();
  }
  render();
  return el('div', { class: 'design-tab-body' }, chartFor(project), host);
}

/* ---------- Decisions ---------- */

/** "Fuel 66 t/day · Cargo 350,000 m3" (or "Not calculated yet") under a candidate's change. */
function figuresLine(candidate) {
  const cards = Object.fromEntries(designParticulars(candidate).map((card) => [card.key, card]));
  const text = (card) => (card.kind === 'quantity'
    ? `${numberText(card.quantity.value, { compact: true, unit: card.quantity.unit })} ${card.quantity.unit}` : t(card.missingKey));
  return t('design.dec.figures', { fuel: text(cards.fuel), cargo: text(cards.cargo_capacity) });
}

/** The candidate cell of the matrix: letter, change summary, figures, failed or unknown checks. */
function candidateCell(project, candidate) {
  const { letter } = project.info.get(candidate.design_id);
  const checks = project.checks.get(candidate.design_id);
  const rules = (state) => checks.filter((check) => check.state === state).map(checkRule).join(', ');
  const summary = variationChanges(candidate, project.parent).map(changeText).join(', ') || candidate.name;
  return el('th', { scope: 'row' }, el('div', { class: 'decision-candidate' },
    el('span', { class: 'decision-letter', 'aria-hidden': 'true' }, letter),
    el('div', {},
      el('a', { href: `#design/${encodeURIComponent(candidate.design_id)}`, title: candidate.name },
        el('span', { class: 'visually-hidden' }, `${letter} · ${candidate.name}: `), summary),
      el('small', {}, figuresLine(candidate)),
      rules('fail') ? el('small', { class: 'decision-fails' }, t('design.check.failsLine', { checks: rules('fail') })) : null,
      rules('unknown') ? el('small', { class: 'decision-unknown' }, t('design.check.unknownLine', { checks: rules('unknown') })) : null)));
}

function decisionGridTable(project) {
  const grid = decisionGrid(project.candidates.map((candidate) => candidate.design_id), project.decisions);
  return el('div', { class: 'table-scroll' }, el('table', { class: 'data-table decision-grid' },
    el('caption', { class: 'visually-hidden' }, t('design.dec.gridCaption')),
    el('thead', {}, el('tr', {}, el('th', { scope: 'col' }, t('design.dec.candidate')),
      ...DISCIPLINES.map((key) => el('th', { scope: 'col' }, t(`design.discipline.${key}`))))),
    el('tbody', {}, ...project.candidates.map((candidate) => el('tr', {},
      candidateCell(project, candidate),
      ...DISCIPLINES.map((key) => {
        const decision = grid.get(candidate.design_id)[key];
        return el('td', {}, decision ? decisionChip(decision) : notDecidedChip());
      }))))));
}

function decisionLogTable(project) {
  const name = (id) => project.info.get(id) ? `${project.info.get(id).letter} · ${project.info.get(id).name}` : id;
  const rows = decisionLog(project.decisions).map((decision) => ({
    id: decision.id, time: decision.recorded_at, candidate: name(decision.candidate_id),
    discipline: t(`design.discipline.${decision.discipline}`), action: t(`design.action.${decision.action}`),
    decision, reason: decision.reason, reviewer: decision.designer_id,
  }));
  return createDataTable({ rows, caption: t('design.dec.logCaption'), emptyText: t('design.dec.noLog'), columns: [
    { key: 'time', label: t('design.dec.time'), format: timeText },
    { key: 'candidate', label: t('design.dec.candidate') },
    { key: 'discipline', label: t('design.dec.discipline') },
    // The reason has its own column here, so the chip needs no tooltip.
    { key: 'action', label: t('design.dec.action'), format: (_, row) => decisionChip(row.decision, { tip: false }) },
    { key: 'reason', label: t('design.dec.reason') },
    { key: 'reviewer', label: t('design.dec.reviewer') },
  ] }).element;
}

function field(id, label, control, help) {
  return el('div', { class: 'field' }, el('label', { class: 'field-label', for: id }, label), control,
    help ? el('span', { class: 'field-help', id: `${id}-help` }, help) : null);
}

/** Read and write the reviewer name; storage can be blocked, so both are wrapped. */
function rememberedReviewer(name) {
  try {
    if (name !== undefined) prefs.set('designReviewer', name);
    return prefs.get('designReviewer', '');
  } catch {
    return '';
  }
}

function decisionForm(project, onRecorded) {
  const id = `decision-${++forms}`;
  const candidate = el('select', { id: `${id}-candidate` }, ...project.candidates.map((item) =>
    el('option', { value: item.design_id }, `${project.info.get(item.design_id).letter} · ${item.name}`)));
  const discipline = el('select', { id: `${id}-discipline` }, ...DISCIPLINES.map((key) =>
    el('option', { value: key }, t(`design.discipline.${key}`))));
  const actions = el('fieldset', { class: 'field' }, el('legend', { class: 'field-label' }, t('design.dec.action')),
    el('div', { class: 'decision-actions' }, ...DECISION_ACTIONS.map((action) => el('label', { class: 'decision-action', dataset: { action } },
      el('input', { type: 'radio', name: `${id}-action`, value: action }),
      el('span', {}, t(`design.actionVerb.${action}`))))));
  const reason = el('textarea', { id: `${id}-reason`, rows: '3', required: true, 'aria-describedby': `${id}-reason-help` });
  const reviewer = el('input', { id: `${id}-reviewer`, type: 'text', required: true, autocomplete: 'name',
    value: rememberedReviewer(), 'aria-describedby': `${id}-reviewer-help` });
  const submit = el('button', { class: 'btn btn-primary', type: 'submit' }, t('design.dec.submit'));
  const message = el('p', { class: 'decision-message' });
  const showMessage = (text, isError) => {
    message.textContent = text;
    message.setAttribute('role', isError ? 'alert' : 'status');
    message.dataset.tone = isError ? 'fail' : 'pass';
  };
  async function onSubmit(event) {
    event.preventDefault();
    // No action is chosen in advance: a person must pick one, so a decision is never a default.
    const chosenAction = actions.querySelector('input:checked');
    const missing = [[actions.querySelector('input'), 'design.dec.actionRequired', !chosenAction],
      [reason, 'design.dec.reasonRequired', !reason.value.trim()],
      [reviewer, 'design.dec.reviewerRequired', !reviewer.value.trim()]].filter(([, , empty]) => empty);
    actions.dataset.invalid = String(!chosenAction);
    for (const input of [reason, reviewer]) input.setAttribute('aria-invalid', String(missing.some(([item]) => item === input)));
    if (missing.length) {
      showMessage(missing.map(([, key]) => t(key)).join(' '), true);
      missing[0][0].focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = t('design.dec.saving');
    try {
      await appendDesignDecision(project.parent.design_id, {
        candidate_id: candidate.value, discipline: discipline.value,
        action: chosenAction.value,
        reason: reason.value.trim(), designer_id: reviewer.value.trim(),
      });
      rememberedReviewer(reviewer.value.trim());
      reason.value = '';
      chosenAction.checked = false;
      await refreshDecisions(project);
      onRecorded();
      showMessage(t('design.dec.saved'), false);
    } catch (error) {
      showMessage(t('design.dec.error', { reason: error.message || String(error) }), true);
    } finally {
      submit.disabled = false;
      submit.textContent = t('design.dec.submit');
    }
  }
  return el('form', { class: 'decision-form', novalidate: true, onsubmit: onSubmit },
    el('div', { class: 'decision-form-row' },
      field(`${id}-candidate`, t('design.dec.candidate'), candidate),
      field(`${id}-discipline`, t('design.dec.discipline'), discipline)),
    actions,
    field(`${id}-reason`, t('design.dec.reason'), reason, t('design.dec.reasonHelp')),
    field(`${id}-reviewer`, t('design.dec.reviewer'), reviewer, t('design.dec.reviewerHelp')),
    el('div', { class: 'decision-submit' }, submit, message),
    el('p', { class: 'design-notice' }, t('design.dec.lead')));
}

/** The decisions tab. `onChange` runs after a decision is recorded (the Lite cards refresh). */
export function decisionsTab(project, { onChange } = {}) {
  const gridHost = el('div');
  const logHost = el('div', { class: 'decision-log' });
  const renderRecords = () => {
    fill(gridHost, project.decisionsError
      ? el('p', { role: 'alert' }, t('design.dec.loadError', { reason: project.decisionsError }))
      : decisionGridTable(project));
    fill(logHost, decisionLogTable(project));
  };
  renderRecords();
  // The matrix and the form side by side on a wide window; the log below both.
  return el('div', { class: 'design-tab-body' },
    el('div', { class: 'decision-layout' },
      el('section', { class: 'design-project-section' }, el('h2', {}, t('design.dec.current')), gridHost),
      el('section', { class: 'design-project-section decision-record' }, el('h2', {}, t('design.dec.record')),
        decisionForm(project, () => { renderRecords(); onChange?.(); }))),
    el('section', { class: 'design-project-section' }, el('h2', {}, t('design.dec.log')), logHost));
}

/* ---------- Lite ---------- */

function liteValue(card) {
  return card.kind === 'quantity' ? quantityValue(card.quantity, { compact: true, focusable: true }) : missingText(card);
}

function candidateCard(project, candidate) {
  const cards = Object.fromEntries(designParticulars(candidate).map((card) => [card.key, card]));
  const point = project.points.find((item) => item.id === candidate.design_id);
  const { letter } = project.info.get(candidate.design_id);
  return el('li', { class: 'design-candidate-card' },
    el('div', { class: 'design-candidate-head' },
      el('h3', {}, el('a', { href: `#design/${encodeURIComponent(candidate.design_id)}` },
        el('span', { class: 'compare-letter' }, letter), candidate.name)),
      chip(t('status.draft'), { tone: 'draft', small: true, title: t('design.draft') })),
    el('dl', { class: 'design-candidate-values' },
      el('div', {}, el('dt', {}, fieldLabel(CARGO)), el('dd', {}, liteValue(cards.cargo_capacity))),
      el('div', {}, el('dt', {}, fieldLabel(FUEL)), el('dd', {}, liteValue(cards.fuel)))),
    el('div', { class: 'design-candidate-states' },
      checkChips(project.checks.get(candidate.design_id)), paretoCell(project, point)),
    decisionChips(project, candidate.design_id));
}

/** Lite: the chart and one short card per candidate. Failed checks and unknowns stay. */
export function liteProject(project) {
  return el('div', { class: 'design-tab-body' }, chartFor(project),
    el('section', { class: 'design-project-section' }, el('h2', {}, t('design.lite.candidates')),
      el('ul', { class: 'design-candidate-list' }, ...project.candidates.map((candidate) => candidateCard(project, candidate)))));
}
