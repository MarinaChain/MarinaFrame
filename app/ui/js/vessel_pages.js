// Vessel tabs in the title bar: Run | Parts | Sources | Export | History, and their pages.

import { setVesselTabState, state } from './app_state.js';
import { invoke } from './api.js';
import { el, fill, icon } from './dom.js';
import * as fmt from './format.js';
import { $, statusBadge, chip, showError } from './ui_kit.js';
import { toCheckCount, partsToCheck, vesselOfTask, runNumber } from './run_facts.js';
import { evidencePageUrl, clearPreviews } from './artifacts.js';
import { renderChanges, buildChanges } from './changes.js';
import { createExport } from './export.js';
import { createParts } from './parts.js';
import { renderSheetHistory } from './sheets.js';
import { costWords } from './run_status.js';
import { createSources } from './sources.js';
import { sectionPlace, placesIn } from './run_strip.js';
import { openTask, loadTaskSoon, refreshTasksSoon } from './run.js';
import { model, setPartOutline, showWholeVessel } from './workspace.js';

// ---------------------------------------------------------------- vessel tabs: Run | Parts | Sources | Export | History

const VESSEL_TABS = ['run', 'parts', 'sources', 'export', 'history'];

export function setVesselTab(tab) {
  if (!VESSEL_TABS.includes(tab)) return;
  setVesselTabState(tab);
  renderVesselPage();
}

/** Show the chosen vessel tab. Run is the workspace; Export and History are full-width pages. */
export function renderVesselPage() {
  // Parts shows only for a run with whole-vessel parts; without them the tab falls back to Run.
  const hasParts = Boolean(state.view?.components?.length);
  if (state.vesselTab === 'parts' && !hasParts && state.view) setVesselTabState('run');
  $('vessel-tabs').querySelector('[data-vtab="parts"]').hidden = !hasParts;
  const tab = state.vesselTab;
  for (const button of $('vessel-tabs').querySelectorAll('[data-vtab]')) {
    button.setAttribute('aria-selected', String(button.dataset.vtab === tab));
    button.tabIndex = button.dataset.vtab === tab ? 0 : -1;
  }
  $('view-run').dataset.vtab = tab;
  for (const page of document.querySelectorAll('.vessel-page')) page.hidden = page.dataset.vtab !== tab;
  // The layout switch only means something on the Run tab.
  $('view-switch').hidden = tab !== 'run';
  $('details-toggle').hidden = tab !== 'run';
  if (tab === 'export') exporter.show(state.task, state.view, toCheckCount(state.view), partsToCheck(state.view));
  if (tab === 'history') renderHistory();
  if (tab === 'parts') parts.show(state.view);
  if (tab === 'sources') sources.show(state.task, sourcesKey(state.view));
}

/** Changes when the run's files may have changed: a new revision or a replaced sheet. */
export function sourcesKey(view) {
  return `${view?.revision ?? ''}|${view?.sheet_review?.history?.length ?? 0}`;
}



/** History: every run of this vessel, newest first. */
export function renderHistory() {
  const host = $('vessel-page-history');
  const vessel = vesselOfTask(state.tasks, state.task);
  const runs = vessel?.runs || [];
  const row = (run) => {
    const current = run.task === state.task;
    return el('li', {},
      el('button', {
        class: 'history-row',
        type: 'button',
        'aria-current': current ? 'true' : null,
        title: run.task,
        onclick: () => { setVesselTab('run'); openTask(run.task); },
      },
      el('span', { class: 'history-run' }, `Run ${runNumber(vessel, run.task)}`),
      statusBadge(run.status),
      el('span', { class: 'history-facts' }, fmt.countOf(run.sections, 'section')),
      el('span', { class: 'history-chips' },
        current && state.view?.sign_off ? chip('Signed off', { tone: 'pass', dot: false, small: true, title: `Signed off by ${state.view.sign_off.name}: ${state.view.sign_off.statement}` }) : null,
        current ? chip('Open', { tone: 'brand', dot: false, small: true }) : null),
      el('span', { class: 'history-time', title: fmt.fullTime(run.updated_ms) }, fmt.relativeTime(run.updated_ms))));
  };
  fill(host, el('div', { class: 'page-body history-page' },
    el('header', { class: 'page-head' },
      el('h1', { id: 'history-title' }, 'History'),
      vessel ? el('span', { class: 'page-head-meta' }, `${vessel.name} · ${fmt.plural(runs.length, 'run')}`) : null),
    runs.length
      ? el('ul', { class: 'history-list' }, ...runs.map(row))
      : el('div', { class: 'page-empty' }, icon('queue'), el('p', {}, 'No runs of this vessel yet.')),
    // Costs and timings: hidden on the Run tab by default, always here.
    costWords(state.view) ? el('p', { class: 'history-cost' },
      `Run ${vessel ? runNumber(vessel, state.task) : 1}: ${costWords(state.view)}`) : null,
    renderSheetHistory(state.view?.sheet_review?.history),
    state.task ? changesSection(vessel) : null));
}

