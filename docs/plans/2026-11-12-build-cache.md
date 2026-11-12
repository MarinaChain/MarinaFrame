# Shared Build Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop local Makefile builds from creating one Rust target per worktree.

**Architecture:** Select one target directory from Git's common directory for local Makefile commands, while preserving environment/command-line overrides and CI's existing target. Use the same selected directory for the smoke executable. Do not add a compiler-cache dependency.

**Tech Stack:** GNU Make, Cargo, Python/pytest, Git.

## Scope and gates (set before measurement)

- Work only on `lane/build-cache` in the assigned worktree. Do not read sealed or holdout material.
- Use only the mandated `CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol`; no second Rust target. It was empty at initial inspection. Never clean this shared directory while other lanes use it.
- Measure cold and immediate warm `make test-quick` before edits. Record elapsed seconds, exit status, target size before/after and lock-wait messages. These are loaded-host observations, not controlled performance guarantees. If another lane uses the cache first, report the cold measurement as contaminated.
- Keep one target, explicit overrides, and CI behavior. Require regression tests plus the quick tier before push. Never push on failed tests.
- `sccache` is absent. Compare its documented scope/cost, but do not install it without PM permission. Do not report an unmeasured speedup.

## Plan review

- Architecture: **PASS** — Makefile already owns local test entry points; Git common-dir joins linked worktrees without machine-specific paths. **WARN** — plain Cargo outside Make is not changed.
- Quality: **PASS** — one default and one smoke path, no wrapper dependency or destructive cache clearing.
- Coverage: **PASS** — test main/linked checkout defaults, overrides, CI, and smoke path with dry runs in temporary Git repositories, without building Rust.
- Performance: **WARN** — Cargo serializes shared-target builds, and branch changes can rebuild local crates. `sccache` cannot eliminate linked test artifacts; it adds installation and a second cache.

## Task 1: Baseline

1. Create `scripts/measure_build_cache.py`, a no-timeout measurement helper taking a target and output path. Run the quick tier twice and save logs/JSON under ignored `work/build-cache/`.
2. Read the logs, record pass/fail and observed disk/time. Do not alter unrelated test failures.
3. Commit the plan and helper after a passing quick tier.

## Task 2: Default and regression tests

1. Create `tests/test_build_cache.py` with dry-run Make tests against temporary ordinary and linked Git checkouts. Require one shared default, environment and command-line priority, unchanged CI, and smoke using the selected target. Run with `/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m pytest -q tests/test_build_cache.py`; expect failure before implementation.
2. Modify `Makefile`: local target is `<git-common-dir>/../.claude/worktrees/shared-target-sol`, exported to Cargo. CI defaults to `target`. Respect explicit `CARGO_TARGET_DIR`. Set a derived executable path for relative and absolute targets.
3. Run the focused tests; expect pass. Run `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` with no explicit target; require pass. Record final measurement.
4. Use demand-elegance and verification-before-completion. Commit the implementation and results. Run quick tier chained to `git push origin lane/build-cache`. Do not merge.

## Option evaluation and lane settings

| Option | Disk behavior | Time / operational cost | Decision |
| --- | --- | --- | --- |
| Shared Cargo target | One directory for compatible dependencies, intermediate output and linked tests; no fixed size cap | Target lock queues competing Cargo jobs; source paths, changed branches, features and toolchains can cause rebuilds/growth. No install. | Choose for local Makefile commands. |
| Capped sccache alone | Adds a compiler cache (suggested trial cap: `SCCACHE_CACHE_SIZE=2G`; upstream default 10 GB), but leaves per-worktree linked outputs | Not installed. Homebrew install needs PM permission. Rust incremental compilations and linked crate types have caching limits; no local timings measured. | Not sufficient for this disk problem. |
| Both | Shared linked outputs plus a second capped cache | Could help compiler misses, but does not remove the shared-target lock. Extra setup and disk, with no measured benefit here. | Defer pending a separate permitted trial. |

After implementation, lanes use `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` without setting a target. For **direct Cargo** commands, keep exporting `CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol`. An explicit environment or Make command-line target wins. CI keeps `target`. No lane may run `cargo clean` on the shared cache while another build or run uses it; use a private override only when coordinated with the PM and disk budget.

The batch instruction prohibits a second target, so the old per-worktree-target baseline is **not run**. Cold/warm use the fresh assigned checkout and the initially empty mandated shared target. Avoided duplication is an estimate from the measured target footprint, not measured deleted disk. Other lanes use the same cache and host; no isolated latency or branch-churn speedup is claimed.

Sources read 2026-11-12: [Cargo build cache](https://doc.rust-lang.org/cargo/reference/build-cache.html), [sccache Rust caveats](https://github.com/mozilla/sccache#rust), [sccache local size configuration](https://github.com/mozilla/sccache/blob/main/docs/Local.md).

## Results / resume point

Baseline complete, both quick tiers exit 0. Logs and JSON: `work/build-cache/baseline/` (ignored).

| Run | Full tier (s) | Clippy (s) | Rust test compilation (s) | Target before/after (KiB) | Lock messages |
| --- | ---: | ---: | ---: | --- | ---: |
| Cold | 1803.932 | 31.72 | 38.45 | 0 / 3087556 | 0 |
| Warm | 1030.935 | 9.22 | 9.03 | 3087556 / 3096836 | 0 |

Cold Python: 2284 passed, 4 skipped, 87 deselected (1651.15 s). Warm Python: 2286 passed, 4 skipped, 87 deselected (802.62 s); the two added helper tests were collected only by the warm run. Both UI tiers passed and both secret scans had 0 findings. Full-tier times are not identical-test-set comparisons, and Python plus changing host load dominates them. Do not claim a 43% cache speedup from these totals. Target footprint is about 2.95 GiB; each avoided identical per-worktree copy saves approximately that amount, but no old target was built or deleted for comparison. Shared cache can grow; it is not capped.

Resume: commit baseline plan/helper and passing helper tests, restore pending Makefile tests from `work/build-cache/test_build_cache.py.pending` (RED observed: 5 failed / 2 passed), then implement the default and smoke path. No model calls or software installs made.

After push: inspect and remove only this worktree's own `target/` if it exists. Keep the shared cache for other active lanes. Final report under 200 words with commits, evidence and omissions.
