// Starting work: the drawing-set intake, the welcome and setup check, the batch queue, the
// sample vessel, the developer New run sheet and files dropped on the window.

import { prefs, setSettings, state, setQueue } from './app_state.js';
import {
  invoke, pickFile, pickFolder, canPickPaths, transportName, pickDrawingFiles, canPickSpecFile,
  pickSpecFile, isSpecFileName, isDrawingFileName, SPEC_EXTENSIONS, onFileDrop,
} from './api.js';
import { fill, el, icon } from './dom.js';
import { $, showError, fileName, pathLabel } from './ui_kit.js';
import { createBatch } from './batch.js';
import { createIntake } from './intake.js';
import { createUsage } from './usage.js';
import { createWelcome } from './welcome.js';
import { renderQueue } from './home.js';
import { navigate } from './router.js';
import { refreshTasks, openTask, refreshTasksSoon, runAction } from './run.js';
import { refreshAiStatus, renderStatusbar, openSettings, showRunMode } from './settings_view.js';

/** How many recently started spec files the New run sheet offers. */
const RECENT_SPECS_MAX = 5;

export let intake, welcome, batch;

/** Create the intake, welcome and batch views, and the key usage meter in Settings. */
export function createStartFlows() {
  intake = createIntake({
    host: $('view-intake'),
    invoke,
    refreshAiStatus: async () => {
      const status = await refreshAiStatus();
      renderStatusbar();
      return status;
    },
    onStarted: async (task) => {
      await refreshTasks();
      await openTask(task);
    },
    onClose: () => navigate('home'),
    openSettings: () => openSettings(),
  });

  welcome = createWelcome({
    host: $('view-welcome'),
    invoke,
    pickFile,
    pickFolder,
    canPickPaths,
    onDone: async () => {
      prefs.set('setupSeen', true);
      setSettings(await invoke('get_settings', {}).catch(() => state.settings));
      await refreshAiStatus();
      renderStatusbar();
      refreshTasks();
      navigate('home');
    },
    openSettings: () => openSettings(),
  });
  $('open-setup').addEventListener('click', () => navigate('welcome'));
  // Key usage (Settings > AI): read only when the person asks.
  $('key-usage-host').replaceWith(createUsage({ invoke }).element);

  // Batch queue: a folder or several drawing sets at once (js/batch.js).
  batch = createBatch({
    invoke,
    showError,
    aiActive: () => state.aiStatus?.active !== false,
    onQueued: (queue) => {
      setQueue(queue);
      navigate('queue');
      renderQueue();
      refreshTasksSoon();
    },
  });
}

// ---------------------------------------------------------------- intake (drawing set)

// A drawing set dropped on the window, or chosen with "Choose files", goes to the intake
// view (js/intake.js). Start reading opens the new run's live screen.

/** At start: the welcome screen on first use, or when the worker or runs folder is not ready. */
export async function needsWelcome() {
  if (!prefs.get('setupSeen', false)) return true;
  try {
    const status = await welcome.check();
    return !status.worker.ok || !status.runs_folder.ok;
  } catch {
    return false;
  }
}

/** Read a drawing set and show it in the intake view. */
async function startIntake(paths) {
  const reading = intake.prepare(paths); // marks the set as loading before the view opens
  navigate('intake');
  try {
    await reading;
  } catch (error) {
    showError(error);
    if (state.route === 'intake' && !intake.hasSet()) navigate('home');
  }
}


/**
 * Dropped or chosen drawings and folders: one set opens the intake (the person checks the
 * views); several sets open the batch sheet, which queues one run per set.
 */
async function openDrawings(paths) {
  const plan = await invoke('plan_batch', { paths });
  if (plan.sets.length > 1) {
    await refreshAiStatus(); // the sheet says when the sets can only wait
    batch.open(plan);
  }
  else if (plan.sets.length === 1) await startIntake(plan.sets[0].files);
  else throw new Error(plan.skipped[0] ? `${fileName(plan.skipped[0].path)}: ${plan.skipped[0].reason}` : 'No drawing was found. Drop PDF, PNG, TIFF or JPEG files.');
}

/** Choose a folder of drawing sets (each PDF and each subfolder is one set). */
export async function chooseDrawingFolder() {
  try {
    const folder = await pickFolder({ title: 'Choose a folder of drawing sets' });
    // Without a folder dialog (the browser preview), the mock folder shows the sheet.
    const path = folder || (transportName === 'mock' ? '/mock/Yard order/' : null);
    if (path) await openDrawings([path]);
  } catch (error) {
    showError(error);
  }
}

export async function chooseDrawingSet() {
  try {
    const paths = await pickDrawingFiles();
    if (paths.length) await openDrawings(paths);
  } catch (error) {
    showError(error);
  }
}

/** The built-in sample vessel (a generated drawing): a whole run without the person's files. */
export async function startSampleRun() {
  let task = null;
  const started = await runAction('Starting the sample vessel…', async () => {
    ({ task } = await invoke('start_sample_run', {}));
  });
  if (!started || !task) return;
  await refreshTasks();
  await openTask(task);
}

// ---------------------------------------------------------------- new run (developers: a spec file)

// The spec file is chosen with the picker, by dropping it on the window, from the recent
// list or from a dataset folder. Typing a path is the fallback under "Type a path".

function recentSpecs() {
  const recent = prefs.get('recentSpecs', []);
  return Array.isArray(recent) ? recent.filter((p) => typeof p === 'string') : [];
}

