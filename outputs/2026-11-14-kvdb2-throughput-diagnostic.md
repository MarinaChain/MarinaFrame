# KVLCC2 DB2 throughput diagnosis

G-KV-DB2 and PM mesh-admission rules remain unchanged. The old serial early
67.6-hour projection is retained as history, not reused as a new estimate.

## Root-cause evidence

Old solver log: nProcs1 despite5CPU quota. Per-step wall31,42,55,190,290s.
Pressure GAMG counts23+4,7+77,10+137,25+510,55+639; velocity1–3 and
k/omega1–2. Pressure solves met relTol; no observed maximum-iteration cutoff.
Anisotropic-layer pressure convergence dominated. k/omega bounding occurred.
Controls were pGAMG/GaussSeidel tol1e-7 relTol.01; others smoothSolver,
p.3/U,k,omega.7 relaxation,consistent SIMPLE/nonorth1.

## Tested recovery

Allowlist permits only exact five-rank simpleFoam/potentialFoam commands,
serial potential initialization,reconstructPar latestTime; arbitrary MPI ranks,
binaries,hosts,options or libraries remain rejected. Tests failed first then
22remote tests passed. Five scotch subdomains, same5CPU/12GiB/nice10/networknone.
Pressure now GAMG/DICGaussSeidel,faceAreaPair cached agglomeration,
coarsest100cells,merge1,post2/finest2 sweeps,tol1e-7 relTol.05,maxIter200;
velocity/turbulence smoothSolver,p.3/others.5,consistentno/nonorth1.
Potential-flow initialization uses10corrections. These are explicit numerical
recovery settings,not exact prescriptions from the reference papers.

Diagnostic01:decompose10s;MPI self,tcp transport failed before solver because
networknone left onlyself usable. Whole32.277242s/0.044829503allocated core-hours.
Retained failure. Diagnostic02 uses local self,vader shared memory with single-
copy disabled; no network or security permission changes.

## Measured result and safety stop

Diagnostic02 confirms **nProcs5**,decompose11s,potential40s. Completed85 of
required100iterations. Steps21–85:mean **13.09231s/step**,median12,p9522.8.
Pressure2–3GAMG iterations,mean2.16923,no200cap hits. This is combined MPI,
initialization and numerical-control improvement,not isolated MPI scaling.

Host monitor **paused** the container during iteration86 under retained
rolling600>9 for600further seconds rule. No automatic unpause. Snapshot to
pause **1242.165595s/1.725229992allocated core-hours**,last sampled Docker
memory1.938GiB,not peak;noOOM. Startup load.59. Total diagnostic attempts
through pause1274.442837s/1.770059496core-hours,excluding continuing paused
reservation. Do not interpret pause as solver exit or completed100-step run.

Required100steps incomplete,so **no new2000-step projection**,force convergence,
y+ or(1+k) result. No new coarse production/medium/fine run. G-KV-DB2 remains
blocked/not converged. PM approval is required to resume this exact paused
container for remaining15steps; then measure21–100and project before continuing.
Do not replace required100by extrapolating partial window.

Raw logs,iteration table,timing summary,runtime inventory and pause receipt are
in approved ignored main work/cfd/kvdb2-mpi-diagnostic02 and related logs.
Final stable-source quick tier exit0:Rust format/clippy/workspace passed;
Python2,746passed,4skipped,100deselected,five warnings in524.99s;UI275passed;
bounded secret scan1,405files,zero findings. Exact-name private identity scan
zero findings. No managed codesight index or lane target exists;shared targets
retained. Push lane only,no merge.
