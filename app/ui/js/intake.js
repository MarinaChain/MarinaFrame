// Intake (M2, storyboard F4): a dropped drawing set becomes a run without a spec file.
//
// prepare_intake reads the files and proposes view regions per page. This view shows the pages
// in a tray and the selected page large (the "stage"), lets the person correct region labels,
// skip pages and type what they know of the vessel, then start_intake_run starts the run and the app opens its live screen.
// Contract: docs/APP_SPEC.md, section "Intake".

import { t } from './i18n.js';
import { el, svg, icon, fill } from './dom.js';
import { checklistPanel, computeChecklist, scaleChip, typeChip, typePicker, withType } from './drawing_set.js';

/** The labels a region can have, in picker order, with the words people see. */
const VIEW_LABELS = [
  ['body_plan', 'ko3.view.body_plan'],
  ['half_breadth', 'ko3.view.half_breadth'],
  ['profile', 'ko3.view.profile'],
  ['title_block', 'ko3.view.title_block'],
  ['other', 'ko3.view.other'],
];
const LABEL_KEYS = Object.fromEntries(VIEW_LABELS);
/** A proposed view label in the current language. */
export function viewLabel(label) {
  return LABEL_KEYS[label] ? t(LABEL_KEYS[label]) : undefined;
}
/** Page count for a drawing set; include the kept count only when pages were skipped. */
export function intakePageCount(total, kept = total) {
  return total === kept
    ? t('ko3.pages', { count: total, unit: t(total === 1 ? 'ko3.pageSingular' : 'ko3.pagePlural') })
    : t('ko3.keptPages', { kept, total });
}

/** The three views a hull is built from. The set summary says which kept pages show each one. */
const HULL_VIEWS = ['body_plan', 'half_breadth', 'profile'];

/** Below this confidence a proposed label is drawn dashed: check it. */
const UNSURE_BELOW = 0.5;
/** Gap in screen pixels between a region chip and the region edge or another chip. */
const CHIP_GAP_PX = 4;

/** Optional particulars: field name, label, unit. All in metres; never required. */
const PARTICULAR_FIELDS = [
  ['loa_m', 'ko3.particular.loa_m'],
  ['beam_m', 'ko3.particular.beam_m'],
  ['depth_m', 'ko3.particular.depth_m'],
  ['draft_m', 'ko3.particular.draft_m'],
];

/** The set warning that the AI line replaces (the line uses the current AI status). */
const AI_OFF_WARNING = 'ai_off';

const clone = (value) => JSON.parse(JSON.stringify(value));
const percent = (value) => `${Math.round(value * 100)}%`;

/** "survey-launch_lines.pdf" -> "Survey launch lines": a first guess at the vessel name. */
function nameFromFile(fileName) {
  const stem = fileName.replace(/\.[^.]+$/, '').replace(/[-_.]+/g, ' ').replace(/\s+/g, ' ').trim();
  return stem ? stem[0].toUpperCase() + stem.slice(1) : '';
}

/** A positive number, null for an empty field, NaN for anything else. */
function readPositive(text) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value > 0 ? value : Number.NaN;
}

/**
 * The intake view. `host` is the view element; `onStarted(task)` opens the new run;
 * `onClose()` leaves the view; `openSettings()` shows Settings (the view keeps its edits).
 */
