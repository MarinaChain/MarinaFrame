# Round 14: PARDON ME holdout (fixed before running)

Status: protocol fixed 2026-11-09, before truth freeze and before any reader run. The original
runs are complete; section 11 records their results and a diagnosis only. All arms fail the rule.
Method copied from round 12 (BUE GIRL): `docs/plans/2026-11-09-whole-vessel-scope.md` section
3.5.11 and `docs/WHOLE_VESSEL_GUNNERUS.md` section 5.9 (including the round 12b addendum).

## 1. Sheet

Runabout launch PARDON ME, HAER NY-547, sheet 4 of 6, "Lines" with "Table of Offsets". US public
domain (HAER, Library of Congress). Source outside this worktree, in the main checkout:
`work/sources/haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif`, 17,600 x 13,600 px,
1-bit, 400 dpi, SHA-256 `586276fc9563e49edd1a7acf3eb6ab229f70377e424d070dfaa67f2a0c7ebb49`.
Printed scale: 3/4 in = 1 ft. Table heading: "Offsets in Feet-Inches-Eighths", "Offsets are to
outside of skin". The body plan is at the upper left of the sheet; the table is to its right.

## 2. Host calibration (drawn grid, labels and scale bar only)

Made by the round-14 agent from the drawn ink. No printed offset value was read or used.
Disclosure: the first whole-sheet overview (1,100 x 850 px, a 16x reduction) showed the table.
Its values were not transcribed or used. All later crops excluded the table. Only the table
title, the heading and the row and column labels were read.

Measured on ink (pixel = dark below 128), by row and column ink projections:

| Item | Value | Evidence |
|---|---|---|
| Body plan box | columns 1,440 to 4,860, rows 3,300 to 5,900 | crops of the drawn plan |
| Centreline column | **3270.0** | dash-dot line, 3 px wide, columns 3269 to 3271; midpoints of the four pairs of grid columns 3270.0 to 3270.5 |
| Waterline rows | W3 **4329**, W2 **4629**, W1 **4929**, W0 **5229**, W-1 **5529**, W-2 **5829** | see below |
| Scale | **300.0 px/ft** (984.252 px/m) | two independent drawn measures, see below |
| Grid columns (buttocks 1 to 4 ft) | left 2970, 2670, 2370, 2070; right 3570, 3871, 4171, 4471 | 3 px vertical lines |
| Maximum search half-span | **1550 px** (5.17 ft) | see below |

Waterline rows: the body plan names only the baseline ("W0 BASELINE", a 5 px line, rows 5227 to
5231). The other rows are baseline + n x 300 px. The drawn grid confirms W3, W2, W1 and W-1 at
exactly those rows (3 px lines). W-2 (row 5829) is not drawn on the body plan; its row comes from
the spacing only. The profile labels its waterlines W3, W2, W1, "W0 BASELINE", W-1 and W-2 at the
same 300 px spacing (profile rows 7434, 7734, 8034, 8334). The table row labels are WL 3-0-0,
2-0-0, 1-0-0, 0-0-0, -1-0-0 and -2-0-0. Thus Wn is the waterline n ft above W0, and the harness
keys the rows by the printed labels `3-0-0` ... `-2-0-0`. The table also has Sheer, Rabbet, Chine
and Transom rows; these are not waterlines.

Scale, two independent drawn measures:

1. Body-plan waterline grid: W3 4329 to W-1 5529 = 1,200 px for 4 ft = **300.0 px/ft**
   (buttock grid columns 2070 to 4471 = 2,401 px for 8 ft = 300.1 px/ft).
2. Feet scale bar under the profile ("0 1 2 3 4 5 FEET"): ticks at columns 8054, 8129, 8204,
   8279, 8354, 8654, 8954, 9254, 9554; 0 to 5 ft = 1,500 px = **300.0 px/ft**.

Agreement: 0.0 % (grid columns 0.03 %). The printed scale 3/4 in = 1 ft at 400 dpi also gives
300 px/ft. The centimetre bar is not used.

