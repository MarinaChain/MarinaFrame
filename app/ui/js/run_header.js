// The run view around the panes: breadcrumb, run actions, notices, the run bar (status
// sentence, its drawer), the narration strip and the revision facts.

import { t } from './i18n.js';
import { state, isRunning, dropNotice } from './app_state.js';
import { invoke } from './api.js';
import { el, fill, icon } from './dom.js';
import * as fmt from './format.js';
import { $, chip, showError } from './ui_kit.js';
import { vesselOfTask, vesselNameOf, runNumber, needsCheck, partsToCheck } from './run_facts.js';
import { summarise, factsOfView, detailText } from './accuracy.js';
import { glyphChip, legendPopover } from './glyphs.js';
import { tipAttributes } from './tooltip.js';
import { navigate } from './router.js';
import { nextToCheck } from './run_strip.js';
import { openTask, replaceSheet } from './run.js';
import { statusSentence, reviewWords, errorWords, costWords } from './run_status.js';
import { renderStatusbar } from './settings_view.js';
import { renderVesselPage, setVesselTab } from './vessel_pages.js';
import { live } from './workspace.js';

// ---------------------------------------------------------------- title bar: breadcrumb

const ROUTE_TITLE_KEYS = {
  home: 'ko3.run_header.home', queue: 'ko3.run_header.queue', intake: 'ko3.run_header.newVessel',
  settings: 'ko3.run_header.settings', welcome: 'ko3.run_header.setup',
};
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
  // The design pages write their own breadcrumb (designs.js).
  if (state.route === 'designs' || state.route.startsWith('design/')) return;
  if (state.route !== 'run') {
    const routeIcon = ROUTE_ICONS[state.route];
    fill(crumbs, el('span', { class: 'crumb crumb-current', 'aria-current': 'page' },
      routeIcon ? icon(routeIcon) : null, t(ROUTE_TITLE_KEYS[state.route])));
    document.title = 'MarinaFrame';
    return;
  }
  if (!view) {
    fill(crumbs, el('span', { class: 'crumb crumb-current' }, t('ko3.run_header.run')));
    document.title = 'MarinaFrame';
    return;
  }
  const vessel = vesselOfTask(state.tasks, state.task);
  const vesselName = vessel?.name || vesselNameOf(view.summary.name);
  // The run crumb is a picker when the vessel has more than one run.
  const runCrumb = vessel && vessel.runs.length > 1
    ? el('select', {
      class: 'crumb crumb-select',
      'aria-label': t('ko3.run_header.runOfThisVessel'),
      title: view.summary.name,
      onchange: (event) => openTask(event.target.value),
    }, ...vessel.runs.map((run) => {
      const option = el('option', { value: run.task }, t('ko3.runNumber', { number: runNumber(vessel, run.task) }));
      option.selected = run.task === state.task;
      return option;
    }))
    : el('span', { class: 'crumb', title: view.summary.name }, t('ko3.runNumber', { number: vessel ? runNumber(vessel, state.task) : 1 }));
  fill(crumbs,
    el('button', { class: 'crumb crumb-link', type: 'button', title: t('ko3.backHome', { name: vesselName }), onclick: () => navigate('home') }, vesselName),
    crumbSeparator(),
    runCrumb,
    view.revision ? [crumbSeparator(), el('span', { class: 'crumb crumb-current crumb-mono', 'aria-current': 'page', title: t('ko3.revision', { revision: view.revision }) }, view.revision)] : null);
  document.title = t('ko3.documentTitle', { name: vesselName });
  $('run-title').textContent = t('ko3.runTitle', { name: vesselName, number: vessel ? runNumber(vessel, state.task) : 1 });
  badge.dataset.status = view.summary.status;
  fill(badge, el('span', { class: 'badge-text' }, fmt.statusLabel(view.summary.status)));
  badge.title = fmt.statusLabel(view.summary.status);
}

export function renderActions() {
  const status = state.view?.summary.status;
  const resume = $('resume-task');
  const cancel = $('cancel-task');
  resume.hidden = !['paused', 'blocked', 'cancelled', 'stalled'].includes(status);
  resume.textContent = status === 'stalled' ? t('ko3.run_header.keepWaiting') : t('ko3.run_header.resume');
  cancel.hidden = !['running', 'stalled'].includes(status);
  resume.disabled = cancel.disabled = Boolean(state.busy);
  renderVesselPage();
}

