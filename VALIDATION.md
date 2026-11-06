# Current continuation versus historical validation

The 0.2 implementation and observed test results are reported in
[docs/HARDENING_RESULTS.md](docs/HARDENING_RESULTS.md). The material below remains
the original research record and is not silently re-scored or relabelled. New
semantic abstentions, dependency changes and geometry stress-test results have
separate evidence. No successful real archival reconstruction or expert approval
has been established.

> Source-only repository note: this document records the original research bundle. Large data, model weights, exports and frozen evidence referenced below are not included here. CI does not reproduce historical benchmark scores.

# Vessel Reconstruction Foundation — validation report

## Outcome and proven scope

**All original acceptance gates were met on the complete fresh confirmation evaluation.** The system produced 39 passing CAD reconstructions from 42 numerical drawing cases, with 3 explicit blocks. It also correctly blocked all four invalid-input cases and one unannotated historical sheet. These information-related blocks do not count as reconstructed vessels.

The proof concerns **calibrated, isolated hull-section drawings with disclosed operator assistance**. It covers pixels to measured curves, real CAD construction, STEP export/reload, evidence preservation, review status, and an offline workbench. It does not establish arbitrary full-ship plan interpretation, fabrication readiness or equivalence to Forge Shipyards' complete product.

No project-specific neural model was trained. Curve extraction is deterministic image analysis; CAD uses CadQuery/OpenCascade. The experimental table reader uses existing pretrained Tesseract LSTM weights. No LLM service, Blender automation or GPU is required for the proven curve workflow.

## Fresh confirmation results

Errors below are calculated **only over completed, passing models**, with the pass/attempt denominator shown. Every failed case remains in the case log. Clean and degraded views share 20 hulls, so they are 40 images of 20 geometries, not 40 independent ships. The two external views share one DTMB reference hull crop.

| Test group | Passing / attempted | Mean envelope-volume error | Worst envelope-volume error | Mean extracted-curve RMS / beam | Worst extracted-curve RMS / beam |
|---|---:|---:|---:|---:|---:|
| Clean drafting drawings | 20/20 | 1.064% | 1.369% | 0.275% | 0.661% |
| Moderately degraded drawings | 17/20 | 1.073% | 1.375% | 0.294% | 0.714% |
| External DTMB CAD-derived drawings | 2/2 | 1.056% | 1.057% | 0.339% | 0.339% |

Across all 39 completed numeric models, mean volume error was **1.067%**, worst **1.375%**. Mean extracted-curve RMS/full beam was **0.287%**, worst **0.714%**. These figures are conditional on successful reconstruction; the three blocked inputs are not discarded from the reported pass rate.

Each passing case recovered every required section, produced one valid positive-volume CAD solid and completed STEP export/reload. Exported STEP volume and length/beam/depth had to agree within 1e-6 relative tolerance. JSON meshes and reporting use metres; STEP/STL use millimetres.

The full 47-case evaluation took **295.39 seconds** with two inference workers. Procedural clean-case median wall time was **13.96 seconds** including process startup and exports. These are measurements on this execution environment, not throughput promises for other machines.

## Gates fixed before scoring

- Clean: at least 90% of cases must have envelope-volume error ≤ 3% and extracted-section RMS/full beam ≤ 1%, plus complete valid CAD.
- Moderate degradation: at least 80% must have volume error ≤ 5% and RMS/full beam ≤ 2%, plus complete valid CAD.
- External geometry: at least one passing CAD case under 5% volume and 2% RMS/full-beam limits.
- Missing-information cases: 100% must block without published geometry.

The original gates were retained after implementation defects were found. Confirmation uses 20 fresh procedural seeds frozen before inference, with no overlap with the original 20. The two procedural families and rendering distributions remain the same. DTMB geometry is reused as an external regression repeat and is not claimed as a new unseen vessel in confirmation.

## Remaining failed confirmation cases

- `holdout_multichine-241009-degraded`: A curve segment is missing for 52 pixels (limit 4); long gaps are not filled. No CAD was published.
- `holdout_roundflare-271043-degraded`: A curve segment is missing for 11 pixels (limit 7); long gaps are not filled. No CAD was published.
- `holdout_roundflare-271063-degraded`: A curve segment is missing for 28 pixels (limit 6); long gaps are not filled. No CAD was published.

All three are degraded inputs. Conservative curve-support checks rejected an interrupted trace at one required station. The system did not fill those segments by reading evaluation labels or guessing a hull family. These cases constrain the reliability claim to 17/20 moderately degraded inputs in this test.

