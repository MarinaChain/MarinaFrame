# Desktop app packaging: release build findings and plan (2026-11-09)

Scope: the Tauri 2 desktop app in `app/src-tauri` (with `app/core`), macOS only. Signing:
ad hoc only. Nothing in `rust-control/` or the Python workers was changed for this note.

## 1. Release build result

Command (from `app/`): `npx tauri build --bundles app,dmg` (Tauri CLI 2.12.4, from
`app/package.json`).

| Item | Result |
|---|---|
| Build | Passes. Release profile compiled in about 1 minute on an incremental target. No warnings. |
| `MarinaFrame.app` | 22 MB (`target/release/bundle/macos/`). One arm64 binary (22 MB) plus `Resources/icon.icns` (the app icon from `src-tauri/icons`). |
| `MarinaFrame_0.5.0_aarch64.dmg` | 8.8 MB (`target/release/bundle/dmg/`). |
| Signature | `adhoc,linker-signed`, `Info.plist=not bound`. No Developer ID, not notarized. |
| Architecture | arm64 only (`aarch64-apple-darwin`); no x86_64 macOS target is installed. |
| Start | The bundled app opens a window and keeps running; it was closed after 5 s. |

The UI (`app/ui`, `frontendDist`) is embedded in the binary. It includes `app/ui/mock/` (synthetic
fixtures for the browser preview, about 0.3 MB). The mock code runs only without `__TAURI__`, so
it is dead weight in the app, not a behaviour risk. Before this build a git-ignored local copy of a
licensed whole-vessel GLB was deleted from `app/ui/mock/files/`, because anything in that folder is
embedded in the bundle.

## 2. What the bundled app still needs from the repository at run time

| Need | How the app finds it now | On a clean Mac |
|---|---|---|
| Worker Python (CadQuery 2.7, OCP 7.8, PyMuPDF, the `vessel_reconstruction` package; OpenCV was removed 2026-11-09) | `Settings.worker_python`. The default is `<repo>/.venv/bin/python`, where `<repo>` is **the build machine's checkout path, baked in at compile time** (`development_checkout()` uses `CARGO_MANIFEST_DIR`). | No default: the welcome check says the CAD worker is missing and the person must choose a Python. |
| Worker source (`src/vessel_reconstruction`) | The repo `.venv` has an editable install (`__editable__.vessel_reconstruction-0.4.0.pth`) that points at the main checkout's `src/`. `MARINAFRAME_WORKER_SOURCE` can override it (`PYTHONPATH`). | Missing unless a venv with the package is installed. |
| Size of that Python layer | `.venv` is 1.1 GB; the largest parts are `vtkmodules` 328 MB, `OCP` 253 MB, `casadi` 129 MB, `cv2` 120 MB, `scipy` 71 MB, `pymupdf` 54 MB. | — |
| Model keys | Environment `OPENCODE_API_KEY*` or `~/.config/marinaframe/opencode-go-keys.txt` (mode 600). | Works when the person adds the key file. |
| Runs folder | App data dir (`~/Library/Application Support/io.marinachain.marinaframe/runs`) or Settings. | Works. |
| Dataset list (developer) | `<repo>/work/sources` (compile-time path). | Empty list; harmless. |
| Provider worker | The app's own executable (`<exe> provider-worker …`). | Works: it is inside the bundle. |
| Sample vessel | Embedded (`include_bytes!` in `app/core/src/sample.rs`). | Works, but a run still needs the worker Python. |
| Notifications | `/usr/bin/osascript`. | Works unsigned. |

So the release `.app` is a complete UI and controller, but every run, intake and export needs an
external Python environment of about 1 GB with the worker package.

## 3. Packaging plan (short)

Each step is independent and ends with a check. Resume at the first step whose check fails.

Status: steps 1 to 3 are done (UI rounds 68 and 69; step 3 on 2026-11-09, local build only).
Resume at step 4 (an owner decision); nothing is distributed until steps 4 and 5 are done.

