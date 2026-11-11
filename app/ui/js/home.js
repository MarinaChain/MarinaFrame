// Home (Needs you, vessel cards) and the Queue, with the Queue count in the sidebar.

import { state, setQueue } from './app_state.js';
import { invoke } from './api.js';
import { el, icon, fill, svg } from './dom.js';
import * as fmt from './format.js';
import { statusBadge, chip, $ } from './ui_kit.js';
import {
  toCheckCount, partsToCheck, sectionShapePath, groupVessels, DRAFT_READY, NEEDS_ATTENTION,
  vesselOfTask, runNumber, vesselNameOf,
} from './run_facts.js';
import { runPreview, cachedArtifact } from './artifacts.js';
import { glyphChip } from './glyphs.js';
import { batch, chooseDrawingSet, chooseDrawingFolder, openNewRun } from './new_vessel.js';
import { navigate } from './router.js';
import { openTask } from './run.js';

/** What waits for a person, as icon counts (the status chip already says the run's state). */
function needsReason(view) {
  const sections = toCheckCount(view);
  const parts = partsToCheck(view);
  return [
    sections ? glyphChip('flag', 'sections', { count: sections, countedName: `${fmt.plural(sections, 'section')} to check`, tone: 'warn', focusable: false }) : null,
    parts ? glyphChip('cube', 'parts', { count: parts, countedName: `${fmt.plural(parts, 'part')} to check`, tone: 'warn', focusable: false }) : null,
  ];
}

function needsCard(vessel) {
  const run = vessel.latest;
  const chips = el('span', { class: 'chip-row' }, statusBadge(run.status));
  const art = el('span', { class: 'needs-icon' }, icon('sheet'));
  const reason = el('span', { class: 'needs-why chip-row' });
  runPreview(run).then((view) => {
    if (view?.revision) chips.append(chip(view.revision, { dot: false, title: `Revision ${view.revision}` }));
    fill(reason, ...needsReason(view));
    // The built sections, as a small body plan, say more than a file icon.
    const hull = view?.model ? hullThumb(view) : null;
    if (hull) fill(art, hull);
  });
  return el('button', {
    class: 'needs-card',
    type: 'button',
    title: `Open ${run.name}`,
    dataset: { status: run.status },
    onclick: () => openTask(run.task),
  },
  art,
  el('span', { class: 'needs-body' },
    el('strong', { class: 'needs-name' }, vessel.name),
    chips,
    reason),
  el('span', { class: 'needs-go', 'aria-hidden': 'true' }, 'Review', icon('chevron')));
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
  const runs = vessel.runs.length > 1 ? `${vessel.runs.length} runs · ` : '';
  const thumb = el('span', { class: 'vessel-thumb' }, el('span', { class: 'crop-marks', 'aria-hidden': 'true' }));
  const meta = el('span', { class: 'vessel-meta', title: fmt.fullTime(run.updated_ms) }, `${runs}${fmt.relativeTime(run.updated_ms)}`);
  runPreview(run).then(async (view) => {
    if (!view) return;
    // A person's sign-off of the parts (the run stays a draft): one navy chip after the time.
    if (view.sign_off) meta.append(' ', chip('Signed off', { tone: 'pass', dot: false, small: true, title: `Signed off by ${view.sign_off.name}: ${view.sign_off.statement}. The run stays a draft.` }));
    if (view.model) {
      const hull = hullThumb(view);
      if (hull) thumb.append(el('span', { class: 'hull-badge', title: 'Built sections' }, hull));
    }
    if (!view.source_page) {
      thumb.append(el('span', { class: 'vessel-thumb-empty' }, 'No drawing read'));
      return;
    }
    try {
      const url = await cachedArtifact('image', run.task, view.source_page.path);
      thumb.prepend(el('img', { src: url, alt: '' }));
    } catch {
      // No drawing image: the card keeps its blank paper.
    }
  });
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
  meta,
  run.status === 'running' ? el('span', { class: 'vessel-progress', 'aria-hidden': 'true' }) : null);
}

/** Grey placeholder cards while the run list loads, so Home does not flash "No runs yet". */
const HOME_SKELETON = { needs: 2, vessels: 4 };

function renderHomeLoading() {
  const bar = (cls) => el('span', { class: `skeleton ${cls}` });
  fill($('needs-row'), ...Array.from({ length: HOME_SKELETON.needs }, () =>
    el('div', { class: 'needs-card is-loading', 'aria-hidden': 'true' }, bar('skeleton-art'), el('span', { class: 'needs-body' }, bar('skeleton-line'), bar('skeleton-line short')))));
  fill($('vessel-grid'), ...Array.from({ length: HOME_SKELETON.vessels }, () =>
    el('div', { class: 'vessel-card is-loading', 'aria-hidden': 'true' }, bar('skeleton-thumb'), bar('skeleton-line'), bar('skeleton-line short'))),
  $('drop-tile'));
  $('needs-row').setAttribute('aria-busy', 'true');
}

