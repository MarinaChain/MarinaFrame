# GA reading for commercial ships: method, exam protocol and results (lane U, 2026-11-12)

Status: development on the 14 development ships; **not frozen** (the PM decides when; the code is
then frozen at the commit that adds this file's "Frozen" section). The holdout is scored once by the
evaluator lane, not by this lane.

Why: HJ Shipbuilding / J.Ocean want "GA AI" (docs/POSITIONING.md); pilot idea: AI-assisted
preparation and checking of one GA revision for a tanker.

## Data rules (hard)

- Test pack: `work/ga-internal-23/` (git-ignored, partner data). `SPLIT.json` lists 14
  `development_cases` and 9 `holdout_scored_cases`.
- This lane opened `inputs/<case>_*` for development cases only. It never listed, opened or
  hashed anything under `sealed/` and never opened a holdout image.
- Nothing per ship goes into git: no images, crops, values, labels, readings or screenshots.
  Only code, tests on synthetic fixtures, and aggregate numbers in this file.
- The user approved sending these drawings to Claude (subscription) for model calls, and to
  GPT-6 Astra (direct Codex) for development review of development ships only.

## The exam (as summarised by the PM from the sealed README)

1. Particulars: from a particulars-table image read LOA, LBP, breadth, depth in metres.
   Unreadable gives null, never a guess. The value printed on the drawing is the truth.
2. GA structure counts on bulk carriers: cargo holds, main cargo hatches, cargo cranes
   (0 is a valid count).

Wrong answers and abstentions are reported separately.

## Method

Code: `src/vessel_reconstruction/ga_commercial.py` (coarse pass, interpretation, counts, app run
folder, command line), `src/vessel_reconstruction/ga_labels.py` (fine pass),
`rust-control/src/ga_reading.rs` (model contracts), `scripts/score_ga_exam.py` (scorer).

1. **Images (code).** The GA sheet goes as a reduced overview plus up to 5 overlapping tiles
   (15 % overlap), each within the provider limits (2,048 px a side, 1 Mpx, 1 MiB; all images of
   a request at most 1.4 MB, else 16 grey levels, then smaller scales). A particulars-table image
   is one more image; a case with a table and no GA sends the table alone (tiled when large).
2. **Coarse pass (model, purpose `ga_reading`).** One request. The model names the drawn views
   (profile, deck plans, tank top, accommodation decks, table) with bounds; returns the printed
   text of each particular (never a converted number); lists holds, hatches, cranes, tanks, engine
   room, accommodation decks and other spaces with a box in pixels of the attached image and
   `read` (printed label) or `guessed` (outline only); and gives counts as value with evidence or
   missing with a reason. Numbered holds, hatches, cargo and slop tanks are listed once per view
   where their label is printed. Reasoning is on (`--effort high`).
3. **Code checks.**
   - Boxes map back to sheet pixels; a box on blank paper (ink share < 0.2 %) is dropped.
   - Particulars are parsed by code (`particulars._LENGTH` units: m, mm, cm, ft-in; tonnes for
     deadweight). No unit printed (on the value or in the heading) gives null. A comma that can be
     decimal or thousands is resolved only when exactly one reading is plausible for the field;
     otherwise null. LBP above LOA nulls both.
   - A faulty item (unknown image, box off the image, unknown kind) is refused alone and listed in
     `checks`; a faulty count or ship type refuses the reply (then every value is null).
4. **Fine pass (code finds, model reads, purpose `ga_labels`).** Code finds text blobs: glyph-sized
   ink components (5-40 px, aspect at most 5:1; dashes of broken lines are longer) joined across
   gaps up to one glyph height in any direction; the direction of a blob comes from its glyph
   centres (turned level only when the centres are clearly one line, spread ratio 12, and 8-60
   degrees off level). Blobs that no coarse space or particular explains are kept: blobs outside
   accommodation deck plans first, then diagonal, then the longest. Pieces of one letter-spaced
   label on one text line (gap up to 5 glyph heights, directions within 15 degrees) are joined
   into one blob first. There is no fixed number of crops: requests go out until every kept blob
   is read, up to the request ceiling of the ship (below). Each
   crop reaches 3 glyph heights beyond its blob, is turned level and enlarged (at most 4x, the
   investigation tools' `MAX_ZOOM`, at most 1,024 px) into a numbered cell of a contact sheet
   (up to 8 cells, 6 sheets per request). The model returns the space labels printed in each
   cell (several in a dense cell). Each label becomes a `read` space whose source region is its
   crop's sheet box. A fine-pass label counts as a hold, hatch, crane, cargo tank or slop tank
   only when its text says so (HOLD, HATCH, CRANE, C.O.T./C.T./CARGO TK, SLOP); otherwise it is
   an other space or tank (`fine_kind_not_in_text` check). In both passes a label that names its
   kind gets that kind when the model gave a general one (`ga_labels.PROMOTIONS`: "NO.4 C.T.(P)"
   is a cargo tank, "NO.9 H O L D" a cargo hold, W.B.T. / A.P.T. a ballast tank, F.O.T. / H.F.O. a
   fuel tank, SLOP a slop tank); a hatch is never promoted (an access hatch is not a cargo hatch).
5. **Counts with cross-view check (code).** A count is kept only when (a) the model gave a value,
   (b) no single view shows more differently numbered spaces of that kind than the count (views
   write tanks differently, "1 (P&S)" in the profile and "1P", "1S" on the tank top, so labels
   are never pooled across views), and (c) every view in which the coarse pass listed two or
   more numbered spaces of the kind ends at the same highest number (profile up to No.5 and tank
   top up to No.4 contradict; a view that misses a label in between does not; fine-pass labels
   do not decide where a view ends). Otherwise null with the reason.
   On a bulk carrier, holds and hatches that differ are listed (`holds_and_hatches_differ`), not
   refused.
6. **Provenance.** Every particular, count, view and space carries a `source-record/v1`
   (docs/SOURCE_RECORD.md): `read` with its sheet region, `guessed` with its input region, or
   `unknown` with the reason.
7. **App.** `ga_commercial read --app-task DIR` writes a run folder (`state.json`,
   `domain/state.json` naming the GA as source page, `ga_reading/`). The app view gains
   `ga_reading` (`app/core/src/ga_reading.rs`, records re-checked); the 3D pane shows the GA panel
   (`app/ui/js/ga_panel.js`): particulars, counts, spaces by kind with Read / Best guess / Not read.
   Pointing at or focusing a row shows its region on the GA in the drawing pane
   (`provenance.js` source view).

## Counting definitions (decided by the PM, 2026-11-12; each is a setting)

| Setting (`ga_commercial.DEFINITIONS`) | Default | Rule | Other value (CLI flag) |
|---|---|---|---|
| `split_holds_are_separate` | true | A cargo hold is a cargo space that transverse bulkheads separate and that has its own main hatch. "No.4A" and "No.4F" are two holds when a bulkhead separates them and each has its own hatch; one hold when they are one space with one label or hatch. | `--one-hold-per-number`: halves of one number are one hold |
| `slop_holding_tank_is_slop` | true | A tank is a slop tank only when its label says SLOP, also "SLOP HOLDING TK" on the centreline. Residue, waste-oil, sludge and other tanks are not. | `--slop-holding-tank-not-slop` |

The sentences go to the model in the request context (`context.definitions`, built by
`definition_sentences`), with: "on a bulk carrier holds and main hatches are usually equal; when
your counts differ, look again". Code counts by the same rule (`_count_key`, `label_kind`). The
settings of a run are recorded in `ga_reading.json` (`definitions`).

## Measured from the frame scale (for the arrangement step; never an exam answer)

Code: `src/vessel_reconstruction/ga_scale.py`; model contract `ga_scale` in
`rust-control/src/ga_reading.rs`. Run with `read --measure`, `batch --measure`, or
`measure --reading ga_reading.json --ga IMAGE --case ID` on an existing reading. Up to seven more
requests a ship; **off by default**, so the exam run is unchanged.

1. **Scale request (model points, code measures).** Images: the profile, the upper deck plan and
   the tank top plan in high-resolution parts (6 images). The model gives the place of every
   printed frame number, of "A.P." and "F.P.", of every printed frame spacing and of every drawn
   change of spacing, and named places: hull aft end, hull fore end, base line, upper deck at
   side at mid-length (profile); centreline and both shell sides (plan).
2. **Frame table (code).** Printed spacings are parsed (`800 MM`, `0.70`, `3,200 mm`; range
   300-5,000 mm; a unitless value below 10 is metres). The range with the most frame numbers
   gives pixels per metre; each change of spacing is put on a whole frame from the frame numbers
   next to it. Frame numbers out of order are left out. Then pixels are fitted to metres on every
   view that has frame numbers (Theil-Sen, then least squares without outliers). The scale is
   **not established** (every measured value null, with the reason) when: no spacing is printed;
   a range of the scale has frame numbers but no spacing; fewer than 4 numbers fit; more than a
   third are outliers; every number of one spacing range is off the fit (a misread spacing makes
   the other ranges fit and leaves that range out); or the fit error is above one frame width. A plan without frame numbers
   takes the profile's scale only when its hull is drawn as long as the profile's hull (2 %).
3. **Principal dimensions** (`measured.{lbp_m,loa_m,breadth_m,depth_m}`): status
   `measured_from_scale`, `uncertainty_m`, `method`, a `source_record` with the pointed regions
   and the frame scale. LBP: frame 0 to the F.P. mark (null when F.P. is not marked or the A.P.
   mark is not at frame 0). LOA: hull end to hull end in the profile. Breadth: shell to shell in
   a plan. Depth: base line to the upper deck **at side, at mid-length** (the pointed place must
   lie in the middle half of the hull). **A depth is `measured_from_scale` only when it passes
   the check against the tops of the spaces boxed below the deck in the profile:** at least one
   such top exists and none is higher than the deck line (a deck line far above them is kept and
   flagged "not confirmed": topside tanks above the holds). A deck line that no boxed space can
   check is null (`depth_not_checked`). A deck line below a space top is never used: the depth
   is then the median cargo-space top when the cargo spaces agree, else null.
   **A substituted value is never `measured_from_scale`:** when the pointed line lies below the
   tops, or a rail or camber height (up to 1.5 m) above at least 3 cargo spaces that agree, or
   when no deck line was pointed amidships and another space or the lowest deckhouse tier ends at
   the cargo-space tops, the depth is the median top with status `derived_from_space_tops`, and
   the record keeps `pointed_depth_m` and the `reason`. It is an
   estimate; a consumer must not check it against the same space tops. Sanity bounds on
   LBP/LOA, L/B and B/D refuse a set that cannot be a ship.
4. **Extents request.** Images: whole views. For each read space with a known label place the
   model boxes its drawn boundary (`outline`) or places a box from the label (`uncertain`). The
   label place is given in pixels of the image actually sent (an image can be sent smaller than
   planned to fit the request size).
   Code gives `spaces[].extent`: `frames` (nearest frame), `x_m`, `z_m` (profile) or `y_m`
   (plan; port positive, from the bow direction), `side` (from the label, else from y), and a
   status per axis: `measured_from_scale` for `outline`, `guessed` for `uncertain`.
5. **Arrangement input.** `ga_arrangement_input.json` (schema of docs/GA_ARRANGEMENT_INPUT.md on
   lane W): particulars are the printed value when there is one, else the measured one with its
   status; `frames.spacings`; one entry per physical space (the views of one space are joined:
   x and z from the profile, y from the plan; a numbered space is matched by kind, number and
   label family). A "(P&S)" pair is two tanks: boxed on one side, the other is its mirror (y
   `guessed`); boxed across the centreline, it is split there; without a plan, one tank each
   side. Two entries with the same box are one space (the other is listed in `dropped`).
   **Overlap rules** (`resolve_overlaps`, after the depth check; lane W, round u4r/u6: holds lost
   most of their volume to boxes drawn over them): a box that takes in a labelled neighbour ends
   at it when the neighbour is a strip at one of its edges (a double-bottom tank under a hold),
   else its axes become `guessed`; a tank printed for the sides that is drawn over a cargo space
   in the profile is a projection and gets no extent unless a plan gives its breadth; plan boxes
   that hold each other's labels get a guessed y; a room seen only on the deck plan over a cargo
   space gets no extent (its height is not known).
   **Fragment labels** (`drop_fragments`, after the fine pass): a label with no words besides
   "NO", an unclosed parenthesis, a single cut letter after the number, a last word that is the
   start of a longer word on the sheet, a single word printed only inside longer labels, or an
   untyped piece read where a longer label is printed is not a space; it is listed in `checks`
   (`fragment_label_dropped`) with its reason. A fitting or an opening (ladder, gangway, davit,
   boat, winch, opening; also a last word cut inside one of these words) and a lone system word
   without its room noun ("FOAM" without "ROOM") are not spaces either.
   **Outboard boxes:** a box whose breadth lies mostly outside half the moulded breadth loses its
   extent (`extent_withheld`); nothing outside the hull is a space.
   **Deck equipment top-up:** cranes and hatch covers still without an extent after the extents
   requests get one more request (`extents-deck`), so that they are not lost when the spaces
   fill the requests.
   **Boxes over a label without a box** (review round 4): the overlap rules above compare two
   boxes; a measured box can also hold the label of a space that has no box (a store above a
   peak tank, a residue tank beside a slop tank). One more request per ship (`extents-redraw`)
   asks for those boxes again and names the labels each must leave out. A redrawn box is kept
   only when it holds none of them, still holds its own label, and keeps at least 60 % of the
   first box's area (smaller cuts were boxes cut to strips to avoid a label printed over the
   space). Otherwise the first box stays with guessed axes and a check entry.
   **Guessed boxes** (lane W, round u6r3): a box guessed on every axis that covers a cargo space
   (missing y and z filled as the arrangement step fills them) loses its extent. A box against
   the shell (a side tank beside a cargo box drawn to the shell) may take at most 15 % of a
   cargo space; such a box with no height drawn in a profile goes in the upper 30 % of the depth
   (top-side and wing tanks under the deck), or loses its extent when its label names a lower
   tank (double bottom, hopper). Hatches and cranes stand on the deck and are not counted. A
   hold or centreline space boxed off the centreline (|y_min + y_max| > 10 % of B) is centred
   with the same breadth and its y becomes guessed. A label of the same kind inside a box (a
   hatch-cover note in a hatch box) is part of that space, not a neighbour. A short untyped
   label (four letters or fewer) keeps a guessed box only up to twice its label box in each
   direction. W's gate fails a box guessed on every axis that breaks these limits.
   Deck names ("UPPER DECK"), notes ("FOLDING TYPE"), access hatches ("A/H"), and an untyped
   label that is a numbered tank read without its number are not spaces.
   **Re-read of cut labels** (PM priority 3): a label dropped as cut (an unclosed parenthesis, a
   cut word, the start or end of a longer label) is read once more from a wider crop (6 glyph
   heights more on every side, in the direction of the first crop), only with the requests the
   ship has left under its ceiling of 6 (coarse and fine passes together); a whole label joins
   the spaces as in the fine pass and the fragment rules run again. Nine of the 14 development
   ships use the whole ceiling already, so it reads labels on the others only.
   **Labels from a shared crop** (round u8): several labels read from one crop of the fine
   pass share its region, so the place of each is not known; they used to be left out of the
   extents requests (457 read spaces on the 14 ships, 48 of them fuel tanks). They are now asked
   with the crop as `near` and the label text, in requests of their own after the labels with a
   known place (mixed in one request, the model marked most boxes "uncertain": round u9n), and
   get no label place for the overlap rules.
   **Spacing chosen by the fit** (PM, round u9n2): when the frame numbers of a range contradict
   its printed spacing, the spacing they show is taken if it is a standard spacing (500-1000 mm
   in steps of 50) or another value printed on the scale, within 3 % of what the numbers show,
   and every other candidate is off by at least 5 % and twice as much; the two halves of the
   range must show one spacing (a range with an undrawn change is refused). The span is marked
   `chosen_by_frame_number_fit`. Otherwise the scale is refused as before. On the round-u9n2
   ship the numbers show 782 mm, between 750 and 800 (2.2 % and 4.3 %): not clear enough, so it
   is still refused.
   **Coverage warnings:** the gate reports a ship whose other spaces have extents but whose fuel
   or ballast tanks have none as a warning, not a failure (the fine pass reads different labels
   from run to run).
   **Local frame spacings** (review round 4): a spacing printed for one frame inside a range of
   another ("1200" between close bulkheads in a range of 800) is a one-frame interval of the
   table when the frame numbers around it show the extra length; otherwise the scale is refused
   as before. The scale prompt asks for such texts; not yet run live.
   **Gate** (`arrangement_gate`, `scripts/ga_arrangement_gate.py`): the arrangement step's
   checks as a regression check of each round: no space left without volume after smaller
   spaces are cut out, no fragment label, no cargo space losing more than 58 % (round s3b).
6. **Exam guard.** `ga_reading.json` `particulars` holds printed values only. The scorer takes a
   particular only when its status is `read` (test
   `test_a_measured_value_is_never_an_exam_answer`).

## Model, transport and budget

- **Model arm: Claude Sonnet 5.5 only** (`claude-sonnet-5-5`). It is one setting (`--model`,
  default in `ga_commercial.MODEL`) passed to `marinaframe vision-request --model`. The controller
  refuses every model for `ga_reading`, `ga_labels` and `ga_scale` that is not on the Claude subscription
  transport (`vision::request_model`). A later arm (Opus, then Fable, only by a later decision) is
  a `--model` value plus one row in the controller's model allow-list (`models::MODELS`).
- **Transport:** the `claude` CLI on the subscription, through the Rust provider worker
  (no tools, no MCP, no session file). Every request has a request file, a receipt and the raw
  response body (`<out>/<case>/provider`, `<out>/<case>/fine/labels-N-provider`).
- **Budget per ship (adaptive, PM decision 2026-11-12):** 1 coarse request, then fine requests
  (up to 72 crops each: up to 12 per sheet, 6 sheets) until every kept text blob is read, with a ceiling of
  **6 requests a ship** (`ga_commercial.MAX_REQUESTS_PER_SHIP`, flag `--max-requests-per-ship`).
  Blobs beyond the ceiling are counted (`passes.fine.crops_not_read`). The controller retries
  only HTTP 429/502/503/504, at most 3 attempts. `batch --max-requests N` stops before a case
  once N requests were sent; requests of a failed case still count (read from its receipts).
  Holdout budget: **54 requests** (9 cases x 6). `--measure` adds up to 7 requests a ship (up to
  3 scale attempts and up to 4 extents requests of 20 spaces) and is not part of the exam run.
- **Usage recorded per ship:** `ga_reading.json` `usage` (requests, tokens, `observed_cost_usd`,
  CLI `list_cost_usd`) and `passes` (coarse images; fine text blobs, crops, answered, spaces
  added, requests); `batch.json` sums them.

## Scoring (fixed before any holdout run)

`scripts/score_ga_exam.py --predictions OUT_DIR --answers ANSWERS [--out score.json]`

- Predictions: `OUT_DIR/<case>/ga_reading.json`; fields `particulars.{loa_m,lbp_m,breadth_m,
  depth_m}.value`, `counts.{cargo_holds,cargo_hatches,cargo_cranes}.value`.
- Answers: JSON `{case: {field: value or null}}` or CSV with a `case` column; aliases LOA, LBP/LPP,
  B/breadth/beam, D/depth, holds, hatches, cranes. An absent field is not scored; null,
  "unreadable" or "-" expects an abstention.
- Particulars: correct when |prediction - answer| <= 0.005 m. Counts: correct only when equal.
- Null prediction = abstention, reported apart from wrong answers. An answer where an abstention
  was expected is wrong; an abstention there is a correct abstention.
- Output per field and per group (particulars, counts): scored, correct, wrong, abstained,
  correct_abstention, answered, accuracy_when_answered, correct_share; and per case.
- A case with no output folder counts as abstentions and is listed.

## What the evaluator runs (once, on the frozen commit)

```sh
make test-quick PY=.venv/bin/python        # or at least the GA tests below
cargo build --release --locked -p marinaframe-control
W=work/ga-internal-23
PYTHONPATH=src .venv/bin/python -m vessel_reconstruction.ga_commercial batch \
  --inputs $W/inputs --cases GA-002 GA-003 GA-014 GA-018 GA-124 GA-125 GA-201 GA-202 GA-203 \
  --max-requests 54 --out $W/holdout-run --binary target/release/marinaframe \
  --basis "GA internal test pack holdout, frozen evaluation; user approved Claude subscription calls"
.venv/bin/python scripts/score_ga_exam.py --predictions $W/holdout-run \
  --answers <answers file converted from sealed/> --out $W/holdout-run/score.json
```

Case files: `<case>_GA.*` is the GA; the one other `<case>_*` image is the particulars table. A
case folder with any other layout fails that case (reported in `batch.json`), it is not guessed.
If the sealed answers use other field names, convert them to the answer form above without
changing values; do not change the tolerance.

## Development results (14 development ships; no answers exist; aggregate only)

Per-ship values stay in `work/ga-internal-23/dev-runs/` (git-ignored). Checks are by eye against
the sheets (overlays of every box) and by the reviewers below; there is no truth file.

| Round | Requests (14 ships) | Requests per ship | Fine crops per ship | Tokens in / out | CLI list estimate | Observed cost |
|---|---:|---:|---:|---:|---:|---:|
| 1 (r6: coarse + fine, first count rules) | 40 | 2-3 | 15-48 | 357k / 102k | 3.39 USD | 0 (subscription) |
| 2 (r7: round-1 fixes) | 48 (42 + 6; budget stop tested) | 2-4, then capped at 3 | 11-48 | 458k / 100k | 3.83 USD | 0 |
| 3 (r9: Fable 5.2 review step; adaptive budget, definitions, joined labels) | 71 reading + 22 frame-scale | reading 2-6 (9 ships at the ceiling of 6; 3 strips need 2) | 14-167 | 901k / 271k (all 93) | 4.51 USD | 0 |

### Round 3 (r9, 2026-11-12; reading by Claude Sonnet 5.5, one batch)

- **Spaces:** 1,161 spaces listed on 14 ships (round 2: 683). Recheck of the 94 labels that the
  round-2 review listed as missing (label match by code, `work/` script; not a new review): 42
  are now in the lists, 52 are not (the same match finds 15 in round 2, 79 not). The 52 are on
  10 ships, most on 3 dense tanker sheets. Crops not read at the ceiling: 334 on 8 ships
  (accommodation cabins go last).
- **Exam fields on the 6 development bulk carriers:** the 4 full sheets with unchanged values
  keep them (holds, hatches, cranes). The hold strip now answers 8 holds (definition: 4A and 4F
  are two holds). One full sheet abstains on holds in this run (hatches 4 and cranes 3 are
  answered): the coarse pass did not list the last hold label of the tank top plan, so the views
  end at different numbers and rule (c) refuses. This is an abstention, not a wrong answer; see
  open issue 3.
- **Slop tanks:** the tanker with a centreline "SLOP HOLDING TK" now answers 3 (definition).
- **Counts changed against round 2 on other ships:** 2 counts answered that were abstained
  (hatches on a tanker strip and a container sheet), 2 not-applicable counts abstained on a
  container strip; no answered count changed its value except the two definition cases.

### Measured from the frame scale (development ships; aggregate)

Final code, scale pass on the round-3 readings (`work/ga-internal-23/dev-runs/final/`; per ship
the source run is in `SOURCES.json`):

| | Ships of 14 |
|---|---:|
| Frame scale established (frame table and pixel-to-metre fit) | 10 |
| LBP / LOA / breadth / depth measured | 10 / 9 / 9 / 9 |
| Depth derived from space tops (status `derived_from_space_tops`) | 0 in the final set (1 in an earlier run) |
| Ships with space extents | 10 |
| Spaces with an extent / with x measured from a drawn boundary / with x, y and z | 266 / 119 / 42 |

- Not established (null, with the reason): 2 single-plan strips print no frame spacing; 1 strip
  has no named view; 1 container sheet's frame numbers do not fit its printed spacings.
- Fit: 19-44 frame numbers a ship, error 0.4-2.7 px (sheet pixels; a frame is 6-30 px).
  Stated uncertainty 0.3-0.7 m on lengths and breadth, 0.3-0.6 m on depth.
- Checks by eye and by the drawing's own printed dimensions: on one bulk carrier the measured
  hold bulkheads give its printed hold lengths exactly, its LBP agrees with the printed
  dimension chain within 0.1 m, and a measured hatch length agrees with the printed one within
  0.05 m. There is no truth file for the principal dimensions.
- **Repeatability:** the same ship measured in 3 separate runs gives LBP within 0.6 m and
  breadth within 0.5 m. Whether the scale is established varies between runs on small print
  (8, 9 and 10 ships of 14 in three runs before the retry; the final code sends the scale
  request a second time when the first does not establish the scale).
- Found and fixed in development (lane W relays): a deck point under the poop (now: mid-length
  only), a deck line at the rail or centreline (now: replaced by the median cargo-space top with
  its own status when within 1.5 m above agreeing tops), an engine-room box under the poop used
  as a deck check (now: only spaces at mid-length).

- Exam fields on the 6 development bulk carriers: on 5 full sheets holds, hatches and cranes
  were answered in both rounds with the same values and agree with the drawings by eye (15 of
  15 answered, 0 abstained). The sixth sheet is a strip of the hold region: holds answered in
  round 1 and abstained in round 2, hatches and cranes abstained in both.
- Cross-view check: holds compared on 2 views on 4 ships in round 1 and 2 more after round 2;
  no contradiction.
- Particulars: no development GA prints a particulars table, so all 14 are null (correct
  abstentions). The particulars path is tested on synthetic fixtures only; the holdout has
  particulars-table images that this lane has not seen.
- Tankers (not in the exam): after the count-rule fix every tanker sheet answers cargo and slop
  tanks (round 1 refused 3 of 6 because labels were pooled across views).
- Fine pass: 11-54 spaces added per ship, mostly engine-room and service tanks from diagonal
  labels the coarse pass missed.

## Independent review (development ships only)

GPT-6 Astra through direct `codex exec -m gpt-6-astra --sandbox read-only -i ...` (checked first on
a synthetic image I drew: it quoted the text exactly). Each call: two ships, up to six view crops
with MarinaFrame's boxes drawn on, and MarinaFrame's extracted answers; it lists disagreements
with evidence. A second opinion to investigate, not truth. Package tool:
`scripts/ga_review_package.py`. 7 calls per round.

| Round | Findings | On answered exam fields | On abstained counts | Other counts | Label or kind | Missing spaces |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 144 | 0 | 3 | 0 | 31 | 110 |
| 2 | 133 | 0 | 1 | 1 | 38 | 93 |

Rounds 3 and 4 (overnight, on rounds u4r and u6; the package also draws the measured extents and
lists the measured values, and the reviewer checks them):

| Round | Findings | On exam counts | Extents | Measured values | Label, kind or missing space |
|---|---:|---:|---:|---:|---:|
| 3 (u4r) | 139 | 0 | 50 | 7 | 82 |
| 4 (u6) | 117 | 0 | 41 | 9 | 67 |
| 5 (u6r7) | 139 | 0 | 68 | 3 | 65 |
| 6 (u10r2) | 129 | 0 | 51 | 5 | 73 |

Round 5 (on u6r7, the redraw and guessed-box rules) found more extent issues than round 4, mostly rectangles where the drawn boundary slopes or tapers, boxes that still hold a neighbour, and hatch breadths above the printed size; the frame table finding repeats because u6r7 replays the scale replies of u6 (the local-spacing prompt runs first in u8).

Real after my check (round 3 and 4): extent boxes that take in neighbouring compartments (holds
down to the base line, one box for a pair, boxes across sloped boundaries); measured hatch
lengths 1-2 m above the size printed in the hatch; a frame table that misses short local ranges
the drawing prints (1,200 mm intervals); one F.P. mark the model gave in a plan only. Fixed:
pairs, tank families, hoist crane, F.P. on the profile; open: the rest (Resume point).

Checked by me and real: cut labels from the fine pass (both rounds), a cut label typed as a
counted kind on a bulk carrier (round 1), hose cranes typed as cargo cranes in the space list
(round 2), letter-spaced titles failing the kind check (round 2), missing tanks. Not acted on:
missing cabins, stores and other rooms (outside the required compartment list); the abstained
counts (abstention is allowed); one tanker slop count where Astra also counts a centreline slop
holding tank (definition question; tankers are not scored).

Fixes: round 1 - counts within one view, highest-number cross-view rule, wider glyph joining,
padded crops, kind check of counted kinds, accommodation blobs last, fine-request cap (2 per
ship). Round 2 - crops padded along the text line, crane kind rejects hose/provision/stores
cranes, letter-spaced words joined before the kind check, kind check also on coarse labels,
where a view's numbering ends comes from the coarse pass only (the fine pass reads only some
crops).

