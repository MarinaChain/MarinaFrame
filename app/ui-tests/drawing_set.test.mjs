// Drawing-set intake (js/drawing_set.js): sheet type and scale chips' data, the checklist.
// Run: cd app && npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  SHEET_TYPES, agreementLine, checklistHeadline, computeChecklist, groupByOutput, missingRequired, scaleState,
  sourceSentence, typeUnsure, withType,
} from '../ui/js/drawing_set.js';

// The mock set is made by the worker's own code (mock/make_drawing_set_mock.py): nine sheets, no shell expansion.
const MOCK = JSON.parse(readFileSync(new URL('../ui/mock/drawing_set.json', import.meta.url), 'utf8'));
const pages = () => structuredClone(MOCK.pages);
const byId = (items) => Object.fromEntries(items.map((item) => [item.id, item]));

test('the checklist computed here equals the one the worker computed (same rules)', () => {
  const here = computeChecklist(pages(), MOCK.set.rules);
  assert.deepEqual(here.map(({ id, status, met_by }) => ({ id, status, met_by })),
    MOCK.set.checklist.map(({ id, status, met_by }) => ({ id, status, met_by })));
});

test('the mock set lacks exactly one required drawing and says so in a few words', () => {
  const items = computeChecklist(pages(), MOCK.set.rules);
  assert.deepEqual(missingRequired(items).map((i) => i.id), ['steel_shell']);
  assert.equal(checklistHeadline(items), '1 required drawing missing');
  assert.equal(byId(items).steel_shell.status, 'missing');
  assert.equal(byId(items).hull_lines.status, 'met');
});

test('changing a sheet to shell expansion meets the need; the source becomes the person', () => {
  const edited = pages();
  edited[8] = withType(edited[8], 'shell_expansion');
  assert.equal(edited[8].sheet.source, 'person');
  assert.equal(edited[8].sheet.confidence, 1);
  assert.equal(typeUnsure(edited[8]), false);
  const items = computeChecklist(edited, MOCK.set.rules);
  assert.equal(missingRequired(items).length, 0);
  assert.equal(checklistHeadline(items), 'All required drawings found');
  assert.deepEqual(byId(items).steel_shell.met_by, ['p9']);
});

test('a skipped page does not meet a need', () => {
  const edited = pages();
  edited[4].skip = true; // the only tank plan
  assert.equal(byId(computeChecklist(edited, MOCK.set.rules)).tanks_plan.status, 'missing');
});

test('a lines plan with a sheer plan meets the profile need and says why', () => {
  const only = [{ page_id: 'p1', skip: false, sheet: { type: 'lines_plan', views: ['sheer', 'body_plan'] } }];
  const profile = byId(computeChecklist(only, MOCK.set.rules)).hull_profile;
  assert.equal(profile.status, 'met');
  assert.match(profile.met_note, /sheer plan/);
  only[0].sheet.views = ['body_plan'];
  assert.equal(byId(computeChecklist(only, MOCK.set.rules)).hull_profile.status, 'missing');
});

test('items are grouped by output and a missing recommended drawing is not a missing required one', () => {
  const groups = groupByOutput(computeChecklist(pages(), MOCK.set.rules), MOCK.set.outputs);
  assert.deepEqual(groups.map((g) => g.id), ['hull', 'tanks', 'steel', 'booklet']);
  assert.deepEqual(groups.map((g) => g.missingRequired), [0, 0, 1, 0]);
});

test('every sheet type has a short word, and the worker types are all known', () => {
  assert.equal(SHEET_TYPES.length, 9);
  for (const page of MOCK.pages) assert.ok(SHEET_TYPES.some(([id]) => id === page.sheet.type));
});

test('weak proposals are marked to check; confident and person-set ones are not', () => {
  const [lines, , , , , , structure] = pages();
  assert.equal(typeUnsure(lines), false);
  assert.equal(typeUnsure(structure), true); // 0.62, asked of the AI
  assert.equal(typeUnsure({}), false); // no sheet result at all
});

test('scale chip states: read, missing, and a length that differs from the other sheets', () => {
  const all = pages();
  const agreement = MOCK.set.scale_agreement;
  assert.deepEqual(scaleState(all[0], agreement), { state: 'read', text: '1:50', detail: 'Printed scale 1:50, read from the lettering.' });
  assert.equal(scaleState(all[5], agreement).state, 'missing'); // the hydrostatic booklet prints no scale
  const differs = scaleState(all[4], agreement);
  assert.equal(differs.state, 'check');
  assert.match(differs.detail, /47\.6 m/);
  assert.equal(scaleState({ page_id: 'p0' }, agreement), null);
});

test('the set line says agree, check or not compared', () => {
  assert.equal(agreementLine(MOCK.set.scale_agreement).text, '1 sheet differs in scale');
  assert.equal(agreementLine({ status: 'agree', estimates: 3, reference_m: 24, spread: 0.02, items: [] }).text, 'Scales agree');
  assert.equal(agreementLine({ status: 'too_few', items: [] }).text, 'Scales not compared');
  assert.equal(agreementLine(null), null);
});

test('where a type came from is said in words, not codes', () => {
  assert.equal(sourceSentence('file_name+text:ocr'), 'From the file name and the lettering on the sheet');
  assert.equal(sourceSentence('text:pdf_text+ocr'), 'From the text in the PDF and the lettering on the sheet');
  assert.equal(sourceSentence('title:ocr+text:ocr'), 'From the lettering on the sheet');
  assert.equal(sourceSentence('model:claude-sonnet-5-5'), 'Asked of the AI');
  assert.equal(sourceSentence('person'), 'Set by you');
  assert.equal(sourceSentence('code:no_rule'), 'No title or keyword found');
});

test('no word in the feature says approved or verified', () => {
  const text = (JSON.stringify(MOCK) + readFileSync(new URL('../ui/js/drawing_set.js', import.meta.url), 'utf8'))
    .replaceAll('engineering_approved', '');
  assert.doesNotMatch(text, /\b(approved|verified)\b/i);
  assert.equal(MOCK.set.engineering_approved, false);
});
