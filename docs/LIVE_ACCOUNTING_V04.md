# Live provider accounting for MarinaFrame 0.4

This ledger counts original task journals and provider receipts. Copied task directories are excluded. Runtime completion, strict task integrity, pixel-bearing request receipts and semantic reconstruction correctness are separate claims.

**46 original v0.4 trials contain 224 intended requests: 223 completed, 1 failed, 0 unknown and 0 explicitly not sent.** Reported usage totals 2,196,623 prompt and 15,871 completion tokens. Cost coverage is 224/224 receipts, with reported sum $0.000000. The separate v0.3 unresolved reservation remains unknown.

## Cohort denominators

| Cohort | Trials | Intended / completed / failed / unknown / not sent | Prompt / completion tokens reported | Cost receipts / requests | Reported cost sum | Strictly valid / currently review-ready |
|---|---:|---|---:|---:|---:|---:|
| dev1 | 1 | 0 / 0 / 0 / 0 / 0 | 0 / 0 | 0 / 0 | $0.000000 | 1 / 0 |
| dev2 | 1 | 0 / 0 / 0 / 0 / 0 | 0 / 0 | 0 / 0 | $0.000000 | 0 / 0 |
| dev3 | 1 | 7 / 6 / 1 / 0 / 0 | 48,323 / 638 | 7 / 7 | $0.000000 | 1 / 0 |
| dev4 | 8 | 47 / 47 / 0 / 0 / 0 | 340,597 / 3,222 | 47 / 47 | $0.000000 | 2 / 0 |
| dev5 | 2 | 8 / 8 / 0 / 0 / 0 | 71,588 / 463 | 8 / 8 | $0.000000 | 2 / 2 |
| dev6 | 2 | 9 / 9 / 0 / 0 / 0 | 122,090 / 511 | 9 / 9 | $0.000000 | 2 / 2 |
| dev7 | 10 | 56 / 56 / 0 / 0 / 0 | 579,289 / 3,821 | 56 / 56 | $0.000000 | 10 / 6 |
| dev8-initial | 2 | 8 / 8 / 0 / 0 / 0 | 96,137 / 580 | 8 / 8 | $0.000000 | 2 / 1 |
| dev8-extension | 4 | 15 / 15 / 0 / 0 / 0 | 185,876 / 1,046 | 15 / 15 | $0.000000 | 4 / 1 |
| final-live | 15 | 74 / 74 / 0 / 0 / 0 | 752,723 / 5,590 | 74 / 74 | $0.000000 | 15 / 8 |

Reported zero cost means that a receipt explicitly returned zero. It is not proof of a zero-cost account, a total invoice, or absent charges when receipts are missing. Token totals similarly sum only reported fields. Every missing field remains visible in JSON coverage counts.

The initial dev8 two-trial cohort is retained separately from its predeclared four-trial extension. The extension never changes the original denominator. Final-live accounting was admitted only after its terminal output lock; no sealed source image/spec or independent evaluator reference was opened by this aggregator.

## Per-trial accounting

