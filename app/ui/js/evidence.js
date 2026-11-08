// Evidence card: hover a section tile to see where its line came from, without leaving the
// strip. The card shows the crop of the drawing page around the section with the lines the
// code found (the used one in blue), the source label and its basis, and how far the built
// section is from the ink in the newest scored revision (research finding 4).

import { el, fill } from './dom.js';
import * as fmt from './format.js';

/** Wait before the card opens, so passing over the strip does not flash cards. */
const OPEN_DELAY_MS = 350;
/** Crop size in CSS pixels (the crop keeps the section's aspect ratio inside this box). */
const CROP_MAX = { width: 240, height: 200 };
/** Space around the section's box in the crop, as a fraction of its size. */
const CROP_PAD = 0.06;

const imageCache = new Map();
function loadImage(url) {
  if (!imageCache.has(url)) {
    imageCache.set(url, new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = url;
    }));
  }
  return imageCache.get(url);
}

/** Draw the page crop around `roi` with the candidate lines on a canvas. */
function drawCrop(canvas, image, section) {
  const [x0, y0, x1, y1] = section.roi_px;
  const padX = (x1 - x0) * CROP_PAD;
  const padY = (y1 - y0) * CROP_PAD;
  const sx = Math.max(0, x0 - padX);
  const sy = Math.max(0, y0 - padY);
  const sw = Math.min(image.naturalWidth, x1 + padX) - sx;
  const sh = Math.min(image.naturalHeight, y1 + padY) - sy;
  const scale = Math.min(CROP_MAX.width / sw, CROP_MAX.height / sh);
  const ratio = window.devicePixelRatio || 1;
  canvas.style.width = `${Math.round(sw * scale)}px`;
  canvas.style.height = `${Math.round(sh * scale)}px`;
  canvas.width = Math.round(sw * scale * ratio);
  canvas.height = Math.round(sh * scale * ratio);
  const g = canvas.getContext('2d');
  g.setTransform(scale * ratio, 0, 0, scale * ratio, -sx * scale * ratio, -sy * scale * ratio);
  g.drawImage(image, 0, 0);
  const style = getComputedStyle(document.documentElement);
  // Other lines first, thin grey; the used line last, on top, in the selection blue.
  const lines = [...section.candidates].sort((a, b) => Number(a.chosen) - Number(b.chosen));
  for (const candidate of lines) {
    if (candidate.polyline_px.length < 2) continue;
    g.beginPath();
    candidate.polyline_px.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
    g.strokeStyle = candidate.chosen ? style.getPropertyValue('--ink-chosen').trim() : style.getPropertyValue('--ink-candidate').trim();
    g.lineWidth = (candidate.chosen ? 3 : 1.5) / scale;
    g.stroke();
  }
}

/**
 * `pageUrl()` resolves to the page image's data URL (or null); `inkOf(id)` gives the distance
 * to the ink in metres (or null).
 */
export function createEvidenceCard({ pageUrl, inkOf }) {
  const canvas = el('canvas', { class: 'evidence-crop', 'aria-hidden': 'true' });
  const text = el('div', { class: 'evidence-text' });
  const card = el('div', { class: 'evidence-card', role: 'tooltip', hidden: true }, canvas, text);
  document.body.append(card);
  let timer = 0;
  let token = 0;

  function place(anchor) {
    const box = anchor.getBoundingClientRect();
    const width = card.offsetWidth;
    const height = card.offsetHeight;
    const left = Math.min(Math.max(8, box.left + box.width / 2 - width / 2), window.innerWidth - width - 8);
    const top = box.top - height - 8 >= 8 ? box.top - height - 8 : box.bottom + 8;
    card.style.setProperty('left', `${left}px`);
    card.style.setProperty('top', `${top}px`);
  }

  async function open(anchor, section) {
    const mine = ++token;
    const ink = inkOf(section.id);
    const used = section.candidates.find((c) => c.chosen);
    fill(text,
      el('strong', {}, `Section at ${fmt.metres(section.x_m)}`),
      el('span', {}, used ? `Uses the ${used.label.toLowerCase()}` : fmt.sectionStateLabel(section.state)),
      section.source ? el('span', {}, fmt.sourceLabel(section.source.label), section.source.basis ? `: ${section.source.basis}` : '') : null,
      ink !== null && ink !== undefined
        ? el('span', { class: 'evidence-ink' }, `Off the ink by ${fmt.millimetres(ink)} (RMS)`)
        : null);
    canvas.hidden = true;
    card.hidden = false;
    place(anchor);
    const url = section.roi_px ? await pageUrl() : null;
    if (mine !== token || !url) return;
    try {
      drawCrop(canvas, await loadImage(url), section);
      if (mine !== token) return;
      canvas.hidden = false;
      place(anchor);
    } catch {
      // No crop: the card keeps its text.
    }
  }

  return {
    /** Hover started on `anchor` for `section`: open after a short wait. */
    hoverStart(anchor, section) {
      clearTimeout(timer);
      timer = setTimeout(() => open(anchor, section), OPEN_DELAY_MS);
    },
    hide() {
      clearTimeout(timer);
      token += 1;
      card.hidden = true;
    },
  };
}
