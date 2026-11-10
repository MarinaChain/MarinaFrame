import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createExport, outputsOf } from '../ui/js/export.js';

const CAD_OUTPUTS = [
  { kind: 'iges', name: 'IGES', hint: 'Hull surfaces for CAD, millimetres. Use STEP for solids.' },
  { kind: '3dm', name: 'Rhino 3dm', hint: 'Rhino file with a layer per output, millimetres; curved trimmed faces are meshes.' },
];

class FakeNode {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.className = ''; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  get textContent() { return this.children.map((child) => typeof child === 'string' ? child : child.textContent).join(''); }
  findAll(test) { return [...(test(this) ? [this] : []), ...this.children.filter((child) => typeof child !== 'string').flatMap((child) => child.findAll(test))]; }
}
globalThis.Node = FakeNode;
globalThis.document = { createElement: (tag) => new FakeNode(tag), createElementNS: (_, tag) => new FakeNode(tag), querySelector: () => null };

test('CAD formats have the requested short names and tooltip details', () => {
  assert.deepEqual(outputsOf({}).slice(0, 4).map((output) => output.kind), ['step', 'iges', '3dm', 'stl']);
  for (const expected of CAD_OUTPUTS) {
    const output = outputsOf({}).find((output) => output.kind === expected.kind);
    assert.ok(output);
    assert.equal(output.name, expected.name);
    assert.equal(output.hint, expected.hint);
  }
});

test('a failed format shows the reason while other files stay available', async () => {
  const host = new FakeNode('div');
  const page = createExport({ host, invoke: async () => ({
    files: [{ kind: 'step', file: 'model.step', path: '/task/model.step', bytes: 100 }],
    folder: '/task/exports/r0003', not_built: ['iges'],
    format_results: { iges: { status: 'failed', reason: 'IGES writer failed' } },
  }) });
  await page.show('/task', { revision: 'r0003', summary: { status: 'draft' } });
  const iges = host.findAll((node) => node.dataset.kind === 'iges')[0];
  assert.match(iges.textContent, /IGES writer failed/);
  const step = host.findAll((node) => node.dataset.kind === 'step')[0];
  assert.ok(step.findAll((node) => node.className === 'export-size').length);
});

test('the package row explains an omitted revision-mismatched display', async () => {
  const host = new FakeNode('div');
  const page = createExport({ host, invoke: async () => ({
    files: [], folder: '/task/exports/r0001', not_built: [],
    display_omissions: [{ file: 'whole-vessel-draft.glb', reason: "display model belongs to revision 'r0002'" }],
  }) });
  await page.show('/task', { revision: 'r0001', summary: { status: 'draft' } });
  const row = host.findAll((node) => node.dataset.kind === 'package')[0];
  assert.match(row.textContent, /whole-vessel-draft\.glb.*r0002/);
});

test('IGES and 3dm rows show their name and hint, send their kinds, and reveal their files', async () => {
  const host = new FakeNode('div');
  const calls = [];
  const files = CAD_OUTPUTS.map(({ kind }) => ({ kind, file: `V_r0003_DRAFT_model.${kind}`, path: `/task/exports/r0003/V_r0003_DRAFT_model.${kind}`, bytes: 1200 }));
  const page = createExport({ host, invoke: async (command, args) => {
    calls.push({ command, args });
    return { files, folder: '/task/exports/r0003', not_built: [] };
  } });
  await page.show('/task', { revision: 'r0003', summary: { status: 'draft' } });
  for (const output of CAD_OUTPUTS) {
    const row = host.findAll((node) => node.dataset.kind === output.kind)[0];
    assert.ok(row);
    const toggle = row.findAll((node) => node.className === 'export-toggle')[0];
    assert.ok(toggle);
    assert.equal(row.findAll((node) => node.className === 'export-name')[0].textContent, output.name);
    // Like every other output, the hint is a subtitle line under the name.
    assert.equal(row.findAll((node) => node.className === 'export-hint')[0].textContent, output.hint);
  }
  for (const output of outputsOf({}).filter((output) => !CAD_OUTPUTS.some(({ kind }) => kind === output.kind))) {
    const row = host.findAll((node) => node.dataset.kind === output.kind)[0];
    row.findAll((node) => node.className === 'export-toggle')[0].listeners.click();
  }
  await host.findAll((node) => node.tag === 'button' && node.textContent === 'Export')[0].listeners.click();
  assert.deepEqual(calls.find((call) => call.command === 'export_run').args.outputs, ['iges', '3dm']);
  for (const output of CAD_OUTPUTS) {
    const row = host.findAll((node) => node.dataset.kind === output.kind)[0];
    const finder = row.findAll((node) => node.attributes['aria-label'] === `Show ${output.name} in Finder`)[0];
    assert.equal(finder.attributes.disabled, undefined);
    await finder.listeners.click();
    assert.equal(calls.at(-1).command, 'reveal_export');
    assert.equal(calls.at(-1).args.path, files.find((file) => file.kind === output.kind).path);
  }
});

