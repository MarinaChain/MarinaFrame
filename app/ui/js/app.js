// MarinaFrame desktop UI: state, rendering and input. Backend access goes only through api.js.

import {
  invoke, onTaskChanged, pickSpecFile, canPickSpecFile, transportName,
  readArtifactAsDataUrl, readArtifactAsBuffer,
} from './api.js';
import { el, svg, icon, fill } from './dom.js';
import { createDrawingView } from './drawing.js';
import { createModelView } from './model3d.js';
import * as fmt from './format.js';

const $ = (id) => document.getElementById(id);

/** Delay before re-reading a task after a burst of task-changed events. */
const REFRESH_DEBOUNCE_MS = 250;
const LIST_REFRESH_DEBOUNCE_MS = 600;
/** Below this stage width the drawing and model stack vertically. */
const STACK_BELOW_PX = 700;
const SPLIT_MIN = 0.2;
const SPLIT_MAX = 0.8;
const PREFS_KEY = 'marinaframe.ui';

const state = {
  tasks: [],
  task: null, // absolute path of the open task
  view: null, // TaskView
  events: [],
  lastSequence: 0,
  sectionId: null,
  tab: 'timeline',
  busy: null, // plain-language description of the running action
  settings: null,
  modelKey: null,
  pageKey: null,
  loadToken: 0,
};

