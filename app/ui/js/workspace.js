// The run workspace panes: the drawing, the 3D model, the live run and Mark and revise,
// the layout switch and splitter, and the whole-vessel model.

import { state, isRunning, setPageKey, setModelKey, prefs } from './app_state.js';
import { invoke } from './api.js';
import { el, fill, icon } from './dom.js';
import * as fmt from './format.js';
import { $, showError } from './ui_kit.js';
import { guessedXRanges } from './run_facts.js';
import { evidencePageUrl, cachedArtifact } from './artifacts.js';
import { createDrawingView } from './drawing.js';
import { createEvidenceCard } from './evidence.js';
import { createLiveRun } from './live.js';
import { createMarkTool } from './mark.js';
import { createModelView } from './model3d.js';
import { capacityRowOf } from './tanks.js';
import { renderThinking } from './inspector.js';
import { renderNarration, renderRevisionStrip } from './run_header.js';
import { selectSection, placesIn, renderStrip } from './run_strip.js';
import { loadTask, runAction } from './run.js';
import { setVesselTab } from './vessel_pages.js';

/** Below this stage width the drawing and model stack vertically. */
const STACK_BELOW_PX = 700;
const SPLIT_MIN = 0.2;
const SPLIT_MAX = 0.8;

export let evidence, drawing, model, live, markTool;
let drawingEmpty;

/** Create the panes. Their callbacks reach the rest of the run view only after start. */
export function createWorkspace() {
  evidence = createEvidenceCard({
    pageUrl: evidencePageUrl,
    inkOf: (id) => live.latestInk().get(id) ?? null,
  });

  drawing = createDrawingView({
    host: $('drawing-host'),
    tooltip: $('drawing-tooltip'),
    readout: $('zoom-readout'),
    onSelectSection: (id) => selectSection(id, { focusDrawing: false }),
    onUserCamera: () => live?.userMovedCamera(),
    onHoverCandidate: (id) => {
      for (const row of document.querySelectorAll('.cand-row')) row.classList.toggle('hot', row.dataset.candidate === id);
    },
  });
  // A click on a section plane in 3D picks it: for Mark and revise while marking, else it selects it.
  model = createModelView({
    host: $('model-host'),
    onPick: (id) => {
      if (markTool.pickSection(id)) return;
      if (state.view?.sections.some((s) => s.id === id)) selectSection(id, { focusDrawing: true });
    },
    // What the run knows of a part, for its fact card in 3D: the capacity plan row of a tank, the
    // part record, and the source it was read from (the drawing opens beside the model).
    partContext: (id) => {
      const component = state.view?.components?.find((part) => part.id === id) || null;
      const basis = component?.arguments?.find((argument) => argument.basis)?.basis;
      const source = component && (basis || component.view)
        ? { label: [basis, component.view ? `${component.view} view` : null].filter(Boolean).join(' · '), open: () => setLayout('split') }
        : null;
      return { row: capacityRowOf(state.view?.capacity_plan, id), component, source };
    },
  });

  /** HOOK(M3 live): the live run (js/live.js) owns narration, Thinking and the ladder when it has steps. */
  live = createLiveRun({
    invoke,
    drawing,
    model,
    isRunning: () => isRunning(),
    placesIn: (text) => placesIn(text),
    nodes: {
      narration: $('narration'),
      thinking: $('panel-thinking'),
      ladder: $('revision-ladder'),
      transport: $('live-transport'),
      follow: $('live-follow'),
      dial: $('fit-dial'),
      caption: $('model-caption'),
    },
    cardActions: (step) => markTool.resultActions(step),
    onStepsChanged: () => {
      if (!live.hasSteps()) {
        renderNarration();
        renderThinking();
        renderRevisionStrip();
      }
      // New scored revisions bring new ink distances for the tiles.
      if (state.view) renderStrip();
    },
  });

  // Mark and revise (js/mark.js): circle part of the drawing and say what to fix.
  markTool = createMarkTool({
    invoke,
    drawing,
    drawingHost: $('drawing-host'),
    strip: $('strip'),
    context: () => ({ task: state.task, view: state.view, running: isRunning() }),
    onSent: () => {
      loadTask();
      live.poke(state.task);
    },
    onError: (error) => showError(error),
  });

  drawingEmpty = el('div', { class: 'pane-empty', hidden: true });
  $('drawing-host').append(drawingEmpty);
}