Halves and station order (labels drawn on the body plan):

- Aft half is **left** (sign -1). Labels "6 7 8 9 10 11" from outboard to inboard. Stations
  outermost first **6, 7, 8, 9, 10, 11**. Grid columns 2970, 2670, 2370, 2070.
- Fore half is **right** (sign +1). Labels "STA. 1", 2, 3, 4, 5; leaders end at the sheer at
  offsets of about 970, 1330, 1480 and (4 and 5 together) 1525 px. Stations outermost first
  **5, 4, 3, 2, 1**. Grid columns 3570, 3871, 4171, 4471.

This matches the fixed round-8 side names (aftbody left of the centreline, forebody right).

Maximum half-breadth: the outermost station crossing at a drawn waterline is 1,451 px (left half,
W3); on the right it is 1,429 px. The label "W0 BASELINE" starts at offset 1,590 px on the right.
1,550 px clears the outermost curve by about 100 px (4 in) and stops before that label.

## 3. Fit of the reader's assumptions (written before any run)

The round-8 reader assumes nested, curved station lines that each cross a waterline once and keep
their nesting order. This sheet is a hard-chine runabout. The drawing shows these departures:

1. Hard chine: each station is two segments that meet at a corner, near-straight topsides above
   and a bottom below. The fore topsides are nearly straight lines with strong flare.
2. W0 is near the chine on both halves. Aft, the chines lie about 0.4 ft below W0, and all six
   station curves and the transom converge within about 80 px at W0. Merged crossings are likely.
   Fore, the chines of stations 1 to 3 lie above W0 and those of 4 and 5 below it, so W0 crosses
   bottoms on some stations and topsides on others.
3. Below the chine the bottoms are shallow, mostly on the aft half (low deadrise). The crossings at
   W-1 may be rejected as shallow (`SHALLOW_SLOPE` 6 columns per row).
4. The aft half has a heavy transom outline inside station 11 at W1 to W3 (seven curves, six
   stations). Station 6 has tumblehome and crosses station 7 between W3 and W1. Only six crossings
   are visible on the aft half at W2 and W1, so the nesting order is not strict there.
5. The fore half has about four unlabelled bow sections inside station 1 (forward of station 1 at
   1 ft spacing in the profile; not in the table), nine curves at W3 in all. Stations 4 and 5 start
   at one sheer point and are about 60 px apart at W3. A heavy chine line crosses W0 at a shallow
   angle.
6. W-2 is at the keel bottom; crossings within 70 px of the centreline are stem or keel structure.

The fit is therefore partial. Per the brief, the reader still runs as fixed: no reader, threshold,
prompt or image change for this sheet. These causes are listed now so that a failure is not
explained after the fact by new causes without evidence.

## 4. Truth

Two independent transcriptions of the printed table, made by other agents and frozen by the PM
before any run. The round-14 agent does not see the transcriptions or the frozen file. The PM
records the frozen path and its SHA-256 in section 8 before the first run.

Scored cells: the **Half Breadths From Centerline** block only, numbered stations **1 to 11**,
waterlines **3-0-0, 2-0-0, 1-0-0, 0-0-0, -1-0-0, -2-0-0**; every **nonblank** cell (at most 66).
The PM records the count from the frozen file in section 8 before any run; the 60 % rule uses that
count. Not scored, but kept in the frozen source with reasons: blank cells; the Sheer, Rabbet and
Chine rows (not waterline half-breadths); the Transom rows (not numbered station curves); the
Heights Above Baseline block and the X-positions.

Printed-value rules (harness only, as round 12): feet-inches-eighths; a trailing `+` adds 1/16 in;
a leading `-` is a sign or separator mark and the magnitude is the half-breadth. Any other form
(ditto, two values, inches 12 or more, eighths 8 or more) stops the loader with an error. The PM
then resolves it in the frozen truth before the run. A cell is never dropped silently.

## 5. Arms (one shared measurement)

