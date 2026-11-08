# Live agent experience: watch it think, watch the ship take shape (design, lane B)

Date 2026-11-08. Base `continue/v0.5`. Branch `design-b-live`. Design only; no code change.
Status: proposal for the founder. Resume point: section 9 (staged plan), stage L1.

## 0. Summary

When a person drops a set of lines drawings, the app shows the investigator at work on the sheet
and the hull growing in 3D, in one synchronised view. Four rules:

1. **The drawing shows where the model looks.** Every model view, crop, trace or click is a box,
   point or path on the source sheet, in sheet pixels. All of these already exist in the ledger
   (`crop_box_px`, `point_px`, `path_px`, `region_px`, `roi_px`).
2. **The model's own words, short.** Show the decision `reason` (one sentence, always present) as
   the narration line. The `notes` (plan) and thinking text go in an expandable "Thinking" box.
3. **The hull is built from section curves first, the surface second.** Sections from the build
   record (`result.json` `points_yz_m`) appear as 3D curves station by station, coloured by
   source label; the STL skin fades in under them when the build has one.
4. **The person can always stop, steer or accept.** Pause, "That is a grid line", "Use this
   stroke", "Accept draft". Each action is a controller operation, so every check applies.

**First version (stage L1) uses only existing events and files.** It replays the ledger with
timing, which also gives replay and scrub of finished runs for free.

## 1. Evidence from real runs

| Fact | Source | Consequence |
|---|---|---|
| A run has 100-130 events in 90-560 s; 15 % are `decision`, 40 % are provider/worker intent and result pairs | `w18d-corrected/dtmb5415-L0` (101 events, 561 s), `h2h-sealed-v2/.../shipd-1-03915-separate-L0` (130 events, 120 s) | About one visible step per 5-40 s. Intent/result pairs are the "working" state, not separate lines. |
| `build_first_hull` took 155 s with no event between intent and result | dtmb5415 events 5-7 | The longest wait has no news. Stage L2 adds worker progress. |
| Every `decision` has a one-sentence `reason`; most also have `notes` (a plan, up to 700 chars) | all decision payloads | `reason` is the narration line; `notes` is the expandable thought. |
| Model views carry `crop_box_px` in sheet pixels and `view_px_per_source_px` | `read_region`, `enumerate_strokes`, `trace_from_point` results | Attention boxes and model clicks map exactly to the sheet. |
| Refused tools return a reason and an image (`stroke_too_short`, `no_ink_in_corridor: ink on 30 of 214 corridor rows`) | shipd-1-03915 events 67, 87 | Refusals are good drama and good teaching: show them in place, in amber. |
| The model repeats itself (3 identical `enumerate_strokes` + `read_region` loops; `repeated_action_refused`) | both runs | Collapse repeats into one line with a count ("Read the labels again, 3 times"). |
| `result.json` sections have `points_yz_m` and `source_label`; the STL is 1.8 MB and the event files are 20-100 KB each (3.8 MB per run) | dtmb5415 `domain/builds/first-*` | Curves are cheap to send; full events are not. Never send raw events to the UI. |
| The scoreboard has per-section `max_m`, `rms_m`, `label`, `colour` | `domain/renders/*/station-scoreboard.json` | The fit score can tick per station. |
| `station-overlay-sheet.png` shows built cuts (solid) over reference (dots) per panel | F1 overlay, dtmb5415 r0191 | s01 and s09 (the AI-corrected ones) visibly miss the ink. Live: overlay cuts on the real drawing as vectors, not as a PNG. |
| Provider requests use `"stream": false`; thinking defaults to disabled; the receipt keeps only the decision | `controller.rs` 1009-1055 | No token streaming in v1. Thinking text needs a receipt field (stage L3). |
| The app polls all task event counts every 500 ms; `get_events` re-reads every event file of the task on each change | `app/src-tauri/src/main.rs` 205-216, `app/core/src/events.rs` | Fine for the timeline, too slow for the live view on long runs. Stage L2 fixes it. |