| Trial | Historical terminal status | I / C / F / U / N | Tokens P / C | Cost coverage | Builds reserved / confirmed | Revision | Assistant setup | Final strict result |
|---|---|---|---:|---:|---:|---|---:|---|
| dev1 deterministic | abstained | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| dev2 deterministic | awaiting_human_review | 0/0/0/0/0 | 0/0 | 0/0 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev3 live | provider_failed | 7/6/1/0/0 | 48,323/638 | 7/7 | 1/1 | r0001 | 0 | valid |
| dev4 live-campaign/ambiguity-trial-01 | awaiting_human_review | 8/8/0/0/0 | 58,271/560 | 8/8 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev4 live-campaign/ambiguity-trial-02 | awaiting_human_review | 8/8/0/0/0 | 58,080/560 | 8/8 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev4 live-campaign/missing-calibration-trial-01 | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| dev4 live-campaign/missing-calibration-trial-02 | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| dev4 live-campaign/retention-trial-01 | awaiting_human_review | 7/7/0/0/0 | 48,509/449 | 7/7 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev4 live-campaign/retention-trial-02 | awaiting_human_review | 8/8/0/0/0 | 60,978/555 | 8/8 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev4 live-campaign/tangency-trial-01 | awaiting_human_review | 8/8/0/0/0 | 57,348/527 | 8/8 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev4 live-campaign/tangency-trial-02 | awaiting_human_review | 8/8/0/0/0 | 57,411/571 | 8/8 | 1/1 | r0001 | 0 | cached_raw_audit_disagrees |
| dev5 trial-01/task | awaiting_human_review | 4/4/0/0/0 | 35,888/241 | 4/4 | 1/1 | r0001 | 3 | valid |
| dev5 trial-02/task | awaiting_human_review | 4/4/0/0/0 | 35,700/222 | 4/4 | 1/1 | r0001 | 3 | valid |
| dev6 trial-01/task | awaiting_human_review | 4/4/0/0/0 | 52,369/212 | 4/4 | 1/1 | r0001 | 3 | valid |
| dev6 trial-02/task | awaiting_human_review | 5/5/0/0/0 | 69,721/299 | 5/5 | 1/1 | r0001 | 3 | valid |
| dev7 controlled-trial-01/task | awaiting_human_review | 13/13/0/0/0 | 159,769/861 | 13/13 | 2/2 | r0002 | 3 | valid |
| dev7 controlled-trial-02/task | awaiting_human_review | 7/7/0/0/0 | 86,142/476 | 7/7 | 2/2 | r0002 | 3 | valid |
| dev7 live-campaign/ambiguity-trial-01 | abstained | 2/2/0/0/0 | 10,164/127 | 2/2 | 0/0 | r0000 | 0 | valid |
| dev7 live-campaign/ambiguity-trial-02 | abstained | 2/2/0/0/0 | 10,164/120 | 2/2 | 0/0 | r0000 | 0 | valid |
| dev7 live-campaign/missing-calibration-trial-01 | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| dev7 live-campaign/missing-calibration-trial-02 | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| dev7 live-campaign/retention-trial-01 | awaiting_human_review | 8/8/0/0/0 | 80,470/563 | 8/8 | 1/1 | r0001 | 0 | valid |
| dev7 live-campaign/retention-trial-02 | awaiting_human_review | 8/8/0/0/0 | 80,968/563 | 8/8 | 1/1 | r0001 | 0 | valid |
| dev7 live-campaign/tangency-trial-01 | awaiting_human_review | 8/8/0/0/0 | 75,953/569 | 8/8 | 1/1 | r0001 | 0 | valid |
| dev7 live-campaign/tangency-trial-02 | awaiting_human_review | 8/8/0/0/0 | 75,659/542 | 8/8 | 1/1 | r0001 | 0 | valid |
| dev8-initial trial-01/task | abstained | 1/1/0/0/0 | 10,852/112 | 1/1 | 1/1 | r0001 | 5 | valid |
| dev8-initial trial-02/task | awaiting_human_review | 7/7/0/0/0 | 85,285/468 | 7/7 | 2/2 | r0002 | 5 | valid |
| dev8-extension trial-03/task | abstained | 2/2/0/0/0 | 23,490/155 | 2/2 | 1/1 | r0001 | 5 | valid |
| dev8-extension trial-04/task | abstained | 4/4/0/0/0 | 48,738/238 | 4/4 | 1/1 | r0001 | 5 | valid |
| dev8-extension trial-05/task | awaiting_human_review | 8/8/0/0/0 | 102,835/558 | 8/8 | 2/2 | r0002 | 5 | valid |
| dev8-extension trial-06/task | abstained | 1/1/0/0/0 | 10,813/95 | 1/1 | 1/1 | r0001 | 5 | valid |
| final-live q_04e5b3a1 | awaiting_human_review | 8/8/0/0/0 | 105,959/613 | 8/8 | 1/1 | r0001 | 0 | valid |
| final-live q_15a6d9c0 | awaiting_human_review | 8/8/0/0/0 | 91,017/602 | 8/8 | 1/1 | r0001 | 0 | valid |
| final-live q_3bd4178e | awaiting_human_review | 7/7/0/0/0 | 64,099/518 | 7/7 | 1/1 | r0001 | 0 | valid |
| final-live q_40bc6a8d | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| final-live q_68de09f5 | abstained | 3/3/0/0/0 | 19,809/194 | 3/3 | 0/0 | r0000 | 0 | valid |
| final-live q_6fa9d080 | awaiting_human_review | 7/7/0/0/0 | 64,211/538 | 7/7 | 1/1 | r0001 | 0 | valid |
| final-live q_7c1052f4 | awaiting_human_review | 8/8/0/0/0 | 105,410/608 | 8/8 | 1/1 | r0001 | 0 | valid |
| final-live q_87c132d9 | awaiting_human_review | 7/7/0/0/0 | 64,441/520 | 7/7 | 1/1 | r0001 | 0 | valid |
| final-live q_912adc37 | awaiting_human_review | 7/7/0/0/0 | 87,087/525 | 7/7 | 1/1 | r0001 | 0 | valid |
| final-live q_a2538ce6 | abstained | 7/7/0/0/0 | 42,575/561 | 7/7 | 0/0 | r0001 | 0 | valid |
| final-live q_b970f41e | abstained | 4/4/0/0/0 | 27,006/285 | 4/4 | 0/0 | r0000 | 0 | valid |
| final-live q_ef943ab2 | awaiting_human_review | 8/8/0/0/0 | 81,109/626 | 8/8 | 1/1 | r0001 | 0 | valid |
| final-live r_09d3ea47 | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| final-live r_73b91d2a | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |
| final-live r_85ac0f61 | blocked | 0/0/0/0/0 | 0/0 | 0/0 | 0/0 | r0000 | 0 | valid |

