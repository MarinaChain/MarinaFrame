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

Next: commit convergence runner/tests, run convergence with background log, record result and choose reference count only by the rule above. Keep condition data under ignored work, aggregate results in git. Commit each step; quick tier in background with long tool limit, push lane only, no merge.
