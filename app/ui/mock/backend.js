// The browser mock backend: sample runs from mock/fixtures.json, pickers that answer with
// demo paths, and a scripted live run. js/api.js loads this file with a dynamic import only
// when neither Tauri nor the HTTP backend is present. The release UI (app/core/src/release_ui.rs)
// copies only index.html, styles.css, js/, vendor/ and assets/, so this folder never ships.

import { BackendError, listenForBrowserDrops, isDrawingFileName } from '../js/backend_common.js';

const MOCK_FIXTURES_URL = 'mock/fixtures.json';
const MOCK_FILES_URL = 'mock/files/';
const MOCK_DISMISSED_KEY = 'marinaframe.mock.dismissed-notices';
const MOCK_SETTINGS_KEY = 'marinaframe.mock.settings';
/** The mock has no file system. Its pickers return paths under this folder. */
const MOCK_PICK_FOLDER = '/Users/demo/MarinaFrame/examples';
/** Delay between mock events for the running task, to imitate a live run. */
const MOCK_PLAYBACK_MS = 4000;
/** With ?mocklive, the mock live run shows one more step this often. */
const MOCK_LIVE_STEP_MS = 2500;

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
/** With ?mockdrawings the mock reads this one file as a nine-sheet set (mock/drawing_set.json). */
const MOCK_DRAWINGS_FILE = '/Users/demo/Downloads/survey-launch-drawings.pdf';
const MOCK_DRAWINGS_URL = 'mock/drawing_set.json';
/** The mock page image (mock/files/page-1.png) in pixels. */
const MOCK_PAGE = { width: 1600, height: 1000 };

/**
 * The preview of the mock drawing set (made by mock/make_drawing_set_mock.py from the worker's own
 * code): each sheet has its type and scale, the set has the checklist. One required drawing is missing.
 */
function mockDrawingSetPreview(drawings, thumbnail, aiActive) {
  const pages = drawings.pages.map((entry, index) => ({
    page_id: entry.page_id, file: `/Users/demo/Downloads/${entry.file_name}`, file_name: entry.file_name,
    kind: 'pdf', page_index: 0, dpi: 200, dpi_source: 'pdf_render',
    width_px: MOCK_PAGE.width, height_px: MOCK_PAGE.height, thumbnail_png_base64: thumbnail, thumbnail_scale: 1,
    regions: [{ region_id: 'r1', label: ['body_plan', 'profile', 'profile', 'other'][index % 4], confidence: 0.6, region_px: [140, 250, 1470, 820], evidence: 'One framed ink group.' }],
    warnings: [], skip: false, sheet: entry.sheet,
  }));
  const warnings = aiActive ? [] : [{ code: 'ai_off', message: 'AI drafting is off. A drawing set without a spec needs the AI to read stations and scale.' }];
  return { intake_id: `intake-${Date.now()}`, pages, warnings, render_dpi: 200, particulars: { vessel_name: '' }, ai_active: aiActive, set: drawings.set };
}

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
        // A set of scans: the sheets take turns at the views a lines plan has (the first is the unsure profile).
        regions: [pages.length < 3
          ? region('r1', 'profile', 0.41, [140, 250, 1470, 820], 'One wide ink group; could be a profile or a body plan.')
          : region('r1', ['half_breadth', 'body_plan', 'profile', 'other'][pages.length % 4], 0.62 + (pages.length % 3) * 0.1, [140, 250, 1470, 820], 'One framed ink group.')],
        warnings: [{ code: 'low_dpi', message: 'Scan 150 dpi: lines may be read less exactly.' }],
      });
    }
  }
  const warnings = aiActive ? [] : [{ code: 'ai_off', message: 'AI drafting is off. A drawing set without a spec needs the AI to read stations and scale.' }];
  return { intake_id: `intake-${Date.now()}`, pages, warnings, render_dpi: 200, particulars: { vessel_name: '' }, ai_active: aiActive };
}

/**
 * Source files of a mock run (APP_SPEC "Sources"), in the shape of app/core sources.rs. Every
 * page picture is a mock file (`image`: mock/files/page-1.png or a station crop); the names,
 * sheet types and scales are made up. The survey launch has a replaced lines plan, a sheet the
 * run could not read and two spec inputs; a run without a drawing page has no sources.
 */
function mockSources(task, view) {
  if (!view.source_page) return [];
  const added = view.summary.updated_ms - 2 * 3_600_000;
  const hash = (seed) => Array.from({ length: 64 }, (_, i) => '0123456789abcdef'[(seed.charCodeAt(i % seed.length) + i * 7) % 16]).join('');
  const page = (index, sheetType = null, scale = null, size = MOCK_PAGE) => ({
    index, sheet_type: sheetType, scale, width_px: size.width, height_px: size.height, dpi: 200, replaced: false,
  });
  const file = (id, fields) => ({
    id, version: 1, status: 'current', pages: [], size_bytes: 24_000, sha256: hash(id), added_ms: added,
    used_from: 'r0000', used_to: null, replaced_by: null, note: null, previewable: true, image: 'page-1.png', ...fields,
  });
  const spec = (id, role) => file(id, { name: id === 'mock-intake' ? 'intake.json' : 'spec.json', kind: 'spec', role, size_bytes: 1_400 });
  if (!task.endsWith('survey-launch')) {
    return [
      file('mock-drawing', { name: 'drawing.png', kind: 'drawing', role: 'Main drawing', pages: [page(0, 'Lines plan', '1:50')], size_bytes: 23_551 }),
      spec('mock-spec', 'Run spec as given'),
    ];
  }
  const crop = { width: 220, height: 290 };
  return [
    file('mock-lines-1', {
      name: 'survey-launch-lines.pdf', kind: 'pdf', role: 'Main drawing', status: 'replaced', size_bytes: 1_840_000,
      pages: [{ ...page(0, 'Lines plan', '1:50'), replaced: true }, page(1, 'Other')],
      used_to: 'r0001', replaced_by: 'mock-lines-2',
    }),
    file('mock-ga', { name: 'survey-launch-ga.png', kind: 'drawing', role: 'Sheet', image: 'ga-1.png', pages: [page(0, 'General arrangement', '1:50')], size_bytes: 412_000 }),
    file('mock-midship', {
      name: 'survey-launch-midship.tif', kind: 'drawing', role: 'Sheet', image: 'crop-st12.png',
      pages: [page(0, 'Midship section', '1:25', crop)], size_bytes: 96_000,
    }),
    file('mock-lines-2', {
      name: 'Lines plan, version 2', kind: 'pdf', role: 'Replacement for Lines plan', status: 'unreadable', version: 2,
      note: 'Lines too faint.', pages: [page(0)], size_bytes: 1_120_000, added_ms: added + 3_600_000, used_from: 'r0002',
    }),
    spec('mock-spec', 'Run spec written from the drawing set'),
    spec('mock-intake', 'Drawing set record'),
  ];
}

