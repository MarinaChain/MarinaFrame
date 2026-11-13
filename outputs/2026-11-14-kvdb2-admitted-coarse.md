# PM-admitted coarse05 solver: runtime-limited

G-KV-DB2 at f357e2d remains unchanged and **blocked/not converged**. The new
PM admission rule was recorded in20c6cb8 before the solver. Earlier mesh
failures remain historical evidence, not deleted or relabelled as gate passes.

## Admission evidence

Exact retained coarse05 mesh:1,501,521 cells,86.02517% full30 layers,
99.8118% partial extrusion. Positive volumes and face pyramids; maximum
nonorthogonality62.6896<70,skewness3.29121<4. Cell-set intersection proves all
22,409 high-aspect-ratio flagged cells belong to472,827 added layer cells:
**high-aspect cells outside layers=0**. This conservatively covers AR>1000.
The previous aspect-ratio flag is a PM-accepted near-wall warning, not a new
G-KV-DB2 tolerance. Factor2 and full wetted reference8.0838m2 unchanged.

## Actual solver execution

Started at load1=1.06,5CPU quota,12GiB memory limit,nice10,existing host
rolling-load/disk supervisor. Ran simpleFoam on the exact admitted mesh.
Completed iteration clocks1..5:31,73,128,318,608seconds. Iteration6 was in
progress when stopped. Projection608/5*2000=243,200seconds=67.5556hours;
iterations4 and5 were becoming slower. This is early throughput,not a stable
convergence rate; nevertheless it exceeds the retained PM24-hour stop rule.
No restart or automatic unpause was used.

Container exit143,wall **721.554989seconds (12.02592minutes)**,
**1.002159706 allocated core-hours**. Sampled kernel process high-water RSS
**2,287,751,168bytes (2.131GiB)**,a lower bound,not exact container peak.
No OOM or load pause. No active lane container remains.

## Unavailable results

Only five complete force samples exist. There are no two100-sample windows,
so force convergence and a credible single-grid(1+k) are unavailable. Partial
forces are retained but not reported as a form-factor diagnostic. yPlus.dat
contains only its header:scheduled100-step output was never reached. No final
boundary field exists; y+ distribution and shares below1/below5 are unavailable.
A binary hull-geometry reader was checked against the retained layer field;
it gives half-hull area4.112614m2,but geometry alone cannot establish y+.
No first-layer change is inferred from absent y+ data. Medium/fine were not
admitted. No CT_est/CW bounds or gate score is claimed.

## Evidence and resume

Ignored main work/cfd holds cell sets,aspect-admission JSON,partial force.dat,
solver log,early throughput,memory samples and immutable terminal receipt.
Resume requires PM compute/numerical-throughput decision under the24-hour rule.
Do not bypass the stop by restarting or claim early partial forces converged.
Final stable-source quick tier exit0:Rust format/clippy/workspace passed;
Python2,745 passed,4 skipped,100 deselected,five warnings in501.09s;
UI275 passed;bounded secret scan1,404 files,zero findings. Exact-name private
identity scan zero findings. No managed codesight index or lane target exists;
shared target retained. Commit/push lane only,no merge.
