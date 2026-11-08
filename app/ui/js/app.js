// MarinaFrame desktop UI: state, rendering and input. Backend access goes only through api.js.

import {
  invoke, onTaskChanged, pickSpecFile, canPickSpecFile, transportName,
  pickFolder, pickFile, canPickPaths, onFileDrop, isSpecFileName, SPEC_EXTENSIONS,
  pickDrawingFiles, isDrawingFileName, readArtifactAsDataUrl, readArtifactAsBuffer,
} from './api.js';
import { el, svg, icon, fill } from './dom.js';
import { createDrawingView } from './drawing.js';
import { createModelView } from './model3d.js';
import { createLiveRun } from './live.js';
import { createIntake } from './intake.js';
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
/** How many recently started spec files the New run sheet offers. */
const RECENT_SPECS_MAX = 5;

/** The places of the app shell. `run` is the run workspace (drawing | 3D | inspector). */
const ROUTES = ['home', 'queue', 'intake', 'run', 'settings'];

const state = {
  route: 'home',
  previousRoute: 'home', // where Settings returns to after Save or Cancel
  tasks: [],
  task: null, // absolute path of the open task
  view: null, // TaskView
  events: [],
  lastSequence: 0,
  sectionId: null,
  tab: 'timeline',
  aiStatus: null,
  busy: null, // plain-language description of the running action
  settings: null,
  modelKey: null,
  pageKey: null,
  loadToken: 0,
  datasets: [],
  defaults: null, // fresh-install settings, offered as one-click choices
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
  onUserCamera: () => live?.userMovedCamera(),
  onHoverCandidate: (id) => {
    for (const row of document.querySelectorAll('.cand-row')) row.classList.toggle('hot', row.dataset.candidate === id);
  },
});
const model = createModelView({ host: $('model-host') });

/** HOOK(M3 live): the live run (js/live.js) owns narration, Thinking and the ladder when it has steps. */
const live = createLiveRun({
  invoke,
  drawing,
  model,
  isRunning: () => isRunning(),
  nodes: {
    narration: $('narration'),
    thinking: $('panel-thinking'),
    ladder: $('revision-ladder'),
    transport: $('live-transport'),
    follow: $('live-follow'),
    dial: $('fit-dial'),
    caption: $('model-caption'),
  },
  onStepsChanged: () => {
    if (!live.hasSteps()) {
      renderNarration();
      renderThinking();
      renderRevisionStrip();
    }
  },
});

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

/**
 * A one- or two-word chip. Longer explanations go in `title` (a tooltip), never inline.
 * `tone` uses the badge colours: accent, pass, fail, warn, draft; `dot: false` drops the
 * leading dot for chips that are labels rather than states.
 */
function chip(text, { tone = null, status = null, title = null, dot = true, small = false } = {}) {
  const classes = ['badge'];
  if (!dot) classes.push('badge-nodot');
  if (small) classes.push('badge-small');
  const dataset = {};
  if (tone) dataset.tone = tone;
  if (status) dataset.status = status;
  // The inner span lets the text end in an ellipsis when the chip is squeezed.
  return el('span', { class: classes.join(' '), dataset, title: title || text }, el('span', { class: 'badge-text' }, text));
}

/**
 * Chip for a section source label: tinted fill in the label's colour with its glyph, so the
 * label does not depend on colour alone. `text` replaces the label name (for counts).
 */
function sourceChip(label, { text = null, title = null, small = true } = {}) {
  const name = fmt.sourceLabel(label);
  const glyph = icon(`src-${label}`);
  glyph.classList.add('badge-glyph');
  return el('span', {
    class: small ? 'badge badge-source badge-small' : 'badge badge-source',
    dataset: { source: label },
    title: title || name,
  }, glyph, el('span', { class: 'badge-text' }, text || name));
}

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function statusBadge(status) {
  return el('span', { class: 'badge', dataset: { status }, title: fmt.statusLabel(status) },
    el('span', { class: 'badge-text' }, fmt.statusLabel(status)));
}

// ---------------------------------------------------------------- vessels (derived from runs)

// There is no vessel model yet: runs are grouped by the vessel name at the start of the run
// name ("Pilot boat, lines plan" -> "Pilot boat"). The vessel lane replaces this.

/** Run states that put a vessel in the "Needs you" row. */
const DRAFT_READY = new Set(['draft', 'needs_review']);
const NEEDS_ATTENTION = new Set(['failed', 'blocked', 'declined']);

