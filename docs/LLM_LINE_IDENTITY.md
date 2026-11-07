# LLM hull-line identity (W11)

Date: 2026-11-08. Host: macOS arm64. All results are DEVELOPMENT results.
Every candidate keeps `engineering_approved=false`. A person must confirm every
model choice. This report does not establish engineering fitness.

## 1. Question and design

Can a vision model identify the hull lines of crowded drawings better than the
deterministic reader, when the model has wide investigative control but cannot
supply geometry or approve its output?

The model is `deepseek-v4.1-flash`, through the Rust provider worker and OpenCode
Go endpoint. `rust-control/src/credentials.rs` selects a provisioned key slot from
current usage. Keys are loaded through `scripts/load_opencode_keys.sh`; no key is
written to the evaluation evidence or this report.

The controller inspects the captured drawing and makes the same unique-line
selections as the deterministic draft policy. The model then controls the order,
region, zoom and number of tool calls. It can trace, compare, revise, rebuild,
render, ask a person, or submit. There is no aggregate request, token or spend
cap. Existing per-request resource limits, retries/backoff, cancellation, task
storage and no-progress stops remain. A no-progress stop is a failed outcome in
this evaluation, not a successful abstention.

### Tools

| Tool | Host operation and limit |
|---|---|
| `view_region` | Any captured source rectangle; bounded PNG, up to 1024 px per side and 4x enlargement. Returns a view ID and source-to-view mapping. |
| `read_region` | The same pixels, marked as labels, scale bar, dimensions or title block. A reading is a model claim. |
| `trace_corridor` | A corridor in a returned view, not a line. The host traces real source ink and re-reads it in the engine's tight corridor. |
| `trace_from_point` | Follow ink under a clicked view point, then run the same corridor verifier. |
| `enumerate_strokes` | Scanline seeds, stroke following and engine verification. Show numbered, coloured traces. Share candidates across sections with exactly the same panel and calibration. Each call is bounded; later calls are not capped in aggregate. |
| `assign_station` | A station-identity claim with candidate ID, label-view ID, label text and reason. Accepted claims are open `model_choice` guesses. |
| `propose_sheet_setup` | Check scale/grid/datum claims. Accepted setups serve comparisons only. The build keeps declared calibration. |
| `compare_views` | Compare body-plan breadths with plan-view ink crossings. A crossing is evidence, not an identified waterline. |
| build, render, validate | Existing host tools. Validation cannot resolve semantic identity. |
| `ask_person`, `finish` | Pause for a person or submit the current draft. Neither approves geometry. |

### Deterministic verification

The line verifier keeps existing engine thresholds: at least 90% row coverage,
missing-run limit 2.5%, long-component support at least 0.65, minimum vertical
span 25% of the calibrated section, and an engine re-read in a 2.75 source-pixel
half-width corridor. These thresholds were not widened.

The assignment verifier requires a selectable catalog candidate, source ink,
a label-evidence view at the section, no duplicate ink assigned to another
section, and a valid comparison when one is named. It does **not** certify that
the model read the label correctly or followed the correct curve through a
crossing. The evidence explicitly sets `identity_certified=false`.

Rust rejects model-traced lines on the direct selection path, policy confirmation
or replacement of open guesses, unknown tools/fields, status/gate/path/code
injection, and unsnapped model choices. Open guesses block review readiness before
other finalization checks. Only a person can confirm them.

The provider stores the raw completion body. Rust re-hashes and re-interprets it,
then checks decision, model, completion ID and usage. Receipts also bind the
request, prompt, observation, source, generation, revision and image inventory.
Every final source-drawing image has a hash, byte size, pixel size and source
crop box. CAD renders have hash, byte size, pixel size and STEP identity; their
source crop box is null because they are not source-sheet crops.
For an inspection composite, the crop box names the source region represented;
it is not a pixel mapping of the two-panel annotated image. Tracing tools require
a real investigation view ID with its explicit mapping.

## 2. WIP defects and checks

The untested `f572408` snapshot compiled and passed the baseline quick tier when
run with the correct worktree Python environment (620 Python tests). It still had
these operational defects:

1. The foreground cache used `id(image)` without keeping the image alive. A later
   allocation could reuse the ID and get stale masks. The cache now holds one
   image and one window, checked by object identity.
2. Enumeration could emit tags whose candidates were not stored after an
   aggregate catalog cap. The overlay lookup then raised `StopIteration`. The
   aggregate cap was removed; per-call work bounds remain. A separate eight-trace
   aggregate cap was also removed from point/corridor tracing. Task storage and
   no-progress controls remain.
