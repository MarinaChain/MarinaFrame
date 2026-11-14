// The app shell's state store. Every module reads `state`; only the setters below change it,
// so each change of the app's state has a name and one place. `prefs` holds per-viewer
// conveniences (layout, last tab) in localStorage.

import { setLocale, applyLocale, DEFAULT_LOCALE } from './i18n.js';

const PREFS_KEY = 'marinaframe.ui';

const store = {
  route: 'home',
  previousRoute: 'home', // where Settings returns to after Save or Cancel
  tasks: [],
  tasksLoaded: false, // true after the first list_tasks answer
  queue: null, // get_queue: sets that wait for a run slot
  task: null, // absolute path of the open task
  view: null, // TaskView
  events: [],
  lastSequence: 0,
  sectionId: null,
  tab: 'timeline',
  vesselTab: 'run', // run | parts | sources | export | history: the vessel tabs in the title bar
  aiStatus: null,
  busy: null, // plain-language description of the running action
  settings: null,
  modelKey: null, // what the 3D view shows: task, revision, model file, stations
  pageKey: null, // what the drawing view shows: task and page file
  placesKey: null, // section ids and places, to redraw step cards when they change
  loadToken: 0,
  pendingOpen: false, // the run view waits for the run list to open the remembered run
  datasets: [],
  defaults: null, // fresh-install settings, offered as one-click choices
};

/** Read-only view of the store. An assignment throws: use a setter. */
export const state = new Proxy(store, {
  set(_target, key) {
    throw new TypeError(`state.${String(key)} is read-only; use a setter in app_state.js`);
  },
  deleteProperty(_target, key) {
    throw new TypeError(`state.${String(key)} is read-only; use a setter in app_state.js`);
  },
});

// ---------------------------------------------------------------- setters

export function setRoute(route) {
  if (route === store.route) return;
  if (route === 'settings') store.previousRoute = store.route === 'settings' ? 'home' : store.route;
  store.route = route;
}

export function setTaskList(tasks, queue) {
  store.tasks = tasks;
  store.queue = queue;
  store.tasksLoaded = true;
}

export function setQueue(queue) {
  store.queue = queue;
}

/** Open another run: forget everything read from the previous one. */
export function setOpenTask(task) {
  store.task = task;
  store.view = null;
  store.events = [];
  store.lastSequence = 0;
  store.sectionId = null;
  store.modelKey = null;
  store.pageKey = null;
}

/** A new read starts; an answer for an older token is stale. */
export function nextLoadToken() {
  store.loadToken += 1;
  return store.loadToken;
}

export function setView(view) {
  store.view = view;
}

/** All steps of the open run, as read with get_events. */
export function setEvents(events) {
  store.events = events;
  store.lastSequence = events.length ? events[events.length - 1].sequence : 0;
}

/** New steps after the last one shown. `events` is not empty. */
export function addEvents(events) {
  store.events.push(...events);
  store.lastSequence = events[events.length - 1].sequence;
}

/** Drop a dismissed notice from the open run's view. */
export function dropNotice(id) {
  if (store.view) store.view.notices = store.view.notices.filter((n) => n.id !== id);
}

export function setSectionId(id) {
  store.sectionId = id;
}

export function setTab(tab) {
  store.tab = tab;
}

export function setVesselTabState(tab) {
  store.vesselTab = tab;
}

export function setAiStatus(status) {
  store.aiStatus = status;
}

export function setBusyText(text) {
  store.busy = text;
}

export function setSettings(settings) {
  store.settings = settings;
}

export function setDefaults(defaults) {
  store.defaults = defaults;
}

export function setDatasets(datasets) {
  store.datasets = datasets;
}

export function setModelKey(key) {
  store.modelKey = key;
}

export function setPageKey(key) {
  store.pageKey = key;
}

export function setPlacesKey(key) {
  store.placesKey = key;
}

export function setPendingOpen(pending) {
  store.pendingOpen = pending;
}

// ---------------------------------------------------------------- derived

/** The selected section of the open run, or null. */
export function currentSection() {
  return store.view?.sections.find((s) => s.id === store.sectionId) || null;
}

export function isRunning() {
  return ['running', 'stalled'].includes(store.view?.summary.status);
}

// ---------------------------------------------------------------- per-viewer preferences

/**
 * Costs and timings (step costs and times, tool durations, list cost) on the Run tab: hidden
 * unless the person turns them on in Settings. CSS hides every `.cost-timing` node of the Run
 * tab while `body[data-costs]` is not "shown"; History shows them always.
 */
export function applyShowCosts(show = prefs.get('showCosts', false) === true, { remember = false } = {}) {
  document.body.dataset.costs = show ? 'shown' : 'hidden';
  if (remember) prefs.set('showCosts', show);
}

/** Interface language: a per-viewer choice, written into the page at once (i18n.js). */
export function applyLanguage(code = prefs.get('language', DEFAULT_LOCALE), { remember = false } = {}) {
  const chosen = setLocale(code);
  applyLocale(document);
  if (remember) prefs.set('language', chosen);
  return chosen;
}

/**
 * Lite or Advanced (docs/design/2026-11-14-workbench-ux-plan.md, section 4.5): how much of the
 * design loop the person controls. A view choice only: both modes read the same design project.
 * `body[data-interface]` lets the design screens show or hide detail; risk is never hidden.
 */
export const INTERFACE_MODES = ['lite', 'advanced'];
export function applyInterfaceMode(mode = prefs.get('interfaceMode', 'advanced'), { remember = false } = {}) {
  const chosen = INTERFACE_MODES.includes(mode) ? mode : 'advanced';
  document.body.dataset.interface = chosen;
  if (remember) prefs.set('interfaceMode', chosen);
  return chosen;
}

// Per-viewer conveniences only (layout, last tab). Wrapped: storage can be blocked.
export const prefs = (() => {
  let values = {};
  try {
    values = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
  } catch {
    values = {};
  }
  return {
    get: (key, fallback) => (key in values ? values[key] : fallback),
    set(key, value) {
      values[key] = value;
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(values));
      } catch {
        // Not saved; the default returns next time.
      }
    },
  };
})();
