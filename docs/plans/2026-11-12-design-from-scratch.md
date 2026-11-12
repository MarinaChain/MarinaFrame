# Plan: tanker concept design from requirements (2026-11-12, draft)

Owner: CEO/PM. Status: draft for discussion with the founder and, later, the pilot's naval architects.
Read with `docs/PRD.md` (D1-D8) and `docs/ROADMAP.md` (track A). Partner names, vessel size and
contract figures are in the private pilot note only.

## 1. Goal

From an owner's requirements (cargo, deadweight, service speed, route and port limits), MarinaFrame
proposes a small set of tanker designs. Each design has a 3D hull, a tank arrangement, capacities,
hydrostatics, stability, a power and fuel estimate, and an uncertainty for each number. The designs are
optimized for two objectives: **fuel use** and **cargo tank capacity**. The designers select one, and it
goes to a physical model test.

"From scratch" in practice means: start from the best data of past ships, then vary and optimize. No
yard designs a tanker from a blank page. Every commercial tool and every research method below does
this too. Our difference must be speed, the use of the yard's own archive, and measured accuracy.

## 2. The design loop we must build

Each step has an input, an output, and a check. The loop runs many times inside the optimizer.

| # | Step | Method (first version) | Output | What we have now |
|---|---|---|---|---|
| 1 | Requirements | Structured form: DWT, cargo volume, speed, draft and beam limits, cargo types, class and flag | Requirement record | Nothing |
| 2 | Main dimensions | Regression and nearest-neighbour search on a fleet and archive database; constraint check | L, B, D, T, Cb ranges | Nothing (D4 reference search is planned) |
| 3 | Hull form | Parent hull from the archive; Lackenby transformation; later free-form deformation and a full parametric hull | Fair 3D hull | Lackenby on KVLCC2 (merged, experimental); hull readers |
| 4 | Tank arrangement | Rule-driven generator: double hull widths, cargo and slop tanks, ballast tanks, engine room, fuel tanks (MARPOL Annex I) | Compartments, capacities at 98 % fill | GA reader, arrangement builder |
| 5 | Weights | Lightship from regressions (steel, outfit, machinery), then from the archive | Lightship, DWT, centre of gravity | Nothing |
| 6 | Hydrostatics and stability | Loading conditions, intact stability (IS Code 2008), damage stability (MARPOL Annex I), freeboard (ICLL) | Pass or fail per criterion | Hydrostatics only |
| 7 | Strength (first check) | Section modulus and still-water bending moment against the IACS CSR minimum | Pass or fail, margin | Nothing |
| 8 | Resistance and propulsion | Holtrop-Mennen (now), then wave-resistance panel code, then RANS CFD for finalists; all calibrated on the yard's model tests | Effective and delivered power, with error band | Holtrop + B-series (merged); KVLCC2 blind +19 to +21 % |
| 9 | Engine, propeller, fuel | B-series propeller selection; engine layout from public engine-maker data; fuel per day; EEDI and CII | Fuel per day, EEDI, CII | Fuel from SFC (merged) |
| 10 | Optimization | Multi-objective search (fuel versus capacity) with surrogate models; Pareto front | 5-10 candidate designs | Nothing |
| 11 | Package | 3D model, GA draft, capacity plan, hydrostatic tables, performance report with uncertainty | Design package | 3D builders, report code |

## 3. Data: what we need and where it comes from

### 3.1 From the pilot yard (the most valuable data; ask early)

Priority A means the performance work cannot be checked without it.

| Priority | Data | Use |
|---|---|---|
| A | Model-test reports: resistance, self-propulsion, open-water propeller, for each hull | Calibrate and blind-check steps 8 and 9 |
| A | Lines plans or 3D hull files (offsets, IGES, NAPA) of the same hulls | Pair geometry with the test results |
| A | Sea-trial reports (speed-power at trial draft) | Check model-to-ship correlation |
| B | GA drawings (they offered many) | Arrangement rules and statistics; our GA reader builds a database |
| B | Capacity plans and tank tables | Truth for step 4 and for the GA reader (G10) |
| B | Trim and stability booklets, loading manuals | Truth for steps 5 and 6; loading conditions |
| B | Lightship weight breakdowns | Calibrate step 5 |
| B | Midship sections and scantling calculations | Step 7; structure reader (S1) |
| C | Owner specifications and inquiry records, with the design that was sold | Step 1 and 2; test cases "requirement in, design out" |
| C | Design-review notes from their naval architects | Rules of thumb that are not written anywhere else |

