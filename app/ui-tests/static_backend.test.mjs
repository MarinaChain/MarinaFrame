// The static, read-only backend of the web demo (app/ui/static/backend.js) on a fake file
// tree: read commands answer from the exported files, every change is refused.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createStaticBackend, staticTransport, artifactMime, bufferToBase64,
  READ_ONLY_CODE, READ_ONLY_MESSAGE, DEMO_RUNS_FOLDER,
} from '../ui/static/backend.js';

const TASK = `${DEMO_RUNS_FOLDER}/demo-hull`;
const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]);

/** The exported files of one run, as build_web_demo.py writes them. */
function demoFiles() {
  return {
    'data/manifest.json': {
      format: 1, read_only: true,
      runs: [{ slug: 'demo-hull', name: 'Demo hull', licence: 'synthetic', source: 'Made for the test.',
        summary: { task: TASK, name: 'Demo hull', status: 'needs_review', policy: 'deterministic', updated_ms: 5, sections: 2 } }],
    },
    'data/runs/demo-hull/task.json': {
      summary: { task: TASK, name: 'Demo hull' }, revision: 'r0002',
      notices: [{ id: 'n1', tone: 'info', text: 'One' }, { id: 'n2', tone: 'warn', text: 'Two' }],
    },
    'data/runs/demo-hull/events.json': [{ sequence: 1, text: 'a' }, { sequence: 2, text: 'b' }, { sequence: 3, text: 'c' }],
    'data/runs/demo-hull/live.json': { steps: [{ last_sequence: 4 }, { last_sequence: 9 }], last_sequence: 9, finished: true },
    'data/runs/demo-hull/sections.json': { r0002: { revision: 'r0002', path: 'builds/r0002', sections: [{ id: 's1' }] }, 'builds/r0002': { revision: 'r0002', sections: [] } },
    'data/runs/demo-hull/sources.json': { revision: 'r0002', sources: [{ id: 'src1', kind: 'drawing', previewable: true }] },
    'data/runs/demo-hull/pages.json': {
      'src1|0|full': { mime: 'image/png', file: 'pages/src1-0-full.png', text: null, width: 4096, height: 2000 },
      'spec1|0|thumb': { mime: 'text/plain', text: '{"name":"x"}', width: 0, height: 0 },
    },
    'data/runs/demo-hull/pages/src1-0-full.png': PNG_BYTES,
    'data/runs/demo-hull/files/domain/page.png': PNG_BYTES,
    'data/runs/demo-hull/exports.json': {
      r0002: { folder: 'exports/r0002', revision: 'r0002', files: [{ kind: 'step', file: 'Demo_r0002_DRAFT.step', path: 'exports/r0002/Demo_r0002_DRAFT.step', bytes: 10 }],
        not_built: [], format_results: {}, display_omissions: [], stamp: 'Draft', engineering_approved: false },
    },
    'data/runs/demo-hull/tables.json': { tank_1: { tank_id: 'tank_1', rows: [[0, 1]] } },
  };
}

function fakeFetch(files, requested = []) {
  return async (url) => {
    requested.push(url);
    if (!(url in files)) return { ok: false, status: 404 };
    const body = files[url];
    return {
      ok: true,
      json: async () => structuredClone(body),
      arrayBuffer: async () => body.buffer.slice(0),
    };
  };
}

const backend = (files = demoFiles(), requested) => createStaticBackend({ fetchImpl: fakeFetch(files, requested), base: 'data/' });

test('list_tasks gives the manifest runs with their source credit', async () => {
  const tasks = await backend().invoke('list_tasks');
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].task, TASK);
  assert.equal(tasks[0].demo_source, 'Made for the test.');
});

test('a concept-preview run is flagged in the list and on its view; the list keeps the demo order', async () => {
  const files = demoFiles();
  const manifest = files['data/manifest.json'];
  const concept = { ...structuredClone(manifest.runs[0]), slug: 'concept-launch', concept: true, tagline: 'Concept preview: Survey launch' };
  concept.summary.task = `${DEMO_RUNS_FOLDER}/concept-launch`;
  manifest.runs.unshift(concept);
  files['data/runs/concept-launch/task.json'] = { summary: { task: concept.summary.task }, notices: [] };
  const demo = backend(files);
  const tasks = await demo.invoke('list_tasks');
  assert.deepEqual(tasks.map((t) => [t.demo_order, t.demo_concept, t.demo_tagline]), [[0, true, 'Concept preview: Survey launch'], [1, false, null]]);
  assert.equal((await demo.invoke('get_task', { task: concept.summary.task })).demo.concept, true);
  assert.deepEqual((await demo.invoke('get_task', { task: TASK })).demo,
    { concept: false, credit: null, note: null, whole_vessel_first: false, section_lines: true, see_through: false });
});