/**
 * Whole-vessel parts of the mock survey launch (a made-up 24 m vessel, not a real drawing),
 * in the shape of APP_SPEC "Whole-vessel parts".
 */
const MOCK_COMPONENTS = (() => {
  const arg = (name, value, source, basis = null) => ({ name, value, source, basis });
  const part = (id, op, label, status, view, reason, box, volume, args) => ({
    id, op, label, status, built: Boolean(box), view, reason,
    bbox_m: box ? { min: box[0], max: box[1] } : null,
    volume_m3: volume, step_path: box ? `whole_vessel/${id}.step` : null, arguments: args, review: 'open',
  });
  return [
    part('hull', 'hull', 'Hull', 'measured_draft', 'body', 'Built from the body plan sections; see the section strip.',
      [[0, -3.6, 0], [24, 3.6, 3.4]], 341.7,
      [arg('length', '24.00 m', 'traced', 'Station spacing on the body plan'), arg('beam', '7.20 m', 'traced', 'Widest section'), arg('depth', '3.40 m', 'traced', 'Deck line at midship')]),
    part('main_deck', 'deck', 'Main deck', 'draft_guess', 'profile', 'thickness: guessed: typical deck plate',
      [[0, -3.6, 3.39], [24, 3.6, 3.4]], 1.6,
      [arg('top', '3.40 m', 'traced', 'Label MAIN DECK on the profile'), arg('outline', 'deck edge, 18 points', 'traced', 'Plan view outline'), arg('thickness', '0.010 m', 'guessed', 'Typical deck plate')]),
    part('house_t1', 'deckhouse', 'Deckhouse tier 1', 'measured_draft', 'plan', 'Component identity needs human review',
      [[9, -2.6, 3.4], [17, 2.6, 5.8]], 99.8,
      [arg('outline', '4 walls', 'traced', 'End wall and side walls on the main deck plan'), arg('height', '3.40 to 5.80 m', 'traced', 'Labels MAIN DECK and A DECK')]),
    part('wheelhouse', 'deckhouse', 'Wheelhouse', 'draft_guess', 'profile', 'outline: guessed: the tier below gives the breadth; the wheelhouse plan has no scale',
      [[11, -2.0, 5.8], [15.5, 2.0, 8.2]], 43.2,
      [arg('height', '5.80 to 8.20 m', 'traced', 'Profile roof line'), arg('outline', 'tier 1 breadth', 'guessed', 'Wheelhouse plan has no scale')]),
    part('aft_bulwark', 'bulwark', 'Aft bulwark', 'draft_guess', 'profile', 'thickness: guessed: typical bulwark plate',
      [[0, -3.6, 3.4], [9, 3.6, 4.4]], 1.6,
      [arg('height', '3.40 to 4.40 m', 'traced', 'Profile bulwark line'), arg('outline', 'deck edge aft of the house', 'traced', 'Plan view outline'), arg('thickness', '0.050 m', 'guessed', 'Typical bulwark plate')]),
    part('rudder', 'appendage', 'Rudder', 'draft_guess', null, 'Not built: no view of the stern below the waterline was found.',
      null, null, []),
  ];
})();

/**
 * Source records of the survey launch (docs/SOURCE_RECORD.md). Part regions are on the mock GA
 * sheet mock/files/ga-1.png (mock/make_ga_mock.py draws it: column = 200 + 50 x, profile row =
 * 480 - 50 z, plan row = 770 - 50 y, in metres). Hull regions are the body plan sections.
 */
const MOCK_GA = 'survey-launch-ga.png';
const MOCK_LINES = 'survey-launch-lines.pdf';
const MOCK_SHEET_PX = [MOCK_PAGE.width, MOCK_PAGE.height];
/** A GA region around ship ranges [x0, x1] and [z0, z1] (profile) or [y0, y1] (plan), with 8 px of space. */
function gaRegion(view, [x0, x1], [v0, v1]) {
  const row = view === 'profile' ? (z) => 480 - 50 * z : (y) => 770 - 50 * y;
  return { sheet: MOCK_GA, page: 0, view, box_px: [200 + 50 * x0 - 8, row(v1) - 8, 200 + 50 * x1 + 8, row(v0) + 8], page_px: MOCK_SHEET_PX };
}
const MOCK_SOURCE_RECORDS = {
  hull: { kind: 'read', regions: [[120, 250, 560, 830], [580, 250, 1020, 830], [1040, 250, 1480, 830]].map((box) => ({ sheet: MOCK_LINES, page: 0, view: 'body plan', box_px: box, page_px: MOCK_SHEET_PX })) },
  main_deck: { kind: 'guessed', method: 'thickness: typical deck plate (no plate label read)', inputs: [gaRegion('profile', [0, 24], [3.4, 3.6]), gaRegion('plan', [0, 24], [-3.6, 3.6])] },
  house_t1: { kind: 'read', regions: [gaRegion('profile', [9, 17], [3.4, 5.8]), gaRegion('plan', [9, 17], [-2.6, 2.6])] },
  wheelhouse: { kind: 'guessed', method: 'outline: the tier below gives the breadth; the wheelhouse plan has no scale', inputs: [gaRegion('profile', [11, 15.5], [5.8, 8.2]), { part: 'house_t1' }] },
  aft_bulwark: { kind: 'guessed', method: 'thickness: typical bulwark plate', inputs: [gaRegion('profile', [0, 9], [3.4, 4.4]), { part: 'main_deck' }] },
  rudder: { kind: 'unknown', reason: 'Not built: no view of the stern below the waterline was found.' },
  tank_fw1: { kind: 'guessed', method: 'Height: the tank height is not drawn', inputs: [gaRegion('plan', [4, 7], [-1.5, 1.5]), gaRegion('profile', [4, 7], [0.2, 1.4])] },
  tank_wb1: { kind: 'read', regions: [gaRegion('plan', [13, 16], [0.2, 2.4])] },
  tank_wb2: { kind: 'read', regions: [gaRegion('plan', [13, 16], [-2.4, -0.2])] },
  tank_do1: { kind: 'read', regions: [gaRegion('plan', [17, 19.5], [-2, 2]), gaRegion('profile', [17, 19.5], [0.2, 1.2])] },
  tank_fo1: { kind: 'unknown', reason: 'No plan region holds its label: not built.' },
};

