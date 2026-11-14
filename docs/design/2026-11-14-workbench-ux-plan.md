# Basic-design workbench: UX audit and plan (2026-11-14, draft)

Owner: UI/UX lead. Status: approved by the founder on 2026-11-14 (section 7 records the decisions).
Phase 0 is in progress.
Read with `docs/PRD.md` (section 4.1, D1-D14), `docs/plans/2026-11-12-design-from-scratch.md`,
`docs/plans/2026-11-13-design-loop-v0.md`, `docs/design-record.md` and
`docs/design/2026-11-08-app-design-plan.md` (the current app design; its rules stay).

Resume point: section 6 (phases). Open questions: section 7.

## 1. Why the UI must change

The pilot shipyard's CAD staff already make 3D views. The value for them is design candidates with
numbers they can trust: each value with its uncertainty, its method and its source, and "unknown" when
we do not know. The current app is a drawing-reading app. The product is becoming a basic-design
workbench: requirements in, candidate designs out, compared and decided by the yard's designers.

## 2. What exists now (audit of `app/ui/`, mock backend)

Screenshots: `docs/design/images/2026-11-14-audit/` (mock data only; no partner material).

| Area | State | Screenshot |
|---|---|---|
| Home: "Needs you" cards, vessel grid, drop target, queue count | Built, polished | `home.jpg`, `home-dark.jpg` |
| Run: drawing with evidence overlay, 3D hull, review bar (Accept / Other line / Mark), ink distance per section | Built, strong | `run-draft.jpg` |
| GA reading: particulars, counts and spaces with Read / Not read per value | Built, inside the 3D pane of a run | `ga-run.jpg` |
| Parts: tree, profile and plan sketches, values with source and basis, tank capacity plan rows | Built | `parts-tank-tables.jpg` |
| Export: draft stamp, open issues, accuracy band, STEP / IGES / 3dm / STL / offsets / hydrostatics / report / package | Built | `export.jpg` |
| History, Queue, Batch, Settings (key usage), palette (Cmd/Ctrl+K), shortcuts, light and dark, a11y tests on 23 mock screens | Built | — |
| Design record (schema 1.1, Rust structs in `app/core/src/design_record.rs`) | Backend only: no Tauri command, no screen | — |
| Design loop (`src/vessel_reconstruction/design_loop/`, CLI `scripts/design_loop.py`) | Backend only: no screen | — |

Strengths to keep: provenance on every value; "Draft" everywhere and no "approved" status; review by
keyboard (A, M, N); evidence on the drawing; honest accuracy bands on export; accessible light and
dark themes; the MarinaChain palette and type (section 9 of the 2026-11-08 plan).

## 3. Gaps

| # | Gap | Effect | Fix in phase |
|---|---|---|---|
| 1 | The top object is a vessel read from drawings. There is no design project (requirement, candidates, decisions) | No place for the new product | 1 |
| 2 | No requirements form, reference search, candidate list, comparison, Pareto chart, decision record or design package (D4, D7, D10-D14) | The pilot workflow cannot be shown | 1-3 |
| 3 | The design record and loop have no app command; the UI cannot open a record | Backend results are invisible | 1 |
| 4 | Values show source and basis, but not an uncertainty band, a method version or a status in one consistent form; design-loop quantities carry all three | Designers cannot judge trust per number | 0 |
| 5 | The GA reading sits inside the 3D pane of a hull run. The run header shows hull messages on a GA run ("Lines plan: lines too faint", "This run found no sections") | Confusing; the GA reader looks like a side feature | 0 |
| 6 | The GA panel text says "not approved". The product rule is that "approved" is never a status word | Wording rule broken | 0 |
| 7 | No dense table for long lists (a tanker has 15-30 tanks; the public fleet table has 708 rows): no sort, filter, column units or copy | Tables do not scale to tankers | 0 |
| 8 | English only. The pilot's designers work in Korean | Lower adoption in the pilot | 0 (scaffold), 2 (full) |
| 9 | The queue is built for reading runs of minutes. CFD runs take hours to days on a compute host | No view of long jobs | 4 |
| 10 | Sign-off is per vessel. The pilot needs a decision per candidate, with reason and reviewer discipline (basic design, structure, machinery, outfitting, accommodation) | D7 not met | 2 |

