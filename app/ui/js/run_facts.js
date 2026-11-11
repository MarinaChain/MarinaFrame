// Pure rules derived from the run list and from one run's view: vessels, review counts,
// section shapes and guessed ranges. No DOM and no backend, so tests import it directly.



// ---------------------------------------------------------------- vessels (derived from runs)

// There is no vessel model yet: runs are grouped by the vessel name at the start of the run
// name ("Pilot boat, lines plan" -> "Pilot boat"). The vessel lane replaces this.

/** Run states that put a vessel in the "Needs you" row. */
export const DRAFT_READY = new Set(['draft', 'needs_review']);
export const NEEDS_ATTENTION = new Set(['failed', 'blocked', 'declined']);

export function vesselNameOf(runName) {
  let name = runName.split(/,|·| — | – | - /)[0].trim() || runName.trim();
  // A file-name slug such as "dtmb-5415-lines-plan" reads better as words.
  if (/^[a-z0-9]+([-_][a-z0-9]+)+$/.test(name)) name = name.replace(/[-_]/g, ' ');
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** Vessels, most recently active first. Each has its runs, newest first. */
export function groupVessels(tasks) {
  const byKey = new Map();
  for (const task of tasks) {
    const name = vesselNameOf(task.name);
    const key = name.toLowerCase();
    if (!byKey.has(key)) byKey.set(key, { key, name, runs: [] });
    byKey.get(key).runs.push(task);
  }
  const vessels = [...byKey.values()];
  for (const vessel of vessels) {
    vessel.runs.sort((a, b) => b.updated_ms - a.updated_ms);
    vessel.latest = vessel.runs[0];
  }
  return vessels.sort((a, b) => b.latest.updated_ms - a.latest.updated_ms);
}

/** Runs of a vessel are numbered oldest first: "Run 1" is the first attempt. */
export function runNumber(vessel, task) {
  return vessel.runs.length - vessel.runs.findIndex((r) => r.task === task);
}

/** The vessel of run `task` among `tasks` (the run list), or null. */
export function vesselOfTask(tasks, task) {
  return groupVessels(tasks).find((v) => v.runs.some((r) => r.task === task)) || null;
}

/** Sections a reviewer should look at: guessed lines and declined sections. */
export function toCheckCount(view) {
  return view?.sections.filter((s) => s.state === 'guessed' || s.state === 'declined').length || 0;
}

/** Whole-vessel parts that still need a look: guessed or not built, and not accepted. */
export function partsToCheck(view) {
  return (view?.components || []).filter((p) => p.review !== 'accepted' && (p.status === 'draft_guess' || !p.built)).length;
}

/** Sections a person still has to look at: a guessed line or a declined section. */
export function needsCheck(section) {
  return section.state === 'guessed' || section.state === 'declined';
}

export function sectionShapePath(section) {
  const line = section.candidates.find((c) => c.chosen) || (section.state === 'declined' ? section.candidates[0] : null);
  if (!line) return null;
  const [x0, y0, x1, y1] = section.roi_px;
  const w = x1 - x0;
  const h = y1 - y0;
  return line.polyline_px.map(([x, y], i) => `${i ? 'L' : 'M'}${(((x - x0) / w) * 44).toFixed(1)} ${(((y - y0) / h) * 54).toFixed(1)}`).join(' ');
}

/**
 * x ranges (metres) the draft guessed. A bridged gap or a dropped end has its own range.
 * A guessed line covers the part of the hull nearer to its station than to any other.
 */
export function guessedXRanges(sections, lengthM) {
  const stations = sections.map((s) => s.x_m).sort((a, b) => a - b);
  const ranges = [];
  for (const section of sections) {
    const guess = section.guess;
    if (!guess) continue;
    if (guess.x_range_m) {
      ranges.push(guess.x_range_m);
      continue;
    }
    const at = stations.indexOf(section.x_m);
    const before = at > 0 ? (stations[at - 1] + section.x_m) / 2 : Math.max(0, section.x_m - 0.25);
    const after = at < stations.length - 1 ? (stations[at + 1] + section.x_m) / 2 : Math.min(lengthM, section.x_m + 0.25);
    ranges.push([before, after]);
  }
  return ranges;
}

export function defaultSection(view) {
  const needsAttention = view.sections.find((s) => s.state === 'declined' || s.state === 'guessed');
  return (needsAttention || view.sections[0])?.id || null;
}
