// The static, read-only backend of the public web demo (docs/WEB_DEMO.md).
//
// js/api.js loads this file with a dynamic import only when the page has
// <meta name="marinaframe-backend" content="static">, which scripts/build_web_demo.py adds.
// Every read command answers from files the build exported with the desktop app's own
// backend (app/core/examples/web_demo_export.rs) under data/:
//
//   data/manifest.json                 runs and their summaries (list_tasks)
//   data/runs/<slug>/task.json         get_task
//   data/runs/<slug>/events.json       get_events
//   data/runs/<slug>/live.json         get_live_steps
//   data/runs/<slug>/sections.json     get_hull_sections, keyed by revision id or path
//   data/runs/<slug>/sources.json      list_sources
//   data/runs/<slug>/pages.json        read_source_page, keyed "<source>|<page>|<size>"
//   data/runs/<slug>/exports.json      list_exports, keyed by revision
//   data/runs/<slug>/tables.json       sounding_table, keyed by tank id
//   data/runs/<slug>/files/<path>      read_artifact
//
// Every command that would change a run, start one or use a model is refused with
// READ_ONLY_MESSAGE. Nothing is saved: notices dismissed here are kept for this page only.
// The release UI leaves out ui/static, so the desktop bundle carries none of this.

import { BackendError } from '../js/backend_common.js';

export const READ_ONLY_CODE = 'demo_read_only';
export const READ_ONLY_MESSAGE = 'Demo: read-only. Install the desktop app to build your own.';
/** The task id prefix the exporter gives every run (DEMO_RUNS_FOLDER in web_demo_export.rs). */
export const DEMO_RUNS_FOLDER = '/MarinaFrame/runs';

/** The demo's settings: shown on the Settings page, never saved. */
const DEMO_SETTINGS = {
  runs_folder: DEMO_RUNS_FOLDER,
  worker_python: '',
  theme: 'system',
  ai_drafting: false,
  notify_finished: false,
};
const AI_OFF = {
  enabled: false, key_found: false, claude_found: false, active: false, key_count: 0, key_file: null,
};
const MIME_BY_EXTENSION = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', stl: 'model/stl', glb: 'model/gltf-binary',
};

function readOnly() {
  return new BackendError(READ_ONLY_CODE, READ_ONLY_MESSAGE);
}

/** Base64 text of an ArrayBuffer, in chunks so a large model does not overflow the call stack. */
export function bufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const CHUNK = 0x8000;
  let binary = '';
  for (let start = 0; start < bytes.length; start += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(start, start + CHUNK));
  }
  return btoa(binary);
}

/**
 * A task-relative artifact path as read_artifact accepts it (app/core/src/artifact.rs):
 * relative, no empty, "." or ".." segments, no backslash, and an image, STL or GLB type.
 * Returns its MIME type, or null.
 */
export function artifactMime(path) {
  if (typeof path !== 'string' || !path || path.length > 1024 || path.startsWith('/')) return null;
  if (path.includes('\\') || path.includes('\0')) return null;
  if (path.split('/').some((part) => part === '' || part === '.' || part === '..')) return null;
  const extension = path.split('.').pop().toLowerCase();
  return MIME_BY_EXTENSION[extension] || null;
}

/**
 * The backend over the files under `base` (a URL ending in "/"). `fetchImpl` is the
 * browser's fetch; tests pass their own.
 */