test('a run with a credit line carries it on its view', async () => {
  const files = demoFiles();
  Object.assign(files['data/manifest.json'].runs[0], {
    credit: 'Drawings: someone, used under licence.', note: 'Bow flagged.', whole_vessel_first: true, section_lines: false, see_through: true,
  });
  const view = await backend(files).invoke('get_task', { task: TASK });
  assert.deepEqual(view.demo, {
    concept: false, credit: 'Drawings: someone, used under licence.', note: 'Bow flagged.', whole_vessel_first: true, section_lines: false, see_through: true,
  });
});

test('get_task answers from task.json and leaves out notices dismissed in this page', async () => {
  const demo = backend();
  assert.equal((await demo.invoke('get_task', { task: TASK })).notices.length, 2);
  await demo.invoke('dismiss_notice', { id: 'n1' });
  assert.deepEqual((await demo.invoke('get_task', { task: TASK })).notices.map((n) => n.id), ['n2']);
  await demo.invoke('reset_notices');
  assert.equal((await demo.invoke('get_task', { task: TASK })).notices.length, 2);
});

test('a task outside the manifest is refused before any run file is read', async () => {
  const requested = [];
  const demo = backend(demoFiles(), requested);
  for (const task of ['/MarinaFrame/runs/other', '/Users/someone/runs/demo-hull', `${DEMO_RUNS_FOLDER}/../demo-hull`, 7]) {
    await assert.rejects(demo.invoke('get_task', { task }), { code: 'task_not_found' });
  }
  assert.deepEqual(requested, ['data/manifest.json']);
});

test('events and live steps are filtered by after_sequence', async () => {
  const demo = backend();
  assert.deepEqual((await demo.invoke('get_events', { task: TASK, after_sequence: 1 })).map((e) => e.sequence), [2, 3]);
  const live = await demo.invoke('get_live_steps', { task: TASK, after_sequence: 4 });
  assert.deepEqual(live.steps.map((s) => s.last_sequence), [9]);
  assert.equal(live.last_sequence, 9);
  // A second read starts from the stored steps again (no shared mutation).
  assert.equal((await demo.invoke('get_live_steps', { task: TASK, after_sequence: 0 })).steps.length, 2);
});

test('hull sections are found by revision id or build path', async () => {
  const demo = backend();
  assert.equal((await demo.invoke('get_hull_sections', { task: TASK, revision: 'r0002' })).sections.length, 1);
  assert.equal((await demo.invoke('get_hull_sections', { task: TASK, revision: 'builds/r0002' })).revision, 'r0002');
  await assert.rejects(demo.invoke('get_hull_sections', { task: TASK, revision: 'r0009' }), { code: 'revision_not_found' });
});

test('read_artifact sends base64 of an exported image and refuses unsafe paths and types', async () => {
  const demo = backend();
  const artifact = await demo.invoke('read_artifact', { task: TASK, path: 'domain/page.png' });
  assert.equal(artifact.mime, 'image/png');
  assert.equal(artifact.base64, Buffer.from(PNG_BYTES).toString('base64'));
  for (const path of ['../task.json', '/etc/passwd', 'domain//page.png', 'domain/./page.png', 'a\\b.png', 'task.json', 'x.step']) {
    await assert.rejects(demo.invoke('read_artifact', { task: TASK, path }), { code: 'unsafe_artifact_path' }, path);
  }
});

test('read_source_page gives an image page as base64 and a spec page as text', async () => {
  const demo = backend();
  const page = await demo.invoke('read_source_page', { task: TASK, source_id: 'src1', page: 0, size: 'full' });
  assert.equal(page.width, 4096);
  assert.equal(page.base64, Buffer.from(PNG_BYTES).toString('base64'));
  assert.equal('file' in page, false);
  const spec = await demo.invoke('read_source_page', { task: TASK, source_id: 'spec1', page: 0, size: 'thumb' });
  assert.equal(spec.base64, null);
  assert.equal(spec.text, '{"name":"x"}');
  await assert.rejects(demo.invoke('read_source_page', { task: TASK, source_id: 'src1', page: 3, size: 'full' }), { code: 'source_not_found' });
});