// ---------------------------------------------------------------- drawing and model

export async function renderDrawing({ fresh = false } = {}) {
  const view = state.view;
  const page = view?.source_page || null;
  if (!page) {
    drawing.setPage(null, null);
    drawing.setSections([], null);
    fill(drawingEmpty, icon('drawing'),
      el('strong', {}, view ? 'No drawing page' : (state.task || state.pendingOpen) ? 'Opening the run…' : 'No run open'),
      el('p', {}, view ? 'This run did not find a drawing page to read.' : (state.task || state.pendingOpen) ? 'Reading the run folder.' : 'Open a vessel on Home.'));
    drawingEmpty.hidden = false;
    $('drawing-meta').textContent = '';
    setPageKey(null);
    return;
  }
  drawingEmpty.hidden = true;
  $('drawing-meta').textContent = `${page.width} × ${page.height} px`;
  const key = `${state.task}|${page.path}`;
  if (key !== state.pageKey) {
    setPageKey(key);
    drawing.setPage(page, null);
    const task = state.task;
    cachedArtifact('image', task, page.path)
      .then((url) => { if (state.pageKey === key) drawing.setPage(page, url); })
      .catch(showError);
  }
  drawing.setSections(view.sections, state.sectionId, { focus: false });
  if (fresh) drawing.fitSections();
}

export async function renderModel() {
  const view = state.view;
  const meta = $('model-meta');
  if (!view?.model) {
    setModelKey(null);
    meta.textContent = '';
    model.setModel(null, [], {
      emptyTitle: view ? 'No 3D model yet' : (state.task || state.pendingOpen) ? 'Opening the run…' : 'No run open',
      emptyText: !view ? ((state.task || state.pendingOpen) ? 'Reading the run folder.' : 'Open a vessel on Home.')
        : isRunning() ? 'The model appears here when the run builds it.'
          : 'This run stopped before it built a model.',
    });
    return;
  }
  const m = view.model;
  meta.textContent = [
    `${fmt.metres(m.length_m, 2)} × ${fmt.metres(m.beam_m, 2)} × ${fmt.metres(m.depth_m, 2)}`,
    m.volume_m3 !== null ? `${fmt.decimal(m.volume_m3, 1)} m³` : null,
  ].filter(Boolean).join(' · ');
  meta.title = `Length × beam × depth · volume: ${meta.textContent}`;
  const stations = view.sections.map((s) => ({ id: s.id, x_m: s.x_m }));
  const guessedRanges = guessedXRanges(view.sections, m.length_m);
  const key = `${state.task}|${view.revision}|${m.stl_path}|${stations.map((s) => s.x_m).join(',')}|${JSON.stringify(guessedRanges)}`;
  if (key === state.modelKey) {
    model.setSelected(state.sectionId);
    return;
  }
  const sameTask = state.modelKey?.startsWith(`${state.task}|`);
  setModelKey(key);
  try {
    const buffer = await cachedArtifact('stl', state.task, m.stl_path);
    if (state.modelKey !== key) return;
    model.setModel(buffer, stations, { keepCamera: sameTask, lengthM: m.length_m, guessedRanges });
    model.setSelected(state.sectionId);
  } catch (error) {
    model.setModel(null, [], { emptyTitle: 'Model file missing', emptyText: error.message });
  }
}

// ---------------------------------------------------------------- layout: view switch and splitter

const stage = $('stage');

export function setLayout(layout) {
  stage.dataset.view = layout;
  prefs.set('layout', layout);
  for (const button of $('view-switch').querySelectorAll('button')) {
    button.setAttribute('aria-checked', String(button.dataset.view === layout));
  }
}

export function setSplit(fraction) {
  const clamped = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, fraction));
  stage.style.setProperty('--split', clamped.toFixed(3));
  $('splitter').setAttribute('aria-valuenow', String(Math.round(clamped * 100)));
  prefs.set('split', clamped);
}

/** Above this the app does not load a whole-vessel GLB (the same limit as the backend). */
const MAX_GLB_BYTES = 64 * 1024 * 1024;

/**
 * Show the run's whole-vessel model (GLB) in the 3D view instead of the hull, with `part`
 * tinted. STEP files are never loaded; a GLB over the limit is refused with a plain reason.
 */
