// The section strip, the selected section in the inspector and the one decision per section.

import { state, isRunning, setSectionId, currentSection } from './app_state.js';
import { invoke } from './api.js';
import { el, fill, icon, svg } from './dom.js';
import * as fmt from './format.js';
import { $, chevron } from './ui_kit.js';
import { needsCheck, sectionShapePath } from './run_facts.js';
import { isGaRun } from './run_status.js';
import { t } from './i18n.js';
import { stateGlyph, sourceGlyph, glyphChip } from './glyphs.js';
import { tipAttributes } from './tooltip.js';
import { areas, openDetailsForReview } from './inspector.js';
import { runAction, loadTask, refreshTasksSoon } from './run.js';
import { live, evidence, drawing, model, markTool } from './workspace.js';

/** Empty tiles in the section strip while a run reads the drawing: a hint of what will fill it. */
const STRIP_PLACEHOLDER_TILES = 3;

// ---------------------------------------------------------------- section strip

/** "st12" -> "12.0 m": a section by its place, as on the strip (the id when unknown). */
export function sectionPlace(id) {
  const section = state.view?.sections.find((s) => s.id === id);
  return section ? fmt.metres(section.x_m) : id;
}

/** A step text with section ids shown as places ("st12" becomes "12.0 m"). */
export function placesIn(text) {
  const places = new Map((state.view?.sections || []).map((s) => [s.id, fmt.metres(s.x_m)]));
  return fmt.withPlaces(text, places);
}

/** Placeholder tiles while a run reads the drawing; a plain line when a finished run has none. */
function stripEmpty() {
  if (!state.view) return null;
  if (isRunning()) {
    const placeholders = Array.from({ length: STRIP_PLACEHOLDER_TILES }, () => el('div', { class: 'tile tile-placeholder', 'aria-hidden': 'true' }));
    return [el('p', { class: 'strip-empty strip-waiting', role: 'status' },
      el('span', { class: 'spinner', 'aria-hidden': 'true' }), t('ko3.run_strip.sectionsAppearHereAsTheAIReadsThem')), ...placeholders];
  }
  if (isGaRun(state.view)) return el('p', { class: 'strip-empty' }, t('ga.noSections'));
  return el('p', { class: 'strip-empty' }, t('ko3.run_strip.thisRunFoundNoSectionsOnTheDrawing'));
}

