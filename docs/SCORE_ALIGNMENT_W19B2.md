# W19b2: combined fit score vs truth on edits

Branch `w19b2-score-alignment` (from `continue/v0.5` ba4d665). Dev data only.

## Method

`benchmarks/score_alignment.py` makes hulls from case truth without the model: the truth hull, 2
"first hulls" with 2-4 wrong stations, and one-station edits from each (shift, scale, height shift,
station swap, grid-line substitution, partial stroke with straight bridges, authored neighbour
blends, bumps, short tops, trace jitter, repairs). Each edit is scored forward and backward. Truth
metric: RMS of station half-breadth error, % of truth half-beam. Waterlines stay fixed per case, as
in the live controller. 24 body-plan cases (`work/w17/factory`) and 24 three-view cases
(`work/factory-3view`, scored body-only and three-view): 14,200 + 7,076 + 7,076 forward edits.

`benchmarks/score_alignment_replay.py` replays the recorded `propose_section` edits of a round
through the current keep rule. The original scorer reproduces the recorded fits (00679: 0.7066 vs
0.7069 recorded; others exact).

Data: `work/w19b2/full-before.*` (original scorer), `full-after.*` (this branch),
`replay-before.json`, `replay-after.json`.

## Results (body-plan mode; three-view mode similar)

| Metric | Before | After |
|---|---:|---:|
| Pairwise agreement (score up = truth better) | 0.922 | 0.933 |
| Agreement, small edits near a good hull (base <= 5 %, change <= 1 %) | 0.921 | 0.938 |
| Keep rule accepts a truth-worsening edit | 5.1 % | 3.9 % |
| Same, live controller (with ink protection) | 4.3 % | 3.3 % |
| Same, three-view mode | 5.4 % | 3.4 % |
| Truth harm of kept edits (% B/2 per edit) | 0.035 | 0.020 |
| Keep rule accepts a truth-improving edit | 86.5 % | 84.0 % |
| Median per-case Spearman (fit vs truth) | 0.57 | 0.56 |

W18d replay: 00679-L0 s08 blend is now rejected (fit 0.721 -> 0.636); s05 is kept. Final 10.31 %
instead of 11.12 % (first hull 10.37 %, harness truth metric). w18d-step4 DTMB: 15.52 -> 12.32 %
(was 14.31 %).

## Changes

- Station order: along each waterline, the table's half-breadths over x must rise then fall. A
  body-plan cell of a station that breaks this order by more than 2 % B/2 scores at most its order
  break. This was the 00679 failure: s08 moved onto another station's line, ink fit perfect.
- Keep rule: an edit that adds `ink_unexplained` cells is not kept (the curve left its own line).
- Unexplained ink: stations whose calibrations differ by a read error (< 5 px) now share their
  panel. Before, L2/L3 panels split per station and every other station's line was "unexplained"
  (truth hulls scored 0.2-0.4 at L3). Speckles, noise-broken grid columns and grid rows are ignored.
- Cell score keeps a slow tail to 30 % B/2. End (keel/top) cells weigh the waterline spacings they
  are off by.
- Speed: `inked` uses a summed-area table; one distance transform per body-plan panel (score
  0.3 s -> 0.075 s).

## Not fixed

- Rotation: injecting the true L2/L3 sheet rotation into the measurement did not raise truth-hull
  fit (truth station cells are within 1 px median at L2/L3). Not added.
- Saturation: the tail did not raise rank correlation over whole hulls (0.57). Bad hulls are still
  ranked poorly.
- Swaps between near-identical neighbours, repairs at L3 and tops at labels still disagree in
  13-20 % of cases. Raising the keep threshold to +0.005 trades about 1 point of false keeps for 6
  points of true keeps; not done.
