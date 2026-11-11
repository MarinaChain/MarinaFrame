# LLM sheet setup and veto review (W12)

Status: development implementation and evaluation, 2026-11-08. **Not ready to make live setup the default.** Every result keeps `engineering_approved=false`. No validation gate or tracing logic was widened.

## Design and authority

The existing Rust provider worker sends DeepSeek requests. Python has no HTTP client. `vision-request` accepts only `sheet_setup` or `build_review`; each purpose has a fixed prompt, typed reply, image hashes and supervised per-request limits. Model text is data, never executable code.

### Sheet setup

`python -m vessel_reconstruction.llm_setup run --source SHEET --out NEW_DIR --binary target/release/marinaframe --provider-transfer-basis TEXT`:

1. Prepare one palette PNG overview with red margin rulers in original sheet coordinates. Record source SHA-256, crop box, image SHA-256, bytes and dimensions.
2. Rust sends the overview and asks for layout, panels, station labels and printed longitudinal positions, units, symmetry and datum. Each value needs visible evidence or an explicit missing reason.
3. Prepare each proposed panel crop, with the same source-coordinate rulers. Ask for centreline, baseline and scale marks.
4. Python checks the proposal. Failed check names go back to the model. Stop after a check does not reduce the number of blocking failures. This is a no-progress rule, not an aggregate call cap.
5. Save `proposal.json`, `checks.json`, `readings.json`, all request/receipt directories, and `overlay.png`.

| Check | Rule |
|---|---|
| Panel | Inside the source; at least 0.2% dark pixels |
| Centreline and baseline | Ink within 2 px along at least 55% of the declared panel extent |
| Scale | At least two distinct physical marks; every estimate within 5% of their mean |
| Labelled scale lines | On ink; the numeric token must match the proposed number |
| Stations | Refer to a proposed panel; evidence contains label; numeric labels and positions strictly increase |
| Missing | Never filled from generator metadata, another sheet or hull priors |

`model_proposed` and `checked` are recorded per value. A pixel consistency check does **not** independently prove the model read a label or selected the right semantic line. Unit/symmetry/datum evidence stays model-proposed. The report states this limitation.

`prepare` and `check` expose these steps separately. `spec` recomputes checks against the source and fills an explicit human template only when all checks pass. The template must supply source rights, closure and elevation extents. Section IDs must match printed station labels. The ordinary spec validator still runs. A companion `setup_provenance.json` records the checked setup and template fields. No automatic spec was published from the evaluation sheets: their longitudinal station positions are not printed in the factory raster, and other required values are missing or rejected.

### Veto review

`run --model-review true --provider-transfer-basis TEXT` opts a task into review. After the ordinary finalization predicate passes, Python independently reimports the exported STEP and cuts each station. Each review image has the source crop on the left and the same crop with a magenta STEP cut on the right. Centreline and top closure edges are omitted.

Rust accepts only `follows`, `does_not_follow` or `cannot_tell` plus a station and reason. Only a completed, image-bound `does_not_follow` adds a blocking `model_review_veto`. The narrow controller hook keeps the task out of human review. A veto is retained for the exact STEP hash. Another STEP's veto does not affect it. No veto, an unreadable image or an incomplete review changes nothing. The reviewer cannot set a pass, review state or approval.

Per request: at most six images, one setup image, 1 MiB per image, 1,048,576 pixels, 2 MiB request, 4096 setup output tokens or 1024 review output tokens. Review batches contain three stations. HTTP 429/502/503/504 can retry up to three attempts, with at most 30 seconds backoff. Unknown/not-sent outcomes stop; two failed review batches stop for no progress. No aggregate call/token/spend cap.

## WIP defects found

- The WIP compiled. `make test-quick` first failed Rust formatting in `vision_request_cli.rs`.
- Rust created `images/` before launching Python, but Python used `exist_ok=False`. Thus every requested finalization review stopped before a model request. The renderer now accepts an empty directory and rejects existing evidence before CAD work.
- `findings` did not independently reject a failed receipt that contained a verdict. It now requires a completed build-review receipt.
- The reading record now carries crop geometry as well as image hash/size receipts.
- This worktree has no `.venv`; Make needs an explicit `PY`. Changing Python files during a running task correctly raises `worker_implementation_changed`; tests were rerun on stable source rather than weakening this guard.

## Development setup evaluation

The selective generator rebuilt 40 DEVELOPMENT drawings (10 hulls, four degradation levels) plus `sysser45-L1`. All 41 image hashes match the frozen manifests. Truth is opened only after model reading. The sample includes separate panels and overlaid plans. It does not touch the sealed test.

