# Independent review of the MarinaFrame 0.4 main report

This note preserves two review cutoffs. The initial review below excluded the
then-unreleased final evaluation. The final addendum completes the review of
the subsequently admitted accuracy results and current decision summary;
final publication/privacy gates remain separately owned.

## Initial scope and outcome

The data/learning/accounting workstream reviewed the separately authored
`docs/V04_REPORT.md` against completed nonsealed reports and selected retained
ledgers. Sections **1–6 and 8–13** are in scope. **Section 7, pending final
assistant/evaluator results, sealed references and evaluator code were excluded.**
This is an independent claim review of the main report, not an independent
repeat of every experiment or a certification of every implementation assertion.

One factual wording error was corrected by the report author: the degraded
parity drawing is a different procedural seed, not a degraded copy of the clean
known47 drawing. A misleading label in this reviewer's accounting report was
also corrected with a separate first-request receipt proof. No remaining material
contradiction was located in the quantitative claim clusters reviewed here.
The final accuracy and release/package sections still require their later
admitted evidence; this note does not approve those pending results.

The exact reviewed main-report SHA-256 is
`1d9b714892f24f0bd48c735217959eb829a929975e0904ea398986e5e0f0b41f`. A separate hash covers only the sections
reviewed. `artifacts/v04/live/accounting/main-report-review.json` records those
identities, the evidence/report hashes and the findings below. Later edits to
the main report are outside this exact cutoff unless reviewed separately.

## Findings and resolution

| Finding | Evidence and implication | Resolution |
|---|---|---|
| R1 — Different degraded source | `cohort.json` identifies clean `roundflare-271097-drafting` and degraded `roundflare-271013-degraded`. A same-hull degradation effect cannot be inferred from their comparison. | The main report now says “a separate degraded 25-station development drawing.” The corrected text was observed. No timed work was rerun. |
| R2 — Overbroad final-view label | The original accounting field requires a STEP hash in the terminal validation contract. Trials 01/03/04/06 abstained without that binding, so their empty lists did not establish that no STEP pixels were attached. | The accounting prose and renderer now say “final audit-bound.” A separate proof confirms all six first completed requests contain both prior views. Original snapshots, outcomes and denominators are unchanged. |
| R3 — Learning replication caveat | The two optimizer runs share training/validation data and selected weights. The first exploratory heuristic search reached its bound; the second expanded it and reserved a new tumblehome test family. | The report author added the shared train/validation data, expanded baseline search, new test family and development status of the earlier test. The corrected text was observed. Accuracy and error counts match the learning report. |

## Bound first-request pixels

All **six** dev8 first completed requests attach body and oblique images whose
STEP hash, generation and revision match the valid assistant-seeded r0001
candidate. Each build is recorded at event 18, intent at event 31 and completed
receipt at event 32. All six terminal histories have retained passing strict
verification. The four abstentions therefore are **pixel-visible attempts**;
this does not establish that the model understood or correctly interpreted the
images. Their five setup actions remain explicit assistant actions.

The separate reproducible derivation is
`benchmarks/v04_accounting_pixel_clarification.py`. Its retained output is
`artifacts/v04/live/accounting/dev8-first-request-pixels.json`, SHA-256
`8244d747c91c8391b9a11c0221c9298e3744e890dadb2e465d978458b17d85ed`.
It binds each exact receipt, committed event, seed candidate, body/oblique image
hash and terminal checkpoint. Twenty accounting/state/receipt/event files were
read and rehashed unchanged, and the completed proof copy matched across a
later tool boundary. No source pixels, request payload, credential, sealed
reference, provider call or native worker was used.

All **29 files** in the pre-clarification accounting publication manifest remain
byte-identical. The old JSON field and frozen report snapshots are preserved as
historical derived records; the new clarification explains their narrower
meaning. The result denominator remains **1/2 initial, 1/4 extension, 2/6 combined**.

## Quantitative claims cross-checked

