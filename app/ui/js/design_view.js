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
    lineage: record.lineage, scope: record.data_scope, warnings, unknowns, lite,
  };
}
