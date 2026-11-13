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

## Resume point
Gates written; commit this file before implementing or checking gates. Next: write synthetic lane tests, then implement independent module. G2 real-ship reconstruction and empirical published-formula coefficients still require accessible public sources; do not claim them complete.
