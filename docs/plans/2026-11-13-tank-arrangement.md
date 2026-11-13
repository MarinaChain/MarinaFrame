# Tank arrangement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate draft tanker compartments from a real closed hull, with capacities, centres and cited rule screens.

**Architecture:** Own typed inputs and outputs in `src/vessel_reconstruction/arrangement_generator/`. Intersect axis-aligned compartment boundaries with a closed OCCT hull; never substitute box volume for hull volume. Accept STEP hulls and solids made from existing Lackenby sections without importing any other batch lane. Expose a plain-dict record fragment; engineering_approved remains false.

**Tech Stack:** Python dataclasses, CadQuery/OCCT, pytest, existing quick tier.

## Scope and review before implementation

- Architecture PASS: closed-hull intersections use existing CAD dependencies. No other lane modules change.
- Quality WARN: planar double sides do not establish perpendicular shell clearance on curved ends. Label this simplification; no whole-rule compliance claim.
- Coverage WARN: public full-hull capacity validation is blocked by incomplete existing KVLCC2 support and missing reference fill basis. Synthetic analytic checks are not a substitute.
- Performance WARN: sequential OCCT intersections, no parallel CAD. Small deterministic grids only.
- Read briefs, PRD 4.1/5.8, design-loop steps 1–11, hull-variation source and its plan. Relevant lessons: preserve source domains; never infer missing hull; chain push to successful quick tier; do not clean shared build output.

## Frozen gates (commit this section before checks)

G0 baseline: `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` must exit 0 before implementation. Run in background with a lane-local target directory and no code-level timeout.

G1 geometry: synthetic closed non-box wedge, with known analytic volume and centroid: relative volume error <=1e-6 and centre absolute error <=1e-6 m. Include a box only as an analytic control. Sum of ALL compartments (including machinery, peaks, voids and ballast) must equal independent below-deck hull volume within 1%. Capacities must equal 0.98 times geometric volume. No negative or overlapping allocated volumes.

G2 inputs/records/rules: reject non-finite dimensions, mismatched hull bounds, empty/open hulls, bad counts and impossible extents. Every computed quantity uses value/unit/uncertainty/method/method_version/sources/status; unknown uncertainty has a reason. Rule screens include 18,19,23,26,29 and collision bulkhead. Incomplete checks stay review_required, with no true compliance assertion. JSON serialization disallows NaN.

G3 public capacity: absolute relative error <=2% at 98% fill, against a published public tanker capacity with known particulars, with hull basis stated. Public reference located BEFORE computation: Tokachi, ClassNK particulars mirrored at https://www.aukevisser.nl/supertankers/VLCC-T/id122.htm : Lpp 316.6 m, B 60 m, D 28.9 m, DWT 280973 t, cargo 328458 m3. Source does NOT state fill basis. Existing KVLCC2 retained hull length 263.999981 m omits 17.5% of Lpp and 0.5 m bottom; it is not Tokachi. Thus G3 is BLOCKED unless a matched complete public hull and explicit 98% source become available. Do not tune extents to capacity. Do not silently treat published geometric capacity as 98% capacity.

G4 delivery: focused tests and full quick tier exit 0; inspect diff for unrelated changes and white-label leaks; commit and push lane/tank-arrangement only. Do not merge. Inspect then delete only lane-local target as last shell action.

## Round 2: PM change of reference and frozen G3b (2026-11-13)

PM changed the reference **before any capacity was computed**. Original G3 was never run: Tokachi has neither a public matched hull nor an explicit fill basis. Its blocked history above remains unchanged. G3b replaces that reference with CAP01, the published ARGYRO design study (NTUA handle 123456789/58817), not a built ship.

