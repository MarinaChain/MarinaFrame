# Hull accuracy on clean sheets, lane A (2026-11-11)

Branch `lane/hull-accuracy` from `continue/v0.5` (4f03667). Brief: `work/pm-briefs/common.md` and
the lane A brief; gap analysis section 3 ("Hull accuracy, clean sheets", "AI value") and section 4
priority 1.

## Goal and gates (written before any run)

More clean-sheet development cases pass the frozen hull gate: RMS of station half-breadth error
<= 2 % of the half-beam and in-range volume error <= 5 %, scored with the frozen factory scorer
against development truth (`work/factory-3view`). The gate does not change in this lane.

## Method

1. Baseline: one live sheet-only round at 4f03667 (Claude Sonnet 5.5 through the subscription,
   `--policy live --on-ambiguity draft --context conversation`), L0 cases, 2-4 first.
   Round folder `work/round-hull-L0-base-4f03667`, code snapshot `work/snap-hull-4f03667`.
2. Code-only measurement: `benchmarks/hull_accuracy/replay_readings.py` replays each stored
   reading through `build_first_hull` with the current source and scores each station
   (`--delivered` scores the delivered draft). Each fix is checked by a replay of all stored
   readings before any new live round.
3. Find the first common blocker in the worst stations, fix it with a test, replay, repeat.
4. 24 development cases only after the L0 cases improve.

## Baseline (live, Claude Sonnet 5.5, sheet-only, L0)

Rounds `work/round-hull-L0-base-4f03667` (dtmb, 00679, 09867, series60) and
`work/round-hull-L0-base2-4354b28` (series60, 08158, 02216; 4354b28 = base + fix 1 only, no hull
change). Delivered draft scored with `replay_readings --delivered`.

| Case | RMS % half-beam | Volume % | Gate | Where the error is |
|---|---|---|---|---|
| dtmb5415-3v-L0 | 5.07 | +0.7 | fail | one 0.05 m deck sample at s01, s02, s04, s06, s07 (6-7 % each); without it every station is 0.3-2.1 % |
| series60-3v-L0 | blocked at input (4f03667); 1.39 (4354b28) | +1.1 | pass | - |
| shipd-1-00679-3v-L0 | 4.39 | +0.5 | fail | bottoms of s02, s05, s06, s08: fore curves meet the keel in one tight bundle and the trace jumps between them |
| shipd-1-08158-3v-L0 | 0.76 | -2.1 | pass | - |
| shipd-1-09867-3v-L0 | 3.63 | +1.6 | fail | fore identity: s07 carries curve 8 (fits truth x 80 at 0.84 %), s08 a grid-line trace, s06 a blend |
| shipd-2-02216-3v-L0 | 3.17 | -1.5 | fail | s07 9.4 %: s06 carries curve 7 (fits truth x 70 at 0.51 %) |

2 of 6 pass. The first hulls (code only, before any model edit) already hold each error.

## Fixes

1. **Spec validation blocked sheet-only runs** (`schema.validate_spec`, 4354b28). Since 7ec97d7
   the intake writes `design_draft_m` / `design_draft_source` when it reads a title-block draft;
   the validator did not list them, so series60-3v-L0 ended `input:unexpected_field` before the
   first model request. Test: `tests/test_particulars.py::test_spec_with_read_draft_passes_validation`.
2. **Panel strokes must bring ink of their own** (`panel_assignment.strokes_with_own_ink`). In an
   overlay panel a stroke made of other strokes' pieces (the outer bundle's top joined to the next
   curve's bottom) or of a grid line plus another curve's bottom (09867: 71 % on the 8 m grid
   column, under the 75 % grid rule) counted as a curve. Two such strokes gave 5 "curves" for 5
   stations, so no station shared and every inner station moved one curve outwards. A stroke now
   needs 15 % of its rows off grid columns and off kept, more hull-like strokes. Tests: four in
   `tests/test_panel_assignment.py`.
3. **Tried and reverted: tops near the deck take the profile deck height** (6c57d6f, reverted
   in 5b8a9d5). With the model's setups the profile deck line puts 7 of 9 dtmb station tops in
   the right 0.05 m truth sample, the body-plan curve ends 4 of 9; the replay gave dtmb
   5.07 -> 3.10 % (still a fail). But on 09867 the deck line reads 0.05-0.1 m below a flat deck
   at the truth grid top, where a low top costs a sample at every station and a high one costs
   nothing, and the changed traced z range made the shared s06 trace jump between curves:
   0.87 -> 8.54 %. Not kept. A safe version would only lower tops (never raise the traced z
   range) and skip flat decks; not tried.