## What each trial demonstrates

The final audit-bound view list matches completed image receipts to the STEP identity in the terminal validation contract. An empty list means that this particular classification has no matches; it does not prove that no STEP pixels were attached. In particular, an abstention without a final validation contract can still follow a request containing valid prior-candidate renders.

- **dev1 deterministic:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev2 deterministic:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev3 live:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev4 live-campaign/ambiguity-trial-01:** Historical ready label rejected by current strict verification; no current-ready credit. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev4 live-campaign/ambiguity-trial-02:** Historical ready label rejected by current strict verification; no current-ready credit. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev4 live-campaign/missing-calibration-trial-01:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev4 live-campaign/missing-calibration-trial-02:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev4 live-campaign/retention-trial-01:** Historical ready label rejected by current strict verification; no current-ready credit. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev4 live-campaign/retention-trial-02:** Historical ready label rejected by current strict verification; no current-ready credit. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev4 live-campaign/tangency-trial-01:** Historical ready label rejected by current strict verification; no current-ready credit. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev4 live-campaign/tangency-trial-02:** Historical ready label rejected by current strict verification; no current-ready credit. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev5 trial-01/task:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev5 trial-02/task:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev6 trial-01/task:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev6 trial-02/task:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev7 controlled-trial-01/task:** Model changed a selection after a candidate existed; complete prior/current two-view qualification not met. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev7 controlled-trial-02/task:** Model changed a selection after a candidate existed; complete prior/current two-view qualification not met. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev7 live-campaign/ambiguity-trial-01:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev7 live-campaign/ambiguity-trial-02:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev7 live-campaign/missing-calibration-trial-01:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev7 live-campaign/missing-calibration-trial-02:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev7 live-campaign/retention-trial-01:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s0, section_cut:s1, section_cut:s2.
- **dev7 live-campaign/retention-trial-02:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s0, section_cut:s1, section_cut:s2.
- **dev7 live-campaign/tangency-trial-01:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s2, section_cut:s3.
- **dev7 live-campaign/tangency-trial-02:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s2, section_cut:s3.
- **dev8-initial trial-01/task:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev8-initial trial-02/task:** Bound prior/current STEP images, model selection change and verified provisional candidate; semantic accuracy not inferred. Final audit-bound STEP views recorded on completed receipts: body, oblique.
- **dev8-extension trial-03/task:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev8-extension trial-04/task:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **dev8-extension trial-05/task:** Bound prior/current STEP images, model selection change and verified provisional candidate; semantic accuracy not inferred. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24.
- **dev8-extension trial-06/task:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live q_04e5b3a1:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s2, section_cut:s5.
- **final-live q_15a6d9c0:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s2, section_cut:s3, section_cut:s5.
- **final-live q_3bd4178e:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s2, section_cut:s3.
- **final-live q_40bc6a8d:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live q_68de09f5:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live q_6fa9d080:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s2, section_cut:s4.
- **final-live q_7c1052f4:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s3, section_cut:s5.
- **final-live q_87c132d9:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s2, section_cut:s5.
- **final-live q_912adc37:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s1, section_cut:s3, section_cut:s5.
- **final-live q_a2538ce6:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live q_b970f41e:** Retained refusal or failure; included in the attempt denominator. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live q_ef943ab2:** Verified provisional construction/current STEP inspection; no post-build model revision demonstrated. Final audit-bound STEP views recorded on completed receipts: body, oblique, section_cut:s2, section_cut:s4, section_cut:s5.
- **final-live r_09d3ea47:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live r_73b91d2a:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.
- **final-live r_85ac0f61:** No provider attempt; deterministic or admission control. Final audit-bound STEP views recorded on completed receipts: none classified.

