# W13 verification ledger

Plan: `docs/plans/2026-11-08-w13-ship-cad.md`.

- Source inspection and design review complete. User scope is the binding specification.
- Synthetic tests were written before the language, measurement tools, sandbox, driver, scorer and independent STEP cutter. Initial failures were observed; targeted suite later passed 29 tests.
- Fresh review found and regression tests reproduced three defects: sorted argument keys changed primary source; asymmetric appendage spans were reflected; openings could erase a target. All three fixes passed the targeted suite.
- Review also found that standalone STEP cuts were not connected to worker execution. A failing integration test was added. Host audit input now reaches the worker and reimports the exported STEP. Missing independent traces still block.
- Six guard mutations caught: unknown fields/free code, literal dimensions, absent measurement handling, external file reads, network bind, and wrong source view. Source mutations run in memory, not on pinned worker files. OS mutations run with isolated Python to ensure tests reach the intended operation. A socket constructor alone is not a denied network operation; the test uses bind.
- `make test-quick` first complete run passed: 674 Python tests, 17 CAD tests deselected; Rust tests, format, Clippy and secret scan passed. Exact final tier results follow in `docs/SHIP_CAD_LANGUAGE.md`.
- Architecture index generation ran only here. It generated `.codesight` but its managed bootstrap failed with `ModuleNotFoundError: render_bootstrap`; generated local files are excluded from the commit.

## Design rulings

- JSON instead of a new text DSL: use existing bounded serde transport; simpler parser surface.
- OS containment is macOS-only for this version; other platforms fail closed. Existing resource supervision is not a security sandbox.
- Available truth is hull-only. Do not claim scores for complete-vessel components absent from truth.
- W13 remains a separate draft-only path. Rust controller readiness and W12 finalization veto are unchanged; W13 does not claim finalization coverage.
- Independent plan/body identities are unresolved on Gunnerus. Keep missing views as blockers instead of comparing arbitrary nearby ink.
- The initial successful-level-hash no-progress rule allowed alternating levels without built components. The corrected rule requires a greater built-component count. Interrupted arm and all receipts remain local and included in accounting.

No changes were made to `ingest.py` or `agent_tools.py`. No source drawing, drawing derivative, truth model or source-derived geometry is included in version control.

Final checks: 30 targeted W13 tests passed. The separate Python CAD tier passed 17 tests (674 deselected). A later wrong-view guard passed its RED/GREEN regression and six mutation probes. The single full-tier attempt failed the pre-existing stalled-worker timeout test; its isolated rerun passed. The expanded Gunnerus CAD retry completed exit 0 in 419.95 s, built only hull, and failed cross-view checking (profile 3.837445 m; plan/body missing). Final quick rerun and hull section metrics are recorded in the language report.

Final post-view-guard make test-quick passed: Python675 passed/17 CAD deselected; Rust, Clippy, format, secrets green. No new source edits after this check.

Cargo cleanup completed after all W13 Cargo/native consumers ended: 18,779 files, 5.1 GiB removed. Worktree and branch are kept; no push.
