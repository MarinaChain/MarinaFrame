// Home thumbnail priority, GA page crops, revision caching and complete-vessel framing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { thumbnailSource, profileCrop, thumbnailCacheKey, thumbnailFrame, thumbnailCrop, thumbnailParts } from '../ui/js/home_thumb.js';

const drawing = { path: 'pages/body.png', width: 1600, height: 1000 };
const model = { stl_path: 'build/hull.stl' };
const whole = { glb_path: 'parts/vessel.glb', loadable: true, bytes: 1024 };
const gaSource = {
  id: 'ga-sheet', name: 'arrangement.pdf', previewable: true, status: 'current',
  pages: [{ index: 0, sheet_type: 'Lines plan' }, { index: 1, sheet_type: 'General arrangement' }],
};

test('prefer the complete vessel model over a hull, GA and the current drawing', () => {
  assert.deepEqual(thumbnailSource({ model, whole_vessel_model: whole, ga_reading: {}, source_page: drawing }),
    { kind: 'model', format: 'glb', path: whole.glb_path });
});

test('hull models are available without any drawing', () => {
  assert.deepEqual(thumbnailSource({ model }), { kind: 'model', format: 'stl', path: model.stl_path });
});

test('oversize, unbuildable and missing-path whole models do not hide a usable hull', () => {
  for (const invalid of [{ ...whole, bytes: 64 * 1024 * 1024 + 1 }, { ...whole, loadable: false }, { ...whole, glb_path: '' }]) {
    assert.equal(thumbnailSource({ model, whole_vessel_model: invalid }).format, 'stl');
  }
});

test('the whole-vessel size limit includes exactly 64 MiB', () => {
  assert.equal(thumbnailSource({ whole_vessel_model: { ...whole, bytes: 64 * 1024 * 1024 } }).kind, 'model');
});

test('GA-only reading uses its source page, including the mock GA shape with no views', () => {
  assert.deepEqual(thumbnailSource({ ga_reading: {}, source_page: drawing }), { kind: 'ga', path: drawing.path, crop: null });
});

test('crop the whole profile region, not the small particulars and part evidence boxes', () => {
  const reading = {
    views: [{ kind: 'deck_plan', box_px: [1, 2, 50, 60] }, { kind: 'profile', sheet: 'body.png', box_px: [10, 20, 1500, 450] }],
    particulars: { loa_m: { source_record: { regions: [{ view: 'profile', box_px: [10, 20, 30, 40] }] } } },
  };
  assert.deepEqual(thumbnailSource({ ga_reading: reading, source_page: drawing }).crop, [10, 20, 1500, 450]);
  assert.equal(profileCrop({ particulars: reading.particulars }, drawing.path), null);
});

test('a profile region from another sheet must not crop the current page', () => {
  assert.equal(profileCrop({ views: [{ kind: 'profile', sheet: 'other.png', box_px: [1, 2, 30, 40] }] }, drawing.path), null);
});

test('invalid or absent view regions show the whole GA page', () => {
  for (const box_px of [null, [], [1, 2, 3], [0, 0, Infinity, 2], [-1, 0, 5, 5], [3, 0, 2, 4], [0, 2, 4, 2]]) {
    assert.equal(profileCrop({ views: [{ kind: 'profile', box_px }] }, drawing.path), null);
  }
});

test('drawing sets choose their GA sheet and correct zero-based page index', () => {
  assert.deepEqual(thumbnailSource({ source_page: drawing }, [gaSource]), { kind: 'ga', sourceId: 'ga-sheet', page: 1, crop: null });
});

test('a mixed run finds the GA reading sheet instead of cropping the lines plan', () => {
  const reading = { sources: { ga: { file: 'arrangement.pdf' } }, views: [{ kind: 'profile', sheet: 'arrangement.pdf', box_px: [0, 10, 500, 200] }] };
  assert.deepEqual(thumbnailSource({ ga_reading: reading, source_page: drawing }, [gaSource]),
    { kind: 'ga', sourceId: 'ga-sheet', page: 1, crop: [0, 10, 500, 200] });
});

