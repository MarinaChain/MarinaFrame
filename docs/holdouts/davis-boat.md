# Holdout: 14'-3" Double Ended Davis Boat (round-bilge; fixed before any run)

Status: protocol fixed 2026-11-11 by lane E (data lane), before calibration and before any reader
run. No reader has run on this sheet. User decision (relayed by the PM): keep the Davis Boat as a
round-bilge holdout. It was first dropped as a hard-chine candidate (`docs/BODY_PLAN_CHINE.md`,
"Dropped: 14'-3" Double Ended Davis Boat").

## 1. Sheet

HAER WA-227, sheet 1 of 3, "Profile, body plan, table of offsets, and general notes", Center for
Wooden Boats, Seattle. Lines by photogrammetry (Jack Becker, Kyle Hunter), documented "as is".
Source: https://www.loc.gov/resource/hhh.wa0928.sheet (US Government work; LoC: no known
restrictions). Downloaded by the PM through a normal browser.

| File (not in git) | SHA-256 |
|---|---|
| `work/holdout/davis_boat/master-pnp-habshaer-wa-wa0900-wa0928-sheet-00001a.tif` (14400 x 9600, 1-bit, Group 4) | `728ea5130529fbd9945fd4045a42bc274085ad89d8cf5a9dea1415d2271b7465` |
| `work/holdout/davis_boat/truth.json` | `5bd7cd2824493218e16a4d932dd619c4e08262f2ba9abbe0889546e86e6ac3c6` |

Hull: double-ended, round bilge, planked; body plan with waterlines every 3 in (WL 3 to WL 24),
buttocks every 6 in and two diagonals. Printed scale 1 1/2" = 1'-0".

## 2. Truth (frozen)

Format: the `parse_truth` format of `benchmarks/deadrise_holdout/score.py` (`units`
ft-in-eighths, values as printed). Mechanical changes only, recorded in `notes`: stations listed
ascending ("0.5", "1", ..., "7", "7.5"; printed STA 7.5 ... STA 0.5, left to right) and printed
"WATERLINE n" (n inches above the baseline) renamed "WL <ft-in-eighths>" (for example WATERLINE 21
-> WL 1-9-0). A printed "-----" is null. The diagonal rows (with AFT RABBET and FWD RABBET
columns) and the BUTTOCK, KEEL and RABBET rows are kept in the file but not scored.

Two transcriptions: reading A (lane E, column crops) and reading B (a separate agent, row-strip
crops, blind to A). They agree on all 184 cells (heights, half-breadths and diagonals); `unsure`
is empty. Parse check with the pinned loader, stations 1 to 7, waterlines every 3 in: 56
waterline cells, **44 nonblank**; 14 point cells (sheer, rabbet). The half stations 0.5 and 7.5
are not whole numbers, so this loader leaves them out (as it leaves out TRANSOM).

## 3. Sides (double-ended: how bow and stern are told apart)

Both ends are pointed and the end profiles are almost the same, and there is no rudder, no
"FWD"/"AFT" label in the views and no sternpost label (both ends carry the same 5/16" stem and 1"
rabbet notes). Shape cannot decide. The clues used:

- **Reading 1 (lane E):** the table's diagonal rows have an extra column **"AFT RABBET" next to
  STA 7.5** (left) and **"FWD RABBET" next to STA 0.5** (right), so station 0 is forward and
  station 8 aft. Profile and plan: stations numbered 8 at the left end to 0 at the right end. Body
  plan labels: left half STA 5, 6, 7, 7.5; right half STA 0.5, 1, 2, 3, 4. So **left half =
  aftbody (5, 6, 7, 7.5), right half = forebody (0.5, 1, 2, 3, 4)**.
