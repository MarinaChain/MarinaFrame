// Transport choice in js/api.js: Tauri first, the browser mock (mock/backend.js) last. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';

const calls = [];
globalThis.window = {
  __TAURI__: {
    core: { invoke: async (command, args) => { calls.push({ command, args }); return { ok: true }; } },
    event: { listen: async () => () => {} },
  },
};
globalThis.document = { querySelector: () => null };
// The mock would read its fixtures with fetch; inside Tauri nothing may fetch them.
globalThis.fetch = async (url) => { throw new Error(`unexpected fetch of ${url}`); };
const api = await import('../ui/js/api.js');

test('inside Tauri the app uses the Tauri transport, not the mock', async () => {
  assert.equal(api.transportName, 'tauri');
  assert.deepEqual(await api.invoke('get_settings', {}), { ok: true });
  assert.deepEqual(calls, [{ command: 'get_settings', args: {} }]);
});

test('a Tauri error becomes a BackendError with plain words', async () => {
  window.__TAURI__.core.invoke = async () => { throw { code: 'task_not_found', message: 'This run folder no longer exists.' }; };
  await assert.rejects(api.invoke('get_task', { task: '/x' }), (error) => error instanceof api.BackendError && error.code === 'task_not_found');
});
