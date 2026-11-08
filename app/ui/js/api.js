// The only module that talks to a backend. Every command, every live update, the file and
// folder pickers and dropped files go through here, so the same UI runs in Tauri, as a web
// app, or on mocks.
//
// Transport selection, in order:
//   1. Tauri:  window.__TAURI__ is present (Tauri 2 with `withGlobalTauri`).
//   2. HTTP:   <meta name="marinaframe-backend" content="http"> is present.
//              Commands: POST /api/<command> with a JSON body; errors use a non-2xx status
//              and the spec's { code, message } body. Live updates: Server-Sent Events at
//              /api/events, one `task-changed` event per change with { task, sequence }.
//              Uploads (the browser has no paths): POST /api/upload_spec?name= gives
//              { spec_path }; POST /api/upload_drawing?name= gives { path }.
//   3. Mock:   neither of the above. Fixtures from mock/fixtures.json.
//
// Arguments follow docs/APP_SPEC.md exactly (snake_case keys such as `after_sequence`).

const MOCK_FIXTURES_URL = 'mock/fixtures.json';
const MOCK_FILES_URL = 'mock/files/';
const MOCK_DISMISSED_KEY = 'marinaframe.mock.dismissed-notices';
const MOCK_SETTINGS_KEY = 'marinaframe.mock.settings';
/** The mock has no file system. Its pickers return paths under this folder. */
const MOCK_PICK_FOLDER = '/Users/demo/MarinaFrame/examples';

/** File types the run spec picker accepts (start_run takes one of these). */
export const SPEC_EXTENSIONS = ['json', 'toml', 'yaml', 'yml'];
/** File types of a drawing set (prepare_intake takes these; app/core/src/intake.rs). */
export const DRAWING_EXTENSIONS = ['pdf', 'png', 'tif', 'tiff', 'jpg', 'jpeg'];
/** Delay between mock events for the running task, to imitate a live run. */
const MOCK_PLAYBACK_MS = 4000;
/** With ?mocklive, the mock live run shows one more step this often. */
const MOCK_LIVE_STEP_MS = 2500;

/** A backend error in the spec's shape. `message` is plain language for people. */
export class BackendError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function toBackendError(raw) {
  if (raw instanceof BackendError) return raw;
  if (raw && typeof raw === 'object' && 'message' in raw) {
    return new BackendError(raw.code || 'error', String(raw.message));
  }
  if (typeof raw === 'string') return new BackendError('error', raw);
  return new BackendError('error', 'The app could not complete this action.');
}

// ---------------------------------------------------------------- Tauri transport

function tauriTransport(tauri) {
  return {
    name: 'tauri',
    async invoke(command, args = {}) {
      try {
        return await tauri.core.invoke(command, args);
      } catch (raw) {
        throw toBackendError(raw);
      }
    },
    onTaskChanged(handler) {
      let stop = () => {};
      tauri.event.listen('task-changed', (event) => handler(event.payload)).then((unlisten) => {
        stop = unlisten;
      });
      return () => stop();
    },
    canPick: () => Boolean(tauri.dialog?.open),
    async pickSpecFile({ defaultPath } = {}) {
      return openDialog({
        title: 'Choose a run spec',
        defaultPath,
        filters: [{ name: 'Run spec', extensions: SPEC_EXTENSIONS }],
      });
    },
    pickFolder({ title, defaultPath } = {}) {
      return openDialog({ title, defaultPath, directory: true });
    },
    pickFile({ title, defaultPath } = {}) {
      return openDialog({ title, defaultPath });
    },
    async pickDrawingFiles() {
      if (!tauri.dialog?.open) return [];
      const picked = await tauri.dialog.open({
        title: 'Choose a drawing set',
        multiple: true,
        filters: [{ name: 'Drawings', extensions: DRAWING_EXTENSIONS }],
      });
      if (!picked) return [];
      return Array.isArray(picked) ? picked : [picked];
    },
    onFileDrop({ enter, leave, drop }) {
      // Tauri takes file drops from the window and sends the full paths as events.
      tauri.event.listen('tauri://drag-enter', () => enter());
      tauri.event.listen('tauri://drag-leave', () => leave());
      tauri.event.listen('tauri://drag-drop', (event) => drop(event.payload?.paths || []));
    },
  };

  // The dialog plugin is optional. Without it the caller asks for a typed path.
  async function openDialog(options) {
    if (!tauri.dialog?.open) return null;
    const picked = await tauri.dialog.open({ multiple: false, ...options });
    return typeof picked === 'string' ? picked : null;
  }
}

