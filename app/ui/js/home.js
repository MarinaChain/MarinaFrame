// Home (Needs you, vessel cards) and the Queue, with the Queue count in the sidebar.

import { t } from './i18n.js';
import { state, setQueue } from './app_state.js';
import { invoke, readOnly } from './api.js';
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
import { thumbnailSource, thumbnailCrop } from './home_thumb.js';

let thumbnailObserver;
const thumbnailJobs = new Map();

function observeThumbnail(node, load) {
  if (!globalThis.IntersectionObserver) {
    queueMicrotask(() => { void load(); });
    return;
  }
  thumbnailObserver ||= new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const job = thumbnailJobs.get(entry.target);
      thumbnailJobs.delete(entry.target);
      thumbnailObserver.unobserve(entry.target);
      if (job) void job();
    }
  });
  thumbnailJobs.set(node, load);
  thumbnailObserver.observe(node);
}

async function drawingThumbnail(run, view, thumb) {
  let sources = [];
  try { sources = (await invoke('list_sources', { task: run.task })).sources || []; } catch { /* Keep the current drawing. */ }
  const preferred = thumbnailSource(view, sources, { models: false });
  const current = view.source_page?.path ? { kind: 'drawing', path: view.source_page.path } : null;
  for (const source of [preferred, current].filter(Boolean)) {
    if (source.kind === 'none') continue;
    try {
      let url;
      if (source.path) url = await cachedArtifact('image', run.task, source.path);
      else {
        const page = await invoke('read_source_page', { task: run.task, source_id: source.sourceId, page: source.page, size: 'full' });
        if (!page.base64) continue;
        url = `data:${page.mime};base64,${page.base64}`;
      }
      const image = el('img', { src: url, alt: '' });
      await image.decode();
      if (source.crop) {
        const facts = sources.find((item) => item.id === source.sourceId)?.pages.find((page) => page.index === source.page);
        const original = source.path ? view.source_page : { width: facts?.width_px, height: facts?.height_px };
        const crop = thumbnailCrop(source.crop, original, { width: image.naturalWidth, height: image.naturalHeight });
        if (crop) {
          const [x0, y0, right, bottom] = crop;
          const canvas = document.createElement('canvas');
          // Keep the crop small; the input page can be a large scan.
          const scale = Math.min(1, 480 / (right - x0), 300 / (bottom - y0));
          canvas.width = Math.max(1, Math.round((right - x0) * scale));
          canvas.height = Math.max(1, Math.round((bottom - y0) * scale));
          try {
            canvas.getContext('2d').drawImage(image, x0, y0, right - x0, bottom - y0, 0, 0, canvas.width, canvas.height);
            image.src = canvas.toDataURL('image/png');
            await image.decode();
          } catch {
            // A blocked canvas still leaves the whole GA sheet available.
            image.src = url;
            await image.decode();
          }
        }
      }
      image.className = 'vessel-thumb-drawing';
      thumb.prepend(image);
      const hull = view.model ? hullThumb(view) : null;
      if (hull) thumb.append(el('span', { class: 'hull-badge', title: t('home.builtSections') }, hull));
      return;
    } catch { /* Try the current drawing if a GA page cannot be read. */ }
  }
  thumb.append(el('span', { class: 'vessel-thumb-empty' }, t('home.noDrawing')));
}

async function loadThumbnail(run, view, thumb) {
  if (!view || !thumb.isConnected) return;
  const source = thumbnailSource(view);
  if (source.kind === 'model') {
    try {
      const { modelThumbnail } = await import('./home_thumb3d.js');
      const url = await modelThumbnail(run, view, source);
      const image = el('img', { src: url, alt: '', class: 'vessel-thumb-model' });
      await image.decode();
      thumb.prepend(image);
      return;
    } catch { /* No WebGL or an unreadable model: quietly show a drawing. */ }
  }
  await drawingThumbnail(run, view, thumb);
}