export function createIntake({ host, invoke, refreshAiStatus, onStarted, onClose, openSettings }) {
  let preview = null; // the edited IntakePreview
  let selectedPageId = null; // the page shown large in the stage
  let aiStatus = null;
  let loading = null; // { count } while prepare_intake reads the files
  let starting = false;
  let error = '';
  let token = 0;
  // Chip positions are in pixels, so they follow the page size.
  window.addEventListener('resize', () => requestAnimationFrame(placeChips));
  document.addEventListener('keydown', onKey);
  /** The form values, kept as typed so a half-typed number is not lost on render. */
  let form = { vessel_name: '', scale: '', loa_m: '', beam_m: '', depth_m: '', draft_m: '' };

  // ---------------------------------------------------------------- actions

  /** Read the dropped or chosen files. Resolves false when a newer set replaced this one; rejects on a backend error. */
  async function prepare(files) {
    const mine = ++token;
    preview = null;
    error = '';
    loading = { count: files.length };
    render();
    try {
      const [result, status] = await Promise.all([invoke('prepare_intake', { files }), refreshAiStatus()]);
      if (mine !== token) return false;
      aiStatus = status;
      preview = clone(result);
      selectedPageId = (preview.pages.find((p) => !p.skip) || preview.pages[0])?.page_id || null;
      form = initialForm(preview);
      return true;
    } catch (failure) {
      if (mine !== token) return false; // cancelled, or a newer set replaced this one
      throw failure;
    } finally {
      if (mine === token) {
        loading = null;
        render();
      }
    }
  }

  function initialForm(set) {
    const known = set.particulars || {};
    const firstPage = set.pages.find((p) => !p.skip) || set.pages[0];
    const asText = (value) => (value === null || value === undefined ? '' : String(value));
    return {
      vessel_name: known.vessel_name || (firstPage ? nameFromFile(firstPage.file_name) : ''),
      scale: asText(known.scale).replace(/^1\s*:\s*/, ''),
      loa_m: asText(known.loa_m),
      beam_m: asText(known.beam_m),
      depth_m: asText(known.depth_m),
      draft_m: asText(known.draft_m),
    };
  }

  /** The particulars to send, or null when a typed number is not valid. */
  function particulars() {
    const result = { vessel_name: form.vessel_name.trim() };
    for (const [key] of PARTICULAR_FIELDS) {
      const value = readPositive(form[key]);
      if (Number.isNaN(value)) return null;
      result[key] = value;
    }
    const scale = readPositive(form.scale);
    if (Number.isNaN(scale)) return null;
    result.scale = scale === null ? null : `1:${scale}`;
    return result;
  }

  // ---------------------------------------------------------------- pages

  function selectPage(pageId, { focusTray = false } = {}) {
    selectedPageId = pageId;
    render();
    if (focusTray) host.querySelector(`#tray-${CSS.escape(pageId)}`)?.focus();
  }

  /** Move to the previous (-1) or next (+1) page. Returns false at either end. */
  function stepPage(delta, options) {
    const pages = preview?.pages || [];
    const index = pages.findIndex((p) => p.page_id === selectedPageId);
    const next = pages[index + delta];
    if (!next) return false;
    selectPage(next.page_id, options);
    return true;
  }

  function toggleSkip(page) {
    page.skip = !page.skip;
    render();
  }

  /**
   * Intake keys: [ ] (and ↑ ↓ in the tray) go between pages, S skips or keeps the page shown.
   * They act only while this view shows a set and no text field has focus.
   */
  function onKey(event) {
    if (!preview || loading || starting || host.closest('[hidden]') || !host.isConnected) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.target.closest?.('input, textarea, select, [contenteditable="true"], dialog')) return;
    const inTray = Boolean(event.target.closest?.('.intake-tray'));
    let handled = false;
    if (event.key === '[' || (inTray && event.key === 'ArrowUp')) handled = stepPage(-1, { focusTray: inTray });
    else if (event.key === ']' || (inTray && event.key === 'ArrowDown')) handled = stepPage(1, { focusTray: inTray });
    else if (inTray && (event.key === 'Home' || event.key === 'End')) {
      const pages = preview.pages;
      selectPage(pages[event.key === 'Home' ? 0 : pages.length - 1].page_id, { focusTray: true });
      handled = true;
    }
    else if (event.key === 's' || event.key === 'S') {
      const page = preview.pages.find((p) => p.page_id === selectedPageId);
      if (page) { toggleSkip(page); handled = true; }
    }
    if (handled) event.preventDefault();
  }

  function keptPages() {
    return preview ? preview.pages.filter((p) => !p.skip) : [];
  }

  /** Why Start reading is off, in one line; empty when the run can start. */
  function blockedReason() {
    if (!aiStatus?.active) return 'ai';
    if (!keptPages().length) return t('ko3.intake.allSkipped');
    if (!particulars()) return t('ko3.intake.invalidParticular');
    return '';
  }

  async function start() {
    if (!preview || starting || blockedReason()) return;
    starting = true;
    error = '';
    render();
    try {
      const edited = { ...clone(preview), particulars: particulars(), ai_active: Boolean(aiStatus?.active) };
      const { task } = await invoke('start_intake_run', { preview: edited });
      preview = null;
      await onStarted(task);
    } catch (failure) {
      error = failure.message;
    } finally {
      starting = false;
      render();
    }
  }

  function cancel() {
    // Stop the drawing reader too, not only the wait for it.
    if (loading) invoke('cancel_intake').catch(() => {});
    token += 1;
    preview = null;
    loading = null;
    error = '';
    onClose();
  }

  // ---------------------------------------------------------------- rendering

  function aiLine() {
    const reason = !aiStatus?.enabled
      ? t('ko3.intake.aiDraftingIsOff')
      : t('ko3.intake.noModelKeyIsSetUp');
    return el('p', { class: 'intake-ai-line', role: 'note' },
      icon('warn'),
      el('span', {}, t('ko3.aiRequired', { reason })),
      el('button', { class: 'btn btn-small', type: 'button', onclick: openSettings }, t('ko3.intake.openSettings')));
  }

  function warningChip(warning) {
    return el('span', { class: 'badge badge-small', dataset: { tone: 'warn' }, title: warning.message },
      icon('warn'), el('span', { class: 'badge-text' }, warning.message));
  }

  function head() {
    const kept = keptPages().length;
    const total = preview?.pages.length || 0;
    const reason = preview ? blockedReason() : 'loading';
    const startButton = el('button', {
      class: 'btn btn-primary btn-large',
      type: 'button',
      id: 'intake-start',
      disabled: Boolean(reason) || starting,
      title: reason && reason !== 'ai' && reason !== 'loading' ? reason : null,
      onclick: start,
    }, starting ? t('ko3.intake.starting') : t('ko3.intake.startReading'));
    return el('div', { class: 'intake-head' },
      el('div', { class: 'intake-title' },
        el('h1', { id: 'intake-title' }, t('ko3.intake.newVessel')),
        preview ? el('span', { class: 'intake-count' }, intakePageCount(total, kept)) : null),
      el('div', { class: 'intake-actions' },
        el('button', { class: 'btn btn-large', type: 'button', onclick: cancel }, t('ko3.intake.cancel')),
        startButton));
  }

  function pageImage(page) {
    return page.thumbnail_png_base64
      ? el('img', { class: 'intake-thumb-img', src: `data:image/png;base64,${page.thumbnail_png_base64}`, alt: t('ko3.pageAlt', { number: page.page_index + 1, file: page.file_name }), draggable: 'false' })
      : el('div', { class: 'intake-thumb-missing' }, t('ko3.intake.noPreview'));
  }

  function regionFrame(page) {
    const { width_px: width, height_px: height } = page;
    return svg('svg', { class: 'intake-regions', viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
      ...page.regions.map((region) => {
        const [left, top, right, bottom] = region.region_px;
        return svg('rect', {
          class: `intake-region${region.confidence < UNSURE_BELOW ? ' unsure' : ''}`,
          'data-label': region.label,
          x: left, y: top, width: right - left, height: bottom - top,
          'vector-effect': 'non-scaling-stroke',
        });
      }));
  }

  /** The large page in the stage: regions drawn on it and a label chip on each. */
  function pagePreview(page) {
    const { width_px: width, height_px: height } = page;
    const chips = page.regions.map((region, index) => {
      const [left, top] = region.region_px;
      // Each chip starts in its region's top-left corner; placeChips() then moves chips so
      // that they do not cover each other.
      return el('button', {
        class: 'intake-region-chip',
        type: 'button',
        dataset: { label: region.label, left: left / width, top: top / height },
        style: { left: `${(left / width) * 100}%`, top: `${(top / height) * 100}%` },
        title: t('ko3.regionTip', { label: viewLabel(region.label), confidence: percent(region.confidence), evidence: region.evidence || '' }).trim(),
        tabindex: '-1',
        onclick: () => host.querySelector(`#${CSS.escape(`label-${page.page_id}-${index}`)}`)?.focus(),
      }, viewLabel(region.label));
    });
    return el('div', { class: 'intake-stage-frame' },
      el('div', { class: 'intake-thumb intake-page', style: { '--page-ratio': String(width / height) } },
        pageImage(page), regionFrame(page), ...chips));
  }

  /**
   * Move region chips down until no two chips overlap. Chips keep their region's left edge;
   * a chip that would leave the page is held inside it.
   */
  function placeChips() {
    const page = host.querySelector('.intake-page');
    if (!page) return;
    const box = page.getBoundingClientRect();
    if (!box.width) return;
    const placed = [];
    const chips = [...page.querySelectorAll('.intake-region-chip')]
      .sort((a, b) => Number(a.dataset.top) - Number(b.dataset.top) || Number(a.dataset.left) - Number(b.dataset.left));
    for (const chip of chips) {
      const width = chip.offsetWidth;
      const height = chip.offsetHeight;
      const x = Math.max(CHIP_GAP_PX, Math.min(Number(chip.dataset.left) * box.width + CHIP_GAP_PX, box.width - width - CHIP_GAP_PX));
      let y = Number(chip.dataset.top) * box.height + CHIP_GAP_PX;
      for (const other of placed) {
        const overlaps = x < other.x + other.width + CHIP_GAP_PX && other.x < x + width + CHIP_GAP_PX
          && y < other.y + other.height + CHIP_GAP_PX && other.y < y + height + CHIP_GAP_PX;
        if (overlaps) y = other.y + other.height + CHIP_GAP_PX;
      }
      y = Math.min(y, box.height - height - CHIP_GAP_PX);
      chip.style.setProperty('left', `${x}px`);
      chip.style.setProperty('top', `${y}px`);
      placed.push({ x, y, width, height });
    }
  }

  function regionRow(page, region, index) {
    const id = `label-${page.page_id}-${index}`;
    const picker = el('select', {
      class: 'intake-label-picker',
      id,
      'aria-label': t('ko3.regionView', { number: index + 1, page: page.page_id }),
      disabled: page.skip || starting,
      onchange: (event) => {
        region.label = event.target.value;
        render();
      },
    }, ...VIEW_LABELS.map(([value, text]) => {
      const option = el('option', { value }, t(text));
      option.selected = value === region.label;
      return option;
    }));
    return el('li', { class: 'intake-region-row' },
      el('span', { class: 'intake-swatch', dataset: { label: region.label }, 'aria-hidden': 'true' }),
      picker,
      el('span', {
        class: `intake-confidence${region.confidence < UNSURE_BELOW ? ' unsure' : ''}`,
        title: region.evidence ? t('ko3.confidence', { evidence: region.evidence }) : t('ko3.intake.howSureTheCodeIsOfThisLabel'),
      }, percent(region.confidence)));
  }

  function pageWhere(page) {
    return page.kind === 'pdf' ? t('ko3.pageWhere', { number: page.page_index + 1 }) : (page.page_index ? t('ko3.frameWhere', { number: page.page_index + 1 }) : null);
  }

  function skipButton(page) {
    return el('button', {
      class: 'btn intake-skip',
      type: 'button',
      id: `skip-${page.page_id}`,
      'aria-pressed': String(page.skip),
      disabled: starting,
      title: page.skip ? t('ko3.intake.useThisPageAgain') : t('ko3.intake.leaveThisPageOutForExampleACoverPage'),
      'aria-keyshortcuts': 'S',
      onclick: () => toggleSkip(page),
    }, page.skip ? t('ko3.intake.keep') : t('ko3.intake.skip'));
  }

  /** One small page in the tray. Click to show it large. */
  function trayItem(page) {
    const where = pageWhere(page);
    const selected = page.page_id === selectedPageId;
    const views = page.regions
      .filter((r) => r.label !== 'other' && r.label !== 'title_block')
      .map((r) => viewLabel(r.label));
    return el('button', {
      class: `intake-tray-item${page.skip ? ' skipped' : ''}`,
      type: 'button',
      id: `tray-${page.page_id}`,
      'aria-pressed': String(selected),
      // One tab stop for the tray; ↑ ↓ move inside it.
      tabindex: selected ? '0' : '-1',
      title: `${page.file_name}${where ? `, ${where}` : ''}`,
      onclick: () => selectPage(page.page_id),
    },
      el('div', { class: 'intake-thumb', style: { 'aspect-ratio': `${page.width_px} / ${page.height_px}` } }, pageImage(page), regionFrame(page)),
      el('span', { class: 'intake-tray-line' },
        el('span', { class: 'intake-page-id' }, page.page_id),
        el('span', { class: 'intake-tray-views' }, page.skip ? t('ko3.intake.skipped') : (views.join(', ') || t('ko3.intake.noView'))),
        page.warnings.length && !page.skip
          ? el('span', { class: 'intake-tray-warn', title: page.warnings.map((w) => w.message).join(' ') }, icon('warn'))
          : null),
      // Sheet type and scale as small chips (drawing_set.js); a skipped page shows none.
      page.sheet && !page.skip
        ? el('span', { class: 'intake-tray-chips' }, typeChip(page, { focusable: false }), scaleChip(page, preview.set?.scale_agreement, { focusable: false }))
        : null);
  }

  /**
   * Which kept pages show each hull view. A missing view is a warning, not a stop:
   * the AI still reads the set and says what it had to guess.
   */
  function setSummary() {
    const kept = keptPages();
    const rows = HULL_VIEWS.map((label) => {
      const where = kept.filter((page) => page.regions.some((r) => r.label === label)).map((page) => page.page_id);
      return el('li', { class: `intake-sum-row${where.length ? '' : ' missing'}` },
        el('span', { class: 'intake-sum-view' }, viewLabel(label)),
        where.length
          ? el('button', {
            class: 'intake-sum-pages', type: 'button', title: t('ko3.showPage', { page: where[0] }),
            onclick: () => selectPage(where[0], { focusTray: true }),
          }, where.join(' '))
          : el('span', { class: 'intake-sum-pages', title: t('ko3.intake.missingViewHelp') }, t('ko3.intake.none')));
    });
    const skipped = preview.pages.length - kept.length;
    return el('section', { class: 'intake-sum', 'aria-label': t('ko3.intake.viewsInTheKeptPages') },
      el('h2', { class: 'intake-sum-title' }, t('ko3.intake.viewsFound'),
        skipped ? el('span', { class: 'intake-sum-skipped' }, t('ko3.skippedCount', { count: skipped })) : null),
      el('ul', {}, ...rows));
  }

  /** The sheet's type (a picker the person can change) and its scale, with the reason in the tooltips. */
  function sheetRow(page) {
    const note = preview.set?.scale_agreement?.items?.find((item) => item.page_id === page.page_id);
    return el('div', { class: 'intake-sheet-row' },
      el('span', { class: 'field-label' }, t('ko3.intake.sheet')),
      typePicker(page, {
        disabled: starting,
        onchange: (type) => { Object.assign(page, withType(page, type)); render(); },
      }),
      typeChip(page, { focusable: true }),
      scaleChip(page, preview.set?.scale_agreement, { focusable: true }),
      note ? el('span', { class: 'intake-sheet-note', role: 'note' }, icon('warn'), note.message) : null);
  }

  /** The selected page, large, with its region labels and warnings. */
  function stage(page) {
    const where = pageWhere(page);
    const dpi = page.dpi ? `${Math.round(page.dpi)} dpi` : null;
    const pages = preview.pages;
    const position = pages.length > 1 ? t('ko3.pagePosition', { number: pages.indexOf(page) + 1, total: pages.length }) : null;
    return el('section', { class: `intake-stage${page.skip ? ' skipped' : ''}`, 'aria-label': `${page.file_name}${where ? `, ${where}` : ''}` },
      el('header', { class: 'intake-card-head' },
        el('span', { class: 'intake-page-id' }, page.page_id),
        position ? el('span', { class: 'intake-position', title: t('ko3.intake.previousOrNextPage') }, position) : null,
        el('span', { class: 'intake-file', title: page.file }, page.file_name),
        where ? el('span', { class: 'intake-where' }, where) : null,
        dpi ? el('span', { class: 'intake-dpi' }, dpi) : null,
        skipButton(page)),
      page.sheet && !page.skip ? sheetRow(page) : null,
      // The labels sit above the page, next to the thing they name; spare height goes below.
      el('div', { class: 'intake-stage-foot' },
        page.skip
          ? el('p', { class: 'intake-skipped-note' }, t('ko3.intake.skippedTheRunDoesNotReadThisPage'))
          : el('ul', { class: 'intake-region-list', 'aria-label': t('ko3.intake.viewRegions') }, ...page.regions.map((r, i) => regionRow(page, r, i))),
        page.warnings.length ? el('div', { class: 'chip-row intake-card-foot' }, ...page.warnings.map(warningChip)) : null),
      pagePreview(page));
  }

  function numberField(key, label, unit) {
    const value = readPositive(form[key]);
    return el('label', { class: 'intake-number' },
      el('span', { class: 'intake-number-label' }, label),
      el('span', { class: 'intake-number-input' },
        el('input', {
          type: 'text', inputmode: 'decimal', id: `intake-${key}`, name: key, value: form[key], autocomplete: 'off', spellcheck: 'false',
          placeholder: '—', 'aria-invalid': Number.isNaN(value) ? 'true' : null, disabled: starting,
          oninput: (event) => onNumberInput(key, event.target),
        }),
        el('span', { class: 'intake-unit' }, unit)));
  }

  function sidePanel() {
    return el('section', { class: 'intake-side', 'aria-label': t('ko3.intake.vessel') },
      el('label', { class: 'field' },
        el('span', { class: 'field-label' }, t('ko3.intake.vesselName')),
        el('input', {
          type: 'text', class: 'intake-name', id: 'intake-vessel-name', name: 'vessel_name', value: form.vessel_name, autocomplete: 'off',
          maxlength: '200', disabled: starting, placeholder: t('ko3.intake.forExampleSurveyLaunch24M'),
          oninput: (event) => { form.vessel_name = event.target.value; },
        })),
      el('fieldset', { class: 'field intake-known' },
        el('legend', { class: 'field-label' }, t('ko3.intake.knownParticulars'), el('span', {
          class: 'intake-optional', tabindex: '0',
          'data-tip-title': t('ko3.intake.optional'), 'data-tip-detail': t('ko3.intake.theAIReadsTheseFromTheSheetsTypeThemOnlyWhenYouKnowThem'),
        }, t('ko3.intake.optional'))),
        el('div', { class: 'intake-number-grid' },
          ...PARTICULAR_FIELDS.map(([key, label]) => numberField(key, t(label), 'm')),
          el('label', { class: 'intake-number' },
            el('span', { class: 'intake-number-label' }, t('ko3.intake.scale')),
            el('span', { class: 'intake-number-input intake-scale' },
              el('span', { class: 'intake-unit' }, '1 :'),
              el('input', {
                type: 'text', inputmode: 'decimal', id: 'intake-scale', name: 'scale', value: form.scale, autocomplete: 'off', spellcheck: 'false',
                placeholder: '—', 'aria-invalid': Number.isNaN(readPositive(form.scale)) ? 'true' : null, disabled: starting,
                'aria-label': t('ko3.intake.scale1To'), oninput: (event) => onNumberInput('scale', event.target),
              })))),
        ),
      el('div', { class: 'intake-mode' },
        el('span', { class: 'field-label' }, t('ko3.intake.mode')),
        aiStatus?.active
          ? el('span', { class: 'badge', dataset: { tone: 'ai' }, title: t('ko3.intake.aiDraftHelp') }, t('ko3.intake.aiDraft'))
          : el('span', { class: 'badge', dataset: { tone: 'warn' }, title: t('ko3.intake.aDrawingSetWithoutASpecNeedsTheAI') }, aiStatus?.enabled ? t('ko3.intake.noKey') : t('ko3.intake.aiOff'))),
      // The drawings the set needs, from the sheet types (they follow the person's edits).
      preview.set?.rules
        ? checklistPanel(computeChecklist(preview.pages, preview.set.rules), preview.set.outputs, preview.set.scale_agreement,
          { onShow: (pageId) => selectPage(pageId, { focusTray: true }) })
        : null);
  }

  function loadingBody() {
    const count = loading.count;
    return el('div', { class: 'intake-loading', role: 'status' },
      el('span', { class: 'spinner', 'aria-hidden': 'true' }),
      t('ko3.readingFiles', { count, unit: t(count === 1 ? 'ko3.fileSingular' : 'ko3.filePlural') }));
  }

  /** A typed number: mark it when it is not valid and update Start, without a full render. */
  function onNumberInput(key, input) {
    form[key] = input.value;
    if (Number.isNaN(readPositive(input.value))) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
    renderStatusOnly();
  }

  /** Only the parts that change while a number is typed: the Start button and its reason. */
  function renderStatusOnly() {
    const button = host.querySelector('#intake-start');
    const line = host.querySelector('.intake-blocked');
    if (!button || !line) return;
    const reason = blockedReason();
    const shown = reason && reason !== 'ai' ? reason : '';
    button.disabled = Boolean(reason) || starting;
    button.title = shown;
    line.textContent = shown;
    line.hidden = !shown;
  }

  function render() {
    if (!preview && !loading) {
      host.replaceChildren();
      return;
    }
    const focusedId = document.activeElement && host.contains(document.activeElement) ? document.activeElement.id : null;
    // A render rebuilds the tray: keep where it was scrolled to, then bring the shown page into view.
    const trayScroll = host.querySelector('.intake-tray')?.scrollTop || 0;
    const setWarnings = (preview?.warnings || []).filter((w) => w.code !== AI_OFF_WARNING);
    const reason = preview ? blockedReason() : '';
    fill(host,
      head(),
      preview && !aiStatus?.active ? aiLine() : null,
      setWarnings.length ? el('div', { class: 'chip-row intake-set-warnings' }, ...setWarnings.map(warningChip)) : null,
      error ? el('p', { class: 'form-error intake-error', role: 'alert' }, error) : null,
      preview ? el('p', { class: 'intake-blocked', role: 'status', hidden: !reason || reason === 'ai' }, reason === 'ai' ? '' : reason) : null,
      loading ? el('div', { class: 'intake-body' }, loadingBody()) : body());
    const tray = host.querySelector('.intake-tray');
    if (tray) {
      tray.scrollTop = trayScroll;
      host.querySelector('.intake-tray-item[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest' });
    }
    if (focusedId) host.querySelector(`#${CSS.escape(focusedId)}`)?.focus({ preventScroll: true });
    requestAnimationFrame(placeChips);
  }

  function body() {
    const pages = preview.pages;
    const selected = pages.find((p) => p.page_id === selectedPageId) || pages[0];
    // One page needs no tray: the stage takes its room.
    const tray = pages.length > 1
      ? el('div', { class: 'intake-tray-wrap' },
        setSummary(),
        el('nav', { class: 'intake-tray', 'aria-label': t('ko3.intake.pages') }, ...pages.map(trayItem)))
      : null;
    return el('div', { class: `intake-body${tray ? ' has-tray' : ''}` }, tray, stage(selected), sidePanel());
  }

  /** Show the view again (for example after Settings): the AI status may have changed. */
  async function show() {
    aiStatus = await refreshAiStatus();
    render();
  }

  return {
    prepare,
    show,
    render,
    hasSet: () => Boolean(preview || loading),
  };
}
