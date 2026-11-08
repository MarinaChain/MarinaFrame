# Lane D: the naval architect's review, trust and handoff workflow (design)

Date 2026-11-08. Base `continue/v0.5`. Branch `design-d-review`. Design only; no code change.
Status: proposal for the founder. Resume point: section 8.

Read before this file: `docs/APP_SPEC.md` (screens, types, drafts, AI labels),
`docs/plans/2026-11-08-whole-vessel-design.md` (offset table, scoreboard, keep rule),
`app/core/src/draft_view.rs`, `app/ui/js/app.js` (current review UI),
`src/vessel_reconstruction/{station_overlay,fairness,whole_vessel_score}.py`.

## 0. Summary

The reviewer is a naval architect (NA) who checks many AI drafts. Value = hours saved per drawing
and more drawings covered. The NA must be able to accept, correct or reject a draft in minutes,
and must never have to trust the AI's own words. So every trust signal is a **measurement against
the drawing ink** or a **classical hull check** (fairness, hydrostatics, dimensions), and every
section shows **where its geometry came from**. The app records a review; it never approves.

Evidence that shapes this design (sample `work/f1-overlay/w18c-round1_dtmb5415-L0_r0191/`):
seven `repaired` sections fit the ink to 0.000 m RMS; the two `ai_corrected` sections (s01, s09)
miss the ink by up to 3.96 m and 2.12 m. The per-section ink fit already finds the bad sections.
Today the app does not show it: the strip shows "Guessed / AI corrected", not "misses the ink by
4 m". Showing that number is the largest single trust gain available.

## 1. What the NA needs to see to trust or reject a draft (ranked)

| # | Need | Why an NA asks for it | Source today |
|---|---|---|---|
| 1 | **Built section cuts drawn over the source ink**, per station, with an ink-fit number (max and RMS, m and % of B/2) | This is how a loftsman checks a lines plan: lay the new body plan over the old one. Seconds per station. | `station_overlay.py` (sheet + per-section scoreboard); not in the app |
| 2 | **Provenance per section** (traced, repaired, interpolated, AI inferred, AI corrected, omitted), on the body plan, the strip and the 3D model | The NA trusts ink, checks repairs, and inspects every AI section. | `source_label`, `source_counts` (in the app as chips) |
| 3 | **Disagreement flags**: AI or repaired sections whose ink fit is large, ranked worst first | An AI correction that leaves the ink is the most common bad draft (dtmb5415-L0: 18 % RMS from 2 sections). | ink fit + label; join not done |
| 4 | **Fairness along the length**: half-breadth per waterline vs x, keel/top height vs x, sectional-area curve, with the flagged station marked | A body plan alone hides an unfair station; the NA fairs in plan and profile too. | `fairness.py` warnings (text only) |
| 5 | **Principal dimensions and hydrostatics vs the drawing**: LOA/LPP, B, D, T from the model vs title block or spec; displacement, Cb, LCB at design draft | A 3 % beam error or an impossible Cb (0.95 for a tug) rejects a draft at once. | dimensions in `model`; hydrostatics not computed |
| 6 | **Open guesses with their alternatives** (confirm, use another line) | Each guess is a decision the NA must own. | `DraftView.guesses` (in the app) |
| 7 | **Gaps**: stations with no readable ink, bridged spans, dropped ends, shaded on the 3D model | The NA must know which part of the hull is invented. | guessed x ranges (in the app) |
| 8 | **Model basis** for AI sections (one line) | Useful to understand a choice; never evidence. Lowest rank on purpose. | `authored_basis` (in the app) |

Rule for the UI: items 1-5 are numbers and pictures from code; item 8 is labelled "the AI's
reason (not checked)". The AI's text never appears next to a pass/fail colour.

## 2. Review flow

### 2.1 Triage: the review queue (many vessels)

A new top-level view "Review queue" (the library sidebar becomes a table when wide). One row per
run: vessel, sheet thumbnail, status, **agreement band**, sections by source (mini bar),
worst section ("s01: 3.96 m off ink, AI corrected"), open guesses, fairness warnings, cost, age.

Sort default: agreement band, then worst ink fit descending inside the band, so that the fastest
decisions (clear pass, clear fail) are at the top of their groups. Filters: band, status,
batch, source label present ("has AI sections"), reviewer.

**Agreement band** (code only, no truth, no model; thresholds tuned on development rounds):

| Band | Rule (draft) | Meaning shown |
|---|---|---|
| Close to drawing | every built section ink max <= 1 % B/2; no fairness warning; no open gap | "All sections follow the drawing ink" |
| Check sections | some section 1-3 % B/2, or fairness warnings, or AI/interpolated sections without ink | "N sections to check" |
| Large disagreement | any section > 3 % B/2, or dimensions off > 2 % | "N sections far from the ink" |
| No usable draft | no STEP, failed, blocked | "No 3D model" + reason |

