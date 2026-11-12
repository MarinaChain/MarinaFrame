# Hull Variation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce draft hull candidates from the public KVLCC2 reference with changed dimensions, Cb and LCB, and report hydrostatics and gross capacity.

**Architecture:** Sample symmetric reference sections through the existing CAD tools. Scale the sections and use a two-parameter, end-body longitudinal station shift (Lackenby-type), leaving a declared parallel middle body unchanged. Build candidates with the existing ruled hull builder and measure them with the existing mesh hydrostatics. No application intake or drawing-reader changes.

**Tech Stack:** Python, NumPy, SciPy, CadQuery/OpenCascade, pytest.

---

## Boundaries and review

Only public KVLCC2 and synthetic code/data. Never read pilot, sealed or holdout material. All outputs are draft; engineering_approved=false. No new dependency. CAD exports use millimetres; calculations use metres. No model calls.

Architecture PASS: reuse geometry.build_hull and mesh_hydrostatics. Quality PASS: isolated module and explicit validation/errors. Coverage WARN: a station representation approximates the original IGES; report that loss independently of transformation accuracy. Performance PASS: solve on a small fixed mesh, build CAD only after solving; no parallel CAD jobs.

## Fixed checks (before runs)

- Identity: section coordinates unchanged to 1e-10 m; built identity volume agrees to 1e-8 relative with the same reference build.
- Target coefficient: absolute Cb error <= 0.001; LCB error <= 0.001 times candidate length. Cb basis is the stated design length, breadth and draft, not hydrostatics waterline length.
- Built volume versus closed mesh hydrostatics: relative error <= 0.001.
- Each candidate: one positive-volume valid closed solid; strictly ordered stations; no section movement in the declared parallel middle body beyond scaling.
- Capacity: gross immersed envelope volume between stated bulkhead x positions, not net cargo or deadweight. Check analytic box cases and bounds.
- Reference approximation: report sampled-reference versus original public geometry where measurable; do not substitute a target match for local shape accuracy.

## Task 1: numerical transformation

Create tests/test_hull_variation.py first, run failing tests, then create src/vessel_reconstruction/hull_variation.py. Test identity, affine scaling, feasible Cb/LCB targets, fixed middle body, invalid inputs and unreachable targets. Shift stations with smooth end-body basis functions that vanish with zero slope at the end and middle-body boundaries. Reject station folding; do not widen gates.

## Task 2: CAD and reports

Extend the module with candidate solid construction and existing hydrostatics. Add marked CAD tests for synthetic identity, validity, volume agreement and gross capacity. Add scripts/check_hull_variation.py for public IGES ingestion, candidate STEP/JSON output and sample views under ignored work/ only. Read the archive in a new empty scratch directory, with code outside it. Record source archive hash and the stated input dimensions/coordinate convention. Test focused unit and CAD cases before committing.

## Task 3: public sample and delivery

Run identity plus at least two changed KVLCC2 candidates sequentially. Read all reports. Record achieved targets, actual errors, valid solids, capacity bounds and approximation/fairness limits here. Run make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python before pushing lane/hull-variation. Do not merge. Remove only this worktree's target directory as the final cleanup after push.

## Resume point

Plan commit: 283a77d. Numerical/CAD module commit: 5fb4092.

Task 1 complete: identity, dimension scaling, both target directions, unchanged middle body, and invalid/unreachable requests pass. Task 2 partial: existing builder, hydrostatics and gross immersed capacity pass synthetic CAD checks. Task 3 blocked on public source representation; not complete.

Ruling: preserve the existing ruled builder, and explicitly report that it is not a C2 fair surface. The smooth map prevents station folding but is not a surface-fairness proof. Cost if wrong: unsuitable local panel fairness for design use; no such suitability is claimed.

Ruling: refuse missing reference shell rather than fill it with guessed breadths. Cost: no KVLCC2 candidates from this first single-valued sampler. The public IGES has sectional geometry that this representation cannot yet retain safely.

## Results and exact stop point

- Focused command: `/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m pytest -q tests/test_hull_variation.py tests/test_hull_variation_source.py`: **11 passed** (includes real CAD).
- Synthetic changed candidate: L=110 m, B=22 m, T=11 m, target Cb = reference + 0.01 and LCB/L = reference + 0.003. The CAD test enforces the original 0.001 coefficient/fraction gates, valid solid and 0.1% mesh/CAD volume gate. Identity build enforces 1e-8 relative volume.
- Public archive SHA-256: `dc032647f00a68d354ede2f4b1ee3d68cd048bc3d34d221c2a8c9aac3a6dd548`. Only the public `kvlcc2.igs` was extracted, under this worktree's ignored `work/hull-variation/source/`.
- Native source bounds: x=-328.085..5.502, y=-0.00353..29.39125, z=-28.00157..0.02790. Midship cuts show keel near native z=0 and shell extending in negative z; use source_z_direction=-1, not an assumed upward datum. Candidate sampling attempted x=-320..0, B=58 m, T=20.8 m, depth=28 m. These are stated sample inputs, not recovered certified particulars.
- Stop: the source sampler finds no shell intersection at x=4 m from the aft sampling endpoint, height=20.8 m. Earlier full-height sampling also fails at terminal sections. No KVLCC2 solid, candidate accuracy table, original-IGES volume comparison, sample images or public candidate runner is claimed.
- Resume: support source sections with multiple regions and variable vertical ranges via geometry.build_region_hull; inspect public IGES topology and x direction before declaring LCB-from-aft. Compare sampled reference against the original geometry before making an accuracy claim. Add a real fairness check or a smooth builder before claiming a fair surface. Keep the fixed gates unchanged.
- Every candidate/report remains draft with engineering_approved=false. Capacity is only the immersed gross envelope between bulkheads, not net cargo, payload or deadweight.

