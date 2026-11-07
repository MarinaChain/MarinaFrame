# Independent measurement of the initial development repair

The representative live revision improved the actual exported geometry substantially, while retaining a serious lower-endpoint defect. Across three measured stations, transverse RMS error fell from **2.880574 m to 0.048361 m**. The revised frame-08 lower endpoint remained **1.302507 m, or 54.5 source pixels**, away from the declared zero-keel reference. This is a useful controlled repair demonstration with `engineering_approved=false`; it is not evidence of production vessel accuracy.

## Experiment and denominator

The measurement was recorded on **2026-11-06 at 22:18:39 UTC**, after the initial two dev8 trials had terminated. Trial 01 abstained. Trial 02 reached `awaiting_human_review`, so the initial cohort is **one of two attempts**, not a selected-success-only denominator. Subsequent predeclared trial extensions are outside this two-task measurement; the campaign summary must retain their outcomes and use its full denominator.

Five explicit `assistant_operator` actions prepared each prior candidate: inspect the source, select retained vertical grid-stroke alternatives, build the provisional model, render its body view, and render its oblique view. The starting fault was therefore deliberately introduced. In representative trial 02, the live model then inspected the source, validated the prior candidate, selected the curved source hypotheses, rebuilt, rendered both views, and requested review. This report measures the original `r0001` and revised `r0002` STEP files from that completed task. It does not tune source processing, make model calls, or rebuild either model.

The source is the already-known procedural development drawing `holdout_roundflare-271097-drafting`. Only original stations **0, 8 and 24** were supplied. Their station positions, viewports, scales and height extents are unchanged. The new sealed evaluation was not accessed. The old development reference was read only after these inference runs had terminated. Its original “holdout” pathname does not make this an independent holdout evaluation now.

## Measurement method

The evaluator independently reimports each actual `model.step` and intersects it at the three original station planes. It compares the nonnegative half-section ordinate **actual y(z) − reference y(z)** at **4,097 uniformly spaced heights per station, including both endpoints**. This is a transverse ordinate-distance convention, not nearest-point or Hausdorff distance.

The reference contains 129 declared points per station. Linear interpolation supplies the comparison ordinate at the 4,097 requested heights; this denser sampling does not create additional reference truth. The retained helper handles straight and degree-1 B-spline STEP boundaries with a fixed **1 nm** endpoint tolerance. A horizontal closing edge is compared at its outer boundary at the declared upper/lower endpoints. Absent, ambiguous or unsupported boundaries would remain unresolved and prevent complete-domain metrics. No requested sample is silently dropped.

All **24,582 requested ordinates** resolved: 12,291 for each STEP, with 4,097/4,097 at each station. Both reimports were valid one-solid shapes. Each of the 12 upper/lower endpoints was explicitly compared. The revised cuts used numerical endpoint-tolerance assistance at 103, 98 and 101 sampled heights respectively; these adjustments are bounded by the fixed 1 nm tolerance and are recorded. Every original and revised cut segment, sampled ordinate, status and error is retained in the evidence.

Source-pixel errors use the unchanged **41.842395189754775 pixels/m** calibration. Aggregate metrics pool the same number of uniformly spaced heights from each station. Both terminal task trees were hashed before and after measurement: **412 files were unchanged**.

## Actual exported STEP errors

| Metric, all three stations | Prior m | Prior mm | Prior source px | Revised m | Revised mm | Revised source px |
|---|---:|---:|---:|---:|---:|---:|
| RMS | 2.880574 | 2880.574 | 120.5301 | 0.048361 | 48.361 | 2.0235 |
| 95th-percentile absolute | 3.998633 | 3998.633 | 167.3124 | 0.030322 | 30.322 | 1.2688 |
| Maximum absolute | 4.108849 | 4108.849 | 171.9241 | 1.302507 | 1302.507 | 54.5000 |

On this deliberately bad prior candidate, RMS decreased by 98.32%, p95 by 99.24%, and maximum error by 68.30%. Those percentages describe this paired development repair. They are not a general reconstruction success rate.

| Station | Prior RMS, m | Revised RMS, m | Revised p95, m | Revised maximum, m | Coverage per STEP |
|---|---:|---:|---:|---:|---:|
| frame-00 | 2.603419 | 0.026446 | 0.030285 | 0.191194 | 4097/4097 |
| frame-08 | 3.184760 | 0.075442 | 0.030728 | 1.302507 | 4097/4097 |
| frame-24 | 2.823584 | 0.025012 | 0.030247 | 0.155345 | 4097/4097 |