3. A later label view removed earlier stroke tags from model context. The model
   repeatedly enumerated the panel instead of assigning. Latest panel tags now
   remain in task memory. Old panels can be omitted under the unchanged request
   byte limit; omitted panel IDs are listed and full evidence stays in the task.
4. Inspection-image metadata lacked crop boxes. These now name the represented
   source region. Composite overlays must not be treated as simple pixel crops.
5. The benchmark summary crashed on a run with no domain checkpoint and skipped
   Gunnerus scoring when no model existed. Both now produce explicit failure or
   `no_model` rows.

Checkpoint `68cf6cb`: formatting, Clippy, Rust quick tests, 623 Python tests and
secret scan passed. Eleven trust-guard mutations were caught and restored.
`outputs/w11/mutations.json` names each guard and focused test. Removing only one
of the two overlapping receipt-purpose checks did not fail the mode test; removing
the purpose-binding condition as a whole did. No mutation is committed.

Extended tests cover image/observation forgery in normal application and recovery,
forged worker approval flags, and policy replacement of a guess after restart.
The CAD submission test uses the required slow-test marker.

Final code checks: `make test-full` ran once after W12's full tier finished and
`pgrep` found no active full tier. It passed: 624 Python quick tests, 10 Python
CAD tests, all Rust CAD suites, the app real-task test, and smoke
`awaiting_human_review, valid` with explicit worktree source. An earlier quick
run overlapped a two-file cap-removal edit and failed six Python tests on a stale
loaded module. The stable-source rerun and the full tier both passed. This was
not hidden or treated as a successful run.

## 3. Evaluation protocol

Three arms use byte-identical prepared inputs:

- **Abstain:** deterministic policy, `--on-ambiguity abstain`.
- **Draft:** deterministic policy, `--on-ambiguity draft`.
- **Live:** DeepSeek autonomous policy, `--on-ambiguity draft`.

Authentic inputs: Gunnerus raster lines plan (72 sections), Balclutha s7 (10),
Balclutha s48 (3 height bands), Wapama s5 (14), ALMA lines (3 height bands), ALMA
cross sections (3 height bands). The authentic calibrations are provisional
assistant readings from the earlier geometry study. Some x positions are
ordinals, not physical station positions. These cases measure line reading, not
valid full-vessel reconstruction.

Factory sample: the pre-existing fixed sample of 40 DEVELOPMENT cases: six
overlay hulls and four separate-panel hulls, each at levels 0–3. No validation or
sealed-test split is used. A folder called `sealed/truth` contains evaluator-only
truth for these development hulls; inference does not read it. Drawing hashes are
checked against the frozen factory manifests.

The deterministic final runs used `work/w11/snap-final`; live runs used corrected
`work/w11/snap-v2`. Both snapshots keep inference source fixed during a task.
The only snapshot difference is source-image crop metadata; geometry, calibration,
tracers and acceptance thresholds are the same. The live controller also retains
panel-tag memory. The source changes were committed as `68cf6cb`; some runs started
before that commit and record `f572408` as their start/end git label. Controller
binary and worker implementation hashes in task evidence are authoritative.
The later `2495bba` fixes (old-panel memory eviction and removal of the residual
eight-trace cap) are not in the first frozen evaluation binary/source. No
request in those runs reached either bound. Later separate-panel runs use the
full-tier rebuilt controller with memory eviction, still with the frozen Python
source. This is a development comparison, not a single-binary frozen accuracy
claim. The implementation ledger records the exact binary and worker hashes. A full-tier smoke
check also exposed the Makefile's missing `--worker-source`; it now pins this
worktree instead of silently using the main checkout's editable install.
That full-tier release rebuild interrupted one concurrent live case,
`shipd-1-00045-L2`, at `controller_binary_changed`. The original failed attempt
stays in the usage ledger and primary outcome table. A separately labelled retry
uses the preserved evaluation executable; it does not replace the failure.

Every failed/abstained/interrupted case stays in the denominator. A section can
have a recorded line even when the CAD build fails. A line count is not a model
count. Visual counts require opened overlay PNGs and are conservative assistant
judgments, not expert labels. Real ink, partial hull segments, full hull lines and
station identity must not be conflated.

The existing Gunnerus scorer uses cached STEP-derived truth and
`benchmarks/gunnerus/config/metric_gunnerus.json`. A missing model gets `no_model`,
not zero error. Factory geometry uses the existing RMS/volume gate without change.

## 4. Results

### Authentic drawings (105 section/band requests)

