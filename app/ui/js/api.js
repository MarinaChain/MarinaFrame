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
//   3. Static: <meta name="marinaframe-backend" content="static"> is present (the public web
//              demo, docs/WEB_DEMO.md). static/backend.js, loaded with a dynamic import only in
//              this case, answers read commands from exported files and refuses every change.
//   4. Mock:   none of the above. mock/backend.js, loaded with a dynamic import only in
//              this case, serves fixtures from mock/fixtures.json. The release UI leaves
//              out ui/mock, so the desktop bundle carries no mock code or data.
//
// Arguments follow docs/APP_SPEC.md exactly (snake_case keys such as `after_sequence`).


import {
  BackendError, toBackendError, listenForBrowserDrops,
  SPEC_EXTENSIONS, DRAWING_EXTENSIONS, isDrawingFileName, isSpecFileName,
} from './backend_common.js';

export { BackendError, SPEC_EXTENSIONS, DRAWING_EXTENSIONS, isDrawingFileName, isSpecFileName };

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
    async pickDrawingFiles({ multiple = true } = {}) {
      if (!tauri.dialog?.open) return [];
      const picked = await tauri.dialog.open({
        title: multiple ? 'Choose a drawing set' : 'Replace sheet',
        multiple,
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
    pickDrawingFiles({ multiple = true } = {}) {
      return new Promise((resolve, reject) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = multiple;
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

// ---------------------------------------------------------------- Selection

async function chooseTransport() {
  if (window.__TAURI__) return tauriTransport(window.__TAURI__);
  if (document.querySelector('meta[name="marinaframe-backend"][content="http"]')) return httpTransport();
  if (document.querySelector('meta[name="marinaframe-backend"][content="static"]')) {
    const { staticTransport } = await import('../static/backend.js');
    return staticTransport();
  }
  // Only the browser preview reaches this line; the desktop and web builds never load the mock.
  const { mockTransport } = await import('../mock/backend.js');
  return mockTransport();
}

const transport = await chooseTransport();

/** "tauri", "http", "static" or "mock". */
export const transportName = transport.name;

/** True in the public web demo: runs are shown, nothing can be changed or started. */
export const readOnly = transport.readOnly === true;

/** What the demo says wherever a control that would change a run is left out. */
export const READ_ONLY_NOTE = 'Demo: read-only. Install the desktop app to build your own.';

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
export function pickDrawingFiles(options) {
  return transport.pickDrawingFiles(options);
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