## The original evaluation failed, and is retained

The first frozen implementation passed **0/20 clean**, **10/20 degraded** and **2/2 external** numeric cases: **12/42 numerical reconstructions**. Four degraded cases blocked during CAD and six timed out; all clean cases blocked. All five information-related blocks were correct. The original clean/degraded gates failed.

Two general defects were repaired using dedicated fixtures. First, inconsistent threshold quantization and light-grid selection caused false competing-contour detections. Second, whole closed-wire lofting guessed correspondence between profiles with different bottom-edge counts. The final method separates ink contrast tiers and constructs explicitly corresponding ruled CAD panels. It adds no target geometry or minimum-width epsilon. Original code, failed runs and the diagnostic replay remain in `artifacts/algorithm_history/` and `data/generated/holdout_evaluation/`.

The original evaluation's incomplete append checkpoint was recovered from its complete in-memory final report without rerunning or rescoring cases. The original checkpoint and recovery receipt are preserved. Confirmation publishes atomic, read-back-verified checkpoints; its 47 unique records agree exactly across report and checkpoint.

## Comparison with a simple pixel baseline

The baseline selects the rightmost pixel darker than 120 at each sampled row, using exactly the same operator calibration. It estimates sections and volume; it does not produce CAD or establish safe abstention. For a paired comparison, the table uses the same successful main-method cases for both methods.

| Group | Paired cases | Main extracted RMS / beam | Baseline RMS / beam | Main CAD volume error | Baseline estimated-volume error |
|---|---:|---:|---:|---:|---:|
| clean | 20 | 0.275% | 0.267% | 1.064% | 0.409% |
| degraded | 17 | 0.294% | 2.604% | 1.073% | 0.705% |
| external | 2 | 0.339% | 2.351% | 1.056% | 0.904% |

The baseline is competitive on clean images and has lower mean volume error in these paired groups. The continuity-based parser has substantially smaller local curve errors under noise. Local errors can cancel in a volume estimate; neither a small volume error nor a plausible-looking mesh proves that every hull region is correct.

## Actual exported CAD boundary diagnostic

A supplemental diagnostic independently cuts the **actual exported STEP** at nine interior drawing stations per selected case, with 129 elevations per station. The four cases were selected before this audit: first clean/degraded multichine and clean/degraded external DTMB. It does not rerun inference or alter the frozen gates.

| Actual STEP case | Compared ordinates | Missing | Ambiguous | Actual STEP RMS / full beam |
|---|---:|---:|---:|---:|
| `external-dtmb5415-clean` | 1161 | 0 | 0 | 0.372% |
| `external-dtmb5415-degraded` | 1161 | 0 | 0 | 0.374% |
| `holdout_multichine-241001-drafting` | 1161 | 0 | 0 | 0.206% |
| `holdout_multichine-241001-degraded` | 1161 | 0 | 0 | 0.206% |

The original diagnostic had strict endpoint comparisons that missed a few ordinates at floating-point gaps between shared edge endpoints. Its unchanged inconclusive results and exact source are retained. The corrected comparator uses a recorded fixed endpoint tolerance and records tolerance-assisted intersections; its analytic fixtures are retained. This check establishes sampled CAD-boundary agreement at those stations, not accuracy between every station, at end caps, or over all ships.


## Original historical drawings: a harder, unsuccessful task

The original Balclutha frame 108 scan was actually tested. The v1 curve heuristic accepted 129 measured/interpolated samples with 100% row coverage and quality score about 0.897. AI visual review found switches onto internal deck brackets and rejected the trace. No CAD was exported. There was no human naval-architect signoff. Continuous ink and a high heuristic quality score did not establish one physical surface's identity.

Two real table-reading attempts used 114 unchanged cells from the original sheet 7 drawing, with source-supported nonuniform station positions from sheet 3. The first pretrained OCR model accepted 43 cells and blocked 71. The separately pinned larger model accepted 57 and blocked 57 under the same confidence/agreement rules. Neither completed the required stations, so both full pipelines blocked with zero CAD exports. Separate AI visual checks found no disagreement in the accepted literals; that is not validation of mapping, survey accuracy or geometry.

The table describes an inner hull surface, and the attempted 4–24 ft height range would be a cropped envelope with assumed closures. No half-breadth answers were typed into the source specification, no confidence threshold was relaxed and no uncertain numeral was silently repaired. The unannotated historical-sheet block in the numerical suite is only a missing-input check, not a successful archival reconstruction.

## Test and application verification