test('list_exports links each existing file for download and has no folder to show', async () => {
  const demo = backend();
  const result = await demo.invoke('list_exports', { task: TASK, revision: 'r0002' });
  assert.equal(result.files[0].path, 'data/runs/demo-hull/exports/r0002/Demo_r0002_DRAFT.step');
  assert.equal(result.folder, '');
  assert.equal(result.engineering_approved, false);
  const none = await demo.invoke('list_exports', { task: TASK, revision: 'r0001' });
  assert.deepEqual(none.files, []);
});

test('sounding_table answers for an exported tank only', async () => {
  const demo = backend();
  assert.equal((await demo.invoke('sounding_table', { task: TASK, tank_id: 'tank_1' })).tank_id, 'tank_1');
  await assert.rejects(demo.invoke('sounding_table', { task: TASK, tank_id: 'tank_9' }), { code: 'sounding_not_found' });
});

test('settings, AI, setup and queue say the demo runs nothing', async () => {
  const demo = backend();
  assert.equal((await demo.invoke('get_settings')).ai_drafting, false);
  assert.equal((await demo.invoke('get_ai_status')).active, false);
  const setup = await demo.invoke('get_setup_status');
  assert.equal(setup.worker.ok, true);
  assert.equal(setup.runs_folder.path, DEMO_RUNS_FOLDER);
  assert.deepEqual((await demo.invoke('get_queue')).waiting, []);
  assert.deepEqual(await demo.invoke('list_datasets'), []);
});

test('every command that starts or changes a run is refused as read-only', async () => {
  const requested = [];
  const demo = backend(demoFiles(), requested);
  const writes = [
    'start_run', 'start_sample_run', 'prepare_intake', 'start_intake_run', 'cancel_intake', 'export_run',
    'reveal_export', 'review_component', 'revise_part', 'keep_part_revision', 'undo_part_revision', 'sign_off',
    'replace_sheet', 'cancel_task', 'resume_task', 'choose_line', 'revise_region', 'force_keep_revision',
    'set_settings', 'plan_batch', 'queue_batch', 'remove_queued', 'move_queued', 'get_model_usage',
    'toString', 'constructor', '__proto__',
  ];
  for (const command of writes) {
    await assert.rejects(demo.invoke(command, { task: TASK }), { code: READ_ONLY_CODE, message: READ_ONLY_MESSAGE }, command);
  }
  assert.deepEqual(requested, [], 'a refused command reads no file');
});

test('the transport is read-only, with no pickers, drops or live updates', async () => {
  const transport = staticTransport({ fetchImpl: fakeFetch(demoFiles()) });
  assert.equal(transport.name, 'static');
  assert.equal(transport.readOnly, true);
  assert.equal(transport.canPick(), false);
  await assert.rejects(transport.pickDrawingFiles(), { code: READ_ONLY_CODE });
  await assert.rejects(transport.pickSpecFile(), { code: READ_ONLY_CODE });
  assert.equal(typeof transport.onTaskChanged(() => {}), 'function');
});

test('a missing file is a plain error, and a failed load is tried again', async () => {
  const files = demoFiles();
  delete files['data/runs/demo-hull/events.json'];
  const demo = backend(files);
  await assert.rejects(demo.invoke('get_events', { task: TASK }), { code: 'not_found' });
  files['data/runs/demo-hull/events.json'] = [{ sequence: 1 }];
  assert.equal((await demo.invoke('get_events', { task: TASK })).length, 1);
});

test('helpers: artifact types and base64 of a large buffer', () => {
  assert.equal(artifactMime('a/b.GLB'), 'model/gltf-binary');
  assert.equal(artifactMime('a/b.stl'), 'model/stl');
  assert.equal(artifactMime('a/b.json'), null);
  const big = new Uint8Array(200_000).map((_, i) => i % 251);
  assert.equal(bufferToBase64(big.buffer), Buffer.from(big).toString('base64'));
});
