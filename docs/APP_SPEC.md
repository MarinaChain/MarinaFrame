# MarinaFrame desktop app: specification v1

Status: approved direction (user, 2026-11-07): Tauri 2, a proper desktop app, Mac first,
Windows next. This file is the contract between the Rust backend (`app/src-tauri/`) and the UI
(`app/ui/`). Change it only together with both sides.

## Goals

A person who is not a naval architect can watch a reconstruction run and understand it:
what drawing went in, which line the system chose on each section and why, what 3D shape came
out, how it was checked, and what the model (DeepSeek) saw and answered.

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
   name, status chip, time. A "New run" button (pick a spec file, policy deterministic).
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
| `read_artifact` | `{ task, path }` | `{ mime, base64 }` (`path` is relative to the task folder, with `/` separators, never absolute, and must stay inside it; images and STL only; the STL is in the unit of the CAD export, so the UI scales it to `length_m`) |
| `start_run` | `{ spec_path: string }` | `{ task: string }` |
| `cancel_task` | `{ task }` | `{ ok: true }` |
| `resume_task` | `{ task }` | `{ ok: true }` |
| `choose_line` | `{ task, section_id, candidate_id }` | `{ ok: true }` (operator intervention, then rebuild/validate via the controller) |
| `get_settings` / `set_settings` | `{}` / `Settings` | `Settings` |
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
  evidence: object               // raw hashes and contract, shown only in Evidence tab
}
SectionView { id: string, x_m: number, roi_px: [x0,y0,x1,y1],
              state: "chosen"|"guessed"|"declined"|"not_read",
              reason: string,                       // plain language; for "guessed" the guess reason
              guess: GuessView | null,              // set when state is "guessed"
              candidates: CandidateView[] }
GuessView { id: string,                             // guess_id
            kind: "best_candidate"|"bridged_gap"|"dropped_end",
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