| Claim cluster | Cross-check and retained limitation |
|---|---|
| Live accounting | 46 original task attempts, 224 intended requests, 223 completed and one failed; 2,196,623 prompt and 15,871 completion tokens; 800 attachment entries on 200 requests, 199 completed. Reported zero cost is not an invoice claim. Seven older histories remain rejected; historical v0.3 uncertainty remains separate. |
| Controlled visual repair | One measured successful development repair has STEP ordinate RMS 2.880574 m → 0.048361 m, with the 1.302507 m endpoint error retained. The two successful repetitions select the same interpretation; the six-trial denominator and assistant fault seeding remain explicit. |
| Source fidelity | The tangency result still fails the unchanged maximum gate; the known47 endpoint policy improves local error while volume worsens slightly. The raw 43.264475 mm spur discrepancy remains above 1.1 mm. `geometry.py` and `pipeline.py` have no changes across the published base and application freeze; the documented changes are source interpretation/sampling and contract handling. |
| Control-plane parity | Six eligible geometry pairs, identical normalized decisions/selected geometry and STEP DATA, 4.0–11.3% mean Rust wall overhead, separate sampled controller/native memory, refused cohorts outside ratios, and limited two-repeat/shared-host scope. |
| Data and local training | Six ALMA assets are one vessel; rights purposes and restricted distribution remain separate. There is no expert authentic gold set. Actual small-model weights and procedural results are distinct from DeepSeek fine-tuning and authentic scan generalization. |
| Recovery and compatibility | The process-group bug is corrected; seven older cached-number histories remain rejected without rewrite. The controlled copy probe does not explain or prove repair of the separate native-workload workspace anomaly. |
| Verification and dependencies | The retained summaries support 411 baseline Python, 670 current Python, 26 distinct Rust tests/54 executions, installed/native/browser scopes, the failed workspace smoke and unchanged /tmp pass. Dependency results are dated, the three VTK advisories remain, and 32 off-target notice texts are uninspected. |

The main report keeps source-trace consistency, independently measured shape,
provisional review readiness and professional engineering approval distinct.
No new native/provider work or change to production code was made for this
review. The pending final evaluation and final release scan remain outside the
conclusion above.

## Final admitted evaluation and decision-summary review

After all automated and assistant outputs were locked and scoring was released,
this reviewer read the complete independent evaluation report, the main report's
completed Section 7, the decision summary and relevant updated release paragraphs.
The following exact document cutoffs were reviewed:

| Document | SHA-256 |
| --- | --- |
| `docs/V04_REPORT.md` | `1bad2c8ac183e4f3a798c3df1ef923e3b1d0b831a9c3f6b0791b0eae1da816bb` |
| `docs/DECISION_SUMMARY_V04.md` | `33e1de15299c79598b771c66cc7f3b48372ec4c959949e3f1ee9560f026e2971` |
| `docs/INDEPENDENT_EVALUATION_V04.md` | `c8a64a78bd3bc74fcb2de048563d4625d5d377a28f89c6fe2607d9c866916847` |

The evidence is retained in
`artifacts/v04/evaluation/independent-claim-review/`: reviewed document snapshots,
the read-only checker and `review.json` (SHA-256
`a0610c55ba45410d3cb58775bad1bb674a735e790bc4a2b51a6054401ffe326d`).
The checker reads released records and compares counts and hashes; it neither
re-scores geometry nor imports the reconstruction or evaluator implementation.
All **92 score files** matched the released per-case ledger, and all **39
measurement files** matched their score bindings. Every arm/cohort summary count
and paired-family all-pass count was recomputed from those score records. All
**148 inspected files** remained unchanged across the check. The original
summary remains SHA-256
`d7576b332fc1fae15da52d403ff4f74337d648080745ab12c4373aa107e860f8`.

### Additional findings and observed corrections

| Finding | Evidence and observed correction |
| --- | --- |
| R4 — Initial intake denominator wording | The retained 30-attempt intake cohort contains **24 procedural executions affected by fractional ROI bounds and six unchanged intentionally incomplete authentic-partial executions**. Original diagnostic records distinguish those failures. The reports now use that split and identify the schema-only check's missed, stricter engine integer-ROI requirement. The summary's historical broad field name and all original scoring bytes remain unchanged. The total remains **92 primary + 30 initial = 122 launched case executions**. |
| R5 — Pass-rate equality versus numerical accuracy | All eight supported cases pass in both published 0.3 and the current arms, but their numerical outputs differ. The decision summary now says **no supported-geometry pass-rate gain**. The main report also discloses that current RMS increases on seven cases and decreases on one. The largest RMS increase is **0.002790928696351 px / 0.024919006217420 mm**, from 0.645162417981514 to 0.647953346677865 px on `q_912adc37`; the largest local-maximum increase is **0.037919484420173 px** on `q_3bd4178e`. These are small measured regressions within the fixed gates, without a population-performance inference. |

The evaluator's independent intake wording correction is recorded in commit
`6dff49f` and `intake_preflight_wording_clarification.json`; it does not change
the original summary or measurements. Both corrected claim clusters were
observed in the exact main/decision/evaluator versions above. No remaining
material factual contradiction was found in the reviewed claim clusters.

### Denominators, accuracy and evidence limits

