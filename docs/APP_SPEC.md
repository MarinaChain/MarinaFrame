# MarinaFrame desktop app: specification v1

Status: approved direction (user, 2026-11-07): Tauri 2, a proper desktop app, Mac first,
Windows next. This file is the contract between the Rust backend (`app/src-tauri/`) and the UI
(`app/ui/`). Change it only together with both sides.

## Goals

A person who is not a naval architect can watch a reconstruction run and understand it:
what drawing went in, which line the system chose on each section and why, what 3D shape came
out, how it was checked, and what the model (Claude Sonnet 5.5 by default) saw and answered.

## Non-goals (v1)

- No engineering approval anywhere. `engineering_approved` is always false.
- No editing of drawings or specs. No new reconstruction logic in the app.
- No cloud, no accounts, no telemetry. Windows packaging is v2 (keep code portable now).
- Compare mode against an answer key (Ship-D, SIMMAN, Gunnerus) is v2; leave a slot for it.

## Architecture

- `rust-control` gains a library target (`src/lib.rs`) that re-exports the existing modules.
  The `marinaframe` binary and the integration tests keep working unchanged.
- `app/src-tauri` (Tauri 2) depends on that library. It reads task folders, and runs
  actions through the same controller functions the CLI uses, so every existing check applies.
- The UI is static HTML, CSS and JavaScript in `app/ui/` (no framework, no bundler required).
  three.js is vendored as a pinned local file. No network access from the UI.
- Reads never take the controller lock. A running task is read from its files
  (`state.json`, `events/*.json`, `domain/**`); the event sequence number is the change signal.
- Actions that mutate a task run on a background thread through the controller, which takes
  its own lock. One action per task at a time.

## Desktop and web from one code base

The UI and the backend logic must also run later as a web app with a thin extra layer:

- UI: every backend call and event subscription goes through one adapter module
  (`invoke(command, args)`, `onTaskChanged(handler)`, file picking). It selects Tauri, HTTP
  (`POST /api/<command>`, Server-Sent Events at `/api/events`) or mocks. No other UI file touches
  `window.__TAURI__` or fetches backend data.
- Backend: view building, path guards, task listing, settings, notices and actions live in a
  transport-independent Rust module with plain functions. Tauri commands are thin wrappers.
  A later HTTP server (for example axum) wraps the same functions.

Work a web deployment adds beyond that layer (not in v1): accounts and access control, per-user
task storage, uploads instead of local file paths, a job queue for CAD workers on Linux servers,
provider keys held on the server, and a rights check before any licensed drawing is shown to
another user.

## Screens

1. **Library (left sidebar).** Tasks found under the configured runs folder, newest first:
   name, status chip, time. A "New run" button (pick a spec file). With AI drafting on (the default) and a model route
   found (the `claude` CLI or an OpenCode Go key), the run uses the live policy in draft mode; otherwise the deterministic draft.
   Section "Datasets" lists `work/sources/*` folders read-only (v1: name and size only).
2. **Workspace (centre).** Drawing and 3D model side by side, resizable split.
   - Drawing: the source page image with the section regions. For the selected section,
     every candidate line drawn as an overlay: chosen = solid accent, others = thin grey;
     hover shows its plain-language label and reason. Zoom and pan.
   - 3D: the current build's `model.stl` in a three.js orbit view (rotate, zoom, reset,
     section planes at the station positions). Empty state when no build exists yet.
   - Section strip below: one tile per section with its status (chosen / declined / not read).
3. **Inspector (right panel), tabs:**
   - **Timeline**: events in plain language, newest at the bottom, live.
   - **Checks**: each validation check with value and limit, e.g. "Trace fidelity 0.86 mm,
     limit 1.1 mm: pass".
   - **Model**: provider requests: the images sent (thumbnails), the answer, accepted or
     rejected, tokens, cost, key slot.
   - **Evidence**: hashes, contract, manifest. Collapsed by default.
4. **Status bar**: one status badge, policy, revision, last update time.

## Writing rules for all UI text (anti-slop)

- Say a fact once, in one place. No repeated disclaimers.
- No internal IDs, hashes or contract field names outside the Evidence tab.
- Plain verbs: "Picked the outer line", "Declined: two lines fit equally well",
  "Built 3D model", "Checked against the drawing".
- No hedging stacks ("provisional", "still requires", "remains outstanding" together).
  Status is a badge: Running, Needs review, Declined, Failed, Cancelled.
- No slogans, no rhetorical triads, no marketing adjectives.

## Notices

Notices (for example "Engineering approval is never automatic") are dismissible. A dismissed
notice stays dismissed across restarts, keyed by notice id, stored by the backend in the app
config directory. Settings has "Show dismissed notices again".

## Commands (Tauri `invoke`), all JSON

Errors return `{ "code": string, "message": string }` with plain-language `message`.

