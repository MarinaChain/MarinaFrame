> Source-only repository note: this document records the original research bundle. Large data, model weights, exports and frozen evidence referenced below are not included here. CI does not reproduce historical benchmark scores.

# Data sources, rights and evaluation splits

All external inputs were obtained on 2026-11-06. Original bytes, source URLs, license notices and SHA-256 inventories are retained. A generated drawing of an external CAD surface is distinguished from an original archival drawing throughout the reports.

## Public reference geometry: DTMB 5415

- Source: [mathLab/WaveBEMapp-DTMB-5415](https://github.com/mathLab/WaveBEMapp-DTMB-5415).
- Pinned commit: `afad0f04a2ce5ee03f37dcefbe697a5281bc0168`.
- Retained files: original IGES, original NumPy data, original README and views, repository LICENSE, and source manifest under `data/external/dtmb5415/`.
- License: the repository's MIT license, with Copyright (c) 2017 Marco Tezzele retained. No separate per-file exception was observed; the manifest records that scope.
- `goteborg_original.iges`: 133,002 bytes; SHA-256 `a3d1e9d82ff5aec16525f39e1708af4bd71960c56e9584d494554633e60dc8ad`.

The source is a three-face half-hull surface, not a closed solid. OpenCascade reads its declared metres into millimetres. The reference builder converts coordinates back to metres, slices the surface, mirrors its half-sections and explicitly closes a cropped region.

The supported region is **original x = -2.5 to +2.9 m**, shifted to reconstruction x = 0 to 5.4 m. The bow/bulb region with disconnected section contours, actual vessel tips and appendages is excluded. This crop is an explicit capability restriction, not a recovered complete vessel.

Forty-one stations become newly rasterized drawing panels. Independent volume reference uses 241 densely spaced stations, 257 elevations per station, and 4,097 samples per source intersection curve. Reference volume for the declared mirrored/capped crop is approximately 1.3241133171 m³. These reference sections and volume stay in generation/scoring code; inference gets image pixels and disclosed calibration only.

The initial test treats this externally authored geometry separately from procedural development geometry. Confirmation reuses the same DTMB shape, with a newly predeclared noise seed in the degraded image. It is a regression repeat, not a second independent ship design.

## Original archival drawings: Balclutha, HAER CA-54

The source set is the [Library of Congress Balclutha survey](https://www.loc.gov/resource/hhh.ca1493.sheet/), with original-file mirrors on Wikimedia Commons. File descriptions expressly identify official National Park Service works and US public-domain status; rights were not inferred merely because a file appeared in a government collection.

| Original | Purpose in this project | Exact original SHA-256 |
|---|---|---|
| Sheet 48: Section at Frame 108, Mark T. Bittle, 1988 | Detailed annotated section stress test | `4e6344f077c9337cf3a1a1e735879e719449852ca6cf1200cd80d51692243fa6` |
| Sheet 7: Body Plan / Table of Hull Measurements, Robbyn L. Jackson / NPS, 1990 | Original overlapping body plan and 114 measurement-cell OCR attempt | `32f09c60a39d5a7f91148eb26148ebb58feea3d0a510e5a9a9da7767c60326a8` |
| Sheet 3: Body Plan / Sheer Plan / Half-Breadth Plan | Dimensioned station-position evidence | `02a14d8d6ec4f6a57d123f02a0ccf2ed5b87ed98dedc5d014b795b20af666163` |

Catalog pages: [sheet 48](https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=48), [sheet 7](https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=7), [sheet 3](https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=3). Exact direct-download URLs and source descriptions are in the adjacent manifests.

The frame 108 input is a documented quarter-size derivative of the original TIFF, with two bottom border pixels removed before resizing. No source contour was painted, masked, traced or recreated. Panel and ruler calibration are manually supplied and visible in an evidence preview. The v1 parser accepted a trace, but source inspection rejected its switches onto internal brackets. That failure is retained and no CAD was exported from it.

The table attempts use stations 1–19 and elevations 4, 8, 12, 16, 20 and 24 feet: **114 cells**. Their text describes the **inner hull surface**, with measurements in feet, inches and eighths of an inch. The numerical half-breadths are recognized from image cells, not transcribed into the input as answers.

Station positions are manually read from sheet 3's printed dimension chain. Intervals are not uniform: 0–4 use 6 ft 1.5 in; 4–8 use 12 ft 3 in; 8–12 use 24 ft 6 in; 12–16 use 12 ft 3 in; 16–19 use 6 ft 1.5 in; and 19–20 uses 6 ft 0.5 in. Their sum is 244 ft 11 in. Source crops and the complete calibration record are retained. These station values are disclosed operator assistance.

The original pretrained OCR model accepted 43/114 cells and blocked 71. The separately tested larger official model accepted 57/114 and blocked 57 under the same threshold and agreement rules. Neither attempt completed every required station, so both full pipelines remained blocked with no CAD. Recognition counts are not accuracy percentages. Separate AI visual inspection found no disagreement in the accepted 43 and 57 literals; it did not establish station mapping, geometry, physical survey accuracy or engineering approval.

The unannotated sheet in the frozen benchmark is only a missing-information abstention check. Its correct blocking does not establish semantic understanding of historical drawings. The calibrated frame and table experiments are reported separately so this distinction is visible.

## Pretrained OCR weights

No weights were trained or fine-tuned for this project.

| Configuration | Origin and provenance | English model SHA-256 |
|---|---|---|
| v1 fast | Exact installed `tessdata_fast` model, Debian package version `1:4.1.0-2`; copied unchanged with license and package copyright notice | `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |
| v2 best | [Official tessdata_best](https://github.com/tesseract-ocr/tessdata_best), pinned commit `e12c65a915945e4c28e237a9b52bc4a8f39a0cec` | `8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba` |

Both retain Apache-2.0 notices under `data/public_scan/ocr_models/`. Language-model bytes, TSV configuration, environment details and acquisition metadata are included. Two OCR configurations using the same language weights are correlated passes, not independent evidence sources.

## Generated paired data

`benchmarks/generate.py` creates image/specification pairs and separately stored numerical reference labels. Development uses a Wigley-style procedural family with seeds 17, 23 and 41. The initial heldout suite uses two different families: multichine and round/flare. Each of its 20 hulls has a drafting and degraded drawing, making 40 image cases rather than 40 independent geometries.

The final confirmation contract uses 20 new procedural seeds, the same two heldout families and unchanged error thresholds. It was frozen before confirmation inference. It tests generalization to new parameters within this generator; it does not represent an independent sample of real shipyard drawings.

Each procedural drawing has 25 station panels and 129 original contour samples per panel. Ground-truth volume is computed independently on an 801-station by 1,025-elevation grid. Input images, specifications, private labels, manifests, source hashes, frozen implementation trees and all case outcomes are retained.

Moderate degradation uses Gaussian image noise with standard deviation 4.5 intensity levels, sparse speckles at probability 0.0006, Gaussian blur radius 0.42 pixels, JPEG quality 78 and a brightness gradient with amplitude 9. There is no rotation, arbitrary stain model, perspective distortion or missing-page simulation. Exact rendering code is frozen with the evaluation.

The four invalid-input cases omit scale, supply a negative scale, erase a required section, or provide too few sections. A separate raw historical case omits section annotations. These check blocking behavior and do not count as numeric reconstruction successes.

## Preservation of unsuccessful attempts

The early development materializations with truncated image writes are retained. The harness detected their hash inconsistency; images are now written atomically. The first full numerical evaluation remains intact with its failed gates and code snapshot. A missing append-checkpoint anomaly was recovered from the complete in-memory final report without rerunning or rescoring cases; the original checkpoint and recovery receipt remain available. Later evaluation checkpoints use atomic writes and read-back verification.

The corrected implementation is scored against the fresh frozen confirmation suite. Original failed scan and OCR attempts remain visible. No test threshold was relaxed and no required measurement was replaced by a hidden answer.

## Where to inspect

- `data/external/dtmb5415/source_manifest.json`: original external CAD, ancillary files and license.
- `data/external/balclutha/`: exact body-plan and station-reference originals, previews and manifests.
- `data/public_scan/README.md`: original scan/OCR experiment index and replay commands.
- `data/generated/holdout/` and `data/generated/confirmation_v2/`: frozen image/spec inputs and separate labels.
- `data/generated/holdout_evaluation/` and `data/generated/confirmation_v2_evaluation/`: complete scored outcomes and exact code snapshots.
- `artifacts/real-scan-frame108-v1/`, `artifacts/real-table-ocr-v1/`, `artifacts/real-table-ocr-best-v2/`: retained real-source observations and reviews.
