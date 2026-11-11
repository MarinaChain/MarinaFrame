# Degraded scans (L2/L3), lane O (2026-11-12)

Branch `lane/degraded-scans` from `origin/continue/v0.5` (3865d8c). Brief: `work/pm-briefs/common.md`
and the lane O brief. Context: `docs/plans/2026-11-11-hull-accuracy.md` (lane A rounds 1-2) and the
gap-analysis row "Hull accuracy, scans".

## Goal and gates (written before any change or run)

Raise the L2/L3 pass rate on the frozen hull gate (RMS of station half-breadth error <= 2 % of the
half-beam, in-range volume error <= 5 %, frozen factory scorer, development truth only) without
hurting L0/L1. The gate does not change.

- Commit gate: on replay of stored readings, L0 must not drop below 4 of 6 passes and L1 not below
  2 of 6 (lane A live result at e2f795e). L2/L3 reported per case.
- Order: replay of stored readings first (no model calls); then one live round on 2-4 cases; then
  the full L2/L3 set once. Model calls: Claude Sonnet 5.5 through the subscription only.

## Scale of the gate on L2/L3 sheets

2 % of the half-beam is 1.4-3.3 body-plan pixels on the L2/L3 sheets (ppm 9.8-17.2, half-beam
71-163 px), about one hull-line width, with blur sigma 0.9-1.7 px. A pass needs every station on
its own curve over its full height; the stored errors (12-59 %) are whole-curve failures, not
precision.

## Diagnosis (stored round `work/round-hull2-dev-e2f795e`, code e2f795e)

Facts:
- The body-plan reader (`MARINAFRAME_BODY_PLAN_READER`) was off in all 12 runs; every hull came from
  the candidate path (`investigation.enumerate_strokes` -> `panel_assignment`).
- The replay of the stored reading gives the delivered result (dtmb L2 32.33 %, L3 59.03 %): the
  first hull decides the outcome; later model edits were rejected by the keep rule.
- Stroke enumeration on blurred panels: most seeds end `stroke_too_short` (8-51 per panel); kept
  strokes have hull likeness 0.1-0.2 (L0: higher); almost every panel has fewer strokes than
  stations, so stations share strokes. Removing ruled grid lines before enumeration (prototype) did
  not change this (not kept).

Per case (delivered draft; model datums against truth datums mapped through the scan matrix;
per-station coverage of the truth height and in-range shape error):

| Case | RMS % / vol % | Model scale / datums | Main station failure |
|---|---|---|---|
| dtmb5415-L2 | 32.33 / +36.7 | right | traces jump to grid columns and between converging aft curves (shape 17-23 % at s05-s08) |
| dtmb5415-L3 | 59.03 / +61.6 | right | model described 3 stations, not 9 |
| series60-L2 | 36.73 / -29.7 | scale 18.465 vs 16.465 (title misread) | all shapes scaled; x spacing 8.9 m |
| series60-L3 | 20.39 / -11.5 | right | no usable strokes; all 9 sections model-authored prior forms |
| 00679-L2 | 28.45 / +11.9 | right | s02-s04 share one stroke; s08/s09 carry other curves |
| 00679-L3 | 44.21 / -22.5 | scale 16.0 vs 14.43 (title unread, LOA guessed), body centreline 78 px off | everything |
| 08158-L2 | 17.38 / -19.2 | right (second body setup 31 px off) | right shapes, missing bottoms: s01-s04 traces start at z 2.4-5.1 m |
| 08158-L3 | 17.70 / +5.2 | right | s05/s06 shared stroke (12 %); s07/s08 bottoms missing |
| 09867-L2 | 12.72 / +5.1 | body datums null (inherited) | aft 2.5 % (shared, close); s09 wrong curve (35 %) |
| 09867-L3 | 35.68 / -44.3 | profile x origin reversed | traces z 4.4-15.0 against 0.1-12.5 |
| 02216-L2 | 17.42 / +10.9 | right | s02-s04 shared wrong stroke (24 %); s08 bottom missing |
| 02216-L3 | 46.79 / -8.4 | right; 10 stations (0-9) | aft s01-s05 one shared curve 44 % |

