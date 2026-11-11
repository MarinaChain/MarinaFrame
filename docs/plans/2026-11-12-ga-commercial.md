# GA reading for commercial ships: method, exam protocol and results (lane U, 2026-11-12)

Status: development done on the 14 development ships; code frozen at the commit that adds this
file's "Frozen" section. The holdout is scored once by the evaluator lane, not by this lane.

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
   accommodation deck plans first, then diagonal, then the longest; at most 48 per ship. Each
   crop reaches 3 glyph heights beyond its blob, is turned level and enlarged (at most 4x, the
   investigation tools' `MAX_ZOOM`, at most 1,024 px) into a numbered cell of a contact sheet
   (up to 8 cells, 6 sheets per request). The model returns the space labels printed in each
   cell (several in a dense cell). Each label becomes a `read` space whose source region is its
   crop's sheet box. A fine-pass label counts as a hold, hatch, crane, cargo tank or slop tank
   only when its text says so (HOLD, HATCH, CRANE, C.O.T./C.T./CARGO TK, SLOP); otherwise it is
   an other space or tank (`fine_kind_not_in_text` check).
5. **Counts with cross-view check (code).** A count is kept only when (a) the model gave a value,
   (b) no single view shows more differently numbered spaces of that kind than the count (views
   write tanks differently, "1 (P&S)" in the profile and "1P", "1S" on the tank top, so labels
   are never pooled across views), and (c) every view in which the coarse pass listed two or
   more numbered spaces of the kind ends at the same highest number (profile up to No.5 and tank
   top up to No.4 contradict; a view that misses a label in between does not; fine-pass labels
   do not decide where a view ends). Otherwise null with the reason.
6. **Provenance.** Every particular, count, view and space carries a `source-record/v1`
   (docs/SOURCE_RECORD.md): `read` with its sheet region, `guessed` with its input region, or
   `unknown` with the reason.
7. **App.** `ga_commercial read --app-task DIR` writes a run folder (`state.json`,
   `domain/state.json` naming the GA as source page, `ga_reading/`). The app view gains
   `ga_reading` (`app/core/src/ga_reading.rs`, records re-checked); the 3D pane shows the GA panel
   (`app/ui/js/ga_panel.js`): particulars, counts, spaces by kind with Read / Best guess / Not read.
   Pointing at or focusing a row shows its region on the GA in the drawing pane
   (`provenance.js` source view).

## Model, transport and budget

- **Model arm: Claude Sonnet 5.5 only** (`claude-sonnet-5-5`). It is one setting (`--model`,
  default in `ga_commercial.MODEL`) passed to `marinaframe vision-request --model`. The controller
  refuses every model for `ga_reading` and `ga_labels` that is not on the Claude subscription
  transport (`vision::request_model`). A later arm (Opus, then Fable, only by a later decision) is
  a `--model` value plus one row in the controller's model allow-list (`models::MODELS`).
- **Transport:** the `claude` CLI on the subscription, through the Rust provider worker
  (no tools, no MCP, no session file). Every request has a request file, a receipt and the raw
  response body (`<out>/<case>/provider`, `<out>/<case>/fine/labels-N-provider`).
- **Budget per ship:** 1 coarse request + at most 2 fine requests (48 crops / 8 per sheet /
  6 sheets). The controller retries only HTTP 429/502/503/504, at most 3 attempts.
  `batch --max-requests N` stops before a case once N requests were sent; requests of a failed
  case still count (read from its receipts). Holdout budget: **27 requests** (9 cases x 3).
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
  --max-requests 27 --out $W/holdout-run --binary target/release/marinaframe \
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

## Open issues (for the next step)

1. Space list coverage: about 100 labelled spaces per round are still missing across 14 ships
   (mostly rooms; some ballast and fuel tanks). The fine pass reads at most 48 blobs in 2
   requests per ship.
2. Cut labels remain on long letter-spaced diagonal labels; a source region is the crop box, so
   hover shows the whole label, but the text can be partial.
3. The model sometimes types a cargo tank as `other_tank` in the fine pass; code does not
   promote kinds from text.
4. Definitions to confirm with the PM: a centreline slop holding tank in the slop count; holds
   numbered with A/F halves (4A, 4F) as separate holds.
5. The particulars-table path has not seen a real table image.
6. Fable 5.2: `claude -p --model claude-fable-5-2` answers `unrecognized_model` on this machine
   (2026-11-12); `fable` resolves to `claude-fable-5-1`. The product arm is Sonnet 5.5 only.

## Resume point (step 3 of the development loop)

Done: two Opus/Astra cycles. Next (PM): a Fable 5.2 agent reviews and fixes in this worktree with
the evidence package `work/ga-internal-23/review/round-2/` (per ship: view crops with boxes and
`answers.txt`; `index.json`; Astra findings `astra-*.txt`). Then this lane checks its changes
(make test-quick, a development batch, diff review), adds the "Frozen" section and commits it;
only then does the evaluator run the command above. Do not run the holdout before that.
