# W17 Investigator Progress Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the live investigator retain its readings, receive useful refusal feedback, and reach explicitly unverified drafts without changing safety gates.

**Architecture:** Keep memory in recorded model decisions and derive observations from the event ledger. Permit bounded source-ink tools after an allowlisted inspection resource failure, not after arbitrary worker errors. Preserve model-choice guesses, competing evidence, validation authority, and engineering_approved=false.

**Tech Stack:** Rust controller/provider, Python source inspection and tools, pytest, cargo test, factory generator and frozen scorer.

---

## Scope and review

- Authorized root: `.claude/worktrees/w17-llm-progress`, branch `w17-llm-progress`, base `a5fd140`.
- No root AGENTS.md or CLAUDE.md exists in this worktree or main checkout. Global instructions and `docs/CONTINUATION_STATUS.md` apply.
- All raw/generated data, frozen executable/source copies and logs go in `/Users/jonathanjie/Documents/workspace/MarinaFrame/work/w17/`.
- Sealed v2 is spent. Do not rerun, score, inspect truth, or tune on its results. Only the supplied evidence and one existing command.json are needed.
- Architecture: PASS, existing event and worker contracts. WARN: resource-failure recovery must not certify identity or bypass inspection for arbitrary errors.
- Quality: PASS, bounded structured diagnostics instead of exception strings. WARN: preserve old serialized ledger hashes with default/omitted optional fields.
- Coverage: test nested history, notes limits/retention, repeated actions/refusal stop/state change, failure-code privacy, recovery ink evidence, grid classification, provider settings/defaults.
- Performance: bounded notes (8 x 600 characters), bounded existing tracing and observation budgets; at most two live jobs with native admission.

## Task 1: Establish development comparison

Files: existing `benchmarks/factory/` and investigation runner; compact records in `outputs/w17/`.

1. Read generator, runner, scorer and one authorized head-to-head CLI command.
2. Select 24 development cases deterministically, three per layout/noise stratum across both layouts and L0-L3. Save IDs before any run.
3. Generate inputs from the development manifest into main `work/w17/` with the existing generator. Do not use sealed inputs.
4. Freeze base a5fd140 executable and Python source before baseline runs. Copy binaries; never run an executable rebuilt by tests.
5. Run baseline detached with the same live/draft/model-review settings, sourced keys (never print), two jobs maximum and native admission. Preserve failures and usage.

## Task 2: History, notes and repeat feedback

Files: `rust-control/src/controller.rs`, `types.rs` (Decision), `provider.rs` (investigation prompt).

1. Add failing unit tests for nested recorded reasons, optional notes bounds and last-eight unverified retention.
2. Read decision reasons from `payload.decision.reason`; preserve refusal diagnostics separately.
3. Add optional notes with character and byte bounds, omit absent notes on serialization. Expose claims with an explicit unverified label; never pass them as measured geometry.
4. Add failing tests that the second unchanged action returns `repeated_action_refused` without a worker call, cites earlier evidence, and offers useful next operations; refusal counts must terminate at the configured limit.
5. Distinguish meaningful domain changes from views. Clear staged decisions on refusal and preserve recovery integrity.
6. Update investigation prompt: record label positions and tag/station mappings in notes, act on them, assign unassigned sections and build rather than reread.
7. Run focused cargo tests.

## Task 3: Safe failed-inspection recovery and grid evidence

Files: `src/vessel_reconstruction/{agent_render_worker,agent_tools,investigation_tools,investigation}.py`, Python tests.

1. Add failing privacy/diagnostic tests for resource-limit failures and unrelated exceptions.
2. Return only allowlisted, fixed, path-free failure codes/messages. Persist affected section status so recovery survives calls/restarts.
3. Allow existing bounded ink tracing/enumeration only for sections inspected or known to have failed the resource budget. Preserve catalog provenance and build prerequisites; all model assignments remain open guesses.
4. Add failing classification tests for axis-aligned full-height straight grid strokes and curved/short alternatives.
5. Mark grid strokes without removing them or promoting another candidate to certified identity.
6. Run focused pytest; keep Python stable during pinned worker integration tests.

## Task 4: Configurable provider settings

Files: `rust-control/src/types.rs` (Config), `main.rs`, controller request payload and tests.

1. Add failing tests for backward-compatible defaults, enabled/disabled thinking and bounded finite temperature.
2. Add investigation-only CLI settings with defaults unchanged: disabled thinking, temperature zero. Omit defaults from serialization to preserve old hashes.
3. Wire settings only into investigation requests; preserve other request purposes.
4. Test exact payload and invalid values.

## Task 5: Verify, measure, document and commit

1. Review combined diff; run `make test-quick` after stable Python source.
2. Freeze changed executable/source and run the same 24 development cases detached.
3. Run matched thinking-on development measurement; keep defaults unchanged unless measured evidence supports a change. Report budget/failure limitations.
4. Score with existing frozen factory gate. Report fixed denominators, statuses, no_progress rate, built, gate-correct, silent wrong builds, labelled wrong drafts, requests and list cost. Silent wrong builds must be zero.
5. Run `make test-full` with logs outside this worktree. Do not edit pinned source during tests.
6. Write `docs/LLM_INVESTIGATOR.md` with causes, safe design and numbers; compact reproducible aggregates in `outputs/w17/`, no drawings/truth/keys.
7. Run demand-elegance review and inspect git diff/status. Commit only W17 work on this branch; no push or merge.

## Resume point

Source root causes checked: nested history reason mismatch and discarded inspection exception detail. File-owned implementation tasks started; benchmark command mapping is read-only in progress. No live measurement started and no result numbers claimed. Next: establish/freeze baseline and development sample, review tests from implementation tasks, then integrate payload settings and run verification.
