// App-wide input: the sidebar, the command palette, the shortcut sheet and keyboard shortcuts.

import { t } from './i18n.js';
import { prefs, state, currentSection, isRunning } from './app_state.js';
import * as fmt from './format.js';
import { $ } from './ui_kit.js';
import { needsCheck, groupVessels } from './run_facts.js';
import { shortcutCommand } from './keymap.js';
import { createPalette } from './palette.js';
import { partState } from './parts.js';
import { createShortcutSheet } from './shortcuts.js';
import { detailsAreOpen, toggleDetails } from './inspector.js';
import { chooseDrawingSet, chooseDrawingFolder, startSampleRun, openNewRun } from './new_vessel.js';
import { navigate } from './router.js';
import {
  nextToCheck, canDecide, acceptCandidate, decide, otherCandidate, selectSection, stepSection,
} from './run_strip.js';
import { openTask } from './run.js';
import { openSettings, THEME_ORDER, THEME_WORD, setThemeChoice } from './settings_view.js';
import { setVesselTab, parts } from './vessel_pages.js';
import { markTool, setLayout, model, live } from './workspace.js';

function isTyping(target) {
  return target?.closest?.('input, textarea, select, [contenteditable="true"], dialog[open]');
}

// Sidebar: expanded (logo, name, labels) or collapsed (logo and icons). Remembered per viewer.
function setRail(mode, { remember = true } = {}) {
  const collapsed = mode === 'collapsed';
  $('app').dataset.rail = collapsed ? 'collapsed' : 'expanded';
  const toggle = $('rail-toggle');
  toggle.setAttribute('aria-expanded', String(!collapsed));
  const label = t(collapsed ? 'shell.rail.expand' : 'shell.rail.collapse');
  toggle.title = `${label} (⌘\\)`;
  toggle.setAttribute('aria-label', label);
  if (remember) prefs.set(railPrefKey(), collapsed ? 'collapsed' : 'expanded');
}
// A narrow window (under 1100 px) starts with the sidebar collapsed; the person's own choice
// comes back when the window is wide again.
const narrowWindow = window.matchMedia('(max-width: 1100px)');
// The Run view gives its width to the drawing and the 3D model (lane K): under 1800 px it starts
// with the sidebar collapsed. A choice made on the Run view is kept apart from the other places.
const runRailWindow = window.matchMedia('(max-width: 1799px)');
const onRunView = () => document.body.dataset.route === 'run';
/** The pref that holds the sidebar choice for the place and window shown now. */
function railPrefKey() {
  return onRunView() && runRailWindow.matches ? 'railRun' : 'rail';
}
function applyRailForPlace() {
  if (narrowWindow.matches) setRail('collapsed', { remember: false });
  else if (railPrefKey() === 'railRun') setRail(prefs.get('railRun', 'collapsed'), { remember: false });
  else setRail(prefs.get('rail', 'expanded'), { remember: false });
}

// ---------------------------------------------------------------- command palette (⌘K)