/** Run mode chip: "AI draft" for the live policy, else "Deterministic". */
function policyChip(policy) {
  return policy === 'live'
    ? glyphChip('src-ai_inferred', t('ko3.run_header.aiDraft'), { tone: 'ai', detail: t('ko3.run_header.aiDraftHelp') })
    : glyphChip('gear', t('ko3.run_header.noAI'), { detail: t('ko3.run_header.deterministicDraftNoModelCalls') });
}

// ---------------------------------------------------------------- run view: hooks for the live lane

/** HOOK(M3 live): narration strip. M1 shows the latest recorded step in plain words. */
export function renderNarration() {
  // The narration row shows only while the run works (or a replay is open, styles.css).
  $('workspace').dataset.running = String(isRunning());
  if (live.hasSteps()) {
    live.renderNarration();
    return;
  }
  const strip = $('narration');
  const last = state.events[state.events.length - 1];
  strip.dataset.live = String(isRunning());
  if (!state.view || !last) {
    fill(strip, el('span', { class: 'narration-dot', 'aria-hidden': 'true' }),
      el('span', { class: 'narration-text narration-empty' }, state.view ? t('ko3.run_header.noStepsRecordedYet') : ''));
    return;
  }
  fill(strip,
    el('span', { class: 'narration-dot', 'aria-hidden': 'true' }),
    el('span', { class: 'narration-text', title: last.text }, last.text),
    el('time', { class: 'narration-time', datetime: new Date(last.time_ms).toISOString() }, fmt.clock(last.time_ms)));
}

/**
 * HOOK(M3 live, M7 compare): the run's revisions and facts, in the run drawer. Without live
 * steps the ladder shows the current revision; the live lane draws the full ladder. The facts:
 * Draft only, the run mode, the model requests and list cost (a cost-timing fact: hidden on the
 * Run tab unless the person shows costs), and when the run changed.
 */