- Freeze G3b in a commit before digitisation or capacity runs. Absolute relative error must remain **<=2%**, at **98% fill**, against **321,202 m3** (PM reference; source table gives 321,202.327 m3 including two slop tanks). Do not tune geometry or boundaries against the result.
- Reconstruct the published vector lines using MarinaFrame readers where suitable. Record station coverage and per-station accuracy against published numeric offsets if any; if none exist, state that independent offset accuracy is unavailable. Check source particulars and the published Cb before capacity computation; report discrepancies, do not adjust to match capacity.
- G3b uses published bulkhead frame positions, 3.5 m double sides and 2.8 m double bottom. Include cargo and slops on the source's basis. Compare the hull-intersected sum, not bounding-box capacities.
- Separately run the existing generator with its own choices for the same particulars. This is descriptive only, with no acceptance gate.
- Licence boundary: source PDF, extracted text, digitised lines, geometry, per-tank tables and all derived data stay in ignored `work/` only. This tracked plan records method, gate outcome and compact aggregate findings only, as requested by PM; never attach source extracts or derived geometry.
- Round-2 delivery is **lane/tank-g3b only**, superseding the old G4 branch name. Run the quick tier, commit, push; no merge. `engineering_approved=false` throughout.

**Round-2 progress, before capacity runs:** G3b frozen in `82289f9`. Twenty AP–FP stations read with the existing vector-reader conversion and single-valued-section checks. PDF path 42 contains two stations joined at the keel; split there. Station 2.5 uses two meeting fragments. The parallel body is explicitly labelled 4.4–7.3. No numeric hull offsets are published: independent per-station accuracy is unavailable, not zero. Per-station source points and diagnostics remain in ignored `work/argyro/results/sections.json`.

The existing `geometry.build_hull` produced one valid closed AP–FP solid. Its default 10 mm requested approximation exceeded the 513-knot limit; existing explicit complexity fitting selected a 19.53125 mm allowance, with maximum measured deviation 19.525 mm and maximum height-weighted RMS 10.859 mm against extracted vectors, not independent source offsets. Breadth/depth/length agree with the source within 0.01 mm. AP–FP Cb is 0.799115 versus published 0.810 (1.344% lower); the bulb beyond FP and aft overhang are excluded. These end omissions do not intersect the published cargo domain. No geometry has been adjusted to capacity.

**Ruling:** Use the published planar bulkhead/side/bottom limits clipped by the reconstructed outer hull, and explicitly report that this is not an exact reconstruction of the source's curved internal structure surfaces or deck camber. A mismatch is a G3b failure, not permission to tune. Source frame and bottom limits differ between the capacity table and later damage-analysis tables; use section 4.4 frame ranges with the section 4.2 frame table for G3b. Do not substitute the later table's different aft centre-tank boundary.

**Ruling:** The current generator does not choose machinery length, peak length, tank counts or slop length: callers must supply all of these. Therefore a fully autonomous 'own choices' run is unavailable. Run an explicitly caller-chosen, ungated baseline (6 rows, 2 columns, machinery 15% L, forepeak 5% L, slops 3% L, fuel reserve 3% L, 2 slop columns), with its existing rule-minimum side/bottom choices. These fractions are fixed here before any capacity computation, not fitted to the reference.

**Round-2 resume point:** run published-boundary intersections and the declared ungated baseline; retain limitations and compare the unchanged 2% band. Evidence: ignored `work/argyro/`; no capacity computation has yet been performed.

## Sources and method limits

MARPOL Annex I text: IMO resolution MEPC.117(52), adopted 15 October 2004, https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.117(52).pdf . Historical version explicitly pinned, not a claim to current consolidated applicability.

- Reg.19.3.1/.2: w=max(1,min(0.5+DWT/20000,2)), h=max(1,min(B/15,2)), for >=5000 DWT. Planar internal sides/bottom are preliminary only; actual perpendicular clearance and bilge treatment require review.
- Reg.18.2: minimum ballast amidship draft 2+0.02L; trim <=0.015L and propeller immersion require loading, lightship and hydrostatics. Report capacity only and unresolved checks, not a fixed ballast percentage.
- Reg.29.2: use conservative 3% slop capacity; do not use reduced allowances without equipment evidence.
- Reg.26.3: conservative wing volume cap 22500 m3 (75% of minimum 30000 outflow limit); centre cap 50000 m3. Conservatively screen length <=max(10,0.1L), rather than implement every bulkhead-dependent exception. Reg.25 hypothetical outflow remains unresolved. IMPORTANT applicability: reg.26.7 excludes tankers delivered on/after 1 January 2010; reg.23.1 applies to those tankers. Show reg.26 only as a historical screening constraint, not a current newbuild requirement.
- Reg.23: report full-release single-tank screening scenario, not probabilistic mean outflow. Mean outflow requires side/bottom damage probabilities, pressure balance, tidal and permeability inputs; leave unknown.
- SOLAS II-1/12.1/.2, MSC.216(82), adopted 8 December 2006: minimum min(0.05L,10 m), maximum max(0.08L,0.05L+3 m), measured aft of FP with bulb correction. Primary text: https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.216(82).pdf . Use caller-stated SOLAS length and forward bulb extension; reference point is min(extension/2,0.015L,3 m) forward of FP. Applicable edition and Administration exceptions still need review.

