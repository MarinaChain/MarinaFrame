# W14 localisation implementation plan

> **For Claude:** Use executing-plans to implement this plan task by task.

**Goal:** Measure the vision model's coordinate frame before assessing drawing localisation.

**Architecture:** Use the existing Rust provider boundary and receipt format. Keep source, transmitted-image and normalized frames separate. Open factory truth only for scoring or explicitly supplied calibration; never send hidden hull truth to the model.

**Tech Stack:** Rust provider worker, Python, Pillow, NumPy, pytest.

## Design review

- Architecture: PASS. Reuse the bounded Rust vision request route; add a typed experimental localisation purpose if the setup contract cannot express calibration answers.
- Code quality: PASS. Store transforms in request manifests and preserve raw replies. No guessing a frame from answer magnitudes.
- Tests: PASS. Test round trips for non-square images, rounded resize dimensions, margins, crop offsets, and invalid/out-of-range replies.
- Performance: WARN. Keep the 1 MiB / 1,048,576-pixel per-image boundary. A 4096-wide image must be shallow or explicitly downsampled. Bound concurrent requests and stop on consecutive failures/no progress; do not impose an aggregate call cap.

## Tasks and checks

1. Read provider, setup, review, W11 tools, and frozen factory contracts. Record source-to-image transformations and any coordinate use in W11. Resume: audit complete only with file/line evidence.
2. Add a typed calibration/localisation request with existing Rust receipt, per-request limits, and image binding. Add schema/guard tests before implementation. Generate small marks/grid images at 512/1024/2048/4096 widths and non-square sizes. Test implicit pixels, explicit pixels, normalized 0..1000, normalized 0..1. Fit scale/offset and axis-order alternatives; retain raw answers and residuals. Resume: frame result saved before changing setup behavior.
3. If calibration supports a mismatch, test and implement explicit image-frame conversion in setup. Preserve raw readings and provenance. Do not weaken ink or semantic checks. Rerun the exact 40 W12 development cases; regenerate and verify all frozen hashes. Reuse W12 scoring and report missing-answer coverage.
4. If W11 consumes model coordinates, rerun 20 development cases with frozen executable/source. Otherwise document why a rerun does not test this fix.
5. Measure station/waterline crossings, half-breadths with supplied scale, and image-derived scale on development drawings. Compare full-sheet and crop views and deterministic tracing at the same stations/heights. Stratify by level and layout. Keep supplied calibration distinct from inferred scale. Stop an unproductive mode rather than manufacture an answer.
6. Aggregate every receipt, including failed calls, into exact calls/tokens/list cost and image inventory. Write outputs/w14 results and docs/LLM_LOCALISATION.md. Do not commit authentic sheets or large generated images.
7. Review with demand-elegance, run targeted tests and make test-quick using the shared Python environment and this worktree's PYTHONPATH. Run cargo clean after all active requests stop. Commit on w14-localisation, do not push. Final reply under 450 words.

## Commands

```sh
export PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
export PYTHONPATH="$PWD/src"
export MARINAFRAME_TEST_PYTHON="$PY"
$PY -m benchmarks.llm_setup_review.sample --setup-sample --root work/w14/factory
# Expected: 40 cases, no drawing hash mismatches.
make test-quick PY="$PY"
# Expected: all quick checks pass.
cargo clean
```

Load keys only with the authorized script. Never print environment values or keys. Keep all new files and commands in this worktree. Temporary evidence belongs in work/w14; final reports and compact receipts belong in outputs/w14.

## Current resume point

All experiments, final usage aggregation and documentation are complete. Forty drawing hashes match; all 20 W11 cases were attempted and stopped for no progress. Final quick tier passed (652 Python tests, Rust, format, Clippy, secrets). Cargo clean removed 4.1 GiB after requests stopped. Commit remains; do not push. Primary setup attempts and separate rejection retries both stay in usage; primary metrics are not replaced with retries.