Round-2 fixes verified live on 3 ships (2 bulk carriers, 1 tanker; r8: 9 requests, 3 per ship,
list estimate 0.84 USD): long diagonal tank labels now read whole instead of cut after two
words; holds compared on 2 views on both bulk carriers; the hose crane is no longer a cargo
crane. Recount of round 2 with the final count rule (no new calls): exam counts unchanged;
every tanker sheet answers cargo and slop tanks.

## Fable 5.2 review-and-fix step (2026-11-12)

Input: `work/ga-internal-23/review/round-2/` (133 findings). What was changed, generally:

| Finding (round 2) | Change | Test |
|---|---|---|
| 93 missing labelled spaces | adaptive fine budget: requests until every text blob is read, ceiling 6 a ship; crops a reply leaves out are asked once more; diagonal crops cut to their text band (more cells a sheet) | `test_every_unexplained_blob_is_a_candidate`, `test_a_crop_that_a_reply_leaves_out_is_asked_once_more`, `test_a_diagonal_crop_is_cut_to_its_text_band` |
| cut labels ("NO. 5 W", "TK (P&S)", unnumbered W.B. TK) | pieces of a letter-spaced label on one text line are joined before cropping | `test_the_pieces_of_a_letter_spaced_label_are_one_blob` |
| cargo tank typed other_tank; "NO.9 H O L D" typed other_space; ballast and fuel tanks typed other | kind from the label's own words (`PROMOTIONS`), both passes | `test_a_label_that_names_its_kind_gets_that_kind` |
| slop holding tank; 4A/4F holds | definitions as settings (above) | `test_hold_halves_...`, `test_the_slop_definition_is_a_setting`, `test_the_definitions_go_to_the_model_...` |
| (new in round 3) a bare number beside the same number with sides counted as another tank; number token without the side printed in the label | `_number_with_side`; bare duplicates left out of the per-view count | `test_a_cut_label_without_its_side_is_not_another_tank` |
| (new in round 3) fragment "HOLD" typed cargo hold by the fine pass | a fine-pass hold or cargo tank needs its number | `test_a_fine_label_of_a_hold_without_its_number_is_not_a_hold` |
| (new) fine labels may complete a view the coarse pass listed | rule (c) reads them for such a view only | `test_a_fine_label_completes_a_view_that_the_coarse_pass_listed` |

