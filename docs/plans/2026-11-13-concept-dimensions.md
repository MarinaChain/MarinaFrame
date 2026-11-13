# Concept dimensions implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build requirements, fleet-based dimension ranges and reference comparison for tanker concept design.

**Architecture:** An independent `concept_dimensions` Python package accepts explicitly supplied public fleet rows. It uses log-linear DWT regressions and nearest neighbours, with training residual envelopes and explicit extrapolation warnings. No other batch module is imported. No bundled fleet is silently used.

**Tech Stack:** Python dataclasses, NumPy, pytest. SI storage; knots also stored as m/s.

## Plan review before implementation
- Architecture PASS: one isolated module; no lane dependencies or platform APIs.
- Quality WARN: public source access is unavailable here; never invent ship particulars or formula coefficients.
- Coverage PASS: validation, deterministic ranking, constraint infeasibility, missing data, provenance, held-out exclusion and regression recovery are separately testable.
- Performance PASS: one small matrix fit and linear reference scan; explicit minimum sample size.

## Frozen gates (commit before checks)
1. **G1 unit gate:** all lane tests pass. Tests use synthetic data, not evidence of real-ship accuracy. Require finite positive inputs, unique ship IDs, explicit Lpp basis, physical dimensions/Cb, training exclusion, reproducible fits, deterministic references, complete quantity metadata, honest missing fields and constraint flags.
2. **G2 reconstruction gate:** reserve public fleet ships `DHT Harrier` and `DHT Falcon` before any fleet fitting. Neither ship nor its sister design may occur in training. At least 10 independent training designs spanning the two reserved DWTs; no restricted benchmark or pilot data. Fit once; pass if all four built values Lpp, B, T and Cb lie within the proposed ranges for both ships (2/2, 100%). Bands are training maximum absolute log residual plus fixed floors: Lpp/B/D/T 10%, Cb 5%; no widening after scoring. Cargo and speed inputs must match the published loading basis. This is a withheld-fit test, not a claim of independent blind evaluation. If particulars or Cb are unavailable, report NOT RUN, not pass. Store the freeze and third-party source manifest under the main ignored `work/concept/` folder.
3. **G3 formula cross-check:** implement Froude number and the displacement identity from preliminary design methodology (Papanikolaou, *Ship Design: Methodologies of Preliminary Design*, 2014; Watson, *Practical Ship Design*, 1998; Schneekluth and Bertram, *Ship Design for Efficiency and Economy*, 2nd ed., 1998). Do not label identities as independently calibrated published dimension regressions. A checked edition/page and coefficients are required before adding empirical design formulas. Missing access means this portion remains incomplete.
4. **G4 quick tier:** run `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`; report actual failures without changing unrelated modules. Run in background. No wall-clock cap on own code.
5. **G5 delivery:** clean branch diff, only lane-owned files, commit and push `lane/concept-dimensions`, no merge. Delete only this worktree's `target/` as last step; never delete shared build output.

## Tasks and checks
1. Create `tests/test_concept_dimensions.py`: synthetic log-linear fleet and fixed physical edge cases. Run with `PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m pytest -q tests/test_concept_dimensions.py`; expect initial import failure.
2. Create `src/vessel_reconstruction/concept_dimensions/__init__.py`: frozen typed requirements, fleet particulars, quantity/range/reference/result types; explicit validation and `to_record_fragment()`.
3. Implement fit, residual bands, nearest-neighbour DWT/cargo/speed comparison, constraints without clipping uncertainty, and preliminary physical checks. Re-run lane tests.
4. Add `scripts/concept_dimensions.py`: JSON fleet/requirements input, explicit excluded IDs, deterministic JSON output. Keep downloaded content and table outside git. Add small cited incomplete sample only; do not fill unknowns from memory.
5. Run G1, G3 and G4. Record G2 as not run if source access remains blocked. Review readability and evidence, commit results and push.

## Initial source-access observations
- Public web search returned no results on two tanker particulars queries.
- Fleet URL `https://www.dhtankers.com/fleet/`: WebFetch socket closed; curl TLS failure; unbrowse reports no configured API key. No API key or environment setting changed.
- Existing public KVLCC2 particulars are documented in `docs/plans/2026-11-12-performance-baseline-results.md` (only the already-exposed particulars paragraph was searched). Do not read unrelated measured or blind results.

