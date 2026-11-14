// Vessel-page labels resolve at call time and preserve English text and backend values.
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setLocale, t } from '../ui/js/i18n.js';
import { EN } from '../ui/js/strings/en.js';
import { KO } from '../ui/js/strings/ko.js';
import { partState, plainReason, partTableText } from '../ui/js/parts.js';
import { tankSource, capacityFields, soundingView, tankLegend, steelLegend, groupLine } from '../ui/js/tanks.js';
import { filesSummary, outputsOf } from '../ui/js/export.js';
import { summarise, band, bandQuantity, OUTPUT_NAMES } from '../ui/js/accuracy.js';
import { groupSources, usedLine, sheetLine, statusWord } from '../ui/js/sources.js';

// History's existing shell imports require inert canvas, desktop and theme surfaces.
// These stubs do not start the application or use a browser.
globalThis.window = { __TAURI__: {}, matchMedia: () => ({ addEventListener() {} }) };
globalThis.document = {
  createElement: () => ({ getContext: () => null }),
  getElementById: () => ({ addEventListener() {} }),
};
const { vesselTabLabel, historyRunLabel } = await import('../ui/js/vessel_pages.js');
afterEach(() => setLocale('en'));

function checkLocales(check) {
  for (const code of ['ko', 'en', 'ko', 'en']) {
    setLocale(code);
    check(code === 'ko');
  }
}

test('Parts state, reason and spreadsheet text follow the active locale', () => {
  checkLocales((ko) => {
    assert.equal(partState({ review: 'accepted' }).word, ko ? '채택됨' : 'Accepted');
    assert.equal(partState({ revision_pending: true }).word, ko ? '새 리비전' : 'New revision');
    assert.equal(plainReason('house_height: missing or invalid measurement'), ko ? '높이: 도면에서 판독하지 못했습니다.' : 'Height: not read from the drawing.');
    assert.equal(plainReason('height: guessed: synthetic basis'), ko ? '높이: 추정 (synthetic basis).' : 'Height: guessed (synthetic basis).');
    const text = partTableText([{ label: '=unsafe', op: 'deck', built: true, status: 'draft_guess', arguments: [], review: 'accepted' }]);
    assert.ok(text.startsWith(ko ? '부품\t작업\t작성 여부' : 'Part\tOp\tBuilt'));
    assert.ok(text.includes("'=unsafe\tdeck\t"));
    assert.ok(text.includes(ko ? '초안, 시공용 아님.' : 'Draft, not for construction.'));
    assert.ok(text.endsWith('engineering_approved: false\n'));
  });
});

test('Tank source descriptions, fields and sounding headings translate without changing numbers', () => {
  checkLocales((ko) => {
    assert.equal(tankSource('ai_inferred').word, ko ? 'AI 판독' : 'AI read');
    assert.equal(tankSource('traced').title, ko ? '도면 선에서 측정했습니다.' : 'Measured from the drawing linework.');
    const fields = capacityFields({ name: 'Synthetic tank', volume_100_m3: 12.5 });
    assert.equal(fields[0].name, ko ? '이름' : 'Name');
    assert.equal(fields[3].value, '12.50 m³');
    assert.equal(fields[7].name, 'LCG');
    const sounding = soundingView({ columns: ['sounding_m', 'ullage_m'], rows: [[1.25, 0.5]] });
    assert.deepEqual(sounding.headings, ko ? ['측심 (m)', '얼리지 (m)'] : ['Sounding (m)', 'Ullage (m)']);
    assert.deepEqual(sounding.rows, [['1.250', '0.500']]);
  });
});

test('Tank and steel legends use glossary terms at call time', () => {
  checkLocales((ko) => {
    assert.equal(tankLegend([{ content_class: 'water_ballast' }])[0].label, ko ? '평형수' : 'Water ballast');
    assert.equal(steelLegend([{ group: 'shell', members: ['a'] }])[0].label, ko ? '외판' : 'Shell plating');
    assert.equal(groupLine({ content: 'water ballast', built: 2, tanks: 3, volume_100_m3: 62.3, weight_98_t: 63.86 }),
      ko ? '평형수 · 3개 중 2개 작성됨 · 62.30 m³ · 63.86 t' : 'Water ballast · 2 of 3 built · 62.30 m³ · 63.86 t');
  });
});

