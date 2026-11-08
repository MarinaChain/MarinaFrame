// Changes in a run (History tab): what each revision changed, read from the live steps
// (get_live_steps). One entry per scored revision: the fit before and after, the step that
// caused it, and the sections whose source or distance to the ink changed. Edits that the
// run did not keep are listed too, with their reason. Nothing here judges a revision as
// "good" or "approved": the numbers are for a person to read.

import { el, icon } from './dom.js';
import * as fmt from './format.js';

/** Step kinds that change the model; the newest one before a build is its cause. */
const CAUSE_KINDS = new Set(['assign', 'propose_section', 'revise', 'choose']);
/** A change in distance to the ink smaller than this (metres) is not shown. */
const INK_CHANGE_MIN_M = 0.001;

function revisionLabel(id) {
  const match = /^r0*(\d+)$/.exec(id || '');
  return match ? `r${match[1]}` : id || 'build';
}

/**
 * The changes of a run, oldest first: `{ kind: 'revision', id, fit, previousFit, cause,
 * sections: [{ x_m, from, to, inkFrom, inkTo }] }` or `{ kind: 'not_kept', title, text }`.
 */
export function buildChanges(steps) {
  const revisions = new Map(); // id -> { id, fit, sections, cause, order }
  const entries = [];
  let cause = null;
  for (const step of steps) {
    if (step.tool?.kept === false) {
      entries.push({ kind: 'not_kept', title: step.title, text: step.tool.text });
      continue;
    }
    if (CAUSE_KINDS.has(step.kind)) cause = step.title;
    const revision = step.revision;
    if (!revision?.id) continue;
    let entry = revisions.get(revision.id);
    if (!entry) {
      entry = { kind: 'revision', id: revision.id, fit: null, sections: [], cause: cause || step.title };
      revisions.set(revision.id, entry);
      entries.push(entry);
      cause = null;
    }
    if (revision.fit !== null && revision.fit !== undefined) {
      entry.fit = revision.fit;
      entry.sections = revision.sections.map((s) => ({ id: s.id, x_m: s.x_m, label: s.source_label, ink: s.ink_rms_m }));
    }
  }
  // Compare each scored revision with the scored one before it.
  let previous = null;
  for (const entry of entries) {
    if (entry.kind !== 'revision' || entry.fit === null) continue;
    entry.previousFit = previous?.fit ?? null;
    entry.changes = [];
    for (const section of entry.sections) {
      const before = previous?.sections.find((s) => s.id === section.id);
      if (!before) continue;
      const labelChanged = before.label !== section.label;
      const inkChanged = before.ink !== null && section.ink !== null && Math.abs(before.ink - section.ink) >= INK_CHANGE_MIN_M;
      if (labelChanged || inkChanged) {
        entry.changes.push({ x_m: section.x_m, from: before.label, to: section.label, inkFrom: before.ink, inkTo: section.ink });
      }
    }
    previous = entry;
  }
  return entries.filter((e) => e.kind === 'not_kept' || e.fit !== null);
}

function fitLine(entry) {
  if (entry.previousFit === null || entry.previousFit === undefined) {
    return el('span', { class: 'change-fit' }, `fit ${entry.fit.toFixed(2)}`);
  }
  const delta = entry.fit - entry.previousFit;
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '±';
  return el('span', { class: 'change-fit' },
    `fit ${entry.previousFit.toFixed(2)} → ${entry.fit.toFixed(2)} `,
    el('span', { class: 'change-delta', dataset: { trend: delta > 0 ? 'up' : delta < 0 ? 'down' : 'same' } },
      `${sign}${Math.abs(delta).toFixed(2)}`));
}

function sectionChange(change) {
  const parts = [];
  if (change.from !== change.to) parts.push(`${fmt.sourceLabel(change.from)} → ${fmt.sourceLabel(change.to)}`);
  if (change.inkFrom !== null && change.inkTo !== null && change.inkFrom !== change.inkTo) {
    parts.push(`off the ink ${fmt.metres(change.inkFrom, 3)} → ${fmt.metres(change.inkTo, 3)}`);
  }
  return el('li', { class: 'change-section' },
    el('span', { class: 'change-x' }, fmt.metres(change.x_m)),
    el('span', {}, parts.join(' · ')));
}

/** The Changes list for the History tab. */
export function renderChanges(entries) {
  if (!entries.length) {
    return el('p', { class: 'panel-empty' }, 'This run has no scored revisions yet.');
  }
  return el('ol', { class: 'change-list' }, ...entries.map((entry) => {
    if (entry.kind === 'not_kept') {
      return el('li', { class: 'change change-not-kept' },
        el('div', { class: 'change-head' },
          el('span', { class: 'change-rev change-rev-x' }, icon('close')),
          el('strong', {}, entry.title)),
        el('p', { class: 'change-cause' }, entry.text));
    }
    return el('li', { class: 'change' },
      el('div', { class: 'change-head' },
        el('span', { class: 'change-rev' }, revisionLabel(entry.id)),
        fitLine(entry)),
      el('p', { class: 'change-cause' }, entry.cause),
      entry.changes.length
        ? el('ul', { class: 'change-sections' }, ...entry.changes.map(sectionChange))
        : null);
  }));
}
