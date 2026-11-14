// Pure Home thumbnail choices, crop validation and cache identity. No DOM or GPU access.

const MAX_MODEL_BYTES = 64 * 1024 * 1024;
const baseName = (path) => String(path || '').split(/[\\/]/).pop();
const isGa = (type) => /^(general[ _-]arrangement|ga)$/i.test(type || '');

/** A usable whole-view rectangle, not a box around a particular or one ship part. */
export function profileCrop(reading, sheet) {
  const profile = (reading?.views || []).find((view) => view.kind === 'profile'
    && (!view.sheet || baseName(view.sheet) === baseName(sheet))
    && validBox(view.box_px));
  return profile ? [...profile.box_px] : null;
}

function validBox(box) {
  return Array.isArray(box) && box.length === 4 && box.every(Number.isFinite)
    && box[0] >= 0 && box[1] >= 0 && box[2] > box[0] && box[3] > box[1];
}

/** Best available picture. `sources` is the backend's source list; omit models on fallback. */
export function thumbnailSource(view, sources = [], { models = true } = {}) {
  if (!view) return { kind: 'none' };
  if (models) {
    const whole = view.whole_vessel_model;
    if (whole?.glb_path && whole.loadable && whole.bytes <= MAX_MODEL_BYTES) {
      return { kind: 'model', format: 'glb', path: whole.glb_path };
    }
    if (view.model?.stl_path) return { kind: 'model', format: 'stl', path: view.model.stl_path };
  }
  const reading = view.ga_reading;
  const gaSheet = reading?.sources?.ga?.file || reading?.views?.find((v) => v.kind === 'profile')?.sheet;
  // A GA-only run already exposes its page as source_page. A mixed run can name another sheet.
  const current = view.source_page;
  if (reading && current?.path && (!gaSheet || baseName(gaSheet) === baseName(current.path))) {
    return { kind: 'ga', path: current.path, crop: profileCrop(reading, current.path) };
  }
  for (const source of sources) {
    if (!source.previewable || source.status === 'replaced' || source.status === 'unreadable') continue;
    const pages = (source.pages || []).filter((page) => !page.replaced);
    const page = pages.find((page) => isGa(page.sheet_type))
      || (gaSheet && baseName(source.name) === baseName(gaSheet) ? pages[0] : null);
    if (page) return {
      kind: 'ga', sourceId: source.id, page: page.index,
      crop: profileCrop(reading, source.name),
    };
  }
  return current?.path ? { kind: 'drawing', path: current.path } : { kind: 'none' };
}

/** Convert original-page coordinates to preview pixels and clamp to the displayed image. */
export function thumbnailCrop(box, original, image) {
  if (!validBox(box) || !(image.width > 0) || !(image.height > 0)) return null;
  const scaleX = original?.width > 0 ? image.width / original.width : 1;
  const scaleY = original?.height > 0 ? image.height / original.height : 1;
  const [x0, y0, x1, y1] = box;
  const scaled = [x0 * scaleX, y0 * scaleY, Math.min(x1 * scaleX, image.width), Math.min(y1 * scaleY, image.height)];
  return validBox(scaled) ? scaled : null;
}

const INTERNAL_KINDS = new Set([
  'cargo_hold', 'engine_room', 'other_space', 'void', 'void_space', 'cofferdam',
]);
const internalKind = (kind) => INTERNAL_KINDS.has(kind) || /(^|_)tank$/.test(kind || '');

function validPartBox(box) {
  return [box?.min, box?.max].every((point) => Array.isArray(point)
    && point.length === 3 && point.every(Number.isFinite))
    && box.max.every((value, axis) => value >= box.min[axis])
    && box.max.some((value, axis) => value > box.min[axis]);
}

/** Built exterior boxes in the vessel's metre, Z-up frame; never fill the hull with spaces. */
export function thumbnailParts(view) {
  return (view?.components || []).filter((part) => part && part.built !== false
    && !['hull', 'opening', 'tank'].includes(part.op)
    && !internalKind(part.op) && !internalKind(part.kind) && !internalKind(part.display?.kind)
    && validPartBox(part.bbox_m));
}

function partsHash(parts) {
  // Sort serialized entries so a tree reorder does not invalidate the same picture.
  const entries = parts.map((part) => JSON.stringify([part.id, part.bbox_m.min, part.bbox_m.max])).sort();
  let hash = 2166136261; // FNV-1a: compact identity for the selected IDs and coordinates.
  for (const character of JSON.stringify(entries)) {
    hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  }
  return (hash >>> 0).toString(16);
}

/** Include updates and exterior boxes: parts can change without a new hull artifact. */
export function thumbnailCacheKey(run, view, source) {
  const parts = source.format === 'stl' ? partsHash(thumbnailParts(view)) : null;
  return `home-thumb-v2:${JSON.stringify([run.task, view.revision, run.updated_ms, source.format, source.path, view.model?.length_m, parts])}`;
}

/** Fit all projected box corners in a 16:10 frame, with ten percent clear space. */
export function thumbnailFrame(points, aspect = 1.6) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  const halfHeight = Math.max(height, width / aspect) * 0.55;
  return { halfHeight, x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2 };
}
