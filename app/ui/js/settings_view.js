// Settings, the theme and the global status bar.

import { state, setSettings, setAiStatus, setDefaults, prefs, applyShowCosts } from './app_state.js';
import { transportName, invoke, canPickPaths, pickFolder, pickFile } from './api.js';
import { fill, icon, el } from './dom.js';
import { $, chip, showError, setChip, pathLabel } from './ui_kit.js';
import { navigate } from './router.js';
import { refreshTasks, refreshDatasets, loadTask } from './run.js';
import { model } from './workspace.js';

/** Global status bar: AI on or off, preview mode, runs folder. Run facts live in the run view. */
export function renderStatusbar() {
  renderThemeToggle();
  const status = state.aiStatus;
  const on = status ? status.active : null;
  const ai = $('status-ai');
  ai.dataset.state = on === null ? 'unknown' : on ? 'on' : 'off';
  ai.textContent = on === null ? 'AI unknown' : on ? 'AI on' : 'AI off';
  ai.title = aiStatusText(status);
  fill($('status-mode'), transportName === 'mock'
    ? chip('Preview', { dot: false, small: true, title: 'Preview data: sample runs, not your runs folder.' })
    : null);
  const folder = state.settings?.runs_folder || '';
  const folderNode = $('status-folder');
  folderNode.textContent = folder ? `Runs folder: ${folder.replace(/^\/Users\/[^/]+/, '~')}` : '';
  folderNode.title = folder;
}

// ---------------------------------------------------------------- settings and theme

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

export function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  model.refreshTheme();
}

// ---- Theme button in the status bar: System → Light → Dark, saved like the Settings choice.
export const THEME_ORDER = ['system', 'light', 'dark'];
const THEME_ICON = { system: 'auto', light: 'sun', dark: 'moon' };
export const THEME_WORD = { system: 'System', light: 'Light', dark: 'Dark' };

function renderThemeToggle() {
  const theme = state.settings?.theme || 'system';
  const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
  const button = $('theme-toggle');
  fill(button, icon(THEME_ICON[theme]), THEME_WORD[theme]);
  button.title = `Theme: ${THEME_WORD[theme]}. Click for ${THEME_WORD[next]}.`;
  button.setAttribute('aria-label', button.title);
}

/** Use and save a theme (the status-bar button and the palette). */
export async function setThemeChoice(theme) {
  if (!state.settings) return;
  applyTheme(theme);
  try {
    setSettings(await invoke('set_settings', { ...state.settings, theme }));
  } catch (error) {
    showError(error);
  }
  renderThemeToggle();
}

/** One line on whether new runs use the AI, and what to do when they cannot. Shown as a tooltip. */
function aiStatusText(status) {
  if (!status) return 'The AI reads the drawing and builds the draft.';
  if (!status.enabled) return 'Off: new runs use the deterministic draft and do not call the model.';
  if (!status.key_found && !status.claude_found) {
    return `No model route found, so new runs use the deterministic draft. Install and log in to Claude Code (the claude command), or put your OpenCode Go key in ${status.key_file} (one key per line, chmod 600).`;
  }
  const keys = status.key_count > 1 ? ` ${status.key_count} model keys found.` : '';
  if (!status.claude_found) {
    return `On: the claude command was not found, so the AI (Crouton, then DeepSeek, through OpenCode Go) reads the drawing and builds the draft.${keys}`;
  }
  const fallback = status.key_found ? ' If the Claude subscription is rate limited, Crouton, then DeepSeek, take over through OpenCode Go.' : '';
  return `On: the AI (Claude Sonnet 5.5 through your Claude subscription) reads the drawing and builds the draft.${fallback}${keys}`;
}

/** AI drafting setting: On, Off or No key. */
function showAiStatus(node, status) {
  if (status && !status.enabled) setChip(node, 'Off', null, aiStatusText(status));
  else if (status && !status.key_found && !status.claude_found) setChip(node, 'No model', 'warn', aiStatusText(status));
  else setChip(node, 'On', 'ai', aiStatusText(status));
}

/** Mode of the next run: AI draft or Deterministic. */
export function showRunMode(node, status) {
  if (status && !status.active) setChip(node, 'Deterministic', null, aiStatusText(status));
  else setChip(node, 'AI draft', 'ai', 'The AI reads the drawing and builds a draft. A person reviews it and signs it off.');
}

export async function refreshAiStatus() {
  try {
    setAiStatus(await invoke('get_ai_status'));
  } catch {
    setAiStatus(null);
  }
  return state.aiStatus;
}

/** Fresh-install settings (default runs folder, repo .venv Python). Read once; optional. */
async function loadDefaults() {
  if (!state.defaults) setDefaults(await invoke('get_default_settings', {}).catch(() => null));
  return state.defaults;
}

// ---- settings: path fields with pickers and one-click suggestions

const PATH_FIELDS = {
  runs_folder: { suggestions: 'runs-folder-suggestions', defaultLabel: 'Default' },
  worker_python: { suggestions: 'worker-python-suggestions', defaultLabel: 'Repo .venv' },
};