test('unreadable, replaced and non-previewable GA sources fall back to the drawing', () => {
  for (const source of [{ ...gaSource, status: 'replaced' }, { ...gaSource, status: 'unreadable' }, { ...gaSource, previewable: false }, { ...gaSource, pages: [{ index: 0, sheet_type: 'GA', replaced: true }] }]) {
    assert.deepEqual(thumbnailSource({ source_page: drawing }, [source]), { kind: 'drawing', path: drawing.path });
  }
});

test('silent rendering fallback skips all model candidates and still prefers GA', () => {
  assert.equal(thumbnailSource({ model, whole_vessel_model: whole, source_page: drawing }, [gaSource], { models: false }).kind, 'ga');
  assert.equal(thumbnailSource({ model, source_page: drawing }, [], { models: false }).kind, 'drawing');
});

test('absent and incomplete runs do not produce broken image sources', () => {
  for (const view of [null, undefined, {}, { source_page: {}, model: {} }]) assert.deepEqual(thumbnailSource(view), { kind: 'none' });
});

test('cache identity separates task, revision, update and model format/path', () => {
  const run = { task: 'task-a', updated_ms: 1 };
  const view = { revision: 'r1' };
  const source = thumbnailSource({ model });
  const key = thumbnailCacheKey(run, view, source);
  for (const changed of [
    thumbnailCacheKey({ ...run, task: 'task-b' }, view, source),
    thumbnailCacheKey(run, { revision: 'r2' }, source),
    thumbnailCacheKey({ ...run, updated_ms: 2 }, view, source),
    thumbnailCacheKey(run, view, { ...source, path: 'other.stl' }),
    thumbnailCacheKey(run, view, { ...source, format: 'glb' }),
  ]) assert.notEqual(key, changed);
  assert.equal(key, thumbnailCacheKey(run, view, source));
});

const partBox = { min: [-2, -3, 4], max: [8, 3, 7] };
const exteriorPart = (id, op = 'deckhouse') => ({ id, op, built: true, bbox_m: structuredClone(partBox) });

test('thumbnail parts include built decks, houses, fittings and other exterior parts without mutation', () => {
  const components = [
    exteriorPart('deck', 'deck'), exteriorPart('house'), exteriorPart('wheelhouse'),
    exteriorPart('bulwark', 'bulwark'), exteriorPart('funnel', 'appendage'),
    exteriorPart('mast', 'appendage'), exteriorPart('crane', 'other'),
    { ...exteriorPart('older-run'), built: undefined },
  ];
  const before = structuredClone(components);
  assert.deepEqual(thumbnailParts({ components }), components);
  assert.deepEqual(components, before);
});

test('thumbnail parts omit hull duplicates, openings, tanks and internal space kinds', () => {
  const components = ['hull', 'opening', 'tank'].map((op) => exteriorPart(op, op));
  for (const kind of ['tank', 'cargo_tank', 'slop_tank', 'ballast_tank', 'fuel_tank', 'other_tank',
    'cargo_hold', 'engine_room', 'other_space', 'void', 'void_space', 'cofferdam']) {
    components.push(exteriorPart(`op-${kind}`, kind));
    components.push({ ...exteriorPart(kind), kind });
    components.push({ ...exteriorPart(`display-${kind}`), display: { kind } });
  }
  components.push({ ...exteriorPart('unbuilt'), built: false });
  assert.deepEqual(thumbnailParts({ components }), []);
});