/**
 * A GA reading (src/vessel_reconstruction/ga_commercial.py) of the mock survey launch with ?mockga.
 * Made-up values; regions are on the mock GA sheet like the part records above.
 */
const MOCK_GA_READING = (() => {
  const read = (view, xs, vs) => ({ kind: 'read', regions: [gaRegion(view, xs, vs)] });
  const unknown = (reason) => ({ value: null, status: 'unknown', reason, source_record: { kind: 'unknown', reason } });
  const space = (id, kind, label, number, status, record) => ({ id, kind, label, number, status, source_record: record });
  return {
    schema: 'marinaframe.ga_reading.v1', engineering_approved: false, model: 'claude-sonnet-5-5',
    ship_type: { value: 'other', status: 'read', evidence: 'Survey launch: no cargo spaces' },
    particulars: {
      loa_m: { value: 24.0, status: 'read', printed: '24.00 m', unit_context: null, evidence: 'L.O.A. on the profile', source_record: read('profile', [0, 24], [0, 0.6]) },
      lbp_m: unknown('not found printed'),
      breadth_m: { value: 7.2, status: 'read', printed: '7.20 m', unit_context: null, evidence: 'B on the plan', source_record: read('plan', [10, 14], [-3.6, 3.6]) },
      depth_m: unknown('not found printed'), draft_m: unknown('not found printed'),
      scantling_draft_m: unknown('not found printed'), deadweight_t: unknown('not found printed'),
    },
    counts: {
      cargo_holds: { value: 0, status: 'read', evidence: 'No cargo hold drawn', labelled_items: 0, source_record: { kind: 'guessed', method: 'count judged by the model from the drawing', inputs: [{ sheet: MOCK_GA, page: 0, view: null, box_px: null }] } },
      cargo_hatches: unknown('No hatch covers drawn'), cargo_cranes: unknown('Davit only; no cargo crane'),
      cargo_tanks: unknown('Not a tanker'), slop_tanks: unknown('Not a tanker'), container_bays: unknown('Not a container ship'),
    },
    spaces: [
      space('accommodation_deck-001', 'accommodation_deck', 'MAIN DECK', null, 'read', read('profile', [9, 17], [3.4, 5.8])),
      space('accommodation_deck-002', 'accommodation_deck', 'A DECK', null, 'guessed', { kind: 'guessed', method: 'identified from the drawn outline by the model; no printed label', inputs: [gaRegion('profile', [11, 15.5], [5.8, 8.2])] }),
      space('fuel_tank-003', 'fuel_tank', 'D.O. TANK', '1', 'read', read('plan', [17, 19.5], [-2, 2])),
      space('ballast_tank-004', 'ballast_tank', 'W.B. TANK (P)', '1P', 'read', read('plan', [13, 16], [0.2, 2.4])),
    ],
    checks: [],
  };
})();

/** The record of a mock section: its region on the page the drawing pane shows. */
function mockSectionRecord(section, page) {
  const region = { sheet: page.path.split('/').pop(), page: 0, view: 'body plan', box_px: section.roi_px, page_px: [page.width, page.height] };
  return section.state === 'guessed'
    ? { kind: 'guessed', method: section.reason, inputs: [region] }
    : { kind: 'read', regions: [region] };
}

/** Metres aft of frame 0 where ?mocksections starts, so the strip also shows a "-1.0 m" tile. */
const MOCK_SECTIONS_START_M = -1;

/**
 * `count` copies of `sections` (taken in turn), spread evenly from MOCK_SECTIONS_START_M to
 * `lengthM`. Each copy gets its own section and candidate ids.
 */
function spreadSections(sections, count, lengthM) {
  const step = (lengthM - MOCK_SECTIONS_START_M) / (count - 1);
  return Array.from({ length: count }, (_, index) => {
    const copy = JSON.parse(JSON.stringify(sections[index % sections.length]));
    const id = `${copy.id}-${index}`;
    for (const candidate of copy.candidates || []) candidate.id = `${candidate.id}-${index}`;
    if (copy.guess?.chosen_candidate_id) copy.guess.chosen_candidate_id = `${copy.guess.chosen_candidate_id}-${index}`;
    if (copy.guess?.alternatives) copy.guess.alternatives = copy.guess.alternatives.map((alt) => `${alt}-${index}`);
    return { ...copy, id, x_m: Number((MOCK_SECTIONS_START_M + index * step).toFixed(2)) };
  });
}

/**
 * With ?mocktanks the survey launch has one tank part and a capacity plan (made-up values in the
 * shape of app/core run_tables.rs), so the tank tables can be checked on the mock.
 */
