# G-TS-SHIPD2 commissioning

## Step 1: reference convergence (before any fresh-ID selection)

Use only the existing 300 development IDs and their frozen source hashes. Recheck exclusion metadata; no sealed or holdout sources are opened. Compute published Michell expressions at 161, 321, 641 angles on identical 301×51 offsets, all four drafts and all eight Fn. Change = 100*abs(Cw_N−Cw_next)/abs(Cw_next). Missing, nonfinite or nonpositive reference values count as infinite changes. Choose the smallest tested count whose p90 change to its tested next level is strictly <0.1%. Candidates are 161 and 321; 641 cannot qualify without a next level. If neither qualifies, stop and report; do not invent convergence or commission an unconverged gate.

Existing development IDs may appear in a later exclusion list because of prior use; they are explicitly authorised for this convergence step, not eligible for fresh selection. The exclusion list is used only as metadata, never to read excluded geometry beyond these authorised existing development IDs.

## Pending gate freeze

No fresh IDs selected or read. Original gate remains FAIL. After convergence, freeze full G-TS-SHIPD2 protocol and commit before fresh selection. Same production settings and unchanged 3% median / 10% p90 thresholds, all Fn including <=.15 inside gate. Numerical Michell agreement only; no physical bulb validity claim.

## Resume point

Next: commit convergence runner/tests, run convergence with background log, record result and choose reference count only by the rule above. Keep condition data under ignored work, aggregate results in git. Commit each step; quick tier in background with long tool limit, push lane only, no merge.
