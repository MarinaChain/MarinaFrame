# Vision LLM localisation (W14)

Status: development experiment, 2026-11-08. **Not suitable for automatic engineering setup or geometry.** All outputs keep `engineering_approved=false`.

## Result

There is a real coordinate-frame failure in the W12 setup contract. It is not a fixed model-wide 0–1000 convention, an axis swap, or proof of an undocumented provider resize. The model usually follows an explicit requested frame on simple marks. With source rulers on a resized image, it can instead answer in attachment pixels, even when asked for original sheet pixels. On a crop, the same instruction can make it use the ruler frame. Thus a correction inferred from coordinate magnitude is unsafe.

The setup fix requests normalized coordinates of the whole attachment, including margins. Python converts them with the recorded crop offset, 36 px margin and actual rounded width/height scales. Raw readings remain unchanged. Invalid normalized answers are rejected, not guessed or clamped. Ink, scale, publication and approval checks are unchanged.

This fix removes a large avoidable frame error. It does **not** make the model a precise localiser or establish line identity. The remaining errors, missing answers and schema failures are material.

## 1. Method and transport

All calls use `deepseek-v4.1-flash` through the Rust provider worker at the OpenCode Go endpoint. Keys are loaded with the authorized loader and are never printed. Python has no model HTTP client. The new typed `localisation` purpose has no task or approval authority.

Every actual request has a request receipt and image hash, dimensions, bytes and crop box. Per-request limits remain: bounded PNGs, at most 1,048,576 pixels and 1 MiB per image, bounded output and worker time, supervised retry policy. There is no aggregate call/token/spend cap. Setup stops after checks fail to improve. The W11 rerun also has a semantic no-progress stop: 180 seconds without a changed assignment or candidate generation; new label views alone do not count as progress.

The harness sends PNGs with `detail: original`. This describes the already-prepared attachment; it does not guarantee that an upstream model uses native pixels. W12 itself downsamples to about 700,000 content pixels and adds rulers. Its old contract asked the model to reverse that transform. W11 investigation views already have actual per-axis scales and convert view pixels back to source pixels; its point/corridor tools do consume model coordinates. The veto reviewer returns only station verdicts, not coordinates, so no review-coordinate conversion is needed.

Only DEVELOPMENT drawings are used. The exact 40 W12 cases were regenerated from the frozen manifest; **40/40 drawing hashes match**. No factory validation or sealed inputs were evaluated. Public source recovery and the matching Ship-D generator commit are recorded in `outputs/w14/METHOD_NOTES.md`. No authentic licensed drawing was added.

### Calibration design

Images contain six known marks: dots, crosses and short-line endpoints, plus a labelled fraction grid. Locations are spread over both axes. Two independent requests per size and mode ask for: pixels without dimensions, pixels with dimensions, normalized 0–1000, and normalized 0–1. Image dimensions are suppressed from the text listing only for the implicit-size control; true dimensions are still validated and receipted.

Native transmitted sizes: 512×512, 1024×768, 2048×480, and 640×1280. A 4096×240 attachment is rejected locally by the existing side limit, before any provider call. Separate 2048² and 4096² source images are explicitly reduced to 896² attachments. Their errors below are converted back to source pixels; they do not test native 4096-pixel model vision.

For each response, fit independent scale and offset on each axis and test xy versus yx order. This diagnostic fit uses known truth and is **in-sample**, not a deployable correction. Reported operational errors use only the requested frame and known image transform, without fitted truth correction.

## 2. Coordinate-frame results

Median Euclidean position error in source pixels; 12 marks per valid size/mode:

| Source size | Attachment | Implicit pixels | Explicit pixels | Normalized 1000 | Normalized 1 |
|---|---|---:|---:|---:|---:|
| 512×512 | native | 48.44 | 2.62 | 2.25 | 3.91 |
| 1024×768 | native | 8.22 | 6.09 | 6.66 | 11.03 |
| 2048×480 | native | 13.42 | 26.82 | 30.82 | 30.61 |
| 640×1280 | native | 145.67 | 8.75 | 9.22 | 10.49 |
| 2048×2048 | 896×896 | 7.88 | 8.97 | 50.24 | 49.24 |
| 4096×4096 | 896×896 | 279.41 | 15.39 | 82.44 | 75.06 |

