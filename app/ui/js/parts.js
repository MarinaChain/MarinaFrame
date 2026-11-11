// Parts tab (whole vessel, APP_SPEC "Whole-vessel parts"): the component tree of a run, a
// profile and a plan sketch of the parts' boxes, and each part's values with the source of
// every value (read from the drawing, read by the AI, or guessed). A part is a draft like the
// hull; the person can accept it as a draft part. Nothing here is "approved".

import { el, svg, icon, fill } from './dom.js';
import { glyphChip } from './glyphs.js';
import { tipAttributes } from './tooltip.js';
import { capacityPanel, capacityRowOf, tankDetailBlock, tankToken } from './tanks.js';

/** Tree groups (ship-cad ops) in the order a naval architect reads a general arrangement. */
const GROUPS = [
  ['hull', 'Hull'],
  ['deck', 'Decks'],
  ['deckhouse', 'Deckhouses'],
  ['bulwark', 'Bulwarks'],
  ['appendage', 'Appendages'],
  ['tank', 'Tanks'],
  ['other', 'Other'],
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
const MARK_CHIPS = ['Too high', 'Too low', 'Too long', 'Too short', 'Wrong place', 'Not a part', 'Missing part'];
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
  return word.charAt(0).toUpperCase() + word.slice(1);
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
    return 'Every value was read from the drawing. Check that this is the right part.';
  }
  return reason.split('; ').map((item) => {
    let match = /^(\w+): missing or invalid measurement$/.exec(item);
    if (match) return `${argumentWord(match[1])}: not read from the drawing.`;
    match = /^(\w+): (guessed|ai_inferred): (.+)$/.exec(item);
    if (match) return `${argumentWord(match[1])}: ${match[2] === 'guessed' ? 'guessed' : 'read by the AI'} (${match[3]}).`;
    if (item === 'primary measurement does not match named source') return 'The outline was read from another view than the part names.';
    // A plain item is its own sentence: capital first letter, full stop.
    const sentence = item.charAt(0).toUpperCase() + item.slice(1);
    return sentence.endsWith('.') ? sentence : `${sentence}.`;
  }).join(' ');
}

