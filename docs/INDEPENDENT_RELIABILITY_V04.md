# Independent MarinaFrame 0.4 reliability probes

## Result and scope

The validation-workstream author exercised the separately authored current Rust
supervisor and recovery code with small real child processes and explicit
protocol fixtures. **Six focused tests passed in 32.03 seconds** after the
implementation owner corrected one independently reproduced process-group
cleanup bug. No production code was changed by this reviewer, and no API key,
provider request or CAD operation was used.

The corrected source was captured at commit
`8916e68f4c175bdab291d7c0bf2978862be8915d`. The independently compiled test
executable has SHA-256
`eaa925dcea603ed96b3e955c7b1a59815c8045dbb38c277b706124733aabe5d2`.
Per-file source and lock identities are retained in
`artifacts/v04/reliability/after-fix/source-identity.json`. The test target
imports the production Rust modules directly; its subprocess behaviors and
receipts are clearly labeled fixtures.

## Reproduced normal-exit descendant bug

On the preceding production commit
`90dc4827f00eed756a87267d29029c170dab77f8`, a controlled worker forked a child
and then exited normally with code 0. Rust's supervisor returned `exited` after
**0.081 seconds**, but the descendant was still running after a further half
second. The pre-fix test failed and explicitly killed its owned fixture group
before asserting, so the probe did not leave an orphan behind.

The normal-exit branch previously called `Child::try_wait()` and returned
without cleaning up the process group. The implementation owner changed it to
observe exit through Linux `waitid` with `WNOWAIT`, kill remaining group members
while the unreaped leader still pins group identity, and then reap the leader.
The cancellation grace period now also observes exit without prematurely
reaping that identity.

The same regression passes after this change: the leader's exit code is still
0 and its descendant is stopped. The cancellation and parent-death cases also
pass after the correction.

Pre-fix evidence is preserved under `artifacts/v04/reliability/before-fix/`,
including `normal-exit-process-group.json`, `normal-exit.log`, the source hashes,
and the executable hash
`b907f5937d2a4b45594dc2214458fa2231a071768b05cb2066833c150d0a11eb`.
Corrected outcomes are preserved separately under `after-fix/`.

## Six focused checks

| Check | Exercised behavior and observed result |
| --- | --- |
| Process-group cancellation | The real Rust supervisor launches a controlled Python leader and forked descendant, both ignoring SIGTERM. A cancellation marker causes group termination, including SIGKILL after the grace period. Both processes stop; corrected supervisor wall time is approximately 2.06 seconds. |
| Normal leader exit | A leader exits 0 while its descendant continues sleeping. The pre-fix test fails; the corrected supervisor terminates the descendant before returning. |
| Parent SIGKILL and nested cleanup | An owned Rust supervisor subprocess is killed with SIGKILL. Linux delivers the configured parent-death SIGTERM to its controlled bridge. That bridge uses the actual production Python `isolation.supervise_process` with a cooperative cancellation event to stop a separately grouped fake native worker and its TERM-resistant descendant. The nested supervisor records `cancelled` in approximately 0.154 seconds; all three fixture processes stop. |
| Missing and late worker receipt | A durable pending intent is followed by a changed domain checkpoint and an explicitly fake unreceipted candidate. Resume retains the old generation and pending intent. Even explicit recovery of a missing controller checkpoint does not adopt the changed domain. A subsequently supplied complete, current fixture receipt reconciles once; a further restart does not duplicate it or increase the operation count. |
| Uncertain provider outcome across restart | A controlled `transmission_or_completion_unknown` receipt remains interrupted across reopen. Resume without acknowledgement refuses. Explicit acknowledgement allows a zero-step pause, with one intended request, one unknown outcome, one missing-cost record, zero completions and no repeated request. No process or network call is made. |
| Source and captured-spec staleness | Independent one-byte changes to the captured source and captured spec produce `source_changed` and `input_spec_changed`. Both are refused before a worker intent or process starts. Explicit missing-checkpoint recovery also refuses and does not publish a replacement checkpoint. |

