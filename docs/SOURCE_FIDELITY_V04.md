# Source fidelity development in 0.4

## Result and scope

Two narrow source improvements are implemented: an explicit alternative for a connected lower endpoint, and bounded retention of observed row features before CAD. They substantially reduce the old known 47 tangency error. The formerly final 12 tangency case still fails its original maximum-error gate. This is a measured development plateau, not an accuracy or engineering approval claim.

The baseline is the exact published draft PR #2 source `5b0b48e3dd9bcef25427d27ce800118935f58d1a`. The old 47 suite and old final 12 are both known development data. They were not relabeled as holdouts. No reference geometry, analytic family, target volume, error score, or evaluator image was supplied to candidate generation or selection. All numerical reference comparisons happened after terminal reconstruction outputs existed.

Controlled source experiments retain the published domain/controller implementation and change only `ingest.py` and the source-inspection helpers below `_adaptive_anchors` in `agent_tools.py`. Their captured module hashes distinguish them from integrated 0.4 acceptance. Each candidate received one fresh native validation; these experiments did not use the old cache/finish behavior. The separate 0.4 validation contract work fixes that behavior.

## Source changes

A broad original horizontal run is classified before any selection corridor can clip it into an apparent curve. A photometrically separated shorter stroke can now be retained from a pale ruler crossing. Uniform broad ink stays excluded. The unchanged source image and sustained competing strokes remain evidence. Retained contrast subsets have coordinates, thresholds, counts, and explicit truncation reporting; contrast does not certify a contour's identity.

The new endpoint interpretation requires actual connected ink reaching the calibrated centreline at the lower boundary, a neighboring curved approach, and connected trace witnesses. A uniform ruler, disconnected centreline mark, or horizontal-bottom/vertical-side corner does not qualify. The catalog retains the row-centroid interpretation and supplies the new interpretation through another opaque candidate ID. `endpoint_evidence.centroid_alternative_id` links the two. Both are ordinary provisional choices. Selection still constrains measurement of actual ink; it does not inject an exact synthetic endpoint. The measured endpoints in the two affected cases remain one source pixel from the centreline.

The former fixed 129-height output grid could erase a narrow observed chine before the existing 1 mm CAD approximation saw it. The updated sampler treats `sample_count` as minimum density, inserts source knots, and verifies a maximum 0.25 pixel ordinate interpolation loss over the complete measured piecewise-linear trace. It retains zero/positive transitions. The existing 1025-point limit remains a blocking resource limit. This 0.25 pixel bound applies to resampling loss, not raster accuracy, source identity, calibration, or unknown geometry between source pixels.

`geometry.py`, native CAD construction tolerances, raw STEP fidelity gates, and original accuracy gates are unchanged.

## Repeated affected-case results

### Former final 12 case `f_48d25a23fca95e80`

Fresh source selection, CAD export, four named STEP reimport views, and raw native fidelity checks completed for all three iterations. Independent STEP cuts at all three stations were compared at 4097 heights each, including terminal caps and explicit outer endpoints of horizontal closures. All 12,291 requested ordinates were resolved in every iteration.

| Metric | Published 0.3 baseline | Endpoint alternative | Endpoint plus row knots |
|---|---:|---:|---:|
| `s3` lower endpoint error | 133.333mm | 16.667mm | 16.667mm |
| Maximum local error | 133.333mm | 109.323mm | 105.006mm |
| Declared CAD section RMS | 18.417mm | 19.538mm | 19.283mm |
| Reimported STEP volume error | 2.0201% | 2.0705% | 2.0598% |
| Original maximum-error gate | FAIL | FAIL | FAIL |

The original gates remain 3% volume, 33.333 mm section RMS, and 66.667 mm maximum local error. The later maximum occurs at `s3`, z=0.0054052734m, where the actual STEP half-breadth is 0.0815299479 m and the analytic reference is 0.1865359875 m. This lies within the first vertical source-pixel row. The source-supported endpoint improves the incorrect bottom location, but a line between row observations still underspecifies the strongly curved subpixel tangency. RMS slightly worsens relative to the original baseline. No hull-family fit or gate change was introduced to hide that tradeoff.

### Known 47 case `holdout_roundflare-271097-drafting`

