# Round 13: BUMBLE BEE 47 holdout (fixed before running)

Status: protocol fixed 2026-11-09, before truth, harness runs and scores. Method copied from round 12
(BUE GIRL, `docs/plans/2026-11-09-whole-vessel-scope.md` section 3.5.11 and
`docs/WHOLE_VESSEL_GUNNERUS.md` section 5.9 with the 12b addendum). Harness:
`benchmarks/bumble_bee/holdout_value.py`; synthetic tests: `tests/test_bumble_bee_holdout_value.py`.

## 1. Sheet

- Bristol Bay gillnet fishing boat BUMBLE BEE 47 (BB-47), HAER OR-165, sheet 2 of 3, "Lines".
  A double-ended Bristol Bay gillnet boat, converted to power. US public domain (HAER, Library of
  Congress).
- File (main checkout, outside this worktree):
  `work/sources/haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif`.
- 14,400 x 9,600 px, 1-bit, 400 dpi. SHA-256
  `d1c0830dff9648b8c6967ead14fcaff484a91021eece277fda62725a0002f991`.
- Views: profile (top), half-breadth plan (middle), body plan (lower left), feet and centimetre
  scale bars (right of the body plan), "Table of Offsets" (lower right). Table notes (read as text,
  not as values): offsets in feet-inches-eighths, to the outside of the skin; stations spaced 2'-0",
  buttock lines spaced 1'-0", waterlines spaced 9"; "Lines drawn as is and not faired".

## 2. Host calibration (drawn grid and labels only)

Made by the round-13 harness agent (Claude Opus 5.5) without the truth and without the printed
offset values. Read: a 600 px wide overview of the whole sheet (table digits not legible at that
size), crops of the body plan, the scale bars, the profile, the plan view, and only these parts of
the table: title and notes, the station header row, the row labels. Measured with column and row
ink sums on the full-resolution 1-bit image.

