// Parts tab (whole vessel, APP_SPEC "Whole-vessel parts"): the component tree of a run, a
// profile and a plan sketch of the parts' boxes, and each part's values with the source of
// every value (read from the drawing, read by the AI, or guessed). A part is a draft like the
// hull; the person can accept it as a draft part. Nothing here is "approved".

import { el, svg, icon, fill } from './dom.js';
import { glyphChip } from './glyphs.js';
import { t } from './i18n.js';
import { valueDisplay } from './value_display.js';
import { tipAttributes } from './tooltip.js';
import { capacityPanel, capacityRowOf, tankDetailBlock, tankToken } from './tanks.js';

/** Tree groups (ship-cad ops) in the order a naval architect reads a general arrangement. */
const GROUPS = [
  ['hull', 'term.hull'],
  ['deck', 'term.deck'],
  ['deckhouse', 'term.deckhouse'],
  ['bulwark', 'term.bulwark'],
  ['appendage', 'term.appendage'],
  ['tank', 'term.tank'],
  ['other', 'ko2.parts.other'],
];
const KNOWN_OPS = new Set(GROUPS.map(([op]) => op));
const SOURCE_WORD = { traced: 'Read', ai_inferred: 'AI read', guessed: 'Guessed' };
const SOURCE_TONE = { traced: '', ai_inferred: 'ai', guessed: 'draft' };
/** Icons of the value sources and the part states (index.html sprite). */
const SOURCE_ICON = { traced: 'read', ai_inferred: 'src-ai_inferred', guessed: 'st-guessed' };
/** Longest mark note (the same limit as Mark and revise). */
const MAX_NOTE = 500;
/** Ops the worker can re-run from a mark (vessel_reconstruction.part_revise REVISABLE_OPS). */
const REVISABLE_OPS = new Set(['deck', 'deckhouse', 'bulwark', 'appendage']);
/** Phrases that start a mark note: one tap, then the person adds the numbers. */
const MARK_CHIPS = ['high', 'low', 'long', 'short', 'place', 'notPart', 'missing'];
/** Sketch scale (SVG units per metre) and margin; the SVG scales to its column width. */
const SKETCH = { unitsPerMetre: 30, pad: 10 };
/**
 * A selected part whose larger side is under this part of the sketch width also gets a ring
 * around it, so a thruster or a skeg fin on a 40 m hull is easy to find. The ring radius is a
 * part of the sketch width too, so it looks the same on any hull length.
 */
const SMALL_PART_SHARE = 0.08;
const RING_RADIUS_SHARE = 0.05;

/**
 * The outline polygons of a part for a sketch: `vertical` 2 is the profile ([x, z] points), 1 the
 * plan ([x, y] points). Null when the run gave none (the sketch then draws the part's box).
 */
export function outlinePolygons(part, vertical) {
  const polygons = vertical === 2 ? part?.display?.profile_m : part?.display?.plan_m;
  const usable = (polygons || []).filter((points) => Array.isArray(points) && points.length >= 3);
  return usable.length ? usable : null;
}

/** One state word per part: the review wins, then what the build could do. */
/** "house_height" or "height" -> "Height": the argument word of a ship-cad name. */
function argumentWord(name) {
  const word = name.split('_').pop() || name;
  const label = word.charAt(0).toUpperCase() + word.slice(1);
  return ['height', 'length', 'breadth', 'width', 'depth', 'thickness', 'volume'].includes(word) ? t(`term.${word}`) : label;
}

/**
 * The ship-cad reason in plain words (the raw text stays in the tooltip). Each '; '-separated
 * item becomes one short sentence.
 */
/**
 * A CAD entity handle in worker text, for example E496460BAFD67193 or A$C18113CC1: ten or more
 * capitals, digits and $ with at least one digit. People cannot use them; the full text stays in
 * the tooltip for engineers.
 */
const HANDLE = String.raw`(?=[A-Z$]*\d)[A-Z0-9$]{10,}`;
const HANDLE_LIST = new RegExp(String.raw`\s*\((?:${HANDLE})(?:,\s*${HANDLE})*\)`, 'g');
const HANDLE_WORD = new RegExp(String.raw`\s*\b${HANDLE}\b`, 'g');

/** Text without CAD entity handles: "(E4964…, E4964…)" lists and single handles go. */
export function withoutHandles(text) {
  if (!text) return text;
  return text.replace(HANDLE_LIST, '').replace(HANDLE_WORD, '').replace(/\s{2,}/g, ' ').trim();
}