The band is not a probability of correctness. W19b showed the combined fit must first be checked
against truth rank; until that holds on a round, the UI says "agreement with the ink", never
"confidence" or "accuracy".

### 2.2 Per-vessel overview (one screen, about 30 s)

Top to bottom: status and band; dimension check row (model vs drawing, with deltas); the
overlay sheet with all stations, each panel framed by its source colour and ink-fit value; a
fairness strip (half-breadth vs x for 3-5 waterlines, flagged stations in red); hydrostatics
card; open guesses list. Keyboard: `J/K` next/previous section, `Enter` open section, `A`
accept guess, `R` reject draft, `N` note.

Two exits from the overview: **Accept as a starting model** (only when no guess is open) or
**Inspect sections** (opens the worst first).

### 2.3 Per-section inspection

Existing layout (drawing | 3D | inspector) with three changes:

1. The drawing pane shows the built cut over the source crop (overlay), not only the candidates.
   Residual colour along the cut: green < 1 % B/2, orange < 3 %, red above (same colours as
   `residual_colour`).
2. The inspector header shows: label, ink fit (max/RMS), fairness note for this station,
   neighbour comparison ("wider than s02 and s04 at WL3").
3. For an AI section, the traced alternative is drawn and offered first: "Use the traced line
   (fits ink 0.00 m)" beside "Keep AI curve (misses ink by 3.96 m)".

### 2.4 Fast corrections

| Correction | Interaction | Backend | Exists |
|---|---|---|---|
| Confirm guess | one click / `A` | `choose_line` (confirm) | yes |
| Pick another stroke | click a candidate on the drawing or list | `choose_line` | yes |
| Revert AI section to trace | one button when a traced candidate exists | `choose_line` on the trace; the AI curve stays in history | no (trace may not be selectable today) |
| Accept AI section | confirm the `model_authored` guess; label stays `ai_inferred` | confirm guess | partly |
| Nudge | drag 3-5 handles on the cut, or type offsets at waterlines; code fairs (PCHIP + `[1,2,1]`) | new `edit_section` -> table cells `ai_corrected` -> `human_edited` | no |
| Redraw | draw a rough polyline over the ink; code snaps it to the nearest ink (`follow_ink`-style) and shows the snap distance | new `trace_from_hint` | no |
| Use interpolation | drop the section; loft spans neighbours; label `interpolated` | select none | partly |
| Lock | mark a section human-checked; no later AI run may change it | `locked` flag in the table (whole-vessel design, section 2) | no |

Every correction is a human operator event in the ledger (who, when, before/after). New label
`human_edited` for nudged or redrawn sections; `traced` stays for a picked stroke.

### 2.5 Re-run after correction

- **Rebuild** (default, about 10-60 s, no model): compile, build draft, overlay, fairness,
  hydrostatics. Shows a before/after diff: ink fit per changed station, displacement and LCB
  change, fairness warnings added/removed.
- **Re-fit** (whole-vessel Phase 2, no model): refit unlocked cells around the NA's locked
  sections, so one correction also fixes neighbours. Kept only by the F4 keep rule; shown as a diff.
- **Ask the AI again** (optional, costs requests): Phase 3 loop with human-locked sections fixed
  and the NA's note passed as a hint. The result is a new revision; the NA's revision is never
  overwritten. Compare revisions side by side.

### 2.6 Sign-off with notes

Review states (app-level record, separate from controller status):

| State | Set by | Allowed when | Text |
|---|---|---|---|
| Draft | system | open guesses or no STEP | "Draft: 2 guesses to check" |
| Ready for review | system | no open guess, STEP valid | "Ready for review" |
| Reviewed: usable as a starting model | NA | Ready for review | "Reviewed by A. Tan, 8 Nov 2026: usable as a starting model. Not approved for construction." |
| Reviewed with reservations | NA | Ready for review; note required | "... usable with reservations: stern above WL6 not checked." |
| Rejected | NA | any; reason required (pick list + text) | "Rejected: wrong station spacing" |

The record (`review.json` in the task folder, plus a ledger event) holds: reviewer name (typed,
local; no accounts in v1), time, draft revision and STEP/STL hashes, review state, scope
checkboxes (sections checked, fairness checked, hydrostatics checked, dimensions checked),
per-section notes, overall note. Any later change to geometry makes the record "stale" and the
state returns to Ready for review. Reject reasons feed back into development data (with consent).

## 3. Outputs the NA wants

