# W18c accuracy feedback and integration

## Boundaries

Merge w18-cad-complexity (86b4812) and app-llm-draft-view (4b683e1), not stroke discovery. All new accuracy behavior is advisory result fields/controller text; no new selection gate or refusal. Coverage is measured against declared calibrated span, not evaluation truth. Frozen score remains 2% RMS/5% volume. Main work/w17 holds raw runs and runtime snapshots.

## Steps

1. Merges completed without conflicts: 6b6b80f CAD simplification/deck closure, a74f216 app labels/warnings/activity. Combined make test-quick passed.
2. Add pure accuracy_feedback helper + tests: constant breadth and <90% span warnings, station-tag warning, fragment continuation/propose_section hint; unambiguous contour recommendation first, retain every candidate.
3. Attach helper only at DomainTools result boundary for inspect/enumerate/trace/assign; accept choices unchanged. Do not edit ingest or discovery/trace implementations.
4. Controller: once per task, ask model to author truly missing sections before build; allow next build unchanged. Unknown candidate refusal includes current catalog IDs. No new refusal code.
5. Quick/full tests on stable source; freeze executable/source; one detached DTMB conversation round, max two jobs, short prompt unchanged. Read round_digest. If >=3 actual draft exports, run dev24 exactly once and score. No sealed evaluation.
6. Record compact results/digest/docs, commit on w17 branch, no push/main merge.

## Resume

Advisory helper/result boundary and controller hints implemented; feedback quick/build running. Next: review once-only build hint/repeat interaction tests, freeze runtime and run one round after quick pass, full suite before report.
