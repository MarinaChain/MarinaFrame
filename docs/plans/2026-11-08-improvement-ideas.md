# Improvement ideas for the AI drawing-to-hull investigator (backlog)

Date 2026-11-08. Base `continue/v0.5`. No code change. Status: brainstorm, ranked. Each idea needs a
4-case round before any campaign.

## How to read this

- Format per idea: **what**. Why (failure or principle, evidence). `I` = expected impact on correct
  drafts (H/M/L), `E` = effort (S/M/L), `C` = cost per draft (down / 0 / up). Test = 4-case round.
- Default round = DTMB L0-L3 (as in W17b-W18c). "Mixed round" = idea G2 (DTMB + Ship-D, separate +
  overlay). Every round: read every trace with `scripts/round_digest.py`, score with dev truth.
- Principles (binding): progress before provenance; AI fills gaps; the model writes geometry; happy
  path (no new failure states, checks are warnings in draft mode); small rounds first; LLM-first
  default; keep it cheap.

### Evidence keys

| Key | Source |
|---|---|
| WDA | `work/w17/wrong-drafts-analysis.md` (8 wrong W17b drafts, 63 sections classified) |
| DDA | `work/deterministic-draft-analysis.md` (deterministic arm, sealed v2 rows, dev truth) |
| W18C | `outputs/w18/w18c-digest.md` on `w17-llm-progress`; runs `work/w17/runs/w18c-round1/` |
| W18D | `work/w17/w18d-brief.md` |
| LLMI | `docs/LLM_INVESTIGATOR.md` on `w17-llm-progress` (W17-W18c log) |
| H2H | `docs/BENCHMARK_FACTORY.md`, "Head-to-head, hull-disjoint (v2)" |
| LOOP | `docs/plans/2026-11-08-w18-agent-loop-design.md` |
| MEM | `docs/research/agent-memory-patterns.md` |

### New evidence read for this backlog (w18c-round1 events and scores)

1. **The model re-submits the same curve.** dtmb5415-L0 made 189 `propose_section` calls: 166 on
   s09, 23 on s01. Of 165 consecutive s09 pairs, 162 differ by < 0.05 m at every common height
   (median change 0.0 m). The reason text repeats ("Authored s09 sits inboard of the drawn S ...").
   The model sees a mismatch in the image but cannot turn it into new numbers.
2. **The model replaced a good trace.** Its first s09 call says the trace "likely misread" the bulb.
   In W17b the same case's s09 trace matched truth within 0.02 m except the deck closure (WDA §4),
   and the closure is now fixed on `w18-cad-complexity`.
3. **L0 was near the gate.** Median station RMS 0.43 m, but RMS of station RMS 1.21 m; in-range
   volume +5.4 %; one section area is off by 179 %. One or two sections decide pass/fail.
4. **The first draft was deterministic.** L0 ran `inspect_source > select_contours > build_draft` before
   any authoring. Nothing compares later drafts with that first draft; the last draft is kept.
5. **Output refusals still end runs.** dtmb5415-L2 stops on `notes_limit` in w18c-round1 (10 requests)
   and again in the running w18c-dev24 (4 requests). L0 in dev24 hit `operation_contract`.
6. **Digest wording.** `round_digest.py` calls `draft_not_verified` with a STEP "failed"; LLMI notes this.

## A. Model loop and prompting

- **A1 Repair model output, never refuse it.** Truncate notes to the limit, clamp out-of-range
  arguments, coerce near-miss shapes (`operation_contract`); warn in the next observation. Why: L2
  ends on `notes_limit` in both w18c runs (W18D 1, evidence 5). I H, E S, C down.
  Test: DTMB L0-L3; zero `repeated_refused_model_output`; L2 reaches a build.
- **A2 Per-section edit budget (soft).** After 3 authoring calls on one section without a better
  ink-fit (B1), the result says "kept your best version of s09; move to another section or finish".
  Calls stay allowed. Why: 166 calls on s09 (evidence 1). I M, E S, C down.
  Test: max calls per section <= 6; same or more STEP drafts.
- **A3 Soft stop and best-draft finish.** After a valid draft: if 3 builds change little, or 20
  authoring calls happen without a build, tell the model to finish; at 80 requests end with the best
  valid draft as `draft_not_verified` (W18D 2-3). I M, E S, C down a lot.
  Test: requests <= 80 per case, cost per draft <= $0.10, no loss of drafts.
