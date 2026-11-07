# Hull-disjoint (v2): generation verification

Date: 2026-11-08. Generator commit: `ad2e2b662e51d89003e08409c9786365581a9bde` (clean at generation).

- 36 Ship-D hulls from nine new partition clusters; 288 drawings. Each hull has both layouts at levels 0, 1, 2 and 3: 36 cases per layout/level cell.
- Seed 20261108. Independently replayed SciPy k-means++ partition: all 30,000 labels and all centres match the frozen selection. No previously rendered hull belongs to a selected cluster. Old frozen manifests are byte-unchanged. Prior skipped candidates were also excluded.
- Name: **hull-disjoint (v2)**. Clusters can share broad families with the frozen splits; this is not family-disjoint. All named families were already used.
- Manifest SHA-256: `856a37fad69439cd9fc83a75382699d5988323c0aa68ed9b1eaf66fcfdef81d3`.
- Generation verifier passed: every drawing/spec/parameter/truth hash, source and generator identity, spec contract, exact case plan, input-folder isolation, and 36 complete truth tables with expected grids, finite nonnegative arrays and positive hydrostatic metadata. All 45 source parameters are recorded per hull.
- Opened with Read: `shipd-3-07824-separate-L0`, `shipd-3-07824-separate-L1`, `shipd-3-07824-overlay-L2`, `shipd-3-07824-overlay-L3`. Samples have the established grid, stations and factory format. Clean is crisp white; mild has slight tone/noise; moderate and heavy show stronger blur, noise, rotation and paper shading; heavy includes an occlusion patch. No reader results were used.
- Storage: ignored `work/factory-sealed-v2/inputs/` = 367,915,342 bytes; `sealed/truth/` = 14,131,782 bytes. Params are separate; meshes stay generator-side. No generated images or truth arrays are committed.
- Synthetic tests: six passed. They cover whole-cluster exclusion, case balance/determinism, disk floor, old-manifest history, future report naming and manifest selection without inference.
- First `make test-quick`: passed (617 Python tests, 10 CAD tests deselected; Rust fmt/clippy/tests passed; bounded secret scan found zero findings). Environment: `PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`, `PYTHONPATH=$PWD/src`, `MARINAFRAME_TEST_PYTHON=$PY`.
- No pipeline or scorer ran on v2. No reader output was inspected. Scoring remains restricted to frozen checkpoints, never development.

Final `make test-quick` also passed: 617 Python tests, 10 deselected; Rust fmt/clippy/tests passed; bounded secret scan zero findings. `cargo clean` removed 2.8 GiB. Final `df -h .`: 39 GiB available; disk stayed above the 15 GiB stop floor. Local logs: `work/test-quick-code.log`, `work/test-quick-freeze.log`, `work/sealed-v2-generation.log` (ignored).
