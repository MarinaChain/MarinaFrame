# Synthetic GA Truth Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate six seeded commercial GA sheets and separate exact box truth, with an offline arrangement scorer.

**Architecture:** Use metre-space boxes as the source for all projections. Reuse concept-launch View/Sheet primitives, the factory lines renderer's text helper, and ga_arrangement's frame and extent conversion. Keep model inputs in images/ and truth in truth/; no reader or model calls.

**Tech Stack:** Python, Pillow, NumPy, SciPy, pytest.

---

## Design review
- Architecture: PASS. Separate generator, renderer and scorer; no product changes or CAD build needed.
- Quality: WARN. Geometric matching must not depend on IDs or labels. Use maximum-cardinality one-to-one same-kind matching with a fixed positive-volume overlap rule, then minimum mean face error. Record this before runs; do not tune it against results.
- Tests: PASS. Cover deterministic seeds, all six cases, box validity, pixel generation, frame conversion, exact and perturbed scoring, omissions, inventions, duplicates and missing extents.
- Performance: PASS. Six small arrangements; assignment matrices are small. No model calls.

## Task 1: Seeded arrangements and three-view renderer
Files: create benchmarks/ga_synthetic/{__init__,generate,render,__main__}.py and tests/test_ga_synthetic.py.
1. Add generator tests: stable same seed, different alternate seeds, six cases, every box has ordered finite metre faces, required kinds present.
2. Run focused pytest; expect import failure before implementation.
3. Generate two bulk carriers, two tankers and two general-cargo ships. Frame-aligned cargo bays, double-bottom and wing ballast tanks, peaks, engine room, three deckhouse tiers; dry cargo ships have hatches/cranes, tankers have paired cargo tanks.
4. Draw profile, upper deck and tank-top projections with frame ticks, labels, frame-spacing note and dimension chain. Save only images to images/; save schema, seed, dimensions, frame table and exact box faces separately in truth/.
5. Add CLI generate, reject existing output folders, and write SHA256SUMS. Run focused tests and quick tier; commit.

## Task 2: Offline scorer
Files: create benchmarks/ga_synthetic/score.py; extend tests/test_ga_synthetic.py and __main__.py.
1. Test exact output (zero error), changed face (known metres), omitted and extra spaces, arbitrary IDs, reordered spaces, duplicate predictions, frame extents and missing extents.
2. Run focused pytest; expect import failure before implementation.
3. Convert readings with ga_arrangement.load_input/hull_size/item_box. Match by kind with positive 3D overlap. Report signed six-face errors and absolute mean/max per kind; found fraction and unmatched truth/read spaces. Missing extent is unmeasured, not a successful match. Report guessed axes separately.
4. Add score CLI. No acceptance threshold or model invocation.
5. Run focused and quick tests; commit.

## Task 3: Samples and closeout
1. Generate six cases under ignored work/ga-synthetic-truth/; inspect sheet images. Do not open holdout or sealed folders.
2. Document commands, truth schema, matching limits, sample locations, tests and commits here.
3. Run demand-elegance and completion checks. Push only lane/ga-synthetic-truth, no merge.
4. Inspect local target/ and delete only that worktree build folder if present. Never delete the shared cache.

## Usage and truth contract

Generate (from this worktree):

```sh
PYTHONPATH=src:. /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m benchmarks.ga_synthetic generate --seed 17 --out work/ga-synthetic-truth
```

The output folder must not exist. `images/` contains only six PNGs, each 3960 x 2800. Only these PNGs may be sent to a future reader. `truth/` contains one JSON per case, schema `marinaframe.ga_synthetic_truth.v1`: case ID, seed, ship type, false engineering flag, axes, principal dimensions, frame-spacing spans, a complete frame-to-x table, and spaces (`id`, printed `label`, vocabulary `kind`, frame ends, and `box_m` with ordered x/y/z pairs in metres). The exact target is the design box, not a hull-clipped volume or presentation inset. `SHA256SUMS` covers images and truth. These are fictional box arrangements, not structurally complete ship designs.

Score an existing arrangement input without reader/model calls:

```sh
PYTHONPATH=src:. /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python -m benchmarks.ga_synthetic score --truth work/ga-synthetic-truth/truth/SYN-GA-001.json --reading work/reading.json --out work/score.json
```

Score output schema is `marinaframe.ga_synthetic_score.v1`. Each matched pair carries reading/truth IDs, kind, six signed face errors (reading minus truth, metres), and guessed axes. Per-kind summaries give counts, found share, mean/max absolute face error, absolute mean for each face, and missing/invented IDs. Global missing, invented and unmeasured lists remain separate. No extent means unmeasured, not found. Provided extents can include inferred y/z; the existing arrangement rules supply these and the score marks those axes guessed. Unknown kinds are inventions. IDs must be unique. Case IDs must agree; no non-finite box faces are accepted.

Matching does not use shared IDs or labels: same-kind boxes must overlap by positive volume. It maximizes pair count before minimizing face error. A badly misplaced non-overlapping box counts as both missing and invented; any small positive overlap can match, so found share is not an accuracy gate. Face errors must be read with recall and invention counts. There is no engineering pass/fail threshold. Do not tune this rule after reader results.

## Results (in progress)
Seed 17 generates two cases per type: bulk carrier, tanker, general cargo. Counts by case are 29, 31, 23, 29, 31, 35 (178 spaces). Sample images and truth are in this worktree's ignored `work/ga-synthetic-truth/`; no drawing or derived data is committed. Generator tests: 2 passed. Combined generator/scorer tests: 6 passed. Initial quick tier stopped on missing ignored `app/ui-release`; copied local static UI there and reran. Full quick tier and fresh review pending. No GA reader run and no model calls.

## Resume point
Generator and scorer implemented; samples generated. Await quick tier and fresh review, address findings, commit in two small steps, then push lane only. All Rust commands must set CARGO_TARGET_DIR=/Users/jonathanjie/Documents/workspace/MarinaFrame/.claude/worktrees/shared-target-sol. Python checks use /Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python with PYTHONPATH=src:. and MARINAFRAME_TEST_PYTHON set inline. No model calls are permitted.
