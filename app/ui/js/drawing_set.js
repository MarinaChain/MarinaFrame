// Drawing-set intake (docs/DRAWING_SET_INTAKE.md): the type and scale of each sheet and the
// checklist of drawings a set needs. The worker proposes (page.sheet, preview.set); the person can
// change a type or skip a page, and the checklist is computed again here from the same rules
// (preview.set.rules), so the list never lags behind an edit.
//
// Pure functions first (tested in ui-tests/drawing_set.test.mjs), DOM builders after.

import { el, icon } from './dom.js';
import { glyphChip } from './glyphs.js';

/** Sheet types in picker order: id, short word, long name, icon (index.html sprite `i-type-<id>`). */
export const SHEET_TYPES = [
  ['lines_plan', 'Lines', 'Lines plan or body plan'],
  ['general_arrangement', 'GA', 'General arrangement'],
  ['profile', 'Profile', 'Profile'],
  ['midship_section', 'Midship', 'Midship section'],
  ['shell_expansion', 'Shell', 'Shell expansion'],
  ['construction_profile', 'Structure', 'Construction profile and decks'],
  ['tank_plan', 'Tanks', 'Tank or capacity plan'],
  ['hydrostatics', 'Hydro', 'Hydrostatic tables'],
  ['other', 'Other', 'Other'],
];
export const TYPE_SHORT = Object.fromEntries(SHEET_TYPES.map(([id, short]) => [id, short]));
export const TYPE_NAME = Object.fromEntries(SHEET_TYPES.map(([id, , name]) => [id, name]));

/** Below this confidence a proposed type is marked "check it". */
export const UNSURE_BELOW = 0.7;

/** The words people see for where a type came from. Headings and notes read by OCR share one phrase. */
const SOURCE_TEXT = {
  'text:pdf_text': 'the text in the PDF',
  'title:pdf_text': 'the lettering on the sheet',
  'text:pdf_text+ocr': 'the text in the PDF and the lettering on the sheet',
  'title:pdf_text+ocr': 'the lettering on the sheet',
  'text:ocr': 'the lettering on the sheet',
  'title:ocr': 'the lettering on the sheet',
  file_name: 'the file name',
  layout: 'the layout of the views',
};

/** "From the file name and the lettering on the sheet", "Asked of the AI", "Set by you". */
export function sourceSentence(source) {
  if (!source) return 'No source';
  if (source === 'person') return 'Set by you';
  if (source.startsWith('model:')) return 'Asked of the AI';
  if (source === 'code:no_rule') return 'No title or keyword found';
  // A source joins its parts with "+", and one part ("text:pdf_text+ocr") holds a "+" itself.
  const parts = source.split(/\+(?=text:|title:|file_name|layout)/);
  const words = [...new Set(parts.map((part) => SOURCE_TEXT[part] || part))];
  return `From ${words.join(' and ')}`;
}

const percent = (value) => `${Math.round(value * 100)}%`;

/** The type of a page, or null when the worker gave none. */
export function sheetType(page) {
  return page?.sheet?.type || null;
}

/** True when the proposed type is weak enough for the person to check. */
export function typeUnsure(page) {
  const sheet = page?.sheet;
  return Boolean(sheet) && sheet.source !== 'person' && sheet.confidence < UNSURE_BELOW;
}

/** The person sets a type: it keeps the views and scale the worker read, and the source says "person". */
export function withType(page, type) {
  const sheet = { ...(page.sheet || { scale: { status: 'missing', main_ratio: null }, views: [], evidence: [] }) };
  return { ...page, sheet: { ...sheet, type, type_label: TYPE_NAME[type], confidence: 1, source: 'person' } };
}

// ---------------------------------------------------------------- scale

/**
 * What the scale chip says for one page. `agreement` is preview.set.scale_agreement.
 * state: read | mixed | missing | check (the sheet's length differs from the others).
 */
