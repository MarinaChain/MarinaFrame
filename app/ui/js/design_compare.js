// Pure project comparison: quantities, constraint states, Pareto points and decision history.
import { designRows, designQuantity } from './design_view.js';

export const CARGO = 'results.capacities.cargo_capacity_m3';
export const FUEL = 'results.fuel.value';
// Values of the decision sidecar (docs/design/2026-11-14-decision-discipline-proposal.md).
export const DISCIPLINES = ['basic_design', 'structure', 'machinery', 'outfitting', 'accommodation'];
export const DECISION_ACTIONS = ['accepted', 'deferred', 'rejected'];
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

/* ---------- Views for the project tabs ---------- */

/** Short chart label: the letter after "Candidate" in the name, else A, B, C by position. */
export function candidateLetter(record, index) {
  const match = /^candidate\s+([A-Za-z0-9]{1,3})\b/i.exec(record?.name || '');
  return match ? match[1].toUpperCase() : String.fromCharCode(65 + (index % 26));
}

// Parent paths where a variation parameter (length, beam, draft, cb) has its base value.
const BASE_PATHS = ['main_dimensions.', 'lineage.variation_parameters.', 'results.hydrostatics.'];

/** Each variation parameter of a candidate against the parent's own value of that key. */
export function variationChanges(candidate, parent) {
  const parentValues = parent ? quantities(parent) : new Map();
  return Object.entries(candidate?.lineage?.variation_parameters || {}).map(([key, quantity]) => {
    const base = BASE_PATHS.map((prefix) => parentValues.get(prefix + key)).find(Boolean) || null;
    const { delta, deltaPercent } = cell(quantity, base);
    return { key, quantity, base, delta, deltaPercent };
  });
}

// Only these two quantities have a direction that is better for every design: less fuel per
// day and more cargo. Every other delta is a change, not a gain or a loss.
const BETTER_WHEN = { [FUEL]: -1, [CARGO]: 1 };

/** 'better', 'worse' or null (no direction for this quantity, or no change). */
export function deltaTone(path, delta) {
  const direction = BETTER_WHEN[path];
  if (!direction || !delta) return null;
  return delta * direction > 0 ? 'better' : 'worse';
}

/** Counts of pass, fail and unknown constraint checks. */
export function checkCounts(checks) {
  const counts = { pass: 0, fail: 0, unknown: 0 };
  for (const check of checks) counts[check.state] += 1;
  return counts;
}

/** 'reference' (the parent), 'unknown' (an axis value is missing), 'dominated' or 'front'. */
export function paretoState(point) {
  if (point.reference) return 'reference';
  if (point.x === null || point.y === null) return 'unknown';
  return point.dominated ? 'dominated' : 'front';
}

/** Each pair of candidates whose bands overlap on both axes, once, in candidate order. */
export function indistinguishablePairs(points) {
  const order = points.map((point) => point.id);
  const pairs = [];
  for (const point of points) {
    for (const other of point.indistinguishable) {
      if (order.indexOf(other) > order.indexOf(point.id)) pairs.push([point.id, other]);
    }
  }
  return pairs;
}

/**
 * The first comparison: up to `limit` candidates on the front, then dominated ones to reach
 * two. A candidate with an unknown axis value is only added when nothing else is left.
 */
export function defaultComparison(points, limit = 4) {
  const competitors = points.filter((point) => !point.reference);
  const rank = { front: 0, dominated: 1, unknown: 2 };
  const ordered = competitors.map((point, index) => ({ point, index }))
    .sort((a, b) => rank[paretoState(a.point)] - rank[paretoState(b.point)] || a.index - b.index);
  const front = ordered.filter(({ point }) => paretoState(point) === 'front');
  const count = Math.min(limit, Math.max(front.length, Math.min(2, ordered.length)));
  return ordered.slice(0, count).sort((a, b) => a.index - b.index).map(({ point }) => point.id);
}

/** Current decisions as candidate id → discipline → decision (null when not decided). */
export function decisionGrid(candidateIds, decisions) {
  const grid = new Map(candidateIds.map((id) => [id, Object.fromEntries(DISCIPLINES.map((key) => [key, null]))]));
  for (const decision of currentDecisions(decisions)) {
    const row = grid.get(decision.candidate_id);
    if (row && decision.discipline in row) row[decision.discipline] = decision;
  }
  return grid;
}

/** The log newest first; for equal times the later entry in the file comes first. */
export function decisionLog(decisions) {
  return decisions.map((decision, index) => ({ decision, index }))
    .sort((a, b) => (Date.parse(b.decision.recorded_at) - Date.parse(a.decision.recorded_at)) || b.index - a.index)
    .map(({ decision }) => decision);
}