export function plainReason(reason) {
  if (!reason) return '';
  reason = withoutHandles(reason);
  if (reason === 'Component identity needs human review') {
    return t('ko2.parts.identity');
  }
  return reason.split('; ').map((item) => {
    let match = /^(\w+): missing or invalid measurement$/.exec(item);
    if (match) return t('ko2.parts.notRead', { item: argumentWord(match[1]) });
    match = /^(\w+): (guessed|ai_inferred): (.+)$/.exec(item);
    if (match) return t('ko2.parts.reasonSource', { item: argumentWord(match[1]), source: t(match[2] === 'guessed' ? 'ko2.parts.reasonGuess' : 'ko2.parts.reasonAi'), basis: match[3] });
    if (item === 'primary measurement does not match named source') return t('ko2.parts.otherView');
    // A plain item is its own sentence: capital first letter, full stop.
    const sentence = item.charAt(0).toUpperCase() + item.slice(1);
    return sentence.endsWith('.') ? sentence : `${sentence}.`;
  }).join(' ');
}

export function partState(part) {
  if (part.revision_pending) return { word: t('ko2.parts.newRevision'), tone: 'ai', icon: 'reset', title: t('ko2.parts.revisionHelp') };
  if (part.review === 'accepted') return { word: t('ko2.parts.accepted'), tone: 'brand', icon: 'st-chosen', title: t('ko2.parts.acceptedHelp') };
  if (part.review === 'marked') return { word: t('ko2.parts.marked'), tone: 'brand', icon: 'drawing', title: t('ko2.parts.markedTitle', { note: part.review_note || '' }) };
  if (!part.built) return { word: t('ko2.parts.notBuilt'), tone: 'warn', icon: 'not-built', title: plainReason(part.reason) };
  if (part.status === 'draft_guess') return { word: t('ko2.parts.guessed'), tone: 'draft', icon: 'st-guessed', title: t('ko2.parts.guessedHelp') };
  return { word: t('ko2.parts.toCheck'), tone: '', icon: 'flag', title: t('ko2.parts.readHelp') };
}

/**
 * A spreadsheet runs a text cell that starts with one of these as a formula. Part labels can
 * come from model output and notes are typed, so such cells get a leading single quote (the
 * rule of src/vessel_reconstruction/exports/csv_safety.py). Numbers are formatted apart and
 * never pass through here, so negative numbers stay numbers.
 */
const FORMULA_PREFIXES = ['=', '+', '-', '@', '\t', '\r'];

/** One text cell of the part list: one line, and never a formula. */
export function safeTextCell(value) {
  const raw = (value ?? '').toString();
  const text = raw.replace(/[\t\r\n]+/g, ' ');
  const formula = [raw, text].some((cell) => FORMULA_PREFIXES.some((prefix) => cell.startsWith(prefix)));
  return formula ? `'${text}` : text;
}

/** One number cell: three decimals, or empty. */
function numberCell(value) {
  return Number.isFinite(value) ? value.toFixed(3) : '';
}

/** The part list as tab-separated text, for a spreadsheet or a sign-off note. */
export function partTableText(parts, signOff = null) {
  const header = [t('ko2.parts.header.part'), t('ko2.parts.header.op'), t('ko2.parts.header.built'), t('ko2.parts.header.status'), t('ko2.parts.header.xFrom'), t('ko2.parts.header.xTo'), t('ko2.parts.header.breadth'), t('ko2.parts.header.zFrom'), t('ko2.parts.header.zTo'), t('ko2.parts.header.volume'), t('ko2.parts.header.read'), t('ko2.parts.header.guessed'), t('ko2.parts.header.review'), t('ko2.parts.header.note')];
  const rows = parts.map((p) => {
    const box = p.bbox_m;
    const text = [p.label, p.op, p.built ? t('ko2.parts.yes') : t('ko2.parts.no'), p.status].map(safeTextCell);
    const numbers = [box?.min[0], box?.max[0], box ? box.max[1] - box.min[1] : null, box?.min[2], box?.max[2], p.volume_m3].map(numberCell);
    const counts = [p.arguments.filter((a) => a.source !== 'guessed').length, p.arguments.filter((a) => a.source === 'guessed').length].map(String);
    return [...text, ...numbers, ...counts, safeTextCell(p.review), safeTextCell(p.review_note || '')];
  });
  return [header, ...rows].map((row) => row.join('\t')).join('\n')
    + (signOff ? `\n${safeTextCell(t('ko2.parts.clipboardSignOff', { name: signOff.name, date: new Date(signOff.time_ms).toISOString().slice(0, 10), statement: signOff.statement }))}` : '')
    + t('ko2.parts.clipboardStamp');
}

function chip(text, tone, title) {
  return el('span', { class: 'badge badge-small', dataset: { tone }, title }, el('span', { class: 'badge-text' }, text));
}