function rememberSpec(path) {
  prefs.set('recentSpecs', [path, ...recentSpecs().filter((p) => p !== path)].slice(0, RECENT_SPECS_MAX));
}

function showNewRunError(message) {
  $('newrun-error').textContent = message;
  $('newrun-error').hidden = !message;
}

function setSpecPath(path) {
  $('newrun-form').spec_path.value = path;
  showNewRunError('');
  renderSpecChoice();
}

/** Show the chosen spec (or the picker when there is none) and enable Start run. */
function renderSpecChoice() {
  const path = $('newrun-form').spec_path.value.trim();
  $('spec-empty').hidden = Boolean(path);
  $('spec-chosen').hidden = !path;
  fill($('spec-chosen-label'), path ? pathLabel(path) : null);
  $('newrun-start').disabled = !path;
  for (const button of $('recent-specs').querySelectorAll('[data-path]')) {
    button.setAttribute('aria-pressed', String(button.dataset.path === path));
  }
}

function renderSpecShortcuts() {
  const recent = recentSpecs();
  $('recent-specs-field').hidden = !recent.length;
  fill($('recent-specs'), ...recent.map((path) => el('button', {
    class: 'choice',
    type: 'button',
    role: 'listitem',
    dataset: { path },
    onclick: () => setSpecPath(path),
  }, icon('file'), pathLabel(path))));

  const canBrowse = canPickSpecFile() && transportName !== 'http'; // the web build uploads, it has no folders
  $('dataset-specs-field').hidden = !canBrowse || !state.datasets.length;
  fill($('dataset-specs'), ...state.datasets.map((dataset) => el('button', {
    class: 'btn btn-small dataset-choice',
    type: 'button',
    title: `Choose a run spec in ${dataset.path}`,
    onclick: () => chooseSpec(dataset.path),
  }, icon('folder'), el('span', { class: 'dataset-name' }, dataset.name))));
}

/** Show the file dialog, starting in `defaultPath` when given. */
async function chooseSpec(defaultPath) {
  try {
    const path = await pickSpecFile({ defaultPath });
    if (path) setSpecPath(path);
  } catch (error) {
    showNewRunError(error.message);
  }
}

/** Open the New run sheet. `browse` is a dataset whose folder the file dialog opens in. */
export async function openNewRun({ browse = null } = {}) {
  const sheet = $('newrun-sheet');
  if (sheet.open) return;
  const form = $('newrun-form');
  form.spec_path.value = '';
  showNewRunError('');
  showRunMode($('newrun-mode'), await refreshAiStatus());
  const canPick = canPickSpecFile();
  $('pick-spec').hidden = !canPick;
  $('change-spec').hidden = !canPick;
  $('typed-spec').open = !canPick;
  renderSpecShortcuts();
  renderSpecChoice();
  sheet.showModal();
  (canPick ? $('pick-spec') : form.spec_path).focus();
  if (browse) chooseSpec(browse.path);
}

/**
 * Files dropped on the window. Drawings (PDF, PNG, TIFF, JPEG) start an intake. A run spec
 * opens the developer New run sheet, as does any drop while that sheet is open.
 */
async function acceptDroppedFiles(paths) {
  if (!paths.length || state.route === 'settings') return;
  const sheetOpen = $('newrun-sheet').open;
  const spec = paths.find((path) => isSpecFileName(path));
  const drawings = paths.filter((path) => isDrawingFileName(path));
  if (sheetOpen || (spec && !drawings.length)) {
    if (!sheetOpen) await openNewRun();
    if (spec) {
      setSpecPath(spec);
      $('newrun-start').focus();
      return;
    }
    const types = SPEC_EXTENSIONS.slice(0, 3).map((ext) => `.${ext}`).join(', ');
    showNewRunError(`${fileName(paths[0])} is not a run spec. Drop the run spec (${types}) that names the drawing.`);
    return;
  }
  // Drawings and folders: one set opens the intake, several the batch sheet.
  try {
    await openDrawings(paths);
  } catch (error) {
    showError(error);
  }
}


/** The sample vessel button, files dropped on the window and the New run sheet. */
export function installStartControls() {
  $('try-sample').addEventListener('click', () => startSampleRun());

  onFileDrop({
    enter: () => document.body.classList.add('dragging-file'),
    leave: () => document.body.classList.remove('dragging-file'),
    drop: (paths) => {
      document.body.classList.remove('dragging-file');
      acceptDroppedFiles(paths);
    },
  });

  $('pick-spec').addEventListener('click', () => chooseSpec());
  $('change-spec').addEventListener('click', () => chooseSpec());
  $('newrun-form').spec_path.addEventListener('input', () => renderSpecChoice());
  $('newrun-cancel').addEventListener('click', () => $('newrun-sheet').close());
  $('newrun-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const specPath = event.target.spec_path.value.trim();
    if (!specPath) return;
    const start = $('newrun-start');
    start.disabled = true;
    start.textContent = 'Starting…';
    showNewRunError('');
    try {
      const { task } = await invoke('start_run', { spec_path: specPath });
      rememberSpec(specPath);
      $('newrun-sheet').close();
      await refreshTasks();
      await openTask(task);
    } catch (error) {
      showNewRunError(error.message);
    } finally {
      start.disabled = false;
      start.textContent = 'Start run';
    }
  });
}
