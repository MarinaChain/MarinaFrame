// Run files read through the backend, cached per run: drawing pages, models, card previews.

import { state } from './app_state.js';
import { readArtifactAsDataUrl, readArtifactAsBuffer, invoke } from './api.js';

const artifactCache = new Map();
export function cachedArtifact(kind, task, path) {
  const key = `${kind}|${task}|${path}`;
  if (!artifactCache.has(key)) {
    const load = kind === 'image' ? readArtifactAsDataUrl(task, path) : readArtifactAsBuffer(task, path);
    artifactCache.set(key, load.catch((error) => {
      artifactCache.delete(key);
      throw error;
    }));
  }
  return artifactCache.get(key);
}

// Evidence card on the section strip (js/evidence.js): the page crop, the lines and the ink distance.
/** The open run's drawing page as a data URL (or null): evidence cards and mark thumbnails. */
export const evidencePageUrl = () => (state.view?.source_page ? cachedArtifact('image', state.task, state.view.source_page.path).catch(() => null) : Promise.resolve(null));

// Card previews need the run's page and sections. Cached per run and update time.
const previewCache = new Map();
export function runPreview(task) {
  const key = `${task.task}|${task.updated_ms}`;
  if (!previewCache.has(key)) {
    previewCache.set(key, invoke('get_task', { task: task.task }).catch(() => null));
  }
  return previewCache.get(key);
}

/** Forget the card previews: a part review or a sign-off changed what the cards show. */
export function clearPreviews() {
  previewCache.clear();
}
