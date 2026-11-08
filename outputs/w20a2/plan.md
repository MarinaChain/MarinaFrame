# W20a2 printed dimensions plan

Goal: prefer printed dimension readings and never silently accept conflicting beam/depth.

Plan review: architecture PASS (existing read tools); quality WARN (text is model transcription, not certified OCR); tests cover printed preference, missing reading, >2% conflicts and optional draft dimensions; performance PASS (bounded readings, six cases at most two concurrently).

1. Add failing tests in tests/test_vessel_description.py for printed text priority, independent depth disagreement, missing model beam warning and optional draft-hull comparisons.
2. Update vessel_description.py only: parse model-transcribed labelled dimension text; prefer printed records over extents, keep raw values, compare every independent source. Use supplied depth bound before uncertain pixels if no print. Preserve off-sheet null LOA/draft.
3. Update Rust describe tool schema/instructions and vessel-phase catalog to allow an explicit title read/crop correction before final description. Never use evaluator metadata in model input.
4. Run focused tests and make test-quick with project venv. Freeze runtime/source, run four body cases then two three-view cases, jobs=2, phase1-only, seven requests. One round, no sealed data.
5. Offline checks use unchanged checker; include accepted off-sheet null fields, all receipt cost, field warning coverage. Wait for any other make test-full, run full tests on stable source.
6. Report actual result and commit w20a2-dimensions, no push/merge. Keep new data <1GB and only cited runtime/source.

Owned code: vessel_description.py, tests, Rust describe-tool portions. Protected: form_fit.py, vessel_model.py, first_hull_tools.py, whole_vessel_score.py, view_measure.py. Draft-hull consistency is exposed through describe_table (public hook already called by the Opus lane), not a new CAD build in Phase 1.

Resume: implementation finished; focused 23 tests pass. Quick tier running task bvts1ejks with existing project target cache; new task build cache removed after exceeding planned cap. Frozen runtime/source in main work/w20a2/runtime and source. Six-case sequential driver PID 58807, log round.log, jobs=2 and seven requests; body arm then threeview arm (not concurrent). Quick passed (873 tests); full passed exit 0 (873 non-CAD + 24 CAD, Rust real-CAD, app real task, smoke valid). All six traces inspected, unchanged offline table saved; 17 requests $0.03286380, R-body dims 3/4 and threeview dims 2/2, warning coverage complete. Temporary smoke target symlink removed. Next commit no push/merge.
