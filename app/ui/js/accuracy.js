// Accuracy summary per output (hull, tanks, steel): a port of src/vessel_reconstruction/accuracy_summary.py.
// It joins the measured error bands (accuracy_bands.js, generated from the Python table) with the
// run's own facts into one short line per output. A compact chip (icon + band) shows it on the run
// page; the full line and the sources are in the chip's two-stage tooltip. Nothing here says a
// result is approved or verified: the bands are measurements on other ships, not a check of this run.
// tests/fixtures/accuracy_summary_cases.json is run by both the Python and the JavaScript tests.

import { el, icon } from './dom.js';
import { glyphChip } from './glyphs.js';
import { BANDS } from './accuracy_bands.js';

export const DRAFT_NOTE = 'Draft only. engineering_approved stays false; a naval architect decides what to trust.';
export const SCOPE_NOTE = 'Bands are measured on other ships and sheets, not on this run. Where a band says not measured, nothing is known.';

const HULL_DETAIL_IDS = {
  model_reading: ['hull.model_reading_clean'],
  scanned_body_plan: ['hull.scanned_bue_girl', 'hull.scanned_bumble_bee', 'hull.scanned_thayer', 'hull.scanned_pardon_me'],
  vector_drawing: ['hull.vector_gunnerus'],
};
const SCANNED_HEAD_IDS = {
  round_bilge: ['hull.scanned_bue_girl', 'hull.scanned_bumble_bee'],
  hard_chine: ['hull.scanned_pardon_me'],
  unknown: ['hull.scanned_bue_girl', 'hull.scanned_pardon_me'],
};
const TANK_HEAD_IDS = {
  vector_plan: ['tanks.vector_gunnerus'],
  raster_plan: ['tanks.raster_dev', 'tanks.raster_holdout'],
  unknown: ['tanks.vector_gunnerus', 'tanks.raster_holdout'],
};
const STEEL_HEAD_IDS = ['steel.positions', 'steel.weight'];
const NOT_PRESENT = { tanks: 'Tanks: none in this run.', steel: 'Steel: none in this run.' };
const WEAK = new Set(['missed', 'mixed', 'not measured']);

/** Icon of each output chip (index.html sprite). */
export const OUTPUT_ICONS = { hull: 'waterline', tanks: 'drop', steel: 'frames' };
export const OUTPUT_NAMES = { hull: 'Hull', tanks: 'Tanks', steel: 'Steel' };

export const band = (id) => BANDS.find((b) => b.id === id);
const validIds = (ids) => ids.filter((id) => band(id).outcome !== 'invalid');
const bandsOf = (ids) => validIds(ids).map(band);
const bandsFor = (output) => BANDS.filter((b) => b.output === output && b.outcome !== 'invalid').map((b) => b.id);
const count = (labels, ...names) => names.reduce((sum, name) => sum + Number(labels?.[name] || 0), 0);
const total = (labels) => Object.values(labels || {}).reduce((sum, n) => sum + Number(n || 0), 0);
const chipOf = (bands) => bands.map((b) => b.chip).join(' / ');
const weak = (bands) => bands.some((b) => WEAK.has(b.outcome));

function hull(facts) {
  const path = HULL_DETAIL_IDS[facts.path] ? facts.path : 'model_reading';
  const hullType = path === 'scanned_body_plan' ? facts.hull_type || null : null;
  const headIds = validIds(path === 'scanned_body_plan' ? SCANNED_HEAD_IDS[hullType || 'unknown'] : HULL_DETAIL_IDS[path]);
  const head = bandsOf(headIds);
  let text = head.map((b) => b.short).join('; ');
  if (path === 'scanned_body_plan' && !hullType) text += ' (hull type not known)';
  const parts = [`Hull: ${text}`];
  const labels = facts.labels || {};
  const all = total(labels);
  const traced = count(labels, 'traced', 'repaired');
  if (all) {
    const extras = [[count(labels, 'interpolated'), 'interpolated'], [count(labels, 'ai_inferred', 'ai_corrected'), 'by AI'], [count(labels, 'omitted'), 'not modelled']];
    parts.push(`${traced} of ${all} sections traced${extras.filter(([n]) => n).map(([n, word]) => `, ${n} ${word}`).join('')}`);
  }
  const toCheck = facts.to_check ?? null;
  if (toCheck !== null) parts.push(toCheck ? `${toCheck} to check` : 'no open check items');
  if (facts.fit !== undefined && facts.fit !== null) parts.push(`fit score ${facts.fit.toFixed(2)}`);
  return {
    output: 'hull', present: true, line: `${parts.join('; ')}.`, chip: chipOf(head),
    caution: weak(head) || Boolean(toCheck) || all > traced, head_ids: headIds, detail_ids: validIds(HULL_DETAIL_IDS[path]),
  };
}