- **Reading 2 (separate agent, own crops, table values not read):** left half outermost to
  innermost STA 5 (about column 7250), 6 (7440), 7 (7830), 7.5 (8100); right half STA 4 (about
  9700), 3 (9650), 2 (9450), 1 (9150), 0.5 (8800); no curve labelled on both halves and none
  unlabelled. Profile: station 8 at the left (about column 2860), 0 at the right (about 11420).
  The "AFT RABBET" / "FWD RABBET" headers decide it: **left = aft, right = forward**. Approximate
  centreline column 8450, baseline row 3238 (for the calibrating agent to measure).
- The two readings agree. Stations 3 and 4 nearly coincide on the right half, and station 4 is
  the outermost there; the calibration must name them from the labels, not from rank alone.

## 4. Scorer and decision rule (existing round-bilge method)

Scored cells: the nonblank waterline half-breadths (`WL 0-3-0` to `WL 2-0-0`) at the numbered
stations 1 to 7, loaded with `benchmarks.deadrise_holdout.score.parse_truth` (waterline cells
only) and scored with the waterline harness scorer `benchmarks.balclutha.model_value.score` (as in
rounds 9 to 14). Point cells (sheer, rabbet) are reported, not gated.

Metrics and rule, copied from `docs/plans/2026-11-09-whole-vessel-scope.md` section 3.5.9 (as
`docs/holdouts/round14-pardon-me.md` section 7): cells given of the scored count (44), RMS and
maximum error, share within 0.05 m and 0.15 m, station identity errors, extra cells, median and
range over repeats. An arm **passes** if **every repeat gives at least 60 % of the scored cells and
the median RMS is at most 0.15 m** (a deterministic arm: its one run). Do not widen this rule after
results. `engineering_approved` stays false.

## 5. Readers (pinned at `origin/continue/v0.5` `87304c7`; to be updated before the run)

The round-bilge reader integration has not landed yet. **These pins will be updated, and this file
committed again, before the run, once the reader integration lands.** The run is valid only with
the files at the SHA-256 values recorded here at that time.

| File | SHA-256 at `87304c7` |
|---|---|
| `src/vessel_reconstruction/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` |
| `src/vessel_reconstruction/body_plan_crossings.py` | `8c0ffde62d5913cfbbba33fff8eecb7e08862439c9edc4063ec691e285c5987c` |
| `src/vessel_reconstruction/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` |
| `src/vessel_reconstruction/body_plan_polyline.py` | `14ab4e82386c1bd11c3626ccf58b7b8ba3ab7dee222ddb7d69c6067fc299494b` |
| `src/vessel_reconstruction/body_plan_reader_v2.py` | `61c6e834ed4df675b96cafd50fc4e77d811f85ef205354697cadb8eaa5a8174f` |
| `src/vessel_reconstruction/body_plan_chine_line.py` | `ef2bd68f4f9e1f65d185dbc8de1896c6383134b6df9c8558200bfd83bf239223` |
| `benchmarks/frozen_readers/v1/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` |
| `benchmarks/frozen_readers/v1/body_plan_crossings.py` | `c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97` |
| `benchmarks/frozen_readers/v1/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` |
| `benchmarks/balclutha/crossing_value.py` | `f5ab03b178508c1cf9232417c38d2888cc1fb94b07d519e830c9fb5c9df82536` |
| `benchmarks/balclutha/model_value.py` | `aa3786c262434e8451f7659e2885c2fecbd6b3a285c922113c93409d638a71e0` |
| `benchmarks/deadrise_holdout/score.py` | `1bc962218d25b86c6006a23c2e5567e241ad169cd430f2bdcb73a92793f58be1` |