1. **Done: stop baking the build path.** `app/core/src/worker_python.rs` finds the worker Python
   at run time in this order: `MARINAFRAME_WORKER_PYTHON`, the Settings value, the runtime inside
   the app bundle (`MarinaFrame.app/Contents/Resources/worker/bin/python3`), then the repository
   `.venv` (only when `MARINAFRAME_REPO` names a checkout, or in a debug build). Else the setup
   check asks, and the person's choice is saved to Settings. No folder merely beside the app is
   searched: anyone who can write it could plant a Python that the app would run without asking
   (security review of b33f637). The repository root is `MARINAFRAME_REPO` at run time; only
   debug builds fall back to the compile folder. A release binary holds no build path.
2. **Done: leave the mock out of the release UI, by default.** `src-tauri/build.rs` runs
   `src-tauri/stage_ui.rs` on every build (`cargo build`, `tauri build`, CI): it copies only
   `index.html`, `styles.css`, `js/`, `vendor/` and `assets/` from `ui/` into `ui-release/` (not
   tracked; unchanged files are not rewritten; stale files are removed) and fails the build on
   any other file type (for example .glb, .step, .tif, .png, .pdf), a link, or a file over 1 MiB.
   The base `tauri.conf.json` embeds `ui-release/`. Only `npm run dev`
   (`tauri dev --config src-tauri/tauri.dev.conf.json`) serves `ui/` with the mock. Tests: the
   `stage_ui` tests in `cargo test -p marinaframe-app`.
3. **Done (local build only): ship the worker Python inside the bundle (option a).**
   `scripts/build_worker_runtime.sh` builds `build/worker-runtime/worker/` (git-ignored):
   CPython 3.12.15 from python-build-standalone release 20261009 (stripped install-only archive,
   SHA-256 pinned in the script and checked), the 45 wheels of
   `requirements-worker-macos-arm64-py312.lock` (the versions of the Linux lock; macOS arm64
   wheels with tags up to macosx_13_0; `--require-hashes`, binary only) and a
   `vessel_reconstruction` wheel built from the committed source at HEAD (not editable). The
   script removes pip, the console scripts and the headers, keeps one interpreter file
   (`bin/python3`, no symbolic links), deletes `direct_url.json` (it held the build path) and
   precompiles all bytecode with `--invalidation-mode unchecked-hash`, so that Python never
   writes `__pycache__` into the bundle (a write would break the signature).
   `MARINAFRAME_RUNTIME.json` in the runtime records the archive, lock and wheel hashes and the
   commit. `build_worker_runtime.sh lock` re-hashes the locks from their pins; `test-env` puts
   pytest, trimesh and jsonschema (`requirements-worker-tools-macos-arm64-py312.lock`) in
   `build/worker-runtime/test-site`, beside the runtime, never in it.
   `npm run build` now merges `src-tauri/tauri.worker.conf.json`, which copies the runtime to
   `Contents/Resources/worker/`; `npm run build:no-worker` builds the 22 MB app without it.
   Plain `cargo build` and CI do not need the runtime.

   | Item | Size |
   |---|---|
   | Runtime (`build/worker-runtime/worker`) | 1.2 GB, 13,799 files, 903 `.so`/`.dylib` (VTK 329 MB, OCP 254 MB, CasADi 129 MB, OpenCV 120 MB, SciPy 120 MB; OpenCV since removed) |
   | `MarinaFrame.app` with the runtime | 1.22 GiB |
   | `MarinaFrame_0.5.0_aarch64.dmg` | 360 MiB |

   Decision: **inside the bundle.** 360 MiB is a normal download for a CAD desktop app, the app
   works offline from the first start, and the bundle signature covers the runtime (the
   resolver trusts `Contents/Resources` for that reason). A first-start download (option b)
   needs a hosted, versioned, hash-checked archive, a writable folder that the app must then
   protect against planted code, and an answer for no network. Reconsider it only if the DMG
   size becomes a problem. Signing (step 5): each of the 903 native libraries and
   `bin/python3` must be signed with the Developer ID and the hardened runtime, inside out,
   before the app itself; test notarization before promising it.

   Checks done (2026-11-09) in a clean environment (`env -i`, no `MARINAFRAME_REPO`, no
   `--worker-source`, no repo `.venv` on `PATH`); the package was imported from the runtime's
   site-packages (pytest with `-o pythonpath=`):
   - `pytest -m "not cad"`: 942 passed (`tests/test_rules.py` left out, see below).
   - `pytest -m cad`: 27 passed (all real-CAD tests, including `tests/test_ship_cad.py`).
   - Deterministic run of the procedural sample (`app/core/sample`) with
     `target/release/marinaframe run --policy deterministic`, first with the built runtime and
     then with the copy inside `MarinaFrame.app`: `awaiting_human_review`, `verify` valid. Then
     `python -m vessel_reconstruction.exports --revision r1` wrote STEP, STL, offsets,
     hydrostatics, the PDF report and the package. No file in the bundle changed.
   - The setup check, computed by the app core from an executable inside the built bundle with
     an empty config folder: "The CAD worker Python is found inside the app." (the same
     executable outside the bundle reports no Python).

   Known limits: `vessel_reconstruction.rules` and `structure.midship_eval` read the repository
   `rules/` folder through `Path(__file__).parents[3]`, so they do not work from an installed
   wheel. No run, intake or export path imports them; `tests/test_rules.py` needs a checkout.
   On a fresh checkout, stage `app/ui-release` (`cargo check -p marinaframe-app`) before the
   first `npm run build`: the Tauri CLI looks for `frontendDist` before `build.rs` runs. Intake
   was not run through the app UI (no screen access in this session).
