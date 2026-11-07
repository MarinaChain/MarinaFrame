# Rust task review

MarinaFrame's Rust task controller owns state transitions, source capture, bounded native operations, typed interventions, cancellation and durable events. The optional Python review interface displays that evidence and submits explicitly bound operator decisions to the configured Rust executable. It never imports or invokes the Python `Harness`.

The interface supports a self-contained HTML evidence export and a local operator session. Both show the captured drawing beside a render from the actual exported and independently reimported STEP, plus source overlays, section comparisons, retained contour alternatives, event history and the current validation contract. Clicking an image opens its full displayed resolution. Each candidate image is labelled as current or preserved from an older revision; freshness requires both generation and revision to match. A previously valid candidate remains visible while the new selection is awaiting its own render.

Engineering approval is always false. The interface records a declared actor (`human_operator` or `assistant_operator`); it does not authenticate professional qualifications or certify the meaning of a contour. A successful trace and CAD audit establishes the recorded numerical checks against the selected source pixels, not that the vessel interpretation or resulting design is correct.

## Export an offline review

From the repository root, using the Python environment documented by the main project:

```sh
PYTHONPATH=src python -m vessel_reconstruction.rust_review export \
  --task /absolute/path/to/rust-task \
  --controller /absolute/path/to/marinaframe \
  --out /absolute/path/to/review.html
```

The destination must be a new file. The exporter runs Rust `verify` before and after reading the evidence, compares the event head and domain checkpoint, and checks the image bytes against their recorded SHA-256 hashes and sizes. It refuses modified, incomplete or unreconciled task evidence. The export embeds the images; it has no external scripts, fonts or network assets.

An offline export can select retained alternatives and download a `marinaframe.intervention.v1` JSON file. The download contains the task ID, expected event head, expected generation, expected revision, and typed decision. Apply it through Rust:

```sh
/absolute/path/to/marinaframe step \
  --task /absolute/path/to/rust-task \
  --intervention /absolute/path/to/marinaframe-intervention.json \
  --actor human_operator \
  --note 'Describe the source evidence supporting this correction.'
```

Rust rechecks the binding while holding the task lock. A decision downloaded before another task change is stale and is refused. A source selection invalidates the current candidate's readiness; rebuild, render and validate the new selection before further review.

## Open the local operator interface

```sh
PYTHONPATH=src python -m vessel_reconstruction.rust_review serve \
  --task /absolute/path/to/rust-task \
  --controller /absolute/path/to/marinaframe \
  --port 8767 \
  --allow-actions \
  --actor human_operator \
  --session-file /private/new-review-session.json
```

The server binds only to `127.0.0.1`. The new session file is created with mode `0600` and contains a one-time browser link, valid for ten minutes. Open that link locally; the browser removes its token from the address bar after bootstrap. Without `--session-file`, the one-time link is printed to the terminal. The resulting cookie is HttpOnly and SameSite Strict, and the session expires after one hour. Restart the server to create a new session.

Without `--allow-actions`, the local page is read-only. With it, a deterministic task supports inspecting more stations, applying retained contour selections, rebuilding, rendering one of four STEP views, validation, cancellation, and explicitly resuming the deterministic workflow. An operator note is required for state-changing work other than requesting cancellation. Cancellation preserves existing work and receipts; clearing a cancellation request requires the explicit resume checkbox. A live provider task remains read-only in this interface, even when `--allow-actions` was supplied. Live continuation uses the configured Rust CLI with an established provider-transfer basis and receipt tracking. The authorized November 2026 campaign has no aggregate request, token or spending cap.

Each requested operation runs through the fixed configured controller executable with an argument list, never a shell. HTTP clients cannot supply a controller, filesystem path, arbitrary operation or command. Only one work operation runs at a time; cancellation remains available while it runs. The browser reports Rust refusal codes and asks the operator to refresh evidence before trying another edit.

### Local request boundary

Host must exactly match the loopback address and port. Mutating requests require that exact Origin, an authenticated session and the session's CSRF token. The bootstrap is single-use. JSON parsing rejects duplicate keys and is bounded by body size, nesting and node count. Requests also have connection and read limits. Unknown action fields and unsupported tools are refused. The UI passes the full intervention binding to Rust, which independently validates the decision and captured candidate IDs.

The page uses escaped text, a nonce-protected script, a restrictive content security policy, no-store responses, no-referrer policy, frame denial and same-origin resource policy. Downloaded static reviews have no session credential. Browser credentials are kept out of retained QA artifacts. Credential comparison first requires ASCII, including controlled rejection of JSON strings containing lone Unicode surrogates.

Resume passes all four expected binding fields through `--expected-head-sha256`, `--expected-generation-id`, `--expected-revision-id` and `--expected-task-id`. Rust checks them under its exclusive task lock before clearing cancellation or performing any work. This closes the interval between the Python display check and the Rust process acquiring the lock. The direct CLI can still resume without these optional fields, but the browser never omits them.

