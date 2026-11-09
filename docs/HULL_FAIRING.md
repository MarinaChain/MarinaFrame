# Hull fairing: one fair surface through all stations

Status: plan (step 1), 2026-11-10. Branch `feature/hull-fairing` (from `continue/v0.5` at ceb2ee5).
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

- Surface. Each section is a half-breadth curve y(z) between its keel height z0 and top height z1.
  The builder already matches sections by normalized height t = (z - z0) / (z1 - z0). The faired
  surface is y(x, t) with z0(x) and z1(x): along every row of constant t (a "waterline" in the
  builder's correspondence) a robust cubic smoothing spline over the station positions x, and the
  same for z0(x) and z1(x). Across t the data are dense traced curves, so the surface keeps their
  resolution (rows at every source t value).
- Fairness penalty. Second-derivative energy along x (the smoothing spline minimises
  sum w (y - f)^2 + lambda * integral f''^2). Knots are at the station positions, which is where
  the minimiser of that energy has its knots (natural cubic spline). lambda comes from a fairing
  length: the distance over which the fit averages, a fixed fraction of the hull length.
- Weights by source label: traced > read > repaired > interpolated > ai_inferred/guessed.
- Constraints: the two terminal stations (stem and transom ends) are held (very large weight);
  the keel row (t = 0) and deck-edge row (t = 1) have a strong weight; points on the centreline
  (y = 0) stay on it.
- Robust loss: Huber, by iteratively reweighted least squares. A point whose residual is above
  the Huber scale pulls the surface with a bounded force, so one bad cell cannot bend the hull.
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

(Step 4.)
