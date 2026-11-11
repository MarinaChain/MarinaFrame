// The open run: opening, reading it again, busy actions and live task-changed updates.

import {
  setBusyText, state, setTaskList, setDatasets, setOpenTask, prefs, nextLoadToken, setView,
  setEvents, setSectionId, setPlacesKey, isRunning,
} from './app_state.js';
import { invoke, pickDrawingFiles, onTaskChanged } from './api.js';
import { fill, el } from './dom.js';
import { $, showError, debounce } from './ui_kit.js';
import { defaultSection } from './run_facts.js';
import { renderSheetReview } from './sheets.js';
import { renderRailCount, renderHome, renderQueue } from './home.js';
import { renderTabs, renderDetailsBadge, appendEvents } from './inspector.js';
import { navigate } from './router.js';
import {
  renderActions, renderCrumbs, renderNotices, renderDraftSummary, renderNarration,
  renderRevisionStrip,
} from './run_header.js';
import { renderSelection, renderStrip } from './run_strip.js';
import { renderHistory } from './vessel_pages.js';
import { live, setPartOutline, model, markTool, renderDrawing, renderModel } from './workspace.js';

/** Delay before re-reading a task after a burst of task-changed events. */
const REFRESH_DEBOUNCE_MS = 250;
const LIST_REFRESH_DEBOUNCE_MS = 600;

function setBusy(text) {
  setBusyText(text);
  const progress = $('status-progress');
  progress.classList.remove('error');
  fill(progress, ...(text ? [el('span', { class: 'spinner', 'aria-hidden': 'true' }), text] : []));
  renderActions();
  renderSelection();
}

/** Run one backend action with progress in the status bar. Only one runs at a time. */
export async function runAction(progressText, action) {
  if (state.busy) return false;
  setBusy(progressText);
  try {
    await action();
    return true;
  } catch (error) {
    showError(error);
    return false;
  } finally {
    setBusy(null);
  }
}

export async function refreshTasks() {
  try {
    const [tasks, queue] = await Promise.all([
      invoke('list_tasks', {}),
      invoke('get_queue', {}).catch(() => null),
    ]);
    setTaskList(tasks, queue);
    renderRailCount();
    renderHome();
    renderQueue();
    renderCrumbs();
    if (state.route === 'run' && state.vesselTab === 'history') renderHistory();
  } catch (error) {
    showError(error);
  }
}
export const refreshTasksSoon = debounce(refreshTasks, LIST_REFRESH_DEBOUNCE_MS);

export async function refreshDatasets() {
  try {
    setDatasets(await invoke('list_datasets', {}));
  } catch {
    setDatasets([]);
  }
}

// ---------------------------------------------------------------- opening a task

export async function openTask(task) {
  if (task === state.task) {
    navigate('run');
    return;
  }
  setOpenTask(task);
  prefs.set('lastTask', task);
  live.open(task);
  navigate('run');
  // Clear the previous run at once: its drawing and model must not show under this name.
  setPartOutline(null);
  model.setWholeVessel(null);
  $('hull-only').hidden = true;
  renderTask({ fresh: true });
  await loadTask({ fresh: true });
}

/** Read the open task again. `fresh` resets the view to its defaults. */
export async function loadTask({ fresh = false } = {}) {
  const token = nextLoadToken();
  const task = state.task;
  try {
    const [view, events] = await Promise.all([
      invoke('get_task', { task }),
      fresh ? invoke('get_events', { task, after_sequence: 0 }) : Promise.resolve(null),
    ]);
    if (token !== state.loadToken) return;
    setView(view);
    if (events) {
      setEvents(events);
    }
    if (!view.sections.some((s) => s.id === state.sectionId)) setSectionId(defaultSection(view));
    renderTask({ fresh });
    live.statusChanged();
    // Step cards name sections by place; when the places are known or change, draw them again.
    const placesKey = view.sections.map((s) => `${s.id}@${s.x_m}`).join(',');
    if (placesKey !== state.placesKey) {
      setPlacesKey(placesKey);
      live.placesChanged();
    }
    markTool.refresh();
  } catch (error) {
    if (token === state.loadToken) showError(error);
  }
}
export const loadTaskSoon = debounce(() => loadTask(), REFRESH_DEBOUNCE_MS);

/** Replace one sheet of the drawing set: keep the draft and retry that sheet's outputs. */
export async function replaceSheet(sheetId) {
  const task = state.task;
  const files = await pickDrawingFiles({ multiple: false });
  if (!files.length || task !== state.task) return;
  if (files.length !== 1) { showError(new Error('Choose one replacement file.')); return; }
  if (await runAction('Replacing the sheet…', () => invoke('replace_sheet', { task, sheet_id: sheetId, file: files[0] }))) {
    await loadTask({ fresh: true });
  }
}

function renderTask({ fresh = false } = {}) {
  renderCrumbs();
  renderActions();
  renderNotices();
  renderDraftSummary();
  fill($('sheet-review'), renderSheetReview(state.view?.sheet_review, {
    busy: state.busy || isRunning(),
    onReplace: replaceSheet,
  }));
  renderNarration();
  renderStrip();
  renderSelection();
  renderTabs();
  renderDetailsBadge();
  renderRevisionStrip();
  renderDrawing({ fresh });
  renderModel();
}

export function renderNoTask() {
  setView(null);
  renderTask({ fresh: true });
}

/** Read new steps when the backend says a task changed. */
export function installLiveUpdates() {
  onTaskChanged(async ({ task, sequence }) => {
    refreshTasksSoon();
    live.poke(task);
    if (task !== state.task || sequence <= state.lastSequence) return;
    try {
      const events = await invoke('get_events', { task, after_sequence: state.lastSequence });
      if (task !== state.task || !events.length) return;
      appendEvents(events.filter((e) => e.sequence > state.lastSequence));
      loadTaskSoon();
    } catch (error) {
      showError(error);
    }
  });
}

/** Stop and Resume in the title bar. */
export function installRunActions() {
  $('cancel-task').addEventListener('click', async () => {
    const task = state.task;
    if (await runAction('Stopping the run…', () => invoke('cancel_task', { task }))) {
      await loadTask();
      refreshTasks();
    }
  });
  $('resume-task').addEventListener('click', async () => {
    const task = state.task;
    if (await runAction('Resuming the run…', () => invoke('resume_task', { task }))) {
      await loadTask();
      refreshTasks();
    }
  });
}
