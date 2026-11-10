// MarinaFrame desktop UI: the entry module. It creates the views, installs the input
// handlers in a fixed order, then starts. Backend access goes only through api.js; the app
// state and its setters are in app_state.js. Each area of the UI has its own module:
//   home.js           Home and the Queue
//   run.js            opening a run, reading it again, live updates
//   run_header.js     breadcrumb, run actions, notices, narration and revision strips
//   run_strip.js      section strip, selected section, the decision per section
//   inspector.js      run-details tabs and hiding the column
//   workspace.js      drawing, 3D model, live run, layout, whole-vessel model
//   vessel_pages.js   Parts, Sources, Export and History tabs
//   new_vessel.js     intake, welcome, batch queue, New run sheet, dropped files
//   settings_view.js  Settings, theme, status bar
//   commands.js       sidebar, command palette, keyboard shortcuts (rules in keymap.js)
//   router.js         routes
//   ui_kit.js, artifacts.js, run_facts.js  shared helpers; run_facts.js has no DOM (tested)

import { prefs, setSettings, state } from './app_state.js';
import { invoke } from './api.js';
import { showError } from './ui_kit.js';
import { installTooltips } from './tooltip.js';
import {
  installShellControls, installRail, createPaletteAndShortcuts, installKeyboard,
} from './commands.js';
import { installHomeControls, renderHome } from './home.js';
import {
  createAreaCurve, installDetails, installTabs, installScrollEdges, selectTab,
} from './inspector.js';
import { createStartFlows, installStartControls, needsWelcome } from './new_vessel.js';
import { installRouter, routeFromHash, applyRoute, openRememberedTask } from './router.js';
import { installClock } from './run_header.js';
import { installStripKeys } from './run_strip.js';
import { installLiveUpdates, installRunActions, refreshDatasets, refreshTasks } from './run.js';
import {
  installSettings, applyTheme, loadSettingsForm, refreshAiStatus, renderStatusbar,
} from './settings_view.js';
import { createVesselPages, installVesselTabs } from './vessel_pages.js';
import {
  createWorkspace, installLayout, installWorkspaceControls, setLayout, setSplit,
} from './workspace.js';

/** Create the views and bind the input, in the order the page has always used. */
function install() {
  createWorkspace();
  installClock();
  createAreaCurve();
  installLiveUpdates();
  installLayout();
  installDetails();
  installSettings();
  createStartFlows();
  installStartControls();
  installRunActions();
  installHomeControls();
  installShellControls();
  createVesselPages();
  installWorkspaceControls();
  installVesselTabs();
  installTabs();
  installStripKeys();
  installRail();
  createPaletteAndShortcuts();
  installScrollEdges();
  installKeyboard();
  installRouter();
}

async function start() {
  installTooltips();
  setLayout(prefs.get('layout', 'split'));
  setSplit(prefs.get('split', 0.56));
  selectTab(prefs.get('tab', 'thinking'));
  renderHome(); // placeholders until the run list arrives
  const route = routeFromHash() || 'home';
  // Show the place at once (Home with placeholders, a run with "Opening the run…"); the
  // data fills in as it arrives. A first use goes to the welcome screen instead.
  const firstUse = route === 'home' && !prefs.get('setupSeen', false);
  if (firstUse) history.replaceState(null, '', '#welcome');
  applyRoute(firstUse ? 'welcome' : route);
  try {
    setSettings(await invoke('get_settings', {}));
    applyTheme(state.settings.theme);
    // A reload on Settings drew the form before the settings arrived: fill it now.
    if (state.route === 'settings') loadSettingsForm();
  } catch (error) {
    showError(error);
  }
  refreshDatasets();
  await Promise.all([refreshTasks(), refreshAiStatus()]);
  renderStatusbar();
  if (state.pendingOpen && state.route === 'run' && !state.task) openRememberedTask();
  // A reload keeps its place; the welcome screen only replaces Home.
  if (!firstUse && state.route === 'home' && await needsWelcome()) {
    history.replaceState(null, '', '#welcome');
    applyRoute('welcome');
  }
}

install();
start();
