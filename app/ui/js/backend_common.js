// Shared by every transport (js/api.js) and by the browser mock (mock/backend.js): the
// backend error shape, the file types the app accepts and browser file drops. No transport
// is chosen here, so the mock can import this file without a cycle through api.js.

/** File types the run spec picker accepts (start_run takes one of these). */
export const SPEC_EXTENSIONS = ['json', 'toml', 'yaml', 'yml'];
/** File types of a drawing set (prepare_intake takes these; app/core/src/intake.rs). */
export const DRAWING_EXTENSIONS = ['pdf', 'png', 'tif', 'tiff', 'jpg', 'jpeg'];

/** A backend error in the spec's shape. `message` is plain language for people. */
export class BackendError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export function toBackendError(raw) {
  if (raw instanceof BackendError) return raw;
  if (raw && typeof raw === 'object' && 'message' in raw) {
    return new BackendError(raw.code || 'error', String(raw.message));
  }
  if (typeof raw === 'string') return new BackendError('error', raw);
  return new BackendError('error', 'The app could not complete this action.');
}

/**
 * File drops in a plain browser. The browser gives the file, not its path, so `toPath`
 * turns each dropped file into a path for start_run (an upload, or a mock path).
 */
export function listenForBrowserDrops({ enter, leave, drop }, toPath) {
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
