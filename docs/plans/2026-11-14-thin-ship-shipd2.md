# G-TS-SHIPD2 commissioning

## Step 1: reference convergence (before any fresh-ID selection)

Use only the existing 300 development IDs and their frozen source hashes. Recheck exclusion metadata; no sealed or holdout sources are opened. Compute published Michell expressions at 161, 321, 641 angles on identical 301×51 offsets, all four drafts and all eight Fn. Change = 100*abs(Cw_N−Cw_next)/abs(Cw_next). Missing, nonfinite or nonpositive reference values count as infinite changes. Choose the smallest tested count whose p90 change to its tested next level is strictly <0.1%. Candidates are 161 and 321; 641 cannot qualify without a next level. If neither qualifies, stop and report; do not invent convergence or commission an unconverged gate.

Existing development IDs may appear in a later exclusion list because of prior use; they are explicitly authorised for this convergence step, not eligible for fresh selection. The exclusion list is used only as metadata, never to read excluded geometry beyond these authorised existing development IDs.

## Reference convergence result

All 9,600 conditions finite. 161→321 p90 change .1125212491%, median .0103195163%, max 1.2095465833%. 321→641 p90 .0188529228%, median .0020318210%, max .5129439883%. Selected **321 angles**, the smallest qualifying count. This is an aggregate convergence criterion, not a per-condition error bound.

## Frozen G-TS-SHIPD2 protocol (before fresh-ID selection)

Original gate remains FAIL. This gate compares a **numerical Michell reference**; a pass shows numerical agreement only, not physical validity for bulbs.

- Sample: 300 fresh IDs, 100 from each constrained subset of 10,000 zero-based rows. Fixed seed string `G-TS-SHIPD2-20261114`; rank eligible IDs by SHA-256 of UTF-8 `seed:id`, take the lowest 100 per subset. Exclude the entire current main `work/ship-d-excluded-ids.txt` and all original development 300 before selection. The PM-provided exclusion list is the permitted metadata boundary for sealed membership; never open sealed IDs, folders or truth. No diffusion or holdout data. If sealed membership is not covered by that list, stop for PM metadata rather than opening sealed sources.
- Freeze exclusion digest and fresh sample digest in a commit before reading selected geometry. No replacement or resampling after outcomes.
- Same conditions: draft/depth [.25,.33,.5,.67]; waterline Fn [.10,.15,.20,.25,.30,.35,.40,.45], 9,600 conditions. U=Fn*sqrt(9.81*generated WL), rho=1000. Generated 301×51 offsets unchanged, draft=-z[0], LOA² reference area. No clipping, end closure or correction.
- Production unchanged: 512 angles, lambda_max=24. Reference: published expressions via the tested vectorised implementation, **321 angles**, identical geometry, speed and LOA² coefficient convention.
- Score once: median absolute relative Cw error <=3% AND p90 <=10%. Nonfinite, missing, unsupported production conditions or nonpositive reference count as infinite errors; fixed denominator 9,600. No gate changes after run. Original gate retained separately.
- Report Fn<=.15 separately as information (small Cw can inflate relative error); retain all such rows inside the gate. Report absolute Cw differences too. No drag-validity claim.
- After scoring, append exactly these 300 IDs to main `work/ship-d-excluded-ids.txt`, preserving existing content and checking concurrent changes with an exclusive lock. They become development data. Do not commit IDs or per-hull values; aggregate summary only.
- One run/one score; immutable trace and score files refuse overwrite. Infrastructure failures are reported, not silently retried as a new gate run.

## Resume point

Gate frozen in `db71ddb` before fresh selection; sample committed in `e05940d` before geometry reads. Fresh sample digest `229237c5ad56e6aef0ff22fd97c4bb29043706fd68c9560b766b2770d1005f90`; pre-run exclusion digest `0b44a428638e648bc56a982469a93b17320424d8697bc76d1cd829fff1dfcaa3`. Manifest: ignored `work/thin-ship-shipd/gate2-sample.json`. Single run and score completed; IDs appended after scoring. Original gate remains FAIL. Quick tier running; next read its final result, commit check record and push lane only.

## Single-run results

**G-TS-SHIPD2 PASS**, fixed denominator 9,600; finite 9,560. Median .1269984804%, p90 1.6914994583%, against unchanged 3% / 10% limits. Forty conditions fail production breadth validation (finite/nonnegative/grid-shape requirement) and remain infinite errors in the gate; no clipping or rerun. Numerical agreement only, not physical validation for bulbs. Original gate remains FAIL.

| Information subset (still inside primary gate) | conditions / finite | median relative % | p90 relative % | median absolute Cw difference | p90 absolute Cw difference |
|---|---:|---:|---:|---:|---:|
| Fn<=.15 | 2400 / 2390 | 1.0186104 | 3.4260827 | .0000187663 | .0002085251 |
| Fn>.15 | 7200 / 7170 | .0862446 | .2802784 | .0000054683 | .0000363300 |

Absolute differences are complete-case information. Low-Fn relative differences can amplify small Cw and are not evidence of meaningful total-drag error. No low-Fn rows removed.

After scoring, appended 300 IDs under an exclusive file lock to the main ignored exclusion file, preserving original bytes. Count 344→644, resulting SHA-256 `03a366b3c373dd6a896406d0f5132e9ae77cbd823b52e685675964ddb24b9d12`. They are now development IDs. No sealed sources opened; selection used PM-provided exclusion metadata. Raw sample, trace, score and logs remain under ignored `work/thin-ship-shipd/`. Aggregate score and reference convergence: `outputs/thin-ship-shipd/gate2-score.json`, `gate2-convergence.json`.

Focused selection/convergence/diagnostic/export suite: 15 passed. No production settings or thresholds changed.