For each hull we record what we received, its permitted uses, and whether geometry and test results
are paired. A hull with geometry and a model test is worth more than ten GA drawings for step 8.

### 3.2 Public and purchasable data

| Data | Source | Use | Cost |
|---|---|---|---|
| Fleet particulars (L, B, T, DWT, speed, power, cargo volume, builder, year) | Clarksons World Fleet Register, S&P Global Sea-web; free partial data in Equasis | Step 2 regressions; reference search | Paid subscription (price to check) |
| Annual design summaries of new ships | RINA "Significant Ships" | Particulars and GA images of recent tankers | Low |
| Benchmark hulls with model tests | KVLCC1/2, KCS, JBC (SIMMAN, Tokyo 2015, Gothenburg workshops) | Validation of steps 3 and 8 | Free; we already have KVLCC2, KCS, JBC |
| Parametric hull datasets | Ship-D (about 30,000 hulls with wave drag, MIT DeCoDE lab); ShipHullGAN data | Surrogate models; generative hull research | Free (licences to check) |
| Resistance and power statistics | Holtrop-Mennen; Kristensen and Lützen (DTU) statistics for tankers and bulk carriers; Guldhammer-Harvald | Step 8 baseline and range checks | Free |
| Rules | MARPOL Annex I and VI, IS Code 2008, ICLL, SOLAS, IACS CSR | Constraints in steps 4, 6, 7, 9 | Free or low |
| Engine data | Engine-maker public layout tools and project guides | Step 9 | Free |

### 3.3 Data we generate ourselves

- **CFD runs** on varied hulls (OpenFOAM), calibrated on the yard's model tests. These train the
  surrogate models for step 10. The cost is compute, not licences.
- **The archive database:** the GA reader and hull readers turn the yard's drawings into structured
  records (particulars, tanks, capacities, frames). This is our main advantage: no tool on the market
  reads a yard's paper archive into a design database.

## 4. Methods, tools and research to learn from

### 4.1 Commercial tools (learn the workflow; do not copy)

| Tool | What it does well | What we learn |
|---|---|---|
| CAESES (Friendship Systems) | Fully parametric hulls, coupled to CFD for optimization | How to describe a hull with few, meaningful parameters; how to couple an optimizer to CFD |
| NAPA | The standard basic-design system in many yards: hull, compartments, hydrostatics, stability, rules | The data model of a ship in basic design; the checks a yard expects; NAPA export formats |
| MAXSURF / Rhino with Orca3D | Hull modelling, hydrostatics, simple resistance | Fairing and hydrostatics conventions |
| SHIPFLOW, STAR-CCM+, Fine/Marine | Ship CFD (potential flow and RANS) | Mesh and set-up practice for full forms; model-to-ship scaling |
| DNV Nauticus Hull, BV MARS/VeriSTAR, LR RulesCalc | Rule checks of structure | Which CSR checks a first design must pass (class tool work stays on hold) |

### 4.2 Open-source tools (candidates to use)

| Tool | Use |
|---|---|
| OpenFOAM (interFoam, with validated KCS and KVLCC2 cases) | RANS resistance and self-propulsion for finalists |
| Michlet or a thin-ship (Michell integral) code | Fast wave-resistance estimate inside the optimizer |
| Capytaine (Python boundary-element method) | Seakeeping and added resistance in waves, later |
| pymoo (NSGA-II, NSGA-III), OpenMDAO, Dakota | Multi-objective optimization and design-loop coupling |
| scikit-learn / GPyTorch (Gaussian processes) | Surrogate models with uncertainty |
| FreeCAD Ship workbench, DELFTship (free edition) | Reference implementations of hydrostatics and hull tools |

