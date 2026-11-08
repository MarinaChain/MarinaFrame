// Live run (milestone M3, stage L1): watch the agent think while the ship takes shape.
//
// Steps come from `get_live_steps` (docs/APP_SPEC.md, "Live steps"); the design is
// docs/design/2026-11-08-b-live-agent.md sections 2 to 7. One cursor (the step shown)
// drives four views at once:
//   - the drawing's attention layer: what the agent looked at, listed, clicked or claimed;
//   - the narration strip: the current step in one line, with a working dot;
//   - the Thinking tab: one card per step, up to the cursor;
//   - the 3D view: the section curves of the newest build up to the cursor, and a fit dial.
// A running run polls for new steps and follows them with a minimum dwell per step. A finished
// run opens at its end state and replays with a scrub bar and a speed choice.

import { el, svg, fill, icon, prefersReducedMotion } from './dom.js';
import { readArtifactAsDataUrl } from './api.js';
import * as fmt from './format.js';

/** Poll interval while a run is active (task-changed events also poll at once). */
const POLL_MS = 1000;
/** A step stays on screen at least this long when following a live run (design 7). */
const MIN_DWELL_MS = 1200;
/** In replay at 1x, a silence between steps is capped at this (design 7). */
const SILENCE_CAP_MS = 1500;
/** Below this delay per step, steps change without animation. */
const ANIMATE_MIN_MS = 250;
/** When a live run is more steps than this ahead of the cursor, jump instead of animating. */
const MAX_LAG_STEPS = 2;
/** The Thinking panel follows the newest card while it is this close to the bottom. */
const NEAR_BOTTOM_PX = 48;
/** Refusal notes on the sheet are cut to this many characters; the full text is the tooltip. */
const NOTE_MAX_CHARS = 56;
/** The drawing camera's move takes 260 ms (drawing.js); notes are placed after it. */
const CAMERA_SETTLE_MS = 320;
/** Space kept between a note and the right edge of the drawing pane, in screen pixels. */
const NOTE_EDGE_PX = 8;
/** Fit dial count-up, and how long the change stays visible. */
const DIAL_COUNT_MS = 600;
const DIAL_DELTA_MS = 2400;
/** The drawing camera never zooms closer than this share of the page's larger side. */
const MIN_CAMERA_FRACTION = 0.4;

const SPEEDS = [
  { id: 'live', label: 'Live', title: 'Real timing' },
  { id: '1', label: '1×', title: 'Silences shortened to 1.5 s' },
  { id: '4', label: '4×', title: 'Four times faster' },
  { id: '16', label: '16×', title: 'Sixteen times faster' },
];

/** Step kinds the AI did (teal), the code did (neutral) or that need a person's eye (amber). */
const AI_KINDS = new Set(['look', 'read', 'strokes', 'trace', 'corridor', 'assign', 'propose_section', 'views', 'vessel']);
const BUILD_KINDS = new Set(['build', 'render', 'score', 'survey']);

/** Tick and dot category of a step, for the scrub bar and the Thinking cards. */
function stepCategory(step) {
  if (step.kind === 'refused' || step.tool?.kept === false || step.tool?.state === 'refused') return 'refused';
  if (step.kind === 'repeat_collapsed' || step.kind === 'system') return 'quiet';
  if (step.kind === 'finish') return 'finish';
  if (step.actor === 'person') return 'person';
  if (AI_KINDS.has(step.kind) || (step.actor === 'model' && !BUILD_KINDS.has(step.kind))) return 'ai';
  return 'build';
}

/** "1:05" from milliseconds. */
function clockDuration(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}

