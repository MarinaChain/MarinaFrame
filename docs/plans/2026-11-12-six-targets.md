# Six-target CI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Measure native Rust builds/tests and Python quick tests on six hosted targets without changing required PR CI.

**Architecture:** A separate nightly/manual workflow uses six native runners and fail-fast disabled. Build, Rust quick tests, and Python quick tests have independent outcomes. An unavailable pinned Python stack produces a visible unsupported step, not an apparent test pass. No application port or release packaging is claimed.

**Tech Stack:** GitHub Actions, Rust 1.99.1, CPython 3.12.10, pip, pytest, Tauri 2.

## Research (2026-11-12, before implementation)

Read `.github/workflows/ci.yml`, `ci-watch.yml`, `docs/CI_CHANGES.md`, all five `requirements-*.lock` files, `requirements-lock.txt`, `scripts/build_worker_runtime.sh`, and `docs/plans/2026-11-09-packaging.md`. The existing Linux aggregate and required macOS job must stay unchanged. The runtime builder explicitly accepts only macOS arm64. The legacy version-only lock has older/different pins (including PyMuPDF 1.26.6 versus 1.26.7); it is not the source of new portability pins.

### Native targets

| Target | Hosted label selected | Rust target | Python quick tier |
|---|---|---|---|
| Windows x86_64 | windows-2022 | x86_64-pc-windows-msvc | Available wheels; run the full quick selection |
| Windows arm64 | windows-11-arm | aarch64-pc-windows-msvc | Unsupported pinned stack |
| macOS arm64 | macos-15 | aarch64-apple-darwin | Worker + tools hash locks; no OpenCV by licence policy |
| macOS x86_64 | macos-15-intel | x86_64-apple-darwin | Unsupported pinned NLopt wheel |
| Linux x86_64 | ubuntu-24.04 | x86_64-unknown-linux-gnu | Full hash-locked quick tier |
| Linux arm64 | ubuntu-24.04-arm | aarch64-unknown-linux-gnu | Unsupported pinned OCP/VTK wheels |

Runner access can depend on repository visibility, preview status, and account entitlement. Failure to allocate a runner is infrastructure failure, not a failed source build. Confirm architecture in each job before compiling.

### Wheel evidence

Public PyPI version JSON returned HTTP 200 for every Linux-lock pin. Wheel compatibility was checked for non-yanked CPython 3.12/abi3 and pure Python wheels, not inferred from the pure-Python CadQuery package. The main Linux lock is authoritative for the full test stack; the macOS runtime/tools locks deliberately omit OpenCV.

| Dependency pin | Linux x64 | Linux arm64 | Mac arm64 | Mac x64 | Win x64 | Win arm64 |
|---|---|---|---|---|---|---|
| cadquery 2.7.0 (pure Python) | yes | yes* | yes | yes* | yes | yes* |
| cadquery-ocp 7.8.1.1.post1 | yes | **no** | yes | yes | yes | **no** |
| casadi 3.7.2 | yes | yes | yes | yes | yes | **no** |
| vtk 9.3.1 | yes | **no** | yes | yes | yes | **no** |
| numpy 2.3.5 | yes | yes | yes | yes | yes | yes |
| scipy 1.17.0 | yes | yes | yes | yes | yes | yes |
| PyMuPDF 1.26.7 | yes | yes | yes | yes | yes | **no** |
| nlopt 2.11.0 | yes | yes | yes | **no** | yes | **no** |
| opencv-python-headless 4.14.0.94 | yes | yes | yes | yes | yes | **no** |

`*` CadQuery's own wheel is present, but its native dependency chain is incomplete. All other checked full-lock pins have compatible wheels for these six targets. macOS rhino3dm 8.35.0 universal2 wheels require macOS 14/15: use macOS 15, not the runtime script's nominal macOS 13 wheel floor.

Evidence endpoints (substitute each exact pin above):
- https://pypi.org/pypi/cadquery/2.7.0/json
- https://pypi.org/pypi/cadquery-ocp/7.8.1.1.post1/json
- https://pypi.org/pypi/casadi/3.7.2/json
- https://pypi.org/pypi/vtk/9.3.1/json
- https://pypi.org/pypi/numpy/2.3.5/json
- https://pypi.org/pypi/scipy/1.17.0/json
- https://pypi.org/pypi/PyMuPDF/1.26.7/json
- https://pypi.org/pypi/nlopt/2.11.0/json
- https://pypi.org/pypi/rhino3dm/8.35.0/json

### Gaps and proposed solutions