No ship-specific rule or constant was added. The product model is unchanged (Claude Sonnet 5.5,
one setting). A new Astra review of round 3 was not run.

## Opus check of the Fable 5.2 step (2026-11-12, lane U)

The Fable step's WIP (frame scale, extents, definitions, adaptive budget, promotions) was reviewed
line by line for general rules, tests and honest statuses. Kept: all of it, except what is fixed
below. The exam path stays printed values only (`--measure` is off by default; the scorer takes a
particular only with status `read`). No ship-specific rule was found.

Regression found by lane W (rounds s4 and r9 against s3b: fewer space extents, depths lost or
unchecked) and its causes:

| Cause | Fix | Test |
|---|---|---|
| The extents request gave label places in the planned image size; images are shrunk to fit the request size, so places were up to 11 % off ("label positions do not match the drawing", model note) | places computed from the size of the image actually sent | `test_label_places_follow_the_image_actually_sent` |
| Asked for 71 spaces in one request, the model boxed 20 (43 of 43 in s3b) | extents in requests of 20 spaces, at most 4, holds and tanks first, then ballast and fuel tanks | `test_many_spaces_go_out_in_short_requests_holds_and_tanks_first` |
| A depth below a boxed space top was kept as `measured_from_scale` and flagged; a depth with no space to check it was kept | contradicted: the agreeing cargo-space top as `derived_from_space_tops`, else null; unchecked: null (`depth_not_checked`) | `test_the_depth_is_taken_amidships_...`, `test_a_depth_that_no_space_can_check_is_not_given` |
| A misread spacing range was accepted: the other ranges fit and the whole range was dropped as outliers (failing test in the WIP) | a spacing range whose numbers are all off the fit refuses the scale | `test_the_frame_numbers_check_the_printed_spacing_of_a_range` |
| A scale reply without hull ends crashed the batch | the frame table keeps the drawn scale ends | `test_a_scale_reply_without_hull_ends_is_measured_without_them` |
| A retried scale request repeated the same miss (tanker: a change of spacing not marked in 3 attempts) | the retry says why the previous reading was refused | `test_a_second_scale_request_can_establish_the_scale` |
| (round u2) A web-frame range of one frame has its spacing text printed beside it, in the next range, which then held two spacings: the scale was refused | a range with at most one frame number and no text takes the nearest text of a neighbour that holds two different spacings | `test_the_text_of_a_one_frame_range_printed_beside_it_belongs_to_it` |
| (round u3) Wing ballast tanks boxed 3.6 m above a deck line that six cargo-tank tops confirm made the depth null | when at least 3 cargo spaces agree and the pointed deck line lies at their top, other spaces boxed above it get a guessed height (`extent_above_the_deck`) and the depth stands | `test_a_tank_boxed_above_the_deck_that_the_holds_confirm_is_the_wrong_box` |
| (round u3) LBP or breadth lost because one run's scale reply left out F.P. or a shell side | the first extents request names the places and marks still missing; A.P./F.P. marks from that reply are used (on the profile, where the LBP needs them: round u6) | `test_places_the_scale_request_left_out_are_asked_for_and_used`, `test_a_perpendicular_mark_counts_only_on_the_profile` |
| (round u4) Cargo tanks boxed to the rail while a ballast tank ends at the pointed deck line: the depth was derived from the rail | when another space confirms the pointed line, cargo tops do not replace it (null, "boxes disagree") | `test_a_tank_boxed_above_the_deck_...` |
| (round u5) Cargo boxes one rail height above the pointed line: a derived depth from the rail | a gap of a rail height or less in that direction gives no depth (code cannot tell rail from deck) | `test_a_tank_boxed_above_the_deck_...` |
| (Astra round 3) Wing tanks of a "(P&S)" pair boxed on one side read as one space across the whole y range | the arrangement input gives two tanks, the boxed one and its mirror (y `guessed`) | `test_a_pair_boxed_on_one_side_is_two_tanks_in_the_arrangement_input` |
| (Astra round 3) Top-side and bottom ballast tanks with one number in one view: the second was dropped as a duplicate | a fine-pass label is the same space only with the same label family | `test_a_label_is_another_space_only_when_its_family_differs` |
| (Astra round 3) A hoist crane typed as a cargo crane | HOIST joins the crane words that are not cargo cranes | `test_a_hoist_crane_is_not_a_cargo_crane` |

