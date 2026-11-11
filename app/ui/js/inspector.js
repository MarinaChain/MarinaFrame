// The run-details column: its tabs (Thinking, Steps, Checks, Calls, Evidence, Sources) and
// hiding and showing the column.

import { state, isRunning, setTab, prefs, addEvents, currentSection } from './app_state.js';
import { invoke } from './api.js';
import { fill, el, icon } from './dom.js';
import * as fmt from './format.js';
import { $, showError, chip, chevron } from './ui_kit.js';
import { toCheckCount, partsToCheck, needsCheck } from './run_facts.js';
import { cachedArtifact } from './artifacts.js';
import { createAreas } from './areas.js';
import { calibrationChoice } from './calibration.js';
import {
  TAB_META, TABS, tabAfter, tabName, storedDetails, reviewBadge, toggleNames, isDetailsOpen, reviewRailName,
} from './details.js';
import { tipAttributes } from './tooltip.js';
import { renderNarration } from './run_header.js';
import { placesIn, selectSection, nextToCheck } from './run_strip.js';
import { sources, sourcesKey, setVesselTab, afterPartsChange } from './vessel_pages.js';
import { live } from './workspace.js';

/** The inspector's Sources tab: the compact list; a pick opens the file on the Sources page. */
function renderSourcesPanel() {
  sources.showPanel($('panel-sources'), state.task, sourcesKey(state.view), (id) => {
    setVesselTab('sources');
    sources.select(id, { focus: true });
  });
}

/** HOOK(M3 live): the Thinking tab. M1 lists the model's recorded steps with their reasons. */
export function renderThinking() {
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
    let text = 'This run did not use the AI. Its steps are under Steps.';
    if (state.view.summary.policy === 'live') {
      // A stopped run will take no more steps, so "not yet" would mislead.
      text = isRunning() ? 'The AI has not taken a step yet.' : 'The AI took no recorded steps in this run. Its steps are under Steps.';
    }
    fill(panel, el('p', { class: 'panel-empty' }, text));
    return;
  }
  fill(panel, el('ol', { class: 'thinking', 'aria-label': 'AI steps, oldest first' },
    ...steps.map((step) => el('li', { class: 'thought' },
      el('span', { class: 'thought-dot', 'aria-hidden': 'true' }),
      el('span', { class: 'thought-body' },
        el('code', { class: 'thought-tool' }, step.tool),
        step.reason ? el('span', { class: 'thought-reason selectable-text' }, step.reason) : null)))));
}

// ---------------------------------------------------------------- inspector: tabs

export function selectTab(tab, { focus = false } = {}) {
  setTab(tab);
  prefs.set('tab', tab);
  for (const name of TABS) {
    const button = $(`tab-${name}`);
    const selected = name === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    $(`panel-${name}`).hidden = !selected;
  }
  if (tab === 'sources') renderSourcesPanel();
  if (focus) $(`tab-${tab}`).focus();
}

/** A tab is an icon (with a small count when there is one); the tooltip says the word. */
function renderTabButton(tab, count = 0, { failing = false } = {}) {
  const meta = TAB_META[tab];
  const button = $(`tab-${tab}`);
  const tip = tipAttributes(meta.word, meta.detail);
  for (const [name, value] of Object.entries(tip.attrs)) button.setAttribute(name, value);
  button.setAttribute('aria-label', tabName(tab, count, { failing }));
  fill(button, icon(meta.icon),
    count ? el('span', { class: `count${failing ? ' bad' : ''}`, 'aria-hidden': 'true' }, String(count)) : null,
    tip.describer);
}

export function renderTabs() {
  const view = state.view;
  const failing = view?.checks.filter((c) => c.result === 'fail').length || 0;
  const calls = view?.provider.length || 0;
  renderTabButton('checks', failing, { failing: true });
  renderTabButton('model', calls);
  renderThinking();
  renderTimeline();
  renderChecks();
  renderModelCalls();
  renderEvidence();
  if (state.tab === 'sources') renderSourcesPanel();
}