Failure classes over the 12 cases (main cause): code tracing on blurred ink (shared strokes, jumps,
missing bottoms) 7; model scale/datum misreading 3 (series60-L2, 00679-L3, 09867-L3); model station
list 1 (dtmb-L3); no traceable strokes 1 (series60-L3). Image downscaling and tile boundaries: not
seen (sheets are 1668-2462 px wide; the model's body crops are upscaled 3-4x).

Base replay of the stored readings at 3865d8c (current code, `work/degraded-lane/replay-base.json`),
RMS % / volume %: dtmb-L2 32.33 / +36.7, dtmb-L3 59.03 / +61.6, series60-L2 36.73 / -29.7,
series60-L3 45.98 / +56.5 (delivered 20.39 came from later model-authored edits), 00679-L2
28.45 / +11.9, 00679-L3 44.21 / -22.5, 08158-L2 47.77 / +3.8 (delivered 17.38 at e2f795e;
stations 2-7 all took one 0.6-5.5 m stroke), 08158-L3 17.70 / +5.2, 09867-L2 12.72 / +5.1,
09867-L3 39.10 / -49.5 (delivered 35.68 after model edits), 02216-L2 20.35 / +17.1 (delivered
17.42), 02216-L3 46.79 / -8.4. All 12 fail.

## Fix 1: shared fragments go to the form fit (`first_hull_tools.shared_fragments`)

The most common station failure in my files: a short stroke (a piece broken by blur or a
crossing) that the panel assignment gives to several stations. Built as drawn, each such station
has no breadth above or below the piece. Rule: a traced anchor covering less than 60 % of its
section height whose ink another station also carries is left out; the form fit fills that station
from its neighbours and the described beam and depth. Short end stations on their own ink
(dtmb s01 covers 4.3-8.8 m of 12.5 m) are kept; reader anchors are never touched. Tests:
`tests/test_first_hull_bottoms.py` (two new).

Commit gate check (written before the replay; probe stops right after the rule,
`work/degraded-lane/fragments-L0L1.log`): the rule leaves out no anchor in any of the 6 L0 and 5 of
6 L1 stored readings, so those hulls are unchanged (L0 stays 4 of 6, L1 passes 08158 and 09867
untouched). It acts on 02216-L1 (50.26 %, a scale misreading): stations 2, 3, 4, 6, 7 shared one
0.7-5.0 m piece of an 8 m section.

### Fix 1 replay (`work/degraded-lane/replay-fix.json`, code 6951d08)

| Case | Base replay RMS / vol % | Fix 1 replay RMS / vol % |
|---|---|---|
| dtmb5415-L2 | 32.33 / +36.7 | 32.33 / +36.7 (unchanged) |
| dtmb5415-L3 | 59.03 / +61.6 | 59.03 / +61.6 (unchanged) |
| series60-L2 | 36.73 / -29.7 | 36.73 / -29.7 (unchanged) |
| series60-L3 | 45.98 / +56.5 | 45.98 / +56.5 (unchanged) |
| 00679-L2 | 28.45 / +11.9 | 28.45 / +11.9 (unchanged) |
| 00679-L3 | 44.21 / -22.5 | **30.50 / -11.9** |
| 08158-L2 | 47.77 / +3.8 | **23.63** / +42.3 (volume worse: fitted fills too full) |
| 08158-L3 | 17.70 / +5.2 | 17.70 / +5.2 (unchanged) |
| 09867-L2 | 12.72 / +5.1 | 12.72 / +5.1 (unchanged) |
| 09867-L3 | 39.10 / -49.5 | **19.53 / +23.4** |
| 02216-L2 | 20.35 / +17.1 | 20.35 / +17.1 (unchanged) |
| 02216-L3 | 46.79 / -8.4 | 46.79 / -8.4 (unchanged) |
| 02216-L1 | 50.26 (lane A, round-1 code) | **12.98 / -9.3** |

RMS better on 3 of 12 L2/L3 and on 02216-L1, unchanged elsewhere; no new pass. Mean L2/L3 RMS
36.0 -> 31.2 %. L0/L1 gates hold (probe above).

Live gate (written before the live round): one live round, Claude Sonnet 5.5 only, sheet-only,
`--policy live --on-ambiguity draft --context conversation`, on the three cases the rule acts on
(08158-L2, 00679-L3, 09867-L3). Report delivered RMS/volume against the e2f795e live numbers
(17.38, 44.21, 35.68). The full L2/L3 set runs once afterwards only if the live round shows no
case worse by more than the run-to-run spread lane A saw (about 4 points).

Gate amendment (PM, written before the next replay): the hull gate is 2 % RMS AND 5 % volume, and
fix 1 made volume worse (08158-L2 +3.8 -> +42.3 %; 09867-L3 |-49.5| -> |+23.4| is better in size
but the fill is too full). Before any push or live run:
1. Find why the stations fix 1 hands to the form fit come out too full and fix it.
2. Volume condition, on replay and on the live round: no case may get worse in |volume error| by
   more than 2 points against its base, and L0/L1 volume errors must stay unchanged.
3. Replay again (all 12 L2/L3 and 02216-L1; the L0/L1 probe again if the change can reach them),
   then the live round on the three cases as planned.

## Fix 2: fitted rows within the printed half-beam (`form_fit.fitted_breadth_cap`)

Why fix 1 overfilled: with anchors, `fit_vessel` ignored the vessel size, so a breadth trend through
three anchors ran to 11.9 m half-breadth on 08158-L2 (printed beam 19.70 m, half-beam 9.85 m; the
description left the printed beam out of the spec because blurred panels measured 24.8 and
27.9 m). Fix 2: fitted rows are no wider than half the printed beam (else the description beam that
sized the prior; never the panel extents), raised to the widest traced anchor
(`first_hull_tools.half_beam_limit`). Tests in `tests/test_form_fit.py` (three).
Probe on all 24 stored readings (`work/degraded-lane/cap-probe2.log`): the limit changes no L0
or L1 hull except 02216-L1, and only rows that fix 1 had left to the fit.

### Replay with fixes 1+2 (`work/degraded-lane/replay-fix2.json`, base on current code with both
off: `replay-base.json`, `replay-base-02216-L1.json`)