| Arm | Sections with a line | Open guesses | Model requests | Prompt / completion tokens | Reported cost, USD | Sum of case wall time, s |
|---|---:|---:|---:|---:|---:|---:|
| Deterministic abstain | 0/105 | 0 | 0 | 0 / 0 | 0 | 59.5 |
| Deterministic draft | 4/105 | 105 | 0 | 0 / 0 | 0 | 277.5 |
| Autonomous live | 20/105 | 27 | 93 | 858,845 / 7,180 | 0 | 1,995.3 |

All six abstain runs abstained. Draft produced one CAD draft (ALMA lines); the
other five abstained, including builds with insufficient readable sections or
invalid geometry. All six live runs ended `no_progress`. No live CAD model was
accepted as a current candidate. Live choices remain visible in state/overlays,
not completed geometry.

| Input | Sections | Abstain lines | Draft lines | Live lines | Live requests | Live prompt / completion tokens | Live wall, s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Balclutha s7 | 10 | 0 | 0 | 10 | 25 | 263,292 / 2,261 | 653.3 |
| Balclutha s48 | 3 | 0 | 0 | 2 | 17 | 120,017 / 1,176 | 249.7 |
| Wapama s5 | 14 | 0 | 0 | 7 | 20 | 201,702 / 1,679 | 507.7 |
| ALMA lines | 3 | 0 | 3 | 0 | 9 | 51,244 / 585 | 79.1 |
| ALMA sections | 3 | 0 | 1 | 1 | 15 | 147,008 / 1,083 | 158.2 |
| Gunnerus raster | 72 | 0 | 0 | 0 | 7 | 75,582 / 396 | 347.3 |

All 93 authentic requests completed; none failed, was unknown, or lacked cost.
Reported marginal cost is $0 under Go billing. Sum of provider list cost is
$0.12399015; it is not an invoice and not a claim that model use has no cost.

**Gunnerus accuracy against STEP truth:** all three arms have 0/72 lines and no
CAD model. The existing scorer returns `no_model` for each. Half-breadth, area,
volume and waterplane errors are undefined, not zero. Truth stays evaluator-only.

### Factory development sample (40 cases, 360 sections per arm)

| Arm | Lines | Open guesses | Built CAD drafts | Correct by existing geometry gate | Run outcomes | Sum wall, s |
|---|---:|---:|---:|---:|---|---:|
| Abstain | 0/360 | 0 | 0 | 0/40 | 39 abstained; 1 interrupted before worker start | 510.2 |
| Draft | 138/360 | 242 | 12 | 1/40 | 28 abstained; 12 draft_not_verified | 792.9 |
| Live | 34/360 | 6 | 1 | 1/40 | 36 no_progress; 1 provider_failed; 1 blocked; 2 draft_not_verified | 4,510.6 |

The interrupted abstain case is `shipd-1-01618-L1` (`worker_not_started`), retained
as a failure. No retry replaces it. Draft line counts by level: L0 90/90,
L1 16/90, L2 26/90, L3 6/90. Only `shipd-1-00617-L0` meets the frozen 2% RMS
half-beam and 5% in-range volume gate. It has 0.34% RMS and -2.64% volume error.
The other 11 built drafts fail that gate. An extreme heavy-degradation draft
(`shipd-1-00617-L3`) has 68.36% RMS and +557.61% volume error. Draft labels are
therefore essential: more CAD output is not better evidence.

All 24 overlay-layout live cases stopped without a line at `no_progress`.
Separate-panel results include one valid CAD draft, one blocked draft submission,
and many no-progress stops. One provider admission failed because all configured
credentials were temporarily unavailable; it is counted, not retried into success. Compact receipt-backed
rows are in `outputs/w11/`. No source drawing or derivative is redistributed.

| Factory live usage | Exact value |
|---|---:|
| Requests intended / completed / not sent | 279 / 278 / 1 |
| Failed HTTP requests / unknown completions | 0 / 0 |
| Prompt / completion tokens | 1,965,007 / 17,065 |
| Reported marginal cost / list cost, USD | 0 / 0.27915568 |
| Receipts without cost | 1 (the not-sent credential failure) |

Of 34 live lines, 28 are unique-line harness selections and six are model choices.
All 34 live lines are level 0; levels 1–3 have none. The model added only six
recorded identities; 25/34 lines are conservatively
hull-side identities on opened overlays, versus 45/138 for deterministic draft.
These counts do not prove complete geometry. The only scored live model is the
same clean Ship-D 00617 hull that passes in deterministic draft. No improvement
in the frozen geometry gate is shown. The second `draft_not_verified` submission
has a blocked invalid-geometry build and no STEP, so it is not counted as built.