test('Export summaries retain singular and plural English and translate Korean', () => {
  checkLocales((ko) => {
    assert.equal(filesSummary('tanks', [{ file: 'x_capacity_plan.csv' }, { file: 'x_sounding_a.csv' }]), ko ? '탱크 용량표 및 측심표 1개' : 'Capacity plan and 1 sounding table');
    assert.equal(filesSummary('structure', [{ file: 'a.csv' }, { file: 'b.csv' }, { file: 'a.3docx' }]), ko ? '강재 표 2개 및 OCX 파일 1개' : '2 steel tables and 1 OCX file');
    const outputs = outputsOf({ tank_model: {} });
    assert.equal(outputs.find((o) => o.kind === 'report').name, ko ? '보고서' : 'Report');
    assert.equal(outputs.find((o) => o.kind === 'step').hint, ko ? 'CAD용 선체 표면, 단위 mm, 헤더에 초안 표시.' : 'Hull surface for CAD, millimetres, draft stamp in the header.');
  });
});

test('Accuracy summaries translate evidence and preserve source counts and caution', () => {
  checkLocales((ko) => {
    const summary = summarise({ hull: { labels: { traced: 2, interpolated: 1 }, to_check: 1, fit: 0.5 } });
    assert.ok(summary.hull.line.includes(ko ? '단면 3개 중 2개 추적, 보간 1개' : '2 of 3 sections traced, 1 interpolated'));
    assert.ok(summary.hull.line.includes(ko ? '깨끗한 합성 도면에서만 측정' : 'measured on clean synthetic sheets only'));
    assert.equal(summary.hull.caution, true);
    assert.equal(summary.tanks.line, ko ? '탱크: 이 실행에 없음.' : 'Tanks: none in this run.');
    assert.equal(OUTPUT_NAMES.steel, ko ? '강재' : 'Steel');
    for (const path of ['model_reading', 'scanned_body_plan', 'vector_drawing']) {
      const output = summarise({
        hull: { path },
        tanks: { path: 'raster_plan', volume_labels: { guessed: 1 }, total: 2, built: 1 },
        steel: { thickness_labels: { printed: 1, guessed: 1 } },
      });
      for (const item of Object.values(output)) {
        assert.doesNotMatch(item.line, /ko2\.|term\.|승인|검증/);
        if (ko) assert.match(item.line, /[가-힣]/);
      }
    }
    const quantity = bandQuantity(band('steel.positions'));
    assert.equal(quantity.value, 0);
    assert.ok(quantity.source.includes(ko ? '도면 표기와 위치 일치' : 'positions match the printed drawing'));
  });
});

test('Sources groups, usage ranges, scale and states translate', () => {
  checkLocales((ko) => {
    assert.deepEqual(groupSources([{ kind: 'drawing' }, { kind: 'pdf', status: 'replaced' }]).map((g) => g.title), ko ? ['도면', '이전 버전'] : ['Drawings', 'Earlier versions']);
    assert.equal(usedLine({ used_from: 'r0001', used_to: 'r0003' }), ko ? 'r0001~r0003에서 사용' : 'Used in r0001 to r0003');
    assert.equal(sheetLine({ scale: '1:50' }), ko ? '축척 1:50' : 'Scale 1:50');
    assert.equal(statusWord({ status: 'unreadable' }), ko ? '판독 불가' : 'Could not be read');
  });
});

test('History run names and every vessel tab translate at call time', () => {
  checkLocales((ko) => {
    assert.equal(historyRunLabel(3), ko ? '실행 3' : 'Run 3');
    assert.deepEqual(['run', 'parts', 'sources', 'export', 'history'].map(vesselTabLabel), ko ? ['실행', '부품', '출처', '내보내기', '기록'] : ['Run', 'Parts', 'Sources', 'Export', 'History']);
    assert.equal(vesselTabLabel('custom'), 'custom');
  });
});

test('Every vessel-page key has matching placeholders in both tables and Korean draft wording', () => {
  const keys = Object.keys(EN).filter((key) => key.startsWith('ko2.'));
  assert.ok(keys.length > 250);
  for (const key of keys) {
    assert.equal(typeof KO[key], 'string', key);
    const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    assert.deepEqual(placeholders(KO[key]), placeholders(EN[key]), key);
    assert.doesNotMatch(KO[key], /승인|검증/, key);
  }
  for (const module of ['parts', 'tanks', 'export', 'accuracy', 'sources', 'vessel_pages']) {
    const source = readFileSync(new URL(`../ui/js/${module}.js`, import.meta.url), 'utf8');
    for (const [, key] of source.matchAll(/t\('(ko2\.[^']+)'/g)) {
      assert.ok(key in EN && key in KO, `${module}: ${key}`);
    }
  }
  checkLocales((ko) => assert.equal(t('ko2.tanks.draft'), ko ? '초안' : 'Draft'));
});
