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
import { createGaPanel } from './ga_panel.js';
import { baseName, createSourceController, createSourceView, sourceForSheet, sourceOf, summaryOf } from './provenance.js';
import { capacityRowOf } from './tanks.js';
import { renderThinking, detailsAreOpen, onDetailsChange, showPartCard } from './inspector.js';
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
/** The source view: the sheet a part came from, beside the 3D model (js/provenance.js). */
let sources;
/** The GA reading of a run (ga_panel.js), shown in the 3D pane when the run has one. */
let gaPanel;

/** A part for the source view; a steel group carries its member ids (their records show). */
function partItem(id) {
  return { kind: 'part', id, members: model?.steelMembersOf(id) || null };
}

/** Create the panes. Their callbacks reach the rest of the run view only after start. */
export function createWorkspace() {
  evidence = createEvidenceCard({
    pageUrl: evidencePageUrl,
    pageSize: () => state.view?.source_page || null,
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
    // The source view follows the pointer in 3D (after a short pause) and the selected part.
    onItemHover: (item) => sources?.hover(item),
    onPartPick: (id) => sources?.select(id ? partItem(id) : null),
    // What the run knows of a part, for its fact card in 3D: the capacity plan row of a tank, the
    // part record, and the source it was read from (the drawing opens beside the model).
    partContext: (id) => {
      const component = state.view?.components?.find((part) => part.id === id) || null;
      const basis = component?.arguments?.find((argument) => argument.basis)?.basis;
      const summary = summaryOf(sourceOf(state.view, { kind: 'part', id })?.record);
      const source = component && (basis || component.view || summary.tone !== 'none')
        ? {
          label: [summary.title, basis, component.view ? `${component.view} view` : null].filter(Boolean).join(' · '),
          open: () => {
            setLayout('split');
            sources.select(partItem(id));
          },
        }
        : null;
      return { row: capacityRowOf(state.view?.capacity_plan, id), component, source };
    },
    // The picked part's card shows in the details column when it is open, else docked in 3D.
    cardInColumn: () => detailsAreOpen(),
    onCard: (card) => showPartCard(card),
    // The card and the hover label keep clear of the source lines and the "best guess" label.
    avoidRects: () => [...document.querySelectorAll('.source-links path, .source-links g')].map((node) => node.getBoundingClientRect()),
  });
  onDetailsChange(() => model.refreshCard());

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
      watchAgainHost: $('run-bar-end'),
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

  const sourceView = createSourceView({
    stage: $('stage'),
    pane: $('drawing-host').parentElement,
    anchorOf: (item) => model.anchorOf(item),
    loadSheet,
    labelOf: (id) => sourceOf(state.view, { kind: 'part', id })?.label || id,
  });
  // Both panes must show: the line runs from the part to its sheet.
  sources = createSourceController({ view: () => state.view, sourceView, canShow: () => $('stage').dataset.view === 'split' });
  gaPanel = createGaPanel({ onHover: (item) => sources.hover(item), onSelect: (item) => sources.select(item) });
  $('model-host').parentElement.append(gaPanel.element);
  // New or moved source lines: the docked card and the hover label move off them.
  const links = $('stage').querySelector('.source-links');
  if (links) new MutationObserver(() => model.placeOverlays()).observe(links, { childList: true });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !sourceView.element.hidden) sources.dismiss();
  });
}

// ---------------------------------------------------------------- source sheets

/** Sheet images of the source view by task, file and page; the source list by task. */
const sheetImages = new Map();
const sourceLists = new Map();

/** One sheet of the run as `{ url, width, height }`, or null when the run does not have it. */
function loadSheet(sheet, page) {
  const task = state.task;
  const key = `${task}|${sheet}|${page}`;
  if (!sheetImages.has(key)) {
    sheetImages.set(key, fetchSheet(task, sheet, page).catch((failure) => {
      sheetImages.delete(key);
      throw failure;
    }));
  }
  return sheetImages.get(key);
}

async function fetchSheet(task, sheet, page) {
  // The page the drawing pane reads is already loaded.
  const current = state.view?.source_page;
  if (current && baseName(current.path) === baseName(sheet)) {
    return { url: await cachedArtifact('image', task, current.path), width: current.width, height: current.height };
  }
  if (!sourceLists.has(task)) sourceLists.set(task, invoke('list_sources', { task }));
  const listing = await sourceLists.get(task);
  const source = sourceForSheet(listing.sources || [], sheet);
  if (!source || !source.previewable) return null;
  const shown = await invoke('read_source_page', { task, source_id: source.id, page, size: 'full' });
  return shown.base64 ? { url: `data:${shown.mime};base64,${shown.base64}`, width: shown.width, height: shown.height } : null;
}

// ---------------------------------------------------------------- drawing and model

let sourcesTask = null;

export async function renderDrawing({ fresh = false } = {}) {
  const view = state.view;
  if (state.task !== sourcesTask) {
    // Another run: its parts and sheets are other ones.
    sourcesTask = state.task;
    sources.dismiss();
    sourceLists.clear();
    sheetImages.clear();
  }
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
  gaPanel.set(view?.ga_reading || null);
  if (!view?.model && view?.ga_reading) {
    setModelKey(null);
    meta.textContent = 'GA reading';
    model.setModel(null, [], { emptyTitle: '', emptyText: '' });
    return;
  }
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
  if (layout !== 'split') sources?.dismiss();
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
  // The run's caption names the build of the section lines, not the whole vessel (live.js).
  $('model-caption').hidden = model.showsWholeVessel || !$('model-caption').textContent;
  setPartOutline(part);
}

/**
 * The web demo's first view of a run (static/backend.js `view.demo`): the whole vessel, the
 * section lines off and the hull see-through when the demo says so. The Section lines and
 * See-through switches change them back.
 *
 * `prepareDemoView` runs before the run view draws: until the whole vessel shows, the 3D pane
 * shows only "Loading the 3D model…", never the hull of the section lines or the lines.
 * `showDemoView` loads the whole vessel and removes the cover.
 */
function demoOpensWholeVessel(demo) {
  return demo?.whole_vessel_first === true && Boolean(state.view?.whole_vessel_model);
}

export function prepareDemoView(demo) {
  if (!demoOpensWholeVessel(demo)) return;
  if (demo.section_lines === false) model.setSectionLinesShown(false);
  const pane = $('model-host').closest('.pane-model');
  pane.classList.add('is-demo-loading');
  if (!pane.querySelector('.demo-model-loading')) {
    pane.append(el('p', { class: 'demo-model-loading', role: 'status' }, 'Loading the 3D model…'));
  }
}

export async function showDemoView(demo) {
  if (!demoOpensWholeVessel(demo)) return;
  try {
    await showWholeVessel(null);
    if (demo.see_through === true) model.setSeeThroughHull(true);
  } finally {
    const pane = $('model-host').closest('.pane-model');
    pane.classList.remove('is-demo-loading');
    pane.querySelector('.demo-model-loading')?.remove();
  }
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
    $('model-caption').hidden = !$('model-caption').textContent;
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
