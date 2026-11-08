# Benchmark factory (W2)

Date: 2026-11-07. Base: `a2608e1` (branch `continue/v0.5`). Frozen code for all runs: **`64a434d`**
(worktree branch, clean tree, controller SHA-256 `2596135e…217b`). Host: macOS arm64, Python 3.12,
CadQuery 2.7.0. Every candidate keeps `engineering_approved=false`.

## 1. Question

How does the deterministic Rust pipeline (`marinaframe run --policy deterministic`) perform on a
large, reproducible set of body-plan drawings whose true hull geometry is known exactly, under
controlled drawing degradation, with sealed splits by hull family? Result in one line: on 1,080
rendered drawings the pipeline built a hull for **12** (1.1 %), abstained on **1,041** and failed on
**27**. Where it built, the hull is accurate on clean drawings. The pipeline is conservative to the
point that accuracy cannot yet be measured at scale. Section 6 gives the tables.

## 2. Method

`benchmarks/factory/` (all commands run from the repository root):

| Step | Command | Output |
|---|---|---|
| 1 | `python -m benchmarks.factory.generate hulls` | canonical hull meshes and native shapes, sealed truth tables, `manifests/hulls.json` |
| 2 | `python -m benchmarks.factory.generate render` | `inputs/<case>/{drawing.png,spec.json}`, `params/<case>.json` |
| 3 | `python -m benchmarks.factory.generate freeze` | `manifests/cases.jsonl`, `manifests/split_manifest.json` (hashes) |
| 4 | `python -m benchmarks.factory.runner --run NAME --split S --jobs 2` | `runs/NAME/<case>/result.json`, `model.step` |
| 5 | `python -m benchmarks.factory.report score --run NAME` then `report table --run ... --out F.md` | `score.json`, tables |

Folders are under `work/factory/` (git-ignored). Sources are read from `work/sources/` (link it first).
Everything is a pure function of code and sources; seeds are in `splits.py` (`SEED`) and per case
(`case_seed`, a hash of the case id).

**Hulls and truth.** Every hull is scaled uniformly to a length of 100 m and put in one frame (x from the
aft end, z up from the lowest point). Named hulls (KCS, KVLCC1, KVLCC2, DTMB 5415 from SIMMAN IGES; Series 60 and
Wigley from the FreeCAD BRep; 59 Delft yacht hulls from DSYHS IGES) are exact CAD surfaces. The drawn curve of a
station is an exact OpenCascade plane section (`hulls.exact_section`), cut 0.1 mm inside the station to avoid
duplicate edges on face boundaries. Truth is the fine tessellation of the same shape (chord deviation 0.5 mm).
Ship-D has no exact surface in the dataset code. The dataset's own published generator
(`HullParameterization.gen_stl`, 160 water-lines x 800 points; run locally, `numpy-stl` replaced by a stub because
no STL is written) makes the mesh, and drawings and truth both come from that mesh. **The factory measures how well the
pipeline recovers the drawn geometry. It does not measure how well a source model matches a real ship.**
Per-hull provenance (source file, SHA-256 of archive and member, URL, licence record, Ship-D set and row, parameter
hash) is in `manifests/hulls.json`.

**Truth folder.** `sealed/truth/<hull>.npz` holds the half-breadth and occupied width of each hull on a common grid (x every
0.5 m, 250 equal steps in z) plus the volume and waterplane at the stated draft. The runner and the drawing/spec files
never read it (`inputs/<case>/` has only `drawing.png` and `spec.json`). Station positions are on the truth grid.

**Stations.** 9 stations at 10 %, 20 % ... 90 % of the length. The deck-lid line of closed CAD hulls is removed so the drawn curve
ends at the deck edge. Terminal closure is `flat_at_terminal_stations`, as the product requires.