| Item | Value | Evidence |
|---|---|---|
| Body plan box | columns about 1,200 to 4,800, rows about 6,400 to 8,710 | crop of the lower-left view |
| Centreline column | **3009.0** | thin dashed centreline below the keel, ink columns 3007 to 3011 (rows 8460 to 8700); the same column above the sheer; buttock grid symmetric about it |
| Baseline row | **8705** | dash-dot line across the body plan, ink rows 8703 to 8707 |
| Scale | **400.0 px/ft** (1312.3360 px/m) | see "Scale agreement" |
| Waterline rows | **1-6-0: 8105, 2-3-0: 7805, 3-0-0: 7505, 3-9-0: 7205** | baseline + height x 400 px/ft; the heights are the table row labels "WL 1-6-0" to "WL 3-9-0" (9" spacing, as the notes say); the body plan has no printed waterline labels |
| Fore half | **left**, sign -1, outermost first **6, 5, 4, 3, 2, 1** | curve labels "STA 6" ... "STA 1" from the outside in; profile and plan put STA 1 next to the stem at the left, the rudder at the right |
| Aft half | **right**, sign +1, outermost first **7, 8, 9, 10, 11, 12, 13, 14** | curve labels "STA 7" (outermost) ... "STA 14" (innermost) |
| Grid columns | fore 2609, 2209, 1809, 1409; aft 3409, 3809, 4209, 4609 | vertical grid lines (buttocks 1 to 4 ft), measured centres, exactly CL ± 400, 800, 1200, 1600 |
| Maximum half-breadth | about **1,780 px** (1.36 m) | outermost ink at row 7205: left 1,774 px, right 1,780 px; at row 7505: 1,750 / 1,766 px |
| Search half-span `max_offset_px` | **1900** | largest half-breadth + 120 px margin; stays 260 px clear of the feet scale bar (column 5170) and inside the left frame |

Scale agreement (independent drawn measures, all 400 px/ft):

1. Feet scale bar: ticks 0, 1, 2, 3 ft at columns 5180, 5580, 5980, 6380: 400.0 px/ft.
2. Body plan buttock grid (labelled 1-0-0 to 4-0-0 in the table and B1 to B4 in the plan view):
   columns 1409 to 4609 at a constant 400.0 px = 1 ft.
3. Profile waterlines WL 1 to WL 4: rows 2983, 2683, 2383, 2083 above the profile baseline 3583:
   600, 900, 1200, 1500 px = 1'-6", 2'-3", 3'-0", 3'-9" at 400.0 px/ft (spacing 300 px = 9").

Measures 1 and 2 agree to better than 0.1 % (both exactly 400 px/ft at whole-pixel resolution).
The centimetre bar is not used.

Body-plan baseline check: the painted waterline is 747 px above the body-plan baseline (row 7958)
and 748 px above the profile baseline (row 2835). The heights in the body plan therefore use the
same baseline and scale as the profile.

Known from the drawing before running (not used to change anything):

- Only the lowest scored waterline has a drawn line near its nominal row. The body plan has a
  1-ft horizontal grid at rows 6913, 7314, 7714 and a short line at 8114 (inside the hull only),
  and the painted waterline at 7958. These are not the table waterlines (they lie at 1.48, 2.48,
  3.48 and 4.48 ft above the baseline). The reader searches ±20 rows for the drawn waterline: at
  1-6-0 (nominal 8105) it will trace the short line at 8114 (9 px, 0.27 in, lower); at 2-3-0,
  3-0-0 and 3-9-0 it finds no line and uses the nominal row (reader behaviour, not changed). If
  the 1-ft grid was drawn from a baseline at 8714, the nominal rows would all be 9 px lower; this
  ambiguity is recorded, not resolved.
- The aft stations 7, 8 and 9 (and fore stations 5 and 6) are drawn within about 10 to 30 px of
  each other at the upper waterlines; merged crossings are likely.
- At 1-6-0 the curves run nearly horizontally towards the keel (curves converge near row 8200);
  the reader's shallow-line rule (more than 6 columns per row) may reject crossings there.
- The stem/keel members are drawn as vertical lines at columns 2952.5 and 3065.5 (56.5 px from
  the centreline, inside the 70 px stem rule).
- "PAINTED WL" lettering lies at rows 7872 to 8042, outside every ±40-row band.

## 3. Truth

- Method copied from round 12: two independent Claude transcriptions of the printed Table of
  Offsets, made by other agents (not this harness agent), compared after whitespace
  normalisation and frozen by the PM before any reader run. The PM gives the frozen path and its
  SHA-256; the harness agent never opens it before the scoring run. No new transcription after
  freezing; a disagreement between the two reads is not resolved by a third read.
- Scored cells: the **Half Breadths From CL** block, rows **WL 1-6-0, WL 2-3-0, WL 3-0-0,
  WL 3-9-0**, numbered stations **1 to 14**: at most 56 cells. The denominator for "cells given"
  is the number of nonblank scored cells N in the frozen truth (fixed before any run; the PM
  records N here or in the result).
- Value rules (harness parser, not a reader change):
  - Feet-inches-eighths `F-I-E`, inches 0 to 11, eighths 0 to 7.
  - A trailing `+` adds 1/16 inch (round-12 PM interpretation; the sheet does not define it).
  - A leading `-` is a sign/separator convention; the magnitude is the half-breadth (round 12).
  - A blank cell is not scored.
  - A ditto mark, a crossed or illegible cell, or a cell where the two transcriptions disagree is
    not scored; the PM writes `null` for it in the scored rows and lists it with its printed
    content and reason in `excluded`. No nonblank, agreed, parseable scored cell is removed.
  - Any other text in a scored cell is an error (the loader stops); it is never guessed.
- Not scored (listed by the PM, kept in the frozen source): station 0 (the stem; no station
  curve in the body plan); the Keel, Rabbet and Sheer rows of the half-breadth block; the whole
  Heights Above Baseline block; "Sheer at rabbet"; the X-Positions row. The boat is double-ended:
  there is no transom column; station 14 is the innermost labelled aft curve and is scored.
  Unlabelled lines inside station 1 or station 14 (stem, sternpost, keel members) are not
  stations.
- Truth file format: section 6.

## 4. Arms

One shared deterministic measurement per arm run (same sheet, same layout). No reader change:
the reader is the source at `80d5fa5` (`continue/v0.5`); the guard test checks the SHA-256 of
`src/vessel_reconstruction/body_plan_reader.py`, `body_plan_crossings.py`, `body_plan_identity.py`
and `benchmarks/balclutha/crossing_value.py` (the same digests as round 12). All thresholds,
prompts, question images, candidate rules and naming are unchanged. The harness adds only the
calibration, the truth loader, the printed-value parser, the scorer dimensions and the run
orchestration; it reuses the round-8 functions and the Thayer `claude_call`.

- **R0, code only**: identity by nesting order; **1 run**.
- **R1, Crouton**: `crouton-alpha-free` on OpenCode Go through `round8.crouton_with_fallback`
  (key 1, reasoning effort high, temperature 0.2, at most 3 turns per question, 4 questions in
  parallel, re-ask on disagreement; a failed request is retried once after 5 s, then sent to
  `deepseek-v4.1-flash`); **3 repeats**.
- **R1, Claude Sonnet 5.5**: the same questions through `thayer.claude_call` (`claude -p --model
  claude-sonnet-5-5`, no tools, stream-json, `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`
  removed, subscription only, never OpenCode Go); **3 repeats**. Run it only where
  `claude -p --model claude-sonnet-5-5` answers a one-line prompt. Access check 2026-11-09 in the
  harness agent's environment (Claude Code 2.1.280, `ANTHROPIC_BASE_URL` =
  `https://api.anthropic.com`, API keys removed): the reply was `OK` (stderr warned that the model
  is not in this CLI version's model catalog; the reply was still produced). The PM repeats the
  check in the run environment. If it fails there, record an **access failure** (as round 12) and
  continue with the other arms; do not score the code fallback as a Sonnet result.

Outputs stay outside the repository (PM's choice of folder, one new folder per arm; the harness
refuses an existing folder). No repeat to improve a score. A failure is reported with its causes;
fixes are a later round.

## 5. Metrics and decision rule (copied from section 3.5.9)

Cells given of N, RMS and maximum error, share within 0.05 m and 0.15 m, station identity errors
(a station whose values fit a neighbouring station's truth better), median and range over
repeats. An arm **passes** if **every repeat gives at least 60 % of the N cells and the median RMS
is at most 0.15 m** (R0: its one run). Also reported: chains per half, questions, re-asks,
invalid replies, answers per model, labels equal to the code's count, fairness flags, tokens,
wall time. Extra cells (emitted where the truth is blank) are reported, not penalised.

Reading, fixed now: the reader **generalises** if R0 and the Crouton arm both pass; it
generalises **only with a strong identifier** if only the Sonnet arm passes; otherwise it **does
not generalise**. Do not widen this rule after results. A metrics pass does not establish correct
identities or engineering use; `engineering_approved` stays false.

## 6. Truth JSON format (input of `load_truth`)

```json
{
  "sheet_sha256": "d1c0830dff9648b8c6967ead14fcaff484a91021eece277fda62725a0002f991",
  "stations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
  "rows": {
    "1-6-0": ["<cell for station 0>", "...15 entries, string as printed or null..."],
    "2-3-0": ["..."],
    "3-0-0": ["..."],
    "3-9-0": ["..."]
  },
  "excluded": [
    {"station": 5, "waterline": "2-3-0", "printed": "\"", "reason": "ditto"}
  ]
}
```

- `stations` must be exactly 0 to 14 (the printed column order). Each row has 15 entries. The
  station-0 entry is kept as printed but never scored.
- Scored entries are the printed string (whitespace free) or `null` (blank, or excluded per
  section 3). `excluded` is optional; it is checked (stations 1 to 14, known waterline, a reason)
  and reported, never scored.
- `sheet_sha256` must equal the sheet hash above.

## 7. Run commands (from the worktree root; not run by the harness agent)

```bash
export PYTHONPATH=src:.
SHEET=/Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif
TRUTH=<frozen truth JSON path from the PM>
OUT=<new folder outside the repository>
.venv/bin/python -m benchmarks.bumble_bee.holdout_value --arm code    --sheet "$SHEET" --truth "$TRUTH" --out "$OUT/code"
.venv/bin/python -m benchmarks.bumble_bee.holdout_value --arm crouton --sheet "$SHEET" --truth "$TRUTH" --out "$OUT/crouton"
claude -p --model claude-sonnet-5-5 "Reply with the single word OK"   # access check first
.venv/bin/python -m benchmarks.bumble_bee.holdout_value --arm sonnet  --sheet "$SHEET" --truth "$TRUTH" --out "$OUT/sonnet"
```

The harness checks the sheet SHA-256 before measuring and stops on a mismatch.

## 8. Resume point

Protocol committed first, then harness and synthetic tests. Next: the PM freezes the truth in the
section 6 format, then runs the three arms once each with the commands of section 7, then records
results in a new section below without changing sections 1 to 7.

### Truth record (completed 2026-11-09)

The PM freeze record at `/private/tmp/claude-501/bumble-bee/truth-frozen/README.md` records
independent row-crop and column-crop transcriptions: 182 nonempty printed cells agreed, with zero
whitespace-normalised differences and no doubtful cells. The full printed table
`truth-frozen/table_as_printed.json` has SHA-256
`d127f9ac3d7c05369e0f0abfbf20314884e3fa96cdd949a4d532a985203c8fb1`.
The derived scoring input `/private/tmp/claude-501/bumble-bee/truth_s2.json` has SHA-256
`906c64f44250eeea038f5b6cfbf25e502538ce05ae00ae5cdc750c661b70d679`.
It has **54 scored cells**, `excluded: []`, and two blank scored-block positions: stations 1 and
14 at 1-6-0. Station 0 remains outside the scoring block. The undefined printed `+` retains the
fixed parser interpretation in section 3. These files remain outside the repository.

## 9. Results (one run per arm, 2026-11-09)

### Measured decision and model value

The fixed code arm ran once. Each fixed model arm ran once with its three prescribed repeats.
Sources are `/private/tmp/claude-501/bumble-bee/runs/{code,crouton,sonnet}/summary.json`, with
saved final labels and replies in the model repeat folders. No arm was rerun, and no calibration,
reader, scoring, truth, threshold, prompt, or decision rule was changed for this diagnosis.
`engineering_approved=false` throughout.

| Arm / repeat | Cells / 54 | Extra | RMS m | Max m | Within 0.05 m | Within 0.15 m | Identity flags |
|---|---:|---:|---:|---:|---:|---:|---|
| Code / 1 | 50 (92.59%) | 2 | 0.114051 | 0.249336 | 42.00% | 76.00% | 2–8, 10, 11, 14 |
| Crouton / 1 | 51 (94.44%) | 1 | 0.127246 | 0.227803 | 37.25% | 64.71% | 2–8, 11, 12 |
| Crouton / 2 | 51 (94.44%) | 1 | 0.127246 | 0.227803 | 37.25% | 64.71% | 2–8, 11, 12 |
| Crouton / 3 | 51 (94.44%) | 1 | 0.127206 | 0.227803 | 37.25% | 64.71% | 2–6, 8, 11, 12 |
| Sonnet / 1 | 51 (94.44%) | 1 | 0.127246 | 0.227803 | 37.25% | 64.71% | 2–8, 11, 12 |
| Sonnet / 2 | 51 (94.44%) | 1 | 0.127246 | 0.227803 | 37.25% | 64.71% | 2–8, 11, 12 |
| Sonnet / 3 | 51 (94.44%) | 1 | 0.127246 | 0.227803 | 37.25% | 64.71% | 2–8, 11, 12 |

Within-tolerance percentages use the returned nonblank truth cells, not all 54. Extra cells are
not penalised. Identity flags are the frozen scorer's **immediate-neighbour fit heuristic**:
a station is flagged if its emitted values fit station s−1 or s+1 better, using at least three
shared rows. Fits can use different row subsets. These flags are not a complete count of wrong
identities: they cannot detect a distant station match, and an unflagged station need not be
correct. The wider chain-fit diagnosis below is separate from that metric.

**All three arms pass the fixed rule.** Every repeat returns at least 60% of the cells; median
RMS is 0.114051 m for code and 0.127246 m for each model arm. RMS ranges are a single value for
code, 0.127206–0.127246 m for Crouton, and a single value for Sonnet. The declared section-5
reading is therefore **“generalises” under this rule**, not “generalises only with a strong
identifier”. This rule is loose for a small boat: 0.114 m RMS is about 4.5 inches, against measured
maximum half-breadths near 1.36 m, and systematic station errors still pass. The rule was **not
changed after the run**. This result does not establish correct station numbering or suitability
for engineering use.

Models changed **6–8 final chain identities** relative to code, but did not fix the systematic
numbering. All three Sonnet tables equal Crouton repeat 1, cell for cell (Crouton repeat 2 also
equals it). Crouton repeat 3 changes only the near-outer right-side assignments, with negligible
RMS change. Models add one scored lowest-row cell, but worsen RMS and tolerance shares. There is
no measured accuracy gain from the stronger identifier here. The constrained candidate station
sets prevent either model from naming the opposite half's stations.

| Arm / repeat | Questions / re-asks / calls | Final labels equal code / null | Changed identities | Prompt / completion tokens | Repeat seconds |
|---|---:|---:|---:|---:|---:|
| Crouton / 1 | 16 / 3 / 19 | 6 / 3 | 6 | 4,022 / 365 | 302.1 |
| Crouton / 2 | 16 / 2 / 18 | 6 / 3 | 6 | 2,869 / 346 | 160.7 |
| Crouton / 3 | 16 / 2 / 18 | 5 / 6 | 8 | 2,869 / 367 | 267.0 |
| Sonnet / 1 | 16 / 1 / 17 | 8 / 1 | 6 | 107,220 / 7,878 | 50.3 |
| Sonnet / 2 | 16 / 1 / 17 | 8 / 1 | 6 | 102,344 / 8,101 | 49.4 |
| Sonnet / 3 | 16 / 2 / 18 | 8 / 1 | 6 | 108,201 / 9,758 | 72.0 |

All repeats record zero invalid replies, unanswered questions, failed final requests, and fairness
flags. Crouton repeat 1 records 18 answers from Crouton and one from DeepSeek fallback; the other
Crouton repeats record 18 Crouton answers each. The final-request failure count does not count
failed attempts hidden inside the fallback wrapper. Sonnet answers are all `claude-sonnet-5-5`.
Sonnet uses about **106k prompt tokens per repeat** (mean 105,922), with no better table.
Code makes zero calls. Deterministic measurement takes 1.5 / 1.7 / 1.7 seconds for the code /
Crouton / Sonnet arms, separate from repeat wall time. All arms have the same 7 left and 9 right
chains, no one-waterline chains, and 0 / 3 inferred links on the left / right. The fairness checks
produce no flags despite the identity errors.

### Main diagnosis: the calibrated halves are reversed relative to the truth

The numerical evidence strongly contradicts the section-2 assignment **fore 1–6 left, aft 7–14
right**. Left chains fit the truth's aft stations 10–14 to a few millimetres, and right chains
fit fore stations 1–6 to a few millimetres. This is a calibration finding of this round, not a
calibration correction. Sections 1–7 and the as-run results remain unchanged. No images were
viewed for this diagnosis; station fits below are numerical evidence, not a new visual reading
of the labels.

Chain indices are zero-based and retain the frozen reader's `fore` (left) / `aft` (right) names.
Each fit searches all stations independently, requires two shared nonblank rows, and uses the
chain's **unchanged** half-breadths. It does not enforce a one-to-one assignment. Near-midship
stations have very similar breadths; those fits are ambiguous. No remapped score is reported.

| Calibrated half / chain | Code station | Best truth station | Fit RMS mm / shared rows | Final model station, except Crouton 3 |
|---|---:|---:|---:|---:|
| Left / 0 | 6 | 7 (9 next at 3.4 mm) | 2.1 / 3 | 6 |
| Left / 1 | 5 | 10 | 4.0 / 4 | 5 |
| Left / 2 | 4 | 11 | 5.2 / 4 | 4 |
| Left / 3 | 3 | 12 | 5.9 / 4 | 3 |
| Left / 4 | 2 | 13 | 5.5 / 4 | 2 |
| Left / 5 | 1 | 14 | 3.4 / 3 | 1 |
| Left / 6 | none | 2, poor fit | 188.2 / 2 | none |
| Right / 0 | 7 | 8 | 2.9 / 3 | 7 |
| Right / 1 | 8 | 7 | 4.5 / 3 | 8 |
| Right / 2 | 9 | 7 | 3.3 / 3 | none |
| Right / 3 | 10 | 6 | 4.0 / 4 | 9 |
| Right / 4 | 11 | 5, with a bad shared node | 43.3 / 4 | 10 |
| Right / 5 | 12 | 4 | 5.3 / 4 | 11 |
| Right / 6 | 13 | 3 | 5.2 / 4 | 12 |
| Right / 7 | 14 | 2 | 4.5 / 4 | 13 |
| Right / 8 | none | 1 | 2.3 / 3 | 14 |

Crouton repeat 3 leaves right chain 0 unassigned and assigns right chains 1 and 2 to 7 and 8;
all remaining assignments match the last column. Raw model labels differ more than the final
tables: for example Crouton labels left chain 0 null, but the assignment still gives it station
6; Sonnet labels right chain 4 as 9, but the nesting solver assigns it 10. The diagnostic script
prints both raw labels and final assignments for every repeat.

Examples of the side mismatch, low to high waterline, in metres:

- Left chain 1, code station 5: **0.5833, 1.1633, 1.2814, 1.3176**; best fits station 10
  (4.0 mm RMS), not station 5 (68.3 mm).
- Left chain 4, code station 2: **0.1992, 0.4975, 0.7264, 0.8787**; best fits station 13
  (5.5 mm), not station 2 (184.5 mm).
- Right chain 7, code station 14: **0.1511, 0.3273, 0.5057, 0.6557**; best fits station 2
  (4.5 mm), not station 14 (210.8 mm over its three nonblank rows).
- Right chain 8, discarded by code's rank zip after eight stations: upper-row values
  **0.0765, 0.1326, 0.1948** fit station 1 (2.3 mm). Models admit it, but name it 14.

Thus this is not just an off-by-one shift, station-0 inclusion, or transom convention. The
innermost curves independently fit station 14 on the left and station 1 on the right; station 0
was never scored or offered as a candidate. The double-ended boat's station 14 is a real scored
station, not a transom. Close-curve loss and chain duplication add local numbering shifts to the
larger half-assignment error. A simple swap alone would not account for all duplicated/missing
midship traces.

### Missing-cell map, extras, and measurement evidence

All omissions are at the lowest row. The protocol's risks correctly predicted shallow rejection,
close curves, and nominal rows without drawn waterlines. **The latter two do not produce missing
scored cells at the upper rows in these as-run tables**; they affect trace identity and fidelity.
A full table is not evidence that each cell comes from a distinct, correct curve.

| Waterline | Truth nonblank | Code missing stations | Each model repeat missing stations | Recorded evidence |
|---|---:|---|---|---|
| 1-6-0 | 12 | 6, 7, 8, 9 | 6, 7, 8 | All assigned chains lack this row; shallow rejections on both halves; models rename right chain 3 from 10 to 9, which fills 9 without tracing new ink |
| 2-3-0 | 14 | none | none | No drawn horizontal line; nominal row 7805 used; right chains 1 and 2 share one crossing |
| 3-0-0 | 14 | none | none | No drawn horizontal line; nominal row 7505 used; right chains 1/2 and 3/4 each share a crossing |
| 3-9-0 | 14 | none | none | No drawn horizontal line; nominal row 7205 used; right chains 0 and 1 share one crossing |

At 1-6-0 both halves locate row **8114**, 9 px below nominal 8105 (6.9 mm in height). The left
crossing at **904.9 px / 0.6895 m**, slope **+7.33**, and right crossing at **969.3 px / 0.7386 m**,
slope **−6.67**, are explicitly rejected as `shallow` (threshold magnitude 6). These lie near
the calibrated truth-offset queries for missing stations 6 and 7/8, respectively. That is
proximity evidence, not proof of their physical station identity: the calibrated halves are
already suspect. A single rejected crossing cannot establish separate traces for both 7 and 8.
Code station 9 is assigned right chain 2, which starts at 2-3-0; an accepted crossing at
**891.5 px / 0.6793 m** is on right chain 3 instead. Models rename that chain 9, filling the cell
by identity change rather than recovery of a lost crossing. No missing cell has truth offset
beyond the **1900 px** search limit. No missing cell has a recorded `double` classification;
`double` would in any event be an accepted station candidate, not a rejection.

Close curves cause **shared chain nodes**, not just large-width `double` records. On the right,
chains 1/2 share **1.253235 m at 2-3-0** and **1.336605 m at 3-0-0**; chains 0/1 share
**1.354613 m at 3-9-0**. More seriously, chains 3/4 share **1.310045 m at 3-0-0**.
Right chain 4 has two inferred links and breadths **0.525173, 1.070839, 1.310045, 1.278686 m**:
the third value is a local bulge from sharing the outer neighbour's crossing. This chain best
fits station 5 but only at 43.3 mm RMS, unlike the other well-separated fore-station fits near
5 mm. The measurement record supports loss of distinct curve paths in the close 5–9 region;
it does not prove which invisible stroke was merged at every row.

Extras are **station 1 / 1-6-0 = 0.104244 m** in every table, plus **station 14 / 1-6-0 =
0.151123 m** in code only. Those truth positions are blank, not failed scored cells. They are
consistent with the left station-14-like curve being named 1 and the right station-2-like curve
being named 14. Models move the right inner assignments and remove the second extra.

### Per-cell code error map and largest errors

Signed error is given minus truth, rounded to millimetres. `M` is missing; `E` is an extra cell
at a truth blank. The diagnostic script lists truth-present, cell-given, and signed error for
**all 56 positions in each of the seven tables**, plus the exact assignment gap and nearby
classified crossings for every missing cell. Model tables cannot be inferred from the code
error map alone; their final chain assignments are given above.

| Waterline / station | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-6-0 | E | +48 | +46 | +95 | +59 | M | M | M | M | +97 | +68 | +69 | +52 | E |
| 2-3-0 | +104 | +175 | +226 | +188 | +101 | +53 | +22 | −12 | +10 | +47 | +52 | +46 | +108 | +151 |
| 3-0-0 | +159 | +226 | +213 | +128 | +57 | +24 | +9 | −6 | +6 | +31 | +126 | +41 | +99 | +220 |
| 3-9-0 | +218 | +228 | +166 | +92 | +40 | +17 | +5 | 0 | −1 | +16 | +31 | +41 | +84 | +249 |

The largest code error is **station 14 / 3-9-0, +249.34 mm**: right chain 7 emits 0.655736 m
against station-14 truth 0.406400 m, although it fits station 2. The largest model error is
**station 2 / 3-9-0, +227.80 mm**: unchanged left chain 4 emits 0.878678 m against 0.650875 m,
although it fits station 13. Other large errors shared by all arms are **station 3 / 2-3-0,
+226.44 mm**, **station 2 / 3-0-0, +226.31 mm**, and **station 1 / 3-9-0, +218.45 mm**.
These are primarily wrong station identities, not a metre/foot scale failure. Models also make
**station 13 / 3-9-0, −218.98 mm** by renaming right chain 7 as 13. The shared-node bulge on right
chain 4 gives code station 11 / 3-0-0 **+125.77 mm**; models rename it 10 rather than correct the
trace. Upper-row completeness and zero fairness flags conceal these defects.

### Reproduce the diagnosis only / next development work

`benchmarks/bumble_bee/diagnose.py` loads the sheet with the frozen hash check, calls the same
measurement functions, and reconstructs tables from code rank and saved final `labels.json`.
It checks every reconstructed score field against the saved repeat, prints actual waterline
rows, per-chain truth fits and model assignments, classified crossings and shared nodes, then
per-cell records, missing evidence, extras, and largest errors. All reconstructed metrics match
the seven saved results. It never calls `run`, builds model questions, invokes a model, writes
run files, changes assignments using truth, or applies a new decision rule. Output goes only to
stdout; the local capture is temporary diagnostic work, not a new scored run.

```bash
PYTHONPATH=src:. .venv/bin/python -m benchmarks.bumble_bee.diagnose \
  --sheet /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/haer/master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif \
  --truth /private/tmp/claude-501/bumble-bee/truth_s2.json \
  --runs /private/tmp/claude-501/bumble-bee/runs
```

**What the reader would need — next development work, not changes to this round:**

1. Independent checks of body-plan side orientation and station labels before fixing candidate
   sets. Include double-ended hulls, station-0 exclusion, and both innermost stations in tests.
2. Retain distinct close-curve alternatives and record shared-node ambiguity rather than count
   duplicated paths as separate complete station measurements. Review the inferred-link bulge.
3. Support shallow intersections and sampling at nominal waterline heights without a drawn line;
   distinguish the drawn 1-ft grid and the 9-px row ambiguity from the table waterlines.
4. For a future protocol fixed before testing, use boat-scale error limits and explicit identity
   checks. Coverage, absolute RMS, and fairness alone did not detect this failure. Do not rescore
   this round under a new rule.

Resume point: diagnosis complete; retain the as-run decision and inputs. Any reader or calibration
development belongs to a later round with its own fixed protocol.