### 4.3 Research methods

- **Holistic ship design and parametric preliminary design** (Papanikolaou, "Ship Design:
  Methodologies of Preliminary Design"; Parsons' parametric design notes; Watson's "Practical Ship
  Design"; Schneekluth and Bertram, "Ship Design for Efficiency and Economy"). These give the formulas
  and the order of steps 2, 5 and 6.
- **Hull transformation:** Lackenby (done), free-form deformation, and fully parametric hulls
  (Harries). Free-form deformation is the next step: it changes the bow and stern shapes, which the
  Lackenby method cannot.
- **Simulation-based design optimization:** a fast method screens many designs; a slow, accurate method
  checks few. Surrogates (Gaussian processes) choose where to run the slow method.
- **Machine learning for hulls:** generative models (ShipHullGAN, models trained on Ship-D) and neural
  surrogates for resistance. Use them only where a blind check on the yard's hulls shows they help.
- **Benchmark validation:** the Tokyo 2015 and Gothenburg workshops publish the scatter of CFD codes on
  KVLCC2, KCS and JBC. That scatter tells us what error is realistic.

## 5. How we prove it works

We use the same discipline as the GA exam: frozen code, rules fixed before the run, one blind run.

1. **Reconstruction test:** take a past yard tanker. Give MarinaFrame only its requirement. Compare
   the proposed design with the ship that was built: main dimensions, cargo capacity, lightship, power.
2. **Performance test:** keep some hulls with model tests blind. Predict their resistance and power
   with frozen code; report the error at each speed. Target to agree with the yard; the scatter of the
   CFD workshops is a fair reference.
3. **Designer review:** the yard's naval architects score each candidate (feasible, plausible,
   better than the parent) and record the reasons (D7).
4. **Final test:** the physical model test of the selected design, compared with our prediction,
   published whatever it shows.

## 6. Order of work (first 12 months, draft)

| Months | Work | Exit check |
|---|---|---|
| 0-2 | Data request and inventory with the yard; fleet database; requirement form; design data model | Inventory with paired geometry and test results counted |
| 1-4 | Read the yard archive (GA, lines, capacity plans) into the design database | Per-field accuracy on yard drawings |
| 2-5 | Steps 2, 4, 5, 6: dimensions, tank arrangement generator, weights, stability | Reconstruction test on 3 past ships |
| 3-7 | Step 8 calibrated: Holtrop on the yard's tests, then OpenFOAM on benchmark hulls, then on yard hulls | Blind performance test on held-out yard hulls |
| 5-9 | Step 3 with free-form deformation; step 10 optimizer with surrogates | Pareto front; designers review candidates |
| 8-12 | Step 7 first strength check; design package; candidate for the model test | Yard accepts the package for model manufacture |

Hire or contract one naval architect with CFD experience before month 3. The yard's assigned naval
architects review steps 2, 4 and 6 from the start.

## 7. Risks

- **No paired model-test data:** step 8 stays at the baseline with a 20 % error. Ask for it first.
- **Data rights:** a model trained on one yard's archive must not serve a competitor. Decide the
  separation (D8) before we sell to a second yard.
- **CFD cost and skill:** RANS for full forms needs experience; validate on KVLCC2 before yard hulls.
- **Optimization finds paper gains:** a design that is optimal for an inaccurate method is not optimal.
  Only trust gains larger than the measured error of the method.
- **Scope:** structure, rules and production details are large. The first version stops at a basic
  design package for the model test, not class approval.

## 8. Open decisions

1. Buy a fleet database subscription (Clarksons or S&P) now, or start with Equasis and the yard data.
2. Build our own parametric hull, or license CAESES for the hull and optimization layer.
3. CFD: run OpenFOAM in-house (compute cost, one expert) or contract runs to a model basin or a CFD
   consultancy for the first year.
4. Which loading condition and fuel basis the optimizer uses (open question for the yard).