/** The commands that make sense on the current screen, for js/palette.js. */
function paletteCommands() {
  const list = [];
  const add = (group, title, run, extra = {}) => list.push({ group, title, run, ...extra });
  const onRun = state.route === 'run' && state.view;
  if (onRun) {
    const sections = state.view.sections || [];
    if (sections.some(needsCheck)) add(t('ko3.commands.review'), t('ko3.commands.nextSectionToCheck'), () => { setVesselTab('run'); nextToCheck(); }, { keys: 'N' });
    if (canDecide() && acceptCandidate(currentSection())) add(t('ko3.commands.review'), t('ko3.acceptAt', { place: fmt.metres(currentSection().x_m) }), () => decide(currentSection(), acceptCandidate(currentSection())), { keys: 'A' });
    if (canDecide() && otherCandidate(currentSection())) add(t('ko3.commands.review'), t('ko3.otherAt', { place: fmt.metres(currentSection().x_m) }), () => decide(currentSection(), otherCandidate(currentSection())), { keys: 'O' });
    if (!isRunning()) add(t('ko3.commands.review'), t('ko3.commands.markTheDrawing'), () => { setVesselTab('run'); markTool.setActive(true); }, { keys: 'M' });
    for (const section of sections) {
      add(t('ko3.commands.stations'), t('ko3.stationAt', { place: fmt.metres(section.x_m) }), () => { setVesselTab('run'); selectSection(section.id); },
        { hint: fmt.sectionStateLabel(section.state) });
    }
    add(t('ko3.commands.thisVessel'), t('ko3.commands.run'), () => setVesselTab('run'));
    if (state.view.components?.length) add(t('ko3.commands.thisVessel'), t('ko3.commands.parts'), () => setVesselTab('parts'), { hint: t('ko3.commands.hullDecksDeckhouses') });
    for (const part of state.view.components || []) {
      add(t('ko3.commands.parts'), part.label, () => { setVesselTab('parts'); parts.selectPart(part.id); }, { hint: partState(part).word });
    }
    add(t('ko3.commands.thisVessel'), t('ko3.commands.sources'), () => setVesselTab('sources'), { hint: t('ko3.commands.drawingsSheetsAndSpecInputs') });
    add(t('ko3.commands.thisVessel'), t('ko3.commands.export'), () => setVesselTab('export'), { hint: t('ko3.commands.stepSTLOffsetsHydrostaticsReport') });
    add(t('ko3.commands.thisVessel'), t('ko3.commands.history'), () => setVesselTab('history'));
    add(t('ko3.commands.layout'), t('ko3.commands.drawingOnly'), () => setLayout('drawing'), { keys: '⌘1' });
    add(t('ko3.commands.layout'), t('ko3.commands.drawingAndModel'), () => setLayout('split'), { keys: '⌘2' });
    add(t('ko3.commands.layout'), t('ko3.commands.modelOnly'), () => setLayout('model'), { keys: '⌘3' });
    add(t('ko3.commands.layout'), detailsAreOpen() ? t('ko3.commands.hideDetails') : t('ko3.commands.showDetails'), toggleDetails, { keys: '⌘4' });
  }
  for (const vessel of groupVessels(state.tasks)) {
    add(t('ko3.commands.vessels'), vessel.name, () => { setVesselTab('run'); openTask(vessel.latest.task); }, { hint: fmt.statusLabel(vessel.latest.status) });
  }
  add(t('ko3.commands.goTo'), t('ko3.commands.home'), () => navigate('home'));
  add(t('design.goTo'), t('design.title'), () => navigate('designs'));
  add(t('ko3.commands.goTo'), t('ko3.commands.queue'), () => navigate('queue'));
  add(t('ko3.commands.goTo'), t('ko3.commands.settings'), () => openSettings(), { keys: '⌘,' });
  add(t('ko3.commands.goTo'), t('ko3.commands.setupCheck'), () => navigate('welcome'));
  add(t('ko3.commands.help'), t('ko3.commands.keyboardShortcuts'), () => shortcutSheet.open(), { keys: '?' });
  for (const theme of THEME_ORDER) add(t('ko3.commands.theme'), t('ko3.theme', { theme: THEME_WORD[theme] }), () => setThemeChoice(theme));
  add(t('ko3.commands.start'), t('ko3.commands.newVesselFromDrawings'), () => chooseDrawingSet(), { keys: '⌘N' });
  add(t('ko3.commands.start'), t('ko3.commands.newVesselsFromAFolder'), () => chooseDrawingFolder(), { hint: t('ko3.commands.oneRunPerDrawingSet') });
  add(t('ko3.commands.start'), t('ko3.commands.openTheSampleVessel'), () => startSampleRun(), { hint: t('ko3.commands.aGeneratedDrawingNoAICost') });
  return list;
}

let palette, shortcutSheet;