/** Under a path field: the detected default as a one-click choice, when it is not the value. */
function renderPathSuggestions(form, field) {
  const suggested = state.defaults?.[field];
  const current = form[field].value.trim();
  const box = $(PATH_FIELDS[field].suggestions);
  if (!suggested || suggested === current) {
    fill(box);
    return;
  }
  fill(box, el('button', {
    class: 'suggestion',
    type: 'button',
    title: `Use ${suggested}`,
    onclick: () => {
      form[field].value = suggested;
      renderPathSuggestions(form, field);
    },
  }, chip(PATH_FIELDS[field].defaultLabel, { dot: false, small: true }), pathLabel(suggested)));
}

/** Fill the Settings view from the saved settings. Called when the view opens. */
/**
 * Under the Worker Python field: the Python runs use now. An empty field is allowed: the app
 * then looks for MARINAFRAME_WORKER_PYTHON, the runtime inside the app bundle, or the repository .venv.
 */
async function showWorkerInUse() {
  const line = $('worker-python-in-use');
  const setup = await invoke('get_setup_status', {}).catch(() => null);
  const worker = setup?.worker;
  if (!worker) return fill(line);
  fill(line, worker.ok ? `In use: ${worker.path}. ${worker.message}` : `${worker.message} Choose a Python, or leave the field empty to find one automatically.`);
  line.classList.toggle('field-warn', !worker.ok);
}

export async function loadSettingsForm() {
  const form = $('settings-form');
  const s = state.settings || { runs_folder: '', worker_python: '', theme: 'system', ai_drafting: true };
  form.runs_folder.value = s.runs_folder;
  form.worker_python.value = s.worker_python;
  form.theme.value = s.theme;
  form.ai_drafting.checked = s.ai_drafting !== false;
  form.notify_finished.checked = s.notify_finished !== false;
  form.show_costs.checked = prefs.get('showCosts', false) === true;
  const [status] = await Promise.all([refreshAiStatus(), loadDefaults(), showWorkerInUse()]);
  showAiStatus($('ai-status'), status);
  for (const field of Object.keys(PATH_FIELDS)) renderPathSuggestions(form, field);
  for (const button of form.querySelectorAll('[data-pick]')) button.hidden = !canPickPaths();
  $('settings-error').hidden = true;
  setChip($('notices-reset-status'), 'Hidden', null, 'Notices you close stay hidden until you show them again.');
  $('reset-notices').disabled = false;
  renderStatusbar();
}

export function openSettings() {
  navigate('settings');
}

/** Leave Settings without saving: undo the theme preview, go back. */
function closeSettings() {
  applyTheme(state.settings?.theme || 'system');
  navigate(state.previousRoute);
}

/** The theme button and the Settings form. */
export function installSettings() {
  systemDark.addEventListener('change', () => model.refreshTheme());
  $('theme-toggle').addEventListener('click', () => {
    const current = state.settings?.theme || 'system';
    setThemeChoice(THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length]);
  });
  $('settings-form').addEventListener('change', (event) => {
    if (event.target.name === 'theme') applyTheme(event.target.value);
    // A per-viewer choice, not a backend setting: it applies and is kept at once.
    if (event.target.name === 'show_costs') applyShowCosts(event.target.checked, { remember: true });
    if (event.target.name === 'ai_drafting') {
      // Preview the chip for the new value; the saved setting decides the next run.
      const enabled = event.target.checked;
      showAiStatus($('ai-status'), state.aiStatus ? { ...state.aiStatus, enabled } : { enabled, key_found: true });
    }
  });
  $('settings-form').addEventListener('input', (event) => {
    if (event.target.name in PATH_FIELDS) renderPathSuggestions(event.currentTarget, event.target.name);
  });
  $('settings-form').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-pick]');
    if (!button) return;
    const form = event.currentTarget;
    const field = button.dataset.field;
    const current = form[field].value.trim() || state.defaults?.[field] || undefined;
    const pick = button.dataset.pick === 'folder' ? pickFolder : pickFile;
    try {
      const path = await pick({ title: button.dataset.title, defaultPath: current });
      if (!path) return;
      form[field].value = path;
      renderPathSuggestions(form, field);
    } catch (error) {
      $('settings-error').textContent = error.message;
      $('settings-error').hidden = false;
    }
  });
  $('settings-cancel').addEventListener('click', closeSettings);
  $('settings-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const next = {
      runs_folder: form.runs_folder.value.trim(),
      worker_python: form.worker_python.value.trim(),
      theme: form.theme.value,
      ai_drafting: form.ai_drafting.checked,
      notify_finished: form.notify_finished.checked,
    };
    $('settings-save').disabled = true;
    try {
      const folderChanged = next.runs_folder !== state.settings?.runs_folder;
      setSettings(await invoke('set_settings', next));
      applyTheme(state.settings.theme);
      await refreshAiStatus();
      renderStatusbar();
      navigate(state.previousRoute);
      if (folderChanged) {
        await refreshTasks();
        refreshDatasets();
      }
    } catch (error) {
      $('settings-error').textContent = error.message;
      $('settings-error').hidden = false;
    } finally {
      $('settings-save').disabled = false;
    }
  });
  $('reset-notices').addEventListener('click', async () => {
    try {
      await invoke('reset_notices', {});
      setChip($('notices-reset-status'), 'Restored', 'pass', 'Dismissed notices are back.');
      $('reset-notices').disabled = true;
      if (state.task) loadTask();
    } catch (error) {
      $('settings-error').textContent = error.message;
      $('settings-error').hidden = false;
    }
  });
}
