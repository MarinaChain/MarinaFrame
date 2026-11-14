# G-KV-DB3 freeze and pre-run admission blocker

## Step1: exact previous hull treatment

Inspected production01/data/0 fields on VPS without a solver run:
- nut:nutLowReWallFunction,valueuniform0.
- k:fixedValue,valueuniform0.
- omega:omegaWallFunction,valueuniform.0606198582,no explicit blending entry.

This is not the frozen DB3Spalding/kqR pairing. Production01 cannot count as
DB3coarse. G-KV-DB2 is **NOT COMPLETED:mesh admission not reachable**,unchanged.

## New gate frozen before solver runs

Commit3043aac freezes G-KV-DB3. Disclosure explicitly states DB2single-grid
(1+k)=1.2438was already known;thresholds were not changed. Acceptance remains
(1+k)[1.17855,1.25145],CT_est[.0039456,.0042744],CW0with+/-1e-4working
bounds. Three grids,actual refinement ratios,grid-convergence estimate and
uncertainty required. No one-grid retrospective pass.

Proposed treatment:kOmegaSST,nutUSpaldingWallFunction,kqRWallFunction,
omegaWallFunction with binomialblending/n2. Spalding joins viscous/logvelocity
laws and blendedomega handles low/highRe limits;the pairing is intended for
mixed y+<1through~100,not a guarantee of hull-model accuracy. Runtime/source
keyword validation is still required;no DB3wall treatment was exercised.

Meshbasecoarse05,30layers,growth1.2,>=85%full-layerarea,PMquality limits,
<=1%area y+>300. Constant~sqrt2base-refinement74/105/148,same physical
firstheight. mapFields from nearest converged solution. Newstop:min500,
max2000after mapping,three successive100-windowcomparisons drift<.1%.
This is newDB3protocol,not a weakenedDB2fixedcount gate. OtherVPSrules unchanged.

## Actual pre-run blocker

Exact coarse05full30-layerarea **84.30936956%**,below85%. Its86.02517%
facecount is not area and cannot substitute. No solver is admitted. No new
regionalmesh retries after the prior three-failure stop. Need PMmesh-method
or admitted-mesh decision;do not round84.31to85or change the frozen threshold.

Provisional activewall budgets using old1900-step26846.5s timing:coarse2000
~7.85h,medium~22.4h,fine~62.8h at roughlinearcell scaling. Fine500minimum
~15.7h is not proof of convergenceby500. These are planning estimates,not
measured scaling. Before eachgrid,replace with precedinggrid evidence;
stop before any projected>30hgrid. Current stop is earlier,at mesh admission.

No DB3solver/mesh runs,no newcells/core-hours/y+or(1+k),no DB3score. Previous
results/failures retained. Stable-source quick tier exit0:Rust fmt/clippy/
workspace passed;Python2,749passed,4skipped,100deselected,fivewarnings in
659.05s;UI275passed;boundedscan1,409files,zero findings. Exact-name identity
scan zero findings;diffclean. Push lane only,no merge.