Final results are in `outputs/llm_setup_review/summary.json` and `case_results.json`. All 40 attempts completed the driver without a Python exception; 8 have no final usable overview. Layout was correct in 22/40. Printed station-label sequences 1..9 were exact in 22/40. All 245 returned longitudinal positions were marked missing; the factory does not print those positions. Units were missing in all 32 retained final proposals. Symmetry and baseline datum were proposed in 32/32, but this does not establish independent semantic truth.

| Value (separate-panel sheets with retained proposal) | Returned / 198 panels | Median absolute error | P90 error | Passed local check |
|---|---:|---:|---:|---:|
| Panel-box coordinates | 22 exact panel counts | 370.5 px per corner | 916.6 px | ink alone is not panel identity |
| Centreline | 141 | 209.42 px | 578.95 px | 0 |
| Baseline | 84 | 471.59 px | 1203.21 px | 4 |
| Pixels per metre | 0 (units missing) | not measurable | not measurable | 0 |

The four locally checked baselines have median truth error 245.74 px: an on-ink check can accept a wrong grid line. No complete proposal or spec passed. Metrics use reading-order pairing on separate panels only; overlaid layouts are excluded from coordinate-error aggregation because station/panel correspondence was not resolved. Missing values are not counted as accurate zero errors.

The main failure is coordinate-frame confusion: despite red original-coordinate rulers, the model often returns coordinates of the resized image. Example: Wigley is 2100 x 2421 pixels, but its overview proposal places the complete 3 x 3 array within about 800 x 900 pixels. The resulting panel crops miss the intended axes. No generator-truth correction is applied.

## Authentic overlay observations

The images were opened with the image reader, not inferred from model text. Large TIFFs were converted to bounded rasters with macOS `sips -Z 6000`; the original files were not changed. Gunnerus page 1 was rendered with PyMuPDF at 2x.

- **Balclutha sheet 7:** clear half-breadth, body plan and longitudinal sections. The proposed blue panels are small rectangles at the top left, not these views. Magenta/green axes do not align with the intended drawing axes. Rejected.
- **Wapama corrected body-plan stations:** the sheet has several rows of section drawings with visible horizontal datum lines. Blue rectangles and axes sit near the upper-left margin and cover only fractions of the actual plots. Rejected.
- **ALMA:** the selected acquired sheet is a sail/rig plan, not a hull section sheet. The blue panels land in blank margins above the vessel. It cannot supply the requested setup. Rejected.
- **C.A. Thayer midship section:** one large, detailed timber cross-section with a clear vertical central axis and bottom framing. The model's overview reply failed the typed contract, so no accepted setup overlay exists. The source overview was opened; no alignment claim is made.
- **Gunnerus Lines Plan PDF:** three labelled views: body plan upper left, plan upper right, profile below. The first overview and two panel replies completed; a later overview failed the typed contract. The partial overlay was opened: its blue boxes, green baseline and magenta centreline cluster near the upper-left margin, rather than enclosing the three views. No accepted setup exists; the run remains incomplete, not a pass.

These observations show a failed automatic setup experiment, not historical-sheet setup accuracy.

## Silent wrong build: deterministic root cause

A fresh exported STEP reproduces **448.9215 mm RMS** and **+27.4468% volume error within range**. Retained evidence is under `work/w12/sysser45-evidence/`; scorer output is `work/w12/sysser45-score.json`.

The factory asks every station for z=0 to the global hull top (`render.py:374-384`). The actual local bottoms at stations 1, 2, 3 and 4 are about 7.810, 4.742, 2.188 and 0.689 m. There is no hull line below these local bottoms. The tracer still fills the demanded rows using vertical buttock grid strokes and switches to the hull near an intersection. Examples from retained selected points:

- Station 1: half-breadth about 8.01 m remains nearly constant from z=0.058 to 4.986 m (the B8 ruler).
- Station 2: about 8.02 m from z=0.102 to 4.898 m (B8).
- Station 3: about 6.04 m from z=0 to 2.439 m (B6).
- Station 9: about 6.02 m from z=0.093 to 3.598 m (B6).

The Viterbi objective (`ingest.py:179-224`) rewards contrast and continuity, not whole-stroke identity. The candidate grid filter accepts a path with enough off-grid points, even if the rest comes from a ruler. Source-to-STEP validation then checks the selected measured trace, so a CAD model faithful to the wrong trace can pass. This is not a CAD accuracy defect.