### The endpoint defect remains

The revised curve follows most of the declared profile closely, but the selected centroid interpretation still starts too far from the centerline at the lowest row. All three declared reference lower endpoints have y=0. The actual revised lower endpoints remain positive:

| Station | Lower endpoint error, m | Error, mm | Error, source px | Upper endpoint absolute error, m / mm / px |
|---|---:|---:|---:|---:|
| frame-00 | 0.191194 | 191.194 | 8.0 | 0.017319 / 17.319 / 0.7247 |
| frame-08 | 1.302507 | 1302.507 | 54.5 | 0.034035 / 34.035 / 1.4241 |
| frame-24 | 0.155345 | 155.345 | 6.5 | 0.029144 / 29.144 / 1.2195 |

The 30.32 mm aggregate p95 does not describe the worst geometry. The full endpoint error is preserved in the maximum metric and marked explicitly on the frame-08 plot. The harness's consistency check against selected source geometry does not certify that the selection itself has the correct semantic endpoint. Review readiness must remain separate from engineering approval.

## Same-scale figures and visual inspection

The evaluator actually viewed the exact frame-08 source crop and both body/oblique renders for both revisions. The initial body projection is rectangular and the initial oblique form is angular. The revised body projection follows a curved lower envelope, while the revised oblique view shows a rounded transverse profile and longitudinal faceting. These original renders use independent automatic scales, so apparent pixel sizes were not used for the measurement.

The following new figures use the measured STEP cuts on **identical physical axes, equal unit aspect, and the same orientation**. The original figures are retained; a presentation-only script moved legends outside the data and gave the endpoint annotation a background. No numeric data changed. Both final figures were opened and visually checked. The complete observations, source/render identities and limitations are recorded in `visual-ledger.json`.

![Frame08 actual STEP before/after on identical physical axes](../artifacts/v04/live/independent-measurement/plots/frame08-step-before-after.png)

![All three actual STEP sections on identical physical axes](../artifacts/v04/live/independent-measurement/plots/all-stations-step-comparison.png)

## Actual envelope dimensions, with no mismatched volume target

| Independently reimported quantity | Prior r0001 | Revised r0002 |
|---|---:|---:|
| Enclosed envelope volume, m³ | 641.709996 | 669.830136 |
| Length, m | 46.461680 | 46.461680 |
| Maximum beam, m | 8.173528 | 10.874138 |
| Depth, m | 2.534694 | 2.534694 |

The original reference has 25 stations; these models have only three. No equivalent three-station reference volume is supplied, so **no volume-error percentage is computed against the 25-station hull**. The volumes above describe the produced envelopes under the supplied symmetry and flat terminal-closure assumptions. They are not steel volumes or automatic displacement estimates.

## Evidence and reproduction

Evidence root: `artifacts/v04/live/independent-measurement/`.

- `measurement/measurement.json`: exact source, reference, task, STEP, selection and helper hashes; setup/live decisions; complete results and caveats.
- `measurement/*-samples.csv` and `*-actual-cut-segments.json`: all requested samples and actual STEP cut boundaries.
- `measure_step_repair.py`: executed read-only evaluator. Its exact source hash is bound in the measurement report.
- `plot_measured_samples.py`: presentation-only plot derivation, with measurement/CSV hash verification and no native geometry calls.
- `plots/`: inspected PNG and PDF figures plus their identity manifest.
- `visual-inputs.json`, `visual-ledger.json`: the source/render provenance and actual visual inspection record.
- `publication-copy-identity.json`: completed `/tmp` outputs were copied and compared byte-for-byte with the evidence copies.

The STEP identities are:

| Revision | SHA-256 |
|---|---|
| r0001 | `6870752bfaf1a68b39f0d862181c57deb459c39c53fe89dcddb962a2383c95a7` |
| r0002 | `68a3fb74cf3c645c4f2d8116cfcfdef09da51d1b6bd7fdb2bfdfd1e71fc41afd` |

Reproduction requires the retained completed trial tasks, the authorized old development reference, and the pinned native environment. Run the evaluator with a fresh `/tmp` output directory and acquire the shared native admission lock as the script does. Never run it during an exclusive performance window. The report includes the original absolute input paths; the artifact bundle retains hashes and complete numeric observations for independent inspection without rerunning inference.
