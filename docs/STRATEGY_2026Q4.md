# MarinaFrame strategy, Q4 2026 to Q1 2027

Owner: CEO/PM (Claude, for the founder). Written 2026-11-07. Resume point for all workstreams.
Read with `docs/CONTINUATION_STATUS.md` (engineering state) and `docs/APP_SPEC.md` (app).

## 1. Where we stand against Forge Shipyard

Forge (forgeshipyard.com) sells a "2D-to-3D model reconciliation layer for ship repair and
maintenance": whole-vessel reconstruction plus compliance rules, a signed decision ledger,
reconciliation over time and drydock work packages, delivered as hosted web with on-premise
options and 90-day governed pilots. One vessel demonstrated (Balclutha), geometry described by
themselves as a "visual envelope", no published accuracy numbers.

| Edge | Forge | MarinaFrame today |
|---|---|---|
| Scope | Whole vessel: hull, decks, structure, openings, outfitting, rigging; piping and machinery in progress | Hull envelope only |
| Compliance | USCG 46 CFR, Plan Review Guides, NVICs as a cited evidence graph | None |
| Workflow | Propose → approve → sign; append-only decision ledger; work-package readiness | Event ledger and operator interventions; no sign-off product |
| Reconciliation | Survey, thickness and repair data update the model through a review gate | None |
| Delivery and customers | Web + on-premise, pilots with design partners, a shipyard owner giving feedback | Desktop app in build; no design partner |
| Measured geometry | Not published | Numeric gates (trace 1.1 mm, STEP reimport audit), validation contract in Rust, abstention |
| Table reading | Local OCR for documents | DeepSeek vision for offset tables with deterministic parsing |
| Proof on a real ship | Visual only | Not yet |

**Our edge:** verifiable geometry. Every number traces to pixels, every build is re-audited from
the exported STEP, and the system declines instead of guessing. **Their edge:** breadth and
workflow that a repair department pays for, plus customers.

## 2. Strategy

1. **Prove the edge in public numbers first.** A real ship with drawings and true CAD
   (Gunnerus), run with frozen code, gives the first authentic accuracy figures in this market.
   Forge has none. This is the single highest-value result.
2. **Close breadth where we can measure it.** Go inward to structure with ground truth
   (MiDShip has drawings, annotations and 3D for 12,753 cargo-hold designs) instead of visual
   reconstruction. "Structure with an error figure" beats "structure that looks right".
3. **Close compliance with structured, cited rules tied to geometry.** Use public rules
   (IACS CSR, class rules, 46 CFR, SOLAS). MiDShip ships ABS rule evaluations per design, so our
   rule checks get a ground truth that Forge's corpus lacks.
4. **Close workflow inside the app,** reusing the Rust ledger: review gate, sign-off records,
   review packets, gauging overlays. Little new data needed; mostly product work.
5. **Get one design partner with a real fleet drawing set** through MarinaChain's existing
   shipping relationships. This is the only route to real survey, gauging and repair records.
6. **Desktop-first, local data** is a sales point for confidential and defence-adjacent owners.
   A narrow web review portal comes after the first partner asks for it.

## 3. Data to procure

Status codes: HAVE (on disk, verified), OPEN (public, free, to download), PARTNER (needs a
relationship), PAID (needs budget approval), BUILD (we generate it).

| Need | Source | Status | Closes / deepens | Size |
|---|---|---|---|---|
| Real ship, drawings + true CAD | R/V Gunnerus (lines plan DXF/PDF, GA, STEP, 3DM) | HAVE | Proof of edge | 2.6 GB |
| Benchmark hulls with offsets | SIMMAN KCS, KVLCC1/2, DTMB 5415 | HAVE | Accuracy, hydrostatics | 3 MB |
| More benchmark hulls with lines/offsets | Duisburg Test Case (DTC), Japan Bulk Carrier (JBC), ONR Tumblehome, Series 60 offset tables, Wigley (analytic) | OPEN | Development set separate from Gunnerus | < 100 MB |
| Many hull variants | Ship-D (30,000 parametric hulls; meshes regenerate locally) | HAVE (tables) / BUILD (drawings) | Accuracy at scale | 0.3 GB + renders |
| Open hull design libraries | DELFTship / FREE!ship sample hulls (licence check per file) | OPEN | Realistic lines plans | small |
| Structure with ground truth | MiDShip: 36-design sample now; next 2,000 designs without 3D (~3 GB) + all 496 SGLD with 3D (~9 GB) | HAVE (sample) / OPEN | Structure breadth with numbers | 12 GB next tranche |
| Structural exchange format | OCX (Open Class 3D Exchange) schema and sample models | OPEN | Interop with class and CAD tools | small |
| Rules, cited | IACS Common Structural Rules, DNV/ABS/LR public rules, 46 CFR, IMO SOLAS chapters available publicly | OPEN | Compliance breadth | < 1 GB |
| Messy real drawings | HAER (Balclutha, Wapama, C.A. Thayer, others), ALMA | HAVE | Line identity, abstention | 0.8 GB |
| Expert labels on authentic sheets | Freelance naval architects label stations and hull lines on HAER/ALMA/Gunnerus sheets | PAID (needs approval) | Authentic gold set | n/a |
| Fleet drawing sets, gauging, survey, repair records | Design-partner shipowner or yard via MarinaChain relationships | PARTNER (needs founder outreach) | Reconciliation, real customers | per vessel |
| Missing HAER sheets | Wapama sheet 8, 26 C.A. Thayer sheets (loc.gov blocks automation) | PARTNER/manual (a person downloads from loc.gov) | Completeness | small |