Measured synthetic candidate: target Cb 0.7088764989192421; built Cb 0.7088807338524958 (absolute error 0.000004235). Target LCB/L 0.503; built 0.5029442786816967 (fraction error 0.00005572, or 0.00613 m). Mesh/CAD volume relative error 0.000004877. Gross immersed capacity at 0.2L..0.8L is 14,015.43 m³.

The first quick-tier run was stopped by the tool's 600-second background limit during Python tests, with no test failure then reported. It was restarted with the longer background budget. No code-level wall or CPU limit was introduced. Final independent review found five input/geometry defects. All were addressed in one correction pass: reject multiple positive shell intersections and negative-side geometry; reject non-MM IGES rather than guessing transferred units; require explicit middle-body boundary stations; densify two-point piecewise-linear grids before CAD; require declared breadth to match geometric breadth within 1 mm. Five regression cases failed before fixes; the non-MM regression also failed before its guard. Final focused run: **14 passed in 5.37 s**. No deferred minor findings.

Ruling: limit the experimental source sampler to MM-declared files with a caller-stated correction for numerically mislabelled public coordinates. This removes ambiguous cross-unit conversion rather than promising generic IGES support. Cost: other declared units require explicit conversion before sampling.

The pre-correction quick tier passed: Rust 318 passed, 50 ignored; Python 2343 passed, 4 skipped, 90 deselected (5 warnings); UI 275 passed; bounded secret scan 0 findings. The fresh full quick tier on correction commit 31e834b **passed (exit 0)**: Rust 318 passed / 50 ignored; Python 2345 passed / 4 skipped / 91 deselected / 5 warnings in 504.01 s; UI 275 passed; bounded secret scan 0 findings. Related geometry and mesh regression tests also passed: 24 tests in 10.62 s. Only documentation changed after this tested source.

Post-correction synthetic set (all valid solids; files remain in ignored work/hull-variation/):

| Candidate | Target Cb | Built Cb | Target LCB/L | Built LCB/L | Mesh/CAD volume relative error |
|---|---:|---:|---:|---:|---:|
| Identity | 0.69887650 | 0.69882537 | 0.50000000 | 0.49999471 | 0.00005973 |
| Fuller, forward | 0.71387650 | 0.71390252 | 0.50300000 | 0.50295877 | 0.00002975 |
| Finer, aft | 0.67887650 | 0.67888411 | 0.49600000 | 0.49595366 | 0.00000915 |

All remain inside the original gates. These are synthetic demonstrations, not KVLCC2 or local-shape accuracy evidence. Refinement was limited to the review's five geometry/input contracts; no reader, application, threshold or holdout change.

## PM continuation: public KVLCC2

Authorized continuation: inspect the actual longitudinal shell support at each waterline; retain only closed supported sections and use builder end caps at the last retained sections. Record omitted lengths per waterline, selected source face indices and axis convention. Do not infer missing shell. Compare the reference with published Lpp/B/T/volume/Cb/wetted area before running variations.

Architecture PASS: use actual CAD waterline cuts, then existing builder. Quality PASS: explicit face selection and omissions, no silent appendage envelope. Coverage WARN: finite sampling must report its resolution and does not establish C2 fairness. Performance PASS: cache public cuts locally; sequential CAD builds.

1. Add failing synthetic tests for per-waterline support and trimming, disjoint support rejection and selected faces; implement in hull_variation_source.py.
2. Inspect all 19 public faces, identify duplicate surfaces and main-shell continuity. Determine aft direction from geometry, not prior naming. Freeze sampling resolution and face choice before comparison. Record all exclusions in ignored work output and summarize ranges in this plan.
3. Add scripts/check_hull_variation.py, including a baseline-only stage. Compare published particulars before creating any variants. Report all differences; do not tune geometry to published integrated values.
4. Build identity and three changed public candidates: +3% and -3% relative Cb and +2 m beam, preserving baseline LCB/L where feasible. Original target gates remain Cb <=0.001, LCB/L <=0.001 and mesh/CAD volume <=0.001. If a request is unreachable, report it rather than relax gates. Output STEP, reports and images under work/ only.
5. Run focused/CAD tests and the quick tier before push. Update results and resume point here. Push only lane/hull-variation; do not merge.

Resume: inspect source waterline cuts and implement support tests. The previous stop is historical, not the final outcome of this continuation.
