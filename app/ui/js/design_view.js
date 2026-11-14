// Pure design-record mapping. Preserve evidence paths, missing values and all risk notices.

/** Flatten schema quantities and tagged evidence without guessing units or dropping unknowns. */
export function designRows(value, path = '') {
  if (value === null || value === undefined) return [{ path, kind: 'unknown' }];
  if (typeof value !== 'object') return [{ path, kind: 'text', value }];
  if ('unit' in value && 'method_version' in value) return [{ path, kind: 'quantity', quantity: value }];
  if ('kind' in value && 'value' in value) {
    if (value.kind === 'missing') return [{ path, kind: 'unknown' }];
    return designRows(value.value, path);
  }
  const entries = Object.entries(value);
  if (!entries.length) return [{ path, kind: 'empty' }];
  return entries.flatMap(([key, child]) => designRows(child, path ? `${path}.${key}` : key));
}

/** Adapt schema deviations to the shared display's endpoints. No band is not zero uncertainty. */
export function designQuantity(quantity) {
  const band = quantity.uncertainty;
  const scale = band?.kind === 'relative' ? Math.abs(quantity.value) : 1;
  return {
    ...quantity,
    uncertainty: band ? { low: quantity.value - band.lower * scale, high: quantity.value + band.upper * scale } : null,
    status: quantity.status === 'review_required' ? 'needs_review' : 'draft',
    source: quantity.sources.join('\n'),
  };
}

/** A missing result is "not calculated yet"; a missing input (also a calculation's input) is "not supplied". */
export function designMissingKey(path) {
  return path.startsWith('results.') && !path.includes('.inputs.') ? 'design.pending' : 'design.notSupplied';
}

// Explicit paths avoid confusing gross immersed volume with usable cargo capacity.
const PARTICULARS = [
  ['length', 'main_dimensions.length'],
  ['beam', 'main_dimensions.beam'],
  ['draft', 'main_dimensions.draft'],
  ['depth', 'main_dimensions.depth'],
  ['cb', 'results.hydrostatics.cb'],
  ['displacement', 'results.hydrostatics.displacement_t'],
  ['deadweight', 'results.capacities.deadweight_t'],
  ['cargo_capacity', 'results.capacities.cargo_capacity_m3'],
  ['service_speed', 'requirements.service_speed.kn'],
  ['brake_power', 'results.power.brake_power_kw'],
  ['fuel', 'results.fuel.value'],
];
const LITE_PARTICULARS = ['length', 'beam', 'draft', 'deadweight', 'cargo_capacity', 'fuel', 'service_speed'];

/** Stable card slots, including absent results. Never infer capacity from hull geometry. */
export function designParticulars(record, { lite = false } = {}) {
  const rows = new Map(designRows(record).map((row) => [row.path, row]));
  const cards = PARTICULARS.map(([key, path]) => ({
    key, path, kind: 'unknown', ...rows.get(path),
    missingKey: designMissingKey(path),
  }));
  return lite ? LITE_PARTICULARS.map((key) => cards.find((card) => card.key === key)) : cards;
}

// Calculation order: resistance feeds power, power feeds fuel. Anything else is about the hull.
export const DESIGN_TOPICS = ['hull', 'resistance', 'power', 'fuel'];

/** The discipline a record path belongs to: resistance, power, fuel or (otherwise) hull. */
export function designTopic(path) {
  return ['resistance', 'power', 'fuel'].find((key) => path.startsWith(`results.${key}.`)) || 'hull';
}

/** Group risk notices by discipline, preserving every notice and its evidence path. */
export function designWarningGroups(rows) {
  const groups = new Map();
  for (const row of rows) {
    const topic = designTopic(row.path);
    if (!groups.has(topic)) groups.set(topic, []);
    groups.get(topic).push(row);
  }
  return [...groups].map(([topic, warnings]) => ({ topic, warnings }));
}

/** Compare variation quantities only with matching parent evidence and units. */
export function designChanges(record, parent) {
  const parameters = record.lineage?.variation_parameters || {};
  const previous = parent?.lineage?.variation_parameters || {};
  return Object.entries(parameters).map(([key, quantity]) => {
    const base = previous[key];
    const delta = base && base.unit === quantity.unit && Number.isFinite(base.value) && Number.isFinite(quantity.value)
      ? Number((quantity.value - base.value).toPrecision(12)) : null;
    return { key, quantity, base: delta === null ? null : base, delta };
  });
}

