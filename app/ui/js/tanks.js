// Tank tables of a run (docs/TANKS_V1.md): the capacity plan row of a tank, the capacity plan
// with totals per content group, and a tank's sounding table. The values come from the CSV files
// the Python export wrote (TaskView.capacity_plan, the sounding_table command); nothing here
// computes tank data. Every value keeps its source label; the tables are drafts.

import { el } from './dom.js';
import { glyphChip } from './glyphs.js';

/**
 * Source labels of the tank model (vessel_reconstruction.tanks SOURCE_LABELS). Tones are the
 * app's existing label styles: plain for drawing values, dashed amber for guesses.
 */
const TANK_SOURCES = {
  traced: { word: 'Traced', tone: '', icon: 'src-traced', title: 'Measured from the drawing linework.' },
  read: { word: 'Read', tone: '', icon: 'read', title: 'Read from printed text on the drawing.' },
  guessed: { word: 'Guessed', tone: 'draft', icon: 'st-guessed', title: 'A default or a convention. Check it.' },
  ai_inferred: { word: 'AI read', tone: 'ai', icon: 'src-ai_inferred', title: 'Read by the AI, with no ink to follow. Check it.' },
};

/** The fields of one capacity plan row, in the order of the capacity plan CSV. */
const CAPACITY_FIELDS = [
  { name: 'Name', key: 'name', source: 'name', text: true },
  { name: 'Content', key: 'content', source: 'content', text: true },
  { name: 'Frames', key: 'frames', source: 'frames', text: true },
  { name: 'Volume 100 %', key: 'volume_100_m3', source: 'volume', digits: 2, unit: 'm³' },
  { name: 'Volume 98 %', key: 'volume_98_m3', source: 'volume', digits: 2, unit: 'm³' },
  { name: 'Density', key: 'density_t_m3', source: 'density', digits: 3, unit: 't/m³' },
  { name: 'Weight 98 %', key: 'weight_98_t', source: 'weight', digits: 2, unit: 't' },
  { name: 'LCG', key: 'lcg_m', source: 'centroid', digits: 3, unit: 'm' },
  { name: 'TCG', key: 'tcg_m', source: 'centroid', digits: 3, unit: 'm' },
  { name: 'VCG', key: 'vcg_m', source: 'centroid', digits: 3, unit: 'm' },
];

/** Sounding table columns the viewer shows, with their headings and decimals. */
const SOUNDING_COLUMNS = [
  { key: 'sounding_m', name: 'Sounding (m)', digits: 3 },
  { key: 'ullage_m', name: 'Ullage (m)', digits: 3 },
  { key: 'volume_m3', name: 'Volume (m³)', digits: 3 },
  { key: 'fill_pct', name: 'Fill (%)', digits: 1 },
];

/**
 * Tank content classes in legend order (vessel_reconstruction.tanks CONTENT_CLASSES), with their
 * legend words. Each colours a tank with the design token `--tank-<class>` (styles.css), the same
 * capacity-plan colour the GLB material has.
 */
export const TANK_CONTENT_CLASSES = [
  ['fuel_oil', 'Fuel oil'],
  ['diesel_oil', 'Diesel / gas oil'],
  ['lube_oil', 'Lube oil'],
  ['oily_residue', 'Sludge, bilge, waste oil'],
  ['water_ballast', 'Water ballast'],
  ['fresh_water', 'Fresh water'],
  ['feed_water', 'Feed / distilled water'],
  ['sewage', 'Sewage, grey, black water'],
  ['cargo', 'Cargo'],
  ['void', 'Void / dry'],
  ['other', 'Other'],
];
const KNOWN_CLASSES = new Map(TANK_CONTENT_CLASSES);

/** The design token of a content class ("--tank-fresh_water"); an unknown class is "other". */
export function tankToken(contentClass) {
  return `--tank-${KNOWN_CLASSES.has(contentClass) ? contentClass : 'other'}`;
}

/** Legend rows for tanks [{ content_class }]: one per class present, in legend order, with counts. */
export function tankLegend(tanks) {
  const counts = new Map();
  for (const tank of tanks) {
    const cls = KNOWN_CLASSES.has(tank.content_class) ? tank.content_class : 'other';
    counts.set(cls, (counts.get(cls) || 0) + 1);
  }
  return TANK_CONTENT_CLASSES
    .filter(([cls]) => counts.has(cls))
    .map(([cls, label]) => ({ cls, label, count: counts.get(cls), token: tankToken(cls) }));
}

/** Steel member groups in legend order (vessel_reconstruction.structure.display MEMBER_GROUPS). */
export const STEEL_GROUPS = [
  ['shell', 'Shell plating'],
  ['deck', 'Decks and inner bottom'],
  ['bulkhead', 'Bulkheads'],
  ['primary', 'Floors, girders, web frames'],
  ['stiffener', 'Frames, beams, stiffeners'],
];
const KNOWN_STEEL = new Map(STEEL_GROUPS);