- **A4 Duplicate-action merge.** If a proposal equals the last one (within 0.05 m), do not run it;
  return "same as r-N; here is its ink-fit" (an observation, not a refusal). Why: evidence 1. I L,
  E S, C down. Test: number of identical consecutive proposals = 0.
- **A5 Plan turn.** First turn writes a short per-section plan (trace / candidate / author, and
  confidence) in notes; the progress line shows plan vs done. Why: wandering, e.g. 35
  `enumerate_strokes` in 679-L1 (WDA §4). I M, E S, C down. Test: fewer tools per section.
- **A6 Phase hints by state.** Controller adds one line by phase: read -> assemble -> check/revise
  -> finish. Hide tools that do not fit (no `inspect_source` after all sections are inspected).
  Why: dev24 L0 calls `inspect_source` again after a render. I L, E S, C down.
- **A7 Semantic stagnation nudge.** When the normalised reason text repeats 3 times, change the
  observation: show B1 numbers and suggest B2 or B4. Why: evidence 1. I M, E S, C down.
- **A8 Thinking only for authoring turns.** A/B thinking on for `propose_section` decisions. Never
  measured (LLMI W17). I M?, E S, C up. Test: paired 4-case rounds, same seed cases.
- **A9 Keep conversation mode only if it wins.** W18 did not improve construction over W17b round 2
  (LLMI W18). Decide with one paired round. I L, E S, C 0.
- **A10 Model-written handoff at compaction (LOOP 4a).** Deferred by founder; try after A2/A3.
  I L, E M, C up slightly.
- **A11 Shorter observations late in the run.** After a draft exists, send only the section in focus,
  its panel, and the draft score. Why: 5.4 M prompt tokens in w18c (LLMI). I L, E S, C down.

## B. Tools the model gets

- **B1 Ink-fit numbers for every section curve.** `propose_section` and `build_draft` return, per
  height, the signed distance (m) from the curve to the nearest ink in the panel, plus RMS and % of
  heights with ink within 2 px. Why: the model says "inboard" but cannot quantify (evidence 1).
  I H, E M, C down. Test: L0 s09 converges in <= 5 calls; ink RMS falls between calls.
- **B2 `follow_ink` authoring form.** Model gives a rough curve or 2-4 hint points; code snaps each
  height to the nearest ink run in a band and keeps the model's values where no ink exists. Labels
  heights `traced` or `ai_inferred`. Why: 27 partial strokes (WDA §3) and authored drift. The model
  still writes the geometry; code makes it exact. I H, E M, C down. Test: fragments covered >= 95 %.
- **B3 `extend_trace`.** Continue a traced candidate to keel and deck along ink; the model authors the
  tail where ink stops. Why: partial strokes, median coverage 59 % (WDA §3). Check overlap with
  `w18-stroke-discovery` fragment linking first. I H, E M, C 0.
- **B4 `compare_sections`.** One image with trace and authored curve over the ink, and B1 numbers for
  both; the model picks or reverts. Why: a good s09 trace was replaced (evidence 2). I M, E S.
- **B5 Delta edits.** `propose_section` form `adjust`: "+0.4 m between z 1-3 m" on the current curve,
  instead of a new 17-point array. Why: whole-array rewrites stay identical (evidence 1). I M, E S,
  C down.
- **B6 Multi-section authoring.** Fill several sections in one call (for example s07-s09 by blend).
  Why: requests, cost. I L, E S, C down.
- **B7 `measure` ruler.** Return half-breadth (m) of the ink at given heights in a panel. Why: the
  model guesses metres from pixels. I M, E S, C 0.
- **B8 Station strip view.** One image with all chosen section curves side by side in order, at one
  scale; the odd one out is easy to see. Why: wrong-station reuse (683-L0 s09, WDA §4). I M, E S.
- **B9 Fuzzy id resolution.** When the model cites a tag number or stale candidate id, map it to the
  current id and say so. Why: 7 and 16 refused `assign_station` in the 683 runs (WDA §4). I M, E S.
- **B10 Revert tool.** `revert_section s09 to <candidate or revision>` in one call. Why: evidence 2.
  I M, E S, C down.

## C. Vision and reading