The process checks compare PID-namespace-aware procfs paths and process birth
ticks, and distinguish stopped/zombie states from running processes. Fake
workers have bounded lifetimes and explicit cleanup. These are tests of the
trusted worker lifecycle, not containment of hostile code that deliberately
escapes its process group or ignores the cooperative bridge's parent-death
behavior. The parent-death case exercises real OS signals and the actual nested
Python supervisor but does not run a heavy CAD workload or the complete
`rust_worker` entry point.

The six new checks complement the six earlier independent receipt/protocol
tests; they are not duplicate executions counted as new coverage. The imported
modules' existing unit tests are filtered out of the focused result. The helper
test used as the owned supervisor subprocess is otherwise ignored.

Run with a fresh evidence directory and an existing private temporary directory:

```sh
TMPDIR=/tmp/marinaframe-reliability-local \
MARINAFRAME_RELIABILITY_EVIDENCE=/tmp/marinaframe-reliability-evidence \
cargo test --locked -p marinaframe-control --test independent_reliability \
  reliability_ -- --test-threads=1 --nocapture
```

The dedicated `TMPDIR` separates the fake fixtures' admission lock from ongoing
real CAD experiments. It changes no supervisor policy and does not launch CAD.
The initial cancellation probe used the ordinary shared admission location and
recorded a 4.9-second queue wait before its two-second cancellation test. The
corrected focused run used the separate fixture directory. The target also
passes `cargo clippy --locked -p marinaframe-control --test
independent_reliability -- -D warnings`.

## Workspace publication and copy observations

The installed-wheel QA stream separately observed a real native run under the
workspace path with a published result and manifest, followed by an unfinished
staging directory and run-lock marker being visible again. The original run is
preserved under
`artifacts/v04/release/python-verification/installed-agent/task/domain/builds/`.
The original observer recorded no matching worker processes and identical
installed/source module hashes. Its filesystem evidence is
`installed-agent-failure-filesystem.json` in the parent verification directory.

This reviewer inspected six reported files read-only and confirmed their raw
SHA-256 values still match that original evidence. The lock and staging
transaction marker have recorded mtimes around **21:37:48 UTC** and ctimes around
**21:37:53 UTC**; the published result and manifest have timestamps around
**21:37:51 UTC**. These observations establish the conflicting filesystem state,
but do not establish why it occurred. The existing run verifier correctly
refuses the unfinished-marker state. No guard was relaxed and no original file
was removed to make that run pass.

`benchmarks/reliability_copy_probe.py` performs a smaller, separate controlled
experiment using only generated binary and JSON bytes. There are **48 rounds in
each of four lanes**, totaling **192 completed directory trees and 576 files**:

1. Atomic staged publication with lock removal under `/tmp`.
2. The same publication sequence under the workspace.
3. Completed-only copies from `/tmp` to the workspace.
4. Completed-only copies from the workspace to `/tmp`.

The expectation manifest is held independently under `/tmp`. Repeated verifier
invocations compare exact file and directory inventories, sizes and byte hashes;
GNU `sha256sum` independently checks samples from all four lanes. The first
verifier sampled only the first lane; subsequent verifier invocations sample all
lanes. Four separate ordinary verifier invocations, spanning approximately six
minutes, performed **2,304 file checks** with the same expectation-manifest hash.
No spontaneous discrepancy or reappearing marker was observed in this controlled
probe. A deliberate one-byte corruption in one workspace copy
was correctly detected; its exact original fixture bytes were then restored and
verified. That positive-control failure is clearly labeled and is not evidence
of a platform anomaly.

Evidence is under `artifacts/v04/reliability/copy-probe/`, including all verifier
reports, the deliberately corrupted positive-control report, restored result,
and a saved copy of the expectation manifest. Filesystem device and timestamp
metadata are captured in sampled records; `/tmp` and the workspace are treated
as two tested path locations, without assuming they are physically independent
filesystems.

