# Cost per ship from stored runs

Accounting date: 2026-11-10. USD throughout.

For planning, allow **$3.39–$8.04 API-equivalent for one hull plus tanks** under the conservative tank-workload assumption below. A sequential time reference is **about 14 minutes**. These are estimates assembled from different cases, not a measured complete ship. No selected stored run measures a complete, accepted hull-and-tanks delivery on one vessel.

Claude runs used a **subscription**. Dollar amounts are API-equivalent estimates, not charges paid for these runs. Human review, subscription fees, host compute, storage, source acquisition and independent truth transcription are outside these token prices.

## Sources and method

The script reads text records only. It does not load images, run CAD, or call a model. The main checkout's records remain read-only:

- Hull campaigns: /Users/jonathanjie/Documents/workspace/MarinaFrame/work/round-3view-*-sonnet-* and work/autocal-live-*.
- Hull controller records: each case's result.json, task/events, request receipts and final CLI result bodies, plus worker resource receipts.
- Intake calibration: intake/run-input/body-plan-answers/receipts/claude.jsonl, counted in addition to controller requests.
- Holdouts: /private/tmp/claude-501/{bue-girl,bumble-bee,pardon-me}/runs/*, including the separate sonnet-12b campaign and resumed Crouton receipts.
- Tank secondary evidence: [TANKS_V2.md, section 5](TANKS_V2.md#5-development-results-2026-11-09). The expected main-checkout work/tanks-raster folder is absent; this collection found **zero tank receipt files**. Missing receipts do not mean zero usage.

This snapshot has **130 run rows: 106 hull attempts and 24 holdout repeats; 1,942 request receipts**. There are 155 receipts with missing usage and nine additional DeepSeek requests without a local exact price. Known subtotals exclude these unknown amounts.

One request here means one transport attempt, including failed attempts. It need not equal one model decision or one logical label question. JSON receipts with the same request_id in original and resumed folders count once. Every JSONL line is retained as a separate attempt. Summary usage is a cross-check, never an additional charge. The final CLI result is cumulative within one invocation; assistant messages, modelUsage and iteration usage are not added again.

Prompt tokens mean uncached input plus cache writes plus cache reads. Controller CLI bodies retain this split; holdout and intake logs collapse it. The intake field named input_tokens is already a collapsed prompt total. A failed call without usage remains unknown, even when a harness wrote zeros.

Hull wall time comes from result.json and includes intake. Model time is summed call latency; worker wall and CPU times are sums of resource receipts. They are separate measures, not extra time to add to case wall time. Holdout repeat wall excludes its separately timed code measurement, sheet loading and question preparation. Missing wall intervals stay unknown.

## Price basis

Rates are USD per million tokens, recorded on 2026-11-10 from the local bundled reference, not refreshed public tariffs. Source: /private/tmp/claude-501/bundled-skills/2.1.317/c2410b3d888fef8507425f875f1de23e/claude-api/shared/models.md and shared/prompt-caching.md. The former gives base/output/read rates; the latter gives 1.25x base for five-minute writes and 2x base for one-hour writes.

| Model | Uncached input | Output | Cache read | 5-min write | 1-hour write |
|---|---|---|---|---|---|
| Claude Sonnet 5.5 | $2 | $10 | $0.20 | $2.50 | $4 |
| Claude Opus 5.5 | $4 | $20 | $0.20 | $5 | $8 |
| DeepSeek V4.1 Flash | price not found | price not found | price not found | price not found | price not found |
| Crouton Alpha Free | $0 | $0 | $0 | $0 | $0 |

No Opus calls occur in the selected receipts. DeepSeek is reported in tokens only; an older blended estimate is not treated as a tariff. CLI list_cost is retained in the JSON as historical provider metadata, but is not added to or substituted for this dated price calculation.

For Sonnet with a collapsed prompt total P and output O, the cost interval is (0.20P + 10O)/1,000,000 through (4P + 10O)/1,000,000. These are algebraic cache-price bounds, not measured cache shares or statistical confidence limits. Where the actual cache split is present, it is priced directly.

## Hull cases

The following table uses only the **79 attempts whose recorded status is draft_not_verified**: 77 development attempts and two BUE GIRL attempts. Every cell is a median across that case's included attempts, except the last column, which is the minimum low cost through maximum high cost. Independent medians need not describe a single run. Tokens and requests include intake where present. All calls in this table are Sonnet 5.5.

The remaining 27 blocked, failed, interrupted, paused or status-missing attempts remain in the ledgers. Four attempts lack case wall time. Fast failures and zero-token failures are not used as successful ship-cost examples. A draft status does not prove correct geometry or engineering acceptance.

| Hull case | Draft attempts | Prompt | Output | Requests | Wall s | Worker wall s | Median cost midpoint | Observed cost band |
|---|---|---|---|---|---|---|---|---|
| bue_girl | 2 | 911,199.5 | 20,381.5 | 26.5 | 659.2 | 403.6 | $2.018 | $1.951–$2.083 |
| dtmb5415-3v-L0 | 13 | 351,269 | 11,708 | 15 | 429.3 | 270.7 | $0.737 | $0.281–$1.675 |
| dtmb5415-3v-L1 | 5 | 363,698 | 13,236 | 18 | 386.7 | 228.0 | $0.794 | $0.336–$0.991 |
| series60-3v-L0 | 14 | 311,380 | 11,144 | 12 | 324.8 | 176.5 | $0.726 | $0.551–$1.554 |
| series60-3v-L1 | 5 | 236,286 | 9,198 | 11 | 323.1 | 227.0 | $0.550 | $0.441–$0.760 |
| shipd-1-00679-3v-L0 | 10 | 447,361.5 | 12,652.5 | 19 | 447.9 | 291.1 | $0.894 | $0.750–$2.429 |
| shipd-1-00679-3v-L1 | 4 | 285,769.5 | 9,524 | 13 | 473.5 | 288.7 | $0.692 | $0.531–$0.945 |
| shipd-1-08158-3v-L0 | 9 | 447,336 | 14,613 | 19 | 429.4 | 253.0 | $0.956 | $0.671–$1.341 |
| shipd-1-08158-3v-L1 | 4 | 398,003 | 11,750 | 18.5 | 481.3 | 343.7 | $0.825 | $0.702–$1.064 |
| shipd-1-09867-3v-L0 | 9 | 502,727 | 14,353 | 20 | 413.0 | 207.1 | $0.978 | $0.829–$1.245 |
| shipd-1-09867-3v-L1 | 4 | 451,492 | 13,178 | 20 | 379.7 | 209.2 | $0.927 | $0.820–$0.990 |

The BUE GIRL live series below retains all six attempts so that development failures remain visible. Cost bands cover cache uncertainty only. Unknown cost is not zero.

| Campaign | Prompt | Output | Requests | Wall s | Worker wall s | API-equivalent | End status |
|---|---|---|---|---|---|---|---|
| autocal-live-1 | unknown | unknown | 2 | 12.4 | 0.1 | unknown | blocked |
| autocal-live-2 | 419910 | 11853 | 12 | 258.6 | 96.6 | $0.901–$1.023 | cli_error |
| autocal-live-3 | 905764 | 21444 | 28 | 547.7 | 276.6 | $1.962–$2.083 | draft_not_verified |
| autocal-live-4 | 332552 | 10279 | 12 | 251.1 | 117.8 | $0.706–$0.830 | cli_error |
| autocal-live-5 | 293622 | 9933 | 12 | 398.7 | 263.7 | $0.625–$0.749 | cli_error |
| autocal-live-6 | 916635 | 19319 | 25 | 770.6 | 530.5 | $1.951–$2.075 | draft_not_verified |

The final live hull is autocal-live-6. It has 18 completed controller decisions, one failed controller attempt with recorded usage, and six completed intake calls: **25 attempts, 916,635 prompt / 19,319 output tokens, $1.951292–$2.075495**, and **770.6 s** inclusive wall time. Worker wall is 530.5 s, worker/child CPU is 521.9 s, and summed model latency including calibration is 216.3 s.

[The live result](AUTO_CALIBRATION.md#94-live-app-path-bue-girl-from-intake-no-hand-steps) remains an unverified draft: 38/39 built scored cells, RMS 32.6 mm, maximum 200.6 mm. Later code replays improved it, but those are separate results and are not new live-run cost measurements.

### Where the final live hull spends its model calls

| Phase | Prompt | Output | Requests | Summed model s | API-equivalent |
|---|---|---|---|---|---|
| intake_calibration | 32685 | 1967 | 6 | 42.1 | $0.026–$0.150 |
| views | 248455 | 4690 | 2 | 37.9 | $0.527–$0.527 |
| vessel | 152601 | 4247 | 3 | 33.8 | $0.348–$0.348 |
| setups | 202867 | 4097 | 4 | 38.7 | $0.447–$0.447 |
| complete | 280027 | 4318 | 10 | 63.9 | $0.603–$0.603 |

The controller part has 874,875 uncached input, 9,075 cache-read and zero cache-write tokens; intake adds 32,685 collapsed prompt tokens. The word complete is a controller phase name, not an acceptance result.

Across all 106 hull attempts, Sonnet accounts for 34,184,330 known prompt / 1,102,722 output tokens and 1,445 attempts. The controller-body split is 17,096,484 uncached input, 9,683,374 cache reads and 7,242,742 one-hour writes; another 161,730 prompt tokens are collapsed intake usage. The known API-equivalent subtotal is **$76.16–$76.77, plus three calls with unknown usage**. It is development spend, not cost per ship.

### Hull phases across all attempts

| Phase | Known prompt | Known output | Attempts | Summed model s | Known API-equivalent |
|---|---|---|---|---|---|
| complete | 15,113,120 | 316,715 | 618 | 4552.5 | $24.998–$24.998 + 1 unknown |
| intake_calibration | 161,730 | 9,798 | 32 | 217.1 | $0.130–$0.745 + 2 unknown |
| setups | 6,821,116 | 228,444 | 384 | 2983.1 | $20.220–$20.220 |
| vessel | 7,068,602 | 357,199 | 183 | 3060.2 | $17.228–$17.228 |
| views | 5,019,762 | 190,566 | 228 | 2141.6 | $13.584–$13.584 |

## Holdout arms: label questions

Each model arm has three repeats; each code arm has one. Tokens, attempts and repeat wall times below are listed in repeat order. Model repeat times exclude the shared code measurement. Code rows show only that measured code time; total code-arm wall was not recorded. No CAD worker times were recorded for these offset-table harnesses.

Crouton-arm request totals include failed transport attempts and DeepSeek fallback. They can exceed the summaries' logical turn counts. The lower-token result is based on provider-reported usage: OpenCode Go omits image tokens, and the Claude CLI includes its own prompt overhead. This is not a like-for-like measure of visual token efficiency.

| Case | Arm / campaign | Prompt R1/R2/R3 | Output R1/R2/R3 | Attempts R1/R2/R3 | Wall s R1/R2/R3 | API-equivalent |
|---|---|---|---|---|---|---|
| bue-girl | code | 0 | 0 | 0 | 3.2 code only | $0 |
| bue-girl | crouton | 2,087 / 6,311 / 6,060 | 235 / 345 / 310 | 17 / 25 / 27 | 178.5 / 361.8 / 472.1 | $0 Crouton component; see unknowns below |
| bue-girl | sonnet | unknown (0 reported) | unknown (0 reported) | 39 / 39 / 39 | 58.3 / 59.8 / 57.6 | unknown; access failure |
| bue-girl | sonnet-12b | 97,996 / 85,995 / 80,826 | 9,883 / 9,531 / 8,872 | 15 / 15 / 14 | 61.1 / 69.4 / 54.7 | $0.105–$0.491 per repeat |
| bumble-bee | code | 0 | 0 | 0 | 1.5 code only | $0 |
| bumble-bee | crouton | 4,022 / 2,869 / 2,869 | 365 / 346 / 367 | 22 / 19 / 22 | 302.1 / 160.7 / 267.0 | $0 Crouton component; see unknowns below |
| bumble-bee | sonnet | 107,220 / 102,344 / 108,201 | 7,878 / 8,101 / 9,758 | 17 / 17 / 18 | 50.3 / 49.4 / 72.0 | $0.100–$0.530 per repeat |
| pardon-me | code | 0 | 0 | 0 | 2.3 code only | $0 |
| pardon-me | crouton | 4,012 / 4,012 / 4,012 | 434 / 434 / 453 | 27 / 25 / 25 | 193.5 / 131.2 / 127.7 | $0 Crouton component; see unknowns below |
| pardon-me | sonnet | 132,029 / 132,032 / 132,036 | 4,309 / 4,443 / 4,021 | 25 / 25 / 25 | 47.2 / 54.0 / 51.0 | $0.067–$0.573 per repeat |

The separate shared code measurements are: BUE GIRL code 3.2 s, original Sonnet 3.4 s, Sonnet-12b 1.2 s, Crouton not recorded; BUMBLE BEE code 1.5 s and model arms 1.7 s; PARDON ME code 2.3 s, Crouton 2.8 s and Sonnet 2.7 s. These are not CAD times.

BUE GIRL Crouton repeat 2 includes the saved eight replies exactly once. Its 361.8 s is only the resumed active interval; the earlier interrupted interval is unknown. Do not interpret that time as full repeat duration. The original BUE GIRL Sonnet arm has 117 failed attempts and no usable replies; its code-fallback geometry is not a Sonnet accuracy result. The separately labelled sonnet-12b arm is the usable comparison.

Crouton-arm unknowns and fallback, by model:

| Case | Model | Attempts | Known prompt | Known output | Unknown usage attempts | API-equivalent |
|---|---|---|---|---|---|---|
| bue-girl | crouton-alpha-free | 61 | 5,781 | 718 | 25 | $0 known component |
| bue-girl | deepseek-v4.1-flash | 8 | 8,677 | 172 | 0 | price not found |
| bumble-bee | crouton-alpha-free | 62 | 8,607 | 1,057 | 8 | $0 known component |
| bumble-bee | deepseek-v4.1-flash | 1 | 1,153 | 21 | 0 | price not found |
| pardon-me | crouton-alpha-free | 77 | 12,036 | 1,321 | 2 | $0 known component |

Unknown usage stays flagged even on a zero-rate model. The full mixed-arm cost is not reported as zero when DeepSeek fallback has no price. Across all holdouts, the usable Sonnet calls have 978,679 prompt / 66,796 output tokens and a known subtotal of $0.864–$4.583; the 117 access failures remain additional unknowns.

## Tank label questions

The only retained cost evidence for tank reading is the published [raster development result](TANKS_V2.md#51-what-the-reader-does). It reports **168 Sonnet 5.5 calls, all completed, approximately 1.19 million prompt and 0.12 million output tokens across all development runs**. The calls read text/labels; geometry is produced by code. The prompt cache split and per-case request allocation cannot be recovered from that aggregate.

At the dated prices, that entire development workload is **approximately $1.44–$5.96 API-equivalent**, using the collapsed-prompt bounds. This is not a measured per-ship tank cost. The same aggregate implies about 7,083 prompt / 714 output tokens and $0.0086–$0.0355 per call as an average, not a uniform price for every question.

One fresh-cache D1 run at 300 dpi is documented at **81 s** and had the same scores as the cached replay. Its own requests, tokens, cache split, worker/CPU time and dollar total are not available. Total wall time for all 168 calls is also not available. The 81 s cannot be attached to the entire development workload.

Accuracy limits remain material: D1 300 dpi matched 20/24 rows, had 8.3% median volume error and a -14.3% total-volume error. D2 raster had 40.9% median volume error and +201% total-volume error. These are draft extraction results, not accepted capacity plans.

## One-ship hull plus tanks estimate

Use the final BUE GIRL live hull and reserve the **entire observed tank development workload** as a conservative per-ship tank allowance. This avoids inventing a per-case token allocation when the tank receipts are missing. It is a budgeting assumption, not evidence that a ship needs 168 tank calls.

- Hull: 25 attempts, 916,635 prompt / 19,319 output tokens; $1.951292–$2.075495.
- Tank allowance: 168 calls, approximately 1,190,000 prompt / 120,000 output tokens; $1.438–$5.960.
- Combined allowance: **193 attempts, approximately 2,106,635 prompt / 139,319 output tokens; $3.39–$8.04 API-equivalent**. A simple midpoint for planning is **$5.71**. The range follows cache-rate bounds and this workload assumption; it is not a forecast confidence interval or a guaranteed maximum. It includes neither missing future work nor engineering correction.

For time, a separate single-case reference is **770.6 + 81 = 851.6 s, or 14.2 minutes**, if hull and tank work run sequentially. Using the two recorded BUE GIRL draft wall times gives **10.5–14.2 minutes** after adding the same 81 s tank example. This varies the hull only: tank runtime variation is unknown. The price allowance uses many tank development runs, while this time reference uses one fresh-cache tank run; they are not a joint measurement of the same workload. Review and repairs add time.

BUE GIRL hull and D1 tanks belong to different vessels. No new model runs, images, CAD runs, or holdout scoring were used to construct this estimate.

## Three biggest cost drivers

1. **Repeated input context and cache writes.** Across hull attempts, uncached input costs about $34.19 and one-hour cache writes $28.97, against $10.93 for controller output and $1.94 for cache reads. Those input components dominate token dollars. In the final live hull, views, vessel and setups together cost $1.322 of the $1.925 controller component. Large repeated reading prompts matter more than the short calibration answers.
2. **Extra decisions, re-asks and retries.** The complete phase alone has 618 of 1,413 controller attempts (44%) and $25.00 in known cost (33% of the controller-body subtotal). Across all hull attempts, 70 of 1,445 attempts failed. Holdouts retain another 117 Sonnet access failures and 35 failed Crouton attempts. These consume wall time and can add unknown usage without improving a draft. Three fixed benchmark repeats are evaluation overhead, not a required production multiplier.
3. **CAD construction and rendering dominate local time.** The final live hull uses 530.5 worker wall seconds against 216.3 summed model seconds. Its describe_vessel calls take 168.4 s, first hull 137.3 s, renders 123.8 s and draft build 72.2 s. Across all selected hull attempts, first-hull builds sum to 10,445.9 worker s and renders to 6,300.1 s. Token prices exclude this compute cost. These are summed operation times, not additional elapsed time to add to case wall.

## Cheaper options already supported by results

Cost is secondary to correct geometry and coverage; the comparisons below do not establish that the cheapest model is suitable for every drawing.

| Option | Observed saving | Accuracy and time trade-off |
|---|---|---|
| Code-only labels on BUE GIRL | Zero model tokens/requests; 3.2 s measured code step, versus 14–15 Sonnet label requests and 54.7–69.4 s repeat wall. | Code and Sonnet-12b both give 37/39 cells, 1.4 mm RMS. Code is sufficient for numbering on this sheet. It still misses cells; hand-calibrated labels do not replace automatic intake, hull construction or review. |
| Crouton label arm on BUMBLE BEE (round invalid: its calibration swapped bow and stern; token figures stand, accuracy figures do not measure the reader) | 10,838 reported total tokens across repeats versus Sonnet 343,502: 31.7x fewer. Crouton is free; one DeepSeek fallback is unpriced. | Median RMS matches Sonnet at 0.127246 m, 51/54 cells. The first two tables agree; repeat 3 differs slightly. Both have identity errors and worse RMS than code-only (0.114051 m, 50/54). Crouton repeat wall is 160.7–302.1 s versus Sonnet 49.4–72.0 s. |
| Crouton label arm on PARDON ME | 13,357 reported total tokens across repeats versus Sonnet 408,870: 30.6x fewer; $0 known Crouton component. | Same table in all six model repeats: RMS 0.128777 m, 34/57 cells. Both improve two code identity errors but fail the 60% coverage rule at 59.6%; neither fixes the missing geometry. Crouton takes 127.7–193.5 s versus Sonnet 47.2–54.0 s. |
| Reuse saved tank answers for code replays | No new model calls for unchanged cached questions; the published cached and fresh D1 scores agree. | Valid only for unchanged image/prompt/model cache keys. It does not remove the first read, repair geometry errors, or establish a cached runtime saving because paired times are absent. |
| Use the existing vector tank path when a DXF is available | Avoid raster label inference on that path; token/time savings were not measured in this ledger. | On the same D2 drawing, vector median volume error is 10.2% and total +4.2%, against raster 40.9% and +201%. This requires vector source; it is not available for every scan. |

The roughly 30x token comparison is about recorded totals; prompt-only ratios and individual repeats differ, and image-token reporting is not equivalent. BUE GIRL Crouton is not a clean substitute either: two repeats equal code-only while the resumed repeat worsens to 27.8 mm RMS and 36/39 cells.

Label-task parity does not establish controller parity. [The stored Crouton drafting result](CONTINUATION_STATUS.md#2026-11-09-1255-sgt-drafting-model-setting-crouton-development-round-commit-66cf8f8) reports two failed development cases, tool-contract problems and token-limit runaway replies. The model setting can therefore be cheaper while costing accuracy or coverage on a different task.

Accuracy sources: [BUE GIRL rounds 12/12b](WHOLE_VESSEL_GUNNERUS.md#59-round-12-bue-girl-holdout-protocol-3511), [BUMBLE BEE results](holdouts/round13-bumble-bee.md#9-results-one-run-per-arm-2026-11-09), [PARDON ME results](holdouts/round14-pardon-me.md#11-results-one-run-per-arm-2026-11-09), and [tank results](TANKS_V2.md#52-metrics-last-run-of-each-case-with-the-final-code).

## Reproduce the accounting

From this worktree:

~~~bash
set -o pipefail
PYTHONPATH=src:. .venv/bin/python scripts/cost_per_ship.py
PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cost_per_ship.py -q
~~~

The default run regenerates work/cost_per_ship.json and work/cost_per_ship_runs.csv. Both are git-ignored derived data; do not commit them. An explicit --out selects another JSON path and a sibling <stem>_runs.csv. JSON retains source paths, per-model cache counters, per-phase totals and worker operations. CSV has one row per run; an unpriced run has blank total cost cells, with unpriced_requests and missing_usage_requests set. Known partial subtotals remain available in JSON. The tables above are a dated summary; changing source records requires regeneration and review.

Validation for this change: six offline accounting tests passed, and the script completed with 130 rows / 1,942 receipts / zero tank receipt files. No new inference or CAD validation was performed.
