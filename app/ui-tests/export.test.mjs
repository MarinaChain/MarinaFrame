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
