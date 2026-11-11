# Independent Rust control-plane review

## Scope and result

The Python validation-workstream author reviewed the separately authored Rust
controller, worker bridge and protocol. The review covered candidate readiness,
source/revision/artifact binding, provider receipt and image identity, request
accounting, checkpoint recovery, and process supervision. No production Rust
code was edited by this reviewer. The root implementation author corrected the
findings; this reviewer wrote separate adversarial probes and regression tests.

The final reviewed executable has SHA-256
`8eb68cb95a71d9779dd93a5d61ad6f1ecfb3cbfb3c4a186f92b04a0914a83edb`.
Against that executable, all **18 actual-artifact validation scenarios** have
the expected readiness outcome. The separate protocol/recovery/supervision
target passes **six tests in 36.06 seconds**, including multiple mutations per
test. The preserved real failed native audit cannot become review-ready. No
model/network/CAD execution was performed by the validation probes or receipt
fixtures; the process-supervision test launches an explicitly fake nonreading
child to test bounded pipe backpressure.

This review establishes the checked implementation behavior, not professional
engineering approval, an external identity signature, or correctness of the
source interpretation. All actual and controlled cases retain engineering
approval false.

## Findings and corrections

| Finding | Evidence and consequence | Correction and independent check |
| --- | --- | --- |
| Provider receipt did not fully bind to durable request | Initial code inspection found that a receipt's image list and request/observation/prompt hashes were not compared with the recorded request. That could make an inconsistent receipt claim current CAD pixels had been transmitted. | The controller now reopens the recorded `ProviderInput` and compares the exact image list, payload hash, prompt hash, observation hash, attempt and retry relationship. Ten receipt/request/image/state substitutions were refused before request completion was recorded. |
| Incomplete raw-audit protocol checks | Initial inspection found omitted semantic obligations, sampling text, section field checks, native receipt resource/inventory checks, and revision-selection content checks. The root author corrected these before the first dynamic suite. | Independent actual-artifact probes reject unknown sampling, removed obligations, extra metric fields, numeric booleans, zero section edges, nonnumeric uncertainty, malformed resource values, altered receipt inventory and inconsistent revision selection. |
| Evidence kind/path and context could disagree with current files | **Reproduced.** A contract labeled a run's submitted specification as `captured_input_spec`, with internally consistent replacement reference hashes. The earlier Rust predicate accepted it. It also accepted changed context metrics and missing context section information. | The controller derives expected source/revision/run evidence from fixed current paths and hashes, and derives metrics and sampled section information from the verified run. All three formerly accepted cases now fail with explicit context-binding errors. |
| Receipt could claim zero cost without a corresponding cost observation | **Reproduced.** A completed receipt with `observed_cost_usd=0` and no `usage.cost` was adopted and counted as a completed request. | Typed usage validation now precedes counter mutation; observed cost must equal the optional recorded usage cost. Zero without cost evidence, differing cost values, boolean token counts and inconsistent token totals are refused. Missing cost remains explicitly unknown. |
| Stdin writing could block outside supervision | Code inspection found synchronous `write_all()` before the timeout/cancellation loop. A child stalled before reading could block the supervisor despite its declared timeout. | Request writes are now nonblocking and polled with process/cancellation/deadline checks. An independent fake child that never reads a 1 MiB request is terminated under a one-second worker limit, with wall time asserted below five seconds. |
| Floating-point JSON parsing could reject an unchanged event chain | Found during separate UI QA and then **independently reproduced** by this reviewer on the preserved real development task. The earlier reader reported `event_chain_mismatch` despite no file change. | With `serde_json`'s `float_roundtrip` feature, the same state bytes verify as 36 events and 144 artifact references, retaining the original chain head and task status. |

The Python independent review separately found a lock gap between context and
finalization. The root author applied the corresponding Rust domain guard around
completed-worker adoption and final predicate/readiness-event commit, with
current-state and cancellation rechecks. The Python guard fixes and independent
review evidence are documented in `docs/VALIDATION_FIX_RESULTS.md`.

## Actual-artifact validation probes

`benchmarks/rust_validation_adversaries.py` creates a fresh copy for each case.
It uses the preserved, actually reimported passing three-station STEP and the
actually failed 25-station terminal-spur STEP. Cases that mutate raw audit data
also update that copy's audit/receipt metadata coherently. This exercises the
meaning of the contract, in addition to the easier unchanged-hash corruption
checks. Original native tasks and measurements are not altered.

The successful case stays review-ready with a `0.896516 mm` raw sampled distance.
The real failed case has valid CAD topology but a `43.264475 mm` raw distance,
above the unchanged `1.1 mm` limit. Its contract is well formed and its readiness
is false. The other 16 scenarios reject malformed, missing, stale or mismatched
evidence. They cover missing binding, stale revision, removed audit, changed
STEP, raw booleans/semantics/sampling/metrics/section fields, receipt resource and
artifact inventory, revision-selection content, and current evidence/context
identity.