/** "Changes in Run N": what each revision of the open run changed (js/changes.js). */
function changesSection(vessel) {
  const task = state.task;
  const body = el('div', { class: 'changes-body' }, el('p', { class: 'panel-empty' }, 'Reading the steps…'));
  invoke('get_live_steps', { task, after_sequence: 0 })
    .then((live) => { if (task === state.task) fill(body, renderChanges(buildChanges(live.steps), { pageUrl: evidencePageUrl, placeOf: sectionPlace, placesIn })); })
    .catch(() => fill(body, el('p', { class: 'panel-empty' }, 'The steps of this run could not be read.')));
  const run = vessel ? `Run ${runNumber(vessel, task)}` : 'this run';
  return el('section', { class: 'changes', 'aria-labelledby': 'changes-title' },
    el('h2', { class: 'page-subtitle', id: 'changes-title' }, `Changes in ${run}`),
    body);
}

/** After a part review or a sign-off: Home cards and the open run read the change. Passes the result on. */
export function afterPartsChange(result) {
  clearPreviews();
  loadTaskSoon();
  refreshTasksSoon();
  return result;
}

export let exporter, sources, parts;

/** Create the Export, Sources and Parts pages. */
export function createVesselPages() {
  // The report's hero picture is the 3D view as it is now, but only while the view shows this run's model.
  exporter = createExport({
    host: $('vessel-page-export'),
    invoke,
    captureView: (task, revision) => (state.task === task && state.modelKey?.startsWith(`${task}|${revision}|`) ? model.captureImage() : null),
  });
  // Sources tab (js/sources.js): the files the run was given, and a large view of each page.
  sources = createSources({ host: $('vessel-page-sources'), invoke });
  // Parts tab (js/parts.js): whole-vessel components with per-part review.
  parts = createParts({
    host: $('vessel-page-parts'),
    review: (id, decision, note = null) => invoke('review_component', { task: state.task, component_id: id, decision, note }).then(afterPartsChange, (error) => { showError(error); throw error; }),
    // Sign off the parts (a person's record, the run stays a draft); an empty name withdraws it.
    signOff: (name) => invoke('sign_off', { task: state.task, name }).then(afterPartsChange, (error) => { showError(error); throw error; }),
    // Re-run one part from its mark note (minutes), then keep or undo the new revision.
    revisePart: (id) => invoke('revise_part', { task: state.task, component_id: id }).then(afterPartsChange, (error) => { showError(error); throw error; }),
    keepRevision: (id) => invoke('keep_part_revision', { task: state.task, component_id: id }).then(afterPartsChange, (error) => { showError(error); throw error; }),
    undoRevision: (id) => invoke('undo_part_revision', { task: state.task, component_id: id }).then(afterPartsChange, (error) => { showError(error); throw error; }),
    showIn3d: (part) => {
      setVesselTab('run');
      setPartOutline(part);
    },
    // The selected part is the one outlined (and, with the whole vessel shown, tinted) in 3D.
    onSelect: (part) => setPartOutline(part),
    showWholeVessel: (part) => showWholeVessel(part),
    // The sounding table of one tank of the run's capacity plan (read from the run's CSV file).
    loadSounding: (tankId) => invoke('sounding_table', { task: state.task, tank_id: tankId }),
  });
}

/** Clicks on the vessel tabs. */
export function installVesselTabs() {
  $('vessel-tabs').addEventListener('click', (event) => {
    const tab = event.target.closest('[data-vtab]');
    if (tab) setVesselTab(tab.dataset.vtab);
  });
}
