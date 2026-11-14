# KVLCC2 regional layer diagnosis: three-approach stop

G-KV-DB2 and95%area y+<1 admission remain unchanged. PM requires97%full-layer
mesh coverage before a250-step y+ screening run. No new solver was admitted.

## Resume inspection

Existing worktree was clean. Mesh06 exited3 (not a session-restart error):
1,476,374cells,410.004734s,0.569451019allocated core-hours,noOOM.
Its checkMesh failure was high aspect ratio3128.5;positive volumes,
nonorth68.0058 andskew3.75273. It did not repair layer coverage. No active
lane container remained at intake.

## Measured spatial map

Coarse05 actual face centres/areas,final production yPlus,and matching
nSurfaceLayers establish **all y+>5 area has incomplete layers**.
Total y+>5 is6.61879%wetted hull area. Coordinate masks below overlap and
are geometric diagnostic regions,not exact anatomical CAD patches.

| Region | Definition in model metres | y+>5, %whole hull area | Incomplete layers, %whole hull area |
|---|---|---:|---:|
| Waterline cut | z>-.02 | .61861 | .86328 |
| Transom edge | x>-.03 | .50449 | .53226 |
| Bow bulb | x<-4.8,z<-.05 | 0 | 0 |
| Stern bulb | x>-.65,z<-.05 | 3.95056 | 6.34239 |
| Bilge | -4.8<=x<=-.65,z<-.25 | 0 | 2.36429 |
| Remaining skin | outside union above | 1.76724 | 5.83481 |

Do not sum overlapping rows. Half-hull measured area4.112614m2. x increases
aft,z=0waterplane. Region masks were not adjusted to improve a result.

## Three new meshing approaches

All cases retained source shape,first-cell height target,growth1.2,5CPU,
12GiB and one-container limits. No force-based geometry or gate tuning.

| Approach | Change | Cells | Full requested layer coverage | Whole wall s | Allocated core-hours |
|---|---|---:|---:|---:|---:|
| 1,mesh07 | 20layers,samefirstheight,termination0/slip180/medial.8 | 1,028,694 | 0% | 314.551592 | .436877211 |
| 2,mesh08 | Restore termination30/slip30/medial.3;local stern/waterline level4 | 1,534,522 | 0% | 938.096702 | 1.302912087 |
| 3,mesh09 | Baseline surface3,12layers,samefirstheight,more smoothing | 1,028,694 | 0% | 286.178203 | .397469726 |

Approach2 retained only24layer cells andmaxnonorth72.9108,also violatingPM<70.
Approaches1/3 have uniform0layer field onall17,002hull faces,notonephysicalface;
clean checkMesh cannot admit a mesh without the required layers. No OOM.
New approaches total1538.826497s (25.64711min),2.137259024allocated core-hours.
This excludes separately retained inheritedmesh06 and earlierproduction.
Sampled process high-water RSS lower bounds for07/08/09 are
2,118,709,248 /3,238,678,528 /2,019,434,496bytes (not exact container peaks).
No active lane container remains;lane directory5,940,498,231bytes,under40GB.

**Stopped after three failures as directed.** No short solver,production,
medium/fine or fourth mesh. Prior valid single-grid diagnostic remains
(1+k)=1.243832512,force drift.000947797%,area y+<1=88.38327%,<5=93.38121%.
This is not a converged grid-family gate result. G-KV-DB2 remains blocked.

Raw maps,face fields,attempt receipts andlogs are in approved ignored main
work/cfd/kvdb2-*. Plan records each approach before execution and its terminal
result. Final background quick tier exit0:Rust format/clippy/workspace passed;
Python2,749passed,4skipped,100deselected,five warnings in991.73s;UI275passed;
bounded secret scan1,407files,zero findings. Focused CFD safety30passed;
exact-name private identityzero findings,diff clean. Push lane only,no merge. Resume needs
PM strategy decision;do not continue parameter guesses beyondthethree-attempt limit.
