// The app shell's state store (js/app_state.js) and its pure run rules (js/run_facts.js). Run: npm run test:ui
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  state, setOpenTask, setView, setEvents, addEvents, setRoute, setSectionId, currentSection, isRunning, nextLoadToken,
} from '../ui/js/app_state.js';
import {
  vesselNameOf, groupVessels, runNumber, vesselOfTask, toCheckCount, partsToCheck, needsCheck, defaultSection, guessedXRanges,
} from '../ui/js/run_facts.js';

const section = (id, x_m, extra = {}) => ({ id, x_m, state: 'traced', candidates: [], ...extra });

test('the state changes only through its setters', () => {
  assert.throws(() => { state.task = '/x'; }, TypeError);
  setOpenTask('/runs/a');
  assert.equal(state.task, '/runs/a');
  assert.equal(state.view, null);
  assert.equal(state.lastSequence, 0);
});

test('opening a run forgets the previous one', () => {
  setOpenTask('/runs/a');
  setView({ summary: { status: 'running' }, sections: [section('st1', 1)] });
  setEvents([{ sequence: 1 }, { sequence: 4 }]);
  setSectionId('st1');
  assert.equal(currentSection().id, 'st1');
  assert.equal(isRunning(), true);
  assert.equal(state.lastSequence, 4);
  addEvents([{ sequence: 7 }]);
  assert.equal(state.events.length, 3);
  assert.equal(state.lastSequence, 7);
  setOpenTask('/runs/b');
  assert.deepEqual([state.view, state.events, state.sectionId, currentSection()], [null, [], null, null]);
});

test('Settings returns to the place it was opened from', () => {
  setRoute('queue');
  setRoute('settings');
  assert.equal(state.previousRoute, 'queue');
  setRoute('settings');
  assert.equal(state.previousRoute, 'queue', 'opening Settings again keeps the place');
});

test('each read gets a newer load token', () => {
  const first = nextLoadToken();
  assert.equal(nextLoadToken(), first + 1);
});

test('runs group into vessels by the start of the run name, newest first', () => {
  assert.equal(vesselNameOf('Pilot boat, lines plan'), 'Pilot boat');
  assert.equal(vesselNameOf('dtmb-5415-lines-plan'), 'Dtmb 5415 lines plan');
  const tasks = [
    { task: '/a1', name: 'Tug — first', updated_ms: 1 },
    { task: '/b1', name: 'Ferry', updated_ms: 5 },
    { task: '/a2', name: 'tug, second', updated_ms: 9 },
  ];
  const vessels = groupVessels(tasks);
  assert.deepEqual(vessels.map((v) => v.name), ['Tug', 'Ferry']);
  assert.equal(vessels[0].latest.task, '/a2');
  assert.equal(runNumber(vessels[0], '/a1'), 1, 'Run 1 is the first attempt');
  assert.equal(runNumber(vessels[0], '/a2'), 2);
  assert.equal(vesselOfTask(tasks, '/b1').name, 'Ferry');
  assert.equal(vesselOfTask(tasks, '/missing'), null);
});

test('review counts: guessed and declined sections, open parts', () => {
  const view = {
    sections: [section('a', 0, { state: 'guessed' }), section('b', 4), section('c', 8, { state: 'declined' })],
    components: [
      { review: 'accepted', status: 'draft_guess', built: true },
      { review: 'open', status: 'draft_guess', built: true },
      { review: 'open', status: 'built', built: false },
      { review: 'open', status: 'built', built: true },
    ],
  };
  assert.equal(toCheckCount(view), 2);
  assert.equal(partsToCheck(view), 2);
  assert.equal(toCheckCount(null), 0);
  assert.equal(needsCheck(view.sections[1]), false);
  assert.equal(defaultSection(view), 'a', 'a run opens on the first section to check');
  assert.equal(defaultSection({ sections: [section('z', 1)] }), 'z');
});

test('a guessed line covers the hull nearer to its station than to any other', () => {
  const sections = [section('a', 0), section('b', 4, { guess: {} }), section('c', 8), section('d', 10, { guess: { x_range_m: [9, 12] } })];
  assert.deepEqual(guessedXRanges(sections, 12), [[2, 6], [9, 12]]);
});