/** What waits for a person, as icon counts (the status chip already says the run's state). */
function needsReason(view) {
  const sections = toCheckCount(view);
  const parts = partsToCheck(view);
  return [
    sections ? glyphChip('flag', 'sections', { count: sections, countedName: t('home.toCheck', { items: fmt.plural(sections, 'section') }), tone: 'warn', focusable: false }) : null,
    parts ? glyphChip('cube', 'parts', { count: parts, countedName: t('home.toCheck', { items: fmt.plural(parts, 'part') }), tone: 'warn', focusable: false }) : null,
  ];
}

function needsCard(vessel) {
  const run = vessel.latest;
  const chips = el('span', { class: 'chip-row' }, statusBadge(run.status));
  const art = el('span', { class: 'needs-icon' }, icon('sheet'));
  const reason = el('span', { class: 'needs-why chip-row' });
  runPreview(run).then((view) => {
    if (view?.revision) chips.append(chip(view.revision, { dot: false, title: t('home.revision', { revision: view.revision }) }));
    fill(reason, ...needsReason(view));
    // The built sections, as a small body plan, say more than a file icon.
    const hull = view?.model ? hullThumb(view) : null;
    if (hull) fill(art, hull);
  });
  return el('button', {
    class: 'needs-card',
    type: 'button',
    title: t('home.open', { name: run.name }),
    dataset: { status: run.status },
    onclick: () => openTask(run.task),
  },
  art,
  el('span', { class: 'needs-body' },
    el('strong', { class: 'needs-name' }, vessel.name),
    chips,
    reason),
  el('span', { class: 'needs-go', 'aria-hidden': 'true' }, t('home.review'), icon('chevron')));
}