/** Create the command palette and the shortcut sheet, and open them on request. */
export function createPaletteAndShortcuts() {
  palette = createPalette({ commands: paletteCommands });
  shortcutSheet = createShortcutSheet();
  // "?" opens the shortcut list anywhere except while typing.
  document.addEventListener('keydown', (event) => {
    if (event.key === '?' && !event.metaKey && !event.ctrlKey && !isTyping(event.target)) {
      event.preventDefault();
      shortcutSheet.open();
    }
  });
  $('open-palette').addEventListener('click', () => palette.open());
}

/** Sidebar places and the error toast. */
export function installShellControls() {
  for (const item of document.querySelectorAll('.rail-item')) {
    item.addEventListener('click', () => navigate(item.dataset.route));
  }
  $('toast-close').addEventListener('click', () => { $('toast').hidden = true; });
}

/** The sidebar starts collapsed in a narrow window; its toggle button. */
export function installRail() {
  applyRailForPlace();
  narrowWindow.addEventListener('change', applyRailForPlace);
  runRailWindow.addEventListener('change', applyRailForPlace);
  // The router marks the place on the body (router.js applyRoute); the sidebar follows it.
  new MutationObserver(applyRailForPlace).observe(document.body, { attributes: true, attributeFilter: ['data-route'] });
  $('rail-toggle').addEventListener('click', () => setRail($('app').dataset.rail === 'collapsed' ? 'expanded' : 'collapsed'));
}

/** Run a ⌘ (Ctrl) shortcut from js/keymap.js. */
function runShortcut({ command, layout }) {
  if (command === 'toggle-rail') setRail($('app').dataset.rail === 'collapsed' ? 'expanded' : 'collapsed');
  else if (command === 'new-run') openNewRun();
  else if (command === 'new-vessel') chooseDrawingSet();
  else if (command === 'palette') palette.toggle();
  else if (command === 'settings') openSettings();
  else if (command === 'details' && state.route === 'run' && state.vesselTab === 'run') toggleDetails();
  else if (command === 'layout') setLayout(layout);
}

/** App-wide keyboard shortcuts. */
export function installKeyboard() {
  document.addEventListener('keydown', (event) => {
    const command = event.metaKey || event.ctrlKey;
    const shortcut = shortcutCommand(event);
    if (shortcut) {
      event.preventDefault();
      runShortcut(shortcut);
    } else if (!command && !event.altKey && !isTyping(event.target) && state.route === 'run') {
      // Arrow keys already mean something in tabs, the section strip, the panes and the scrub bar.
      const arrowsTaken = event.target.closest?.('[role="tablist"], [role="radiogroup"], [role="listbox"], .splitter, #drawing-host, #model-host, .scrub, select');
      let handled = true;
      if (event.key === '[') stepSection(-1);
      else if (event.key === ']') stepSection(1);
      else if ((event.key === 'n' || event.key === 'N') && state.vesselTab === 'run') nextToCheck();
      else if ((event.key === 'n' || event.key === 'N') && state.vesselTab === 'parts') handled = parts.nextSelected();
      else if ((event.key === 'a' || event.key === 'A') && state.vesselTab === 'run' && canDecide()) decide(currentSection(), acceptCandidate(currentSection()));
      else if ((event.key === 'a' || event.key === 'A') && state.vesselTab === 'parts') handled = parts.acceptSelected();
      else if ((event.key === 'm' || event.key === 'M') && state.vesselTab === 'parts') handled = parts.markSelected();
      else if ((event.key === 'o' || event.key === 'O') && state.vesselTab === 'run' && canDecide()) decide(currentSection(), otherCandidate(currentSection()));
      else if (event.key === 'r' || event.key === 'R') model.resetView();
      else if (event.key === ' ' && !event.target.closest?.('button')) handled = live.togglePlay();
      else if (event.key === 'ArrowLeft' && !arrowsTaken) handled = live.stepModel(-1);
      else if (event.key === 'ArrowRight' && !arrowsTaken) handled = live.stepModel(1);
      else handled = false;
      if (handled) event.preventDefault();
    }
  });
}
