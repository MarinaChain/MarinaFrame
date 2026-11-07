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
| `read_artifact` | `{ task, path }` | `{ mime, base64 }` (path must be inside the task; images and STL only) |
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
TaskSummary { task: string (absolute path), name: string, status: Status,
              policy: "deterministic"|"live", updated_ms: number, sections: number }
Status = "running" | "needs_review" | "declined" | "failed" | "cancelled" | "paused" | "blocked"
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
  evidence: object               // raw hashes and contract, shown only in Evidence tab
}
SectionView { id: string, x_m: number, roi_px: [x0,y0,x1,y1],
              state: "chosen"|"declined"|"not_read",
              reason: string,                       // plain language
              candidates: CandidateView[] }
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
