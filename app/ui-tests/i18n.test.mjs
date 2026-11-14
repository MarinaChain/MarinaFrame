// Interface language (js/i18n.js, js/strings/): English and Korean tables, the ship-term
// glossary and the draft rule for status words. Run: npm run test:ui
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { t, setLocale, locale, normalizeLocale, LOCALES } from '../ui/js/i18n.js';
import { EN } from '../ui/js/strings/en.js';
import { KO } from '../ui/js/strings/ko.js';
import { GLOSSARY } from '../ui/js/strings/glossary.js';
import { gaRows, statusWord, STATUSES } from '../ui/js/ga_panel.js';

afterEach(() => setLocale('en'));

const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test('the Korean table has the same keys and placeholders as the English table', () => {
  assert.deepEqual(Object.keys(KO).sort(), Object.keys(EN).sort());
  for (const key of Object.keys(EN)) assert.deepEqual(placeholders(KO[key]), placeholders(EN[key]), key);
});

test('every glossary term has English and Korean, and abbreviations stay in Latin letters', () => {
  for (const [id, entry] of Object.entries(GLOSSARY)) {
    assert.ok(entry.en && entry.ko, id);
    if (entry.abbr) assert.match(entry.abbr, /^[A-Za-z]+$/, id);
  }
});

test('no string in any locale calls a result approved or verified', () => {
  const english = [...Object.values(EN), ...Object.values(GLOSSARY).flatMap((e) => [e.en, e.enPlural || ''])];
  for (const text of english) assert.doesNotMatch(text, /\b(approved|verified)\b/i, text);
  const korean = [...Object.values(KO), ...Object.values(GLOSSARY).map((e) => e.ko)];
  for (const text of korean) assert.doesNotMatch(text, /승인|검증/, text);
});

test('an unknown locale falls back to English, and a missing key shows the key', () => {
  assert.equal(normalizeLocale('fr'), 'en');
  assert.deepEqual(LOCALES, ['en', 'ko']);
  setLocale('ko');
  assert.equal(locale(), 'ko');
  assert.equal(t('no.such.key'), 'no.such.key');
  assert.equal(t('ga.meta', { shipType: '탱커' }), '탱커 · 초안: 엔지니어 검토용 도면 판독 결과');
});

test('glossary keys give one item or a heading', () => {
  assert.equal(t('term.cargo_tank'), 'Cargo tank');
  assert.equal(t('terms.cargo_tank'), 'Cargo tanks');
  setLocale('ko');
  assert.equal(t('term.cargo_tank'), '화물탱크');
  assert.equal(t('terms.cargo_tank'), '화물탱크');
});

test('the GA rows read in Korean, with the English abbreviation after a particular', () => {
  setLocale('ko');
  const rows = gaRows({
    ship_type: { value: 'tanker' },
    particulars: { lbp_m: { value: 240, status: 'read' } },
    spaces: [{ id: 's1', kind: 'cargo_tank', label: '', status: 'guessed' }],
  });
  assert.equal(rows.shipType, '탱커');
  assert.equal(rows.particulars.find((r) => r.id.endsWith('lbp_m')).label, '수선간장 (LBP)');
  assert.equal(rows.groups[0].label, '화물탱크');
  assert.equal(rows.groups[0].rows[0].label, '표기 없는 화물탱크');
  assert.deepEqual(STATUSES.map(statusWord).slice(0, 3), ['판독', '추정', '알 수 없음']);
});

test('times read in Korean, and English times keep their words', async () => {
  const { relativeTime, shortTime } = await import('../ui/js/format.js');
  const twelveMinutesAgo = Date.now() - 12 * 60_000;
  assert.equal(relativeTime(twelveMinutesAgo), '12 min ago');
  assert.equal(shortTime(Date.now()), 'Now');
  setLocale('ko');
  assert.equal(relativeTime(twelveMinutesAgo), '12분 전');
  assert.equal(shortTime(Date.now()), '방금');
});

test('a missing or undefined key never throws', () => {
  assert.equal(t(undefined), '');
  assert.equal(t(''), '');
});