The combined primary live evaluation used 372 intended requests (371 completed,
one not sent), 2,823,852 prompt and 24,245 completion tokens. Reported marginal
cost is $0; list cost is $0.40314583. Sum of live case wall times is 6,505.9 s;
parallel wall time is smaller. These totals exclude the separately listed pilots
and supplemental retry.

### Development attempts outside the primary table

The inherited/pilot ledger contains 79 provider receipts, 555,725 prompt tokens
and 5,069 completion tokens. Reported cost is $0; list cost totals $0.08306973.
This includes the previous agent's s7 pilot and the first interrupted batch before
panel-tag memory was fixed. None is substituted for a final result. The supplemental
binary-drift retry (`shipd-1-00045-L2`) made 37 completed calls, 397,076 prompt
and 2,880 completion tokens in 618.0 s. It recorded seven lines (six model choices
and one fallback), but stopped at `no_progress` with no valid model. Its overlay
still contains grid extensions and partial hull curves; it does not repair the
primary failure or establish reliable identity. Its reported cost is $0 and
list cost is $0.05778962. Cost means the provider's
reported marginal cost; list cost is shown to avoid implying free computation.
Across primary runs, retained pilots and the supplemental retry: 488 intended
requests, 3,776,653 prompt tokens, 32,194 completion tokens, reported cost $0 and
list cost $0.54400518. One request was not sent; 487 completed. These totals include
inherited pilot evidence, not only calls made by this continuation.

## 5. Visual findings

- Deterministic overlay-layout drafts repeat one inner curve across all stations
  of a half-panel. The lines are real ink, but most identities must be wrong.
- ALMA lines draft follows the same outer right-hand curve over three height
  bands. These are hull-like curves, not three established station identities.
- ALMA cross-section draft follows a small vertical keel/detail line, not the
  broad side envelope.
- Balclutha s7 live made ten model choices. The opened crop shows centre/grid
  lines, curve-to-grid switches, short upper verticals and diagonal construction
  strokes. Conservative confirmed complete identities: 0/10. Passed verifiers
  establish ink support, not hull identity.
- Balclutha s48 live recorded two guesses. One follows a lower outer vertical
  frame/planking line; the other an interior vertical chain/grid line. Neither is
  a defensible complete hull envelope.
- Separate factory panels are easier at clean levels. DTMB5415 L0/L1/L2 has
  9/7/2 visibly hull-side draft lines. Ship-D 00617 L0 has 9. Ship-D 01103 L0/L2
  has 9/9 visually hull-side lines at page scale, although the L2 CAD score is
  poor. These total 45 conservative visual hull-side identities out of 138
  recorded factory draft lines. This visual test is weaker than geometric truth.
  All 40 draft overlay PNGs were opened as four contact sheets; every nonempty
  case was also opened individually. Overlay-layout repeated identities remain
  uncertain, with at most one correct identity per half-panel, not nine.
- Other separate drafts extend a local hull bottom down a vertical grid line.
  Ship-D 00045 L0/L2 has partial hull segments mixed with these extensions.
  Ship-D 00617 L3 picks long grid/centreline segments while black hull curves
  remain visible behind them. Conservative complete-line identity count is zero
  for these mixed/grid cases.
- DTMB5415 L0 live has seven deterministic selections plus one model choice;
  all eight visibly follow the separate station-side outlines, but station 9
  remains unread. Ship-D 00617 L0 live has seven automatic selections and two
  model choices; all nine follow hull sides, and its geometry score matches the
  deterministic draft. Ship-D 01103 L0 live has eight hull-side lines at page
  scale, leaving station 9 out. Ship-D 00045 L0 live has eight automatic selections and one
  model choice. Most curves are hull-like, but low-end grid extensions remain
  and its CAD build is blocked. Do not call nine recorded lines a valid model.
- Wapama live guesses include diagonal construction paths and long vertical
  grid switches. ALMA sections live selects a small vertical keel/detail line,
  not the broad side envelope. Conservative complete identities for all 20
  authentic live choices: zero.

## 6. Conclusions and limits

The architecture gives the model primary investigative control without giving it
geometry-writing or approval authority. That is not evidence that the model is a
reliable primary hull-line reader. Initial results are negative: no-progress
stops are common, and real-ink verifiers accept semantically wrong grid segments.
A person remains essential. More calls alone do not resolve wrong identity.

The next improvement must separate complete hull paths from grid/construction
strokes and test label-to-curve continuity through crossings. It must not loosen
ink support or review gates to increase coverage. Results here are development
feedback; a future accuracy claim needs new held-out families and expert visual
labels, not another pass over these cases.
