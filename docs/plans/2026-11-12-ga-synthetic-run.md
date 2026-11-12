# Synthetic GA measured run — 2026-11-12

## Fixed protocol (before model calls)

- Source: `ac0ca3a`, branch `lane/ga-synthetic-run`. Measurement only; reader and scorer stay unchanged. `engineering_approved` stays false.
- Generate all six fictional ships with seed 17 in a new directory under `/Users/jonathanjie/Documents/workspace/MarinaFrame/work/ga-synthetic-run/`. Keep sheets and truth separate. Only sheets enter requests.
- Use release controller built with `cargo build --release --locked -p marinaframe-control`, shared target cache, then copy the executable into the run directory to pin its bytes.
- One reading per case, default Claude Sonnet 5.5 (`claude-sonnet-5-5`), subscription transport, measuring pass enabled, six coarse/fine requests per ship. Run the first two cases, inspect every response trace, then continue the remaining four without tuning or repeating results.
- Hard campaign cap: 80 receipted provider attempts, including failures and transport retries. The existing batch cap checks only between cases and its exception path does not add failed-case usage. The measuring pass also sits outside the coarse/fine ceiling. Therefore use a serial executable guard around the unchanged controller: before each `vision-request`, count prior receipt files and reserve three slots (the controller's maximum attempts). Refuse the invocation if fewer than three slots remain. Record this conservative stop as a budget stop, not a model failure. No case retry is planned.
- Build arrangement inputs with the existing reader/arrangement code. Score with `benchmarks.ga_synthetic score`. Matching is frozen: same kind, positive 3D overlap, maximum cardinality then minimum face error; no ID/label matching, no post-run thresholds.
- Aggregate found share uses all truth spaces. Report inventions separately from unmeasured readings. Six-face absolute-error medians and maxima use matched spaces only, with sample counts and guessed-axis caveats.
- Exam scoring uses printed particulars only: 0.005 m tolerance for LOA/LBP/breadth/depth; exact hold/hatch/crane counts. Missing output remains in the denominator as abstention.
- Per-ship data, receipts, answers and scores stay in ignored `work/`. Only aggregate results enter this document.

## Checks

1. Confirm six sheets, separate truth, pinned executable and initial receipt count zero.
2. Inspect first two cases' raw responses, request count and transport; no reader/scorer edits.
3. Score all six cases, preserve failure/abstention denominators, reconcile receipt totals with reader totals.
4. Run focused GA tests and `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` before push.
5. Review aggregate report; commit and push this lane only. Do not merge. Remove only this worktree's local `target/`, if one exists; retain shared cache.

## Infrastructure findings (no reader/scorer fixes)

1. `ga_commercial.measure_one` calls `ga_scale.arrangement_input`, but that compatibility export was removed. The exception occurs after all replies and usage are aggregated. The external run driver catches only that exact exception, preserves its completed reading from the failing frame, and calls existing `ga_scale_arrangement.arrangement_input`. It sends no replacement model request.
2. The arrangement builder emits extent status `printed` for dimension-chain hold lengths. `ga_arrangement.load_input` accepts only `read`, `measured_from_scale`, and `guessed`. The unchanged scorer therefore rejects such raw arrangements. Preserve the raw error and input. For diagnostic box metrics only, create a separate copy changing `printed` to `read`; keep all numbers, spaces and matching rules unchanged. Label those results compatibility scores, not successful end-to-end raw scores.
3. The batch cap is not a hard total bound inside a case; the external serial guard reserves three attempts before each controller invocation. No reader or scorer source is changed.

## Final measured results

All six ships were read once. **54/80 provider attempts**, all completed, all Sonnet 5.5 through `claude-cli:print:subscription`; reader totals and receipt totals agree. No case retries, no cap stops, and no transport failures. The three scale attempts on one ship are part of the unchanged measuring pass, not case reruns. Tokens: 527,675 prompt and 151,668 completion. Receipt observed cost: **$0.00** (subscription); CLI list-price estimate: **$2.572030**, not a subscription charge.

All six measurements hit the removed-export exception after completing their model passes; the external driver preserved the readings and used the existing arrangement builder. Raw offline scoring succeeds for two tanker inputs (one has no established scale); four dry-cargo inputs fail on `printed` status. The following box results combine those two raw scores with four explicitly status-compatible diagnostic scores. **This is not a successful raw end-to-end pipeline result.**

### Space coverage and inventions

Found: **120/178 (67.42%)**. Missing: **58/178 (32.58%)**. Invented: **15**. Unmeasured reading entries: **73**. The 208 arrangement entries comprise 120 matches, 15 inventions, and 73 unmeasured entries. Unmeasured entries are not inventions under the frozen scorer. An invention share uses all arrangement entries of that kind, including unmeasured entries; the separate count prevents the denominator from hiding inventions.

| Kind | Found / truth | Found share | Invented / entries | Invention share | Unmeasured | Matches with guessed axes |
|---|---:|---:|---:|---:|---:|---:|
| accommodation_deck | 15/18 | 83.33% | 2/20 | 10.00% | 3 | 15 |
| ballast_tank | 59/90 | 65.56% | 4/100 | 4.00% | 37 | 49 |
| cargo_crane | 0/12 | 0.00% | 0/0 | — | 0 | 0 |
| cargo_hatch | 16/16 | 100.00% | 0/16 | 0.00% | 0 | 0 |
| cargo_hold | 16/16 | 100.00% | 0/16 | 0.00% | 0 | 0 |
| cargo_tank | 10/20 | 50.00% | 0/35 | 0.00% | 25 | 0 |
| engine_room | 4/6 | 66.67% | 0/5 | 0.00% | 1 | 4 |
| other_space | 0/0 | — | 9/15 | 60.00% | 6 | 0 |
| other_tank | 0/0 | — | 0/1 | 0.00% | 1 | 0 |

### Absolute box-face errors in metres

Each cell is **median / worst**, matched boxes only. `0.000` includes floating-point residuals below 0.0005 m. No matches means no error estimate, not zero error. Longitudinal frame snapping and printed dimension-chain spans explain the near-zero x errors; these are not independent sub-millimetre image measurements. No hull clipping is applied.

| Kind (matched n) | x aft | x forward | y starboard | y port | z bottom | z top |
|---|---:|---:|---:|---:|---:|---:|
| accommodation_deck (15) | 0.000 / 0.000 | 0.000 / 0.000 | 2.295 / 2.925 | 2.295 / 2.925 | 0.050 / 0.160 | 0.040 / 0.100 |
| ballast_tank (59) | 0.000 / 0.000 | 0.000 / 0.000 | 0.030 / 7.390 | 0.046 / 3.925 | 0.000 / 0.090 | 0.000 / 0.050 |
| cargo_crane (0) | — | — | — | — | — | — |
| cargo_hatch (16) | 0.000 / 0.000 | 0.000 / 0.000 | 0.009 / 0.052 | 0.045 / 0.062 | 0.050 / 0.120 | 0.040 / 0.050 |
| cargo_hold (16) | 0.000 / 0.000 | 0.000 / 0.000 | 0.040 / 0.070 | 0.060 / 0.070 | 0.030 / 0.040 | 0.035 / 0.050 |
| cargo_tank (10) | 0.000 / 0.000 | 0.000 / 0.000 | 0.020 / 0.030 | 0.010 / 0.010 | 0.010 / 0.010 | 0.020 / 0.020 |
| engine_room (4) | 0.000 / 0.000 | 0.000 / 0.000 | 0.005 / 0.005 | 0.005 / 0.005 | 0.050 / 0.070 | 0.070 / 0.120 |
| other_space (0) | — | — | — | — | — | — |
| other_tank (0) | — | — | — | — | — | — |

### Main dimensions and counts against truth

Printed exam values only; the frozen 0.005 m dimension tolerance and exact count rules are unchanged. The sheet prints LBP, B and D but **does not print LOA**. Thus six LOA abstentions are the correct reader behaviour for an unprinted value, although the requested comparison against geometric truth scores them as abstentions rather than correct answers.

| Exam field | Correct / 6 | Wrong | Abstained |
|---|---:|---:|---:|
| loa_m | 0 | 0 | 6 |
| lbp_m | 6 | 0 | 0 |
| breadth_m | 6 | 0 | 0 |
| depth_m | 6 | 0 | 0 |
| cargo_holds | 6 | 0 | 0 |
| cargo_hatches | 6 | 0 | 0 |
| cargo_cranes | 6 | 0 | 0 |

Printed dimensions: 18/24 correct, six abstentions, zero wrong. Counts: 18/18 correct, zero abstentions or wrong. Correct crane counts do **not** mean crane boxes were retained.

Measured dimensions are separate from exam answers. Against geometric truth:

| Measured field | Returned / 6 | Median absolute error (m) | Worst absolute error (m) |
|---|---:|---:|---:|
| loa_m | 5 | 0.050 | 0.080 |
| lbp_m | 1 | 0.010 | 0.010 |
| breadth_m | 5 | 0.040 | 0.070 |
| depth_m | 5 | 0.040 | 0.060 |

Measured LBP is returned once despite no A.P./F.P. marks on these generated sheets: the scale reply correctly says the marks are absent, but a later extents reply inserts A.P./F.P. at frame endpoints. Its close numeric result does not establish valid provenance. Five ships establish a frame scale; one has no measured dimensions or extents.

### Three largest observed error causes

1. **Scale crop loses the printed spacing.** One tanker returns no spacing in all three built-in scale attempts (`no frame spacing is printed`), so all 31 truth spaces are missed, including ten cargo tanks. The generator prints a spacing note in the sheet header; the scale task crops views. Successful replies on other ships describe the spacing as cut at the crop's top edge. This is a crop/coverage failure, not a transport failure. It alone accounts for 31/58 missing truth spaces. No rerun was made.
2. **Valid abbreviations are filtered or merged as fragments.** All 12 crane truth boxes are lost as cranes: `CR.n` is demoted by `coarse_kind_not_in_text` / `fine_kind_not_in_text`, despite correct counts. Complete `NO.n DB W.B.` labels are dropped because `W.B.` is treated as a cut prefix of wing-tank labels. Wider re-reads can place several labels in one crop; uncertain projection boxes then combine distinct tanks. This removes ballast coverage and creates wrong-kind or duplicate boxes. The worst matched ballast face is 7.390 m: an all-guessed port-side box overlaps a double-bottom target and qualifies under positive-overlap matching. A match is not proof of correct identity.
3. **Missing plan breadth falls back to a generic breadth.** All 15 matched accommodation tiers have guessed breadth; median side-face error is 2.295 m, worst 2.925 m. The sheet explicitly says the three tiers have the same breadth, but the cross-view join does not supply it for these entries. Double-bottom breadth can likewise be guessed too wide (up to 3.925 m per face). Low median tank errors must be read with omissions and guessed-axis counts, not in isolation.

### Checks, evidence and limits

- Release build exit 0; pinned executable SHA256 `ea22b946260894dd0de6dc6db4598443432e1a8dd7f45b2db2c42c4c8bfd2042`.
- Input manifest: all 12 hashes match; inputs folder contains exactly six PNGs and no truth. Sheet format inspected. No sealed or holdout data opened.
- Full GA/reporting tests: 300 passed. Required quick tier exit 0: Rust format/clippy/workspace tests passed; Python 2334 passed, 4 skipped, 87 deselected, 5 warnings; UI 275 passed; bounded secret scan zero findings.
- Reporting tests also pass after final aggregation. Reader, generator and scorer source diff is empty. No threshold changed, no result-driven rerun, no engineering acceptance claim. `engineering_approved` remains false.
- Per-ship outputs and aggregate JSON remain under `/Users/jonathanjie/Documents/workspace/MarinaFrame/work/ga-synthetic-run/seed17-first/`; run driver and cap guard are in this worktree's ignored `work/ga-synthetic-run/`. Reporting code: commit `95c4d95`.
- `scripts/ga_replay_scale.py` was read but not used: its CLI glob selects `GA-*`, not `SYN-GA-*`. The live driver used the same existing arrangement builder directly. There was no offline replay that changed a model response.

## Resume point

Measurement, scoring and local checks are complete. No further model calls are authorized by this run. Delivery branch: `lane/ga-synthetic-run` only; do not merge. PM follow-up: triage the recorded export/status-contract defects, scale-crop coverage, abbreviation/fragment rules and breadth joins in a separate code lane. Raw integration defects remain unfixed by design. Retain shared Rust cache; no worktree-local `target/` exists.