## Open issues (for the next step)

1. Space list coverage: 52 of the 94 round-2 missing labels are still not listed (dense tanker
   sheets), and 334 crops were not read at the ceiling of 6 requests. Follow-up (out of scope
   on 2026-11-12, PM): an agentic zoom step, where the model chooses crops with parallel tool
   calls instead of code-chosen contact sheets.
2. Frame scale on small print: on 2 tankers with one-frame web-frame ranges (a long spacing
   between two printed numbers) the model sometimes misses a change of spacing; the scale is
   then refused. A retried scale request now says why the previous reading was refused (Opus
   check, below); a code fit of the change from the frame numbers alone was not built. One
   container sheet's numbers never fitted its spacings (not investigated on the sheet).
3. Count rule (c) (views end at different numbers) abstained once in round 3 where the hold
   count is clear on the sheet. The rule was kept: relaxing it after one development case
   could turn abstentions into wrong answers on the holdout. PM decision.
4. Extents: a box is `outline` (measured) or `uncertain` (guessed) by the model's own word; the
   ends are not snapped to detected bulkhead lines. y and z come from one view each, so only 42
   spaces have all three axes. Hull outline polygons (`hull_outline` of the arrangement input)
   are not produced.
5. (Closed in the Opus check) A contradicted or unchecked depth is no longer kept as measured.
6. The particulars-table path has not seen a real table image.
7. Fable 5.2: `claude -p --model claude-fable-5-2` answers `unrecognized_model` on this machine
   (2026-11-12); `fable` resolves to `claude-fable-5-1`. The product arm is Sonnet 5.5 only.

