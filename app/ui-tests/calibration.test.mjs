import { test } from 'node:test';
import assert from 'node:assert/strict';
import { calibrationChoice } from '../ui/js/calibration.js';

class FakeNode {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.value = ''; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attributes[key] = String(value); if (key === 'value') this.value = String(value); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  get textContent() { return this.children.map((c) => typeof c === 'string' ? c : c.textContent).join(''); }
  findAll(test) { return [...(test(this) ? [this] : []), ...this.children.filter((c) => typeof c !== 'string').flatMap((c) => c.findAll(test))]; }
}
globalThis.Node = FakeNode;
globalThis.document = { createElement: (tag) => new FakeNode(tag) };
const named = (root, name) => root.findAll((n) => n.attributes['aria-label'] === name)[0];

test('a side disagreement suggests a swap but waits for the person', async () => {
  const saved = [];
  const choice = calibrationChoice({ check: { flags: ['sides: side checks disagree or are missing: labels say fore left, shapes say fore right'] },
    onSave: async (fix) => saved.push(fix), onCancel() {} });
  assert.equal(named(choice, 'What is wrong').value, 'swap_sides');
  assert.equal(saved.length, 0);
  assert.match(choice.textContent, /Suggested/);
  await named(choice, 'Apply correction').listeners.click();
  assert.deepEqual(saved, [{ kind: 'swap_sides' }]);
});

test('other flags do not suggest a side swap', () => {
  for (const flags of [[], ['scale: measures disagree'], ['sides: labels are missing']]) {
    const choice = calibrationChoice({ check: { flags }, onSave() { assert.fail('No automatic correction'); }, onCancel() {} });
    assert.equal(named(choice, 'What is wrong').value, '');
  }
});

test('the small choice records a swap only after Apply', async () => {
  const saved = [];
  const choice = calibrationChoice({ onSave: async (fix) => saved.push(fix), onCancel() {} });
  assert.equal(saved.length, 0);
  assert.match(choice.textContent, /Bow\/stern swapped/);
  assert.match(choice.textContent, /Station order/);
  assert.match(choice.textContent, /Other/);
  named(choice, 'What is wrong').value = 'swap_sides';
  await named(choice, 'Apply correction').listeners.click();
  assert.deepEqual(saved, [{ kind: 'swap_sides' }]);
});

test('station order names the half; Other keeps free text without a geometry fix', async () => {
  const saved = [];
  const choice = calibrationChoice({ onSave: async (fix) => saved.push(fix), onCancel() {} });
  const kind = named(choice, 'What is wrong');
  kind.value = 'reverse_order'; kind.listeners.change();
  named(choice, 'Half').value = 'aft';
  await named(choice, 'Apply correction').listeners.click();
  kind.value = 'other'; kind.listeners.change();
  named(choice, 'What is wrong (note)').value = '  The scale is wrong  ';
  await named(choice, 'Apply correction').listeners.click();
  assert.deepEqual(saved, [{ kind: 'reverse_order', half: 'aft' }, { kind: 'other', text: 'The scale is wrong' }]);
  assert.doesNotMatch(choice.textContent, /approved|verified/i);
});
