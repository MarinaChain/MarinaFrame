## Split required CI and schedule dependency watches

The locked Linux job serializes independent checks. Run them in parallel and keep its existing check name as an aggregate. Keep the macOS protection as a separate required job. The four Python quick shards partition files in sorted order and split the measured slowest quick file by a stable test-ID hash; two CAD shards run the complementary marker selection. Mark real geometry and export-check builds as CAD while keeping validation-only tests quick.

### Coverage before and after

| Before | After |
| --- | --- |
| Linux locked dependency installation and `pip check` | All Linux Python/Rust jobs install both hash-checked locks; wheel job runs `pip check` |
| Linux UI tests | UI job |
| Linux workspace Rust build and non-ignored tests, excluding the desktop shell | Wheel job builds the workspace; Rust controller job runs the same tests |
| Linux ignored real-CAD Rust tests | Rust real-CAD job, unchanged `make rust-cad` |
| Linux complete Python suite | Four quick shards plus the complementary Python real-CAD job |
| Linux source secret scan | Lint and secrets job |
| Linux package build, isolated wheel smoke, installed Rust smoke | Wheel job |
| Linux OSV audits of both locks | Wheel job |
| Required macOS cleanup, Seatbelt, scripted part revision and app-core real workers | Same required macOS job, with `MARINAFRAME_REQUIRE_WORKER=1` |
| Windows portability watch (non-blocking) | Nightly, manual and dependency-file changes; remains report-only |
| Manual supported-range dependency update probe | Nightly, manual and dependency-file changes |
| Not previously in CI: Rust format and clippy | Lint job; Linux excludes the desktop shell because GTK/WebKit is not installed |

The legacy `Locked Linux / Python 3.12.14` status aggregates all required Linux jobs. Keep the existing macOS status required. Check branch protection after deployment: new job statuses are visible individually, while the aggregate prevents a failed or skipped Linux job from passing the existing gate.

### Timing and limits

Before: locked Linux measured 869–1,516 seconds (14.5–25.3 minutes), plus any queue delay. After: estimated 7–12 minutes with parallel runners, likely bounded by macOS (about 7–9 minutes including setup), the slowest Python shard or real-CAD job. This is a projection, not a GitHub measurement; cold caches, runner availability and indivisible slow tests may change it. Rust caches are separated by operating system, architecture, toolchain/lock hashes and job; rustup uses the pinned repository toolchain.

### Verification

- YAML parsed with PyYAML and basic job/step/timeout checks; `actionlint` is not installed.
- Collection: 1,869 tests accounted for exactly once across quick shards (516, 411, 387, 490) and CAD shards (35 and 30).
- Local `make lint-ci`, UI (182 tests) and secret scan passed.
- Both `make test-quick` and `make test-full` failed at the existing `part_revise_worker` real-worker test. This environment denies even a minimal `sandbox-exec` probe (`sandbox_apply: Operation not permitted`), so macOS worker protection still needs an unrestricted runner.
- Before the final ten export-check marker changes, full Python `--durations=40`: 1,847 passed, 10 failed, one skipped and 11 errors in 763.74 s. The standalone quick tier had 1,798 passed, five failed and 11 errors; the CAD tier had 49 passed, five failed and one skipped. Socket binding, process inspection and nested Seatbelt are denied in this session.
- After those marker changes, all ten affected export-check tests passed; pytest collection confirmed every test appears in exactly one shard.
- `make rust-cad`: passed all eight targets in 455.37 s on a loaded Mac. A no-fail-fast Rust workspace run failed the part-revision worker and two process-group tests; the latter did not publish their fixture files.
- Slowest Python calls under concurrent local load: CAD complexity 53.52 s, flared bow containment 47.00 s, provisional CAD build 42.76 s, and body-plan label leader 41.06 s. Top-40 calls and setup in `test_body_plan_polyline.py` totalled 154.92 s; its cases are distributed across quick shards.
- Redundancy: real geometry builds in `test_geometry*.py` and `test_cad_export_check.py` were unmarked. Rust integration targets include source modules by path, so their inline unit tests compile and run repeatedly (for example, 99 shared tests per target). The tests remain intact; converting those targets to library imports is a separate refactor.
- Full local logs are in ignored `work/ci-measure/`.

GitHub branch-protection settings and hosted-run timings cannot be verified from this worktree.