## Results and use
- Gates frozen in `7dd99fa` before implementation. G1: **38 lane tests pass** (synthetic only). Initial run failed at the missing module; CLI test also failed before implementation. Null required fleet fields were found by edge tests and then rejected explicitly.
- Independent module: typed requirements, complete fleet rows with source/design IDs, DWT log-linear regressions for Lpp/B/D/T/Cb, fixed residual bands, independent-design deduplication, sister-design exclusion, nearest-neighbour envelopes, source-linked difference tables, port-limit checks without clipping statistical bands, explicit extrapolation/missing-data warnings, and plain JSON fragments. Power/fuel/payload are unknown, never inferred from DWT.
- G2 **NOT RUN**: 0 public fleet fits, 0 held-out ships scored. Frozen selection is `DHT Harrier`, `DHT Falcon`; required joint coverage remains 2/2 (100%). No threshold changed. Freeze and empty-download manifest: main checkout `work/concept/concept-dimensions/{freeze,manifest}.json`. No downloaded third-party files exist.
- G3 **PARTIAL**: displacement identity and Froude number have numeric tests. Published empirical formula coefficients/page citations are **not implemented**; the three books are methodology references only, not proof of formula reproduction. A small second-hand, explicitly incomplete public KVLCC2 sample is in `docs/plans/2026-11-13-concept-dimensions-sample.json`; it is not training eligible.
- G4 first attempt failed in `tauri::generate_context!`: shared build cache had no local `app/ui-release`. Re-triggered the existing local build script by touching `app/src-tauri/build.rs` (no content change). Retry completed: Rust 318 passed / 0 failed / 50 ignored; Python 2,572 passed / 1 failed / 4 skipped / 92 deselected. The one failure was this lane's CLI subprocess importing the main installed package without the worktree source path. Fixed the subprocess environment explicitly, then all 38 lane tests passed without a shell PYTHONPATH. UI checks and secret scan passed separately. Final complete quick tier **PASS (exit 0)**: Python 2,579 passed / 4 skipped / 92 deselected (5 upstream deprecation warnings); UI 275 passed / 0 failed; bounded secret scan 1,330 tracked text files / 0 findings; Rust format, clippy and workspace tests passed. Evidence: ignored `work/concept/concept-dimensions/quick-final.log`.
- Elegance review: kept one calculation module, one CLI and one test file; no new runtime dependency or coupling to other lanes. Incomplete rows fail before fit; unknown optional comparisons remain null with reasons. Structural summary scan completed for this worktree, but the helper then failed with `ModuleNotFoundError: render_bootstrap`. Removed its newly generated untracked `.codesight/` output instead of committing whole-repository summaries or changing global tooling.

Run with a source-linked fleet JSON array and requirements JSON object:

```sh
PYTHONPATH=src /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python scripts/concept_dimensions.py \
  --fleet /absolute/path/to/public-fleet.json --requirements /absolute/path/to/requirements.json \
  --exclude-ship 'DHT Harrier' --exclude-ship 'DHT Falcon'
```

Focused review fixes: unresolved excluded ship IDs now fail closed (when reserved ship rows are intentionally absent, supply explicit frozen sister-design IDs instead). Numeric validation rejects booleans and strings. `port_limits_within_ranges` reports only the marginal port checks; overall `feasible` remains null unless a port limit excludes the range, in which case it is false. The failing regression tests were run before each fix; no coverage threshold was changed.

All complete fleet rows require: `ship_id`, `design_id`, `dwt_t`, `lpp_m`, `beam_m`, `depth_m`, `draft_m`, `cb`, `sources` (array). Optional: `cargo_volume_m3`, `service_speed_kn`, `cargo_types`; `length_basis` is `lpp` only. Cb/draft/DWT must describe one loading basis. Give all sisters one design ID. Missing records can be inventoried separately but cannot train. `MIN_DESIGNS=4` permits synthetic/development operation; G2 still requires 10 independent designs. Dimension regressions depend only on DWT; cargo/speed affect ranking, not capacity or propulsion feasibility. No fleet data is silently loaded.

## Resume point
G4 passed. Implementation commits: `a5e8130`, review fixes `81df4aa`, frozen gates `7dd99fa`. Delivery target is only `origin/lane/concept-dimensions`; no merge. Local `target/` cleanup follows push; shared build output is preserved. To finish the engineering exit gate later, acquire public fleet particulars with matching Lpp/loading/Cb and full citations, isolate each download in a new directory, record URL/date/SHA-256, and exclude the frozen ships and all sister designs before fitting. Obtain checked editions/pages for empirical design cross-checks. Do not call this lane a completed real-ship reconstruction until the unchanged G2 gate has been run. PM must review data and map the fragment to the canonical design record after the design-record lane merges.