- **R0, code only**: deterministic, **1 run** (identity by nesting order, as round 8).
- **R1, Crouton**: `round8.crouton_with_fallback()` (Crouton Alpha Free on OpenCode Go, key 1; one
  failed-request retry after 5 s, then DeepSeek V4.1 Flash). **3 repeats**.
- **R1, Claude Sonnet 5.5**: `thayer.claude_call(thayer.SONNET)` (`claude -p --model
  claude-sonnet-5-5`, subscription login, no tools, no API key, never OpenCode Go). **3 repeats**.
  Access check on 2026-11-09 with a one-line prompt: `claude -p --model claude-sonnet-5-5`
  answered "ok", result `success`, `modelUsage` `claude-sonnet-5-5`, both with the session's
  environment and with `ANTHROPIC_BASE_URL` removed. Runs use a shell without
  `ANTHROPIC_BASE_URL` (as round 12b). If access fails during the run, record an access failure
  and continue the other arms; the code-fallback numbers are then not reported as Sonnet scores.

Four question workers, temperature, effort, invalid-reply retries and disagreement re-asks are
unchanged from round 8. Outputs stay outside the repository:
`/private/tmp/claude-501/pardon-me/runs/<arm>`. **No repeat to improve a score.** An interrupted
repeat is completed from its saved replies, as round 12 did, and disclosed.

## 6. Frozen reader

The source at **80d5fa5** (branch `continue/v0.5`). No change to `src/vessel_reconstruction/body_plan_*.py`
or `benchmarks/balclutha/crossing_value.py`. SHA-256 at this commit (guarded by a test):
`body_plan_reader.py` 327c9f14…ba94e11, `body_plan_crossings.py` c6553371…aaf6fcf97,
`body_plan_identity.py` ba738892…c441e9a0c34, `crossing_value.py` bafb3ac5…4c9a4ddf.
The harness `benchmarks/pardon_me/holdout_value.py` adds only this calibration, the truth loader
and parser, the scorer dimensions and orchestration. It reuses the round-8, round-12 and Thayer
functions. A failure is reported with its causes, not repaired in this round.

## 7. Metrics and decision rule (copied from 3.5.9)

