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

## Resume point

Source tracing complete. Next: failing G7 tests, then the first scoped fix.

## Results

Pending.