## Overnight rounds u1-u6 (2026-11-12, lane U; measurement pass, development ships)

Per round: reading and `--measure` on the 14 development ships, three parallel batches. Coverage is
compared per ship with round s3b (measured principal dimensions, spaces with an extent, and the
frame scale). Aggregate only; per-ship files stay in `work/`.

| Round | Requests | CLI list estimate | Ships with frame scale | Dimensions measured / derived (of 56) | Spaces with an extent | Ships below s3b on some item |
|---|---:|---:|---:|---:|---:|---:|
| s3b (reference) | - | - | 10 | 36 / 1 | 268 | - |
| u1 (Fable code + first fixes; one batch of 4 ships crashed) | 66 | 3.29 USD | 6 of 10 | 22 / 0 | 147 | (crash) |
| u2 (label places, short extents requests) | 119 | 5.90 USD | 9 | 35 / 0 | 455 | 3 |
| u3 (short web-frame range texts) | 124 | 5.78 USD | 10 | 36 / 0 | 473 | 4 |
| u4 (missing places named; cargo-confirmed deck) | 122 | 5.71 USD | 9 | 35 / 1 | 442 | 2 |
| u4r (u4 replayed through the u4 final rules) | 0 | - | 9 | 35 / 0 | 442 | 3 |
| u5 (stricter extents wording; pairs split; hoist crane) | 123 | 6.09 USD | 10 | 36 / 1 | 495 | 2 |
| u6 (shorter extents wording; label families; rail-gap depth rule) | 129 | 6.19 USD | 10 | 36 / 0 | 542 | 4 |