test('mock fixtures write and list both CAD formats', async () => {
  const fixtures = JSON.parse(fs.readFileSync(new URL('../ui/mock/fixtures.json', import.meta.url)));
  assert.ok(fixtures.export_files, 'Mock export file fixtures are missing.');
  assert.deepEqual(fixtures.export_files.iges[0][0], 'model.iges');
  assert.deepEqual(fixtures.export_files['3dm'][0][0], 'model.3dm');
  globalThis.window = {};
  globalThis.location = { search: '' };
  globalThis.fetch = async (url) => {
    assert.equal(url, 'mock/fixtures.json');
    return { json: async () => structuredClone(fixtures) };
  };
  const api = await import('../ui/js/api.js');
  const task = fixtures.tasks.find((task) => task.status === 'draft').task;
  const result = await api.invoke('export_run', { task, revision: 'r3', outputs: ['3dm', 'iges'] });
  assert.deepEqual(result.files.map((file) => file.kind), ['iges', '3dm', 'manifest']);
  assert.ok(result.files.every((file) => file.bytes > 0));
  const listed = await api.invoke('list_exports', { task, revision: 'r3' });
  assert.deepEqual(listed.files, result.files);
});

/** Export page with the given capture function; resolves to the export_run arguments. */
async function exportWith(captureView, chosenKinds) {
  const host = new FakeNode('div');
  const calls = [];
  const page = createExport({ host, captureView, invoke: async (command, args) => {
    calls.push({ command, args });
    return { files: [], folder: '/task/exports/r0003', not_built: [] };
  } });
  await page.show('/task', { revision: 'r0003', summary: { status: 'draft' } });
  for (const output of outputsOf({})) {
    const toggle = host.findAll((node) => node.dataset.kind === output.kind)[0].findAll((node) => node.className === 'export-toggle')[0];
    const on = chosenKinds.includes(output.kind);
    // Every output starts chosen; click the ones that must change.
    if (!on) toggle.listeners.click();
  }
  await host.findAll((node) => node.tag === 'button' && node.textContent === 'Export')[0].listeners.click();
  return calls.find((call) => call.command === 'export_run').args;
}

test('the report export sends the 3D view picture of this run', async () => {
  const seen = [];
  const args = await exportWith((task, revision) => { seen.push([task, revision]); return 'iVBORw0KGgoAAAA'; }, ['report']);
  assert.equal(args.viewer_image, 'iVBORw0KGgoAAAA');
  assert.deepEqual(seen, [['/task', 'r0003']]);
});

test('the package carries the report, so it sends the picture too', async () => {
  assert.equal((await exportWith(() => 'iVBORw0KGgoAAAA', ['package'])).viewer_image, 'iVBORw0KGgoAAAA');
});

test('without the report or the package no picture is taken', async () => {
  let taken = 0;
  const args = await exportWith(() => { taken += 1; return 'iVBORw0KGgoAAAA'; }, ['stl', 'offsets']);
  assert.equal(args.viewer_image, null);
  assert.equal(taken, 0);
});

test('a view that shows another run, or fails to draw, still exports the report without a picture', async () => {
  assert.equal((await exportWith(() => null, ['report'])).viewer_image, null);
  assert.equal((await exportWith(() => { throw new Error('no WebGL'); }, ['report'])).viewer_image, null);
});