## Separate published v0.3 history

The original records contain **six completed calls** (two capability probes and four task decisions), with **14,708 prompt and 390 completion tokens** reported. All six report observed cost $0. A seventh follow-up policy call was reserved and interrupted with **no provider completion or billing receipt**. Its transmission, tokens and cost remain unknown. It is never counted as zero or not-sent and is excluded from all v0.4 totals.

## Accounting rules and limits

- A completed provider receipt includes a valid returned decision. Failed decisions, including schema/summary violations, remain charged to the intended denominator and retain any reported usage/cost.
- Explicit not-sent means the journal records that state; absence of a receipt is classified unknown. A task rejected before a provider intent contributes a trial but no request.
- Every request is identified by original task ID and request ID. Duplicate copied identities are excluded from aggregate request totals and listed separately.
- Old dev2/dev4 ready labels that fail the current strict numeric/audit reader remain rejected. Their provider usage remains part of historical accounting; their ready labels receive no current verified-success credit.
- Completed pixel-bearing request receipts prove attached, bound image payload metadata, not that the model understood a drawing or that the selected interpretation is correct.
- Assistant seed selection/build/render actions are counted separately. A model correction is not credited as a complete visual revision sequence unless prior and current STEP body/oblique receipts, changed selection, new build and final strict verification are present.
- Development strict verification uses the unchanged final frozen binary. Final-live uses existing strict verification outputs bound by the terminal output lock, avoiding any independent reference/source inspection.
- The aggregator opens no provider request payload, credential text, sealed source pixels/specifications or independent evaluator reference. It performs no native job, provider call, retry or evidence rewrite.

## Repeated dev8 interpretation

Trial02 and trial05 selected the same candidate IDs: **True**. Their CAD section bytes match: **True**. Full selection-document bytes match: **True**. Both sequence qualifications are retained in the JSON alongside exact event/request IDs. This comparison reads existing candidate/selection artifacts only; it does not rerun CAD or establish independent contour truth.

## Evidence and reproducibility

The accounting directory contains `accounting.json`, `provider-attempts.jsonl`, `provider-attempts.md`, `source-inventory.json`, the separate historical ledger, strict-verification results embedded per trial, and the immutable initial and final snapshots. The original runtime paths and SHA-256 identities permit auditing every counted receipt.

Reproduce with `python benchmarks/v04_live_accounting.py --out /tmp/NEW_ACCOUNTING` for the original cohort; add `--include-dev8-extension` for the four separately declared additional trials. The final-live output lock is mandatory and checked by hash. All candidates retain `engineering_approved=false`.

