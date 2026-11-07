# Rust control plane contract (0.4)

The published 0.3 base is `5b0b48e3dd9bcef25427d27ce800118935f58d1a`.
Rust owns the new task event stream, task lifecycle, policy dispatch, request
accounting, cancellation, worker admission, artifact checks and finalization.
The retained Python `DomainTools` owns source processing and the native tool
cache as a subordinate domain checkpoint. It does not run the Python Harness
or create a second authoritative task event store in this path.

The local CLI is the supported boundary. The initial supported target is Linux
x86_64 with Rust 1.99.1 and the existing locked Python 3.12 / CadQuery profile.
No claim of macOS or Windows support follows from using Rust.

## Worker protocol

`marinaframe.worker.v1` requests and results use bounded JSON over stdin/stdout.
Only initialize, observe, named source/CAD operations and explicit verification
are accepted. Task/source paths are trusted operator configuration, never model
arguments. A worker response binds its request identity, domain checkpoint hash,
source identity, operation result and artifact inventory. Rust checks exact
booleans, operation schemas, paths, identities and artifacts independently.

Model operations remain inspect_source, select_contours, build_provisional,
render_candidate, validate_candidate and finish. Selections use known source
candidate IDs. Models cannot supply coordinates, scripts, paths, calibration,
tolerances or engineering approval. New source-supported hypotheses are exposed
through the same bounded candidate selection interface.

## Validation and finalization

The `marinaframe.validation.v1` contract is shared with the repaired Python path.
Worker execution, artifact integrity, CAD validity, trace fidelity, semantic
review and professional approval are separate fields. Rust checks current
generation/revision, source/spec/selection, run/STEP, validator implementation,
audit evidence, contract version, units, fixed tolerances and measured checks.
A cached report must satisfy the same requirements as a fresh report.
No unknown/missing/contradictory result can finalize as review-ready. Every
automated result retains engineering_approved=false.

## Persistence and recovery

Events are versioned, ordered and hash-chained. Each event contains a typed state
snapshot; the mutable state file is a checked cache. Task locking is an OS lock
on a permanent ordinary-file inode. New event bytes are fsynced and published
without replacing an existing event. Domain checkpoints are bound to events;
unreceipted worker changes after an interruption do not become accepted evidence.
Source/STEP mutation, missing evidence and stale review decisions stop execution.

Provider intent is durable before transmission. Outcomes distinguish not_sent,
completed, failed and transmission_or_completion_unknown. An unknown in-flight
request is retained and is never automatically repeated on resume. A later
explicit continue action can start a new request while retaining the uncertainty.
There is no invented provider idempotency guarantee.

## Current research authorization

The 7 November 2026 attached brief explicitly authorizes effectively unlimited
use of the existing provisioned DeepSeek account for this research. This campaign
has no aggregate model-request, token or spend cap. Optional deployment caps may
still be configured. Per-request time/size/output limits, bounded concurrency,
native resource limits, storage admission, cancellation and no-progress guards
remain operational safeguards. Reported cost zero requires an actual receipt;
an absent receipt or absent cost is unknown. No account/billing settings change.

Only authorized source observations are transmitted, with exact image hashes and
candidate/view provenance. Credentials come from the configured process secret,
never model input, files in the repository, CLI values or worker environments.
The earlier eight-call pilot and interrupted reservation remain historical
evidence and do not constrain this newly authorized campaign.

## Compatibility and rollback

The existing Python CLI remains available as an explicit comparison/fallback.
There is no hidden switch between control planes. New Rust tasks have their own
versioned state and are not relabeled legacy Python histories. Preserve original
records; use separate task roots when comparing or rolling back. The geometry
engine's metres-to-millimetres conversion and STEP reimport checks stay intact.
STL still carries no inherent units; its declared coordinate unit is millimetres.
