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
   machine-readable counts under `outputs/` and tables here. Test replay accounting and
   repeatability, run related regression tests, review the diff, then commit results.

Resume at the first checkpoint absent from `git log`. Run Python with
`PYTHONPATH=src:. .venv/bin/python`. All shell commands start `set -o pipefail`;
never push, merge, switch branches or pipe git. No files under `work/factory-sealed-*`
may be opened. Optional fit down-weighting is deferred, not silently enabled.
