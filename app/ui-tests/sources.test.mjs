import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSources, groupSources, sourceFacts } from '../ui/js/sources.js';

class FakeNode {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.className = ''; this.hidden = false; this.disabled = false; this.focused = false;
    this.style = { setProperty() {} };
    this.classList = { add: (name) => { this.className = `${this.className} ${name}`.trim(); } };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) {
    this.attributes[key] = String(value);
    if (key === 'hidden') this.hidden = true;
  }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  focus() { this.focused = true; }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join(''); }
  findAll(match) {
    return [...(match(this) ? [this] : []), ...this.children.filter((c) => typeof c !== 'string').flatMap((c) => c.findAll(match))];
  }
}
globalThis.Node = FakeNode;
globalThis.document = { createElement: (tag) => new FakeNode(tag), createElementNS: (_, tag) => new FakeNode(tag) };

const page = (index, sheetType = null, scale = null) => ({ index, sheet_type: sheetType, scale, width_px: 1600, height_px: 1000, dpi: 200, replaced: false });
const source = (id, fields) => ({
  id, version: 1, status: 'current', pages: [page(0)], size_bytes: 2_400_000, sha256: 'ab'.repeat(32), added_ms: 1_000,
  used_from: 'r0000', used_to: null, replaced_by: null, note: null, previewable: true, ...fields,
});
const SOURCES = [
  source('old', { name: 'lines.pdf', kind: 'pdf', role: 'Main drawing', status: 'replaced', used_to: 'r0001', replaced_by: 'new',
    pages: [{ ...page(0, 'Lines plan', '1:50'), replaced: true }, page(1, 'Other')] }),
  source('ga', { name: 'ga.png', kind: 'drawing', role: 'Sheet', pages: [page(0, 'General arrangement', '1:100')] }),
  source('new', { name: 'lines.pdf, version 2', kind: 'pdf', role: 'Replacement for lines.pdf', version: 2, used_from: 'r0002',
    pages: [page(0), page(1), page(2)] }),
  source('spec', { name: 'spec.json', kind: 'spec', role: 'Run spec as given', pages: [] }),
];

/** A fake backend: records every call; `fail` makes list_sources throw. */
function backend({ sources = SOURCES, fail = null } = {}) {
  const calls = [];
  const invoke = async (command, args) => {
    calls.push({ command, args });
    if (command === 'list_sources') {
      if (fail) throw { code: 'runs_folder', message: fail };
      return { sources, revision: 'r0002' };
    }
    if (args.source_id === 'spec') return { mime: 'application/json', base64: null, text: '{"units": "m"}', width: 0, height: 0 };
    return { mime: 'image/png', base64: `${args.source_id}-${args.page}-${args.size}`, text: null, width: 800, height: 500 };
  };
  return { invoke, calls };
}

