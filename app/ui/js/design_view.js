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
    missingKey: path.startsWith('results.') ? 'design.pending' : 'design.notSupplied',
  }));
  return lite ? LITE_PARTICULARS.map((key) => cards.find((card) => card.key === key)) : cards;
}

/** Group risk notices by discipline, preserving every notice and its evidence path. */
export function designWarningGroups(rows) {
  const groups = new Map();
  for (const row of rows) {
    const topic = ['resistance', 'power', 'fuel'].find((key) => row.path.startsWith(`results.${key}.`)) || 'hull';
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
    return { key, quantity, delta };
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
