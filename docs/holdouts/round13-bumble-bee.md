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
