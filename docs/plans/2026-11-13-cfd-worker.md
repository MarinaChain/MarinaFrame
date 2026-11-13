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
