# KVLCC2 physical double-body study

Status: in progress; no G-KV-DB pass is claimed.

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

Medium final force 20.4808400 N, CV 0.004624263674, implied (1+k)
1.340500704. Fixed-window drift 0.00003369%; y+ min/mean/max
13.7969/129.155/1266.09. Both solver exits are successful processes;
three-mesh convergence remains unmeasured until the fine run.

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

Raw logs, immutable attempt receipts, force histories, offsets and numeric
checks remain in the approved ignored main `work/cfd/` folder. The plan records
each run checkpoint and exact resume state.