The full core/application/harness suite passed **95 tests** in **27.89 seconds**, recorded in `artifacts/validation/pytest.xml` and `pytest.txt`. The subsequently added STEP-comparator suite passed **6 additional tests**, recorded separately in `step-audit-pytest.xml`: **101 passing automated tests across the two suites**. They cover independent analytic volumes, dimensional scaling, valid CAD and STEP round trips, independently loaded watertight STL, missing-frame and dimensional-conflict blocks, source changes versus unrelated reference-label changes, extreme/nonfinite numeric inputs, OCR conversion and uncertainty, dataset/scorer integrity, review records, uploaded-source preservation, server confinement, and distinction between floating-point endpoint gaps and actual missing CAD boundaries.

Browser checks exercised actual 21-section upload/reconstruction and interactive calibration to a new three-section CAD result. Packaged assets were tested from a separately installed wheel outside the source repository. Offline snapshots, section/source overlays, a software-rendering fallback and 390 px layout were exercised with no JavaScript errors. Final snapshot-specific evidence is retained under `artifacts/validation/workbench/`; browser screenshots are not part of the deliverable.

The supplied portable DTMB workbench contains the actual final 41-section model, original drawing, evidence and CAD downloads. It can be inspected offline; new reconstruction requires the local server. The server is a localhost development application, not a deployed multi-user service.

## Data provenance and assistance

