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
  let pass = null; // the open Mark and revise pass, until its result step
  for (const step of steps) {
    // Mark and revise: the person's step opens a pass; its edits and the keep rule's result
    // belong to that one entry (APP_SPEC "Mark and revise", live steps).
    if (step.kind === 'revise' && step.actor === 'person') {
      if (step.title === 'Kept anyway') {
        const last = [...entries].reverse().find((e) => e.kind === 'mark');
        if (last) last.forced = true;
        continue;
      }
      pass = { kind: 'mark', instruction: step.text || '', marks: step.marks || [], area: step.attention_px || null,
        sections: (step.targets || []).filter((t) => t.kind === 'section').map((t) => t.id), why: null, result: null, forced: false };
      entries.push(pass);
      continue;
    }
    if (pass) {
      if (step.actor === 'model' && step.text && !pass.why) pass.why = step.text;
      if (step.mark_revision) {
        pass.result = { ...step.mark_revision, title: step.title, detail: step.tool?.text || '' };
        pass.forced = Boolean(step.mark_revision.operator_forced);
        pass = null;
      }
      if (step.tool?.kept === false) continue; // told in the pass entry
    }
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
  return entries.filter((e) => e.kind === 'not_kept' || e.kind === 'mark' || e.fit !== null);
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
    parts.push(`off the ink ${fmt.millimetres(change.inkFrom)} → ${fmt.millimetres(change.inkTo)}`);
  }
  return el('li', { class: 'change-section' },
    el('span', { class: 'change-x' }, fmt.metres(change.x_m)),
    el('span', {}, parts.join(' · ')));
}

/** Thumbnail box around a mark (sheet pixels): its points, else the area the pass looked at. */
function markBox(entry) {
  const points = entry.marks.flatMap((m) => m.points_px || []);
  if (points.length) {
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  return entry.area;
}

/** Size of a mark thumbnail in CSS pixels, and the space around the mark (part of its size). */
const THUMB = { width: 168, height: 120, pad: 0.35 };

/** A small crop of the drawing page around the person's mark, with the mark in brand blue. */
function markThumbnail(entry, pageUrl) {
  const box = markBox(entry);
  if (!box || !pageUrl) return null;
  const canvas = el('canvas', { class: 'change-thumb', 'aria-hidden': 'true', width: String(THUMB.width * 2), height: String(THUMB.height * 2) });
  pageUrl().then((url) => {
    if (!url) return;
    const image = new Image();
    image.onload = () => {
      const [x0, y0, x1, y1] = box;
      const padX = Math.max(20, (x1 - x0) * THUMB.pad);
      const padY = Math.max(20, (y1 - y0) * THUMB.pad);
      const sx = Math.max(0, x0 - padX);
      const sy = Math.max(0, y0 - padY);
      const sw = Math.min(image.naturalWidth - sx, x1 - x0 + 2 * padX);
      const sh = Math.min(image.naturalHeight - sy, y1 - y0 + 2 * padY);
      const scale = Math.min(canvas.width / sw, canvas.height / sh);
      const g = canvas.getContext('2d');
      g.fillStyle = '#F7F5F0';
      g.fillRect(0, 0, canvas.width, canvas.height);
      g.setTransform(scale, 0, 0, scale, -sx * scale, -sy * scale);
      g.drawImage(image, 0, 0);
      g.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--ink-chosen').trim() || '#06448E';
      g.lineWidth = 2.5 / scale;
      g.setLineDash([6 / scale, 4 / scale]);
      for (const mark of entry.marks) {
        const pts = mark.points_px || [];
        if (mark.shape === 'box' && pts.length === 2) g.strokeRect(pts[0][0], pts[0][1], pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]);
        else if (pts.length > 1) {
          g.beginPath();
          pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
          g.stroke();
        }
      }
    };
    image.src = url;
  }).catch(() => {});
  return canvas;
}

const OUTCOME = {
  kept: { word: 'Kept', tone: 'brand' },
  partly_kept: { word: 'Partly kept', tone: 'brand' },
  not_kept: { word: 'Not kept', tone: 'warn' },
  no_edit: { word: 'No edit', tone: '' },
  stopped: { word: 'Stopped', tone: 'warn' },
};

/** One Mark and revise pass: what the person asked, where, what the AI did and the keep rule's answer. */
function markEntry(entry, pageUrl, placeOf) {
  const result = entry.result;
  const outcome = entry.forced ? { word: 'Kept anyway', tone: 'brand' } : result ? (OUTCOME[result.outcome] || { word: result.outcome, tone: '' }) : { word: 'Working', tone: 'ai' };
  let fitText = null;
  if (result?.fit_change) fitText = `fit ${result.fit_change > 0 ? '+' : '−'}${Math.abs(result.fit_change).toFixed(3)}`;
  else if (result?.not_kept_fit_change) fitText = `would have been ${result.not_kept_fit_change > 0 ? '+' : '−'}${Math.abs(result.not_kept_fit_change).toFixed(3)}`;
  return el('li', { class: 'change change-mark', dataset: { outcome: result?.outcome || 'working' } },
    markThumbnail(entry, pageUrl),
    el('div', { class: 'change-mark-body' },
      el('div', { class: 'change-head' },
        el('span', { class: 'change-who' }, 'You marked'),
        el('span', { class: 'badge badge-small', dataset: { tone: outcome.tone } }, el('span', { class: 'badge-text' }, outcome.word)),
        fitText ? el('span', { class: 'change-fit' }, fitText) : null),
      el('blockquote', { class: 'change-instruction' }, `“${entry.instruction}”`),
      entry.sections.length ? el('p', { class: 'change-cause' }, `${entry.sections.length === 1 ? 'Section' : 'Sections'} at ${entry.sections.map(placeOf).join(', ')}`) : null,
      entry.why ? el('p', { class: 'change-why' }, el('strong', {}, 'The AI: '), entry.why) : null,
      result?.detail && result.outcome !== 'kept' ? el('p', { class: 'change-cause' }, `Why: ${result.detail}`) : null));
}

/** The Changes list for the History tab. `pageUrl()` gives the drawing page image for mark thumbnails. */
export function renderChanges(entries, { pageUrl = null, placeOf = (id) => id } = {}) {
  if (!entries.length) {
    return el('p', { class: 'panel-empty' }, 'This run has no scored revisions yet.');
  }
  return el('ol', { class: 'change-list' }, ...entries.map((entry) => {
    if (entry.kind === 'mark') return markEntry(entry, pageUrl, placeOf);
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