/**
 * File drops in a plain browser. The browser gives the file, not its path, so `toPath`
 * turns each dropped file into a path for start_run (an upload, or a mock path).
 */
function listenForBrowserDrops({ enter, leave, drop }, toPath) {
  let depth = 0; // dragenter and dragleave fire for every child element
  const hasFiles = (event) => event.dataTransfer?.types.includes('Files');
  document.addEventListener('dragenter', (event) => {
    if (!hasFiles(event)) return;
    depth += 1;
    if (depth === 1) enter();
  });
  document.addEventListener('dragleave', (event) => {
    if (!hasFiles(event)) return;
    depth = Math.max(0, depth - 1);
    if (depth === 0) leave();
  });
  document.addEventListener('dragover', (event) => {
    if (hasFiles(event)) event.preventDefault();
  });
  document.addEventListener('drop', async (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth = 0;
    const files = [...event.dataTransfer.files];
    drop(await Promise.all(files.map(toPath)));
  });
}

// ---------------------------------------------------------------- HTTP transport

function httpTransport() {
  async function post(path, body, contentType = 'application/json') {
    let response;
    try {
      response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': contentType },
        body,
      });
    } catch {
      throw new BackendError('offline', 'The MarinaFrame server is not reachable.');
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw toBackendError(payload || { code: String(response.status), message: response.statusText });
    return payload;
  }

  return {
    name: 'http',
    invoke(command, args = {}) {
      return post(`/api/${encodeURIComponent(command)}`, JSON.stringify(args));
    },
    onTaskChanged(handler) {
      const source = new EventSource('/api/events');
      source.addEventListener('task-changed', (event) => handler(JSON.parse(event.data)));
      return () => source.close();
    },
    canPick: () => false, // server paths: the settings are typed
    pickSpecFile() {
      return new Promise((resolve, reject) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = SPEC_EXTENSIONS.map((ext) => `.${ext}`).join(',');
        input.addEventListener('change', () => {
          const file = input.files?.[0];
          if (!file) return resolve(null);
          uploadSpec(file).then(resolve, reject);
        });
        input.addEventListener('cancel', () => resolve(null));
        input.click();
      });
    },
    pickFolder: async () => null,
    pickFile: async () => null,
    pickDrawingFiles() {
      return new Promise((resolve, reject) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = true;
        input.accept = DRAWING_EXTENSIONS.map((ext) => `.${ext}`).join(',');
        input.addEventListener('change', () => {
          Promise.all([...(input.files || [])].map(uploadDrawing)).then(resolve, reject);
        });
        input.addEventListener('cancel', () => resolve([]));
        input.click();
      });
    },
    onFileDrop(handlers) {
      listenForBrowserDrops(handlers, (file) => {
        if (isSpecFileName(file.name)) return uploadSpec(file);
        if (isDrawingFileName(file.name)) return uploadDrawing(file);
        return file.name;
      });
    },
  };

  // Upload a spec file; the server stores it and returns the path to pass to start_run.
  async function uploadSpec(file) {
    const result = await post(`/api/upload_spec?name=${encodeURIComponent(file.name)}`, file, 'application/octet-stream');
    return result.spec_path;
  }

  // Upload one drawing file; the server stores it and returns the path for prepare_intake.
  async function uploadDrawing(file) {
    const result = await post(`/api/upload_drawing?name=${encodeURIComponent(file.name)}`, file, 'application/octet-stream');
    return result.path;
  }
}

// ---------------------------------------------------------------- Mock transport

function readStored(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be blocked; the mock then forgets between reloads.
  }
}

function blobToBase64(blob) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(blob);
  });
}

/** What the mock's "Choose files" picks: a two-page PDF and a low-resolution scan. */
const MOCK_DRAWING_SET = ['/Users/demo/Downloads/survey-launch-lines.pdf', '/Users/demo/Downloads/survey-launch-sections.tif'];
/** The mock page image (mock/files/page-1.png) in pixels. */
const MOCK_PAGE = { width: 1600, height: 1000 };

/**
 * An IntakePreview for `files`, shaped like the worker's: a PDF gives a lines page (body plan,
 * title block) and a cover page with no view; a raster gives a 150 dpi scan whose view the
 * code is unsure of.
 */
