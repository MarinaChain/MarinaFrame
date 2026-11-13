# MarinaFrame: product requirements (PRD)

Owner: CEO/PM (Claude, for the founder). Written 2026-11-12. Status: working document.
This is the one place for what MarinaFrame must do, for whom, and how we measure it. Details live in:

| Topic | Document |
|---|---|
| Positioning and users | `docs/POSITIONING.md` |
| Strategy to Q1 2027 | `docs/STRATEGY_2026Q4.md` |
| Vision and gaps | `docs/plans/2026-11-09-gap-analysis.md` |
| Desktop app contract (screens, commands, exports) | `docs/APP_SPEC.md` |
| GA reader for commercial ships | `docs/plans/2026-11-12-ga-commercial.md` |
| Published accuracy | `docs/results/`, `docs/holdouts/REGISTRY.md` |
| Roadmap (phases and dates) | `docs/ROADMAP.md` |

Status words in this document: **Done** (in `continue/v0.5` and tested), **In progress** (a lane or
branch exists), **Planned** (agreed, not started), **On hold** (the founder paused it).

Every output of MarinaFrame is a draft. `engineering_approved` is always false. No output is
"approved" or "verified".

## 1. Problem

A ship in service often needs a 3D model: for repairs and steel renewal, conversions and retrofits,
stability after changes, performance studies, surveys and damage response. Most owners have only 2D
drawings (paper scans, PDFs, old CAD). A naval architect rebuilds the model by hand, which takes weeks.
Ships live 25-30 years or more, so drawing-only ships stay the majority of the fleet for many years.

## 2. Users (in order)

1. Conversion and repair designers, and repair yards. They work against a dock date.
2. Fleet technical managers: dry-dock planning, retrofits, steel renewal.
3. Shipbuilder basic-design and technical-sales teams: for a new order, find the closest reference
   ships in their own archive, compare them, and get candidate designs to check (pilot direction from
   2026-11-12; see section 4.1).
4. Shipbuilders and owners who hold large GA archives and want a quick 3D arrangement.
5. Later: class societies and surveyors (3D hull condition records).

## 3. Product promise

One line: MarinaFrame turns the drawings an owner already has into a 3D ship model in days, ready for
the job that needs it.

1. **Speed:** a usable draft model in days, not weeks.
2. **Honesty:** every value shows where it came from: read from the drawing, measured from the
   drawing's scale, printed on the drawing, or a labelled guess. The engineer checks only the guesses.
3. **Measured accuracy:** we publish error figures from blind tests with frozen code and fixed rules.
4. **Local and private:** a desktop app. The customer's drawings stay on their machine; only model
   calls leave it.
5. **Ready for the next tool:** STEP, offsets, hydrostatics and a review report that open in the
   tools engineers already use.

We do not say: "AI ship designer", "replaces naval architects", "approved", "verified", or "any
drawing, perfect result". For basic design we say: MarinaFrame finds and compares reference ships and
proposes candidates for the designers to check; model tests and sea trials decide.

## 4. What the product does

```
drawing set (scans, PDFs, CAD exports)
  -> intake: sort sheets, read particulars and scale
  -> readers: lines plan (hull), GA (arrangement, decks, superstructure), structure sections
  -> 3D draft: hull, whole-vessel parts, compartments, with a source label on every value
  -> checks: consistency gates, hydrostatics, review items for the engineer
  -> exports: STEP, offsets, hydrostatics, GA arrangement, review report
```

The model (Claude Sonnet 5.5 by default) reads drawings. Code measures, checks and builds. Every model
call has a receipt (request, reply, tokens, cost). Code written by a model runs only in a sandbox.

### 4.1 Pilot direction: basic-design support (from 2026-11-12)

A shipbuilder pilot asked for AI-assisted basic design: from an owner's requirements (cargo, payload,
service speed), find the closest reference ships, compare them, and propose candidate hull forms and
basic drawings with estimated cargo capacity and fuel use. The pilot starts with one product-tanker
design and aims at a physical model test in 2027. The shipbuilder's CAD staff already make 3D views,
so 3D alone is not the value for this user.