## Final interpretation and retained snapshots

The final ledger covers **31 original development/control trials plus 15 locked final-live trials**. The 46 histories contain **36 confirmed build attempts** and **48 assistant setup actions**. There are **39 strictly valid histories and 20 current review-ready labels**; these heterogeneous development and locked-run outcomes are not an accuracy rate. All seven rejected histories are the preserved dev2/dev4 `cached_raw_audit_disagrees` cases.

The two qualifying dev8 visual revisions are **1/2 in the original cohort, 1/4 in the predeclared extension, and 2/6 combined**. The four other repetitions abstained. Both qualifying runs reach the same selected IDs, selection document and CAD section bytes. This is a repeated controlled case, not two independent vessel generalization results.

All 42 initial trial rows are identical in canonical JSON within the final 46-row accounting; the extension adds 15 provider requests. Both complete snapshots and [denominator-preservation.json](../artifacts/v04/live/accounting/denominator-preservation.json) are retained. The aggregator checks only admitted runtime records against the final-live output lock; it does not open all 2,164 locked files or any independent reference/source data.

The authoritative derived ledger is [accounting.json](../artifacts/v04/live/accounting/accounting.json), with [one row per provider request](../artifacts/v04/live/accounting/provider-attempts.md), [structured request records](../artifacts/v04/live/accounting/provider-attempts.jsonl), [source hashes](../artifacts/v04/live/accounting/source-inventory.json), and [the separate v0.3 history](../artifacts/v04/live/accounting/historical-v03-separate.json). The first collector pass retained verification failures but omitted their stderr error codes; corrected snapshots preserve the exact code. That bookkeeping correction changed no original evidence or accounting totals.

## First-request prior pixels in all six dev8 trials

All six first completed requests attached **both body and oblique pixels bound to the valid assistant-seeded r0001 STEP**. This includes the four abstained trials. Each exact receipt is committed at event 32, follows its prior build at event 18 and request intent at event 31, and matches the generation, revision and STEP hash of that prior candidate. All six terminal histories pass the recorded current strict verification.

| Trial | Terminal outcome | First completed request has bound prior body + oblique | Final validation STEP binding | Original final audit-bound view list |
|---|---|---|---|---|
| trial-01 | abstained | Yes | Absent | Empty; no terminal binding |
| trial-02 | awaiting_human_review | Yes | Present | body, oblique |
| trial-03 | abstained | Yes | Absent | Empty; no terminal binding |
| trial-04 | abstained | Yes | Absent | Empty; no terminal binding |
| trial-05 | awaiting_human_review | Yes | Present | body, oblique, section_cut:frame-00, section_cut:frame-08, section_cut:frame-24 |
| trial-06 | abstained | Yes | Absent | Empty; no terminal binding |

The earlier JSON key `final_current_STEP_views_on_completed_receipts` and both original snapshots are retained byte-for-byte. Its name was too broad: it additionally requires the terminal validation contract’s STEP binding. The four abstentions have no such binding, so the field is empty even though their first requests carried the prior pixels. The prose now describes this as the **final audit-bound** view list. This correction changes no request count, outcome, build count or success denominator: the controlled initial cohort remains 1/2, its extension 1/4, and the combined set 2/6.

`artifacts/v04/live/accounting/dev8-first-request-pixels.json` retains all six first request IDs, receipt and event hashes, seed-build identities, exact body/oblique image hashes, terminal checkpoint hashes and input inventory. The derivation checked 20 existing accounting/state/receipt/event files before and after; every byte identity was unchanged. It read no source pixels, request payload, key or independent reference and made zero provider/native calls. Attached pixels do not establish the model’s attention or semantic understanding.

Reproduce this clarification from the preserved original development task paths and accounting with `python benchmarks/v04_accounting_pixel_clarification.py --accounting artifacts/v04/live/accounting --out /tmp/NEW_PIXEL_CLARIFICATION.json`. Use a new output file. The frozen accounting snapshots remain the primary denominator record.
