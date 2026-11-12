# Hull Variation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce draft hull candidates from the public KVLCC2 reference with changed dimensions, Cb and LCB, and report hydrostatics and gross capacity.

**Architecture:** Sample symmetric reference sections through the existing CAD tools. Scale the sections and use a two-parameter, end-body longitudinal station shift (Lackenby-type), leaving a declared parallel middle body unchanged. Build candidates with the existing ruled hull builder and measure them with the existing mesh hydrostatics. No application intake or drawing-reader changes.

**Tech Stack:** Python, NumPy, SciPy, CadQuery/OpenCascade, pytest.

---

## Boundaries and review

Only public KVLCC2 and synthetic code/data. Never read pilot, sealed or holdout material. All outputs are draft; engineering_approved=false. No new dependency. CAD exports use millimetres; calculations use metres. No model calls.

Architecture PASS: reuse geometry.build_hull and mesh_hydrostatics. Quality PASS: isolated module and explicit validation/errors. Coverage WARN: a station representation approximates the original IGES; report that loss independently of transformation accuracy. Performance PASS: solve on a small fixed mesh, build CAD only after solving; no parallel CAD jobs.

## Fixed checks (before runs)

- Identity: section coordinates unchanged to 1e-10 m; built identity volume agrees to 1e-8 relative with the same reference build.
- Target coefficient: absolute Cb error <= 0.001; LCB error <= 0.001 times candidate length. Cb basis is the stated design length, breadth and draft, not hydrostatics waterline length.
- Built volume versus closed mesh hydrostatics: relative error <= 0.001.
- Each candidate: one positive-volume valid closed solid; strictly ordered stations; no section movement in the declared parallel middle body beyond scaling.
- Capacity: gross immersed envelope volume between stated bulkhead x positions, not net cargo or deadweight. Check analytic box cases and bounds.
- Reference approximation: report sampled-reference versus original public geometry where measurable; do not substitute a target match for local shape accuracy.

## Task 1: numerical transformation

Create tests/test_hull_variation.py first, run failing tests, then create src/vessel_reconstruction/hull_variation.py. Test identity, affine scaling, feasible Cb/LCB targets, fixed middle body, invalid inputs and unreachable targets. Shift stations with smooth end-body basis functions that vanish with zero slope at the end and middle-body boundaries. Reject station folding; do not widen gates.

## Task 2: CAD and reports

Extend the module with candidate solid construction and existing hydrostatics. Add marked CAD tests for synthetic identity, validity, volume agreement and gross capacity. Add scripts/check_hull_variation.py for public IGES ingestion, candidate STEP/JSON output and sample views under ignored work/ only. Read the archive in a new empty scratch directory, with code outside it. Record source archive hash and the stated input dimensions/coordinate convention. Test focused unit and CAD cases before committing.

## Task 3: public sample and delivery

Run identity plus at least two changed KVLCC2 candidates sequentially. Read all reports. Record achieved targets, actual errors, valid solids, capacity bounds and approximation/fairness limits here. Run make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python before pushing lane/hull-variation. Do not merge. Remove only this worktree's target directory as the final cleanup after push.

## Resume point

Plan committed before implementation. Next: write numerical tests and implement Task 1. Results and exact commands will be appended below.
