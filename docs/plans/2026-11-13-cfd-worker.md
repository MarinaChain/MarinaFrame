# CFD worker implementation plan

> **For Claude:** Use executing-plans to implement this plan task by task.

**Goal:** Control a separate OpenFOAM resistance process and measure its limits on public KCS and KVLCC2 hulls.

**Architecture:** An independent `vessel_reconstruction.cfd` module owns typed inputs, STL checks, case files, process lifecycle and force records. No imports from the other batch lanes. Solver binaries run as separate processes, never linked. Fixed-attitude, double-body RANS is an initial plumbing check only: it cannot pass the total-resistance free-surface gate.

**Tech stack:** Python standard library, existing Python test environment, external native OpenFOAM, pytest.

## Scope and boundaries

- Branch `lane/cfd-worker`, based on local `continue/v0.5`; work only in `.claude/worktrees/cfd-worker`.
- Run data and meshes only in `/Users/jonathanjie/Documents/workspace/MarinaFrame/work/cfd/` (ignored). No pilot, holdout, sealed, or JBC inputs.
- Do not edit PRD, ROADMAP, shared worker modules or other lane modules.
- Never set `engineering_approved` true; results remain `review_required`.
- No Docker Desktop or system configuration changes. Native Homebrew installation is permitted.
- Own-code runs have no wall-clock deadline. Cancel only on explicit request or resource safety failure. Reserve 10 GB disk before every large mesh; do not start a mesh whose estimated peak output breaches that reserve.
- Limit local solver concurrency to one case and at most two cores while other lanes are active.

## Architecture review before implementation

- Architecture: PASS — separate executable, lane-local types, no shared-module edits.
- Quality: WARN — OpenFOAM versions vary; pin the supported dialect and reject absent executables. Never treat an executable stub as a physical run.
- Coverage: PASS — test closed/open STL, case references, force normalization, malformed/nonfinite inputs, cancellation and failed commands.
- Performance: WARN — the shared disk and native install can block physical validation. Do not substitute empirical predictions for CFD output.

## Frozen gates (committed before any checks)

G0 — Native availability: `simpleFoam`, `blockMesh`, `snappyHexMesh`, `checkMesh`, and `surfaceCheck` must exist in one supported native installation. Record version and installation failure. Missing runtime blocks physical gates, not unit tests.

G1 — Software: all new CFD tests pass, plus `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`. Synthetic force values produce CT = F/(0.5*rho*U^2*S), with explicit full/half geometry multiplier. Unknown sinkage/trim stay null with a reason. Failed/cancelled runs never yield a successful result. Closed oriented triangulation is required before case publication.

G2 — KCS mesh convergence: before speed series, use Fn 0.227, U=1.922 m/s, Lpp=7.2786 m, rho=999.5 kg/m3, nu=1.27e-6 m2/s. Three systematically refined meshes with target cell counts 0.25, 0.75, 2.25 million (actual counts recorded; refinement ratio based on actual cells). Require monotone CT convergence, fine/medium CT difference <=2%, and final-window force drift <=1% over the last two equal windows, each at least 100 samples. Fixed-attitude double-body output is excluded from G2 and G3 total-CT scoring. Stop before any mesh which projects free space below 10 GB.

G3 — KCS total CT: chosen speeds Fn 0.195, 0.227, 0.260; experiment CT 0.003475, 0.003467, 0.003711. Acceptance is inside the min/max Tokyo 2015 submission CT at each speed, extracted and frozen with source/cell provenance BEFORE solver runs. Existing experiment values alone do not establish submission scatter. If scatter is unavailable, this gate is blocked; do not invent a tolerance or replace scatter with experiment error.

G4 — KVLCC2: Fn 0.142, CT reference 0.004110 (second-hand, not a primary experiment). Report signed relative error, scale, wetted reference area, appendages and attitude limits. No pass threshold inferred from this single reference. Free-surface total resistance required to claim comparability.

G5 — Resource accounting: every physical run records actual cells, allocated cores, elapsed wall seconds and allocated core-hours (cores*wall/3600, explicitly not measured CPU consumption). Record mesh and solver separately. No completed solver means zero measured physical runs, not zero-cost validation. Host sizing based on measured scaling when available; otherwise report a provisional budget, not a measured requirement.

## Tasks

1. Commit these gates. Probe Homebrew native formula and runtime; inspect permitted public input filenames only. Run the quick baseline in the background, with logs under main `work/cfd/`.
2. Add `tests/test_cfd.py` for G1 contracts and run to observe missing implementation.
3. Create `src/vessel_reconstruction/cfd/` with typed inputs/results, watertight oriented STL writer, supported double-body case writer, runner/progress/cancel and force reader. Keep free-surface validation explicitly pending unless implemented and exercised.
4. Run targeted tests, then quick tier; fix only lane-owned code. Review simplicity and failure paths.
5. If G0 passes, prepare permitted public hull surface, freeze geometry provenance and measured scatter, run smallest mesh and solver in background without a wall deadline. Check resource safety before refinement. Do not run a speed series before G2.
6. Record results, limitations and concrete resume steps here. Commit and push only `lane/cfd-worker`. Inspect and remove only this worktree's rebuildable `target/` as the last step.

## Results

Not checked yet. Gates above are fixed before checks.

## Resume point

Next: commit the frozen gates, then probe G0 and run baseline quick tests. Do not start physical scoring until G3 submission scatter is frozen and a free-surface setup is supported.
