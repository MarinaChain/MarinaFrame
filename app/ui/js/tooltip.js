// Shared tooltip for icons and icon chips: the title first, then the full detail on demand.
//
//   1. Hover an element with `data-tip-title` (or focus it by keyboard): after TIP_DELAY_MS a
//      small tooltip shows the title only (keyboard focus shows it at once).
//   2. If the element has `data-tip-detail` and the pointer stays on the element or on the
//      tooltip, a ring next to the title fills over RING_MS; then the tooltip shows the detail.
//      Leaving before the ring completes cancels it. Shift (or a click on the tooltip) shows
//      the detail at once.
//   3. Escape closes. Touch: a tap shows the title, a second tap the detail.
//   4. Reduced motion: no ring animation; the detail still follows after the same time.
//
// The title is the element's accessible name (its aria-label); the detail is reachable by
// screen readers through aria-describedby (see tipAttributes). The tooltip stays inside the
// window and never covers its element: it goes below it, or above when there is no room.

import { el, svg, fill } from './dom.js';

/** Hover time before the title shows. */
export const TIP_DELAY_MS = 300;
/** Time the ring takes to fill before the detail shows (styles.css --tip-ring-ms matches). */
export const RING_MS = 1000;
/** Time the pointer may spend between the element and its tooltip without closing it. */
const LEAVE_GRACE_MS = 150;
/** Space between the element and the tooltip, and between the tooltip and the window edge. */
const GAP_PX = 6;

/**
 * The tooltip states, without the DOM: idle -> pending -> (title | ringing) -> detail.
 * `render({ state, owner, ring })` is called on every change; `ring` is true while the ring
 * should animate (never under reduced motion). Timers are injectable for tests.
 */
export function createTipMachine({ render, setTimer = setTimeout, clearTimer = clearTimeout, reducedMotion = () => false }) {
  let state = 'idle';
  let owner = null;
  let hasDetail = false;
  let timer = 0;

  function set(next) {
    state = next;
    render({ state, owner, ring: state === 'ringing' && !reducedMotion() });
  }
  function arm(ms, then) {
    clearTimer(timer);
    timer = setTimer(then, ms);
  }
  function showTitle() {
    if (!hasDetail) {
      set('title');
      return;
    }
    set('ringing');
    arm(RING_MS, () => set('detail'));
  }

  return {
    get state() { return state; },
    get owner() { return owner; },
    /** The pointer or focus reached `next`. `via`: 'pointer', 'focus' or 'touch'. */
    enter(next, { detail = false, via = 'pointer' } = {}) {
      if (via === 'touch' && next === owner && (state === 'title' || state === 'ringing')) {
        clearTimer(timer);
        if (hasDetail) set('detail');
        return;
      }
      if (via !== 'touch' && next === owner && state !== 'idle') return;
      clearTimer(timer);
      owner = next;
      hasDetail = detail;
      if (via === 'touch') set('title');
      else if (via === 'focus') showTitle();
      else {
        set('pending');
        arm(TIP_DELAY_MS, showTitle);
      }
    },
    /** The pointer left the element and the tooltip, or the focus moved away. */
    leave() {
      clearTimer(timer);
      owner = null;
      if (state !== 'idle') set('idle');
    },
    /** Shift, "?" or a click on the tooltip: the detail now. */
    expand() {
      if (!owner || !hasDetail || state === 'idle' || state === 'detail') return;
      clearTimer(timer);
      set('detail');
    },
    escape() { this.leave(); },
  };
}

// ---------------------------------------------------------------- attributes for owners

let detailCount = 0;

/**
 * Attributes and children that give an element a tooltip: `title` is the accessible name,
 * `detail` (optional) the description. Use as `el(tag, { ...tip.attrs, ...}, ...children, tip.describer)`.
 * `label: false` leaves aria-label off, for an element whose own text already names it.
 */
export function tipAttributes(title, detail = null, { label = true } = {}) {
  const attrs = { 'data-tip-title': title };
  let describer = null;
  if (label) attrs['aria-label'] = title;
  if (detail && detail !== title) {
    detailCount += 1;
    const id = `tip-detail-${detailCount}`;
    attrs['data-tip-detail'] = detail;
    attrs['aria-describedby'] = id;
    describer = el('span', { id, class: 'visually-hidden' }, detail);
  }
  return { attrs, describer };
}

// ---------------------------------------------------------------- DOM

let installed = null;