/** A viewer that records the pages it is given instead of drawing them. */
function fakeViewer() {
  const shown = [];
  return { shown, create: () => ({ setPage: (p, url) => shown.push(p ? { ...p, url } : null), zoomIn() {}, zoomOut() {}, fitPage() {} }) };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const rows = (root) => root.findAll((n) => n.tag === 'button' && n.className.startsWith('source-row'));
const byText = (root, text) => root.findAll((n) => n.tag === 'button' && n.attributes['aria-label']?.startsWith(text))[0];

test('current files group by kind; a replaced file is only an earlier version', () => {
  const groups = groupSources(SOURCES);
  assert.deepEqual(groups.map((g) => [g.title, g.items.map((s) => s.id)]), [
    ['Drawings', ['ga']], ['PDFs', ['new']], ['Spec inputs', ['spec']], ['Earlier versions', ['old']],
  ]);
  assert.deepEqual(sourceFacts(SOURCES[1]), ['1 page', 'General arrangement · Scale 1:100', '2.4 MB', 'Used from r0000']);
  assert.deepEqual(sourceFacts(SOURCES[0]), ['2 pages', '2.4 MB', 'Used in r0000 to r0001']);
});

test('the list shows each file with its facts and picks the first current file', async () => {
  const host = new FakeNode('section');
  const { invoke, calls } = backend();
  const viewer = fakeViewer();
  const sources = createSources({ host, invoke, createViewer: viewer.create });
  await sources.show('/runs/a', 'r0002|1');
  await settle();
  const listed = rows(host);
  assert.deepEqual(listed.map((r) => r.dataset.source), ['ga', 'new', 'spec', 'old']);
  assert.match(host.textContent, /Earlier versions/);
  assert.match(listed[3].textContent, /Replaced/);
  assert.match(listed[0].textContent, /General arrangement · Scale 1:100/);
  assert.equal(listed[0].attributes['aria-selected'], 'true');
  assert.equal(listed[0].attributes.tabindex, '0');
  assert.equal(listed[1].attributes.tabindex, '-1');
  assert.deepEqual(sources.selection, { id: 'ga', page: 0 });
  // Thumbnails for page files, the large page for the selection; the spec has no thumbnail.
  const pages = calls.filter((c) => c.command === 'read_source_page').map((c) => `${c.args.source_id}:${c.args.size}`);
  assert.deepEqual(pages.filter((p) => p.endsWith('thumb')).sort(), ['ga:thumb', 'new:thumb', 'old:thumb']);
  assert.ok(pages.includes('ga:full'));
  assert.deepEqual(viewer.shown.at(-1), { path: '/runs/a|ga|0', width: 800, height: 500, url: 'data:image/png;base64,ga-0-full' });
  // The UI names files by id only, never by a path.
  assert.ok(calls.every((c) => !('path' in c.args)));
  // The same key does not read the run folder again.
  await sources.show('/runs/a', 'r0002|1');
  assert.equal(calls.filter((c) => c.command === 'list_sources').length, 1);
});

test('selecting a multi-page file shows its pages one by one with the page buttons and keys', async () => {
  const host = new FakeNode('section');
  const { invoke } = backend();
  const viewer = fakeViewer();
  const sources = createSources({ host, invoke, createViewer: viewer.create });
  await sources.show('/runs/a', 'k');
  await rows(host)[1].listeners.click();
  await settle();
  assert.deepEqual(sources.selection, { id: 'new', page: 0 });
  assert.equal(rows(host)[1].attributes['aria-selected'], 'true');
  assert.match(host.textContent, /Page 1 of 3/);
  const back = byText(host, 'Previous page');
  const next = byText(host, 'Next page');
  assert.equal(back.disabled, true);
  next.listeners.click();
  await settle();
  assert.deepEqual(sources.selection, { id: 'new', page: 1 });
  assert.equal(viewer.shown.at(-1).url, 'data:image/png;base64,new-1-full');
  const pageHost = host.findAll((n) => n.className.includes('source-host'))[0];
  let prevented = false;
  pageHost.listeners.keydown({ key: 'PageDown', preventDefault: () => { prevented = true; } });
  await settle();
  assert.ok(prevented);
  assert.deepEqual(sources.selection, { id: 'new', page: 2 });
  assert.equal(next.disabled, true);
  // Arrow keys in the list move to the next file and its row takes the focus.
  const list = host.findAll((n) => n.attributes.role === 'listbox')[0];
  list.listeners.keydown({ key: 'ArrowDown', preventDefault() {} });
  await settle();
  assert.deepEqual(sources.selection, { id: 'spec', page: 0 });
  assert.ok(rows(host)[2].focused);
  // A spec input shows as text, not as a page.
  assert.match(host.findAll((n) => n.tag === 'pre')[0].textContent, /"units": "m"/);
});

test('an earlier version says what replaced it', async () => {
  const host = new FakeNode('section');
  const sources = createSources({ host, invoke: backend().invoke, createViewer: fakeViewer().create });
  await sources.show('/runs/a', 'k');
  sources.select('old');
  await settle();
  const details = host.findAll((n) => n.tag === 'dl')[0].textContent;
  assert.match(details, /StatusReplaced/);
  assert.match(details, /Replaced bylines\.pdf, version 2/);
  assert.match(details, /RevisionsUsed in r0000 to r0001/);
  assert.doesNotMatch(host.textContent, /approved|verified/i);
});

test('a run without sources and a list that cannot be read say so in plain words', async () => {
  const empty = new FakeNode('section');
  await createSources({ host: empty, invoke: backend({ sources: [] }).invoke, createViewer: fakeViewer().create }).show('/runs/a', 'k');
  assert.match(empty.textContent, /No source files are recorded for this run\./);
  assert.equal(rows(empty).length, 0);

  const failing = new FakeNode('section');
  const { invoke, calls } = backend({ fail: 'The run folder could not be read.' });
  await createSources({ host: failing, invoke, createViewer: fakeViewer().create }).show('/runs/a', 'k');
  assert.match(failing.textContent, /The source list could not be read\. The run folder could not be read\./);
  const retry = failing.findAll((n) => n.tag === 'button' && n.textContent === 'Try again')[0];
  await retry.listeners.click();
  await settle();
  assert.equal(calls.filter((c) => c.command === 'list_sources').length, 2);
});

test('the inspector list opens a file on the Sources page', async () => {
  const host = new FakeNode('section');
  const panel = new FakeNode('div');
  const sources = createSources({ host, invoke: backend().invoke, createViewer: fakeViewer().create });
  const opened = [];
  await sources.showPanel(panel, '/runs/a', 'k', (id) => { opened.push(id); sources.select(id); });
  const compact = rows(panel);
  assert.equal(compact.length, 4);
  assert.ok(compact.every((r) => r.attributes.role === undefined));
  compact[3].listeners.click();
  assert.deepEqual(opened, ['old']);
  assert.deepEqual(sources.selection, { id: 'old', page: 0 });
});