MarinaFrame is the reading layer of that work. It reads one hull's GA, midship section and lines
plan, links them, traces every value to its place on the drawing, and returns "unknown" when a value
cannot be read. The design layers on top of it (reference search, candidate generation, performance
estimates) are new requirements in section 5.8.

Technical limit: a GA alone cannot give the underwater hull or the fuel use. Performance estimates
need hull geometry, draft, speed, loading and engine and propeller data, paired with model-test or
sea-trial results for the same hulls. Without that data, the first deliverable is reference-ship
search and drawing comparison only.

Scope widened on 2026-11-12 (evening): the pilot wants tanker design from requirements. The system
proposes a starting 3D design, with tank arrangement, capacities, stability and a fuel estimate,
optimized for fuel use and cargo tank capacity, for the designers to select and send to a model test.
The yard will supply many GA drawings and, later, naval architects to co-develop. The product is to be
sold to other shipbuilders after the pilot, so per-customer separation (D8) is a contract item. The
plan is `docs/plans/2026-11-12-design-from-scratch.md`; the new design-loop requirements are D9-D14.

## 5. Requirements

### 5.1 Hull from lines plans

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| H1 | Read the body plan of a lines drawing into half-breadths at the drawn waterlines | Done | `docs/BODY_PLAN_CHINE.md` |
| H2 | Read hard-chine body plans (polyline reader, engages on chines) | Done (opt-in reader; the current reader stays default) | lane N merge; `docs/plans/2026-11-11-reader-selection.md` |
| H3 | Build a fair hull surface and a valid solid from the sections | Done | `docs/HULL_FAIRING.md` |
| H4 | Name stations so that one missed station does not shift the others | Not met; parked | `docs/plans/2026-11-12-polyline-naming.md` on branch `lane/polyline-naming` (rejected by its fixed rule) |
| H5 | Find the profile and plan views on a lines sheet automatically | Not met | `docs/plans/2026-11-12-view-detection.md` on branch `lane/view-detection` (found on 1 of 9 sheets) |
| H6 | Publish blind accuracy on real ships | Done for two boats (1 pass, 1 fail) | `docs/results/2026-11-11-published-holdouts.md` |

### 5.2 Whole vessel from a GA (small vessels)

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V1 | Build decks, deckhouse, superstructure and appendages from a GA | Done (development, one research vessel) | `docs/WHOLE_VESSEL_GUNNERUS.md` |
| V2 | Show each part's source region on the drawing (hover to source) | Done | provenance view in the app |
| V3 | Revise one part from a mark without a full rebuild | Done | `docs/APP_SPEC.md`, "Re-run one part from a mark" |

### 5.3 GA reader for commercial ships

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| G1 | Read the main dimensions (LOA, LBP, breadth, depth) from the particulars | Done | blind exam: see section 7 |
| G2 | Count cargo holds, hatches and cranes on bulk carriers, or abstain with a reason | Done | blind exam: see section 7 |
| G3 | Measure the frame scale, dimensions and each space's box from the GA, with a status per axis | Done (development) | `docs/plans/2026-11-12-ga-commercial.md` |
| G4 | Use printed values (hatch sizes, dimension-chain spans) instead of measured boxes where printed | Done | same plan, status section |
| G5 | Build an estimated 3D arrangement from the reading | Done (demo ships on the web demo) | `docs/GA_ARRANGEMENT_INPUT.md` |
| G6 | Outlines for sloped and tapered spaces | Done (optional; builder support planned) | same plan |
| G7 | Read cranes and other abbreviated labels as spaces (for example "CR.1") | Planned | synthetic run, cause 2 |
| G8 | Keep the frame scale when the printed spacing is outside the model's crop | Planned | synthetic run, cause 1 |
| G9 | Reduce run-to-run variation (for example read twice and keep what agrees) | Planned (cost decision) | plan, status section |
| G10 | Measure 3D arrangement accuracy against real truth (capacity plans, tank tables) | Blocked: needs truth data from a pilot partner | section 9 |

