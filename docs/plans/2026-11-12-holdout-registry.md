# Item 10: holdout registry and status markers

## Scope and gates (2026-11-12)

Work only on `lane/holdout-registry`. Read tracked protocols and result summaries;
never open truth files, holdout images, sealed material or run folders. No model
calls, scoring, score changes or reader changes. `engineering_approved` stays false.

## Steps

1. Inventory `benchmarks/*/holdout_value.py` and the named protocol/result docs.
2. Add a source-only test that each module has one literal `STATUS`, from
   `blind`, `spent`, `development`, matching one registry row. Observe failure first.
3. Write `docs/holdouts/REGISTRY.md`, with sheet, kind, protocol, original blind-run
   date/result, current status and cited status evidence. Add constants and reasons.
4. Run focused tests and `make test-quick` with the main Python environment and
   shared Sol Rust target. Commit passing work in small steps; push only this lane.
5. Remove this worktree's own `target/` if present; never remove the shared target.

## Status policy

`blind`: no blind reader run is recorded; not a claim that a candidate is ready.
`spent`: blind run complete, with no recorded later development use.
`development`: explicit development designation or recorded post-run development use.
A sheet cannot become blind again. Historical pass/fail results stay unchanged.
Catalogue-only and rejected candidates are separate from actual test sheets.

## Resume point

Inventory complete: 10 holdout modules, all now development cases. Sources include
`docs/BODY_PLAN_CHINE.md`, `docs/WHOLE_VESSEL_GUNNERUS.md`,
`docs/AUTO_CALIBRATION.md`, `docs/holdouts/` and `docs/results/`.
Registry, ten status constants and source-only tests are complete. Metadata tests
first failed as expected (11 failures: ten missing constants, missing registry),
then all 107 focused tests passed. AST comparison confirms all 10 harnesses are
unchanged except `STATUS`. Relative document links and heading anchors resolve.
No truth, images, sealed material or saved run folders were opened.

Implementation and quick tier complete. Next: commit this results record and
push `lane/holdout-registry` only. No merge. No worktree-local `target/` exists;
leave the shared Sol target untouched. PM can review the registry and merge after CI.

## Results

- Registry: ten spent holdouts now designated `development`, plus Balclutha as a
  development-only reference. Unused catalogue candidates and ineligible ALMA
  remain separate; no blind result is invented for them.
- Original pass/fail decisions, including BUMBLE BEE's station-label failure and
  BUE GIRL's separate round-12b access addendum, are retained without re-scoring.
- Commit `caa8938`: registry, ten constants, source-only consistency test.
- Focused tests: 107 passed in 1.04 s; post-commit repeat: 107 passed in 1.21 s.
- Quick-tier preparation: initial runs failed in Tauri's compile-time macro because
  the shared cache had not staged this worktree's ignored `app/ui-release`.
  Touching the UI directory did not resolve this. A temporary Rust runner in
  `work/` called the existing `release_ui::stage` function; no tracked build or UI
  source was changed. The quick tier passed after that staging step (exit 0).
- Quick tier: Rust format, clippy and workspace tests passed; Python 2295 passed,
  4 skipped, 87 deselected, 5 warnings in 1937.74 s; UI 275 passed, 0 failed;
  bounded secrets scan: 1276 tracked text files, 0 findings. Python SWIG
  deprecation and Node module-type/localStorage warnings remain; no warning fixes
  are in this metadata-only scope. Log: `work/holdout-registry-quick.log` (ignored).
- Not run: full/CAD tier, CI status checks, scoring and model calls.
- Cleanup: no local `target/` was created; never delete the shared Sol target.
