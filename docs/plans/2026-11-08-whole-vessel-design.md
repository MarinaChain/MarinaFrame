# Whole-vessel modelling for the AI investigator (design)

Date 2026-11-08. Base `continue/v0.5`. Branch `design-whole-vessel`. Design only; no code change.
Status: proposal for the founder. Resume point: section 10.

## 0. Summary

Today the investigator works station by station: it picks or authors one curve per station, then
lofts. It almost never uses the plan (half-breadth) view or the profile view
(`propose_sheet_setup` and `compare_views` exist but are almost never called). A naval architect
fairs the lines in all three views at the same time: the half-breadth of station x at waterline z in
the body plan must equal the breadth of waterline z at station x in the plan view, and keel, stem,
stern, deck and sheer must agree with the profile.

This design changes the unit of work from "a curve per station" to **one offset table for the whole
vessel**: half-breadth `hb(x_i, z_j)` on stations x waterlines, plus profile boundaries. The body
plan, plan view and profile are three projections of that one table, so cross-view agreement is a
property of the data structure, not a separate check.

1. **Phase 1, read the vessel.** The model writes a structured hull description (dimensions,
   stations, waterlines, ends, deck, form type, view map). Code measures pixels and adds warnings.
2. **Phase 2, first full hull.** Code fits a fair, complete offset table: traced ink is kept as
   exact anchors, and a small general form family fills the gaps. No model call is needed.
3. **Phase 3, match to all views.** Code measures the table against the ink of every view and
   makes one scoreboard. The model edits the table or the description. An edit is kept only if the
   combined ink fit improves or it fills cells with no ink (F4). `finish` delivers the best table.

The CAD path does not change: the table compiles to sections for the existing `build_draft`.

## 1. Evidence that drives this design

| Evidence | Source | Consequence |
|---|---|---|
| dtmb5415-L0: the 7 traced sections were exact; the model's 2 "corrections" caused the whole 18 % RMS | founder brief; ideas backlog evidence 2-3 | Traced ink is locked by default. A model edit must win on measured fit. |
| 166 near-identical `propose_section` calls on one section | ideas backlog evidence 1 | The model needs numbers (residuals), not images only, and a fixed edit budget. |
| Latest drafts are complete but 18-43 % RMS (gate 2 %) | W18c digest | Progress is solved; accuracy is the problem. |
| Wrong drafts: partial strokes 27, grid lines 15, missing sections 6 | `work/w17/wrong-drafts-analysis.md` | A second view catches each of these: a grid line or fragment cannot match the plan waterlines. |
| W15: 792 plan anchors, all refused (648 competing crossings, 144 missing endpoint identity) | `docs/BENCHMARK_GUNNERUS.md` §9 | Do not ask the plan view for a unique crossing. Predict where the waterline is, then measure the nearest ink, with a confidence (section 5). |
| Localisation: model points about 45-51 px off; tracer 0.02 m | `docs/LLM_LOCALISATION.md` | The model gives identity and rough position; code measures. |
| Deterministic draft beat LLM-first in head-to-head (13 vs 9 correct) | `docs/BENCHMARK_FACTORY.md` | The first hull is deterministic; the model improves on it (keep-best). |

## 2. Data model (new, shared by all phases)

`vessel.json` (task domain state, one per task; versioned revisions like the spec):

```text
description:            # Phase 1, written by the model, checked by code
  units, frame          # x aft->fwd from AP (or station 0), z up from baseline, metres
  principal: loa, lpp, beam, depth, draft            (each: value, source, view_id)
  stations: [{id, x_m, label}]                        (body plan ids; spec ids where given)
  waterlines: [{id, z_m, label}]                      (from the body/profile grid)
  buttocks: [{id, y_m}]                               (optional, profile check only)
  ends: keel_z(x) | rise_of_floor, stem {type, x_top, x_foot, rake}, stern {type: transom|cruiser|
        counter, x_transom, transom_z_bottom}, bulb {present, length, height}
  deck: sheer_z(x) (profile), deck_hb(x) (plan deck line), camber (optional)
  form: {type: displacement|planing|..., sections_fore: U|V|flare, sections_aft: U|V|flat,
         parallel_midbody: [x0, x1], knuckles: [...]}
  views: [{view_id, kind: body|plan|profile|body_fore|body_aft, region_px, calibration (setup_id),
           halves, mirror}]
table:                  # Phase 2/3
  x: station x (m), z: waterline z (m)                (grid = description stations x waterlines)
  cells[i][j]: {hb_m, source: traced|plan_traced|fitted|ai_inferred|ai_corrected, locked}
  profile: {keel_z[i], top_z[i], stem polyline, stern polyline}
  extra_rows: section curves at full trace resolution between waterlines (kept for the build)
```

