# Development

Use Python 3.12 on Linux; the tested patch version is 3.12.14. Create a virtual
environment, install the exact supported dependency set, then install the source:

```bash
python -m pip install --require-hashes -r requirements-linux-py312.lock
python -m pip install --no-build-isolation --no-deps -e .
python -m pytest -q
python -m build --no-isolation
```

The system Tesseract executable and DejaVu fonts are required for OCR tests.
Do not confuse source imports with an installed-package check. Install the built
wheel with `--no-deps` into another freshly locked environment and run
`scripts/smoke_installed.py --out artifacts/installed-smoke` with that interpreter.
See `docs/DEPENDENCIES_AND_RIGHTS.md` for native dependencies and unresolved rights.
Range-based dependency probes (`.[test,documents]`) run separately from the
hash-pinned release profile.

Retain baseline and failed results when changing acceptance behavior. The current
release's dispositions and measured limits are in `docs/HARDENING_RESULTS.md`.
Use `python scripts/scan_secrets.py` after staging new source files; it scans
tracked text and does not promise a complete secret audit.

Keep generated datasets, CAD exports, model weights, credentials and confidential
source drawings out of Git. Retain provenance and third-party notices when adding
licensed material. Never describe a regression pass as an independent shipyard
validation. Preserve blocked-output behavior and the `review_required` status.

The project has no open-source license or contributor license agreement. Discuss
rights with maintainers before submitting third-party contributions.
