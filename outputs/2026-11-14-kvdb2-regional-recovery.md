# KVLCC2 regional layer recovery: stopped at three failures

G-KV-DB2 remains frozen and not converged. The97%full-layer mesh target and
95%area y+<1 admission are unchanged. No new solver was admitted.

## Measured regional diagnosis

Matched coarse05 face centres/areas,nSurfaceLayers and final2000-step y+.
All y+>5 area belongs to incomplete-layer faces. Regions are overlapping
coordinate masks,not anatomical CAD patches;their shares must not be summed.

| Region | Definition (model m) | y+>5, % total hull area | Incomplete layers, % total hull area |
|---|---|---:|---:|
| Waterline cut | z>-.02 | 0.619 | 0.863 |
| Transom edge | x>-.03 | 0.504 | 0.532 |
| Bow bulb | x<-4.8,z<-.05 | 0 | 0 |
| Stern bulb | x>-.65,z<-.05 | 3.951 | 6.342 |
| Bilge | -4.8<=x<=-.65,z<-.25 | 0 | 2.364 |
| Remaining skin | Outside mask union | 1.767 | 5.835 |

Total hull area with y+>5:6.619%. Main deficit is stern/termination skin,
not bow. Coordinate segmentation is explicit and reproducible in ignored
work/cfd/kvdb2-layer-region-map.json/.npz.

## Three bounded meshing approaches

| Approach | Cells | Full requested layers | Whole wall s | Allocated core-hours |
|---|---:|---:|---:|---:|
| 1:20-layer reduced stack/termination controls,mesh07 | 1,028,694 | 0% | 314.551592 | 0.436877211 |
| 2:local stern/waterline level4,mesh08 | 1,534,522 | 0% | 938.096702 | 1.302912087 |
| 3:12-layer stack/increased smoothing,mesh09 | 1,028,694 | 0% | 286.178203 | 0.397469726 |

Total1538.826497s(25.6471min),2.137259024allocated core-hours,5CPUquota.
NoOOM. Mesh08 also violates PMnonorthogonality limit:72.9108>70,despite
checkMesh exit0. Mesh07/09 pass basic mesh checks but have no layers.

Actual mesh09minThickness was.001,not planned.000001. This execution mismatch
is preserved. The existing mesh09 was discovered running when a fresh launch
refused an existing directory;no duplicate container was started. The third
failure limit ends retries,including a retry solely to correct that mismatch.

## Protocol changes and results not obtained

Before any new solver,the plan now requires mapFields-consistent from old
coarse production01time2000;medium/fine map next-coarser converged fields.
Mapping was **not exercised**,because no mesh met admission. The proposed
three-successive100-window<.1%stop is recorded as diagnostic only:the frozen
plan explicitly requires all2000iterations,so gate runs retain2000 and final
100+100drift<=1%. No early-stop weakening.

No short250-step y+check,new production,medium/fine,or new(1+k)exists. Prior
single-grid diagnostic1.243832512,force drift.000947797%,88.38327%area y+<1
and93.38121%area y+<5 remain the only converged coarse results,not gate pass.
Next action requires PM mesh-method decision;do not run a fourth approach.

Raw receipts,layer fields,quality logs and transport diagnostics remain in
approved ignored main work/cfd. Existing worktree retained. Final stable-source
quick tier exit0:Rust format/clippy/workspace passed;Python2,749passed,
4skipped,100deselected,five warnings in991.73s;UI275passed;bounded secret
scan1,407files,zero findings. Exact-name identity scan zero findings. No active
lane container remains. Push lane only,no merge.