export function scaleState(page, agreement = null) {
  const sheet = page?.sheet;
  if (!sheet) return null;
  const scale = sheet.scale || { status: 'missing' };
  const differs = (agreement?.items || []).find((item) => item.page_id === page.page_id && item.code === 'scale_disagrees');
  if (differs) {
    return { state: 'check', text: scale.main_text || 'Scale', detail: differs.message };
  }
  if (scale.status === 'missing') {
    return { state: 'missing', text: 'No scale', detail: 'No printed scale was found on this sheet.' };
  }
  const detail = scale.status === 'mixed'
    ? `Several scales are printed (${(scale.scales || []).map((s) => `1:${s.ratio}`).join(', ')}). The most frequent, ${scale.main_text}, is used.`
    : `Printed scale ${scale.main_text}, ${scale.source === 'text:pdf_text' ? 'read from the PDF text' : 'read from the lettering'}.`;
  return { state: scale.status, text: scale.main_text || `1:${scale.main_ratio}`, detail };
}

/** The one-line state of the set's scales: agree, check or too few sheets to compare. */
export function agreementLine(agreement) {
  if (!agreement) return null;
  if (agreement.status === 'agree') {
    return { tone: null, text: 'Scales agree', detail: `${agreement.estimates} sheets give a vessel length of about ${agreement.reference_m} m (spread ${percent(agreement.spread)}).` };
  }
  if (agreement.status === 'check') {
    const count = agreement.items.filter((i) => i.code === 'scale_disagrees').length;
    return { tone: 'warn', text: `${count} ${count === 1 ? 'sheet differs' : 'sheets differ'} in scale`, detail: 'The sheets do not give the same vessel length. Check the marked sheets.' };
  }
  return { tone: null, text: 'Scales not compared', detail: 'Fewer than two sheets show the whole hull with a printed scale.' };
}

// ---------------------------------------------------------------- checklist

/**
 * The checklist for the kept pages from the worker's rules (same logic as drawing_set.checklist
 * in Python). Each item: { ...rule, status: 'met'|'missing', met_by: [page_id], met_note }.
 */
export function computeChecklist(pages, rules) {
  const kept = pages.filter((page) => !page.skip && page.sheet);
  return (rules || []).map((rule) => {
    const direct = kept.filter((p) => rule.any_of.includes(p.sheet.type)).map((p) => p.page_id);
    const via = kept
      .filter((p) => (rule.via_views || []).some((route) => p.sheet.type === route.type && (p.sheet.views || []).includes(route.view)))
      .map((p) => p.page_id)
      .filter((id) => !direct.includes(id));
    const metBy = [...direct, ...via];
    return {
      id: rule.id, output: rule.output, need: rule.need, level: rule.level, why: rule.why,
      status: metBy.length ? 'met' : 'missing', met_by: metBy,
      met_note: via.length && !direct.length ? 'from the sheer plan on the lines sheet' : '',
    };
  });
}

/** Required items that are missing. */
export function missingRequired(items) {
  return items.filter((item) => item.level === 'required' && item.status === 'missing');
}

/** The heading line of the checklist: what is missing, in a few words. */
export function checklistHeadline(items) {
  const missing = missingRequired(items);
  if (!missing.length) return 'All required drawings found';
  return `${missing.length} required ${missing.length === 1 ? 'drawing' : 'drawings'} missing`;
}

/** Items grouped by output, in the worker's output order. */
export function groupByOutput(items, outputs) {
  return (outputs || []).map((output) => {
    const rows = items.filter((item) => item.output === output.id);
    return { id: output.id, label: output.label, rows, missingRequired: missingRequired(rows).length };
  }).filter((group) => group.rows.length);
}

// ---------------------------------------------------------------- DOM