Explicit-pixel median errors as fractions of the source long side are 0.51%, 0.59%, 1.31%, 0.68%, 0.44% and 0.38%, respectively. Large-source P90 errors are worse: 74.01 px at 2048² and 199.36 px at 4096². Small medians do not imply reliable endpoints.

All best fits use **xy**, not swapped axes. Explicit native 512/1024 pixel fit slopes are near one; normalized fit slopes follow the requested image dimensions, not a hidden universal source frame. The shallow 2048×480 image has a vertical bias (fit scale about 1.16 for explicit pixels, about 0.57 source px per normalized unit versus the expected 0.48). Model localisation/aspect-ratio bias remains after a valid frame contract. Median in-sample fitted RMS for explicit pixels is 2.65, 3.39, 4.03 and 4.69 px on the four valid native sizes. For the two downsampled squares it is 9.32 and 59.14 source px. These residuals cannot be subtracted from drawing errors.

### Direct W12 ruler/crop probe

A 2400×1800 synthetic source is prepared with the actual W12 resize, crop and margin code. Six marks are visible in the overview; three in the offset crop.

| View and requested frame | Median source error | Diagnostic fitted RMS |
|---|---:|---:|
| Overview, original source rulers | 938.58 px | 10.15 px |
| Overview, attachment pixels + known transform | 25.95 px | 13.78 px |
| Overview, normalized 1000 + known transform | 36.67 px | 9.30 px |
| Offset crop, original source rulers | 72.84 px | 16.52 px |
| Offset crop, attachment pixels + known transform | 1136.66 px | 12.67 px |
| Offset crop, normalized 1000 + known transform | 25.26 px | 5.16 px |

The overview source-ruler answer is consistent with attachment pixels: applying the **known**, not fitted, attachment transform to that raw answer reduces its median from 938.58 to 20.19 px. The crop's attachment-pixel request instead shows source-frame contamination. Normalized coordinates are the most consistent contract across this ruler/crop pair, although not the best mode on every simple synthetic image.

## 3. W12 setup before and after

Same 40 hash-matched drawings; same reading-order scoring on separate panels only. Overlaid station/panel correspondence is not asserted. Missing values are excluded from error distributions, but remain failures and stay in the planned denominator.

| Value | W12 returned | W12 median / P90 | W14 returned | W14 median / P90 |
|---|---:|---:|---:|---:|
| Panel coordinate components | 22 exact panel counts | 370.50 / 916.60 px | 14 exact counts; 504 components | 71.44 / 202.04 px |
| Centreline | 141 | 209.42 / 578.95 px | 90 | 40.46 / 95.26 px |
| Baseline | 84 | 471.59 / 1203.21 px | 46 | 171.39 / 293.88 px |
| Pixels per metre | 0 | not measurable | 0 | not measurable |

The panel metric is the absolute error of each of four box coordinate components, matching W12's code; it is not Euclidean distance per corner.

Coverage fell: 15/40 retained final proposals versus 32/40 in W12; layout correct 14/40 versus 22/40. Eleven primary attempts ended in driver exceptions (nine out-of-range normalized replies and two invalid-crop directory collisions). Other missing proposals include typed-schema failures. The primary after table is **not replaced by retries**. Separate retained retries check the repaired rejection/unique-directory handling. No complete spec passed; units and longitudinal positions are still not printed.

Paired axis values returned in both experiments show the same direction: centreline median 257.08→40.94 px (45 pairs), baseline 714.20→183.09 px (16 pairs). Pairing uses the same case and reading-order panel index, not independently proven station identity. Lower error on fewer returned values is not a general success-rate improvement.

## 4. Drawing localisation

