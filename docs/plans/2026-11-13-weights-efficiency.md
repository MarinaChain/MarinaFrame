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

## Frozen public cases (before any ship predictions)

The following owner Q88 cases are fixed. Per-ship source data stays outside git, in main
`work/weights/public-ardmore-{gibraltar,purpose,persistence}-20261113/`; each directory contains
its URL/date/SHA-256 manifest. Cases: Ardmore Gibraltar, Ardmore Purpose, Ardmore Persistence.
Source pages: lightship p3 for all; engine and efficiency p20 for Gibraltar/Persistence and
p20–21 for Purpose. Owner PDFs are at:
- https://www.ardmoreshipping.com/s/Ardmore-Gibraltar_q88_02Sep2025.pdf
- https://www.ardmoreshipping.com/s/Ardmore-Purpose_q88_02Sep2025.pdf
- https://www.ardmoreshipping.com/s/Ardmore-Persistence_q88_02Sep2025.pdf

Keep the original <=20% lightship and <=10% index bands. Owner questionnaires label the
indices EEDI/EEXI ratings, but do not supply the technical files. None supplies demonstrated
regulatory Vref, vessel-specific reference-point SFOC and full correction inputs. Maximum or
economical service speed is NOT Vref. Weight inputs also lack justified MR-tanker steel K,
house length-height sums and component CGs. Do not borrow a small-tanker K or fit these cases.
The public-ship gate is therefore BLOCKED at source sufficiency; compute no ship errors.

## Equation sources and specific checks (before new checks)

- Public secondary weight source: https://dspace.lib.ntua.gr/xmlui/bitstream/handle/123456789/38613/leventakis_roro_tanker.pdf?sequence=1
  pp22–23: EN and steel power 1.36, block correction at 0.8D; p29: outfit K*L*B;
  p30: machinery remainder Cm*MCR^0.70. Coefficients remain explicit, not general defaults.
  Main-engine mass comes from its source table; do not apply the medium-speed p29 coefficient
  to two-stroke engines. CGs are explicit assumptions, not a sourced CG regression.
- Public engine programme 2025, p27 layout and L1 SFOC, pp8–9 conditions/tolerances:
  https://www.hd-marineengine.com/pdf/Everllence%20Engine%20Program%202025.pdf
  Local `public-engine-programme-2025-20261113/`. Do not apply L1 SFOC to another SMCR rating.
- IMO primary PDFs: `https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.<number>(<session>).pdf`.
  Archived 364(79),350(78),352(78),353(78),355(78),338(76),400(83), with `imo-manifest.json`.
  EEDI §§2.1,2.2.1–7; EEXI §2.2.1; CII G1 §4 and G2 table1. G5 deductions not implemented.
  CII factors include the 2025 amendment MEPC.400(83), 2027–2030; reject later years.
- Engine source check: reference table rating must match selected SMCR/rpm before SFOC is
  used. Reject other ratings until a matching table is supplied. Arithmetic remains gate 3.

## Results and resume point

- Worktree created from local `continue/v0.5` at `bbf5ace`; main checkout changes preserved.
- Research limitation: WebSearch returned empty results; unbrowse returned `api_key_required`. Static public document retrieval remains available. No predictions run.
- Resume: obtain primary IMO texts and public case evidence, then write source-specific gates before calculations. Current gates are unchanged.