export async function showWholeVessel(part) {
  const info = state.view?.whole_vessel_model;
  if (!info) return;
  if (!info.loadable || info.bytes > MAX_GLB_BYTES) {
    showError(new Error(`The whole-vessel model is ${fmt.bytes(info.bytes)}, more than the ${fmt.bytes(MAX_GLB_BYTES)} the app shows. Open the part STEP files in your CAD program.`));
    return;
  }
  setVesselTab('run');
  if (!model.showsWholeVessel) {
    const task = state.task;
    await runAction('Loading the whole-vessel model…', async () => {
      const buffer = await cachedArtifact('model', task, info.glb_path);
      if (task === state.task) await model.setWholeVessel(buffer);
      await showStructure(task);
    });
  }
  // The space list says why it is empty from the run's tank parts.
  const tanks = (state.view?.components || []).filter((component) => component.op === 'tank');
  model.setSpacesContext({ tankParts: tanks.length, builtTanks: tanks.filter((tank) => tank.built).length });
  $('hull-only').hidden = !model.showsWholeVessel;
  setPartOutline(part);
}

/**
 * Add the run's steel structure (structure/<stem>_structure.glb, see run_tables.rs) to the whole
 * vessel shown. A run without one, or one over the GLB limit, shows the vessel without steel.
 */
async function showStructure(task) {
  const file = state.view?.structure_files?.find((f) => f.role === 'structure_model');
  if (!file || file.bytes > MAX_GLB_BYTES) return;
  const buffer = await cachedArtifact('model', task, file.path);
  if (task === state.task) await model.setStructure(buffer);
}

/** Outline one part in the 3D view (null hides it); the 3D pane offers Hide outline. */
export function setPartOutline(part) {
  const box = part?.bbox_m || null;
  model.setHighlightBox(box);
  model.highlightPart(part?.id || null);
  const button = $('clear-outline');
  button.hidden = !box;
  button.title = box ? `Hide the outline of ${part.label}` : '';
}

/** The stacked layout in a narrow stage, and the splitter. */
export function installLayout() {
  new ResizeObserver(() => {
    const stacked = stage.clientWidth < STACK_BELOW_PX;
    stage.classList.toggle('stacked', stacked);
    $('splitter').setAttribute('aria-orientation', stacked ? 'horizontal' : 'vertical');
  }).observe(stage);
  const splitter = $('splitter');
  splitter.setAttribute('aria-valuemin', String(SPLIT_MIN * 100));
  splitter.setAttribute('aria-valuemax', String(SPLIT_MAX * 100));
  splitter.addEventListener('pointerdown', (event) => {
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add('dragging');
    const move = (e) => {
      const rect = stage.getBoundingClientRect();
      const stacked = stage.classList.contains('stacked');
      setSplit(stacked ? (e.clientY - rect.top) / rect.height : (e.clientX - rect.left) / rect.width);
    };
    const stop = () => {
      splitter.classList.remove('dragging');
      splitter.removeEventListener('pointermove', move);
      splitter.removeEventListener('pointerup', stop);
    };
    splitter.addEventListener('pointermove', move);
    splitter.addEventListener('pointerup', stop);
  });
  splitter.addEventListener('keydown', (event) => {
    const current = Number(getComputedStyle(stage).getPropertyValue('--split')) || 0.56;
    const delta = { ArrowLeft: -0.04, ArrowUp: -0.04, ArrowRight: 0.04, ArrowDown: 0.04 }[event.key];
    if (delta) {
      event.preventDefault();
      setSplit(current + delta);
    }
  });
  splitter.addEventListener('dblclick', () => setSplit(0.56));
}

/** Pane buttons: whole vessel, outline, zoom, model reset and the layout switch. */
export function installWorkspaceControls() {
  $('hull-only').addEventListener('click', async () => {
    await model.setWholeVessel(null);
    $('hull-only').hidden = true;
  });
  $('clear-outline').addEventListener('click', () => setPartOutline(null));
  $('zoom-in').addEventListener('click', () => { live.userMovedCamera(); drawing.zoomIn(); });
  $('zoom-out').addEventListener('click', () => { live.userMovedCamera(); drawing.zoomOut(); });
  $('zoom-fit').addEventListener('click', () => { live.userMovedCamera(); drawing.fitPage(); });
  $('model-reset').addEventListener('click', () => model.resetView());
  $('view-switch').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-view]');
    if (button) setLayout(button.dataset.view);
  });
}