- **C1 Sheet-level grid mask.** Detect the regular grid (waterlines, buttocks, centreline) once per
  sheet and draw it grey in stroke images; tag its candidates `grid`. Why: grid lines picked in
  7/7 wrong drafts, 15 sections (WDA §3). Merge `w18-stroke-discovery` first. I H, E M, C 0.
  Test: zero grid-line sections in the round's drafts.
- **C2 Overlay body plan rules.** Tell the model the half (fore/aft) and nesting order of stations
  (midship outermost, ends inmost), and give a hint when two sections use one stroke. Why: overlay
  LLM 0/144 built (H2H); 312/492 duplicate picks in the deterministic arm (DDA §1). I H (overlay),
  E M. Test: mixed round overlay cases have 0 shared strokes.
- **C3 Station label sanity, stronger.** Pure numbers, unique, monotone with x; `S1.5W`-style tags
  mapped to waterline/buttock (WDA §3). W18c has an advisory; add an auto-suggested mapping. I M, E S.
- **C4 Plan-view waterline cross-check.** Trace waterlines in the plan view; compare hb(x) at each
  station with the section hb at that z; warn at > 3 % B/2. Why: catches grid lines, wrong stations,
  missing bulbs. I H, E M, C 0. Test: every wrong section in the round gets a warning.
- **C5 Profile cross-check for z-range.** Keel, stem, stern and sheer from the profile give each
  station's bottom and top. Why: deck closure (WDA §4, DDA §3), truncated x range (679-L1). I M, E M.
- **C6 Auto zoom on gaps.** When a trace breaks, send a high-resolution crop of the gap. I L, E S.
- **C7 Scale and title-block cross-check (real drawings).** Scale bar vs beam/draft in the title block.
  Calibration was never wrong on factory data (WDA §2). I L (dev), E M.

## D. Geometry authoring and fairing

- **D1 Cross-station fairness outliers.** At each waterline, hb(x) over stations must be smooth and
  rise to midship; the sectional-area curve must be smooth. Name the outlier section and the expected
  hb range from neighbours (a warning). Why: 617-L3 s01 hb 35-41 m vs 12 m (WDA §4); one area +179 %
  (evidence 3). I H, E S, C 0. Test: each bad section in the round is named.
- **D2 Parametric hull family fill.** Fit a parametric family (Lackenby-style form parameters) to the
  sections the model trusts; use it for missing sections and as `propose_section form: family`.
  Why: 6 missing sections, 3 truncated hulls (WDA §3). I M, E L.
- **D3 Low-dimensional section shapes.** Express sections as a few coefficients (PCA from dev hulls
  only); the model edits coefficients. Why: 17-point arrays do not converge (evidence 1). I M, E L.
- **D4 End-section forms.** Add `transom` and `bulb` options; prior from the profile outline. Why:
  166 edits on the s09 bulb; s01 grid/fragment picks (W18C L0). I M, E M.
- **D5 Verify deck closure fix in a round.** Sections end at the deck edge (`w18-cad-complexity`).
  dtmb-L0 W17b was wrong only from closure (WDA §4). I M, E S. Test: dtmb-L0 deterministic draft
  scores <= 2 % RMS.
