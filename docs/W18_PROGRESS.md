# W18 prototype checkpoint

W17 and W17b are committed: `46363f6`, `68afb96`. W17b full tests passed. W17b four-case round 2 produced 3/4 STEP drafts, 0/4 gate-correct, no silent wrong, 80 requests, USD 0.11823454 list cost. Its one permitted dev24 batch is still running on immutable round-two code in main `work/w17/`; do not restart or duplicate it.

## Current implementation (prototype measured, not complete)

- Native `controller::transcript` module projects completed investigation receipt decisions and host results from existing events.
- Recent assistant/user pairs, compact-result whitelist, current progress/state and last-message-only images.
- Default 32k estimated context budget, configurable 8k–120k. Default remains stateless. CLI `--context conversation` opts in.
- Older pairs folded into author-labelled controller record and a model-claim notes handoff. `context_compacted` event stores the record.
- `recall_view` reattaches a known task view, with normal repeat guard.
- Historical/observation values remove paths, hashes, resource/artifact fields and obvious credential markers before transcript text.
- Provider validator checks role alternation, string historical content, final-user image inventory.

## Explicit gaps before W18 completion

- Dedicated compaction provider request from design section 4a is not implemented; current handoff reuses the model's latest notes. Do not claim a measured model-generated compaction summary.
- Summary format/window differs from the full design and needs review/measurement.
- Recall behavioral and provider historical-image tests need stronger integration coverage; current recall test covers argument contract only.
- Full replay payload equality/unresolved IDs/covered-event hashes are deferred under design section 0; no added provenance framework.
- W18 round 1 completed: two actual STEP drafts, zero gate-correct, zero silent wrong, 83 requests, USD 0.09883013 list cost. Three draft statuses included L1 with no export. No default-setting change and no broad W18 run. CAD complexity is the first blocker; L3 still loops on label reads.

## Resume procedure

1. `make test-full` PASSED for the current prototype: 713 quick Python tests, 19 CAD tests, Rust workspace/CAD/app checks, smoke valid. Log: MAIN `work/w17/w18-full.log`. Frozen W18 round-one source/executable copied after this pass.
2. Read main `work/w17/w17b-dev24.log`; when all 24 attempts finish, existing detached driver scores into `outputs/w17/w17b-dev24.json`. Do not launch more than two provider jobs total.
3. Freeze W18 executable/source only after final prototype fixes and quick checks. Run one DTMB L0-L3 conversation round after dev24 is done. Inspect each first blocker; no big W18 batch before three drafts.
4. Update `docs/LLM_INVESTIGATOR.md`, complete W18 design requirements or state remaining gaps, run full tests, commit only on w17 branch. No push/merge.

Design documents were imported from `continue/v0.5` by `git show`, not branch merge, to respect no-merge instruction. `docs/plans/2026-11-08-w18-implementation.md` lists the prototype sequence.