Rules: one table is the only geometry state. `build_draft` compiles each station row (cells plus
`extra_rows`, clipped by keel and top) into the existing section curve and runs the existing builder
(including W18 knot limits and deck-edge closure). Source labels map to today's labels
(`traced`, `interpolated`, `ai_inferred`, `ai_corrected`), so the app view needs no change.

## 3. Phase 1: read the vessel

Goal: a complete description in about 4-6 model requests, before any section work.

**Flow.**

1. Code (no model): `survey_sheet` tiles the sheet, runs the C1 grid detector and stroke discovery
   (`w18-stroke-discovery`) per region, and returns a sheet map: candidate view regions, regular
   grid families (spacing in px, orientation), text boxes, and long smooth strokes per region.
2. Model, one request with the whole sheet (0-1000 coordinates) and the sheet map: `describe_views`
   names each region (body / plan / profile / title / other), its halves, and which grid family is
   stations, waterlines or buttocks.
3. Model, one request per view (crop at full resolution): `propose_sheet_setup` (existing tool,
   now called by plan, not by chance) with scale claim and datum lines. Code snaps the datum lines
   to the detected grid lines (measurement), and reports the snap distance.
4. Model, one request: `describe_vessel` writes the description fields of section 2. Numbers come
   from the title block, dimension text, the declared spec, or the model's reading of the views.
   Each value carries `source` (`spec`, `title_block`, `measured`, `ai_inferred`).
5. Code: `measure_description` replaces every "measured" value that code can measure with the pixel
   measurement (for example beam = 2 x max ink half-breadth in the body plan; depth and sheer from
   the profile top line; stations and waterlines from grid lines). The model value stays in the
   record next to the code value.

**Checks by code (warnings only, never refusals).** Each warning names the field, both values and
a suggested fix:

- beam: body-plan max hb vs plan-view max breadth vs stated beam (warn > 2 %);
- depth/draft: profile vs body-plan top vs stated values;
- station x: monotone, count equals labelled stations, spacing fits the plan/profile grid;
- waterline z: monotone, spacing equals the body-plan horizontal grid, max below depth;
- ends: stem and transom x inside the profile outline; bulb present only if the profile shows it;
- labels: C3 sanity (`S1.5W`-style tags are waterline/buttock tags, not stations).