**Amendment: integrated reader pins (lane I, 2026-11-11, before any run on this sheet).** The polyline reader
was chosen as the hard-chine reader (user decision), its station naming was fixed on the nine development sheets
(`c3cfb0a`; CALEB JONES 6 correct / 10 wrong -> 21 / 0 point cells, no sheet worse) and it was integrated as the
product entry point `body_plan_sides.read_side` (`c14de7d`); see `docs/plans/2026-11-11-polyline-integration.md`.
Reader v2 and the chine-line module moved from `src/` to `benchmarks/hard_chine/`. This is the pin update of step 2 for the reader integration; the pins above are replaced
by the pins below (at `c14de7d`); the run is valid only with these files at these SHA-256 values. No reader has
run on this sheet; this lane did not open its folder. For this round-bilge sheet the product reading is `body_plan_sides.read_side`; where the polyline reader declines a half it gives the crossing reader's rank table unchanged (shown on BUE GIRL, C.A. Thayer, Balclutha and BUMBLE BEE). The integration run showed
`body_plan_sides` equal to the benchmark product rule (`deadrise_holdout.score.polyline_table` and
`polyline_curves`) on all nine development sheets (tables and scores).

| File | SHA-256 | Change |
|---|---|---|
| `src/vessel_reconstruction/body_plan_sides.py` | `0f3279d3c5d36a90eb383c5332f5909667a1ebcbf8a98d889205e93b27afd163` | product entry point (new) |
| `src/vessel_reconstruction/body_plan_polyline.py` | `1b432ba917a0cea38717492c65a03cd0ef31e4dea6273b07d6909b97b4ae4606` | naming fix `c3cfb0a` |
| `src/vessel_reconstruction/body_plan_reader.py` | `cd5cbf77b11400250ca105f956a1ecbd623efaf924aa187003aeed514ee38a24` | lane B thresholds `14125aa` |
| `src/vessel_reconstruction/body_plan_crossings.py` | `40e9f6306eb2255079b1d978edf95d360709a39ebe4a96508dd4fce9565ee54c` | lane B thresholds `14125aa` |
| `src/vessel_reconstruction/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` | unchanged |
| `src/vessel_reconstruction/body_plan_intake.py` | `ded09b706f2c12d549941faf4a5687a9181383aeecd2d9a633d6952bcaf3ecfd` | calls `read_side` |
| `benchmarks/hard_chine/reader_v2.py` | `9f50aea5e831eb320d63d079097287b9ea29a7c25a099268913af74ea9e5d04d` | moved from src (comparison arm only; import path changed) |
| `benchmarks/hard_chine/chine_line.py` | `ef2bd68f4f9e1f65d185dbc8de1896c6383134b6df9c8558200bfd83bf239223` | moved from src, content unchanged |
| `benchmarks/frozen_readers/v1/body_plan_reader.py` | `327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11` | unchanged |
| `benchmarks/frozen_readers/v1/body_plan_crossings.py` | `c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97` | unchanged |
| `benchmarks/frozen_readers/v1/body_plan_identity.py` | `ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34` | unchanged |
| `benchmarks/deadrise_holdout/score.py` | `1bc962218d25b86c6006a23c2e5567e241ad169cd430f2bdcb73a92793f58be1` | unchanged |
| `benchmarks/ec_collier/point_score.py` | `b38bbda707c921f3d930cebf7ad37cb73e025a29af5e9dabac36a17755df2158` | unchanged |
| `benchmarks/balclutha/crossing_value.py` | `f5ab03b178508c1cf9232417c38d2888cc1fb94b07d519e830c9fb5c9df82536` | unchanged |
| `benchmarks/balclutha/model_value.py` | `aa3786c262434e8451f7659e2885c2fecbd6b3a285c922113c93409d638a71e0` | unchanged |
| `scripts/measure_deadrise_holdout.py` | `a31fc6854823fd76add2e3c6dbf2e91f8751cd324fed60c9d303f4c631f0e115` | reader v2 import path only |

**Amendment: calibration written truth-blind, before any run (lane L, 2026-11-11).** Step 1 of section 6.
Lane L did not open, list or hash `truth.json` or any other file in the folder except the sheet TIFF and
`SOURCE.md` (sections 2 and 3 of this file were read; they hold no cell values), and viewed the table of offsets only in whole-sheet overviews downsampled 16 times (digits
not legible); every lane L crop was at columns 6600 and above or rows 6300 and below. No reader, intake,
pipeline or scorer ran on the sheet. Values and how each was read are in the calibration file:

