# G2-mid Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Check withheld-design range coverage for public 70,000–170,000 DWT tankers once.

**Architecture:** Reuse the existing DWT-only FleetModel without changes. Keep public particulars and per-ship results in ignored work/concept-mid; commit the protocol and generic runner only.

**Tech Stack:** Python, NumPy, existing concept_dimensions package.

## Pre-fit review
- Architecture PASS: existing regression and proposal interfaces; no new model.
- Quality WARN: derived design IDs do not prove sister independence. Add conservative transitive geometric exclusion.
- Coverage PASS: require four withheld designs, training support at both extremes and at least ten training clusters before fitting.
- Performance PASS: one small least-squares fit; no network calls.

## Frozen gate G2-mid — commit before fit

Selection and exclusions were prepared without fitting or inspecting errors. This is a withheld-fit check, not a blind evaluation. Capacity and speed are **not used**, in training or proposals. This new gate does not repair or replace original G2's cargo/speed conditions.

1. Eligible rows: complete_for_concept_fit=true, inclusive 70,000–170,000 summer DWT, from the supplied CSV. No other fleet or restricted data.
2. Make connected components: join equal design_id or IMO; also join geometric sisters regardless of builder when Lpp differs by at most 1 m, B and D by at most 0.1 m, and DWT by at most 2% of the smaller value. Apply transitively. This deliberately removes some possibly unrelated designs; it cannot prove all licence-built sisters are known.
3. Choose one representative per component by source grade (primary, secondary, copied), then lexical IMO, then row_id. Choose one representative in each band [70k,85k), [85k,110k), [110k,125k), [125k,170k]. Within a band prefer source grade, then distance to band midpoint, then lexical IMO and row_id. At least one Aframax/LR2 is required. Exclude every member of all four selected components from training.
4. Frozen source SHA-256: `6705cc191a719ffae76551077eb9231f514b39b217b16e54f4f08d1f4e140eec`.
5. Frozen manifest SHA-256: `074590ddf9be372f864f7908d47ba44bf2ea88f5515a3d9b7c6075f386d43d60`. Exact rows, selection and membership remain in ignored `work/concept-mid/freeze.json`. The hash fixes the selected designs without putting per-ship third-party data in git.
6. Freeze inventory: 53 ships, 36 derived design IDs, 30 conservative components. Four selected components contain eight excluded ships. Training uses 26 independent-component representatives (4 primary, 22 copied); evaluation uses three primary and one copied representative. Training DWT spans all selected DWTs. Independence is inferred, not confirmed.
7. Fit once. Use unchanged maximum absolute training log residual **plus** log(1.10) for Lpp/B/D/T, log(1.05) for Cb. Use existing Cb clipping at 1.0. Do not alter quantity ranges or refit after results.
8. Score one proposal per selected design. PASS only if **all Lpp, B, T and Cb values are inside their marginal regression ranges for all four designs: 4/4, 16/16 checks**. D is a diagnostic, not an added pass condition. Missing required truth means NOT RUN, not pass.
9. Report coverage and signed estimate errors per quantity and source grade. Secondary evaluation count may be zero; report NOT RUN rather than infer coverage. Capacity/speed, displacement prediction, hull shape and joint feasibility are outside scope. Cb is derived from summer displacement and may use extreme breadth and shell/appendage-inclusive displacement. Keep engineering_approved=false.

## Execution steps and resume point

1. Commit this gate and `scripts/run_concept_mid.py` before fitting. Freeze mode has already completed; neither fit nor score has run.
2. Run `python3 -I scripts/run_concept_mid.py score --evidence work/concept-mid` on the clean committed tree. The runner records the commit and freeze hash and creates an exclusive attempt marker before fitting. Never delete that marker to retry. Preserve any failure as evidence.
3. Summarize the stored result only; do not rescore. Append aggregate results here and commit this small step. Store full numeric evidence only in ignored work/concept-mid.
4. Run focused concept tests, then `MF_IDENTITY_DENYLIST_FILE=/Users/jonathanjie/Documents/workspace/marinaframe-private/identity-denylist.txt MARINAFRAME_TEST_PYTHON=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` in the background, with a long tool allowance. Capture exit status without a pipeline that can hide it.
5. Record checks, review the diff, commit, and push only lane/concept-mid after a passing quick tier. No merge. Inspect local target/ then remove only that worktree-local Rust build folder after push; do not follow a symlink into a shared cache.

## One-shot results

