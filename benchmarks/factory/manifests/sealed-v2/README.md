# hull-disjoint (v2)

Frozen 2026-11-08, before inference or scoring. **Clusters can share broad families with the frozen splits; this is not family-disjoint.** All named hull families (including the Delft yacht series) were already used, so this split contains only Ship-D hulls.

## Selection

- Fixed partition seed: **20261108**. Standardise the 45 parameters of all 30,000 constrained-random Ship-D rows; use SciPy `kmeans2`, k-means++ initialisation, 256 clusters, 10 iterations.
- Exclude each new cluster containing any previously rendered hull in the frozen case manifests. Also conservatively exclude prior hull catalogue entries and rejected candidates. This excludes 162 clusters; 94 remain eligible.
- Select nine clusters using seed 20261109; select the first four hulls with usable sections from each seeded candidate permutation (`20261108 + 100 + cluster`). Eleven candidates failed geometry feasibility. No reader outcome influenced selection.
- Selected cluster IDs: **122, 88, 31, 176, 120, 221, 217, 182, 212**. Each contains four selected hulls. Cluster labels are namespaced `shipd-v2-cNNN`.
- `selection.json` records all partition labels, centres, standardisation, candidate orders, skips, exclusions, source hashes, versions and mesh/truth settings. `hulls.json` includes all 45 parameters per selected hull, source set/row and truth hash.

## Counts

| Layout | L0 clean | L1 mild | L2 moderate | L3 heavy | Total |
|---|---:|---:|---:|---:|---:|
| separate | 36 | 36 | 36 | 36 | 144 |
| overlay | 36 | 36 | 36 | 36 | 144 |
| Total | 72 | 72 | 72 | 72 | **288** |

36 hulls × both layouts × four levels. The existing factory hull loader, truth builder and renderer are unchanged. Each case has its own deterministic seed and full rendering record.

## Seal and storage

`split_manifest.json` SHA-256:

`856a37fad69439cd9fc83a75382699d5988323c0aa68ed9b1eaf66fcfdef81d3`

It hashes `cases.jsonl`, `hulls.json`, `selection.json` and the generator source files. The case manifest hashes every drawing, spec, parameter file and truth file. Generator commit: `ad2e2b662e51d89003e08409c9786365581a9bde` (clean).

Local git-ignored data, relative to this worktree:

- `work/factory-sealed-v2/inputs/<case>/{drawing.png,spec.json}`: 367,915,342 bytes (350.9 MiB), 288 drawings and specs. These are the only inference inputs.
- `work/factory-sealed-v2/sealed/truth/<hull>.npz`: 14,131,782 bytes (13.5 MiB), 36 truth tables. **Inference never reads this folder.**
- `work/factory-sealed-v2/params/`: per-case seeds, rendering parameters, geometry calibration and station positions.
- `work/factory-sealed-v2/hulls/`: generator-side mesh cache (129.8 MiB); not an inference input.

No data images, mesh caches or truth arrays are committed. The old frozen manifests are unchanged.

## Protocol

Score **only at frozen checkpoints**, for deterministic abstain vs deterministic draft vs LLM-first; never during development. Freeze code and policy settings before opening outcomes. Reports and scores must use the name **hull-disjoint (v2)** and state the broad-family caveat above. No inference or scoring was run during generation, and no reader output was inspected.

Generation-only verification checks all file hashes, source/code identity, exclusion of occupied clusters, exact case balance, spec validity, input-folder isolation, truth grids/array shapes/finite values and positive hydrostatic metadata. Read-tool samples at L0/L1 (separate) and L2/L3 (overlay) match the established factory drawing format.

```bash
PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
PYTHONPATH=$PWD/src "$PY" -m benchmarks.factory.sealed_v2 --verify
```

To regenerate in a fresh worktree with the same sources, run the module without `--verify` using the frozen generator commit. It refuses to overwrite an existing data root or frozen split manifest. Reproducing image bytes requires the recorded library versions. Future approved checkpoint runs select these case manifests with the runner's `--manifest-dir benchmarks/factory/manifests/sealed-v2` and data root `--root work/factory-sealed-v2`; that is not permission to run them during development.