export function createStaticBackend({ fetchImpl = (...args) => fetch(...args), base = 'data/' } = {}) {
  const jsonCache = new Map();
  const dismissed = new Set();

  async function fetchOk(url) {
    let response;
    try {
      response = await fetchImpl(url);
    } catch {
      throw new BackendError('offline', 'The demo files could not be loaded. Check the connection and reload.');
    }
    if (!response.ok) throw new BackendError('not_found', 'This demo file is missing.');
    return response;
  }

  function json(path) {
    if (!jsonCache.has(path)) {
      const load = fetchOk(base + path).then((response) => response.json());
      load.catch(() => jsonCache.delete(path));
      jsonCache.set(path, load);
    }
    return jsonCache.get(path);
  }

  const manifest = () => json('manifest.json');

  /** The slug of a demo task id, checked against the manifest. */
  async function slugOf(task) {
    const prefix = `${DEMO_RUNS_FOLDER}/`;
    const slug = typeof task === 'string' && task.startsWith(prefix) ? task.slice(prefix.length) : '';
    const { runs } = await manifest();
    if (!slug || !runs.some((run) => run.slug === slug)) {
      throw new BackendError('task_not_found', 'This run is not part of the demo.');
    }
    return slug;
  }

  const runJson = async (task, name) => json(`runs/${await slugOf(task)}/${name}`);

  /** The download address of a file the exporter copied, relative to the page. */
  const fileUrl = (slug, relative) => `${base}runs/${slug}/${relative}`;

  const commands = {
    async list_tasks() {
      const { runs } = await manifest();
      // Home shows the runs in the manifest's order, each with its line and where its
      // drawings came from (the licence credit).
      return runs.map((run, index) => ({
        ...structuredClone(run.summary),
        demo_order: index,
        demo_tagline: run.tagline || null,
        demo_concept: run.concept === true,
        demo_source: run.source,
      }));
    },
    async get_task({ task }) {
      const view = structuredClone(await runJson(task, 'task.json'));
      const slug = await slugOf(task);
      const { runs } = await manifest();
      // A concept-preview run (made-up vessel and drawings) carries its flag to every page,
      // and a run whose drawings need a credit carries that line.
      const listed = runs.find((run) => run.slug === slug);
      view.demo = { concept: listed?.concept === true, credit: listed?.credit || null };
      // As in app/core/src/view.rs, a dismissed notice is left out.
      view.notices = (view.notices || []).filter((notice) => !dismissed.has(notice.id));
      return view;
    },
    async get_events({ task, after_sequence = 0 }) {
      const events = await runJson(task, 'events.json');
      return events.filter((event) => event.sequence > after_sequence);
    },
    async get_live_steps({ task, after_sequence = 0 }) {
      const live = structuredClone(await runJson(task, 'live.json'));
      live.steps = (live.steps || []).filter((step) => step.last_sequence > after_sequence);
      return live;
    },
    async get_hull_sections({ task, revision }) {
      const builds = await runJson(task, 'sections.json');
      const found = builds[revision];
      if (!found) throw new BackendError('revision_not_found', 'That build cannot be found.');
      return structuredClone(found);
    },
    async read_artifact({ task, path }) {
      const slug = await slugOf(task);
      const mime = artifactMime(path);
      if (!mime) throw new BackendError('unsafe_artifact_path', 'This file cannot be shown.');
      const response = await fetchOk(fileUrl(slug, `files/${path}`));
      return { mime, base64: bufferToBase64(await response.arrayBuffer()) };
    },
    async list_sources({ task }) {
      return structuredClone(await runJson(task, 'sources.json'));
    },
    async read_source_page({ task, source_id: sourceId, page = 0, size = 'thumb' }) {
      const slug = await slugOf(task);
      const pages = await runJson(task, 'pages.json');
      const facts = pages[`${sourceId}|${page}|${size}`];
      if (!facts) throw new BackendError('source_not_found', 'This page is not part of the demo.');
      const { file, ...preview } = structuredClone(facts);
      preview.base64 = null;
      if (file) preview.base64 = bufferToBase64(await (await fetchOk(fileUrl(slug, file))).arrayBuffer());
      return preview;
    },
    async list_exports({ task, revision }) {
      const slug = await slugOf(task);
      const exports = await runJson(task, 'exports.json');
      const found = exports[revision];
      if (!found) {
        return { folder: '', revision, files: [], not_built: [], format_results: {}, display_omissions: [], stamp: '', engineering_approved: false };
      }
      const result = structuredClone(found);
      // The file paths become download addresses (js/export.js links them in the demo).
      for (const file of result.files) file.path = fileUrl(slug, file.path);
      result.folder = '';
      return result;
    },
    async sounding_table({ task, tank_id: tankId }) {
      const tables = await runJson(task, 'tables.json');
      const found = tables[tankId];
      if (!found) throw new BackendError('sounding_not_found', 'This run has no sounding table for that tank.');
      return structuredClone(found);
    },
    async get_settings() {
      return { ...DEMO_SETTINGS };
    },
    async get_default_settings() {
      return { ...DEMO_SETTINGS };
    },
    async get_ai_status() {
      return { ...AI_OFF };
    },
    async get_setup_status() {
      return {
        ai: { ...AI_OFF },
        worker: { ok: true, path: '', message: READ_ONLY_MESSAGE },
        runs_folder: { ok: true, path: DEMO_RUNS_FOLDER, message: READ_ONLY_MESSAGE },
      };
    },
    async get_queue() {
      return { slots: 0, running: 0, waiting: [], held: null };
    },
    async list_datasets() {
      return [];
    },
    async dismiss_notice({ id }) {
      dismissed.add(id);
      return { ok: true };
    },
    async reset_notices() {
      dismissed.clear();
      return { ok: true };
    },
  };

  return {
    /** Answer one command, or refuse it as read-only. */
    async invoke(command, args = {}) {
      const run = Object.hasOwn(commands, command) ? commands[command] : null;
      if (!run) throw readOnly();
      return run(args || {});
    },
    manifest,
  };
}

/** The transport js/api.js uses: read-only, no pickers, no file drops, no live updates. */
export function staticTransport(options) {
  const backend = createStaticBackend(options);
  return {
    name: 'static',
    readOnly: true,
    invoke: (command, args) => backend.invoke(command, args),
    manifest: backend.manifest,
    onTaskChanged: () => () => {},
    canPick: () => false,
    pickSpecFile: async () => { throw readOnly(); },
    pickFolder: async () => null,
    pickFile: async () => null,
    pickDrawingFiles: async () => { throw readOnly(); },
    onFileDrop() {},
  };
}