The small probe **does not reproduce or explain the native installed-smoke
anomaly**, and its successful copies do not guarantee future publication
behavior. The cause remains unestablished. The active native smoke under `/tmp`
and its completed-copy checks belong to the installed-wheel QA stream and are
reported separately.

## Distinction from the corrected JSON float parser issue

The earlier `serde_json` float-parsing defect was reproduced by applying two
readers to the same unchanged event bytes: the old reader rejected the event
chain, while `float_roundtrip` verified it without modifying the task. That
evidence is documented in `docs/INDEPENDENT_RUST_REVIEW.md`.

The publication observation concerns the existence and raw bytes of filesystem
markers and directories. The copy probe hashes bytes directly and never
reserializes JSON to determine identity. It therefore provides separate
filesystem evidence and does not attribute the marker behavior to the already
corrected parser issue.

## Historical reader compatibility: old cached numeric values

The corrected float parser also exposes a separate compatibility consequence
for earlier development histories. Read-only verification of the **seven
previously recorded review-ready tasks in development runs 2 and 4** now reaches
the strict raw-audit comparison and refuses each one with
`cached_raw_audit_disagrees`. Every file hash in those task directories is
unchanged before and after the verification commands. Their historical readers
accept four of these tasks and reject the other three at the older
`event_chain_mismatch` check.

| Historical task | Cached/raw numeric differences | Maximum distance |
| --- | ---: | ---: |
| Development 2, deterministic | 1 | 1 ULP |
| Development 4, ambiguity trial 1 | 4 | 1 ULP |
| Development 4, ambiguity trial 2 | 4 | 1 ULP |
| Development 4, retention trial 1 | 1 | 1 ULP |
| Development 4, retention trial 2 | 1 | 1 ULP |
| Development 4, tangency trial 1 | 2 | 1 ULP |
| Development 4, tangency trial 2 | 2 | 1 ULP |

For example, development 4 `retention-trial-01` has the following stored values
at `/geometry_audit/metrics/volume_m3`:

| Representation | Value |
| --- | --- |
| Authoritative Python raw audit token | `20.849681027691894` |
| Historical Rust event/checkpoint cached token | `20.849681027691897` |
| Authoritative IEEE-754 value | `0x1.4d984b221f7e6p+4` |
| Cached IEEE-754 value | `0x1.4d984b221f7e7p+4` |
| Absolute difference | `3.552713678800501e-15` |

An isolated, offline Rust reproducer using the same pinned **serde_json
1.0.145** parsed all **15 differing authoritative numeric tokens** with and
without `float_roundtrip`. The default parser reproduced **every historical
cached floating-point bit pattern exactly**. The roundtrip parser preserved
every authoritative bit pattern and distinguished all 15 historical cached
values. This reproduces the numeric conversion mechanism directly; it does not
depend on a filesystem mutation or numerical tolerance change.

The historical compatibility report, exact differences, both reader outcomes,
unchanged-file checks, and the isolated reproducer's source, lock, inputs and
outputs are under `artifacts/v04/reliability/historical-reader/`. The reader used
for this check has SHA-256
`2e81bf6aa6e71d3226a84fb0d303176da991920ebc1fbb152f5401fc796b0f3d`.

The original raw audit, STEP and development records remain preserved. Their
earlier `awaiting_human_review` labels are historical observations and are **not
automatically accepted by the final reader**. A parser fix does not silently
migrate cached event values. No old event, receipt, checkpoint or audit was
rewritten here, and the strict equality check was not weakened. A new current
task and freshly bound observations/validation are the supported way to obtain
a current review-ready record; an explicit history-migration mechanism has not
been implemented or claimed. A one-ULP metadata discrepancy by itself is not a
new geometric-failure measurement, but it does fail the controller's required
exact evidence consistency.

All fixture outcomes retain `engineering_approved=false`; these reliability
checks do not certify source interpretation or geometric fitness.
