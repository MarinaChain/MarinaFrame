# Development

Use Python 3.12 on Linux. Create a virtual environment, install `.[test,documents]`,
then run `python -m pytest -q`. Tesseract is required for OCR tests. For package
checks, install `build` and run `python -m build`.

Keep generated datasets, CAD exports, model weights, credentials and confidential
source drawings out of Git. Retain provenance and third-party notices when adding
licensed material. Never describe a regression pass as an independent shipyard
validation. Preserve blocked-output behavior and the `review_required` status.

The project has no open-source license or contributor license agreement. Discuss
rights with maintainers before submitting third-party contributions.