Cells given of the scored count, RMS and maximum error, share within 0.05 m and 0.15 m, station
identity errors (a station whose values fit a neighbouring station's truth better), median and
range over repeats. An arm **passes** if **every repeat gives at least 60 % of the scored cells and
the median RMS is at most 0.15 m** (R0: its one run). Also reported: chains per half, questions,
re-asks, invalid replies, answers per model, labels equal to the code's count, fairness flags,
extra cells, tokens and wall time.

Reading, fixed now: the reader **generalises** if R0 and Crouton both pass; **only with a strong
identifier** if only Sonnet passes; otherwise it **does not generalise**, and the failure causes
are listed (section 3 first). Do not widen this rule after results. A metrics pass does not
establish correct identities or engineering use. `engineering_approved` stays false.

## 8. Truth freeze record (PM fills before the first run)

- Frozen truth path: `/private/tmp/claude-501/pardon-me/truth_s4.json` (converted from
  `truth-frozen/table_as_printed.json`, sha256 0d394abb58306b80556c77d97b4e5475e40b4d740f4cd8bcb10bed6a24a4cdf2;
  only the Halfbreadths From Centerline rows WL 3-0-0 to -2-0-0, stations 1 to 11)
- SHA-256: `ab33dc13e0c1ffec81fb1e45068788953adb033d6bc9cb29b3e132da03089242`
- Scored nonblank cells (of 66): `57`
- Transcriptions agree on: `162` station cells (all; pass A Sonnet 5.5 row crops, pass B Opus 5.5
  column crops) and the six transom values; differences resolved: `0` (none needed)

## 9. Run commands (from the worktree root, in a shell without `ANTHROPIC_BASE_URL`)

```
SHEET=/Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/haer/master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif
TRUTH=<frozen truth path from section 8>
RUNS=/private/tmp/claude-501/pardon-me/runs
PYTHONPATH=src:. .venv/bin/python -m benchmarks.pardon_me.holdout_value --arm code    --sheet $SHEET --truth $TRUTH --out $RUNS/code
PYTHONPATH=src:. .venv/bin/python -m benchmarks.pardon_me.holdout_value --arm crouton --sheet $SHEET --truth $TRUTH --out $RUNS/crouton
PYTHONPATH=src:. .venv/bin/python -m benchmarks.pardon_me.holdout_value --arm sonnet  --sheet $SHEET --truth $TRUTH --out $RUNS/sonnet
```

## 10. Resume point

Done: protocol (this file), harness and synthetic tests, truth freeze, one run of each arm, and
the results and diagnosis in section 11. Next: development work listed at the end of section 11,
in a new round. Do not rerun these arms or change this round.

## 11. Results (one run per arm, 2026-11-09)

Sources: `/private/tmp/claude-501/pardon-me/runs/{code,crouton,sonnet}/summary.json`, and
`benchmarks/pardon_me/diagnose.py` (read-only; it re-measures the sheet with the frozen reader,
applies the saved labels, and stops if any score differs from the saved summary). The diagnosis
is not a scored run. Nothing was rerun and no reader, truth, scoring or rule was changed.
`engineering_approved` is false for every arm.

### 11.1 Table

All 57 scored cells (of 66); 1 extra cell (W-2, station 1, truth blank) in every repeat; 0
fairness flags; 0 invalid replies.

| Arm (repeats) | Cells given | Coverage | RMS (m) | Max (m) | Within 0.05 m | Within 0.15 m | Identity errors | Calls | Prompt tokens |
|---|---|---|---|---|---|---|---|---|---|
| code (1) | 34 | 59.6 % | 0.1347 | 0.637 | 79 % | 91 % | 6, 10, 11 | 0 | 0 |
| Crouton (3, all identical) | 34 | 59.6 % | 0.1288 | 0.637 | 91 % | 94 % | 6 | 25 each | about 4,000 each |
| Sonnet 5.5 (3, all identical) | 34 | 59.6 % | 0.1288 | 0.637 | 91 % | 94 % | 6 | 25 each | about 132,000 each |

Crouton prompt tokens: 4,012. Sonnet 5.5 prompt tokens: 132,029 to 132,036.

### 11.2 Decision

The rule needs every repeat at 60 % or more of the scored cells, and a median RMS of 0.15 m or
less. Coverage is 34/57 = 59.6 %, 0.4 point below 60 % (one more cell would give 61.4 %). Median RMS
is within the limit for all three arms (0.1347 m and 0.1288 m). Every arm **fails** the rule on
coverage, so the reader **does not generalise** to this sheet. The RMS passes only on the cells
that were given. This is not an engineering pass.

### 11.3 Model value

The model labels changed 2 of the 3 code identity errors: stations 10 and 11 are fixed (RMS
0.1347 to 0.1288 m; within 0.05 m 79 % to 91 %). The station 6 error stays in every arm. Crouton and
Sonnet 5.5 give the same table in all six repeats, so Sonnet 5.5 adds no value over Crouton here,
at about 33 times the prompt tokens. Neither model changes the coverage: the missing cells are
not label problems (section 11.4). Labels cannot add a cell that no chain holds.

### 11.4 Missing cells (23 of 57; the same 23 in all arms)

Scored cells given per waterline: W3 9/11, W2 9/11, W1 9/11, W0 4/11, W-1 2/10, W-2 1/3 (the
truth has no value at W-1 for station 11, and none at W-2 for stations 1 and 5 to 11).

| Waterline | Missing stations |
|---|---|
| W3, W2, W1 | 1, 2 |
| W0 | 1, 2, 3, 6, 7, 8, 9 |
| W-1 | 3, 4, 5, 6, 7, 8, 9, 10 |
| W-2 | 3, 4 |

Cause per cell (from the crossing and chain record; none is a beyond-maximum-offset case and none
lacks a crossing on its half):

- 20 cells: a crossing exists within 0 to 5 px of the truth offset, but the chain rule left it
  out. The rule keeps only chains that cross 2 or more waterlines, then gives stations by
  nesting rank. Chains that the chine splits into pieces (a topside piece at W1 to W3, and bottom
  pieces at W0, W-1, W-2) are not joined. The links found 0 inferred links on each half.
- Fore stations 1 and 2 (W3 to W0 and W-1 to W-2): the first five chains with 2 or more
  waterlines are used. Chains 4 and 5 are bottom pieces at W-1 and W-2 only, so they take
  stations 2 and 1, and the chains that span W3 to W0 further in (chains 8 and 9, and later) get no station. Result: stations 1
  and 2 are missing at W3 to W0.
- W0 aft, stations 6 to 9: W0 holds merged "double" crossings for stations 6, 8 and 9 (within 1 to 3 px
  of the truth offset), and the other aft W0 crossings sit in chains of one waterline. This is the
  protocol prediction (section 3, items 2 and 3).
- 2 cells (W-1 aft, stations 6 and 7): no crossing within the 8 px link tolerance of the truth
  offset; the nearest is a double crossing 8 and 10 px away.
- 1 cell (W-1 aft, station 10): the crossing is classified shallow, so it was rejected. The
  protocol predicted this (section 3, item 3).

The extra cell (W-2, station 1, 0.126 m) comes from fore chain 5, which is a bottom piece of
another station.

### 11.5 Largest errors

| Cell | Truth (m) | Given (m) | Error (m) | Arms | Cause |
|---|---|---|---|---|---|
| W-1, station 1 | 0.078 | 0.715 | 0.637 | all | fore bottom piece (chain 5) took station 1; 0.715 m is the W-1 crossing at the station 5 truth (0.714 m) |
| W-1, station 2 | 0.325 | 0.715 | 0.390 | all | fore bottom piece (chain 4) took station 2; it shares the same W-1 crossing |
| W3, station 11 | 1.033 | 1.196 | 0.162 | code only | aft chain 5 took station 11; the model fixes it |
| W3, station 10 | 1.195 | 1.315 | 0.120 | code only | aft chain 4 took station 10; the model fixes it |
| W-2, station 2 | 0.060 | 0.131 | 0.071 | all | fore chain 4 took station 2 |

All other errors are 0.08 m or less. In the Crouton and Sonnet table, the three fore cells
(W-1 stations 1 and 2, W-2 station 2) hold nearly all of the squared error: their sum is 0.563 m2
of about 0.564 m2 in total, so the RMS of 0.1288 m is set by them. The two fore W-1 cells alone
give 0.558 m2.
The station 6 identity error is flagged by the harness in every arm; its cell errors are small
(0.03 m at W1). Its cause is not isolated here; protocol section 3 item 4 (tumblehome crossing
station 7) is the likely one, but this is not proved.

### 11.6 What the reader would need (next development work, not a change to this round)

1. Join the pieces of one station across the chine, so a station has one chain from W3 to W-2.
   Today a chain is kept only if it has 2 or more waterlines, and no link crosses the chine corner.
2. Accept station curves that show at one waterline (W0 and W-1 aft) when the neighbours fix the
   station by position, instead of dropping them.
3. Split merged double crossings at W0 aft (where 6 curves lie within about 80 px) by using the
   chain above and below, not only the local crossings.
4. Handle shallow bottoms at W-1 and W-2: do not reject a bottom crossing as shallow when a chain
   above it ends at the chine.
5. Reject bottom pieces and keel or stem structure (within 70 px of the centreline) from the
   station rank, and the unlabelled bow sections inside station 1.
6. Add a check that the identity of each given cell is plausible against nesting at the same
   waterline. The 0.715 m cell at W-1 for both stations 1 and 2 shows a duplicate crossing.

Any of these needs a new round, with the protocol written before the run.