function mockIntakePreview(files, thumbnail, aiActive) {
  const pages = [];
  const page = (file, fields) => {
    const fileName = file.split('/').pop();
    pages.push({
      page_id: `p${pages.length + 1}`, file, file_name: fileName, page_index: 0,
      width_px: MOCK_PAGE.width, height_px: MOCK_PAGE.height,
      thumbnail_png_base64: thumbnail, thumbnail_scale: 1, warnings: [], skip: false, ...fields,
    });
  };
  const region = (id, label, confidence, box, evidence) => ({ region_id: id, label, confidence, region_px: box, evidence });
  for (const file of files) {
    if (file.toLowerCase().endsWith('.pdf')) {
      page(file, {
        kind: 'pdf', dpi: 200, dpi_source: 'pdf_render',
        regions: [
          region('r1', 'body_plan', 0.86, [120, 240, 1480, 830], 'Three framed curve groups share a centre line.'),
          region('r2', 'title_block', 0.74, [1180, 860, 1560, 960], 'Small boxed text at the lower right.'),
        ],
      });
      page(file, {
        kind: 'pdf', page_index: 1, dpi: 200, dpi_source: 'pdf_render',
        regions: [region('r1', 'other', 0.18, [40, 40, 1560, 960], 'No separate ink groups.')],
        warnings: [{ code: 'no_view_found', message: 'No drawing view found on this page.' }],
      });
    } else {
      page(file, {
        kind: 'raster', dpi: 150, dpi_source: 'file_metadata',
        regions: [region('r1', 'profile', 0.41, [140, 250, 1470, 820], 'One wide ink group; could be a profile or a body plan.')],
        warnings: [{ code: 'low_dpi', message: 'Scan 150 dpi: lines may be read less exactly.' }],
      });
    }
  }
  const warnings = aiActive ? [] : [{ code: 'ai_off', message: 'AI drafting is off. A drawing set without a spec needs the AI to read stations and scale.' }];
  return { intake_id: `intake-${Date.now()}`, pages, warnings, render_dpi: 200, particulars: { vessel_name: '' }, ai_active: aiActive };
}

/** File suffixes and sizes (bytes) the mock "writes" for each export. */
const MOCK_EXPORT_FILES = {
  step: [['model.step', 4_812_330]],
  stl: [['model.stl', 2_160_084]],
  offsets: [['offsets.csv', 3_912]],
  hydrostatics: [['hydrostatics.json', 1_731], ['hydrostatics.csv', 1_452]],
  report: [['report.pdf', 486_220]],
  package: [['package.zip', 6_903_118]],
};

