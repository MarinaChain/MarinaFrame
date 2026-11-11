# Gunnerus Whole-Vessel Build Speed (Lane D)

**Goal:** Make the full Gunnerus whole-vessel build faster with the same outputs. Accuracy
behaviour does not change.

**Branch:** `lane/build-speed` from `continue/v0.5`. Outputs (drawing derivatives) are in the
git-ignored `work/build-speed/` folder of the lane worktree; `work/whole-vessel/` is not changed.

## 1. What the full build is

The app does not build the whole vessel; it shows a folder that two commands make:

1. Step 1, `python -m benchmarks.gunnerus.whole_vessel --sources S --out R/step1`: GA reading
   (`build_inputs`), appendages, detail (hull side from the lines plan, deckhouse end contours,
   windows), then all parts in the sandboxed ship-cad worker (`ship_cad_worker.run`, a separate
   process).
2. Assembly, `python -m benchmarks.gunnerus.whole_vessel_assembly --sources S --step1 R/step1
   --out R/asm`: hull panel loft (`build_hull`), hull cut at the deck (`build_hull_to_deck`),
   precise volumes, STEP and GLB export with the display mesh, render.

The 602 s figure was from before the ingest speed-up (`work/whole-vessel/detail-final`:
assembly 594 s). On this branch base the build took 354 s on a quiet machine.

## 2. Method

- Stage timing: `benchmarks/gunnerus/whole_vessel_timing.py` wraps the stage functions by name (no source
  change) and runs the normal entry points; it writes `<out>-timings.json`.
- Profiles: cProfile of step 1 in process (`--in-process` runs the same `ship_cad.execute` as the
  worker) and of the assembly; then direct timers per shape and per face, because cProfile
  misattributes time around OCP calls (see 3.1).
- Identity: `benchmarks/gunnerus/whole_vessel_compare.py BEFORE AFTER` compares every output file: STEP by
  the DATA section (the header holds a timestamp), GLB, PNG and BREP by bytes, JSON parsed with
  timing fields, process ids and the run folder path left out.
- Before/after timing ran side by side (baseline from `git archive origin/continue/v0.5` in
  `work/build-speed/base-src`) because other lanes loaded the machine (load average 6 to 19).

## 3. Hot spots and fixes

### 3.1 Display mesh: OCP iteration end (assembly, -85 s)

Ending a Python iteration over an OCP `TopTools_IndexedMapOfShape` (or a triangulation array)
costs about 6 ms (80 ms the first time), whatever its size: pybind11 passes the `StopIteration`
through every exception translator that OCP registers. CadQuery's `Faces()`, `Edges()`,
`Wires()`, `innerWires()` and `tessellate()` iterate such maps. `display_mesh.shape_mesh` made
several of these calls per face, and the hull has 3,151 faces: the hull mesh took 61 to 100 s,
even when the triangulation already existed.

