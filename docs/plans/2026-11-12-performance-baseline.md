# Performance baseline protocol (calm-water resistance, power and fuel)

Lane 1 of the basic-design batch, 2026-11-12. Branch `lane/performance-baseline`.
PRD D6: performance estimates checked against published model tests, built from
public data only. This document is the protocol: it fixes the test ships, the
conditions, the metric and the reporting rule **before** any comparison run.
Common rules in `work/pm-briefs/common.md` apply, including the GLM lane data
rule: only public data, synthetic data and code.

## Status of this document

Draft. Every score in the report is a draft estimate; the words "approved" and
"verified" are not used anywhere for these results.

## Ships and splits

Geometry is already local (`work/sources/simman/simman2008/`, SIMMAN 2008 IGES).
Published results are downloaded to `work/sources/simman_modeltests/`
(manifest with URL, size, SHA-256; nothing committed to git).

| Ship | Role | Published comparison data |
|---|---|---|
| KVLCC2 | development + blind check | none public found this lane; see "Blind check" below |
| KVLCC1 | development | none public found this lane |
| KCS | development scoring | Tokyo 2015 `vary_Fr_2-1.xls`: CT x10^3, sinkage, trim at Fr 0.108..0.282 (SVA model, Lpp 7.2786 m) |
| DTMB 5415 | development | none public found this lane |
| JBC | **blind check** (scored once, at the end) | Tokyo 2015 templates: Case 1-1a CT x10^3 = 4.289 at Fr 0.142 (Re 7.46e6); Case 1-5a self-propulsion CT 4.811, KT 0.217, KQ 0.0279, n 7.8 rps. MP687 propeller open-water table. Public IGES hull. |

Scanned SIMMAN 2008 test-program PDFs (KVLCC/KCS NMRI CMT) carry test
conditions, not measured tables; the measured NMRI series was distributed by
FTP and is not on the public pages. KCS and JBC give six and one published
speed points respectively; KVLCC1/2 and 5415 are therefore built and
sanity-checked (particulars from geometry vs published particulars, plausible
speed-power curves) but not scored. This is recorded as a limitation, not a
silently dropped requirement.

**Blind check (frozen before any JBC contact):** the JBC numbers above are
*known to the author* (they were needed to confirm the data exists), so JBC is
not a perfect blind. Mitigation recorded in the protocol: the code, its
constants, the conditions file and the reporting rule are committed and pushed
**before** the JBC run; the JBC run happens once, after `make test-quick`
passes, and its output is appended to the report without adjustment. No
constant is touched after that run. Any future truly-blind hull can reuse the
same frozen pipeline.

## Conditions (fixed now)

- Water: fresh water for KCS model point (rho = 999.5 kg/m^3, nu = 1.27e-6 m^2/s,
  Tokyo 2015 Case 2.1 page); standard ITTC values otherwise, stated per run.
- KCS speeds (model): U = 0.915, 1.281, 1.647, 1.922, 2.196, 2.379 m/s
  (Fr = 0.108, 0.152, 0.195, 0.227, 0.260, 0.282).
- JBC: Fr = 0.142 at ship scale (Lpp 280 m, U = 14.5 kn design full condition),
  rho = 999.0 kg/m^3 fresh water stated by the workshop instructions (or the
  value computed from the stated Re = 7.46e6; whichever is used is recorded).
- The draft used per ship is the published model-test draft (KCS T = 0.3418 m
  model / 10.8 m ship; JBC T_M = 16.5 m full).
- No gate or threshold is widened after a result is seen. The gates below are
  the only acceptance gates.

## Metric (fixed now)

For each scored ship and speed:

- `Ct_err%` = (Ct_est - Ct_meas) / Ct_meas x 100, where Ct uses the wetted
  surface area computed from the same geometry pipeline (S from mesh), and the
  measured Ct from the published file.
- `P_eff_err%` = (Peff_est - Peff_meas) / Peff_meas x 100, where
  Peff = R_T x U at the same speed.
- Reported per ship per speed, plus mean absolute error over the speed sweep.

## Gates (written before runs)

- Sanity gates, development ships (KCS): each published particulars value
  (Lpp, B, T, displacement, Cb, Cm, LCB) reproduced from geometry within 2 %
  relative. Published Cb/Cm/LCB come from the workshop pages.
- Scoring gates (informational, not pass/fail for the lane): report
  `Ct_err%` and `P_eff_err%` as measured. The lane succeeds when the pipeline
  runs, the numbers are computed and reported honestly with their method and
  validity range. No error target is imposed before results; none is widened
  after.
