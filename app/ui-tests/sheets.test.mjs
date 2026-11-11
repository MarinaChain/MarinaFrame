import { test } from 'node:test';
import assert from 'node:assert/strict';
import { renderSheetReview, renderSheetHistory } from '../ui/js/sheets.js';

class FakeNode {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; }
  append(child) { this.children.push(child); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  get textContent() { return this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
  findAll(test) { return [...(test(this) ? [this] : []), ...this.children.filter(c => typeof c !== 'string').flatMap(c => c.findAll(test))]; }
}
globalThis.Node = FakeNode;
globalThis.document = { createElement: tag => new FakeNode(tag), createElementNS: (_, tag) => new FakeNode(tag) };
const review = { sheets: [
  { id: 'ga', label: 'GA', status: 'ok', reason: '' },
  { id: 'lines', label: 'Lines plan', status: 'unreadable', reason: 'Lines too faint.' },
], outputs: [{ id: 'hull', status: 'stale' }], requests: [
  { id: 'req', sheet_id: 'lines', output_id: 'hull', who: 'Yard', status: 'open', text: 'Send a clearer lines plan.' },
], history: [] };

test('one bad sheet has its reason and replace action; other work stays a draft', async () => {
  const replaced = [];
  const root = renderSheetReview(review, { onReplace: async id => replaced.push(id) });
  assert.match(root.textContent, /Lines too faint\./);
  assert.match(root.textContent, /Yard/);
  assert.match(root.textContent, /hull/);
  assert.match(root.textContent, /Draft/);
  const buttons = root.findAll(n => n.tag === 'button');
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].attributes['aria-label'], 'Replace Lines plan');
  await buttons[0].listeners.click();
  assert.deepEqual(replaced, ['lines']);
  const chips = root.findAll(n => n.attributes.role === 'img');
  assert.ok(chips.some(n => n.attributes['aria-label'].includes('Unreadable')));
});

test('send later leaves a request open; answered requests remain in the list', () => {
  const answered = structuredClone(review);
  answered.requests[0].status = 'answered';
  const root = renderSheetReview(answered, { onReplace() {} });
  assert.match(root.textContent, /Answered/);
  assert.match(root.textContent, /Send later/);
  assert.equal(answered.requests[0].status, 'answered');
});

test('history names the old revision kept and the new revision', () => {
  const root = renderSheetHistory([{ label: 'Lines plan', previous_revision_id: 'r0002', revision_id: 'r0003',
    stages: ['read', 'build'], status: 'partial' }]);
  assert.match(root.textContent, /r0002.*kept/);
  assert.match(root.textContent, /r0003/);
  assert.match(root.textContent, /Needs input/);
});

test('missing and wrong-scale sheets name the issue and offer replacement', () => {
  const root = renderSheetReview({ sheets: [
    { id: 'a', label: 'Lines', status: 'missing', reason: 'Send the lines plan.' },
    { id: 'b', label: 'GA', status: 'wrong_scale', reason: 'Confirm the scale.' },
  ], outputs: [], requests: [] }, { onReplace() {} });
  assert.match(root.textContent, /Send the lines plan/);
  assert.match(root.textContent, /Confirm the scale/);
  assert.equal(root.findAll(n => n.tag === 'button').length, 2);
});
