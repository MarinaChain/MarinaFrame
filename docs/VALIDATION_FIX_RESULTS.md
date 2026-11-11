# Validation cache and finalization results

> **Historical (0.5):** the Python Harness, `vessel-reconstruct agent ...`, `agent_review` and `agent_provider` described here were removed. Rust (`rust-control/`) is the control plane; see `docs/RUST_CONTROL_PLANE.md`. Results below stay as recorded.

## Result and scope

The published 0.3 cached-failure defect is reproduced, preserved and fixed. A
completed native worker, valid CAD topology, source-trace fidelity, artifact
integrity and semantic review are separate facts. Review readiness now requires
a complete `marinaframe.validation.v1` report, agreement with the actual native
audit files, all current identities and unchanged referenced bytes.

This work does not grant engineering approval, change the raw `1.1 mm` source
audit tolerance or turn the bounded sampled audit into full vessel validation.
The independent Rust controller must enforce the contract separately. The
author's checks below are not the independent review requested for that work.

## Published baseline and first correction

The original probe ran from an archive of the exact published PR #2 head
`5b0b48e3dd9bcef25427d27ce800118935f58d1a`, before modifying its source. It injects
a failed geometric audit into the real cache/finalization methods; it is a
controlled state-machine reproduction, not a failed real geometry measurement.

| Probe | First validation | Cached validation | Native audit calls | Finish result |
| --- | --- | --- | --- | --- |
| Published 0.3 | false | **true** | 1 injected call | `awaiting_human_review` |
| Minimal fix `a36457a` | false | false | 1 injected call | `blocked` |
| Complete typed failed-audit fixture | false | false | 1 injected call | `blocked` |

`engineering_approved` is false in every row. The original failure was promotion
to review readiness, not professional approval. The minimal fix was committed
before the typed migration, and its paired evidence is retained separately.

Evidence: `artifacts/v04/validation/cache-reproduction.json`, the corresponding
`baseline-controlled/` and `minimal-fixed-controlled/` task folders, and
`benchmarks/reproduce_validation_cache.py`.

## Complete validation contract

The full specification is in `docs/VALIDATION_CONTRACT_V1.md` and
`schemas/candidate-validation-v1.schema.json`. The Python implementation rejects
missing, unknown, malformed, null or nonboolean check fields; contradictory
individual checks/conclusions; unsupported versions, units or tolerances; and
incomplete or duplicate sampled-section coverage.

The report binds generation, revision, source manifest, input specification,
selection, revision specification, native run, STEP and audit implementation.
Each cache hit rechecks captured source/calibration, immutable native run,
authoritative audit JSON, worker receipt and sampled-section image files.
Finalization independently reopens the current context and repeats the complete
predicate. A permissive envelope cannot override an incomplete or failed audit.

Authoritative-file comparisons preserve JSON types. Python's ordinary equality
would accept `true == 1` or `false == 0`; it is not used to establish equality
between the native audit file/receipt and the typed cached raw report.

Selecting A, then B, then A requires a new revision-bound build. An older A build
cannot become current just because generation identity repeats. Rendering a
preserved candidate marks it stale when either generation or revision differs.

## Focused verification

The final focused suite passed **150 tests in 5.58 seconds**. It covers fresh,
cached and restarted pass/failure; attempted finish after cached failure;
incomplete legacy data; invalid worker execution; malformed/native/cached
reports; missing or modified source, specification, selection, manifest, result,
STEP, audit and image files; current revision/calibration/selection changes;
maliciously permissive envelopes; numeric boolean equivalents in native audit
artifacts; repeated generation identity; stale rendering; mutation attempts
during the final predicate and readiness-event commit; cancellation/deadlines
arriving during the predicate; and malformed persisted revision identities.

The controlled test fixture clearly marks dummy STEP and image bytes. It
substitutes native execution only for state/contract adversaries. The separate
native integration test passed in **26.77 seconds**, building actual CAD,
reimporting STEP, rendering four views, measuring actual section cuts,
preserving a prior valid candidate after an invalid revision, and rejecting a
changed STEP artifact. That integration fixture intentionally ends tampered and
is not presented as a clean golden task.

The separate full-validator schema suite passed **29 tests in 0.10 seconds**,
checking all three golden fixtures, each omitted required field, and malformed
or contradictory protocol fields against both Draft 2020-12 and runtime checks.

Logs and JUnit: `artifacts/v04/validation/review-fix-tests.log`,
`review-fix-tests.junit.xml`, `schema-tests.log` and `schema-tests.junit.xml`.
The earlier 139-test run remains in `focused-tests.log` and its JUnit file.
Full Draft 2020-12 schema validation is recorded in
`jsonschema-validation.json`; lightweight runtime checks are additional to that
schema validation.