function eventRow(event, fresh = false) {
  return el('li', { class: fresh ? 'event fresh' : 'event', dataset: { kind: event.kind } },
    el('time', { class: 'event-time', datetime: new Date(event.time_ms).toISOString(), title: fmt.fullTime(event.time_ms) }, fmt.clock(event.time_ms)),
    el('span', { class: 'event-dot', 'aria-hidden': 'true' }),
    el('span', { class: 'selectable-text' }, placesIn(event.text)));
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

export function appendEvents(events) {
  // A task can change (a worker writes build files) without a new step; nothing to add then.
  if (!events.length) return;
  const panel = $('panel-timeline');
  const nearBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 40;
  addEvents(events);
  const list = panel.querySelector('.timeline');
  if (!list) {
    renderTimeline();
    return;
  }
  for (const event of events) list.append(eventRow(event, true));
  if (nearBottom) panel.scrollTop = panel.scrollHeight;
  renderNarration();
}

export let areas;

/** Create the section-area curve of the Checks tab. */
export function createAreaCurve() {
  // The section-area curve (js/areas.js) heads the Checks tab. A dot selects its station when
  // that station is one the run read (interpolated stations have no tile).
  areas = createAreas({
    invoke,
    onSelect: (id) => {
      if (state.view?.sections.some((s) => s.id === id)) selectSection(id);
    },
  });
}

/**
 * The automatic body-plan calibration (docs/AUTO_CALIBRATION.md) as one item to confirm: the
 * overlay (centreline, baseline, waterlines, FORE and AFT halves), whether the body-plan reader's
 * stations were used, the open flags, and Confirm / Wrong buttons saved like a part review.
 */
const BODY_PLAN_REVIEW_ID = 'body_plan_calibration';
function bodyPlanCheckCard(check) {
  if (!check) return null;
  const decision = check.review?.decision || 'open';
  const status = check.used
    ? `Stations ${check.stations_used.join(', ')} were measured by the body-plan reader.`
    : `Body-plan reader not used: ${check.reason}`;
  const image = el('img', { class: 'body-plan-check-image', alt: 'Body-plan calibration overlay', width: check.width, height: check.height });
  cachedArtifact('image', state.task, check.overlay_path).then((url) => { image.src = url; }, () => { image.alt = 'Overlay not readable'; });
  const save = (value, note = null) => invoke('review_component', { task: state.task, component_id: BODY_PLAN_REVIEW_ID, decision: value, note })
    .then(afterPartsChange, (error) => { showError(error); });
  const choice = el('div');
  const choose = () => fill(choice, calibrationChoice({
    check,
    onSave: (correction) => save('marked', JSON.stringify({ calibration_correction: correction })),
    onCancel: () => fill(choice),
  }));
  return el('section', { class: 'body-plan-check', 'aria-label': 'Body-plan calibration' },
    el('div', { class: 'body-plan-check-head' },
      el('strong', {}, 'Body-plan calibration'),
      chip({ accepted: 'Confirmed', marked: 'Marked wrong', open: 'To confirm' }[decision], { tone: decision === 'accepted' ? 'pass' : decision === 'marked' ? 'fail' : '', small: true })),
    el('p', { class: 'check-value selectable-text' }, status),
    ...check.flags.map((flag) => el('p', { class: 'body-plan-check-flag selectable-text' }, flag)),
    ...check.notes.concat(check.warnings).map((note) => el('p', { class: 'check-value selectable-text' }, note)),
    image,
    el('p', { class: 'chip-row' },
      el('button', { type: 'button', class: 'btn', onclick: () => save('accepted') }, 'Calibration is right'),
      el('button', { type: 'button', class: 'btn', onclick: choose }, 'Something is wrong'),
      decision !== 'open' ? el('button', { type: 'button', class: 'btn', onclick: () => save('open') }, 'Undo') : null),
    choice);
}

function renderChecks() {
  const panel = $('panel-checks');
  const checks = state.view?.checks || [];
  if (!state.view) {
    fill(panel);
    return;
  }
  areas.show(state.task, state.view, state.sectionId);
  const calibration = bodyPlanCheckCard(state.view.body_plan_check);
  if (!checks.length) {
    fill(panel, calibration, areas.element, el('p', { class: 'panel-empty' }, isRunning() ? 'Checks run after the 3D model is built.' : 'No checks ran for this run.'));
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
    calibration,
    areas.element,
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
  const costChip = chip(cost, { dot: false, small: true, title: 'List cost of the model requests' });
  // Costs and timings show on the Run tab only when the person turns them on (Settings).
  costChip.classList.add('cost-timing');
  const facts = [
    [fmt.plural(activity.requests, 'request'), 'Requests to the model'],
    [`${fmt.integer(activity.prompt_tokens)} sent`, 'Tokens sent to the model'],
    [`${fmt.integer(activity.completion_tokens)} received`, 'Tokens received from the model'],
  ];
  return el('details', { class: 'activity' },
    el('summary', { title: 'What the AI did in this run' }, chevron(), 'Model activity',
      chip(fmt.plural(activity.steps.length, 'step'), { dot: false, small: true })),
    el('p', { class: 'chip-row' }, ...facts.map(([text, title]) => chip(text, { dot: false, small: true, title })), costChip),
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
  const totalChip = chip(fmt.usd(totalCost), { dot: false, small: true, title: 'Cost of all calls' });
  totalChip.classList.add('cost-timing');
  const task = state.task;
  fill(panel,
    renderActivity(state.view.activity),
    el('p', { class: 'call-total chip-row' },
      chip(fmt.plural(calls.length, 'call'), { dot: false, small: true }),
      totalChip),
    ...calls.map((call) => {
      const images = el('div', { class: 'call-images' }, ...call.images.map((image) => {
        const img = el('img', { alt: image.label });
        cachedArtifact('image', task, image.path).then((url) => { img.src = url; }).catch(() => { img.alt = `${image.label} (missing)`; });
        return el('figure', {}, img, el('figcaption', {}, image.label));
      }));
      const facts = [
        call.prompt_tokens !== null && `${fmt.integer(call.prompt_tokens)} tokens sent`,
        call.completion_tokens !== null && `${fmt.integer(call.completion_tokens)} received`,
        call.cost_usd !== null && el('span', { class: 'cost-timing' }, fmt.usd(call.cost_usd)),
        call.key_slot !== null && `Key ${call.key_slot}`,
      ].filter(Boolean);
      const verdict = call.state === 'completed'
        ? el('span', { class: 'badge', dataset: { tone: call.accepted ? 'pass' : 'warn' } }, call.accepted ? 'Answer used' : 'Answer not used')
        : el('span', { class: 'badge', dataset: { tone: call.state === 'failed' ? 'fail' : '' } }, fmt.callStateLabel(call.state));
      return el('article', { class: 'call' },
        el('div', { class: 'call-head' }, verdict),
        call.images.length ? images : null,
        call.answer ? el('p', { class: 'call-answer selectable-text' }, call.answer) : null,
        facts.length ? el('p', { class: 'call-facts' }, ...facts.map((f) => (typeof f === 'string' ? el('span', {}, f) : f))) : null);
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

// ---------------------------------------------------------------- run details: hide and show

/** Open review items (sections and parts to check): the badge on the toggle while details are hidden. */
function openReviewItems(view) {
  return toCheckCount(view) + partsToCheck(view);
}

export function detailsAreOpen() {
  return document.documentElement.dataset.details !== 'closed';
}

/** Listeners told when the column opens or folds (the 3D view moves the part card). */
const detailsListeners = new Set();
export function onDetailsChange(listener) {
  detailsListeners.add(listener);
}

/**
 * Open or fold the column. `remember` stores a person's choice; an automatic open (a section
 * that needs a decision) does not, so the next run starts as the person left it.
 */
function setDetails(open, { remember = true } = {}) {
  const changed = detailsAreOpen() !== open || !document.documentElement.dataset.details;
  document.documentElement.dataset.details = open ? 'open' : 'closed';
  $('inspector').inert = !open;
  $('details-rail').hidden = open;
  if (remember) prefs.set('details', storedDetails(open));
  renderDetailsBadge();
  // The panes follow the freed width through their own resize observers.
  if (changed) for (const listener of detailsListeners) listener(open);
}

/** Names of the toggle and the rail, and the rail's review count (the rail shows only while folded). */
export function renderDetailsBadge() {
  const open = detailsAreOpen();
  const names = toggleNames(open, openReviewItems(state.view));
  const toggle = $('details-toggle');
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', names.spoken);
  toggle.dataset.tipTitle = names.title;
  const edge = $('details-edge');
  edge.setAttribute('aria-label', names.spoken);
  edge.dataset.tipTitle = names.title;
  // The rail's review button counts the sections to check: a press goes to the next one.
  const sections = toCheckCount(state.view);
  const review = $('details-review');
  const reviewName = reviewRailName(sections);
  review.hidden = !reviewName;
  if (reviewName) {
    review.setAttribute('aria-label', reviewName.spoken);
    review.dataset.tipTitle = reviewName.title;
    $('details-edge-count').textContent = reviewBadge(sections).text;
  }
}

export function toggleDetails() {
  setDetails(!detailsAreOpen());
}

/** Open the column for a section that needs a decision, without changing the stored choice. */
export function openDetailsForReview() {
  if (!detailsAreOpen()) setDetails(true, { remember: false });
}

/** The rail's tab icons: a press opens the column at that tab. */
function renderRailTabs() {
  fill($('details-rail-tabs'), ...TABS.map((tab) => {
    const meta = TAB_META[tab];
    const tip = tipAttributes(`Show ${meta.word}`, meta.detail);
    return el('button', {
      class: 'details-rail-item', type: 'button', 'aria-controls': 'inspector', dataset: { tab }, ...tip.attrs,
      onclick: () => {
        setDetails(true);
        selectTab(tab, { focus: true });
      },
    }, icon(meta.icon), tip.describer);
  }));
}

/** The details toggle, the rail and the remembered choice. */
export function installDetails() {
  $('details-toggle').addEventListener('click', toggleDetails);
  $('details-edge').addEventListener('click', () => {
    setDetails(true);
    $('details-toggle').focus();
  });
  $('details-review').addEventListener('click', () => {
    openDetailsForReview();
    if (!needsCheck(currentSection() || {})) nextToCheck();
    // The decision bar (Accept, Other line, Mark) is the first thing to reach.
    ($('selection').querySelector('.decision-bar button:not([disabled])') || $('details-toggle')).focus();
  });
  renderRailTabs();
  setDetails(isDetailsOpen(prefs.get('details', null), window.innerWidth), { remember: false });
}

// ---------------------------------------------------------------- picked part

/**
 * Show the picked part's fact card at the top of the column (`card` is a DOM node from
 * js/factcard3d.js), or clear it with null.
 */
export function showPartCard(card) {
  const slot = $('part-card');
  if (card) fill(slot, card);
  else fill(slot);
  slot.hidden = !card;
}

/** Tab buttons and arrow keys in the tab list. */
export function installTabs() {
  for (const tab of TABS) renderTabButton(tab);
  $('tabs').addEventListener('click', (event) => {
    const button = event.target.closest('[role="tab"]');
    if (button) selectTab(button.dataset.tab);
  });
  $('tabs').addEventListener('keydown', (event) => {
    const next = tabAfter(state.tab, event.key);
    if (!next) return;
    event.preventDefault();
    selectTab(next, { focus: true });
  });
}

/** Inspector panels fade at an edge only when more content is that way. */
export function installScrollEdges() {
  // Inspector panels fade at an edge only when more content is that way (styles.css).
  function markScrollEdges(panel) {
    panel.dataset.scrollTop = String(panel.scrollTop > 1);
    panel.dataset.scrollBottom = String(panel.scrollTop + panel.clientHeight < panel.scrollHeight - 1);
  }
  for (const panel of document.querySelectorAll('.tab-panel')) {
    const update = () => markScrollEdges(panel);
    panel.addEventListener('scroll', update, { passive: true });
    new ResizeObserver(update).observe(panel);
    new MutationObserver(update).observe(panel, { childList: true, subtree: true });
  }
}