| Command | Arguments | Returns |
|---|---|---|
| `list_tasks` | `{}` | `TaskSummary[]` |
| `get_task` | `{ task: string }` | `TaskView` |
| `get_events` | `{ task, after_sequence: number }` | `EventView[]` (only newer) |
| `get_live_steps` | `{ task, after_sequence: number }` | `LiveSteps` (see "Live steps") |
| `get_hull_sections` | `{ task, revision: string }` | `HullSections` (see "Live steps") |
| `read_artifact` | `{ task, path }` | `{ mime, base64 }` (`path` is relative to the task folder, with `/` separators, never absolute, and must stay inside it; images, STL (48 MB) and GLB (64 MB) only; the STL is in the unit of the CAD export, so the UI scales it to `length_m`) |
| `start_run` | `{ spec_path: string }` | `{ task: string }` |
| `start_sample_run` | `{}` | `{ task: string }`. The built-in sample vessel (`app/core/sample/`: a generated drawing of 11 station sections of an analytic hull form and its spec, made by `examples/make_sample_ship.py`; no licensed data) is written to `<runs>/samples/sample-<ms>/` and started as a deterministic run (no model calls). Home offers it on a first start |
| `prepare_intake` | `{ files: string[] }` | `IntakePreview` (see "Intake") |
| `start_intake_run` | `{ preview: IntakePreview }` | `{ task: string }` (see "Intake") |
| `cancel_task` | `{ task }` | `{ ok: true }` |
| `resume_task` | `{ task }` | `{ ok: true }` |
| `choose_line` | `{ task, section_id, candidate_id }` | `{ ok: true }` (operator intervention, then rebuild/validate via the controller) |
| `revise_region` | `{ task, request: RevisionRequest }` | `{ ok: true }` (see "Mark and revise"; the pass runs in the background) |
| `force_keep_revision` | `{ task, revision_id }` | `{ ok: true }` (see "Mark and revise") |
| `get_settings` / `set_settings` | `{}` / `Settings` | `Settings` |
| `get_default_settings` | `{}` | `Settings` (fresh-install defaults; the UI offers them as one-click choices) |
| `get_setup_status` | `{}` | `SetupStatus { ai: AiStatus, worker: SetupCheck, runs_folder: SetupCheck }`, `SetupCheck { ok, path, message }`. File-system checks only (no process starts). The worker Python is found at run time: `MARINAFRAME_WORKER_PYTHON`, then Settings, then the runtime inside the app bundle (`Contents/Resources/worker/bin/python3`), then the repository `.venv` (`MARINAFRAME_REPO`, or debug builds); nothing merely beside the app is searched. Runs, intake and export use the same Python. When none is found the setup check asks and the choice is saved to Settings. The welcome screen shows it on first use and when the worker or runs folder is not ready; a missing key is not a stop (continue without AI) |
| `get_model_usage` | `{}` | `ModelUsage { key_source, slots: KeyUsage[], next_slot, warning, checked_ms }`, `KeyUsage { slot, meters: UsageMeter[], highest_percent, usable, error }`, `UsageMeter { window, percent, status, resets_at }`. Settings > Key usage, on demand only (no timer). One `GET https://opencode.ai/zen/go/v1/usage` per configured key, made exactly as the provider worker makes it (bearer key, same User-Agent, 64 KiB bound, an answer that echoes the key is refused). Keys are read as `model_keys.rs` reads them and never returned; `next_slot` uses the worker's rule (`credentials::highest_usage_percent`; one key is used without a read). `warning` when every usable key is at 90% or more, or none is usable |
| `plan_batch` | `{ paths: string[] }` | `BatchPlan { sets: DrawingSet[], skipped: { path, reason }[] }`, `DrawingSet { name, files }`. Reads names only. Files dropped on their own are one set (as before: one vessel's sheets). A dropped folder is a batch: each PDF in it is one set, each subfolder is one set of its drawings, and its loose images together are one set. More than 32 sheets in a set, or more than 40 sets, are skipped with a reason. One set opens the intake; several open the batch sheet |
| `queue_batch` | `{ sets: DrawingSet[] }` | `QueueView { slots, running, waiting: QueuedSet[], held }`, `QueuedSet { id, name, files, added_ms, state: waiting\|starting\|failed, message }`. Adds the sets at the end of the queue (`batch_queue.json` in the app config folder; a restart keeps it). The watcher pump starts waiting sets, in order, while running runs (any in the runs folder) plus starting sets are fewer than `slots` (the native slot rule of the worker: half the cores, 1 to 8, `MARINAFRAME_NATIVE_SLOTS`). A start reads the set and starts its run with the proposed labels; a started set leaves the queue, a failed one stays with its reason. `held` says why nothing starts (AI drafting off or no key) |
| `get_queue`, `remove_queued`, `move_queued` | `{}`, `{ id }`, `{ id, delta }` | `QueueView`. Remove or move (delta -1 or +1) a waiting or failed set; a starting set cannot change |
| `dismiss_notice` / `reset_notices` | `{ id }` / `{}` | `{ ok: true }` |
| `list_datasets` | `{}` | `{ name, path, bytes }[]` |

Live updates: the backend emits the event `task-changed` with `{ task, sequence }` when a
watched task's event count grows (poll every 500 ms or file watch).

### Types

```text
TaskSummary { task: string (absolute path), name: string (vessel_id of the captured spec, else the task folder name), status: Status,
              policy: "deterministic"|"live", updated_ms: number, sections: number }
Status = "running" | "needs_review" | "draft" | "declined" | "failed" | "cancelled" | "paused" | "blocked"
                                 // "draft" = controller status draft_not_verified
TaskView {
  summary: TaskSummary,
  revision: string|null,
  source_page: { path: string, width: number, height: number } | null,
  sections: SectionView[],
  model: { stl_path: string, length_m: number, beam_m: number, depth_m: number,
           volume_m3: number|null } | null,
  checks: CheckView[],
  provider: ProviderCallView[],
  notices: NoticeView[],         // already filtered: dismissed ones removed
  draft: DraftView | null,       // set while the current build is a draft (see "Drafts")
  source_counts: { label: string, count: number }[],  // sections per source label of the draft build
  warnings: string[],            // warnings of the draft build; shown as warnings, never errors
  activity: ModelActivity | null, // live-model steps and cost; null for a deterministic run
  evidence: object               // raw hashes and contract, shown only in Evidence tab
}
SectionView { id: string, x_m: number, roi_px: [x0,y0,x1,y1],
              state: "chosen"|"guessed"|"declined"|"not_read",
              reason: string,                       // plain language; for "guessed" the guess reason
              guess: GuessView | null,              // set when state is "guessed"
              source: { label: string, basis: string|null } | null,  // draft build only (see "AI in a draft")
              candidates: CandidateView[] }
GuessView { id: string,                             // guess_id
            kind: "best_candidate"|"bridged_gap"|"dropped_end"|"model_choice"|"model_authored",
            x_range_m: [number, number] | null,      // bridged or dropped region
            chosen_candidate_id: string | null,      // null when a station was spanned
            alternatives: string[],                  // other candidate ids a person can pick
            score: number | null,                    // 0..1 source support of the chosen line
            reason: string }                         // e.g. "5 lines found; took the best-supported one (score 0.93)."
DraftView { status: "draft_not_verified",
            guesses: GuessView[],                    // open; each blocks review
            resolved: (GuessView & { resolution: "confirmed"|"replaced",
                                     resolved_candidate_id: string })[] }
CandidateView { id: string, label: string,          // plain language, e.g. "Outer line"
                chosen: boolean, selectable: boolean, why: string,
                polyline_px: [number, number][] }    // in source-page pixels
CheckView { name: string, value: string, limit: string|null, result: "pass"|"fail"|"not_run" }
ProviderCallView { id: string, state: "completed"|"failed"|"not_sent"|"unknown",
                   images: { path: string, label: string }[], answer: string,
                   accepted: boolean, prompt_tokens: number|null,
                   completion_tokens: number|null, cost_usd: number|null, key_slot: number|null }
EventView { sequence: number, time_ms: number, text: string,  // plain language
            kind: "read"|"choose"|"build"|"render"|"check"|"model"|"finish"|"other" }
NoticeView { id: string, tone: "info"|"warning", text: string }
Settings { runs_folder: string, worker_python: string, theme: "system"|"light"|"dark" }
```

## Drafts (best-effort result)

Decision (founder, 2026-11-07, confirmed by the sealed head-to-head on 2026-11-08): where the
source is ambiguous, a run started from the app builds a draft instead of declining
(controller `on_ambiguity: draft`, deterministic policy). The CLI default stays `abstain`; the
app sets draft explicitly and does not read the CLI default (flag `--on-ambiguity draft|abstain`).
LLM-first stays an explicit option, not the default. Reason: see
[Head-to-head, hull-disjoint (v2)](BENCHMARK_FACTORY.md#head-to-head-hull-disjoint-v2) and its
[protocol](plans/2026-11-08-h2h-sealed-v2.md). The verified path is unchanged. A pinned test
(`app_runs_default_to_deterministic_draft`, `app/core/src/actions.rs`) guards the default.

- Controller status `draft_not_verified` (app Status `"draft"`, badge "Draft"). A draft never
  becomes "Needs review" while a guess is open; the controller refuses it at finish and in
  `verify`. `engineering_approved` stays false.
- Data sources for the backend: open guesses are `domain.open_guesses` in `state.json` (the
  same list as `domain/state.json` `guesses`), resolved ones are `domain.resolved_guesses`; the
  ledger event `draft_built` lists the guesses of each draft. A section is `"guessed"` when it
  has an open guess. A `bridged_gap` or `dropped_end` section has no line in the draft.
- The draft build's files are `model-draft.step` and `model-draft.stl` (not `model.stl`);
  `current_candidate.draft` is true and the run's `result.json` has a `draft` object with the
  guesses. `model.stl_path` must use the run's `exports.stl` name.
- To make a draft verified, a person confirms or replaces each guess with `choose_line` (an
  operator `select_contours`). Confirming keeps the guessed candidate; replacing picks another.
  Then `resume_task` runs the normal build, render, validate and finish. A `bridged_gap` or
  `dropped_end` guess has no line to pick: it stays open, and that task stays a draft.
- Draft banner: a notice with id `draft-guesses:<open count>` (warning tone, dismissible; a new
  count is a new id, so it returns). It says how many guesses remain and what to do next. The
  "Draft" badge stays while the status is draft. Timeline lines: "Built a draft: 3 sections
  guessed", "You confirmed the line for 4.0 m", "You picked another line for 4.0 m".
- UI marks: guessed lines and tiles are dashed amber; guessed x ranges (a bridged gap, a dropped
  end, or the span around a guessed line) are shaded amber on the 3D model. A guessed section
  offers "Confirm this line" (the guessed line) and "Use another line" (each alternative).
- UI text examples: "Draft: 2 guesses to check", "Guessed: took the best-supported of 5 lines",
  "No readable line at x=4 m; spanned 2 to 6 m".

## AI in a draft (read-only)

- `SectionView.source.label` is the `source_label` of the section in the current draft build's
  `result.json`: `traced`, `repaired`, `interpolated`, `ai_inferred`, `ai_corrected`; `omitted`
  for a dropped end. A bridged gap has no built section and shows `interpolated`. `basis` is
  `evidence.authored_basis`, the model's one-line basis for the AI labels. `source_counts` counts
  the labels in a fixed order. Without a draft build all three are empty or null.
- `warnings` are the build's `gaps` with severity `warning` plus the fairing notes of AI sections.
  The UI shows them in a collapsible amber list. Blocking gaps are not listed; the status says so.
- `activity` comes from the event log: `decision` events with actor `live_model` (tool and
  reason), and provider receipts (`provider_result`, `provider_reconciled`: request count,
  tokens, `usage.list_cost`). If a receipt has no list cost, `list_cost_complete` is false and the
  sum is a lower bound. The Model calls tab shows it as a collapsible list.
- None of this adds a failure state: missing files give empty results.

## Mock data

`app/ui/mock/` holds JSON fixtures in exactly these shapes, plus a small STL and PNG, so the UI
runs in a plain browser without the backend (`window.__TAURI__` absent → mocks). The backend
agent builds a real `TaskView` from a real task and checks it against the same shapes.

## Acceptance

- `cargo tauri dev` (via npm script) opens the app on macOS arm64 and shows a real task.
- A new deterministic run started from the app updates the timeline live and ends in
  "Needs review" with a rotatable model.
- Choosing another line rebuilds and re-validates through the controller.
- A dismissed notice stays dismissed after restart.
- All existing tests, Clippy and the deterministic smoke still pass.


## Run notifications (2026-11-09)

- Setting `notify_finished` (default `true`, also for older settings files). When the watcher sees a
  run go from running to stopped, the app shows one macOS notification for that run: the run name
  and its outcome only (draft ready, ready for review, declined, stopped with an error, waiting for
  you), never drawing content. A cancel gives none; the first watch round after start gives none.
- Shown with `/usr/bin/osascript` (`display notification`); the texts are script arguments, not
  script source. No notification plugin is used (none was in the lock file).

## AI drafting (LLM-first default, 2026-11-08)

- Founder decision: the AI builds the draft by default. Setting `ai_drafting` (default `true`,
  also for settings files written before the field existed).
- Keys: the environment (`OPENCODE_API_KEY`, `_2`, `_3`) or the key file
  `~/.config/marinaframe/opencode-go-keys.txt` (one key per line, mode 600; the same file as
  `scripts/load_opencode_keys.sh`). The app never shows or logs a key; `get_ai_status` returns only
  `enabled`, `key_found`, `claude_found` (the `claude` CLI was found), `active` (enabled and
  `claude_found` or `key_found`), the key file path and `key_count` (key slots a new run can use, 0
  to 3; never the keys). The Claude subscription needs no key: the `claude` CLI uses its own login.
- Without the `claude` CLI and without a key, or with AI drafting off, runs use the deterministic draft and the New run sheet
  says so.
- The controller runs each model request in a child process of its own executable
  (`provider-worker`); the desktop app handles that call in `main` before any window starts.
- Model (founder decision 2026-11-09): the app drafts with Claude Sonnet 5.5 through the Claude
  subscription (the `claude` CLI in print mode; run config `model` = `claude-sonnet-5-5`,
  `fallback_models` = `crouton-alpha-free`, `deepseek-v4.1-flash`). Only a subscription rate-limit
  or usage-limit answer moves a run to Crouton, then DeepSeek, through OpenCode Go (a
  `model_switched` event). A model choice in Settings may come later; for now the default is
  fixed. Details: `docs/AGENT_HARNESS.md`, "Drafting model".

## Exports

Backend for milestone M5 (design plan section 7; review workflow sections 3, 5, 6 P0-6, P0-7,
P0-9, P0-11). Package `src/vessel_reconstruction/exports/`; it only reads the task folder.

In the app (`app/core/src/export.rs`, `js/export.js`):

- `export_run(task, revision, outputs)` with `outputs` a subset of `step`, `stl`, `offsets`,
  `hydrostatics`, `report`, `tanks`, `structure`, `package`. The backend runs the command below (arguments, no shell;
  at most 300 s, then the worker is stopped: `export_timeout`) into a staging folder, moves the
  chosen files and the manifest into `<task>/exports/<rNNNN>/` and removes the staging folder.
  Refused while an action runs on the task. Returns `{ folder, revision, files: [{ kind, file,
  path, bytes }], not_built, stamp, engineering_approved: false }`; `not_built` lists chosen
  outputs the build does not have (`step`, `stl`). Worker refusal: `export_worker` with the
  worker's reason.
- `list_exports(task, revision)`: the same shape for the files already in the folder.
- `tanks` (capacity plan and sounding tables, CSV) and `structure` (steel tables, CSV, the
  OCX file, `.3docx`, and the display GLB `<stem>_structure.glb`, role `structure_model`, which the
  3D view adds to the whole vessel with a Steel switch; `structure/display.py`) need the run's tank model or structure folder (layout fixed in
  `app/core/src/run_tables.rs`: `<task>/tanks.npz`, `<task>/tank_tables/`, `<task>/structure/`).
  The backend passes `--tanks <task>/tanks.npz` and `--structure <task>/structure` to the
  worker when they exist; otherwise a chosen `tanks` or `structure` is listed in `not_built`.
  The UI offers these two rows only when the run has them (`TaskView.tank_model`,
  `TaskView.structure_files`).
- `reveal_export(task, path)`: shows a file or folder inside `<task>/exports/` in Finder
  (`open -R`; `explorer /select,` on Windows; `xdg-open` of the folder on Linux). Other paths:
  `export_reveal`.
- UI: an **Export** button in the run title bar (any run with a revision that is not running)
  opens a sheet: one toggle per output (icon, one-word name), size after export, "Show in
  Finder" per row and "Show folder". The sheet states "Draft, not for construction"; it never
  says approved or verified.

Command: `python -m vessel_reconstruction.exports --task DIR --revision rN --out DIR
[--draft-m T] [--waterlines N] [--vessel NAME]`. It prints the manifest as JSON; exit code 2 (and
`{"error": ...}` on stderr) when the revision has no valid build. Python: `export_draft(task,
"r3", out)`.

- Build used: the last `valid` entry of `domain/state.json` `builds` with `revision_id` rN
  (`r3` and `r0003` are the same). Station overlays and ink fit come from the render whose
  `observation.json` audits the same STEP bytes (SHA-256). Open guesses: the task's current
  `guesses` when rN is the current revision, else the build's `draft.guesses`.
- File names: `<vessel>_<rNNNN>_DRAFT_<part>`. Vessel: `--vessel`, else spec `vessel_name`, else
  the build's `vessel_id`.
- `_offsets.csv`: one row per station: `station, x_m, source_label, keel_z_m, top_z_m`, then
  half-breadths (m, 3 decimals) at each waterline (`hb_at_z_<z>_m`). Read from the built section
  curves (largest |y| where the curve meets the height). Waterlines: spec `waterlines_m` when
  given, else 10 equal steps from the lowest keel to the highest top point. Empty cell: the
  station does not reach that waterline (never written as 0). Leading `#` lines: stamp, vessel,
  revision, run, units and datum.
- `_hydrostatics.json` and `_hydrostatics.csv`: at the design waterline z = T above the baseline
  (`--draft-m`, else spec `design_draft_m`, else 0.6 x depth marked "assumed"). Volume,
  displacement (1.025 t/m3), LCB, VCB, KB, Awp, LCF, BMt, BMl, waterline length, largest breadth,
  largest section area, wetted surface, Cb, Cp, Cm, Cwp (basis stated in the file). Method: the
  exported STL (a tessellation of the STEP) clipped at T, divergence theorem, exact for the mesh;
  the mesh volume is checked against the build volume (warning above 1 %). Without an STL: the
  station curves by the trapezoid rule, with a warning. Not computed: `hydrostatics: null` with
  `not_computed_reason`.
- `_report.pdf` (matplotlib PDF backend; matplotlib is a locked dependency): page 1 summary
  (vessel, revision, run, status and review state, particulars, hydrostatics, per-section source
  in plain words and ink fit max/RMS/% B/2/near, open guesses, warnings; long lists continue on
  page 2), then one page per station overlay image. Ink fit that was not rendered shows "not
  checked". Footer on every page: "Draft — not for construction; engineering sign-off happens
  outside MarinaFrame".
- `_model.step` and `_model.stl`: copies of the build's files. STEP `FILE_DESCRIPTION` holds the
  stamp "Draft hull model from MarinaFrame. Not approved for construction.", vessel, revision,
  run and units; a binary STL has the stamp in its 80-byte header. The manifest keeps the SHA-256
  of the original files (`source_sha256`). A missing file is listed in `not_built`.
- `_manifest.json`: stamp, vessel, revision, run, build, `result_sha256`, review state, open
  guess count, `engineering_approved: false`, and every file with role, bytes and SHA-256.
- `_package.zip`: all files above plus the manifest, with fixed entry dates, so the same build
  gives the same zip bytes.
- Tests: `tests/test_exports.py` (synthetic box task, closed-form V prism, and a trimmed real
  fixture `tests/fixtures/exports/shipd-1-00679-L0` without CAD files).
- The benchmark hull metrics (`benchmarks/gunnerus/hull_metrics.py`, used by
  `benchmarks/factory/truth.py`) are not moved: sealed benchmark manifests hash that file. The
  export computes the same quantities (volume and waterplane area below T) with its own exact
  mesh integrals.

## Live steps (stage L1, 2026-11-09)

Design: [live agent](design/2026-11-08-b-live-agent.md) sections 3 to 5 and 8.2. Code:
`app/core/src/live.rs` (types, cache), `live/builder.rs` (events to steps), `live/geometry.rs`.

`get_live_steps(task, after_sequence)` derives compact steps from the event ledger. It never
returns raw events, receipts, keys or host paths: free text from the model or the worker has
absolute paths replaced by `[path]`; image and build paths are task-relative.

- One step per model decision (`actor: "model"`), person decision (`"person"`) or harness
  operation without a decision (`"code"`: open, survey, first hull, first score). The worker
  intent and result of a decision fold into its step. Ledger noise (provider intent and result,
  staging) is not a step; a pending request or worker shows in `in_flight`.
- Incremental: the backend keeps the parsed ledger per task and reads only newer event files.
  A step can change after it was first returned (its result arrives, a repeat count grows); its
  `last_sequence` then grows and the next call returns it again. **The UI replaces steps by
  `sequence`.** Pass the returned `last_sequence` as the next `after_sequence`; 0 returns all.
- Replay: `time_ms` is relative to the first event, so a finished run replays with its own timing.
- Repeats: a model decision equal to one of the last 3 model steps (same tool, arguments and
  controller progress key), or a `repeated_action_refused`, folds into one `repeat_collapsed`
  step per repeated step, with `repeat_of` (the repeated step's `sequence`) and `count` (times in
  all, original included). Identical system lines in a row (notes shortened) share one step.
- A decision that the controller did not run (a build declined by `missing_sections_hint`, or
  another decision came first) closes as `refused` with "Not run ...".
- Kinds: `survey` (survey_sheet), `views` (describe_views, propose_sheet_setup), `vessel`,
  `look` (inspect_source, view_region, recall_view, compare_views), `read` (read_region),
  `strokes` (enumerate_strokes), `trace` (trace_from_point), `corridor` (trace_corridor),
  `assign` (assign_station, select_contours), `propose_section`, `build`, `render`, `score`
  (a render with a fit score, validate_candidate), `refused` (host refusal, `operation_rejected`,
  `finalization_rejected`), `repeat_collapsed`, `finish`, `system`.
- Marks are in source-page pixels. View pixels convert with the view's `crop_box_px` and
  `view_px_per_source_px` (from earlier results in the ledger, else the loaded
  `domain/state.json` `views`); a view that neither knows gives no mark. Section boxes
  and calibration come from the captured spec and inspection results. A model-drawn section
  (`curve_summary_yz_m`) converts with the section calibration (`x = centre + y * ppm`,
  `y = baseline - z * ppm`). Stroke and accepted lines use the catalog candidate polyline (at
  most 64 points), else the stroke's two ends.
- Builds: a worker result with a candidate build path gives `revision` with that build's
  `result.json` sections. A render with `fit_score` gives `revision` with the fit and each
  section's ink RMS (`fit_score.station_ink_fit[id].rms_m`). Each build's curves travel once:
  later steps of the same build carry the sections with empty `points_yz_m`.
- Size: about 30 to 70 KB for a whole finished run of 100 to 130 events (first call), a few KB
  per later call. A first call takes 30 to 70 ms (release build).

```text
LiveSteps { steps: LiveStep[], last_sequence: number, started_ms: number (epoch ms of the first event),
            elapsed_ms: number, in_flight: InFlight | null, finished: boolean }
InFlight  { kind: "model"|"worker", operation: string|null, since_ms: number }
LiveStep  { sequence: number, last_sequence: number, time_ms: number,
            kind: StepKind, actor: "model"|"person"|"code",
            title: string,                 // plain headline: "Listed 6 strokes in the s01 panel"
            text: string,                  // narration: the decision reason, or plain text for code
            notes: string|null,            // the model's notes (plan), for a collapsed "Why"
            targets: { kind: "section"|"view", id: string }[],
            attention_px: [l, t, r, b] | null,   // camera box, source pixels
            marks: Mark[],
            tool: ToolCard | null,
            revision: RevisionInfo | null,
            images: string[],              // task-relative PNG paths for read_artifact (at most 4)
            model_ms: number|null, cost_usd: number|null,   // model answer time and list cost
            repeat_of: number|null, count: number }
Mark      { shape: "box"|"point"|"polyline"|"band", tone: Tone, points_px: [x, y][],
            label?: string, tag?: number, candidate_id?: string, half_width_px?: number }
            // box: two corners; point: one point; band: polyline + half_width_px
Tone      = "attention"|"view"|"panel"|"stroke"|"accepted"|"authored"|"refused"|"person"
            // refused marks carry the refusal reason as label on the first one
ToolCard  { tool: string, duration_ms: number|null, state: "working"|"ok"|"refused"|"failed",
            text: string,                  // "Refused: ...", "6 strokes", "Not kept: fit 0.1793 to 0.1752"
            kept?: boolean }               // model-drawn section kept by the build
RevisionInfo { id: string|null, path: string|null, fit: number|null, sections: SectionCurve[] }
SectionCurve { id: string, x_m: number, points_yz_m: [y, z][],   // 64 points by arc length, metres
               source_label: string|null, ink_rms_m: number|null }
HullSections { revision: string|null, path: string, sections: SectionCurve[] }
```

`get_hull_sections(task, revision)` returns the section curves of one build for the 3D growth:
`revision` is a revision id (`r0002`) or a step's `revision.path`. It reads only that build's
`result.json` (no STL). Unknown builds return the error code `revision_not_found`.


## Mark and revise (2026-11-09)

A person circles part of the drawing and says what to fix, as in an image chat. It works on
AI runs (live policy, draft mode) that are not working at that moment.

**UI (`js/mark.js`).** The drawing pane has a **Mark** button (key M). In mark mode the person
drags a **Box** or a freehand **Lasso** on the drawing, or clicks a section tile in the strip.
A popover shows what was marked, five quick chips (Too full, Too fine, Follow ink, Smoother,
Wrong line) that prefill a sentence, a text field (500 characters at most) and **Send**. The
person's mark is brand blue; teal stays for AI activity and amber for review.

**Request.** `revise_region` sends:

```
RevisionRequest {
  schema_version: "marinaframe.revision_request.v1",
  instruction: string,                       // 1..500 characters
  region?: { page_px_box: [l, t, r, b] } | { lasso_px: [x, y][] },   // sheet pixels, 3..64 lasso points
  station_range_m?: [from, to],              // a station range, metres
  target_section_ids?: string[]              // at most 12
}
```

At least one of `region`, `station_range_m` or `target_section_ids` is required.

**Controller (`rust-control/src/revision.rs`).** The request is recorded as the ledger event
`operator_revision_requested` (actor `human_operator`). Then one focused pass runs:

1. The worker crops the marked region (`view_region`); the crop goes to the model first.
2. The model sees the instruction, the region and the current curves of the sections in range
   (`[height_m, half_breadth_m]` offsets, with their ink fit), and is offered `propose_section`
   only. Named sections and a station range give up to three edits; a drawn region alone gives
   one edit on a section whose panel it touches (any section when it touches none).
3. The worker's keep rule judges each edit: it is kept only when the combined fit improves.
4. When an edit was kept and the run had a built draft, the draft is rebuilt.

The result is the event `operator_revision_result` with `outcome` (`kept`, `partly_kept`,
`not_kept`, `no_edit`, `stopped`), `fit_change`, `not_kept_fit_change` and each edit. A finished
draft stays a finished draft; any other run pauses. `force_keep_revision` applies the not-kept
edits without the keep rule and records `operator_revision_forced` with `operator_forced: true`.
`engineering_approved` stays false in every event.

**Live steps.** The request is a person step (`kind: "revise"`, a `person` mark, the instruction
as text). The crop and the model's edit are ordinary steps. The result step has `kind: "revise"`,
the title "Kept, fit +0.012" or "Not kept: worse by 0.004", and `mark_revision`:

```
MarkRevision { revision_id, outcome, fit_change, not_kept_fit_change,
               can_keep_anyway: boolean, operator_forced: boolean }
```

The Thinking card of a result with `can_keep_anyway` has a **Keep anyway** button.

**CLI.** `marinaframe revise --task DIR --request FILE.json` and
`marinaframe force-keep --task DIR --revision ID` do the same from a terminal.

**Mock.** In the preview the pass streams in as live steps. The edit is kept unless the
instruction contains "fine" or "wrong", so both results can be seen.


## Intake (drop a drawing set, no spec file; M2)

The person drops PDF, PNG, TIFF or JPEG files. The app writes the run spec itself.

1. `prepare_intake { files }` runs `python -m vessel_reconstruction.intake prepare`. It renders
   every PDF page (200 dpi, `ingest._read_image`), reads each raster frame and its dpi, runs the
   sheet survey and proposes view regions per page with a label and a confidence. It never
   refuses a page: a page without a recognised view gets one `other` region and the warning
   `no_view_found`. A file that cannot be read is a set warning `unreadable_file`; the other
   files continue. Files go to `<runs folder>/intake-sets/<intake_id>/` (no task state, so the
   run list skips it).
2. The UI shows the pages (thumbnails), lets the person change labels, skip pages and type
   particulars, then calls `start_intake_run { preview }` with the edited preview.
3. `start_intake_run` checks the edits (labels, regions inside their page, at least one page
   kept), runs `intake write-spec` (copies the sources into `run-input-<ms>/sources/`, writes
   `intake.json` and a sheet-only `spec.json`), starts the run with the current AI setting
   (`actions::start_run`) and copies the inputs into the task's `intake/` folder.

The spec is sheet-only: `sections: []` and `intake: {file, sha256}`. The spec page is the page
with the most confident body plan. Typed LOA, beam and depth become `constraints`. Only a live
draft run accepts a sheet-only spec: the model reads views, scale and stations in phase 1, then
the domain materializes the sections (`materialize.py`; evidence `ai_inferred`, warnings for
every fallback) before the first hull. Strict runs and runs without AI stop at once with
`input:sheet_only_needs_live_draft`; the preview then carries the warning `ai_off`.

```text
IntakePreview { intake_id, pages: IntakePage[], warnings: IntakeWarning[], render_dpi,
                particulars: Particulars, ai_active: bool }
IntakePage    { page_id, file, file_name, kind: "pdf"|"raster", page_index, dpi: number|null,
                dpi_source: "pdf_render"|"file_metadata"|"unknown", width_px, height_px,
                thumbnail_png_base64, thumbnail_scale, regions: IntakeRegion[],
                warnings: IntakeWarning[], skip: bool }
IntakeRegion  { region_id, label: "body_plan"|"half_breadth"|"profile"|"title_block"|"other",
                confidence: 0..1, region_px: [left, top, right, bottom], evidence }
IntakeWarning { code, message, file? }   // low_dpi ("Scan 150 dpi: lines may be read less
                                         // exactly."), dpi_unknown, small_image, no_view_found,
                                         // unreadable_file, ai_off
Particulars   { vessel_name, loa_m?, lpp_m?, beam_m?, depth_m?, draft_m?, scale? }
```

Errors: `intake_files` (0 or more than 32 files), `intake_file_type`, `intake_file_missing`,
`intake_region`, `intake_no_pages`, `intake_unknown`, `intake_worker`, `intake_copy`,
`worker_python_missing`.

## Whole-vessel parts (2026-11-09)

Status: the app reads `<task>/whole_vessel/execution.json` (the ship-cad worker output, `app/core/src/parts.rs`); the mock gives the same shape. It mirrors one entry of
`result.components` in the ship-cad worker output (`src/vessel_reconstruction/ship_cad.py`,
`execution.json`), plus a plain label and the person's review. Plan:
`docs/plans/2026-11-09-whole-vessel-scope.md` section 7.

`TaskView.components: ComponentView[] | null` (null or absent: the run has no parts beyond the hull).

```text
ComponentView {
  id: string,                        // ship-cad component id, "house_t1"
  op: string,                        // ship-cad op: "hull"|"deck"|"deckhouse"|"bulwark"|"appendage"|"opening"|…
  label: string,                     // the worker's optional "label", else made from the id
  status: "measured_draft"|"draft_guess",   // ship-cad status; both are drafts
  built: boolean,                    // false: no solid (reason says why)
  reason: string,                    // ship-cad reason: what was filled, or why it was not built
  view: "plan"|"profile"|"body"|null,      // ship-cad source.view
  bbox_m: { min: [x, y, z], max: [x, y, z] } | null,   // hull frame, metres; null when not built
  volume_m3: number | null,
  step_path: string | null,          // "whole_vessel/<id>.step" relative to the task folder (mm)
  arguments: { name: string, value: string|null,       // value as text with its unit, when known; an outline: "4 points, 13.57 to 21.27 m by -3.00 to 3.00 m"
               source: "traced"|"ai_inferred"|"guessed",  // ship-cad source_labels[name]
               basis: string|null }[],                  // ship-cad provenance[name].basis
  review: "open"|"accepted"|"marked", // the person's review of this part (app state)
  review_note: string | null,       // what to change, when "marked"
  revision: number,                  // 0 as the run built it; +1 for each re-run from a mark
  revision_note: string | null,      // the mark note the last re-run followed
  revision_pending: boolean,         // the last re-run waits for Keep or Undo
  changes: { name: string,           // what the last re-run changed ("volume" is the last row)
             before: string|null, after: string|null,
             before_source: string|null, after_source: string|null }[],
  display: { profile_m: [x, z][][],  // sketch outlines (a tank: from its loft), metres; from the
             plan_m: [x, y][][],     // worker's component "display"; null when none was written
             content_class: string|null } | null   // tank colour token --tank-<class> (TANKS_V1 section 6)
}
```

Command: `review_component { task, component_id, decision: "accepted"|"marked"|"open", note?: string }` →
`{ ok: true }`; saved in the app config folder (`part_reviews.json`), not in the run folder. A part with guessed values can be accepted as a draft part; nothing is ever
"approved" (`engineering_approved` stays false). "marked" needs a note of 1 to 500 characters (what to change).

### Re-run one part from a mark (2026-11-09)

Commands (each returns the part as a `ComponentView`):

- `revise_part { task, component_id }`: re-run the part from its saved mark note. Refused when
  the part has no mark note (`revise_needs_mark`), while another action runs on the run
  (`action_in_progress`), when AI drafting is off (`ai_drafting_off`) or no model key is found
  (`model_key_missing`). Takes up to 20 minutes (then it is stopped and the old part stays).
  Any sign-off of the parts ends (the part changed).
- `keep_part_revision { task, component_id }`: keep the new revision. The mark has been acted
  on, so the review of the part opens again; any sign-off ends.
- `undo_part_revision { task, component_id }`: put back the previous entry and STEP file. The
  mark stays, so the person can change the note and re-run.

The app runs the worker `python -m vessel_reconstruction.part_revise --task <task> --part <id>
--note=<note>` (or `--keep`, `--undo`) with the worker Python of the other workers
(`worker_python.rs`), arguments only (no shell). The model key comes from the app's key lookup
(`model_keys.rs`) into the worker's environment only; it is never an argument or printed. The
worker crops the run's drawings around the part (at most 3 crops, profile and plan first, at most
1,000,000 pixels each) from `<task>/whole_vessel/views.json` (each view: drawing file, kind,
bounds, origin, metres per unit; DXF, PNG or JPEG; schema in the module docstring). It gives
DeepSeek the crops with their pixel-to-metre calibration, the part's current values with their
source labels, and the note (ship-cad JSON, thinking disabled, at most 3 turns; a reply that does
not build goes back with the reason). Only that part is rebuilt in the ship-cad worker. Its entry
in `whole_vessel/execution.json` gets the new values (source `ai_inferred`; a value the model
gives back unchanged keeps its old label and evidence, so a traced value stays traced), `revision`,
`revision_note`, `revision_kept: false`, `revision_history` (the whole previous entries) and the
request receipts; the old STEP stays as `<id>.r<previous revision>.step`. Crops, replies and
receipts stay in `whole_vessel/revisions/<id>-r<n>-<time>/`. The other parts do not change, and
`engineering_approved` stays false. Hull parts cannot be re-run this way (the hull is a loft).
The whole-vessel GLB is not rebuilt: the 3D view shows the run's model until the next full run.

