// The run view around the panes: breadcrumb, run actions, notices, the draft summary row,
// the narration strip and the revision strip.

import { state, isRunning, dropNotice } from './app_state.js';
import { invoke } from './api.js';
import { el, fill, icon } from './dom.js';
import * as fmt from './format.js';
import { $, chip, showError } from './ui_kit.js';
import { vesselOfTask, vesselNameOf, runNumber, needsCheck, partsToCheck } from './run_facts.js';
import { accuracyChips } from './accuracy.js';
import { glyphChip, sourceGlyph, legendPopover } from './glyphs.js';
import { tipAttributes } from './tooltip.js';
import { navigate } from './router.js';
import { nextToCheck } from './run_strip.js';
import { openTask } from './run.js';
import { renderStatusbar } from './settings_view.js';
import { renderVesselPage, setVesselTab } from './vessel_pages.js';
import { live } from './workspace.js';

// ---------------------------------------------------------------- title bar: breadcrumb

const ROUTE_TITLES = { home: 'Home', queue: 'Queue', intake: 'New vessel', settings: 'Settings', welcome: 'Setup' };
/** The title bar shows the same icon as the sidebar for these places. */
const ROUTE_ICONS = { home: 'home', queue: 'queue', settings: 'gear' };

function crumbSeparator() {
  return el('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, '›');
}

/** Breadcrumb Vessel › Run N › rN on the run view; the place name elsewhere. */
export function renderCrumbs() {
  const crumbs = $('crumbs');
  const badge = $('task-badge');
  const view = state.route === 'run' ? state.view : null;
  badge.hidden = !view;
  if (state.route !== 'run') {
    const routeIcon = ROUTE_ICONS[state.route];
    fill(crumbs, el('span', { class: 'crumb crumb-current', 'aria-current': 'page' },
      routeIcon ? icon(routeIcon) : null, ROUTE_TITLES[state.route]));
    document.title = 'MarinaFrame';
    return;
  }
  if (!view) {
    fill(crumbs, el('span', { class: 'crumb crumb-current' }, 'Run'));
    document.title = 'MarinaFrame';
    return;
  }
  const vessel = vesselOfTask(state.tasks, state.task);
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
  $('run-title').textContent = `${vesselName}, run ${vessel ? runNumber(vessel, state.task) : 1}`;
  badge.dataset.status = view.summary.status;
  fill(badge, el('span', { class: 'badge-text' }, fmt.statusLabel(view.summary.status)));
  badge.title = fmt.statusLabel(view.summary.status);
}

export function renderActions() {
  const status = state.view?.summary.status;
  const resume = $('resume-task');
  const cancel = $('cancel-task');
  resume.hidden = !['paused', 'blocked', 'cancelled', 'stalled'].includes(status);
  resume.textContent = status === 'stalled' ? 'Keep waiting' : 'Resume';
  cancel.hidden = !['running', 'stalled'].includes(status);
  resume.disabled = cancel.disabled = Boolean(state.busy);
  renderVesselPage();
}

/** Run mode chip: "AI draft" for the live policy, else "Deterministic". */
function policyChip(policy) {
  return policy === 'live'
    ? glyphChip('src-ai_inferred', 'AI draft', { tone: 'ai', detail: 'The AI read the drawing and built the draft (live model).' })
    : glyphChip('gear', 'No AI', { detail: 'Deterministic draft: no model calls.' });
}

// ---------------------------------------------------------------- run view: hooks for the live lane

/** HOOK(M3 live): narration strip. M1 shows the latest recorded step in plain words. */
export function renderNarration() {
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
export function renderRevisionStrip() {
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
    chip('Draft only', { dot: false, small: true, title: 'Engineering approval is never automatic. A naval architect signs off outside this app.' }),
    policyChip(view.summary.policy),
    activity ? el('span', { class: 'rev-fact', ...tipAttributes(`${fmt.plural(activity.requests, 'model request')}, ${cost}`, 'List cost of the model requests.', { label: false }).attrs },
      `${activity.requests} · ${cost}`) : null,
    el('span', { class: 'rev-fact', title: `Updated ${fmt.fullTime(view.summary.updated_ms)}` }, fmt.relativeTime(view.summary.updated_ms)));
}

/** Relative times in the revision strip and status bar stay current. */
export function installClock() {
  setInterval(() => {
    renderRevisionStrip();
    renderStatusbar();
  }, 30_000);
}

// ---------------------------------------------------------------- notices

/**
 * The backend's standing notice that sign-off happens outside the app. It is the same on
 * every run, so it shows as the "Draft only" chip in the revision strip, not as a bar.
 */
const ENGINEERING_NOTICE_ID = 'engineering-approval';
/**
 * The backend's draft banner ("Draft: 2 guesses to check. ..."). The review status in the
 * summary row says the same thing once, with this text as its tooltip detail.
 */
const DRAFT_NOTICE_PREFIX = 'draft-guesses:';

export function renderNotices() {
  const notices = (state.view?.notices || [])
    .filter((n) => n.id !== ENGINEERING_NOTICE_ID && !n.id.startsWith(DRAFT_NOTICE_PREFIX));
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
    dropNotice(notice.id);
    row.remove();
  } catch (error) {
    row.classList.remove('leaving');
    showError(error);
  }
}