### 5.4 Structure and rules

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| S1 | Read a 2D midship section | Done (development); priority raised by the pilot (tanker midship sections) | `docs/CONTINUATION_STATUS.md` |
| S2 | Plates and stiffeners along the ship, with OCX export | Planned | gap analysis, step 2 |
| S3 | Rule checks with cited rules, tied to geometry | Partly (a rule subset outside the app); class-tool work on hold | strategy section 2 |
| S4 | Gauging on plate IDs, wastage against class rules, steel-renewal list | Planned (needs partner gauging data) | positioning, "lasting product" |

### 5.5 Desktop app

The full contract is `docs/APP_SPEC.md`. Main requirements:

| ID | Requirement | Status |
|---|---|---|
| A1 | Drop a drawing set; the run starts without a spec file | Done |
| A2 | Watch the run live: drawing, chosen lines, 3D model, model questions and answers | Done |
| A3 | Review: needs-review items, part cards with source and status, see-through 3D view | Done |
| A4 | Replace a sheet and resume; re-export a finished run without rebuilding | Done |
| A5 | Exports: STEP, offsets, hydrostatics, review report | Done |
| A6 | Mac app (Apple silicon) | Done, unsigned |
| A7 | Signed and notarized installer with updates | Planned (needs the founder's Apple Developer ID) |
| A8 | Windows app | Planned (sandbox design done) |

### 5.6 Web demo

| ID | Requirement | Status |
|---|---|---|
| W1 | A read-only web demo of finished runs, with no login | Done: frame.marinachain.io |
| W2 | Show only runs whose drawings may be shown (licence key per run) | Done (`docs/WEB_DEMO.md`) |
| W3 | A web review portal for a pilot partner | Planned, only when a partner asks |

### 5.7 Platform, security and cost

| ID | Requirement | Status |
|---|---|---|
| P1 | Model-written code runs only in a sandbox; no unsandboxed fallback | Done: macOS Seatbelt; Linux Landlock with a default-deny seccomp allow-list (independently reviewed) |
| P2 | Keys never in git or logs; drawings never in git | Done (secret scan in CI) |
| P3 | CI on the macOS desktop app and the Ubuntu x86 web host, with per-job path filters | Done |
| P4 | Windows, Intel Mac and ARM Linux in CI | Deferred |
| P5 | Cost per ship is known before a run (request caps per ship) | Done for the GA reader (6 requests per ship; about USD 0.26 per ship at list price in the exam) |
| P6 | One shared build cache for all worktrees | Done |

### 5.8 Basic-design support (pilot direction)

| ID | Requirement | Status |
|---|---|---|
| D1 | Link one hull's GA, midship section and lines plan: shared frames, scale and particulars; flag contradictions between drawings | Planned (first pilot step) |
| D2 | Read the lines plan and midship section of a large commercial ship (tanker), with "unknown" where unreadable | Planned (readers exist for small boats, standard hull forms and development midship sections) |
| D3 | Inventory a design archive per hull: drawings, revisions, particulars, linked test and trial results, and permitted uses | Planned |
| D4 | Reference-ship search: for a set of requirements, find the closest past hulls and show the material differences in one table (payload, deadweight, speed, fuel, main dimensions) | In progress: search and difference tables built on public fleet data (2026-11-13) |
| D5 | Candidate designs: vary the closest reference hull within stated constraints, with 3D, hydrostatics and payload for each candidate | In progress: variation module done (targets met); the public tanker hull is read only in part (ends missing) |
| D6 | Performance estimates (resistance, propulsion, fuel), checked blind against held-out hulls with model-test or trial results | In progress: empirical baseline built; blind tanker error +19 to +21 %, too high for quotes; needs tanker calibration or CFD |
| D7 | Record why the designer accepted or deferred each candidate | Planned |
| D8 | Keep each customer's drawings, derived data and results separate and unavailable to any other customer | Planned (contract and deployment design); required before a second yard |
| D9 | Design database: read a yard archive (GA, lines plans, capacity plans, stability booklets) into structured per-hull records | Planned (GA and hull readers exist) |
| D10 | Requirements to main dimensions: from DWT, cargo volume, speed and port limits, propose L, B, D, T and Cb ranges from fleet and archive statistics | In progress: held-out checks pass on public data (VLCC 2/2 ships, mid-size 4/4 designs); ranges still broad |
| D11 | Tank arrangement generator: double hull, cargo, slop, ballast, engine room and fuel tanks to MARPOL Annex I, with capacities at 98 % fill | In progress: generator built; frozen capacity check on a published design failed (+4.6 %), development rerun +2.6 % after shaped internal surfaces; automatic layout choices not yet design logic |
| D12 | Weights, loading conditions, intact and damage stability and freeboard for each candidate | In progress: preliminary lightship, engine screening, EEDI/EEXI/CII built; accuracy check blocked on public input data; stability not started |
| D13 | First strength check: midship section modulus and still-water bending moment against the IACS CSR minimum | Planned |
| D14 | Multi-objective optimization of fuel use against cargo capacity, with surrogate models and a Pareto front; gains smaller than the method's measured error are not reported as gains | In progress: versioned design record and a cached end-to-end design loop (requirements to EEDI/CII) built; thin-ship wave resistance validated against theory; optimizer not started |

## 6. Non-goals

- No engineering approval or sign-off inside the product. Class and engineers approve.
- Not a CAD editor. We feed the tools engineers already use. For basic design we propose candidates;
  we do not produce a final design.
- No performance claim without evidence. Resistance and fuel estimates are shown only with their
  validation against model tests or sea trials; no estimate replaces a model test.
- No hosted processing of customer drawings by default. Data stays on the customer's machine.
- No guessing without a label. A value with no basis is shown as a guess or left empty with a reason.

## 7. Success measures (current values)

All figures are from fixed protocols. "Blind" means one run with frozen code on data the developers
did not see.

| Measure | Current value | Source |
|---|---|---|
| GA exam, blind (9 ships, 42 items) | 35 / 42 correct, **0 wrong**, 7 abstained | `docs/plans/2026-11-12-ga-commercial.md` |
| GA exam, after fixing two post-reply checks (same stored replies, no new model calls, not blind) | 42 / 42 | same |
| Hull reader, published real boats | Davis Boat PASS (37 / 44 cells), Cama Beach FAIL | `docs/results/2026-11-11-published-holdouts.md` |
| GA measuring pass, synthetic ships (6 ships, 178 spaces) | 67 % of spaces found, 15 invented; found boxes mostly within a few cm; cranes 0 / 12 | `docs/plans/2026-11-12-ga-synthetic-run.md` on branch `lane/ga-synthetic-run` |
| GA measuring pass against printed values (development ships) | frame spacing median 0.002 m; hatch breadth median 3.0 m off (printed sizes now replace it) | GA plan, status section |
| Blind hull holdouts left | **0**: all 10 real sheets are spent | `docs/holdouts/REGISTRY.md` |
| Resistance estimate (Holtrop-Mennen), development ships KCS and JBC, model scale | 3-8 % error | `docs/plans/2026-11-12-performance-baseline-results.md` |
| Resistance estimate, **blind** tanker KVLCC2, model scale | **+19 to +21 %** (over-predicts at every speed) | same |
| Main dimensions from requirements, held-out public tankers (frozen ranges) | VLCC 2 / 2 ships (8 / 8 checks); mid-size 4 / 4 designs (16 / 16 checks), mean errors Lpp 0.8 %, B 4.5 %, T 3.5 %, Cb 1.5 % | `docs/plans/2026-11-13-concept-dimensions.md`, `docs/plans/2026-11-13-concept-mid.md` |
| Cargo capacity at 98 %, published design (frozen 2 % gate) | **+4.6 %, failed**; development rerun +2.6 % | `docs/plans/2026-11-13-tank-arrangement.md` |
| Thin-ship wave resistance against published Michell results (Wigley hull, 91 points) | max 1.5 % error; under 6 ms per call | `docs/plans/2026-11-13-thin-ship.md` |

Targets for the next quarter:
1. A blind GA result on new ships, including GA drawings without labels and other ship types.
2. A real-truth accuracy figure for the 3D arrangement (needs capacity plans or tank tables).
3. New blind hull holdouts, then one published result per quarter.
4. Basic-design pilot: reading accuracy on the pilot's own drawings of one hull (D1, D2), reported per
   field with "unknown" counts, before any design or performance work.

## 8. Pilots and go-to-market

- **Shipbuilder pilot:** a commercial GA test pack of 23 ships (14 development, 9 holdout), cleared
  for development and for the web demo by case ID only. The first demo was held on 2026-11-12 with the
  web demo and a desktop kit. At that meeting the shipbuilder chose basic-design support as the first
  area (section 4.1), starting with one product tanker, aiming at a physical model test in 2027, and
  asked for a proposal: scope, phased deliverables, schedule, cost and staffing per discipline, an
  in-house versus external deployment comparison, and data rights. Production staffing and inspection
  records are later, separate pilots.
- **Design partner:** one owner or yard with a real fleet drawing set and gauging records. Founder
  outreach through MarinaChain's shipping relationships.
- **Pilot package:** the app, a review session and a measured report.
- Sales are event-driven: repair yards, conversion designers and fleet managers before dry-docking.

## 9. Open decisions and dependencies (founder)

1. Truth data from the pilot partner: capacity plans or tank tables for about 5 ships (unblocks G10).
2. New blind test sets: GA drawings without labels and other ship types; new hull holdouts.
3. Apple Developer ID for signing and notarization (A7).
4. Class-society tool work and its comparison with free tools: on hold.
5. Model capacity for batch pilots.
6. Basic-design pilot proposal: scope, price, staffing, deployment (in-house or external) and data
   rights; the governing loading condition, speed and fuel basis; whether drawings can be paired with
   model-test and trial results; who approves candidates; and what the 2027 test milestone means.
7. Design-from-requirements tools: decided 2026-11-12. No paid fleet database (build with public data
   now; the yard supplies bulk data later); our own parametric hull; CFD in-house as an OpenFOAM worker
   that MarinaFrame controls (`docs/plans/2026-11-12-design-from-scratch.md`, section 8).

## 10. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| No truth data for 3D arrangements | We cannot state 3D accuracy on real ships | Ask pilot partners for capacity plans; synthetic truth as an upper bound |
| Run-to-run variation of the model | The same ship gives different results | Gates, abstention, and the read-twice option (G9) |
| Over-fitting rules to a few development ships | Good development numbers, weaker real results | Blind tests with frozen code; no rule change after a result |
| Unsigned installer | Partners cannot install easily | Developer ID (A7) |
| Drawing rights | A drawing shown without permission | Licence key per run; drawings never in git |
| No paired performance data for the pilot | Design candidates without fuel or resistance estimates | Start with reference search and drawing comparison (D4); scope D6 only once paired data is verified |
| Expectation that AI replaces model tests | A promise we cannot keep | State in the proposal that model tests and trials decide (section 6) |
| Customer data reaching a competitor | Loss of the pilot and of trust | Per-customer separation (D8); rights written into the contract |
| Optimizer gains that exist only in an inaccurate method | A candidate that is not better in the model test | Calibrate on the yard's model tests; report only gains above the measured error (D14) |

## Change log

- 2026-11-12: first version, from the four documents above and the results of 2026-11-11 and
  2026-11-12.
- 2026-11-12: added the basic-design pilot direction (section 4.1, requirements D1-D8, non-goals,
  targets, open decisions, risks) after the pilot meeting of 2026-11-12, and a link to `docs/ROADMAP.md`.
- 2026-11-12: D5 and D6 progress; resistance results on development ships and the blind tanker.
- 2026-11-12: scope widened to tanker design from requirements (section 4.1); new requirements D9-D14;
  open decision 7; optimizer risk. Plan: `docs/plans/2026-11-12-design-from-scratch.md`.
