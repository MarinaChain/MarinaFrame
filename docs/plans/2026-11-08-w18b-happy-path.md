# W18b happy-path integration

## Goal and boundaries

Integrate W17c authored geometry with W18 conversation. Deliver complete labelled drafts, keep engineering_approved=false and the frozen 2%/5% score. No new refusals/states. Do not edit CAD loft/surface/513-knot handling; branch w18-cad-complexity owns that work. No push or merge to main; the two inbound merges below were explicitly authorized.

## Completed source steps

1. Read main work/w17/w18-brief.md additions.
2. Merge w17c-model-geometry (3abaa5e) as 3b4ffe0; additive conflicts kept both recall_view/propose_section and both doc sections.
3. Merge continue/v0.5 as a53849e to obtain round_digest and current instructions. Retained both lesson sections. No sealed run/scoring performed.
4. Merge quick passed: 747 Python tests.
5. Remove authored_outside_draft schema restriction. Real CAD test confirms person-selected AI section builds, source_label ai_inferred retained, engineering_approved false.
6. Finish in draft mode tries build when candidate absent/invalid. No-STEP feedback remains a build result, not a false draft terminal claim. Existing validation/model-review failures become draft warnings when valid CAD exists; strict path unchanged.
7. Rewrite prompt once to 1,368 characters. Tool details remain in catalog. Prompt prioritizes authoring missing or poor traces, complete draft, build/render early then revise.

## Verification/run plan and resume

- Quick after merge, happy path, prompt; final quick/build logs main work/w17/w18b-{final-quick,final-build}.log.
- Full tests queued detached in w18b-full.log after final build; do not edit worker Python during tests.
- One DTMB L0-L3 conversation round queued detached, max 2 jobs, immutable runtime/source: w18b-round1. Same live/draft/model-review settings, thinking disabled. No new 24-case campaign.
- Existing driver scores frozen dev truth; round_digest.py reads all four traces into main work/w17/w18b-digest.md. Read every case and report first blocker.
- Copy compact rows/digest to outputs/w18, update docs/LLM_INVESTIGATOR.md, review and commit after full pass. Dedicated model compaction request deferred by user.
