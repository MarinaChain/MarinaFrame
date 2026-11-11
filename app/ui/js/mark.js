// Mark and revise (docs/APP_SPEC.md, "Mark and revise"): circle part of the drawing, or pick
// a section in the strip, and say what to fix. The controller records the request as a
// person's action and runs one short model pass on the marked sections; the live screen
// shows that pass like any other steps. Its result step offers "Keep anyway" when the
// keep rule did not keep the edit.
//
// Colours: the person's mark is brand blue; teal stays for AI activity, amber for review.

import { el, svg, fill } from './dom.js';

const REQUEST_SCHEMA = 'marinaframe.revision_request.v1';
const MAX_INSTRUCTION_CHARS = 500;
/** Lasso outlines are thinned to this many points (the controller accepts up to 64). */
const MAX_LASSO_POINTS = 48;
/** A drag shorter than this (screen pixels) is a click, not a mark. */
const MIN_DRAG_PX = 6;
/** Quick chips: one word on the chip, a sentence in the text field. */
const QUICK_CHIPS = [
  ['Too full', 'Too full here: bring the curve in to the drawn line.'],
  ['Too fine', 'Too fine here: let the curve out to the drawn line.'],
  ['Follow ink', 'Follow the drawn ink more closely in this region.'],
  ['Smoother', 'Make this part of the section smoother, without kinks.'],
  ['Wrong line', 'This follows the wrong line; use the hull line of this station.'],
];

/** Thin a polyline to at most `max` points, keeping the first and last. */
function thin(points, max) {
  if (points.length <= max) return points;
  const step = (points.length - 1) / (max - 1);
  return Array.from({ length: max }, (_, i) => points[Math.round(i * step)]);
}

const round = (value) => Math.round(value * 10) / 10;

/**
 * `drawing`: the drawing view (drawing.js). `drawingHost`: its element. `strip`: the section
 * strip. `context()` returns `{ task, view, running }` for the open run. `onSent()` runs after
 * a request or "Keep anyway" was accepted, so the app reads the run again.
 */