## 2. Layout

Same three panes as `APP_SPEC.md`, with a live mode on the workspace:

- **Drawing (left, large).** Source sheet with the attention layer (section 3) on top.
- **3D (right).** Hull view (section 4). A small score dial in its corner.
- **Narration strip (under both, 2 lines high).** The current step: icon, one sentence, elapsed
  time, a pulsing dot while a request or worker is in flight. Click opens the step in the timeline.
- **Inspector Timeline tab** becomes the "Thinking" log: one card per model step (section 5).
- **Control bar (top of workspace):** Pause / Resume, Speed (live, 1x, 4x, 16x for replay),
  scrub bar with step ticks, "Accept draft" (enabled when a draft exists).

## 3. On the drawing, moment by moment

Coordinates: all marks are in source-page pixels, drawn in the existing SVG overlay of
`drawing.js`. A view in view pixels converts with `crop_box_px` and `view_px_per_source_px`.

| Moment (ledger) | What the person sees on the sheet | Camera |
|---|---|---|
| `task_created`, `worker_result initialize` | The sheet fades in. A thin scan line sweeps once top to bottom (600 ms) while the narration says "Reading the sheet". | Fit page. |
| `survey_sheet` / `describe_views` result | One labelled box per view family (Body, Plan, Profile, Title block), drawn in turn, 150 ms apart. Panels of a body family get thin inner boxes. | Fit page. |
| `describe_vessel` decision | The read dimensions appear as small pins at their `view_id` box: "LOA 142 m (read)", "Draft 6.2 m (inferred)" in a lighter tone. Stations and waterlines appear as faint ticks along the body plan grid. | Fit page. |
| `inspect_source` decision | The listed sections' `roi_px` boxes pulse once. The "cursor of attention" (a soft ring, 24 px, accent colour) glides to the first box. | Zoom to the union of the boxes. |
| `inspect_source` result | Every candidate line of those sections draws in thin grey (stroke-dashoffset, 400 ms per section, staggered 80 ms). | Hold. |
| `read_region` decision and result | A rectangle at `region_px` with the subject tag ("Labels") and a magnifier icon. When the result arrives, the crop the model saw shows as a thumbnail in the Thinking card. | Zoom to the region, 600 ms ease. |
| `enumerate_strokes` result | Each stroke lights up in its own colour with its tag number, one after another (60 ms apart), then holds. This mirrors the image the model received. | Zoom to the panel. |
| `trace_from_point` decision | A click ripple at `point_px` (converted to sheet pixels). | Zoom to a 300 px box around it. |
| `trace_corridor` decision | The corridor (`path_px` with `half_width_px`) draws as a translucent band along the path. | Zoom to the band. |
| trace accepted | The new candidate line draws inside the band in accent colour; the band fades. | Hold. |
| trace refused | The band or ripple turns amber with the refusal reason as a pinned note ("Ink on 30 of 214 rows"). It fades to a faint mark after 4 s but stays on the sheet until scrubbed away. | Hold. |
| `select_contours` / `assign_station` | The chosen line turns solid in its source colour; a station pin snaps to its top end ("St 1, read 'BODY PLAN STATION 1'"). Other candidates of that section dim. | Short zoom out to the panel. |
| `propose_section` | The authored curve draws dashed purple over the panel, from keel to deck, with the model's `basis` as the pin text. | Zoom to the panel. |
| `render_candidate` result, scoreboard | Built cuts overlay the drawing as vectors (section 4.4). | Fit sections. |
| `repeated_action_refused`, `model_output_rejected` | No sheet change. The narration shows "Same step again, refused" in grey. | Hold. |

Attention cursor rules: one cursor only; it moves at most once per 400 ms; it never jumps
further than the visible area without a zoom-out first (zoom out, move, zoom in: 300 + 300 ms).
The person's own pan or zoom turns automatic camera off until they press "Follow" (a toggle in
the drawing toolbar). Marks stay after the camera leaves, so the sheet slowly becomes a map of
everything the model looked at.