The probe's `python_ready` column uses a fresh Python domain context. The two
cases that mutate only the separately supplied Rust context do not mutate the
valid Python context; their Python result is therefore true. The Rust contract
still requires that its supplied context agree with independently derived
current values, and now rejects those malformed protocol inputs.

Evidence under `artifacts/v04/independent-rust-review/`:

- `validation-before-context-fix.json`: first 18-case run; three unexpected
  readiness acceptances, executable SHA-256 `05052a012303752020b1dfeec4ae36d090043b454de6f8c622f46d0c732d98ef`.
- `validation-after-context-fix.json`: all expected outcomes, executable SHA-256
  `016319f52af7f0f879310850c1eb8003b758707e6e3e85868c582e562f7a740b`.
- `validation-final.json`: all expected outcomes against the final reviewed
  executable identified above.
- Corresponding `.log` files and copies of the probe script preserve the
  preceding and corrected observations separately.

## Receipt, recovery and supervisor checks

`rust-control/tests/independent_receipt_review.rs` calls the public reconciliation
and recovery entry points with explicitly controlled protocol records. The
receipt baseline cannot call the model: its task is already blocked, so resume
stops after receipt reconciliation and before execution. Its recorded request
is labeled as a fixture and is never transmitted.

The six independent tests establish:

1. A completed consistent fixture is reconciled once; absent cost is counted as
   missing cost rather than manufactured zero-cost evidence.
2. Ten changed request, image, retry and completion fields are refused while
   retaining the pending intent and leaving completion counters unchanged.
3. Four contradictory cost/token cases are refused before counters change.
4. A missing receipt becomes `transmission_or_completion_unknown`; subsequent
   resume requires explicit acknowledgement and does not automatically repeat
   the request or charge another intended request.
5. A stale mutable checkpoint is rejected by ordinary open. Explicit recovery
   accepts only a genuine committed-event prefix and records the recovery event.
6. A nonreading worker cannot block indefinitely while the supervisor writes its
   large request.

Run the independent target without recounting the imported production modules'
existing tests:

```sh
cargo test --locked -p marinaframe-control --test independent_receipt_review \
  -- --skip ::tests:: --nocapture
```

`receipt-before-cost-fix.log` preserves the failed zero-without-cost regression.
`receipt-and-state-after-fix.log` records the six passing independent tests.

## Unchanged-event float regression

`float-roundtrip-independent-verification.json` records both reader outcomes
against `/tmp/marinaframe-v04-dev3/live`. Its `state.json` SHA-256 is unchanged
before and after verification:
`821dccb5d1962bafc2b6f188da8462b4b3d1789018354a95803452f75b8c0477`.

The corrected reader verifies 36 events and 144 artifact references with head
`8957de5f40ee1b7c2079e53f88294a565f3701cfb0781c2eafeea7aed6fe873a`.
The task remains `provider_failed`; a parser correction does not relabel that
earlier live experiment as successful or alter its provider outcome.

## Author-separated local review UI assessment

The validation reviewer separately inspected the data-workstream author's
`rust_review.py` boundary and tests at commit `1a0beec`. The reviewed UI source
SHA-256 is
`30ace8ea6043029e1d6efc557d4643b1a7b6cd8c05855e67933a0d15580c990b`;
the associated test-file hash is
`907d8dcc7f4ae6d7a56a01e47da064f6156e9d46e4a09e328dfdd28d2d5aaac0`.
The review covered loopback binding, Host/Origin/session/CSRF checks, credential
parsing, task-bound subprocess arguments, mutation freshness and current versus
older candidate display. The reviewer did not edit the UI implementation.

Two issues were reported and corrected by the implementation authors:

1. A fresh UI snapshot followed by an unbound Rust `resume` left a race in which
   a separate legitimate CLI action could change the candidate before resume
   acquired its lock. The UI now forwards expected task ID, event-chain head,
   generation and revision; Rust checks the all-or-none binding under its store
   lock before mutation. The regression verifies all four arguments and
   controlled refusal when the task changes after the UI snapshot.
2. A lone-surrogate credential supplied through escaped JSON could raise during
   UTF-8 encoding. Credential matching now rejects non-ASCII strings before
   constant-time comparison, returning a controlled forbidden response. The
   regression includes both the escaped surrogate and non-ASCII header input.

The reviewer independently reran the resulting **17 UI boundary tests: all
passed in 5.65 seconds**. The preserved log and JUnit results are
`artifacts/v04/independent-rust-review/ui-boundary-tests.log` and
`ui-boundary-tests.junit.xml`. No blocking finding remained in this inspected
scope. This code/test review is separate from the UI author's real-browser
native rebuild, stale selection, cancellation and resume evidence; it does not
claim to have repeated those operator actions.

## Limits of this review

Local hashes and protocol checks establish consistency under the stated trusted
controller/tool boundary. They do not authenticate an adversary who can rewrite
the host, executable and all files. The native raw source-section audit remains
bounded to sampled stations. Receipt reconciliation tests are protocol doubles,
not live model capability evidence. Actual visual model behavior, source-backed
revision decisions and campaign-level measurements are separate experiments.