## Tasks and resume point

1. Commit gates; run baseline quick tier. If failing, stop implementation and report.
2. Write focused tests first in `tests/test_arrangement_generator.py`, demonstrate missing-module failure. Add CAD tests marked cad for exact wedge intersections and closure.
3. Implement typed model, intersection generator and record fragment in own module. Split cargo grid, aft slop row, full double bottom, wings, forepeak and machinery/fuel reserve. State boundary conventions and net-capacity exclusions.
4. Run focused unit/CAD tests and fix only lane-owned files. Review simplicity and unresolved rules. Record actual numbers and failures below.
5. Run quick tier, record result, commit/push own branch. Delete lane target after inspection.

**Resume point:** G0, G1, G2 and local G4 checks passed on e3d1db7. Implementation and 24 focused tests pass. Independent review corrections applied. Push lane/tank-arrangement after the final chained quick check; retain worktree, remove its target only. PM follow-up: obtain a matched complete public hull and explicit 98% capacity; implement clearance, loading and probabilistic outflow before any statutory claim. Public G3 remains blocked, not passed. No public capacity computation performed.

## Results

- G0 baseline quick tier exit 0: Python 2541 passed, 4 skipped, 92 deselected (1228.96 s); Rust/UI successful; bounded scan 1326 files, 0 findings. Log: ignored `work/checks/baseline.log`.
- Test-first missing-module run failed as expected before implementation. First CAD run exposed an OCCT API detail: Solid.Closed() is not the closed-shell test. Fixed by checking each solid shell; no gate change.
- G1/G2 focused run: **21 passed in 4.95 s**, including six real-CAD cases. Wedge 18000 m3, centre (55.5555556,0,6) m; box 24000 m3, centre (50,0,6) m, partition and first-moment tolerances passed. STEP mm input/deck clipping, bad geometry, quantity serialization and failed rule screens tested.
- Review refinement: reg.29.3 requires two slop tanks for >=70000 t. Regression failed before fix, passes after. Reg.29 screen now checks count as well as capacity.
- Independent review found disconnected intersections merged as one tank and bare citation strings accepted. Both regression tests failed before fixes; now reject disconnected cells and require a citation tuple. Review also identified potential first-object STEP truncation: changed import to collect all objects before checking one solid. Multi-solid STEP regression already rejected by the old single-solid guard, so no reproduced loss claim for that fixture. Final focused run: **24 passed in 4.69 s**. Stopped the pre-correction quick run during Python tests; it is not a final pass. Rerun G4 on corrected source before push.
- Post-review G4 quick tier **exit 0 on e3d1db7**: Python **2557 passed, 4 skipped, 100 deselected, 5 warnings** in 602.66 s; Rust **318 passed, 50 ignored, 0 failed**; UI **275 passed, 0 failed**; format/clippy passed; bounded scan **1328 files, 0 findings**. Log: ignored `work/checks/post-review-quick.log`. No code changes after this run. A final chained quick run will gate the branch push; only this results document changes.
- Commits: d12c414 (frozen gates), 6adb3c7 (primary sources/applicability), e3d1db7 (implementation/tests). Delivery branch lane/tank-arrangement; no merge or PR requested.
- No tracked `.codesight` or context map exists; no shared structural metadata changed.
- G3 remains BLOCKED. No matched complete public hull with explicit published 98% capacity. Do not call this a validated MARPOL generator: reg.19 clearance, reg.18 loading and probabilistic reg.23 mean outflow remain unresolved; only a full-release scenario is calculated. Fuel reserve is not a finished fuel tank.
- No other lane code, PRD or ROADMAP modified. Sources are the primary IMO links above and the public particulars mirror. Public source PDFs/text stay in ignored `work/regulations/`.
