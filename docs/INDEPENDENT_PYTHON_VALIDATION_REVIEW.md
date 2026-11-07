# Independent Python validation/finalization review

Reviewer: `data_learning_v04`, separate from the author of the validation
changes. Reviewed validation revision:
`8c9c4fd90c64ddfca22801d7f2cb66f55e7647e3`.

Scope: `validation_contract.py`; `DomainTools` capture/checkpoint, build identity,
cache and validation methods; the Python `Harness` finish branch; the complete
candidate-validation JSON schema; relevant state/contract regressions. Geometry
helpers and native hull accuracy are outside this review. No external provider
or native CAD job was invoked. Deterministic interleaving probes use the existing
explicit controlled native fixture while exercising the actual domain selection,
locking, cache, validation predicate and controller event code.

## Findings at the reviewed revision

### P1 — finalization does not keep its current-state lock through commit

`DomainTools.validation_context()` acquires the domain lock, reloads and verifies
the current candidate, returns a context, and releases the lock. `Harness._run`
then calls `ready_for_review` and writes its terminal event without that domain
lock. A legitimate second `DomainTools.select_contours` operation can commit a
new revision in this gap. Its old source/revision/run artifacts remain intact,
so the passing report still verifies against the *returned old context*.

The independent probe started with a valid controlled report for `r0000`,
committed an allowed selection yielding `r0001` and a different generation after
the context returned, and still obtained `awaiting_human_review`. Engineering
approval remained false, but readiness no longer described the current selected
revision. This is a deterministic reproduction of an allowed concurrent
interleaving, not a host attacker rewriting all hashes.

**Required correction:** hold one domain guard across the fresh context,
complete readiness predicate and terminal state commit, or implement an
atomically equivalent compare/commit transaction. An additional unlocked hash
comparison only moves the race. Verify that a second public selection is rejected
both during the predicate and immediately before the terminal event is written.

### P2 — cancellation during final verification can still commit success

The Python finish path checks cancellation/deadline after `validate_candidate`,
then constructs the fresh context and verifies the complete report. It does not
check cancellation again before committing review readiness. The probe set the
shared cancellation event during that final-context phase and still obtained
`awaiting_human_review`.

**Required correction:** check cancellation and elapsed deadline immediately
before successful termination, inside the finalization guard. Regression coverage
must inject cancellation after the full predicate has returned true, not only
before the initial validation call.

### P2 — a malformed checkpoint revision can reuse validation

Persisted `state.revision=false` is accepted by the current reload path and
formats as `r0000`. A cached passing report for numeric revision zero is then
reused with `ok=true`. This finding concerns domain checkpoint admission;
the raw-validation boolean checks themselves correctly require exact booleans.

**Required correction:** reject non-exact-integer, negative and out-of-bound
revision values before assigning a loaded checkpoint to the active object.
Validate before assignment so the error response does not try to format invalid
state again. Cover both existing-object reload and reopened-domain admission.

## Positive findings

The original cached-geometric-failure defect is addressed in the reviewed code.
A controlled failed geometric report remains `ok=false` on reuse, and a forged
permissive observation envelope cannot override the complete failed contract.
The predicate rechecks current generation/revision binding, source and run
artifacts, raw audit JSON, worker receipt and sampled-section inventory.
Canonical JSON comparison preserves boolean versus numeric distinctions in the
authoritative artifacts. The explicit review/approval fields remain fail closed.

The complete contract's runtime checks are stricter than structural JSON alone:
finite quantities, exact booleans, supported tolerances, arithmetic consistency,
ordered sampled-section coverage, evidence identity and derived conclusion must
agree. Stale or malformed cached artifacts do not silently trigger a replacement
audit. Source interpretation and engineering approval remain separate limits.

## Evidence and independent regression expectations

`artifacts/v04/data-author-validation-review/probe-results.json` contains the
actual pre-correction observations, including one audit call per controlled case.
`probe-script.py` preserves the executed reproduction. The original evidence is
not rewritten after fixes.

`guard_regressions.py` adds ten focused independent regression cases: concurrent
selection during the predicate, concurrent selection during the terminal event
commit, cancellation after a passing predicate, an elapsed-deadline expiration after a passing predicate, and six malformed revision
values. The guard tests assert that their hooks actually executed, preventing an
unused old hook from appearing to pass after refactoring.

All three findings were corrected in
`670054ff19217636e567c58ef23803391043a436`. The independent reviewer inspected
the guard/revision changes and reran all ten regression cases: **10 passed in
1.02 seconds**. Competing public selections were rejected during both the
predicate and terminal event commit. Cancellation after a passing predicate
ended cancelled; elapsed-deadline expiration ended budget_exhausted. All six
malformed revision values failed closed on live reload and fresh admission.
The guard now spans fresh context, complete predicate, final cancellation/deadline
check and terminal event commit. No additional native audit was needed for these
state/locking corrections. No unresolved blocker remains within this review
scope; the original pre-correction evidence remains preserved separately. This document is a code review, not a
qualified naval-architecture review or an independent real-vessel accuracy claim.