/** The design token of a steel member group ("--steel-shell"); an unknown group is "primary". */
export function steelToken(group) {
  return `--steel-${KNOWN_STEEL.has(group) ? group : 'primary'}`;
}

/** Legend rows for structure meshes [{ group, members }]: member counts per group, in legend order. */
export function steelLegend(meshes) {
  const counts = new Map();
  for (const mesh of meshes) {
    const group = KNOWN_STEEL.has(mesh.group) ? mesh.group : 'primary';
    counts.set(group, (counts.get(group) || 0) + (mesh.members?.length || 0));
  }
  return STEEL_GROUPS
    .filter(([group]) => counts.has(group))
    .map(([group, label]) => ({ cls: group, label, count: counts.get(group), token: steelToken(group) }));
}

/**
 * Screen labels that do not overlap: `labels` are { id, x, y, width, height, priority } (a box
 * centred on x, y; higher priority first, then the given order). Returns the ids to show.
 */
export function placeLabels(labels) {
  const placed = [];
  const order = labels.map((label, index) => ({ label, index }))
    .sort((a, b) => (b.label.priority || 0) - (a.label.priority || 0) || a.index - b.index);
  for (const { label } of order) {
    const box = { left: label.x - label.width / 2, right: label.x + label.width / 2, top: label.y - label.height / 2, bottom: label.y + label.height / 2 };
    const overlaps = placed.some((other) => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top);
    if (!overlaps) placed.push({ ...box, id: label.id });
  }
  return new Set(placed.map((box) => box.id));
}

/** Word, tone and title of a source label; an unknown label shows as it is. */
export function tankSource(label) {
  return TANK_SOURCES[label] || { word: label || '—', tone: '', title: '' };
}

/** "2.01 t" from a number, or "—" when the file has no value. */
export function tankNumber(value, digits, unit = '') {
  if (!Number.isFinite(value)) return '—';
  return unit ? `${value.toFixed(digits)} ${unit}` : value.toFixed(digits);
}

/** The values of one capacity plan row as { name, value, source } items. */
export function capacityFields(row) {
  return CAPACITY_FIELDS.map((field) => ({
    name: field.name,
    value: field.text ? (row[field.key] || '—') : tankNumber(row[field.key], field.digits, field.unit),
    source: row.sources?.[field.source] || null,
  }));
}

/** The capacity plan row of a tank part, or null. */
export function capacityRowOf(plan, id) {
  return plan?.rows?.find((row) => row.id === id) || null;
}

/** One line per content group: "Water ballast · 2 of 3 built · 62.30 m³ · 63.86 t". */
export function groupLine(group) {
  const content = group.content ? group.content.charAt(0).toUpperCase() + group.content.slice(1) : 'No content';
  return `${content} · ${group.built} of ${group.tanks} built · ${tankNumber(group.volume_100_m3, 2, 'm³')} · ${tankNumber(group.weight_98_t, 2, 't')}`;
}

/** The sounding table as shown: headings and formatted rows of the columns the file has. */
export function soundingView(table) {
  const columns = SOUNDING_COLUMNS
    .map((column) => ({ ...column, index: table?.columns?.indexOf(column.key) ?? -1 }))
    .filter((column) => column.index >= 0);
  return {
    headings: columns.map((column) => column.name),
    rows: (table?.rows || []).map((row) => columns.map((column) => tankNumber(row[column.index], column.digits))),
  };
}

export function sourceChip(label) {
  if (!label) return null;
  const source = tankSource(label);
  if (!source.icon) {
    return el('span', { class: 'badge badge-small', dataset: { tone: source.tone }, title: source.title },
      el('span', { class: 'badge-text' }, source.word));
  }
  return glyphChip(source.icon, source.word, { tone: source.tone || null, detail: source.title, focusable: false });
}

/** The capacity plan row of the selected tank, inside the part detail. */
export function tankDetailBlock(row) {
  if (!row) {
    return el('p', { class: 'parts-note' }, 'This tank is not in the run\'s capacity plan.');
  }
  return el('section', { class: 'tank-detail', 'aria-label': 'Capacity plan row' },
    el('h3', {}, 'Capacity plan'),
    el('table', { class: 'parts-args' },
      el('caption', { class: 'visually-hidden' }, `Capacity plan values of ${row.name}`),
      el('thead', {}, el('tr', {},
        el('th', { scope: 'col' }, 'Item'), el('th', { scope: 'col' }, 'Value'), el('th', { scope: 'col' }, 'Source'))),
      el('tbody', {}, ...capacityFields(row).map((field) => el('tr', { dataset: { source: field.source || '' } },
        el('th', { scope: 'row' }, field.name),
        el('td', { class: 'parts-value' }, field.value),
        el('td', {}, sourceChip(field.source)))))),
    row.notes ? el('p', { class: 'parts-reason' }, row.notes) : null);
}