4. **Licences (done 2026-11-09).** PyMuPDF: commercial licence bought. OpenCV removed from
   the runtime: every macOS arm64 wheel vendors GPL codecs, and the worker's three OpenCV
   operations now use SciPy (`raster_morphology.py`) with identical results (random images
   and the 24 `work/factory-3view` drawings). VTK stays (OCP links it); BSD-3 with permissive
   or permissive-option third-party libraries. NLopt's `_nlopt.so` is LGPL-2.1+ despite its
   MIT metadata. Details and the handling of each LGPL item:
   `docs/DEPENDENCIES_AND_RIGHTS.md` ("Worker runtime licence review");
   `docs/WORKER_RUNTIME_LICENCES.md` lists every bundled package. Remaining: write the
   third-party notices file for the app before the first distribution.

   Rebuilt runtime without OpenCV (2026-11-09): 1.1 GB, 809 `.so`/`.dylib`, 44 wheels plus the
   package; the build fails if `cv2` is importable. In the same clean environment:
   `pytest -m "not cad"` (without `tests/test_rules.py`): 921 passed, 37 skipped (the OpenCV
   comparison tests, `PlanRaster` tests and benchmark-factory modules skip without OpenCV);
   `pytest -m cad`: 26 passed (the 27th lives in a skipped factory benchmark module). The
   release-app run was not repeated.
5. **Signing and notarization** (owner decision; not done here). Without a Developer ID, a
   downloaded app is blocked by Gatekeeper; testers must use Open from the context menu or
   remove the quarantine attribute. Notarization also needs the hardened runtime and
   entitlements for the Python child processes.
6. **Intel Macs.** A universal binary needs the `x86_64-apple-darwin` target and an x86_64 worker
   runtime; defer unless a customer needs it.

## 4. How to repeat the build

```
scripts/build_worker_runtime.sh      # macOS arm64, about 2 minutes: build/worker-runtime/worker
build/worker-runtime/worker/bin/python3 -I scripts/worker_runtime_licences.py \
    --out docs/WORKER_RUNTIME_LICENCES.md
cargo check -p marinaframe-app       # stages app/ui-release on a fresh checkout
cd app
npm run build -- --bundles app,dmg   # with the runtime; npm run build:no-worker leaves it out
du -sh ../target/release/bundle/macos/MarinaFrame.app ../target/release/bundle/dmg/*.dmg
codesign -dv ../target/release/bundle/macos/MarinaFrame.app
```

Every build embeds `ui-release/` only, so local data in `app/ui/mock/files/` stays out; a
forbidden file anywhere in the staged entries stops the build.
