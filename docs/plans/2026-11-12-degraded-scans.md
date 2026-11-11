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
28.45 / +11.9, 00679-L3 44.21 / -22.5; 08158-L2 47.77 (single probe run, delivered 17.38 at
e2f795e: stations 2-7 all took one 0.6-5.5 m stroke); rest paused (see resume point).

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

## Resume point

Fix 1 committed on `lane/degraded-scans` (not pushed; quick tier not yet run). The PM paused the
base replay (pid 67509) for a demo build and asked for no new heavy jobs. When released:
1. Let the base replay finish (`work/degraded-lane/replay-base.json`).
2. Replay with fix 1: the 12 L2/L3 readings and 02216-L1 (command in
   `benchmarks/hull_accuracy/replay_readings.py` docstring; `--rounds work/round-hull2-dev-e2f795e`,
   out `work/degraded-lane/replay-fix.json`), at most 2 cases at a time.
3. Quick tier, push. Live round (2-4 cases) only if the replay improves L2/L3; then the full
   L2/L3 set once.
Next candidate fixes (not started): scale cross-check of the model's title-block scale against the
measured station-line spacing (series60-L2, 00679-L3); keel-agreement rule on blurred profiles
(08158-L2 profile keel/deck heights wrong).
