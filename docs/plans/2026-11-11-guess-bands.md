# Lane G2: 3D guess bands (2026-11-11)

Branch: `lane/guess-bands` from `origin/continue/v0.5`. Quick tier.

## Problem

`app/ui/js/model3d.js` drew one amber box per guessed x range. On a 72-station run with every
station guessed, 72 boxes with edges at every station hid the hull (a dense orange block).

## Change

- `app/ui/js/guess3d.js` (new, pure): `mergeGuessRanges` merges adjacent or overlapping ranges;
  `guessDisplay` clips them to the hull and picks the form: `boxes` (share <= 50 % of the hull
  length, one box per merged range) or `bar` (share > 50 %: a thin amber bar just under the base
  line per merged range, and one note "Most stations are guesses").
- `model3d.js`: uses `guessDisplay`; new "Guessed ranges" switch in the Show group (default on);
  the replay hook (`setReviewOverlays`) and the switch both control the bands and the note.
- `app/ui/mock/backend.js`: `addManyGuessesRun` adds "Research vessel, 72 stations" (68 guessed,
  every 18th read; per-station guesses with no x range, as on a real run).
- Tests: `app/ui-tests/guess3d.test.mjs` (merging, threshold, clipping, the mock run end to end).

## Checks

- `node --test app/ui-tests` passes.
- Screenshots (main checkout, ignored): `work/guess-bands/before-72-stations.jpg` (base code,
  dense block) and `work/guess-bands/after-72-stations.jpg` (bar in 4 merged pieces plus note).
- Switch checked in the browser: on shows the note, off hides the bar and the note.

## Resume point

Done, pushed, not merged. Not done: no hull-surface tint (the base-line bar was chosen instead);
the threshold is a fixed 50 %, not a setting.