Proposed follow-up: retain source-supported local endpoint hypotheses and block paths that gain coverage by ruler continuation or switch identities at grid crossings. Add a shortened-hull-plus-grid regression and retain this frozen case. Do not change the frozen input, force it to fit truth, or widen checks. `agent_tools.py` was not changed.

The fresh controller replay exported CAD but later stopped with `worker_boundary_valueerror`; the frozen historical run's passing status is not assigned to that new task. The exported STEP itself was independently reimported and scored.

## Veto evaluation

- Wrong `sysser45-L1`: model vetoed stations 1-4; it did not veto 5-9. Stations 7 and 8 have short wrong lower continuations visible in the opened overlays. Station 9 follows the B6 grid below the true local hull bottom and is also a confirmed miss. Thus visual whole-line review gives **4 true vetoes, 0 false vetoes, 3 misses and 2 true no-vetoes** on this hull. Main-band RMS alone hides station 9's below-hull extension because that metric starts at the true local bottom. The historical phrase “five wrong stations” is not an exhaustive pixel-identity label.
- Correct Wigley L0 and Ship-D `shipd-1-01410-L0`: all 18 stations returned `follows`, **0 false vetoes**. Fresh STEP scores confirm 7.507 mm / -1.329% volume error and 30.820 mm / -0.377%, respectively. These are two clean control hulls, not a false-veto rate estimate for historical scans.
- Authority remains one-sided: even all-follows does not approve a task.

## Exact model usage

Every request used `deepseek-v4.1-flash` at `https://opencode.ai/inference/go/openai/v1/chat/completions`, through the Rust provider worker. Keys were loaded with the authorized script and were never printed. Final unique receipt totals include failed schema replies and both preliminary probes; no test stub calls are included.

| Experiment | Calls | Prompt tokens | Completion tokens | Reported USD | Provider list USD |
|---|---:|---:|---:|---:|---:|
| 40 development drawings | 581 | 618,569 | 176,567 | 0.00 | 0.19855620 |
| Authentic sheets, including first oversized-raster attempt | 35 | 35,544 | 10,382 | 0.00 | 0.01156080 |
| Setup probes | 21 | 22,075 | 6,136 | 0.00 | 0.00699285 |
| Veto reviews (27 stations, 3 hulls) | 9 | 17,097 | 1,226 | 0.00 | 0.00330015 |
| **Total** | **646** | **693,285** | **194,311** | **0.00** | **0.22041000** |

Final states: 543 completed, 103 failed, zero unknown/not-sent. There were 664 image attachments. All receipts report cost (Go billing); zero reported charge is not an estimate of unsubsidized API cost. The list cost comes from provider receipts, not a memorized price. `receipt_inventory.json` holds each unique request ID, receipt hash, image hash/size and usage. Source crop boxes are in each hash-bound `request.json`; new reading records also retain the image geometry directly. Failed outputs remain evidence, not retries relabelled as success.

## Verification and limits

`refresh-codesight` generated the local structural index, but its managed-bootstrap step failed (`ModuleNotFoundError: render_bootstrap`). No external checkout was changed. The generated index includes temporary captured worker sources and is not part of the source deliverable.

`make test-quick` passed with 630 Python tests (10 CAD deselected), Rust tests, format, Clippy and secret scan. `make test-full` ran once after checking no other full tier was active: PASS, including 10 Python CAD tests, 43 Rust CAD tests, the app real-task test and smoke (`awaiting_human_review`, verifier valid). The Makefile smoke originally omitted `--worker-source`, so that smoke could use the main checkout's editable install. The Makefile now passes the worktree source explicitly; that smoke was rerun separately. All evaluation builds already passed `--worker-source` explicitly. No new Rust CAD test file was needed; the two new finalization tests are in the already-listed `finalization_guards` target.

Mutation checks caught and restored **13 setup guards, 5 Rust guards and 1 renderer guard**. Rust mutations removed the finalization hook, same-STEP binding, completed-receipt guard, image binding and veto-only verdict filter; each produced a failing regression test, not a compile failure. Setup mutations cover panel ink, axes, independent scales, agreement, station order/label/panel, missing fields, scale token/ink, spec publication and no-progress stop. No mutation is committed.

Not complete as a production rollout: automatic source-coordinate reading is unreliable; semantic labels are not independently verified; authentic inputs did not yield complete specs; false-veto coverage is small. Keep the existing supported-input boundary and human review. W12 must not enable the app's live default or replace missing evidence with a guess.