export function renderRevisionStrip() {
  const view = state.view;
  if (live.hasSteps()) live.renderLadder();
  else fill($('revision-ladder'), view
    ? (view.revision
      ? el('span', { class: 'rev-step rev-current', title: t('ko3.revision', { revision: view.revision }) }, view.revision)
      : el('span', { class: 'rev-empty' }, t('ko3.run_header.noRevisionYet')))
    : null);
  if (!view) {
    fill($('revision-facts'));
    return;
  }
  const cost = costWords(view);
  fill($('revision-facts'),
    chip(t('ko3.run_header.draftOnly'), { dot: false, small: true, title: t('ko3.run_header.draftOnlyHelp') }),
    policyChip(view.summary.policy),
    cost ? el('span', { class: 'rev-fact cost-timing' }, cost) : null,
    el('span', { class: 'rev-fact', title: t('ko3.updated', { time: fmt.fullTime(view.summary.updated_ms) }) }, t('ko3.updated', { time: fmt.relativeTime(view.summary.updated_ms) })));
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
 * The backend's draft banner ("Draft: 2 guesses to check. ..."). The run bar's status
 * sentence says the same thing, so the banner does not show as a notice.
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
        title: t('ko3.run_header.dismiss'),
        'aria-label': t('ko3.dismiss', { text: notice.text }),
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

// ---------------------------------------------------------------- run bar and run drawer

/** The drawer under the status sentence is open (kept across renders of the run bar). */
let drawerOpen = false;

/**
 * The run bar's status sentence ("Draft · 2 sections need you · Lines plan: lines too faint"),
 * its primary action (Replace a sheet) and Next; then the drawer's detail in words: the review,
 * the warnings, the hull error band and the parts.
 */
export function renderDraftSummary() {
  const view = state.view;
  $('run-bar').hidden = !view;
  if (!view) {
    fill($('run-status'));
    fill($('draft-summary'));
    setDrawer(false);
    return;
  }
  const { parts, action } = statusSentence(view);
  const open = (view.sections || []).filter(needsCheck).length;
  const sentence = parts.join(' · ');
  const needsPerson = Boolean(open || action);
  // No tooltip: it would repeat the sentence over the drawer it opens.
  fill($('run-status'),
    el('button', {
      class: 'run-status-toggle',
      id: 'run-status-toggle',
      type: 'button',
      'aria-expanded': String(drawerOpen),
      'aria-controls': 'run-drawer',
      dataset: { tone: needsPerson ? 'attention' : 'calm' },
      onclick: () => setDrawer(!drawerOpen),
    }, icon(needsPerson ? 'flag' : 'checks'), el('span', { class: 'run-status-text' }, sentence), icon('chevron', 'run-status-chevron')),
    action ? el('button', {
      class: 'btn btn-small run-status-action write-action',
      type: 'button',
      disabled: Boolean(state.busy) || isRunning(),
      ...tipAttributes(t('ko3.replace', { label: action.label }), t('ko3.run_header.replaceHelp'), { label: false }).attrs,
      onclick: () => replaceSheet(action.sheetId),
    }, t('ko3.run_header.replace')) : null,
    open ? el('button', {
      class: 'btn btn-small run-status-next',
      type: 'button',
      disabled: isRunning(),
      ...tipAttributes(t('ko3.run_header.nextSectionToCheckN'), null, { label: false }).attrs,
      onclick: nextToCheck,
    }, t('ko3.run_header.next'), el('kbd', { class: 'key-hint' }, 'N')) : null);
  fill($('draft-summary'), drawerSummary(view));
}

/** The drawer's first group: the review in words, the warnings, the error band, the parts. */
function drawerSummary(view) {
  const warnings = view.warnings || [];
  const parts = view.components || [];
  const review = reviewWords(view);
  const accuracy = accuracyLines(view);
  if (!review && !accuracy.length && !parts.length) return null;
  return el('div', { class: 'drawer-group' },
    el('h2', { class: 'drawer-title' }, t('ko3.run_header.draft')),
    review ? el('p', { class: 'drawer-line' }, el('span', {}, review), view.source_counts?.length ? legendPopover() : null) : null,
    warnings.length ? el('details', { class: 'draft-warnings' },
      el('summary', {}, t('ko3.warnings', { warnings: fmt.plural(warnings.length, 'warning') })),
      el('ul', { class: 'selectable-text' }, ...warnings.map((w) => el('li', {}, w)))) : null,
    ...accuracy,
    parts.length ? partsLink(view, parts.length) : null);
}

/** "Hull 0.8–14 % from the drawing", one line per output; the tooltip says what it means. */
function accuracyLines(view) {
  if (!view?.revision) return [];
  return Object.values(summarise(factsOfView(view))).filter((s) => s.present).map((summary) => {
    const name = t(`ko3.output.${summary.output}`);
    const tip = tipAttributes(`${name}: ${errorWords(summary.chip)}`,
      t('ko3.accuracy', { name: name.toLowerCase(), detail: detailText(summary) }));
    return el('p', { class: 'drawer-line drawer-accuracy', tabindex: '0', ...tip.attrs, dataset: { caution: String(summary.caution) } },
      el('span', { class: 'drawer-key', 'aria-hidden': 'true' }, name),
      el('span', { 'aria-hidden': 'true' }, errorWords(summary.chip)), tip.describer);
  });
}

/** Whole-vessel parts: one button to the Parts tab, with how many still need a look. */
function partsLink(view, count) {
  const toCheck = partsToCheck(view);
  return el('button', {
    class: 'btn btn-ghost btn-small parts-link',
    type: 'button',
    ...tipAttributes(t('ko3.run_header.openThePartsTab'), t('ko3.run_header.hullDecksDeckhousesAndAppendages'), { label: false }).attrs,
    onclick: () => { setDrawer(false); setVesselTab('parts'); },
  }, icon('cube'), `${fmt.plural(count, 'part')}${toCheck ? t('ko3.partsToCheck', { count: toCheck }) : ''}`);
}

/** Open or close the run drawer; closing gives the focus back to the sentence if it was inside. */
function setDrawer(open) {
  const drawer = $('run-drawer');
  const toggle = document.getElementById('run-status-toggle');
  const hadFocus = drawer.contains(document.activeElement);
  drawerOpen = open;
  drawer.hidden = !open;
  toggle?.setAttribute('aria-expanded', String(open));
  if (!open && hadFocus) toggle?.focus();
}

/** The drawer closes with Escape (focus in it or on the sentence) and a click outside the bar. */
export function installRunDrawer() {
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !drawerOpen) return;
    const target = event.target;
    if (!$('run-drawer').contains(target) && target.id !== 'run-status-toggle') return;
    event.preventDefault();
    event.stopPropagation();
    setDrawer(false);
    document.getElementById('run-status-toggle')?.focus();
  }, true);
  document.addEventListener('pointerdown', (event) => {
    if (!drawerOpen) return;
    if ($('run-drawer').contains(event.target) || $('run-status').contains(event.target)) return;
    setDrawer(false);
  });
}