| Output | Content | Target tools | Priority |
|---|---|---|---|
| STEP (AP214) | solid + surfaces (exists) | Rhino, SolidWorks, NAPA, Maxsurf import | have |
| IGES | NURBS surfaces of the hull | Maxsurf, older Rhino/AutoCAD flows, many yards | P1 |
| Offsets table CSV / XLSX | half-breadths at drawn stations x waterlines (plus keel/top heights), units, origin and datum stated; XLSX cell colour = source label; second sheet = labels | Every NA, class submissions, lofting, Maxsurf/Delftship input | P0 CSV, P1 XLSX |
| Hydrostatics summary | at design draft: displacement (volume and tonnes at stated density), LCB, VCB/KB, Awp, LCF, BMt, Cb, Cp, Cm, Cwp, wetted surface; P1: table at 5-10 drafts (curves of form) | Sanity check vs drawing and owner data; not a stability booklet | P0 basic, P1 table |
| PDF review report | cover (vessel, revision, reviewer state, "not approved for construction"), dimension check, overlay sheet, provenance map, fairness plots, hydrostatics, guesses and decisions, AI sections with basis, ledger summary, hashes | Owner, yard, internal QA, class correspondence | P0 |
| DXF lines plan | body plan, half-breadth (waterlines) and profile as 2D polylines from the model; layers per source label (`MF_TRACED`, `MF_AI_INFERRED`, ...), station/waterline grid layer, title block | AutoCAD, Rhino 2D, comparison overlay with the original | P1 |
| STL | mesh (exists) | viewing, 3D print, quick CFD mesh | have |
| 3DM / Maxsurf .msd | native files | Rhino, Maxsurf | P2 |

Every export carries the same stamp in its header or title block: tool version, task, revision,
review state, "Draft hull model from MarinaFrame. Not approved for construction." The STEP header
`FILE_DESCRIPTION` and DXF/PDF title blocks hold it. Units and origin (x from AP, z from baseline,
metres) are stated in each file, because a wrong datum is the most expensive handoff error.

Class documentation: the outputs are inputs to the NA's own work (the NA re-runs hydrostatics and
stability in approved software). The PDF report helps trace the geometry's origin; it is not a
class document. Say this once in the report cover.

## 4. Batch and ground coverage

1. **Drop a folder** (or pick one): the app lists sheets found (PDF pages, PNG, TIFF), one row
   each, with page thumbnails. Multi-page PDFs split per page; a page with no body plan is
   marked "skip" by Phase 1 `describe_views` (P1) or by the user.
2. **Specs**: v1 needs a spec per sheet. P0: pair `sheet.png` with `sheet.spec.json` by name, and
   offer a quick spec form (stations count/spacing, LPP, B, D, scale) with values copied across
   rows. P1: Phase 1 reading proposes the spec; the NA confirms it in the queue (one click per
   sheet when the title block is clear).
3. **Run all**: queue with the existing two-job limit and native worker lock; a cost cap per batch
   (shown before start: "50 sheets, about $3-9 at current rates") and a request cap per case (40).
   Runs survive app restart (resume), and the Mac does not sleep (keep-awake while a batch runs).
4. **Morning review queue**: the batch opens as a filter of the review queue (section 2.1), with a
   summary: "50 sheets: 31 close to drawing, 12 to check, 4 large disagreement, 3 no 3D model".
   Failures are grouped by reason ("no body plan found: 2", "CAD complexity limit: 1") with a
   one-click retry (deterministic draft, or AI again).
5. **Batch export**: one ZIP per batch of reviewed vessels: STEP, offsets CSV, PDF report per
   vessel, plus `index.csv` (vessel, state, reviewer, band, displacement, hashes). Rejected and
   unreviewed vessels are excluded unless the NA ticks "include drafts" (then stamped "Draft").