/** One sounding table: the levels of the selected tank, or why there are none. */
function soundingBlock(row, sounding) {
  if (!row) return el('p', { class: 'panel-empty' }, 'Pick a tank to see its sounding table.');
  const title = el('h3', {}, `Sounding table: ${row.name}`);
  if (!row.has_sounding) return el('div', { class: 'tank-sounding' }, title, el('p', { class: 'panel-empty' }, 'This tank has no sounding table (not built).'));
  if (!sounding || sounding.loading) return el('div', { class: 'tank-sounding' }, title, el('p', { class: 'panel-empty' }, 'Loading…'));
  if (sounding.error) return el('div', { class: 'tank-sounding' }, title, el('p', { class: 'form-error', role: 'alert' }, sounding.error));
  const view = soundingView(sounding.table);
  return el('div', { class: 'tank-sounding' }, title,
    el('p', { class: 'parts-revision-hint' }, 'Sounding from the lowest point of the tank, even keel (no sounding pipe position is drawn). Origin: ', sourceChip('guessed')),
    el('div', { class: 'tank-table-scroll' },
      el('table', { class: 'parts-args tank-table' },
        el('caption', { class: 'visually-hidden' }, `Sounding table of ${row.name}`),
        el('thead', {}, el('tr', {}, ...view.headings.map((heading) => el('th', { scope: 'col' }, heading)))),
        el('tbody', {}, ...view.rows.map((cells) => el('tr', {}, ...cells.map((cell) => el('td', { class: 'parts-value' }, cell))))))));
}

/**
 * The capacity plan panel: every tank with its labelled values, totals per content group and
 * the sounding table of the selected tank. `onPick(id)` selects a tank.
 */
export function capacityPanel({ plan, selectedId, sounding, onPick }) {
  if (!plan?.rows?.length) return null;
  const selected = capacityRowOf(plan, selectedId);
  const cell = (row, key, digits, source) => el('td', { class: 'parts-value' }, tankNumber(row[key], digits), ' ', sourceChip(row.sources?.[source]));
  return el('section', { class: 'tank-plan', 'aria-labelledby': 'tank-plan-title' },
    el('header', { class: 'parts-detail-head' },
      el('h2', { id: 'tank-plan-title' }, 'Capacity plan'),
      el('span', { class: 'badge badge-small', dataset: { tone: 'draft' }, title: plan.stamp?.join('\n') || '' }, el('span', { class: 'badge-text' }, 'Draft'))),
    el('p', { class: 'export-stamp' }, el('strong', {}, 'Draft, not for construction.'), ` Read from ${plan.file}. Volumes at 100 % and 98 % fill; weight at 98 %; centroid at 100 %.`),
    el('ul', { class: 'tank-groups', 'aria-label': 'Totals per content group' }, ...plan.groups.map((group) => el('li', {}, groupLine(group)))),
    el('div', { class: 'tank-table-scroll' },
      el('table', { class: 'parts-args tank-table' },
        el('caption', { class: 'visually-hidden' }, 'Tanks of the capacity plan'),
        el('thead', {}, el('tr', {}, ...['Tank', 'Content', 'Frames', 'Vol. 100 % (m³)', 'Vol. 98 % (m³)', 'Weight 98 % (t)', 'LCG (m)', 'VCG (m)', 'TCG (m)']
          .map((heading) => el('th', { scope: 'col' }, heading)))),
        el('tbody', {}, ...plan.rows.map((row) => el('tr', { class: row.id === selectedId ? 'is-selected' : '', dataset: { source: row.sources?.volume || '' } },
          el('th', { scope: 'row' }, el('button', { class: 'tank-pick', type: 'button', 'aria-pressed': String(row.id === selectedId), onclick: () => onPick(row.id) }, row.name || row.id)),
          el('td', {}, row.content, ' ', sourceChip(row.sources?.content)),
          el('td', { class: 'parts-value' }, row.frames || '—'),
          cell(row, 'volume_100_m3', 2, 'volume'),
          cell(row, 'volume_98_m3', 2, 'volume'),
          cell(row, 'weight_98_t', 2, 'weight'),
          cell(row, 'lcg_m', 3, 'centroid'),
          cell(row, 'vcg_m', 3, 'centroid'),
          cell(row, 'tcg_m', 3, 'centroid')))))),
    soundingBlock(selected, sounding));
}