const MOCK_TANK_PART = {
  id: 'tank_fw1', op: 'tank', label: 'No 1 fresh water', status: 'draft_guess', built: true, view: 'plan',
  reason: 'height: guessed: the tank height is not drawn', bbox_m: { min: [4, -1.5, 0.2], max: [7, 1.5, 1.4] },
  volume_m3: 4.2, step_path: 'whole_vessel/tank_fw1.step', review: 'open',
  arguments: [{ name: 'outline', value: '4 points', source: 'traced', basis: 'Tank plan region' }, { name: 'height', value: '0.20 to 1.40 m', source: 'guessed', basis: 'Tank height not drawn' }],
  // Sketch outlines as the worker writes them (made-up): the bottom follows the hull, rising aft.
  display: {
    profile_m: [[[4, 0.42], [5, 0.3], [6, 0.23], [7, 0.2], [7, 1.4], [6, 1.4], [5, 1.4], [4, 1.4]]],
    plan_m: [[[4, -1.1], [5, -1.32], [6, -1.45], [7, -1.5], [7, 1.5], [6, 1.45], [5, 1.32], [4, 1.1]]],
    content_class: 'fresh_water',
  },
};
const MOCK_CAPACITY_PLAN = {
  file: 'tank_tables/Survey_launch_r0003_DRAFT_capacity_plan.csv',
  stamp: ['Draft hull model from MarinaFrame. Not for construction.'],
  engineering_approved: false,
  rows: [
    { id: 'tank_fw1', name: 'No 1 fresh water', content: 'fresh water', frames: '6...10', built: true, volume_100_m3: 4.2, volume_98_m3: 4.116, density_t_m3: 1, weight_98_t: 4.116, lcg_m: 5.5, tcg_m: 0, vcg_m: 0.83, max_free_surface_moment_tm: 2.1, printed_volume_m3: 4, sources: { name: 'read', content: 'read', frames: 'read', volume: 'guessed', density: 'read', centroid: 'guessed', weight: 'guessed' }, notes: '', has_sounding: true },
    { id: 'tank_wb1', name: 'No 1 ballast port', content: 'water ballast', frames: '14...18', built: true, volume_100_m3: 9.5, volume_98_m3: 9.31, density_t_m3: 1.025, weight_98_t: 9.543, lcg_m: 14.5, tcg_m: 1.3, vcg_m: 0.75, max_free_surface_moment_tm: 3.2, printed_volume_m3: null, sources: { name: 'read', content: 'read', frames: 'guessed', volume: 'guessed', density: 'guessed', centroid: 'guessed', weight: 'guessed' }, notes: '', has_sounding: false },
    { id: 'tank_wb2', name: 'No 1 ballast starboard', content: 'water ballast', frames: '14...18', built: true, volume_100_m3: 9.5, volume_98_m3: 9.31, density_t_m3: 1.025, weight_98_t: 9.543, lcg_m: 14.5, tcg_m: -1.3, vcg_m: 0.75, max_free_surface_moment_tm: 3.2, printed_volume_m3: null, sources: { name: 'read', content: 'read', frames: 'guessed', volume: 'guessed', density: 'guessed', centroid: 'guessed', weight: 'guessed' }, notes: '', has_sounding: false },
    { id: 'tank_do1', name: 'Diesel oil', content: 'diesel oil', frames: '19...22', built: true, volume_100_m3: 10.0, volume_98_m3: 9.8, density_t_m3: 0.84, weight_98_t: 8.232, lcg_m: 18.25, tcg_m: 0, vcg_m: 0.7, max_free_surface_moment_tm: 4.1, printed_volume_m3: 10, sources: { name: 'read', content: 'read', frames: 'read', volume: 'read', density: 'guessed', centroid: 'guessed', weight: 'guessed' }, notes: '', has_sounding: false },
    { id: 'tank_fo1', name: 'No 1 fuel oil', content: 'fuel oil', frames: '10...12', built: false, volume_100_m3: null, volume_98_m3: null, density_t_m3: 0.85, weight_98_t: null, lcg_m: null, tcg_m: null, vcg_m: null, max_free_surface_moment_tm: null, printed_volume_m3: 2, sources: { name: 'read', content: 'read', frames: 'read', volume: 'guessed', density: 'guessed', centroid: 'guessed', weight: 'guessed' }, notes: 'no plan region holds its label: not built', has_sounding: false },
  ],
  groups: [
    { content: 'fresh water', tanks: 1, built: 1, volume_100_m3: 4.2, weight_98_t: 4.116 },
    { content: 'water ballast', tanks: 2, built: 2, volume_100_m3: 19, weight_98_t: 19.086 },
    { content: 'diesel oil', tanks: 1, built: 1, volume_100_m3: 10, weight_98_t: 8.232 },
    { content: 'fuel oil', tanks: 1, built: 0, volume_100_m3: 0, weight_98_t: 0 },
  ],
};

/** The mock run with many stations, most of them guessed (as on a real 72-station drawing). */
export const MOCK_MANY_GUESSES_TASK = '/Users/demo/MarinaFrame/runs/2026-11-07-research-vessel';
const MOCK_MANY_GUESSES_STATIONS = 72;
/** Every this-many-th station of that run was read; the others are guesses. */
const MOCK_MANY_GUESSES_READ_EVERY = 18;

/**
 * Add the many-guesses run to `data` (the fixtures): a copy of the survey launch with 72 stations
 * from 0 m to the bow, all guessed but every 18th. Each guess is the best candidate at its own
 * station (no x range), so the 3D view spreads it half way to the next station, as on a real run.
 */
export function addManyGuessesRun(data) {
  const fromTask = Object.keys(data.views).find((task) => task.endsWith('survey-launch'));
  const from = data.views[fromTask];
  const guessed = from.sections.find((s) => s.guess && !s.guess.x_range_m);
  const read = from.sections.find((s) => s.state === 'chosen');
  const lengthM = from.model.length_m;
  const view = JSON.parse(JSON.stringify(from));
  const step = lengthM / (MOCK_MANY_GUESSES_STATIONS - 1);
  view.sections = Array.from({ length: MOCK_MANY_GUESSES_STATIONS }, (_, index) => {
    const template = index % MOCK_MANY_GUESSES_READ_EVERY === 0 ? read : guessed;
    const copy = JSON.parse(JSON.stringify(template));
    const x = Number((index * step).toFixed(3));
    const suffix = `-rv${index}`;
    for (const candidate of copy.candidates || []) candidate.id += suffix;
    if (copy.guess) {
      copy.guess.id += suffix;
      if (copy.guess.chosen_candidate_id) copy.guess.chosen_candidate_id += suffix;
      copy.guess.alternatives = (copy.guess.alternatives || []).map((alt) => alt + suffix);
    }
    return { ...copy, id: `st${index}`, x_m: x };
  });
  const name = 'Research vessel, 72 stations';
  view.summary = { ...view.summary, task: MOCK_MANY_GUESSES_TASK, name, policy: 'deterministic', updated_ms: view.summary.updated_ms - 600_000, sections: MOCK_MANY_GUESSES_STATIONS };
  data.views[MOCK_MANY_GUESSES_TASK] = view;
  data.events[MOCK_MANY_GUESSES_TASK] = JSON.parse(JSON.stringify(data.events[fromTask] || []));
  data.tasks.push({ task: MOCK_MANY_GUESSES_TASK, name, status: view.summary.status, policy: 'deterministic', updated_ms: view.summary.updated_ms, sections: MOCK_MANY_GUESSES_STATIONS });
}