Fresh 25-station baseline and updated source-policy runs completed, with all 25 selections, valid single-solid STEP, and successful fresh raw source-to-STEP checks. Full-case source ordinate maximum decreased from 1.302506698 m to 0.089033309 m; RMS decreased from 0.064418029 m to 0.023500589 m. `frame-08`'s baseline endpoint decreased from 1.302506698 m to 0.023899205 m, one pixel at the declared scale.

Independent cuts of the exported STEP confirm the affected maximum changed from 1.302506698 m to 0.089033309 m. All 4,097 requested ordinates at each predeclared cut (`frame-00`, affected `frame-08`, and `frame-24`) resolve in both runs. At the two terminal cuts, maxima improve from 430.186/358.488 mm to 33.653/32.287 mm. Whole-case declared CAD section RMS changes from 64.420 mm to 23.505 mm. STEP volume error changes from 0.6022% to 0.7367%, a small deterioration that remains visible alongside the local improvement.

The exact post-inference STEP-cut results are recorded in `artifacts/v04/geometry/roundflare-comparison-iteration2.json`. No unsampled full-surface accuracy claim is made.

The first development probe stopped without CAD after bounded observations omitted already-catalogued sections. Those incomplete attempts are retained as `roundflare-baseline-native` and `roundflare-endpoint-iteration2-native`. The probe was corrected to explicitly request pending IDs until all returned observations were processed; complete reruns have `complete-native` in their names. This is a probe pagination fix, not a relaxed selection rule.

### Narrow observed chine and controls

The same untouched raster fixture loses 7 pixels of a connected narrow feature under the published uniform sampler. Updated extraction uses 132 points and retains the independently measured row centres to floating-point precision. A straight source stays at 129 points. A trace requiring more than 1025 points refuses instead of smoothing away detail.

Focused ingestion and semantic tests: 47 passed. Independent accelerated STEP comparator policy tests: 8 passed. The controls include missing calibration, blank/noisy pages, long erasures, sustained competing contours, mixed-contrast alternatives, uniform rulers, disconnected marks, and flat-bottom corners. The degraded-curve test's former index 3 cutoff was expressed as the identical original physical height, 3×5/128 m, because adaptive insertion changes indices. Its numerical error threshold and evaluated physical domain are unchanged.

## Terminal zero-width spurs

The published multichine terminal-spur discrepancy remains 43.264475 mm against the raw 1.1 mm fidelity gate. The source profile includes y=0 at z=0, 0.0216322, and 0.0432645 m. Mirroring retraces that zero-area interval; the existing terminal-cap construction omits the redundant spur from a solid's boundary while retaining the raw measured points. This is a distinction between a raw source trace and a material boundary. It is not permission to mark the raw audit successful.

No material-boundary replacement score or waiver is introduced here. The original images and raw audit are preserved. The validation stream independently reaudited the original STEP with the new contract: first, cached, and reopened results all remain false, and finalization is blocked. See `artifacts/v04/validation/real-native-failure-current-summary.json` and `docs/VALIDATION_CONTRACT_V1.md`.

## Evidence and limitations

`artifacts/v04/geometry` contains source inputs, both completed native runs for the known 47 case, three completed native runs for the old final 12 case, failed/incomplete attempts, frozen implementation manifests, evaluator-only references, complete numerical comparisons, plots, test logs, a visual-iteration ledger, and copied-run verification. All five completed copied candidate runs verify successfully. The ledger records fourteen actually viewed images, including source crops, error overlays, native views, and the unchanged terminal-spur failure. Active native work ran under `/tmp`; only terminal artifacts were copied and verified after copying.

The source-only driver is `benchmarks/source_fidelity_probe.py`; the post-inference comparator is `benchmarks/source_fidelity_compare.py`; the narrow-feature reproducer is `benchmarks/source_sampling_probe.py`. Their experiment names explicitly disclaim final-holdout and live-model claims. All outputs retain `engineering_approved=false`.

A pre-existing compatibility mismatch remains: `schema.py` admits `sample_count` 17..513, while ingestion accepts 65..1025. The common default 129 is supported. This work did not broaden either admission range; the mismatch should be reconciled deliberately in a later contract change.

The endpoint proposal is limited to a calibrated lower centreline contact in this section representation. It does not solve arbitrary body plans, infer missing scales, validate ship structure, or recover subpixel tangency from an underresolved drawing. Existing 513-common-knot and 20,000-face CAD complexity limits still apply; preserving more source features can correctly expose those limits. New independent evaluation is required after the integrated implementation freezes.
