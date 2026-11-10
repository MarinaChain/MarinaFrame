# Hull fairing: one fair surface through all stations

Status: measured (step 4), 2026-11-10. Fairing stays off by default (section 6.6). Branch `feature/hull-fairing` (from `continue/v0.5` at ceb2ee5).
`engineering_approved` stays false for every result here. Development data only
(`work/factory-3view`, BUE GIRL development truth); `work/factory-sealed-*` is never opened.

## 1. Goal

The current hull (`geometry.build_hull`) goes through every station section exactly (1 mm CAD
bound) and joins neighbouring stations with ruled panels. Each station is used alone, so one bad
cell or one misread station bends the hull there (BUE GIRL live run, docs/AUTO_CALIBRATION.md 9.4:
one cell moved 0.2 m by the hull-bottom step, 32.6 mm RMS; 2.3 mm without that cell).

A naval architect fairs the lines: one smooth surface is fitted to all the evidence at once, and a
point that does not agree with its neighbours is questioned, not followed. This work does the same
in code: a new module `src/vessel_reconstruction/fairing.py` fits one fair hull surface to all
stations at once and gives the existing builder sections taken from that surface. It is behind a
setting (`MARINAFRAME_HULL_FAIRING=1`), off by default, until the measurements below justify it.

The frozen gates do not change: 2 % RMS of half-beam, 5 % in-range volume.

## 2. Method (summary; details in the module docstring)

- Surface (as built, v3; section 6.1 has the two earlier forms). Each section is a half-breadth
  curve y(z). The faired surface is y(u, z): along every true waterline (one at every source
  height) a cubic smoothing spline over the station index u through the stations that reach that
  height. Keel and top heights stay as read from the profile.
- Fairness penalty. Second-derivative energy along x (the smoothing spline minimises
  sum w (y - f)^2 + lambda * integral f''^2). Knots are at the station positions, which is where
  the minimiser of that energy has its knots (natural cubic spline). lambda comes from a fairing
  length: the distance over which the fit averages, a fixed fraction of the hull length.
- Weights by source label: traced > read > repaired > interpolated > ai_inferred/guessed.
- Constraints: only the stations from the first to the last measured (traced or read) station
  are faired; the end stations outside them (stem and transom, from the profile and plan) are
  kept; a faired station that is a hull terminal is held; each station's keel and deck-edge points
  have a strong weight; points on the centreline (y = 0) stay on it.
- Robust weights: Huber, judged by how far a value lies outside the range of its two neighbouring
  stations on the same waterline (not by the fit residual, see 6.1).
- Explainable: every output section keeps its id, x and source label; the input points are kept in
  the section's `fairing` record with the distance each moved; a point moved more than its label's
  tolerance gives a check item with the distance.
- Build: sections sampled from the faired surface go to the same builder, STEP, GLB and
  hydrostatics. A fit or build failure falls back to the current hull with a check item.

## 3. Metrics

All metrics come from REPLAY: the recorded section inputs (`extracted_sections.json`) of stored
builds are rebuilt with the current code, without and with fairing, and scored with the frozen
scorer. No live model runs.

Replay set:

- Primary: the delivered build of each L0 and L1 development case of the latest live rounds
  (`work/round-3view-L{0,1}-sonnet-4f92e9f`, the STEP that `scripts/round_digest.py` scores):
  10 cases.
- Secondary: every first-hull and revision build (`first-*`, `r0001-*`) of the same cases, both
  readings: all stored readings of that round.
- BUE GIRL: the delivered build of the live app run `work/autocal-live-6/bue_girl` (12 `read`
  stations), scored at the 39 truth cells of `/private/tmp/claude-501/bue-girl/truth_s2.json`
  (development truth now), by the method of `benchmarks/auto_calibration/live_score.py`.

### 3.1 Gate metrics, before and after

- RMS % of half-beam (`truth.score_model`, `half_breadth_main`) and in-range volume error, per
  case, without and with fairing. "Before" must equal the recorded score (replay check).
- BUE GIRL: RMS m, max m and cells within 0.05 m.

### 3.2 Fairness metrics (on the sections given to the builder, before and after)

- Per waterline (20 heights evenly spaced between the lowest keel and the highest top, excluding
  the end rows): half-breadth at every station; second divided differences over x; inflection count
  = sign changes of that second difference, ignoring values whose magnitude is below a noise floor
  (0.2 % of half-beam per station spacing squared).
- Per section: half-breadth at 21 heights evenly spaced between its keel and top (a step of 5 %
  of its height, about one waterline spacing, so pixel noise of a trace is not counted); inflection
  count = sign changes of the plain second difference above 0.2 % of half-beam.
- Max curvature jump: the largest change of the second divided difference between neighbouring
  stations along a waterline, as a fraction of half-beam per station spacing squared.

### 3.3 Fidelity: how far the fairing moves each input point

For every input point, the distance to its faired point (same section, same normalized height),
reported per source label: max, 95th percentile, share within tolerance. Tolerances:

| Label | Tolerance |
|---|---|
| traced, read | 1 % of half-beam (half the RMS gate) |
| repaired, interpolated, ai_inferred, guessed | 5 % of half-beam |

### 3.4 Robustness: one injected bad cell

On each primary case, one traced station near midships and one near the quarter length get a bad
cell: +0.2 m added at mid-height, tapering linearly to zero over +-5 % of the section height (one
waterline spacing of a typical offset table). Also reported: +5 % of half-beam, and a whole
traced station shifted outwards by 5 % of half-beam (a misread station). Measure: how far the built
section at that station moves at that height, against the unperturbed build of the same mode. The
current build moves by the full injected amount (it goes through every point).

## 4. Targets (fixed before any result)

| # | Target |
|---|---|
| G1 | No primary case worse by more than 0.10 RMS points; mean RMS over the 10 cases not higher |
| G2 | No gate pass lost; no in-range volume error worse by more than 0.5 points |
| G3 | BUE GIRL: RMS at the 38 built cells <= 10 mm (from 32.6 mm); max <= 0.05 m |
| F1 | Total waterline inflection count lower on every primary case |
| F2 | Max curvature jump lower on every primary case |
| D1 | traced/read points: >= 95 % within 1 % of half-beam on every case; every point outside it has a check item |
| R1 | Injected +0.2 m cell: the faired hull moves <= 25 % of it (<= 0.05 m) on every case |
| R2 | Misread station (+5 % half-beam, whole station): faired hull moves <= 60 % of it |

Default parameters are set in the module before the replay and reported with it. A sensitivity
table (fairing length 0.025, 0.05, 0.1 of hull length) is reported; a parameter change after the
results is tuning on development data and is said so. Decision rule: make fairing the default only
if G1, G2 and R1 hold; if some cases are worse, find the cause or keep fairing off for that kind
of input, and say so.

## 5. Steps (one commit each, with tests)

1. This plan.
2. `fairing.py`: the robust fair fit, labels, constraints, check items, fairness metrics. Unit
   tests on synthetic hulls (a bad cell, a misread station, a fair hull kept within tolerance).
3. Build: the setting in the pipeline's hull call site (`pipeline.py`, draft and strict runs with
   single-region sections), the fallback, the setting passed to the worker. Test: a run with the
   setting builds a valid STEP with faired sections; a fit failure falls back with a check item.
4. Measure: `benchmarks/hull_fairing/replay.py`; tables in section 6; images in
   `work/hull-fairing/` (git-ignored).

Resume point: the last committed step. Outputs stay outside the repository.

## 6. Results