| Claim | Independent record check |
| --- | --- |
| Supported reconstruction | Published 0.2 passes **4/8**; published 0.3, current Python, current Rust and live DeepSeek each pass **8/8**, representing four paired families. All eight exports pass in each latter arm. The four absent 0.2 grid-case exports remain failures in the attempted denominator. |
| Original-four negatives and separate sensitivity | The original refusal-label tally stays **4/4, 2/4, 2/4, 4/4, 4/4** explicit refusals in the same arm order. The pre-outcome interior-loop qualification is retained; ready exterior-envelope candidates do not by themselves prove wrong hull geometry. Excluding that one case gives three sensitivity negatives: both Python harnesses explicitly refuse **2/3**, safely stop on **3/3**; 0.2/Rust/live explicitly refuse **3/3**. |
| Authentic partial inputs | All five automated arms have **zero ready candidates and zero exports on the three authentic partial inputs**. The two Python harnesses have three diagnostic no-progress stops each; the other arms have three explicit blocks each. No authentic 3D gold or measured full-vessel accuracy is inferred. Missing declared calibration tests the input contract even when a scale bar is visible. |
| Current-arm output identity | The retained identity ledger shows equal selected-trace coordinate and STEP DATA hashes for current Python/Rust/live on **8/8** cases, while 0.3 differs on all eight. This review checked those ledger comparisons and bound full-STEP hashes against the per-case scores; it did not rerun STEP parsing. Header differences are not treated as geometry differences. |
| Measurement coverage | Bound measurement arrays total **39 exports, 195 station cuts, 798,915 required ordinates and 25,243 selected-trace samples**, with zero unresolved values. The count includes two original-label-violating diagnostic exports and the assisted export. Selected-trace consistency remains distinct from correct source interpretation and independently measured shape. |
| Pixel baseline | **10,451/10,460** supported source rows resolve; nine unresolved rows remain. All 15 pixel attempts produce no CAD and are not counted as 3D successes. |
| Live resources | The 15 final tasks have **74 completed requests**, 752,723 prompt and 5,590 completion tokens; eight ready, three abstained, four blocked. Reported observed cost 0, nominal list cost $0.11304483 and unknown invoice/subscription cost remain distinct. The final cases demonstrate current-pixel workflow, not a new repair or accuracy advantage. |
| Assistant sample | The sampling receipt matches its pre-handoff commitment and the two actual attempt IDs: smallest scanned-source hash plus the sole predeclared ambiguity diagnostic. One supported pass and one abstention, six interventions and 554.012 seconds remain separately reported. There is no human-engineer arm or population estimate; zero external task-provider calls does not price assistant conversation use. |

The 92 primary executions consist of **75 automated CAD-capable attempts, 15
pixel attempts and two assistant-operated attempts**. All five automated CAD
arms have 15 terminal records and no primary inference execution failure,
resource-limit termination or watchdog interruption. The diagnostic stops and
false refusals are not removed from those denominators. The checker itself had
two construction stops before its final pass: an omitted original-negative
filter and an attempted read of intentionally absent gold metrics on diagnostic
exports. Both reviewer-only corrections are explicitly recorded in `review.json`;
neither changed evaluation records or manufactured a metric for missing gold.

### Release paragraphs and remaining review boundary

The delivered wheel bytes match **195,930 bytes**, SHA-256
`6b422e6b84280440c1164aea0767078936d8b9ce814fc0157abbac130fdd6e59`.
The retained comparison identifies README metadata-only changes in `METADATA`
and `RECORD`, with the 32 executable/package-data members identical to the
previously tested wheel. The extracted-runtime receipt records 460 verified
payload members and the nine-check smoke's **16.195884677 seconds**, which
supports the report's 16.20-second rounded claim. It explicitly reused the
validated native environment and did not install the refreshed wheel as a new
independent dependency environment.

The earlier independent five-item public-subset review and Pillow 13 replay
remain consistent with the main report: strict construction emits zero authentic
gold/training rows, historical Pillow 12.3 training results retain their original
environment identity, and the compatibility replay is not retraining or a new
untouched test. The main report keeps the known VTK advisories, off-target
notice gaps, package-review scope and unresolved workspace publication anomaly
visible.

**Final postcommit privacy/source-history scans and scans/identities of the
actual delivered archives are separate release gates. This reviewer has not
independently executed or approved those final gates.** Their later receipts
must accompany the delivery. The main report's final archive-verification
wording is not accepted here as evidence in place of those receipts. No native
job, provider call, training run, dependency mutation, production-source edit or
new accuracy experiment was performed for this final claim review.
