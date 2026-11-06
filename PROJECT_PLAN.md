# Vessel Reconstruction Foundation

## Current continuation: 7 November 2026

The original scope and gates below remain historical. The 0.2 continuation
implemented typed/resource boundaries, transactional evidence, durable bounded
workers, local authentication, explicit contour alternatives and error-bounded
CAD correspondence. See [actual results and dispositions](docs/HARDENING_RESULTS.md)
for the tested revision, complete test counts, negative results and readiness.
The old numerical benchmark's completion gates are not currently met without
new selection assistance. No authentic archival reconstruction or engineering
approval has been established. The next validation priority is permitted real
drawings with expert contour/calibration labels and measured correction effort.

## Scope and evaluation contract, fixed before evaluation
Build a reproducible local system for section-based vessel hull reconstruction from actual 2D drawing pixels, with a geometry kernel, source provenance, visible uncertainty, and replayable evaluation. Add structural primitives only where explicitly specified by drawing evidence. This is a foundation, not arbitrary full-vessel certified reconstruction.

## Proposed acceptance gates
- Input images are interpreted without reading ground-truth offsets, CAD or generator metadata. An explicitly supplied calibration and page regions are permitted and reported; automatic interpretation is reported separately.
- Reconstruct watertight CAD solids for multiple unseen hull geometries; export and reload STEP.
- On clean held-out synthetic drawings, relative volume error <= 3 percent and RMS section error <= 1 percent of beam for >=90 percent of cases.
- On moderately degraded held-out drawings, relative volume error <= 5 percent and RMS section error <= 2 percent of beam for >=80 percent of cases.
- Validate on at least one externally sourced hull dataset, kept separate from development geometry. Where possible ingest an independently authored public scanned ship drawing; report this distinctly from generated projections.
- Missing scale, missing essential views, inconsistent calibration, or unsupported geometry must become explicit failures or review-required gaps, never fabricated certainty.
- Every accepted reconstructed component links to source hash and evidence region. No automated engineering approval.
- Report all attempted evaluation cases, including failures and baselines. Freeze evaluation inputs before final scoring.

## Deliverables
Python package/CLI, immutable source inventory, editable CAD exports, interactive local inspection viewer, dataset generation/acquisition and licenses, training/evaluation harness, measured results, documented limitations, reproducible environment and complete source bundle.
