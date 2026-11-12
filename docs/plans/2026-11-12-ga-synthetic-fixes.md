# Draft: synthetic GA reader fixes (G7, G8)

## Scope and fixed checks

Only public/synthetic data and code. No partner drawings, development-run folders,
sealed data or holdout data. No model calls. `engineering_approved` remains false.
Do not change thresholds, scoring, tank-fragment rules, breadth joins or other causes.

Evidence: `lane/ga-synthetic-run:docs/plans/2026-11-12-ga-synthetic-run.md`, causes 1–2.
The shared crane regex requires CRANE, so CR.1 becomes other_space; the fragment
pass can then treat CR as a prefix of CRANE. Both passes use this vocabulary.
The scale request tiles only padded view boxes, not the sheet header. Existing
local OCR returns word boxes and line IDs; it can locate spacing notes without a
provider request. OCR will locate crops only; the model still reads the value.

## Steps and acceptance checks

1. Add failing crane abbreviation tests. Extend shared cargo-crane vocabulary,
   preserve non-cargo crane exclusions and access-hatch handling. Check that
   complete crane labels retain their source boxes through fragment removal.
2. Add failing request-coverage tests. Locate printed spacing-note text locally;
   include uncovered note regions in the existing scale request, within six images.
   Keep note coordinates tied to an existing view for the unchanged scale parser.
   Check no-note/no-OCR behavior and retry coverage.
3. Generate synthetic sheets offline. Check note coverage and crane-label retention;
   no claimed model accuracy improvement without a live run.
4. Run focused GA tests and the required quick tier. Commit passing steps, push
   only lane/ga-synthetic-fixes, do not merge. PM owns development replay and live runs.
5. Remove this worktree's local target directory after delivery, if present.

## Design review

- Architecture: PASS. Reuse the optional local OCR reader and its sheet-pixel word
  boxes. OCR locates images only; the existing model and scale parser read values.
- Code quality: PASS. One note crop holds uncovered matching lines. Existing view
  IDs keep coordinate mapping and provenance unchanged.
- Coverage: PASS. Test abbreviations, non-cargo exclusions, access hatches, initial
  and retry crops, multiple notes, absent OCR/text and profile-free requests.
- Performance: WARN. Each scale attempt adds one local whole-sheet OCR pass. No
  new provider call. A found note reserves one image slot; spare slots go to views
  in existing order. No-note view tiling stays unchanged.

## Results

- G7 red: five abbreviation cases failed kind checks; after the vocabulary change,
  three still failed dotted-prefix fragment checks. Both causes now have tests.
- G7 focused vocabulary/labels/commercial suite: 143 passed. Commit `dfc3a14`.
- G8 red: nine coverage cases failed because the header was outside all images.
  Add matching note-line regions to the existing request and preserve the six-image
  limit. Include a parser test using note-image coordinates to establish scale.
- Offline generator check: seed 17, six ships. Real local Tesseract found a header
  note on 6/6 sheets with synthetic tight view boxes; kind/fragment checks retained
  all 12 generated crane labels. No provider calls and no model accuracy claim.
  An initial harness used a padded profile that already covered the header; it was
  corrected to an explicitly uncovered header before the six-case check.
- Full GA suite: 326 passed before the final added local-OCR integration test.
- Quick-tier first attempt failed because a shared cached app build did not stage
  this worktree's `app/ui-release`. Rebuilding only marinaframe-app fixed staging.
  Next attempt passed format/clippy but failed the unrelated real-worker primary
  sheet replacement: `Some("The action could not be completed (sheet_replacement_failed).")`
  versus `None`, app/core/tests/replace_sheet.rs:144. One diagnostic with explicit
  worker Python and RUST_BACKTRACE passed (1 passed; registry error `None`). No
  unrelated code or test was changed. Complete tier rerun failed at the same
  primary replacement assertion. This remains a merge blocker for the PM, not a
  reason to change unrelated worker code in this lane.
- Final scale/vocabulary checks: 139 passed. Final vocabulary/commercial/labels/
  note-crop checks, including generated-sheet local OCR: 157 passed. The fragment
  exemption is limited to labels ending in CR, not arbitrary crane-label fragments.
- UI: 275 passed, zero failures. Bounded secret scan: zero findings.
- The separate Python quick tier reached 51% with four skips and no displayed
  failures before the tool stopped it at its 600-second background limit. It is
  incomplete, not passing. A longer restart was started then cancelled because
  the unrelated Rust quick-tier blocker already requires PM follow-up.

## Resume point

Both scoped fixes are committed (`dfc3a14`, `c0a5db3`). Delivery stops at the
unrelated full-tier Rust blocker. Push the passing scoped work as the brief directs
for a blocked lane; this is not a clean quick-tier delivery. PM must resolve or
triage the primary sheet-replacement failure, complete the Python quick tier,
run development byte-identical replay, and authorize any live model re-run.
No partner drawing or restricted folder was opened. No merge. No structural
module change; Codesight refresh is not required. No worktree-local target folder
exists, so no Rust build-folder removal is needed; shared cache remains untouched
apart from the single app-package cache repair noted above.