Parts tab: on a marked part with a note, "Re-run with this note". While it runs, a status line
with the elapsed time (other actions wait). Then the part's state is "New revision" (AI teal),
with "Revision n: what changed" (each changed value before and after, with its source label) and
Keep or Undo. A kept revision shows "Revision n, from the note …".

The Parts tab groups parts by op, draws a profile and a plan sketch of the boxes (the selected
part in the selection blue, parts with guesses dashed amber), lists each value with its source
label and basis, and offers Accept (A), Mark (M), Next (N), Show in 3D and Copy part list.

Tanks (`op` `tank`) form their own group. `TaskView.capacity_plan` (read by
`app/core/src/run_tables.rs` from `<task>/tank_tables/*_capacity_plan.csv`; `null` without one)
holds `{ file, stamp, rows, groups, engineering_approved: false }`; each row keeps the source
label of each value (`traced`, `read`, `guessed`; the weight takes the weaker label of volume and
density). A selected tank shows its row; below the parts, a Capacity plan panel lists every tank
with totals per content group and the sounding table of the selected tank
(`sounding_table { task, tank_id }` → `{ tank_id, file, stamp, columns, rows,
engineering_approved: false }`; only a tank of the capacity plan, else `sounding_not_found`).
The app does not compute tank values.

3D: `TaskView.whole_vessel_model: { glb_path, bytes, loadable } | null` names the run's
tessellated model (`whole-vessel-draft.glb`, one node per part named by its id). The app loads
it through `read_artifact` only when `loadable` (at most 64 MB); STEP files are never loaded into
the 3D view (a hull STEP can be 150 MB). Above the limit the Parts tab says so.

Sign-off: `sign_off { task, name }` → `SignOffView { name, time_ms, statement: "usable as a
starting model" } | null` (an empty name withdraws it). Allowed only when every part is reviewed
(accepted or marked); a part opened again ends it. `TaskView.sign_off` shows it as "Signed off by
<name>, <date>: usable as a starting model". It records a person's judgement in the app config
folder (`signoffs.json`); the run and every file stay drafts and `engineering_approved` stays false.

The part list copy is tab-separated; a text cell that starts with =, +, -, @, a tab or a carriage
return gets a leading single quote (as `exports/csv_safety.py`); numbers stay numbers.
