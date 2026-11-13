# KVLCC2 physical double-body study

Status: **G-KV-DB NOT PASSED**. All three physical meshes and 2,000-iteration
solver runs completed. CV is nonmonotone, and the fine/medium change is
5.84766%, above 2%. The required finest converged mesh does not exist in this
study. The nominal finest-mesh hybrid also lies outside the frozen CT band.

## Frozen conditions

Scale 1:58, Lpp 5.5172 m, draft 0.3586 m, speed 1.047 m/s (nominal Fn
0.142), rho 999.6 kg/m3, nu 1.2557626956521737e-6 m2/s, reference wetted
area 8.0838 m2. Bare hull, no appendages, fixed zero attitude, waterplane
symmetry, SST steady RANS. Experimental attitude correspondence is unresolved.
The PM accepted the community solid for CFD; the earlier wetted-area failure
remains a failure. This is not a free-surface RANS validation.

G-KV-DB requires CT_est = CV + Cw in [0.0039045, 0.0043155], monotone
three-mesh CV, fine/medium difference <=2%, and final two fixed 100-sample
force-window drift <=1%. Engineering approval remains false.

## Physical runs

Five allocated cores per stage; core-hours mean allocated cores times elapsed
wall hours, not measured CPU use. Stage times have integer-second resolution.
Whole-attempt times include admission-independent container/monitor overhead.

| Attempt | Cells | Stage wall (s) | Stage core-hours | Whole wall (s) | Whole core-hours |
|---|---:|---:|---:|---:|---:|
| Coarse mesh 01, failed before refinement | 8,192 background | 2 | 0.002778 | 31.452394 | 0.043683881 |
| Coarse mesh 02, checkMesh OK | 16,257 | 5 | 0.006944 | 31.076458 | 0.043161747 |
| Coarse solver 01, 2000 iterations | 16,257 | 163 | 0.226389 | 182.187129 | 0.253037680 |
| Medium mesh 01, checkMesh OK | 35,426 | 24 | 0.033333 | 32.409143 | 0.045012698 |
| Medium solver 01, 2000 iterations | 35,426 | 365 | 0.506944 | 393.009871 | 0.545847042 |
| Fine mesh 01, checkMesh OK | 80,069 | 26 | 0.036111 | 31.475456 | 0.043715910 |
| Fine solver 01, 2000 iterations | 80,069 | 868 | 1.205556 | 879.062201 | 1.220919723 |

Medium final force 20.4808400 N, CV 0.004624263674, implied (1+k)
1.340500704. Fixed-window drift 0.00003369%; y+ min/mean/max
13.7969/129.155/1266.09. Fine final force 21.6784900 N, CV 0.004894674917,
implied (1+k) 1.418888635. Fine drift is 0.00000185%; y+ min/mean/max
17.1999/90.9219/804.101. Medium/fine extruded-face coverage is
92.3775%/97.0385%, average layers 2.49/2.84.

Actual cell-based refinement ratios are 1.29646 and 1.31234. CV decreases
then increases, and the fine/medium change is 5.84766%: convergence fails.
Force-window stability passes on all three runs, but does not cure spatial
nonconvergence. Implied finest (1+k) is diagnostic, not converged; compare
prior Holtrop-type values 1.36 (1982) and 1.34 (1984).

Whole monitored attempts, including the failed attempt, total 1,580.672651 s
(26.3445 min), 2.195378682 allocated core-hours. Mesh stages total 57 s /
0.079167 core-hours including the failed attempt; solver stages total 1,396 s /
1.938889 core-hours. Whole totals include overhead. No load pause or >24-hour
projection occurred. Every stage started below load1 4; fine rolling-load
monitoring passed a complete 600-second window.

Coarse final force 24.1434222 N, CV 0.00545121930, implied (1+k)
1.58022203. Its fixed-window drift is 0.00000746%. Actual ITTC-57 CF is
0.00344965404. Coarse layers cover 92.9181% of faces, mean 2.56 layers;
y+ min/mean/max 30.2276/170.305/1766.82. The high local y+ is a limitation,
not a reason to change controls after inspecting forces.

## Thin-ship calculation and approximation

The module is byte-identical to `resistance_thin_ship/__init__.py` from merged
`origin/continue/v0.5` at 76d7e01b99d32e1cf2d178176d9e00c91fd87ee1.
Offsets are horizontal intersections of the solid's preserved wetted
triangulation, using the outer nonnegative half-breadth. The real immersed
transom stays in CFD. For thin-ship only, each waterline ends at its source
stern profile and closes to zero over its terminal grid panel. That panel
shrinks with longitudinal refinement. This is the PM-authorized stern closure,
not a validated transom correction. No hull length, breadth or area was fitted.

| x nodes | z nodes | Angle nodes | Lambda maximum | Cw |
|---:|---:|---:|---:|---:|
| 321 | 33 | 512 | 24 | 0.004575490115 |
| 641 | 65 | 512 | 24 | 0.004570431108 |
| 1281 | 129 | 512 | 24 | 0.004559510253 |
| 1281 | 129 | 1024 | 24 | 0.004559510273 |
| 1281 | 129 | 1024 | 32 | 0.004560656669 |
| 2561 | 257 | 1024 | 32 | 0.004551062078 |
| 2561 | 257 | 2048 | 40 | 0.004551615822 |

Selected Cw = 0.004551615821723439, Rw = 20.1590830 N. The last panel
refinement changes Cw by -0.21038%; the final combined angle/tail change is
+0.01217%. Offset-integrated volume 1.60142559 m3 differs from exact CAD
1.600124995282 m3 by +0.08128%. These checks do not bound stern-model or
solid-tessellation error. Contrary to the expected small wave contribution,
this approximation produces a large wave term. It is retained, not tuned down.

## Hybrid sensitivity and gate outcome

These are nominal finest-mesh diagnostics, not estimates based on a converged
mesh. No favourable mesh or force window was selected.

| Wave assumption | CT_est | Signed error vs 0.004110 |
|---|---:|---:|
| Cw = 0 | 0.004894674917 | +19.09185% |
| Stated thin-ship Cw | 0.009446290739 | +129.83676% |
| Cw doubled | 0.013997906560 | +240.58167% |

The stated Cw is used for the nominal score, not zero or a fitted correction.
G-KV-DB does not pass: convergence prerequisites fail and the nominal stated-Cw
score exceeds the upper bound 0.0043155. Large Cw under this blunt-hull/stern
approximation needs investigation, not silent correction. No further mesh or
model changes are authorized by this report; the frozen result is retained.

## Verification and evidence

Final stable-source quick tier exited 0: Rust format/clippy/workspace tests;
Python 2,741 passed, 4 skipped, 100 deselected (674.41 s, five dependency
warnings); UI 275 passed; bounded tracked secret scan 1,400 files, zero findings.
Focused CFD contracts: 70 passed. Exact-name private identity scan: zero findings.
A broader exploratory identity scan matched historical local filesystem paths;
it was not a zero-finding scan. New report content contains no VPS address.

Raw logs, immutable attempt receipts, force histories, offsets and numeric
checks remain in the approved ignored main `work/cfd/` folder. The plan records
each run checkpoint. Resume requires a PM decision on failed spatial convergence
and the unexpectedly large stern-closed thin-ship term. No automatic rerun,
free-surface substitution, gate change or engineering approval is made.
