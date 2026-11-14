// Mock design command parity: IDs, per-file failures and public fixture transport.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { listMockDesigns, openMockDesign } from '../ui/mock/designs.js';

test('mock lists both records and opens by record ID, not filename', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url) => {
    const text = await readFile(new URL(`../ui/${url}`, import.meta.url), 'utf8');
    return new Response(text, { headers: { 'last-modified': 'Sat, 14 Nov 2026 00:00:00 GMT' } });
  });
  const rows = await listMockDesigns();
  assert.equal(rows.length, 2);
  assert.ok(rows.every((row) => row.id && !row.validation_error && row.updated_ms));
  const record = await openMockDesign(rows[1].id);
  assert.equal(record.lineage.parent_design_id, rows[0].id);
  await assert.rejects(openMockDesign('../kvlcc2'), /not found or invalid/);
});

test('one unreadable mock file does not hide the other record', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url) => {
    if (url.includes('cb-variant')) return new Response('{}', { status: 404 });
    return new Response(await readFile(new URL(`../ui/${url}`, import.meta.url), 'utf8'));
  });
  const rows = await listMockDesigns();
  assert.equal(rows[0].validation_error, null);
  assert.ok(rows[1].validation_error);
  assert.equal(rows[1].id, null);
  assert.equal((await openMockDesign(rows[0].id)).design_id, rows[0].id);
});