// Per-viewer conveniences only (layout, last tab). Wrapped: storage can be blocked.
const prefs = (() => {
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

const artifactCache = new Map();
function cachedArtifact(kind, task, path) {
  const key = `${kind}|${task}|${path}`;
  if (!artifactCache.has(key)) {
    const load = kind === 'image' ? readArtifactAsDataUrl(task, path) : readArtifactAsBuffer(task, path);
    artifactCache.set(key, load.catch((error) => {
      artifactCache.delete(key);
      throw error;
    }));
  }
  return artifactCache.get(key);
}

// ---------------------------------------------------------------- views

const drawing = createDrawingView({
  host: $('drawing-host'),
  tooltip: $('drawing-tooltip'),
  readout: $('zoom-readout'),
  onSelectSection: (id) => selectSection(id, { focusDrawing: false }),
  onHoverCandidate: (id) => {
    for (const row of document.querySelectorAll('.cand-row')) row.classList.toggle('hot', row.dataset.candidate === id);
  },
});
const model = createModelView({ host: $('model-host') });

const drawingEmpty = el('div', { class: 'pane-empty', hidden: true });
$('drawing-host').append(drawingEmpty);

// ---------------------------------------------------------------- helpers

function currentSection() {
  return state.view?.sections.find((s) => s.id === state.sectionId) || null;
}

function isRunning() {
  return state.view?.summary.status === 'running';
}

function showError(error) {
  $('toast-text').textContent = error?.message || 'Something went wrong.';
  $('toast').hidden = false;
}

function setBusy(text) {
  state.busy = text;
  const progress = $('status-progress');
  progress.classList.remove('error');
  fill(progress, ...(text ? [el('span', { class: 'spinner', 'aria-hidden': 'true' }), text] : []));
  renderActions();
  renderSelection();
}

/** Run one backend action with progress in the status bar. Only one runs at a time. */
async function runAction(progressText, action) {
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

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ---------------------------------------------------------------- task list

function renderTaskList() {
  const list = $('task-list');
  if (!state.tasks.length) {
    const folder = state.settings?.runs_folder;
    fill(list, el('li', { class: 'empty-list' }, folder ? `No runs in ${folder}.` : 'No runs yet.'));
    return;
  }
  fill(list, ...state.tasks.map((task) => el('li', {
    class: 'task-item',
    role: 'option',
    id: `task-${CSS.escape(task.task)}`,
    'aria-selected': String(task.task === state.task),
    dataset: { task: task.task },
    onclick: () => openTask(task.task),
  },
  el('span', { class: 'task-name', title: task.name }, task.name),
  el('span', { class: 'task-time', title: fmt.fullTime(task.updated_ms) }, fmt.shortTime(task.updated_ms)),
  el('span', { class: 'task-sub' }, statusBadge(task.status), task.sections ? fmt.plural(task.sections, 'section') : null),
  )));
  const selected = list.querySelector('[aria-selected="true"]');
  list.setAttribute('aria-activedescendant', selected?.id || '');
}

function statusBadge(status) {
  return el('span', { class: 'badge', dataset: { status } }, fmt.statusLabel(status));
}

async function refreshTasks() {
  try {
    state.tasks = await invoke('list_tasks', {});
    renderTaskList();
  } catch (error) {
    showError(error);
  }
}
const refreshTasksSoon = debounce(refreshTasks, LIST_REFRESH_DEBOUNCE_MS);

async function refreshDatasets() {
  try {
    const datasets = await invoke('list_datasets', {});
    fill($('dataset-list'), ...(datasets.length
      ? datasets.map((d) => el('li', { title: d.path }, el('span', {}, d.name), el('span', { class: 'size' }, fmt.bytes(d.bytes))))
      : [el('li', {}, 'None')]));
  } catch {
    fill($('dataset-list'), el('li', {}, 'Could not read the datasets folder.'));
  }
}

// ---------------------------------------------------------------- opening a task

async function openTask(task) {
  if (task === state.task) return;
  state.task = task;
  state.view = null;
  state.events = [];
  state.lastSequence = 0;
  state.sectionId = null;
  state.modelKey = null;
  state.pageKey = null;
  prefs.set('lastTask', task);
  renderTaskList();
  await loadTask({ fresh: true });
}

/** Read the open task again. `fresh` resets the view to its defaults. */
async function loadTask({ fresh = false } = {}) {
  const token = ++state.loadToken;
  const task = state.task;
  try {
    const [view, events] = await Promise.all([
      invoke('get_task', { task }),
      fresh ? invoke('get_events', { task, after_sequence: 0 }) : Promise.resolve(null),
    ]);
    if (token !== state.loadToken) return;
    state.view = view;
    if (events) {
      state.events = events;
      state.lastSequence = events.length ? events[events.length - 1].sequence : 0;
    }
    if (!view.sections.some((s) => s.id === state.sectionId)) state.sectionId = defaultSection(view);
    renderTask({ fresh });
  } catch (error) {
    if (token === state.loadToken) showError(error);
  }
}
const loadTaskSoon = debounce(() => loadTask(), REFRESH_DEBOUNCE_MS);

function defaultSection(view) {
  const declined = view.sections.find((s) => s.state === 'declined');
  return (declined || view.sections[0])?.id || null;
}

function renderTask({ fresh = false } = {}) {
  renderToolbar();
  renderNotices();
  renderStrip();
  renderSelection();
  renderTabs();
  renderStatusbar();
  renderDrawing({ fresh });
  renderModel();
}

// ---------------------------------------------------------------- toolbar and status

function renderToolbar() {
  const view = state.view;
  $('task-name').textContent = view ? view.summary.name : 'MarinaFrame';
  document.title = view ? `${view.summary.name} — MarinaFrame` : 'MarinaFrame';
  const badge = $('task-badge');
  badge.hidden = !view;
  if (view) {
    badge.dataset.status = view.summary.status;
    badge.textContent = fmt.statusLabel(view.summary.status);
  }
  renderActions();
}

function renderActions() {
  const status = state.view?.summary.status;
  const resume = $('resume-task');
  const cancel = $('cancel-task');
  resume.hidden = !['paused', 'blocked', 'cancelled'].includes(status);
  cancel.hidden = status !== 'running';
  resume.disabled = cancel.disabled = Boolean(state.busy);
}

function renderStatusbar() {
  const view = state.view;
  const badge = $('status-badge');
  badge.hidden = !view;
  if (view) {
    badge.dataset.status = view.summary.status;
    badge.textContent = fmt.statusLabel(view.summary.status);
  }
  $('status-policy').textContent = view ? (view.summary.policy === 'live' ? 'Live model' : 'Deterministic') : '';
  $('status-revision').textContent = view ? (view.revision ? `Revision ${view.revision}` : 'No revision yet') : '';
  $('status-updated').textContent = view ? `Updated ${fmt.relativeTime(view.summary.updated_ms)}` : '';
  $('status-mode').textContent = transportName === 'mock' ? 'Preview data' : '';
}
setInterval(renderStatusbar, 30_000);

// ---------------------------------------------------------------- notices

function renderNotices() {
  const notices = state.view?.notices || [];
  fill($('notices'), ...notices.map((notice) => {
    const row = el('div', { class: 'notice', dataset: { tone: notice.tone, notice: notice.id } },
      icon(notice.tone === 'warning' ? 'warn' : 'info'),
      el('span', { class: 'notice-text' }, notice.text),
      el('button', {
        class: 'btn btn-ghost btn-icon btn-small',
        type: 'button',
        title: 'Dismiss',
        'aria-label': `Dismiss: ${notice.text}`,
        onclick: () => dismissNotice(notice, row),
      }, icon('close')),
    );
    return row;
  }));
}

async function dismissNotice(notice, row) {
  row.classList.add('leaving');
  try {
    await invoke('dismiss_notice', { id: notice.id });
    // The backend filters dismissed notices; drop it locally to match.
    if (state.view) state.view.notices = state.view.notices.filter((n) => n.id !== notice.id);
    row.remove();
  } catch (error) {
    row.classList.remove('leaving');
    showError(error);
  }
}

// ---------------------------------------------------------------- section strip

function sectionShapePath(section) {
  const line = section.candidates.find((c) => c.chosen) || (section.state === 'declined' ? section.candidates[0] : null);
  if (!line) return null;
  const [x0, y0, x1, y1] = section.roi_px;
  const w = x1 - x0;
  const h = y1 - y0;
  return line.polyline_px.map(([x, y], i) => `${i ? 'L' : 'M'}${(((x - x0) / w) * 44).toFixed(1)} ${(((y - y0) / h) * 54).toFixed(1)}`).join(' ');
}

function renderStrip() {
  const strip = $('strip');
  const sections = state.view?.sections || [];
  if (!sections.length) {
    fill(strip, el('p', { class: 'strip-empty' }, state.view ? 'No sections found on this drawing.' : ''));
    strip.removeAttribute('aria-activedescendant');
    return;
  }
  fill(strip, ...sections.map((section) => {
    const path = sectionShapePath(section);
    return el('div', {
      class: 'tile',
      role: 'option',
      id: `tile-${section.id}`,
      'aria-selected': String(section.id === state.sectionId),
      'aria-label': `Section at ${fmt.metres(section.x_m)}: ${fmt.sectionStateLabel(section.state)}`,
      dataset: { section: section.id, state: section.state },
      onclick: () => selectSection(section.id),
    },
    svg('svg', { class: 'tile-shape', viewBox: '0 0 44 54', 'aria-hidden': 'true' },
      svg('path', { class: 'axis', d: 'M2 2V52' }),
      path ? svg('path', { class: 'shape', d: path }) : null),
    el('span', { class: 'tile-x' }, section.x_m.toFixed(1), el('small', {}, ' m')),
    el('span', { class: 'tile-state' }, fmt.sectionStateLabel(section.state)));
  }));
  strip.setAttribute('aria-activedescendant', `tile-${state.sectionId}`);
}

function selectSection(id, { focusDrawing = true } = {}) {
  if (!id || id === state.sectionId) return;
  state.sectionId = id;
  for (const tile of document.querySelectorAll('.tile')) tile.setAttribute('aria-selected', String(tile.dataset.section === id));
  $('strip').setAttribute('aria-activedescendant', `tile-${id}`);
  document.getElementById(`tile-${id}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  renderSelection();
  drawing.setSections(state.view.sections, id, { focus: focusDrawing });
  model.setSelected(id);
}

function stepSection(delta) {
  const sections = state.view?.sections || [];
  if (!sections.length) return;
  const index = sections.findIndex((s) => s.id === state.sectionId);
  const next = sections[Math.min(sections.length - 1, Math.max(0, index + delta))];
  selectSection(next.id);
}

// ---------------------------------------------------------------- inspector: selection

function renderSelection() {
  const head = $('selection-head');
  const body = $('selection');
  const view = state.view;
  const section = currentSection();

  if (!view) {
    fill(head, el('h2', {}, 'Section'));
    fill(body, el('p', { class: 'selection-empty' }, 'Open a run to see its sections.'));
    return;
  }
  if (!section) {
    fill(head, el('h2', {}, 'Section'));
    fill(body, el('p', { class: 'selection-empty' }, isRunning() ? 'Sections appear here as the run reads them.' : 'This run has no sections.'));
    return;
  }

  const tone = { chosen: 'accent', declined: 'warn' }[section.state];
  fill(head,
    el('h2', {}, `Section at ${fmt.metres(section.x_m)}`),
    el('span', { class: 'badge', dataset: tone ? { tone } : {} }, fmt.sectionStateLabel(section.state)),
  );

  const canChoose = !state.busy && !isRunning();
  const rows = section.candidates.map((candidate) => {
    const swatch = svg('svg', { class: 'cand-swatch', viewBox: '0 0 22 10', 'aria-hidden': 'true' },
      svg('line', {
        x1: 1, y1: 5, x2: 21, y2: 5,
        stroke: candidate.chosen ? 'var(--ink-chosen)' : 'var(--ink-candidate)',
        'stroke-width': candidate.chosen ? 3 : 1.5,
      }));
    let trailing = null;
    if (candidate.chosen) trailing = el('span', { class: 'cand-tag' }, 'In use');
    else if (candidate.selectable) {
      trailing = el('button', {
        class: 'btn btn-small',
        type: 'button',
        disabled: !canChoose,
        title: isRunning() ? 'Available when the run stops' : null,
        onclick: () => chooseLine(section, candidate),
      }, 'Use this line');
    }
    return el('div', {
      class: 'cand-row',
      dataset: { candidate: candidate.id },
      onmouseenter: () => drawing.highlightCandidate(candidate.id),
      onmouseleave: () => drawing.highlightCandidate(null),
      onfocusin: () => drawing.highlightCandidate(candidate.id),
      onfocusout: () => drawing.highlightCandidate(null),
    }, swatch, el('span', { class: 'cand-label' }, candidate.label), trailing || el('span'),
    el('span', { class: 'cand-why' }, candidate.why));
  });

  fill(body,
    el('p', { class: 'selection-reason selectable-text' }, section.reason),
    rows.length ? el('div', { class: 'cand-list', role: 'list', 'aria-label': 'Lines found in this section' }, ...rows) : null,
  );
}

async function chooseLine(section, candidate) {
  const task = state.task;
  const done = await runAction(`Using the ${candidate.label.toLowerCase()} at ${fmt.metres(section.x_m)}, then rebuilding…`, () =>
    invoke('choose_line', { task, section_id: section.id, candidate_id: candidate.id }));
  if (done && task === state.task) {
    await loadTask();
    refreshTasksSoon();
  }
}

// ---------------------------------------------------------------- inspector: tabs

const TABS = ['timeline', 'checks', 'model', 'evidence'];

function selectTab(tab, { focus = false } = {}) {
  state.tab = tab;
  prefs.set('tab', tab);
  for (const name of TABS) {
    const button = $(`tab-${name}`);
    const selected = name === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    $(`panel-${name}`).hidden = !selected;
  }
  if (focus) $(`tab-${tab}`).focus();
}

function renderTabs() {
  const view = state.view;
  const failing = view?.checks.filter((c) => c.result === 'fail').length || 0;
  const calls = view?.provider.length || 0;
  fill($('tab-checks'), 'Checks', failing ? el('span', { class: 'count bad' }, `${failing} fail`) : null);
  fill($('tab-model'), 'Model calls', calls ? el('span', { class: 'count' }, String(calls)) : null);
  renderTimeline();
  renderChecks();
  renderModelCalls();
  renderEvidence();
}

function eventRow(event, fresh = false) {
  return el('li', { class: fresh ? 'event fresh' : 'event', dataset: { kind: event.kind } },
    el('time', { class: 'event-time', datetime: new Date(event.time_ms).toISOString(), title: fmt.fullTime(event.time_ms) }, fmt.clock(event.time_ms)),
    el('span', { class: 'event-dot', 'aria-hidden': 'true' }),
    el('span', { class: 'selectable-text' }, event.text));
}

function renderTimeline() {
  const panel = $('panel-timeline');
  if (!state.view) {
    fill(panel);
    return;
  }
  if (!state.events.length) {
    fill(panel, el('p', { class: 'panel-empty' }, 'No steps recorded yet.'));
    return;
  }
  fill(panel,
    el('ol', { class: 'timeline', 'aria-label': 'Steps, oldest first' }, ...state.events.map((e) => eventRow(e))),
    isRunning() ? el('p', { class: 'timeline-live' }, 'Working on the next step') : null,
  );
  panel.scrollTop = panel.scrollHeight;
}

function appendEvents(events) {
  const panel = $('panel-timeline');
  const nearBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 40;
  state.events.push(...events);
  state.lastSequence = events[events.length - 1].sequence;
  const list = panel.querySelector('.timeline');
  if (!list) {
    renderTimeline();
    return;
  }
  for (const event of events) list.append(eventRow(event, true));
  if (nearBottom) panel.scrollTop = panel.scrollHeight;
}

function renderChecks() {
  const panel = $('panel-checks');
  const checks = state.view?.checks || [];
  if (!state.view) {
    fill(panel);
    return;
  }
  if (!checks.length) {
    fill(panel, el('p', { class: 'panel-empty' }, isRunning() ? 'Checks run after the 3D model is built.' : 'No checks ran for this run.'));
    return;
  }
  const counts = { pass: 0, fail: 0, not_run: 0 };
  for (const check of checks) counts[check.result] += 1;
  const summary = [
    counts.pass && `${counts.pass} pass`,
    counts.fail && `${counts.fail} fail`,
    counts.not_run && `${counts.not_run} not run`,
  ].filter(Boolean).join(', ');
  fill(panel,
    el('p', { class: 'check-summary' }, summary),
    el('ul', {}, ...checks.map((check) => el('li', { class: 'check' },
      el('span', { class: 'check-name' }, check.name),
      el('span', { class: 'check-value selectable-text' }, check.limit ? `${check.value}, limit ${check.limit}` : check.value),
      el('span', { class: 'badge', dataset: { tone: { pass: 'pass', fail: 'fail' }[check.result] || '' } }, fmt.checkLabel(check.result)),
    ))),
  );
}

function renderModelCalls() {
  const panel = $('panel-model');
  const calls = state.view?.provider || [];
  if (!state.view) {
    fill(panel);
    return;
  }
  if (!calls.length) {
    fill(panel, el('p', { class: 'panel-empty' },
      state.view.summary.policy === 'live' ? 'The model has not been asked anything yet.' : 'This run is deterministic. It does not call the model.'));
    return;
  }
  const totalCost = calls.reduce((sum, c) => sum + (c.cost_usd || 0), 0);
  const task = state.task;
  fill(panel,
    el('p', { class: 'call-total' }, `${fmt.plural(calls.length, 'call')}, ${fmt.usd(totalCost)} in total`),
    ...calls.map((call) => {
      const images = el('div', { class: 'call-images' }, ...call.images.map((image) => {
        const img = el('img', { alt: image.label });
        cachedArtifact('image', task, image.path).then((url) => { img.src = url; }).catch(() => { img.alt = `${image.label} (missing)`; });
        return el('figure', {}, img, el('figcaption', {}, image.label));
      }));
      const facts = [
        call.prompt_tokens !== null && `${fmt.integer(call.prompt_tokens)} tokens sent`,
        call.completion_tokens !== null && `${fmt.integer(call.completion_tokens)} received`,
        call.cost_usd !== null && fmt.usd(call.cost_usd),
        call.key_slot !== null && `Key ${call.key_slot}`,
      ].filter(Boolean);
      const verdict = call.state === 'completed'
        ? el('span', { class: 'badge', dataset: { tone: call.accepted ? 'pass' : 'warn' } }, call.accepted ? 'Answer used' : 'Answer not used')
        : el('span', { class: 'badge', dataset: { tone: call.state === 'failed' ? 'fail' : '' } }, fmt.callStateLabel(call.state));
      return el('article', { class: 'call' },
        el('div', { class: 'call-head' }, verdict),
        call.images.length ? images : null,
        call.answer ? el('p', { class: 'call-answer selectable-text' }, call.answer) : null,
        facts.length ? el('p', { class: 'call-facts' }, ...facts.map((f) => el('span', {}, f))) : null);
    }),
  );
}

function renderEvidence() {
  const panel = $('panel-evidence');
  if (!state.view) {
    fill(panel);
    return;
  }
  fill(panel, el('details', { class: 'evidence' },
    el('summary', {}, icon('chevron'), 'Hashes, contract and manifest'),
    el('pre', { class: 'selectable-text' }, JSON.stringify(state.view.evidence, null, 2))));
  panel.querySelector('summary .icon').classList.add('chevron');
}

// ---------------------------------------------------------------- drawing and model

async function renderDrawing({ fresh = false } = {}) {
  const view = state.view;
  const page = view?.source_page || null;
  if (!page) {
    drawing.setPage(null, null);
    drawing.setSections([], null);
    fill(drawingEmpty, icon('drawing'),
      el('strong', {}, view ? 'No drawing page' : 'No run open'),
      el('p', {}, view ? 'This run did not find a drawing page to read.' : 'Choose a run in the sidebar.'));
    drawingEmpty.hidden = false;
    $('drawing-meta').textContent = '';
    state.pageKey = null;
    return;
  }
  drawingEmpty.hidden = true;
  $('drawing-meta').textContent = `${page.width} × ${page.height} px`;
  const key = `${state.task}|${page.path}`;
  if (key !== state.pageKey) {
    state.pageKey = key;
    drawing.setPage(page, null);
    const task = state.task;
    cachedArtifact('image', task, page.path)
      .then((url) => { if (state.pageKey === key) drawing.setPage(page, url); })
      .catch(showError);
  }
  drawing.setSections(view.sections, state.sectionId, { focus: false });
  if (fresh) drawing.fitSections();
}

async function renderModel() {
  const view = state.view;
  const meta = $('model-meta');
  if (!view?.model) {
    state.modelKey = null;
    meta.textContent = '';
    model.setModel(null, [], {
      emptyTitle: view ? 'No 3D model yet' : 'No run open',
      emptyText: !view ? 'Choose a run in the sidebar.'
        : isRunning() ? 'The model appears here when the run builds it.'
          : 'This run stopped before it built a model.',
    });
    return;
  }
  const m = view.model;
  meta.textContent = [
    `${fmt.metres(m.length_m, 2)} × ${fmt.metres(m.beam_m, 2)} × ${fmt.metres(m.depth_m, 2)}`,
    m.volume_m3 !== null ? `${fmt.decimal(m.volume_m3, 1)} m³` : null,
  ].filter(Boolean).join(' · ');
  const stations = view.sections.map((s) => ({ id: s.id, x_m: s.x_m }));
  const key = `${state.task}|${view.revision}|${m.stl_path}|${stations.map((s) => s.x_m).join(',')}`;
  if (key === state.modelKey) {
    model.setSelected(state.sectionId);
    return;
  }
  const sameTask = state.modelKey?.startsWith(`${state.task}|`);
  state.modelKey = key;
  try {
    const buffer = await cachedArtifact('stl', state.task, m.stl_path);
    if (state.modelKey !== key) return;
    model.setModel(buffer, stations, { keepCamera: sameTask });
    model.setSelected(state.sectionId);
  } catch (error) {
    model.setModel(null, [], { emptyTitle: 'Model file missing', emptyText: error.message });
  }
}

// ---------------------------------------------------------------- empty app

function renderNoTask() {
  state.view = null;
  renderTask({ fresh: true });
}

// ---------------------------------------------------------------- live updates

onTaskChanged(async ({ task, sequence }) => {
  refreshTasksSoon();
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

// ---------------------------------------------------------------- layout: view switch and splitter

const stage = $('stage');

function setLayout(layout) {
  stage.dataset.view = layout;
  prefs.set('layout', layout);
  for (const button of $('view-switch').querySelectorAll('button')) {
    button.setAttribute('aria-checked', String(button.dataset.view === layout));
  }
}

function setSplit(fraction) {
  const clamped = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, fraction));
  stage.style.setProperty('--split', clamped.toFixed(3));
  $('splitter').setAttribute('aria-valuenow', String(Math.round(clamped * 100)));
  prefs.set('split', clamped);
}

new ResizeObserver(() => {
  const stacked = stage.clientWidth < STACK_BELOW_PX;
  stage.classList.toggle('stacked', stacked);
  $('splitter').setAttribute('aria-orientation', stacked ? 'horizontal' : 'vertical');
}).observe(stage);

(function bindSplitter() {
  const splitter = $('splitter');
  splitter.setAttribute('aria-valuemin', String(SPLIT_MIN * 100));
  splitter.setAttribute('aria-valuemax', String(SPLIT_MAX * 100));
  splitter.addEventListener('pointerdown', (event) => {
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add('dragging');
    const move = (e) => {
      const rect = stage.getBoundingClientRect();
      const stacked = stage.classList.contains('stacked');
      setSplit(stacked ? (e.clientY - rect.top) / rect.height : (e.clientX - rect.left) / rect.width);
    };
    const stop = () => {
      splitter.classList.remove('dragging');
      splitter.removeEventListener('pointermove', move);
      splitter.removeEventListener('pointerup', stop);
    };
    splitter.addEventListener('pointermove', move);
    splitter.addEventListener('pointerup', stop);
  });
  splitter.addEventListener('keydown', (event) => {
    const current = Number(getComputedStyle(stage).getPropertyValue('--split')) || 0.56;
    const delta = { ArrowLeft: -0.04, ArrowUp: -0.04, ArrowRight: 0.04, ArrowDown: 0.04 }[event.key];
    if (delta) {
      event.preventDefault();
      setSplit(current + delta);
    }
  });
  splitter.addEventListener('dblclick', () => setSplit(0.56));
})();

// ---------------------------------------------------------------- settings and theme

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  model.refreshTheme();
}
systemDark.addEventListener('change', () => model.refreshTheme());

function openSettings() {
  const form = $('settings-form');
  const s = state.settings || { runs_folder: '', worker_python: '', theme: 'system' };
  form.runs_folder.value = s.runs_folder;
  form.worker_python.value = s.worker_python;
  form.theme.value = s.theme;
  $('settings-error').hidden = true;
  $('notices-reset-status').textContent = 'Dismissed notices stay hidden.';
  $('reset-notices').disabled = false;
  $('settings-sheet').showModal();
}

function closeSettings() {
  applyTheme(state.settings?.theme || 'system');
  $('settings-sheet').close();
}

$('settings-form').addEventListener('change', (event) => {
  if (event.target.name === 'theme') applyTheme(event.target.value);
});
$('settings-cancel').addEventListener('click', closeSettings);
$('settings-sheet').addEventListener('cancel', () => applyTheme(state.settings?.theme || 'system'));
$('settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const next = {
    runs_folder: form.runs_folder.value.trim(),
    worker_python: form.worker_python.value.trim(),
    theme: form.theme.value,
  };
  $('settings-save').disabled = true;
  try {
    const folderChanged = next.runs_folder !== state.settings?.runs_folder;
    state.settings = await invoke('set_settings', next);
    applyTheme(state.settings.theme);
    $('settings-sheet').close();
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
    $('notices-reset-status').textContent = 'Dismissed notices are back.';
    $('reset-notices').disabled = true;
    if (state.task) loadTask();
  } catch (error) {
    $('settings-error').textContent = error.message;
    $('settings-error').hidden = false;
  }
});

// ---------------------------------------------------------------- new run

function openNewRun() {
  const form = $('newrun-form');
  form.spec_path.value = '';
  $('newrun-error').hidden = true;
  $('pick-spec').hidden = !canPickSpecFile();
  $('newrun-sheet').showModal();
  form.spec_path.focus();
}

$('pick-spec').addEventListener('click', async () => {
  try {
    const path = await pickSpecFile();
    if (path) $('newrun-form').spec_path.value = path;
  } catch (error) {
    $('newrun-error').textContent = error.message;
    $('newrun-error').hidden = false;
  }
});
$('newrun-cancel').addEventListener('click', () => $('newrun-sheet').close());
$('newrun-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const specPath = event.target.spec_path.value.trim();
  if (!specPath) return;
  const start = $('newrun-start');
  start.disabled = true;
  start.textContent = 'Starting…';
  $('newrun-error').hidden = true;
  try {
    const { task } = await invoke('start_run', { spec_path: specPath });
    $('newrun-sheet').close();
    await refreshTasks();
    await openTask(task);
  } catch (error) {
    $('newrun-error').textContent = error.message;
    $('newrun-error').hidden = false;
  } finally {
    start.disabled = false;
    start.textContent = 'Start run';
  }
});

// ---------------------------------------------------------------- task actions

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

// ---------------------------------------------------------------- input bindings

$('new-run').addEventListener('click', openNewRun);
$('open-settings').addEventListener('click', openSettings);
$('toast-close').addEventListener('click', () => { $('toast').hidden = true; });
$('zoom-in').addEventListener('click', () => drawing.zoomIn());
$('zoom-out').addEventListener('click', () => drawing.zoomOut());
$('zoom-fit').addEventListener('click', () => drawing.fitPage());
$('model-reset').addEventListener('click', () => model.resetView());
$('view-switch').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-view]');
  if (button) setLayout(button.dataset.view);
});
$('tabs').addEventListener('click', (event) => {
  const button = event.target.closest('[role="tab"]');
  if (button) selectTab(button.dataset.tab);
});
$('tabs').addEventListener('keydown', (event) => {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
  if (!step) return;
  event.preventDefault();
  const next = TABS[(TABS.indexOf(state.tab) + step + TABS.length) % TABS.length];
  selectTab(next, { focus: true });
});

$('task-list').addEventListener('keydown', (event) => {
  const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
  if (!step || !state.tasks.length) return;
  event.preventDefault();
  const index = state.tasks.findIndex((t) => t.task === state.task);
  const next = state.tasks[Math.min(state.tasks.length - 1, Math.max(0, index + step))];
  openTask(next.task);
});
$('strip').addEventListener('keydown', (event) => {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
  if (!step) return;
  event.preventDefault();
  stepSection(step);
});

function isTyping(target) {
  return target.closest('input, textarea, select, [contenteditable="true"], dialog[open]');
}

document.addEventListener('keydown', (event) => {
  const command = event.metaKey || event.ctrlKey;
  if (command && event.key.toLowerCase() === 'n') {
    event.preventDefault();
    openNewRun();
  } else if (command && event.key === ',') {
    event.preventDefault();
    openSettings();
  } else if (command && ['1', '2', '3'].includes(event.key)) {
    event.preventDefault();
    setLayout({ 1: 'drawing', 2: 'split', 3: 'model' }[event.key]);
  } else if (!command && !event.altKey && !isTyping(event.target)) {
    if (event.key === '[') stepSection(-1);
    else if (event.key === ']') stepSection(1);
    else if (event.key === 'r' || event.key === 'R') model.resetView();
    else return;
    event.preventDefault();
  }
});

// ---------------------------------------------------------------- start

async function start() {
  setLayout(prefs.get('layout', 'split'));
  setSplit(prefs.get('split', 0.56));
  selectTab(prefs.get('tab', 'timeline'));
  try {
    state.settings = await invoke('get_settings', {});
    applyTheme(state.settings.theme);
  } catch (error) {
    showError(error);
  }
  refreshDatasets();
  await refreshTasks();
  const remembered = prefs.get('lastTask', null);
  const first = state.tasks.find((t) => t.task === remembered) || state.tasks[0];
  if (first) await openTask(first.task);
  else renderNoTask();
}

start();