function mockTransport() {
  const listeners = new Set();
  let fixtures = null;
  let playbackStarted = false;

  async function load() {
    if (!fixtures) {
      const response = await fetch(MOCK_FIXTURES_URL);
      fixtures = await response.json();
      shiftTimesToNow(fixtures);
    }
    return fixtures;
  }

  // Fixtures use fixed times; move them so the newest run is "now" and the list reads naturally.
  function shiftTimesToNow(data) {
    const newest = Math.max(...data.tasks.map((t) => t.updated_ms));
    const offset = Date.now() - newest;
    for (const task of data.tasks) task.updated_ms += offset;
    for (const view of Object.values(data.views)) view.summary.updated_ms += offset;
    for (const events of Object.values(data.events)) for (const e of events) e.time_ms += offset;
  }

  const clone = (value) => JSON.parse(JSON.stringify(value));
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function requireTask(data, task) {
    const view = data.views[task];
    if (!view) throw new BackendError('task_not_found', 'This run folder no longer exists.');
    return view;
  }

  function emit(task, sequence) {
    for (const handler of listeners) handler({ task, sequence });
  }

  // Plays the scripted events of the running task, then marks it finished.
  async function startPlayback(data) {
    if (playbackStarted || !data.playback) return;
    playbackStarted = true;
    const { task, events: script, finished_view: finishedFrom } = data.playback;
    for (const step of script) {
      await pause(MOCK_PLAYBACK_MS);
      const events = data.events[task];
      const sequence = events[events.length - 1].sequence + 1;
      events.push({ sequence, time_ms: Date.now(), text: step.text, kind: step.kind });
      applyPlaybackStep(data, task, finishedFrom, step);
      emit(task, sequence);
    }
  }

  function applyPlaybackStep(data, task, finishedFrom, step) {
    const view = data.views[task];
    const finished = data.views[finishedFrom];
    view.summary.updated_ms = Date.now();
    if (step.section) {
      const index = view.sections.findIndex((s) => s.id === step.section);
      view.sections[index] = clone(finished.sections[index]);
    }
    if (step.kind === 'build') view.model = clone(finished.model);
    if (step.kind === 'check') view.checks = clone(finished.checks);
    if (step.kind === 'finish') {
      view.summary.status = 'needs_review';
      view.revision = 'r1';
      view.evidence = clone(finished.evidence);
      view.evidence.revision_id = 'r1';
    }
    Object.assign(data.tasks.find((t) => t.task === task), view.summary);
  }

  // ---- Live steps. With ?mocklive in the page address, the fixture's live run streams in
  // as if it were running: one step every MOCK_LIVE_STEP_MS, with a request in flight
  // between steps. Otherwise it is a finished run to replay.
  // A run started from the intake streams its live steps the same way.
  let liveStream = new URLSearchParams(location.search).has('mocklive');
  // With ?mocknokey, the mock has no model key (the intake then cannot start).
  const mockNoKey = new URLSearchParams(location.search).has('mocknokey');
  let liveStreamStarted = 0;

  /** Steps of the task's live run that exist "now", and whether the run is still going. */
  function liveSnapshot(data, task) {
    const run = data.live?.[task];
    if (!run) return null;
    if (!liveStream) return { run, steps: run.steps, finished: run.finished };
    if (!liveStreamStarted) {
      liveStreamStarted = Date.now();
      scheduleLiveStream(data, task);
    }
    const shown = Math.min(run.steps.length, 1 + Math.floor((Date.now() - liveStreamStarted) / MOCK_LIVE_STEP_MS));
    return { run, steps: run.steps.slice(0, shown), finished: shown === run.steps.length };
  }

  function scheduleLiveStream(data, task) {
    const total = data.live[task].steps.length;
    for (let i = 1; i < total; i += 1) {
      setTimeout(() => emit(task, data.live[task].steps[i].sequence), i * MOCK_LIVE_STEP_MS + 20);
    }
  }

  function isLiveStreaming(data, task) {
    const snapshot = liveStream ? liveSnapshot(data, task) : null;
    return Boolean(snapshot && !snapshot.finished);
  }

  // ---- Exports: the files the mock "wrote" in this page session.
  const mockExports = new Map();
  const mockRevision = (revision) => `r${String(revision).replace(/^r/, '').padStart(4, '0')}`;
  function mockExportResult(task, revision) {
    const order = ['step', 'stl', 'offsets', 'hydrostatics', 'report', 'package', 'manifest'];
    const folderRevision = mockRevision(revision);
    const files = [...(mockExports.get(`${task}|${folderRevision}`) || [])]
      .sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
    return {
      folder: `${task}/exports/${folderRevision}`,
      revision: folderRevision,
      files,
      not_built: [],
      stamp: 'Draft hull model from MarinaFrame. Not approved for construction.',
      engineering_approved: false,
    };
  }

  /** Sections whose panel a marked region touches. */
  function touchedSections(view, region) {
    const points = region?.page_px_box ? [region.page_px_box.slice(0, 2), region.page_px_box.slice(2)] : region?.lasso_px || [];
    if (!points.length) return [];
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const [l, t, r, b] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    return view.sections.filter((s) => s.roi_px[0] < r && l < s.roi_px[2] && s.roi_px[1] < b && t < s.roi_px[3]).map((s) => s.id);
  }

  /** Append scripted live steps one by one (each after its delay), then call `done`. */
  async function playRevisionSteps(data, task, script, done) {
    const run = data.live[task];
    for (const [index, { delay, step, inFlight }] of script.entries()) {
      await pause(delay);
      const last = run.steps[run.steps.length - 1];
      const sequence = last.last_sequence + 1;
      const time = last.time_ms + Math.max(delay, 300);
      run.steps.push({ notes: null, revision: null, images: [], model_ms: null, cost_usd: null, repeat_of: null, count: 1,
        ...step, sequence, last_sequence: sequence, time_ms: time });
      run.mock_in_flight = inFlight ? { kind: inFlight, operation: null, since_ms: time } : null;
      if (index === script.length - 1) done();
      // A ledger event too, so the app reads the run's status again.
      const events = data.events[task];
      const eventSequence = events[events.length - 1].sequence + 1;
      events.push({ sequence: eventSequence, time_ms: Date.now(), text: step.title, kind: 'revise' });
      emit(task, eventSequence);
    }
  }

  const commands = {
    async list_tasks(data) {
      startPlayback(data);
      return [...data.tasks]
        .map((t) => (isLiveStreaming(data, t.task) ? { ...t, status: 'running' } : t))
        .sort((a, b) => b.updated_ms - a.updated_ms);
    },
    async get_live_steps(data, { task, after_sequence }) {
      requireTask(data, task);
      const snapshot = liveSnapshot(data, task);
      if (!snapshot) {
        return { steps: [], last_sequence: 0, started_ms: 0, elapsed_ms: 0, in_flight: null, finished: true };
      }
      const { run, steps, finished } = snapshot;
      const last = steps[steps.length - 1];
      const next = finished ? null : run.steps[steps.length];
      return clone({
        steps: steps.filter((s) => s.last_sequence > after_sequence),
        last_sequence: last.last_sequence,
        started_ms: run.started_ms,
        elapsed_ms: last.time_ms,
        in_flight: run.mock_in_flight || (next ? { kind: next.actor === 'model' ? 'model' : 'worker', operation: next.tool?.tool || null, since_ms: last.time_ms } : null),
        finished,
      });
    },
    async get_hull_sections(data, { task, revision }) {
      requireTask(data, task);
      const builds = data.hull_sections?.[task] || {};
      const found = builds[revision] || Object.values(builds).find((b) => b.path === revision);
      if (!found) throw new BackendError('revision_not_found', 'This build is not in the run folder.');
      return clone(found);
    },
    async get_task(data, { task }) {
      const view = clone(requireTask(data, task));
      if (isLiveStreaming(data, task)) view.summary.status = 'running';
      const dismissed = new Set(readStored(MOCK_DISMISSED_KEY, []));
      view.notices = view.notices.filter((n) => !dismissed.has(n.id));
      return view;
    },
    async get_events(data, { task, after_sequence }) {
      requireTask(data, task);
      return clone((data.events[task] || []).filter((e) => e.sequence > after_sequence));
    },
    async read_artifact(_data, { path }) {
      const name = path.split('/').pop();
      const response = await fetch(MOCK_FILES_URL + encodeURIComponent(name));
      if (!response.ok) throw new BackendError('artifact_missing', 'This file is not in the run folder.');
      const blob = await response.blob();
      const mime = name.endsWith('.stl') ? 'model/stl' : blob.type || 'image/png';
      return { mime, base64: await blobToBase64(blob) };
    },
    async start_run(_data, { spec_path }) {
      await pause(600);
      throw new BackendError('mock_mode', `Runs cannot start in the preview. The app would start ${spec_path.split('/').pop()}.`);
    },
    async cancel_task(data, { task }) {
      const view = requireTask(data, task);
      await pause(500);
      view.summary.status = 'cancelled';
      Object.assign(data.tasks.find((t) => t.task === task), view.summary);
      return { ok: true };
    },
    async resume_task(data, { task }) {
      requireTask(data, task);
      await pause(500);
      return { ok: true };
    },
    // Mark and revise: the focused pass streams in as live steps (mark, crop, model edit,
    // keep-rule result). The preview keeps the edit unless the instruction says "fine" or
    // "wrong", so both results and "Keep anyway" can be seen.
    async revise_region(data, { task, request }) {
      const view = requireTask(data, task);
      const run = data.live?.[task];
      if (!run || view.summary.policy !== 'live') throw new BackendError('revision_requires_live_draft_run', 'Mark and revise needs a run that uses the model.');
      const instruction = String(request?.instruction || '').trim();
      if (!instruction || instruction.length > 500) throw new BackendError('revision_instruction', 'Say what to fix in up to 500 characters.');
      const sections = request.target_section_ids?.length ? request.target_section_ids : touchedSections(view, request.region);
      const section = sections[0] || view.sections[0].id;
      const kept = !/fine|wrong/i.test(instruction);
      const revisionId = `revision-mock${run.steps.length}`;
      const mark = request.region?.page_px_box
        ? { shape: 'box', tone: 'person', points_px: [request.region.page_px_box.slice(0, 2), request.region.page_px_box.slice(2)] }
        : request.region?.lasso_px ? { shape: 'polyline', tone: 'person', points_px: [...request.region.lasso_px, request.region.lasso_px[0]] } : null;
      const roi = view.sections.find((s) => s.id === section)?.roi_px || null;
      const resumeStatus = view.summary.status;
      const target = (id) => ({ kind: 'section', id });
      const script = [
        { delay: 0, inFlight: 'worker', step: { kind: 'revise', actor: 'person', title: 'Marked for revision', text: instruction, targets: sections.map(target),
          attention_px: mark ? null : roi, marks: mark ? [mark] : [], tool: null } },
        { delay: 900, inFlight: 'model', step: { kind: 'look', actor: 'code', title: 'Cropped the marked region for the model', text: '',
          targets: [], attention_px: roi, marks: roi ? [{ shape: 'box', tone: 'attention', points_px: [roi.slice(0, 2), roi.slice(2)] }] : [],
          tool: { tool: 'view_region', duration_ms: 310, state: 'ok', text: '1 view' } } },
        { delay: 2600, step: { kind: 'propose_section', actor: 'model', title: `Drew section ${section}`,
          text: `The person asked: “${instruction.slice(0, 80)}”. I redrew ${section} from the marked ink, with the turn of the bilge where the line is drawn.`,
          targets: [target(section)], attention_px: roi, marks: [], model_ms: 2400, cost_usd: 0.0012,
          tool: { tool: 'propose_section', duration_ms: 820, state: 'ok', kept, text: kept ? 'Kept: the fit improved' : 'Not kept: the fit got worse' } } },
        { delay: 900, step: { kind: 'revise', actor: 'code', title: kept ? 'Kept, fit +0.012' : 'Not kept: worse by 0.004', text: '',
          targets: [target(section)], attention_px: null, marks: [],
          tool: { tool: 'keep rule', duration_ms: null, state: 'ok', kept, text: kept ? 'Kept, fit +0.012' : 'Combined fit 0.931 -> 0.927: needs +0.002' },
          mark_revision: { revision_id: revisionId, outcome: kept ? 'kept' : 'not_kept', fit_change: kept ? 0.012 : 0, not_kept_fit_change: kept ? null : -0.004, can_keep_anyway: !kept, operator_forced: false } } },
      ];
      await pause(400);
      run.finished = false;
      view.summary.status = 'running';
      playRevisionSteps(data, task, script, () => {
        view.summary.status = resumeStatus;
        run.finished = true;
      });
      return { ok: true };
    },
    async force_keep_revision(data, { task, revision_id }) {
      const view = requireTask(data, task);
      const run = data.live?.[task];
      const result = run?.steps.find((s) => s.mark_revision?.revision_id === revision_id);
      if (!result?.mark_revision.can_keep_anyway) throw new BackendError('revision_has_no_unkept_edit', 'Every edit of this revision is already kept.');
      await pause(400);
      const resumeStatus = view.summary.status;
      run.finished = false;
      view.summary.status = 'running';
      playRevisionSteps(data, task, [{ delay: 700, step: { kind: 'revise', actor: 'person', title: 'Kept anyway',
        text: '', targets: [], attention_px: null, marks: [], tool: null } }], () => {
        result.mark_revision = { ...result.mark_revision, can_keep_anyway: false, operator_forced: true };
        result.last_sequence = run.steps[run.steps.length - 1].sequence;
        view.summary.status = resumeStatus;
        run.finished = true;
      });
      return { ok: true };
    },
    async choose_line(data, { task, section_id, candidate_id }) {
      const view = requireTask(data, task);
      await pause(1400);
      const section = view.sections.find((s) => s.id === section_id);
      const candidate = section?.candidates.find((c) => c.id === candidate_id);
      if (!candidate?.selectable) throw new BackendError('not_selectable', 'This line cannot be used for the hull.');
      const guess = section.guess;
      for (const c of section.candidates) c.chosen = c.id === candidate_id;
      section.state = 'chosen';
      section.guess = null;
      section.reason = `You picked the ${candidate.label.toLowerCase()}.`;
      let text = `Section at ${section.x_m.toFixed(1)} m: you picked the ${candidate.label.toLowerCase()}. Rebuilt and checked again`;
      if (guess) {
        text = guess.chosen_candidate_id === candidate_id
          ? `You confirmed the line for ${section.x_m.toFixed(1)} m`
          : `You picked another line for ${section.x_m.toFixed(1)} m`;
        const draft = view.draft;
        draft.resolved.push({
          ...guess,
          resolution: guess.chosen_candidate_id === candidate_id ? 'confirmed' : 'replaced',
          resolved_candidate_id: candidate_id,
        });
        draft.guesses = draft.guesses.filter((g) => g.id !== guess.id);
        view.notices = view.notices.filter((n) => !n.id.startsWith('draft-guesses:'));
        if (draft.guesses.length) {
          // Same text rules as the backend banner.
          const open = draft.guesses.length;
          const stuck = draft.guesses.filter((g) => g.kind !== 'best_candidate').length;
          const noun = open === 1 ? 'guess' : 'guesses';
          const text2 = stuck === 0
            ? `Draft: ${open} ${noun} to check. Confirm each guessed line or pick another. The app then rebuilds and checks the model.`
            : `Draft: ${open} ${noun} to check. No line could be read there, so there is nothing to pick and this run stays a draft.`;
          // The mock only ever leaves guesses that have no line (stuck === open).
          view.notices.push({ id: `draft-guesses:${open}`, tone: 'warning', text: text2 });
        } else {
          view.draft = null;
          view.summary.status = 'needs_review';
          Object.assign(data.tasks.find((t) => t.task === task), view.summary);
        }
      }
      if (!view.sections.some((s) => s.state === 'declined') && view.summary.status === 'declined') {
        view.summary.status = 'needs_review';
        Object.assign(data.tasks.find((t) => t.task === task), view.summary);
      }
      const events = data.events[task];
      const sequence = events[events.length - 1].sequence + 1;
      events.push({ sequence, time_ms: Date.now(), text, kind: 'choose' });
      view.summary.updated_ms = Date.now();
      emit(task, sequence);
      return { ok: true };
    },
    async get_settings(data) {
      return { ...data.settings, ...readStored(MOCK_SETTINGS_KEY, {}) };
    },
    async get_default_settings(data) {
      return { ...data.default_settings };
    },
    async set_settings(data, settings) {
      writeStored(MOCK_SETTINGS_KEY, settings);
      return { ...data.settings, ...settings };
    },
    async get_ai_status(data) {
      const settings = { ...data.settings, ...readStored(MOCK_SETTINGS_KEY, {}) };
      const enabled = settings.ai_drafting !== false;
      const keyFound = !mockNoKey;
      return { enabled, key_found: keyFound, active: enabled && keyFound,
               key_file: '/Users/demo/.config/marinaframe/opencode-go-keys.txt' };
    },
    async dismiss_notice(_data, { id }) {
      const dismissed = new Set(readStored(MOCK_DISMISSED_KEY, []));
      dismissed.add(id);
      writeStored(MOCK_DISMISSED_KEY, [...dismissed]);
      return { ok: true };
    },
    async reset_notices() {
      writeStored(MOCK_DISMISSED_KEY, []);
      return { ok: true };
    },
    async list_datasets(data) {
      return data.datasets;
    },
    async list_exports(data, { task, revision }) {
      requireTask(data, task);
      return mockExportResult(task, revision);
    },
    async export_run(data, { task, revision, outputs }) {
      const view = requireTask(data, task);
      if (!outputs?.length) throw new BackendError('export_outputs', 'Choose at least one export.');
      await pause(900);
      const folderRevision = mockRevision(revision);
      const stem = `${view.summary.name.split(',')[0].replace(/\W+/g, '_')}_${folderRevision}_DRAFT`;
      const written = mockExports.get(`${task}|${folderRevision}`) || [];
      const notBuilt = [];
      const add = (kind, suffix, bytes) => {
        const file = `${stem}_${suffix}`;
        const entry = { kind, file, path: `${task}/exports/${folderRevision}/${file}`, bytes };
        const index = written.findIndex((f) => f.file === file);
        if (index >= 0) written[index] = entry;
        else written.push(entry);
      };
      for (const kind of outputs) {
        // A run without a model has no mesh to copy.
        if (kind === 'stl' && !view.model) {
          notBuilt.push(kind);
          continue;
        }
        for (const [suffix, bytes] of MOCK_EXPORT_FILES[kind]) add(kind, suffix, bytes);
      }
      add('manifest', 'manifest.json', 2310);
      mockExports.set(`${task}|${folderRevision}`, written);
      return { ...mockExportResult(task, revision), not_built: notBuilt };
    },
    async reveal_export(data, { task, path }) {
      requireTask(data, task);
      if (!path?.startsWith(`${task}/exports/`)) throw new BackendError('export_reveal', "That file is not in this run's exports.");
      return { ok: true };
    },
    async prepare_intake(data, { files }) {
      if (!files?.length || files.length > 32) throw new BackendError('intake_files', 'Drop between 1 and 32 drawing files.');
      const wrong = files.find((path) => !isDrawingFileName(path));
      if (wrong) throw new BackendError('intake_file_type', `${wrong.split('/').pop()} is not a drawing. Use PDF, PNG, TIFF or JPEG files.`);
      await pause(900);
      const status = await commands.get_ai_status(data);
      return mockIntakePreview(files, await mockThumbnail(), status.active);
    },
    async start_intake_run(data, { preview }) {
      await pause(700);
      if (!preview.pages.some((page) => !page.skip)) throw new BackendError('intake_no_pages', 'Every page is skipped. Keep at least one page.');
      // The preview has one recorded live run: the new run plays it from the first step.
      const task = Object.keys(data.live || {})[0];
      if (!task) throw new BackendError('mock_mode', 'Runs cannot start in the preview.');
      liveStream = true;
      liveStreamStarted = 0;
      return { task };
    },
  };

  let thumbnail = null;
  async function mockThumbnail() {
    if (!thumbnail) {
      const response = await fetch(`${MOCK_FILES_URL}page-1.png`);
      thumbnail = await blobToBase64(await response.blob());
    }
    return thumbnail;
  }

  return {
    name: 'mock',
    async invoke(command, args = {}) {
      const run = commands[command];
      if (!run) throw new BackendError('unknown_command', `Unknown command ${command}.`);
      return run(await load(), args);
    },
    onTaskChanged(handler) {
      listeners.add(handler);
      return () => listeners.delete(handler);
    },
    // The preview has no file system or dialogs: pickers answer at once with demo paths.
    canPick: () => true,
    async pickSpecFile({ defaultPath } = {}) {
      return `${defaultPath || MOCK_PICK_FOLDER}/spec.json`;
    },
    async pickFolder({ defaultPath } = {}) {
      return defaultPath || '/Users/demo/MarinaFrame/runs';
    },
    async pickFile({ defaultPath } = {}) {
      return defaultPath || '/usr/local/bin/python3';
    },
    async pickDrawingFiles() {
      return MOCK_DRAWING_SET;
    },
    onFileDrop(handlers) {
      listenForBrowserDrops(handlers, async (file) => `/Users/demo/Downloads/${file.name}`);
    },
  };
}

