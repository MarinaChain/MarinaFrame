# MarinaFrame roadmap (2026-11-12)

Owner: CEO/PM (Claude, for the founder). Read with `docs/PRD.md` (requirements and their IDs) and
`docs/STRATEGY_2026Q4.md`. This roadmap replaces the "next four weeks" priority list of
`docs/plans/2026-11-09-gap-analysis.md`.

Dates are planning targets, not commitments. The basic-design track works back from a shipbuilder
pilot's aim of a physical model test in 2027 (`docs/PRD.md`, section 4.1). It depends on a signed pilot
agreement and on the data the pilot supplies. Every phase ends with a measured check, not a date alone.

## Tracks

| Track | Purpose | Main PRD IDs |
|---|---|---|
| A. Basic-design pilot | Reading, reference search and tanker design from requirements for one product tanker | D1-D14, S1, G1-G5 |
| B. Reading accuracy | Measured, blind accuracy of the readers we have | G7-G10, H4-H6 |
| C. App and platform | A partner can install and use the app safely | A7, A8, P4 |
| D. Structure and repair | The lasting product after the pilot | S2-S4 |

## Phase 0: proposal and first evidence (now to end of November 2026)

| Work | Track | Exit check |
|---|---|---|
| Pilot proposal: scope, phases, schedule, cost and staffing per discipline, in-house versus external deployment, data rights | A | Proposal sent to the pilot's corporate planning |
| Inventory the pilot material per hull, with permitted uses (D3) | A | Inventory table: received versus reported, rights per use |
| Data request to the pilot, model tests paired with hull geometry first (`docs/plans/2026-11-12-design-from-scratch.md`, section 3.1) | A | Count of hulls with paired geometry and model tests |
| Decide fleet database, parametric hull tool and CFD route (PRD open decision 7) | A | Decisions recorded |
| Fix the two causes the synthetic run found: crane abbreviations (G7) and scale crops that miss the printed spacing (G8) | B | Synthetic re-run: cranes found; no ship loses its scale |
| New blind test sets: GA drawings without labels and other ship types; new hull holdouts | B | Sets frozen and sealed before any run |
| Apple Developer ID, then a signed and notarized installer (A7) | C | A partner installs without security warnings |

## Phase 1: read one hull completely (December 2026 to February 2027)

| Work | Track | Exit check |
|---|---|---|
| Read the pilot hull's GA, midship section and lines plan; link them by frames, scale and particulars (D1, D2) | A | Per-field reading report on the pilot's own drawings: correct, unknown, wrong; every value traced to its drawing |
| Tanker midship-section reader (S1) | A | Plates and stiffeners of the pilot midship section, checked by the pilot's structure specialist |
| Reference-ship search and comparison table for one real inquiry (D4) | A | Technical sales confirms the table is useful for that inquiry |
| Design database from the yard archive (D9); requirements to main dimensions (D10); tank arrangement generator (D11); weights and stability (D12) | A | Reconstruction test: from a past ship's requirements, compare our design with the ship that was built (3 ships) |
| Resistance calibrated on the yard's model tests; OpenFOAM validated on benchmark hulls | A | Blind performance test on held-out yard hulls |
| 3D arrangement accuracy against real truth, with capacity plans or tank tables from the pilot (G10) | B | Published error per space kind on at least 5 ships |
| Blind GA run on the new test sets | B | Published blind score |

## Phase 2: candidates and, if data allows, performance (March to May 2027)

| Work | Track | Exit check |
|---|---|---|
| Candidate designs: vary the closest reference hull within the stated constraints, with 3D, hydrostatics and payload (D5); free-form deformation of bow and stern | A | Candidates meet the constraints; designers review them and record decisions (D7) |
| Optimizer for fuel against cargo capacity with surrogates (D14); first strength check (D13) | A | Pareto front; only gains above the measured error are reported |
| Performance estimates, only if hulls with paired model-test or trial data exist (D6) | A | Blind check on held-out hulls with a stated error; otherwise this work is not started |
| Per-customer data separation in the chosen deployment (D8) | A, C | Security review passed |
| Windows app (A8) | C | Installer and sandbox tests pass on Windows |

## Phase 3: design package for the model test (June to September 2027)

| Work | Track | Exit check |
|---|---|---|
| Select the candidate with the designers; prepare the basic-design package for model manufacture | A | The pilot accepts the package for model manufacture |
| Compare our estimates with the model-test results when they come | A | Published comparison, whatever it shows |

The meaning of the 2027 milestone (design submission, start of model manufacture, or start or end of
tank testing) is still open with the pilot. Phase 3 changes when it is fixed.

## After the pilot, or in parallel when there is capacity

- Production staffing and inspection-record pilots: separate scopes, inputs and baselines.
- 3D structure along the ship and OCX export (S2), then gauging, wastage and steel renewal (S3, S4).
- Automatic view detection on lines sheets (H5) and station naming from printed labels (H4).
- Read-twice option for run-to-run variation (G9), a cost decision.
- Windows, Intel Mac and ARM Linux in CI (P4).
- Class-society tool work and its comparison with free tools: on hold by the founder.

## How we change this roadmap

Update it when a phase exit check passes or fails, when the pilot fixes a date or a scope, or when the
founder changes a priority. Record each change below.

## Change log

- 2026-11-12: first version, after the pilot meeting of 2026-11-12.
- 2026-11-12: scope widened to tanker design from requirements; added the data request, tool decisions,
  D9-D14 work and the reconstruction test (plan `docs/plans/2026-11-12-design-from-scratch.md`).