- Scale 600.0 px/ft: feet bar ticks at columns 8123-8125, 8723-8725, 9323-9325 (0, 1, 2 ft); checked by the
  profile station lines 2876 (8) to 11426 (0), (10357 - 3945) / 6 = 1068.67 px = 21 3/8" (599.95 px/ft).
- Centreline column 8450.0 (keel / stem lines symmetric at +-19 and +-50 px); base line row 3243.0 (dashed,
  one row, zero slope).
- Measuring rows: the drawn WL 3 to WL 24 at rows 3093, 2943, 2793, 2643, 2493, 2343, 2193, 2043, labels
  `0-3-0` to `2-0-0`. Buttock grid columns 8150 / 7850 / 7550 / 7250 (left) and 8750 / 9050 / 9350 / 9650.
- Sides: left = aft, outer first 5, 6, 7, 7.5; right = fore, outer first 4, 3, 2, 1, 0.5 (names from the
  "STA n" labels; 4 is outside 3 at every waterline). The half stations carry placeholders 1075 and 1005
  and are never scored; scored stations 1 to 7. Bow side from the drawing alone is a convention (station 0
  at the right end of the profile and conventionally forward; forebody conventionally right of the
  body-plan centreline); it agrees with section 3 and changes no cell.
- Reach `MAX_OFFSET_PX` 1270 (outermost hull ink 1250 right at station 4, 1200 left at station 5).

**Second check (independent, truth-blind).** A separate agent with its own crops, not given these values,
measured: scale 600 px/ft (ticks 8124 / 8724 / 9324; station lines 2876, 3410, 3945, then 1068-1069 px
apart to 11426), centreline 8450, base line 3243 (flat), WL 3 to WL 24 at rows 3093 to 2043 every 150 px,
right half 4, 3, 2, 1, 0.5 and left half 5, 6, 7, 7.5 from the outside in, outermost ink +1252 / about
-1196 to -1199 px. Bow: "probably right (low confidence)", by the same station-0 convention; it found no
drawing evidence that decides it. **Agreement** on scale, axes, waterlines, station naming and reach; the
bow side is agreed but rests on convention in both readings (the table headers of section 3 decide it).
Disclosure: one of the checker's crops (rows 3500 to 9000, columns 2600 to 4600) caught the bottom row of
the table of offsets, which runs below row 3450, at a legible scale; the checker reports that it did not
use those digits, and no value in the calibration comes from the checker. The checker develops no reader
and did not see `truth.json`.

| File | SHA-256 |
|---|---|
| `benchmarks/davis_boat/holdout_value.py` | `e9f416bf1730883b28f3487f8278c797ecc9ae1ae6bf0f3de3b506766735132b` |
| `benchmarks/davis_boat/__init__.py` (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/test_holdout_calibrations.py` (synthetic, no sheet, no truth) | `534852126cf200cc11ad072b1907fc15d18beecfb086356816d13ec14f14a3f2` |

The round-bilge run script is not written yet; it must read this calibration unchanged.

## 6. Order of work

1. **Calibration** (`benchmarks/davis_boat/holdout_value.py`) by an agent that has not seen
   `truth.json`, the table crops or these transcriptions (lane E read the table, so it does not
   calibrate). Scale from the printed bar, checked against the 21 3/8" station spacing; measuring
   rows on the drawn waterlines WL 3 to WL 24; sides and station order as section 3, with the half
   stations listed but not scored. `TRUTH_SHA256` as section 1.
2. **Pin update** (section 5) after the reader integration lands; commit before the run.
3. **One run per arm**, no tuning; outputs and their SHA-256 values kept in `work/`. A failure is
   reported with its causes; after the run the sheet is a development case.

Disclosure: lane E saw this sheet's table in a whole-sheet overview while checking the hull form
for the hard-chine lane, before this protocol. Lane E develops no reader.