function vesselNameOf(runName) {
  const name = runName.split(/,|·| — | – | - /)[0].trim() || runName.trim();
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** Vessels, most recently active first. Each has its runs, newest first. */
function groupVessels(tasks) {
  const byKey = new Map();
  for (const task of tasks) {
    const name = vesselNameOf(task.name);
    const key = name.toLowerCase();
    if (!byKey.has(key)) byKey.set(key, { key, name, runs: [] });
    byKey.get(key).runs.push(task);
  }
  const vessels = [...byKey.values()];
  for (const vessel of vessels) {
    vessel.runs.sort((a, b) => b.updated_ms - a.updated_ms);
    vessel.latest = vessel.runs[0];
  }
  return vessels.sort((a, b) => b.latest.updated_ms - a.latest.updated_ms);
}

/** Runs of a vessel are numbered oldest first: "Run 1" is the first attempt. */
function runNumber(vessel, task) {
  return vessel.runs.length - vessel.runs.findIndex((r) => r.task === task);
}

function vesselOfTask(task) {
  return groupVessels(state.tasks).find((v) => v.runs.some((r) => r.task === task)) || null;
}

// Card previews need the run's page and sections. Cached per run and update time.
const previewCache = new Map();
function runPreview(task) {
  const key = `${task.task}|${task.updated_ms}`;
  if (!previewCache.has(key)) {
    previewCache.set(key, invoke('get_task', { task: task.task }).catch(() => null));
  }
  return previewCache.get(key);
}

async function refreshTasks() {
  try {
    state.tasks = await invoke('list_tasks', {});
    renderHome();
    renderQueue();
    renderCrumbs();
  } catch (error) {
    showError(error);
  }
}
const refreshTasksSoon = debounce(refreshTasks, LIST_REFRESH_DEBOUNCE_MS);

async function refreshDatasets() {
  try {
    state.datasets = await invoke('list_datasets', {});
  } catch {
    state.datasets = [];
  }
}

// ---------------------------------------------------------------- home

/** Sections a reviewer should look at: guessed lines and declined sections. */
function toCheckCount(view) {
  return view?.sections.filter((s) => s.state === 'guessed' || s.state === 'declined').length || 0;
}

function needsCard(vessel) {
  const run = vessel.latest;
  const chips = el('span', { class: 'chip-row' }, statusBadge(run.status));
  runPreview(run).then((view) => {
    if (view?.revision) chips.append(chip(view.revision, { dot: false, title: `Revision ${view.revision}` }));
    const count = toCheckCount(view);
    if (count) chips.append(chip(`${count} to check`, { dot: false, title: fmt.plural(count, 'section') + ' to check' }));
  });
  return el('button', {
    class: 'needs-card',
    type: 'button',
    title: `Open ${run.name}`,
    onclick: () => openTask(run.task),
  },
  el('span', { class: 'needs-icon' }, icon('sheet')),
  el('span', { class: 'needs-body' },
    el('strong', { class: 'needs-name' }, vessel.name),
    chips));
}

/** A mini body plan of the built sections: each station's chosen line, mirrored, in its source style. */
function hullThumb(view) {
  const lines = [];
  for (const section of view.sections) {
    const path = sectionShapePath(section);
    if (path) lines.push({ path, source: section.source?.label || 'traced' });
  }
  if (!lines.length) return null;
  return svg('svg', { class: 'hull-thumb', viewBox: '-46 -2 92 58', 'aria-hidden': 'true' },
    svg('path', { class: 'hull-thumb-axis', d: 'M0 0V54' }),
    ...lines.flatMap(({ path, source }) => [
      svg('path', { class: 'src-stroke', 'data-source': source, d: path }),
      svg('path', { class: 'src-stroke', 'data-source': source, d: path, transform: 'scale(-1 1)' }),
    ]));
}

function vesselCard(vessel) {
  const run = vessel.latest;
  const thumb = el('span', { class: 'vessel-thumb' }, el('span', { class: 'crop-marks', 'aria-hidden': 'true' }));
  runPreview(run).then(async (view) => {
    if (!view) return;
    if (view.model) {
      const hull = hullThumb(view);
      if (hull) thumb.append(el('span', { class: 'hull-badge', title: 'Built sections' }, hull));
    }
    if (!view.source_page) return;
    try {
      const url = await cachedArtifact('image', run.task, view.source_page.path);
      thumb.prepend(el('img', { src: url, alt: '' }));
    } catch {
      // No drawing image: the card keeps its blank paper.
    }
  });
  const runs = vessel.runs.length > 1 ? `${vessel.runs.length} runs · ` : '';
  return el('button', {
    class: 'vessel-card',
    type: 'button',
    title: `Open ${run.name}`,
    dataset: { status: run.status },
    onclick: () => openTask(run.task),
  },
  thumb,
  el('span', { class: 'vessel-row' },
    el('strong', { class: 'vessel-name' }, vessel.name),
    statusBadge(run.status)),
  el('span', { class: 'vessel-meta', title: fmt.fullTime(run.updated_ms) }, `${runs}${fmt.relativeTime(run.updated_ms)}`),
  run.status === 'running' ? el('span', { class: 'vessel-progress', 'aria-hidden': 'true' }) : null);
}

function renderHome() {
  const vessels = groupVessels(state.tasks);
  const waiting = vessels.filter((v) => DRAFT_READY.has(v.latest.status) || NEEDS_ATTENTION.has(v.latest.status));
  fill($('needs-row'), ...(waiting.length
    ? waiting.map(needsCard)
    : [el('p', { class: 'home-empty' }, state.tasks.length ? 'Nothing waiting for you.' : 'No runs yet. Drop a drawing set to start.')]));
  const grid = $('vessel-grid');
  const dropTile = $('drop-tile');
  fill(grid, ...vessels.map(vesselCard), dropTile);
}

function renderQueue() {
  const active = state.tasks.filter((t) => t.status === 'running' || t.status === 'paused');
  fill($('queue-list'), ...(active.length
    ? active.map((task) => el('li', {},
      el('button', { class: 'queue-row', type: 'button', onclick: () => openTask(task.task) },
        el('span', { class: 'queue-name', title: task.name }, task.name),
        statusBadge(task.status),
        el('span', { class: 'queue-time' }, fmt.shortTime(task.updated_ms)))))
    : [el('li', { class: 'home-empty' }, 'No runs in the queue.')]));
}

// ---------------------------------------------------------------- opening a task

async function openTask(task) {
  if (task === state.task) {
    navigate('run');
    return;
  }
  state.task = task;
  state.view = null;
  state.events = [];
  state.lastSequence = 0;
  state.sectionId = null;
  state.modelKey = null;
  state.pageKey = null;
  prefs.set('lastTask', task);
  live.open(task);
  navigate('run');
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
    live.statusChanged();
  } catch (error) {
    if (token === state.loadToken) showError(error);
  }
}
const loadTaskSoon = debounce(() => loadTask(), REFRESH_DEBOUNCE_MS);