// ---------------------------------------------------------------- Selection

function chooseTransport() {
  if (window.__TAURI__) return tauriTransport(window.__TAURI__);
  if (document.querySelector('meta[name="marinaframe-backend"][content="http"]')) return httpTransport();
  return mockTransport();
}

const transport = chooseTransport();

/** "tauri", "http" or "mock". */
export const transportName = transport.name;

/** Call one backend command. Rejects with BackendError. */
export function invoke(command, args) {
  return transport.invoke(command, args);
}

/** Subscribe to task-changed ({ task, sequence }). Returns an unsubscribe function. */
export function onTaskChanged(handler) {
  return transport.onTaskChanged(handler);
}

/**
 * Ask for a run spec file, starting in `defaultPath` when given. Resolves to a path for
 * start_run, or null (cancelled or unsupported).
 */
export function pickSpecFile(options) {
  return transport.pickSpecFile(options);
}

/** True when pickSpecFile can show a picker; otherwise the UI asks for a typed path. */
export function canPickSpecFile() {
  return transport.name === 'http' || transport.canPick();
}

/** True when pickFolder and pickFile can show a picker (the desktop app and the preview). */
export function canPickPaths() {
  return transport.canPick();
}

/** Ask for a folder. Resolves to its path, or null. */
export function pickFolder(options) {
  return transport.pickFolder(options);
}