Ballast and fuel tanks listed on the 14 ships: 200 in u5, 234 in u6 (label families: two tank
families with one number in one view are no longer taken as one). Extent boxes marked by the model
as drawn boundary (`outline`): 214 in u4, 160 in u5 (a long list of exclusions in the extents
wording made the model unsure), 203 in u6 (shorter wording).

Observed cost is 0 in every round (subscription).

- Every measured depth passes the check against the boxed space tops; otherwise it is null or
  derived with its reason. `u4r` is u4 replayed through the final rules without new calls (one
  depth that the u4 rule derived wrongly from cargo boxes drawn to the rail is null there).
- The shortfalls move between ships from round to round: they are places or ranges the model
  points in one run and not in the next (an F.P. mark, a shell side, a misread spacing), not
  code that lost coverage. Replaying an earlier round's replies through the final code gives
  that round's coverage back (checked on two ships).
- Lane W tested u6 and refused it (round u6 trial in `work/ga-arrangement-u6`): holds still lost
  up to 89 % of their volume, fragment labels became spaces, and "(P&S)" cargo tanks were not
  split where no plan gave their breadth. Fixed (Method, step 5: overlap rules, fragments,
  pairs, same-box entries, tank matching across views) and replayed without new calls: `u6r`.
- **Gate on `u6r`: 14 of 14 development ships pass** (no space without volume, no fragment,
  largest cargo-space loss 0.25; the same gate on round s3b fails 11 ships). For lane W:
  `work/ga-internal-23/dev-runs/u6r/<case>/ga_arrangement_input.json`.