## 4. In 3D, how the hull grows

### 4.1 First hull

`first_hull_ready` (always before the model's first call in the current controller): the section
curves of the first build appear one by one from aft to fore (80 ms apart), each sliding in from
0.3 m off its station plane. Then the STL skin fades from 0 to 0.85 opacity over 500 ms.
Caption: "First hull from the traced lines". The score dial shows the first combined fit.

During the 155 s wait before it (stage L1), the 3D pane shows a wire box of the principal
dimensions if `describe_vessel` gave them, else an empty grid with "Building the first hull".

### 4.2 Sections station by station

Data: `sections[].points_yz_m` and `source_label` of the current build's `result.json` (new
command `get_build_sections`, section 8.2). Each section is one `THREE.Line` (half-breadth,
mirrored), placed at `x_m`.

- A section whose curve changes between builds morphs over 400 ms (same point count after
  resampling to 64 points by arc length). Unchanged sections do not move.
- A section the model is working on (from the last `inspect_source`, `assign_station`,
  `propose_section` decision) is drawn thicker with a slow pulse; the matching station plane
  shows.
- Colour by source label, one palette shared with the drawing and the section strip:

| Label | Colour | Line |
|---|---|---|
| traced | slate blue | solid |
| repaired | teal | solid |
| interpolated | grey | dotted |
| ai_inferred | purple | dashed |
| ai_corrected | magenta | dashed |
| omitted | none; a red tick on the keel line | n/a |

### 4.3 Skin

The STL arrives only with a build (`draft_built`, `worker_result build_*`). Load it in a worker
thread (`STLLoader.parse` in a Web Worker), then swap the mesh with a 300 ms cross-fade. Guessed x
ranges stay amber bands (existing `guessedRanges`). Between builds the old skin stays at 0.4
opacity so the section curves read clearly in front of it.

### 4.4 Cuts on the drawing

When a render writes `station-scoreboard.json`, the built cut of each station draws on its body
panel in the drawing as a solid line over the ink, coloured green to red by `rms_m` relative to
`cut_tolerance_m`. This is the live form of the F1 overlay sheet: the person sees s09's built
curve leave the ink without opening an image. Stage L1 can show the overlay PNG
(`station-overlay-sheet.png`) in the Thinking card instead; vector cuts need the cut points in
the scoreboard (stage L2, section 8.1).

### 4.5 Fit score

A dial in the 3D corner: combined fit (`combined_fit`, today 0.9919) and the worst station. When a
new value arrives it counts to it over 600 ms and flashes green (better) or amber (worse), with
the change ("+0.4 %"). A per-view breakdown (body, plan, profile from `whole_vessel_score.py`)
shows on hover once the whole-vessel design lands.

## 5. How the reasoning is shown

One card per model step in the Thinking log. Never the raw JSON.

```text
[icon] Read the labels in the station 1 panel                       0:16   $0.002
       "I need the station label near the curve to tell which tag
        is station 1."                                    <- decision.reason, quoted
       ▸ Plan (notes)        ▸ What it saw (thumbnail)   ▸ Thinking (if on)
       Result: label read view, 1024 x 738                <- plain worker result
```