## 4. Information architecture (proposed)

Left rail: **Home**, **Designs** (new), **Archive** (today's vessels: drawings read into records),
**Jobs** (today's Queue, extended for long compute), **Settings**.

The Archive is the reference library: every vessel read from drawings is a candidate parent and a
row in reference search. Designs use it; they do not duplicate it.

### 4.1 Design project (new top object)

Breadcrumb: Designs › project › candidate. Project tabs:

| Tab | Content | PRD |
|---|---|---|
| Requirements | Form: cargo volume, DWT, service speed, draft and beam limits, cargo types, range, class and flag notes. Each field has a unit, a source (owner spec, sales estimate) and "unknown" | D10 |
| References | Closest ships from the Archive and the fleet table; one comparison table with the material differences; pick a parent | D4, D9 |
| Candidates | List of candidate designs with main particulars, capacity, fuel, constraint status; filter and sort | D5, D11-D13 |
| Compare | Parent and 2-4 candidates side by side; deltas; Pareto chart of fuel against cargo capacity | D14 |
| Decisions | Accept / defer / reject per candidate, with reason and reviewer discipline; full log | D7 |
| Package | Design package export for the model test: 3D, GA draft, capacity plan, hydrostatic tables, performance report with uncertainty; draft stamp | Phase 3 of roadmap |

### 4.2 Candidate detail

Tabs: **Overview** (particulars with uncertainty), **Hull** (3D, lines, sectional-area curve, change
from parent), **Arrangement** (tank plan and capacity table), **Weights and stability** (lightship,
loading conditions, criteria pass or fail), **Performance** (speed-power curve with its band and
method tier: empirical, thin-ship, CFD), **Checks** (every constraint with pass, fail or unknown),
**Provenance** (the step graph: method versions, inputs, cache hits, what changed since last run).

### 4.3 One value display for the whole app

Every number shows, in this order: value, unit, uncertainty (± or band), method chip (for example
"empirical", "CFD", "read from GA"), status chip (Draft, Needs review, Unknown). Hover or focus opens
the source: the drawing region, the method document, or the step in the graph. "Unknown" is a value
state, not a blank. This replaces the per-screen variants in Parts, GA and Export.

### 4.4 Pareto chart rules

- Axes: fuel per day at service speed, and cargo volume at 98 % fill.
- Each candidate has error bars from its uncertainty.
- Candidates that fail a constraint are hatched, not hidden.
- Dominated candidates are grey.
- When two candidates differ by less than the measured error, the chart marks them as not
  distinguishable (PRD D14).
- The parent ship is a fixed reference point.

### 4.5 Lite and Advanced modes (decided 2026-11-14)

Two views of the same design project. The mode changes how much the user controls, not the data.
The user selects the mode in Settings and with a switch in the project header. The app remembers it
per user. Switching keeps the current project and candidate.

| | Lite: "brief and review" | Advanced: "workbench" |
|---|---|---|
| Who | A user who wants the agent to do the design loop: a project lead, a new designer, technical sales later | A basic-design naval architect who wants control of each step |
| Input | A short brief: requirements, limits, and one objective slider (fuel against cargo capacity) | The full Requirements form; design variables with ranges; locked values; the method tier for each step |
| Agent | Runs the full design loop by itself. Returns 3 recommended candidates and explains each trade-off in plain words | Runs only the steps the user starts. The user can run one step again, change one variable, or ask the agent for a proposal |
| Display | Main particulars, capacity, fuel and their bands; a confidence label; one Pareto chart with the 3 candidates marked | Every value display (4.3), dense tables, the step graph, all candidates, the full Pareto chart |
| Decisions | The user accepts, defers or rejects a candidate, with a reason (D7) | The same, per discipline, plus locks and notes per value |

Rules for both modes:

- Lite hides detail, never risk. A failed constraint, an "unknown" value and the draft status show in
  Lite too. Every Lite number opens its full value display on request.
- The agent proposes; a person decides. No mode marks a candidate as accepted without a person.
- One data model. A Lite project opens in Advanced with all steps, and Advanced locks show in Lite as
  fixed items with their reason.
- Advanced stays clean: progressive disclosure (summary first, detail on request), a column chooser
  with a short default set, at most two panes beside the main view, and the command palette for rare
  actions instead of more buttons.
- Default mode: Advanced for the pilot's basic-design users; Lite for other users.

Lite is also the later path for technical sales (section 7, question 3): a quick estimate is a Lite
brief with references in place of a full loop.

## 5. Constraints that stay

- Draft only; never "approved" or "verified" as a status; engineering approval is outside the app.
- No vendor or third-party product names in the UI, code or docs (identity check before each push).
- No partner names, vessel sizes or partner drawings in committed screenshots or mocks; mock data
  uses public ships (KVLCC2, KCS, JBC) and synthetic values.
- Static UI in `app/ui/` (no framework); accessible in light and dark; keyboard first.
- Desktop and narrow widths; platform-agnostic (macOS, Windows, Linux).

## 6. Phases

Each phase ends with screenshots, a passing `npm run test:ui` and `npm run test:a11y`, and the
quick test tier. New screens are added to the a11y screen list.

| Phase | Work | Needs from the design-loop owner | Done when |
|---|---|---|---|
| 0. Foundations | Value display component (4.3); dense table component (sort, filter, units, copy); GA reading as its own run view with GA-specific header; fix "not approved" wording; i18n scaffold (string table, English and Korean, English fallback, ship-term glossary); mode setting (Lite / Advanced) stored per user | None | Parts, GA and Export use the one value display; a 30-tank table is usable; wording fixed; the language and mode switches work; a11y passes |
| 1. Design shell (Advanced) | Designs in the rail; project page with a short Requirements form and Candidate detail first (Overview, Arrangement, Weights and stability, Performance, Provenance) reading a design record file; mock record from the public KVLCC2 loop output | A Tauri command to open and validate a design record (Rust structs exist) | A designer opens a record and sees every value with uncertainty and method |
| 2. Candidates, decisions and Lite | Candidates list; Compare with deltas; Pareto chart (4.4); Decisions log by discipline; Lite brief and review (4.5); full Korean strings for the design screens | A command that lists candidates of a project and their records; a command that runs the full loop from a brief and returns ranked candidates with reasons | 5 mock candidates compare, chart and get decisions; a Lite brief returns 3 candidates; Korean UI complete for these screens |
| 3. References | References tab: search the Archive and fleet table, comparison table, pick a parent; Archive view of vessels as references | Reference search API (D4, D9) | One requirement returns ranked references with the differences shown |
| 4. Jobs and package | Jobs view for long compute (CFD on a compute host: state, progress, ETA, pause reason); Package export for the model test | Job status API from the solver worker; package writer | A CFD job shows progress and pauses; the package exports with the draft stamp |

Phases 0 and 1 can start now. Phases 2-4 follow the backend in the order above.

## 7. Founder decisions (2026-11-14)

1. Language: full i18n with English and Korean, and a switch. Standard abbreviations (LBP, DWT, Cb, GM,
   MCR, EEDI) stay in English in both. One ship-term glossary, reviewed by a yard designer, controls
   the Korean terms. The export language is a separate setting from the UI language. Korean status
   words follow the draft rule (no word for "approved" or "verified").
2. First users: basic design. Candidates, Compare, Pareto and Decisions come first. Technical sales
   follows as a Lite quick estimate after reference search exists.
3. Modes: Lite and Advanced (section 4.5).

Still open:

4. One app with Archive and Designs, or a separate design mode for the pilot users? (Default: one app.)
5. Do reviewers from each discipline sign decisions in the app, or does the app only record the
   decisions made in yard meetings? (Default: record only.)