- Lane W tested u6r: accommodation ladders (outboard, no volume) were spaces, some fragments
  remained, and the cranes of one ship had lost their extents (they come last in the extents
  order). Fixed as general rules (fittings and openings, lone system words, cut dotted
  abbreviations, outboard boxes, deck-equipment top-up). Replay `u6r3`: stored u6 replies plus
  one live deck top-up request per ship that needed it (`u6r2`); no other new calls.
- **Gate on `u6r3`: 14 of 14 development ships pass**; the cranes have extents again. One known
  miss: a two-letter untyped tank label (two dotted letters) stays, because a general rule for it would also
  drop real two-letter tanks ("B.T."). For lane W:
  `work/ga-internal-23/dev-runs/u6r3/<case>/ga_arrangement_input.json`.
- Lane W tested u6r3: the tanker passes and is used; the bulk carrier failed because a short untyped tank
  label got a box guessed along a whole hold. Astra round 4 (on u6) also found boxes that take
  in spaces without a box (40 measured boxes in u6r3 held another space's label). Fixed by the
  rules in Method, step 5 (boxes over a label without a box, guessed boxes); W's gate also
  fails a box guessed on every axis over a cargo space.
- Round `u6r7`: stored u6 replies, the u6r2 deck top-ups, and one live redraw request per ship
  where a box held another label (`u6r5`; 7 ships, 7 calls; 15 boxes asked, 7 redrawn boxes
  kept). **Gate: 14 of 14 development ships pass**; measured boxes that hold another space's
  label 40 -> 3; fully measured extents 167 -> 160 (boxes that still cover a neighbour are now
  guessed). For lane W: `work/ga-internal-23/dev-runs/u6r7/<case>/ga_arrangement_input.json`.
- Lane W tested the bulk carrier on u6r7: guessed wing tanks became full-height columns in a
  hold, one hatch lost its box (a hatch-cover note inside it), and a hold boxed off the
  centreline was marked measured. Fixed (Method, step 5, guessed boxes) and replayed without
  new calls: **`u6r8`, gate 14 of 14 pass** (largest cargo loss 0.175). For lane W:
  `work/ga-internal-23/dev-runs/u6r8/<case>/ga_arrangement_input.json`.
- Live round `u8` (all rules up to u6r7, the local-spacing prompt; 126 Claude requests, then one
  ship again with 13 after a scale fix) replayed through the current code as `u8f`. **Gate: 14
  of 14 pass.** The container ship's frame table now has its four printed 1200 mm frames: its
  measured hold spans now equal the printed spans (they were 0.4 m short). Two fixes from this
  round: when the marks of earlier scale replies spoil a clean reply, that reply is read alone;
  the local frames are confirmed by the fit of all frame numbers of the range (one local frame is
  about the scatter of the numbers). Cranes and hatches whose box begins more than 1 m above
  the deck reach down to the deck (z guessed; lane W, round u6r8). Against s3b per ship: more
  spaces and extents on most ships; one ship has fewer spaces (accommodation rooms the fine pass
  did not read this time) and one lost its two fuel-tank extents (run-to-run variance); both are
  open.
- Live samples `u9s` (outlines; 4 ships, 45 requests) and `u9n2` (labels from a shared crop and
  the re-read of cut labels; 4 ships, 36 requests). Outlines: the model gave 26, the checks kept
  14 and dropped 11 with a reason (4 held another space's label); a kept outline follows a
  sloped boundary that the box could not (a forepeak along the stem, a cargo tank beside a
  tapered wing tank). Labels from a shared crop: extents per ship rose by about half on the
  ships with a scale (for example 41 -> 70); the depth stayed measured. The re-read used one
  request left under the ceiling on one ship and added 8 spaces. Gate: pass on all 8 ship runs.
  One ship lost its frame scale in u9n2: all three scale replies read a printed "800" as "600",
  which its frame numbers contradict, so the scale was refused (run-to-run variance in the
  reading of small print; the same ship read correctly in u8).
- Live round `u10` (outlines, labels from a shared crop, re-read, the fit-chosen spacing and
  coverage warnings; 141 Claude requests), replayed after two fixes as `u10r2`. **Gate: 14 of
  14 pass.** Fixes from this round: a numbered hold is one hold, whatever note follows its label
  ("(PORT USE W. B.)" was read as a port side and gave a second hold); profile-only readings of a
  space are checked against each other; "NO.I T." (a capital I for 1, then one letter) is cut.
  Extents rose on most ships (for example 20 -> 41 and 40 -> 63). Open: three ships have no
  measured depth in this round: the model marked all their hold boxes "uncertain", so the deck
  line could not be checked (run-to-run variance; one of them was measured in u9n2 with the same
  prompt). One ship has no fuel-tank extent (coverage warning).
- Astra round 6 (on u10r2; 8 calls, one repeated after a router error): 129 findings, none on the
  exam counts; extent findings 68 -> 51. Real and fixed: a 1200 mm spacing applied over four
  frames (a change drawn four frames past a one-frame "1200"): a short range between two drawn
  changes must now span its frames at its spacing, else the two changes are left out and its
  text is a one-frame spacing (`u10r3`, gate 14 of 14). Open, as before: rectangles across
  sloped boundaries, boxes over a store above a peak tank, hatch breadths above the printed
  size (the printed-size proposal), one hold box a frame short at a local frame.

## Proposal (not built; PM 2026-11-12): printed sizes as a check of extents

Astra rounds 3 and 4 found measured hatch lengths 1-2 m above the size printed in the hatch
(for example "15.47 x 20.40") and hold spans that differ from the printed dimension chain. A
check needs the printed text: an optional `printed_size` per extent in the `ga_scale` reply (the
text as printed, never converted), parsed by code (metres or millimetres) and compared with the
measured length and breadth; a difference above 0.5 m or 3 % would make that axis `guessed`
with a check entry. The geometry would not be replaced by the printed value. This changes the
model contract (Rust `ScaleReply`, CLI schema, prompt), so it waits for a PM decision.

## Outlines for sloped and tapered boundaries (PM decision 2026-11-12: approved, conditions)

Astra round 5 has 68 extent findings; most are rectangles where the drawn boundary slopes or
tapers (bow and stern tanks, hopper and top-side tanks, tanks beside the narrowing hull).

- **Contract** (`rust-control/src/ga_reading.rs`): an extent of the `ga_scale` reply may carry
  `outline`, 3 to 8 points [x, y] on its image, asked only for a space whose drawn boundary is
  not a rectangle. It is optional in the CLI schema; the strict parse still refuses unknown
  keys; an outline with too few or too many points or a point off its image is dropped alone
  (the box stays) and counted in `refused`. No extra request: the outline comes in the same
  extents requests (the per-ship ceiling and the exam budget are unchanged).
- **Checks** (`_outline_problem`): the outline is kept only when it lies inside its box (3 px for
  the line width), holds the space's own label and holds no other label of the view (a label of
  the same family, or a note of the same kind, is the same space, as for the boxes); otherwise
  it is dropped with a reason in `checks` (`outline_dropped`). An outline whose box the overlap
  rules changed (trimmed, guessed, a projection) is dropped too.
- **Status:** an outline is a trace by the model; its points are placed with the frame scale,
  but it has its own status `traced` and changes no axis status. The mirrored outline of the
  other tank of a pair is `guessed`.
- **Arrangement input:** an optional `outline_m` list per space extent; each item is
  `{"plane": "xz" | "xy", "points": [[x, z or y], ...], "status": "traced" | "guessed"}` (x
  and z from a profile, x and y from a plan, metres). It is given only when an outline was kept;
  a step that changes an axis (a pair split at the centreline, a centred off-centre space, a
  crane brought down to the deck) drops the outline of that plane. An input without
  `outline_m` is exactly as before (test, and the 13 replayed development ships are unchanged
  byte for byte). Lane W's builder ignores the field until W adopts it.

Text for `docs/GA_ARRANGEMENT_INPUT.md` (lane W's file, on lane W's branch; to apply when W
adopts the field):

> `extent.outline_m` (optional, list): traces of a boundary that is not a rectangle. Each item
> has `plane` (`xz` from the profile, `xy` from a plan), `points` (3 to 8 [x, z] or [x, y] in
> metres, in order) and `status` (`traced`, or `guessed` for the mirror of a pair). The points
> lie inside the extent's box. A builder that does not read `outline_m` builds the box as
> before.

## Resume point

Done: two Opus/Astra cycles; the Fable 5.2 step; the Opus check of it (regression found and fixed,
overnight rounds u1-u6, overlap and fragment rules replayed as u6r, fittings, outboard boxes and
deck top-up replayed as u6r3; redraw of boxes over labels, guessed-box rules and local frame
spacings as u6r7; side, off-centre and hatch rules as u6r8; live round u8 as u8f). **Not frozen; the exam was not run; the PM said not to freeze or prepare
the exam until told.** Next: a full live round (scale requests with the local-spacing prompt,
all extents rules) and its gate; Astra review; then recover spaces whose only label is a
fragment (a wider crop read again) if it fits the per-ship ceiling, boxes along sloped and
tapered boundaries, the printed-size proposal (above) if the PM accepts it.
To repeat a development round: `ga_commercial batch --measure --max-requests 65` on groups of
the 14 development cases; each `ga_reading.json` has `passes`, `frames`, `measured` and the space
extents, and `ga_arrangement_input.json` is beside it.