In the tested controller, the five typed UI interventions retain the exact declared actor and note in Rust events. Resume and cancellation acknowledgment use the controller's generic `operator` actor, and the resume note is not preserved in that event. The browser QA record declares `assistant_operator` for the whole trial. This distinction must not be read as a human or professional signature.

The interface is a local workstation tool, not a multi-user identity service. A same-user process with filesystem access can already invoke the trusted CLI and inspect task evidence. Run it on an ordinary trusted local machine; do not expose the listener through a public reverse proxy.

## Evidence and limits

Review loading is deliberately bounded to 1,000 events, 96 MiB of event JSON, at most 72 embedded images, 8 MiB per image and 32 MiB of image payload. The page reports the number embedded versus recorded. These are display bounds, not permission to skip omitted source evidence. Rendering is static orthographic STEP evidence rather than an interactive mesh editor. Calibration and contour identity remain recorded assumptions; this UI chooses among the candidates the source inspector actually captured.

The first browser run against the development fixtures verified desktop and phone layouts, image completeness, a full-resolution image dialog, disabled static mutation controls, a bound intervention download and a preserved live-provider failure. There were no page errors, external network requests or horizontal overflow at 390 px. Screenshots were then opened and inspected. The live fixture visibly retains `provider_failed` and `summary_limit`; it is not represented as a successful live completion.

## Completed native browser trial

The actual operator trial used a frozen Rust binary with SHA-256 `e1338e7d185915e9d17b183e1769708710530e71bcd50fb8e3256bb5ac69e1ef`, 29 frozen Python modules, the pinned native CAD environment, and the existing three-station procedural smoke source. The trial is a control and evidence-handling test; it is not an authentic-vessel accuracy benchmark. It made **zero provider requests**.

| Browser action | Observed result |
| --- | --- |
| Open one-time session | Real authenticated page loaded; replay of the bootstrap returned 403; cookie was HttpOnly and SameSite Strict. |
| Choose retained alternative at `s0` | Rust recorded an `assistant_operator` intervention, advanced `r0001` to `r0002`, changed generation and cleared current readiness. The old candidate remained labelled as preserved. |
| Replay decision from the previous view | HTTP 409 `stale_or_foreign_intervention`; the current event head did not change. |
| Rebuild and render | A real second native build completed. The displayed STEP reimport changed; beam increased from 2.483333 m to 3.000000 m. |
| Validate the alternative | Worker execution, artifact integrity, CAD validity and trace fidelity passed. The maximum sampled section distance was 0.896516 mm against the 1.1 mm threshold. This does not certify that the alternate contour is the intended hull. |
| Restore the prior contour | Rust created `r0003`. Its generation matched the earlier source choice, while its revision remained distinct; previous renders and validation remained older evidence. |
| Request cancellation, then explicitly clear and resume | The cancellation marker and notice appeared. The bound resume cleared the marker, built and checked the new revision, and ended at `awaiting_human_review`. |

The final task contains **3 native builds, 5 explicit operator interventions, 17 domain operations, 12 deterministic decisions and 80 events**. Rust verified **344 artifact references**, reported no pending reconciliation, and retained `engineering_approved: false`. The final head is `c8403630c21efced0c46abed505f40669a1419079dac446d3c708331521c9622`. A complete copy of the task also verified with the same head: 357 files and 9,711,393 bytes. One earlier unchanged setup task contributed one additional native build, so the entire UI workstream performed four builds across two fresh tasks.

The final self-contained `native-operator-reviewed.html` embeds 18 actual recorded images, including nine preserved older candidate images. Its browser test confirmed all images loaded, all mutation controls were disabled, and no page errors or external requests occurred. Eleven recorded UI screenshots were subsequently opened for pixel inspection; the viewing ledger identifies the files and observations.

The 17 focused boundary tests passed in 5.64 seconds. A separate author reviewed the module and independently reran all 17 tests in 5.65 seconds. That review identified two issues before completion: resume needed the atomic Rust binding described above, and malformed Unicode credentials needed a controlled rejection. Both were corrected and covered by regression tests; the independent reviewer reported no remaining blocking finding within this boundary review.

### Preserved unsuccessful attempts

A listener connection failure before authentication is preserved; no operation or provider call happened in that attempt. Browser and local server were then co-launched because the managed execution context did not expose the listener across separate command sessions. The first co-launched QA script incorrectly waited for a JSON script element to become visible instead of attached; authentication succeeded and the task remained unchanged. A later QA polling call raced the successful page reload after the second native build. The native build had completed, so the script was corrected to poll independently of page navigation and continued from that same verified task without repeating the build. These are retained setup/QA failures, not erased or reported as uninterrupted passes.

The test development log also retains the initial embedded-JSON escaping regression. It was corrected before authenticated mutation testing. All failure records, browser scripts, receipts, screenshots, hashes and the complete final task are under `artifacts/v04/review/`. Independent review evidence is under `artifacts/v04/independent-rust-review/`.

Historical task evidence can be inspected with a compatible verifying reader. Mutating a task requires its exact captured controller and worker identity; the final release dependency build may have a different binary hash than this frozen QA runtime. Start a new task with the installed release runtime rather than changing an old task's identity fields.