test('thumbnail parts reject malformed boxes but retain flat deck boxes', () => {
  for (const bbox_m of [null, {}, { min: [0, 0], max: [1, 1, 1] },
    { min: [0, 0, 0], max: [1, NaN, 1] }, { min: [0, 0, 0], max: [Infinity, 1, 1] },
    { min: [0, 0, 0], max: [1, -1, 1] }, { min: [0, 0, 0], max: [0, 0, 0] }]) {
    assert.deepEqual(thumbnailParts({ components: [{ ...exteriorPart('bad'), bbox_m }] }), []);
  }
  const flat = { ...exteriorPart('flat', 'deck'), bbox_m: { min: [0, 0, 4], max: [10, 3, 4] } };
  assert.deepEqual(thumbnailParts({ components: [null, flat] }), [flat]);
  for (const view of [null, undefined, {}]) assert.deepEqual(thumbnailParts(view), []);
});

test('STL cache hashes exterior ids and boxes, independent of component order and internal spaces', () => {
  const run = { task: 'task-a', updated_ms: 1 };
  const source = thumbnailSource({ model });
  const components = [exteriorPart('house'), exteriorPart('mast', 'appendage')];
  const key = (parts, selected = source) => thumbnailCacheKey(run, { revision: 'r1', components: parts }, selected);
  const original = key(components);
  assert.equal(original, key([...components].reverse()));
  assert.equal(original, key([...components, exteriorPart('tank', 'tank')]));
  assert.notEqual(original, key(components.slice(1)));
  assert.notEqual(original, key([...components, exteriorPart('funnel')]));
  assert.notEqual(original, key([{ ...components[0], id: 'new-house' }, components[1]]));
  for (const bound of ['min', 'max']) for (const axis of [0, 1, 2]) {
    const changed = structuredClone(components);
    changed[0].bbox_m[bound][axis] += 0.1;
    assert.notEqual(original, key(changed));
  }
  assert.equal(key(components, { ...source, format: 'glb' }), key([], { ...source, format: 'glb' }));
});

test('hull length changes invalidate the metre-aligned model thumbnail', () => {
  const run = { task: 'task-a', updated_ms: 1 };
  const source = thumbnailSource({ model });
  assert.notEqual(thumbnailCacheKey(run, { model: { length_m: 40 } }, source),
    thumbnailCacheKey(run, { model: { length_m: 50 } }, source));
});

test('frame includes tall masts and fittings beyond the hull ends', () => {
  const hull = { min: [0, -4, 0], max: [40, 4, 5] };
  const parts = thumbnailParts({ components: [
    { ...exteriorPart('mast'), bbox_m: { min: [12, -1, 5], max: [13, 1, 30] } },
    { ...exteriorPart('fitting'), bbox_m: { min: [-5, -1, 4], max: [0, 1, 6] } },
  ] });
  const points = [hull, ...parts.map((part) => part.bbox_m)].flatMap(({ min, max }) =>
    [min[0], max[0]].flatMap((x) => [min[2], max[2]].map((z) => [x, z])));
  const frame = thumbnailFrame(points);
  for (const [x, z] of points) {
    assert.ok(Math.abs(x - frame.x) < frame.halfHeight * 1.6);
    assert.ok(Math.abs(z - frame.y) < frame.halfHeight);
  }
});

test('GA crops scale from original sheet pixels to a downsampled preview', () => {
  assert.deepEqual(thumbnailCrop([100, 200, 1800, 900], { width: 2000, height: 1000 }, { width: 1000, height: 500 }), [50, 100, 900, 450]);
  assert.deepEqual(thumbnailCrop([0, 0, 3000, 2000], { width: 2000, height: 1000 }, { width: 1000, height: 500 }), [0, 0, 1000, 500]);
  assert.equal(thumbnailCrop([3000, 0, 4000, 500], null, { width: 1000, height: 500 }), null);
});

test('wide and tall projected vessels fit with clear space on all sides', () => {
  for (const points of [[[10, 20], [210, 30]], [[-2, -40], [5, 100]]]) {
    const frame = thumbnailFrame(points);
    for (const [x, y] of points) {
      assert.ok(Math.abs(x - frame.x) < frame.halfHeight * 1.6);
      assert.ok(Math.abs(y - frame.y) < frame.halfHeight);
    }
  }
});