Two named stations (3 and 7), two printed waterlines nearest 30% and 60% depth, on each of 40 drawings. Two modes: bounded whole-sheet image and station-panel crop. Each request asks for normalized crossing positions and physical half-breadths with supplied centreline, baseline and per-axis scale. These are **calibrated** measurements, not end-to-end scale discovery. Crop boxes come from the same caller metadata as the tracer, not hidden curve truth.

Truth is the original rendered station polyline, projected through the factory affine transform and, for overlays, its raster split/mirror transform. All 160 unique station-height truth intersections exist. The two modes give 320 scored rows. The deterministic strict tracer receives the same source, station regions and calibration; it abstains on all 80 station inputs. A separate deterministic draft chooses the best source-support candidate without using truth for ranking. Draft errors are not approved geometry.

### Separate panels

Position: median Euclidean source-pixel error (returned/planned). Breadth: median absolute metres. Draft: median absolute metres from the existing best-score deterministic draft. Each level has 28 station-height targets.

| Level | Sheet position | Crop position | Crop breadth | Deterministic draft breadth |
|---|---:|---:|---:|---:|
| L0 | 31.27 px (8/28) | 51.17 px (28/28) | 1.112 m (26/28) | 0.0214 m (28/28) |
| L1 | 226.38 px (6/28) | 47.23 px (24/28) | 1.122 m (24/28) | 0.0212 m (10/28) |
| L2 | 88.60 px (4/28) | 45.97 px (22/28) | 1.849 m (20/28) | 0.0250 m (10/28) |
| L3 | no answer (0/28) | 32.41 px (2/28) | 0.306 m (2/28) | 32.0785 m (4/28) |

Pooled separate panels: sheet position **96.32 px**, P90 313.15 (18/112); crop **49.53 px**, P90 112.08 (76/112). Crop breadth **1.194 m**, P90 5.551 (72/112). The low L3 median is based on two answers and is not evidence that degradation improves accuracy. Strict-tracer abstention is not zero error. The draft's extreme L3 errors demonstrate why unverified continuity/contrast choices must remain guesses.

### Overlaid layouts

At each L0–L3 level, model position and breadth coverage is **0/12** in both sheet and crop modes (0/48 per mode overall). This is failed station identity/localisation, not accurate abstention. Deterministic draft L0 returns 12/12 with 0.0274 m median error and 1.1645 m P90; L1–L3 return none. Strict tracing returns none at every level. No layout-wide success claim is supported.

### Independent grid scale

The original combined requests also asked for scale. That design leaked the supplied breadth calibration into the scale question. **Those scale answers are excluded.** Forty separate crop requests contain no calibration answer. Factory units are not printed, so the result is pixels per printed drawing unit, not an independently read metre unit.

| Layout | Level | Returned / planned | Median relative error | P90 |
|---|---|---:|---:|---:|
| Separate | L0 | 2/7 | 7.58% | 10.23% |
| Separate | L1 | 3/7 | 23.12% | 29.68% |
| Separate | L2 | 1/7 | 3.74% | 3.74% |
| Separate | L3 | 0/7 | not measurable | not measurable |
| Overlay | each L0–L3 | 0/3 | not measurable | not measurable |

Crop/zoom is the best tested **drawing** setup by coverage and pooled position error. It still misses most overlay targets and has metre-scale breadth errors. No adaptive truth-selected zoom, fitted calibration correction, or semantic line assignment was applied.

## 5. W11 live-arm rerun

The tools use model pixels for view-local point and corridor selection, then snap to real ink. Their mapping already accounts for crop offsets and actual per-axis resize scales. W14 does not apply the setup normalized-frame conversion to these tools: that would change their documented contract.

Twenty frozen development cases are listed in `outputs/w14/w11_cases.json` (five hulls × four levels). Executable bytes and Python worker source are frozen under `work/w14/` before the run. Every invocation passes the worktree worker source explicitly. Native no-progress stops and the additional assignment-level supervisor are retained as outcomes, not labelled successful CAD builds. All 20 cases were attempted: 18 ended at native `no_progress`, one at the 180-second semantic supervisor, and one original attempt was stopped after repeated label/enumeration cycles. There are no completed review-ready builds. Retained state has 34 selected lines and 28 open guesses out of 180 planned station slots; these are not independently scored correct identities. The model made one corridor and two point-trace decisions, plus 87 label reads and three view requests. Two interrupted provider calls remain `transmission_or_completion_unknown`; they were not retried or assigned zero usage. This rerun does not demonstrate a W11 accuracy improvement.

