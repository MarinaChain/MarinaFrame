# Desktop demo kit

A kit lets a person install the MarinaFrame desktop app on their own Mac (Apple Silicon) and open
the demo runs (R/V Gunnerus, the Survey launch concept preview, optionally DTMB 5415 and
Series 60) as they look on https://frame.marinachain.io. They start new runs with their own
Claude Code login (`claude` CLI, Settings > AI drafting on).

Kit output (not in git; R/V Gunnerus drawings are licensed): `work/desktop-kit/`.

## What makes a copied run open like the web demo

| Need | Where it is kept | Code |
|---|---|---|
| The run's whole drawing set (hover a part, see its sheet) | `sources/sheets.json` and `sources/sheets/*.png` in the run | `scripts/add_run_sheets.py` writes them; `app/core/src/sources.rs` (`ADDED_SHEETS_FILE`) lists them; `parts.rs` `place_on_added_sheets` gives the part records the page size and the part box |
| No "A different build of MarinaFrame made this run" | `config.binary_sha256` in `state.json` is the SHA-256 of the shipped app executable | `MarinaFrame make-run` (app/src-tauri/src/main.rs, `actions::run_deterministic_now`) runs the app's own deterministic draft run without a window. The check itself is unchanged. |
| Part reviews | `review/part_reviews.json` in the run | `parts.rs`. Reviews kept by earlier versions in the app config (`part_reviews.json`, keyed by the run folder path) are still read; the next review moves them into the run and removes the config entry. |
| First view (whole vessel, section lines off, see-through) and the note line | `presentation.json` in the run | `app/core/src/presentation.rs`; UI `js/presentation.js`. A concept-preview run (`config.policy` "concept_preview") always shows its concept label. The web demo's manifest still wins on the public site. |

### Sheets added to a run

```sh
.venv/bin/python scripts/add_run_sheets.py --task RUN --slug gunnerus --sheets-root work/sources/gunnerus
```

The list (names, SHA-256, roles, `dxf_boxes_view`) is the `extra_sheets` entry of
`scripts/web_demo_runs.json`. A sheet with another SHA-256 is refused. The run's own records
(state, events, `whole_vessel/execution.json`) are not changed. The web exporter skips a sheet
that the run already holds.

### `presentation.json`

```json
{"schema": "marinaframe.presentation.v1", "whole_vessel_first": true, "section_lines": false,
 "see_through": false, "credit": "R/V Gunnerus drawings: NTNU ...", "note": null}
```

### `make-run`

```sh
MarinaFrame.app/Contents/MacOS/marinaframe-app make-run --runs-folder DIR --spec FILE
```

Same configuration as "Start a run" with AI drafting off (deterministic draft, no model calls),
with the bundled worker Python. It prints the task folder and its status. A run made this way
has the SHA-256 of that exact executable, so only that app build opens it without the notice.

## Making the kit

1. Commit, then build: `scripts/build_worker_runtime.sh` and `(cd app && npm run build)`.
2. Copy `MarinaFrame.app` out of the DMG (`hdiutil attach -nobrowse -readonly`) to a scratch folder.
3. For each spec run (Gunnerus, DTMB 5415, Series 60): `make-run` with a copy of the input spec
   (Gunnerus: `vessel_id` "R/V Gunnerus"). Gunnerus then gets the whole-vessel outputs of the web
   demo run copied in (`whole_vessel/`, `whole-vessel-draft.glb(.json)`, `tanks.npz`,
   `tank_tables/`, `structure/`), the same files RUNS.md step 7 copied, made from the same
   r0001 hull; then `add_run_sheets.py` and `presentation.json`.
4. The concept run is copied as made by `benchmarks/concept_launch` (it records no controller
   binary, so it has no notice), plus `presentation.json` (whole vessel, see-through).
5. Reviews: written into each run's `review/part_reviews.json` from the web demo config.
6. `MarinaFrame-demo-runs.zip`, `install-runs.command`, `README.md` (for a person's AI agent),
   `GUIDE.md`/`GUIDE.pdf`, then `MarinaFrame-demo-kit.zip` with all of them.

## Install rules for the kit

No `sudo`, no removing the quarantine attribute, no Gatekeeper or other security setting
changes. The app is not signed by a developer ID: the person opens it the first time with
right-click > Open. `install-runs.command` only copies run folders into
`~/Library/Application Support/io.marinachain.marinaframe/runs/` and never overwrites a run
folder that is already there.
