# Hull selection: run-to-run spread and the draft fit (2026-11-09)

Branch `feature/best-of-n`. Development truth only (`work/factory-3view`); gates unchanged
(2 % RMS of half-beam, 5 % in-range volume). Sonnet 5.5 through the Claude subscription,
`scripts/run_round.py --sheet-only --model claude-sonnet-5-5`.

## 1. Spread with the current code

Three repeat L0 rounds on `b4c9204` (0388ff1 plus the worker limit fix), one case at a time per
round (`work/round-3view-L0-sonnet-rep{1,2,3}-b4c9204`):

| Case | rep1 | rep2 | rep3 | Spread | What differs |
|---|---|---|---|---|---|
| dtmb5415-L0 | 5.07 | 5.07 | 6.00 | 0.9 | rep3 read twice: 6.00 kept, 9.48 set aside |
| series60-L0 | 4.61 | 4.61 | 4.62 | 0.0 | every reading put station 5 on the aft half (fixed in 3b7c1c3) |
| shipd-1-00679-L0 | 6.17 | 6.17 | 6.58 | 0.4 | rep3: station 5 read as aft; a 13.4 % reading set aside |
| shipd-1-08158-L0 | 0.76 | 0.75 | 0.76 | 0.0 | passes |
| shipd-1-09867-L0 | 3.63 | 3.60 | 24.65 | 21.0 | rep1/2: a model edit of s08 repaired 7.6 -> 3.6 %; rep3: one body view, sides wrong at 5-6, no hull ends |

RMS % of half-beam. Tokens in per case 196k-666k (mean 408k), out 8-19k; 9-29 requests.

Findings:
- Before the limit fix, 8 of 11 runs on a loaded machine (load 12-17) ended with
  `worker_receipt_missing`: `build_first_hull` takes 100-208 s and the worker limit was 210 s
  (fixed in b4c9204: 600 s wall, 480 s CPU).
- The second reading usually repeats the first: 11 of 15 repeat runs gave the same setup, so no
  second hull was built. The spread comes from occasional bad readings, from model section
  edits (09867 s08), and from the model's fore/aft sides of the midship station.
- Large per-station errors that every reading shares are code errors, not reading errors:
  dtmb5415 (about 6.5 % at five stations) is the top cell of the truth grid (a deck height
  within 1 px of the truth but in the next 0.05 m cell costs one whole cell); 00679 s3-s5 is
  the flat-bottom trace near the baseline.
- Sonnet called `propose_section` as a native tool, got "No such tool available" and then
  noted that the action was unavailable (fixed in 192c74b).

## 2. Draft fit without truth

`src/vessel_reconstruction/draft_fit.py`. The old selection used `fit_feedback.score`: body
plan only, in each reading's own frame. A reading with x = 0 3 m off the hull's aft end fits
its own body-plan frame as well as a correct one (08158-L1: fit 0.919 at 11.9 % RMS was kept
over 0.872 at 5.3 %).

The draft fit measures every draft in one frame measured by code on the sheet: profile x = 0 at
the outline's aft extreme, z = 0 on its lowest line, plan centreline on the drawn line where the
plan outline's ends meet it, waterlines at the profile's grid rows, the intake's regions widened
to the outline's full length. It scores the body plan (own panels), profile (keel, top, stem,
stern) and half-breadth plan (waterlines, deck) and averages the three view fits.

Offline validation (`truth.score_model` on every stored first-hull and revision build of the L0
and L1 dev cases, 130 drafts; pairs of one case whose RMS differs by at least 0.5 points):

| Score | L0 pairs ranked as truth | L0 extra RMS of the top pick | L1 pairs | L1 extra RMS of the top pick |
|---|---|---|---|---|
| body-plan fit (old) | 75 % | 1.35 pt | 65 % | 9.60 pt |
| three views, cell-weighted | 85 % | 0.11 pt | 69 % | 3.47 pt |
| three views, equal weights (used) | 85 % | 0.11 pt | 84 % | 1.00 pt |

The weighting was chosen on the same data (two variants tried); treat the L1 figure as
optimistic. The 08158-L1 pair ranks correctly (0.708 against 0.627).

## 3. Best of N

`first_hull_tools.READINGS` is now a general N; a repeat reading with an unchanged setup is
recorded as `same_setup`. Simulated best-of-k on the pooled first hulls of the Sonnet rounds
(per case, mean RMS of the top-scored draft over all k-subsets): k=1 -> 2 changes the mean by -3.4 to +0.02 points
per case (mean -1.3), k=2 -> 3 by -0.54 to +0.07 (mean -0.2). Since most second readings repeat
the first setup, a third reading would rarely add a different hull; N stays 2.
Cost basis: one repeat reading is describe_views, two or three propose_sheet_setup calls and
describe_vessel, about 4 requests and 90-120k input tokens (the stable context is cached) and
1-2 minutes, plus one first-hull build (100-200 s) when the setup changes. That is about 25 % of
a case's mean 408k input tokens for an expected gain of about 0.2 points at k = 3. Per-section
choice across readings is not cheap: two readings with the same setup build no second hull, and
readings with different setups have different frames.

## 4. Fixes on this branch

| Commit | Fix | Check |
|---|---|---|
| b4c9204 | worker limits 600 s wall, 480 s CPU | 0 of 15 repeat runs interrupted (was 8 of 11) |
| 192c74b | Claude prompt: actions are answered through StructuredOutput | unit test; live round |
| 9f0dfde | readings chosen by draft fit; best of N | offline ranking above; unit tests |
| 3b7c1c3 | midship station's half follows its x | replay: series60-L0 4.61 -> 1.39 % |

## 5. Still open

- dtmb5415 top-cell residual (deck height subpixel; a first centroid try did not help).
- 00679 flat-bottom trace near the baseline (s3-s5).
- 09867 readings that describe the overlaid body plan as one view with wrong sides.
- Model section edits are still kept by the body-plan keep rule only.
