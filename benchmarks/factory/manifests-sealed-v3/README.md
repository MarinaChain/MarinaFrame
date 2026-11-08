# hull-disjoint (v3)

Frozen 2026-11-08, before inference or scoring, as the held-out split for the next pre-registered evaluation of the LLM investigator (W17/W18 changes). v2 is spent for model selection. No inference, scoring or truth inspection was run on v3.

**Caveat (must appear in every report):** Hull-disjoint from v1 and v2 and cluster-disjoint from v2; no hull shares a v1 family with a v2 hull. Every hull is in a broad family used by the frozen v1 splits; this is not family-disjoint from v1.

## Selection

- Fixed seed: **20261201**. Cluster order seed 20261202; candidate order seed `20261201 + 100 + cluster`. Case seeds are prefixed `v3:20261201:`.
- Partition: the **frozen v2 partition** (256 k-means clusters of the 30,000 standardised Ship-D rows), read from `manifests/sealed-v2/selection.json`. It is not recomputed.
- Excluded hulls (370): every v1 hull, v1 catalogue entry and rejected v1 candidate (as in v2), every v2 hull and every rejected v2 candidate. Each cluster that contains an excluded hull is excluded: 171 clusters, including all nine v2 clusters. 85 remain eligible.
- Broad families: v1 clustered Ship-D into 44 families (`splits.py`, k=44) and used **all 44** across development, validation and test. The labels are recomputed and checked against every v1 Ship-D hull. The 36 v2 hulls are in 20 of these families; v3 candidates in those 20 families are not used.
- Nine clusters, four feasible hulls each: **28, 249, 181, 110, 48, 174, 136, 161, 239** (namespaced `shipd-v3-cNNN`). Three candidates failed geometry feasibility. No cluster was short. No reader outcome influenced selection.

## What disjointness holds

| Property | v1 (frozen splits) | v2 |
|---|---|---|
| No shared hull (incl. rejected candidates) | yes | yes |
| No shared v2-partition cluster (k=256) | yes | yes |
| No shared v1 family (k=44) | **no**: v3 uses 14 v1 families (8 development, 5 validation, 1 test: `shipd-c39`) | yes |
| Named-hull families | v3 has only Ship-D; all named families were already used | v2 has only Ship-D |

All hulls come from the same Ship-D parametric generator, so the broad hull family (parametric Ship-D) is shared with both v1 and v2.

## Counts

36 hulls × 2 layouts (separate, overlay) × 4 levels (L0 to L3) = **288** drawings, 36 per layout and level. Same generator, renderer, truth builder and correctness gate (2 % RMS of half-beam, 5 % in-range volume) as v1 and v2.

## Seal and storage

`split_manifest.json` SHA-256:

`4b81c182462b03ae71ca38c70d400cb6a0f879e05aa0034914a9982dc904bb76`

It hashes `cases.jsonl`, `hulls.json`, `selection.json` and the generator files. `cases.jsonl` hashes every drawing, spec, parameter file and truth file. Generator commit: `56def2d` (clean).

Data is only in the main checkout's ignored `work/factory-sealed-v3/` (also when run from a linked worktree):

- `inputs/<case>/{drawing.png,spec.json}` (355 MiB): the only inference inputs.
- `sealed/truth/<hull>.npz` (14 MiB): never read by inference; checked by hash only.
- `params/` (1.1 MiB) and `hulls/` (134 MiB mesh cache): not inference inputs.

The manifests are in `benchmarks/factory/manifests-sealed-v3/`, outside `manifests/`, because `sealed_v2.previous_hulls` hashes every `cases.jsonl` below `manifests/`. v2 verification is unchanged.

## Verification

```bash
PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
PYTHONPATH=$PWD/src "$PY" -m benchmarks.factory.sealed_v3 --verify        # hashes, rules, specs; truth not opened
PYTHONPATH=$PWD/src "$PY" -m benchmarks.factory.sealed_v3 --regen-check   # regenerate, compare bytes, delete copy
```

`--regen-check` was run once after the freeze: the second generation gave byte-identical `selection.json`, `hulls.json` and `cases.jsonl`, so every drawing, spec, parameter and truth hash is identical. The library versions are in `selection.json` (Python 3.12.9, NumPy 2.3.5, SciPy 1.17.0, Pillow 13.0.0, OpenCV 4.14.0).

## Protocol

Score only at a pre-registered frozen checkpoint, once, never during development. Use `--manifest-dir benchmarks/factory/manifests-sealed-v3` and `--root <main checkout>/work/factory-sealed-v3` with the factory runner. That is not permission to run it now.
