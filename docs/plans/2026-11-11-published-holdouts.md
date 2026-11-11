# Published holdout run: CAMA BEACH SKIFF No. 22 and Davis Boat (lane M, 2026-11-11)

Backlog item 4: one published real-ship result with frozen code. One run per holdout, no tuning, no rerun.
Branch `lane/published-holdout` from `origin/continue/v0.5` `99ce579`.

## Run start (committed before either run)

- Code commit for both runs: `c473190965e042d53f9a9e6e69315b639495363c` (the run-start commit after it
  changes documents only).
- Pin check: every pin in `docs/BODY_PLAN_CHINE.md` ("Holdout protocol: CAMA BEACH SKIFF No. 22", lane I and
  lane L amendments) and `docs/holdouts/davis-boat.md` (lane I, lane L and lane M amendments) matches,
  including both sheets and both `truth.json` files (hash only). No re-pin was needed.
- Environment: Python 3.12.9 (`/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv`), numpy 2.3.5,
  Pillow 13.0.0, macOS 27.0.1 arm64. No model calls.
- Commands (run from the worktree root, `PYTHONPATH=src:.`, `W=/Users/jonathanjie/Documents/workspace/MarinaFrame/work`):

```
python scripts/measure_deadrise_holdout.py --boat cama-beach-skiff-22 \
  --sheet $W/holdout/cama_beach_skiff_22/master-pnp-habshaer-wa-wa0800-wa0881-sheet-00001a.tif \
  --truth $W/holdout/cama_beach_skiff_22/truth.json \
  --out $W/published-holdout/cama.json --overlay $W/published-holdout/cama-overlay.png \
  > $W/published-holdout/cama.stdout 2>&1

python scripts/measure_round_bilge_holdout.py --boat davis-boat \
  --sheet $W/holdout/davis_boat/master-pnp-habshaer-wa-wa0900-wa0928-sheet-00001a.tif \
  --truth $W/holdout/davis_boat/truth.json \
  --out $W/published-holdout/davis.json > $W/published-holdout/davis.stdout 2>&1
```

- A crash for an infrastructure reason is recorded verbatim and stops the lane until the PM decides.

## Steps

1. [x] Read both protocols; verify pins.
2. [x] Davis run script and pre-run amendment (`c473190`).
3. [ ] Run start note (this file), committed.
4. [ ] One run each; outputs and SHA-256 values in `work/published-holdout/`.
5. [ ] Results in both protocols; public summary `docs/results/2026-11-11-published-holdouts.md`.
6. [ ] Quick test tier; push branch (no merge).

## Resume point

If step 4 has not started, run the two commands above once each. If any output file exists in
`work/published-holdout/`, the run happened: do not run again; record what is there.
