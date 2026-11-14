// Pure project comparison: quantities, constraint states, Pareto points and decision history.
import { designRows, designQuantity } from './design_view.js';

const CARGO = 'results.capacities.cargo_capacity_m3';
const FUEL = 'results.fuel.value';
const KEY_RESULTS = [CARGO, FUEL, 'results.hydrostatics.cb',
  'results.hydrostatics.displacement_t', 'results.capacities.deadweight_t',
  'results.power.brake_power_kw'];

/** Resolve direct children only. A missing or ambiguous parent has no project. */
export function designProject(records, projectId) {
  const parents = records.filter((record) => record.design_id === projectId);
  const parent = parents.length === 1 ? parents[0] : null;
  return { parent, candidates: parent ? records.filter((record) =>
    record.design_id !== projectId && record.lineage?.parent_design_id === projectId) : [] };
}

function quantities(record) {
  return new Map(designRows(record).filter((row) => row.kind === 'quantity')
    .map((row) => [row.path, row.quantity]));
}

function cell(quantity, base) {
  if (!quantity || !Number.isFinite(quantity.value)) {
    return { state: 'unknown', value: null, unit: null, band: null, delta: null, deltaPercent: null };
  }
  const comparable = base && Number.isFinite(base.value) && base.unit === quantity.unit;
  const delta = comparable ? quantity.value - base.value : null;
  return { state: 'known', value: quantity.value, unit: quantity.unit,
    band: designQuantity(quantity).uncertainty, quantity,
    delta, deltaPercent: comparable && base.value !== 0 ? delta / Math.abs(base.value) * 100 : null };
}

/** Rows use evidence paths as stable keys; absent and incompatible values stay explicit. */
export function compareRows(parent, candidates) {
  const maps = [parent, ...candidates].map(quantities);
  const dimensions = new Set([parent, ...candidates].flatMap((record) =>
    Object.keys(record?.main_dimensions || {}).map((key) => `main_dimensions.${key}`)));
  return [...dimensions, ...KEY_RESULTS].map((path) => {
    const base = maps[0].get(path);
    return { path, parent: cell(base, base), candidates: candidates.map((record, index) =>
      ({ candidate_id: record.design_id, ...cell(maps[index + 1].get(path), base) })) };
  });
}

const CONSTRAINTS = {
  max_draft: ['main_dimensions.draft', 'm', 'max'],
  min_cargo_volume: [CARGO, 'm3', 'min'],
  max_fuel_per_day: [FUEL, 't/day', 'max'],
};

/** Check central values in the stated units. Unsupported requirements are unknown. */
export function constraintChecks(record) {
  const values = quantities(record);
  return Object.entries(record?.requirements?.quantities || {}).map(([key, requirement]) => {
    const spec = CONSTRAINTS[key];
    const actual = spec ? values.get(spec[0]) : null;
    const known = spec && actual && Number.isFinite(actual.value) && Number.isFinite(requirement?.value)
      && actual.unit === spec[1] && requirement.unit === spec[1];
    const passes = known && (spec[2] === 'max' ? actual.value <= requirement.value : actual.value >= requirement.value);
    return { key, state: known ? (passes ? 'pass' : 'fail') : 'unknown',
      actual: actual || null, requirement };
  });
}

function overlaps(a, b) {
  return a && b && a.low <= b.high && b.low <= a.high;
}

/** Parent is a fixed reference, not a competitor. Bands do not change central-value dominance. */
export function paretoPoints(parent, candidates) {
  const points = [parent, ...candidates].filter(Boolean).map((record) => {
    const values = quantities(record);
    const fuel = values.get(FUEL);
    const cargo = values.get(CARGO);
    const x = fuel?.unit === 't/day' ? cell(fuel) : cell(null);
    const y = cargo?.unit === 'm3' ? cell(cargo) : cell(null);
    return { id: record.design_id, reference: record === parent, x: x.value, y: y.value,
      xBand: x.band, yBand: y.band, fails: constraintChecks(record).filter((check) => check.state === 'fail'),
      dominated: false, indistinguishable: [] };
  });
  const competitors = points.filter((point) => !point.reference);
  for (const point of competitors) {
    if (point.x === null || point.y === null) continue;
    point.dominated = competitors.some((other) => other !== point && other.x !== null && other.y !== null
      && other.x <= point.x && other.y >= point.y && (other.x < point.x || other.y > point.y));
    point.indistinguishable = competitors.filter((other) => other !== point
      && overlaps(point.xBand, other.xBand) && overlaps(point.yBand, other.yBand)).map((other) => other.id);
  }
  return points;
}

/** Latest ISO timestamp wins per candidate and discipline; append order breaks timestamp ties. */
export function currentDecisions(decisions) {
  const latest = new Map();
  for (const decision of decisions) {
    const key = JSON.stringify([decision.candidate_id, decision.discipline]);
    const previous = latest.get(key);
    if (!previous || Date.parse(decision.recorded_at) >= Date.parse(previous.recorded_at)) latest.set(key, decision);
  }
  return [...latest.values()];
}