function place(node, owner) {
  const box = owner.getBoundingClientRect();
  const tip = node.getBoundingClientRect();
  const maxLeft = window.innerWidth - tip.width - GAP_PX;
  const left = Math.max(GAP_PX, Math.min(maxLeft, box.left + box.width / 2 - tip.width / 2));
  const roomBelow = window.innerHeight - box.bottom - GAP_PX * 2;
  const top = tip.height <= roomBelow ? box.bottom + GAP_PX : Math.max(GAP_PX, box.top - GAP_PX - tip.height);
  node.style.setProperty('left', `${Math.round(left)}px`);
  node.style.setProperty('top', `${Math.round(top)}px`);
}

/** Wire the tooltip to the whole page. Call once; later calls return the same machine. */
export function installTooltips() {
  if (installed) return installed;
  const titleText = el('span', { class: 'tip-title' });
  const ring = svg('svg', { class: 'tip-ring', viewBox: '0 0 12 12', 'aria-hidden': 'true' },
    svg('circle', { class: 'tip-ring-track', cx: 6, cy: 6, r: 4.5 }),
    svg('circle', { class: 'tip-ring-fill', cx: 6, cy: 6, r: 4.5, pathLength: 1 }));
  const detailText = el('p', { class: 'tip-detail' });
  // aria-hidden: the owner's aria-label and aria-describedby already give both texts.
  const node = el('div', { class: 'tooltip tip', id: 'tip', 'aria-hidden': 'true', hidden: true },
    el('div', { class: 'tip-head' }, titleText, ring), detailText);
  document.body.append(node);
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');

  const machine = createTipMachine({
    reducedMotion: () => motion.matches,
    render({ state, owner, ring: ringOn }) {
      if (state === 'idle' || state === 'pending' || !owner) {
        node.hidden = true;
        return;
      }
      fill(titleText, owner.dataset.tipTitle);
      const detail = owner.dataset.tipDetail || '';
      fill(detailText, state === 'detail' ? detail : '');
      node.dataset.state = state;
      node.dataset.ring = String(ringOn);
      // An SVG element has no `hidden` property; the attribute works through [hidden] in CSS.
      ring.toggleAttribute('hidden', !(state === 'ringing' || (state === 'title' && detail)));
      // Restart the ring animation for each new owner.
      ring.classList.remove('tip-ring-run');
      if (ringOn) {
        void ring.getBoundingClientRect();
        ring.classList.add('tip-ring-run');
      }
      node.hidden = false;
      place(node, owner);
    },
  });

  let graceTimer = 0;
  const ownerOf = (target) => target?.closest?.('[data-tip-title]') || null;
  const enter = (owner, via) => {
    clearTimeout(graceTimer);
    machine.enter(owner, { detail: Boolean(owner.dataset.tipDetail), via });
  };

  document.addEventListener('pointerover', (event) => {
    if (event.pointerType === 'touch') return;
    if (node.contains(event.target)) {
      clearTimeout(graceTimer);
      return;
    }
    const owner = ownerOf(event.target);
    if (owner) {
      if (owner !== machine.owner) machine.leave();
      enter(owner, 'pointer');
      return;
    }
    if (!machine.owner) return;
    clearTimeout(graceTimer);
    graceTimer = setTimeout(() => machine.leave(), LEAVE_GRACE_MS);
  });
  document.addEventListener('pointerdown', (event) => {
    if (node.contains(event.target)) {
      machine.expand();
      return;
    }
    const owner = ownerOf(event.target);
    if (event.pointerType === 'touch' && owner) enter(owner, 'touch');
    else if (event.pointerType === 'touch') machine.leave();
  });
  document.addEventListener('focusin', (event) => {
    const owner = ownerOf(event.target);
    if (owner && event.target.matches(':focus-visible')) {
      if (owner !== machine.owner) machine.leave();
      enter(owner, 'focus');
    } else if (machine.owner && !machine.owner.contains(event.target)) machine.leave();
  });
  document.addEventListener('focusout', (event) => {
    if (machine.owner && machine.owner.contains(event.target)) machine.leave();
  });
  document.addEventListener('keydown', (event) => {
    if (machine.state === 'idle') return;
    if (event.key === 'Escape') machine.escape();
    // Shift only: "?" already opens the shortcut sheet (shortcuts.js).
    else if (event.key === 'Shift') machine.expand();
  }, true);
  document.addEventListener('scroll', () => machine.leave(), true);
  installed = machine;
  return machine;
}