/**
 * The run's one review status, then compact facts: sections per source label, the build's
 * warnings and the parts. Each fact is an icon and a count; the words are in its tooltip.
 */
export function renderDraftSummary() {
  const view = state.view;
  const counts = view?.source_counts || [];
  const warnings = view?.warnings || [];
  const sections = view?.sections || [];
  const parts = view?.components || [];
  const open = sections.filter(needsCheck).length;
  const accuracy = accuracyChips(view);
  if (!counts.length && !warnings.length && !parts.length && !open && !accuracy) {
    fill($('draft-summary'));
    return;
  }
  fill($('draft-summary'), el('div', { class: 'source-counts' },
    reviewStatus(view, open, sections.length),
    ...counts.map((c) => sourceGlyph(c.label, { count: c.count })),
    warnings.length ? warningsToggle(warnings) : null,
    counts.length ? legendPopover() : null,
    accuracy,
    parts.length ? partsLink(view, parts.length) : null));
}

/** "2 to check" and Next: the one place the run says what waits for a person. */
function reviewStatus(view, open, total) {
  if (!open) return null;
  const banner = (view.notices || []).find((n) => n.id.startsWith(DRAFT_NOTICE_PREFIX));
  const tip = tipAttributes(`${open} of ${fmt.plural(total, 'section')} to check`, banner?.text || null);
  return el('span', { class: 'review-status' },
    el('span', { class: 'review-count', role: 'img', tabindex: '0', ...tip.attrs },
      icon('flag'), el('strong', { 'aria-hidden': 'true' }, String(open)), el('span', { 'aria-hidden': 'true' }, 'to check'), tip.describer),
    el('button', {
      class: 'btn btn-small',
      type: 'button',
      disabled: isRunning(),
      ...tipAttributes('Next section to check (N)', null, { label: false }).attrs,
      onclick: nextToCheck,
    }, 'Next', el('kbd', { class: 'key-hint' }, 'N')));
}

/** Warnings of the draft build: an icon and a count; the list opens below the row. */
function warningsToggle(warnings) {
  const name = fmt.plural(warnings.length, 'warning');
  return el('details', { class: 'draft-warnings' },
    el('summary', { class: 'badge badge-small badge-glyphchip', dataset: { tone: 'warn' }, ...tipAttributes(name, 'Warnings of the draft build. Click to list them.').attrs },
      icon('warn'), el('span', { class: 'badge-count', 'aria-hidden': 'true' }, String(warnings.length))),
    el('ul', { class: 'selectable-text' }, ...warnings.map((w) => el('li', {}, w))));
}

/** Whole-vessel parts: one button to the Parts tab, with how many still need a look. */
function partsLink(view, count) {
  const toCheck = partsToCheck(view);
  const title = `${fmt.plural(count, 'part')}${toCheck ? `, ${toCheck} to check` : ''}`;
  return el('button', {
    class: 'btn btn-ghost btn-small parts-link',
    type: 'button',
    ...tipAttributes(title, 'Open the Parts tab: hull, decks, deckhouses and appendages.').attrs,
    onclick: () => setVesselTab('parts'),
  }, icon('cube'), el('span', { 'aria-hidden': 'true' }, String(count)),
  toCheck ? el('span', { class: 'parts-link-check', 'aria-hidden': 'true' }, icon('flag'), String(toCheck)) : null);
}