Fix: `vessel_reconstruction/topology.py` lists sub-shapes by index (`FindKey`), in the same
order, and reads a face's triangulation by index with the same values as `tessellate`.
`display_mesh` and `geometry.export_geometry` (the hull pipeline's mesh.json) use it.
Hull mesh: 99.6 s -> 3.1 s; all 12 meshes byte-identical (old module against new, same shapes).

### 3.2 Repeated precise volumes (worker and hull-to-deck, about -40 s)

`precise_volume_mm3` (adaptive integration) was 44 of 49 s of the part worker: one smooth part
was integrated up to 4 times (loft check, part check, build check, result record), and the
bulwark lofts again in `wall_between`. `_one_face_solid` integrated each hull solid twice
(sign, then value), and `_closed_solid` called `Volume()` three times.

Fix: `geometry.reused_volumes()`, a memo active only inside `ship_cad.execute`; a kept value is
used only for the same Python object whose wrapped shape still equals a snapshot (same TShape,
location, orientation). `_one_face_solid` and `_closed_solid` integrate again only when they
reverse the solid; `_closed_solid` returns its volume. Worker: 49.4 s -> 28.7 s in process,
`provenance.json` identical.

### 3.3 Repeated DXF parsing (step 1 and assembly, about -25 s)

Step 1 parsed the 56 MB GA four times (4.4 s each) and the 45 MB lines plan twice (7 s each);
the assembly parsed the lines plan twice. Fix: `dxf_documents.shared_documents()` /
`read_document`: inside the block each file (path, size, mtime) is parsed once; the readers
only read. Active only in `whole_vessel.main` (GA reading, appendages, detail) and
`whole_vessel_assembly.build_hull`. Memory: about 420 MB while active.

### 3.4 Left as is

- Hull panel loft (`build_hull`, 64 s quiet): sewing 43 s, validity checks 23 s, solid making
  20 s under load: kernel work that the result depends on.
- Precise volume of the hull compound (20 s) and of each part read from STEP: the values differ
  in the last bits from sums of solid volumes, so they stay.
- `vector_config` and `read_sections` run in both step 1 and the assembly (separate processes).
- Next step if more speed is needed: run the panel loft (only used for `hull/model.brep` and
  `hull_loft_volume_m3`) in parallel with the hull-to-deck build.
- None of the hot spots is in `ingest.py`, `body_plan_crossings.py` or `sheet_calibration.py`.

## 4. Results

### 4.1 Stage timing, side by side under the same load (seconds)

| Stage | Before | After |
|---|---|---|
| Step 1: GA reading (`build_inputs`) | 10.1 | 5.5 |
| Step 1: appendages | 5.3 | 0.2 |
| Step 1: detail (hull side, ends, windows) | 37.3 | 24.8 |
| Step 1: part worker (sandboxed) | 51.7 | 30.6 |
| **Step 1 total** | **104.3** | **61.0** |
| Assembly: hull section reading | 8.7 | 1.8 |
| Assembly: hull panel loft | 99.2 | 95.9 |
| Assembly: hull (reading + loft) | 130.6 | 120.4 |
| Assembly: hull to deck | 68.2 | 43.5 |
| Assembly: precise volumes (all calls) | 87.4 (38 calls) | 65.5 (25 calls) |
| Assembly: display mesh | 89.1 | 4.1 |
| Assembly: export (STEP, mesh, GLB) | 91.4 | 6.4 |
| Assembly: render | 6.1 | 6.7 |
| **Assembly total** | **340.3** | **224.7** |
| **Full build** | **444.6** | **285.7 (-36 %)** |

Stages overlap (the precise volumes are inside other stages). Quiet-machine baseline before the
change: step 1 53.6 s, assembly 300.7 s, total 354.3 s.

### 4.2 Identical outputs

- `whole_vessel_compare.py cmp/base cmp/new`: 47 files; the only differences are `assembly.json` timing
  fields, the run folder path and `assembly_step_sha256` (a hash of the whole STEP file with its
  timestamp header; the STEP DATA sections are identical).
- Same code run twice (`base/step1` vs `cmp/base/step1`): `azimuth_sb.step` differs in one pcurve
  point (1.1e-13 vs 0). That noise exists before the change; the side-by-side runs did not show it.
- Display meshes: all 12 parts byte-identical, old module against new on the same shapes.
- `export_geometry` mesh.json of the hull-to-deck shape (15 solids, 3,151 faces), old and new code in
  separate processes: byte-identical (80,028,515 bytes); 174.1 s old, 118.6 s new under load. (The
  old-code export of the full panel hull was stopped after 25 minutes.)

### 4.3 Tests

- New: `tests/test_topology.py` (lists and triangulations equal CadQuery's; memo reuse and
  in-place change; `_closed_solid` volume), `tests/test_dxf_documents.py`.
- Related CAD tests (display mesh, geometry, exports, region pipeline, ship CAD, superstructure,
  tanks, appendages, step 1): 249 passed, 1 skipped.
- `make test-quick`: exit 0 (Rust tests, pytest 1,848 passed and 76 CAD tests deselected, UI tests,
  secret scan). `tests/test_whole_vessel_compare.py` (2 tests) was added after that run and passes.

## 5. Resume point

Done: sections 3.1 to 3.3, committed on `lane/build-speed`. To repeat the measurement:

```
S=work/sources/gunnerus; R=work/build-speed/run; PY=<venv python>
PYTHONPATH=src:. $PY -m benchmarks.gunnerus.whole_vessel_timing step1 --sources $S --out $R/step1
PYTHONPATH=src:. $PY -m benchmarks.gunnerus.whole_vessel_timing assembly --sources $S --step1 $R/step1 --out $R/asm
PYTHONPATH=src:. $PY -m benchmarks.gunnerus.whole_vessel_compare <before run> $R
```

For a fair before/after, run both side by side: other lanes change the machine load.

Next (not started): parallel panel loft (3.4).