1. **Linux arm64 OCP/VTK:** evaluate conda-forge as a separately solved and locked environment. A differently numbered conda OCP build is not proof of the exact pip pin. Otherwise build OCCT/OCP and VTK from source in a dedicated release pipeline. Until then report Python unsupported.
2. **Windows arm64 native CAD stack:** conda/source availability must be established for the whole graph, not just NumPy/SciPy. Build OCCT/OCP, VTK, CasADi, NLopt and MuPDF with MSVC arm64 if no coherent conda solution exists. OpenCV is test-only and absent from the shipped worker by policy. Document native Python unsupported; x64 emulation is a different target and is not substituted.
3. **macOS Intel NLopt:** source-build NLopt 2.11.0 or create a conda-forge lock for the exact supported stack. Do not silently change the pin to make CI green.
4. **Locks:** Linux hashes are Linux-x64-specific; macOS worker/tools hashes are arm64-specific. Windows x64 uses exact pins extracted from the full Linux and data locks, with platform-native wheels and no source builds. This is a version-pinned portability probe, not a release lock. Create target-specific hash locks before shipping. macOS arm64 installs the existing hash-locked runtime/tools pair (jsonschema included), deliberately without OpenCV.
5. **Rust Windows:** current source imports `std::os::unix` unconditionally in worker, store, supervision, util, and app model-key handling; tests also use Unix symlinks/permissions. Run native build/tests and retain errors. A separate port must design Windows process-tree cleanup, private file ACLs, and sandbox policy; do not merely remove security controls.
6. **Tauri:** native compilation needs Linux GTK/WebKit/AppIndicator development libraries, MSVC/WebView2 on Windows, and Xcode tools on macOS. This workflow compiles the desktop shell but does not package/sign. App/DMG need separate architecture runtimes (or a universal Rust binary plus both native Python graphs); Windows MSI/NSIS and Linux deb/rpm/AppImage need native packaging and platform resource paths. The current runtime builder and bundled interpreter resolver are macOS-specific. Signing/notarization, Windows signing, third-party notices and clean-machine runtime tests remain release work.
7. **Workflow registration:** a new workflow may need to exist on the default branch before GitHub accepts manual dispatch. Try dispatch on this branch; if refused, record it. Do not merge or change the default branch to bypass this rule. Scheduled runs start only after the workflow reaches the default branch.
8. **Infrastructure:** DNS/download/runner provisioning errors must be reported with their actual stage, never classified as code failures or absent packages.

### Runner, conda-forge, Rust and bundle references

- GitHub's current runner table lists all six selected native labels, including `windows-2022`, `windows-11-arm`, `macos-15-intel`, `macos-15`, and both Ubuntu labels: https://docs.github.com/en/actions/reference/runners/github-hosted-runners . These are labels, not a guarantee of immediate capacity.
- Conda-forge package metadata returned HTTP 200 at `https://api.anaconda.org/package/conda-forge/{ocp,casadi,vtk,nlopt,pymupdf,cadquery}`. Linux-aarch64 has Python 3.12 OCP, VTK, CasADi and NLopt builds. Examples: `ocp-7.8.1.1-py312h2fdf706_0.conda`, `vtk-9.3.1-qt_py312h1234567_200.conda`. OCP requires VTK >=9.3.1,<9.4 and vtk-base >=9.3.1,<9.3.2. CadQuery 2.7.0 is noarch. PyMuPDF has no linux-aarch64 conda build in the checked metadata, but its PyPI wheel is available. None of these six conda packages has win-arm64 files. macOS Intel has `nlopt-2.11.0-np2py312h0d41952_2.conda`. A solver check and complete lock are still required before selecting a mixed or conda-only environment.
- Rust supports all six listed native triples with host tools. Current tier classification is Tier 1 with host tools for five, Tier 2 with host tools for Intel macOS: https://doc.rust-lang.org/rustc/platform-support.html . Native tests, not cross-compilation alone, are the acceptance check.
- Tauri Windows arm64 uses the ARM C++ tools and target; NSIS can package the native ARM application although the installer executable itself runs through x86 emulation. MSI creation needs Windows: https://v2.tauri.app/distribute/windows-installer/ . ARM AppImage creation must run natively or under emulation, not cross-compile: https://v2.tauri.app/distribute/appimage/ . macOS bundles and DMGs require the corresponding native Python runtime; universal Rust does not make Python universal.

### Plan review

- Architecture: PASS — separate workflow, no PR/push trigger and no required-job changes.
- Quality: PASS — SHA-pinned existing actions, read-only token, no secrets, no source-build fallback.
- Coverage: WARN — Windows source portability and three Python stacks are incomplete; explicit outcomes required.
- Performance: PASS — native matrix is nightly/manual only; no local Cargo builds.

## Implementation and checks

1. Create `.github/workflows/six-targets.yml`: schedule/manual only; six explicit matrix entries; architecture assertion; Linux desktop dependencies; independent Rust build/test and Python quick steps; final always-run outcome summary. Do not use continue-on-error to turn failed tests green.
2. Use full Linux hash locks on Linux x64; existing runtime/tools hash locks on macOS arm64; exact Linux/data version pins (platform wheels only) for Windows x64. Use explicit unsupported steps with reasons elsewhere.
3. Validate YAML, six unique triples/labels, trigger restrictions, pinned actions, and unchanged required CI. Run local Python/UI/secrets quick checks; invoke `make test-quick` with Cargo disabled to respect the explicit no-local-build constraint, and record Rust as not run locally.
4. Commit with the requested attribution, push only `lane/six-target-ci`, attempt one branch dispatch, inspect every target's step conclusion and logs. Record infrastructure failures separately. No merge.

## Results and resume point

Implementation complete in `.github/workflows/six-targets.yml` (six native matrix entries, only schedule/manual triggers). YAML structure, six unique native triples, pinned action SHAs, every Bash block's syntax, and `git diff --check` pass. `ci.yml` and `ci-watch.yml` are unchanged. `cargo fmt --all --check` passes without compiling. UI: 266 passed, zero failed. Secret scan: 1,197 tracked text files, zero findings. Local `make test-quick ... CARGO=true` is running Python; Cargo compile/clippy/tests are deliberately not run locally because of the disk constraint. This command is not a full Rust quick-tier pass.

Resume after the local Python quick result, then commit/push/dispatch and append hosted outcomes or the exact dispatch infrastructure/registration error. `engineering_approved` remains false. No release-support claim follows from a green controller build or an unsupported Python step.