- **Headline**: the plain verb from `events.rs` `describe_decision`, extended for the new tools
  ("Clicked on the ink at station 1", "Drew a corridor along station 1", "Listed 6 strokes in
  the station 1 panel", "Claimed tag 1 is station 1").
- **Quote**: `decision.reason`, as written by the model, in quotes and italic so it reads as the
  model's claim, not the app's fact.
- **Plan**: `decision.notes`, collapsed. Show only when it changed from the last card.
- **What it saw**: thumbnails from the provider request `images` (already in `ProviderCallView`).
- **Thinking**: the model's reasoning text when `investigation_thinking` is on and the receipt
  keeps it (stage L3), collapsed, monospace, capped at 2 000 characters with "show all".
- **Result line**: one plain sentence from the worker `result.status` and `message`
  ("Refused: the stroke is only 3 rows long"). Refusals amber, success neutral.
- **Repeats**: a step with the same tool and arguments as the previous card merges into it with
  a counter ("x3"). `model_output_rejected` and `context_compacted` show as one grey line.
- **Cost**: per-call `observed_cost_usd`, and a running total in the status bar.

Narration strip = the headline and the quote of the newest card, nothing else.

## 6. Steering: pause, correct, accept

| Control | Where | Effect | Exists? |
|---|---|---|---|
| Pause | control bar, Space | Controller stops at the next step boundary with status Paused. In-flight request finishes. | Partly: `cancel_task` stops at a boundary; the controller has a Paused status (`requested_step_boundary`) but the app has no pause command yet |
| Resume | control bar | `resume_task`. | Yes |
| "Use this line" | click a candidate on the drawing | `choose_line` (operator `select_contours`), then rebuild. | Yes |
| "That is a grid line" | right-click a candidate or stroke | Records an operator note on that candidate; the controller excludes it from selection and shows the note to the model. | New: `operator_hint` |
| "Use this stroke" | right-click a stroke from `enumerate_strokes` | Operator `assign_station` with label "operator". | New tool route |
| "Look here" | drag a box on the sheet while paused | Operator hint with `region_px`; the next model observation includes it. | New: `operator_hint` |
| Free text | text field under the narration while paused | Operator note (300 chars) in the next observation. | New: `operator_hint` |
| Accept draft | control bar | Stop the agent, keep the best valid draft, status Draft. Open guesses stay open. | Partly: `finish` path for operators |

Rules: steering is only possible while paused or between steps (the controller lock is per
action). A hint is evidence for the model, never an approval: it does not close a guess and does
not certify identity. Every hint is a ledger event, so replay shows it as a "You" card.

## 7. Pacing

Real runs alternate long silences (5-155 s per request or worker) with bursts (intent, result,
decision in under 100 ms). The UI must smooth both.

- **Batching.** Events that arrive within 250 ms of each other form one beat. A beat produces at
  most one narration change, one camera move and one 3D update.
- **Minimum dwell.** Each visible step holds at least 1.2 s live (so bursts do not flicker) and
  never queues more than 3 s behind real time; beyond that, intermediate steps skip their
  animation and show their final state.
- **Working state during silence.** While a provider or worker intent has no result: pulsing dot,
  elapsed time ("Thinking 0:23", "Building the hull 1:12"), and for workers the last progress
  line (stage L2). No fake progress bars.
- **Animation budget.** Line draw 400 ms, camera 600 ms ease-in-out, 3D morph 400 ms, fade 300 ms.
  Respect `prefers-reduced-motion`: no camera moves, no draw-on, instant state changes.
- **Noise filter.** Hidden live: `worker_intent`, `provider_intent` (become the working state),
  `context_compacted`, hash fields, `catalog_ready`. Shown grey and merged: rejected or repeated
  model output.
- **Replay and scrub.** A finished run opens at its end state with the scrub bar. Dragging the
  scrub rebuilds the view state at that sequence (section 8.4) without animation; Play runs the
  beats with compressed silences (each silence capped at 1.5 s at 1x). Step ticks on the bar are
  coloured by kind (read, trace, choose, build, check, refusal). Keyboard: left/right = previous
  or next model step.

## 8. Technical plan

### 8.1 Events: what exists, what to add

Existing and enough for stage L1:

| Need | Source today |
|---|---|
| Model step, tool, arguments, reason, notes | `decision` (actor `live_model`) |
| Attention boxes | `arguments.region_px`, `point_px`, `path_px`; result `view.crop_box_px`, `view_px_per_source_px`; `roi_px` of sections |
| Refusals | `worker_result` `result.status` = `proposal_refused`, `error_code`, `message`; `operation_rejected`; `repeated_action_refused` |
| In-flight state | `provider_intent` / `worker_intent` without a result yet |
| Builds | `first_hull_ready`, `draft_built`, `worker_result` of `build_draft`; `domain/builds/*/result.json` |
| Scores | `best_valid_candidate.combined_fit` in each worker response; `station-scoreboard.json` |
| Cost, images | `provider_result` receipt |

To add (controller, all appended through `store.append`, so the hash chain holds):

1. **`worker_progress`** (stage L2): `{operation, stage, done, total, section_id?}` from Python
   workers via a progress file the controller tails, written at most once per 500 ms.
   Not part of the chain's meaning; the controller may also write it to a side file
   `task/progress.json` instead, to keep the ledger small. Prefer the side file.
2. **`section_built`** (stage L2): during `build_first_hull` and `build_draft`, one record per
   section as soon as its curve is final: `{section_id, x_m, source_label, points_yz_m (64
   points)}`. Same side-file route: `task/live/sections.json`, rewritten atomically.
3. **Cut points in the scoreboard** (stage L2): `station_overlay.py` adds `cut_px` (sheet
   pixels, at most 128 points per station) next to `max_m` and `rms_m`.
4. **`operator_hint`** (stage L3): ledger event `{actor, kind: grid_line|use_stroke|look_here|
   note, section_id?, candidate_id?, region_px?, text?}`. The observation builder adds the open
   hints to `recent_history`; selection code excludes candidates marked `grid_line`.
5. **Thinking text** (stage L3): when thinking is on, keep `reasoning_content` in the provider
   receipt file (not the event), bounded to 8 KB, redacted with `transcript::safe_text`.
6. **Attention events are not needed**: the regions are already in decision arguments and
   results. A UI-side projection derives them.

### 8.2 Backend (app/core)

- New transport-independent function `get_live_steps(task, after_sequence) -> LiveStep[]`, next
  to `get_events`. `LiveStep { sequence, time_ms, kind, tool, headline, reason, notes,
  marks: Mark[], result: {state: ok|refused|working, text}, images, cost_usd, score }`;
  `Mark { shape: box|point|path|band, px: number[][], label, tone }`. Marks are in sheet pixels.
  All parsing stays in Rust; the UI never sees raw events.
- Incremental reading: cache per task the last parsed sequence and the `Context` (as `events.rs`
  builds it), so each call reads only new event files. Today `get_events` reads all of them.
  Use the existing compact-JSON byte check (`provider_view.rs`) to skip large events early.
- `get_build_sections(task, build_path) -> {x_m, source_label, points_yz_m}[]` from
  `result.json`, bounded (8 MB read limit as in `draft_view.rs`) and resampled to 64 points.
- `get_live_state(task) -> {in_flight: {kind, operation, since_ms}|null, progress, score}` from
  the tail of the ledger and the side files.
- Commands follow the adapter rule in `APP_SPEC.md`, so the later web build gets them over HTTP.

### 8.3 Streaming instead of 500 ms polling

- Replace the poll loop in `app/src-tauri/src/main.rs` with a `notify` file watcher (one
  recursive watch on the runs folder, filtered to `*/events/*.json`, `*/progress.json`,
  `*/live/*.json`). Debounce 100 ms per task. Emit `task-changed` (unchanged payload, so the
  current UI keeps working) and a new `task-live` `{task, sequence, live_changed: bool}`.
- Keep the 500 ms poll as a fallback when the watcher fails to start (network drives, some Linux
  setups) and for the task list.
- The web build maps `task-live` to the planned Server-Sent Events endpoint.
- Expected latency: under 150 ms from `store.append` to the UI, against up to 500 ms + full
  re-read today.

### 8.4 UI (app/ui)

- New module `js/live.js`: a step queue with the beat, dwell and catch-up rules of section 7,
  and a pure function `stateAt(steps, sequence)` that returns the marks, section curves, score
  and narration at any sequence. Live mode and scrub both use it, so replay is not a second
  code path.
- `drawing.js`: add a `marks` layer (SVG group) with `setMarks(marks, {animate})`; reuse
  `animateTo` for the camera; add the "Follow" toggle.
- `model3d.js`: add `setSections(sections, {animate})` that keeps one `THREE.Line` per section
  id, updates `BufferGeometry` positions in place (`attributes.position.needsUpdate`), and
  morphs with a 400 ms tween in the existing `requestRender` loop. The hull mesh stays as is;
  add opacity cross-fade on swap. Dispose replaced geometries (already the pattern in
  `clearModel`).
- `app.js`: `onTaskLive` handler calls `get_live_steps` and feeds `live.js`; the existing
  `get_task` reload stays for the inspector, debounced to once per 2 s while running.

### 8.5 Performance limits

| Item | Limit | Why |
|---|---|---|
| Marks on the sheet | 400 live; older ones merge into one faint path per section | SVG stays smooth at 60 fps |
| Section curves | 300 sections x 64 points, mirrored = 38 k vertices | Trivial for three.js |
| STL swap | parse in a Web Worker; at most one per 3 s | 1.8 MB parse blocks about 100 ms on the main thread |
| `get_live_steps` payload | 64 KB per call; steps carry no images, only artifact paths | Event files are 20-100 KB each |
| Thumbnails | lazy, through `read_artifact` and the existing `cachedArtifact` cache | Images are 6-60 KB each |
| Replay of a 130-event run | `stateAt` under 5 ms; precompute keyframes every 20 steps | Scrub must track the pointer |
| File watcher | one watch for the runs folder; ignore `receipts/`, `requests/`, `worker-logs/` | Workers write many files |

## 9. Staged plan

**L1, existing events only (first version).** Backend `get_live_steps` with incremental read;
UI `live.js`, marks layer, Thinking cards with `reason` and `notes`, narration strip, working
state from intent-without-result, first-hull section curves from `result.json` (new read-only
command), STL fade, score dial from `combined_fit`, overlay PNG in the card, replay and scrub,
Stop/Resume (`cancel_task`, `resume_task`) and "Use this line" (existing); a true Pause command
is a small L1 backend addition. Keep 500 ms polling.
Check: open `w18d-corrected/dtmb5415-L0` and `h2h-sealed-v2/.../shipd-1-03915-separate-L0`
in replay; every decision has a card and a mark; scrub end state equals the static view.

**L2, live feel.** `notify` watcher and `task-live`; `progress.json` and `live/sections.json`
side files from the workers (sections snap in during `build_first_hull`, which fills the 155 s
gap); cut points in the scoreboard, vector cuts on the drawing.
Check: latency under 150 ms on a live deterministic run; no UI frame over 50 ms (Performance
panel) during an STL swap.

**L3, steering and thinking.** `operator_hint` event and its use in the observation and in
selection; "That is a grid line", "Use this stroke", "Look here", free text; Accept draft;
thinking text kept in receipts.
Check: a controller test that a `grid_line` hint removes that candidate from selection and
appears in the next observation; the hash chain verifies after hints.

## 10. Risks and open questions

- **Theatre over truth.** Animations must follow ledger facts only. No invented "scanning" of
  regions the model did not request. The opening scan line is the one exception and is labelled
  "Reading the sheet" (the initialize worker really reads it).
- **The model's `reason` can be wrong** (dtmb5415: "s01-s03 are confirmed good" while s01 was the
  worst fit). Quotes are styled as claims; the score dial and vector cuts are the check beside
  them.
- **Side files vs ledger.** Progress and partial sections outside the hash chain are display
  only; the final build in the ledger stays the record. Founder to confirm.
- **Steering changes the benchmark.** Runs with operator hints must be marked and excluded from
  blind benchmarks.
- **Thinking text cost.** Thinking requests take up to 45 s; showing them does not slow the run,
  but enabling thinking does. Keep it a setting, default off.