Rules for every acquisition: record source, licence, permitted uses, SHA-256 and size in a
manifest under `work/sources/<name>/`; nothing licensed is committed or sent to a provider
without a recorded decision; stay inside the free-disk headroom (warn above 10 GB per tranche).

## 4. Workstreams (run in parallel, separate worktrees, separate files)

| ID | Workstream | Model | Owns | Done when |
|---|---|---|---|---|
| W0 | Desktop app v1 (backend + UI) | Sonnet + Opus | `app/`, `rust-control/src/lib.rs` | Running app on macOS shows a live run (in progress) |
| W1 | Gunnerus real-ship benchmark | Opus | `benchmarks/gunnerus/`, DXF lines ingestion module, `docs/BENCHMARK_GUNNERUS.md` | Frozen-code run; published half-breadth, section and displacement errors vs the STEP model |
| W2 | Benchmark factory: render drawings from Ship-D, SIMMAN, DTC/JBC/Series 60 with realistic degradation; sealed splits | Sonnet | `benchmarks/factory/`, `docs/BENCHMARK_FACTORY.md` | Reproducible generator, frozen holdout manifest, accuracy table at scale |
| W3 | Structure from midship drawings (MiDShip) | Opus | `src/vessel_reconstruction/structure/`, tests, `docs/STRUCTURE_V1.md` | Member detection and placement scored against MiDShip 3D/annotations on a sealed split |
| W4 | Rules as cited data + checks on structure | Sonnet | `rules/`, `src/vessel_reconstruction/rules/`, `docs/RULES_V1.md` | IACS CSR subset encoded with citations; agreement rate vs MiDShip ABS evaluations |
| W5 | Data acquisition (open sources in section 3) | Sonnet | `work/sources/*` manifests, `docs/DATA_ACQUISITION.md` | Every OPEN row acquired or blocked with reason |
| W6 | Review gate, sign-off, review packet, gauging overlay in the app | Sonnet | `app/` (after W0 merges) | Signed decision records exported and verified |
| W7 | Design-partner pack: one-pager, data request list, pilot plan | CEO + founder | `docs/partners/` | Founder approves and sends (outward-facing: founder only) |

Wave 1 (now): W1, W3, W4, W5, with W0 already running. Wave 2: W2 (after W1 sets the
metric definitions), W6 (after W0 merges), W7 (needs founder input).

Engineering rules for every stream: no widened gates after seeing results; sealed holdouts
split by vessel/design family; no reference answers in inference; `engineering_approved=false`
everywhere; one owner per file.

Test tiers (`Makefile`): agents run `make test-quick` (format, Clippy, unit tests, secret scan;
real-CAD tests skipped; about 1.5 min) before each commit and report it. The CEO runs
`make test-full` (adds the real-CAD Rust tests marked `#[ignore = "real CAD ..."]`, the pytest
`cad` marker and the deterministic smoke run) once before each merge. New tests that build or
audit real CAD must carry those marks. Run only one full tier on the machine at a time.

## 5. Targets for the next 90 days

1. Gunnerus: published, reproducible hull accuracy figures from frozen code (W1).
2. Hull accuracy table on at least 1,000 rendered drawings plus 8 benchmark hulls (W2).
3. Structure v1: midship member detection with precision/recall and placement error on a
   sealed MiDShip split (W3).
4. Rules v1: one rule family encoded with citations, agreement measured against MiDShip
   evaluations (W4).
5. App v1 used by the founder on real runs; review gate and sign-off export (W0, W6).
6. One design partner with a real drawing set under an agreed data-handling note (W7).

## 6. Decisions needed from the founder

- Budget for expert labelling (freelance naval architects) and its scope.
- Which MarinaChain relationship to approach first for a design partner, and who sends it.
- Whether to download the next MiDShip tranche (about 12 GB).
- Whether any DeepSeek transfer of licensed drawings is allowed (today: none).

## 7. Update 2026-11-08: LLM-first reading (founder decision)

Evidence: the benchmark factory (docs/BENCHMARK_FACTORY.md) shows the deterministic reader is
accurate when it reads (sealed 6/6 correct) but reads almost nothing on realistic drawings
(12 builds of 1,080; all overlaid body plans and all moderate/heavy scans declined), plus one
silent wrong build. The founder: "we should lean even more on LLM".

Direction: the vision LLM becomes the primary reader; deterministic code becomes the verifier
and the fallback.
- W11 (running): LLM line identity with wide investigative autonomy; picks snapped to ink and
  verified; unconfirmed picks are draft guesses.
- W12 (new): LLM sheet setup (proposes panels, scale, datum, station positions; deterministic
  cross-checks against scale bar, grid, dimensions and views) and an LLM veto reviewer (compares
  drawing and rendered STEP sections after a build; can block, never approve).
- Default policy in the app becomes live (LLM) with draft on ambiguity, once W11 and W12 pass on
  a fresh sealed factory split.
- Unchanged: the Rust controller alone decides review readiness; engineering_approved=false;
  no widened gates; every model call and image is receipted.
- Later: a self-hosted vision model for confidential customers, measured against DeepSeek on
  the same sealed split.
