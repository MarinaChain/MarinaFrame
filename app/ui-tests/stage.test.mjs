// Release UI staging (scripts/stage-release-ui.mjs). Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { stage, problems, MAX_FILE_BYTES } from '../scripts/stage-release-ui.mjs';

function fakeUi() {
  const root = mkdtempSync(join(tmpdir(), 'mf-ui-'));
  const ui = join(root, 'ui');
  for (const dir of ['js', 'vendor', 'assets', 'mock/files', 'screenshots']) mkdirSync(join(ui, dir), { recursive: true });
  writeFileSync(join(ui, 'index.html'), '<!doctype html>');
  writeFileSync(join(ui, 'styles.css'), 'body{}');
  writeFileSync(join(ui, 'js', 'app.js'), '');
  writeFileSync(join(ui, 'vendor', 'LICENSE'), 'MIT');
  writeFileSync(join(ui, 'assets', 'mark.svg'), '<svg/>');
  writeFileSync(join(ui, 'mock', 'files', 'whole-vessel-draft.glb'), 'glTF');
  writeFileSync(join(ui, 'screenshots', 'shot.png'), 'png');
  return { root, ui, target: join(root, 'ui-release') };
}

test('the mock, screenshots and local data stay out of the release UI', () => {
  const { ui, target } = fakeUi();
  assert.deepEqual(stage(ui, target), []);
  assert.ok(existsSync(join(target, 'js', 'app.js')));
  assert.ok(!existsSync(join(target, 'mock')));
  assert.ok(!existsSync(join(target, 'screenshots')));
});

test('a model, drawing or large file in the staged UI fails the check', () => {
  const { ui, target } = fakeUi();
  writeFileSync(join(ui, 'assets', 'hull.step'), 'ISO-10303-21;');
  writeFileSync(join(ui, 'vendor', 'sheet.TIF'), 'II*');
  writeFileSync(join(ui, 'js', 'big.js'), Buffer.alloc(MAX_FILE_BYTES + 1));
  const found = stage(ui, target);
  assert.equal(found.length, 3, found.join('\n'));
  assert.ok(found.some((p) => p.includes('hull.step')));
  assert.ok(found.some((p) => p.includes('sheet.TIF')));
  assert.ok(found.some((p) => p.includes('big.js')));
  assert.deepEqual(problems(join(target, 'js')).length, 1);
});
