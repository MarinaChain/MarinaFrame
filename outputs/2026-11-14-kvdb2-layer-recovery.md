# KVLCC2 DB2 prism-layer recovery

**G-KV-DB2 remains blocked/not converged.** The frozen gate in f357e2d and
prior failures are unchanged. Thin-ship is not used.

## Runtime and method

The exact pinned OpenCFD v2412 minimal image contains no cartesianMesh or
cfMesh path. Checked installed platforms and complete stopped lane-container
filesystem inventory. No image change, package install or system change was
made. Added only plain cartesianMesh to runner allowlist with red/green tests;
options and unrequested utilities remain rejected. No cfMesh mesh was run.

Used PM-authorized fallback: official retained DTC addLayersControls, separate
snapping and layer-only passes, relative final thickness0.3,30 layers,growth1.2,
featureAngle180, increased smoothing. Initial pass-only quality relaxation
rolled back all layers. A root-cause-directed retry disabled determinant/twist
restrictions for thin prisms during extrusion only. Standalone checkMesh and
95% full-count acceptance were not relaxed.

## Physical recovery attempts

| Attempt | Cells | Full-count layer coverage (hull) | checkMesh | Whole wall s | Allocated core-hours |
|---|---:|---:|---|---:|---:|
| Coarse04 | 1,028,694 | 0/17,002 =0% | Pass | 250.453681 | 0.347852335 |
| Coarse05 | 1,501,521 | 14,626/17,002 =86.02517% | Fail | 345.299768 | 0.479583011 |
| Medium | Not run | Unavailable | Not run | — | — |
| Fine | Not run | Unavailable | Not run | — | — |

Five allocated cores per attempt. Recovery total595.753449s (9.92922min),
0.827435345 allocated core-hours, not measured CPU consumption.04 stage
walls1/5/157/76/8s (surfaceCheck/blockMesh/snap/layers/checkMesh);05 walls
0/9/182/127/12s. Whole receipts include overhead. Startup loads1.71 and1.25;
no load pause/OOM/>24h projection occurred.

Coarse05 any-extrusion coverage99.8118% and mean27.8 layers do **not** meet
95% full30-layer coverage. Binary nSurfaceLayers field:32 faces have0 layers,
2,344 have1–29,14,626 have30. Final checkMesh fails high aspect ratio:
22,409 cells flagged,maximum1566.2. All volumes are positive; maximum
nonorthogonality62.6896 and skewness3.29121. These passes do not cancel the
failed aspect-ratio check. No solver admitted, so **y+ distribution and (1+k)
are unavailable on every recovery grid**; no CT_est/CW bounds are measured.

## Memory

Sampled layer-process kernel VmHWM lower bounds:04 **2,484,256,768bytes
(2.314GiB)**,05 **2,369,462,272bytes (2.207GiB)**. These are not exact
container peaks. Host lacks memory.peak; image lacks Python and GNU time.
The12GiB hard limit remained active. Previous2.2GiB does not prove4M fits.

## Verification and resume

Stable-source quick tier exit0: Rust format/clippy/workspace tests passed;
Python2,745 passed,4 skipped,100 deselected,five warnings in547.61s;
UI275 passed,0 failed; bounded secret scan1,403 files,0 findings.
Targeted recovery/remote contracts24 passed. Exact-name identity scan and
final lane state are checked before push. Existing worktree/evidence retained.

Raw logs, memory samples, immutable receipts and binary layer field remain
in approved ignored main work/cfd/kvdb2-* files. No medium/fine or solver
run is justified until full-count coverage>=95% and checkMesh pass together.
Next action needs revised mesh strategy or separately authorized cfMesh
runtime, not a weakened gate or more parameter guesses. Push lane only,no merge.
