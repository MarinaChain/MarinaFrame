# G-KV-DB3 corrected admission and mapped coarse attempt

PMerratum52e6710was committed before anyDB3solver/result. It corrects the
face/area confusion and makes layerpresent>=95%area the meshprerequisite;
full-layerarea informationonly,250-steparea y+>300<=1%. Thresholds,wallpairing,
ratio,mapping,stoppingunchanged. Coarse05present99.87747%,full84.30937%,so
admitted. Production01oldwallconditions remainineligibleasDB3coarse.

TestedDB3Spalding/kqR/binomialomega fields and min500/max2000three100-window
<.1%stop contracts:29focusedtests passed. Officialv2412source confirms
blendingbinomial and exponentkeywordn. Samehalfmesh1,501,521cells,5MPIranks,
5CPU12GiBnice10networknone,otherloadmonitor,noimage/systemchanges.

| Attempt | Outcome | Whole wall s | Allocated core-hours |
|---|---|---:|---:|
| Coarse01 | mapFieldscompleted;binaryfieldwall-editstartupfailed | 61.622038 | 0.085586164 |
| Coarse02 | mapped/ASCIIconverted/exactBCs;divergediteration40 | 1048.987686 | 1.456927341 |

Coarse02stagewallsmap44/convert28/decompose56/solver900s. Initialfields mapped
consistentlyfromproduction01time2000;mappingemittedtet-decompositionwarnings,
retained. ASCIIconversion allowedexactwallBCediting. VerifiednutUSpalding,
kqR,omegaWallFunctionbinomialn2beforedecompose. Omega boundedfromiteration1,
maximum4.01424e11;force/continuitylatergrewunbounded;velocityhit1000linear
iterationsat40,rank2FPEinDICpressure,exit136. NoOOM.

Total1110.609724s(18.51016min),1.542513505allocatedcore-hours. No250-step
y+fieldorvalidformfactor. DivergentforcesarenotaDB3measurement. No medium/fine
started;noDB3score. These failuresdo notprovewallmodelinvalid;rootcausecould
involvemappedturbulence/BCtransition/numericsandisnotestablished. Preserve
allsourcefields/logs/receipts;donottuneagainstinvalidforces.

The medium/fineprojectioncannotbereplacedbydivergenttimings. Newrunneeds
root-causeinvestigationfirst. G-KV-DB3NOTCOMPLETED,gateunchanged. Failedcoarse
checkpointcommitted/pushedpromptly. Finalstablequickexit0:Rustfmt/clippy/
workspacepassed;Python2751passed,4skipped,100deselected,5warnings604.57s;
UI275passed;boundedscan1412files0findings;exact-nameidentity0findings.
Laneonly,no merge.