- **D6 Between-station check.** Slice the built loft between stations; warn on hb oscillation (the
  scorer's `between_station` metric shows max 6.7 m in L0). I M, E S.
- **D7 Midship anchor.** Read beam and draft from the fullest section; scale end proposals to it.
  I L, E S.
- **D8 Bulb-aware fairing.** Fairness relative to neighbours, so the PCHIP/[1,2,1] passes do not erase
  a real bulb or knuckle. I L, E S.

## E. CAD build

- **E1 Incremental build.** Rebuild only changed sections; reuse the loft for others. Why: long runs
  build 8-17 times. I L, E M, C 0 (time down).
- **E2 Never-block build, verified.** Knot-limit relaxation and deck-edge closure are merged (W18C);
  keep a ruled-loft fallback so a draft always exists. I L, E S.
- **E3 Build from plan + profile.** When the body plan is too poor, build from plan waterlines and
  profile. I M (L2/L3), E L.
- **E4 Per-section build deviation.** Report curve-to-surface deviation per section (partly done in
  `w18-cad-complexity`). I L, E S.

## F. Self-checking by the model

- **F1 Reproject the built hull onto the body plan.** Cut the STEP at each station, draw the cuts
  over the source panel at the source calibration, with B1 per-section scores. Why: `render_candidate`
  shows 3D views that cannot be compared with ink; the model re-authors blindly (evidence 1).
  I H, E M, C 0. Test: model fixes the worst section named in the overlay within 3 calls.
- **F2 Reproject onto plan and profile.** Built waterlines on the plan view, outline on the profile,
  with distance scores. I H, E M. Pairs with C4/C5.
- **F3 Draft scoreboard in the progress line.** "draft r0005 ink-fit 0.92, best r0003 0.95,
  fairness warnings 1". Why: no draft-vs-draft comparison (evidence 4). I H, E S (after B1/F1).
- **F4 Keep-best and deterministic baseline.** Always build the deterministic draft first; keep a
  model edit only when the label-free self-score (B1 + D1 + coverage) improves; `finish` delivers
  the best draft, not the last. Why: evidence 3-4; deterministic arm made 13 correct vs 9 (H2H).
  I H, E M, C down. Test: no round case ends worse than its first draft.
- **F5 Pre-finish checklist (warnings).** Each section: coverage >= 90 %, not grid, fair with
  neighbours, ink-fit ok. Shown to the model and stored for the person. I M, E S.
- **F6 Cheap critic request.** One extra request per draft with only the F1 overlay: "name the worst
  section and why". Feeds A5's plan. I M, E S, C up slightly.

## G. Evaluation and data

- **G1 Digest scores drafts.** `round_digest.py` reads `score.json`, prints gate result, per-section
  RMS, source label per section (traced/authored), STEP count, cost per draft; stop calling drafts
  "failed" (evidence 6). I M (enables all), E S, C 0.
- **G2 Mixed 4-case round set.** Fixed set: DTMB L0, Ship-D separate L2, Ship-D overlay L0, Ship-D
  overlay L2. Why: all W17b-W18c rounds are DTMB; overlay is the weakest (H2H). I M, E S.
- **G3 Section-panel unit set.** Panels with known traps (grid line, fragment, bulb, duplicate
  overlay stroke) and truth curves; tests tools without the LLM. I M, E M, C 0.
- **G4 Replay with new tools.** Re-run recorded decisions against new tool code, no provider cost,
  to check tool-result changes before a live round. I M, E M, C down.
- **G5 Oracle ablations per round.** Score first draft, best draft and last draft for each case.
  Shows whether the loop helps (evidence 3-4). I M, E S.
- **G6 Real drawings round.** ALMA/HAER sheets, qualitative, 4 cases. I M, E M.
- **G7 New held-out split before any claim.** v2 is spent; v3 is a later check. I L, E M.
- **G8 Harder factory levels.** Hand-drawn style, text clutter, broken lines. I L, E M.

## H. Cost and speed

- **H1 Cost per correct draft as the headline metric.** $0.08 -> $0.24 per draft came from long runs.
  I L, E S. (A2-A4, A11 do the work.)
- **H2 Prefix-cache check.** Confirm cache hits on the stable system + tools prefix (LOOP §2) from
  receipts; fix ordering if low. I L, E S, C down.
- **H3 Image diet.** Only the panel in focus at full resolution; others as ids (`recall_view`).
  I L, E S, C down.
- **H4 Use the early-stop round runner** (`tools-run-round`). I L, E S, C down.
- **H5 Cheap model for routine steps.** Deterministic actions (inspect, select, build) need no model
  call; let the controller run them as harness steps. I L, E S, C down.

## I. App and review UX

- **I1 Section source map.** Per section: traced / repaired / interpolated / ai_inferred /
  ai_corrected, with ink-fit score; click to accept or revert. I M (human), E M.
- **I2 "Fix this section" by the person.** 2-3 clicks on the drawing become `follow_ink` hints.
  I M, E M.
- **I3 Show the F1 overlay in review.** I M, E S (after F1).
- **I4 Cost meter and "finish with best draft" button.** I L, E S.
- **I5 Verify a real AI run from the desktop app** (open, CONTINUATION_STATUS 13:35). I L, E S.

## J. Longer term

- **J1 Few-shot episodes from solved drawings.** Store short solved section episodes (panel crop,
  good tool sequence) and retrieve 1-2 per case. I M, E M, C up.
- **J2 Stroke classifier.** Small vision model or classical classifier on factory panels: hull /
  grid / text / fragment, per stroke. I M, E L, C down.
- **J3 Ensemble only for disputed sections.** Two cheap models vote on which tag is the hull. I M,
  E M, C up slightly.
- **J4 Subagent per section.** Short-context loop per section; a coordinator assembles and fairs.
  I M?, E L.
- **J5 Self-play data.** Factory drawings + LLM runs; good runs become few-shot or fine-tune data
  (dev hulls only). I M, E L.
- **J6 Silhouette fit.** Optimise a parametric hull to the ink of all three views (distance-transform
  loss); the model picks hull strokes and starting form. Strong accuracy, but code writes geometry:
  keep it as a model tool, not a replacement. I H?, E L.
- **J7 Fine-tune DeepSeek-class model on section reading.** Only when J5 gives enough episodes.
  I M?, E L.

## Top 10: do next (ranked by impact per effort, within the principles)

| # | Idea | I/E | Why first | 4-case test |
|---|---|---|---|---|
| 1 | A1 repair model output | H/S | L2 dies on `notes_limit` in every run | DTMB L0-L3: 0 output-refusal ends |
| 2 | A2+A3+A4 edit budget, soft stop, 80-request cap, best-draft finish | M/S | 166 s09 calls, 162 identical; $0.24/draft | <= 80 requests, <= $0.10/draft, drafts kept |
| 3 | G1+G2 digest scores drafts; mixed round set | M/S | Measure every later idea; DTMB-only rounds | Digest shows gate and per-section RMS |
| 4 | B1 ink-fit numbers per section | H/M | Model cannot quantify "inboard" | L0 s09 converges in <= 5 calls |
| 5 | F4 deterministic baseline first, keep-best | H/M | L0 near gate; first draft never compared | No case ends worse than its first draft |
| 6 | D1 cross-station fairness outliers | H/S | One section decides L0; 617-L3 s01 | Each bad section named in warnings |
| 7 | B2 `follow_ink` + B3 `extend_trace` | H/M | 27 partial strokes; authored drift | Section coverage >= 95 % |
| 8 | F1+F3 reprojection overlay and draft scoreboard | H/M | 3D renders do not show ink mismatch | Worst section fixed in <= 3 calls |
| 9 | C1 grid mask (merge `w18-stroke-discovery`) | H/M | Grid lines in 7/7 wrong drafts | 0 grid-line sections in drafts |
| 10 | C2 overlay nesting/side rules, one stroke per station | H/M | LLM overlay 0/144 built | Mixed round overlay cases: 0 shared strokes |

Order rule: 1-3 are happy path and measurement; 4-8 give the model numbers to converge on; 9-10 fix
reading. Run one 4-case round per item (or per pair), and the dev24 only after >= 3 drafts.

## Avoid (conflicts with principles or evidence)

- **New refusals or gates** (refuse grid lines, refuse low coverage, refuse a replaced trace): breaks
  the happy path. Use warnings and better candidates (W18D, founder).
- **Chooser-only tuning of `candidate_score`**: an oracle chooser barely helps; the catalog lacks the
  right curve (DDA §1, fix 5).
- **Campaigns before rounds**: no 24-case or sealed run until a 4-case round gives >= 3 drafts; never
  tune on sealed v2/v3.
- **Provenance machinery now** (covered-event hashes, replay identity, `unresolved_ids`): deferred
  by founder (LOOP §0).
- **More prompt prose for rules the code enforces**: W18b cut the prompt to 1,368 characters; move
  detail to tool results.
- **Bigger or ensemble models on every request**: cost up many times with no measured gain; use only
  for disputed sections (J3) after a round shows value.
- **More free-form `propose_section` without numbers**: evidence 1 shows it loops; add B1/B2 first.
- **Raising extraction budgets globally**: catch and continue instead (DDA §2); budgets cost time.
- **Fine-tuning now**: too few solved episodes; do J5 first.

## Resume point

Next action: brief item 1 (A1) and item 2 (A2-A4) as one W18d change on `w17-llm-progress`, run the
DTMB round, then G1/G2. Check `work/w17/w18c-dev24.log` result first (running when this was written).
