// Dynamic labels and run sentences follow locale changes without reloading modules.
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { setLocale } from '../ui/js/i18n.js';
import {
  statusLabel, sectionStateLabel, sourceLabel, checkLabel, callStateLabel, plural, countOf,
} from '../ui/js/format.js';
import { statusSentence, reviewWords, errorWords, costWords } from '../ui/js/run_status.js';

afterEach(() => setLocale('en'));

const view = (overrides = {}) => ({
  summary: { status: 'draft' },
  sections: [{ state: 'guessed' }],
  ...overrides,
});

test('all label tables resolve at call time, including switching back to English', () => {
  const labels = [
    [statusLabel, 'running', 'Running', '실행 중'],
    [statusLabel, 'stalled', 'Waiting for you', '사용자 조치 대기'],
    [statusLabel, 'needs_review', 'Needs review', '검토 필요'],
    [statusLabel, 'draft', 'Draft', '초안'],
    [statusLabel, 'signed_off', 'Signed off', '담당자 확인 완료'],
    [statusLabel, 'declined', 'Declined', '채택 안 함'],
    [statusLabel, 'failed', 'Failed', '실패'],
    [statusLabel, 'cancelled', 'Cancelled', '취소됨'],
    [statusLabel, 'paused', 'Paused', '일시 정지'],
    [statusLabel, 'blocked', 'Blocked', '진행 불가'],
    [sectionStateLabel, 'chosen', 'Line chosen', '선 선택됨'],
    [sourceLabel, 'ai_inferred', 'AI inferred', 'AI 추정'],
    [checkLabel, 'pass', 'Pass', '통과'],
    [callStateLabel, 'unknown', 'Result unknown', '결과 알 수 없음'],
  ];
  for (const locale of ['en', 'ko', 'en']) {
    setLocale(locale);
    for (const [label, id, english, korean] of labels) {
      assert.equal(label(id), locale === 'en' ? english : korean);
    }
  }
});

test('unknown label fallbacks keep their existing behaviour in both languages', () => {
  for (const locale of ['ko', 'en']) {
    setLocale(locale);
    for (const label of [statusLabel, sectionStateLabel, checkLabel, callStateLabel]) {
      assert.equal(label('custom_state'), 'custom_state');
    }
    assert.equal(sourceLabel('custom_source'), 'custom source');
  }
});

test('English count phrases keep zero, singular, plural and unlisted noun rules', () => {
  setLocale('en');
  for (const noun of ['section', 'part', 'set', 'run', 'warning', 'model request', 'custom noun']) {
    assert.equal(plural(0, noun), `0 ${noun}s`);
    assert.equal(plural(1, noun), `1 ${noun}`);
    assert.equal(plural(3, noun), `3 ${noun}s`);
    assert.equal(countOf(0, noun), `No ${noun}s`);
    assert.equal(countOf(1, noun), `1 ${noun}`);
    assert.equal(countOf(3, noun), `3 ${noun}s`);
  }
});

test('Korean count phrases put the noun before the counter and handle zero', () => {
  setLocale('ko');
  for (const [noun, korean] of [
    ['section', '단면'], ['part', '부품'], ['set', '도면 세트'],
    ['run', '실행'], ['warning', '경고'], ['model request', '모델 요청'],
  ]) {
    for (const count of [0, 1, 3]) assert.equal(plural(count, noun), `${korean} ${count}개`);
    assert.equal(countOf(0, noun), `${korean} 없음`);
    assert.equal(countOf(1, noun), `${korean} 1개`);
    assert.equal(countOf(3, noun), `${korean} 3개`);
  }
});

test('status sentences translate sheet states, remaining sheets and user actions', () => {
  const current = view({ sheet_review: { sheets: [
    { id: 'a', label: 'GA', status: 'missing' },
    { id: 'b', label: 'PDF', status: 'wrong_scale' },
  ] } });
  for (const [locale, expected] of [
    ['ko', ['초안', '단면 1개 사용자 조치 필요', 'GA: 누락 (외 1개)']],
    ['en', ['Draft', '1 section needs you', 'GA: missing (+1 more)']],
  ]) {
    setLocale(locale);
    assert.deepEqual(statusSentence(current), {
      parts: expected, action: { kind: 'replace', sheetId: 'a', label: 'GA' },
    });
  }
  setLocale('ko');
  for (const [status, word] of [['unreadable', '판독 불가'], ['wrong_scale', '축척 오류']]) {
    assert.equal(statusSentence(view({ sheet_review: { sheets: [{ id: 'a', label: 'GA', status }] } })).parts[2], `GA: ${word}`);
  }
});

test('status sentences translate plural needs and nothing to check', () => {
  for (const [locale, needs, nothing] of [
    ['ko', '단면 2개 사용자 조치 필요', '확인할 항목 없음'],
    ['en', '2 sections need you', 'nothing to check'],
  ]) {
    setLocale(locale);
    assert.equal(statusSentence(view({ sections: [{ state: 'guessed' }, { state: 'declined' }] })).parts[1], needs);
    assert.equal(statusSentence(view({ sections: [{ state: 'chosen' }] })).parts[1], nothing);
    assert.deepEqual(statusSentence(null), { parts: [], action: null });
  }
});

test('review, drawing error and cost phrases translate without changing money formats', () => {
  const current = view({
    source_counts: [{ label: 'traced', count: 1 }, { label: 'ai_corrected', count: 2 }],
    warnings: ['synthetic warning'],
    activity: { requests: 3, list_cost_usd: 0.0121, list_cost_complete: false },
  });
  setLocale('ko');
  assert.equal(reviewWords(current), '추적 1개 · AI 보정 2개 · 경고 1개');
  assert.equal(errorWords('0.8-14 %'), '도면 대비 오차 0.8–14 %');
  assert.equal(costWords(current), '모델 요청 3개 · 정가 기준 비용 최소 $0.0121');
  setLocale('en');
  assert.equal(reviewWords(current), '1 traced · 2 AI corrected · 1 warning');
  assert.equal(errorWords('0.8-14 %'), '0.8–14 % from the drawing');
  assert.equal(costWords(current), '3 model requests · at least $0.0121 list cost');
  assert.equal(costWords({}), null);
});

test('GA reading run sentences follow the active locale too', () => {
  const current = view({ sections: [], ga_reading: { particulars: { loa_m: { value: 24, status: 'read' } } } });
  setLocale('ko');
  assert.deepEqual(statusSentence(current).parts, ['초안', 'GA 판독', '13개 중 1개 판독']);
  setLocale('en');
  assert.deepEqual(statusSentence(current).parts, ['Draft', 'GA reading', '1 of 13 values read']);
});