export function partState(part) {
  if (part.revision_pending) return { word: 'New revision', tone: 'ai', icon: 'reset', title: 'Re-run from your mark. Keep it or undo it.' };
  if (part.review === 'accepted') return { word: 'Accepted', tone: 'brand', icon: 'st-chosen', title: 'You accepted this part as a draft part.' };
  if (part.review === 'marked') return { word: 'Marked', tone: 'brand', icon: 'drawing', title: `You marked it: ${part.review_note || ''}` };
  if (!part.built) return { word: 'Not built', tone: 'warn', icon: 'not-built', title: plainReason(part.reason) };
  if (part.status === 'draft_guess') return { word: 'Guessed', tone: 'draft', icon: 'st-guessed', title: 'One or more values were guessed. Check them.' };
  return { word: 'To check', tone: '', icon: 'flag', title: 'Every value was read from the drawing. Check what the part is.' };
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
  const header = ['Part', 'Op', 'Built', 'Status', 'x from (m)', 'x to (m)', 'Breadth (m)', 'z from (m)', 'z to (m)', 'Volume (m3)', 'Values read', 'Values guessed', 'Review', 'Note'];
  const rows = parts.map((p) => {
    const box = p.bbox_m;
    const text = [p.label, p.op, p.built ? 'yes' : 'no', p.status].map(safeTextCell);
    const numbers = [box?.min[0], box?.max[0], box ? box.max[1] - box.min[1] : null, box?.min[2], box?.max[2], p.volume_m3].map(numberCell);
    const counts = [p.arguments.filter((a) => a.source !== 'guessed').length, p.arguments.filter((a) => a.source === 'guessed').length].map(String);
    return [...text, ...numbers, ...counts, safeTextCell(p.review), safeTextCell(p.review_note || '')];
  });
  return [header, ...rows].map((row) => row.join('\t')).join('\n')
    + (signOff ? `\n${safeTextCell(`Signed off by ${signOff.name}, ${new Date(signOff.time_ms).toISOString().slice(0, 10)}: ${signOff.statement}.`)}` : '')
    + '\nDraft, not for construction. engineering_approved: false\n';
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
  return glyphChip(SOURCE_ICON[source] || 'info', SOURCE_WORD[source] || source, {
    tone: SOURCE_TONE[source] || null, detail: basis ? withoutHandles(basis) : null, focusable: false,
  });
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
      svg('svg', { viewBox: `0 0 ${width.toFixed(0)} ${height.toFixed(0)}`, role: 'img', 'aria-label': `${title} sketch of the parts` },
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
        class: 'btn btn-primary',
        type: 'button',
        disabled: busy,
        title: 'Accept this part as a draft part (A)',
        onclick: () => decide(part, 'accepted'),
      }, 'Accept', el('kbd', { class: 'key-hint' }, 'A')) : null,
      !reviewed ? el('button', {
        class: 'btn',
        type: 'button',
        disabled: busy,
        title: 'Say what is wrong with this part (M)',
        onclick: () => { marking = true; render(); host.querySelector('.parts-mark textarea')?.focus(); },
      }, 'Mark', el('kbd', { class: 'key-hint' }, 'M')) : null,
      reviewed ? el('button', {
        class: 'btn',
        type: 'button',
        disabled: busy,
        title: 'Open this part again for review',
        onclick: () => decide(part, 'open'),
      }, 'Reopen') : null,
      part.bbox_m ? el('button', { class: 'btn', type: 'button', onclick: () => (wholeModel?.loadable ? showWholeVessel(part) : showIn3d(part)) }, icon('cube'), 'Show in 3D') : null);
  }

  /** What the person wants changed: chips that start a sentence, then their words. */
  function markForm(part) {
    const text = el('textarea', { rows: '3', maxlength: String(MAX_NOTE), placeholder: 'What should change in this part?', 'aria-label': `What should change in ${part.label}` });
    const count = el('span', { class: 'parts-mark-count' }, `0 / ${MAX_NOTE}`);
    const save = el('button', { class: 'btn btn-primary', type: 'submit', disabled: true }, 'Save mark');
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
    el('div', { class: 'chip-row' }, ...MARK_CHIPS.map((phrase) => el('button', {
      class: 'btn btn-small',
      type: 'button',
      onclick: () => { text.value = text.value ? `${text.value.trim()} ${phrase}` : phrase; update(); text.focus(); },
    }, phrase))),
    text,
    el('div', { class: 'parts-mark-actions' },
      count,
      el('span', { class: 'export-actions-spacer' }),
      el('button', { class: 'btn', type: 'button', onclick: () => { marking = false; render(); } }, 'Cancel'),
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
      return el('section', { class: 'parts-rerun', role: 'status', 'aria-label': 'Re-run in progress' },
        el('span', { class: 'spinner', 'aria-hidden': 'true' }),
        el('p', {},
          el('strong', {}, 'Re-running this part from your note. '),
          'The AI reads the drawing around the part and your note; then only this part is rebuilt. This takes 1 to 5 minutes. ',
          el('span', { class: 'parts-rerun-time', 'aria-hidden': 'true' }, elapsedText(Date.now() - rerun.startedMs))));
    }
    if (part.revision_pending) {
      return el('section', { class: 'parts-revision', 'aria-labelledby': 'parts-revision-title' },
        el('h3', { id: 'parts-revision-title' }, `Revision ${part.revision}: what changed`),
        part.revision_note ? el('p', { class: 'parts-revision-note' }, 'From your note: ', el('q', {}, part.revision_note)) : null,
        part.changes?.length
          ? el('table', { class: 'parts-args parts-changes' },
            el('caption', { class: 'visually-hidden' }, `Values of ${part.label} before and after the re-run`),
            el('thead', {}, el('tr', {},
              el('th', { scope: 'col' }, 'Item'), el('th', { scope: 'col' }, 'Before'), el('th', { scope: 'col' }, 'After'))),
            el('tbody', {}, ...part.changes.map((c) => el('tr', {},
              el('th', { scope: 'row' }, c.name),
              el('td', { class: 'parts-value' }, c.before || '—', c.before_source ? [' ', sourceChip(c.before_source)] : null),
              el('td', { class: 'parts-value' }, c.after || '—', c.after_source ? [' ', sourceChip(c.after_source)] : null)))))
          : el('p', {}, 'No value changed.'),
        el('p', { class: 'parts-revision-hint' }, 'AI values are drafts. Keep the new part, or undo to put back the old part and its STEP file.'),
        el('div', { class: 'decision-bar' },
          el('button', { class: 'btn btn-primary', type: 'button', disabled: busy, onclick: () => settleRevision(part, true) }, 'Keep'),
          el('button', { class: 'btn', type: 'button', disabled: busy, onclick: () => settleRevision(part, false) }, 'Undo')));
    }
    if (canRerun(part) && revisePart) {
      return el('div', { class: 'parts-rerun-offer' },
        el('button', { class: 'btn btn-primary', type: 'button', disabled: busy, onclick: () => rerunPart(part) }, 'Re-run with this note'),
        el('span', { class: 'parts-revision-hint' }, 'The AI rebuilds only this part from your note (1 to 5 minutes).'));
    }
    if (part.revision > 0) {
      return el('p', { class: 'parts-revision-hint' }, `Revision ${part.revision}`,
        part.revision_note ? [', from the note ', el('q', {}, part.revision_note)] : null, '.');
    }
    return null;
  }

  function detail(part) {
    if (!part) return el('p', { class: 'panel-empty' }, 'Pick a part.');
    const state = partState(part);
    const box = part.bbox_m;
    return el('section', { class: 'parts-detail', 'aria-labelledby': 'parts-detail-title' },
      el('header', { class: 'parts-detail-head' },
        el('h2', { id: 'parts-detail-title' }, part.label),
        stateChip(state, { small: false }),
        part.view ? chip(part.view, '', 'The drawing view this part was read from') : null),
      actions(part),
      marking ? markForm(part) : null,
      part.review === 'marked' && part.review_note
        ? el('p', { class: 'parts-marked' }, el('strong', {}, 'You marked: '), part.review_note, ' Saved with the review of this run.')
        : null,
      revisionBlock(part),
      el('p', { class: 'parts-reason', title: part.reason }, plainReason(part.reason)),
      part.op === 'tank' && capacityPlan ? tankDetailBlock(capacityRowOf(capacityPlan, part.id)) : null,
      box ? el('p', { class: 'parts-box-line' },
        `x ${box.min[0].toFixed(2)} to ${box.max[0].toFixed(2)} m · breadth ${(box.max[1] - box.min[1]).toFixed(2)} m · `
        + `z ${box.min[2].toFixed(2)} to ${box.max[2].toFixed(2)} m`
        + (part.volume_m3 !== null && part.volume_m3 !== undefined ? ` · ${part.volume_m3.toFixed(1)} m³` : '')) : null,
      part.arguments.length
        ? el('table', { class: 'parts-args' },
          el('caption', { class: 'visually-hidden' }, `Values of ${part.label}`),
          el('thead', {}, el('tr', {},
            el('th', { scope: 'col' }, 'Item'), el('th', { scope: 'col' }, 'Value'), el('th', { scope: 'col' }, 'Source'), el('th', { scope: 'col' }, 'Basis'))),
          el('tbody', {}, ...part.arguments.map((a) => el('tr', { dataset: { source: a.source } },
            el('th', { scope: 'row' }, a.name),
            el('td', { class: 'parts-value' }, a.value || '—'),
            el('td', {}, sourceChip(a.source)),
            el('td', { class: 'parts-basis', title: a.basis || '' }, withoutHandles(a.basis || ''))))))
        : null);
  }



  async function copyTable(button) {
    try {
      await navigator.clipboard.writeText(partTableText(parts, signedOff));
      button.textContent = 'Copied';
    } catch {
      button.textContent = 'Copy failed';
    }
    setTimeout(() => { button.textContent = 'Copy part list'; }, 1600);
  }

  /**
   * Sign-off (founder wording): "Signed off by <name>, <date>: usable as a starting model".
   * Open once every part is reviewed. It records a person's judgement; the run and its files
   * stay drafts and engineering_approved stays false.
   */
  function signOffBlock() {
    if (!parts.length) return null;
    const open = parts.filter((p) => p.review !== 'accepted' && p.review !== 'marked').length;
    const draftLine = el('span', { class: 'parts-signoff-note' }, 'The run and its files stay drafts.');
    if (signedOff) {
      const date = new Date(signedOff.time_ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
      return el('section', { class: 'parts-signoff is-signed', 'aria-label': 'Sign-off' },
        icon('check'),
        el('p', {}, el('strong', {}, `Signed off by ${signedOff.name}, ${date}: `), signedOff.statement, '. ', draftLine),
        el('button', { class: 'btn', type: 'button', disabled: busy, onclick: () => submitSignOff('') }, 'Withdraw'));
    }
    // Until every part is reviewed, the review progress in the head says so (its tooltip).
    if (open) return null;
    const name = el('input', { type: 'text', maxlength: '80', placeholder: 'Your name', 'aria-label': 'Your name for the sign-off', value: nameDraft ?? lastName(), oninput: (event) => { nameDraft = event.target.value; } });
    const form = el('form', {
      class: 'parts-signoff',
      'aria-label': 'Sign-off',
      onsubmit: (event) => { event.preventDefault(); submitSignOff(name.value); },
    },
    el('p', {}, el('strong', {}, 'Every part is reviewed. '), `Sign off as usable as a starting model. `, draftLine),
    name,
    el('button', { class: 'btn btn-primary', type: 'submit', disabled: busy }, 'Sign off'));
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
      ...tipAttributes('Copy part list', 'A table to paste into a spreadsheet.').attrs,
      onclick: (event) => copyTable(event.currentTarget),
    }, icon('table'));
    const open = parts.length - reviewed;
    const progressTip = tipAttributes(`${reviewed} of ${parts.length} parts reviewed`,
      open ? `Sign-off opens when every part is reviewed: ${open} still open.` : null, { label: false });
    return el('div', { class: 'parts-progress' },
      el('span', { class: 'parts-progress-text', tabindex: '0', ...progressTip.attrs }, el('strong', {}, String(reviewed)), `/${parts.length} reviewed`, progressTip.describer),
      el('span', { class: 'parts-progress-bar', role: 'img', 'aria-label': `${reviewed} of ${parts.length} parts reviewed` },
        el('span', { style: { width: `${parts.length ? (reviewed / parts.length) * 100 : 0}%` } })),
      el('button', { class: 'btn', type: 'button', disabled: !next, title: 'Go to the next part to review (N)', onclick: () => next && select(next.id) }, 'Next', el('kbd', { class: 'key-hint' }, 'N')),
      wholeModel ? el('button', {
        class: 'btn',
        type: 'button',
        disabled: !wholeModel.loadable,
        title: wholeModel.loadable ? 'Show every part in the 3D view' : 'The whole-vessel model is too large for the app; open the part STEP files in your CAD program',
        onclick: () => showWholeVessel(parts.find((p) => p.id === selectedId) || null),
      }, icon('cube'), 'Whole vessel in 3D') : null,
      copy);
  }

  function render() {
    const built = parts.filter((p) => p.built).length;
    const accepted = parts.filter((p) => p.review === 'accepted').length;
    const marked = parts.filter((p) => p.review === 'marked').length;
    const selected = parts.find((p) => p.id === selectedId) || null;
    fill(host, el('div', { class: 'page-body parts-page' },
      el('header', { class: 'page-head parts-head' },
        el('h1', { id: 'parts-title' }, 'Parts'),
        el('span', { class: 'page-head-meta chip-row' },
          glyphChip('cube', 'built', { count: `${built}/${parts.length}`, countedName: `${built} of ${parts.length} parts built` }),
          accepted ? glyphChip('st-chosen', 'accepted', { count: accepted, tone: 'brand' }) : null,
          marked ? glyphChip('drawing', 'marked', { count: marked, tone: 'brand' }) : null),
        progress()),
      signOffBlock(),
      el('div', { class: 'parts-layout' },
        el('nav', { class: 'parts-tree', 'aria-label': 'Parts' },
          ...GROUPS.map(([op, title]) => {
            const items = parts.filter((p) => (KNOWN_OPS.has(p.op) ? p.op : 'other') === op);
            return items.length ? el('section', { class: 'parts-group' }, el('h2', {}, title), el('ul', {}, ...items.map(treeRow))) : null;
          })),
        el('div', { class: 'parts-main' },
          el('div', { class: 'parts-sketches' }, sketch(2, 'Profile'), sketch(1, 'Plan')),
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
      soundings.set(id, { error: failure?.message || 'The sounding table could not be read.' });
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