export function createMarkTool({ invoke, drawing, drawingHost, strip, context, onSent, onError }) {
  const button = el('button', {
    class: 'btn btn-ghost btn-small mark-toggle write-action',
    type: 'button',
    'aria-pressed': 'false',
    title: 'Mark part of the drawing, or pick a section below or in 3D, and say what to fix (M)',
    onclick: () => setActive(!active),
  }, 'Mark');
  drawingHost.closest('.pane')?.querySelector('.pane-tools')?.prepend(button);

  let active = false;
  let shape = 'box';
  let drag = null;
  let popover = null;

  const preview = svg('svg', { class: 'mark-preview', 'aria-hidden': 'true' });
  const shapeButtons = ['box', 'lasso'].map((name) => el('button', {
    class: 'btn btn-ghost btn-small', type: 'button', dataset: { shape: name },
    'aria-pressed': String(name === shape),
    onclick: (event) => {
      event.stopPropagation();
      shape = name;
      for (const b of shapeButtons) b.setAttribute('aria-pressed', String(b.dataset.shape === shape));
    },
  }, name === 'box' ? 'Box' : 'Lasso'));
  const hint = el('div', { class: 'mark-hint', onpointerdown: (event) => event.stopPropagation() },
    el('span', {}, 'Drag on the drawing, or pick a section below or in 3D.'), ...shapeButtons,
    el('button', { class: 'btn btn-ghost btn-small', type: 'button', onclick: () => setActive(false) }, 'Done'));
  const overlay = el('div', { class: 'mark-overlay', hidden: true }, preview, hint);
  drawingHost.append(overlay);

  // ---------------------------------------------------------------- availability

  /** Marking needs an open AI run that is not working right now. */
  function available() {
    const { task, view, running } = context();
    return Boolean(task && view && view.summary.policy === 'live' && !running);
  }

  function refresh() {
    const ok = available();
    button.hidden = !context().view || context().view.summary.policy !== 'live';
    button.disabled = !ok;
    button.title = ok
      ? 'Mark part of the drawing, or pick a section below or in 3D, and say what to fix (M)'
      : 'Marking is possible when the AI run is not working.';
    if (!ok && active) setActive(false);
  }

  function setActive(next) {
    active = next && available();
    button.setAttribute('aria-pressed', String(active));
    overlay.hidden = !active;
    strip.classList.toggle('mark-picking', active);
    if (!active) {
      closePopover();
      fill(preview);
    }
  }

  // ---------------------------------------------------------------- drawing a mark

  /** Client point -> source-page pixels, through the drawing's SVG transform. */
  function toPage(clientX, clientY) {
    const matrix = drawing.attentionLayer.ownerSVGElement?.getScreenCTM();
    if (!matrix) return null;
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return [point.x, point.y];
  }

  function localPoint(event) {
    const rect = overlay.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  function drawPreview(points) {
    if (shape === 'box') {
      const [[x0, y0], [x1, y1]] = [points[0], points[points.length - 1]];
      fill(preview, svg('rect', {
        class: 'mark-shape', x: Math.min(x0, x1), y: Math.min(y0, y1),
        width: Math.abs(x1 - x0), height: Math.abs(y1 - y0), rx: 4,
      }));
    } else {
      fill(preview, svg('polygon', { class: 'mark-shape', points: points.map((p) => p.join(',')).join(' ') }));
    }
  }

  overlay.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || popover) return;
    event.stopPropagation();
    overlay.setPointerCapture(event.pointerId);
    drag = { id: event.pointerId, screen: [localPoint(event)], client: [[event.clientX, event.clientY]] };
  });
  overlay.addEventListener('pointermove', (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    event.stopPropagation();
    drag.screen.push(localPoint(event));
    drag.client.push([event.clientX, event.clientY]);
    drawPreview(drag.screen);
  });
  overlay.addEventListener('pointerup', (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    event.stopPropagation();
    const done = drag;
    drag = null;
    const [first, last] = [done.client[0], done.client[done.client.length - 1]];
    const spread = Math.max(...done.client.map(([x, y]) => Math.hypot(x - first[0], y - first[1])));
    if (spread < MIN_DRAG_PX) {
      fill(preview);
      return;
    }
    const page = done.client.map(([x, y]) => toPage(x, y)).filter(Boolean);
    let region;
    if (shape === 'box') {
      const [a, b] = [toPage(...first), toPage(...last)];
      region = { page_px_box: [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])].map(round) };
    } else {
      region = { lasso_px: thin(page, MAX_LASSO_POINTS).map(([x, y]) => [round(x), round(y)]) };
    }
    openPopover({ region }, done.screen[done.screen.length - 1]);
  });
  overlay.addEventListener('pointercancel', () => {
    drag = null;
    fill(preview);
  });

  // A click on a section tile while marking picks that section instead of selecting it.
  strip.addEventListener('click', (event) => {
    if (!active) return;
    const tile = event.target.closest?.('.tile');
    if (!tile?.dataset.section) return;
    event.stopPropagation();
    event.preventDefault();
    openPopover({ target_section_ids: [tile.dataset.section] }, null);
  }, true);

  // ---------------------------------------------------------------- popover

  /** Sections whose panel the mark touches, for the popover's line. */
  function sectionsOf(place) {
    const sections = context().view?.sections || [];
    if (place.target_section_ids) return place.target_section_ids;
    const points = place.region.page_px_box
      ? [place.region.page_px_box.slice(0, 2), place.region.page_px_box.slice(2)]
      : place.region.lasso_px;
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const [l, t, r, b] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    return sections.filter((s) => s.roi_px && s.roi_px[0] < r && l < s.roi_px[2] && s.roi_px[1] < b && t < s.roi_px[3]).map((s) => s.id);
  }

  function describe(place, ids) {
    if (place.target_section_ids) {
      // Say where the section is (as on the strip), not its internal id.
      const sections = context().view?.sections || [];
      const names = ids.map((id) => {
        const x = sections.find((s) => s.id === id)?.x_m;
        return Number.isFinite(x) ? `${x.toFixed(1)} m` : id;
      });
      return `Picked the section at ${names.join(', ')}`;
    }
    const what = place.region.page_px_box ? 'Box' : 'Lasso';
    if (!ids.length) return `${what} on the drawing; the AI picks the section`;
    if (ids.length === 1) return `${what}: section ${ids[0]}`;
    return `${what}: ${ids.length} sections (the AI edits the one the mark shows)`;
  }

  function openPopover(place, anchor) {
    closePopover();
    const ids = sectionsOf(place);
    const text = el('textarea', {
      class: 'mark-text', rows: '3', maxlength: String(MAX_INSTRUCTION_CHARS),
      placeholder: 'What should change here?', 'aria-label': 'What should change here',
    });
    const count = el('span', { class: 'mark-count' }, `0 / ${MAX_INSTRUCTION_CHARS}`);
    const error = el('p', { class: 'mark-error', role: 'alert', hidden: true });
    const send = el('button', { class: 'btn btn-primary btn-small', type: 'submit', disabled: true }, 'Send');
    const update = () => {
      count.textContent = `${text.value.length} / ${MAX_INSTRUCTION_CHARS}`;
      send.disabled = !text.value.trim();
    };
    text.addEventListener('input', update);
    const chips = QUICK_CHIPS.map(([label, sentence]) => el('button', {
      class: 'badge mark-chip', type: 'button',
      onclick: () => {
        text.value = sentence;
        update();
        text.focus();
      },
    }, label));
    const form = el('form', {
      class: 'mark-popover', 'aria-label': 'Revise the marked region',
      onpointerdown: (event) => event.stopPropagation(),
      onkeydown: (event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          closePopover();
        }
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !send.disabled) form.requestSubmit();
      },
      onsubmit: async (event) => {
        event.preventDefault();
        send.disabled = true;
        error.hidden = true;
        const request = { schema_version: REQUEST_SCHEMA, instruction: text.value.trim(), ...place };
        try {
          await invoke('revise_region', { task: context().task, request });
          setActive(false);
          onSent();
        } catch (failure) {
          error.textContent = failure?.message || 'The request could not be sent.';
          error.hidden = false;
          send.disabled = false;
        }
      },
    },
    el('p', { class: 'mark-place' }, describe(place, ids)),
    el('div', { class: 'mark-chips' }, ...chips),
    text,
    error,
    el('div', { class: 'mark-actions' }, count,
      el('button', { class: 'btn btn-ghost btn-small', type: 'button', onclick: closePopover }, 'Cancel'),
      send));
    if (anchor) {
      const width = overlay.clientWidth;
      const left = Math.max(8, Math.min(anchor[0] + 12, width - 328));
      const top = Math.max(8, Math.min(anchor[1] + 12, overlay.clientHeight - 240));
      form.style.setProperty('left', `${left}px`);
      form.style.setProperty('top', `${top}px`);
    } else {
      form.classList.add('mark-popover-docked');
    }
    overlay.append(form);
    popover = form;
    text.focus();
  }

  function closePopover() {
    popover?.remove();
    popover = null;
    fill(preview);
  }

  // ---------------------------------------------------------------- result actions

  /** "Keep anyway" for a revision result the keep rule did not keep (live.js card hook). */
  function resultActions(step) {
    const revision = step.mark_revision;
    if (!revision) return null;
    if (revision.operator_forced) return el('p', { class: 'mark-forced' }, 'Kept by a person; the fit did not improve.');
    if (!revision.can_keep_anyway) return null;
    const keep = el('button', {
      class: 'btn btn-small mark-keep write-action', type: 'button',
      title: 'Use this edit although the drawing fit did not improve. It is recorded as kept by a person.',
      onclick: async () => {
        keep.disabled = true;
        try {
          await invoke('force_keep_revision', { task: context().task, revision_id: revision.revision_id });
          onSent();
        } catch (failure) {
          keep.disabled = false;
          onError(failure);
        }
      },
    }, 'Keep anyway');
    return el('div', { class: 'mark-result-actions' }, keep);
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && active && !popover) setActive(false);
    const typing = event.target.closest?.('input, textarea, select, [contenteditable]');
    if (!typing && !event.metaKey && !event.ctrlKey && (event.key === 'm' || event.key === 'M') && !button.hidden && !button.disabled
      && button.offsetParent !== null) { // only while the drawing is on screen (the Run tab)
      if (document.getElementById('view-run')?.hidden) return;
      setActive(!active);
    }
  });

  /** A section picked outside the strip (the 3D view): while marking, ask about it. Returns true when used. */
  function pickSection(id) {
    if (!active) return false;
    openPopover({ target_section_ids: [id] }, null);
    return true;
  }

  return { refresh, resultActions, setActive, pickSection };
}