## Results: code-only replays of the stored readings (no model calls)

Each stored phase-1 reading rebuilt with `build_first_hull` and scored (RMS % half-beam /
in-range volume %). Base = 4f03667 + fix 1 (4354b28 snapshot for round-2 readings).
Outputs: `work/hull-lane/replay-*.json`.

| Case | Base first hull | Branch (fix 2; = 5b8a9d5) | Gate after | (fix 3 trial, reverted) |
|---|---|---|---|---|
| dtmb5415-3v-L0 | 5.07 / +0.7 | 5.07 / +0.7 | fail (deck samples) | 3.10 / +0.7 |
| series60-3v-L0 | 1.39 / +1.1 | 1.39 / +1.1 | pass | - |
| shipd-1-00679-3v-L0 | 4.39 / +0.5 | 4.43 / +0.6 | fail (bottom bundle) | 4.37 / +0.6 |
| shipd-1-08158-3v-L0 | 0.75 / -2.1 | 0.75 / -2.1 | pass | - |
| shipd-1-09867-3v-L0 | 3.79 / +0.5 | 0.87 / +1.8 | pass | 8.54 / +1.7 |
| shipd-2-02216-3v-L0 | 3.17 / -1.5 | 0.59 / -1.7 | pass | - |

L0 passes on the same readings: 2 of 6 -> 4 of 6 (series60 counted as passing in the base only
with fix 1; at 4f03667 it was blocked at input).

## Results: live check at 5b8a9d5 (Sonnet 5.5, sheet-only)

Round `work/round-hull-L0-fix-5b8a9d5` (snapshot `work/snap-hull-5b8a9d5`), the four failing
cases. Delivered draft, RMS % / volume %:

| Case | Live baseline | Live 5b8a9d5 | Note |
|---|---|---|---|
| shipd-1-09867-3v-L0 | 3.63 / +1.6 | **0.87 / +1.7 (pass)** | first hull 0.87 %, as the replay |
| shipd-2-02216-3v-L0 | 3.17 / -1.5 | 3.47 / -2.0 | new reading put s05 in the aft panel; two close fore strokes (72 % same ink) both keep >15 % own rows and s07 takes the wrong one (9.4 %) |
| dtmb5415-3v-L0 | 5.07 / +0.7 | 8.92 / +0.7 | reading 1 first hull 5.07 % (= baseline); best of 2 kept reading 2 by drawing fit (0.7365 vs 0.721), profile x origin 165 px vs 160, errors 7-11 % at every station: selection, not this change |
| shipd-1-00679-3v-L0 | 4.39 / +0.5 | 4.43 / +0.6 | bottom bundle (unchanged) |

Live L0 (6 cases, series60 and 08158 from the base2 round): 3 of 6 pass (series60, 08158,
09867) against 1 of 6 at 4f03667 (series60 blocked, 08158) and 2 of 6 with fix 1 only.
Run-to-run variance from the model reading is large (dtmb 5.07 vs 8.92 % on one code).

## Open (next blockers, in order)

1. **Best-of-2 picks the worse reading** (dtmb live: fit 0.7365 kept 8.92 % over 0.721 / 5.07 %).
   Owner: best-of-N lane (`draft_fit`). A datum check of the profile x origin against the
   outline's aft end (165 vs 160 px) would have flagged reading 2.
2. **Close fore strokes** (02216 second reading): two strokes 72 % same ink, both kept. A rule
   from the curve tops would help: each station curve ends at the deck at its own half-breadth
   (station labels sit there); not tried.
3. **00679 bottoms**: the fore curves run into one bundle along a rising floor near the keel;
   the trace jumps between them (s05 bottom 5.3 m vs truth 1.07 m at z 0.06). This is corridor
   measurement in `ingest.py` (other lane). Proposed there: inside a crowded bottom band, follow
   the stroke whose slope continues the curve above the band, not the nearest ink run.
4. **dtmb deck samples**: see fix 3 above; a lower-only, non-flat-deck variant is untried.
5. **24 development cases**: not run. The L0 gain is one case live (09867) and one more on
   replay (02216, first reading); blockers 1 and 2 should be fixed first (tasks/lessons.md, DTMB
   L0-L3 and early stop).

## Resume point

Branch `lane/hull-accuracy` at the commit after 5b8a9d5 (doc), pushed; quick tier passed on
5b8a9d5 (1850 Python tests, Rust, UI, lint, secrets). Next: open item 2 or 1, check each with
`benchmarks/hull_accuracy/replay_readings.py` on the stored readings in
`work/round-hull-L0-{base-4f03667,base2-4354b28,fix-5b8a9d5}` before any live round.