## 6. Exact usage and cost

Final receipt totals are generated by `python -m benchmarks.localisation.summarize`. They include failed schema replies, unsuccessful preliminary calibration, ruler probes, setup rejection retries and interrupted W11 requests. Preflight image rejections have no provider receipt and are not billed calls. Reported Go charge is distinct from the provider's receipted `usage.list_cost`; no remembered price is used. Missing usage on failed HTTP requests remains explicit, not an invented token estimate.

Final unique receipt totals (all requests have ended):

| Experiment | Calls | Prompt tokens | Completion tokens | Provider list USD |
|---|---:|---:|---:|---:|
| Calibration, preliminary failures and diagnostics | 74 | 50,665 | 9,536 | 0.01227296 |
| W12 ruler/crop probe | 6 | 4,995 | 841 | 0.00125091 |
| Primary 40-case setup | 328 | 468,572 | 147,531 | 0.15526428 |
| Separate setup rejection retries | 13 | 17,184 | 7,412 | 0.00620337 |
| Drawing point/breadth experiment | 160 | 147,559 | 38,169 | 0.04493884 |
| Independent scale control | 40 | 21,923 | 2,903 | 0.00502731 |
| W11 20-case live arm | 253 | 2,084,961 | 17,053 | 0.31627395 |
| **Total** | **874** | **2,795,859** | **223,445** | **0.54123162** |

States: 731 completed, 141 failed, two transmission/completion unknown; 1,569 image attachments. Observed receipted charge is USD 0.00 (Go allowance), not a list-cost estimate. Eighteen receipts have no usage: 16 preliminary HTTP failures and the two interrupted live calls. Tokens and list cost above are the **exact returned usage**, a lower bound for total upstream use where these receipts omit usage. No estimate is invented for the unknown calls. There are 17 local preflight image-limit rejections, separate from the 874 provider requests.

Drawing localisation used 160 calls, 147,559 prompt and 38,169 completion tokens, list USD 0.04493884. This is USD 0.00028087 per request and USD 0.00007022 per planned point/breadth answer (640 such answer slots; each request also contained the excluded scale question). Independent scale used 40 calls, 21,923 prompt and 2,903 completion tokens, list USD 0.00502731: USD 0.00012568 per planned scale answer. Cost per returned answer is higher; missing replies are not free successes.

## 7. Verification and limits

- Coordinate tests cover crop offsets, 36 px margins, actual rounded per-axis dimensions, boxes, station labels, scale endpoints, missing values and invalid normalized ranges.
- Rust tests keep localisation typed and bounded, with no approval field. Provider failure bodies are bounded and key-echo filtered.
- All source truth and candidate selection boundaries remain unchanged. No tracing tolerance or approval gate was widened.
- The first quick tier exposed stale Rust test initializers from the inherited W12 receipt fields; test fixtures were repaired. The final full quick tier passed: 652 Python tests, 10 CAD deselected, Rust tests, formatting, Clippy and secret scan. Targeted coordinate/summary tests also passed.
- `refresh-codesight` generated the local index; its managed bootstrap failed with `ModuleNotFoundError: render_bootstrap`. No external checkout was modified. Generated index files are not part of this deliverable.
- Small synthetic mark controls are not representative of crowded drawings. In-sample frame fits are diagnostics only. Setup correspondence is reading-order based, metre scale is supplied for breadth questions, and no authentic localisation accuracy was measured.

**Conclusion:** Fix the harness frame contract, but retain human setup and semantic review. Current DeepSeek vision is useful for proposals and investigation, not precision drawing measurement. Missing answers, wrong grid/curve identity, aspect-ratio bias and schema errors remain independent failure modes.