/** Select the next section to check after the current one (wraps to the first). */
export function nextToCheck() {
  const sections = state.view?.sections || [];
  const index = sections.findIndex((s) => s.id === state.sectionId);
  const ordered = [...sections.slice(index + 1), ...sections.slice(0, index + 1)];
  const next = ordered.find(needsCheck);
  if (next) {
    selectSection(next.id);
    $(`tile-${next.id}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
}

/** The review count left of the tiles, as an icon and "open/total" (the status row has Next). */
function renderStripHead() {
  const sections = state.view?.sections || [];
  const open = sections.filter(needsCheck).length;
  const head = $('strip-head');
  head.hidden = !sections.length;
  if (!sections.length) return;
  const tip = tipAttributes(t('ko3.toCheck', { open, sections: fmt.plural(sections.length, 'section') }));
  fill(head, el('span', { class: 'strip-count', role: 'img', tabindex: '0', dataset: { open: String(open > 0) }, ...tip.attrs },
    icon('flag'), el('strong', { 'aria-hidden': 'true' }, String(open)), el('span', { 'aria-hidden': 'true' }, `/${sections.length}`)));
}

export function renderStrip() {
  const strip = $('strip');
  const sections = state.view?.sections || [];
  renderStripHead();
  if (!sections.length) {
    fill(strip, stripEmpty());
    strip.removeAttribute('aria-activedescendant');
    // Without tiles the strip is a plain status line, not a list box with no options.
    strip.removeAttribute('role');
    strip.removeAttribute('aria-orientation');
    return;
  }
  strip.setAttribute('role', 'listbox');
  strip.setAttribute('aria-orientation', 'horizontal');
  const ink = live.hasSteps() ? live.latestInk() : new Map();
  fill(strip, ...sections.map((section) => {
    const path = sectionShapePath(section);
    return el('div', {
      class: 'tile',
      role: 'option',
      id: `tile-${section.id}`,
      'aria-selected': String(section.id === state.sectionId),
      'aria-label': t('ko3.sectionLabel', { place: fmt.metres(section.x_m), state: fmt.sectionStateLabel(section.state), source: section.source ? `, ${fmt.sourceLabel(section.source.label)}` : '' }),
      dataset: { section: section.id, state: section.state, source: section.source?.label },
      onclick: () => { evidence.hide(); selectSection(section.id); },
      onmouseenter: (event) => evidence.hoverStart(event.currentTarget, section),
      onmouseleave: () => evidence.hide(),
    },
    svg('svg', { class: 'tile-shape', viewBox: '0 0 44 54', 'aria-hidden': 'true' },
      svg('path', { class: 'axis', d: 'M2 2V52' }),
      path ? svg('path', {
        class: section.source ? 'shape src-stroke' : 'shape',
        'data-source': section.source?.label,
        d: path,
      }) : null),
    el('span', { class: 'tile-head' },
      el('span', { class: 'tile-x' }, section.x_m.toFixed(1), el('small', {}, ' m')),
      stateGlyph(section.state, { focusable: false, hoverTip: false }),
      section.source ? sourceGlyph(section.source.label, { focusable: false, hoverTip: false }) : null),
    el('span', { class: 'tile-chips' },
      Number.isFinite(ink.get(section.id))
        ? el('span', { class: 'tile-ink', title: t('ko3.run_strip.inkDistanceHelp') }, fmt.millimetres(ink.get(section.id)))
        : null));
  }));
  strip.setAttribute('aria-activedescendant', `tile-${state.sectionId}`);
}

export function selectSection(id, { focusDrawing = true } = {}) {
  if (!id || id === state.sectionId) return;
  setSectionId(id);
  for (const tile of document.querySelectorAll('.tile')) tile.setAttribute('aria-selected', String(tile.dataset.section === id));
  $('strip').setAttribute('aria-activedescendant', `tile-${id}`);
  document.getElementById(`tile-${id}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  renderSelection();
  // A section that needs a decision opens the folded column at Accept, Other line and Mark.
  if (needsCheck(currentSection() || {})) openDetailsForReview();
  drawing.setSections(state.view.sections, id, { focus: focusDrawing });
  model.setSelected(id);
  areas.show(state.task, state.view, id);
}

export function stepSection(delta) {
  const sections = state.view?.sections || [];
  if (!sections.length) return;
  const index = sections.findIndex((s) => s.id === state.sectionId);
  const next = sections[Math.min(sections.length - 1, Math.max(0, index + delta))];
  selectSection(next.id);
}

// ---------------------------------------------------------------- inspector: selection

export function renderSelection() {
  const head = $('selection-head');
  const body = $('selection');
  const view = state.view;
  const section = currentSection();

  if (!view) {
    fill(head, el('h2', {}, t('ko3.run_strip.section')));
    fill(body, el('p', { class: 'selection-empty' }, (state.task || state.pendingOpen) ? t('ko3.run_strip.openingTheRun') : t('ko3.run_strip.openARunToSeeItsSections')));
    return;
  }
  if (!section) {
    fill(head, el('h2', {}, t('ko3.run_strip.section')));
    fill(body, el('p', { class: 'selection-empty' }, isRunning() ? t('ko3.run_strip.sectionsAppearHereAsTheRunReadsThem') : t('ko3.run_strip.thisRunHasNoSections')));
    return;
  }

  fill(head,
    el('h2', {}, el('span', { class: 'visually-hidden' }, t('ko3.run_strip.sectionAt')), fmt.metres(section.x_m)),
    stateGlyph(section.state, { small: false }),
    section.source ? sourceGlyph(section.source.label, { detail: section.source.basis || null, small: false }) : null,
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
    // The decision bar already offers Accept and the one other line; a line row keeps its
    // own button only when the bar does not cover it (one way to decide each line).
    const coveredByBar = candidate === otherCandidate(section) && needsCheck(section);
    if (guessedLine) {
      trailing = stateGlyph('guessed');
    } else if (candidate.chosen) trailing = glyphChip('st-chosen', t('ko3.run_strip.inUse'), { tone: 'brand' });
    else if (candidate.selectable && coveredByBar) {
      const tip = tipAttributes(t('ko3.run_strip.otherLineO'), t('ko3.run_strip.useItWithOtherLineAbove'));
      trailing = el('kbd', { class: 'key-hint cand-key', role: 'img', tabindex: '0', ...tip.attrs }, 'O', tip.describer);
    } else if (candidate.selectable) {
      const label = guessedSection ? t('ko3.run_strip.useInstead') : t('ko3.run_strip.use');
      if (guessedSection) action = chooseButton(section, candidate, label, canChoose, false);
      else trailing = chooseButton(section, candidate, label, canChoose, false);
    }
    return el('div', {
      class: 'cand-row',
      role: 'listitem',
      dataset: { candidate: candidate.id },
      onmouseenter: () => drawing.highlightCandidate(candidate.id),
      onmouseleave: () => drawing.highlightCandidate(null),
      onfocusin: () => drawing.highlightCandidate(candidate.id),
      onfocusout: () => drawing.highlightCandidate(null),
    }, swatch, el('span', { class: 'cand-label', 'data-tip-title': candidate.label, 'data-tip-detail': candidate.why || null }, candidate.label), trailing || el('span'),
    action ? el('div', { class: 'cand-actions' }, action) : null);
  });

  fill(body,
    decisionBar(section),
    rows.length ? el('div', { class: 'cand-list', role: 'list', 'aria-label': t('ko3.run_strip.linesFoundInThisSection') }, ...rows) : null,
    selectionWhy(section),
  );
}

/**
 * The section's explanations on demand: a one-line fact in the summary ("2 lines · best
 * 0.62", else the reason cut to one line), and inside, the reason, the source's basis and
 * why each line was read as it was.
 */
function selectionWhy(section) {
  const facts = fmt.reasonFacts(section.reason);
  const lines = section.candidates.filter((c) => c.why);
  if (!section.reason && !section.source?.basis && !lines.length) return null;
  return el('details', { class: 'selection-source' },
    el('summary', {},
      chevron(),
      icon(facts ? 'lines' : 'info'),
      el('span', { class: 'selection-fact' }, facts || section.reason || t('ko3.run_strip.why')),
      el('span', { class: 'selection-why-word' }, t('ko3.run_strip.why'))),
    el('div', { class: 'selection-why selectable-text' },
      facts || !section.reason ? (section.reason ? el('p', {}, section.reason) : null) : null,
      section.source?.basis ? el('p', {}, el('strong', {}, `${fmt.sourceLabel(section.source.label)}: `), section.source.basis) : null,
      lines.length ? el('dl', { class: 'why-lines' }, ...lines.flatMap((c) => [el('dt', {}, c.label), el('dd', {}, c.why)])) : null));
}

// ---- One decision per section, with keys (research finding 2): Accept (A) the guessed line,
// use the Other line (O), or Mark (M) the drawing and say what to fix. After a decision the
// next section to check opens, so a review is a short run of key presses.

export function canDecide() {
  return !state.busy && !isRunning() && needsCheck(currentSection() || {});
}

/** The line a person accepts with A: the guessed line of a guessed section. */
export function acceptCandidate(section) {
  return section?.state === 'guessed' ? section.candidates.find((c) => c.chosen) || null : null;
}

/** The line O uses: the one other line that could be used, when there is exactly one. */
export function otherCandidate(section) {
  const others = section?.candidates.filter((c) => c.selectable && !c.chosen) || [];
  return others.length === 1 ? others[0] : null;
}

export async function decide(section, candidate) {
  if (!candidate) return;
  const id = section.id;
  await chooseLine(section, candidate);
  const after = state.view?.sections.find((s) => s.id === id);
  if (after && !needsCheck(after)) nextToCheck();
}

function decisionBar(section) {
  if (!needsCheck(section)) return null;
  const canChoose = !state.busy && !isRunning();
  const accept = acceptCandidate(section);
  const other = otherCandidate(section);
  const key = (letter) => el('kbd', { class: 'key-hint' }, letter);
  return el('div', { class: 'decision-bar write-action', role: 'group', 'aria-label': t('ko3.run_strip.decideThisSection') },
    accept ? el('button', {
      class: 'btn btn-primary',
      type: 'button',
      disabled: !canChoose,
      title: t('ko3.accept', { line: accept.label.toLowerCase() }),
      onclick: () => decide(section, accept),
    }, t('ko3.run_strip.accept'), key('A')) : null,
    other ? el('button', {
      class: 'btn',
      type: 'button',
      disabled: !canChoose,
      title: t('ko3.other', { line: other.label.toLowerCase() }),
      onclick: () => decide(section, other),
    }, t('ko3.run_strip.otherLine'), key('O')) : null,
    el('button', {
      class: 'btn',
      type: 'button',
      disabled: isRunning(),
      title: t('ko3.run_strip.markPartOfTheDrawingAndSayWhatToFixM'),
      onclick: () => markTool.setActive(true),
    }, t('ko3.run_strip.mark'), key('M')),
    !accept && !other
      ? el('span', { class: 'decision-hint' }, section.candidates.some((c) => c.selectable) ? t('ko3.run_strip.pickALineBelow') : t('ko3.run_strip.noLineToPickMarkTheDrawing'))
      : null);
}

function chooseButton(section, candidate, label, canChoose, primary) {
  return el('button', {
    class: primary ? 'btn btn-small btn-primary write-action' : 'btn btn-small write-action',
    type: 'button',
    disabled: !canChoose,
    title: isRunning() ? t('ko3.run_strip.availableWhenTheRunStops') : t('ko3.useLine', { label, line: candidate.label.toLowerCase() }),
    onclick: () => chooseLine(section, candidate),
  }, label);
}

/** Progress text for a line choice, resolved in the current language. */
function lineChoiceProgress(confirming, label, x) {
  return t(confirming ? 'ko3.confirmLine' : 'ko3.useLineProgress', { line: label.toLowerCase(), place: fmt.metres(x) });
}

async function chooseLine(section, candidate) {
  const task = state.task;
  const confirming = section.state === 'guessed' && candidate.chosen;
  const done = await runAction(lineChoiceProgress(confirming, candidate.label, section.x_m), () =>
    invoke('choose_line', { task, section_id: section.id, candidate_id: candidate.id }));
  if (done && task === state.task) {
    await loadTask();
    refreshTasksSoon();
  }
}

/** Arrow keys walk the section strip. */
export function installStripKeys() {
  $('strip').addEventListener('keydown', (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    stepSection(step);
  });
}
