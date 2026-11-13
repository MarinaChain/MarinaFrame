# Weights and efficiency implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add traceable preliminary tanker weight, engine selection and efficiency calculations, without a compliance claim.

**Architecture:** One independent Python package, `weights_efficiency`, with typed inputs and outputs and a plain-dict record fragment. Read Holtrop results without modifying its module. Public reference tables stay in the main checkout's ignored `work/weights/`; no other batch modules are imported.

**Tech Stack:** Python dataclasses, standard library, pytest; existing quick test tier.

## Plan review (before implementation)

- Architecture: PASS — isolated package; no shared schema dependency.
- Code quality: WARN — empirical coefficients and engine tables need source pages; do not invent defaults.
- Coverage: PASS — hand calculations, unsupported-domain rejection, layout interpolation and record serialization are testable.
- Performance: PASS — scalar algebra and small table lookups; no solver or new dependency.

## Gates (frozen before checks)

1. **Source gate:** Read the cited equations and resolution pages before implementation. Archive downloaded documents in separate directories under main `work/weights/`, with URL, retrieval date and SHA-256. Missing sources block the affected calculation, not the whole lane.
2. **Public-ship exit gate:** Select and commit 2–3 named public tanker cases and their cited published lightship and attained EEDI/EEXI, before computing any predictions. Absolute relative lightship error must be <=20%; attained EEDI/EEXI error <=10%, for each selected ship. No fitting to these ships; no band changes. If two complete source-backed cases cannot be obtained, record BLOCKED and do not substitute synthetic examples for this gate.
3. **Numerical gate:** Independent hand calculations agree within 1e-9 relative (1e-9 absolute near zero). Reject nonfinite, nonpositive physical inputs, unsupported fuel/types/years and out-of-layout operating points. No compliance assertion for omitted corrections or unknown uncertainty.
4. **Record gate:** Every computed quantity has value, unit, uncertainty and basis/reason, neutral method, method_version, sources and draft/review_required status. `engineering_approved` remains false. Speeds carry kn and m/s.
5. **Regression gate:** `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python` passes before push. A pre-existing failure is reported, not hidden. Run long jobs in the background.
6. **Delivery gate:** Commit only this lane's files, push only `lane/weights-efficiency`, no merge; inspect then remove this worktree's Rust `target/` last.

## Implementation steps

1. Read rules, project context, Holtrop interfaces and matching lessons. Research public validation ships separately from calculations; freeze eligible source rows before estimates.
2. Read IMO primary documents. Implement a deliberately scoped conventional single-fuel, single-screw tanker calculation; reject unsupported cases and separate attained from required/reference indices.
3. Add source-backed weight equations, explicit centre assumptions and uncertainty propagation. If source support is insufficient, expose only explicit user-supplied coefficients and label them uncalibrated; do not attribute them to a published regression.
4. Add engine-layout selection with explicit sea/engine margins and source-backed operating-point SFOC tables. No inferred manufacturer's data.
5. Add tests first for arithmetic, constraints and metadata; implement the minimum complete module and run focused tests.
6. Run the frozen public gate only if source gate passes; preserve a blocked gate otherwise. Review readability and scope; run quick tier, record results, commit and push.

## Results and resume point

- Worktree created from local `continue/v0.5` at `bbf5ace`; main checkout changes preserved.
- Research limitation: WebSearch returned empty results; unbrowse returned `api_key_required`. Static public document retrieval remains available. No predictions run.
- Resume: obtain primary IMO texts and public case evidence, then write source-specific gates before calculations. Current gates are unchanged.
