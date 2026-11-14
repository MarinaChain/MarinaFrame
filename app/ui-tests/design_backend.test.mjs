// Mock design command parity: IDs, per-file failures and public fixture transport.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { listMockDesigns, openMockDesign } from '../ui/mock/designs.js';

test('mock lists every record and opens by record ID, not filename', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url) => {
    const text = await readFile(new URL(`../ui/${url}`, import.meta.url), 'utf8');
    return new Response(text, { headers: { 'last-modified': 'Sat, 14 Nov 2026 00:00:00 GMT' } });
  });
  const rows = await listMockDesigns();
  assert.equal(rows.length, 6);
  assert.ok(rows.every((row) => row.id && !row.validation_error && row.updated_ms));
  const record = await openMockDesign(rows[1].id);
  assert.equal(record.lineage.parent_design_id, rows[0].id);
  await assert.rejects(openMockDesign('../kvlcc2'), /not found or invalid/);
});

test('one unreadable mock file does not hide the other record', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url) => {
    if (url.includes('candidate-c')) return new Response('{}', { status: 404 });
    return new Response(await readFile(new URL(`../ui/${url}`, import.meta.url), 'utf8'));
  });
  const rows = await listMockDesigns();
  const broken = rows.filter((row) => row.validation_error);
  assert.equal(broken.length, 1);
  assert.equal(broken[0].id, null);
  assert.equal(rows[0].validation_error, null);
  assert.equal((await openMockDesign(rows[0].id)).design_id, rows[0].id);
});

test('mock decisions append to the log with the desktop backend checks', async (context) => {
  const { listMockDecisions, appendMockDecision } = await import('../ui/mock/designs.js');
  context.mock.method(globalThis, 'fetch', async (url) => new Response(await readFile(new URL(`../ui/${url}`, import.meta.url), 'utf8')));
  const project = 'public-kvlcc2-example';
  const before = await listMockDecisions(project);
  const decision = { candidate_id: 'synthetic-kvlcc2-candidate-b', action: 'accepted', discipline: 'machinery',
    reason: ' Synthetic reason. ', designer_id: 'Machinery reviewer' };
  const entry = await appendMockDecision(project, decision);
  assert.equal(entry.reason, 'Synthetic reason.');
  assert.equal(entry.status, 'draft');
  assert.match(entry.recorded_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
  assert.equal((await listMockDecisions(project)).length, before.length + 1);
  await assert.rejects(appendMockDecision(project, { ...decision, action: 'approved' }), /action/);
  await assert.rejects(appendMockDecision(project, { ...decision, reason: '  ' }), /reason/);
  await assert.rejects(appendMockDecision(project, { ...decision, candidate_id: project }), /not a design of this project/);
  assert.equal((await listMockDecisions(project)).length, before.length + 1);
});
