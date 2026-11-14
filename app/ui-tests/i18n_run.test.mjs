// Run intake and command labels follow locale changes without requiring a DOM.
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setLocale, t } from '../ui/js/i18n.js';
import { EN } from '../ui/js/strings/en.js';
import { KO } from '../ui/js/strings/ko.js';
import { viewLabel, intakePageCount } from '../ui/js/intake.js';
import { shortcutGroups } from '../ui/js/shortcuts.js';

afterEach(() => setLocale('en'));

test('intake view names resolve at call time and preserve English labels', () => {
  for (const [locale, labels] of [
    ['ko', ['정면선도', '반폭도', '측면도', '표제란', '기타']],
    ['en', ['Body plan', 'Half-breadth', 'Profile', 'Title block', 'Other']],
    ['ko', ['정면선도', '반폭도', '측면도', '표제란', '기타']],
  ]) {
    setLocale(locale);
    assert.deepEqual(['body_plan', 'half_breadth', 'profile', 'title_block', 'other'].map(viewLabel), labels);
    assert.equal(viewLabel('custom_view'), undefined);
  }
});

test('intake page counts translate singular, plural, zero and skipped pages', () => {
  for (const [locale, expected] of [
    ['ko', ['1페이지', '3페이지', '0페이지', '전체 3페이지 중 1페이지 포함']],
    ['en', ['1 page', '3 pages', '0 pages', '1 of 3 pages kept']],
  ]) {
    setLocale(locale);
    assert.deepEqual([intakePageCount(1), intakePageCount(3), intakePageCount(0), intakePageCount(3, 1)], expected);
  }
});

test('shortcut descriptions translate but every keyboard shortcut remains unchanged', () => {
  setLocale('en');
  const english = shortcutGroups();
  assert.equal(english[0][0], 'Anywhere');
  assert.equal(english[1][1][1][1], 'Accept the guessed line');
  setLocale('ko');
  const korean = shortcutGroups();
  assert.equal(korean[0][0], '어디서나');
  assert.equal(korean[1][1][1][1], '추정한 선 채택');
  assert.deepEqual(korean.map(([, rows]) => rows.map(([key]) => key)), english.map(([, rows]) => rows.map(([key]) => key)));
  assert.deepEqual(korean[1][1].map(([key]) => key), ['N', 'A', 'O', 'M', '[ ]']);
  setLocale('en');
  assert.deepEqual(shortcutGroups(), english);
});

test('run, review, inspector and command phrases retain English and use Korean', () => {
  for (const [key, params, english, korean] of [
    ['ko3.runTitle', { name: 'Synthetic', number: 2 }, 'Synthetic, run 2', 'Synthetic, 실행 2'],
    ['ko3.confirmLine', { line: 'A', place: '12.0 m' }, 'Confirming the A at 12.0 m, then rebuilding…', '12.0 m의 A 확인 후 다시 작성하는 중…'],
    ['ko3.checks.fail', { count: 2 }, '2 fail', '미통과 2개'],
    ['ko3.tabFailing', { word: 'AI', count: 2 }, 'AI, 2 failing', 'AI, 2개 미통과'],
    ['ko3.theme', { theme: 'AI' }, 'AI theme', 'AI 테마'],
  ]) {
    setLocale('ko');
    assert.equal(t(key, params), korean);
    setLocale('en');
    assert.equal(t(key, params), english);
  }
});

test('all static ko3 keys used by the scoped modules exist in both tables', () => {
  for (const file of ['run_header', 'run_strip', 'inspector', 'palette', 'shortcuts', 'commands', 'new_vessel', 'intake', 'settings_view']) {
    const source = readFileSync(new URL(`../ui/js/${file}.js`, import.meta.url), 'utf8');
    for (const [, key] of source.matchAll(/['"](ko3\.[\w.]+)['"]/g)) {
      assert.ok(Object.hasOwn(EN, key), `${file}: ${key} in English`);
      assert.ok(Object.hasOwn(KO, key), `${file}: ${key} in Korean`);
    }
  }
});
