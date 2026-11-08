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
| Worker Python (CadQuery 2.7, OCP 7.8, PyMuPDF, OpenCV, the `vessel_reconstruction` package) | `Settings.worker_python`. The default is `<repo>/.venv/bin/python`, where `<repo>` is **the build machine's checkout path, baked in at compile time** (`development_checkout()` uses `CARGO_MANIFEST_DIR`). | No default: the welcome check says the CAD worker is missing and the person must choose a Python. |
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

1. **Stop baking the build path.** Replace the compile-time `development_checkout()` default with:
   the `MARINAFRAME_REPO` environment variable, else the bundled worker (step 3), else none.
   Check: a release build moved to another folder shows "choose a Python" and nothing else
   from the build machine (dataset list empty).
2. **Leave the mock out of the release UI.** Build step that copies `app/ui` without `mock/`
   into a staging `frontendDist` (or a `beforeBuildCommand`). Check: the bundle has no
   `fixtures.json`; the browser preview still works from `app/ui`.
3. **Ship the worker Python.** Options, in the order recommended:
   - a. A relocatable CPython 3.12 (python-build-standalone) in `Contents/Resources/worker/`
     with a **macOS arm64 lock with hashes** (the current locks are Linux only) and the
     `vessel_reconstruction` wheel. About 1 GB in the bundle; DMG perhaps 350 to 450 MB.
   - b. The same runtime downloaded on first start into Application Support (small DMG; needs a
     hosted, hash-checked archive and an offline answer).
   - c. Keep today's external venv and the setup check (developer builds only).
   Check: on a Mac without the repo, intake, a sample run and an export complete.
4. **Licence decision before distribution.** PyMuPDF is AGPL-3.0 or commercial
   (`docs/DEPENDENCIES_AND_RIGHTS.md`); bundling it is distribution. The VTK scoped exclusion
   also applies. Owner decision needed before step 3a/3b ships outside the company.
5. **Signing and notarization** (owner decision; not done here). Without a Developer ID, a
   downloaded app is blocked by Gatekeeper; testers must use Open from the context menu or
   remove the quarantine attribute. Notarization also needs the hardened runtime and
   entitlements for the Python child processes.
6. **Intel Macs.** A universal binary needs the `x86_64-apple-darwin` target and an x86_64 worker
   runtime; defer unless a customer needs it.

## 4. How to repeat the build

```
cd app
npx tauri build --bundles app,dmg
du -sh ../target/release/bundle/macos/MarinaFrame.app ../target/release/bundle/dmg/*.dmg
codesign -dv ../target/release/bundle/macos/MarinaFrame.app
```

Before building, make sure `app/ui/mock/files/` has no git-ignored local data (for example a
whole-vessel GLB): it would be embedded in the app.