function defaultSection(view) {
  const needsAttention = view.sections.find((s) => s.state === 'declined' || s.state === 'guessed');
  return (needsAttention || view.sections[0])?.id || null;
}

function renderTask({ fresh = false } = {}) {
  renderCrumbs();
  renderActions();
  renderNotices();
  renderDraftSummary();
  renderNarration();
  renderStrip();
  renderSelection();
  renderTabs();
  renderRevisionStrip();
  renderDrawing({ fresh });
  renderModel();
}

// ---------------------------------------------------------------- title bar: breadcrumb

const ROUTE_TITLES = { home: 'Home', queue: 'Queue', intake: 'New vessel', settings: 'Settings' };

function crumbSeparator() {
  return el('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, '›');
}

/** Breadcrumb Vessel › Run N › rN on the run view; the place name elsewhere. */
function renderCrumbs() {
  const crumbs = $('crumbs');
  const badge = $('task-badge');
  const view = state.route === 'run' ? state.view : null;
  badge.hidden = !view;
  if (state.route !== 'run') {
    fill(crumbs, el('span', { class: 'crumb crumb-current', 'aria-current': 'page' }, ROUTE_TITLES[state.route]));
    document.title = 'MarinaFrame';
    return;
  }
  if (!view) {
    fill(crumbs, el('span', { class: 'crumb crumb-current' }, 'Run'));
    document.title = 'MarinaFrame';
    return;
  }
  const vessel = vesselOfTask(state.task);
  const vesselName = vessel?.name || vesselNameOf(view.summary.name);
  // The run crumb is a picker when the vessel has more than one run.
  const runCrumb = vessel && vessel.runs.length > 1
    ? el('select', {
      class: 'crumb crumb-select',
      'aria-label': 'Run of this vessel',
      title: view.summary.name,
      onchange: (event) => openTask(event.target.value),
    }, ...vessel.runs.map((run) => {
      const option = el('option', { value: run.task }, `Run ${runNumber(vessel, run.task)}`);
      option.selected = run.task === state.task;
      return option;
    }))
    : el('span', { class: 'crumb', title: view.summary.name }, `Run ${vessel ? runNumber(vessel, state.task) : 1}`);
  fill(crumbs,
    el('button', { class: 'crumb crumb-link', type: 'button', title: `${vesselName}: back to Home`, onclick: () => navigate('home') }, vesselName),
    crumbSeparator(),
    runCrumb,
    view.revision ? [crumbSeparator(), el('span', { class: 'crumb crumb-current crumb-mono', 'aria-current': 'page', title: `Revision ${view.revision}` }, view.revision)] : null);
  document.title = `${vesselName} › Run — MarinaFrame`;
  badge.dataset.status = view.summary.status;
  fill(badge, el('span', { class: 'badge-text' }, fmt.statusLabel(view.summary.status)));
  badge.title = fmt.statusLabel(view.summary.status);
}

function renderActions() {
  const status = state.view?.summary.status;
  const resume = $('resume-task');
  const cancel = $('cancel-task');
  resume.hidden = !['paused', 'blocked', 'cancelled'].includes(status);
  cancel.hidden = status !== 'running';
  resume.disabled = cancel.disabled = Boolean(state.busy);
}

/** Global status bar: AI on or off, preview mode, runs folder. Run facts live in the run view. */
function renderStatusbar() {
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

/** Run mode chip: "AI draft" for the live policy, else "Deterministic". */
function policyChip(policy) {
  return policy === 'live'
    ? chip('AI draft', { tone: 'ai', dot: false, small: true, title: 'The AI read the drawing and built the draft (live model).' })
    : chip('No AI', { dot: false, small: true, title: 'Deterministic draft: no model calls.' });
}

// ---------------------------------------------------------------- run view: hooks for the live lane

/** HOOK(M3 live): narration strip. M1 shows the latest recorded step in plain words. */
function renderNarration() {
  if (live.hasSteps()) {
    live.renderNarration();
    return;
  }
  const strip = $('narration');
  const last = state.events[state.events.length - 1];
  strip.dataset.live = String(isRunning());
  if (!state.view || !last) {
    fill(strip, el('span', { class: 'narration-dot', 'aria-hidden': 'true' }),
      el('span', { class: 'narration-text narration-empty' }, state.view ? 'No steps recorded yet.' : ''));
    return;
  }
  fill(strip,
    el('span', { class: 'narration-dot', 'aria-hidden': 'true' }),
    el('span', { class: 'narration-text', title: last.text }, last.text),
    el('time', { class: 'narration-time', datetime: new Date(last.time_ms).toISOString() }, fmt.clock(last.time_ms)));
}

/**
 * HOOK(M3 live, M7 compare): revision and timeline strip. M1 shows the current revision,
 * the run mode, when it changed, and the model requests and cost (small; accuracy leads).
 */
function renderRevisionStrip() {
  const view = state.view;
  if (live.hasSteps()) live.renderLadder();
  else fill($('revision-ladder'), view
    ? (view.revision
      ? el('span', { class: 'rev-step rev-current', title: `Revision ${view.revision}` }, view.revision)
      : el('span', { class: 'rev-empty' }, 'No revision yet'))
    : null);
  if (!view) {
    fill($('revision-facts'));
    return;
  }
  const activity = view.activity;
  const cost = activity ? (activity.list_cost_complete ? fmt.usd(activity.list_cost_usd) : `≥ ${fmt.usd(activity.list_cost_usd)}`) : null;
  fill($('revision-facts'),
    policyChip(view.summary.policy),
    activity ? el('span', { class: 'rev-fact', title: 'Requests to the model, list cost' }, `${fmt.plural(activity.requests, 'request')} · ${cost}`) : null,
    el('span', { class: 'rev-fact', title: `Updated ${fmt.fullTime(view.summary.updated_ms)}` }, fmt.relativeTime(view.summary.updated_ms)));
}
setInterval(() => {
  renderRevisionStrip();
  renderStatusbar();
}, 30_000);

/** HOOK(M3 live): the Thinking tab. M1 lists the model's recorded steps with their reasons. */
function renderThinking() {
  if (live.hasSteps()) {
    live.renderThinking();
    return;
  }
  const panel = $('panel-thinking');
  if (!state.view) {
    fill(panel);
    return;
  }
  const steps = state.view.activity?.steps || [];
  if (!steps.length) {
    fill(panel, el('p', { class: 'panel-empty' }, state.view.summary.policy === 'live'
      ? 'The AI has not taken a step yet.'
      : 'This run did not use the AI. Its steps are under Steps.'));
    return;
  }
  fill(panel, el('ol', { class: 'thinking', 'aria-label': 'AI steps, oldest first' },
    ...steps.map((step) => el('li', { class: 'thought' },
      el('span', { class: 'thought-dot', 'aria-hidden': 'true' }),
      el('span', { class: 'thought-body' },
        el('code', { class: 'thought-tool' }, step.tool),
        step.reason ? el('span', { class: 'thought-reason selectable-text' }, step.reason) : null)))));
}

// ---------------------------------------------------------------- notices

function renderNotices() {
  const notices = state.view?.notices || [];
  fill($('notices'), ...notices.map((notice) => {
    const row = el('div', { class: 'notice', dataset: { tone: notice.tone, notice: notice.id } },
      icon(notice.tone === 'warning' ? 'warn' : 'info'),
      el('button', {
        class: 'notice-text',
        type: 'button',
        title: notice.text,
        'aria-expanded': 'false',
        onclick: (event) => {
          const expanded = row.classList.toggle('expanded');
          event.currentTarget.setAttribute('aria-expanded', String(expanded));
        },
      }, notice.text),
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

// ---------------------------------------------------------------- draft summary

function chevron() {
  const node = icon('chevron');
  node.classList.add('chevron');
  return node;
}

/** Sections per source label, and the build's warnings (shown as warnings, not errors). */
function renderDraftSummary() {
  const view = state.view;
  const counts = view?.source_counts || [];
  const warnings = view?.warnings || [];
  if (!counts.length && !warnings.length) {
    fill($('draft-summary'));
    return;
  }
  const chips = counts.map((c) => sourceChip(c.label, {
    text: `${c.count} ${fmt.sourceLabel(c.label)}`,
    title: `${fmt.plural(c.count, 'section')}: ${fmt.sourceLabel(c.label)}`,
  }));
  const warningList = warnings.length ? el('details', { class: 'draft-warnings' },
    el('summary', { title: 'Warnings of the draft build. Click to show them.' }, chevron(),
      chip(fmt.plural(warnings.length, 'warning'), { tone: 'warn', dot: false, small: true })),
    el('ul', { class: 'selectable-text' }, ...warnings.map((w) => el('li', {}, w)))) : null;
  // One row: the source chips, then the warnings toggle; its list opens below the row.
  fill($('draft-summary'), el('div', { class: 'source-counts' },
    chips.length ? el('span', { class: 'source-counts-title' }, 'Sources') : null, ...chips, warningList));
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
      'aria-label': `Section at ${fmt.metres(section.x_m)}: ${fmt.sectionStateLabel(section.state)}${section.source ? `, ${fmt.sourceLabel(section.source.label)}` : ''}`,
      dataset: { section: section.id, state: section.state, source: section.source?.label },
      onclick: () => selectSection(section.id),
    },
    svg('svg', { class: 'tile-shape', viewBox: '0 0 44 54', 'aria-hidden': 'true' },
      svg('path', { class: 'axis', d: 'M2 2V52' }),
      path ? svg('path', {
        class: section.source ? 'shape src-stroke' : 'shape',
        'data-source': section.source?.label,
        d: path,
      }) : null),
    el('span', { class: 'tile-x' }, section.x_m.toFixed(1), el('small', {}, ' m')),
    el('span', { class: 'tile-chips' },
      el('span', { class: 'tile-state' }, fmt.sectionStateLabel(section.state)),
      section.source ? sourceChip(section.source.label, { title: section.source.basis || null }) : null));
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

  const tone = { chosen: 'brand', declined: 'warn', guessed: 'draft' }[section.state];
  fill(head,
    el('h2', { title: `Section at ${fmt.metres(section.x_m)}` }, `Section at ${fmt.metres(section.x_m)}`),
    chip(fmt.sectionStateLabel(section.state), { tone }),
    section.source ? sourceChip(section.source.label, { title: section.source.basis || null, small: false }) : null,
  );

  const canChoose = !state.busy && !isRunning();
  const rows = section.candidates.map((candidate) => {
    const swatch = svg('svg', { class: 'cand-swatch', viewBox: '0 0 22 10', 'aria-hidden': 'true' },
      svg('line', {
        x1: 1, y1: 5, x2: 21, y2: 5,
        stroke: candidate.chosen ? 'var(--ink-chosen)' : 'var(--ink-candidate)',
        'stroke-width': candidate.chosen ? 3 : 1.5,
      }));
    const guessedSection = section.state === 'guessed';
    const guessedLine = guessedSection && candidate.chosen;
    let trailing = null;
    // In a guessed section, the guessed line is confirmed and any other line replaces it.
    let action = null;
    if (guessedLine) {
      trailing = chip('Guessed', { tone: 'draft', small: true });
      action = chooseButton(section, candidate, 'Confirm', canChoose, true);
    } else if (candidate.chosen) trailing = chip('In use', { tone: 'brand', small: true });
    else if (candidate.selectable) {
      const label = guessedSection ? 'Use instead' : 'Use';
      if (guessedSection) action = chooseButton(section, candidate, label, canChoose, false);
      else trailing = chooseButton(section, candidate, label, canChoose, false);
    }
    return el('div', {
      class: 'cand-row',
      dataset: { candidate: candidate.id },
      onmouseenter: () => drawing.highlightCandidate(candidate.id),
      onmouseleave: () => drawing.highlightCandidate(null),
      onfocusin: () => drawing.highlightCandidate(candidate.id),
      onfocusout: () => drawing.highlightCandidate(null),
    }, swatch, el('span', { class: 'cand-label', title: candidate.label }, candidate.label), trailing || el('span'),
    el('span', { class: 'cand-why' }, candidate.why),
    action ? el('div', { class: 'cand-actions' }, action) : null);
  });

  fill(body,
    el('p', { class: 'selection-reason selectable-text' }, section.reason),
    section.source?.basis ? el('details', { class: 'selection-source' },
      el('summary', {}, chevron(), `Why ${fmt.sourceLabel(section.source.label)}`),
      el('p', { class: 'selectable-text' }, section.source.basis)) : null,
    rows.length ? el('div', { class: 'cand-list', role: 'list', 'aria-label': 'Lines found in this section' }, ...rows) : null,
  );
}

function chooseButton(section, candidate, label, canChoose, primary) {
  return el('button', {
    class: primary ? 'btn btn-small btn-primary' : 'btn btn-small',
    type: 'button',
    disabled: !canChoose,
    title: isRunning() ? 'Available when the run stops' : `${label}: the ${candidate.label.toLowerCase()}`,
    onclick: () => chooseLine(section, candidate),
  }, label);
}

async function chooseLine(section, candidate) {
  const task = state.task;
  const confirming = section.state === 'guessed' && candidate.chosen;
  const verb = confirming ? 'Confirming' : 'Using';
  const done = await runAction(`${verb} the ${candidate.label.toLowerCase()} at ${fmt.metres(section.x_m)}, then rebuilding…`, () =>
    invoke('choose_line', { task, section_id: section.id, candidate_id: candidate.id }));
  if (done && task === state.task) {
    await loadTask();
    refreshTasksSoon();
  }
}

// ---------------------------------------------------------------- inspector: tabs

const TABS = ['thinking', 'timeline', 'checks', 'model', 'evidence'];

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
  fill($('tab-model'), 'Calls', calls ? el('span', { class: 'count' }, String(calls)) : null);
  renderThinking();
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
    isRunning() ? el('p', { class: 'timeline-live', title: 'Working on the next step' }, 'Working') : null,
  );
  panel.scrollTop = panel.scrollHeight;
}

function appendEvents(events) {
  // A task can change (a worker writes build files) without a new step; nothing to add then.
  if (!events.length) return;
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
  renderNarration();
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
    counts.pass && chip(`${counts.pass} pass`, { tone: 'pass', small: true }),
    counts.fail && chip(`${counts.fail} fail`, { tone: 'fail', small: true }),
    counts.not_run && chip(`${counts.not_run} not run`, { small: true }),
  ].filter(Boolean);
  fill(panel,
    el('p', { class: 'check-summary chip-row' }, ...summary),
    el('ul', {}, ...checks.map((check) => el('li', { class: 'check' },
      el('span', { class: 'check-name' }, check.name),
      el('span', { class: 'check-value selectable-text' }, check.limit ? `${check.value}, limit ${check.limit}` : check.value),
      el('span', { class: 'badge', dataset: { tone: { pass: 'pass', fail: 'fail' }[check.result] || '' } }, fmt.checkLabel(check.result)),
    ))),
  );
}

/** Collapsible list of what the live model did: each step, request count, tokens, list cost. */
function renderActivity(activity) {
  if (!activity) return null;
  const cost = activity.list_cost_complete
    ? fmt.usd(activity.list_cost_usd)
    : `at least ${fmt.usd(activity.list_cost_usd)}`;
  const facts = [
    [fmt.plural(activity.requests, 'request'), 'Requests to the model'],
    [`${fmt.integer(activity.prompt_tokens)} sent`, 'Tokens sent to the model'],
    [`${fmt.integer(activity.completion_tokens)} received`, 'Tokens received from the model'],
    [cost, 'List cost of the model requests'],
  ];
  return el('details', { class: 'activity' },
    el('summary', { title: 'What the AI did in this run' }, chevron(), 'Model activity',
      chip(fmt.plural(activity.steps.length, 'step'), { dot: false, small: true })),
    el('p', { class: 'chip-row' }, ...facts.map(([text, title]) => chip(text, { dot: false, small: true, title }))),
    el('ol', { class: 'activity-steps selectable-text' }, ...activity.steps.map((step) => el('li', {},
      el('strong', {}, step.tool),
      step.reason ? `: ${step.reason}` : null))));
}

function renderModelCalls() {
  const panel = $('panel-model');
  const calls = state.view?.provider || [];
  if (!state.view) {
    fill(panel);
    return;
  }
  if (!calls.length) {
    fill(panel, renderActivity(state.view.activity), el('p', { class: 'panel-empty' },
      state.view.summary.policy === 'live' ? 'The model has not been asked anything yet.' : 'This run is deterministic. It does not call the model.'));
    return;
  }
  const totalCost = calls.reduce((sum, c) => sum + (c.cost_usd || 0), 0);
  const task = state.task;
  fill(panel,
    renderActivity(state.view.activity),
    el('p', { class: 'call-total chip-row' },
      chip(fmt.plural(calls.length, 'call'), { dot: false, small: true }),
      chip(fmt.usd(totalCost), { dot: false, small: true, title: 'Cost of all calls' })),
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
      el('p', {}, view ? 'This run did not find a drawing page to read.' : 'Open a vessel on Home.'));
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

/**
 * x ranges (metres) the draft guessed. A bridged gap or a dropped end has its own range.
 * A guessed line covers the part of the hull nearer to its station than to any other.
 */
function guessedXRanges(sections, lengthM) {
  const stations = sections.map((s) => s.x_m).sort((a, b) => a - b);
  const ranges = [];
  for (const section of sections) {
    const guess = section.guess;
    if (!guess) continue;
    if (guess.x_range_m) {
      ranges.push(guess.x_range_m);
      continue;
    }
    const at = stations.indexOf(section.x_m);
    const before = at > 0 ? (stations[at - 1] + section.x_m) / 2 : Math.max(0, section.x_m - 0.25);
    const after = at < stations.length - 1 ? (stations[at + 1] + section.x_m) / 2 : Math.min(lengthM, section.x_m + 0.25);
    ranges.push([before, after]);
  }
  return ranges;
}

async function renderModel() {
  const view = state.view;
  const meta = $('model-meta');
  if (!view?.model) {
    state.modelKey = null;
    meta.textContent = '';
    model.setModel(null, [], {
      emptyTitle: view ? 'No 3D model yet' : 'No run open',
      emptyText: !view ? 'Open a vessel on Home.'
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
  meta.title = `Length × beam × depth · volume: ${meta.textContent}`;
  const stations = view.sections.map((s) => ({ id: s.id, x_m: s.x_m }));
  const guessedRanges = guessedXRanges(view.sections, m.length_m);
  const key = `${state.task}|${view.revision}|${m.stl_path}|${stations.map((s) => s.x_m).join(',')}|${JSON.stringify(guessedRanges)}`;
  if (key === state.modelKey) {
    model.setSelected(state.sectionId);
    return;
  }
  const sameTask = state.modelKey?.startsWith(`${state.task}|`);
  state.modelKey = key;
  try {
    const buffer = await cachedArtifact('stl', state.task, m.stl_path);
    if (state.modelKey !== key) return;
    model.setModel(buffer, stations, { keepCamera: sameTask, lengthM: m.length_m, guessedRanges });
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

/** One line on whether new runs use the AI, and what to do when they cannot. Shown as a tooltip. */
function aiStatusText(status) {
  if (!status) return 'The AI reads the drawing and builds the draft.';
  if (!status.enabled) return 'Off: new runs use the deterministic draft and do not call the model.';
  if (!status.key_found) {
    return `No model key found, so new runs use the deterministic draft. Put your OpenCode Go key in ${status.key_file} (one key per line, chmod 600).`;
  }
  return 'On: the AI (DeepSeek through OpenCode Go) reads the drawing and builds the draft.';
}

/** Show `text` in the chip `node` with a badge tone, and `title` as its tooltip. */
function setChip(node, text, tone, title) {
  node.textContent = text;
  node.title = title;
  if (tone) node.dataset.tone = tone;
  else delete node.dataset.tone;
}

/** AI drafting setting: On, Off or No key. */
function showAiStatus(node, status) {
  if (status && !status.enabled) setChip(node, 'Off', null, aiStatusText(status));
  else if (status && !status.key_found) setChip(node, 'No key', 'warn', aiStatusText(status));
  else setChip(node, 'On', 'ai', aiStatusText(status));
}

/** Mode of the next run: AI draft or Deterministic. */
function showRunMode(node, status) {
  if (status && !status.active) setChip(node, 'Deterministic', null, aiStatusText(status));
  else setChip(node, 'AI draft', 'ai', 'The AI reads the drawing and builds a draft. A person reviews it and signs it off.');
}

async function refreshAiStatus() {
  try {
    state.aiStatus = await invoke('get_ai_status');
  } catch {
    state.aiStatus = null;
  }
  return state.aiStatus;
}

/** Fresh-install settings (default runs folder, repo .venv Python). Read once; optional. */
async function loadDefaults() {
  if (!state.defaults) state.defaults = await invoke('get_default_settings', {}).catch(() => null);
  return state.defaults;
}

const fileName = (path) => path.split(/[\\/]/).filter(Boolean).pop() || path;
const folderName = (path) => path.slice(0, Math.max(0, path.length - fileName(path).length)).replace(/[\\/]$/, '');

/** A path as a bold file name and a muted folder that shortens with an ellipsis. */
function pathLabel(path) {
  return el('span', { class: 'path-label', title: path },
    el('span', { class: 'path-name' }, fileName(path)),
    // The folder box is right-to-left so the ellipsis cuts the start; the left-to-right
    // marks keep the slashes of the path in their places.
    el('span', { class: 'path-folder' }, `‎${folderName(path)}‎`));
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
async function loadSettingsForm() {
  const form = $('settings-form');
  const s = state.settings || { runs_folder: '', worker_python: '', theme: 'system', ai_drafting: true };
  form.runs_folder.value = s.runs_folder;
  form.worker_python.value = s.worker_python;
  form.theme.value = s.theme;
  form.ai_drafting.checked = s.ai_drafting !== false;
  const [status] = await Promise.all([refreshAiStatus(), loadDefaults()]);
  showAiStatus($('ai-status'), status);
  for (const field of Object.keys(PATH_FIELDS)) renderPathSuggestions(form, field);
  for (const button of form.querySelectorAll('[data-pick]')) button.hidden = !canPickPaths();
  $('settings-error').hidden = true;
  setChip($('notices-reset-status'), 'Hidden', null, 'Notices you close stay hidden until you show them again.');
  $('reset-notices').disabled = false;
  renderStatusbar();
}

function openSettings() {
  navigate('settings');
}

/** Leave Settings without saving: undo the theme preview, go back. */
function closeSettings() {
  applyTheme(state.settings?.theme || 'system');
  navigate(state.previousRoute);
}

$('settings-form').addEventListener('change', (event) => {
  if (event.target.name === 'theme') applyTheme(event.target.value);
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
  };
  $('settings-save').disabled = true;
  try {
    const folderChanged = next.runs_folder !== state.settings?.runs_folder;
    state.settings = await invoke('set_settings', next);
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

// ---------------------------------------------------------------- intake (drawing set)

// A drawing set dropped on the window, or chosen with "Choose files", goes to the intake
// view (js/intake.js). Start reading opens the new run's live screen.

const intake = createIntake({
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

async function chooseDrawingSet() {
  try {
    const paths = await pickDrawingFiles();
    if (paths.length) await startIntake(paths);
  } catch (error) {
    showError(error);
  }
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
async function openNewRun({ browse = null } = {}) {
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
  if (drawings.length) {
    await startIntake(drawings);
    return;
  }
  showError(new Error(`${fileName(paths[0])} is not a drawing. Drop PDF, PNG, TIFF or JPEG files.`));
}

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

$('new-vessel').addEventListener('click', () => chooseDrawingSet());
$('drop-choose').addEventListener('click', () => chooseDrawingSet());
$('new-run').addEventListener('click', () => {
  $('home-more').open = false;
  openNewRun();
});
// The More menu closes on a click outside it or on Escape.
document.addEventListener('click', (event) => {
  const menu = $('home-more');
  if (menu.open && !menu.contains(event.target)) menu.open = false;
});
$('home-more').addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    $('home-more').open = false;
    $('home-more').querySelector('summary').focus();
  }
});
for (const item of document.querySelectorAll('.rail-item')) {
  item.addEventListener('click', () => navigate(item.dataset.route));
}
$('toast-close').addEventListener('click', () => { $('toast').hidden = true; });
$('zoom-in').addEventListener('click', () => { live.userMovedCamera(); drawing.zoomIn(); });
$('zoom-out').addEventListener('click', () => { live.userMovedCamera(); drawing.zoomOut(); });
$('zoom-fit').addEventListener('click', () => { live.userMovedCamera(); drawing.fitPage(); });
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

$('strip').addEventListener('keydown', (event) => {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
  if (!step) return;
  event.preventDefault();
  stepSection(step);
});

function isTyping(target) {
  return target.closest('input, textarea, select, [contenteditable="true"], dialog[open]');
}

// Sidebar: expanded (logo, name, labels) or collapsed (logo and icons). Remembered per viewer.
function setRail(mode) {
  const collapsed = mode === 'collapsed';
  $('app').dataset.rail = collapsed ? 'collapsed' : 'expanded';
  const toggle = $('rail-toggle');
  toggle.setAttribute('aria-expanded', String(!collapsed));
  const label = collapsed ? 'Expand the sidebar (⌘\\)' : 'Collapse the sidebar (⌘\\)';
  toggle.title = label;
  toggle.setAttribute('aria-label', label.replace(/ \(.*\)$/, ''));
  prefs.set('rail', collapsed ? 'collapsed' : 'expanded');
}
setRail(prefs.get('rail', 'expanded'));
$('rail-toggle').addEventListener('click', () => setRail($('app').dataset.rail === 'collapsed' ? 'expanded' : 'collapsed'));

document.addEventListener('keydown', (event) => {
  const command = event.metaKey || event.ctrlKey;
  if (command && event.key === '\\') {
    event.preventDefault();
    setRail($('app').dataset.rail === 'collapsed' ? 'expanded' : 'collapsed');
  } else if (command && event.key.toLowerCase() === 'n') {
    event.preventDefault();
    if (event.shiftKey) openNewRun();
    else chooseDrawingSet();
  } else if (command && event.key === ',') {
    event.preventDefault();
    openSettings();
  } else if (command && ['1', '2', '3'].includes(event.key)) {
    event.preventDefault();
    setLayout({ 1: 'drawing', 2: 'split', 3: 'model' }[event.key]);
  } else if (!command && !event.altKey && !isTyping(event.target) && state.route === 'run') {
    // Arrow keys already mean something in tabs, the section strip, the panes and the scrub bar.
    const arrowsTaken = event.target.closest?.('[role="tablist"], [role="radiogroup"], [role="listbox"], .splitter, #drawing-host, #model-host, .scrub, select');
    let handled = true;
    if (event.key === '[') stepSection(-1);
    else if (event.key === ']') stepSection(1);
    else if (event.key === 'r' || event.key === 'R') model.resetView();
    else if (event.key === ' ' && !event.target.closest?.('button')) handled = live.togglePlay();
    else if (event.key === 'ArrowLeft' && !arrowsTaken) handled = live.stepModel(-1);
    else if (event.key === 'ArrowRight' && !arrowsTaken) handled = live.stepModel(1);
    else handled = false;
    if (handled) event.preventDefault();
  }
});

// ---------------------------------------------------------------- start

// ---------------------------------------------------------------- routes

function routeFromHash() {
  const route = location.hash.replace(/^#\/?/, '');
  return ROUTES.includes(route) ? route : null;
}

/** Show one view. The hash keeps the place across reloads and gives Back a meaning. */
function applyRoute(route) {
  if (route !== state.route) {
    if (route === 'settings') state.previousRoute = state.route === 'settings' ? 'home' : state.route;
    state.route = route;
  }
  for (const view of document.querySelectorAll('.view')) view.hidden = view.dataset.route !== route;
  for (const item of document.querySelectorAll('.rail-item')) {
    if (item.dataset.route === route) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  }
  $('run-actions').hidden = route !== 'run';
  document.body.dataset.route = route;
  renderCrumbs();
  if (route === 'settings') loadSettingsForm();
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

function navigate(route) {
  if (location.hash !== `#${route}`) history.pushState(null, '', `#${route}`);
  applyRoute(route);
}

window.addEventListener('popstate', () => applyRoute(routeFromHash() || 'home'));

/** The run view with no run open: open the last one, else the newest. */
async function openRememberedTask() {
  const remembered = prefs.get('lastTask', null);
  const first = state.tasks.find((t) => t.task === remembered) || state.tasks[0];
  if (first) await openTask(first.task);
  else renderNoTask();
}

async function start() {
  setLayout(prefs.get('layout', 'split'));
  setSplit(prefs.get('split', 0.56));
  selectTab(prefs.get('tab', 'thinking'));
  try {
    state.settings = await invoke('get_settings', {});
    applyTheme(state.settings.theme);
  } catch (error) {
    showError(error);
  }
  refreshDatasets();
  await Promise.all([refreshTasks(), refreshAiStatus()]);
  renderStatusbar();
  applyRoute(routeFromHash() || 'home');
}

start();