| Case | Base RMS / vol % | Fixes 1+2 RMS / vol % | Volume condition |
|---|---|---|---|
| 00679-L3 | 44.21 / -22.5 | 30.50 / -11.9 | met |
| 08158-L2 | 47.77 / +3.8 | 22.40 / +37.8 | **failed** (+34 points) |
| 09867-L3 | 39.10 / -49.5 | 19.53 / +23.4 | met |
| 02216-L1 | 50.26 / -4.4 | 12.62 / -9.3 | **failed** (+4.9 points) |

The other 8 L2/L3 readings and all L0/L1 except 02216-L1 have unchanged hulls (probe).
08158-L2 stays overfull because the anchors that fix 1 keeps (s01, s08, s09) are wrong curves
themselves (shape error 23-29 %); in the base, those over-wide anchors and the fragments cut off at
5.5 m cancelled in volume by chance.

Verdict against the committed gate: fix 1 fails the volume condition on two cases. Fix 1 is
removed (no live round with it). Fix 2 stays: it changes no stored hull without fix 1 and limits
any future fit that runs past the printed beam.

## Results for this lane

L2/L3 pass rate unchanged: 0 of 12 (replay, current code). L0 4 of 6 and L1 2 of 6 unchanged
(fix 2 changes no L0/L1 hull). No live model calls were made in this lane (cost 0); the stored
round that was diagnosed cost $43.29 list (lane A).

## Resume point

Branch `lane/degraded-scans`: diagnosis, fix 2, fix 1 removed. Quick tier, then push. Next work, in
order of cases affected (diagnosis table):
1. Identity of the anchors themselves on blurred panels (08158-L2 s01/s08/s09, dtmb-L2 s05-s08):
   no rule that hands stations to the fit helps while the remaining anchors are wrong curves. A
   per-station check of each anchor against the plan-view waterline breadths at its x (code
   reading, no model call) would flag wrong curves before the fit.
2. Model scale misreads (series60-L2 16.465 read as 18.465; 00679-L3 title unread): cross-check the
   title scale against the station-line spacing in the profile (stations x spacing / px spacing)
   in `propose_sheet_setup` and tell the model when they disagree by more than 2 %.
3. Blurred profile outline (08158-L2 keel 7.51 = deck at s02): keel and deck heights are wrong
   on L2/L3 profiles, so bottom and top completion rules stay off there.
Each step: replay all 24 stored readings with the volume condition before any live round.