function tanks(facts) {
  if (!facts) return { output: 'tanks', present: false, line: NOT_PRESENT.tanks, chip: '', caution: false, head_ids: [], detail_ids: [] };
  const headIds = validIds(TANK_HEAD_IDS[facts.path || 'unknown'] || TANK_HEAD_IDS.unknown);
  const head = bandsOf(headIds);
  const parts = [`Tanks: ${head.map((b) => b.short).join('; ')}`];
  const all = total(facts.volume_labels);
  const guessed = count(facts.volume_labels, 'guessed');
  if (all) parts.push(`${all - guessed} of ${all} volumes traced or read${guessed ? `, ${guessed} guessed` : ''}`);
  const missing = Number(facts.total || 0) - Number(facts.built || 0);
  if (missing > 0) parts.push(`${missing} not built`);
  return {
    output: 'tanks', present: true, line: `${parts.join('; ')}.`, chip: chipOf(head),
    caution: weak(head) || guessed > 0 || missing > 0, head_ids: headIds, detail_ids: bandsFor('tanks'),
  };
}

function steel(facts) {
  if (!facts) return { output: 'steel', present: false, line: NOT_PRESENT.steel, chip: '', caution: false, head_ids: [], detail_ids: [] };
  const head = bandsOf(STEEL_HEAD_IDS);
  const parts = [`Steel: ${head.map((b) => b.short).join('; ')}`];
  const all = total(facts.thickness_labels);
  if (all) {
    const printed = count(facts.thickness_labels, 'printed');
    parts.push(`${printed} of ${all} thicknesses printed, ${all - printed} guessed or missing`);
  }
  return { output: 'steel', present: true, line: `${parts.join('; ')}.`, chip: chipOf(head), caution: true, head_ids: validIds(STEEL_HEAD_IDS), detail_ids: bandsFor('steel') };
}

/** The summary of every output from a run's facts (see accuracy_summary.py for the shape). */
export function summarise(facts) {
  return { hull: hull(facts.hull || {}), tanks: tanks(facts.tanks ?? null), steel: steel(facts.steel ?? null) };
}

/** Facts of a run from its TaskView (the fields app/core gives the UI). Path and hull type are not recorded in a view. */
export function factsOfView(view) {
  const labels = {};
  for (const entry of view?.source_counts || []) labels[entry.label] = entry.count;
  const toCheck = (view?.sections || []).filter((s) => s.state === 'guessed' || s.state === 'declined').length;
  const rows = view?.capacity_plan?.rows || [];
  const volumeLabels = {};
  for (const row of rows.filter((r) => r.built)) {
    const source = row.sources?.volume || 'guessed';
    volumeLabels[source] = (volumeLabels[source] || 0) + 1;
  }
  return {
    hull: { path: view?.body_plan_check?.used ? 'scanned_body_plan' : 'model_reading', hull_type: null, labels, to_check: toCheck, fit: null },
    tanks: view?.tank_model ? { built: rows.filter((r) => r.built).length, total: rows.length, path: null, volume_labels: Object.keys(volumeLabels).length ? volumeLabels : null } : null,
    steel: view?.structure_files?.length ? { thickness_labels: null } : null,
  };
}

/** The tooltip detail: the line, then each band with its set, N and source (limits are in the report). */
// The tooltip detail stays short (founder: few words). The run's summary line already names the measured
// band, so the detail is that line alone, broken at its clauses into at most three lines. Sources and doc
// sections are in the PDF report's "Accuracy and limits" section, not in the app.
const DETAIL_MAX_LINES = 3;

export function detailText(summary) {
  const clauses = summary.line.split('; ').map((clause) => clause.trim()).filter(Boolean);
  const head = clauses.slice(0, DETAIL_MAX_LINES - 1);
  const rest = clauses.slice(DETAIL_MAX_LINES - 1).join('; ');
  return [...head, ...(rest ? [rest] : [])].join('\n');
}

/** One compact chip: the output's icon and its band; the line and sources are in the tooltip. */
export function accuracyChip(summary, { focusable = true } = {}) {
  const name = OUTPUT_NAMES[summary.output];
  return glyphChip(OUTPUT_ICONS[summary.output], `${name} accuracy`, {
    count: summary.chip, countedName: `${name} accuracy: ${summary.chip}`, tone: summary.caution ? 'draft' : null,
    detail: detailText(summary), focusable,
  });
}

/** The chips of the outputs a run has, in a row for the run page. */
export function accuracyChips(view) {
  const present = Object.values(summarise(factsOfView(view))).filter((s) => s.present);
  if (!view?.revision || !present.length) return null;
  return el('span', { class: 'accuracy-chips', role: 'group', 'aria-label': 'Accuracy of each output, measured on other ships' }, ...present.map((s) => accuracyChip(s)));
}

/** The export page block: the same summary as the report's "Accuracy and limits", one line per output. */
export function accuracyBlock(view) {
  const present = Object.values(summarise(factsOfView(view))).filter((s) => s.present);
  if (!present.length) return null;
  return el('section', { class: 'export-accuracy', 'aria-labelledby': 'export-accuracy-title' },
    el('h2', { id: 'export-accuracy-title', class: 'export-accuracy-title' }, icon('info'), 'Accuracy and limits'),
    el('p', { class: 'export-accuracy-note' }, SCOPE_NOTE),
    ...present.map((s) => el('p', { class: 'export-accuracy-line', dataset: { output: s.output } }, accuracyChip(s), el('span', {}, s.line))));
}