/** Rows for each tab and Lite. Empty collections remain explicit; warnings are never filtered away. */
export function designView(record) {
  const all = designRows(record);
  const under = (...prefixes) => all.filter((row) => prefixes.some((prefix) => row.path === prefix || row.path.startsWith(`${prefix}.`)));
  const warnings = all.filter((row) => /warning|validity|\.notes\./i.test(row.path) && row.kind !== 'empty');
  const unknowns = all.filter((row) => row.kind === 'unknown' || row.kind === 'empty');
  const overview = under('main_dimensions', 'results.hydrostatics', 'results.capacities', 'results.fuel.value');
  const lite = [...new Map([...under('main_dimensions', 'results.capacities', 'results.fuel.value', 'requirements.constraints'), ...unknowns].map((row) => [row.path, row])).values()];
  return {
    overview, requirements: under('requirements'), arrangement: under('compartments', 'tanks'),
    weights: under('weights', 'loading_conditions', 'results.stability'),
    performance: under('results.resistance', 'results.power', 'results.fuel'),
    provenance: all.filter((row) => row.kind === 'quantity'),
    all, particulars: designParticulars(record),
    lineage: record.lineage, scope: record.data_scope, warnings, unknowns, lite,
  };
}

/**
 * Maximum fraction digits for a summary value: enough to read a design change at a glance
 * (Cb 0.914 to 0.924), not every digit of the calculation. The full value stays in the evidence.
 */
export function designDigits(value) {
  const size = Math.abs(value);
  if (size > 0 && size < 0.01) return null; // tiny coefficients: use significant digits instead
  if (size >= 100) return 0;
  if (size >= 10) return 1;
  if (size >= 1) return 2;
  return 3;
}

// Keys a section shows elsewhere: the Draft rule is in the page header, warnings are in the
// warnings block, the method is the section caption and the unit is part of each value.
const SECTION_ASIDE = /^(engineering_approved|method|unit|validity_warnings|range_warnings|warnings)$/;

/** The section a row belongs to: results.<discipline>[.<part>] for results, else the top-level key. */
function sectionPath(path) {
  const keys = path.split('.').filter((key) => !/^\d+$/.test(key));
  const isResult = keys[0] === 'results';
  const depth = Math.min(isResult ? 3 : 1, Math.max(keys.length - 1, isResult ? 2 : 1));
  return keys.slice(0, depth).join('.');
}

/**
 * Rows of a tab grouped into sections (for example results.resistance.inputs), in `order` of
 * topic. Each section keeps its method text apart; warnings and the Draft flag are left out
 * because the page shows them in one place. Unknown and empty rows stay: they are states.
 */
export function designSections(rows, order = DESIGN_TOPICS) {
  const sections = new Map();
  for (const row of rows) {
    const path = sectionPath(row.path);
    if (!sections.has(path)) sections.set(path, { path, topic: designTopic(`${path}.`), method: null, rows: [] });
    const section = sections.get(path);
    const leaf = row.path.split('.').filter((key) => !/^\d+$/.test(key)).at(-1);
    if (leaf === 'method' && row.kind === 'text') section.method = row.value;
    else if (!SECTION_ASIDE.test(leaf) || row.path === path) section.rows.push(row);
  }
  const rank = (section) => order.indexOf(section.topic);
  return [...sections.values()].filter((section) => section.rows.length)
    .map((section, index) => ({ ...section, index }))
    .sort((a, b) => rank(a) - rank(b) || a.index - b.index);
}

// Empty lists that mean "none found", not "not supplied": warning lists and sampling gaps.
const EMPTY_IS_NONE = /(warnings|disconnected_intervals_m)$|^results\.hull_variation\./;
// Record keeping, not design inputs: the customer ID is administrative, and decisions have their
// own tab (they live in a sidecar until schema 1.2). Neither belongs in "what the designer lacks".
const NOT_A_DESIGN_INPUT = /^(data_scope\.customer_id|designer_decisions)$/;

/**
 * What the designer still lacks, split into results not calculated yet and inputs not supplied.
 * Main particulars come first. Each path appears once.
 */
export function designMissing(record) {
  const view = designView(record);
  const rows = [...view.particulars.filter((card) => card.kind === 'unknown' || card.kind === 'empty'),
    ...view.unknowns.filter((row) => !EMPTY_IS_NONE.test(row.path) && !NOT_A_DESIGN_INPUT.test(row.path))];
  // A missing container (results.capacities) is already shown by its particulars (deadweight).
  const covered = (row) => !row.key && view.particulars.some((card) => card.path.startsWith(`${row.path}.`));
  const unique = [...new Map(rows.filter((row) => !covered(row)).map((row) => [row.path, row])).values()];
  return {
    pending: unique.filter((row) => designMissingKey(row.path) === 'design.pending'),
    notSupplied: unique.filter((row) => designMissingKey(row.path) === 'design.notSupplied'),
  };
}