/** Ask for a file of any type. Resolves to its path, or null. */
export function pickFile(options) {
  return transport.pickFile(options);
}

/**
 * Files dragged onto the window. `enter` and `leave` mark the drag; `drop` receives the
 * paths of the dropped files (on the web, spec and drawing files are uploaded first).
 */
export function onFileDrop(handlers) {
  transport.onFileDrop(handlers);
}

/**
 * Ask for the files of a drawing set (several at once). Resolves to their paths for
 * prepare_intake, or an empty list (cancelled or unsupported).
 */
export function pickDrawingFiles() {
  return transport.pickDrawingFiles();
}

/** True when the file name has a drawing set extension (PDF, PNG, TIFF, JPEG). */
export function isDrawingFileName(name) {
  const ext = name.split('.').pop()?.toLowerCase();
  return name.includes('.') && DRAWING_EXTENSIONS.includes(ext);
}

/** True when the file name has a run spec extension. */
export function isSpecFileName(name) {
  const ext = name.split('.').pop()?.toLowerCase();
  return name.includes('.') && SPEC_EXTENSIONS.includes(ext);
}

/** Fetch an artifact from a task as a data: URL (images) or an ArrayBuffer (STL). */
export async function readArtifactAsDataUrl(task, path) {
  const { mime, base64 } = await invoke('read_artifact', { task, path });
  return `data:${mime};base64,${base64}`;
}

export async function readArtifactAsBuffer(task, path) {
  const { base64 } = await invoke('read_artifact', { task, path });
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}