/** A mini body plan of the built sections: each station's chosen line, mirrored, in its source style. */
function hullThumb(view) {
  const lines = [];
  for (const section of view.sections || []) {
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
  const runs = vessel.runs.length > 1 ? `${fmt.plural(vessel.runs.length, 'run')} · ` : '';
  const thumb = el('span', { class: 'vessel-thumb' }, el('span', { class: 'crop-marks', 'aria-hidden': 'true' }));
  const meta = el('span', { class: 'vessel-meta', title: fmt.fullTime(run.updated_ms) }, `${runs}${fmt.relativeTime(run.updated_ms)}`);
  const preview = runPreview(run);
  preview.then((view) => {
    // A person's sign-off of the parts (the run stays a draft): one navy chip after the time.
    if (view?.sign_off) meta.append(' ', chip(t('home.signedOff'), { tone: 'pass', dot: false, small: true, title: t('home.signOffDraft', { name: view.sign_off.name, statement: view.sign_off.statement }) }));
  });
  observeThumbnail(thumb, async () => {
    await loadThumbnail(run, await preview, thumb);
  });
  return el('button', {
    class: 'vessel-card',
    type: 'button',
    title: t('home.open', { name: run.name }),
    dataset: { status: run.status },
    onclick: () => openTask(run.task),
  },
  thumb,
  el('span', { class: 'vessel-row' },
    el('strong', { class: 'vessel-name' }, vessel.name),
    statusBadge(run.status)),
  meta,
  // The demo's line for a showcase run, and where each drawing came from (static/backend.js).
  run.demo_tagline ? el('span', { class: 'vessel-tagline' }, run.demo_tagline) : null,
  run.demo_source ? el('span', { class: 'vessel-source' }, run.demo_source) : null,
  run.status === 'running' ? el('span', { class: 'vessel-progress', 'aria-hidden': 'true' }) : null);
}

/**
 * Home of the web demo: the runs in the order the demo lists them (static/backend.js), with
 * the pilot proposal after the showcase runs (those with their own line: the real ship and
 * the concept preview).
 */
function demoCards(vessels) {
  const ordered = [...vessels].sort((a, b) => (a.latest.demo_order ?? 0) - (b.latest.demo_order ?? 0));
  const showcases = ordered.filter((v) => v.latest.demo_tagline);
  const others = ordered.filter((v) => !v.latest.demo_tagline);
  return [...showcases.map(vesselCard), pilotCard(), ...others.map(vesselCard)];
}

function pilotCard() {
  return el('a', { class: 'vessel-card demo-pilot-card', href: 'static/pilot.html' },
    el('span', { class: 'vessel-thumb demo-pilot-thumb' },
      el('span', { class: 'demo-pilot-stages', 'aria-hidden': 'true' }, t('home.pilotBaseline'), el('br'), t('home.pilotTask'), el('br'), t('home.pilotDeliverable'))),
    el('span', { class: 'vessel-row' }, el('strong', { class: 'vessel-name' }, t('home.pilotTitle'))),
    el('span', { class: 'vessel-tagline' }, t('home.pilotText')));
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
  thumbnailObserver?.disconnect();
  thumbnailJobs.clear();
  if (!state.tasksLoaded) {
    renderHomeLoading();
    return;
  }
  $('needs-row').removeAttribute('aria-busy');
  const vessels = groupVessels(state.tasks);
  const waiting = vessels.filter((v) => DRAFT_READY.has(v.latest.status) || NEEDS_ATTENTION.has(v.latest.status));
  fill($('needs-row'), ...(waiting.length
    ? waiting.map(needsCard)
    : [el('p', { class: 'home-empty' }, state.tasks.length ? t('home.nothingWaiting') : t('home.noRuns'))]));
  const grid = $('vessel-grid');
  const dropTile = $('drop-tile');
  if (readOnly) {
    fill(grid, ...demoCards(vessels), dropTile);
  } else {
    fill(grid, ...vessels.map(vesselCard), dropTile);
  }
  // First start: no runs. Home becomes one large drop target with the four steps ahead.
  const empty = !state.tasks.length;
  $('view-home').dataset.empty = String(empty);
  $('home-needs-title').textContent = readOnly ? t('home.demo') : empty ? t('home.firstVessel') : t('home.needsYou');
  const queued = state.queue?.waiting.length || 0;
  const link = $('home-queue-link');
  link.hidden = queued === 0;
  link.textContent = t('home.inQueue', { sets: fmt.plural(queued, 'set') });
}

/** Queue groups, in order: what the AI works on, what waits for a person, the rest. */
const QUEUE_GROUPS = [
  { id: 'working', titleKey: 'home.queue.working', statuses: new Set(['running', 'paused']) },
  { id: 'ready', titleKey: 'home.queue.ready', statuses: new Set([...DRAFT_READY, ...NEEDS_ATTENTION]) },
  { id: 'earlier', titleKey: 'home.queue.earlier', statuses: null }, // everything else
];

function queueRow(task) {
  const vessel = vesselOfTask(state.tasks, task.task);
  const run = vessel ? t('home.runNumber', { number: runNumber(vessel, task.task) }) : t('home.run');
  // Whole-vessel runs add their parts and a sign-off once the run's view is read (cached).
  const extra = el('span', { class: 'queue-extra' });
  runPreview(task).then((view) => {
    const parts = view?.components || [];
    if (!parts.length) return;
    const open = partsToCheck(view);
    fill(extra,
      view.sign_off ? chip(t('home.signedOff'), { tone: 'pass', dot: false, small: true, title: t('home.signOff', { name: view.sign_off.name, statement: view.sign_off.statement }) })
        : open ? chip(t('home.toCheck', { items: fmt.plural(open, 'part') }), { tone: 'draft', dot: false, small: true })
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
  const words = [running ? t('home.running', { count: running }) : null, waiting ? t('home.waiting', { count: waiting }) : null].filter(Boolean).join(', ');
  count.title = words;
  count.closest('.rail-item').setAttribute('aria-label', words ? t('home.queueSummary', { words }) : t('home.queue'));
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
      el('h2', { class: 'queue-group-title' }, t(group.titleKey), el('span', { class: 'queue-count' }, String(group.tasks.length))),
      el('ul', { class: 'queue-rows' }, ...group.tasks.map(queueRow))))]
    : [el('li', { class: 'home-empty' }, t('home.queueEmpty'))]));
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
