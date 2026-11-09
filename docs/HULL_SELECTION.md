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

## 6. Final live rounds (snapshot 3b7c1c3)

`work/round-3view-L{0,1}-sonnet-3b7c1c3-r2`, one pass each. The first attempt (`...-3b7c1c3`)
ended with `provider_rate_limited` on all 10 cases (subscription limit). None of those runs was
complete, so all 10 were run again.

| Case | Before (b5a9dac L0 / e445d52 L1) | After 3b7c1c3 | Tokens in / out | Requests |
|---|---|---|---|---|
| dtmb5415-L0 | 5.07 / +0.6 | 6.00 / +0.9 | 296k / 9k | 16 |
| series60-L0 | 1.39 / +1.0 (pass) | 1.39 / +1.0 (pass) | 445k / 16k | 17 |
| shipd-1-00679-L0 | 6.17 / -0.4 | 6.27 / -0.3 | 419k / 12k | 18 |
| shipd-1-08158-L0 | 1.13 / -2.1 (pass) | 0.75 / -2.1 (pass) | 408k / 13k | 18 |
| shipd-1-09867-L0 | 3.63 / +1.7 | 2.99 / +0.7 | 523k / 15k | 24 |
| dtmb5415-L1 | 18.22 / +14.0 | 14.34 / +13.2 | 466k / 14k | 19 |
| series60-L1 | 3.49 / -0.5 | 3.49 / -0.5 | 271k / 9k | 14 |
| shipd-1-00679-L1 | 8.59 / -3.3 | 8.75 / -3.1 | 332k / 10k | 16 |
| shipd-1-08158-L1 | 11.92 / +0.7 | 1.96 / -2.8 (pass) | 515k / 16k | 20 |
| shipd-1-09867-L1 | 2.06 / +1.8 | 2.09 / +1.3 | 487k / 11k | 24 |

RMS % of half-beam / in-range volume, development truth. Passes: L0 2 -> 2 (series60 is now
the reading-independent 1.39 %, not a lucky reading), L1 0 -> 1. In every case the second
reading repeated the first setup (`same_setup`), so the draft fit did not choose between hulls
in this round; the 08158-L1 gain comes from that run's reading. No "No such tool available"
replies (0 receipts; earlier rounds: 1-4 cases a round). Mean input 416k tokens a case (L0 418k,
L1 414k).

## 7. Hull accuracy lane (branch `feature/hull-accuracy`, 2026-11-09)

| Commit | Fix | Check |
|---|---|---|
| 81d3047 | repeat reading hides the earlier reading (history, notes, description, setup) | live L0 81d3047: 2 of 5 second readings differ (was 0-4 of 15) |
| 9322fb2 | profile and plan setups count as setup changes; kept reading's setups and description restored | unit tests; live 4f92e9f: 10 of 10 second readings built a second hull |
| 14c869c | section edits kept or refused by the three-view draft fit | replay of 61 recorded Sonnet edits (16 cases): same decisions, same RMS |
| 04ca8c3 | traced bottom stopping above the profile keel continued to it (not end stations) | replay: 00679-L0 6.27 -> 4.50, 00679-L1 8.85 -> 5.05, 09867-L1 2.09 -> 1.13, others unchanged |
| 2a4adcb | readings counted by reading, not record | unit test |
| 44c8231 | printed sheet scale outranks a view scale off by > 0.2 % | replay 09867-L0 at 19.2 px/m: 13.03 -> 7.58; 00679-L1: 4.51 -> 5.05 |
| 4f92e9f | profile region widened to the profile outline | replay 09867-L0 (81d3047 reading 2): 21.94 -> 7.58; no other stored reading changes |

Not committed (fix 5, DTMB deck): the deck tops are within 1 px but in the wrong 0.05 m truth cell.
Snapping every top to the profile deck line (bias -0.006 m against -0.065 m for the body-plan
tops, 19 dtmb L0/L1 stations) gave dtmb5415-L0 6.00 -> 5.65 but series60-L0 1.39 -> 3.37 (deck
line 1-2 px low at s2/s9); a sub-pixel cap-edge measurement was not reliable. Open.

Final live rounds (snapshot 4f92e9f, `work/round-3view-L{0,1}-sonnet-4f92e9f`, one pass each,
no rate limit): RMS % half-beam (pass), tokens in / out.

| Case | Before (3b7c1c3-r2) | After 4f92e9f | Tokens | Reading 1 / 2 first hulls (kept) |
|---|---|---|---|---|
| dtmb5415-L0 | 6.00 | 8.09 | 305k / 10k | 4.12 / **8.09** |
| series60-L0 | 1.39 pass | 1.38 pass | 393k / 13k | **1.38** / 22.27 |
| shipd-1-00679-L0 | 6.27 | 4.05 | 507k / 16k | **4.05** / 5.78 |
| shipd-1-08158-L0 | 0.75 pass | 0.76 pass | 425k / 13k | 0.75 / **0.76** |
| shipd-1-09867-L0 | 2.99 | 3.25 | 392k / 13k | **7.44** / 27.17 (edit 7.44 -> 3.25) |
| dtmb5415-L1 | 14.34 | 14.34 | 342k / 10k | **14.34** / 15.59 |
| series60-L1 | 3.49 | 3.49 | 218k / 10k | **3.49** / 3.49 |
| shipd-1-00679-L1 | 8.75 | 5.47 | 474k / 14k | 3.89 / **5.47** |
| shipd-1-08158-L1 | 1.96 pass | 1.64 pass | 437k / 12k | 1.87 / **1.64** |
| shipd-1-09867-L1 | 2.09 | 1.00 pass | 413k / 13k | **1.00** / 1.12 |

Passes L0 2 -> 2, L1 1 -> 2. Mean input 404k (L0) and 377k (L1) tokens a case. Every second
reading now builds its own hull; the draft fit picked the better of two in 6 of 8 pairs that
differ by more than 0.05 points, and set aside the two worst hulls (22.3 %, 27.2 %). Its two
wrong picks (dtmb5415-L0 4.12 kept 8.09; 00679-L1 3.89 kept 5.47) cost more than the other
picks gained: against reading 1 alone the mean RMS is 0.5 points worse in this round.

Open: draft-fit ranking errors (dtmb5415-L0, 00679-L1); dtmb5415 top cells; dtmb5415-L1
readings (14 %); 09867 body-plan curve identity at the overlaid stations 5-7.
