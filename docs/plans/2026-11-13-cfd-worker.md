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

## Remote follow-up results (2026-11-13)

- PM selected the Linux VPS; no OpenFOAM installation on the Mac. SSH destination is not stored in tracked files. Only public KCS STL was uploaded, plus generated lane monitor code; no pilot data or repository upload.
- Image: official vendor-distributed `opencfd/openfoam-default:2412`, pinned OCI digest `sha256:1ba02114b1c025c370f2e269a07677c16c9bea8d990fcd75ac8378aff9d41b50`, local reported size 469,235,718 bytes. Provenance: https://gitlab.com/openfoam/core/openfoam/-/wikis/precompiled/docker.md and https://hub.docker.com/v2/repositories/opencfd/openfoam-default/tags/2412 . No apt/sudo/system changes; no other container/image/volume modified or inspected into.
- G0 runtime capability on the new authorized backend: v2412; `interFoam`, `blockMesh`, `snappyHexMesh`, `checkMesh`, `surfaceCheck` found in the official image. This is a remote backend replacement, not a relaxation of physical gates. Three short named probes checked runtime/tutorial files, all limited to 5 CPUs/12 GB, network disabled, priority 10.
- `RemoteHost` / `RemoteSolverRun`: explicit configuration, confined names/root, case-only upload, SSH start/progress/cancel/wait/collect, named Docker cancellation, credential-free container, single-lane flock and active-prefix check, detached host monitor, pre-run/600-s uptime checks, pause after >7 sustained over 600 s, conservative 8 GB peak admission allowance and 10 GB host reserve. Remote work + selected image size counted against 40 GB. Pause does not auto-resume.
- G1 targeted contracts: **61 passed** (43 existing + 18 remote). Shell monitor passed `bash -n`. Remote surface diagnostic exercised the real host monitor and receipt path. High-load pause is unit-tested and shell-contract-tested, not live stress-tested on a production host. No deliberate host load was generated.
- KCS geometry preparation: public SIMMAN starboard IGES, scale 230/7.2786 = 31.5994834171, mirrored port side; 83,428 triangles. Initial preparation failed because optional `networkx` was absent. Installed it only under main ignored `work/cfd/python-deps/`, not the shared venv. Second preparation completed and explicitly reported non-watertight. No geometry was silently patched.
- Official `surfaceCheck` diagnostic: **108 illegal triangles**, **2,788 one-face edges**, **201 edges with >2 faces**, **25 disconnected parts**, **255 normal zones**. Exit zero therefore does NOT establish geometry acceptance. Bounds (-0.189877,-0.510222,-0.0000584) to (7.526837,0.510222,0.743683) m. G1 closed-surface prerequisite fails for this preparation. The raw public input needs CAD sewing, trim/duplicate treatment and end/deck closure with geometric deviation checks; indiscriminate triangle hole filling is not acceptable.
- Diagnostic accounting: `kcs-surface-check`, **0 volume cells**, 5-core quota, **6 s wall**, **0.008333 allocated core-hours** (not measured CPU). This was a surface check, NOT a mesh or RANS solution. Logs and receipt copied to main ignored `work/cfd/kcs-surface-check.log` and `kcs-surface-check-receipt.json`. No mesh/time directories were generated.
- G2 remains BLOCKED at the geometry prerequisite: zero convergence meshes/solver runs. Therefore the KCS speed series and KVLCC2 were not started, as required by the frozen order. There is no evidence that five cores are insufficient: geometry, not compute, stopped this attempt. Full-gate core-hours remain unknown; earlier host sizing remains provisional only.
- G3 research: official Tokyo KCS assessment (https://t2015.nmri.go.jp/Presentations/Day2-AM2-KCS-Resistance_SP-Kim.pdf), pages 19/21/23, unfiltered 2015 CT SD%D = 2.4/2.7/1.5 at Fn .195/.227/.260. These are standard deviations, NOT min/max submission bounds. Raw per-speed submission extremes were not found. The frozen min/max gate stays blocked; no interval was invented and no SD substituted.
- Remote API end-to-end check: a generated tetrahedron case uploaded through `RemoteSolverRun.start`, ran `surfaceCheck`, returned progress and completed receipt, **6 s / 0.008333 allocated core-hours**, zero volume cells. This is a synthetic transport check, not KCS resistance. Logs and receipt copied back under main ignored `work/cfd/`.
- Latest measured remote directory bytes: **9,736,005**, selected image **469,235,718** bytes (about 0.479 GB combined before the tiny synthetic case). No running `mf-cfd-*` container at that check; uptime 1-minute load **1.20**. No high-load pause triggered during the short diagnostics.
- Structural refresh scanned the new module; bootstrap again failed on missing `render_bootstrap`. Generated index moved to main ignored `work/cfd/codesight-remote-index/`; shared tooling unchanged.
- CAD root-cause probe: the source has **55 faces**. A single CAD sewing operation at **0.1 mm full-scale tolerance** retained 55 faces in **3 shells**, with **95 free edges**, **0 multiple edges**, **9 degenerated shapes**. Thus independent tessellation is not the only problem; sewing alone does not yield a closed hull. No sewn surface was substituted into scoring, and no wet geometry was changed.
- Full quick tier **exit 0**: Rust format/clippy/workspace tests passed; Python **2602 passed, 4 skipped, 92 deselected**, 5 dependency warnings in **424.52 s**; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Log: main ignored `work/cfd/remote-quick.log`. Source was held stable during this run; only docs changed.

### Post-push security correction

Automated review of `f3f2b6b` identified a real container-to-host boundary flaw: the writable case bind also exposed the executing supervisor and receipt paths. It also identified unbounded Docker log/writable-layer accounting. No long solver runs were started with that version. Correction: host control files remain in the attempt root; only its dedicated `data/` child is mounted. Root is read-only, /tmp is 256 MB no-exec tmpfs, local logs rotate at 2 x 10 MB; generated-case upload rejects executable dictionary constructs/custom libraries, and command options are allowlisted. Added live host free-space checks and a 500 MB bounded-extra allowance with a conservative 39 GB pause threshold. Noclobber host writes avoid silently following pre-existing output targets. Focused regression suite: **63 passed**; new isolation test failed before the correction. This is for trusted generated cases, not an assertion of hostile-case sandboxing. Corrected remote API was exercised on a fresh generated-tetrahedron attempt: read-only root and separated mount completed surfaceCheck, **6 s wall / 0.008333 allocated core-hours**, no volume cells. Final quick tier after this correction completed **exit 0**: Rust format/clippy/workspace tests passed; Python **2604 passed, 4 skipped, 92 deselected**, 5 dependency warnings in **562.29 s**; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Log: main ignored `work/cfd/remote-hardened-quick.log`. Latest VPS check: **9,804,049 lane-directory bytes**, no active lane container, load **0.96**.

### Remote limitations and next work

The remote backend currently launches one command per immutable attempt, not a multi-step mesh/solver pipeline. A preflight failure before container creation is visible in `monitor.log` but does not yet produce a terminal JSON receipt; callers must inspect that log rather than wait indefinitely. Remote cancel before container creation can report a missing container. These startup-state gaps need a follow-up test and durable failure receipt before unattended long runs. Serial command execution receives a five-core quota; MPI is not yet wired. Official probe runs and the surface-check attempt are exited containers retained for evidence; no unrelated containers are touched. No mesh deletions were needed. Docker layer and per-container diagnostic/log storage must remain in future budget accounting. The 600-s safety policy is observation-based (two high samples), not continuous load proof between observations. The production host was not stress-tested to force a pause.

## Resume point

1. Software checks completed. Push the lane-only prototype commit; do not merge. Logs are in main `work/cfd/final-quick.log`; targeted CFD tests pass (43). Preserve the worktree for the blocked physical follow-up. No lane-local `target/` exists; the Makefile used its shared build target, which this lane must not delete.
2. Remote runtime is available and pinned; no Mac installation is needed. Current next physical step is CAD-based KCS closure repair with measured geometric deviation, then a clean surfaceCheck. Preserve failed input/diagnostic evidence. Do not run snappyHexMesh on the rejected surface.
3. Prepare only named KCS and KVLCC2 public surfaces from the allowed SIMMAN folder. Record scale, draft, wetted reference area, transforms and source provenance. Implement CAD reflection/closure rather than pretending the raw half hull is watertight.
4. Exercise the case writer with the actual supported solver dialect. Fix syntax through failing tests. Add prism layers and measure wall-y+. Implement a free-surface setup and explicit sinkage/trim assumptions.
5. Extract Tokyo submission CT min/max at Fn 0.195/0.227/0.260, write exact provenance/numerical intervals, and commit them BEFORE physical runs. Do not widen them later.
6. Run the three-mesh KCS study at Fn 0.227, then speed series only if G2 passes; then KVLCC2. Check disk reserve before every mesh and record actual cells, wall seconds and allocated core-hours per mesh/solver stage. Replace provisional host allowance with measured scaling.
7. Add durable staged execution, app worker integration and remote/MPI transport only after local physical gates give usable evidence. Preserve failed attempts and never turn process exit zero into physical-validation status.

## Batch 13b surface-repair gate (frozen before repair measurements)

Base updated by fast-forward to local `continue/v0.5` at `5dc2585`. All original physical gates and remote production-host limits remain unchanged.

**G6 surface gate:** at model Lpp **7.2786 m** and design draft **0.3418 m**, the repaired KCS surface must be a closed outward-oriented manifold, and OpenFOAM surfaceCheck must report **zero illegal triangles, zero one-face/open edges, zero edges with more than two faces**. Bare-hull wetted area must be within **0.5% of 9.4379 m2** (9.3907105–9.4850895 m2), and displaced volume within **0.5% of 1.6490 m3** (1.640755–1.657245 m3). Source: Tokyo 2015 KCS geometry/conditions, model 1: https://t2015.nmri.go.jp/kcs_gc.html . Rudder area 0.1152 m2 is excluded from this geometry gate; appendage treatment must be stated in resistance runs.

Repair protocol: inspect public IGES per-face topology and bounds; remove only demonstrable duplicate/internal/non-hull patches with a written geometric rule; detect half/full side coverage before reflection. Start OCCT sewing tolerance **0.1 mm at full scale**, i.e. 3.16465 micrometres model scale. Record any later repair tolerance change BEFORE applying it and justify by geometry, never by force or particulars errors. Close deck/transom from existing boundary curves, not a guessed submerged envelope. Tessellate connected topology, weld shared edge nodes, remove zero-area triangles, orient consistently. Report patch counts, removed areas, closure areas and representation error. No scaling or offsets fit to the reference area/volume.

Architecture PASS: lane-local surface module and public preparation CLI, no other lane edits. Quality WARN: disconnected source patches and independent trim tessellation require topology diagnostics before repair. Coverage PASS: synthetic half/full hulls, missing deck/transom, duplicate/internal patches, closure/manifold and exact box area/volume. Performance WARN: CAD preparation local in background, solver/mesh only on VPS; no wall cap.

Tasks: (1) commit G6; (2) diagnose CAD face/edge topology; (3) add failing synthetic repair/measurement tests; (4) implement geometric repair and public CLI; (5) measure G6 and remote surfaceCheck; (6) only after G6 passes, free-surface KCS three-mesh convergence then speed series then KVLCC2 under the unchanged gates; (7) record all actual cell counts, wall seconds, allocated core-hours, quick tier and resume point; commit/push own branch.

Resume: G6 committed as `c07dd64`; topology diagnostic checkpoint follows below. No repaired geometry or physical run checked yet in batch 13b.

### Batch 13b topology checkpoint

- Added an explicit-input, read-only CAD diagnostic CLI, `scripts/diagnose_cfd_surface.py`. It records per-face area, precise bounds, validity and surface type, and sewn free-edge bounds/endpoints. It does not discover other inputs, change tolerances, remove patches, close holes or emit a solver surface.
- Public KCS input has **55 valid trimmed faces**. Sewing at the frozen **0.1 mm full-scale** tolerance gives **3 shells, 95 free edges, 0 multiple edges and 9 degenerated shapes**, reproducing the earlier probe. All faces are individually valid; face validity alone does not establish hull closure. Side bounds show the input is a starboard half (only approximately 0.000105 m negative-y support overshoot), not an already complete hull.
- Free-edge endpoints expose mismatched submerged joins, not only a missing deck: at x=230.4993 m the neighbouring patches end at (y,z)=(1.67274,3.00000) and (1.67553,3.00621) m; another join ends at x=138.2018 rather than x=138.0000 m at z=8 m. These coordinates are full scale. Endpoint differences are diagnostics, not a measured curve-to-curve maximum or permission to increase sewing tolerance. Deck/transom capping alone cannot address these joins. No patch was classified as non-hull or removed without further evidence.
- Raw reports and transfer logs remain in main ignored `work/cfd/kcs-topology-13b.*` and `kcs-topology-detail-13b.*`. No third-party geometry was added to git. Focused tests: **65 passed** (two new synthetic CAD diagnostic contracts plus 63 existing CFD tests). The new helper tests failed first on its absent API, then passed after implementation.
- G6 remains **BLOCKED / unmeasured**: no repaired wetted-area or displaced-volume result, no new surfaceCheck. Frozen limits remain area 9.3907105–9.4850895 m2 and volume 1.640755–1.657245 m3. Prior failed surfaceCheck remains 108 illegal triangles, 2,788 open edges and 201 non-manifold edges; it is not a result for repaired geometry.
- This checkpoint used no VPS container, generated no volume cells, and started no mesh or solver. New physical run count is **0**; no new physical wall time or allocated core-hours are claimed.
- Checkpoint implementation commit: `3b07465`. Structural scan completed (395 libraries, 1,522 import links), but bootstrap failed on the existing missing `render_bootstrap` module. Generated index is archived in main ignored `work/cfd/topology-13b-codesight-index/`; shared tooling was not changed.
- First quick-tier attempt was stopped by the tool's 600-s background limit during Python tests (Rust format/clippy/workspace tests had passed). This is an incomplete test run, not a pass. The full retry completed **exit 0**: Rust format/clippy/workspace tests passed; Python **2,717 passed, 4 skipped, 100 deselected**, 5 dependency warnings, **564.50 s**; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Log: main ignored `work/cfd/topology-13b-quick-retry.log`. Source remained unchanged during the retry; only this results document changed. No lane-local `target/` exists; the shared Rust target must not be removed.

Historical resume (superseded by PM reconstruction direction below): associate each free edge with its source face and sample paired boundary curves. G3 submission min/max bounds remain unavailable; never substitute standard deviations. No frozen gate changed.

### PM-directed section reconstruction (method recorded before measurements; BRep construction later superseded)

Stop sewing source IGES faces. The PM instead authorizes reconstruction from dense OCCT plane sections. G0–G6, including G6's reference values and 0.5% limits, remain unchanged. The earlier sewing repair protocol is superseded as a method, not as an acceptance gate.

1. Slice the source with OCCT at **321 cosine-spaced stations** (dense at both ends), record every x and min/max spacing. Work in transferred full-scale millimetres; divide by 1000 and the fixed 230/7.2786 scale for model metres. Use a flat deck at full-scale **17.19999 m** (model approximately 0.54431 m), above design draft. Bound longitudinal reconstruction by source intersections with that deck; do not extend the underwater hull to above-deck source extremities.
2. Sample each actual section edge, form the outer starboard half-breadth y(z), record multi-valued/overlapping sections and unsupported gaps. Do not infer interior patches solely by face number. Mirror the sections, close the deck and both terminal sections (explicit aft transom), and build a closed OCCT ruled loft solid. Record any end truncation. No particulars-based scale or ordinate fitting.
3. Add synthetic tests first for station density, half-breadth extraction, exact box area/volume, mirrored closed loft and missing/invalid data. Tessellate the connected solid at **0.1 mm model deflection** and angular deflection **0.2 rad**, weld only coincident nodes and reject invalid topology before publication. Record representation settings.
4. Measure submerged volume and wetted skin at the frozen draft, excluding the artificial waterplane. Compare independently with frozen G6; sample distances to the source trimmed IGES (and source to reconstruction), report sample counts and maxima as sampled distances, not a certified Hausdorff bound. Separate intentional deck/end caps from original hull skin.
5. Run official surfaceCheck on the VPS under unchanged limits, record wall seconds/core-hours (zero volume cells for this diagnostic). Only if G6 passes proceed to G2, then speed series, then KVLCC2. Commit after each step; run quick tier before lane-only push.

Resume: section extraction and synthetic box loft are implemented (`624c3c6`, `0a3bb4e`). Public attempts 01/02 stopped at station 239 because the declared deck lies in a source trim gap: lower edge ends near z=0.54430712 m, next edge starts near z=0.54431241 m, deck=0.544312379 m. Before attempt 03, set and record **1 micrometre model-space intersection-height tolerance** for endpoint sampling (clamp to actual segment; do not extrapolate the segment). This is a reconstruction sampling tolerance, not a changed G6 limit or source-face sewing. A synthetic split-box case reproduces the gap before the fix. Larger missing keel/deck intervals still fail. Preserve all earlier failed-surface evidence. Attempt 03 extracted all **321 stations**. Actual spacing is **0.000182970549–0.037274154754 m model scale**, deck **0.544312379191 m**, fixed scale divisor **31.5994834171**. **35 stations** contain internal sampled source gaps that were explicitly interpolated and recorded. Maximum competing breadth is **0.509502 m** (includes centreline/flat-bottom source boundaries; not a shape-distance error). Maximum deck extension in this attempt is **0 m**. The OCCT ruled-solid build is running; do not report a solid, STL, G6 area/volume or sampled-distance result before it completes. Source and station data remain in main ignored `work/cfd/kcs-reconstruction-03/`. Quick tier completed on committed source (`e40d106`) with **exit 0**: Rust format/clippy/workspace tests passed; Python **2,726 passed, 4 skipped, 100 deselected**, 5 warnings in **687.09 s**; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Log: main ignored `work/cfd/reconstruction-quick.log`. No source changed during this check. The OCCT build was **stopped by the tool's maximum 7,200-s background limit**, after all sections were extracted but before any solid output. Only `sections.json` (4,210,870 bytes) remains. This was a harness stop, not numerical convergence or a CAD error result. Do not restart the same task at the already-used maximum allowance. Resume from the saved sections with a smaller, checkpointed construction strategy (for example matched ruled panels or separately persisted loft segments); test that strategy before a new public attempt. No solid, STL, sampled-distance or G6 result is claimed. No VPS run started. No reconstruction G6 measurements yet.

### PM-directed direct triangle strips (current method)

No BRep loft. Reuse all 321 saved OCCT sections. Resample piecewise by normalized arc length with keel, detected chine (turn >= 10 degrees) and deck as fixed knots. Use a common union of normalized knot fractions plus 321 uniform samples so every strip has matching indices. Mirror half-sections; connect skin, flat deck and any flat keel with oriented strips. Planar end caps are triangulated in the yz plane with boundary vertices retained. Reject zero-area facets and validate every directed edge and positive volume before STL publication.

Compute wetted skin by exact linear triangle clipping at z=0.3418 m. Compute volume using signed tetrahedra with origin on the waterplane, so the missing horizontal cap contributes zero; independently test exact boxes and wedges. Do not count waterplane area as wetted skin. Record sampled mesh-to-trimmed-IGES distances separately for original skin and artificial closures. This is a sampled bound, not a certified global maximum. No frozen acceptance gate changes. Long local jobs run detached with nohup, durable logs and completion receipts; short calls check progress.

Direct-mesh implementation committed in `b7e1c91`; measurement CLIs in `84451c7`. Synthetic box and V-wedge tests establish closed directed-edge pairing, positive volume and exact clipped area/volume. Focused CFD suite **77 passed**. Resampling gives **486 points per half-section**, **167 fixed normalized knots**, **626,968 triangles** over all 321 stations. Python topology check passes; this does not prove geometric fidelity or absence of self-intersections.

**G6 FAIL on wetted area**, unchanged frozen limits: volume **1.648273053080 m3**, signed error **-0.0440841%** (inside 0.5%); wetted area **9.615022050855 m2**, signed error **+1.8767104%** (outside 0.5%). No area/volume fitting was done. Retain this failed result. No G2 mesh or solver run may start.

Sampled centroid distances to exact trimmed source IGES, starboard side, not certified Hausdorff bounds: hull skin **1,000 samples**, max **0.089968983 m**, mean **0.001044368 m**; keel closure **506 samples**, max **0.018357955 m**; terminal caps **1,000 samples**, max **0.093304073 m**; intentional artificial deck **640 samples**, max **0.339668 m**. Deck and caps are reported separately because the source does not contain the constructed closure. Sampling uses uniform triangle indices, not an area-uniform distribution; reverse source-to-mesh distances remain pending. Artifacts/logs: main ignored `work/cfd/kcs-direct-mesh-01/` and `kcs-direct-{mesh,distance}-01.log`.

Remote preflight: load 1.79, lane directory 9,804,049 bytes, 173,030,633,472 host bytes available, no active lane container. Surface diagnostic attempt `kcs-direct-check-01` completed under the pinned runner: **11 s wall**, **5 allocated cores**, **0.015277778 allocated core-hours**, **0 volume cells**. This is a surface diagnostic, not a mesh or solver. OpenFOAM reports **152 illegal triangles, 0 open edges, 93 edges with >2 faces**, one connected part and 153 normal zones. Exit zero is not acceptance. Warnings show centreline coordinates near y=-3.47e-18 that OpenFOAM merges while exact-coordinate Python topology treats them separately. Preserve this failed STL; numerical vertex canonicalization needs a synthetic regression before a second diagnostic. No physical mesh/solver runs started. Logs and receipt are archived in main ignored `work/cfd/kcs-direct-check-01/`.

First detached quick tier failed (exit 2) in existing `intake_supervision` Rust reader timing tests: stopped-reader test reported stage `starting`, and reporting-reader test returned `intake_stalled` rather than `intake_worker`. Source unchanged; no unrelated test edits. Full retry completed **exit 0** on unchanged source: Rust format/clippy/workspace tests passed; Python **2,729 passed, 4 skipped, 100 deselected**, 5 warnings in **1,556.46 s**; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Durable log/exit receipt: main ignored `work/cfd/direct-mesh-quick-retry.*`. Structural scan completed but bootstrap again failed on missing `render_bootstrap`; generated index archived under main ignored `work/cfd/direct-mesh-codesight-index/`, shared tooling unchanged.

### Source-first diagnosis and correction checkpoints

PM direction: source distance is the primary reconstruction quality evidence. Re-measure in order: source max/p99/mean, surfaceCheck, then frozen G6. No parameter fit to published particulars.

- Old mesh outlier instrumentation (`5f20c66`) locates worst skin distance **0.089968983 m at (7.403308293, 0.012712906, 0.361950502) m**, forward bulb/upper-stem gap. Old skin distance **p99 0.044896386 m**, mean **0.001044368 m**, 1,000 samples. At x=7.385391718 m, actual source curves end on the centreline at z=0.274453735 and restart at z=0.514716087 m. The old extractor interpolated positive breadth across this empty interval. Stern x=0.174654867 m also contains separate source lobes, with centreline endpoints near z=0.153500866 and 0.299740899 m. Saved profiles include 77–89 missing height samples at the forward stations. This is not explained by insufficient midbody station density.
- `5f20c66` distinguishes gaps bounded by source centreline endpoints from ordinary missing trim joins; `82eff80` welds numerical centreline breadths within **1e-8 m model tolerance** before and after resampling. No source vertex is moved except numerical centreline coincidence. `04d84f1` adds extraction-only and mesh-only controls so no BRep or premature G6 scoring runs.
- Public sections regenerated successfully to main ignored `work/cfd/kcs-sections-04/sections.json`. Mesh attempt 02 failed Python topology after source-gap correction; attempt 03 also failed after omission of duplicate zero-width centreplane skin (`a739f19`). Diagnostic found 28 bad directed edges (14 undirected) where a collapsed centreline station edge receives four strip faces from adjacent stations.
- Synthetic isolated-collapse test failed before `4e87c4c`; side-specific diagonal reconnection passes that synthetic test without moving station vertices. Focused CFD suite **82 passed**. Public attempt 04 nevertheless rejects an **unsupported collapsed centreline branch junction** before publication. This is a second branch-pattern case not represented by the simple synthetic isolated-collapse fixture. Preserve rejection; do not bypass validation or retry parameter guesses. No corrected mesh/STL was published.
- Detached quick tier completed on `4e87c4c` with **exit 0**: Rust format/clippy/workspace tests passed; Python **2,734 passed, 4 skipped, 100 deselected**, 5 warnings in **759.11 s**; UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Log/exit receipt: main ignored `work/cfd/source-first-quick.*`. Source remained unchanged during the run. All local long preparation jobs used nohup and logs. No new VPS attempt, physical mesh or solver run. Last measured physical diagnostic remains 0 cells, 11 s, 0.015277778 allocated core-hours; old G6 and surfaceCheck failures remain the only measured gate results.

Resume: inspect the exact rejected branch junction and its source-edge correspondence; add the matching minimal synthetic fixture before another topology change. The synthetic edge flip alone is not a complete public-hull fix. If the section-strip correspondence cannot represent the source lobes, stop and revise the representation with PM rather than hide the gap or alter G6. Once a closed corrected mesh exists, measure source max/p99/mean, run surfaceCheck, then G6 in the requested order. Do not run G2 until both pass. Quick-tier receipt must be read before lane-only push.

## DTC-first split checkpoint (2026-11-14)

PM supersedes the reconstruction-first sequence, not G0–G6 or the VPS limits.
Track A uses the existing official tutorial DTC STL. Track B starts only once A
is running, triangulates actual IGES faces and uses an established mesh repair
method, not section lofting. No fit to published area or volume is permitted.

### Primary reference located; G-DTC not yet frozen

el Moctar, Shigunov and Zorn (2012), *Duisburg Test Case: Post-Panamax
Container Ship for Benchmarking*, Ship Technology Research 59(3), pp. 50–64,
DOI https://doi.org/10.1179/str.2012.59.3.004 . Publisher-author copy linked by
https://www.uni-due.de/inam/journals.php :
https://www.uni-due.de/imperia/md/content/inam/paper_post_panamax_container_ship.pdf .
Accessed 2026-11-14; downloaded paper/text stay in ignored main
`work/cfd/dtc-reference-20261114/`. No third-party file enters git.

Table 4, printed p. 53 (PDF p. 4), gives measured model total resistance:

| Model speed (m/s) | Published Fn | Total resistance (N) |
| --- | --- | --- |
| 1.335 | 0.174 | 20.34 |
| 1.401 | 0.183 | 22.06 |
| 1.469 | 0.192 | 24.14 |
| 1.535 | 0.200 | 26.46 |
| 1.602 | 0.209 | 28.99 |
| 1.668 | 0.218 | 31.83 |

Use table values, not the inconsistent rounded Fn range in section 3.3 prose.
Table 1, p. 51: Lpp 5.976 m, beam 0.859 m, draft 0.244 m, zero static trim,
volume 0.827 m3 and bare-hull resting wetted area 6.243 m2; scale 1:59.407.
Section 3.3, p. 52: water density 998.8 kg/m3, kinematic viscosity
1.090e-6 m2/s; model free in trim and sinkage. Fixed-attitude tutorial output
cannot silently be called the same experimental condition. Appendix/rudder
configuration must be resolved before scoring.

**Blocker:** this paper contains no quantitative experimental uncertainty
statement. Figure 9 is a plotted CFD comparison, not a numerical scatter table.
No numerical uncertainty or acceptance band is invented here. G-DTC remains
unfrozen, so no DTC surfaceCheck, mesh or solver run has started. This is a source
checkpoint, not fulfillment of the requested gate freeze. The explicit ignored
VPS host configuration from the earlier session was also not found in the lane
run folder; do not guess a host from unrelated SSH aliases.

### Review and resumable steps

- Architecture PASS: reuse the pinned official-image process boundary and host
  supervisor, with the existing one-container/5-CPU/12-GB/nice/load/disk rules.
- Quality WARN: establish measured uncertainty and typical RANS scatter before
  the numeric gate commit; match attitude and appendages explicitly.
- Coverage WARN: staged startup failure receipts and tutorial force scaling need
  tests before unattended pipeline execution; original remote limitations stand.
- Performance WARN: runtime/cells remain unknown; no sizing claim is possible.

1. Obtain a cited quantitative uncertainty source (the underlying SVA report is
   cited in the paper) and a numerical RANS scatter basis. Restore an explicit
   caller-owned ignored VPS configuration. Freeze exact resistance bounds and
   conditions in a commit before **any** DTC run.
2. Record the tutorial STL hash, bounds, scale and appendages; run surfaceCheck
   through the unchanged host monitor. Commit results including diagnostic costs.
3. Freeze the three DTC mesh settings at 1.535 m/s before meshing. Use systematic
   refinement, actual cell counts, monotone resistance, <=2% fine/medium change,
   and <=1% force drift over two final equal windows of >=100 samples. These
   proposed DTC convergence conditions must be committed with G-DTC; they do not
   replace or loosen KCS G2.
4. Run three meshes sequentially, then the six-speed series only after convergence.
   Record actual cells, allocated cores, mesh/solver wall seconds and allocated
   core-hours separately. Keep durable background logs and terminal receipts.
5. Once A runs, replace the section representation for Track B with actual-face
   tessellation plus established repair. Commit method/tolerances before applying;
   add synthetic non-manifold/hole/component tests first. Measure source-distance
   max/p99/mean, then surfaceCheck, then unchanged G6, in that order.
6. Run quick tier with the private identity denylist, read its terminal receipt,
   commit each completed step and push only `lane/cfd-worker`; no merge. Remove
   only lane-local Rust target if it exists, never the shared target.

Current new physical runs: **0**. No new cell count, wall time or core-hour
measurement. Track B has not started; previous failed KCS evidence is unchanged.

Checkpoint quick tier completed with **exit 0** on `8f87545`: Rust
format/clippy/workspace tests passed; Python **2,734 passed, 4 skipped,
100 deselected**, 5 warnings in **611.18 s**; UI **275 passed, 0 failed**;
tracked-text secret scan **0 findings**. Separate tracked-file identity scan with
the private denylist: **0 findings**. Durable log and exit receipt are main
ignored `work/cfd/dtc-source-quick.log` and `dtc-source-quick.exit`. No source
changed during the run. No lane-local `target/` exists; the shared Rust target
is retained. Resume at step 1 above; no physical gate is newly passed.

## PM decisions and frozen G-DTC (before any DTC run, 2026-11-14)

These explicit PM decisions supersede the two blockers above. No DTC run has
occurred before this gate commit. Existing G0–G6 and VPS limits are unchanged.

- Caller-owned configuration: main ignored `work/cfd/remote-host.json`, keys
  `host`, `image` (pinned official digest), `root`. Read it at runtime; never
  copy the host into tracked files or report it.
- **G-DTC, free-attitude condition:** at U=1.535 m/s, total CT on the finest
  converged mesh must be within **+-4%** of measured CT. Across all six speeds
  in Table 4 above, mean absolute relative CT error must be **<=4%**. Use
  CT=RT/(0.5*998.8*U^2*6.243), including full/half force accounting; derive
  reference CT from measured RT rather than the rounded published CT column.
- **Separate fixed-attitude condition:** if the tutorial cannot solve free
  sinkage and trim, declare zero fixed attitude explicitly and use **+-6%**
  at design speed and **<=6%** mean absolute relative CT error across the series.
  This is separately labelled fixed-attitude evidence, not a free-attitude pass.
- Basis is a **PM-set engineering acceptance band**, not a claimed published
  experimental uncertainty: typical RANS scatter against towing-tank data for
  this hull class in published workshop comparisons. Locate and cite at least
  one such comparison when available, but it does not block this gate or runs.
  The primary paper provides no numerical uncertainty; do not manufacture one.
- Match bare hull or rudder configuration to the test and state the evidence.
  Use free sinkage and trim if supported by the tutorial. Any unresolved
  appendage mismatch prevents a comparable-condition gate claim.
- **G-DTC convergence:** three systematically refined meshes at **1.535 m/s**;
  record actual cells and refinement ratios. Require monotone total resistance,
  **<=2%** fine/medium relative change and **<=1%** force drift between two final
  equal windows, each **>=100 samples**. Do not start the speed series before
  convergence passes. Mesh settings must be frozen before meshing.
- Every run records cells, allocated cores, elapsed wall seconds and allocated
  core-hours; mesh and solver costs separately. No successful process exit is
  a substitute for surface, mesh, convergence or physical acceptance.

Next: read caller configuration, inspect only the pinned image's DTC tutorial,
record STL hash/bounds, run monitored surfaceCheck, commit results; then freeze
mesh settings and begin the three-mesh study. Track B follows once A is running.

### DTC tutorial surface and configuration checkpoint

G-DTC committed before all DTC runs as `212fb5a`. Caller-owned configuration
loaded without disclosing its host. Preflight: 0.85 one-minute load,
229,459,107 lane bytes, 469,235,718 selected-image bytes, 172,438,994,944 free
host bytes and no active lane container.

Official v2412 resource `tutorials/resources/geometry/DTC-scaled.stl.gz` was
decompressed without geometry changes. Decompressed STL SHA-256:
`887052c1ed7cc680e11f81f4e86ad7e6ce9d04ea62e8c2148deb5b98c599787c`.
116,062 triangles, 58,033 vertices; bounds (-0.113504,-0.429253,-2.51549e-11)
to (6.16209,0.429252,0.572322) m. SurfaceCheck: **0 illegal triangles, 0 open
edges, 0 non-manifold edges**, one component, one normal zone. This establishes
surface topology, not resistance accuracy.

Tutorial inventory found both `RAS/DTCHull` and **`RAS/DTCHullMoving`**. The latter
supports heave Pz and pitch Ry with rigid-body motion; therefore use the moving
setup and the **4% free-attitude gate**, not the optional fixed-attitude band.
Tutorial is a half-domain (negative y, symmetry at y=0): double the integrated
half-hull resistance for full-hull CT. Moving tutorial mass 412.73 kg corresponds
to half-model displacement; retain original mass/inertia and motion damping.
Tutorial reference points to the 2012 paper. Appendage correspondence still
requires explicit geometry evidence before a physical comparability claim.

All three diagnostics ran in the unchanged safety supervisor at 5 allocated
cores, 12 GB, nice 10, no network, with durable host monitoring:

| Attempt | Result | Volume cells | Wall seconds | Allocated core-hours |
| --- | --- | --- | --- | --- |
| dtc-tutorial-probe-01 | failed path lookup; no surface work | 0 | 6 | 0.008333333 |
| dtc-tutorial-probe-02 | tutorial inventory completed | 0 | 7 | 0.009722222 |
| dtc-surface-check-01 | surface topology passes | 0 | 6 | 0.008333333 |

Logs/receipts remain in main ignored `work/cfd/dtc-*.log` and remote lane attempt
folders. None is a mesh or solver run.

### Frozen DTC mesh settings (before meshing)

Use the official **DTCHullMoving** domain/boxes, three prism layers and six
nested xy-only refinement passes. Systematically refine the background grid in
all axes (round to integers):

| Mesh | x cells | y cells | vertical block counts bottom-to-top |
| --- | --- | --- | --- |
| coarse | 32 | 14 | 38, 38, 3, 3, 30, 15 |
| medium | 42 | 19 | 50, 50, 4, 4, 40, 20 |
| fine | 56 | 25 | 67, 67, 5, 5, 53, 27 |

Keep tutorial geometric grading, nested box bounds, snapping and relative layer
parameters unchanged. Set maxGlobalCells to 6,000,000 as a safety ceiling, not a
target; a truncated refinement cannot count as systematic completion. Use actual
final cell counts for ratios. No extra surface levels. Inlet U=1.535 m/s,
nu=1.090e-6 m2/s, rho=998.8 kg/m3, waterline z=0.244 m. Use transient Euler
moving-grid setup, maxCo=1, maxAlphaCo=0.5, maxDeltaT=0.01 s. Start with 35 s
physical duration; extension may only gather convergence samples, never select
a favourable window. Store every force sample and evaluate the final two equal
windows (>=100 samples), report elapsed physical time. Keep at most two output
time directories; retain full force and motion histories. Run mesh/checkMesh
and solver as separate monitored stages, record their costs separately. Reject
failed mesh topology before solver. Five MPI ranks maximum for the solver;
meshing is serial under the same 5-core quota. Resource admission retains the
8 GB peak allowance and 10 GB free reserve before every stage. If a stage does
not fit, stop and report, rather than reduce fidelity after seeing forces.

### Track A mesh launch / Track B method checkpoint

Coarse attempts 01 and 02 failed before creating volume cells because strict
shell flags were enabled while sourcing the vendor environment (unset variable,
then setup return handling). Each costs **6 s, 5 cores, 0.008333333 allocated
core-hours**, zero cells. Attempt 03 sources the vendor environment first, then
enables strict flags; geometry and mesh settings are unchanged. It is running
under the detached host supervisor with per-command logs and
`data/stage-accounting.csv`. Resume remote `dtc-coarse-mesh-03`; do not launch
another solver container while it is active. Main ignored launcher:
`work/dtc_mesh.py` in this worktree; receipt collector `work/dtc_wait.py`.

Track B begins while A meshes. Method frozen before public repair: actual OCCT
trimmed-face triangulation at **10 mm full-scale deflection**, angular deflection
**0.2 rad**, fixed scale divisor 230/7.2786, mirror starboard side with reversed
winding. Merge coincident nodes at **7 decimal model-metre digits**, as in the
preserved raw-face preparation; no sections, lofts or reference-based offsets.
Use established **PyMeshFix 0.18.1** (MeshFix algorithm), `clean_from_arrays`
with `joincomp=True`, `remove_smallest_components=False` so components are not
silently discarded. Keep pre-repair mesh and record counts, topology and volume
before/after. Record all library defaults and warnings. A single method trial,
not a tuning loop. Test hole filling/component joining on synthetic meshes
before public input. Reject non-closed/inconsistent output rather than publish.
Only then measure sampled exact source-distance max/p99/mean (original skin and
intentional closures separately where identifiable), then official surfaceCheck,
then frozen G6. No area/volume result may drive repair parameters. The isolated
optional repair dependency is in this worktree's ignored `work/meshfix-deps/`;
the shared venv is unchanged.

### First measured DTC volume mesh: rejected quality

`dtc-coarse-mesh-03` completed meshing with **359,241 cells**, then the
all-geometry/all-topology check reported **2 failed checks** despite process
exit zero: **29,942 cells with determinant <0.001**, minimum determinant
5.35573e-7, and **15,520 concave cells**. Additional diagnostics: 207 concave
faces, one warped face (flatness 0.695891); max non-orthogonality 69.9546,
max skewness 2.74243. Cell volumes, connectivity and single region pass. The
stage-level text gate rejected the mesh and returned failed receipt. **No
solver ran**. Do not silently lower this quality criterion or claim convergence.
Next diagnosis: localize failed-cell sets relative to refinement transitions and
layer termination, compare the official background grid before changing mesh
parameters. All frozen force bands stay unchanged.

Allocated resource accounting (5-core quota; not measured CPU consumption):
background/features/refinement **36 s / 0.050000 core-hours**;
snappyHexMesh **282 s / 0.391667 core-hours**;
checkMesh **11 s / 0.015278 core-hours**. Full monitored attempt **332 s /
0.461111 core-hours**, including 3 s supervisory overhead. Mesh stage log sum
**329 s**. Main ignored evidence `work/cfd/dtc-coarse-mesh-03-result.log`.
No sustained-load pause occurred; run was shorter than 600 s. The three-mesh
study and speed series remain incomplete.

Track B actual-face repair is running detached at main ignored
`work/cfd/kcs-face-meshfix-03/` with log `kcs-face-meshfix-03.log`, local PID
70189 at launch. Synthetic hole closure and manifold checks passed, but the
library printed `MeshFix could not fix everything` even on these fixtures;
therefore no claim of intersection-free synthetic repair. Public import has
83,428 triangles; MeshFix reports non-manifold cuts, 102 duplicate triangles
removed, component joining, and 16,819 initially intersecting triangles. No
repaired output or source-distance/G6 measurement exists yet. Earlier startup
failures remain in logs: int32 face-array API requirement, then optional
networkx import path (must be set before importing trimesh). No public geometry
parameters changed between preparation attempts.

Track B repair completed: **25,376 triangles**, Python edge closure and winding
checks pass. Raw input had **83,428 triangles**. The large geometry change is
not evidence of fidelity. The repair metadata's 1.300915585716 m3 signed
full-closed volume is an algorithm diagnostic, **not** a clipped design-draft G6
result. No reference was used for tuning. Exact trimmed-source distance sampling
is now running detached (`work/track_b_distance.py`, log main ignored
`work/cfd/kcs-face-meshfix-03-distance.log`). It samples 1,000 starboard centroids;
closure/skin attribution and reverse source-to-mesh distance are not yet
available. Do not claim source fidelity, surfaceCheck or G6 before measurements.
Separate private identity scan on the checkpoint: **0 findings**.

### Track B source-first result: repair rejected

Measurements followed the required order. Exact trimmed-source distances at
1,000 uniform triangle-index starboard centroids: **max 0.404878332 m,
p99 0.153896050 m, mean 0.002889370 m**. These mix skin and generated closures,
are not area-uniform or a global bound, and omit reverse distance. Thus they
cannot establish skin fidelity.

Official `kcs-face-meshfix-check-01`: **0 illegal, 0 open, 0 non-manifold edges**,
one component/normal zone; **0 volume cells, 6 s, 5 cores, 0.008333333 allocated
core-hours**. However, bounds now end at **x=3.45733 m** rather than the source
forward end near 7.52684 m. The repair lost a large hull region despite the
explicit `remove_smallest_components=False`; library cleanup after joining is
not a geometry-preservation guarantee. Surface topology alone is insufficient.

Then frozen G6 clipping at z=0.3418 m: wetted area **5.142457739389 m2
(-45.512691%)**, displaced volume **0.803020084870 m3 (-51.302602%)**.
**G6 FAIL**, unchanged 0.5% bands. Reject this repair; do not use it for CFD or
tune it to published particulars. Preserve all evidence under main ignored
`work/cfd/kcs-face-meshfix-03/` and `kcs-face-meshfix-check-01.log`. A robust
repair that preserves all source regions remains unimplemented; this first
established-method trial does not solve Track B. Next method review should
consider a source-distance-constrained implicit reconstruction, with synthetic
branch-junction and region-preservation tests before public application.

Workshop comparison for the PM band rationale (not DTC uncertainty): Tokyo 2015
KCS resistance assessment, Kim et al.,
https://t2015.nmri.go.jp/Presentations/Day2-AM2-KCS-Resistance_SP-Kim.pdf ,
pages 19/21/23, reports CT submission standard deviations relative to experiment
of **2.4%, 2.7%, 1.5%** at Fn **0.195, 0.227, 0.260**. KCS is another container
hull; this is relevant hull-class scatter, not a DTC uncertainty estimate, min/max
range or statistical guarantee for the PM 4% band. The citation was already
recorded in the earlier source research above; no numerical band changes.

Final VPS observation: no active lane container, load **5.14**, lane directory
**324,099,683 bytes**, selected image **469,235,718 bytes**, host available
**172,453,351,424 bytes**. All failed attempts and diagnostics retained; no
unrelated resources inspected or removed. No resource pause or automatic
unpause occurred.

Final quick tier **exit 0**: Rust format/clippy/workspace tests passed;
Python **2,734 passed, 4 skipped, 100 deselected**, 5 warnings in **693.22 s**;
UI **275 passed, 0 failed**; tracked-text secret scan **0 findings**. Private
identity scan also **0 findings**. Log/terminal receipt: main ignored
`work/cfd/dtc-mesh-quick.log` and `dtc-mesh-quick.exit`. Only documentation changed
during this check; all experimental launchers/dependencies remain ignored.

Resume: diagnose the rejected DTC coarse mesh check sets before running any
solver or refining the study. G-DTC remains frozen and unscored, not failed
resistance. Three-mesh convergence and speed series are incomplete; there is
one measured DTC volume mesh and **zero resistance solver runs**. Track B's
first actual-face repair is rejected for source-region loss and G6 failure;
no parameter tuning or second geometry algorithm trial started. All steps and
costs above are evidence checkpoints, not a completed solver pipeline.

## PM official-tutorial reference direction (before reference run)

Track B is **parked**. Its rejected MeshFix artifacts remain evidence only;
no further KCS repair methods or measurements will run. PM will supply another
geometry route.

First run the pinned official v2412 **DTCHullMoving** meshing setup unchanged:
blockMeshDict, snappyHexMeshDict, meshQualityDict, all six topoSet/refineMesh
boxes and the Allrun meshing order (surfaceFeatureExtract, blockMesh, six
pairs of topoSet/refineMesh, snappyHexMesh). Preserve the compressed tutorial
STL input as Allrun copies it. Record hashes of the dictionaries before and
after execution. Do not substitute the earlier coarse block grid or cell ceiling.
Run checkMesh with tutorial meshQualityControls and record basic plus extended
checks; failed extended checks are observations of this unchanged reference,
not silently discarded or automatically proof that the tutorial's own criteria
failed. Under PM direction run the solver on that reference mesh at **1.535 m/s**
after recording mesh evidence. Capture all force/motion histories and costs.

G-DTC and its convergence rules remain frozen. This reference replaces the
previous custom-coarse-first sequence, not any force acceptance band. Only after
the reference solver run build a systematic study around tutorial settings.
Same one-container, 5-CPU, 12-GB, nice-10, host monitor/load-pause/disk rules.
Account mesh, initialization and solver separately. No other host resources
may be changed. Commit after reference mesh and after solver result; quick tier
before lane-only push, no merge.

Reference solver protocol before launch: use DTCHullMoving's own transient
Euler/PIMPLE controls, including endTime 35 s, maxCo 25, maxAlphaCo 15 and
maxDeltaT 0.05 s. This PM reference run supersedes the earlier custom-study
solver-control proposal for the reference only. Change only speed from 1.668
to **1.535 m/s**, decomposition from eight ranks to **five** (hierarchical
5x1x1 to comply with the quota), and purgeWrite from zero to **two** for disk
safety. Water nu=1.09e-6, rho=998.8 and zero surface tension already match the
tutorial. Retain all force samples and solver/motion logs. No mesh setting
changes. Report any numerical failure; do not quietly reduce Courant settings
or force a resistance acceptance result. The unchanged-reference measurement
is not a converged finest mesh and cannot pass G-DTC by itself.

### Unchanged official mesh result

`dtc-official-mesh-01`: **848,025 cells**, **854 s wall**, **1.186111 allocated
core-hours** at five-core quota. Mesh generation stages total **796 s /
1.105556 core-hours**, checkMesh stages **50 s / 0.069444 core-hours**, monitor
and setup overhead **8 s / 0.011111 core-hours**. All system dictionaries and
dynamicMeshDict matched their pre-run hashes. Full six-pass Allrun meshing
sequence used; no mesh dictionary changed.

SnappyHexMesh's own final mesh-quality report: **zero faces in error** under
tutorial controls. `checkMesh -meshQuality` also reports zero violations of
those controls, but its standard geometry check reports **one skew face**
(max 5.23784), so its summary is **Failed 1 mesh checks**. Basic checkMesh has
the same single failure. Extended check adds **69,245 low-determinant cells**
(minimum 5.44737e-7) and **26,920 concave cells**, summary **3 failed checks**;
236 concave faces and four warped faces are additional diagnostics. Thus the
earlier extended determinant/concavity failures also occur on the unchanged
shipped tutorial. These are measured observations, not claims the checks pass.
PM explicitly directs the reference solver run on this mesh; retain warnings
in the force report. No force gate changed. Durable evidence main ignored
`work/cfd/dtc-official-mesh-01-result.log` and `dtc-official-mesh-quality.log`;
remote attempt retains hashes, individual logs and stage-accounting.csv.
Load observations 1.55 at startup and 3.93 after 600 s; no pause triggered.

### Reference solver launched / quick-tier checkpoint

`dtc-official-solver-01` is running detached on the reference **848,025-cell**
mesh at **1.535 m/s**, five MPI ranks, under the unchanged host supervisor.
Initialization stage costs: setFields **3 s / 0.004167 allocated core-hours**,
decomposePar **8 s / 0.011111**, renumberMesh **8 s / 0.011111**. Solver selected
rigidBodyMotion/Newmark and is initializing. No completed force history, solver
wall total or resistance result is claimed yet. Durable files are remote
`dtc-official-solver-01/data/log.interFoam`, `solver-accounting.csv`,
`postProcessing/forces/`, with attempt-level monitor/load/receipt paths. Local
collector `work/dtc_reference_wait.py dtc-official-solver-01`; do not start a
second solver while active. It records every terminal state including pause.

Quick tier completed **exit 0**: Rust format/clippy/workspace tests passed;
Python **2,734 passed, 4 skipped, 100 deselected**, five warnings in **732.02 s**;
UI **275 passed, 0 failed**; secret scan **0 findings**. Separate private identity
scan **0 findings**. Main ignored log/receipt `work/cfd/dtc-official-quick.log`
and `dtc-official-quick.exit`. Only tracked documentation changed during checks.
Track B remains parked. No systematic refinement study or speed series started;
wait for this reference solver's force-history result first.

### Reference solver safety pause (no automatic unpause)

The host supervisor **paused** `mf-cfd-dtc-official-solver-01` after load
**12.15** at 01:28:26 and **7.86** at 01:38:30, 604 s apart; startup load was
3.60 at 01:18:25. Docker confirms `paused=true`. Later load 3.55 is not
permission to resume. **PM decision required before unpause**; no second
container or solver was launched. Track B stays parked.

Mesh remains **848,025 cells**. Container start 17:18:26 UTC to pause marker
17:38:30 UTC gives **1,204 s pre-pause wall / 1.672222 allocated core-hours**
(five-core quota, includes initialization; excludes ongoing paused reservation).
Initialization stages are the 19 s recorded above. Last completed solver step
reports **ClockTime 1,173 s** and **ExecutionTime 888 s**; these are partial
solver-reported times, not a completed-stage receipt or measured total CPU.
No terminal completion receipt exists while paused; final allocated accounting
must include later paused elapsed time per the existing receipt convention.

Partial force history collected: **10 samples**, physical time 0.000120005 to
**0.00311429 s**; next step began at 0.00385657 s. Half-hull total Fx ranges
**-79,778.83 to +17,526.89 N**; last **+970.9435 N**. These are severe startup
transients, not resistance estimates. Do not score CT, force drift or G-DTC
from ten startup samples. Full force rows and motion-log tail archived in main
ignored `work/cfd/dtc-official-solver-01-paused-forces.log` and
`dtc-official-solver-01-state.log`; remote originals remain intact. Attempt
uses 254,056,786 data bytes; host available 171,880,181,760 bytes.

The local waiter detected paused state, then failed collecting nonexistent
`run-receipt.json`/`solver.log` (these are written only after container exit).
This is a **collector failure, not solver exit**. Direct read of pause marker,
load log, Docker state and live case log established the outcome above. Resume:
PM must decide whether to resume this paused reference on the shared host;
fix pause-aware collection before using this waiter for another long run.
No solver controls, safety limits or frozen gates changed.

## PM operating-limit change and throughput measurement

PM manually unpaused the reference container after observing baseline host load
1.97 (approximately 2). This is authorization to continue the existing solver,
not restart it. For **DTC only**, replace the old load>7 rule with **10-minute
load average >9 continuously for 10 minutes**. CPU quota 5, memory 12 GB,
nice 10, one-run lock, disk limits and no automatic unpause remain unchanged.
This is a **PM change to an operating limit**, not G-DTC or convergence gates.

Linux provides only 1/5/15-minute load values. Operational implementation will
sample its 1-minute value every 30 seconds and compute a time-weighted rolling
600-second mean, requiring a complete window; pause only when that rolling
mean stays above 9 for a further 600 seconds. Log raw samples and rolling mean.
This is an explicit rolling estimate, not a falsely labelled native 10-minute
kernel statistic. The existing monitor is alive (PID 3352544 at inspection) but
retains the old rule/state; replace only that supervisor with a detached
pause-aware monitor under the same lane lock. Never restart the container.

Record timestamped completed force-sample time/count at least 1,800 seconds
apart with no pause in the measurement window. Project remaining wall time
and allocated core-hours to tutorial endTime=35 s from measured simulated-time
advance. Also report sample throughput and the >=200-sample lower bound needed
for two final >=100-sample drift windows. This does not guarantee convergence;
report startup/nonlinear-rate uncertainty and no finite validated convergence
ETA if stability is not yet established. Commit/push this projection early.
If projected wall exceeds 48 hours, leave solver/monitor running and stop further
CFD work for the PM compute-host decision. Track B remains parked.

Monitor replacement completed without restarting/unpausing the solver: old
lane supervisor PID 3352544 was checked against this exact attempt's cwd, then
terminated without its old signal trap (which would pause the container).
New detached wrapper PID **3381983** runs host Python `monitor-v2.py` under
`python3 -I`, acquires the same `.solver.lock`, logs every 30 s, and pauses this
container on monitor failure or disk/resource breach. It has no start/unpause
operation. Wrapper/script/log remain in the lane attempt root, outside the
writable container bind. Docker start timestamp remains **17:18:26.353641585Z**.

First rate sample: epoch **1794591897.1224945**, completed physical time
**0.00474757 s**, **12 force samples**, state running; load1 10.23 (no complete
600-s rolling window yet). Lane directory 699,669,173 bytes; host free
171,859,873,792 bytes. Require >=1,800 s continuous running after this sample
before reporting measured throughput. Durable `rate-start.json`,
`operating-v2.csv`, `load-v2.log`; projection will be `rate-projection.json`.
Local launch source is ignored `work/dtc_monitor_v2.py`; no caller host copied
into tracked documentation. Historical safety-pause.txt is retained as evidence
but no longer defines the live state; inspect Docker and v2 monitor records.

### New operating rule triggered before 30-minute measurement

V2 monitor paused the same container at epoch **1794593115.1647146**. First
complete rolling mean above 9 was **12.7642** at epoch 1794592505.6185205;
it remained above 9 for **609.546 s**, ending at **26.5904**. Raw load1 peaked
at **34.28** during this interval. Docker confirms paused, unchanged original
start timestamp. Monitor remains active; **no automatic unpause**. This is a
resource-safety interruption under the new PM operating rule, not a physical
gate result. No solver restart, other container or Track B work.

The requested **>=30-minute uninterrupted rate measurement is blocked** by the
pause after **1,218.042 s (20.3007 minutes)**. Completed physical time advanced
from **0.00474757 to 0.0185392 s**, force samples **12 to 19**. Interval cost
**1.691725 allocated core-hours** at five-core quota. Last complete step reports
ClockTime **2,737 s**, ExecutionTime **1,829.96 s**; next physical step
0.0223581 s was incomplete. Existing 848,025-cell mesh remains unchanged.

**Early diagnostic projection, explicitly NOT the requested 30-minute result:**
partial-window rate **0.0407620 simulated s/wall hour**, **20.6889 force
samples/hour**. Constant-rate extrapolation from 0.0185392 to tutorial 35 s:
**858.19 remaining wall hours / 4,290.94 allocated core-hours**. At the same
sample rate 200 samples take **9.67 h**, but those could still be startup data;
no validated finite ETA for converged resistance exists. Adaptive timestep is
still increasing and the host was heavily contended, so this extrapolation
cannot be treated as a stable runtime prediction or compute-host requirement.
It nevertheless greatly exceeds 48 h and is recorded early for the PM.
A valid 30-minute rate still requires a PM-authorized uninterrupted interval.
Do not bypass safety just to complete the rate window. G-DTC remains unscored.

Evidence: main ignored `work/cfd/dtc-rate-paused-evidence.log`,
`dtc-rate-result.json`; remote `operating-v2.csv`, `safety-pause-v2.json`,
`rate-interrupted.json`. At pause lane directory **699,696,788 bytes**, free
host bytes **171,267,104,768**. Disk reserve was not the trigger. Original
solver/force logs are retained. PM must choose a dedicated host or explicitly
resume this paused run; the instruction to leave it going for a >48h projection
does not override the mandated resource pause.

Quick tier **exit 0**: Python **2,734 passed, 4 skipped, 100 deselected**, five
warnings in **974.14 s**; UI **275 passed, 0 failed**; Rust checks/tests passed;
secret scan **0 findings**, separate private identity scan **0 findings**.
Main ignored `work/cfd/dtc-rate-quick.log` / `dtc-rate-quick.exit`. Only tracked
documentation changed during this run. Resume at the PM resource decision;
no more runtime or gate changes made.

## PM KVLCC2 double-body direction and frozen G-KV-DB (2026-11-14)

This section supersedes the DTC continuation and KCS-first run order, not their
historical results or gates. **Stop DTC** and preserve its logs/forces. The
~858 h partial-window projection (~860 h) is not a stable throughput estimate.
Free-surface RANS is reserved for finalists on a larger machine later. Track B
remains parked. No new physical run has started at this gate freeze.

### Fixed conditions, geometry decision and gate

- Steady `simpleFoam`, SST RANS, fixed zero attitude, flat waterplane represented
  by a symmetry plane. No moving surface, sinkage, trim or wave force in CFD.
- KVLCC2 scale 1:58, Lpp **5.5172 m**, T **0.3586 m**, nominal Fn **0.142**,
  U **1.047 m/s**. Use the rounded PM draft as stated; record its small difference
  from 20.8/58 without fitting geometry. Water: rho **999.6 kg/m3** (assumed fresh
  water, not a published density), nu **1.2557626956521737e-6 m2/s**, derived from
  the published model Re **4.6e6**. Source: permitted main ignored
  `work/perf-eval/kvlcc2-cases.json`, consistent with the performance plan.
- Community solid: main ignored
  `work/cfd/sources/grabcad/kvlcc2_solid-1.snapshot.1.zip`, SHA-256
  `5a7eda8ca298ab3783df53386e826f8f2aafc385f5290924e9658cd7e55151d1`.
  Extract only its STEP into a new empty directory. Native numeric coordinates
  mean physical metres despite STEP millimetre declarations; apply the explicit
  1000-mm-per-coordinate interpretation, then divide by 58. Native x increases
  aft and z points down. Full hull: do not mirror across the centreplane.
- PM accepts this source for CFD on volume **+0.008940%**, Lwl **+0.000460%**
  and the recorded source-distance evidence. Original wetted-area gate **FAIL
  (+1.855346%) stands**; it is not reruled. Analytic curved-shape checks found no
  area-code bias. Reference convention is the PM's working attribution, **not
  independently confirmed**. Mesh distance maxima can be dominated by
  tessellation; complete exact common-skin statistics remain unavailable.
- Normalise all coefficients with published bare-hull **S=8.0838 m2**, never
  the computed area. State no rudder/appendages and unresolved experimental
  attitude correspondence. Keep `engineering_approved=false`, `review_required`.
- **G-KV-DB:** CT_est = CV(double-body, finest converged mesh) + Cw(thin-ship,
  same geometry/condition/reference area). Require **abs(CT_est/0.004110-1)<=0.05**,
  i.e. **0.0039045 <= CT_est <= 0.0043155**. This is a PM-set hybrid estimate
  gate, not a free-surface RANS pass or experimental uncertainty statement.
- **Convergence:** three systematic meshes, monotone CV, fine/medium relative
  difference **<=2%**; final force drift **<=1%** between the final two equal
  windows, each **>=100 samples**. Record actual cells and refinement ratios.
  Do not select favourable windows or stop after two meshes.
- Report implied **(1+k)=CV/CF**, CF=0.075/(log10(Re)-2)^2 (ITTC-57), alongside
  prior Holtrop-type **1.36 (1982)** / **1.34 (1984)**. Their eight-speed mean
  errors were +20.9% / +18.9%; design-point errors +20.4% / +18.4%.
- Thin-ship implementation/protocol is on merged `origin/continue/v0.5` in
  `docs/plans/2026-11-13-thin-ship.md`; use matching source via `git show`, not a
  branch merge. Its closed-end/immersed-transom limitations must not be bypassed
  by deleting source regions or forcing endpoint breadth to zero. If this hull
  cannot be represented, report Cw and G-KV-DB blocked rather than invent a term.

### Operating rules for this track

One job/container at a time, only `~/marinaframe-cfd/`, names `mf-cfd-*`, pinned
official image from main ignored `work/cfd/remote-host.json`; host never tracked
or printed. Five-CPU quota, 12 GB RAM, nice 10, same lock, no network, host-side
monitor and isolated control paths. Prefer startup load1 **<4**. Apply PM's
**10-minute rolling load estimate >9 continuously for a further 10 minutes**
to this track too (30-s load1 samples, complete time-weighted 600-s window).
Pause and report; never automatically unpause. Preserve 10 GB host disk reserve,
<40 GB lane accounting including image/layers/logs. **Stop and report if any
run projects above 24 h**; this replaces the earlier DTC 48-h reporting rule,
not an arbitrary wall timeout. Record mesh/solver cells, allocated cores,
wall seconds and core-hours separately, including failed/interrupted attempts.

### Design review and committed execution steps

Architecture PASS: reuse separate solver/image/SSH boundary; a symmetry-plane
case is distinct from the old reflected-full-body writer (force factor 1 vs .5).
Quality WARN: old writer has no layers and is not physical evidence; test new
boundary/force accounting and actual v2412 syntax before use. Coverage WARN:
exercise rolling-load monitor, terminal states, symmetry fields and geometry
clipping on synthetic cases. Performance WARN: measure coarse iteration cost
before medium/fine admission; no claim of a <24-h fit without measurements.

1. Commit this gate and decisions before **any** new run. Inspect the exact DTC
   container and stop it without unpausing; retain all evidence and final state.
2. Inspect source units/topology; generate model-space wetted solid/STL with
   explicit waterplane closure for meshing, retaining all physical skin. Freeze
   tessellation and three systematic mesh settings before public preparation.
   Run topology/source checks before mesh, no area fitting. Commit evidence.
3. Add failing synthetic tests for symmetry-plane case output, force factor,
   wall layers/y+ diagnostics, final-window convergence and rolling-load safety.
   Implement only lane-local CFD code/scripts; run focused tests; commit.
4. Run monitored surfaceCheck, coarse mesh/checkMesh, then solver sequentially.
   Capture all forces and y+, cells/stage timing and runtime projection early.
   Stop on safety, mesh failure or >24-h projection. Commit each stage result.
5. Only when admitted, run medium/fine sequentially; compute Cw only through a
   source-supported adapter and report its panel/angle sensitivity. Score the
   fixed gate only after all prerequisites pass. Never substitute empirical CV.
6. Run quick tier with main venv and inline private identity denylist. Read the
   terminal receipt, record limitations/resume point, commit and push only
   `lane/cfd-worker`, no merge. Remove only lane-owned target if present.

Gate freeze commit: `1306382`. DTC preflight finds the exact reference container
already **exited, code 137**, finished 2026-11-13 18:08:01 UTC; no restart,
unpause or stop command was sent. No active lane container. Load1 **0.95**;
lane directory **699,698,787 bytes**; host free **170,586,517,504 bytes**.
Evidence: main ignored `work/cfd/kvdb-preflight.log`.

Preparation settings frozen before public preparation: exact STEP unit
interpretation above, CAD tessellation **0.005 m model deflection**, angular
**0.1 rad**, clipped at model draft **0.3586 m**, no reference-based offsets.
Inspect the clipped native aft closure before thin-ship adaptation; do not
invent a transom correction. Meshing settings will be separately committed
before meshing, after geometry and boundary contracts are tested.

Process deviation: a read-only helper was mistakenly invoked with tool-level
worktree isolation despite the explicit ban. It was stopped immediately and
returned no findings; no helper code/result is used. A subsequent worktree list
shows no checkout for that helper. All lane work remains in `cfd-worker`.

### Solid and symmetry-case checkpoint

Source STEP SHA-256 **fc06135c3b170e6222addcb02e1b99d75f97aae9f9c478303a17ea0143ab76ab**;
one valid solid and one closed shell. At the explicit rounded model draft
0.3586 m (native plane -20.7988), clipped volume **1.600124995282 m3**, true
wetted skin **8.233565747674 m2**, artificial waterplane **4.975760962726 m2**.
These are diagnostics, not a rerun or reruling of the hull-ends gate. The
published **8.0838 m2** remains the CFD/coefficient denominator.

Aft source closures retain **0.004120524282 m2** below the waterline (two patches,
centres native x≈5.500937, z≈-20.07194). Thus this source has a real immersed
transom; it cannot be silently converted to the thin-ship API's closed-ended
hull. Merged `resistance_thin_ship._offsets` explicitly raises **closed ends
required; immersed transom correction is not implemented** for nonzero endpoint
breadths. **Cw and G-KV-DB are blocked pending a source-supported transom
formulation**, not assigned zero or an invented correction. Double-body CFD
can remain a separate CV measurement; no total-CT gate claim is possible yet.

The first exploratory inspection wrongly counted the cap through a spline bbox
classification (**13.2093267104 m2**, invalid diagnostic). The tested classifier
uses the actual planar surface/normal/location and excludes only the waterplane.
Preserve that failed attempt, do not use its area. A synthetic tilted closure
also reproduced the too-strict axis-normal aft diagnostic; candidate location
classification retains curved closure patches without altering their area.
Inspection helper commits **c09d8a2**, **a4b9db4**; tests first failed on missing
helper and on tilted closure, then passed. Final run exit **0**; evidence main
ignored `work/cfd/kvdb-inspection-final.{log,exit}` and
`kvdb-solid-inspection-final.json`. An earlier harness-limited inspection was
interrupted, then rerun detached with durable logs/receipt; no concurrent retry.

Case writer commit **d01840a** adds explicit fixed-waterplane symmetry mode,
full-width force multiplier **1**, three requested prism layers and y+ output.
Old reflected mode/default force factor **0.5** remains separate. Symmetry fields
and clipped-domain precondition were tested red then green. **87 CFD tests
passed**. This is generated-case evidence only, not exercised v2412 syntax,
layer coverage, wall-y+ quality or physical accuracy. No VPS diagnostic, mesh,
solver or new allocated core-hour cost has been incurred in this track.

The first quick tier began on c09d8a2 and source changed during its run, so it
cannot count as a stable-source delivery check even if its receipt says zero.
Run a fresh quick tier on d01840a or later stable source before push.

Resume: add/test the new rolling-load host monitor (the reusable remote.py still
has the historical >7 policy), then source-preserving wetted STL preparation and
frozen systematic mesh settings. Do not launch through the old policy or claim
G-KV-DB while Cw's immersed-transom formulation is missing. No new physical run
has started. Private tracked identity scan completed exit **0**, **0 findings**.
No managed `.codesight` directory exists here, so no stale managed index was
changed; no lane-local `target/` exists and the shared Rust target is retained.
Stable-source quick tier completed **exit 0**: Rust format/clippy and quick
workspace tests passed; Python **2,739 passed, 4 skipped, 100 deselected**, five
warnings in **701.64 s**; UI **275 passed, 0 failed**; bounded tracked secret
scan **1,397 files, 0 findings**. Durable evidence:
`work/cfd/kvdb-stable-quick.{log,exit}`. Source stayed fixed at d01840a during
this run; later changes were documentation/lessons only. Private identity scan
also completed exit 0 with 0 findings. Push only this lane; no merge.
Read `work/hull-ends-plan.md` and `work/thin-ship-plan.md` snapshots
for full source evidence; these are ignored copies, not new published results.

## PM transom approximation and physical sequence (before runs)

Fresh-session PM confirmation (2026-11-14): execute the physical coarse,
medium and fine sequence below, not another preparation-only checkpoint.
At Fn 0.142 the wave term is expected to be small; this is a motivation for
reporting sensitivity, not an assumed numerical result. Use the merged
thin-ship module on offsets from this solid with the stated stern-profile
closure, score with its calculated Cw, and report the zero/doubled-Cw bounds.
All other G-KV-DB conditions remain frozen. Commit each run, run quick tier
at the end, push `lane/cfd-worker`, and do not merge.

PM supersedes the transom blocker: compute thin-ship Cw from this solid's
waterline offsets, ending each waterline at its stern profile to close the
immersed transom. **This is an explicit thin-ship stern-closure approximation,
not the physical CFD transom geometry or a validated transom correction.** Keep
the real transom in double-body CFD. Score unchanged G-KV-DB with this Cw;
also report CT_est with **Cw=0** and **2*Cw**. No tolerance or convergence change.

Frozen numerical study: same source/draft/domain and SST settings on all meshes;
background base_cells **16 / 22 / 30**, surface refinement level **3** throughout,
three prism layers with existing relative-size parameters. Actual cell counts
and effective refinement ratios determine convergence evidence; maxGlobalCells
2,500,000 is an admission ceiling, not a target (hitting it invalidates systematic
refinement). Domain one L upstream, three L downstream, one L lateral and below
the hull, waterplane z=0. Full-width physical force multiplier **1**. Steady
solver **2000 iterations**, all force samples retained; if final two 100-sample
windows do not meet <=1% drift, report nonconvergence (do not choose windows).
Measure y+ and actual layer coverage. Run checkMesh before simpleFoam; failed
checks stop admission rather than lowering thresholds after inspection.

Start **every** remote stage only at load1 **<4**; otherwise wait and recheck
every **600 s** in background without treating waiting as task completion.
Use the detached host monitor with complete rolling 600-s load estimate >9 for
600 further seconds, one-job lock/5 CPU/12 GB/nice10/disk limits unchanged.
From observed iteration throughput after >=100 iterations, project total 2000-
iteration wall time; stop and report if >24 h. Also stop a stage if measured
progress establishes a >24-h projection. Commit each run and its costs before
the next mesh. Quick tier at end, push lane only, no merge.

Resume: prepare source-preserving clipped STL and stern-profile offsets, test
monitor/case contracts, then physical coarse mesh/checkMesh/solver; continue
medium/fine sequentially if safety and mesh admission permit. No new run yet.

Preparation numerical canonicalization: OCCT clipped-solid tessellation produced
four zero-area facets and a maximum **22.95 micrometre model-space** overshoot
above the exact clipping plane. Remove only zero-area facets, round shared
vertices to **1e-8 m**, and clamp positive-z tessellation overshoot to the exact
z=0 clipping plane, rejecting overshoot above **5e-5 m**. This is bounded
representation cleanup of an already exactly clipped solid, not fitting to
area/volume/forces. Retain failed preparation logs 01/02 and recheck directed
closure/orientation after cleanup before publication.

### Physical coarse attempt 01: dialect failure, retained

`kvdb-coarse-mesh-01` started at load1 **2.10**. Official surfaceCheck:
**61,174 triangles, zero illegal triangles, closed two-face edges, one part,
one normal zone** (four nearby-point warnings). blockMesh produced **8,192
cells**. snappyHexMesh then failed before refinement: generated include omitted
v2412's `.cfg` suffix. Installed image inspection confirms
`caseDicts/mesh/generation/meshQualityDict.cfg`. Regression failed first, then
**67 focused tests passed** after the one-path fix; numerical settings unchanged.
Stage accounting: surfaceCheck **1 s / 0.001389 allocated core-hours**;
blockMesh **0 s at integer-second resolution**; failed snappy **1 s /
0.001389 core-hours**. Whole monitored attempt **31.452394 s / 0.043683881
allocated core-hours**, 5-core quota, including monitor overhead. No checkMesh
or solver ran. Evidence: ignored `work/cfd/kvdb-coarse-mesh-01-result.log`.
Retry is a fresh immutable attempt, not a replacement of this failure.

### Coarse mesh 02: physical mesh accepted

Started load1 **1.26**; **16,257 cells**, official checkMesh **Mesh OK**,
max non-orthogonality **63.6712**, max skewness **1.48945**. Stage walls:
surfaceCheck **0 s** (integer resolution), blockMesh **1 s**, snappy **4 s**,
checkMesh **0 s**; mesh allocation **0.006944 core-hours** over 5 s.
Whole supervised attempt **31.076458 s / 0.043161747 allocated core-hours**,
5-core quota. These are a coarse mesh, not force or convergence results.
Evidence: ignored `work/cfd/kvdb-coarse-mesh-02-result.log`. Admit coarse
simpleFoam next with unchanged 2000 iterations and projection rule.

### Coarse solver 01: physical steady run completed

Load1 **1.57**, **16,257 cells**, **2000 iterations / 2000 force samples**.
Final two fixed 100-sample means **24.1434204 / 24.1434222 N**, drift
**0.00000746%**. CV **0.00545121930**, implied **(1+k)=1.58022203**,
ITTC-57 CF **0.00344965404** (actual stated U,L,nu). No gate score from one mesh.
y+ min/mean/max **30.2276 / 170.305 / 1766.82**; poor local maximum retained.
Layers: **92.9181% faces extruded**, average **2.56** layers vs 3 requested.
Solver stage **163 s / 0.226388889 allocated core-hours**; whole monitored
attempt **182.187129 s / 0.253037680 core-hours**, five-core quota. Projection
at iteration 1816 **164.10 s**, below 24 h; no resource pause. Evidence:
ignored `work/cfd/kvdb-coarse-solver-01/` and matching `-result.log`.
Next medium uses frozen base_cells 22, same settings; no force-based tuning.

### Medium mesh 01: physical mesh accepted

Load1 **2.01**, **35,426 cells**, checkMesh **Mesh OK**; max
non-orthogonality **64.7552**, skewness **2.27712**. snappy **24 s /
0.033333333 allocated core-hours**; other stages report 0 s at integer
resolution. Whole monitor **32.409143 s / 0.045012698 core-hours**,
five-core quota. Evidence: ignored `work/cfd/kvdb-medium-mesh-01-result.log`.
No cell ceiling reached. Proceed to medium solver under unchanged settings.

### Medium solver 01: physical run completed

Load1 **1.50**, **35,426 cells**, **2000 samples/iterations**. Fixed final
100-sample forces **20.4808469 / 20.4808400 N**, drift **0.00003369%**;
CV **0.004624263674**, implied **(1+k)=1.340500704**. y+ min/mean/max
**13.7969 / 129.155 / 1266.09**. Solver stage **365 s / 0.506944444
allocated core-hours**; whole monitor **393.009871 s / 0.545847042
core-hours**, five-core quota. Last projection **363.18 s**, no pause.
Evidence: ignored `work/cfd/kvdb-medium-solver-01/` and result log.
Fine remains required: the coarse/medium difference is not mesh convergence.

### Fine mesh 01: physical mesh accepted

Load1 **2.16**, **80,069 cells**, checkMesh **Mesh OK**; max
non-orthogonality **64.8758**, skewness **3.46921**. surfaceCheck **1 s**,
snappy **25 s**, blockMesh/checkMesh 0 s at integer resolution; combined
**26 s / 0.036111111 allocated core-hours**. Whole monitor **31.475456 s /
0.043715910 core-hours**, five-core quota. Evidence: ignored
`work/cfd/kvdb-fine-mesh-01-result.log`. No cell ceiling reached; admit fine
solver. Final quick tier is running on unchanged source in parallel with
remote physical execution; only result documentation changes locally.

### Stable-source physical-delivery quick tier

Final quick tier **exit 0**: Rust format/clippy/workspace tests passed;
Python **2,741 passed, 4 skipped, 100 deselected**, 5 warnings in **674.41 s**;
UI **275 passed, zero failed**; bounded tracked secret scan **1,400 files,
zero findings**. Log/receipt: ignored `work/cfd/kvdb-physical-quick.{log,exit}`.
Source remained unchanged throughout (only docs/lessons/results changed).
Private exact-name identity scan completed **zero findings**. A broader
exploratory identity scan matched historical local filesystem paths; no
credentials or host were copied into the new report. No managed `.codesight`
index or lane-local target exists. Shared targets were not removed.

Delegation deviation: repeated helper calls retained an unwanted isolation
option; all were stopped without using any results. Worktree inventory showed
no new helper checkout from these calls. Wave calculation was executed directly
inside the existing lane. The matching lesson now requires stopping delegation
instead of repeated dispatch/cancel attempts.

### Fine solver 01 and fixed-gate outcome

Load1 **1.80**, **80,069 cells**, **2000 force samples/iterations**. Final
fixed 100-sample forces **21.6784896 / 21.6784900 N**, drift **0.00000185%**;
CV **0.004894674917**, diagnostic implied **(1+k)=1.418888635**. y+
min/mean/max **17.1999 / 90.9219 / 804.101**. Fine face-layer coverage
**97.0385%**, mean **2.84** layers; medium coverage **92.3775%**, mean **2.49**.
Solver stage **868 s / 1.205555556 allocated core-hours**; whole monitor
**879.062201 s / 1.220919723 core-hours**. Last projection **865.92 s**;
no resource pause. Final evidence in ignored `work/cfd/kvdb-fine-solver-01/`.

**G-KV-DB NOT PASSED.** CV sequence **0.005451219298, 0.004624263674,
0.004894674917** is nonmonotone; fine/medium **5.84766% >2%**. Actual
cell refinement ratios **1.29646 / 1.31234**. Force-window drift passes, but
there is no finest converged mesh. No extra mesh or force-window selection.

Merged thin-ship module matched byte-for-byte at origin/continue/v0.5
76d7e01. Solid-tessellation waterline offsets use the PM stern-profile
closure (terminal grid panel to zero, shrinks on refinement); real CFD transom
unchanged. Selected **Cw=0.004551615822**, **Rw=20.1590830 N**, with
2561 x 257 offset nodes, 2048 angular nodes, lambda_max 40. Last panel change
**-0.21038%**, angle/tail change **+0.01217%**; offset volume vs CAD **+0.08128%**.
This unexpectedly large term is retained, not forced small. Stern model and
surface tessellation errors are not bounded by these numerical checks.
Nominal finest CT_est **0.009446290739 (+129.83676%)** with stated Cw;
zero-Cw **0.004894674917 (+19.09185%)**; doubled-Cw **0.013997906560
(+240.58167%)**. Nominal score is outside the frozen band, independently of
failed convergence. Not a validated hybrid or free-surface result.

All attempts total **1580.672651 s / 2.195378682 allocated core-hours**,
five-core quota. Mesh stages (including failed attempt) **57 s / 0.079167
core-hours**; solver stages **1396 s / 1.938889 core-hours**. Whole totals
include monitor/container overhead. Final report:
`outputs/2026-11-14-kvdb-physical-runs.md`.

Resume: PM decision required for failed spatial convergence and large
stern-closed wave estimate; do not change gates, tune after force inspection,
or launch additional runs automatically. All three requested physical runs
are complete; preserve logs/meshes and the existing worktree. Push lane only,
no merge. Stable-source quick tier above passed; only documentation changed.

## PM G-KV-DB2 wall-resolved study (frozen before runs)

The original G-KV-DB failure above remains recorded. PM rejects thin-ship
for this blunt full hull with closed transom: Cw=4.55e-3 exceeds measured
total CT. **Do not use thin-ship Cw for KVLCC2.**

Reference read: main ignored `work/cfd/sources/formfactor/kvlcc2_formfactor_reference.md`,
PDFs and MANIFEST beside it. Experimental **(1+k)=1.215**, Prohaska/ITTC-57,
1:58, is second-hand A26 (Argyros 2026) citing Larsson & Raven 2010.
K21 typical double-body **1.223 at Fn .142**, reported spread ~1.6%.
Important qualification: the nearest **1.9% form-factor uncertainty is a
ballast-case analogue**, not published uncertainty for this design draught.
Published references include rudder; this study remains bare hull and must
state the mismatch. Re=4.6e6 vs some publications 4.9e6 is retained explicitly.

**G-KV-DB2:** finest converged grid (1+k)=CV/CF57 must lie in
**[1.17855, 1.25145]** (1.215 +/-3%, PM-set tolerance motivated by the
uncertainty analogue and RANS spread, not a derived confidence interval).
CF57=0.075/(log10(U*L/nu)-2)^2, same U/L/nu/S as G-KV-DB.
CT_est=(1+k)*CF57+CW, central **CW=0**, must lie in
**[0.0039456, 0.0042744]** (measured .004110 +/-4%). Report CW bounds
**-0.0001 and +0.0001**; this is a PM working estimate, not a citation.
Gate uses central estimate; report whether bounds also fit. Never use thin-ship.
Keep monotone three-grid CV, fine/medium <=2%, final two equal 100-sample
windows drift <=1%, all 2000 iterations retained. No selected windows.

### Design review
Architecture PASS: independent lane-local case adapter and detached host monitor;
half hull with centreplane y=0 and free-surface z=0 symmetry; physical full-hull
force multiplier **2**, reference full wetted area **8.0838 m2**.
Quality WARN: y+ and layer survival must be measured, not inferred from settings;
no wall-function coarse-grid result substitutes for wall-resolved validation.
Coverage PASS: test symmetry patches, force multiplier, absolute layer controls,
low-Re fields, unchanged gate arithmetic, peak-memory receipt and stop rules.
Performance WARN: serial 1/2/4M runs may exceed 24h or 12GB; measure coarse and
project subsequent costs before admission. A resource-limited study is not converged.

### Frozen mesh method and implementation sequence
1. Add lane-local `cfd/wall_resolved.py`, tests `tests/test_cfd_wall_resolved.py`.
Reuse the validated wetted solid; clip at centreplane y=0 in CAD, preserve
physical skin, artificial plane caps only for meshing. No shape fit. Tessellation
.005 m/.1 rad, canonicalization and bounded clip cleanup as before.
2. Three systematic half-domain backgrounds base_cells **74/94/118**, surface
level **3**, aft box (last .35L) level **4**, same domain upstream L/downstream
3L/lateral L/depth L. Approximate target **1/2/4 million cells**; report actual
counts/ratios and target deviation, no retroactive force-driven cell tuning.
Set admission ceiling **6 million**, not a target. Absolute prism layers:
**30 layers**, first thickness **8e-6 m / refinement factor**, expansion **1.2**,
minimum thickness **1e-6 m / factor**, factors 1,94/74,118/74. These target
wall-resolved y+ <1; report measured min/mean/max and coverage. Low-Re SST:
no-slip U, k fixed zero, nutLowReWallFunction, omegaWallFunction viscous limit.
3. Test first, implement and focused checks; commit settings before physical
preparation/meshing. Prepare half-solid and validate surface topology. Inspect
installed v2412 dictionaries, not guessed include paths.
4. Mesh/checkMesh/solver sequentially coarse then medium then fine; commit each
attempt including failures before the next. Record real cells, stages and full
attempt wall/core-hours. Capture container cgroup memory.peak before exit using
an in-container shell; no docker socket or host control bind exposed. Poll
Docker memory too; report exact cgroup peak separately from sampled RSS if needed.
5. Existing startup load1 **<4**, otherwise background check every **600 s**;
rolling complete 600-s estimate >9 for further600s pauses, no automatic unpause.
Same pinned image, one lane lock/container, --cpus5 --memory12g, nice10,
no network/system changes, remote root only, 10GB reserve and <40GB lane total.
Use **12GB as hard memory limit**; stop/report OOM or admission projection
that will not fit. Stop any run projected >24h; finest feasible only is explicitly
not converged. No fourth grid or control tuning after forces.
6. Quick tier on stable source at end, identity/secret checks, final report in
`outputs/2026-11-14-kvdb2-physical-runs.md`; commit/push lane/cfd-worker only,
no merge. Keep existing worktree/evidence. Resume here until implementation
and tests complete; **no DB2 run has started at this freeze**.

### DB2 preparation correction before any remote run

Exact source CAD centreplane Boolean returned an empty shape (two attempts,
no remote cost). Do not invent or repair a half skin. Reuse the accepted closed
full-width wetted STL, but mesh **only y>=0** using centreplane symmetry.
This is geometric domain clipping by snappy, not full-hull solving; force factor
remains **2**. The upstream locationInMesh is strictly inside y>0, tested.
Half-domain controls are unchanged. Focused tests **69 passed**; new half-hull
and gate tests failed first on missing module, seed-point regression failed
before correction. Absolute 30-layer controls and low-Re fields are generated.
Detached DB2 monitor retains startup/rolling rules and records cgroup memory.peak
on shell EXIT plus sampled Docker memory and OOM status. No physical DB2 run
has started. Preparation log: ignored `work/cfd/kvdb2-prepare-03.log`.

### DB2 coarse mesh 01 stopped: oversized refinement (before forces)

Load1 **2.03**, blockMesh **810,448 cells**, then volumetric aft level4
refinement produced **7,219,675 cells**, exceeding the 6M admission ceiling
and coarse target. Stopped before checkMesh/solver, exit143, no OOM. Whole
attempt **785.248483 s / 1.090622894 allocated core-hours**. surfaceCheck1s,
blockMesh22s; snappy interrupted. Last Docker memory sample **5.009 GiB**;
an earlier sample **5.310 GiB** was observed. Exact peak unavailable: this host
kernel exposes memory.current but **no memory.peak**. Do not label a sampled
value as peak. Evidence `work/cfd/kvdb2-coarse-mesh-01-result.log` and stop details.
No (1+k) exists for this attempt. Failure retained.

Before any retry/force results: narrow aft box to physical half-beam+0.02L,
physical draft+0.02L below surface, level **3**; retain level3 hull, 30 absolute
layers, bases74/94/118. This removes unintended entire-volume 16x subdivision,
not a force fit. Measure actual target counts; if coarse still materially
exceeds ~1M, stop to revise study rather than claim target achieved. Capture
exact process peak RSS via Python resource.wait4 wrapper around each stage,
plus sampled total container memory, since cgroup peak is unsupported.

### DB2 coarse mesh 02: monitor instrumentation failure

Load1 **1.38**; no mesh stage ran: pinned minimal image has no python3.
Stage-wrapper launch exited127, container exit1. Whole **32.898258 s /
0.045692025 allocated core-hours**, no OOM, peak unavailable. Retain receipt.
No numerical controls changed. Use shell sampling of /proc child VmHWM/VmRSS
at 0.2s; report sampled kernel high-water mark as lower bound, not an exact
container peak. No packages installed and no image change. The missing
memory.peak and minimal runtime preclude claiming exact total peak memory.

### DB2 coarse mesh 03: checkMesh passes, wall-resolution admission FAIL

Load1 **1.15**. Actual **1,029,000 cells**, centreplane y=0 confirmed,
checkMesh **Mesh OK**, max nonorthogonality64.9424 and skewness3.75273.
Stages surfaceCheck1s, blockMesh6s, snappy317s, checkMesh8s: **332s /
0.461111111 allocated core-hours**. Whole **344.404176s / 0.478339133
core-hours**, five-core quota, no OOM. Sampled process high-water RSS maximum
**2,385,797,120 bytes (2.222GiB)**, lower bound, not exact container peak.

**Physical wall-resolution prerequisite FAIL:** requested30 layers but actual
mean **0.018 layers**, only **146/17002 faces (0.858723%)** extruded; overall
mean thickness **5.19e-5m** and only0.549% requested coverage/thickness ratio.
Thus this is not a wall-resolved grid despite clean checkMesh. Do not run
simpleFoam or spend medium/fine on this failed family; no y+ or (1+k) is
available. Need a revised prism-layer strategy, not a wall-function substitute.
Three preparation/attempt failures retained; G-KV-DB2 **BLOCKED / NOT CONVERGED**.
No gate thresholds changed; original G-KV-DB remains failed.

DB2 attempt totals so far **1162.550917s / 1.614654052 allocated core-hours**,
including oversized mesh and instrumentation failure. Evidence main ignored
`work/cfd/kvdb2-coarse-mesh-{01,02,03}-result.log`,
`kvdb2-coarse-memory-layers.log`. Resume: PM review of prism-layer failure;
never claim y+<1 from first-layer setting or start unsupported medium/fine.
Quick tier running on stable source; commit this completed mesh before delivery.

### DB2 delivery verification

Stable-source quick tier **exit0**: Rust format/clippy/workspace passed;
Python **2743 passed,4 skipped,100 deselected**, five warnings, **483.57s**;
UI **275 passed,0 failed**, bounded secret scan **1402 files,0 findings**.
Evidence ignored `work/cfd/kvdb2-quick.{log,exit}`. Exact-name private scan
zero findings; diff check clean. No active lane containers. Lane root
**1,990,734,749 bytes**, host free **168,935,940,096 bytes**; limits preserved.
No managed codesight index or lane target exists; shared targets retained.
Final DB2 report `outputs/2026-11-14-kvdb2-physical-runs.md` states no (1+k)
for any grid; medium/fine and all solver runs not admitted. G-KV-DB2 remains
blocked/not converged. Push lane only, no merge. Resume at revised layer
strategy with PM; do not silently substitute the failed grid or prior DB1 values.

## PM prism-layer recovery (G-KV-DB2 unchanged at f357e2d)

Before any recovery mesh: first verify cfMesh/cartesianMesh in the pinned
v2412 image; use it if present, extending only required runner commands with
red/green tests. If absent/fails, PM authorizes separate snappy snapping and
layer addition from official retained DTC controls. No package/image changes.
Acceptance before solver: **>=95% hull faces with full requested layer count**,
per hull patch; checkMesh must pass. After solver: **y+<1 on >=95% wetted
hull area**, distribution reported. Partial extrusion is not full-count coverage.
G-KV-DB2 thresholds and three-grid convergence remain frozen. No thin-ship.

Architecture PASS: same lane-only half-domain/case and host supervisor, factor2.
Quality WARN: full-count coverage needs face-level layer output, not mean layers;
post-run area-weighted y+ needs boundary fields and face areas. Coverage PASS:
test command allowlist, separate pass controls, full-count and y+ admission.
Performance WARN: previous2.2GiB is a sampled process lower bound, not total
peak. Retain12GiB hard limit and resource admission; do not assume4M fit proved.

Recovery fallback settings (recorded before run): reuse coarse snapped grid
without layers, base74, hull/aft refinement3. Layer-only pass castellatedMesh
false/snap false/addLayers true. Start official DTC settings: relativeSizes true,
finalLayerThickness **0.3**, **30 layers**, expansionRatio **1.2**, minThickness
**0.001**, featureAngle **180**, mergePatchFacesAngle60, layerTerminationAngle30,
slipFeatureAngle30. Increase normal/thickness smoothing to5/10/30 and relax
iterations10, nLayerIter100, nRelaxedIter20. Pass-only mesh quality maxNonOrtho75,
minTetQuality-1e30, maxInternalSkewness8, minDeterminant1e-4. Final standalone
checkMesh remains unchanged: relaxing extrusion does not relax acceptance.
At typical hull outer spacing~0.01m, final0.3 yields first-cell thickness
~1.5e-5m (centre distance half), estimated y+~0.3; actual y+ governs admission.
Thirty1.2-growth layers have final/first~198; full coverage must be demonstrated.
Write layerSets/layerFields to count actual full layers, per patch. Preserve
failed attempts; no solver until full-count evidence. Then coarse solver,
medium/fine only if layers and post-run y+ pass; record costs and memory.
Commit each step, quick tier at end, push lane only, no merge.

### cfMesh availability check and minimal runner capability

Pinned container filesystem inventory (stopped own coarse03 container) contains
**no cartesianMesh or cfMesh path**, confirmed platform/bin scan and full tar
listing. Thus cfMesh is unavailable in this exact pinned minimal v2412 image;
no install/image change made. Inventory evidence main ignored
`work/cfd/kvdb2-cfmesh-image-inventory.log`. Read retained official DTC
snappyHexMeshDict from dtc-official-mesh01, not guessed defaults. Runner now
permits only plain `cartesianMesh` (no extra utility), tested red/green;
arguments/dynamic libraries remain rejected. Availability is not claimed.
Proceed to explicitly authorized separate-pass snappy fallback.

### Recovery coarse mesh04: separate-pass measured failure

cfMesh absent from pinned image. Snappy snap157s, layer76s, surfaceCheck1s,
blockMesh5s, checkMesh8s; whole **250.453681s /0.347852335 allocated core-hours**.
Actual **1,028,694 cells**, checkMesh OK. Layer field confirms hull uniform0:
**0/17002 full-count faces**, no solver admission. Initial full extrusion
created510060 candidates but **249588 faces failed determinant<1e-4**, 94 twist,
52 pyramid and7 interpolation-weight checks; rollback removed all layers.
Sampled layer VmHWM **2484256768bytes (2.314GiB)** lower bound, no OOM.
Evidence ignored `kvdb2-recovery-{full-layer,layer-evidence,layer-diagnostic}.log`.

Before force measurements, one root-cause-directed layer-only retry: disable
thin-prism-incompatible determinant/twist constraints **minDeterminant-1,
minTwist-1**, reduce minVol1e-18 and minFaceWeight0.001 for extrusion only.
All other settings unchanged. Final checkMesh still gates output; do not
accept negative volumes or weaken standalone checkMesh. This tests the logged
quality rollback cause, not a geometry/force fit. Commit mesh04 before retry.

### Recovery coarse05: extrusion improved, both admission checks FAIL

Load1 **1.25**, **1,501,521 cells**. Targeted determinant/twist relaxation
produced99.8118% any extrusion, but actual binary nSurfaceLayers hull field
shows **14626/17002=86.02517% full30 layers**, below95%. Counts0:32;
counts1..29:2344; full30:14626. Mean27.8 is not full-count coverage.
Standalone checkMesh **FAILS1 check**:22409 high-aspect-ratio cells, maximum
**1566.2**; volumes positive, nonorthogonality62.6896/skewness3.29121 pass.
Do not lower aspect-ratio acceptance or count partial layers as full. No solver.
Stage walls surfaceCheck0/blockMesh9/snap182/layers127/checkMesh12s, total330s
**0.458333333 allocated core-hours**. Whole **345.299768s /0.479583011
core-hours**, five-core quota. Sampled layer VmHWM **2369462272bytes (2.207GiB)**
lower bound; exact total peak unavailable, no OOM. Binary field and logs retained
main ignored `kvdb2-recovery05-nSurfaceLayers`, `kvdb2-recovery05-evidence.log`.

Recovery attempts04+05 total **595.753449s /0.827435345 core-hours**,
including all stage/monitor overhead, excluding read-only image inventory.
G-KV-DB2 **BLOCKED / NOT CONVERGED**. No y+ distribution or (1+k) on any new
grid because solver admission failed. Medium/fine not run per PM acceptance.
Resume at a new mesh strategy/PM review, not more control guesses. Keep all
failures and frozen gates. cfMesh needs a separately authorized runtime if
required; do not install/change the pinned image automatically.

### Layer recovery delivery verification
Stable-source quick tier exit0: Rust format/clippy/workspace pass; Python
**2745 passed,4 skipped,100 deselected**,5 warnings,547.61s; UI275 pass;
bounded scan1403 files,0 findings. Focused recovery/remote24 pass. Exact-name
identity scan0 findings, diff clean. No active lane containers; no OOM or safety
pause. No managed codesight or lane target exists; shared targets retained.
Report `outputs/2026-11-14-kvdb2-layer-recovery.md`. G-KV-DB2 blocked,
no solver/y+/(1+k) on any new grid; preserve failures and worktree. Push lane
only/no merge. Resume requires new mesh strategy or authorized cfMesh runtime.

## PM operating-rule change: coarse05 solver admission

This PM change supersedes prior checkMesh-aspect/full-count admission rules,
**not G-KV-DB2 frozen at f357e2d** and not historical failures. Near-wall
high aspect ratio is expected for y+<1. Admission now requires no negative
volumes/wrong-oriented faces, maximum nonorthogonality **<70**, skewness **<4**,
and **zero cells with aspect ratio>1000 outside added layer cells**. Report
that outside count explicitly. Coarse05 is PM-admitted despite86.025% full-count
and99.812% partial coverage, conditional on the recorded layer-cell location
check. All requested settings/actual coverage stay reported.

1. Intersect retained highAspectRatioCells with addedCells; report total and
outside counts using actual cell labels, not layer coverage inference. Commit.
2. Run coarse05 simpleFoam2000 iterations, retain all forces; final fixed100+100
window drift<=1%. Use factor2/full S. Report single-grid(1+k), never gate pass.
3. Read final yPlus boundary field and geometric hull face areas. Report area-
weighted distribution and shares **y+<1 and <5**, plus face-count shares.
If<1 covers>=95% area, admit systematic medium/fine with same layer settings,
linear ratio~1.3 (base96/125 vs74; target~2.2x/4.8x coarse cells). Measure
actual refinement and memory, never assume fit. Otherwise reduce first-layer
height, record setting before rebuilding and rerun coarse before further grids.
4. Same startup load1<4 otherwise600s background wait, rolling-load pause,
no automatic unpause;5CPU/12GiB/nice10/one container/disk limits; stop>24h
projection. Commit each step, final stable quick tier, push lane only/no merge.
No thin-ship. Resume now at cell-label admission check; no new solver yet.

### Coarse05 PM admission verified

Retained label sets: **22409 highAspectRatioCells**, **472827 addedCells**;
set difference highAspectRatioCells minus addedCells = **0**. All flagged
cells (a conservative superset of AR>1000) are in layers. Previously measured
positive volumes/face pyramids, nonorthogonality62.6896<70, skewness3.29121<4.
Coarse05 meets revised PM operating rule. Admission evidence ignored
`work/cfd/kvdb2-coarse05-aspect-admission.json`. Admit first2000-iteration
solver on exact mesh05, factor2, unchanged low-Re SST; no gate claim.

### Admitted coarse05 solver01 stopped by >24h runtime projection

Start load1 **1.06**, exact1,501,521-cell mesh05,5CPU/12GiB. Completed
iteration clocks1..5 **31,73,128,318,608s**; iteration6 was running.
Measured full-study projection **608/5*2000=243200s=67.5556h**, last two
iterations progressively slower. This is early throughput, not steady solver
convergence; nevertheless PM's stop-any-run-projected>24h rule requires stop.
Stopped without unpause/restart, exit143, whole **721.554989s /1.002159706
allocated core-hours**, no OOM. Sampled kernel VmHWM **2287751168bytes
(2.131GiB)** lower bound, exact total peak unavailable. Partial forces/logs
preserved under ignored `work/cfd/kvdb2-coarse-solver-01/` and timing/memory
logs. No >=200 samples, no force convergence, no admissible(1+k) diagnostic.
No scheduled100-step yPlus output reached: distribution/share<1/<5 unavailable.
Do not infer y+ from requested thickness or partial forces. Medium/fine not
admitted. G-KV-DB2 remains **BLOCKED / NOT CONVERGED**, gates unchanged.
Resume at PM compute/numerics decision; don't bypass24h stop by extending,
restarting or claiming early partial output converged. Quick tier at end.

### Admitted coarse delivery verification
Quick tier exit0:Rust format/clippy/workspace passed;Python2745passed,
4skipped,100deselected,5warnings,501.09s;UI275passed;bounded scan1404files,
0findings. Exact-name private identity0findings,diff clean. Five force samples
confirmed; yPlus.dat header only. No active lane containers, lane2,960,025,413
bytes. Report `outputs/2026-11-14-kvdb2-admitted-coarse.md`. Gates unchanged;
no credible(1+k)/y+ or medium/fine result. Preserve worktree and all evidence.
Push lane only/no merge; resume at PM decision on67.6h early projection.

## PM throughput diagnosis and bounded parallel diagnostic

G-KV-DB2/mesh admission unchanged. Old run **nProcs1**, plain simpleFoam:
5CPU quota did not create parallel execution. Completed iteration wall deltas
**31,42,55,190,290s**. Pressure GAMG solves per iteration **23+4,7+77,
10+137,25+510,55+639**; U1–3 iterations, k/omega1–2. No explicit maxIter
was specified; pressure residuals met relTol, so no evidence of max-iteration
cutoff. Cost escalation is pressure convergence on anisotropic prisms, not
only cell-count scaling. SST k and omega bounding occurred during startup.
Actual controls pGAMG tol1e-7/relTol.01 GaussSeidel; others smoothSolver
symGaussSeidel tol1e-8/relTol.1; SIMPLE consistentyes/nonorth1;
relaxation p.3,U/k/omega.7. Old67.6h projection remains historical early
estimate, superseded for decisions by PM's100-step parallel diagnostic.

Architecture PASS: exact5-rank mpirun inside same restricted container;
no remote-machine MPI, no extra resource allocation. Quality WARN: changing
initialization/linear numerics must be explicit; do not claim MPI-only speedup.
Coverage PASS: allow exact5-rank simpleFoam/potentialFoam parallel invocations,
reject arbitrary MPI binaries/ranks/options, test100-step controls. Performance
WARN: pressure iterations dominate; measure steps21–100 before projecting.

1. Add tested allowlist exact `mpirun -np 5 simpleFoam -parallel`, same for
potentialFoam with `-initialiseUBCs`, plus potentialFoam serial option and
reconstructPar -latestTime. Plain decomposePar already allowed. No shell paths,
extra utilities or dynamic libraries. Pin5 subdomains scotch. Probe MPI binary.
2. Fresh immutable diagnostic from exact coarse05 mesh/initial fields. Potential
initialization, then100 simpleFoam steps, same low-Re SST. Use pressure GAMG
DICGaussSeidel, cacheAgglomerationtrue, faceAreaPair, nCellsInCoarsestLevel100,
mergeLevels1, nPreSweeps0/nPostSweeps2, nFinestSweeps2, tol1e-7/relTol.05,
maxIter200 (explicit log/limit detection). U/k/omega smoothSolver as before,
p.3/U.5/k.5/omega.5 relaxation, SIMPLE nonorth1/consistentno. Potential Phi
GAMG tol1e-8/relTol.01,10 nonorth corrections. These are numerical recovery
settings, not reference-paper prescriptions: cited papers give wall/grid
practice but no portable exact solver dictionary. Keep grid/physics fixed.
3. No2000 projection from startup; finish bounded100, report fields/pressure
counts and mean/median/p95 per-step wall for21–100, then project2000 using
observed rate plus initialization. If<=24h continue fresh/restarted physical
coarse to2000 with receipt/forces/y+; else stop/report. Same load/disk/memory
rules remain, no automatic unpause. Tests/commit each step, final quick/push
lane only/no merge. No new diagnostic started at this checkpoint.

### MPI diagnostic01 startup transport failure
Actual startup load1 **0.62**. decomposePar completed10s into5
subdomains; MPI initialization failed before potentialFoam/solver. Explicit
self,tcp transport found onlyself usable under --networknone, so ranks could
not communicate. Whole **32.277242s /0.044829503 core-hours**, no OOM.
Retain receipt; no iterations/projection. Retry uses **self,vader** local
shared-memory transport and disables vader single-copy mechanism (no ptrace),
no network permission change or host networking. Same5 ranks/resources.

### MPI diagnostic02: throughput recovered, mandatory load pause before100

Start load1 **0.59**, decompose11s/potential40s, confirmed **nProcs5**.
Completed85 steps, iteration86 interrupted by host PM rolling-load rule
**rolling600>9 sustained600** at epoch1794607215.692. Container remains
**paused**, no automatic unpause/new solver. Pre-pause receipt **1242.165595s /
1.725229992 allocated core-hours**,5CPU,12GiB,noOOM; paused reservation time
continues and is not included in this snapshot. Last Docker sample1.938GiB,
not peak. Transport self,vader works within networknone; no permissions changed.

Steps21–85 mean **13.09231s/step**, median12,p9522.8. Pressure GAMG
**2–3 iterations**,mean2.16923,no200-iteration cap hits. Initialization/
smoother/relaxation/MPI all changed, so not MPI-only speedup. Required100
not complete: **no new2000-step projection** and no convergence claim.
No coarse/medium/fine gate result. Evidence main ignored
`kvdb2-mpi-diagnostic02/{log.simpleFoam,log.potentialFoam,timing-summary.json,iterations.json}`,
immutable pause receipt/safety marker. Commit paused result; no unpause without
PM approval. Resume exact diagnostic02 for remaining15 steps only if authorized;
then post20–100 timing/projection decides coarse continuation. Gates unchanged.

### MPI delivery verification
Stable-source quick exit0:Rust fmt/clippy/workspace passed;Python2746pass,
4skip,100deselect,5warnings,524.99s;UI275pass;bounded scan1405files0findings.
Exact-name private identity0findings. Source stable sincef1fa451;only docs
changed during verification. Paused diagnostic remains paused,no new solver.
Report `outputs/2026-11-14-kvdb2-throughput-diagnostic.md`. No projection
until100steps;PM unpause decision required. No managed index/lane target,
shared target retained. Commit/push lane only,no merge.

## PM standing load-resume authorization

PM explicitly authorizes **unpause diagnostic02 now**; this immediate one-off
direction is separate from standing threshold evidence. Thereafter lane may
unpause **only its own exact mf-cfd-* container** when complete rolling600-s
load estimate is **<6 continuously for600s**. Pause remains rolling600>9 for600s.
No unrelated containers; same one-job lock/resources/disk. Keep host monitor
alive across pauses,check resume eligibility every600s while sampling30s;
reset sustained-high state after authorized unpause. Resource/failure pauses
are not automatically resumed by load rule. Preserve pause/resume timestamps,
active vs reserved wall/core-hours and original receipts as snapshots.

Finish exact100-step diagnostic; exclude measured paused intervals from
throughput/window21–100. If within24h,continue/restart five-rank coarse to2000
with fixed final100+100 drift test,measure area-weighted y+ shares<1/<5 and
(1+k). If>=95%area<1,proceed same-settings medium/fine systematic ratios;
otherwise coarse first-layer adjustment before refining. Gates unchanged.
Do not end task merely for load waiting:background supervisor waits/rechecks.
Commit each run,final quick/push lane only,no merge. Resume at installing
pause-aware supervisor and immediate PM-authorized diagnostic02 unpause.

### Completed100-step diagnostic after authorized resume

Immediate PM unpause epoch1794607647.674; original pause1794607215.692,
paused431.982185s.100steps/reconstruct completed exit0. Solver wall1753s,
includes pause;decompose11/potential40/reconstruct8s. Complete steps21–100
pause-adjusted mean **12.55022s**,median11,p9522.05. Projection including
startup **25215.44s=7.00429h**,inside24h. Required100-step evidence now complete.
Resume supervisor segment151.698712s/0.210692655core-hours,all active;
original reserved accounting retained separately,no double count of snapshots.
Evidence `kvdb2-mpi-diagnostic02/completed-timing-summary.json` and logs.
Admit production continuation from diagnostic100 to2000,same5ranks/settings;
use reconstructed100fields and fresh decompose,retain100diagnostic samples
for complete history. Standing load pause/resume supervisor throughout. Final
force windows1901–2000/1801–1900 govern,no favourable window selection.

## PM other-load rule change (before live supervisor replacement)

PM supersedes total-load hysteresis only. Host10-minute estimate remains
complete time-weighted600s from load1 samples. **Other load=host rolling600
minus5 while running,minus0 while paused.** Pause if other>9 for600s;
unpause load-paused own container if other<6 for600s,check every600s.
All CPU5/memory12GiB/nice10/one-run/mf-cfd-only/disk<40GB rules unchanged.
G-KV-DB2 unchanged. Tests first failed on absentOtherLoad,then passed.
New attach-only `cfd/monitor.py` does not launch/reset solver. Replace exact
old host monitor PID after identity/cmdline check,retain backups and old logs,
release same flock,attach new under same lock. Preserve original container
StartedAt/PID and iteration. **Live inspection finds iteration378 paused,
not282**: do not rewind to282 or discard progress. Resume from actual state.
Proceed coarse convergence/y+;refine only after>=95%area y+<1. Ten-minute
wait checks stay active; no stop merely for load pause. Commit each run,
quick tier at end,push lane only/no merge.

### Coarse production01 completed2000 under new other-load monitor

Same container PID/start preserved;no restart/rewind. End2000,exit0,1900new
force samples plus100diagnostic. Final fixed100means full force
**19.00407514/19.00389502N**,drift **0.000947797%** passes1%. CV
**0.004290791853**,single-grid **(1+k)=1.243832512**,not gate-converged.
Final y+ area distribution:min.04808,p50.25481,p957.41060,p9918.61135,
max80.02026,mean1.18467;**88.38327%area<1,93.38121%area<5**.
Face shares89.53653%/93.95953%. Thus wall-resolution admission fails95%,
no medium/fine. Strong tail corresponds to partial/lost layers; reducing
requested thickness cannot by itself establish resolved uncovered cells.

Whole production reserved **34606.135596s /48.064077216 core-hours**,
paused **7759.628403s**,active **26846.507193s /37.286815545 core-hours**.
5CPU12GiB,noOOM. decompose14s,solver34562s(includes pauses),reconstruct12s.
Evidence ignored `work/cfd/kvdb2-coarse-production-01/`. Original failed
receipts and monitor logs retained. G-KV-DB2 **NOT CONVERGED**,no gate pass.
Per PM authorization,before new coarse run reduce relative final-layer
thickness0.3->**0.15** (first height halved,30layers/growth1.2 unchanged),
rebuild coarse with same snapping/quality controls and verify PM mesh
admission;then MPI100diagnostic/run/y+ again. No force-fit geometry/gate change.

## PM region-directed recovery: three approaches maximum

Restart inspection:worktree clean;mesh06 exited3,1,476,374cells,410.004734s/
0.569451019allocated core-hours,noOOM. Only aspect-ratio check failed
(max3128.5);positive volumes,nonorth68.0058,skew3.75273. No active lane
container. Thin first-height-only change did not fix lost layers.

Region map uses actual coarse05 hull-face centres/areas,y+2000 and matching
nSurfaceLayers. Overlapping coordinate masks (not anatomical CAD identities):
waterline z>-.02;transom x>-.03;bow x<-4.8,z<-.05;stern x>-.65,z<-.05;
bilge middle longitudinal range,z<-.25. Percent of total wetted area with
**y+>5 / incomplete layers**:waterline **0.619/0.863%**,transom
**0.504/0.532%**,bow **0/0%**,stern **3.951/6.342%**,bilge **0/2.364%**,
remaining skin **1.767/5.835%**. Regions overlap:do not sum. All y+>5 area
(**6.619% hull**) has incomplete layers. Exact map in ignored
`work/cfd/kvdb2-layer-region-map.{json,npz}`.

PM admission now **>=97% full requested layer count before any solver**,then
short **250iterations** with>=95%area y+<1 before full production. Frozen
G-KV-DB2 and95%y+ criterion unchanged. At most **three new meshing approaches**
after this diagnosis;stop/report on third failure,no more guesses.
Approach1:retain mesh06 first height (relative final.15/1.2^29),reduce
requested30->20 with final **.15/1.2^10=.02422584**,growth1.2;remove
layerTerminationAngle30 truncation ->0,slipFeatureAngle180,
maxThicknessToMedialRatio.8. Same surface/shape,snap,meshquality controls.
Targets stern/waterline termination and thick-stack medial interference;
no geometry fit. If unsuccessful,approach2 local stern+waterline surface
level4 (rest3),same20-layer first height in absolute metres where possible;
approach3 fewer12layers with same first height and additional normal smoothing.
Freeze exact controls before each attempt. Check region/full-count coverage
and PM volume/orientation/nonorth<70/skew<4/ARoutside0. Other-load monitor,
5CPU12GiB,one container,disk limits remain. Commit each approach,background
quick log at end,push lane only,no merge. No new production before admission.

### Approach1(mesh07) FAIL1/3
Reduced20-layer stack plustermination0/slip180/medial.8 producedzero layers,
uniform0actual field;1,028,694cells,checkMeshOK. Whole314.551592s/
.436877211core-hours,noOOM. No solver. Evidence coverageJSON/log retained.
Approach2before run:restore known-working termination30/slip30/medial.3;
retain20layers/samefirstheight,add stern x>-.65 and waterline z>-.025
searchable-box level4 refinement. Finer tangential cells target measured tail;
relativefinal.02422584 means firstheight equal or smaller,not larger.
97%fullcount/PMquality still required;two approaches remaining.

## PM mapping and convergence protocol additions (before next solver)

New short250-iteration y+check and any subsequent production must initialize
by **mapFields -consistent from converged coarse-production01 time2000** on
the same physical hull,not uniform/potential-only fields. Medium/fine map from
next coarser converged solution. Mapping output and source/target times retained;
never reuse unmapped time labels as post-mapping iteration counts.

PM proposed stop:<0.1%drift between successive100means for3successive windows,
minimum500/maximum2000iterations after mapping. **Frozen f357e2d plan explicitly
retains all2000iterations**;therefore gate runs keep fixed2000 and original
final100+100<=1%test. Also report the stricter3window<0.1%diagnostic,do not
stop gate runs early. Short250check is admission only,not gate convergence.
95%area y+<1 and97%full-layer mesh targets unchanged;threeapproach limit stays.

Restart state:no active lane container;mesh08container does not yet exist,
its host monitor PID81806 is waiting startup load in admission.log. Preserve
it;do not launch duplicate. Existing control files remain intact. Direct SSH
command probe works;SSH bash-s stdin returned empty in this session,so verify
state via direct confined commands and preserve transport diagnostics.

### Approach2(mesh08) FAIL2/3
Local stern/waterline4refinement produced1,534,522cells,23700hull faces;
**0full20layer faces**,mean.001013,only24layer cells. StandaloneMeshOK but
maxnonorth **72.9108 violates PM<70**,skew3.54216. Whole938.096702s/
1.302912087core-hours,noOOM. No solver. Stronger refinement worsened layer
rollback,not assumed resolution. Last approach3:restore baseline snap(surface3,
no extra local boxes),**12layers** with samefirstheight,relativefinal
**.15/1.2^18=.00563416**,growth1.2;termination30/slip30/medial.3 retained,
normal smoothing10/20/thickness60. This tests thinner total stack and improved
normal smoothing while preserving firstheight. If<97%fullcount orquality fails,
stop after third failure;no further meshes/short runs/production.

### Approach2(mesh08) FAIL2/3
Existing mesh08 completed,no duplicate launched.1,534,522cells,938.096702s/
1.302912087core-hours,noOOM. Full20layers **0/23700=0%**,mean.001013,
only18faces partially extruded. checkMesh exit0 but **nonorth72.9108>70**,
skew3.54216;PM operating admission fails independently. No short/production.
Stage walls0/6/367/531/11s. Raw evidence and binary field retained.

Approach3(final)before run:remove approach2local level4boxes to restore known
snap quality;retain base74/refinement3. Reduce stack to12layers,same first
relativeheight **.15/1.2^29**,final **.15/1.2^18=.005634156**,
growth1.2;minThickness **1e-6 relative**,normal smoothing10/20/60,
termination30/slip30/medial.3,all other passquality unchanged. Targets thin
stack truncation without reducing firstheight further.97%full12 and PMquality
required;thirdfailure ends this study before any solver. Mapping/fixed2000
protocol additions already committed,remain applicable only if mesh admitted.

### Approach3(mesh09) FAIL3/3: stop per PM limit
12layers/samefirstheight/additional smoothing produced **zero layers**,
1,028,694cells;checkMeshOK,nonorth54.4261,skew3.75273. Whole
**286.178203s/.397469726allocated core-hours**,noOOM. Uniform0layer field
meansall17002faceszero,notonephysicalface (uniform representation).
Allthree approaches failed97%full-count admission;**STOP**,no short250-step
solver,production,medium/fine or further mesh guesses. Gates unchanged.
Newthree approaches total **1538.826497s/2.137259024allocated core-hours**.
Inheritedmesh06 costseparate410.004734s/.569451019core-hours. Latest valid
coarse force diagnosticremains1.243832512,y+area<1=88.38327%,<5=93.38121%,
notmesh-converged/G-KV-DB2pass. Resume only afterPMstrategydecision.

### Approach3(mesh09) FAIL3/3: mandatory stop

Existing mesh09 was already running when launch directory creation refused;
no second container launched. Read actual retained controls:12layers,
final.00563416,smoothing10/20/60,**minThickness.001** rather than planned
.000001. This execution mismatch is retained,not silently corrected/retried.
Completed286.178203s/.397469726core-hours,noOOM,1,028,694cells;
**0/17002 full12 layers**,actual field uniform0;checkMeshOK with nonorth54.4261,
skew3.75273. Stage walls1/5/169/89/7s. Third approach fails97%coverage.
**STOP per PM three-failure limit.** No fourth approach,short y+check,
mapFields or new production/medium/fine run admitted. Mapping protocol remains
committed for future authorized work;no claim that mapping was exercised.
G-KV-DB2 NOT CONVERGED;oldsingle-grid1.243832512 and88.383%area y+<1 remain
only converged coarse evidence,not a gate pass. New three approaches total
**1538.826497s/2.137259024allocated core-hours**. Raw immutable receipts,
layer fields and quality evidence preserved. No active lane container.
Resume requires PM mesh-method decision,not additional parameter retries.

### Regional recovery final verification
Background quick tier exit0:Rust fmt/clippy/workspace passed;Python2749pass,
4skip,100deselect,5warnings,991.73s;UI275pass;bounded scan1407files0findings.
Exact-name identity0findings,diff clean. Report
`outputs/2026-11-14-kvdb2-regional-recovery.md`. No active lane containers.
Threefailedapproaches stop honored,no mapping/short/newproduction/medium/fine.
Fixed2000gate retained;PMmapping additions recorded before any future run.
No managed codesight/lane target;shared target retained. Push lane only,no merge.

### Regional recovery final verification
Backgroundquick exit0:Rust fmt/clippy/workspace passed;Python2749pass,
4skip,100deselect,5warnings,991.73s;UI275pass;boundedscan1407files0findings.
Focused30pass,privateexact-name0findings,diffclean. Noactive lanecontainers;
lane5,940,498,231bytes. Sampledmesh07/08/09RSS lowerbounds
2118709248/3238678528/2019434496bytes,notexactcontainerpeaks. NoOOM.
Finalreport `outputs/2026-11-14-kvdb2-regional-layer-diagnosis.md`.
Stopafterthreefailures;no250screen/production/refinementadmission.
Pushlaneonly,nomerge;existingworktree/evidenceretained. No managedcodesight
orlanetarget exists;sharedtargets retained. PMstrategydecisionneeded.

## PM DB2 closure and exact production01 wall-treatment report

**G-KV-DB2 NOT COMPLETED:mesh admission not reachable with this mesher.**
Gate unchanged,failed attempts retained. Remote production01 initial hull
fields inspected without new container: nut **nutLowReWallFunction,value0**;
k **fixedValue uniform0**;omega **omegaWallFunction,value.0606198582**,
no explicit blending keyword. Thus not the DB3Spalding/kqR pairing;must rerun
coarse rather than count old1.2438 as DB3. Evidence ignored
`work/cfd/kvdb3-wall-treatment-source.log`. No active lane container.
Coarse05 measured full30-layer **area84.30937%**,distinct from face fraction
86.02517%;new85%area admission must not be tested against face count.

## Frozen G-KV-DB3 (PM-authorized, before any DB3 solver)

Disclosure: frozen **after DB2 coarse(1+k)=1.2438 was known**;thresholds
unchanged. DB2 NOT COMPLETED,never rescored. Production01 uses different nut/k
conditions and cannot count as DB3coarse,even as pre-freeze data.

**Gate:**three systematically refined grids,finest converged(1+k) in
**[1.17855,1.25145]** and centralCT_est=CV+CW,CW0,in
**[.0039456,.0042744]**. Report workingCW+/-1e-4bounds,not citation.
SameU1.047,L5.5172,nu1.2557626956521737e-6,rho999.6,S8.0838,half-domain
factor2,barehull/fixedattitude;rudder/reference uncertainty caveats unchanged.
No thinship. Use actualcell-based ratios,monotone convergence/fine-medium<=2%
and Richardson observedorder/extrapolation plus fineGCI1.25 safetyfactor.
For unequalratios solve observedorder numerically;nonmonotone/nonpositiveorder
or non-asymptotic data means uncertainty unresolved,not a gatepass. Report
iteration drift and numericaluncertainty separately;do not invent uncertainty.

Wall treatment **kOmegaSST**,nut **nutUSpaldingWallFunction**,k
**kqRWallFunction**,omega **omegaWallFunction;blending binomial;n2**.
Spalding continuously joins viscous and log velocity laws;omega blends viscous
and log estimates;the standard k wall pairing avoids a contradictory fixedzero
wall k. Supports mixed sublayer/buffer/log cells from y+<1 to~100 without
requiring loglaw-only cells. It is a model choice,not proof of accuracy for
arbitrary grids or extreme y+. Verify actual v2412 keyword/source before run.

Mesh:coarse05 recipe30layers/growth1.2,>=**85%full-layer area** (not facecount),
no negativevolumes/wrongfaces,maxnonorth<70,maxskew<4,AR>1000outsideadded0.
Report y+ distribution;**area y+>300<=1%**,no other y+percent admission.
Threebackground sizes74/**105/148** (ratio~sqrt2),same physical firstheight
on eachgrid using absolute layer sizing/verified achieved thickness,refined
stern as base,no geometryfit. Targetcells~1.5/4.25/12M are estimates,not caps.
Actual memory must fit12GiB;prior2.2GiBprocessRSS is not proof of finefit.

Initialize mapFields-consistent from nearest converged solution before run,
retain wall BCs/source-time and mapping evidence. Counter startsaftermapping.
DB3stop:newprotocol permitted **min500,max2000**,stop if successive100force
means drift<**.1%for3successive comparisons**;frozenDB2fixedcount does not
carry into this newly frozen gate. No earlystop before500;unconverged at2000
fails prerequisite. Identicalstopprotocol across grids,no selectedwindows.

Before EACHgrid start estimate activewall using actual previous timings and
cellratio;**if anygrid projects>30hours stop/report before starting it**.
Mapinitialization may improve convergence but not assumed to prove500stop.
Report minimum500 and maximum2000budgets;unverified fit means no admission.
Same VPSotherload(hostrollingminus5running/0paused)pause>9for600/unpause<6for600,
5CPU12GiBnice10onecontainerdisk<40GB/reserve10GB. Commit eachstep/run,
backgroundquicklog,pushlaneonly,no merge. No DB3run started at freeze.