/** A part state as an icon chip: the word is its name and tooltip title. */
function stateChip(state, options = {}) {
  return glyphChip(state.icon, state.word, { tone: state.tone || null, detail: state.title || null, ...options });
}

/** A value source (Read, AI read, Guessed) as an icon chip; the basis is the tooltip detail. */
function sourceChip(source, basis = '') {
  return glyphChip(SOURCE_ICON[source] || 'info', (SOURCE_WORD[source] ? t(`parts.source.${source}`) : source), {
    tone: SOURCE_TONE[source] || null, detail: basis ? withoutHandles(basis) : null, focusable: false,
  });
}

/** Adapt only a single number with a unit; ranges, outlines and labels stay as text. */
export function partQuantity(argument) {
  const match = /^([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s+(m|mm|cm|m²|m³|m2|m3|kg|t|°|deg|%)$/.exec(String(argument.value ?? '').trim());
  if (!match || !Number.isFinite(Number(match[1]))) return null;
  const source = SOURCE_WORD[argument.source]
    ? t(`parts.source.${argument.source}`) : argument.source || t('status.unknown');
  return {
    value: Number(match[1]), unit: match[2], digits: (match[1].split('.')[1] || '').length,
    status: argument.source === 'traced' ? 'read' : argument.source === 'guessed' ? 'guessed' : 'draft',
    source: `${source}${argument.basis ? ` · ${argument.basis}` : ''}`,
  };
}

function argumentValue(argument) {
  const quantity = partQuantity(argument);
  return quantity ? valueDisplay(quantity) : argument.value || t('status.unknown');
}

/** Whether "Re-run with this note" is offered: a marked part with a note, of an op the worker revises. */
export function canRerun(part) {
  return part.review === 'marked' && Boolean(part.review_note) && !part.revision_pending && REVISABLE_OPS.has(part.op);
}

/** "1:05" from milliseconds. */
export function elapsedText(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * `review(id, decision)` saves a review (review_component) and resolves when done;
 * `showIn3d(part)` switches to the Run tab with the part outlined. `revisePart(id)`,
 * `keepRevision(id)` and `undoRevision(id)` re-run a marked part and settle its new revision;
 * each resolves with the part (ComponentView) and rejects after the app showed the error.
 */
export function createParts({ host, review, showIn3d, signOff, revisePart = null, keepRevision = null, undoRevision = null, loadSounding = null, onSelect = () => {}, showWholeVessel = () => {} }) {
  let wholeModel = null; // TaskView.whole_vessel_model, or null
  let capacityPlan = null; // TaskView.capacity_plan, or null
  let selectedTankId = null; // the tank whose sounding table shows
  let soundings = new Map(); // tank id -> { loading } | { table } | { error }
  let parts = [];
  let selectedId = null;
  let busy = false;
  let rerun = null; // { id, startedMs } while a part is re-run from its mark
  let rerunTimer = null;
  let marking = false; // the mark form is open on the selected part
  let signedOff = null; // SignOffView of this run, or null
  // Typed text kept across re-renders (a reload of the run must not wipe what the person typed).
  let markDraft = '';
  let nameDraft = null;

  function sketch(vertical, title) {
    const built = parts.filter((p) => p.bbox_m);
    if (!built.length) return null;
    const lo = [0, 1, 2].map((k) => Math.min(...built.map((p) => p.bbox_m.min[k])));
    const hi = [0, 1, 2].map((k) => Math.max(...built.map((p) => p.bbox_m.max[k])));
    // True scale, as on a general arrangement; both sketches share the scale, so in their two
    // equal columns the profile and the plan show the same length the same size.
    const scale = SKETCH.unitsPerMetre;
    const width = (hi[0] - lo[0]) * scale + 2 * SKETCH.pad;
    const height = (hi[vertical] - lo[vertical]) * scale + 2 * SKETCH.pad;
    const px = (x) => SKETCH.pad + (x - lo[0]) * scale;
    const py = (v) => height - SKETCH.pad - (v - lo[vertical]) * scale;
    // The selected part is drawn last, on top.
    const order = [...built].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId));
    return el('figure', { class: 'parts-sketch' },
      el('figcaption', {}, title),
      svg('svg', { viewBox: `0 0 ${width.toFixed(0)} ${height.toFixed(0)}`, role: 'img', 'aria-label': t('ko2.parts.sketch', { title }) },
        ...order.map((p) => {
          const outline = sketchOutline(p, vertical, px, py);
          if (outline) return outline;
          const { min, max } = p.bbox_m;
          const rect = svg('rect', {
            class: `parts-box${p.id === selectedId ? ' selected' : ''}`,
            'data-status': p.status,
            x: px(min[0]).toFixed(1), y: py(max[vertical]).toFixed(1),
            width: Math.max(1, (max[0] - min[0]) * scale).toFixed(1),
            height: Math.max(1, (max[vertical] - min[vertical]) * scale).toFixed(1),
          });
          rect.append(svg('title', {}, p.label));
          rect.addEventListener('click', () => select(p.id));
          return rect;
        }),
        focusRing(order.find((p) => p.id === selectedId), { px, py, vertical, scale, sketchWidth: width })));
  }

  /**
   * A part's real outline in the sketch (a tank: its profile or plan polygons from the run,
   * filled with its capacity-plan colour), or null to draw its box.
   */
  function sketchOutline(part, vertical, px, py) {
    const polygons = outlinePolygons(part, vertical);
    if (!polygons) return null;
    const selected = part.id === selectedId;
    const group = svg('g', {
      class: `parts-outline${selected ? ' selected' : ''}`,
      'data-status': part.status,
      style: { '--tank-fill': `var(${tankToken(part.display.content_class)})` },
    }, ...polygons.map((points) => svg('polygon', {
      points: points.map(([x, v]) => `${px(x).toFixed(1)},${py(v).toFixed(1)}`).join(' '),
    })));
    group.append(svg('title', {}, part.label));
    group.addEventListener('click', () => select(part.id));
    return group;
  }

  /** A ring around the selected part when it is too small to see at once in the sketch. */
  function focusRing(part, { px, py, vertical, scale, sketchWidth }) {
    if (!part) return null;
    const { min, max } = part.bbox_m;
    const width = (max[0] - min[0]) * scale;
    const height = (max[vertical] - min[vertical]) * scale;
    if (Math.max(width, height) >= sketchWidth * SMALL_PART_SHARE) return null;
    return svg('circle', {
      class: 'parts-focus',
      cx: ((px(min[0]) + px(max[0])) / 2).toFixed(1),
      cy: ((py(min[vertical]) + py(max[vertical])) / 2).toFixed(1),
      r: (sketchWidth * RING_RADIUS_SHARE).toFixed(1),
      'aria-hidden': 'true',
    });
  }

  function treeRow(part) {
    const state = partState(part);
    return el('li', {},
      el('button', { class: 'parts-row', type: 'button', 'aria-pressed': String(part.id === selectedId), onclick: () => select(part.id) },
        el('span', { class: 'parts-name' }, part.label),
        stateChip(state, { focusable: false })));
  }

  async function decide(part, decision, note = null) {
    if (busy) return;
    busy = true;
    render();
    try {
      try {
        await review(part.id, decision, note);
      } catch {
        return; // the app showed the error; the part keeps its review
      }
      part.review = decision;
      // Reopening a part ends a sign-off of the parts (the backend withdraws it too).
      if (decision === 'open') signedOff = null;
      part.review_note = decision === 'marked' ? note.trim() : null;
      marking = false;
      markDraft = '';
      // After an accept, the next part with guesses opens: a review is a short run of keys.
      if (decision === 'accepted') {
        const next = parts.find((p) => p.review !== 'accepted' && p.built && p.status === 'draft_guess');
        if (next) selectedId = next.id;
      }
    } finally {
      busy = false;
      render();
    }
  }

  function actions(part) {
    const reviewed = part.review === 'accepted' || part.review === 'marked';
    return el('div', { class: 'decision-bar' },
      part.built && !reviewed ? el('button', {
        class: 'btn btn-primary write-action',
        type: 'button',
        disabled: busy,
        title: t('ko2.parts.acceptHelp'),
        onclick: () => decide(part, 'accepted'),
      }, t('ko2.parts.accept'), el('kbd', { class: 'key-hint' }, 'A')) : null,
      !reviewed ? el('button', {
        class: 'btn write-action',
        type: 'button',
        disabled: busy,
        title: t('ko2.parts.markHelp'),
        onclick: () => { marking = true; render(); host.querySelector('.parts-mark textarea')?.focus(); },
      }, t('ko2.parts.mark'), el('kbd', { class: 'key-hint' }, 'M')) : null,
      reviewed ? el('button', {
        class: 'btn write-action',
        type: 'button',
        disabled: busy,
        title: t('ko2.parts.reopenHelp'),
        onclick: () => decide(part, 'open'),
      }, t('ko2.parts.reopen')) : null,
      part.bbox_m ? el('button', { class: 'btn', type: 'button', onclick: () => (wholeModel?.loadable ? showWholeVessel(part) : showIn3d(part)) }, icon('cube'), t('ko2.parts.show3d')) : null);
  }

  /** What the person wants changed: chips that start a sentence, then their words. */
  function markForm(part) {
    const text = el('textarea', { rows: '3', maxlength: String(MAX_NOTE), placeholder: t('ko2.parts.changePrompt'), 'aria-label': t('ko2.parts.changeLabel', { part: part.label }) });
    const count = el('span', { class: 'parts-mark-count' }, `0 / ${MAX_NOTE}`);
    const save = el('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, t('ko2.parts.saveMark'));
    const update = () => {
      markDraft = text.value;
      count.textContent = `${text.value.length} / ${MAX_NOTE}`;
      save.disabled = busy || !text.value.trim();
    };
    text.addEventListener('input', update);
    text.value = markDraft; // before the first update, which saves the field into the draft
    update();
    text.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { marking = false; render(); }
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !save.disabled) form.requestSubmit();
    });
    const form = el('form', {
      class: 'parts-mark',
      onsubmit: (event) => { event.preventDefault(); decide(part, 'marked', text.value); },
    },
    el('div', { class: 'chip-row' }, ...MARK_CHIPS.map((key) => {
      const phrase = t(`ko2.parts.mark.${key}`);
      return el('button', {
        class: 'btn btn-small',
        type: 'button',
        onclick: () => { text.value = text.value ? `${text.value.trim()} ${phrase}` : phrase; update(); text.focus(); },
      }, phrase);
    })),
    text,
    el('div', { class: 'parts-mark-actions' },
      count,
      el('span', { class: 'export-actions-spacer' }),
      el('button', { class: 'btn', type: 'button', onclick: () => { marking = false; render(); } }, t('ko2.parts.cancel')),
      save));
    return form;
  }

  /** Put a part the backend returned in place of the old one. */
  function replacePart(updated) {
    const index = parts.findIndex((p) => p.id === updated.id);
    if (index >= 0) parts[index] = updated;
  }

  /** Re-run the part from its saved mark note; the work takes minutes. */
  async function rerunPart(part) {
    if (busy || !revisePart) return;
    busy = true;
    rerun = { id: part.id, startedMs: Date.now() };
    // Only the clock text changes each second; the rest of the page stays as it is.
    rerunTimer = setInterval(() => {
      const clock = host.querySelector('.parts-rerun-time');
      if (clock && rerun) clock.textContent = elapsedText(Date.now() - rerun.startedMs);
    }, 1000);
    render();
    try {
      replacePart(await revisePart(part.id));
      signedOff = null; // the part changed: the backend withdrew any sign-off
    } catch {
      // The app showed the error; the old part stays.
    } finally {
      clearInterval(rerunTimer);
      rerun = null;
      busy = false;
      render();
    }
  }

  /** Keep or undo the new revision of a part. */
  async function settleRevision(part, keep) {
    const call = keep ? keepRevision : undoRevision;
    if (busy || !call) return;
    busy = true;
    render();
    try {
      replacePart(await call(part.id));
      if (keep) signedOff = null;
    } catch {
      // The app showed the error; the part keeps its revision.
    } finally {
      busy = false;
      render();
    }
  }

  /** Re-run offer, progress, or the new revision with what changed and Keep / Undo. */
  function revisionBlock(part) {
    if (rerun?.id === part.id) {
      return el('section', { class: 'parts-rerun', role: 'status', 'aria-label': t('ko2.parts.rerunning') },
        el('span', { class: 'spinner', 'aria-hidden': 'true' }),
        el('p', {},
          el('strong', {}, t('ko2.parts.rerunningNote')),
          t('ko2.parts.rerunningHelp'),
          el('span', { class: 'parts-rerun-time', 'aria-hidden': 'true' }, elapsedText(Date.now() - rerun.startedMs))));
    }
    if (part.revision_pending) {
      return el('section', { class: 'parts-revision', 'aria-labelledby': 'parts-revision-title' },
        el('h3', { id: 'parts-revision-title' }, t('ko2.parts.revisionChanges', { revision: part.revision })),
        part.revision_note ? el('p', { class: 'parts-revision-note' }, t('ko2.parts.fromNote'), el('q', {}, part.revision_note)) : null,
        part.changes?.length
          ? el('table', { class: 'parts-args parts-changes' },
            el('caption', { class: 'visually-hidden' }, t('ko2.parts.beforeAfter', { part: part.label })),
            el('thead', {}, el('tr', {},
              el('th', { scope: 'col' }, t('ko2.parts.item')), el('th', { scope: 'col' }, t('ko2.parts.before')), el('th', { scope: 'col' }, t('ko2.parts.after')))),
            el('tbody', {}, ...part.changes.map((c) => el('tr', {},
              el('th', { scope: 'row' }, c.name),
              el('td', { class: 'parts-value' }, argumentValue({ value: c.before, source: c.before_source }), c.before_source ? [' ', sourceChip(c.before_source)] : null),
              el('td', { class: 'parts-value' }, argumentValue({ value: c.after, source: c.after_source }), c.after_source ? [' ', sourceChip(c.after_source)] : null)))))
          : el('p', {}, t('ko2.parts.noChange')),
        el('p', { class: 'parts-revision-hint' }, t('ko2.parts.revisionHint')),
        el('div', { class: 'decision-bar write-action' },
          el('button', { class: 'btn btn-primary', type: 'button', disabled: busy, onclick: () => settleRevision(part, true) }, t('ko2.parts.keep')),
          el('button', { class: 'btn', type: 'button', disabled: busy, onclick: () => settleRevision(part, false) }, t('ko2.parts.undo'))));
    }
    if (canRerun(part) && revisePart) {
      return el('div', { class: 'parts-rerun-offer write-action' },
        el('button', { class: 'btn btn-primary', type: 'button', disabled: busy, onclick: () => rerunPart(part) }, t('ko2.parts.rerun')),
        el('span', { class: 'parts-revision-hint' }, t('ko2.parts.rerunHint')));
    }
    if (part.revision > 0) {
      return el('p', { class: 'parts-revision-hint' }, t('ko2.parts.revision', { revision: part.revision }),
        part.revision_note ? [t('ko2.parts.noteSuffix'), el('q', {}, part.revision_note)] : null, '.');
    }
    return null;
  }

  function detail(part) {
    if (!part) return el('p', { class: 'panel-empty' }, t('ko2.parts.pick'));
    const state = partState(part);
    const box = part.bbox_m;
    return el('section', { class: 'parts-detail', 'aria-labelledby': 'parts-detail-title' },
      el('header', { class: 'parts-detail-head' },
        el('h2', { id: 'parts-detail-title' }, part.label),
        stateChip(state, { small: false }),
        part.view ? chip(part.view, '', t('ko2.parts.viewHelp')) : null),
      actions(part),
      marking ? markForm(part) : null,
      part.review === 'marked' && part.review_note
        ? el('p', { class: 'parts-marked' }, el('strong', {}, t('ko2.parts.youMarked')), part.review_note, t('ko2.parts.markSaved'))
        : null,
      revisionBlock(part),
      el('p', { class: 'parts-reason', title: part.reason }, plainReason(part.reason)),
      part.op === 'tank' && capacityPlan ? tankDetailBlock(capacityRowOf(capacityPlan, part.id)) : null,
      box ? el('p', { class: 'parts-box-line' },
        t('ko2.parts.box', { xFrom: box.min[0].toFixed(2), xTo: box.max[0].toFixed(2), breadth: (box.max[1] - box.min[1]).toFixed(2), zFrom: box.min[2].toFixed(2), zTo: box.max[2].toFixed(2) })
        + (part.volume_m3 !== null && part.volume_m3 !== undefined ? ` · ${part.volume_m3.toFixed(1)} m³` : '')) : null,
      part.arguments.length
        ? el('table', { class: 'parts-args' },
          el('caption', { class: 'visually-hidden' }, t('ko2.parts.values', { part: part.label })),
          el('thead', {}, el('tr', {},
            el('th', { scope: 'col' }, t('ko2.parts.item')), el('th', { scope: 'col' }, t('ko2.parts.value')), el('th', { scope: 'col' }, t('ko2.parts.source')), el('th', { scope: 'col' }, t('ko2.parts.basis')))),
          el('tbody', {}, ...part.arguments.map((a) => el('tr', { dataset: { source: a.source } },
            el('th', { scope: 'row' }, a.name),
            el('td', { class: 'parts-value' }, argumentValue(a)),
            el('td', {}, sourceChip(a.source)),
            el('td', { class: 'parts-basis', title: a.basis || '' }, withoutHandles(a.basis || ''))))))
        : null);
  }



  async function copyTable(button) {
    try {
      await navigator.clipboard.writeText(partTableText(parts, signedOff));
      button.textContent = t('ko2.parts.copied');
    } catch {
      button.textContent = t('ko2.parts.copyFailed');
    }
    setTimeout(() => { button.textContent = t('ko2.parts.copy'); }, 1600);
  }

  /**
   * Sign-off (founder wording): "Signed off by <name>, <date>: usable as a starting model".
   * Open once every part is reviewed. It records a person's judgement; the run and its files
   * stay drafts and engineering_approved stays false.
   */
  function signOffBlock() {
    if (!parts.length) return null;
    const open = parts.filter((p) => p.review !== 'accepted' && p.review !== 'marked').length;
    const draftLine = el('span', { class: 'parts-signoff-note' }, t('ko2.parts.stayDraft'));
    if (signedOff) {
      const date = new Date(signedOff.time_ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
      return el('section', { class: 'parts-signoff is-signed', 'aria-label': t('ko2.parts.signOffLabel') },
        icon('check'),
        el('p', {}, el('strong', {}, t('ko2.parts.signedBy', { name: signedOff.name, date })), signedOff.statement, '. ', draftLine),
        el('button', { class: 'btn write-action', type: 'button', disabled: busy, onclick: () => submitSignOff('') }, t('ko2.parts.withdraw')));
    }
    // Until every part is reviewed, the review progress in the head says so (its tooltip).
    if (open) return null;
    const name = el('input', { type: 'text', maxlength: '80', placeholder: t('ko2.parts.name'), 'aria-label': t('ko2.parts.nameHelp'), value: nameDraft ?? lastName(), oninput: (event) => { nameDraft = event.target.value; } });
    const form = el('form', {
      class: 'parts-signoff write-action',
      'aria-label': t('ko2.parts.signOffLabel'),
      onsubmit: (event) => { event.preventDefault(); submitSignOff(name.value); },
    },
    el('p', {}, el('strong', {}, t('ko2.parts.reviewed')), t('ko2.parts.signOffHelp'), draftLine),
    name,
    el('button', { class: 'btn btn-primary', type: 'submit', disabled: busy }, t('ko2.parts.signOff')));
    return form;
  }

  function lastName() {
    try {
      return localStorage.getItem('marinaframe.signoff-name') || '';
    } catch {
      return '';
    }
  }

  async function submitSignOff(name) {
    if (busy) return;
    if (name.trim()) {
      try {
        localStorage.setItem('marinaframe.signoff-name', name.trim());
      } catch {
        // Not remembered; the field is empty next time.
      }
    }
    busy = true;
    render();
    try {
      signedOff = await signOff(name);
    } catch {
      // The app showed the error.
    } finally {
      busy = false;
      render();
    }
  }

  /** The next part that still needs a person, after the selected one. */
  function nextToReview() {
    const index = parts.findIndex((p) => p.id === selectedId);
    const ordered = [...parts.slice(index + 1), ...parts.slice(0, index + 1)];
    return ordered.find((p) => p.review !== 'accepted' && p.review !== 'marked') || null;
  }

  function progress() {
    const reviewed = parts.filter((p) => p.review === 'accepted' || p.review === 'marked').length;
    const next = nextToReview();
    const copy = el('button', {
      class: 'btn btn-icon',
      type: 'button',
      ...tipAttributes(t('ko2.parts.copy'), t('ko2.parts.copyHelp')).attrs,
      onclick: (event) => copyTable(event.currentTarget),
    }, icon('table'));
    const open = parts.length - reviewed;
    const progressTip = tipAttributes(t('ko2.parts.progress', { reviewed, total: parts.length }),
      open ? t('ko2.parts.progressHelp', { open }) : null, { label: false });
    return el('div', { class: 'parts-progress' },
      el('span', { class: 'parts-progress-text', tabindex: '0', ...progressTip.attrs }, el('strong', {}, String(reviewed)), t('ko2.parts.progressSuffix', { total: parts.length }), progressTip.describer),
      el('span', { class: 'parts-progress-bar', role: 'img', 'aria-label': t('ko2.parts.progress', { reviewed, total: parts.length }) },
        el('span', { style: { width: `${parts.length ? (reviewed / parts.length) * 100 : 0}%` } })),
      el('button', { class: 'btn', type: 'button', disabled: !next, title: t('ko2.parts.nextHelp'), onclick: () => next && select(next.id) }, t('ko2.parts.next'), el('kbd', { class: 'key-hint' }, 'N')),
      wholeModel ? el('button', {
        class: 'btn',
        type: 'button',
        disabled: !wholeModel.loadable,
        title: wholeModel.loadable ? t('ko2.parts.wholeHelp') : t('ko2.parts.tooLarge'),
        onclick: () => showWholeVessel(parts.find((p) => p.id === selectedId) || null),
      }, icon('cube'), t('ko2.parts.whole')) : null,
      copy);
  }

  function render() {
    const built = parts.filter((p) => p.built).length;
    const accepted = parts.filter((p) => p.review === 'accepted').length;
    const marked = parts.filter((p) => p.review === 'marked').length;
    const selected = parts.find((p) => p.id === selectedId) || null;
    fill(host, el('div', { class: 'page-body parts-page' },
      el('header', { class: 'page-head parts-head' },
        el('h1', { id: 'parts-title' }, t('ko2.parts.parts')),
        el('span', { class: 'page-head-meta chip-row' },
          glyphChip('cube', t('ko2.parts.builtLower'), { count: `${built}/${parts.length}`, countedName: t('ko2.parts.builtCount', { built, total: parts.length }) }),
          accepted ? glyphChip('st-chosen', t('ko2.parts.acceptedLower'), { count: accepted, tone: 'brand' }) : null,
          marked ? glyphChip('drawing', t('ko2.parts.markedLower'), { count: marked, tone: 'brand' }) : null),
        progress()),
      signOffBlock(),
      el('div', { class: 'parts-layout' },
        el('nav', { class: 'parts-tree', 'aria-label': t('ko2.parts.parts') },
          ...GROUPS.map(([op, title]) => {
            const items = parts.filter((p) => (KNOWN_OPS.has(p.op) ? p.op : 'other') === op);
            return items.length ? el('section', { class: 'parts-group' }, el('h2', {}, t(title)), el('ul', {}, ...items.map(treeRow))) : null;
          })),
        el('div', { class: 'parts-main' },
          el('div', { class: 'parts-sketches' }, sketch(2, t('term.profile')), sketch(1, t('term.plan'))),
          detail(selected))),
      capacityPanel({ plan: capacityPlan, selectedId: selectedTankId, sounding: soundings.get(selectedTankId), onPick: pickTank })));
  }

  /** Show a tank in the capacity plan (and as the selected part, when it is one). */
  function pickTank(id) {
    if (parts.some((p) => p.id === id)) {
      select(id);
      return;
    }
    selectedTankId = id;
    loadTankSounding(id);
    render();
  }

  /** Read the sounding table of a tank once; the panel shows it when it arrives. */
  async function loadTankSounding(id) {
    const row = capacityRowOf(capacityPlan, id);
    if (!row?.has_sounding || !loadSounding || soundings.has(id)) return;
    soundings.set(id, { loading: true });
    try {
      soundings.set(id, { table: await loadSounding(id) });
    } catch (failure) {
      soundings.set(id, { error: failure?.message || t('ko2.parts.soundingError') });
    }
    if (selectedTankId === id) render();
  }

  function select(id) {
    marking = false;
    selectedId = id;
    if (capacityRowOf(capacityPlan, id)) {
      selectedTankId = id;
      loadTankSounding(id);
    }
    onSelect(parts.find((p) => p.id === id) || null);
    render();
  }

  return {
    /** Show the parts of a TaskView (`view.components`). */
    show(view) {
      parts = view?.components || [];
      signedOff = view?.sign_off || null;
      wholeModel = view?.whole_vessel_model || null;
      const plan = view?.capacity_plan || null;
      // A new capacity plan file can hold new sounding tables: read them again.
      if (plan?.file !== capacityPlan?.file) soundings = new Map();
      capacityPlan = plan;
      if (!capacityRowOf(capacityPlan, selectedTankId)) selectedTankId = capacityPlan?.rows?.[0]?.id || null;
      if (!parts.some((p) => p.id === selectedId)) {
        selectedId = (parts.find((p) => p.built && p.status === 'draft_guess') || parts[0])?.id || null;
      }
      loadTankSounding(selectedTankId);
      // While the person types (a mark or a name), a reload of the run waits: re-drawing now
      // would move the caret. The data is kept and shows with the next render.
      const typing = host.contains(document.activeElement) && document.activeElement.matches('input, textarea');
      if (!typing) render();
    },
    /** Key A on the Parts tab: accept the selected part. Returns true when it acted. */
    /** Key M on the Parts tab: start a mark on the selected part. Returns true when it acted. */
    markSelected() {
      const part = parts.find((p) => p.id === selectedId);
      if (!part || part.review === 'accepted' || part.review === 'marked' || busy) return false;
      marking = true;
      render();
      host.querySelector('.parts-mark textarea')?.focus();
      return true;
    },
    /** Key N on the Parts tab: the next part to review. Returns true when it acted. */
    /** Show one part (the command palette). */
    selectPart(id) {
      if (parts.some((p) => p.id === id)) select(id);
    },
    nextSelected() {
      const next = nextToReview();
      if (!next) return false;
      select(next.id);
      return true;
    },
    acceptSelected() {
      const part = parts.find((p) => p.id === selectedId);
      if (!part?.built || part.review === 'accepted' || busy) return false;
      decide(part, 'accepted');
      return true;
    },
  };
}
