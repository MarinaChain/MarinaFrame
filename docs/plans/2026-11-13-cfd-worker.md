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
- PM update: do not install OpenFOAM on this Mac. Use only an official OpenFOAM Docker image on the configured Linux VPS; no apt, sudo or system changes. Host/user belong only in ignored configuration.
- Remote work only in `~/marinaframe-cfd/`; containers named `mf-cfd-*`. Never inspect into or modify other containers/images/volumes. One solver container maximum, `--cpus 5 --memory 12g`, solver under `nice -n 10`. Total lane disk use below 40 GB; retain logs/forces, remove only lane-generated disposable mesh/time data.
- Before every run and every 600 s, record uptime. Two consecutive checks 600 s apart above load 7 trigger `docker pause` of this lane's container and a report. No automatic unpause. Use a host-side monitor so SSH loss does not remove the safety check.
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

## Remote follow-up plan (PM-authorized; original gates unchanged)

Architecture PASS: separate SSH transport and host-side Docker monitor, lane-local files only. Quality WARN: shell arguments require strict validation/quoting; no remote shell strings supplied by a caller. Coverage PASS: test host/path/image validation, command resource limits, load state machine, cancel targeting and progress receipts. Performance WARN: 5-core quota is not five dedicated cores; report allocated time, not measured CPU consumption.

1. Add red tests for configured remote host, official-image allowlist, confined remote paths, resource flags, exclusive lane lock, sustained-load pause, progress and cancel. Implement `RemoteHost` and `RemoteSolverRun` with start/progress/cancel/wait parity. No host address in tracked files.
2. Pin a supported official image by digest, record image/runtime evidence, and probe only that image's runtime/tutorial files. Keep pull storage in the lane's <40 GB accounting even though Docker stores layers globally. Do not prune anything.
3. Prepare public KCS surface under main ignored `work/cfd/`, then write/exercise a free-surface fixed-attitude case. Freeze source/scale/area and numerical scatter before solver runs. Preserve the original G2 targets and thresholds.
4. Run coarse/medium/fine sequentially. Store remote host-side monitoring and durable receipts under the lane root. Pull logs/forces/receipts to main ignored `work/cfd/`. If G2 is not met, do not launch the speed series or KVLCC2 out of order.
5. Run targeted tests and full quick tier on stable source. Update this file with actual results and resume point, commit, push only lane branch, inspect/remove only lane-local `target/` if present.

## Results

Gates committed before checks in `759607d`.

- G0 BLOCKED: no native solver commands on PATH. `brew info gerlero/openfoam/openfoam` required an explicit tap. `brew tap gerlero/openfoam` succeeded, but Homebrew then refused to load the cask from an untrusted tap. No `brew trust`, quarantine change, Docker installation or system setting change was made. The cask itself includes an xattr quarantine-removal postflight. PM must decide the permitted installation route; do not bypass that boundary.
- G1 targeted contracts: **43 passed** (synthetic only). Initial red run failed on missing `vessel_reconstruction.cfd`; later added failed-receipt test failed on unsupported argument before implementation. Force factor tests cover full force and reflected double-body half force. Case publication checks closed oriented facets and 10 GB reserve. Process tests exercise real short Python child programs, not a solver.
- First background quick attempt was NOT a clean baseline: it reached Python collection while this lane's test-first files were incomplete and failed on missing `cfd.case`. Rust format/lint and Rust tests passed in that attempt. This is a lane sequencing error, not a baseline regression. Final quick rerun completed with exit 0: Rust format/clippy/workspace tests passed; Python **2579 passed, 4 skipped, 92 deselected**, 5 dependency warnings, 1286.91 s; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Targeted CFD tests were rerun after the final pressure-field fix: **43 passed**. Logs remain in main `work/cfd/final-quick.log`.
- G2/G3/G4 BLOCKED, not passed: zero physical meshes and zero solver runs. No KCS speed series, no KVLCC2 CT error, no measured cells, wall time or core-hours. Tokyo experiment values are known; submission scatter has not been extracted, so no numerical scatter interval was invented.
- G5: no measured sizing claim is possible. Provisional remote trial budget: 16–32 cores, 64–128 GB RAM, 100 GB scratch for three meshes (0.25/0.75/2.25 million target cells), then three KCS speeds and one KVLCC2 point. This is a planning allowance, not evidence that the gate needs or fits that hardware. Actual runs must record mesh/solver wall time, cells and core-hours before budget refinement. The serial prototype itself does not yet launch MPI or remote jobs.
- Disk: 27 GiB free at intake; 18 GiB at later check while other lanes were active. No large mesh was started. Case admission uses a 6 GB mesh allowance plus triangle storage against the 10 GB reserve. Other lanes can consume disk after admission; a remote/production supervisor still needs continuous disk monitoring.
- Structural index: `refresh-codesight` scanned this worktree successfully (379 libraries, 1517 links), then bootstrap failed with `ModuleNotFoundError: render_bootstrap`. Generated local index was moved to main `work/cfd/codesight-index/` to keep generated files out of the commit; no global helper or shared bootstrap file was edited.

### Implementation limits

The case writer is an unexercised OpenCFD double-body serial setup with SST wall functions and no prism layers. It accepts triangulated surfaces, not raw IGES; CAD closure/reflection is not implemented. It excludes wave resistance and solves neither sinkage nor trim. It therefore cannot replace the requested free-surface validated worker. Surface checks establish edge closure/orientation, not absence of self-intersection. `read_forces` can read synthetic raw files without a receipt; production callers must pass the completed run receipt. Zero exit code is process completion, not numerical convergence. Separate-step logs/receipts need explicit archival between commands. No app route, remote transport or MPI adapter was added. These omissions are explicit resume work, not successful gate results.

## Resume point

1. Software checks completed. Push the lane-only prototype commit; do not merge. Logs are in main `work/cfd/final-quick.log`; targeted CFD tests pass (43). Preserve the worktree for the blocked physical follow-up. No lane-local `target/` exists; the Makefile used its shared build target, which this lane must not delete.
2. PM decides how to install the native runtime without an unapproved trust/quarantine change. Recheck G0 on the selected host and record executable/version evidence.
3. Prepare only named KCS and KVLCC2 public surfaces from the allowed SIMMAN folder. Record scale, draft, wetted reference area, transforms and source provenance. Implement CAD reflection/closure rather than pretending the raw half hull is watertight.
4. Exercise the case writer with the actual supported solver dialect. Fix syntax through failing tests. Add prism layers and measure wall-y+. Implement a free-surface setup and explicit sinkage/trim assumptions.
5. Extract Tokyo submission CT min/max at Fn 0.195/0.227/0.260, write exact provenance/numerical intervals, and commit them BEFORE physical runs. Do not widen them later.
6. Run the three-mesh KCS study at Fn 0.227, then speed series only if G2 passes; then KVLCC2. Check disk reserve before every mesh and record actual cells, wall seconds and allocated core-hours per mesh/solver stage. Replace provisional host allowance with measured scaling.
7. Add durable staged execution, app worker integration and remote/MPI transport only after local physical gates give usable evidence. Preserve failed attempts and never turn process exit zero into physical-validation status.
