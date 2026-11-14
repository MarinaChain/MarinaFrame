# Thin-ship production rejection diagnosis

## Scope and invariant

Only original 300 plus G-TS-SHIPD2 300 development IDs authorised by PM. Diagnosis reads only failed grids from these manifests; no other geometry, sealed data or new gate. Original FAIL and G-TS-SHIPD2 PASS remain unchanged.

## Step 1 evidence

Reproduction script: `scripts/diagnose_thin_ship_rejections.py`. Raw evidence stays in ignored `work/thin-ship-shipd/rejection-diagnosis/`.

| Cause | Original conditions / grids | G-TS-SHIPD2 conditions / grids |
|---|---:|---:|
| Negative half-breadth | 8 / 1 | 40 / 5 |
| Open ends | 0 / 0 | 0 / 0 |
| Nonfinite offsets | 0 / 0 | 0 / 0 |
| Nonmonotonic grid, shape mismatch, waterline or numeric guard | 0 / 0 | 0 / 0 |

Exactly one negative sample per failing grid, all in the bottom depth row (not the waterline). Original minimum −5.16676e−5 m; gate2 minimum −1.76557e−4 m; smallest-magnitude negative −2.32365e−6 m. These are not machine-epsilon sign noise. All failing end rows are closed; no nonfinite breadths. Five gate2 grids correspond to two hulls (one across all four drafts, one at one draft); original one grid belongs to one hull. Eight speeds reuse each grid, explaining 48 condition failures from six grids / three hulls.

## Decision before implementation

The production rejection is correct: a half-breadth cannot be negative. These supplied grids violate the method's geometric input contract. Do not clip, mirror, loosen tolerance, or alter the external parameterisation to turn these into accepted hulls. This does not prove the underlying continuous hull is invalid; the generated offsets are unsuitable as supplied. The defect is diagnostic quality: a combined generic message hides which guard failed. Add a typed `HullOffsetsError` (ValueError-compatible) with stable reason code, plus negative-value location/value and an engineer-action message. Retain strict zero tolerance and all numerical behaviour. Synthetic tests must fail before implementation, then pass; no gate rerun.

## Resume point

Diagnosis and typed rejection implementation complete. Eight synthetic tests failed first because errors were untyped, then focused solver/validation/rejection suite passed 36 tests. All six development grids were regenerated and still reject with `HullOffsetsError.code=negative_half_breadth`; no scoring or gate rerun. Message includes worst station/depth indices, signed value in metres, contract explanation and advice to check/regenerate geometry; no clipping. Other geometry reasons have distinct codes (shape, nonfinite breadth, invalid x/z grid, draft span, open ends), retaining ValueError compatibility. Numerical integral and accepted-input behaviour are unchanged. Quick tier running in background with 7,200-second tool limit, log `work/thin-ship-shipd/rejections-quick.log`. Next read result, final identity check, commit and push lane only. No new gate or recorded-result change.
