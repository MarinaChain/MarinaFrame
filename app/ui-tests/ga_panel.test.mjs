// GA reading panel (js/ga_panel.js): rows of particulars, counts and spaces, and their source
// records in the source view. Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GA_PREFIX, STATUSES, statusWord, gaRecords, gaRows } from '../ui/js/ga_panel.js';
import { sourceOf } from '../ui/js/provenance.js';

const region = { sheet: 'X_GA.png', page: 0, view: null, box_px: [10, 10, 90, 30], page_px: [1000, 500] };

function reading() {
  return {
    schema: 'marinaframe.ga_reading.v1', engineering_approved: false,
    ship_type: { value: 'bulk_carrier', status: 'read' },
    views: [{ view_id: 'v1', kind: 'profile', title: 'PROFILE' }],
    particulars: {
      loa_m: { value: 189.99, status: 'read', printed: '189.99 m', source_record: { kind: 'read', regions: [region] } },
      lbp_m: { value: null, status: 'unknown', reason: 'not found printed', source_record: { kind: 'unknown', reason: 'not found printed' } },
    },
    counts: {
      cargo_holds: { value: 5, status: 'read', evidence: 'NO.1-NO.5 HOLD', source_record: { kind: 'read', regions: [region] } },
      cargo_cranes: { value: 0, status: 'read', evidence: 'gearless' },
      cargo_hatches: { value: null, status: 'unknown', reason: 'partial view' },
    },
    spaces: [
      { id: 'engine_room-003', kind: 'engine_room', label: 'ENGINE ROOM', number: null, status: 'read', source_record: { kind: 'read', regions: [region] } },
      { id: 'cargo_hold-001', kind: 'cargo_hold', label: 'NO.1 CARGO HOLD', number: '1', status: 'read', view_id: 'v1', source_record: { kind: 'read', regions: [region] } },
      { id: 'cargo_hold-002', kind: 'cargo_hold', label: '', number: null, status: 'guessed', source_record: { kind: 'guessed', method: 'outline', inputs: [region] } },
    ],
  };
}

test('rows keep abstentions and zero counts apart', () => {
  const rows = gaRows(reading());
  assert.equal(rows.shipType, 'Bulk carrier');
  const loa = rows.particulars.find((r) => r.id === `${GA_PREFIX}particular:loa_m`);
  assert.equal(loa.value, '189.99 m');
  assert.equal(loa.note, 'Printed “189.99 m”');
  const lbp = rows.particulars.find((r) => r.id.endsWith('lbp_m'));
  assert.deepEqual([lbp.value, lbp.status, lbp.note], ['—', 'unknown', 'not found printed']);
  const counts = Object.fromEntries(rows.counts.map((r) => [r.id.split(':').pop(), r.value]));
  assert.equal(counts.cargo_cranes, '0');
  assert.equal(counts.cargo_hatches, '—');
  assert.equal(counts.container_bays, '—'); // not in the reading: shown as not read
});

test('spaces group by kind in a fixed order and an unlabelled outline is named', () => {
  const { groups } = gaRows(reading());
  assert.deepEqual(groups.map((g) => g.label), ['Cargo holds', 'Engine room']);
  assert.equal(groups[0].rows[1].label, 'Unlabelled cargo hold');
  assert.equal(groups[0].rows[1].status, 'guessed');
  assert.equal(groups[0].rows[0].note, 'In profile PROFILE');
});

test('a run without a reading has no rows', () => {
  assert.equal(gaRows(null), null);
  assert.deepEqual(gaRecords(undefined), []);
});

test('the source view finds a GA row by its id', () => {
  const view = { sections: [], components: null, ga_reading: reading() };
  const hold = sourceOf(view, { kind: 'part', id: `${GA_PREFIX}space:cargo_hold-001` });
  assert.equal(hold.label, 'NO.1 CARGO HOLD');
  assert.equal(hold.record.regions[0].sheet, 'X_GA.png');
  const count = sourceOf(view, { kind: 'part', id: `${GA_PREFIX}count:cargo_cranes` });
  assert.equal(count.record, null); // no record: the view says so instead of drawing a region
});

test('status words never claim approval', () => {
  for (const word of STATUSES.map(statusWord)) assert.doesNotMatch(word, /approv|verif/i);
});

test('measured values show their own status, an unconfirmed depth included', () => {
  const data = reading();
  data.measured = {
    lbp_m: { value: 168.05, status: 'measured_from_scale', method: 'frame 0 to the F.P. mark' },
    depth_m: { value: 11.97, status: 'unconfirmed_from_uncertain_boxes', note: 'not confirmed' },
    breadth_m: { value: null, status: 'unknown', reason: 'no shell side pointed' },
  };
  const rows = gaRows(data);
  const byKey = Object.fromEntries(rows.measured.map((r) => [r.id.split(':').pop(), r]));
  assert.deepEqual([byKey.lbp_m.value, statusWord(byKey.lbp_m.status)], ['168.05 m', 'Measured']);
  assert.deepEqual([byKey.depth_m.value, statusWord(byKey.depth_m.status)], ['11.97 m', 'Unconfirmed']);
  assert.deepEqual([byKey.breadth_m.status, byKey.breadth_m.note], ['unknown', 'no shell side pointed']);
  // Without the frame-scale pass there is no measured section.
  assert.equal(gaRows(reading()).measured.length, 0);
});
