# Neutral native kernel landing

Status: draft. This is an intake foundation and a sample rectangular-volume calculation, not a ship-design method. No original runtime is called or shipped. Engineering acceptance remains false.

## Local checks

```sh
cmake -S kernels -B work/kernel-build -DCMAKE_BUILD_TYPE=Release
cmake --build work/kernel-build --config Release
ctest --test-dir work/kernel-build -C Release --output-on-failure
MF_KERNEL_LIBRARY="$PWD/work/kernel-build/libmf_kernels.dylib" python kernels/tests/test_python.py
CARGO_TARGET_DIR="$PWD/target/kernels" cargo test --manifest-path kernels/rust/Cargo.toml --locked
```

Python takes an explicit absolute shared-library path. On Linux use `libmf_kernels.so`; on Windows multi-configuration builds use `Release/mf_kernels.dll`. Rust builds the same C source as a static library through CMake. A consumer in `app/core` or `rust-control` can add a path dependency on `marinaframe-kernels` at `kernels/rust`; neither consumer is changed in this lane. CMake and a native C compiler are build requirements. Cross-compilation is not supported by the sample build script; CI uses native hosts.

C ABI: `mf_box_volume(length_m, breadth_m, depth_m, output_m3)` returns 0 for success, 1 for invalid dimensions or a null output pointer. Negative, non-finite and overflowing inputs fail without changing output. Zero dimensions produce zero. Python raises `ValueError`; Rust returns `InvalidDimensions`.

## Identity boundary

The founder must set repository Actions secret **`MF_IDENTITY_DENYLIST`** to the private newline-separated rules. This lane does not set secrets. Alternatively, local checks read `MF_IDENTITY_DENYLIST_FILE` from a private external path. Lines starting with `#` are notes. Normal rules match lower-case text with non-alphanumeric runs collapsed to spaces. `cs:` rules match case-sensitive whole words. A missing list warns and passes identity checks; native fingerprints remain checked.

Run `python -I scripts/check_identity.py` after staging new files. It checks current tracked paths and contents, not history. Diagnostics show only sorted tracked-file ordinal, line and category, never paths or matched strings. Resolve an ordinal locally against `git ls-files`; do not put private values in logs. UTF-8 text and every path/name use all rules unchanged. Binary files use only case-insensitive entries of at least six normalized characters, checked against raw bytes and UTF-16 text already extracted by the scanner. The output reports the binary-skipped entry count without tokens. Native files under `kernels/` and all intake output must be text; binaries fail even with no identity list. NUL-bearing content is binary. Compressed payloads and visible text in images require a separate private review; this is not OCR or archive extraction. This policy was set by the PM before the final run.

Native source under `kernels/` also rejects long hexadecimal addresses and 64-hex hashes. `scripts/identity_allowlist.json` contains exact `{path, kind, value}` exceptions only for legitimate fingerprints. It cannot permit denied identities. Keep this list narrow and reviewed.

## Offline source intake

```sh
MF_IDENTITY_DENYLIST_FILE=/private/path/list.txt python -I tools/cleanroom/intake.py /private/source /private/mapping.json work/neutral-output
```

The mapping is a private JSON object from source C identifiers to distinct neutral C identifiers. Keep it outside the repository and source tree. Inputs may contain only C/C++ source or header files; no links. Output must be new and disjoint from input. File and directory identifiers are renamed; code identifiers are replaced as complete tokens. String literals are not rewritten. Comments containing mapped names, identity rules or fingerprints are blanked while preserving line breaks. Residual identities, native fingerprints and case-insensitive output collisions fail without publishing partial output. Review transformed source before placing it under `kernels/`; passing intake is not proof of numerical correctness or general C++ syntax support.

## Platform checks

The `kernels` job in `native-targets.yml` runs C, Rust and Python callers on macOS arm64, Linux x64 and Windows x64. Existing desktop jobs remain scoped to their previous platforms. Local success does not establish remote CI success. See `docs/plans/2026-11-13-port-landing.md` for results and resume instructions.