/** A type chip: the type's icon, its short word as the name, how sure and from where as the detail. */
export function typeChip(page, { focusable = false } = {}) {
  const sheet = page?.sheet;
  if (!sheet) return null;
  const unsure = typeUnsure(page);
  const detail = `${sheet.source === 'person' ? 'Set by you.' : `${percent(sheet.confidence)} sure. ${sourceSentence(sheet.source)}.`}${unsure ? ' Check it.' : ''}`;
  const chip = glyphChip(`type-${sheet.type}`, TYPE_NAME[sheet.type] || sheet.type, {
    tone: unsure ? 'warn' : null, detail, focusable, hoverTip: true,
  });
  chip.classList.add('type-chip');
  if (unsure) chip.classList.add('unsure');
  return chip;
}

/** A scale chip: a ruler icon with the printed scale, or the reason there is none. */
export function scaleChip(page, agreement, { focusable = false } = {}) {
  const state = scaleState(page, agreement);
  if (!state) return null;
  const tone = state.state === 'missing' || state.state === 'check' ? 'warn' : null;
  const chip = glyphChip(state.state === 'check' ? 'warn' : 'scale', state.text, { tone, detail: state.detail, focusable, hoverTip: true });
  chip.classList.add('scale-chip');
  chip.dataset.scale = state.state;
  const text = el('span', { class: 'scale-chip-text', 'aria-hidden': 'true' }, state.text);
  chip.append(text);
  return chip;
}

/** The type picker of the stage. `onchange(type)` receives the new type id. */
export function typePicker(page, { disabled = false, onchange }) {
  const select = el('select', {
    class: 'intake-type-picker', id: `type-${page.page_id}`, 'aria-label': `Type of page ${page.page_id}`,
    disabled,
    onchange: (event) => onchange(event.target.value),
  }, ...SHEET_TYPES.map(([id, , name]) => {
    const option = el('option', { value: id }, name);
    option.selected = id === sheetType(page);
    return option;
  }));
  return select;
}

/**
 * The checklist panel: one block per output, one row per drawing: status icon, name, level,
 * and the pages that meet it (buttons that show the page). `onShow(pageId)` selects a page.
 */
export function checklistPanel(items, outputs, agreement, { onShow }) {
  const groups = groupByOutput(items, outputs);
  const line = agreementLine(agreement);
  return el('section', { class: 'intake-sum intake-checklist', 'aria-label': 'Drawings the set needs' },
    el('h2', { class: 'intake-sum-title' }, 'Drawings',
      el('span', { class: `intake-sum-skipped${missingRequired(items).length ? ' warn' : ''}`, role: 'status' }, checklistHeadline(items))),
    ...groups.map((group) => el('div', { class: 'check-group' },
      el('h3', { class: 'check-group-title' }, group.label),
      el('ul', {}, ...group.rows.map((item) => checkRow(item, onShow))))),
    line ? el('p', { class: `check-scale${line.tone ? ` ${line.tone}` : ''}`, title: line.detail },
      icon(line.tone === 'warn' ? 'warn' : 'scale'), line.text) : null);
}

function checkRow(item, onShow) {
  const met = item.status === 'met';
  const what = met ? `Found on ${item.met_by.join(' ')}${item.met_note ? `, ${item.met_note}` : ''}.` : 'Not in the set.';
  const levelWord = item.level === 'required' ? 'Required' : 'Recommended';
  return el('li', {
    class: `check-row ${item.status} ${item.level}`,
    dataset: { id: item.id, status: item.status, level: item.level },
    title: `${item.need}: ${levelWord.toLowerCase()}. ${what} ${item.why}`,
  },
  el('span', { class: 'check-state', 'aria-hidden': 'true' }, icon(met ? 'check' : 'st-declined')),
  el('span', { class: 'check-need' }, item.need, el('span', { class: 'check-level' }, ` ${levelWord}`)),
  el('span', { class: 'visually-hidden' }, met ? 'Found.' : 'Missing.'),
  met
    ? el('button', { class: 'intake-sum-pages', type: 'button', title: `Show ${item.met_by[0]}`, onclick: () => onShow(item.met_by[0]) }, item.met_by.join(' '))
    : el('span', { class: 'intake-sum-pages' }, 'Missing'));
}