/** "240 ms", "1.0 s", "2 min 28 s". */
function toolDuration(ms) {
  if (ms === null || ms === undefined) return null;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

/** "r0003" -> "r3"; other ids stay. */
function revisionLabel(id) {
  const match = /^r0*(\d+)$/.exec(id || '');
  return match ? `r${match[1]}` : id || 'build';
}

function truncate(text, max) {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** The step's box on the page: its attention box, else the bounds of its marks. */
function boxOfMarks(marks) {
  const points = marks.flatMap((m) => m.points_px);
  if (!points.length) return null;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

export function createLiveRun({ invoke, drawing, model, nodes, isRunning, onStepsChanged, cardActions = () => null }) {
  const layer = drawing.attentionLayer;

  let task = null;
  let token = 0;
  let steps = [];
  let lastSequence = 0;
  let finished = true;
  let elapsedMs = 0;
  let inFlight = null;
  let fetchedAt = 0;
  let pollTimer = 0;
  let polling = false;

  let cursor = -1;
  let playing = false;
  let playTimer = 0;
  let followLive = true;
  let speed = 'live';
  // Replay controls are hidden while the agent works live; a finished run offers
  // "Watch again", which opens them (founder, 2026-11-09: the point is to watch it live).
  let replayOpen = false;
  let cameraFollow = true;
  let thinkingFollow = true;
  let pinnedRevision = null;

  /** revision key -> Promise of SectionCurve[] with points. */
  const hullCache = new Map();
  /** revision key the 3D view shows, and its request token. */
  let shownRevision = null;
  let revisionToken = 0;
  /** sequence -> { last_sequence, node } for the Thinking cards. */
  const cards = new Map();
  let dialValue = null;
  let dialFrame = 0;
  let dialDeltaTimer = 0;
  let clockTimer = 0;

  // ---------------------------------------------------------------- data

  const hasSteps = () => steps.length > 0;
  const bySequence = (sequence) => steps.find((s) => s.sequence === sequence) || null;
  const current = () => (cursor >= 0 ? steps[cursor] : null);

  /** The step whose marks and attention a step shows: a repeat shows the step it repeats. */
  function sourceOf(step) {
    if (step?.kind === 'repeat_collapsed' && step.repeat_of !== null) return bySequence(step.repeat_of) || step;
    return step;
  }

  function stepTitle(step) {
    if (step.kind === 'repeat_collapsed') {
      const original = bySequence(step.repeat_of);
      const base = original ? original.title : step.title.replace(/\s*\(\d+ times\)$/, '');
      return `${base} again, ${step.count} times`;
    }
    return step.title;
  }

  function reset(nextTask) {
    replayOpen = false;
    token += 1;
    task = nextTask;
    steps = [];
    lastSequence = 0;
    finished = true;
    elapsedMs = 0;
    inFlight = null;
    cursor = -1;
    followLive = true;
    thinkingFollow = true;
    pinnedRevision = null;
    shownRevision = null;
    dialValue = null;
    hullCache.clear();
    cards.clear();
    stopPlaying();
    stopPolling();
    clearInterval(clockTimer);
    clockTimer = 0;
  }

  /** Merge a LiveSteps answer: steps are replaced by sequence (APP_SPEC "Live steps"). */
  function merge(answer) {
    let changedShown = false;
    for (const step of answer.steps) {
      const at = steps.findIndex((s) => s.sequence === step.sequence);
      if (at >= 0) {
        steps[at] = step;
        if (at <= cursor) changedShown = true;
      } else {
        steps.push(step);
      }
    }
    steps.sort((a, b) => a.sequence - b.sequence);
    lastSequence = Math.max(lastSequence, answer.last_sequence);
    finished = answer.finished;
    elapsedMs = answer.elapsed_ms;
    inFlight = answer.in_flight;
    fetchedAt = Date.now();
    return changedShown;
  }

  async function fetchSteps() {
    if (!task || polling) return;
    polling = true;
    const asked = token;
    try {
      const answer = await invoke('get_live_steps', { task, after_sequence: lastSequence });
      if (asked !== token) return;
      const first = !hasSteps();
      const changedShown = merge(answer);
      if (first && hasSteps()) openAtEnd();
      else if (!first) afterUpdate(changedShown);
      if (finished) stopPolling();
      else startPolling();
      onStepsChanged();
    } catch (error) {
      // An older backend without live steps, or a run folder that is gone: stay quiet,
      // the M1 views still show the run.
      if (error?.code !== 'unknown_command') console.warn('get_live_steps', error);
    } finally {
      polling = false;
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(fetchSteps, POLL_MS);
    if (!clockTimer) clockTimer = setInterval(renderNarration, 1000);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = 0;
  }

  // ---------------------------------------------------------------- cursor and playback

  /** A finished run opens at its end; a running run at its newest step, following it. */
  function openAtEnd() {
    cursor = steps.length - 1;
    followLive = true;
    showCursor({ animate: false, moveCamera: false });
  }

  function afterUpdate(changedShown) {
    if (followLive && !playing && cursor < steps.length - 1) {
      catchUp();
      return;
    }
    if (changedShown) showCursor({ animate: false, moveCamera: false });
    else renderControls();
  }

  /** Follow a live run: one step per dwell; jump when far behind (design 7). */
  function catchUp() {
    clearTimeout(playTimer);
    if (!followLive || cursor >= steps.length - 1) return;
    if (steps.length - 1 - cursor > MAX_LAG_STEPS) {
      cursor = steps.length - 2;
      showCursor({ animate: false });
    }
    playTimer = setTimeout(() => {
      cursor += 1;
      showCursor({ animate: true });
      catchUp();
    }, cursor < 0 ? 0 : MIN_DWELL_MS);
  }

  function delayAfter(index) {
    const here = steps[index];
    const next = steps[index + 1];
    if (!here || !next) return MIN_DWELL_MS;
    const gap = Math.max(0, next.time_ms - here.time_ms);
    if (speed === 'live') return Math.max(MIN_DWELL_MS, gap);
    const capped = Math.max(MIN_DWELL_MS, Math.min(gap, SILENCE_CAP_MS));
    return capped / Number(speed);
  }

  function play() {
    if (!hasSteps()) return;
    if (cursor >= steps.length - 1) {
      if (!finished) {
        followLive = true;
        return;
      }
      // Replay from the start: the empty sheet, then step by step.
      cursor = -1;
      showCursor({ animate: false });
    }
    playing = true;
    followLive = false;
    scheduleNext(cursor < 0 ? 300 : delayAfter(cursor));
    renderControls();
  }

  function scheduleNext(delay) {
    clearTimeout(playTimer);
    playTimer = setTimeout(() => {
      if (!playing) return;
      if (cursor >= steps.length - 1) {
        stopPlaying();
        if (!finished) {
          followLive = true;
          catchUp();
        }
        renderControls();
        return;
      }
      cursor += 1;
      const next = delayAfter(cursor);
      showCursor({ animate: delay >= ANIMATE_MIN_MS || next >= ANIMATE_MIN_MS });
      scheduleNext(next);
    }, delay);
  }

  function stopPlaying() {
    playing = false;
    clearTimeout(playTimer);
    playTimer = 0;
  }

  function seek(index, { animate = false } = {}) {
    stopPlaying();
    cursor = Math.max(-1, Math.min(steps.length - 1, index));
    followLive = !finished && cursor === steps.length - 1;
    showCursor({ animate });
  }

  /** Show the state at the cursor everywhere. */
  function showCursor({ animate = false, moveCamera = true } = {}) {
    const motion = animate && !prefersReducedMotion();
    renderMarks(motion);
    if (moveCamera) followCamera(motion);
    renderNarration();
    renderThinking();
    renderControls();
    render3d(motion);
  }

  // ---------------------------------------------------------------- drawing: attention layer

  function screenGroup(x, y, className = '') {
    return svg('g', { class: `mk-screen ${className}`.trim(), style: { transform: `translate(${x}px, ${y}px) scale(var(--u, 1))` } });
  }

  /** A pinned note in screen pixels; its box is sized once the text is on the page. */
  function note(x, y, text, tone, sizing) {
    const group = screenGroup(x, y, `mk-note tone-${tone}`);
    const label = svg('text', { x: 14, y: -10 }, truncate(text, NOTE_MAX_CHARS));
    const box = svg('rect', { x: 8, y: -24, rx: 4, height: 20, width: 40 });
    group.append(svg('title', {}, text), box, label);
    sizing.push(() => {
      box.setAttribute('width', String(label.getComputedTextLength() + 12));
      // Measure where the note lands once the camera has finished its move.
      setTimeout(() => keepInside(group, [box, label]), CAMERA_SETTLE_MS);
    });
    return group;
  }

  /**
   * Move a note's parts left when the note would run past the right edge of the drawing
   * pane. Children of a screen group are in screen pixels, so the shift is too.
   */
  function keepInside(group, parts) {
    const pane = layer.ownerSVGElement?.getBoundingClientRect();
    if (!pane) return;
    const overflow = group.getBoundingClientRect().right - (pane.right - NOTE_EDGE_PX);
    if (overflow <= 0) return;
    for (const part of parts) part.setAttribute('x', String(Number(part.getAttribute('x')) - overflow));
  }

  function topPoint(points) {
    return points.reduce((best, p) => (p[1] < best[1] ? p : best), points[0]);
  }

  function polyPoints(points) {
    return points.map(([x, y]) => `${x},${y}`).join(' ');
  }

  /** Draw one mark. `now` marks get labels, tags and entry motion; past marks are faint. */
  function drawMark(mark, target, { now, index, step, sizing }) {
    const tone = mark.tone;
    const notKept = tone === 'authored' && step?.tool?.kept === false;
    const toneClass = notKept ? 'refused' : tone;
    const style = { '--i': index };
    const points = mark.points_px;

    if (mark.shape === 'box') {
      const [[x0, y0], [x1, y1]] = points;
      const rect = { x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0) };
      if (tone === 'attention' && now) target.append(svg('rect', { ...rect, class: 'mk mk-halo', rx: 6 }));
      target.append(svg('rect', { ...rect, class: `mk mk-box tone-${toneClass}`, rx: tone === 'attention' ? 6 : 2, style }));
      if (now && mark.label) {
        const group = screenGroup(rect.x, rect.y, `mk-tag tone-${toneClass}`);
        const text = svg('text', { x: 6, y: -6 }, mark.label);
        group.append(text);
        target.append(group);
      }
      return;
    }

    if (mark.shape === 'band') {
      target.append(svg('polyline', {
        points: polyPoints(points),
        class: `mk-band tone-${toneClass}`,
        'stroke-width': String(2 * (mark.half_width_px || 6)),
      }));
      if (now && mark.label) target.append(note(points[0][0], points[0][1], mark.label, toneClass, sizing));
      return;
    }

    if (mark.shape === 'point') {
      const [x, y] = points[0];
      const group = screenGroup(x, y, `mk-click tone-${toneClass}`);
      if (now) group.append(svg('circle', { class: 'mk-ripple', r: 6 }), svg('circle', { class: 'mk-ripple mk-ripple-2', r: 6 }));
      group.append(svg('circle', { class: 'mk-dot', r: now ? 4.5 : 3 }));
      target.append(group);
      if (now && mark.label) target.append(note(x, y, mark.label, toneClass, sizing));
      return;
    }

    // Polylines: listed strokes, accepted lines, model-drawn sections.
    target.append(svg('polyline', {
      points: polyPoints(points),
      class: `mk mk-line tone-${toneClass}`,
      pathLength: '1',
      style,
    }));
    if (!now) return;
    const [tx, ty] = topPoint(points);
    if (mark.tag !== undefined && mark.tag !== null) {
      const tag = screenGroup(tx, ty, `mk-stroke-tag tone-${toneClass}`);
      tag.style.setProperty('--i', String(index));
      tag.append(svg('circle', { r: 9 }), svg('text', { y: 4 }, String(mark.tag)));
      target.append(tag);
    } else if (notKept) {
      target.append(note(tx, ty, step.tool.text, 'refused', sizing));
    } else if (mark.label) {
      // A chosen line snaps a station pin to its top end.
      const pin = screenGroup(tx, ty, `mk-pin tone-${toneClass}`);
      const label = svg('text', { x: 12, y: -12 }, mark.label);
      const box = svg('rect', { x: 6, y: -26, rx: 4, height: 20, width: 40 });
      pin.append(svg('line', { x1: 0, y1: 0, x2: 8, y2: -8 }), svg('circle', { r: 4 }), box, label);
      sizing.push(() => box.setAttribute('width', String(label.getComputedTextLength() + 12)));
      target.append(pin);
    }
  }

  function renderMarks(animate) {
    layer.replaceChildren();
    if (cursor < 0) return;
    const past = svg('g', { class: 'live-past' });
    const now = svg('g', { class: animate ? 'live-now live-enter' : 'live-now' });
    const sizing = [];
    const drawn = new Set();
    // Marks stay after the camera leaves, so the sheet becomes a map of everything looked at.
    for (let i = 0; i < cursor; i += 1) {
      for (const mark of steps[i].marks) {
        const key = `${mark.shape}|${mark.tone}|${JSON.stringify(mark.points_px)}`;
        if (drawn.has(key)) continue;
        drawn.add(key);
        drawMark(mark, past, { now: false, index: 0, step: steps[i], sizing });
      }
    }
    const step = current();
    const source = sourceOf(step);
    source.marks.forEach((mark, index) => drawMark(mark, now, { now: true, index, step: source, sizing }));
    // Look and read steps without a box of their own get the attention ring on their crop.
    if (!source.marks.some((m) => m.tone === 'attention') && ['look', 'read'].includes(source.kind) && source.attention_px) {
      const [l, t, r, b] = source.attention_px;
      now.prepend(svg('rect', { x: l, y: t, width: r - l, height: b - t, rx: 6, class: 'mk mk-box tone-attention' }));
    }
    if (step.kind === 'repeat_collapsed') {
      const box = source.attention_px || boxOfMarks(source.marks);
      if (box) {
        const badge = screenGroup(box[2], box[1], 'mk-repeat');
        const text = svg('text', { x: -8, y: 16 }, `×${step.count}`);
        badge.append(svg('rect', { x: -38, y: 2, rx: 9, width: 34, height: 19 }), text);
        now.append(badge);
      }
    }
    layer.append(past, now);
    for (const size of sizing) size();
  }

  function followCamera(animate) {
    if (!cameraFollow || cursor < 0) return;
    const source = sourceOf(current());
    const box = source.attention_px || boxOfMarks(source.marks);
    if (box) drawing.fitBox(atLeast(box, drawing.page), { animate });
  }

  /**
   * Grow a camera box around its centre to a minimum share of the page, so a click's small
   * box still shows the panel around it and its pinned note.
   */
  function atLeast([l, t, r, b], page) {
    if (!page) return [l, t, r, b];
    const minimum = Math.max(page.width, page.height) * MIN_CAMERA_FRACTION;
    const cx = (l + r) / 2;
    const cy = (t + b) / 2;
    const halfW = Math.max(r - l, minimum) / 2;
    const halfH = Math.max(b - t, minimum) / 2;
    return [cx - halfW, cy - halfH, cx + halfW, cy + halfH];
  }

  // ---------------------------------------------------------------- 3D

  function revisionKey(revision) {
    return revision.path || revision.id;
  }

  /** The build the 3D view shows at the cursor: the newest build step up to it. */
  function buildAtCursor() {
    for (let i = cursor; i >= 0; i -= 1) {
      const revision = steps[i].revision;
      if (revision && (revision.id || revision.path)) return revision;
    }
    return null;
  }

  /** Fit of the newest scored build up to the cursor. */
  function fitAtCursor() {
    for (let i = cursor; i >= 0; i -= 1) {
      const fit = steps[i].revision?.fit;
      if (fit !== null && fit !== undefined) return fit;
    }
    return null;
  }

  function sectionsOf(revision) {
    const key = revisionKey(revision);
    if (!hullCache.has(key)) {
      const carried = revision.sections.length && revision.sections.every((s) => s.points_yz_m.length > 1);
      hullCache.set(key, carried
        ? Promise.resolve(revision.sections)
        : invoke('get_hull_sections', { task, revision: revision.path || revision.id }).then((h) => h.sections));
    }
    return hullCache.get(key);
  }

  async function render3d(animate) {
    renderDial(animate);
    model.setReviewOverlays(cursor === steps.length - 1);
    const step = current();
    model.setFocusSections(step?.actor === 'model' ? sourceOf(step).targets.filter((t) => t.kind === 'section').map((t) => t.id) : []);
    const pinned = pinnedRevision ? revisions().find((r) => r.key === pinnedRevision) : null;
    const revision = pinned ? pinned.revision : buildAtCursor();
    renderCaption(revision);
    const key = revision ? revisionKey(revision) : null;
    if (key === shownRevision) return;
    const asked = ++revisionToken;
    const previous = shownRevision;
    shownRevision = key;
    if (!revision) {
      model.showSections([], { hideSkin: true });
      return;
    }
    try {
      const sections = await sectionsOf(revision);
      if (asked !== revisionToken) return;
      const mode = !animate ? 'instant' : previous ? 'update' : 'grow';
      model.showSections(sections, { mode });
    } catch (error) {
      hullCache.delete(key);
      if (asked === revisionToken) shownRevision = previous;
      console.warn('get_hull_sections', error);
    }
  }

  function renderCaption(revision) {
    const caption = nodes.caption;
    let text = '';
    if (hasSteps() && !revision) {
      text = !finished && inFlight?.kind === 'worker' ? 'Building the first hull' : 'No hull yet';
    } else if (pinnedRevision && revision) {
      text = `Showing ${revisionLabel(revision.id)} · click it again to follow the run`;
    } else if (revision && steps.find((s) => s.revision && revisionKey(s.revision) === revisionKey(revision))?.actor === 'code') {
      text = 'First hull from the traced lines';
    }
    caption.textContent = text;
    caption.hidden = !text;
  }

  function renderDial(animate) {
    const dial = nodes.dial;
    const fit = hasSteps() ? fitAtCursor() : null;
    dial.hidden = fit === null;
    if (fit === null) {
      dialValue = null;
      return;
    }
    const from = dialValue;
    dialValue = fit;
    const delta = from === null ? 0 : fit - from;
    const ring = dial.querySelector('.dial-arc');
    const value = dial.querySelector('.dial-value');
    const change = dial.querySelector('.dial-delta');
    dial.title = `Fit ${fit.toFixed(4)}: how closely the model's cuts follow the ink (1 is a perfect match).`;
    const draw = (v) => {
      ring.style.strokeDashoffset = String(1 - Math.max(0, Math.min(1, v)));
      value.textContent = v.toFixed(2);
    };
    cancelAnimationFrame(dialFrame);
    if (!animate || from === null || Math.abs(delta) < 1e-6) {
      draw(fit);
    } else {
      const began = performance.now();
      const step = (now) => {
        const t = Math.min(1, (now - began) / DIAL_COUNT_MS);
        draw(from + delta * (1 - (1 - t) ** 3));
        if (t < 1) dialFrame = requestAnimationFrame(step);
      };
      dialFrame = requestAnimationFrame(step);
    }
    if (animate && Math.abs(delta) >= 0.005) {
      change.textContent = `${delta > 0 ? '+' : '−'}${Math.abs(delta).toFixed(2)}`;
      change.dataset.tone = delta > 0 ? 'better' : 'worse';
      dial.dataset.flash = delta > 0 ? 'better' : 'worse';
      clearTimeout(dialDeltaTimer);
      dialDeltaTimer = setTimeout(() => {
        change.textContent = '';
        delete dial.dataset.flash;
      }, DIAL_DELTA_MS);
    } else if (!animate) {
      change.textContent = '';
      delete dial.dataset.flash;
    }
  }

  // ---------------------------------------------------------------- narration

  function renderNarration() {
    const strip = nodes.narration;
    const step = current();
    if (!step) {
      strip.dataset.live = 'false';
      fill(strip, el('span', { class: 'narration-dot', 'aria-hidden': 'true' }),
        el('span', { class: 'narration-text narration-empty' }, hasSteps() ? 'Press play to replay the run from the start.' : ''));
      return;
    }
    const atEnd = cursor === steps.length - 1;
    const working = (atEnd && !finished && inFlight) || playing;
    strip.dataset.live = String(Boolean(working));
    strip.dataset.category = stepCategory(step);
    const source = sourceOf(step);
    const quote = source.actor === 'model' && source.text ? source.text : null;
    let time;
    if (atEnd && !finished && inFlight) {
      const now = elapsedMs + (Date.now() - fetchedAt);
      const what = inFlight.kind === 'model' ? 'Thinking' : (inFlight.operation || '').includes('hull') ? 'Building the hull' : 'Working';
      time = `${what} ${clockDuration(now - inFlight.since_ms)}`;
    } else {
      time = `${clockDuration(step.time_ms)} / ${clockDuration(finished ? elapsedMs : elapsedMs + (Date.now() - fetchedAt))}`;
    }
    fill(strip,
      el('span', { class: 'narration-dot', 'aria-hidden': 'true', title: working ? 'Working' : null }),
      el('span', { class: 'narration-text', title: quote ? `${stepTitle(step)}. “${quote}”` : stepTitle(step) },
        el('span', { class: 'narration-title' }, stepTitle(step)),
        quote ? el('span', { class: 'narration-quote' }, `“${quote}”`) : null),
      el('span', { class: 'narration-time' }, time));
  }

  // ---------------------------------------------------------------- Thinking tab

  function targetChips(step) {
    return step.targets.filter((t) => t.kind === 'section').map((t) => el('span', { class: 'target-chip' }, t.id));
  }

  function resultTone(tool) {
    if (tool.kept === false || tool.state === 'refused' || tool.state === 'failed') return 'refused';
    if (tool.state === 'working') return 'working';
    if (tool.kept === true) return 'kept';
    return 'ok';
  }

  function toolCard(step) {
    const tool = step.tool;
    if (!tool) return null;
    const tone = resultTone(tool);
    return el('div', { class: 'tool-card', dataset: { tone } },
      el('div', { class: 'tool-head' },
        el('code', { class: 'tool-name' }, tool.tool),
        ...targetChips(step),
        tool.duration_ms !== null ? el('span', { class: 'tool-duration' }, toolDuration(tool.duration_ms)) : null),
      el('p', { class: 'tool-result' }, tone === 'working' ? 'Working…' : tool.text));
  }

  function imagesBlock(step) {
    if (!step.images?.length) return null;
    const grid = el('div', { class: 'thought-images' });
    const details = el('details', { class: 'thought-more' },
      el('summary', {}, icon('chevron'), 'What it saw'), grid);
    details.addEventListener('toggle', () => {
      if (!details.open || grid.childElementCount) return;
      for (const path of step.images) {
        const img = el('img', { alt: `Image the model saw: ${path.split('/').pop()}`, loading: 'lazy' });
        grid.append(img);
        readArtifactAsDataUrl(task, path).then((url) => { img.src = url; }).catch(() => img.remove());
      }
    }, { once: false });
    return details;
  }

  function buildCard(step, index) {
    const category = stepCategory(step);
    const seekHere = () => seek(index);
    const quiet = (step.actor === 'code' && step.kind !== 'revise') || step.kind === 'repeat_collapsed' || step.kind === 'system';
    if (quiet) {
      return el('li', { class: 'thought thought-quiet', dataset: { category, sequence: String(step.sequence) } },
        el('span', { class: 'thought-dot', 'aria-hidden': 'true' }),
        el('button', { class: 'thought-line', type: 'button', onclick: seekHere, title: step.text },
          el('span', { class: 'thought-line-title' }, stepTitle(step)),
          step.tool?.text && step.kind !== 'repeat_collapsed' ? el('span', { class: 'thought-line-result' }, step.tool.text) : null,
          el('time', { class: 'thought-time' }, clockDuration(step.time_ms))));
    }
    const previousNotes = steps.slice(0, index).reverse().find((s) => s.notes)?.notes || null;
    const notes = step.notes && step.notes !== previousNotes ? step.notes : null;
    return el('li', { class: 'thought', dataset: { category, sequence: String(step.sequence) } },
      el('span', { class: 'thought-dot', 'aria-hidden': 'true' }),
      el('article', { class: 'thought-card' },
        el('header', { class: 'thought-head' },
          el('button', { class: 'thought-title', type: 'button', onclick: seekHere, title: 'Show this step' },
            step.actor === 'person' ? el('span', { class: 'thought-who' }, 'You') : null, stepTitle(step)),
          el('span', { class: 'thought-meta' },
            el('time', {}, clockDuration(step.time_ms)),
            step.cost_usd ? el('span', { title: 'List cost of this model answer' }, fmt.usd(step.cost_usd)) : null)),
        step.text ? el('blockquote', { class: 'thought-quote selectable-text' }, `“${step.text}”`) : null,
        toolCard(step),
        notes ? el('details', { class: 'thought-more' },
          el('summary', {}, icon('chevron'), 'Why'),
          el('p', { class: 'thought-notes selectable-text' }, notes)) : null,
        imagesBlock(step),
        // Mark and revise: "Keep anyway" on a result the keep rule did not keep (mark.js).
        cardActions(step)));
  }

  function cardFor(step, index) {
    const cached = cards.get(step.sequence);
    if (cached && cached.last === step.last_sequence) return cached.node;
    const node = buildCard(step, index);
    cached?.node.replaceWith(node);
    cards.set(step.sequence, { last: step.last_sequence, node });
    return node;
  }

  function renderThinking() {
    const panel = nodes.thinking;
    if (!hasSteps()) return;
    let list = panel.querySelector('.thinking-live');
    if (!list) {
      list = el('ol', { class: 'thinking thinking-live', 'aria-label': 'What the AI did, oldest first' });
      const jump = el('button', { class: 'badge thinking-jump', type: 'button', hidden: true, onclick: () => {
        thinkingFollow = true;
        jump.hidden = true;
        scrollThinking();
      } }, el('span', { class: 'badge-text' }, 'Live ↓'));
      fill(panel, list, jump);
      panel.onscroll = () => {
        if (panel.dataset.autoScroll === 'true') return;
        const nearBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight < NEAR_BOTTOM_PX;
        thinkingFollow = nearBottom;
        jump.hidden = nearBottom;
      };
    }
    while (list.children.length > steps.length) list.lastChild.remove();
    steps.forEach((step, index) => {
      const node = cardFor(step, index);
      if (node.parentNode !== list || list.children[index] !== node) list.insertBefore(node, list.children[index] || null);
      node.hidden = index > cursor;
      node.classList.toggle('is-current', index === cursor);
    });
    if (thinkingFollow) scrollThinking();
  }

  function scrollThinking() {
    const panel = nodes.thinking;
    const node = current() ? cards.get(current().sequence)?.node : null;
    if (!node || panel.hidden) return;
    panel.dataset.autoScroll = 'true';
    const target = node.offsetTop + node.offsetHeight - panel.clientHeight + 16;
    panel.scrollTop = Math.max(0, target);
    requestAnimationFrame(() => { panel.dataset.autoScroll = 'false'; });
  }

  // ---------------------------------------------------------------- revision ladder and transport

  /** Builds and not-kept attempts up to the cursor, in order, with their newest fit. */
  function revisions() {
    const rungs = [];
    for (let i = 0; i <= cursor; i += 1) {
      const step = steps[i];
      if (step.tool?.kept === false) {
        rungs.push({ key: `rejected-${step.sequence}`, rejected: true, step, index: i });
        continue;
      }
      const revision = step.revision;
      if (!revision || !(revision.id || revision.path)) continue;
      const key = revisionKey(revision);
      let rung = rungs.find((r) => r.key === key);
      if (!rung) {
        rung = { key, rejected: false, revision, fit: null, index: i };
        rungs.push(rung);
      }
      if (revision.sections.some((s) => s.points_yz_m.length > 1)) rung.revision = revision;
      if (revision.fit !== null && revision.fit !== undefined) rung.fit = revision.fit;
    }
    return rungs;
  }

  function sparkline(fits) {
    const width = 72;
    const height = 20;
    if (fits.length < 2) return null;
    const lo = Math.min(...fits);
    const hi = Math.max(...fits);
    const span = hi - lo || 1;
    const pts = fits.map((f, i) => [2 + (i * (width - 4)) / (fits.length - 1), height - 3 - ((f - lo) / span) * (height - 6)]);
    const last = pts[pts.length - 1];
    return svg('svg', { class: 'rev-spark', viewBox: `0 0 ${width} ${height}`, width, height, 'aria-hidden': 'true' },
      svg('polyline', { points: polyPoints(pts) }),
      svg('circle', { cx: last[0], cy: last[1], r: 2.2 }));
  }

  function renderLadder() {
    const ladder = nodes.ladder;
    const rungs = revisions();
    if (!rungs.length) {
      fill(ladder, el('span', { class: 'rev-empty' }, hasSteps() && cursor >= 0 ? 'No build yet' : 'No revision yet'));
      return;
    }
    const shown = pinnedRevision || (buildAtCursor() ? revisionKey(buildAtCursor()) : null);
    const items = [];
    rungs.forEach((rung, i) => {
      if (i) items.push(el('span', { class: 'rev-sep', 'aria-hidden': 'true' }, '›'));
      if (rung.rejected) {
        items.push(el('span', { class: 'rev-step rev-rejected', title: `${rung.step.title}. ${rung.step.tool.text}` },
          el('span', { 'aria-hidden': 'true' }, '✕'), el('span', { class: 'visually-hidden' }, 'Not kept')));
        return;
      }
      const label = revisionLabel(rung.revision.id);
      const isShown = rung.key === shown;
      items.push(el('button', {
        class: `rev-step rev-rung${isShown ? ' rev-current' : ''}${rung.key === pinnedRevision ? ' rev-pinned' : ''}`,
        type: 'button',
        'aria-pressed': String(rung.key === pinnedRevision),
        title: rung.key === pinnedRevision
          ? `Showing ${label} in 3D. Click to follow the run again.`
          : `Show ${label} in 3D${rung.fit !== null ? `, fit ${rung.fit.toFixed(4)}` : ''}. The run keeps going.`,
        onclick: () => {
          pinnedRevision = pinnedRevision === rung.key ? null : rung.key;
          renderLadder();
          render3d(true);
        },
      }, label, rung.fit !== null ? el('span', { class: 'rev-fit' }, rung.fit.toFixed(2)) : null));
    });
    fill(ladder, ...items, sparkline(rungs.filter((r) => !r.rejected && r.fit !== null).map((r) => r.fit)));
    // Keep the newest rung in view when the ladder is wider than its place.
    ladder.scrollLeft = ladder.scrollWidth;
  }

  function renderTransport() {
    const transport = nodes.transport;
    transportParts.watchAgain.hidden = !(hasSteps() && finished && !replayOpen);
    transport.hidden = !(hasSteps() && finished && replayOpen);
    if (transport.hidden) return;
    const { play: playButton, scrub, ticks, speeds } = transportParts;
    const atLiveEdge = !finished && followLive && cursor === steps.length - 1;
    playButton.dataset.state = playing ? 'playing' : 'paused';
    fill(playButton, icon(playing ? 'pause' : 'play'));
    playButton.title = playing ? 'Pause the replay (Space)' : cursor >= steps.length - 1 && finished ? 'Replay from the start (Space)' : 'Play (Space)';
    playButton.setAttribute('aria-label', playButton.title);
    scrub.max = String(Math.max(0, steps.length - 1));
    scrub.value = String(Math.max(0, cursor));
    scrub.setAttribute('aria-valuetext', current() ? `Step ${cursor + 1} of ${steps.length}: ${stepTitle(current())}` : 'Start');
    if (ticks.childElementCount !== steps.length || ticks.dataset.last !== String(lastSequence)) {
      ticks.dataset.last = String(lastSequence);
      fill(ticks, ...steps.map((step, i) => el('span', {
        class: 'scrub-tick',
        dataset: { category: stepCategory(step) },
        style: { left: `${steps.length > 1 ? (i / (steps.length - 1)) * 100 : 0}%` },
      })));
    }
    for (const button of speeds.querySelectorAll('button')) {
      button.setAttribute('aria-checked', String(button.dataset.speed === speed));
    }
    transportParts.live.hidden = finished;
    transportParts.live.setAttribute('aria-pressed', String(atLiveEdge));
  }

  function renderControls() {
    renderLadder();
    renderTransport();
    renderFollow();
  }

  function renderFollow() {
    const button = nodes.follow;
    button.hidden = !hasSteps();
    button.setAttribute('aria-pressed', String(cameraFollow));
    button.title = cameraFollow
      ? 'The view follows what the AI looks at. Pan or zoom to stop.'
      : 'Follow what the AI looks at';
  }

  // ---------------------------------------------------------------- controls

  const transportParts = (() => {
    const playButton = el('button', { class: 'btn btn-ghost btn-icon live-play', type: 'button' });
    playButton.addEventListener('click', () => (playing ? (stopPlaying(), renderControls(), renderNarration()) : play()));
    const scrub = el('input', { class: 'scrub-input', type: 'range', min: '0', max: '0', step: '1', value: '0', 'aria-label': 'Replay position' });
    scrub.addEventListener('input', () => seek(Number(scrub.value)));
    const ticks = el('div', { class: 'scrub-ticks', 'aria-hidden': 'true' });
    const speeds = el('div', { class: 'segmented segmented-speed', role: 'radiogroup', 'aria-label': 'Replay speed' },
      ...SPEEDS.map((s) => el('button', {
        type: 'button', role: 'radio', title: s.title, dataset: { speed: s.id },
        onclick: () => {
          speed = s.id;
          if (playing) scheduleNext(delayAfter(cursor));
          renderTransport();
        },
      }, s.label)));
    const live = el('button', { class: 'badge live-edge', type: 'button', title: 'Jump to the newest step and follow the run', hidden: true,
      onclick: () => {
        stopPlaying();
        followLive = true;
        thinkingFollow = true;
        catchUp();
        if (cursor === steps.length - 1) showCursor({ animate: false });
      } }, el('span', { class: 'badge-text' }, 'Live'));
    const close = el('button', { class: 'btn btn-ghost btn-icon', type: 'button', title: 'Close the replay', 'aria-label': 'Close the replay',
      onclick: () => {
        stopPlaying();
        replayOpen = false;
        seek(steps.length - 1);
        renderControls();
      } }, icon('close'));
    fill(nodes.transport, playButton, el('div', { class: 'scrub' }, ticks, scrub), speeds, live, close);
    const watchAgain = el('button', { class: 'btn btn-ghost watch-again', type: 'button', hidden: true,
      title: 'Replay this run from the start',
      onclick: () => {
        replayOpen = true;
        seek(0);
        play();
      } }, icon('play'), el('span', {}, 'Watch again'));
    nodes.transport.after(watchAgain);
    nodes.transport.addEventListener('keydown', (event) => {
      if (event.key === ' ' && event.target !== scrub) return;
      if (event.key === ' ') {
        event.preventDefault();
        playButton.click();
      }
    });
    return { play: playButton, scrub, ticks, speeds, live, watchAgain };
  })();

  nodes.follow.addEventListener('click', () => {
    cameraFollow = !cameraFollow;
    renderFollow();
    if (cameraFollow) followCamera(true);
  });

  /** Clear everything the live run draws, for a run without live steps. */
  function clearViews() {
    layer.replaceChildren();
    model.showSections(null);
    model.setFocusSections([]);
    model.setReviewOverlays(true);
    nodes.dial.hidden = true;
    nodes.caption.hidden = true;
    nodes.transport.hidden = true;
    nodes.follow.hidden = true;
  }

  return {
    /** Open a task: forget the old run and read the new one's steps. */
    open(nextTask) {
      reset(nextTask);
      clearViews();
      fill(nodes.thinking);
      if (nextTask) fetchSteps();
    },
    /** A task-changed event or a reload: read new steps now. */
    poke(changedTask) {
      if (changedTask === task && (!finished || isRunning())) fetchSteps();
    },
    /** The app learned the run's status; a run that is going again polls again. */
    statusChanged() {
      if (task && isRunning() && finished && !pollTimer) {
        finished = false;
        startPolling();
      }
    },
    hasSteps,
    /** Distance to the ink (RMS, metres) per section id in the newest scored revision. */
    latestInk() {
      for (let i = steps.length - 1; i >= 0; i -= 1) {
        const revision = steps[i].revision;
        if (revision?.fit !== null && revision?.fit !== undefined && revision.sections?.some((s) => s.ink_rms_m !== null)) {
          return new Map(revision.sections.map((s) => [s.id, s.ink_rms_m]));
        }
      }
      return new Map();
    },
    renderNarration,
    renderThinking,
    renderLadder,
    /** The person panned or zoomed the drawing: stop moving the camera for them. */
    userMovedCamera() {
      if (!cameraFollow || !hasSteps()) return;
      cameraFollow = false;
      renderFollow();
    },
    /** Space bar on the run view: play or pause. Returns true when it acted. */
    togglePlay() {
      if (!hasSteps()) return false;
      transportParts.play.click();
      return true;
    },
    /** Left and right arrows: the previous or next model step. */
    stepModel(direction) {
      if (!hasSteps()) return false;
      let index = cursor + direction;
      while (index >= 0 && index < steps.length && steps[index].actor !== 'model') index += direction;
      if (index < 0 || index >= steps.length) return false;
      seek(index, { animate: true });
      return true;
    },
  };
}
