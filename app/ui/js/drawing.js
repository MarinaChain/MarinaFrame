// Drawing view: the source page image with section regions and candidate lines, in an SVG
// whose viewBox gives zoom and pan. Coordinates are source-page pixels throughout.

import { el, svg, prefersReducedMotion } from './dom.js';

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 16;
/** Zoom factor per wheel notch and per button press. */
const ZOOM_STEP = 1.25;
/** Space kept around a section when the view zooms to it, as a fraction of its size. */
const SECTION_PADDING = 0.18;
const ANIMATION_MS = 260;

export function createDrawingView({ host, tooltip, readout, onSelectSection, onHoverCandidate }) {
  const root = svg('svg', { role: 'img', 'aria-label': 'Source drawing' });
  const pageLayer = svg('g');
  const regionLayer = svg('g');
  const lineLayer = svg('g');
  root.append(pageLayer, regionLayer, lineLayer);
  host.append(root);

  let page = null;
  let sections = [];
  let selectedId = null;
  let hotCandidateId = null;
  let view = { x: 0, y: 0, w: 1, h: 1 };
  let animationFrame = 0;
  /** Re-applies the last fit when the pane resizes; null once the user zooms or pans. */
  let refit = null;

  // ---------------------------------------------------------------- view box

  function hostSize() {
    return { width: host.clientWidth || 1, height: host.clientHeight || 1 };
  }

  /** Pixels on screen per page pixel. */
  function zoomLevel() {
    const { width, height } = hostSize();
    return Math.min(width / view.w, height / view.h);
  }

  function applyView() {
    root.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
    readout.textContent = `${Math.round(zoomLevel() * 100)}%`;
  }

  /** View box that shows a page rectangle at its largest, centred, with the host's aspect ratio. */
  function boxFor(x, y, w, h) {
    const { width, height } = hostSize();
    const aspect = width / height;
    if (w / h > aspect) {
      const fullH = w / aspect;
      return { x, y: y - (fullH - h) / 2, w, h: fullH };
    }
    const fullW = h * aspect;
    return { x: x - (fullW - w) / 2, y, w: fullW, h };
  }

  function animateTo(target) {
    cancelAnimationFrame(animationFrame);
    if (prefersReducedMotion()) {
      view = target;
      applyView();
      return;
    }
    const start = { ...view };
    const began = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - began) / ANIMATION_MS);
      const eased = 1 - (1 - t) ** 4;
      for (const key of ['x', 'y', 'w', 'h']) view[key] = start[key] + (target[key] - start[key]) * eased;
      applyView();
      if (t < 1) animationFrame = requestAnimationFrame(step);
    };
    animationFrame = requestAnimationFrame(step);
  }

  function fitPage(animate = true) {
    if (!page) return;
    refit = () => fitPage(false);
    const margin = Math.max(page.width, page.height) * 0.02;
    const target = boxFor(-margin, -margin, page.width + 2 * margin, page.height + 2 * margin);
    if (animate) animateTo(target);
    else {
      view = target;
      applyView();
    }
  }

  function fitSection(id, animate = true) {
    const section = sections.find((s) => s.id === id);
    if (!section) return;
    refit = () => fitSection(id, false);
    const [x0, y0, x1, y1] = section.roi_px;
    const padX = (x1 - x0) * SECTION_PADDING;
    const padY = (y1 - y0) * SECTION_PADDING;
    const target = boxFor(x0 - padX, y0 - padY, x1 - x0 + 2 * padX, y1 - y0 + 2 * padY);
    if (animate) animateTo(target);
    else {
      view = target;
      applyView();
    }
  }

  /** Fit all section regions, or the page when there are none. */
  function fitSections(animate = true) {
    if (!sections.length) return fitPage(animate);
    refit = () => fitSections(false);
    const xs0 = Math.min(...sections.map((s) => s.roi_px[0]));
    const ys0 = Math.min(...sections.map((s) => s.roi_px[1]));
    const xs1 = Math.max(...sections.map((s) => s.roi_px[2]));
    const ys1 = Math.max(...sections.map((s) => s.roi_px[3]));
    const pad = Math.max(xs1 - xs0, ys1 - ys0) * 0.04;
    const target = boxFor(xs0 - pad, ys0 - pad, xs1 - xs0 + 2 * pad, ys1 - ys0 + 2 * pad);
    if (animate) animateTo(target);
    else {
      view = target;
      applyView();
    }
  }

  function zoomAt(factor, clientX, clientY) {
    refit = null;
    const current = zoomLevel();
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor));
    const applied = next / current;
    const rect = host.getBoundingClientRect();
    const px = clientX ?? rect.left + rect.width / 2;
    const py = clientY ?? rect.top + rect.height / 2;
    const point = toPage(px, py);
    view = {
      x: point.x - (point.x - view.x) / applied,
      y: point.y - (point.y - view.y) / applied,
      w: view.w / applied,
      h: view.h / applied,
    };
    cancelAnimationFrame(animationFrame);
    applyView();
  }

  function toPage(clientX, clientY) {
    const matrix = root.getScreenCTM();
    if (!matrix) return { x: 0, y: 0 };
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return { x: point.x, y: point.y };
  }

  // ---------------------------------------------------------------- pointer input

  let pan = null;
  host.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || !page) return;
    pan = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false, target: event.target };
    host.setPointerCapture(event.pointerId);
  });
  host.addEventListener('pointermove', (event) => {
    if (!pan || pan.id !== event.pointerId) return;
    const dx = event.clientX - pan.x;
    const dy = event.clientY - pan.y;
    if (!pan.moved && Math.hypot(dx, dy) < 3) return;
    pan.moved = true;
    host.classList.add('panning');
    hideTooltip();
    refit = null;
    const scale = 1 / zoomLevel();
    view.x -= dx * scale;
    view.y -= dy * scale;
    pan.x = event.clientX;
    pan.y = event.clientY;
    applyView();
  });
  host.addEventListener('pointerup', (event) => {
    if (!pan || pan.id !== event.pointerId) return;
    host.classList.remove('panning');
    // A click without movement selects the section under the pointer.
    if (!pan.moved) {
      const sectionId = pan.target.closest?.('[data-section]')?.dataset.section;
      if (sectionId && sectionId !== selectedId) onSelectSection(sectionId);
    }
    pan = null;
  });
  host.addEventListener('pointercancel', () => {
    pan = null;
    host.classList.remove('panning');
  });

  host.addEventListener('wheel', (event) => {
    event.preventDefault();
    if (event.ctrlKey || Math.abs(event.deltaY) >= Math.abs(event.deltaX)) {
      // Pinch gestures arrive as ctrlKey wheel events with small deltas.
      const intensity = event.ctrlKey ? 0.01 : 0.0025;
      zoomAt(Math.exp(-event.deltaY * intensity), event.clientX, event.clientY);
    } else {
      refit = null;
      const scale = 1 / zoomLevel();
      view.x += event.deltaX * scale;
      applyView();
    }
  }, { passive: false });

  host.addEventListener('keydown', (event) => {
    const panStep = 60 / zoomLevel();
    const keys = {
      '+': () => zoomAt(ZOOM_STEP),
      '=': () => zoomAt(ZOOM_STEP),
      '-': () => zoomAt(1 / ZOOM_STEP),
      0: () => fitPage(),
      ArrowLeft: () => { view.x -= panStep; applyView(); },
      ArrowRight: () => { view.x += panStep; applyView(); },
      ArrowUp: () => { view.y -= panStep; applyView(); },
      ArrowDown: () => { view.y += panStep; applyView(); },
    };
    if (event.metaKey || event.ctrlKey || !keys[event.key]) return;
    event.preventDefault();
    if (event.key.startsWith('Arrow')) refit = null;
    keys[event.key]();
  });

  new ResizeObserver(() => {
    if (!page) return;
    if (refit) {
      cancelAnimationFrame(animationFrame);
      refit();
      return;
    }
    // Keep the centre and the zoom level when the pane changes size.
    const centre = { x: view.x + view.w / 2, y: view.y + view.h / 2 };
    const scale = zoomLevel();
    const { width, height } = hostSize();
    view = { x: centre.x - width / scale / 2, y: centre.y - height / scale / 2, w: width / scale, h: height / scale };
    applyView();
  }).observe(host);

  // ---------------------------------------------------------------- tooltip

  /** True for the line a draft guessed in this section. */
  function isGuessedLine(section, candidate) {
    return section.state === 'guessed' && candidate.chosen;
  }

  function showTooltip(candidate, section, clientX, clientY) {
    const guessed = isGuessedLine(section, candidate);
    const tag = guessed ? 'Guessed' : candidate.chosen ? 'In use' : candidate.selectable ? 'Alternative' : 'Not usable';
    tooltip.replaceChildren(
      el('strong', {}, candidate.label, el('span', { class: candidate.chosen && !guessed ? 'tip-tag' : 'tip-tag muted' }, tag)),
      guessed ? el('div', {}, section.reason) : null,
      el('div', {}, candidate.why),
    );
    tooltip.hidden = false;
    const hostRect = host.parentElement.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    let left = clientX - hostRect.left + 14;
    let top = clientY - hostRect.top + 16;
    if (left + tipRect.width > hostRect.width - 8) left = clientX - hostRect.left - tipRect.width - 14;
    if (top + tipRect.height > hostRect.height - 8) top = clientY - hostRect.top - tipRect.height - 12;
    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
  }

  function hideTooltip() {
    tooltip.hidden = true;
  }

  // ---------------------------------------------------------------- drawing

  function pointsAttr(polyline) {
    return polyline.map(([x, y]) => `${x},${y}`).join(' ');
  }

  function renderOverlays() {
    regionLayer.replaceChildren();
    lineLayer.replaceChildren();
    if (!page) return;

    for (const section of sections) {
      const [x0, y0, x1, y1] = section.roi_px;
      const selected = section.id === selectedId;
      const region = svg('rect', {
        class: selected ? 'region selected' : 'region',
        x: x0, y: y0, width: x1 - x0, height: y1 - y0,
        'data-section': section.id,
        'data-state': section.state,
      });
      const label = `Section at ${section.x_m.toFixed(1)} m`;
      region.append(svg('title', {}, section.state === 'guessed' ? `${label}. ${section.reason}` : label));
      regionLayer.append(region);

      if (!selected) {
        const chosen = section.candidates.find((c) => c.chosen);
        const guessed = chosen && isGuessedLine(section, chosen);
        if (chosen) lineLayer.append(svg('polyline', { class: `cand cand-overview${guessed ? ' cand-guess' : ''}`, points: pointsAttr(chosen.polyline_px) }));
      }
    }

    const section = sections.find((s) => s.id === selectedId);
    if (!section) return;
    // Draw others first so the chosen line sits on top.
    const ordered = [...section.candidates].sort((a, b) => Number(a.chosen) - Number(b.chosen));
    for (const candidate of ordered) {
      const points = pointsAttr(candidate.polyline_px);
      const line = svg('polyline', {
        class: `cand ${candidate.chosen ? 'cand-chosen' : 'cand-other'}${isGuessedLine(section, candidate) ? ' cand-guess' : ''}${candidate.id === hotCandidateId ? ' hot' : ''}`,
        points,
        'data-candidate': candidate.id,
      });
      const hit = svg('polyline', { class: 'cand-hit', points, 'data-section': section.id });
      hit.addEventListener('pointerenter', (event) => {
        setHot(candidate.id);
        onHoverCandidate(candidate.id);
        showTooltip(candidate, section, event.clientX, event.clientY);
      });
      hit.addEventListener('pointermove', (event) => {
        if (!pan?.moved) showTooltip(candidate, section, event.clientX, event.clientY);
      });
      hit.addEventListener('pointerleave', () => {
        setHot(null);
        onHoverCandidate(null);
        hideTooltip();
      });
      lineLayer.append(line, hit);
    }
  }

  function setHot(candidateId) {
    hotCandidateId = candidateId;
    for (const line of lineLayer.querySelectorAll('[data-candidate]')) {
      line.classList.toggle('hot', line.dataset.candidate === candidateId);
    }
  }

  return {
    /** Show a page. `imageUrl` is a data: URL, or null while it loads. */
    setPage(nextPage, imageUrl) {
      const samePage = page && nextPage && page.path === nextPage.path && page.width === nextPage.width;
      page = nextPage;
      if (!page) {
        pageLayer.replaceChildren();
        renderOverlays();
        return;
      }
      if (!samePage || imageUrl) {
        pageLayer.replaceChildren(
          svg('rect', { class: 'page-frame', x: 0, y: 0, width: page.width, height: page.height, fill: 'white' }),
          ...(imageUrl ? [svg('image', { href: imageUrl, x: 0, y: 0, width: page.width, height: page.height, preserveAspectRatio: 'none' })] : []),
        );
      }
      if (!samePage) fitPage(false);
    },
    setSections(nextSections, nextSelectedId, { focus = false } = {}) {
      const changedSelection = nextSelectedId !== selectedId;
      sections = nextSections;
      selectedId = nextSelectedId;
      renderOverlays();
      if (focus && changedSelection && selectedId) fitSection(selectedId);
    },
    highlightCandidate: setHot,
    fitPage: () => fitPage(),
    fitSections: () => fitSections(false),
    fitSection,
    zoomIn: () => zoomAt(ZOOM_STEP),
    zoomOut: () => zoomAt(1 / ZOOM_STEP),
  };
}
