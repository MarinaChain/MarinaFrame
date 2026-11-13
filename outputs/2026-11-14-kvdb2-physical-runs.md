# G-KV-DB2 wall-resolved study: blocked at coarse mesh

## Decision and gate

The previous G-KV-DB failure is unchanged. Thin-ship is not valid for this
blunt closed-transom KVLCC2 approximation; its Cw is not used in DB2.
G-KV-DB2 was frozen in `f357e2d` before any DB2 remote run.

- Finest converged (1+k) in [1.17855, 1.25145], central reference 1.215.
- Central CT_est=(1+k) CF57 + CW, CW=0, in [0.0039456, 0.0042744].
- CW sensitivity is +/-0.0001, a PM working estimate, not a published value.
- Three monotone CV grids, fine/medium <=2%, final two fixed 100-sample
  force-window drift <=1%. Wall-resolved y+<1 must be demonstrated.
- Half-domain y>=0, waterplane z=0 symmetry, full-hull force multiplier 2,
  full reference wetted area 8.0838 m2. Conditions otherwise unchanged.

The supplied reference file was read. The 1.215 value is a secondary citation
(Argyros 2026 citing Larsson & Raven 2010). The 1.9% uncertainty is a ballast
analogue, not published design-draught uncertainty. Published reference cases
include rudder; these cases remain bare hull. Typical multi-code double-body
(1+k)=1.223 at Fn .142 and spread1.6% are context, not replacement measurements.

## Physical attempts

All attempts use five allocated cores and the unchanged 12GiB Docker limit.
Core-hours are allocated cores times wall hours, not measured CPU consumption.

| Attempt | Actual cells | Whole wall s | Allocated core-hours | Outcome |
|---|---:|---:|---:|---|
| Coarse mesh 01 | 7,219,675 before layers | 785.248483 | 1.090622894 | Stopped: exceeded 6M ceiling and coarse target |
| Coarse mesh 02 | No new mesh | 32.898258 | 0.045692025 | Instrumentation failed: no python3 in pinned image |
| Coarse mesh 03 | 1,029,000 | 344.404176 | 0.478339133 | checkMesh OK; wall-layer admission failed |
| Medium | Not run | — | — | Failed coarse grid family |
| Fine | Not run | — | — | Failed coarse grid family |

Total **1162.550917 s (19.37585 min), 1.614654052 allocated core-hours**.
Coarse03 stage times: surfaceCheck1s, blockMesh6s, snappy317s, checkMesh8s
(332s / 0.461111111 allocated core-hours); whole-attempt time adds overhead.
No OOM, load pause or >24-hour projection occurred. Startup loads were
2.03, 1.38 and 1.15. Only this lane's containers were started/stopped.

## Why solver admission failed

Coarse03 has max nonorthogonality64.9424, skewness3.75273, one connected
flow domain and checkMesh `Mesh OK`. But requested30 absolute prism layers
survived on only **146 of 17,002 hull faces (0.858723%)**; mean layers
**0.018**, mean overall thickness **5.19e-5m**, reported thickness ratio0.549%.
The first-cell setting alone does not establish wall resolution. Running
simpleFoam on this mesh would not satisfy the requested wall-resolved study.
No solver was launched; **(1+k) is unavailable on every DB2 grid**. Neither
CT_est nor its CW bounds are measurable. G-KV-DB2 is **BLOCKED / NOT CONVERGED**,
not passed and not a new resistance failure measurement.

The first broad aft volume produced too many cells; its sizing correction was
committed before any force measurement. No force-based tuning occurred.
The source CAD centreplane Boolean returned empty; the accepted full closed
surface is instead intersected by the half-domain mesher, preserving skin.

## Memory evidence and limitations

This VPS kernel does not expose cgroup `memory.peak`. The pinned image has no
Python or `/usr/bin/time`; no packages or image changes were made. The original
wrapper failure is retained. Coarse03 samples `/proc/<solver>/status` at0.2s:
maximum observed kernel VmHWM **2,385,797,120 bytes (2.222 GiB)**. This is a
sampled process high-water lower bound, **not exact peak container memory**.
An oversized coarse01 Docker sample reached5.310GiB; exact peak is unavailable.
All processes stayed under the12GiB hard limit and no OOM was reported.

## Resume and evidence

A new prism-layer strategy is needed before solver admission or medium/fine.
Do not substitute wall functions, infer y+ from requested thickness, reuse old
DB1 form factors, or claim convergence from a single clean checkMesh. The gate
and failures remain frozen. Raw attempt receipts/logs and layer/memory samples
are preserved in approved ignored main `work/cfd/kvdb2-*` files. The existing
worktree remains available. Final stable-source quick tier exited0: Rust
format/clippy/workspace tests passed; Python2,743 passed,4 skipped,100 deselected,
five warnings in483.57s; UI275 passed; bounded secret scan1,402 files,zero
findings. Exact-name private identity scan:zero findings. No active lane
container remains; lane directory1,990,734,749 bytes, host free168,935,940,096
bytes. No managed codesight index or lane-local target exists; shared targets
were retained.
