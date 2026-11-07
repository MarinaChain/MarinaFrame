# sysser45 wrong-build experiment

Base commit: `ea2300eea73466b48efbadc5091c995a700554be`.
Branch: `fix-sysser45`. No reference geometry enters source reading.

## Evidence

The raw fingerprint files (`procedural-*.json`, `factory-before.json`, `factory-after.json`,
`factory-h9-partial.json`, `factory-h10-partial.json`; 5.6 MB) are kept locally in
`work/archived-runs/sysser45/`, not in the repository. `factory-comparison.json` and
`procedural-comparison.json` hold their differences.

- `score-before.json`: independent reimport of the baseline STEP; 448.9215459 mm station RMS and +27.4467632% volume error within range.
- `inspection-before.json`, `inspection-after.json`: source-bound candidates and rejection evidence. Raw raster derivatives remain in `work/`.
- `procedural-before.json`, `procedural-after.json`: per-section candidates, selected IDs, measurement hashes and gaps for 45 drawings plus two examples.
- `factory-before.json`, `factory-after.json`: development source fingerprints. These are not CAD build results.
- `factory-hash-check.json`: mismatch list against frozen inputs; must be empty.
- `inspection-h11.json`, `result-final.json`: final mixed-stroke refusal and native abstention. Inspection JSON is compact; raw coordinates and PNG derivatives remain in `work/retained-attempts/` and `work/sysser45-h11/`.
- `correct-controls.json`, `score-final-*.json`: all four fresh final-source native controls are correct.
- `new-native-results.json`: final newly complete source case is blocked, not a correct build.
- Native build/score summary and all keep/revert decisions: `docs/GEOMETRY_ACCURACY_V05.md`, section 9.

## Reproduce source fingerprints

Retained runners: `outputs/sysser45/replay.py` and `compare.py` (the commands below used their scratch copies in `work/`). Baseline Python package: `work/factory-source-before/` (captured before the fix, hashes in `snapshot.json`). Runtime:

```sh
PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
PYTHONPATH="$PWD/work/factory-source-before:$PWD" "$PY" work/replay.py \
  --source "$PWD/work/factory-source-before" --suite procedural \
  --out outputs/sysser45/procedural-before.json
PYTHONPATH="$PWD/src:$PWD" "$PY" work/replay.py \
  --source "$PWD/src" --suite procedural --out outputs/sysser45/procedural-after.json
```

Use `--suite factory` and fresh output names for factory development. Existing fingerprint entries are resumed, not overwritten. Native builds use a copied controller at `work/bin/marinaframe` and explicit `--worker-source "$PWD/src"`.

## Limits

This fix refuses a known class of identity ambiguity. It does not prove that every accepted path follows one engineering stroke. A long true hull side on a ruler can also be refused. Explicit source-supported local ranges remain supported; no automatic endpoint is inferred where the hull and ruler meet without separable source evidence. CAD and validation gates stay unchanged.