- External CAD: [mathLab WaveBEMapp DTMB5415](https://github.com/mathLab/WaveBEMapp-DTMB-5415), pinned commit `afad0f04a2ce5ee03f37dcefbe697a5281bc0168`, retained MIT notice. Original x=[-2.5,2.9]m is cropped to one connected half-section representation, mirrored and capped. Newly rendered drawings are used for inference; the source IGES is never an inference input.
- Real archival scans: [Library of Congress Balclutha HAER survey](https://www.loc.gov/resource/hhh.ca1493.sheet/), sheets 3, 7 and 48, with documented official NPS public-domain notices and exact original-file hashes.
- Training/reference pairs: generated images and separate private labels. Procedural reference volume uses 801 stations × 1,025 elevations. External reference uses 241 dense stations. These numerical targets are decoded after inference completes.
- Operator assistance: station identification and x position, single-contour panel/cell regions, scale and datum for curve inputs, elevation ranges, symmetry and closure. These are supplied facts, not automatically recovered capabilities.

The source/spec-only subprocess boundary is auditable data separation, not an operating-system sandbox. File hashes detect changes relative to retained manifests; they are not externally signed certification. New runs preserve exact inference Python files, environment versions and original source bytes.

## What has not been established

The work does not prove automatic interpretation of arbitrary overlapping plans, dimension conventions, revisions, old handwriting, stains, rotation, perspective distortion or all faint competing strokes. Synthetic degradation is the documented blur/noise/speckle/JPEG/gradient process. Forty procedural images do not represent the distribution of real shipyards.

The model is a hull envelope. It does not infer plating thickness, steel volume, material, structural frames, decks, piping, machinery or current as-built condition. Envelope volume is not automatically displacement. Top, lower and terminal closures and between-station interpolation are modeling assumptions. Successful outputs remain review-required and no automated or local review entry produces engineering approval.

The deliverable is a usable, measured foundation for a broader system. The historical failures identify the next technical bottleneck: semantic line identity and reliable extraction of measurement evidence.

## Reproduce and inspect

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install -e '.[test,documents]'
python -m pytest -q
python -m vessel_reconstruction serve --artifacts artifacts --port 8765
python -m benchmarks.evaluate data/generated/confirmation_v2 --out artifacts/new-evaluation --jobs 2 --timeout 90
```

Full commands, input schema, source rights and modeling choices are in `README.md`, `CONTRACT.md`, `DATA_SOURCES.md` and `ARCHITECTURE.md`. Each run requires a fresh output directory so prior evidence is retained. Both initial and final suites, all acquired source data, licenses, trained OCR weights, scripts, tests, frozen code, failure records and CAD exports are in the source bundle.

Confirmation input manifest SHA-256: `67230410b389d46fbd3d02be94db7dd1122372d4ff89bb716b8bf5d0ca79381b`.

Confirmation numerical report SHA-256: `8bfc00f0e9f8eaa3017a8d5698fa7b369dc2a3686d797ed7068824fc52700e8b`.

Original numerical report SHA-256: `97ec585438c924537dbbae0dc82820b913454ba9a72da33a51a4ddb28d6d01af`.

## Complete confirmation case inventory

RMS is displayed here only for complete passing reconstructions. Raw reports retain partial extraction diagnostics for failed cases. Information blocks have no numeric reconstruction score.

| Case | Outcome | Envelope-volume error | Extracted-curve RMS / beam |
|---|---|---:|---:|
| `holdout_multichine-241001-drafting` | CAD pass | 1.080% | 0.201% |
| `holdout_multichine-241001-degraded` | CAD pass | 1.080% | 0.202% |
| `holdout_multichine-241009-drafting` | CAD pass | 1.043% | 0.212% |
| `holdout_multichine-241009-degraded` | Reconstruction failed / blocked | — | — |
| `holdout_multichine-241013-drafting` | CAD pass | 1.092% | 0.204% |
| `holdout_multichine-241013-degraded` | CAD pass | 1.091% | 0.204% |
| `holdout_multichine-241027-drafting` | CAD pass | 1.280% | 0.231% |
| `holdout_multichine-241027-degraded` | CAD pass | 1.278% | 0.231% |
| `holdout_multichine-241031-drafting` | CAD pass | 1.101% | 0.221% |
| `holdout_multichine-241031-degraded` | CAD pass | 1.100% | 0.221% |
| `holdout_multichine-241037-drafting` | CAD pass | 1.137% | 0.220% |
| `holdout_multichine-241037-degraded` | CAD pass | 1.135% | 0.220% |
| `holdout_multichine-241043-drafting` | CAD pass | 1.226% | 0.250% |
| `holdout_multichine-241043-degraded` | CAD pass | 1.232% | 0.251% |
| `holdout_multichine-241049-drafting` | CAD pass | 1.000% | 0.213% |
| `holdout_multichine-241049-degraded` | CAD pass | 0.997% | 0.213% |
| `holdout_multichine-241061-drafting` | CAD pass | 1.098% | 0.208% |
| `holdout_multichine-241061-degraded` | CAD pass | 1.095% | 0.208% |
| `holdout_multichine-241067-drafting` | CAD pass | 1.369% | 0.276% |
| `holdout_multichine-241067-degraded` | CAD pass | 1.375% | 0.277% |
| `holdout_roundflare-271003-drafting` | CAD pass | 1.311% | 0.365% |
| `holdout_roundflare-271003-degraded` | CAD pass | 1.312% | 0.367% |
| `holdout_roundflare-271009-drafting` | CAD pass | 1.365% | 0.381% |
| `holdout_roundflare-271009-degraded` | CAD pass | 1.355% | 0.394% |
| `holdout_roundflare-271013-drafting` | CAD pass | 0.917% | 0.235% |
| `holdout_roundflare-271013-degraded` | CAD pass | 0.915% | 0.235% |
| `holdout_roundflare-271027-drafting` | CAD pass | 0.689% | 0.314% |
| `holdout_roundflare-271027-degraded` | CAD pass | 0.645% | 0.378% |
| `holdout_roundflare-271043-drafting` | CAD pass | 0.944% | 0.250% |
| `holdout_roundflare-271043-degraded` | Reconstruction failed / blocked | — | — |
| `holdout_roundflare-271049-drafting` | CAD pass | 0.945% | 0.260% |
| `holdout_roundflare-271049-degraded` | CAD pass | 0.948% | 0.261% |
| `holdout_roundflare-271063-drafting` | CAD pass | 0.897% | 0.238% |
| `holdout_roundflare-271063-degraded` | Reconstruction failed / blocked | — | — |
| `holdout_roundflare-271067-drafting` | CAD pass | 0.943% | 0.260% |
| `holdout_roundflare-271067-degraded` | CAD pass | 0.917% | 0.294% |
| `holdout_roundflare-271079-drafting` | CAD pass | 1.146% | 0.307% |
| `holdout_roundflare-271079-degraded` | CAD pass | 1.128% | 0.323% |
| `holdout_roundflare-271097-drafting` | CAD pass | 0.690% | 0.661% |
| `holdout_roundflare-271097-degraded` | CAD pass | 0.639% | 0.714% |
| `negative-missing_scale` | Correct information block | — | — |
| `negative-missing_curve` | Correct information block | — | — |
| `negative-negative_scale` | Correct information block | — | — |
| `negative-insufficient_sections` | Correct information block | — | — |
| `external-dtmb5415-clean` | CAD pass | 1.057% | 0.339% |
| `external-dtmb5415-degraded` | CAD pass | 1.055% | 0.339% |
| `historical-balclutha-unannotated` | Correct information block | — | — |