Replay: `benchmarks/hull_fairing/replay.py` (outputs in `work/hull-fairing/`, git-ignored),
tables by `benchmarks/hull_fairing/summary.py`. "Before" is the current builder on the recorded
sections; it reproduces the recorded scores exactly (for example dtmb5415-L0 8.0866 against the
digest's 8.09). Development truth only.

### 6.1 What was tried (in order, all on the same replay)

| Version | Change | Mean RMS % (10 cases) | Worst case | Why it failed or was kept |
|---|---|---|---|---|
| v1 | rows at normalized height t, z0(x) and z1(x) faired, Huber on fit residuals, x in metres | 4.35 -> 10.46 | 00679-L1 5.47 -> 14.60 | keel heights of the end stations (0 -> 6.4 m in one 2 m step) were spread into the body; traced points moved by metres |
| v2 | rows at normalized arc length, (y, z) fitted, u = station index | not replayed | series60-L0 s5 moved 2.2 m | flat-bottom traces of different extent do not line up at one arc length |
| (probe) | t rows, y only, fit-residual Huber | not replayed | series60-L0 s5 6.30 -> 6.46 m | a down-weighted midbody station let the spline overshoot the fair shoulder; weights are now judged against the neighbours |
| v3a | t rows, y only, fitted span = measured stations, neighbour-range weights, length 0.5 | 4.35 -> 4.45 | 08158-L0 0.76 -> 1.69; BUE GIRL 33 -> 80 mm | at one t the BUE GIRL bottom cells of neighbouring stations lie at different heights |
| v3b | waterlines at true height, otherwise as v3a | 4.35 -> 4.61 | 09867-L1 1.00 -> 2.37 (pass lost) | smoothing over half a station flattens real shoulders of fine bows |
| v3b + rejection | length 0.2, no weight beyond 2 % of half-beam outside the neighbours | 4.35 -> 4.36 | 09867-L0 3.25 -> 4.27 | fair traced points moved up to 4.4 m where the hull changes faster than the stations |
| **v3 (kept)** | as v3b, length **0.2** station, Huber only | **4.35 -> 4.20** | none worse by > 0.01 | gates; robustness fails (6.4) |

The fairing length 0.2 and dropping the rejection were chosen on this development replay after
the targets were fixed: that is tuning on development data. No sealed data was opened.

### 6.2 Gate metrics, delivered build of each case (v3, length 0.2)

| Case | RMS % before | after | Volume % before | after |
|---|---|---|---|---|
| dtmb5415-L0 | 8.09 | 8.09 | +1.0 | +1.0 |
| series60-L0 | 1.38 pass | 1.29 pass | +1.1 | +1.0 |
| shipd-1-00679-L0 | 4.05 | 3.85 | +0.0 | -0.0 |
| shipd-1-08158-L0 | 0.76 pass | 0.72 pass | -2.1 | -2.0 |
| shipd-1-09867-L0 | 3.25 | 2.51 | +1.8 | +1.8 |
| dtmb5415-L1 | 14.34 | 14.19 | +13.2 | +13.2 |
| series60-L1 | 3.49 | 3.33 | -0.5 | -0.5 |
| shipd-1-00679-L1 | 5.47 | 5.44 | -0.9 | -0.9 |
| shipd-1-08158-L1 | 1.64 pass | 1.63 pass | -3.1 | -3.1 |
| shipd-1-09867-L1 | 1.00 pass | 0.98 pass | +2.2 | +2.1 |
| mean | 4.35 | 4.20 | | passes 4 -> 4 |

BUE GIRL (12 `read` stations, 38 built cells): RMS 32.6 -> 34.3 mm, max 0.201 -> 0.211 m, within
0.05 m 97 % -> 97 %. G3 not met. Cause: the outlier (station 10, 2-6-0, +0.20 m) is not a lone
bad cell. Below the lowest read cell the first hull's bottom handling draws a straight line to
the keel at stations 10 and 11 alike (`work/hull-fairing/bue-9-11.png`), so on that waterline the
neighbours are as wrong as the cell and the truth (0.286 m) lies outside their range. Fairing
cannot repair evidence that the neighbours share; the fix belongs in the bottom handling.

All stored builds (first hulls of both readings and revisions, 4f92e9f rounds): section 6.5.

### 6.3 Fairness and fidelity (delivered builds)

| Case | Waterline inflections | Section inflections | Max curvature jump | traced/read within 1 % | max move m | check items |
|---|---|---|---|---|---|---|
| dtmb5415-L0 | 38 -> 36 | 21 -> 21 | 1.73 -> 1.73 | 100.0 % | 0.040 | 0 |
| series60-L0 | 92 -> 81 | 32 -> 30 | 3.89 -> 3.89 | 99.5 % | 0.673 | 1 |
| 00679-L0 | 43 -> 51 | 41 -> 41 | 0.45 -> 0.45 | 99.0 % | 1.257 | 2 |
| 08158-L0 | 50 -> 54 | 42 -> 42 | 3.67 -> 3.66 | 100.0 % | 0.048 | 0 |
| 09867-L0 | 87 -> 77 | 25 -> 25 | 1.33 -> 1.33 | 95.0 % | 0.465 | 2 |
| dtmb5415-L1 | 48 -> 48 | 31 -> 33 | 3.79 -> 3.79 | 90.1 % | 0.394 | 3 |
| series60-L1 | 94 -> 94 | 41 -> 41 | 4.05 -> 4.05 | 98.0 % | 0.330 | 2 |
| 00679-L1 | 63 -> 61 | 27 -> 27 | 0.68 -> 0.68 | 100.0 % | 0.047 | 0 |
| 08158-L1 | 52 -> 52 | 66 -> 66 | 3.74 -> 3.74 | 100.0 % | 0.052 | 0 |
| 09867-L1 | 95 -> 95 | 18 -> 17 | 0.57 -> 0.57 | 100.0 % | 0.038 | 0 |
| BUE GIRL | 23 -> 23 | 28 -> 29 | 0.75 -> 0.74 | 98.8 % | 0.056 | 4 |

F1 (fewer waterline inflections on every case) not met: lower on 5, equal on 4, higher on 2
(00679-L0, 08158-L0). F2 (lower max curvature jump) not met: the largest jumps sit at the kept end
stations, which fairing does not move. D1 met on 9 of 11 (dtmb5415-L1 90.1 %); every point
outside its tolerance has a check item. The large moves (up to 1.26 m) are points of trace
artefacts (flat-bottom ink near the baseline, a station edge beside the next station's curve) that
lie far outside their neighbours; those are the moves fairing is for.

### 6.4 Robustness: injected bad cell (R1, R2)

22 injections per kind (two traced stations per case, 11 cases), faired move / injected:

| Kind | median | max |
|---|---|---|
| cell +0.2 m | 0.97 | 1.00 |
| cell +5 % half-beam | 0.95 | 1.00 |
| station +5 % half-beam | 0.95 | 1.00 |

The current build follows each by 1.00. R1 (<= 0.25) and R2 (<= 0.60) are not met. Exception:
BUE GIRL, where 0.2 m is 16 % of the half-beam: 0.77 at most.

Why. The detector must tell a bad value from the hull's own change between stations. A cubic
through the two stations on each side predicts a station's half-breadth with a median error of
0.5-3.7 % of half-beam and a 90th percentile of 2-10 % on these drawings (`work/hull-fairing/loo.py`):
at a ten-station spacing the hull changes by as much between stations as the bad cells to be
found (0.2 m is 3 % of these half-beams). A value inside its neighbours' range cannot be
recognised; a strong smoothing or a rejection rule that would catch it also moves fair traced
points (6.1: v3b, rejection). Fairing along the stations alone cannot meet R1 on this data.

### 6.5 All stored builds

All 21 stored first-hull and revision builds of the ten cases (both readings, 4f92e9f rounds):
mean RMS 6.52 -> 6.42 %; 7 builds better by more than 0.1 point (best -0.74), none worse by more
than 0.005; gate passes 7 -> 7.

### 6.6 Recommendation

Keep fairing off by default. With the kept settings it is safe (no case worse by more than
0.01 points, no pass lost, mean 4.35 -> 4.20 % RMS, gains on 09867-L0, 00679-L0 and series60-L1)
and its check items name real trace artefacts, but it does not do what it was built for: one bad
cell or misread station still bends the hull (R1, R2 fail), and the BUE GIRL outlier is shared
evidence, not a lone cell (G3 fails). Next steps that would address the causes: (1) fix the
first hull's bottom handling below the lowest read cell (BUE GIRL); (2) detect bad cells along
the section (dense in height) and against the profile and plan views, which are independent of
the neighbouring stations; (3) more stations (half stations at the ends) make the cross-station
check sharper.

## 7. Cross-view cell detector: protocol fixed before results

Date: 2026-11-10. No detector replay results were inspected before this protocol.
The detector is a report-only check, not a new acceptance gate. Fairing stays off.
Frozen body-plan readers, draft fit, best-of-N selection and the 2 %/5 % gates do not change.

### 7.1 Replay population and denominators

Replay the delivered build and every stored first/revision build of the ten L0/L1
4f92e9f development cases listed in section 3. Report delivered and all-build results
separately, since revisions are correlated. Include BUE GIRL's stored reader sections
as a separate case. No live model calls, new images, CAD builds or sealed holdouts.
Use only stored sections and their source sheet/calibration for independent view scans.
No truth geometry enters the detector. Missing inputs fail the replay, not disappear.

A cell is a point in a measured (`read` or `traced`) section, in source curve order.
The unchanged-reading alarm rate is flagged cells / all measured cells. It is a
**conservative false-alarm proxy**, not a truth-labelled false-positive rate: unchanged
readings can contain real errors. Also report alarms / cells with usable independent
view evidence and coverage for plan, profile and section-neighbour checks. Missing or
ambiguous evidence is not agreement. Report each case and pooled counts, not only a mean.

Inject one fault at a time into the same stored geometry. Select the measured stations
nearest 25 % and 50 % of the measured x span (distinct ids; deterministic x/id tie break).
At each selected station inject +0.1 m and +0.2 m at mid-height, with the section 3.4
triangular taper over +/-5 % of section height; insert the peak vertex if absent.
Keep centreline points fixed. Separately increase every positive half-breadth in that
station by 5 % of the unchanged measured half-beam (section 3.4 convention).
Cell detection means the peak cell is flagged; station detection means at least one
changed cell is flagged. Report raw detection and **new** detection (not already flagged
at that location in the unchanged input). Count missing-view trials as misses in the
all-trial rate; also show the covered-only rate. Report unchanged-cell collateral alarms.

### 7.2 Targets and fixed decision rule

| Metric | Target fixed before replay |
|---|---|
| +0.1 m peak-cell detection | >= 80 % of trials |
| +0.2 m peak-cell detection | >= 90 % of trials |
| Whole station +5 % half-beam detection | >= 90 % of trials |
| Unchanged-reading alarm proxy | <= 1 % pooled, <= 2 % on every delivered case and BUE GIRL |
| Independent plan/profile coverage | >= 90 % of measured cells on every delivered case |

Both raw and new detection must meet the detection targets. These are engineering
aspirations, not relaxed gates. Use in fairing by default only after all targets hold
and a separate weighted-fit replay meets G1/G2. This task makes no default-weight change.
Failure or insufficient view coverage means keep report-only; do not tune after seeing
results without explicitly recording a new development experiment.

### 7.3 Design, constants and execution checkpoints

Use a separate `cross_view_outliers.py` module. Reuse the existing read-only reference
view calibration and ink-scan primitives, without changing the selection score. Compare
each cell with plan ink at its station x; this is nearest-curve evidence, not proof of
waterline identity. Mark competing runs ambiguous. Profile checks are one-sided limits
(below keel, above deck, aft of transom, forward of stem), not an interior shape predictor.
For the section check, use distance to the chord between bracketing neighbours at a
5 %-height scale, not immediate dense trace pixels; this matches the injected-cell scale.
Do not extrapolate section neighbours at curve ends.

Initial tolerance: max(0.02 m, 0.005 * unchanged half-beam, 3 source pixels in metres).
The 20 mm floor avoids sub-centimetre drawing noise; 0.5 % of half-beam is one quarter
of the RMS gate; three pixels allow line thickness and scan/calibration noise. Flag
when any usable independent-view distance exceeds tolerance, or the section chord
distance exceeds twice it (curvature needs more allowance). Report all distances,
tolerances, ambiguity and missing checks per cell, with one check item per flagged cell.
Explain additional constants at their definitions. Never infer an independent view
from the sections being checked. Report-only avoids removing real chines or shoulders.

Implementation checkpoints (commit each):
1. Commit this protocol after existing fairing unit tests and a diff check.
2. Write failing synthetic tests, implement the pure detector and replay input adapter,
   test exact/shifted curves, profile limits, neighbours, missing/ambiguous views,
   invalid inputs and input immutability. Commit source and tests.
3. Run `benchmarks/hull_fairing/replay_outliers.py` over the fixed population, write
   machine-readable per-run counts under git-ignored `work/` and tables here. Test replay accounting and
   repeatability, run related regression tests, review the diff, then commit results.

Resume at the first checkpoint absent from `git log`. Run Python with
`PYTHONPATH=src:. .venv/bin/python`. All shell commands start `set -o pipefail`;
never push, merge, switch branches or pipe git. No files under `work/factory-sealed-*`
may be opened. Optional fit down-weighting is deferred, not silently enabled.

### 7.4 Replay results (2026-11-10)

Run from this worktree:

```bash
set -o pipefail
PYTHONPATH=src:. .venv/bin/python -m benchmarks.hull_fairing.replay_outliers
```

The script writes per-run derived data to `work/cross-view-outliers.json`
(git-ignored, not committed). `--work` selects the development input root;
`--output` selects the report path. The report contains baseline check items with
distances, input hashes, reference calibrations, per-trial counts and pooled rates.
No detector constants were tuned after this replay. No truth, CAD build, new model
reading, rendered image or sealed holdout was used.

Population: 10 delivered builds, 21 stored first/revision builds (including those
10), and the BUE GIRL frozen reader curves **before** bottom/deck continuation.
One stored build, `shipd-1-09867-3v-L0/first-1041bae1a618`, contains only
`ai_inferred`/`interpolated` sections. It has no eligible measured cells. Its six
planned trials are explicitly unavailable and remain misses in the all-build
trial denominator; its unchanged alarm rate is undefined, not zero. No input
files were missing. Revisions are correlated, so the all-build set is not an
independent validation set.

#### Detection

Each entry is raw / newly detected, with the common trial denominator. A new
alarm must be absent at the same location in the paired unchanged geometry;
when a peak vertex is inserted, it is inserted in both runs. Missing independent
views count as misses, as fixed in section 7.1.

| Population | +0.1 m cell | +0.2 m cell | Station +5 % half-beam |
|---|---|---|---|
| Delivered (20 trials per kind) | 3/20 / 0/20 (15 % / 0 %) | 1/20 / 1/20 (5 % / 5 %) | 20/20 / 20/20 (100 % / 100 %) |
| All stored builds (42 per kind) | 7/42 / 1/42 (16.67 % / 2.38 %) | 3/42 / 3/42 (7.14 % / 7.14 %) | 40/42 / 40/42 (95.24 % / 95.24 %) |
| BUE GIRL reader (2 per kind) | 0/2 / 0/2 | 0/2 / 0/2 | 0/2 / 0/2 |

All delivered trials have some independent evidence. The all-build covered-only
rates (40 covered trials per kind) are 17.5 % raw / 2.5 % new for +0.1 m,
7.5 % / 7.5 % for +0.2 m, and 100 % / 100 % for station faults.
BUE GIRL has no usable reference plan/profile from the existing calibration
helper, so its covered-only rates are undefined. Its section-only check flags
both injected cell peaks for each amplitude (2/2 raw and new), but no station
fault (0/2). These section-only flags do not count as cross-view detections.

Per delivered case below, entries are raw/new counts out of two trials. Every
case detects both station faults, with two new alarms.

| Case | +0.1 m | +0.2 m | Station +5 % |
|---|---|---|---|
| dtmb5415-L0 | 0/0 | 0/0 | 2/2 |
| series60-L0 | 0/0 | 0/0 | 2/2 |
| 00679-L0 | 0/0 | 0/0 | 2/2 |
| 08158-L0 | 1/0 | 0/0 | 2/2 |
| 09867-L0 | 0/0 | 0/0 | 2/2 |
| dtmb5415-L1 | 1/0 | 0/0 | 2/2 |
| series60-L1 | 0/0 | 0/0 | 2/2 |
| 00679-L1 | 0/0 | 1/1 | 2/2 |
| 08158-L1 | 1/0 | 0/0 | 2/2 |
| 09867-L1 | 0/0 | 0/0 | 2/2 |

#### Unchanged-reading alarms and coverage

Coverage is the share of measured cells with a usable plan scan, at least one
profile limit, or a bracketing section chord. A usable profile limit does **not**
mean that all four limits are present or that profile can predict interior breadth.

| Case | Alarms / measured cells | Alarm proxy | Plan coverage | Profile coverage | Section coverage |
|---|---|---|---|---|---|
| dtmb5415-L0 | 562/1207 | 46.56 % | 77.1 % | 100 % | 88.1 % |
| series60-L0 | 207/1190 | 17.39 % | 60.3 % | 100 % | 87.9 % |
| 00679-L0 | 116/837 | 13.86 % | 61.3 % | 100 % | 87.3 % |
| 08158-L0 | 372/659 | 56.45 % | 92.7 % | 100 % | 88.3 % |
| 09867-L0 | 486/1104 | 44.02 % | 93.3 % | 100 % | 87.2 % |
| dtmb5415-L1 | 440/934 | 47.11 % | 75.9 % | 100 % | 87.7 % |
| series60-L1 | 215/938 | 22.92 % | 77.2 % | 100 % | 87.1 % |
| 00679-L1 | 109/845 | 12.90 % | 68.0 % | 100 % | 87.1 % |
| 08158-L1 | 710/1098 | 64.66 % | 93.0 % | 100 % | 87.3 % |
| 09867-L1 | 484/1111 | 43.56 % | 95.0 % | 100 % | 86.9 % |
| BUE GIRL reader | 17/1391 | 1.22 % | 0 % | 0 % | 89.1 % |
| Delivered pooled | 3701/9923 | **37.30 %** | | | |
| All stored pooled | 7693/19920 | **38.62 %** | | | |

For delivered and eligible stored builds, every measured cell has at least one
profile limit. Their covered-cell alarm rates therefore equal their all-cell
rates. BUE GIRL has no independently covered cells, so that rate is undefined.
The alarm proxy is not a truth-labelled false-positive rate; even so, its high
value fails the fixed <=1 % pooled and <=2 % per-delivered-case targets.

New alarms on unchanged collateral cells: zero for all development-build trials
(+0.1 m: 0/39307 cell-trial observations; +0.2 m: 0/39307; station: 0/34265).
For BUE GIRL they are 3/2758 (0.11 %), 13/2758 (0.47 %), and 0/2544,
respectively. These denominators repeat unchanged cells across trials; they are
not counts of distinct cells.

### 7.5 Recommendation and limits

**Keep report-only; do not use this detector to down-weight fairing by default.
Keep fairing off by default.** Whole-station detection meets its target, but both
cell-detection targets and the unchanged-reading alarm target fail. Nominal
profile coverage meets the delivered-case coverage target; plan-only coverage
is below 90 % in six delivered cases, and BUE GIRL has no independent coverage.
No weighted-fit replay was run, so G1/G2 are not established for detector weights.

The current nearest-plan-ink check is not a labelled waterline-curve matcher.
At a height not drawn in plan, even a correct section point can be far from the
nearest drawn waterline; after an injection it can move closer to another line.
Thus larger faults need not give more alarms (15 % raw at +0.1 m versus 5 % at
+0.2 m). Profile bounds do not constrain an interior half-breadth, and a short
chord can preserve a bump when the section is steep. Outer profile ink can also
include non-hull marks. These are method limits, not evidence that the unchanged
readings are all wrong. Do not use the reported coverage as proof of correct
waterline identity or calibrated hull-limit identity.

Before automatic fit weighting, identify each plan waterline independently and
compare only cells at that height (or a justified interpolation between labelled
curves), validate hull-only profile limits, and support BUE GIRL's reference
frame. Then preregister a new experiment and repeat the full paired replay and
weighted-fit G1/G2 checks. No reader, draft-fit selection, default or gate changes
are justified by this result.

Verification: a second full replay produced byte-identical JSON (`cmp` passed).
The non-CAD Python suite passed: **1467 passed, 45 deselected**, with five SWIG
import deprecation warnings. This includes detector and replay-accounting tests.
CAD and detector-weighted fit tests were not run; no geometry or fit integration
was changed. Per-run JSON and logs remain under ignored `work/`.

## 8. Three-view surface: protocol fixed before results

Date: 2026-11-10, branch `feature/three-view-fairing`. This section and the
machine-readable `benchmarks/hull_fairing/three_view_protocol.json` are committed
before collecting new evidence or running new fits. No live model calls, images,
sealed factory inputs, reader edits, selection edits or gate edits are part of this work.

### 8.1 Fixed fit/check split

The fit half is the five **L0** cases in the 4f92e9f round: dtmb5415, series60,
shipd-1-00679, shipd-1-08158 and shipd-1-09867 (full ids in the JSON). The check
half is the same five **L1** cases. Every stored first/revision build follows its
case, including both readings. No reading can cross the split. BUE GIRL's stored
reader output is an additional check case. This is a paired degradation check;
it is not a hull-disjoint test and all these cases have earlier development results.
Report delivered builds and all stored builds separately; revisions are correlated.
No fit choices may use L1 or BUE GIRL results, including injection results.

### 8.2 Metrics and fixed targets

Use the unchanged section 6 replay scorer and development truth. Report per case
and per half: gate RMS % of half-beam, signed in-range volume error %, gate passes,
waterline/section inflections and maximum curvature jump. Report both the current
builder and the station-only fairer against the new surface. Also report BUE GIRL
at the stored reader cells **before bottom/deck continuation**, RMS m, maximum m,
number of scored cells and share within 0.05 m. Keep unavailable cells visible.

At the measured stations nearest 25 % and 50 % of the measured span (ties by x,
then id), inject each of: one +0.1 m cell, one +0.2 m cell (linear taper to zero
at +/-5 % section height), and one whole station +5 % of the unperturbed measured
half-beam. Centreline points stay zero. Use a paired zero-injection baseline with
the same inserted midpoint. **Freeze the other two views and all scales/weights**
for each paired test. Report signed and absolute follow share, median and maximum,
and off-target movement. Missing fits remain explicit failed trials.

For each view and source label, report point count, median, p95 and maximum
Euclidean movement to the fitted surface at the same x and height (profile:
projected x/z). Include the movement of hard boundaries. Report coverage, ambiguous
points, and fit/build failures. Never call inferred or ambiguous points traced.

| Id | Fixed target, applied separately to fit and check halves |
|---|---|
| T1 | Delivered mean RMS improves by at least 0.10 points; no case regresses by more than 0.10 points |
| T2 | No delivered gate pass lost; no absolute in-range volume error increases by more than 0.5 points |
| T3 | Each +0.1 m and +0.2 m trial follows at most 25 %; each whole-station trial at most 60 % (absolute share) |
| T4 | In each available view, at least 95 % of traced/read points stay within 1 % of unperturbed half-beam per case; report every excess as a check item |
| T5 | BUE GIRL reader output RMS <= 0.01 m, maximum <= 0.05 m, with no lost scored cells |

All-build metrics are secondary. Fewer inflections and curvature jumps are desired
and reported; they do not replace T1-T3. Switch fairing on by default only if the
**check** half meets T1-T3, every planned case builds, and no BUE GIRL regression
or hidden coverage loss occurs. Otherwise retain the off-by-default setting.

### 8.3 Data and fit design

Reuse `draft_fit.reference_views` for the reference frame and `view_measure` ink
scans. Sample plan waterlines and the deck line between stations as well as at
stations. Waterline height labels come from the profile grid. Matching uses the
stored hull as a search prediction only; competing/merged crossings are labelled
`repaired` with reduced confidence. Store coordinates in metres, labels, curve
ids, calibration, pixel locations and missing/ambiguous counts per stored build.
Profile keel/deck and stem/transom scans define boundary evidence. No truth enters
the evidence collector or fitter. Store derived data and logs under ignored `work/`;
commit code, tests and concise result tables.

Fit one tensor spline surface, with view weights, the existing source-label
weights, a second-difference fairness penalty and Huber residual weights. Keep
keel/centreline, terminal sections and deck edges as exact boundary conditions.
Profile evidence fixes the domain between stations; add half stations in the first
and last measured gaps only where profile evidence spans them. Report conflicting
boundary evidence; do not silently move a hard boundary to satisfy it. The current
station-only fit remains the fallback when cross-view evidence is absent.

Choose plan weight from **0.5, 2, 8** using only delivered L0 evidence and paired
injections. Body and profile weights = 1, fairness = 0.02, Huber scale = 1 % of
unperturbed half-beam. Among candidates meeting T4 on L0, choose the smallest
worst absolute injection follow share; ties choose the smaller plan weight. If
none meet T4, choose the largest minimum within-tolerance share, then the smallest
worst follow share, then smaller weight. Freeze that choice in a committed file
before scoring either half or running check-half injections. Do not tune after
check results. The final replay includes all stored builds on both halves.

## 9. Three-view implementation and replay

PM instruction after protocol commit `cf3c5f4`: finish steps 2-4 without running
`git commit`; leave file groups for the PM. The split and targets in section 8
are unchanged. The weight-choice file was saved before any check-half fit or
score. All data below are stored-reading replays; no live model was called.

### 9.1 Evidence collected (step 2)

`three_view_evidence.py` reuses `draft_fit.reference_views` and
`view_measure.measure_views`. `collect_three_view.py` collects 21 stored
first/revision builds, plus the BUE GIRL reader output: 11 fit entries and 11
check entries. It records each build's scale, reference frame and source hash.
No current task-state reading is substituted for an older stored build.

There are 8,754 plan points across the 21 development builds. Each source gap
has four sampling intervals, so the evidence includes ink between stations.
Each observation stores view, curve id, source label, confidence, hull x/y/z,
and pixel position where applicable. Profile observations have `y_m=null`:
a silhouette is not a measurement of interior breadth. Missing views and scan
failures have explicit counts. Body points retain their stored source labels.
Unique plan/profile scans are `traced`; competing, distant, one-sided or shared
crossings are `repaired`. Two waterline labels assigned the same ink both get
lower confidence. The height association still uses the stored hull prediction;
these are not independently verified waterline identities.

BUE GIRL's captured intake supplies only a body-plan region. The existing
reference-frame helper returns no usable plan or profile. This gap is retained;
its result is an explicit station-only fallback, not a three-view success.

Derived observations, manifest and logs are under
`work/three-view-fairing/evidence/` and `work/three-view-fairing/collection.log`.
They remain ignored. No `work/factory-sealed-*` directory was opened. The scorer
uses only the development truth under `work/factory-3view/sealed/truth/`.

### 9.2 Surface and frozen choice (step 3)

`three_view_fairing.py` fits one cubic tensor spline correction to a boundary
patch. Coordinates are hull x and the square root of normalized height above
the profile keel. Body and plan observations constrain breadth at true height.
Profile keel/deck observations fit robust height curves between the fixed source
station heights. Source-label weights are the existing fairing weights; each
breadth view's weights are normalized by its observation count. Each profile
boundary curve is normalized separately. Huber residual weights and a
second-difference penalty limit local bends in both spline directions.

The correction vanishes at the keel, deck and terminal sections. Those source
boundaries are exact, including centreline observations. Hard constraints use
elimination and a boundary patch, not a large approximate penalty weight.
The profile's stem/stern scans are compared with this held terminal domain.
A conflicting end silhouette is reported; it does not move a stored terminal
cap. Thus the end silhouette is a boundary check, while keel/deck profile ink
constrains the fitted domain. This is a limit when the stored end sections are
wrong or do not reach the drawn ends. Half stations are added at the first and
last measured gaps only where profile keel and deck samples bracket them.
Their shape is labelled `interpolated`.

The explicit API is `fairing.fair_sections(sections, evidence=point_sets)`.
The application pipeline remains unchanged: `run_record.py` requires the
submitted and observed station ids to match exactly. Adding new half stations
inside that pipeline would violate this contract. A future application hook
must declare inferred stations in an earlier materialization step; this lane
does not change that gate or the other lane's reading materialization. The
replay builds and scores the complete returned sections directly. Missing
cross-view evidence uses the station-only fallback. The existing application
setting remains off by default; application publication of the new surface is
not established by the direct CAD test.

L0-only choice, before check evaluation:

| Plan weight | Minimum traced/read fidelity across L0 cases/views | Worst injection follow share (all kinds) |
|---|---|---|
| **0.5 (selected)** | **32.14 %** | **0.993** |
| 2 | 12.78 % | 0.938 |
| 8 | 12.66 % | 0.760 |

None met T4. The frozen rule therefore selects 0.5, which has the largest
minimum fidelity. Body/profile weights are 1, fairness 0.02 and Huber scale 1 %
of the unperturbed measured half-beam. Increasing plan weight reduces the
single-cell influence on L0, but moves more original points. The saved choice
is `benchmarks/hull_fairing/three_view_choice.json`; tuning details are in
`work/three-view-fairing/tuning.json`. There is no check-half tuning.

Reproduction (from this worktree, with the existing development data):

```bash
set -o pipefail
export PYTHONPATH=src:.
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python -m benchmarks.hull_fairing.collect_three_view
.venv/bin/python -m benchmarks.hull_fairing.replay_three_view choose --choice work/three-view-fairing/repeat-choice.json --output work/three-view-fairing/repeat-tuning.json
.venv/bin/python -m benchmarks.hull_fairing.replay_three_view replay --choice work/three-view-fairing/repeat-choice.json --output work/three-view-fairing/repeat-replay
.venv/bin/python -m benchmarks.hull_fairing.summary_three_view work/three-view-fairing/repeat-replay/replay.json --export-sections work/three-view-fairing/repeat-sections --complete-output work/three-view-fairing/repeat-complete.json --json-output work/three-view-fairing/repeat-summary.json
```

The choice command creates its choice file exclusively. For another repeat,
use a new choice filename. To evaluate the saved choice without tuning, omit
the `choose` command and pass
`--choice benchmarks/hull_fairing/three_view_choice.json` to `replay`.

### 9.3 Fixed-choice results (step 4)

All 21 development builds were rebuilt in three modes and scored through the
unchanged STEP scorer: 63 CAD builds, no fit/build/score failure. BUE GIRL was
scored on reader points and curves only; it was not rebuilt as CAD. The two
unavailable all-build injection trials per kind remain in the denominator.

Gate metrics below use rebuilt STEP meshes. Injection follow and fidelity use
the returned section/surface points, as in section 6; the injection ratios do
not include a fresh CAD approximation or mesh cut for each perturbation.
Inflection counts include added half stations. All source boundary points of
the joint fit are held exactly; independent ink can still disagree with them.

The canonical data are `work/three-view-fairing/replay/replay.json` and its
per-build JSON files. Exact returned section arrays for all three modes are in
`work/three-view-fairing/sections/` (22 files). `summary.json` and `summary.md`
are under `work/three-view-fairing/`. The old raw combined replay is retained
as `replay-before-scale-fix.json`: its legacy injection scales were not frozen.
The canonical injection results were recomputed with the unperturbed half-beam
fixed for both legacy and joint fallbacks. Unperturbed reports and every
three-view injection response were checked equal before exporting sections;
no fit choice or gate score changed.

Modes in each cell: **current / station-only / joint**. Signed volume errors use the unchanged in-range scorer.

Joint-fit diagnostics: 34 added half stations; 1282 negative breadth samples projected to the small positive floor.

| Delivered case | Split | RMS % | Volume % | Gate passes |
|---|---|---|---|---|
| dtmb5415-L0 | fit | 8.087 / 8.087 / 8.301 | 0.989 / 0.991 / 1.270 | 0 / 0 / 0 |
| series60-L0 | fit | 1.385 / 1.285 / 3.411 | 1.068 / 1.027 / 2.069 | 1 / 1 / 0 |
| 00679-L0 | fit | 4.048 / 3.846 / 9.415 | 0.032 / -0.041 / -4.685 | 0 / 0 / 0 |
| 08158-L0 | fit | 0.755 / 0.715 / 3.058 | -2.072 / -2.037 / 0.102 | 1 / 1 / 0 |
| 09867-L0 | fit | 3.246 / 2.506 / 4.260 | 1.797 / 1.751 / 2.654 | 0 / 0 / 0 |
| dtmb5415-L1 | check | 14.339 / 14.188 / 13.915 | 13.194 / 13.180 / 13.042 | 0 / 0 / 0 |
| series60-L1 | check | 3.492 / 3.334 / 7.123 | -0.521 / -0.507 / -0.199 | 0 / 0 / 0 |
| 00679-L1 | check | 5.467 / 5.438 / 8.173 | -0.941 / -0.949 / -2.119 | 0 / 0 / 0 |
| 08158-L1 | check | 1.642 / 1.625 / 3.120 | -3.129 / -3.133 / -3.214 | 1 / 1 / 0 |
| 09867-L1 | check | 1.005 / 0.983 / 1.191 | 2.150 / 2.104 / 1.552 | 1 / 1 / 1 |

| Population | Planned builds | Scored (current / station-only / joint) | Mean RMS % | Passes |
|---|---|---|---|---|
| fit | 5 | 5 / 5 / 5 | 3.504 / 3.288 / 5.689 | 2 / 2 / 0 |
| check | 5 | 5 / 5 / 5 | 5.189 / 5.114 / 6.704 | 2 / 2 / 1 |
| all_builds | 21 | 21 / 21 / 21 | 6.521 / 6.424 / 7.877 | 7 / 7 / 2 |
| all_builds_fit | 11 | 11 / 11 / 11 | 7.732 / 7.613 / 9.063 | 3 / 3 / 0 |
| all_builds_check | 10 | 10 / 10 / 10 | 5.190 / 5.116 / 6.572 | 4 / 4 / 2 |

| Population | Mode | Injection | Available / planned | Median signed share | Median absolute share | Max absolute share | Target met |
|---|---|---|---|---|---|---|---|
| fit | station_only | cell_0.1m | 10 / 10 | 0.978 | 0.978 | 0.987 | False |
| fit | station_only | cell_0.2m | 10 / 10 | 0.979 | 0.979 | 0.997 | False |
| fit | station_only | station_5pct | 10 / 10 | 0.965 | 0.965 | 0.985 | False |
| fit | joint | cell_0.1m | 10 / 10 | 0.153 | 0.153 | 0.306 | False |
| fit | joint | cell_0.2m | 10 / 10 | 0.127 | 0.127 | 0.342 | False |
| fit | joint | station_5pct | 10 / 10 | 0.931 | 0.931 | 0.993 | False |
| check | station_only | cell_0.1m | 10 / 10 | 0.978 | 0.978 | 0.998 | False |
| check | station_only | cell_0.2m | 10 / 10 | 0.960 | 0.960 | 0.998 | False |
| check | station_only | station_5pct | 10 / 10 | 0.903 | 0.903 | 0.998 | False |
| check | joint | cell_0.1m | 10 / 10 | 0.206 | 0.206 | 0.254 | False |
| check | joint | cell_0.2m | 10 / 10 | 0.189 | 0.189 | 0.246 | True |
| check | joint | station_5pct | 10 / 10 | 0.974 | 0.974 | 1.002 | False |
| BUE GIRL reader | station_only | cell_0.1m | 2 / 2 | 0.872 | 0.872 | 0.911 | False |
| BUE GIRL reader | station_only | cell_0.2m | 2 / 2 | 0.730 | 0.730 | 0.761 | False |
| BUE GIRL reader | station_only | station_5pct | 2 / 2 | 0.938 | 0.938 | 0.973 | False |
| BUE GIRL reader | joint | cell_0.1m | 2 / 2 | 0.872 | 0.872 | 0.911 | False |
| BUE GIRL reader | joint | cell_0.2m | 2 / 2 | 0.730 | 0.730 | 0.761 | False |
| BUE GIRL reader | joint | station_5pct | 2 / 2 | 0.938 | 0.938 | 0.973 | False |
| all stored (factory) | station_only | cell_0.1m | 40 / 42 | 0.978 | 0.978 | 1.000 | False |
| all stored (factory) | station_only | cell_0.2m | 40 / 42 | 0.965 | 0.965 | 1.000 | False |
| all stored (factory) | station_only | station_5pct | 40 / 42 | 0.916 | 0.916 | 1.000 | False |
| all stored (factory) | joint | cell_0.1m | 40 / 42 | 0.188 | 0.188 | 1.000 | False |
| all stored (factory) | joint | cell_0.2m | 40 / 42 | 0.154 | 0.154 | 1.000 | False |
| all stored (factory) | joint | station_5pct | 40 / 42 | 0.941 | 0.941 | 1.002 | False |

The current builder follows every available injection by 1.00. The JSON also records off-target maximum movement for every trial.

Traced/read point movements below are **median / p95 / max metres; % within tolerance**. Each view uses its own measured points. Full per-source-label statistics and every excess location are in the replay JSON.

| Delivered case | Body plan | Half-breadth plan | Profile |
|---|---|---|---|
| dtmb5415-L0 | traced: 0.049 / 0.370 / 0.743; 62.2% (1207 points, 0 unavailable) | traced: 0.063 / 0.468 / 0.699; 54.6% (119 points, 0 unavailable) | traced: 0.021 / 0.395 / 0.894; 70.8% (144 points, 0 unavailable) |
| series60-L0 | traced: 0.026 / 0.643 / 1.106; 73.9% (1190 points, 0 unavailable) | traced: 0.039 / 0.414 / 0.730; 62.5% (176 points, 0 unavailable) | traced: 0.013 / 0.394 / 0.551; 77.7% (175 points, 0 unavailable) |
| 00679-L0 | traced: 0.188 / 0.763 / 1.483; 32.1% (837 points, 0 unavailable) | traced: 0.095 / 0.903 / 1.821; 46.7% (75 points, 0 unavailable) | traced: 0.025 / 0.204 / 3.126; 81.4% (183 points, 0 unavailable) |
| 08158-L0 | traced: 0.093 / 0.624 / 0.734; 53.0% (659 points, 0 unavailable) | traced: 0.086 / 0.617 / 0.929; 57.0% (128 points, 0 unavailable) | traced: 0.028 / 0.722 / 1.377; 76.7% (150 points, 0 unavailable) |
| 09867-L0 | traced: 0.015 / 0.175 / 1.102; 89.1% (1104 points, 0 unavailable) | traced: 0.025 / 0.393 / 0.974; 69.0% (87 points, 0 unavailable) | traced: 0.030 / 0.873 / 1.637; 75.0% (132 points, 0 unavailable) |
| dtmb5415-L1 | traced: 0.055 / 0.740 / 1.769; 52.9% (934 points, 0 unavailable) | traced: 0.164 / 0.802 / 1.364; 19.8% (101 points, 0 unavailable) | traced: 0.061 / 0.451 / 0.813; 55.5% (146 points, 0 unavailable) |
| series60-L1 | traced: 0.039 / 0.960 / 5.190; 63.6% (938 points, 0 unavailable) | traced: 0.121 / 0.576 / 0.910; 38.2% (131 points, 0 unavailable) | traced: 0.043 / 0.392 / 0.753; 64.6% (181 points, 0 unavailable) |
| 00679-L1 | traced: 0.107 / 0.817 / 1.095; 42.2% (845 points, 0 unavailable) | traced: 0.075 / 0.726 / 1.103; 52.0% (100 points, 0 unavailable) | traced: 0.024 / 0.169 / 1.270; 87.5% (184 points, 0 unavailable) |
| 08158-L1 | traced: 0.118 / 0.649 / 1.082; 42.6% (1098 points, 0 unavailable) | traced: 0.138 / 0.978 / 1.394; 40.8% (130 points, 0 unavailable) | traced: 0.061 / 0.698 / 0.888; 58.6% (133 points, 0 unavailable) |
| 09867-L1 | traced: 0.020 / 0.093 / 0.413; 95.2% (1111 points, 0 unavailable) | traced: 0.078 / 0.732 / 1.257; 54.5% (33 points, 0 unavailable) | traced: 0.066 / 0.835 / 2.256; 63.9% (147 points, 0 unavailable) |
| bue_girl | read: 0.000 / 0.001 / 0.006; 100.0% (1391 points, 0 unavailable) | not available (station-only fallback) | not available (station-only fallback) |

| Delivered case | WL inflections | Section inflections | Max curvature jump |
|---|---|---|---|
| dtmb5415-L0 | 38.000 / 36.000 / 32.000 | 21.000 / 21.000 / 13.000 | 1.734 / 1.734 / 1.892 |
| series60-L0 | 92.000 / 81.000 / 72.000 | 32.000 / 30.000 / 23.000 | 3.890 / 3.890 / 2.895 |
| 00679-L0 | 43.000 / 51.000 / 153.000 | 41.000 / 41.000 / 5.000 | 0.449 / 0.454 / 0.397 |
| 08158-L0 | 50.000 / 54.000 / 44.000 | 42.000 / 42.000 / 34.000 | 3.668 / 3.664 / 4.200 |
| 09867-L0 | 87.000 / 77.000 / 112.000 | 25.000 / 25.000 / 0.000 | 1.329 / 1.329 / 1.174 |
| dtmb5415-L1 | 48.000 / 48.000 / 60.000 | 31.000 / 33.000 / 13.000 | 3.787 / 3.787 / 3.452 |
| series60-L1 | 94.000 / 94.000 / 154.000 | 41.000 / 41.000 / 22.000 | 4.049 / 4.049 / 3.084 |
| 00679-L1 | 63.000 / 61.000 / 143.000 | 27.000 / 27.000 / 0.000 | 0.677 / 0.683 / 0.547 |
| 08158-L1 | 52.000 / 52.000 / 45.000 | 66.000 / 66.000 / 56.000 | 3.743 / 3.738 / 4.078 |
| 09867-L1 | 95.000 / 95.000 / 69.000 | 18.000 / 17.000 / 6.000 | 0.575 / 0.575 / 0.452 |
| bue_girl | 12.000 / 9.000 / 9.000 | 18.000 / 18.000 / 18.000 | 0.290 / 0.280 / 0.280 |

| BUE GIRL reader mode | RMS m | Max m | Within 0.05 m | Scored / truth cells |
|---|---|---|---|---|
| stored reader cells | 0.00143 | 0.00588 | 100.0% | 37 / 39 |

Missing stored reader truth cells: `[{"station": 10, "waterline": "2-6-0"}, {"station": 12, "waterline": "2-6-0"}]`.

| Resampled reader curves | RMS m | Max m | Within 0.05 m | Scored / truth cells |
|---|---|---|---|---|
| current | 0.00229 | 0.00938 | 100.0% | 37 / 39 |
| station_only | 0.00217 | 0.00832 | 100.0% | 37 / 39 |
| joint | 0.00217 | 0.00832 | 100.0% | 37 / 39 |

Targets: `{"fit": {"complete": true, "T1": false, "T2": false, "T3": false, "T4": false}, "check": {"complete": true, "T1": false, "T2": false, "T3": false, "T4": false}}`. BUE GIRL T5: `True`.


### 9.4 Recommendation and limits

**Keep fairing off by default. Do not route the application to this fit.**
On the delivered check half, RMS increases from 5.189 to 6.704 %, one of two
gate passes is lost, and 00679-L1's absolute volume error increases by more than
0.5 points. T1 and T2 fail. Across all ten delivered development cases, mean
RMS is 4.347 / 4.201 / 6.197 % (current / station-only / joint), with passes
4 / 4 / 1. All stored development builds give 6.521 / 6.424 / 7.877 %.

The joint surface reduces single-cell influence: on the five delivered check
cases, the +0.2 m maximum follow share is 0.246, within the nominal 0.25 target.
But +0.1 m reaches 0.254, whole-station errors reach 1.002, and BUE GIRL lacks
cross-view evidence and falls back. T3 fails. T4 also fails: movements of
traced points in all three views exceed the fixed fidelity allowance on many
cases. The fit adds 34 half stations and projects 1,282 negative breadth
samples to a small positive floor. Those projections keep the CAD open but
are a further limit on a claim of smoothness; they are counted, not hidden.

These results establish a response improvement for isolated cells, not an
accuracy improvement. Two limits are explicit in this implementation: ink
identity still depends on a stored-hull prediction, and hard stored boundaries
can conflict with independent ink. In the whole-station injection, the stored
deck edge is itself shifted but remains a hard boundary. The terminal boundary
patch also carries the terminal curves' shape into the interior; its limited
spline correction need not remove their noise. The experiment does not isolate
these causes with an ablation and does not justify more tuning on the check half.

BUE GIRL's stored cell output has 1.43 mm RMS. Resampling its raw curves at exact
truth heights gives 2.29 mm before fitting and 2.17 mm after the station-only
fallback. These are separate measurements, not a new reader run. Both methods
score 37/39 truth cells; stations 10 and 12 at 2-6-0 are absent. Seven extra
reader cells have no truth entry. T5 is met on available cells, with no cell
lost by fitting, but no three-view benefit is established for this drawing.

Application publication is a separate pending integration task: inferred half
stations must be declared before reconstruction under the existing immutable
station-id contract. No reader, selection, application pipeline, verifier or
2 % RMS / 5 % volume gate was changed by this experiment.

### 9.5 Verification

- 31 focused fairing/evidence/replay/protocol tests passed, including five CAD
  tests and a regression that freezes the reference half-beam in paired trials.
- The supported non-CAD suite passed: 1,470 passed, 61 deselected, five existing
  SWIG deprecation warnings. Deselections are 46 CAD tests and 15 sandbox-bound
  tests, not a change to the test definitions.
- A full non-CAD attempt before those exclusions gave 1,468 passed, four runtime
  failures and 11 review-server setup errors. The sandbox denies process
  inspection/control and localhost port binding needed by those tests. No
  runtime or server code was changed. An intermediate supported rerun was
  interrupted under high host load; it is not counted as a complete run.
- Report/replay tests were checked again after the final report-only additions.
  Per-view statistics, corrected paired trials and section exports are present
  for every planned entry. No live model calls or image deliverables were used.

### 9.6 Files for PM commits

Step 1 is already committed as `cf3c5f4`. All files below remain uncommitted.
The protocol JSON and its original test remain unchanged.

**Step 2: evidence data adapter and collection**

```text
src/vessel_reconstruction/three_view_evidence.py
benchmarks/hull_fairing/collect_three_view.py
tests/test_three_view_evidence.py
```

**Step 3: fit, frozen choice and fit-half measurements**

```text
src/vessel_reconstruction/fairing.py
src/vessel_reconstruction/three_view_fairing.py
benchmarks/hull_fairing/replay_three_view.py
benchmarks/hull_fairing/three_view_choice.json
tests/test_fairing.py
tests/test_fairing_pipeline.py
tests/test_three_view_fairing.py
tests/test_three_view_replay.py
tasks/lessons.md
```

**Step 4: final report and summary checks**

```text
benchmarks/hull_fairing/summary_three_view.py
tests/test_three_view_summary.py
docs/HULL_FAIRING.md
```

Derived replay data and logs stay ignored under `work/three-view-fairing/`;
they are not commit inputs. No commit, push, merge or branch switch was run
after the PM's update.

## 10. Plan and profile view reader v2

Date: 2026-11-10, branch `feature/view-reader-v2`. Development data only
(`work/factory-3view`); no `work/factory-sealed-*` directory was opened. No
model call, no application wiring: the reader is off by default and is used
only by the benchmark scripts below.

### 10.1 Why and what

Section 9 found two evidence limits: plan-view waterline identity came from the
stored hull prediction, and stored boundaries conflict with independent ink.
A measurement of the old evidence (10.3) adds a third: the old waterline
heights came from every long horizontal line of the profile, so flat keels,
flat decks and buttock bottoms became "waterlines" (series60, 00679 and 09867
have 1-4 spurious heights; 09867-L1 lost four of six true heights).

`src/vessel_reconstruction/view_reader_v2.py` reads the profile and the
half-breadth plan from the drawing only (region boxes and scale from
`draft_fit.reference_views`; no stored hull, no truth):

- The sheet rotation (`view_skew`) is removed by resampling each view.
- Profile: hull ink is separated from grid, baseline and centreline by tone.
  Keel and deck/sheer are the outer edges of the lowest and highest outline
  runs in each column (less half a line); stem and stern are the outer runs of
  each row. z = 0 is the drawn baseline when it is within 3 px of the lowest
  keel ink.
- Waterline heights: grid rows that have a label left of the view and lie on
  a whole number of grid spacings above the baseline label.
- Plan identity: a waterline meets the centreline where the profile outline
  crosses its height. Each curve is named at its own end (the curves that end
  nearer to that end lie nearer the centreline) and then followed along its
  own line. Following stops at a bunch of curves, at a crossing, at a split
  and outside the profile's keel-to-deck span. An exclusion step names the
  last free run when every other curve present holds its own run. Points
  followed from both ends must agree (`traced`); one-end points are
  `repaired`; two curves on one run abstain.
- No order from the centreline is assumed. A first version named runs by
  order (lowest waterline nearest the centreline). Fit-half development showed
  this is wrong for tumblehome (00679: the deck line is innermost) and for
  crossing waterlines (08158).
- Breadth is the distance of an ink run above the centreline row, outside a
  one-line clearance; runs within one more line width of the centreline
  abstain. A negative breadth cannot occur; abstentions are counted by reason.

Development used only the five L0 fit cases. The settings and the reader's
SHA-256 were committed in `benchmarks/hull_fairing/view_reader_v2_settings.json`
(commit a4bb28c) before the check half was read; the evaluator refuses a
changed reader for the check split. The check half was scored once.

### 10.2 Evidence error method

`benchmarks/hull_fairing/view_reader_eval.py` scores the plan/profile points
of the delivered build of each case against development truth lines, for the
old reader (`collect_three_view`, regenerated) and the new one. Plan error is
read breadth minus the truth waterline (or deck) breadth at the point's x.
Identity is correct when the claimed height is a truth waterline present at x
and the point is nearest to that truth curve (or within 1 % of half-beam of
it). Old points at a height that is no truth waterline count as wrong identity
and are not in the RMS. Keel truth is `keel_xz_m`, deck truth is
`deck_xyz_m` (deck at side). Stem/stern truth is the midpoint of the 0.5 m
truth grid step where breadth starts, so stem/stern errors below about 0.25 m
are within the truth resolution. Old "abstention" is its missing-scan share;
the old reader also kept 50-90 % of its plan points as `repaired`.

### 10.3 Evidence results: old reader against v2

Plan totals (delivered builds):

| Split | Reader | Plan points | Identity correct | Plan abstention | Points within 1 % half-beam |
|---|---|---|---|---|---|
| fit | old | 2246 | 64.5 % | 0.0 % | 73.7 % |
| fit | new | 637 | 99.8 % | 90.1 % | 97.6 % |
| check | old | 1977 | 51.8 % | 0.2 % | 42.4 % |
| check | new | 292 | 74.7 % | 95.3 % | 68.9 % |

Per case (plan, profile and heights):

| Case | Reader | Plan points | Plan RMS / max m | Identity correct | Plan abstention | Negative | Keel RMS / max m | Deck RMS / max m | Stem / stern RMS m | Heights matched (spurious) |
|---|---|---|---|---|---|---|---|---|---|---|
| dtmb5415-3v-L0 | old | 283 | 0.149 / 1.047 | 79.5 % | 0.4 % | 0 | 0.340 / 2.509 | 0.073 / 0.111 | 0.191 / 3.561 | 6/6 (0) |
| dtmb5415-3v-L0 | new | 218 | 0.032 / 0.096 | 100.0 % | 77.9 % | 0 | 0.043 / 0.139 | 0.020 / 0.054 | 0.231 / 0.312 | 6/6 (0) |
| series60-3v-L0 | old | 526 | 0.168 / 1.135 | 72.4 % | 0.0 % | 0 | 0.069 / 0.134 | 0.075 / 0.129 | 0.173 / 0.185 | 7/7 (1) |
| series60-3v-L0 | new | 3 | 0.068 / 0.096 | 100.0 % | 99.8 % | 0 | 0.029 / 0.058 | 0.040 / 0.098 | 0.225 / 0.114 | 7/7 (0) |
| shipd-1-00679-3v-L0 | old | 567 | 0.326 / 4.500 | 54.1 % | 0.0 % | 0 | 0.088 / 0.428 | 0.171 / 1.301 | 0.711 / 0.845 | 7/7 (2) |
| shipd-1-00679-3v-L0 | new | 12 | 0.028 / 0.080 | 100.0 % | 99.2 % | 0 | 0.101 / 0.120 | 0.064 / 0.153 | 0.338 / 0.195 | 7/7 (0) |
| shipd-1-08158-3v-L0 | old | 260 | 0.121 / 1.275 | 89.6 % | 0.0 % | 0 | 0.770 / 3.649 | 0.057 / 0.103 | 0.339 / 0.422 | 5/5 (0) |
| shipd-1-08158-3v-L0 | new | 202 | 0.049 / 0.153 | 99.5 % | 81.1 % | 0 | 0.101 / 0.142 | 0.072 / 0.168 | 0.281 / 0.339 | 5/5 (0) |
| shipd-1-09867-3v-L0 | old | 610 | 0.366 / 2.911 | 49.5 % | 0.0 % | 0 | 0.052 / 0.218 | 0.087 / 0.448 | 0.412 / 0.276 | 5/6 (4) |
| shipd-1-09867-3v-L0 | new | 202 | 0.018 / 0.065 | 100.0 % | 84.9 % | 0 | 0.106 / 0.149 | 0.073 / 0.146 | 0.259 / 0.145 | 6/6 (0) |
| dtmb5415-3v-L1 | old | 272 | 0.924 / 3.282 | 45.6 % | 0.0 % | 0 | 0.725 / 5.009 | 0.147 / 0.238 | 0.444 / 6.857 | 6/6 (0) |
| dtmb5415-3v-L1 | new | 92 | 0.050 / 0.098 | 93.5 % | 90.6 % | 0 | 0.035 / 0.156 | 0.025 / 0.217 | 0.258 / 0.468 | 6/6 (0) |
| series60-3v-L1 | old | 549 | 0.225 / 0.962 | 48.5 % | 0.5 % | 0 | 0.109 / 0.179 | 0.110 / 0.177 | 0.175 / 0.198 | 7/7 (1) |
| series60-3v-L1 | new | 36 | 0.854 / 1.172 | 0.0 % | 97.6 % | 0 | 0.053 / 0.159 | 0.096 / 0.155 | 0.257 / 0.133 | 7/7 (0) |
| shipd-1-00679-3v-L1 | old | 536 | 0.339 / 4.553 | 49.3 % | 0.0 % | 0 | 0.164 / 0.662 | 0.161 / 1.252 | 0.990 / 1.195 | 6/7 (3) |
| shipd-1-00679-3v-L1 | new | 10 | 0.025 / 0.043 | 100.0 % | 99.3 % | 0 | 0.139 / 0.201 | 0.126 / 0.188 | 0.539 / 0.233 | 7/7 (0) |
| shipd-1-08158-3v-L1 | old | 293 | 0.151 / 1.266 | 79.5 % | 0.0 % | 0 | 0.795 / 3.770 | 0.054 / 0.089 | 0.401 / 0.502 | 5/5 (0) |
| shipd-1-08158-3v-L1 | new | 147 | 0.600 / 2.300 | 78.2 % | 83.6 % | 0 | 0.157 / 0.300 | 0.118 / 0.195 | 0.505 / 0.379 | 4/5 (0) |
| shipd-1-09867-3v-L1 | old | 327 | 0.318 / 1.410 | 41.9 % | 0.0 % | 0 | 0.143 / 0.484 | 0.161 / 0.834 | 0.643 / 0.388 | 2/6 (3) |
| shipd-1-09867-3v-L1 | new | 7 | 0.114 / 0.135 | 100.0 % | 99.5 % | 0 | 0.111 / 0.157 | 0.067 / 0.104 | 0.282 / 0.152 | 6/6 (0) |
| bue_girl (check) | both | not available: intake has only a body-plan region; no plan or profile view to read | | | | | | | | |
Plan error per curve (points, RMS m, max m; "absent" = a claimed waterline
that truth does not have at that x):

| Case | Reader | Per curve: points, RMS m, max m |
|---|---|---|
| dtmb5415-3v-L0 | old | deck: 67, 0.191, 0.861; deck_absent: 1 unscorable; wl_10: 23, 0.030, 0.047; wl_12: 17, 0.031, 0.059; wl_2: 10, 0.499, 1.047; wl_2_absent: 2 unscorable; wl_4: 39, 0.045, 0.164; wl_4_absent: 2 unscorable; wl_6: 57, 0.103, 0.479; wl_6_absent: 2 unscorable; wl_8: 61, 0.080, 0.429; wl_8_absent: 2 unscorable |
| dtmb5415-3v-L0 | new | deck: 12, 0.069, 0.096; wl_10: 42, 0.031, 0.066; wl_12: 11, 0.053, 0.093; wl_4: 151, 0.025, 0.093; wl_8: 2, 0.028, 0.028 |
| series60-3v-L0 | old | deck: 72, 0.047, 0.170; deck_absent: 1 unscorable; spurious_height: 8 unscorable; wl_1: 57, 0.080, 0.329; wl_2: 58, 0.160, 0.879; wl_3: 59, 0.203, 0.914; wl_3_absent: 1 unscorable; wl_4: 59, 0.227, 0.823; wl_4_absent: 3 unscorable; wl_5: 65, 0.230, 1.135; wl_6: 70, 0.222, 0.991; wl_7: 73, 0.049, 0.267 |
| series60-3v-L0 | new | wl_6: 3, 0.068, 0.096 |
| shipd-1-00679-3v-L0 | old | deck: 71, 0.710, 4.500; deck_absent: 2 unscorable; spurious_height: 84 unscorable; wl_10: 64, 0.127, 0.438; wl_12: 51, 0.204, 0.643; wl_14: 33, 0.091, 0.454; wl_2: 55, 0.374, 0.907; wl_4: 64, 0.193, 0.635; wl_6: 70, 0.118, 0.365; wl_8: 73, 0.096, 0.341 |
| shipd-1-00679-3v-L0 | new | wl_2: 11, 0.027, 0.080; wl_4: 1, 0.033, 0.033 |
| shipd-1-08158-3v-L0 | old | deck: 65, 0.069, 0.395; wl_10: 19, 0.055, 0.060; wl_2: 29, 0.021, 0.034; wl_4: 39, 0.134, 0.360; wl_6: 50, 0.215, 1.275; wl_6_absent: 2 unscorable; wl_8: 56, 0.081, 0.533 |
| shipd-1-08158-3v-L0 | new | deck: 32, 0.050, 0.153; wl_2: 140, 0.045, 0.078; wl_4: 23, 0.068, 0.087; wl_6: 7, 0.057, 0.097 |
| shipd-1-09867-3v-L0 | old | deck: 71, 0.520, 1.583; deck_absent: 2 unscorable; spurious_height: 193 unscorable; wl_10: 70, 0.409, 2.911; wl_10_absent: 2 unscorable; wl_12: 68, 0.407, 1.149; wl_4: 54, 0.079, 0.512; wl_4_absent: 7 unscorable; wl_6: 64, 0.176, 0.564; wl_6_absent: 6 unscorable; wl_8: 69, 0.352, 2.742; wl_8_absent: 4 unscorable |
| shipd-1-09867-3v-L0 | new | wl_2: 169, 0.013, 0.065; wl_4: 23, 0.034, 0.061; wl_6: 10, 0.039, 0.057 |
| dtmb5415-3v-L1 | old | deck: 68, 0.203, 0.774; deck_absent: 1 unscorable; wl_10: 22, 1.080, 1.540; wl_12: 17, 0.298, 0.477; wl_2: 8, 0.534, 0.961; wl_2_absent: 1 unscorable; wl_4: 38, 1.182, 2.313; wl_6: 56, 1.141, 3.282; wl_8: 61, 1.087, 2.622 |
| dtmb5415-3v-L1 | new | deck: 12, 0.067, 0.093; wl_10: 61, 0.039, 0.081; wl_10_absent: 6 unscorable; wl_12: 11, 0.074, 0.098; wl_8: 2, 0.043, 0.049 |
| series60-3v-L1 | old | deck: 71, 0.203, 0.675; deck_absent: 1 unscorable; spurious_height: 34 unscorable; wl_1: 56, 0.138, 0.468; wl_2: 58, 0.178, 0.620; wl_3: 58, 0.211, 0.635; wl_3_absent: 2 unscorable; wl_4: 59, 0.333, 0.962; wl_4_absent: 3 unscorable; wl_5: 64, 0.231, 0.899; wl_5_absent: 1 unscorable; wl_6: 69, 0.266, 0.846; wl_6_absent: 1 unscorable; wl_7: 72, 0.183, 0.679 |
| series60-3v-L1 | new | wl_6: 36, 0.854, 1.172 |
| shipd-1-00679-3v-L1 | old | deck: 71, 0.718, 4.553; deck_absent: 2 unscorable; spurious_height: 87 unscorable; wl_10: 64, 0.133, 0.429; wl_12: 50, 0.177, 0.503; wl_2: 55, 0.379, 0.917; wl_4: 64, 0.203, 0.587; wl_6: 70, 0.098, 0.389; wl_8: 73, 0.102, 0.316 |
| shipd-1-00679-3v-L1 | new | wl_2: 9, 0.025, 0.043; wl_4: 1, 0.016, 0.016 |
| shipd-1-08158-3v-L1 | old | deck: 65, 0.126, 0.862; wl_10: 53, 0.163, 0.773; wl_2: 29, 0.054, 0.104; wl_4: 38, 0.115, 0.355; wl_6: 50, 0.237, 1.266; wl_6_absent: 2 unscorable; wl_8: 56, 0.121, 0.537 |
| shipd-1-08158-3v-L1 | new | deck: 30, 0.044, 0.101; wl_10: 5, 0.019, 0.033; wl_2: 44, 0.044, 0.072; wl_6: 31, 0.994, 1.844; wl_8: 37, 0.774, 2.300 |
| shipd-1-09867-3v-L1 | old | deck: 71, 0.451, 1.410; deck_absent: 2 unscorable; spurious_height: 142 unscorable; wl_2: 43, 0.099, 0.278; wl_2_absent: 8 unscorable; wl_4: 54, 0.199, 1.008; wl_4_absent: 7 unscorable |
| shipd-1-09867-3v-L1 | new | wl_6: 7, 0.114, 0.135 |

Summary:

- Waterline heights: v2 matched every truth height on 9 of 10 sheets with no
  spurious height (08158-L1: 4 of 5). The old reader had 14 spurious heights
  over the ten sheets and lost four 09867-L1 heights.
- Profile keel: v2 RMS 0.03-0.16 m and maximum at most 0.30 m on all ten
  sheets; old maxima reached 2.5-5.0 m (dtmb, 08158). Deck: v2 RMS
  0.02-0.13 m.
- Plan: where v2 names a curve on the fit half, 99.8 % of points have the
  correct identity and 97.6 % are within 1 % of half-beam (old: 64.5 % and
  73.7 %). Coverage is the cost: v2 abstains on 90 % of plan places on the fit
  half and 95 % on the check half. Curves whose ends cluster within three line
  widths (series60, 00679, most of 09867-L1) get no name at all.
- Check half: dtmb, 00679 and 09867 stay accurate. Two failures remain:
  series60-L1 (36 points, all on the wrong curve, 0.85 m RMS) and 08158-L1
  (two-end `traced` points on waterlines 6 and 8 follow a neighbour through
  a crossing, 0.99 / 0.77 m RMS). The check identity share is 74.7 % against
  the old 51.8 %. No setting was changed after these results.
- Negative breadths: 0 for both readers in the evidence. (Section 9's 1,282
  were fitted-surface samples projected to the floor, not evidence values.)

### 10.4 Frozen three-view fairing replay with v2 evidence

`collect_view_reader_v2.py` keeps each stored build's sections and body-plan
points and replaces only the plan and profile points with v2 points. The
replay used `replay_three_view replay` with the unchanged
`three_view_choice.json` (plan weight 0.5, fairness 0.02, Huber 1 %), all 21
development builds plus BUE GIRL, 63 CAD builds, no failure. Current and
station-only columns do not use plan/profile evidence and equal section 9.3.

| Delivered case | Split | RMS % current / station-only | Joint, 9.3 evidence | Joint, v2 evidence | Volume % joint 9.3 / v2 | Joint passes 9.3 / v2 |
|---|---|---|---|---|---|---|
| dtmb5415-L0 | fit | 8.087 / 8.087 | 8.301 | 8.380 | 1.270 / 0.568 | 0 / 0 |
| series60-L0 | fit | 1.385 / 1.285 | 3.411 | 4.061 | 2.069 / 2.340 | 0 / 0 |
| 00679-L0 | fit | 4.048 / 3.846 | 9.415 | 16.419 | -4.685 / -13.378 | 0 / 0 |
| 08158-L0 | fit | 0.755 / 0.715 | 3.058 | 6.616 | 0.102 / 6.368 | 0 / 0 |
| 09867-L0 | fit | 3.246 / 2.506 | 4.260 | 4.106 | 2.654 / 2.792 | 0 / 0 |
| dtmb5415-L1 | check | 14.339 / 14.188 | 13.915 | 12.391 | 13.042 / 11.342 | 0 / 0 |
| series60-L1 | check | 3.492 / 3.334 | 7.123 | 8.066 | -0.199 / 1.797 | 0 / 0 |
| 00679-L1 | check | 5.467 / 5.438 | 8.173 | 10.981 | -2.119 / -6.762 | 0 / 0 |
| 08158-L1 | check | 1.642 / 1.625 | 3.120 | 4.326 | -3.214 / -4.602 | 0 / 0 |
| 09867-L1 | check | 1.005 / 0.983 | 1.191 | 1.381 | 1.552 / 1.136 | 1 / 1 |

| Population | Mean RMS % current / station-only | Joint 9.3 | Joint v2 | Joint passes 9.3 / v2 |
|---|---|---|---|---|
| fit (5 delivered) | 3.504 / 3.288 | 5.689 | 7.916 | 0 / 0 |
| check (5 delivered) | 5.189 / 5.114 | 6.704 | 7.429 | 1 / 1 |
| all builds (21) | 6.521 / 6.424 | 7.877 | 9.510 | 2 / 2 |
| all builds fit (11) | 7.732 / 7.613 | 9.063 | 11.317 | 0 / 0 |
| all builds check (10) | 5.190 / 5.116 | 6.572 | 7.521 | 2 / 2 |

Injections with v2 evidence (delivered, maximum absolute follow share): fit
+0.1 m 0.254, +0.2 m 0.233, whole station 1.040; check 0.330, 0.272, 1.000.
Joint diagnostics: 34 added half stations, 1,344 negative fitted-surface
samples projected to the floor (9.3: 1,282). Targets T1-T4 fail on both
halves; BUE GIRL T5 holds (station-only fallback, no plan/profile view).

### 10.5 Findings and limits

**Keep three-view fairing off.** Better evidence did not give a better
surface: the joint fit with v2 evidence is worse than with the old evidence on
both halves (fit 5.69 -> 7.92 %, check 6.70 -> 7.43 %) and much worse than
station-only (3.29 / 5.11 %). It improves only dtmb5415-L1 (13.92 -> 12.39 %)
and 09867-L0.

The joint fit now rests mainly on profile evidence (about 440 keel/deck/end
points per case, against 3-218 plan points). A diagnostic after the replay
(not a tuning input) compared each stored station's lowest and highest point
with the v2 profile at the same x. On the eight non-DTMB sheets the stored
deck ends sit a median 0.08-0.19 m below the v2 deck (keel: 0.01-0.18 m below,
08158-L1 +0.03 m); on both DTMB sheets they agree within 0.03 m. Single
stations differ by up to 3.6 m (08158 keel at an end station). The stored
reading and the drawing frame have different z datums. The fitter holds the
stored station ends exactly and bends the height envelope between stations
towards the profile ink, so a datum offset becomes a wave in every gap
(00679-L0 volume -13.4 %). This is a frame-alignment limit of the fitter,
not an evidence error; it was not tested by an ablation here.

The plan evidence is now accurate where it exists but sparse; its weight
(0.5, normalised by point count) is fixed, and the fitted surface still moves
named plan points by about 1 m on dtmb5415-L1 and 08158 (10-30 % within
tolerance). The evidence measurement (10.3) is the main result of this lane;
the fairing replay shows that the fitter must align frames before it can use
independent profile evidence.

Open items:

1. Align the stored reading's frame to the drawing frame (x origin, z datum,
   scale) before a joint fit, or let the fit move station ends within the
   profile evidence instead of holding them.
2. Plan coverage: curves with clustered ends get no name. Candidate cues: the
   buttock correspondence (plan curve k crosses buttock row j where the
   profile buttock j crosses waterline k) and body-plan ink at stations.
3. Crossings: 08158-L1 shows two-end agreement can still be wrong through a
   shallow crossing. A crossing check (two curves exchange runs) is missing.
4. series60-L1: one wrongly named curve (rank seed at a crowded bow). Find
   the failing seed on a new development sheet, not on this check case.
5. Stem/stern truth here is on a 0.5 m grid; an exact truth contour would
   make the end errors comparable.
6. BUE GIRL has no plan/profile region in its intake; the reader was not run.

### 10.6 Reproduction and verification

```bash
set -o pipefail
export PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python -m benchmarks.hull_fairing.collect_three_view --output work/view-reader-v2/old-evidence
for s in fit check; do .venv/bin/python -m benchmarks.hull_fairing.view_reader_eval --split $s --old work/view-reader-v2/old-evidence --output work/view-reader-v2/eval-$s.json --overlays work/view-reader-v2/overlays-$s; done
.venv/bin/python -m benchmarks.hull_fairing.summary_view_reader_v2 work/view-reader-v2/eval-fit.json work/view-reader-v2/eval-check.json
.venv/bin/python -m benchmarks.hull_fairing.collect_view_reader_v2 --old work/view-reader-v2/old-evidence --output work/view-reader-v2/evidence
for s in fit check; do .venv/bin/python -m benchmarks.hull_fairing.replay_three_view replay --evidence work/view-reader-v2/evidence/$s --output work/view-reader-v2/replay-$s --choice benchmarks/hull_fairing/three_view_choice.json; done
```

Merge the two `replay.json` row lists and run `summary_three_view` with
`--evidence work/view-reader-v2/evidence/check` (it holds BUE GIRL). Derived
data, overlays and logs stay in ignored `work/view-reader-v2/`.
`tests/test_view_reader_v2.py` reads a synthetic lines drawing (heights,
keel/deck, named plan curves within 0.2 m, positive breadths, abstention
counts, ambiguous-run and coincident-end refusals).

Test runs on this branch: the non-CAD suite passed (1,661 passed, 46
deselected). The CAD suite gave 40 passed, 1 skipped and 5 failures, all in
sandbox or part-revision tests (`test_ship_cad` sandbox tests,
`test_part_revise`, `test_whole_vessel_step1`) that fail with
`sandbox-exec: execvp() ... Operation not permitted` inside this agent's own
sandbox. This lane changed none of those modules (as in 9.5, where the same
sandbox-bound tests were deselected).
