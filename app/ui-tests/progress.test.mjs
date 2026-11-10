import { test } from 'node:test';
import assert from 'node:assert/strict';
import { workerProgressView, renderWorkerProgress } from '../ui/js/progress.js';

const inFlight = { kind: 'worker', since_ms: 0, operation: 'build_first_hull',
  progress: { stage: 'Building the hull', part: 31, total: 72, unit: 'section' }, stalled: false };

test('running worker shows the current section and elapsed minutes', () => {
  const view = workerProgressView(inFlight, 12 * 60_000);
  assert.equal(view.text, 'Building the hull: section 31 of 72 · 12 min');
  assert.deepEqual(view.actions, []);
});

test('stalled worker names its stage and offers Keep waiting and Stop', () => {
  const view = workerProgressView({ ...inFlight, stalled: true }, 12 * 60_000);
  assert.match(view.text, /^No progress: Building the hull/);
  assert.deepEqual(view.actions.map(({ label, command }) => [label, command]),
    [['Keep waiting', 'resume_task'], ['Stop', 'cancel_task']]);
  assert.ok(view.actions.every(({ title, detail }) => title && detail));
});

test('worker without a progress record still has a useful running line', () => {
  const view = workerProgressView({ ...inFlight, progress: null }, 900_000);
  assert.equal(view.text, 'Building the hull · 15 min');
  assert.equal(workerProgressView({ kind: 'model' }, 1000), null);
});

test('strip buttons render both tooltip stages and dispatch the selected action', () => {
  class Element {
    constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.events = {}; }
    append(child) { this.children.push(child); }
    replaceChildren() { this.children = []; }
    setAttribute(key, value) { this.attrs[key] = value; }
    addEventListener(key, callback) { this.events[key] = callback; }
  }
  const oldDocument = globalThis.document;
  const oldNode = globalThis.Node;
  globalThis.Node = Element;
  globalThis.document = { createElement: (tag) => new Element(tag) };
  try {
    const strip = new Element('div');
    const calls = [];
    renderWorkerProgress(strip, workerProgressView({ ...inFlight, stalled: true }, 900_000),
      (command) => calls.push(command));
    const buttons = strip.children.filter((node) => node.tag === 'button');
    assert.equal(buttons.length, 2);
    assert.equal(buttons[0].children[0], 'Keep waiting');
    for (const button of buttons) {
      assert.ok(button.attrs['data-tip-title']);
      assert.ok(button.attrs['data-tip-detail']);
      assert.equal(button.children[1].attrs.id, button.attrs['aria-describedby']);
      button.events.click({ currentTarget: button });
    }
    assert.deepEqual(calls, ['resume_task', 'cancel_task']);
    renderWorkerProgress(strip, workerProgressView({ ...inFlight, stalled: true }, 960_000), () => {});
    assert.equal(strip.children[2], buttons[0], 'polling keeps the focused action in place');
    renderWorkerProgress(strip, workerProgressView(inFlight, 900_000), () => {});
    assert.equal(strip.children.filter((node) => node.tag === 'button').length, 0);
  } finally {
    globalThis.document = oldDocument;
    globalThis.Node = oldNode;
  }
});