Freeze committed as `6d162e8` before the sole fit and four proposals. Numerical G2-mid range gate **PASS: 4/4 designs, 16/16 required quantity checks**. No threshold or selection changed after scoring. D diagnostic also covered 4/4. The runner recorded its commit and freeze digest in `work/concept-mid/attempt.json`; full coefficients, bounds, truth, warnings and signed errors are in `result.json`. No fleet data is tracked.

Aggregate errors below are absolute percentages of the published/derived value, calculated from stored results, not a new fit or score. Each cell gives coverage; mean absolute percentage error / maximum absolute percentage error.

| Quantity | All four designs | Primary (3 designs) | Copied (1 design) |
|---|---|---|---|
| Lpp | 4/4; 0.806% / 1.436% | 3/3; 0.596% / 0.675% | 1/1; 1.436% / 1.436% |
| B | 4/4; 4.484% / 7.854% | 3/3; 5.466% / 7.854% | 1/1; 1.536% / 1.536% |
| T | 4/4; 3.485% / 7.418% | 3/3; 4.532% / 7.418% | 1/1; 0.346% / 0.346% |
| Cb | 4/4; 1.525% / 2.739% | 3/3; 1.580% / 2.739% | 1/1; 1.358% / 1.358% |
| D (diagnostic) | 4/4; 2.586% / 5.943% | 3/3; 3.379% / 5.943% | 1/1; 0.209% / 0.209% |

Joint coverage by evaluation source grade: primary 3/3; copied 1/1; secondary **NOT RUN (0 designs)**. These grade splits evaluate one mixed-grade fitted model, not separately fitted models. Training had 4 primary and 22 copied representatives. Four withheld designs do not establish fleet-wide accuracy or calibrated coverage. Bands include fixed 10% dimension / 5% Cb floors plus maximum training residuals; coverage is not point-estimate precision. Stored upper bounds exceed their point estimates by 13.64% (Lpp), 21.60% (B), 20.40% (T) and 16.52% (Cb), so the numerical gate is broad. Sister exclusion is conservative but inferred, Cb is derived, and copied sources remain unconfirmed. Capacity, speed, hull geometry and joint feasibility were not tested. `engineering_approved=false`.

## Checks and review

- Focused concept suite: **38 passed** in 5.62 s.
- First quick-tier attempt exited 2 in clippy: `tauri::generate_context!` could not find ignored `app/ui-release`. This is the documented shared-cache staging issue, not a model failure. Touching the lane-local `app/src-tauri/build.rs` (no content change) triggered its existing staging script. The retry passed clippy and proceeded to tests; full tier result pending. Logs: ignored `work/concept-mid/quick.log` and `quick-final.log`.
- Elegance check: reuse model code unchanged; no new fitting abstraction, no structural changes, no codesight refresh needed. Per-ship data remains ignored. Gate and runner content remain identical to the pre-fit commit.
- Process correction (2026-11-13): when a lane forbids extra worktrees, omit Agent isolation entirely; a read-only review does not need a new checkout. After an isolation denial, stop rather than arrange alternate access. This correction remains in the lane-owned report; shared lesson files were not changed.
- Independent review was blocked by the review agent's worktree isolation. A mistaken isolation option created a temporary agent checkout despite the no-extra-worktree instruction; the agent was told to stop, not bypass access, and not edit that checkout. No independent review conclusion is claimed. This process deviation did not change the gate, source data or score.

### Runner reuse limits and evidence cross-check

The review agent continued after stop requests and was terminated. Its partial notes raised runner hardening candidates, not a completed review: score mode does not enforce a committed expected freeze digest or model-source digest, the evidence path is not constrained to ignored folders, several guards use assertions (disabled by Python -O), and missing truth may consume the attempt marker without writing a NOT RUN record. Do not treat this task-specific runner as a hardened general evaluation service. Hardening is deferred; changing it after scoring would not improve the original run's provenance.

Direct checks after those notes found the current manifest SHA-256 equals both the pre-fit committed value and attempt.json; attempt/result identify the pre-fit `6d162e8` commit; model and runner have no diff from that commit; required truth is present. Actual invocation used Python -I without -O and ignored work/concept-mid. These checks read stored evidence only and did not fit or score again. No identified candidate invalidates this recorded numerical result; an independent completed review is still absent.

Current resume point: sole fit and score complete; do not rerun. Focused tests pass. Await complete quick-tier result, then record it, commit and push only lane/concept-mid. No merge.