**Body-plan-only drawings** (most of today's dev set): steps 2-5 run with the body view only. The
description then comes from the spec, the body plan and `ai_inferred` values: keel and top z per
station from the section ends, beam from max hb, form type from the shapes. Plan and profile fields
are `ai_inferred` and do not enter the Phase 3 score.

## 4. Phase 2: first full hull

### Options

| Option | For | Against |
|---|---|---|
| A. Parametric fit, Ship-D generator (45 parameters) | Always fair and complete; one fit uses all views | Ship-D dev cases are drawn from this generator, so it leaks the test family and flatters Ship-D. Poor family for DTMB, Gunnerus, real ships (bulbs, knuckles, skegs). Non-convex 45-D fit: slow, local minima. |
| B. Interpolation from traced stations only | Keeps exact ink (dtmb-L0 lesson); cheap | No answer where few stations trace (L2/L3, overlay); no use of plan/profile; ends stay wrong. |
| C. Model authors all sections | Fills every gap | Evidence: the model's numbers are its weakest output (dtmb-L0 18 %, 166-call loops). Expensive. |
| **D. Anchored form fit (chosen): B + a small general form family for gaps** | Exact where ink exists, fair and complete everywhere, uses all views, no model call | New code (one module); the family is simple, so gap shape is approximate until Phase 3 |

### Chosen method: anchored form fit

1. **Anchors.** All cells with measured ink: body-plan traces (stroke discovery top candidate per
   station, C2 assignment for overlay panels, `follow_ink`-style snapping), plan-view waterline
   crossings (section 5, measured at the predicted position), profile keel/top/stem/stern.
   Each anchor has a confidence (coverage, hull-likeness, plan/body agreement).
2. **Trend (form family).** Per station: top half-breadth `b(x)`, keel height `k(x)`, top height
   `t(x)` from the profile, and a two-parameter section shape `s(x)` = (fullness, deadrise). The
   section curve is a superellipse between keel and top: `hb(z) = b * (1 - (1 - eta)^p)^(1/p)` with
   `eta = (z - k) / (t - k)`, plus a straight deadrise segment. Each longitudinal parameter is a
   smooth curve in x (cubic spline, 6-8 knots, fixed smoothing). About 25-35 numbers in total.
   Bulb and transom are local add-ons from the description (bulb ellipse in the profile; transom
   cuts the table at `x_transom`). The description's form type gives the start values.
3. **Fit.** Weighted least squares of the trend to all anchors (scipy, bounded, deterministic, under
   1 s). Then the table = trend + residual field, where the residual at anchors is exact and is
   interpolated in x (PCHIP along each waterline) and in z (along each station). So traced cells
   keep their ink value exactly, and cells with no ink get trend plus nearby residuals.
4. **Fair.** Existing fairing (PCHIP, `[1,2,1]` passes) along stations and along waterlines, never
   on locked cells; D1 fairness runs on the result and becomes warnings.
5. **Build.** Compile rows to sections; `build_draft`; F1 overlay; first scoreboard (section 6).

Labels: anchors `traced` / `plan_traced`; filled cells `fitted` (shown as `interpolated`). Locked:
body anchors with coverage >= 90 % and hull-like (not grid, not vertical, W18c advisory checks).

This is idea D2 and J6 in a form that keeps the "model writes geometry" rule: the fit is the
deterministic first draft (F4 baseline); the model then edits the table and the description.
Ship-D option A stays out of the product. It may be used only as an offline upper-bound probe on
Ship-D dev cases, never as a tool.

## 5. Phase 3: match to all views

### Measurement by code (per view)

| View | What code cuts from the table / build | What it measures in the ink | Reuse |
|---|---|---|---|
| Body plan | Built STEP cut at each station x (render tessellation) | Signed distance cut -> nearest ink per waterline z, in m; coverage | F1 `station_overlay.py` scoreboard |
| Plan | Table row at each waterline z: `hb(x)` along x | Predict-then-measure: at each station column, the ink run nearest the predicted y within a band of 3 % B/2 (min 6 px); report distance, number of competing runs, confidence | W15 `plan_corridors.py` column reading, without the unique-crossing refusal |
| Profile | Keel line, top/sheer line, stem and stern polylines | Distance to the nearest ink along normals; profile outline coverage | `ship_cad.check_views` sampling; stroke discovery on the profile region |

Why predict-then-measure fixes W15: W15 needed one unique crossing per column and an identified
waterline region, so 648 of 792 anchors were refused for competing crossings. Here the table says
where waterline z should cross at station x; code takes the nearest run and scores it. Competing
runs lower the confidence weight; they do not refuse. Waterline identity per stroke comes once per
plan view: the model tags the plan strokes (from stroke discovery) with waterline ids in one
`label_view_strokes` call (the W16 idea), and code uses the tagged stroke first, the nearest run
second.

### Combined scoreboard

One JSON result and one line in the progress observation:

```text
draft r0004  fit 0.94 (best r0004)  body 0.031 m  plan 0.058 m  profile 0.12 m  coverage 91 %
worst: s09 body +0.41 m z 1-3 m | WL2 plan x 88-96 m -0.35 m | stem profile 0.9 m
fairness: 1 warning (s01)   description: 2 warnings (beam plan vs body 2.6 %)
```

- Per cell: residual per view (m and % B/2), confidence, source label.
- Per station, per waterline, per profile line: RMS, max, coverage, and the worst range.
- Combined fit = confidence-weighted mean of `1 - min(1, |residual| / (5 % B/2))` over all
  measured cells, with each view weighted by its share of measured cells (no view tuning). Cells
  with no ink in any view do not count; they are reported as gap count.
- One overlay image per view: table cuts drawn over the ink, residual colour (green < 1 % B/2,
  orange < 3 %, red above). The body overlay is F1's; plan and profile overlays are new and use
  the same drawing code.

### How the model revises

Tools (all draft mode; results are observations; nothing new refuses):

- `edit_table {target: station s|waterline w|profile line, z or x range, delta_m | values | form}`:
  delta edits (idea B5) on cells; `form` edits change trend parameters for a range (fullness,
  deadrise, bulb size).
- `edit_description {field, value, reason}`: for example move a waterline z or the transom x; code
  re-measures and re-fits all unlocked cells.
- `unlock_cells {target, reason}`: the only way to change a locked traced cell; the edit is then
  judged by the same keep rule.
- `label_view_strokes {view_id, tags: {stroke_tag: waterline_id|station_id|keel|sheer|stem}}`.
- `revert {revision}` and `finish`. `build_draft` and `render_candidate` stay; build runs
  automatically after each kept edit batch, so the model does not need to ask.

**Keep rule (F4).** Code applies an edit to a copy, re-measures (no CAD build needed: the table
cuts are analytic for plan and profile; body uses the table rows before the build), and keeps it
only if (a) the combined fit improves by >= 0.002, or (b) it changes only cells with no ink in any
view (a gap fill), and measured cells do not get worse by more than 0.5 % B/2. A rejected edit is
not a refusal: the result says "kept r0004; your edit made WL2 plan -0.4 m worse" with the numbers.
`finish` always delivers the best-fit revision, not the last.

**Budget.** Soft per-target budget (A2): after 3 rejected edits on one target the result suggests
another target. Phase hints (A6) per phase. Hard cap 40 model requests per case; at the cap the
best revision is delivered as `draft_not_verified`.

## 6. Reuse and new work

| Item | Reuse as | Change |
|---|---|---|
| F1 `station_overlay.py` (f1-station-overlay) | Body-view measurement and overlay | Generalise the drawing code to plan/profile overlays |
| D1 fairness (d1-fairness) | Warnings on the table along x per waterline and along z per station | Run on the table, not only on the built sections |
| C2 `panel_assignment.py` (c2-overlay-assignment) | Overlay body plans: one stroke per station as Phase 2 anchors | None |
| Stroke discovery (w18-stroke-discovery) | Candidate strokes in every view, grid tagging, hull-likeness | Run on plan and profile regions too |
| W15 `plan_corridors.py` | Column reading of plan ink | Predict-then-measure mode with confidence, no refusal (new function, old one kept) |
| `propose_sheet_setup`, `compare_views` | Phase 1 setups per view; `compare_views` replaced by the plan scoreboard | Snap datum lines to detected grid |
| `ship_cad` language (W13) | The table is the host measurement for the `hull` op; profile sheer/deck lines feed `deck` later | None now |
| `propose_section` (W17c) | Still accepted; compiles into an `edit_table` on one station row | Judged by the keep rule |
| `section_authoring.py` fairing | Fairing of table rows/columns | None |
| New | `vessel_model.py` (description + table + compile), `form_fit.py` (anchored form fit), `view_measure.py` (plan/profile predict-then-measure), `whole_vessel_score.py` (scoreboard, keep rule), `survey_sheet` | |

## 7. Data and testing

**Factory.** Today it renders body plans only. Branch `factory-three-view` (other engineer) adds
plan and profile views. Interface this design needs from that branch (please confirm with its
owner): per case, `views.json` with each view's region, kind, calibration and halves, in the same
spec form as body sections; truth meshes stay as now (waterline and profile truth are cuts of the
same mesh). No truth value enters the inputs.

**Round sets (4 cases each, development hulls only, never sealed v2/v3):**

| Set | Cases | Use |
|---|---|---|
| R-body | dtmb5415-L0, Ship-D separate L2, Ship-D overlay L0, Ship-D overlay L2 (G2 mixed set) | Body-only fallback; every stage |
| R-3view | the same 4 hulls rendered as 3-view drawings (L0, L2, L0, L2) | After `factory-three-view` lands |
| Gunnerus | 1 case, qualitative only (dev data) | After W21 |

**Metrics (per case, by `round_digest.py --factory`):** frozen gate (station RMS <= 2 % B/2 and
|in-range volume| <= 5 %); first-hull RMS (after Phase 2, before any model edit); best and final
RMS; waterline RMS (plan cut vs truth) and profile max distance; combined fit (label-free) and its
correlation with truth RMS across the round; edits proposed / kept / rejected; requests, tokens,
list cost per case and per draft; silent wrong builds (must stay 0).

**Must-hold invariants per round:** no case ends worse than its first hull (keep-best); no new
terminal failure state; every draft labelled `draft_not_verified`, `engineering_approved` false.

**Body-plan-only fallback.** The table is still the state. The plan-view score is replaced by the
table's own x-fairness (D1 along each waterline): this is the "virtual plan view". The profile
score is replaced by keel/top smoothness along x. Combined fit = body fit only; fairness stays
warnings. This is the mode for the current dev set and for most real body-plan-only sheets.

**Unit tests (no LLM, G3 style):** synthetic table -> render 3 views -> measure -> residual 0
within 1 px; anchored fit keeps anchors exactly; keep rule accepts an improving edit and rejects a
worsening one; predict-then-measure picks the right crossing with 3 competing runs.

## 8. Cost per vessel

Effective DeepSeek V4.1 Flash rates from our receipts (W17b dev24: 5.05 M prompt + 87 k completion
tokens = $0.758): about $0.14 per M prompt tokens (with cache hits) and about $0.6 per M completion
tokens. Estimates are per case.

| Phase | Requests | Prompt tokens | Completion tokens | List cost |
|---|---:|---:|---:|---:|
| 1 Read (views, setups, description) | 5-7 | 60-90 k | 6 k | $0.012-0.016 |
| 2 First hull (code only) | 0 | 0 | 0 | $0 |
| 3 Match (12-25 edits, numbers + 1-3 images per turn) | 12-25 | 150-300 k | 8-15 k | $0.03-0.05 |
| Total (cap 40 requests) | 17-32 | 210-390 k | 14-21 k | **$0.04-0.07** |

Today: about $0.18 per case and $0.24 per draft (W18c round: $0.21, 94 requests and 1.36 M prompt
tokens per case). The saving comes from no per-station reading loops, numbers instead of repeated
images, the request cap, and a deterministic first hull. Every case ends with a draft, so cost
per draft equals cost per case. CPU: the anchored fit is under 1 s; each scoreboard without a CAD
build is under 0.5 s; CAD builds as today, about one per kept edit batch.

## 9. Staged implementation plan

Base for all lanes: `continue/v0.5` with `f1-station-overlay`, `d1-fairness`,
`c2-overlay-assignment` and `w18-stroke-discovery` merged into the W18 integration branch
(`w17-llm-progress`) first. That merge is step W19-0 (Sol's lane; it already owns that branch).

| Stage | Lane | Files owned (only this lane edits them) | 4-case check | Done when |
|---|---|---|---|---|
| W19-0 merge | Sol | merge commits on `w17-llm-progress` | R-body, current loop | merged; quick tier passes; round no worse than W18c |
| W19a table + anchored fit | A | new `vessel_model.py`, `form_fit.py`, `tests/test_form_fit.py` | R-body, no LLM: deterministic anchors -> fit -> build | first-hull RMS <= deterministic draft on 4/4; dtmb5415-L0 <= 2 %; unit tests pass |
| W19b view measurement | B | new `view_measure.py`, `whole_vessel_score.py`, overlay drawing in `station_overlay.py`, tests | synthetic 3-view + R-body | residual 0 within 1 px on synthetic; scoreboard on R-body; combined fit ranks the 4 cases like truth RMS |
| W19c 3-view factory | other engineer | `benchmarks/factory/*` on `factory-three-view` | renders R-3view | `views.json` interface (section 7) agreed; truth cuts available |
| W20a Phase 1 read | C | new `vessel_description.py`; `survey_sheet`; tool schemas `describe_views`, `describe_vessel` in `rust-control/src/controller.rs` + `types.rs` | R-body and R-3view, Phase 1 only (stop after description) | dims within 2 % on 4/4; station/waterline sets right on >= 3/4; <= 7 requests; warnings name each wrong field |
| W20b keep rule + scoreboard in the loop | B | `agent_tools.py` (build/render result fields), `investigation_tools.py` (new tools), keep-best `finish` | R-body, current tools + scoreboard | no case ends worse than its first draft; scoreboard in every build result |
| W21 Phase 3 tools + prompt | C | `edit_table`, `edit_description`, `unlock_cells`, `label_view_strokes`, `revert` (Python + Rust schemas), prompt rewrite, phase hints, 40-request cap | R-body then R-3view | >= 3/4 drafts; >= 1 more gate-correct than W19-0 on each set; 0 silent wrong; <= $0.08 per case |
| W22 evaluation | PM | `docs/`, `outputs/w22/` | dev24 once, then Gunnerus qualitative | dev24 correct count and cost per correct draft reported vs W18c; v3 check only after this |

Parallel lanes: W19a, W19b, W19c and W20a can run at the same time (no shared files; W20a's Rust
schemas are new entries only). W20b needs W19a + W19b. W21 needs W20a + W20b. Rust controller
files are edited by lane C only, so there is no merge race on `controller.rs`.

## 10. Risks and open questions

**Risks.**

1. *Form family too simple* (bulbs, knuckles, chines, tunnel sterns). Mitigation: anchors override
   the trend; knuckle positions from the description stop fairing across them; the model can edit
   the trend locally. Check: per-family first-hull RMS in W19a.
2. *A wrong description distorts every section* (for example wrong waterline spacing). Mitigation:
   code measures every value it can and warns on each disagreement; `edit_description` re-fits.
   The keep rule judges description edits too.
3. *Plan-view ink has competing curves* (diagonals, buttocks, deck line). Mitigation:
   predict-then-measure with confidence and model stroke tags; a low-confidence cell gets low weight,
   not a refusal. Check: plan residual on Gunnerus.
4. *Combined fit does not track truth* (a self-score can be gamed by matching the wrong ink, for
   example a grid line). Mitigation: grid strokes are masked (C1); W19b checks rank agreement of the
   fit with truth RMS before the loop uses it.
5. *Locked traces that are wrong* (a fragment marked hull-like). Mitigation: lock only at coverage
   >= 90 % and hull-like; plan/profile disagreement > 3 % B/2 unlocks automatically with a warning.
6. *Factory 3-view branch is late.* Mitigation: everything except R-3view works in body-only mode.
7. *Ship-D bias.* Ship-D dev hulls dominate the dev set; keep DTMB in every round and do not use
   the Ship-D generator as the family.

**Open questions for the founder.**

1. Is the 40-request cap acceptable as the default (best draft delivered at the cap)?
2. Should `unlock_cells` exist at all, or should traced cells change only through plan/profile
   disagreement (risk 5)? This design keeps it, judged by the keep rule.
3. Do we want buttocks and diagonals in the score later, or only waterlines and profile lines?
4. Table resolution: drawn stations x drawn waterlines, or a finer interpolated grid for the build?
   Proposal: the drawn grid for the score, full trace resolution (`extra_rows`) for the build.

**Resume point.** Next action: founder review of sections 4 and 9. On approval, brief W19-0 (Sol)
and W19a/W19b (two lanes) in parallel, each with its 4-case check from section 9.