## Actual native pass and failure

A three-station synthetic task was run end to end with the deterministic policy,
including source inspection, selection, native build, actual STEP rendering,
native source-section audit and finalization. It took six decisions, six actions
and one build. It measured **0.896516 mm** maximum sampled source-to-STEP error,
below the unchanged **1.1 mm** threshold, and ended `awaiting_human_review` with
engineering approval false. Its completed copied task verified with 22 observed
artifacts and 26 events.

After the final type-preserving comparison correction, an explicit test fixture
reaudited copies of both the preserved passing STEP and the real previously
failed `holdout_multichine-241001-drafting` STEP. It did not rebuild or change
geometry. It first observed that an old-contract cache cannot be accepted,
preserved that prior report, and then explicitly requested one new audit in the
copy. This test-fixture action is not a production automatic cache migration;
ordinary invalid cache hits remain blocked and retain their original report.

| Actual native case | Maximum raw error | CAD validity | Trace fidelity | First / cached / restarted | Finish |
| --- | ---: | --- | --- | --- | --- |
| Synthetic three-station STEP | 0.896516 mm | passed | passed | true / true / true | `awaiting_human_review` |
| Preserved terminal-spur STEP | 43.264475 mm | passed | failed | false / false / false | `blocked` |

Both current-contract probes use one actual native audit, zero additional audits
on cache/restart/finish, and preserve `engineering_approved=false`. The original
source tasks remain unchanged. The failing case is a valid solid whose raw
source-section comparison fails, demonstrating why topology alone is not enough.

Current completed copies, observations, contexts and summaries are under
`artifacts/v04/validation/real-native-pass-current/` and
`real-native-failure-current/`, with separate summary JSON and logs. Earlier
golden and pre-final-comparison evidence remain distinct; their recorded audit
implementation identities are not rewritten to look current.

The actual oblique STEP image and passing/failing source-cut comparisons were
opened and visually inspected by the assistant. The artifact hashes and limited
observations are in `visual-inspection-ledger.json`. This is artifact inspection,
not qualified naval architecture review or vessel certification.

## Independent review and corrections

The separate data-workstream author reviewed commit `8c9c4fd` and reproduced
three additional issues with controlled fixtures: a public selection could
advance the revision between context creation and readiness commit;
cancellation during the final predicate could be missed; and a boolean false
checkpoint revision could compare as revision zero. The original review probes
and results are retained in `artifacts/v04/data-author-validation-review/`.

The correction holds the domain guard through context, predicate and committed
final event; checks cancellation/deadline again under that guard; and rejects
non-integer/out-of-range revisions on initial admission and reload. Eleven new
regressions cover these boundaries. Real passing and failing native tasks were
then copied and finalized through the corrected guard using their unchanged
valid audit contracts, with **zero new native executions**. They respectively
remained `awaiting_human_review` and `blocked`, both with engineering approval
false. Completed copies and verification are recorded in
`guarded-native-finalization.json`, `guarded-native-pass/` and
`guarded-native-failure/`. Their audit implementation identity did not change;
the correction is in cache admission and controller finalization.

The independent reviewer then reran the adversaries at the new guarded call
sites: competing selections were refused both during the predicate and at the
readiness-event commit; cancellation after a true predicate changed the final
status to cancelled; and malformed revisions failed on execution and reopening.
The separate review record preserves the original findings and follow-up
outcomes rather than treating an unused old hook as a passing regression.

## Reproduction

Use the pinned project CAD environment and execute native probes serially. Run
the state/contract regressions with:

```sh
PYTHONPATH=src python -m pytest tests/test_validation_cache.py tests/test_agent_harness.py -q
```

An actual preserved native task can be reaudited explicitly in a new directory:

```sh
PYTHONPATH=src python benchmarks/reaudit_preserved_native_run.py \
  --source-task /path/to/completed/source-task \
  --out /tmp/new-explicit-reaudit-task --expect failed
```

Use `--expect passed` for the passing fixture. The script copies the source
domain, preserves its old validation, invokes the actual native auditor once,
reopens the domain, attempts finalization, and verifies the completed event
chain. Original source state and STEP bytes are not edited.

## Remaining limits

The audit samples first two, middle and last two stations, with duplicate indices
removed. It checks selected source traces against the provisional STEP, not
whether the selected contour, calibration, station correspondence, symmetry,
closures or vessel condition are correct. It does not establish independent
vessel accuracy. Native geometric failure remains diagnostic evidence rather
than an automatic repair or a reason to weaken the tolerance.

Local content hashes detect changed or inconsistent evidence. They do not
provide external authenticity against an actor who controls the host and
rewrites all records. A trusted review identity and professional approval remain
outside this automated contract.
