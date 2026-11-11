// Guessed ranges in the 3D view (js/guess3d.js): merging and the box limit. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { GUESS_BOX_LIMIT_SHARE, guessDisplay, mergeGuessRanges } from '../ui/js/guess3d.js';
import { guessedXRanges } from '../ui/js/run_facts.js';
import { addManyGuessesRun, MOCK_MANY_GUESSES_TASK } from '../ui/mock/backend.js';

test('adjacent and overlapping ranges merge into one, separate ones stay apart', () => {
  assert.deepEqual(mergeGuessRanges([[4, 6], [0, 2], [2, 3], [5, 8], [10, 11]]), [[0, 3], [4, 8], [10, 11]]);
});

test('ranges that miss each other by a rounding hair still merge', () => {
  assert.deepEqual(mergeGuessRanges([[0, 1.0004], [1.0009, 2]]), [[0, 2]]);
});

test('a swapped range is read the right way round and bad ranges are dropped', () => {
  assert.deepEqual(mergeGuessRanges([[3, 1], null, [Number.NaN, 2], [5]]), [[1, 3]]);
});

test('a run of 72 per-station guesses is one band, not 72', () => {
  const sections = Array.from({ length: 72 }, (_, i) => ({ x_m: i, guess: { x_range_m: null } }));
  const ranges = guessedXRanges(sections, 71);
  assert.equal(ranges.length, 72);
  assert.deepEqual(mergeGuessRanges(ranges), [[0, 71]]);
});

test('no guesses: nothing to draw', () => {
  assert.deepEqual(guessDisplay([], 0, 24), { mode: 'none', ranges: [], share: 0 });
});

test('guesses on half the hull or less draw boxes', () => {
  const display = guessDisplay([[0, 6], [6, 12]], 0, 24);
  assert.equal(display.mode, 'boxes');
  assert.deepEqual(display.ranges, [[0, 12]]);
  assert.equal(display.share, GUESS_BOX_LIMIT_SHARE);
});

test('guesses on more than half the hull draw the base-line bar instead of boxes', () => {
  const display = guessDisplay([[0, 6], [6, 13]], 0, 24);
  assert.equal(display.mode, 'bar');
  assert.ok(display.share > GUESS_BOX_LIMIT_SHARE);
});

test('ranges are clipped to the hull, so guesses past the ends do not count', () => {
  const display = guessDisplay([[-5, 2], [22, 40]], 0, 24);
  assert.deepEqual(display.ranges, [[0, 2], [22, 24]]);
  assert.equal(display.mode, 'boxes');
});

test('the 72-station mock run shows the bar: few merged ranges, most of the hull covered', async () => {
  const data = JSON.parse(await readFile(new URL('../ui/mock/fixtures.json', import.meta.url), 'utf8'));
  const runs = data.tasks.length;
  addManyGuessesRun(data);
  assert.equal(data.tasks.length, runs + 1);
  const view = data.views[MOCK_MANY_GUESSES_TASK];
  assert.equal(view.sections.length, 72);
  const guessedCount = view.sections.filter((s) => s.guess).length;
  assert.ok(guessedCount >= 68, `${guessedCount} guessed`);
  assert.equal(new Set(view.sections.map((s) => s.id)).size, 72);
  const display = guessDisplay(guessedXRanges(view.sections, view.model.length_m), 0, view.model.length_m);
  assert.equal(display.mode, 'bar');
  // The read stations split the run: one merged range between each pair, not one per station.
  assert.ok(display.ranges.length <= 5, `${display.ranges.length} ranges`);
});