Measures to report per batch (the product's value): sheets in, drafts out, reviewed usable,
review minutes per vessel (timer from open to sign-off), corrections per vessel, cost per usable
model.

## 5. Trust signals and wording

Principles: show measurements, not adjectives; say what was checked and against what; the AI's
statements are labelled as claims; never imply approval.

| Never write | Write instead |
|---|---|
| Approved, Verified, Certified, Validated, Accurate, Correct | Reviewed by <name>: usable as a starting model / Follows the drawing ink within 0.02 m |
| Confidence 92 % / AI confidence | Close to drawing (all stations within 1 % B/2 of the ink) |
| AI fixed section 1 | AI corrected section 1: its curve misses the ink by 3.96 m |
| Hull is fair | No fairness warning along 5 waterlines (method: neighbour range) |
| Ready for construction / production | Not approved for construction (stamp, once per export) |
| Needs review (for a run with no NA action) | Ready for review |

Label names in the UI (keep the internal labels; show plain words): Traced = "From ink",
Repaired = "From ink, repaired", Interpolated = "Filled between stations", AI inferred = "AI drawn
(no ink)", AI corrected = "AI changed the ink", Human edited = "Edited by <name>", Omitted =
"Not modelled". Colours: ink labels neutral/blue, filled grey dashed, AI orange, disagreement red.

Each number links to its method on hover: "Ink fit: distance from the built cut to the nearest dark
pixel in the station's crop; render tessellation, chord 2 mm". A signal that was not computed is
shown as "not checked", never as a pass.

The existing notice "A naval architect signs off outside this app" changes to "Your review is
recorded here. It is not an engineering approval." (shown once, dismissible).

## 6. Prioritised features

Effort: S <= 2 days, M 3-7 days, L 2-4 weeks (one engineer, existing code reused).

### P0 (makes review fast and honest; needed for a pilot NA)

| # | Feature | Effort | Builds on |
|---|---|---|---|
| P0-1 | Overlay in the app: built cuts over ink per section, ink fit on each tile and in the inspector | M | `station_overlay.py` output; `TaskView` gains `section.ink_fit` |
| P0-2 | Disagreement flags: rank sections by ink fit; red when AI/repaired section > 3 % B/2; open worst first | S | P0-1 |
| P0-3 | "Use the traced line" for AI-corrected sections (revert to trace, one click, rebuild) | S | `choose_line`; make the replaced trace selectable |
| P0-4 | Review queue across runs with agreement band and worst-section text | M | P0-1, fairness warnings |
| P0-5 | Review record and sign-off states (section 2.6), stale on change, wording (section 5) | M | ledger event, `review.json` |
| P0-6 | Offsets table CSV with source label per cell, datum and units | S | build sections / whole-vessel table |
| P0-7 | Hydrostatics summary at design draft (volume, displacement, LCB, KB, Awp, LCF, BMt, Cb, Cp, Cm, Cwp) | M | OCC volume/centroid of the STEP solid cut at T |
| P0-8 | Dimension check row (model vs spec/title block, deltas) | S | `model` dims, spec |
| P0-9 | PDF review report (section 3) | M | P0-1, P0-5, P0-7 |
| P0-10 | Batch v1: folder of sheet+spec pairs, run all with cost cap, resume, morning summary | M | `start_run`, job limit |
| P0-11 | Export stamp in STEP header and every report | S | export code |

### P1 (fewer clicks per correction, better handoff)

| Feature | Effort |
|---|---|
| Fairness plots (half-breadth vs x per waterline, sectional-area curve, keel/top) with flagged stations | M |
| Nudge (handles or typed offsets, code fairs) and `human_edited` label | M |
| Redraw with snap to ink | M |
| Lock sections + deterministic re-fit around locks (whole-vessel Phase 2) | M (after W19a) |
| Ask the AI again with locks and note; revision compare side by side | M |
| IGES export | S |
| DXF lines plan with label layers | M |
| XLSX offsets with coloured provenance; curves of form table | S |
| Batch: Phase 1 proposes specs; multi-page PDF split; failure grouping and retry | L |
| Batch ZIP export with `index.csv` | S |
| Keyboard-first review and review timer | S |

### P2

| Feature | Effort |
|---|---|
| Rhino 3DM / Maxsurf native export | M each |
| Compare with a printed offsets table on the sheet (vision table reading) | L |
| Plan and profile overlays in the app (whole-vessel Phase 3 views) | M (after W19b) |
| Second reviewer / reviewer roles, web deployment sharing | L |
| Reject reasons as development data (consent, rights check) | M |

## 7. Data and type changes (for the backend lane)

`SectionView` gains `ink_fit: { max_m, rms_m, max_pct_half_beam, coverage } | null` and
`fairness: string | null`. `TaskView` gains `hydrostatics | null`, `dimension_check[]`,
`review: ReviewRecord | null`, `band`. `TaskSummary` gains `band`, `worst_section_text`,
`open_guesses`, `review_state`. New commands: `set_review`, `export_offsets`, `export_report`,
`start_batch`, `list_batches`. All read existing files; none adds a controller failure state;
`engineering_approved` stays false everywhere.

## 8. Open questions and resume point

1. Band thresholds (1 % and 3 % of B/2): confirm on one development round against truth RMS
   before showing bands to a pilot user.
2. Reviewer identity without accounts: a typed name in Settings is enough for v1?
3. Hydrostatics density default (1.025 t/m3) and which draft is "design draft" when the spec
   has none.
4. Should "Reviewed with reservations" be allowed to export without the "Draft" stamp?

Resume point: founder review of sections 1, 5 and 6. On approval, brief P0-1..P0-3 (UI + backend,
one lane) and P0-6/P0-7/P0-11 (export lane) in parallel; then P0-4/P0-5/P0-9/P0-10.
