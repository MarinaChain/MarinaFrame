// Routes of the app shell. The hash keeps the place across reloads and gives Back a meaning.

import { setRoute, state, setPendingOpen, prefs } from './app_state.js';
import { $ } from './ui_kit.js';
import { welcome, intake } from './new_vessel.js';
import { renderCrumbs } from './run_header.js';
import { refreshTasksSoon, renderNoTask, openTask } from './run.js';
import { loadSettingsForm } from './settings_view.js';

/** The places of the app shell. `run` is the run workspace (drawing | 3D | inspector). */
const ROUTES = ['home', 'queue', 'intake', 'run', 'settings', 'welcome'];

export function routeFromHash() {
  const route = location.hash.replace(/^#\/?/, '');
  return ROUTES.includes(route) ? route : null;
}

/** Show one view. The hash keeps the place across reloads and gives Back a meaning. */
export function applyRoute(route) {
  setRoute(route);
  for (const view of document.querySelectorAll('.view')) view.hidden = view.dataset.route !== route;
  for (const item of document.querySelectorAll('.rail-item')) {
    if (item.dataset.route === route) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  }
  $('run-actions').hidden = route !== 'run';
  $('vessel-tabs').hidden = route !== 'run';
  document.body.dataset.route = route;
  renderCrumbs();
  if (route === 'settings') loadSettingsForm();
  if (route === 'welcome') welcome.show();
  // The queue may have moved while another page was open (a set started or failed).
  if (route === 'queue') refreshTasksSoon();
  if (route === 'intake') {
    // Nothing to show after a reload: the set lives only in this window.
    if (intake.hasSet()) {
      intake.show();
    } else {
      history.replaceState(null, '', '#home');
      applyRoute('home');
      return;
    }
  }
  if (route === 'run' && !state.task) openRememberedTask();
}

export function navigate(route) {
  if (location.hash !== `#${route}`) history.pushState(null, '', `#${route}`);
  applyRoute(route);
}

/** The run view with no run open: open the last one, else the newest. */
export async function openRememberedTask() {
  // Before the run list arrives, say the run is opening; start() opens it after the list.
  if (!state.tasksLoaded) {
    setPendingOpen(true);
    renderNoTask();
    return;
  }
  setPendingOpen(false);
  const remembered = prefs.get('lastTask', null);
  const first = state.tasks.find((t) => t.task === remembered) || state.tasks[0];
  if (first) await openTask(first.task);
  else renderNoTask();
}

/** Back and Forward move between places. */
export function installRouter() {
  window.addEventListener('popstate', () => applyRoute(routeFromHash() || 'home'));
}