- Blind ship (JBC): scored once with the frozen code. Its numbers are reported
  as-is. If a coding bug (not an accuracy shortfall) is found in the blind run,
  the bug fix is committed, the whole re-run is reported as a second table, and
  the first table stays in the report.

## Method inventory (what the module implements)

New module `src/vessel_reconstruction/performance.py`:

1. `hull_particulars` — L, B, T, displacement volume, Cb, Cp, Cm, Cwp, LCB,
   wetted surface from the existing mesh hydrostatics
   (`vessel_reconstruction.exports.hydrostatics.mesh_hydrostatics`) on the
   hull triangulated from IGES via OCP (pattern of
   `benchmarks/gunnerus/hull_metrics.mesh_triangles`). Model or ship scale is
   an explicit input; scale errors are the caller's problem and flagged.
2. `ittc1957_friction` — ITTC-1957 model-ship correlation line
   Cf = 0.075 / (log10(Re) - 2)^2.
3. `holtrop_mennen_resistance` — Holtrop-Mennen 1982/1984: friction from
   ITTC-1957, residual with the full regression terms, appendage, air,
   wave-breaking and model-correlation allowances as in the paper. Validity
   ranges coded and checked: Fr <= 0.28 (bounded by the wave-making fit),
   0.55 <= Cb <= 0.85 (added for tankers as in the 1984 extension), L/B ~
   3.9..14.9, B/T ~ 2.1..4.0. Outside a range the output is marked.
4. `b_series_open_water` — Wageningen B-series polynomial coefficients
   (K_T, K_Q as polynomials in Z, P/D, EAR, J) after Oosterveld & van
   Oortmerssen (1975), for the B4-55 family used by JBC's MP687
   (B = 4 blades, EAR 0.50) with the published validity ranges (0.5 <= P/D <=
   1.2, J range of the fit, Re correction).
5. `propulsion_estimate` — thrust deduction t and wake fraction w from the
   Holtrop-Mennen regressions, relative rotative efficiency eta_R from the
   same regressions; delivered power P_D = P_E / (eta_H x eta_0 x eta_R x
   eta_S) with eta_S = 0.98 (shafting, stated constant); propulsive
   self-check against the JBC open-water table.
6. `fuel_per_day` — from P_D and a stated specific fuel consumption (SFOC
   g/kWh as an explicit input with a default recorded in the report), fuel
   tonnes per day at the tested speed.
7. Optional `eedi` — from P at the reference speed and deadweight if given.
8. `compare_published` — the comparison runner: loads the published file,
   computes `Ct_err%` and `P_eff_err%` per the metric above, emits a table.
   One function, one table, no interactive tuning.

Every output carries: method name + paper citation, the validity flags that
fired, and the scale (model/ship) it ran at. Outside a validity range the
result is marked "outside range" in the output, never silently scaled.

## Tests (before any comparison)

- Unit tests on each formula against published worked examples where they
  exist:
  - Holtrop-Mennen worked example (common textbook example hull) reproduced to
    a stated tolerance.
  - ITTC-1957 Cf at a stated Re (known value, e.g. Re = 1e7 -> Cf ~ 2.92e-3).
  - B-series polynomial against a digitized point of the Oosterveld &
    van Oortmerssen diagrams (or against the JBC MP687 open-water table, which
    is a B4-55-family 5-blade AU propeller; noted as an approximation because
    MP687 is not exactly a B-series).
  - Validity-range flagging fires for an out-of-range hull.
  - particulars function against a closed-form box hull (existing pattern in
    `tests/test_exports.py`).
- The comparison runner: runs end-to-end on KCS geometry + published xls in
  the work sources dir (guarded skip if data missing), computes the six
  error values, and is the artifact the report table is built from.

## Reporting rule

`docs/plans/2026-11-12-performance-baseline-results.md` (this lane's report):
error table per ship per speed, the blind ship scored once, and a section
listing every speed/hull where a method runs outside its validity range. Every
number carries its source (file + cell/line). The lane report to the PM is
under 200 words and points at that file.

## Resume point

- Protocol committed first (this file).
- Then data manifest exists at `work/sources/simman_modeltests/manifest.tsv`
  (work dir, not in git; re-downloadable from the URLs there).
- Module + tests commit after the protocol; comparison runs after
  `make test-quick` passes; blind JBC run last, frozen code, one shot.
- If the lane stops early: everything committed and pushed as it passes; the
  report file states which of steps 2-5 of the brief are done.