export function mockTransport() {
  const listeners = new Set();
  let fixtures = null;
  let playbackStarted = false;

  async function load() {
    if (!fixtures) {
      const response = await fetch(MOCK_FIXTURES_URL);
      fixtures = await response.json();
      addManyGuessesRun(fixtures);
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
  // The task the mock started as the sample vessel (shown even with ?mockempty).
  let sampleTask = null;
  // The person's review of whole-vessel parts in this page session (component id -> decision).
  const componentReviews = new Map();
  // The sign-off of the mock survey launch's parts (SignOffView or null).
  let mockSignOff = null;
  // Parts re-run from a mark in this page session: id -> { part, previous } (ComponentViews).
  const componentRevisions = new Map();

  /** A whole-vessel part as get_task gives it: base or re-run values, plus the review. */
  function mockPart(base) {
    const revised = componentRevisions.get(base.id)?.part;
    return {
      revision: 0, revision_note: null, revision_pending: false, changes: [],
      ...clone(revised || base),
      review: componentReviews.get(base.id)?.decision || 'open',
      review_note: componentReviews.get(base.id)?.note || null,
    };
  }

  /**
   * What a re-run from a mark gives in the mock: the guessed values (else the first value) come
   * back as AI values, a height range 0.2 m lower at the top, and the box and volume to match.
   */
  function mockPartRevision(part, note) {
    const next = clone(part);
    next.revision = (part.revision || 0) + 1;
    next.revision_note = note;
    next.revision_pending = true;
    const targets = part.arguments.some((a) => a.source === 'guessed')
      ? part.arguments.filter((a) => a.source === 'guessed') : part.arguments.slice(0, 1);
    const changes = [];
    next.arguments = part.arguments.map((a) => {
      if (!targets.includes(a)) return a;
      const range = /^(-?\d+\.\d+) to (-?\d+\.\d+) m$/.exec(a.value || '');
      const value = range ? `${range[1]} to ${(Number(range[2]) - 0.2).toFixed(3)} m` : (a.value?.endsWith(' m') ? `${(parseFloat(a.value) * 0.9).toFixed(3)} m` : '4 points, 11.00 to 15.50 m by -1.80 to 1.80 m');
      changes.push({ name: a.name, before: a.value, after: value, before_source: a.source, after_source: 'ai_inferred' });
      return { ...a, value, source: 'ai_inferred', basis: `Revised from your mark: ${note}` };
    });
    if (next.bbox_m) {
      next.bbox_m.max[2] = Number((next.bbox_m.max[2] - 0.2).toFixed(3));
      next.volume_m3 = Number((part.volume_m3 * 0.93).toFixed(1));
      changes.push({ name: 'volume', before: `${part.volume_m3.toFixed(2)} m³`, after: `${next.volume_m3.toFixed(2)} m³`, before_source: null, after_source: null });
    }
    next.status = 'draft_guess';
    next.changes = changes;
    return next;
  }

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
    const order = ['step', 'iges', '3dm', 'stl', 'offsets', 'hydrostatics', 'report', 'tanks', 'structure', 'package', 'manifest'];
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

  /** Batch queue of the mock: waiting sets, and the run slot limit. */
  const MOCK_SLOTS = 3;
  const mockQueue = [];
  const commands = {
    async list_design_records() {
      return (await import('./designs.js')).listMockDesigns();
    },
    async open_design_record(data, { id }) {
      return (await import('./designs.js')).openMockDesign(id);
    },
    async list_design_decisions(data, { project_id }) {
      return (await import('./designs.js')).listMockDecisions(project_id);
    },
    async append_design_decision(data, { project_id, decision }) {
      return (await import('./designs.js')).appendMockDecision(project_id, decision);
    },
    async replace_sheet(data, { task, sheet_id, file }) {
      requireTask(data, task);
      if (!isDrawingFileName(file)) throw new BackendError('sheet_file_type', 'Choose a drawing file.');
      const view = data.views[task];
      const review = view.sheet_review;
      const sheet = review?.sheets.find(s => s.id === sheet_id);
      if (!sheet) throw new BackendError('sheet_not_found', 'This run has no such sheet.');
      const previous = view.revision;
      sheet.status = 'replaced';
      sheet.reason = '';
      sheet.version = (sheet.version || 1) + 1;
      for (const request of review.requests) {
        if (request.sheet_id === sheet_id) request.status = 'answered';
      }
      for (const output of review.outputs) {
        if (output.sheet_ids.includes(sheet_id)) output.status = 'draft';
      }
      view.revision = `r${Number(String(previous).replace('r', '')) + 1}`;
      review.history.push({ sheet_id, label: sheet.label, previous_revision_id: previous,
        revision_id: view.revision, stages: ['read', 'build', 'render', 'check'], status: 'draft', engineering_approved: false });
      emit(task, Date.now());
    },
    async list_tasks(data) {
      // With ?mockempty the runs folder has no runs (a first start).
      if (new URLSearchParams(location.search).has("mockempty")) return data.tasks.filter((t) => t.task === sampleTask).map((t) => ({ ...t, status: "running" }));
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
      // The task view names a revision "r3"; the builds use "r0003".
      const found = builds[revision] || builds[mockRevision(revision)] || Object.values(builds).find((b) => b.path === revision);
      if (!found) throw new BackendError('revision_not_found', 'This build is not in the run folder.');
      return clone(found);
    },
    async get_task(data, { task }) {
      const view = clone(requireTask(data, task));
      // Whole-vessel parts (APP_SPEC "Whole-vessel parts"): the mock gives them to the survey launch.
      // ?mockpartsfile: parts read by app/core from a real run folder into the git-ignored
      // mock/files/parts-local.json (parts.rs ignored test, MARINAFRAME_PARTS_OUT). Local checks only.
      const localParts = new URLSearchParams(location.search).has('mockpartsfile')
        ? await fetch('mock/files/parts-local.json').then((r) => (r.ok ? r.json() : null)).catch(() => null)
        : null;
      view.components = task.endsWith('survey-launch')
        ? clone(localParts || MOCK_COMPONENTS).map(mockPart)
        : null;
      view.sign_off = task.endsWith('survey-launch') ? clone(mockSignOff) : null;
      const mockTanks = task.endsWith('survey-launch') && new URLSearchParams(location.search).has('mocktanks');
      if (mockTanks) view.components.push(mockPart(MOCK_TANK_PART));
      view.capacity_plan = mockTanks ? clone(MOCK_CAPACITY_PLAN) : null;
      // The survey launch has source records; the other mock runs are older runs without them.
      if (task.endsWith('survey-launch')) {
        for (const item of [...(view.components || []), ...(view.capacity_plan?.rows || [])]) {
          if (MOCK_SOURCE_RECORDS[item.id]) item.source_record = clone(MOCK_SOURCE_RECORDS[item.id]);
        }
        if (view.source_page) for (const section of view.sections) section.source_record = mockSectionRecord(section, view.source_page);
      }
      view.tank_model = mockTanks;
      // ?mockga: the survey launch is a GA reading run (made-up values on the mock GA sheet), with no
      // 3D model, so the 3D pane shows the GA panel. ?mockgafile: the reading and sheet of a real
      // development run copied into the git-ignored mock/files/ga-local.json and ga-local.png
      // (local screenshots only; never committed).
      const gaParams = new URLSearchParams(location.search);
      if (task.endsWith('survey-launch') && (gaParams.has('mockga') || gaParams.has('mockgafile'))) {
        const local = gaParams.has('mockgafile')
          ? await fetch('mock/files/ga-local.json').then((r) => (r.ok ? r.json() : null)).catch(() => null)
          : null;
        view.ga_reading = clone(local?.reading || MOCK_GA_READING);
        view.source_page = local ? clone(local.page) : { path: 'ga_reading/ga-1.png', ...MOCK_PAGE };
        view.model = null;
        view.sections = [];
        view.components = null;
        // A GA reading run reviews the GA sheet only: no lines-plan review and no hull warnings.
        view.sheet_review = null;
        view.warnings = [];
      }
      // ?mockstructure (with a structure GLB placed in mock/files; none is shipped): the survey
      // launch has a steel structure for the 3D view.
      view.structure_files = task.endsWith('survey-launch') && new URLSearchParams(location.search).has('mockstructure')
        ? [{ role: 'structure_model', file: 'mock_structure.glb', path: 'structure/mock_structure.glb', bytes: 1_000_000 }]
        : [];
      // With ?mockglb (and a GLB placed in mock/files for a local check; none is shipped) the
      // survey launch has a whole-vessel model; ?mockglbbig makes it too large to load.
      const glbParam = new URLSearchParams(location.search);
      view.whole_vessel_model = task.endsWith('survey-launch') && (glbParam.has('mockglb') || glbParam.has('mockglbbig'))
        ? { glb_path: 'whole-vessel-draft.glb', bytes: glbParam.has('mockglbbig') ? 147_000_000 : 9_000_000, loadable: !glbParam.has('mockglbbig') }
        : null;
      if (isLiveStreaming(data, task)) {
        view.summary.status = 'running';
        // Before the first build, a real run has read no sections and has no model yet.
        const snapshot = liveSnapshot(data, task);
        if (!snapshot.steps.some((step) => step.kind === 'build')) {
          view.sections = [];
          view.model = null;
          view.components = null;
        }
      }
      // ?mocksections=72: the survey launch has that many sections (a long strip, as on a real
      // ship), copies of its three sections spread from 1 m aft of frame 0 to the bow.
      const sectionCount = Number(glbParam.get('mocksections'));
      if (task.endsWith('survey-launch') && sectionCount > view.sections.length) {
        view.sections = spreadSections(view.sections, sectionCount, view.model?.length_m || 24);
      }
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
      // ?mockfair: the hull is the fairness test hull, with a kink and a flat spot planted in it.
      const file = name === 'model.stl' && new URLSearchParams(location.search).has('mockfair') ? 'model-fair.stl' : name;
      const response = await fetch(MOCK_FILES_URL + encodeURIComponent(file));
      if (!response.ok) throw new BackendError('artifact_missing', 'This file is not in the run folder.');
      const blob = await response.blob();
      const mime = name.endsWith('.stl') ? 'model/stl' : blob.type || 'image/png';
      return { mime, base64: await blobToBase64(blob) };
    },
    async list_sources(data, { task }) {
      const view = requireTask(data, task);
      // ?mocksourcesfail: the list cannot be read (the error state of the Sources tab).
      if (new URLSearchParams(location.search).has('mocksourcesfail')) {
        throw new BackendError('runs_folder', 'The run folder could not be read.');
      }
      await pause(150);
      const sources = mockSources(task, view).map(({ image, ...source }) => source);
      return { sources, revision: view.revision ? mockRevision(view.revision) : null };
    },
    async read_source_page(data, { task, source_id, page }) {
      const source = mockSources(task, requireTask(data, task)).find((s) => s.id === source_id);
      if (!source) throw new BackendError('source_not_found', 'This source file is not in the run.');
      if (source.kind === 'spec') {
        const text = JSON.stringify({ schema_version: '1.0', vessel_id: task.split('/').pop(), units: 'm',
          source: { file: 'sources/drawing.png' }, sections: [], engineering_approved: false }, null, 2);
        return { mime: 'application/json', base64: null, text, width: 0, height: 0 };
      }
      const facts = source.pages.find((p) => p.index === page);
      if (!facts) throw new BackendError('source_page_missing', 'The run has no record of this page.');
      await pause(200);
      const response = await fetch(MOCK_FILES_URL + encodeURIComponent(source.image));
      if (!response.ok) throw new BackendError('source_render', 'This page could not be shown.');
      return { mime: 'image/png', base64: await blobToBase64(await response.blob()), text: null, width: facts.width_px, height: facts.height_px };
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
      return { enabled, key_found: keyFound, claude_found: keyFound, active: enabled && keyFound, key_count: keyFound ? 3 : 0,
               key_file: '/Users/demo/.config/marinaframe/opencode-go-keys.txt' };
    },
    /**
     * Batch queue (APP_SPEC "Batch queue"). Dropped files are one set; a folder (a path
     * without an extension) gives five synthetic sets. Synthetic names only.
     */
    async plan_batch(_data, { paths }) {
      await pause(200);
      const folder = paths.some((p) => /[\\/]$/.test(p) || !/\.[a-z0-9]+$/i.test(p));
      if (folder) {
        return {
          sets: ['Survey launch 18 m', 'Harbour tug B', 'Pilot boat 15 m', 'Workboat 12 m', 'Patrol craft 20 m']
            .map((name, i) => ({ name, files: Array.from({ length: 1 + (i % 3) }, (_, k) => `/mock/Yard order/${name}/sheet-${k + 1}.png`) })),
          skipped: [{ path: '/mock/Yard order/notes.txt', reason: 'Not a PDF, PNG, TIFF or JPEG drawing.' }],
        };
      }
      // Files dropped on their own are one set (the intake), as in the backend.
      const stemOf = (p) => p.split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
      return { sets: paths.length ? [{ name: stemOf(paths[0]), files: paths }] : [], skipped: [] };
    },
    async queue_batch(data, { sets }) {
      await pause(300);
      const now = Date.now();
      sets.forEach((set, i) => mockQueue.push({ id: `batch-${now}-${i}`, name: set.name, files: set.files, added_ms: now, state: 'waiting', message: null }));
      return commands.get_queue(data);
    },
    async get_queue(data) {
      const running = data.tasks.filter((t) => t.status === 'running' || isLiveStreaming(data, t.task)).length;
      // Mock pump: free slots take the first waiting sets; they stay "starting" in the mock.
      // With ?mocknokey the AI is not active: sets only wait (the backend's "held").
      const noAi = new URLSearchParams(location.search).has('mocknokey');
      let free = noAi ? 0 : MOCK_SLOTS - running - mockQueue.filter((s) => s.state === 'starting').length;
      for (const set of mockQueue) {
        if (free <= 0) break;
        if (set.state === 'waiting') { set.state = 'starting'; free -= 1; }
      }
      if (new URLSearchParams(location.search).has('mockbatchfail') && mockQueue.length > 2) {
        Object.assign(mockQueue[mockQueue.length - 1], { state: 'failed', message: 'The drawings could not be read.' });
      }
      return { slots: MOCK_SLOTS, running: running + mockQueue.filter((s) => s.state === 'starting').length, waiting: clone(mockQueue), held: noAi && mockQueue.some((s) => s.state === 'waiting') ? 'Waiting sets start when AI drafting is on and a model key is found.' : null };
    },
    async remove_queued(data, { id }) {
      const index = mockQueue.findIndex((s) => s.id === id);
      if (index < 0) throw new BackendError('queue_unknown', 'This set is no longer in the queue.');
      if (mockQueue[index].state === 'starting') throw new BackendError('queue_starting', 'This set is starting; it cannot be removed now.');
      mockQueue.splice(index, 1);
      return commands.get_queue(data);
    },
    async move_queued(data, { id, delta }) {
      const index = mockQueue.findIndex((s) => s.id === id);
      const target = index + Math.sign(delta);
      if (index >= 0 && target >= 0 && target < mockQueue.length) [mockQueue[index], mockQueue[target]] = [mockQueue[target], mockQueue[index]];
      return commands.get_queue(data);
    },
    /**
     * Key usage (Settings). Synthetic meters: ?mockusagefull puts every key near or at a limit,
     * ?mockusageone has one key whose check fails. Never real account data.
     */
    async get_model_usage() {
      await pause(500);
      const params = new URLSearchParams(location.search);
      const inHours = (hours) => new Date(Date.now() + hours * 3_600_000).toISOString();
      const meters = (rolling, weekly, monthly) => [
        { window: 'rolling', percent: rolling, status: rolling < 100 ? 'ok' : 'rate-limited', resets_at: inHours(3) },
        { window: 'weekly', percent: weekly, status: weekly < 100 ? 'ok' : 'rate-limited', resets_at: inHours(52) },
        { window: 'monthly', percent: monthly, status: monthly < 100 ? 'ok' : 'rate-limited', resets_at: inHours(400) },
      ];
      const slot = (number, rolling, weekly, monthly) => {
        const all = [rolling, weekly, monthly];
        const usable = all.every((p) => p < 100);
        return { slot: number, meters: meters(rolling, weekly, monthly), highest_percent: usable ? Math.max(...all) : null, usable, error: null };
      };
      if (params.has('mockusageone')) {
        return {
          key_source: 'key_file', next_slot: 1, checked_ms: Date.now(),
          slots: [{ slot: 1, meters: [], highest_percent: null, usable: false, error: 'Could not reach OpenCode. Check the network and try again.' }],
          warning: 'This key is at a limit or could not be checked. A run may stop until a meter resets.',
        };
      }
      if (params.has('mockusagefull')) {
        return {
          key_source: 'key_file', next_slot: 2, checked_ms: Date.now(),
          slots: [slot(1, 100, 64, 41), slot(2, 93, 71, 58), slot(3, 88, 97, 62)],
          warning: 'Every usable key is near a limit (90% or more). A long run may stop when a meter reaches 100%.',
        };
      }
      return {
        key_source: 'key_file', next_slot: 2, checked_ms: Date.now(),
        slots: [slot(1, 72, 45, 30), slot(2, 18, 33, 21), slot(3, 100, 80, 52)],
        warning: null,
      };
    },
    async get_setup_status(data) {
      await pause(300);
      const settings = { ...data.settings, ...readStored(MOCK_SETTINGS_KEY, {}) };
      // With ?mocknoworker the worker Python is "missing", to show the failing check.
      const workerOk = !new URLSearchParams(location.search).has('mocknoworker');
      return {
        ai: await commands.get_ai_status(data),
        worker: workerOk
          ? { ok: true, path: settings.worker_python, message: 'The CAD worker Python is found.' }
          : { ok: false, path: settings.worker_python, message: 'This Python was not found.' },
        runs_folder: { ok: true, path: settings.runs_folder, message: 'Runs are saved here.' },
      };
    },
    async sign_off(data, { task, name }) {
      requireTask(data, task);
      await pause(300);
      if (!name?.trim()) {
        mockSignOff = null;
        return null;
      }
      const open = MOCK_COMPONENTS.filter((c) => !['accepted', 'marked'].includes(componentReviews.get(c.id)?.decision)).length;
      if (open) throw new BackendError('sign_off_open_parts', `Review every part first: ${open} still open.`);
      mockSignOff = { name: name.trim(), time_ms: Date.now(), statement: 'usable as a starting model' };
      return mockSignOff;
    },
    async review_component(data, { task, component_id: id, decision, note }) {
      requireTask(data, task);
      if (!['accepted', 'marked', 'open'].includes(decision)) throw new BackendError('review_decision', 'Unknown review decision.');
      const text = (note || '').trim();
      if (decision === 'marked' && (!text || text.length > 500)) throw new BackendError('review_note', 'Say what to change, in 1 to 500 characters.');
      await pause(300);
      componentReviews.set(id, { decision, note: decision === 'marked' ? text : null });
      if (decision === 'open') mockSignOff = null;
      return { ok: true };
    },
    // Re-run one part from its mark (APP_SPEC "Whole-vessel parts"). ?mockrevisefail: the
    // model's replies do not build, as the worker reports it.
    async revise_part(data, { task, component_id: id }) {
      requireTask(data, task);
      const base = MOCK_COMPONENTS.find((c) => c.id === id);
      if (!base) throw new BackendError('component_not_found', 'This run has no such part.');
      const review = componentReviews.get(id);
      if (review?.decision !== 'marked' || !review.note) throw new BackendError('revise_needs_mark', 'Mark the part and say what to change first.');
      await pause(3000);
      if (new URLSearchParams(location.search).has('mockrevisefail')) {
        throw new BackendError('part_revise_worker', 'The part was not rebuilt (outline self-intersects); the old part stays.');
      }
      const current = mockPart(base);
      componentRevisions.set(id, { part: mockPartRevision(current, review.note), previous: componentRevisions.get(id) || null });
      mockSignOff = null;
      return mockPart(base);
    },
    async keep_part_revision(data, { task, component_id: id }) {
      requireTask(data, task);
      const revised = componentRevisions.get(id);
      if (!revised?.part.revision_pending) throw new BackendError('part_revise_worker', 'This part has no new revision to keep or undo.');
      await pause(300);
      revised.part.revision_pending = false;
      componentReviews.set(id, { decision: 'open', note: null });
      mockSignOff = null;
      return mockPart(MOCK_COMPONENTS.find((c) => c.id === id));
    },
    async undo_part_revision(data, { task, component_id: id }) {
      requireTask(data, task);
      const revised = componentRevisions.get(id);
      if (!revised?.part.revision_pending) throw new BackendError('part_revise_worker', 'This part has no new revision to keep or undo.');
      await pause(300);
      if (revised.previous) componentRevisions.set(id, revised.previous);
      else componentRevisions.delete(id);
      return mockPart(MOCK_COMPONENTS.find((c) => c.id === id));
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
    async sounding_table(data, { task, tank_id }) {
      requireTask(data, task);
      if (tank_id !== 'tank_fw1') throw new BackendError('sounding_not_found', 'This run has no sounding table for that tank.');
      const levels = [0, 0.3, 0.6, 0.9, 1.2];
      return {
        tank_id, file: 'tank_tables/Survey_launch_r0003_DRAFT_sounding_tank_fw1.csv', stamp: [], engineering_approved: false,
        columns: ['sounding_m', 'ullage_m', 'volume_m3', 'fill_pct'],
        rows: levels.map((level) => [level, 1.2 - level, 3.5 * level, (100 * level) / 1.2]),
      };
    },
    async list_exports(data, { task, revision }) {
      requireTask(data, task);
      return mockExportResult(task, revision);
    },
    async export_run(data, { task, revision, outputs, viewer_image: viewerImage = null }) {
      const view = requireTask(data, task);
      if (!outputs?.length) throw new BackendError('export_outputs', 'Choose at least one export.');
      // The preview writes no files; it keeps the last 3D view picture for a local check (the app writes it into the export).
      globalThis.mockLastViewerImage = viewerImage;
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
        for (const [suffix, bytes] of data.export_files[kind]) add(kind, suffix, bytes);
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
      if (files[0] === MOCK_DRAWINGS_FILE) {
        const drawings = await fetch(MOCK_DRAWINGS_URL).then((r) => r.json());
        return mockDrawingSetPreview(drawings, await mockThumbnail(), status.active);
      }
      return mockIntakePreview(files, await mockThumbnail(), status.active);
    },
    async start_sample_run(data) {
      await pause(500);
      // The mock plays its one recorded live run as the sample.
      const task = Object.keys(data.live || {})[0];
      if (!task) throw new BackendError('mock_mode', 'Runs cannot start in the preview.');
      liveStream = true;
      liveStreamStarted = 0;
      sampleTask = task;
      data.views[task].summary.name = 'Sample hull';
      data.tasks.find((t) => t.task === task).name = 'Sample hull';
      return { task };
    },
    async cancel_intake() {
      return { ok: true };
    },
    async start_intake_run(data, { preview }) {
      await pause(700);
      if (!preview.pages.some((page) => !page.skip)) throw new BackendError('intake_no_pages', 'Every page is skipped. Keep at least one page.');
      // The preview has one recorded live run: the new run plays it from the first step.
      const task = Object.keys(data.live || {})[0];
      if (!task) throw new BackendError('mock_mode', 'Runs cannot start in the preview.');
      liveStream = true;
      liveStreamStarted = 0;
      // Like the backend, the run takes the vessel name typed at intake.
      const typedName = preview.particulars?.vessel_name?.trim();
      if (typedName) {
        data.views[task].summary.name = typedName;
        data.tasks.find((t) => t.task === task).name = typedName;
      }
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
    async pickDrawingFiles({ multiple = true } = {}) {
      if (!multiple) return [MOCK_DRAWING_SET[0]];
      // With ?mockset=N (2 to 16) the set is N scanned sheets plus the PDF: a customer's full set.
      if (new URLSearchParams(location.search).has('mockdrawings')) return [MOCK_DRAWINGS_FILE];
      const sheets = Number(new URLSearchParams(location.search).get('mockset'));
      if (sheets >= 2 && sheets <= 16) {
        return [MOCK_DRAWING_SET[0], ...Array.from({ length: sheets }, (_, i) => `/Users/demo/Downloads/sheet-${String(i + 1).padStart(2, '0')}-lines-plan-scan.tif`)];
      }
      return MOCK_DRAWING_SET;
    },
    onFileDrop(handlers) {
      listenForBrowserDrops(handlers, async (file) => `/Users/demo/Downloads/${file.name}`);
    },
  };
}

