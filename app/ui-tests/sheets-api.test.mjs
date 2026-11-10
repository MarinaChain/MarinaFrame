import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const fixtures = JSON.parse(await readFile(new URL('../ui/mock/fixtures.json', import.meta.url)));
Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => null, setItem() {} }, configurable: true });
globalThis.window = {};
globalThis.document = { querySelector: () => null };
globalThis.location = { search: '' };
globalThis.fetch = async () => ({ json: async () => structuredClone(fixtures) });
const { invoke, pickDrawingFiles } = await import('../ui/js/api.js');

test('replacement picker selects one file; intake can still select a set', async () => {
  assert.equal((await pickDrawingFiles({ multiple: false })).length, 1);
  assert.ok((await pickDrawingFiles()).length > 1);
});

test('PM mock replacement answers its request and keeps unrelated output and history', async () => {
  const task = fixtures.tasks.find(t => t.task.endsWith('survey-launch')).task;
  const before = await invoke('get_task', { task });
  const previousRevision = before.revision;
  assert.equal(before.sheet_review.sheets.filter(s => s.status === 'unreadable').length, 1);
  await invoke('replace_sheet', { task, sheet_id: 'source', file: '/demo/clear.png' });
  const after = await invoke('get_task', { task });
  assert.equal(after.sheet_review.sheets.find(s => s.id === 'source').status, 'replaced');
  assert.equal(after.sheet_review.requests[0].status, 'answered');
  assert.deepEqual(after.sheet_review.outputs.find(o => o.id === 'Decks'), before.sheet_review.outputs.find(o => o.id === 'Decks'));
  assert.equal(after.sheet_review.history[0].previous_revision_id, previousRevision);
  assert.notEqual(after.revision, previousRevision);
  assert.equal(after.sheet_review.history[0].engineering_approved, false);
});
