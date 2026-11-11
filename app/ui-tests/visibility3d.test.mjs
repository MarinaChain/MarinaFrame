// Hide, isolate and the part list of the 3D view (js/visibility3d.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createPartVisibility, describeParts, filterParts, humanName, PART_STATES, sectionPlaneShown, shellPartOpacity, steelPartId, steelPartOpacity,
} from '../ui/js/visibility3d.js';

test('with no hide and no isolate every part shows', () => {
  const v = createPartVisibility();
  assert.equal(v.stateOf('tank_a'), 'shown');
  assert.equal(v.active, false);
});

test('hide takes a part out and a second hide brings it back', () => {
  const v = createPartVisibility();
  v.toggleHide('tank_a');
  assert.equal(v.stateOf('tank_a'), 'hidden');
  assert.equal(v.stateOf('tank_b'), 'shown');
  assert.equal(v.active, true);
  v.toggleHide('tank_a');
  assert.equal(v.stateOf('tank_a'), 'shown');
  assert.equal(v.active, false);
});

test('isolate keeps one part and makes every other part ghost', () => {
  const v = createPartVisibility();
  v.toggleIsolate('tank_a');
  assert.equal(v.stateOf('tank_a'), 'shown');
  assert.equal(v.stateOf('tank_b'), 'ghost');
  assert.equal(v.stateOf(steelPartId('deck')), 'ghost');
  v.toggleIsolate('tank_a');
  assert.equal(v.stateOf('tank_b'), 'shown');
});

test('a hidden part stays hidden under an isolate, and isolating a hidden part shows it', () => {
  const v = createPartVisibility();
  v.toggleHide('tank_b');
  v.toggleIsolate('tank_a');
  assert.equal(v.stateOf('tank_b'), 'hidden');
  v.toggleIsolate('tank_b');
  assert.equal(v.stateOf('tank_b'), 'shown');
  assert.equal(v.stateOf('tank_a'), 'ghost');
});

test('show all ends every hide and the isolate, and every change raises the version', () => {
  const v = createPartVisibility();
  const before = v.version;
  v.toggleHide('a');
  v.toggleIsolate('b');
  v.showAll();
  assert.equal(v.active, false);
  assert.equal(v.stateOf('a'), 'shown');
  assert.equal(v.isolatedId, null);
  assert.equal(v.version, before + 3);
});

test('a new model forgets parts it does not have', () => {
  const v = createPartVisibility();
  v.toggleHide('old');
  v.toggleIsolate('gone');
  v.keepOnly(['new']);
  assert.equal(v.stateOf('old'), 'shown');
  assert.equal(v.isolatedId, null);
});

const MODEL = {
  shell: [{ partId: 'deckhouse_1' }, { partId: 'hull' }],
  tanks: [
    { partId: 'tank_b', label: 'No 2 ballast', content_class: 'water_ballast', content_label: 'Water ballast' },
    { partId: 'tank_a', label: 'No 1 fresh water', content_class: 'fresh_water', content_label: 'Fresh water' },
    { partId: 'tank_c', label: 'No 10 ballast', content_class: 'water_ballast', content_label: 'Water ballast' },
  ],
  steel: [{ group: 'bulkhead', group_label: 'Bulkheads', members: [{}, {}] }, { group: 'deck', group_label: 'Decks', members: [{}] }],
};

test('the part list puts the hull first, then parts, tanks by name, then steel groups', () => {
  const list = describeParts(MODEL);
  assert.deepEqual(list.map((e) => e.name), ['Hull', 'Deckhouse 1', 'No 1 fresh water', 'No 2 ballast', 'No 10 ballast', 'Bulkheads', 'Decks']);
  assert.deepEqual(list.map((e) => e.kind), ['hull', 'part', 'tank', 'tank', 'tank', 'steel', 'steel']);
  assert.equal(list[5].id, 'steel:bulkhead');
  assert.equal(list[5].detail, '2 members');
  assert.equal(list[6].detail, '1 member');
});

test('a search needs every word to start a word of the name, kind or detail', () => {
  const list = describeParts(MODEL);
  assert.deepEqual(filterParts(list, 'ballast').map((e) => e.id), ['tank_b', 'tank_c']);
  assert.deepEqual(filterParts(list, 'no 1').map((e) => e.id), ['tank_a', 'tank_c']);
  assert.deepEqual(filterParts(list, 'FRESH').map((e) => e.id), ['tank_a']);
  assert.deepEqual(filterParts(list, 'steel').map((e) => e.id), ['steel:bulkhead', 'steel:deck']);
  assert.deepEqual(filterParts(list, 'allast water').length, 0);
  assert.equal(filterParts(list, '  ').length, list.length);
});

test('a node name reads as a title', () => {
  assert.equal(humanName('hull_body'), 'Hull body');
  assert.equal(humanName(''), '');
});

// ---- See-through hull and section planes.

const shell = (over) => shellPartOpacity({ state: PART_STATES.shown, isHull: true, insideShown: false, seeThroughHull: false, ...over });

test('with no tanks or steel and See-through hull off, the hull and every part are solid', () => {
  assert.equal(shell({}), 1);
  assert.equal(shell({ isHull: false }), 1);
});

test('See-through hull makes the hull faint and keeps the parts inside it solid', () => {
  const hull = shell({ seeThroughHull: true });
  assert.ok(hull > 0 && hull < 0.2, `hull opacity ${hull}`);
  assert.equal(shell({ seeThroughHull: true, isHull: false }), 1);
});

test('See-through hull makes the hull fainter than the shell is with tanks inside', () => {
  assert.ok(shell({ seeThroughHull: true, insideShown: true }) < shell({ insideShown: true }));
  assert.ok(shell({ insideShown: true }) < 1);
});

test('a ghost part stays ghost and a hidden part is not drawn, with See-through hull on or off', () => {
  for (const seeThroughHull of [false, true]) {
    assert.ok(shell({ state: PART_STATES.ghost, seeThroughHull }) < 0.1);
    assert.equal(shell({ state: PART_STATES.hidden, seeThroughHull }), 0);
  }
});

test('steel members stay solid; See-through hull makes the shell plating fainter', () => {
  const steel = (over) => steelPartOpacity({ state: PART_STATES.shown, isShellPlating: false, seeThroughHull: false, ...over });
  assert.equal(steel({}), 1);
  assert.equal(steel({ seeThroughHull: true }), 1);
  assert.ok(steel({ isShellPlating: true, seeThroughHull: true }) < steel({ isShellPlating: true }));
});

test('only the selected section has a plane until Section planes is on', () => {
  const ids = Array.from({ length: 72 }, (_, i) => `st${i}`);
  const drawn = (allPlanes, selectedId) => ids.filter((id) => sectionPlaneShown({ id, selectedId, allPlanes }));
  assert.deepEqual(drawn(false, 'st10'), ['st10']);
  assert.deepEqual(drawn(false, null), []);
  assert.equal(drawn(true, 'st10').length, 72);
});
