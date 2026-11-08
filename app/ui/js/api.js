// The only module that talks to a backend. Every command, every live update and the
// spec-file picker go through here, so the same UI runs in Tauri, as a web app, or on mocks.
//
// Transport selection, in order:
//   1. Tauri:  window.__TAURI__ is present (Tauri 2 with `withGlobalTauri`).
//   2. HTTP:   <meta name="marinaframe-backend" content="http"> is present.
//              Commands: POST /api/<command> with a JSON body; errors use a non-2xx status
//              and the spec's { code, message } body. Live updates: Server-Sent Events at
//              /api/events, one `task-changed` event per change with { task, sequence }.
//   3. Mock:   neither of the above. Fixtures from mock/fixtures.json.
//
// Arguments follow docs/APP_SPEC.md exactly (snake_case keys such as `after_sequence`).

const MOCK_FIXTURES_URL = 'mock/fixtures.json';
const MOCK_FILES_URL = 'mock/files/';
const MOCK_DISMISSED_KEY = 'marinaframe.mock.dismissed-notices';
const MOCK_SETTINGS_KEY = 'marinaframe.mock.settings';
/** Delay between mock events for the running task, to imitate a live run. */
const MOCK_PLAYBACK_MS = 4000;

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
    async pickSpecFile() {
      // The dialog plugin is optional. Without it the caller asks for a typed path.
      if (!tauri.dialog?.open) return null;
      const picked = await tauri.dialog.open({
        multiple: false,
        filters: [{ name: 'Run spec', extensions: ['json', 'toml', 'yaml', 'yml'] }],
      });
      return typeof picked === 'string' ? picked : null;
    },
  };
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
    pickSpecFile() {
      // Upload the chosen file; the server stores it and returns the path to pass to start_run.
      return new Promise((resolve, reject) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json,.toml,.yaml,.yml';
        input.addEventListener('change', async () => {
          const file = input.files?.[0];
          if (!file) return resolve(null);
          try {
            const result = await post(`/api/upload_spec?name=${encodeURIComponent(file.name)}`, file, 'application/octet-stream');
            resolve(result.spec_path);
          } catch (error) {
            reject(error);
          }
        });
        input.addEventListener('cancel', () => resolve(null));
        input.click();
      });
    },
  };
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

  const commands = {
    async list_tasks(data) {
      startPlayback(data);
      return [...data.tasks].sort((a, b) => b.updated_ms - a.updated_ms);
    },
    async get_task(data, { task }) {
      const view = clone(requireTask(data, task));
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
    async set_settings(data, settings) {
      writeStored(MOCK_SETTINGS_KEY, settings);
      return { ...data.settings, ...settings };
    },
    async get_ai_status(data) {
      const settings = { ...data.settings, ...readStored(MOCK_SETTINGS_KEY, {}) };
      const enabled = settings.ai_drafting !== false;
      return { enabled, key_found: true, active: enabled,
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
  };

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
    async pickSpecFile() {
      return null;
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

/** Ask for a run spec file. Resolves to a path for start_run, or null (cancelled or unsupported). */
export function pickSpecFile() {
  return transport.pickSpecFile();
}

/** True when pickSpecFile can show a picker; otherwise the UI asks for a typed path. */
export function canPickSpecFile() {
  if (transport.name === 'tauri') return Boolean(window.__TAURI__?.dialog?.open);
  return transport.name === 'http';
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