export function renderHome() {
  if (!state.tasksLoaded) {
    renderHomeLoading();
    return;
  }
  $('needs-row').removeAttribute('aria-busy');
  const vessels = groupVessels(state.tasks);
  const waiting = vessels.filter((v) => DRAFT_READY.has(v.latest.status) || NEEDS_ATTENTION.has(v.latest.status));
  fill($('needs-row'), ...(waiting.length
    ? waiting.map(needsCard)
    : [el('p', { class: 'home-empty' }, state.tasks.length ? 'Nothing waiting for you.' : 'No runs yet. Drop a drawing set to start.')]));
  const grid = $('vessel-grid');
  const dropTile = $('drop-tile');
  fill(grid, ...vessels.map(vesselCard), dropTile);
  // First start: no runs. Home becomes one large drop target with the four steps ahead.
  const empty = !state.tasks.length;
  $('view-home').dataset.empty = String(empty);
  $('home-needs-title').textContent = empty ? 'Your first vessel' : 'Needs you';
  const queued = state.queue?.waiting.length || 0;
  const link = $('home-queue-link');
  link.hidden = queued === 0;
  link.textContent = `${fmt.plural(queued, 'set')} in the Queue`;
}

/** Queue groups, in order: what the AI works on, what waits for a person, the rest. */
const QUEUE_GROUPS = [
  { id: 'working', title: 'Working now', statuses: new Set(['running', 'paused']) },
  { id: 'ready', title: 'Ready to check', statuses: new Set([...DRAFT_READY, ...NEEDS_ATTENTION]) },
  { id: 'earlier', title: 'Earlier', statuses: null }, // everything else
];

function queueRow(task) {
  const vessel = vesselOfTask(state.tasks, task.task);
  const run = vessel ? `Run ${runNumber(vessel, task.task)}` : 'Run';
  // Whole-vessel runs add their parts and a sign-off once the run's view is read (cached).
  const extra = el('span', { class: 'queue-extra' });
  runPreview(task).then((view) => {
    const parts = view?.components || [];
    if (!parts.length) return;
    const open = partsToCheck(view);
    fill(extra,
      view.sign_off ? chip('Signed off', { tone: 'pass', dot: false, small: true, title: `Signed off by ${view.sign_off.name}: ${view.sign_off.statement}` })
        : open ? chip(`${open} ${open === 1 ? 'part' : 'parts'} to check`, { tone: 'draft', dot: false, small: true })
          : chip(fmt.plural(parts.length, 'part'), { dot: false, small: true }));
  });
  return el('li', {},
    el('button', { class: 'queue-row', type: 'button', title: task.name, onclick: () => openTask(task.task) },
      el('span', { class: 'queue-name' }, vessel?.name || vesselNameOf(task.name)),
      el('span', { class: 'queue-run' }, run),
      statusBadge(task.status),
      el('span', { class: 'queue-facts' }, fmt.countOf(task.sections, 'section')),
      extra,
      el('span', { class: 'queue-time', title: fmt.fullTime(task.updated_ms) }, fmt.relativeTime(task.updated_ms))));
}

/**
 * While a queued set is starting, read the queue again every few seconds: a start that
 * fails changes no run folder, so no task-changed event would show it.
 */
const QUEUE_STARTING_POLL_MS = 3000;
let queuePollTimer = 0;
function pollQueueWhileStarting() {
  clearTimeout(queuePollTimer);
  if (state.route !== 'queue' || !state.queue?.waiting.some((s) => s.state === 'starting')) return;
  queuePollTimer = setTimeout(async () => {
    setQueue(await invoke('get_queue', {}).catch(() => state.queue));
    renderQueue();
  }, QUEUE_STARTING_POLL_MS);
}

/** The Queue rail item: how many runs are going and how many sets wait. */
export function renderRailCount() {
  const running = state.tasks.filter((t) => ['running', 'stalled'].includes(t.status)).length;
  const waiting = state.queue?.waiting.length || 0;
  const count = $('rail-queue-count');
  count.hidden = running + waiting === 0;
  count.textContent = String(running + waiting);
  const words = [running ? `${running} running` : null, waiting ? `${waiting} waiting` : null].filter(Boolean).join(', ');
  count.title = words;
  count.closest('.rail-item').setAttribute('aria-label', words ? `Queue, ${words}` : 'Queue');
}

export function renderQueue() {
  pollQueueWhileStarting();
  renderRailCount();
  const grouped = new Set();
  const groups = QUEUE_GROUPS.map((group) => {
    const tasks = state.tasks.filter((t) => !grouped.has(t) && (!group.statuses || group.statuses.has(t.status)));
    for (const task of tasks) grouped.add(task);
    return { ...group, tasks };
  });
  const waiting = batch.waitingGroup(state.queue, {
    onChange: (queue) => {
      setQueue(queue);
      renderQueue();
    },
  });
  fill($('queue-list'), ...(state.tasks.length || waiting
    ? [waiting, ...groups.filter((g) => g.tasks.length).map((group) => el('li', { class: 'queue-group' },
      el('h2', { class: 'queue-group-title' }, group.title, el('span', { class: 'queue-count' }, String(group.tasks.length))),
      el('ul', { class: 'queue-rows' }, ...group.tasks.map(queueRow))))]
    : [el('li', { class: 'home-empty' }, 'No runs yet. Drop a drawing set on Home to start.')]));
}

/** Buttons and the More menu of Home. */
export function installHomeControls() {
  $('new-vessel').addEventListener('click', () => chooseDrawingSet());
  $('drop-choose').addEventListener('click', () => chooseDrawingSet());
  $('drop-choose-folder').addEventListener('click', () => chooseDrawingFolder());
  $('home-queue-link').addEventListener('click', () => navigate('queue'));
  $('new-folder').addEventListener('click', () => {
    $('home-more').open = false;
    chooseDrawingFolder();
  });
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
}