**Specification.** ROI, scale, centreline column, baseline row, z range 0 to the hull top, station x, symmetry. No offsets or
answers (the test `tests/test_factory.py` checks the spec against the product's own validator).

## 3. Realism knobs

Every parameter and seed of every drawing is stored in `params/<case>.json` and, in short, in `manifests/cases.jsonl`.
Four degradation levels set the ranges (`render.LEVELS`); each parameter is drawn uniformly from its range.

| Knob | 0 clean | 1 mild | 2 moderate | 3 heavy |
|---|---|---|---|---|
| Resolution (scale on px/m) | 1.0 | 0.9-1.0 | 0.75-0.95 | 0.5-0.8 |
| Hull line weight / tone | 3 px / 15 | 2-4 px / 20-50 | 1.5-4 / 30-80 | 1.5-3 / 50-110 |
| Grid (water-lines, buttocks) tone, width | 205, 1 px | 170-210 | 130-180, 1-2 px | 90-140, 1-2 px |
| Centreline | light solid | light or dash-dot | dash-dot or solid | solid or dash-dot, dark |
| Paper tone, uneven light | white, none | cream, 2-5 % | grey-yellow, 5-10 % | dark, 10-18 % |
| Rotation, shear | none | +-0.2 deg, 0.001 | +-0.6 deg, 0.003 | +-1.2 deg, 0.008 |
| Blur sigma (px) | 0 | 0.4-0.7 | 0.8-1.2 | 1.2-1.9 |
| Scan noise sd, speckles per Mpx | 0 | 2-4, 20-60 | 4-8, 80-200 | 8-14, 200-500 |
| JPEG quality (decoded back to PNG) | none | 88-95 | 60-80 | 35-55 |
| Section tag inside the ROI (probability) | 0 | 0.25 | 0.6 | 1.0 |
| Occlusion patches (tape, stamp, stain) | 0 | 0 | 0-1 | 1-2 |
| Calibration read error (px, centreline and baseline) | 0 | 0 | up to 0.5 | up to 1.5 |

Always drawn: water-line and buttock grid with labels, baseline, centreline, station labels or titles outside the ROI.
Order of degradation: paper and light, rotation and shear, blur, noise, speckles, occlusion, JPEG. Rotation is handled the way an
operator would: the datum is declared at the middle of each ROI (the spec has no tilt field).

**Layouts.** `separate` (80 % of hulls): one starboard half section per panel on a sheet, ROI holds one curve. `overlay` (20 %,
chosen per hull by hash, so all four levels of a hull share a layout): the classic body plan with one centreline, afterbody left,
forebody right, station numbers at the curve tops; the sheet is cut into a forebody panel and a mirrored afterbody panel (as
the Gunnerus raster path does), and each section ROI is the whole panel, which holds 4 or 5 curves.

## 4. Splits (frozen before any scoring)

`manifests/split_manifest.json` records the SHA-256 of `cases.jsonl` and `hulls.json` (which carries the truth hash of every hull);
`cases.jsonl` has the hashes of every drawing, spec, parameter file and truth table. A family is never split.

| Split | Families | Hulls | Cases |
|---|---|---:|---:|
| development | 26 Ship-D clusters, DTMB 5415, Series 60, Wigley | 132 | 528 |
| validation | 9 Ship-D clusters, Delft yacht series (one family, 48 hulls with usable sections) | 90 | 360 |
| sealed test | 9 Ship-D clusters, KCS, KVLCC1, KVLCC2 (each its own family; KVLCC1 and 2 are relatives and stay together) | 48 | 192 |

Ship-D families: the 30,000 feasible hulls of the three constrained random sets were clustered on their 45 parameters
(standardised, k-means++, k = 44, seed in `splits.py`); 5 hulls per cluster were taken (the first 5 of 9 shuffled candidates that gave
usable sections on all 9 stations). The diffusion-augmented sets were not used. 53 candidate hulls were skipped as infeasible
(listed in `hulls.json`). One deviation from the brief: the Delft series (59 hulls) is one family rather than 59, because its hulls are
variations of parent forms.

### Sealed split v2

Replacement holdout: **hull-disjoint (v2)**, generated 2026-11-08. **Clusters can share broad families with the frozen splits; this is not family-disjoint.** All named families were already used, so only Ship-D is included.

A new fixed-seed partition (**20261108**, 256 standardised-parameter k-means++ clusters) excludes every cluster containing a previously rendered hull, plus prior rejected candidates. Nine unoccupied clusters (122, 88, 31, 176, 120, 221, 217, 182, 212) supply four feasible hulls each. Each of the **36 hulls** has both layouts and all four degradation levels: **288 drawings**, 36 per layout/level cell (144 separate, 144 overlay; 72 per level).

Frozen manifests, full selection parameters and protocol: `benchmarks/factory/manifests/sealed-v2/README.md`. `split_manifest.json` SHA-256: `856a37fad69439cd9fc83a75382699d5988323c0aa68ed9b1eaf66fcfdef81d3`. Drawings/specs are in ignored `work/factory-sealed-v2/inputs/` (350.9 MiB); truth is separate in `work/factory-sealed-v2/sealed/truth/` (13.5 MiB), never read by inference. The original loader, truth builder and renderer are unchanged.

**Score only at frozen checkpoints**: deterministic abstain vs deterministic draft vs LLM-first; never during development. Generation was checked by hashes, spec validation, complete truth tables and Read-tool samples at all four levels. No pipeline or scorer was run on v2 and no reader output was inspected.

### Sealed split v3

v2 is spent for model selection. **hull-disjoint (v3)**, generated 2026-11-08 for the next pre-registered evaluation (W17/W18), uses seed **20261201** and the frozen v2 partition. It excludes every v1 and v2 hull and rejected candidate and every cluster that holds one (so it is cluster-disjoint from v2), and it uses no v1 family (k=44) that holds a v2 hull. It is **not family-disjoint from v1**: v1 used all 44 families. Nine clusters (28, 249, 181, 110, 48, 174, 136, 161, 239) × 4 hulls = **36 hulls, 288 drawings**, same layouts, levels and gate.

Manifests and the disjointness table: `benchmarks/factory/manifests-sealed-v3/README.md` (outside `manifests/`, so v2 verification is unchanged). `split_manifest.json` SHA-256: `4b81c182462b03ae71ca38c70d400cb6a0f879e05aa0034914a9982dc904bb76`. Data only in the main checkout's ignored `work/factory-sealed-v3/`. A second generation was byte-identical. No inference or scoring was run, and truth was checked by hash only.

## 5. Protocol actually followed

1. Metrics, generator and splits written; scorer checked on a box hull with a cadquery STEP (`tests/test_factory.py`, mark `cad`).
2. A pilot of single drawings on development hulls only (Wigley, Series 60, DTMB 5415, Ship-D) was used to debug the renderer. The sealed hulls were
   rendered but the pipeline was **not** run on them before the freeze.
3. Frozen manifest written; code committed (`64a434d`); development, then validation, then the sealed test were run **once** each with that commit.
   After the runs no renderer, runner or scorer code was changed.
4. Failure analysis (section 7) used development and validation outcomes plus one kept-task rerun of two development cases.
   Those reruns are not in the tables.

Run times (wall clock): development 6,048 s with 3 native jobs (528 cases); after the coordinator asked for lower load, validation 4,826 s and the
sealed test 2,426 s with 2 jobs (median case 13 s and 11 s). Sums of case times were 17,983 s, 9,641 s and 4,805 s. The development run
had 5 `interrupted` and 1 `protocol_error` results while the machine was overloaded (load average above 30); these are kept as failures.
Task folders were deleted after each case; `model.step` and `result.json` are kept in `runs/`.

## 6. Results

"Correct" gate, fixed before any run and never changed: built, scored, RMS of station half-breadth errors (main band, bottom to hull top)
at most 2 % of the hull's half-beam, and volume error below the design draft within the reconstructed range at most 5 % in magnitude.
Draft T = 0.6 x hull depth. Metric functions are those of `docs/BENCHMARK_GUNNERUS.md` section 3 (`benchmarks/gunnerus/hull_metrics.py`);
two grids are scaled to the hull (z: depth/250; x: every 0.5 m, and every truth cut inside the model counts as "between stations").
Abstention is a separate outcome: not a pass and not a failure. Full tables (by level, layout, level x layout, family, and with p90) are in
`benchmarks/factory/results/accuracy_tables.md`; one row per case in `case_outcomes.csv`.

### All splits, by degradation level

| Split | Level | Attempted | Built | Abstained | Failed | Correct / attempted | Correct / built | Station RMS median, mm | Volume error in range, median |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| development | 0 clean | 132 | 4 | 122 | 6 | 4/132 | 4/4 | 31.2 | 0.85 % |
| development | 1 mild | 132 | 0 | 128 | 4 | 0/132 | 0/0 | - | - |
| development | 2 moderate | 132 | 0 | 131 | 1 | 0/132 | 0/0 | - | - |
| development | 3 heavy | 132 | 0 | 129 | 3 | 0/132 | 0/0 | - | - |
| validation | 0 clean | 90 | 1 | 82 | 7 | 1/90 | 1/1 | 210.3 | 1.08 % |
| validation | 1 mild | 90 | 1 | 89 | 0 | 0/90 | 0/1 | 448.9 | 27.45 % |
| validation | 2 moderate | 90 | 0 | 90 | 0 | 0/90 | 0/0 | - | - |
| validation | 3 heavy | 90 | 0 | 90 | 0 | 0/90 | 0/0 | - | - |
| **sealed test** (run once) | 0 clean | 48 | 6 | 38 | 4 | 6/48 | 6/6 | 34.1 | 1.05 % |
| sealed test | 1 mild | 48 | 0 | 47 | 1 | 0/48 | 0/0 | - | - |
| sealed test | 2 moderate | 48 | 0 | 48 | 0 | 0/48 | 0/0 | - | - |
| sealed test | 3 heavy | 48 | 0 | 47 | 1 | 0/48 | 0/0 | - | - |
| **sealed test** | all | 192 | 6 | 180 | 6 | 6/192 | 6/6 | 34.1 | 1.05 % (p90 1.53 %) |
| all splits | all | 1,080 | 12 | 1,041 | 27 | 11/1,080 | 11/12 | | |

(Counts in the last row: abstained 510 + 351 + 180 = 1,041; failed 14 + 7 + 6 = 27; built 4 + 2 + 6 = 12.)

By layout: `overlay` (216 cases): 0 built. `separate` (864 cases): 12 built, all at level 0 except one at level 1.

By family (sealed test): KCS 0/4, KVLCC1 0/4, KVLCC2 0/4 built (all abstained); the 9 Ship-D test clusters 6 built of 180. Development: Wigley 1/4 built;
DTMB 5415 and Series 60 0/4. Validation: Delft series 1 built of 192, 0 correct (see below).

Accuracy where built (sealed test, 6 cases, all clean Ship-D, separate layout): station half-breadth RMS median 34 mm (0.32 % of the half-beam),
maximum error median 2.7 % of the half-beam (near the keel, where a small height offset gives a large breadth difference), volume
below T within the modelled range 1.05 % median (p90 1.5 %), volume against the whole hull 10.2 % low (flat caps at stations 10 % and 90 % cut off the ends; this is
the definition from the Gunnerus benchmark), waterplane in range 0.66 %. Development (4 built): RMS median 31 mm (0.21 %), volume in range 0.85 %. The 31-34 mm
station error is about 1 to 2 pixels (about 15 to 30 mm per pixel at the clean-level scale).

One silent wrong build exists: validation `sysser45-L1` (Delft yacht, mild degradation) was built and passed the controller's checks, but five of nine stations follow
a wrong stroke (RMS 449 mm, 3.9 % of half-beam; stations 2-4 have maxima above 5 m and volume in range is 27 % off). It is not "correct" by the gate and it counts in the built column.

## 7. Failure modes

Counts over the 1,068 cases that did not build (all splits; classification from the recorded inspection data; per-case entries in `result.json`):

| Mode | Cases | Evidence |
|---|---:|---|
| Section has no selectable candidate | 369 | inspected sections list zero selectable contours |
| Several candidates and none unique | 300 | sections hold 2-3 selectable hypotheses (all-contrast, high-contrast, retained alternative); `unique_non_grid_candidate_id` absent |
| Inspection worker error | 303 | only at levels 1 and 2. Reproduced on dev `shipd-3-00262-L1` (this run only; not in the tables): `DrawingError resource_limit` ("Contour candidate complexity exceeds the bounded tracing budget; select a smaller panel") on 6 of 9 sections and `ambiguous_curve` ("Multiple sustained source strokes remain plausible across contrast bands") on 3. Paper tone and noise raise contrast-band complexity. |
| `source_or_geometry_operation_failed` | 69 | a later step failed after selection; the policy abstained |
| Blocked, `source_ambiguity_requires_explicit_operator_selection` | 21 | status `blocked`, counted as failed |
| Worker not started / interrupted, protocol error | 6 | overloaded machine, development run only |

Overlay layouts abstain by design: the policy accepts a section only when exactly one contour hypothesis exists, and a panel with 4-5 station curves
cannot satisfy that. `abstain_overlay_series60_L0.png` (checked with the Read tool) shows the retained candidates for the clean Series 60 overlay `series60-L0`:
the green and red candidates lock onto the nearly coincident station curves 5 and 6 (and a short piece between them), so identity cannot be decided.

Pattern by level: all 12 builds are level 0 except one level 1. Levels 2 and 3 produced no build in 540 cases. Sample drawings of levels 1-3 were
inspected (Read tool) and are legible to a person; the product's raster path is not tolerant of texture, tone, rotation and noise at these ranges. This is a finding about the
product at its current gates, not about the factory. The gates were not widened.

What this does not show: accuracy of the built hulls at levels 1-3 (no data), accuracy of the deterministic path with operator-supplied `contour_selection`
corridors (not used, because a corridor would have to come from truth or a person), and any live-policy result (not run).

## 8. Limits and cautions

- Ship-D hulls are parameter-space hulls, many not ship-like (beam up to 0.6 of length, tumblehome, bulb sections in two pieces). They give breadth of shapes, not realism. Named hulls give
  realism but only 6 exist, and all 3 test named hulls abstained at every level.
- The sealed test is dominated by Ship-D (180 of 192 cases). Its result must not be read as a result on real ships.
- Truth for Ship-D carries the mesh chord error of the generator (a few mm); truth for exact hulls carries 0.5 mm.
- Calibration is declared from the exact drawing geometry (with the read error of the level). A real operator is less exact.
- Station spacing, 9 stations, and `flat_at_terminal_stations` make full-hull volume 10 % low by construction; use "in range" figures for pipeline error.
- The development run used 3 native jobs while the machine was overloaded; its 6 interrupted/protocol failures are not typical.
- The scorer reuses the Gunnerus metric functions but is a separate implementation (`truth.py`); it was checked on a box hull, not against `benchmarks/gunnerus/score.py` on the same inputs.

## 9. Regenerate

```bash
ln -s <main checkout>/work/sources work/sources          # sources, git-ignored
python -m benchmarks.factory.generate hulls               # ~10 min with 3 processes
python -m benchmarks.factory.generate render              # ~4 min
python -m benchmarks.factory.generate freeze              # compare with the committed manifests
cargo build --release --locked -p marinaframe-control
python -m benchmarks.factory.runner --run dev1 --split development --jobs 2
python -m benchmarks.factory.report score --run dev1
python -m benchmarks.factory.report table --run dev1 --out dev1.md
```

The frozen manifests must reproduce byte for byte from the same sources and code (image hashes can differ across OpenCV or Pillow builds;
the hull and truth hashes are the first thing to compare). Tests: `make test-quick`; the scorer test is `@pytest.mark.cad`.
Disk: `work/factory/inputs` is 1.7 GB and the hull cache 1.6 GB (deleted after generation; rebuild with the `hulls` step).

## Head-to-head, hull-disjoint (v2)

**Silent wrong builds are reported first:** abstain: 0, draft: 0, llm: 0.

**Decision from the pre-registered rule: deterministic draft becomes the default; LLM-first remains an explicit option.** No app setting was changed by this evaluation.

Protocol: [pre-registration](plans/2026-11-08-h2h-sealed-v2.md). Each arm ran once on all 288 drawings, with two jobs at most. Frozen inference code is `7c2d4f6`, captured from `d9d8609` (only the protocol document differs). DeepSeek uses `deepseek-v4.1-flash`, draft ambiguity mode, the frozen W11 tools and CLI operational defaults, with W12/W14 code present. The W12 `--model-review` veto was enabled for the LLM arm by the resume driver, before any LLM case ran (see deviations). No retries replaced results and no inference settings changed after the first case.

**Broad-family caveat:** Clusters can share broad families with the frozen splits; this is not family-disjoint. These are 36 Ship-D hulls, both layouts, four levels; no named real-ship family is included.

**Restoration note (not a protocol deviation):** Regenerated with unchanged frozen generator after original worktree deletion; frozen manifests and all input, parameter and truth hashes match. No inference/scoring during restoration. Before the first case, this run independently checked all 900 unique drawing/spec/parameter/truth files against the frozen manifests (288 cases, 36 truth tables). Hash checking is separate from inference. Inference received only each drawing/spec input folder; it never opened sealed truth. Each arm was scored only after completion, using the existing independent factory scorer and unchanged 2% RMS half-beam / 5% in-range volume gate. Scoring used the same per-user native admission lock as inference.

Snapshot tree SHA-256: `0ca02b07eeb9dd69d220ce838d06137e8092d43d050cec5abb1a26c93c8359c9`. Controller SHA-256: `6593e6bc65de13cc7c06a380282956e69bb6f69074c7ad6658344655834e9197`. Git archive SHA-256: `2f1ad1a2e76d03fc287d0c54686f5f162c131f34f8e5806a605aaaddbb0e3522`. Manifest SHA-256: `856a37fad69439cd9fc83a75382699d5988323c0aa68ed9b1eaf66fcfdef81d3`.

| Arm / group | Cases | Built | Correct | Silent wrong | Wrong draft | Review-ready | Draft status | Abstained | Blocked | Failed* | Guesses / lines median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| abstain | 288 | 7 | 7 | 0 | 0 | 2 | 0 | 282 | 2 | 4 | 0 / 0 |
| draft | 288 | 75 | 13 | 0 | 62 | 2 | 68 | 218 | 0 | 0 | 9 / 0 |
| llm | 288 | 14 | 9 | 0 | 5 | 0 | 10 | 0 | 0 | 274 | 0 / 0 |

*Failed includes blocked and other non-built/non-abstained outcomes; it overlaps the blocked column. Built counts valid CAD candidates even if the final status is not review-ready. Lines are sections with a selected or guessed source-backed candidate, not correct models. Guesses count open final-state guesses. A missing model is `no_model`, not zero error.

### By layout and level

| Arm / group | Cases | Built | Correct | Silent wrong | Wrong draft | Review-ready | Draft status | Abstained | Blocked | Failed* | Guesses / lines median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| abstain / separate/L0 | 36 | 7 | 7 | 0 | 0 | 2 | 0 | 34 | 0 | 0 | 0 / 7 |
| abstain / separate/L1 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 35 | 0 | 1 | 0 / 0 |
| abstain / separate/L2 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 35 | 0 | 1 | 0 / 0 |
| abstain / separate/L3 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 | 0 / 0 |
| abstain / overlay/L0 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 | 0 / 0 |
| abstain / overlay/L1 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 35 | 1 | 1 | 0 / 0 |
| abstain / overlay/L2 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 | 0 / 0 |
| abstain / overlay/L3 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 35 | 1 | 1 | 0 / 0 |
| draft / separate/L0 | 36 | 13 | 12 | 0 | 1 | 2 | 6 | 28 | 0 | 0 | 1 / 9 |
| draft / separate/L1 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 | 0 / 0 |
| draft / separate/L2 | 36 | 7 | 0 | 0 | 7 | 0 | 7 | 29 | 0 | 0 | 8.5 / 0 |
| draft / separate/L3 | 36 | 4 | 0 | 0 | 4 | 0 | 4 | 32 | 0 | 0 | 9 / 0 |
| draft / overlay/L0 | 36 | 35 | 1 | 0 | 34 | 0 | 35 | 1 | 0 | 0 | 9 / 9 |
| draft / overlay/L1 | 36 | 5 | 0 | 0 | 5 | 0 | 5 | 31 | 0 | 0 | 0 / 0 |
| draft / overlay/L2 | 36 | 9 | 0 | 0 | 9 | 0 | 9 | 27 | 0 | 0 | 9 / 0 |
| draft / overlay/L3 | 36 | 2 | 0 | 0 | 2 | 0 | 2 | 34 | 0 | 0 | 9 / 0 |
| llm / separate/L0 | 36 | 13 | 9 | 0 | 4 | 0 | 7 | 0 | 0 | 23 | 0 / 9 |
| llm / separate/L1 | 36 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 36 | 0 / 0 |
| llm / separate/L2 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 / 0 |
| llm / separate/L3 | 36 | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 35 | 0 / 0 |
| llm / overlay/L0 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 / 0 |
| llm / overlay/L1 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 / 0 |
| llm / overlay/L2 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 / 0 |
| llm / overlay/L3 | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 / 0 |

### Marginal layout and level counts

| Arm / group | Cases | Built | Correct | Silent wrong | Wrong draft | Review-ready | Draft status | Abstained | Blocked | Failed* | Guesses / lines median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| abstain / separate | 144 | 7 | 7 | 0 | 0 | 2 | 0 | 140 | 0 | 2 | 0 / 0 |
| abstain / overlay | 144 | 0 | 0 | 0 | 0 | 0 | 0 | 142 | 2 | 2 | 0 / 0 |
| abstain / L0 | 72 | 7 | 7 | 0 | 0 | 2 | 0 | 70 | 0 | 0 | 0 / 0 |
| abstain / L1 | 72 | 0 | 0 | 0 | 0 | 0 | 0 | 70 | 1 | 2 | 0 / 0 |
| abstain / L2 | 72 | 0 | 0 | 0 | 0 | 0 | 0 | 71 | 0 | 1 | 0 / 0 |
| abstain / L3 | 72 | 0 | 0 | 0 | 0 | 0 | 0 | 71 | 1 | 1 | 0 / 0 |
| draft / separate | 144 | 24 | 12 | 0 | 12 | 2 | 17 | 125 | 0 | 0 | 2 / 0 |
| draft / overlay | 144 | 51 | 1 | 0 | 50 | 0 | 51 | 93 | 0 | 0 | 9 / 0 |
| draft / L0 | 72 | 48 | 13 | 0 | 35 | 2 | 41 | 29 | 0 | 0 | 4.5 / 9 |
| draft / L1 | 72 | 5 | 0 | 0 | 5 | 0 | 5 | 67 | 0 | 0 | 0 / 0 |
| draft / L2 | 72 | 16 | 0 | 0 | 16 | 0 | 16 | 56 | 0 | 0 | 9 / 0 |
| draft / L3 | 72 | 6 | 0 | 0 | 6 | 0 | 6 | 66 | 0 | 0 | 9 / 0 |
| llm / separate | 144 | 14 | 9 | 0 | 5 | 0 | 10 | 0 | 0 | 130 | 0 / 0 |
| llm / overlay | 144 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 144 | 0 / 0 |
| llm / L0 | 72 | 13 | 9 | 0 | 4 | 0 | 7 | 0 | 0 | 59 | 0 / 5 |
| llm / L1 | 72 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 72 | 0 / 0 |
| llm / L2 | 72 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 72 | 0 / 0 |
| llm / L3 | 72 | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 71 | 0 / 0 |

### Model usage, wall time and failures

Arm wall is for the driver session that finished the arm; abstain also ran 65 cases before the interruption.

| Arm | Requests intended / completed / failed / unknown / not sent | Prompt tokens | Completion tokens | List cost USD | Observed cost USD | Arm wall s | Case wall median s |
|---|---:|---:|---:|---:|---:|---:|---:|
| abstain | 0 / 0 / 0 / 0 / 0 | 0 | 0 | 0.00000000 | 0.00000000 | 1719.9 | 8.1 |
| draft | 0 / 0 / 0 / 0 / 0 | 0 | 0 | 0.00000000 | 0.00000000 | 3387.0 | 17.1 |
| llm | 2611 / 2611 / 0 / 0 / 0 | 20,038,411 | 171,563 | 2.89340212 | 0.00000000 | 8427.7 | 32.4 |

List cost is provider-reported nominal usage, not an invoice. Observed cost is the receipt cost field; subscription cost is unknown. Case wall includes native queue waits and provider time. Summed case wall is not elapsed arm wall.

- **abstain failures:** `{"interrupted_by_harness_stop": 2, "source_ambiguity_requires_explicit_operator_selection": 2}`. Score statuses: `{"no_model": 281, "scored": 7}`.
- **draft failures:** `{}`. Score statuses: `{"no_model": 213, "scored": 75}`.
- **llm failures:** `{"open_guesses_block_review": 3, "repeated_identical_action_without_generation_progress": 270, "repeated_refused_proposals": 1}`. Score statuses: `{"no_model": 274, "scored": 14}`.

**Protocol deviations:**

- The first driver process stopped at 05:36 when its router session ended its turn (65 abstain cases done). The two abstain cases in progress (shipd-3-06455-separate-L1, -L2) are counted as failures (`interrupted_by_harness_stop`) and were not rerun. A detached resume driver ran only the cases that had not started.
- The original driver did not pass `--model-review true`, although the pre-registered LLM-first arm includes the W12 veto. The resume driver added it for the LLM arm only, before any LLM case ran.

The dataset restoration preserved the frozen input bytes. The split is now spent for model selection; later tuning requires a new holdout.

Compact per-case rows and all marginal counts, usage, timing and provenance: [`outputs/h2h-sealed-v2/`](../outputs/h2h-sealed-v2/). Full finished task folders remain local under the main checkout’s ignored `work/h2h-sealed-v2/`. Drawings, truth, overlays and credentials are not committed.

### Reading the result

- **Draft wins on the rule, but most of its builds are wrong.** Draft built 75 models and 13 pass
  the gate. The other 62 are labelled `draft_not_verified`, so none is a silent wrong build. On
  overlay L0 draft built 35 models and only 1 is correct. Draft is useful as a labelled first
  guess, not as an answer.
- **LLM-first was more precise but stalled.** It built 14 models and 9 pass the gate. All 9 are on
  separate L0. On separate L0 draft had 12 correct and LLM-first had 9. The LLM arm built nothing on
  overlay drawings.
- **Why the LLM arm stalled (diagnosis after scoring; no result changed).** 270 cases stopped with
  `repeated_identical_action_without_generation_progress`. Two harness causes, not the model's
  ability:
  1. In 87 L1/L2 cases, `inspect_source` failed for every section with an evidence-budget
     `resource_limit`. The model received only `inspection_worker_failed` without the reason, and
     every model tool then refused with `section_not_inspected`. The deterministic arms abstained on
     the same 87 cases.
  2. In the other cases, the model repeated an identical `read_region` or `enumerate_strokes` until
     the repeat limit stopped it. The observation history sent `"reason": null` for every earlier
     decision (the controller read the reason from the wrong field), the model had no place to
     record what it read, and requests used temperature 0 with thinking off. The same observation
     therefore produced the same action.
- **Follow-up:** W17 fixes these causes and measures them on non-sealed development data. Any
  claim that W17 improves the LLM arm needs a new held-out split, because this one is spent.

## Reading a small LLM round cheaply

Run `python scripts/round_digest.py RUN_DIR [RUN_DIR ...]` on finished case folders (each holds
`task/events/*.json`; `result.json` and `stdout.log` are optional). Add `--json` for machine output.
It prints, per case: end reason, decision count, compressed tool sequence, first blocker, last 3 model
reasons, draft/STEP state, requests and list cost. It ends with failure counts, a one-line verdict and an
early-stop hint. Run 2 to 4 cases first. If the hint says the first cases fail the same way, stop the round.
