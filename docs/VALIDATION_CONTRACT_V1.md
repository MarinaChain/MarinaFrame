# Candidate validation and cache trust boundary

## The reproduced defect and first correction

The published 0.3 head `5b0b48e3dd9bcef25427d27ce800118935f58d1a` returned
`ok=true` for a cached audit whose `geometry_checks_passed` was false. A finish
decision trusted that envelope flag. `benchmarks/reproduce_validation_cache.py`
reproduced first validation false, second validation true, one audit call, and
controller status `awaiting_human_review` after two actions. Engineering approval
remained false. This is a controlled injected audit failure, not a measured
invalid real hull or a claim that professional approval occurred.

Commit `a36457a` applied the small correction before migration: cached and fresh
failure both return false, and finalization checks the nested validation fields.
The same controlled probe then stayed blocked. The continuation additionally
implements the complete typed contract below, artifact rechecks and revision
invalidation. Historical files and the first correction's evidence are retained.

## Authoritative result

`validate_candidate` retains its legacy observation and raw audit fields for
display, and adds `validation.contract`, version `marinaframe.validation.v1`.
The complete JSON schema is `schemas/candidate-validation-v1.schema.json`.
`validation_contract.py` adds checks that JSON Schema alone cannot establish:
actual artifact hashes, current-candidate identity, authoritative audit-file
agreement, independent error arithmetic and consistent individual checks.

A review-ready candidate requires all of the following:

1. A complete exact-schema report for the current generation **and revision**.
2. Successfully completed native validator execution and intact evidence.
3. Reimported STEP validity: one valid solid, one closed shell, millimetre STEP
   units, positive finite metre-based measurements and at most `1e-6` relative
   disagreement with the immutable engine record.
4. The retained raw source-sample-to-STEP-section audit passes its unchanged
   `0.0011 m` maximum-distance threshold at every sampled section.
5. The envelope, raw native audit, typed contract and artifact bytes agree.
6. Human semantic review remains required and engineering approval is false.

A successful validator process may return failed geometric checks. The typed
statuses make this explicit:

```json
{
  "checks": {
    "worker_execution": "succeeded",
    "artifact_integrity": "passed",
    "cad_validity": "passed",
    "trace_fidelity": "failed"
  },
  "outcome": "failed",
  "semantic_review": "required",
  "engineering_approved": false
}
```

The automated controller may display that candidate diagnostically, but it
cannot finish it as `awaiting_human_review`. Native-worker failure/interruption
has no completed validation contract and cannot inherit a prior pass.

## Contract fields

All fields are required. Unknown fields, versions and enum values are rejected.
Boolean checks are exact JSON booleans; `1`, `0`, strings and null are invalid.
Nonfinite measurements, inconsistent units, missing section IDs, duplicate IDs,
incomplete coverage, unsupported tolerances and contradictory conclusions fail.

| Field | Meaning |
| --- | --- |
| `schema_version` | Exactly `marinaframe.validation.v1` |
| `audit_contract_version` | `step_source_sections_v1` for a single-solid run; `step_source_regions_v2` for a region run (see below). The run record decides; the contract cannot choose |
| `binding` | Current generation/revision/run identity and all required content digests |
| `checks` | Separate worker, integrity, CAD-validity and trace-fidelity statuses |
| `outcome` | `passed` only when both geometric checks pass; otherwise `failed` |
| `units` | Input and reporting in metres, STEP coordinates in millimetres |
| `tolerances` | Fixed `max_section_distance_m=0.0011` and `max_relative_metric_error=0.000001` |
| `sampling` | Fixed policy, ordered unique sampled station IDs and total station count |
| `measurements` | Maximum sampled distance and STEP-to-record relative metric error |
| `evidence` | Confined relative paths, artifact kinds, exact byte counts and SHA-256 digests |
| `semantic_review` | Exactly `required` |
| `engineering_approved` | Exactly false |

The binding includes `generation_id`, `revision_id`, `run_id`,
`source_manifest_sha256`, `input_spec_sha256`, `selection_sha256`,
`revision_spec_sha256`, `run_manifest_sha256`, `run_result_sha256`,
`step_sha256`, and `audit_implementation_sha256`. The implementation digest
includes the audit/contract/verification/geometry modules and installed CadQuery,
OCP and NumPy versions. Changes therefore invalidate conclusions produced by a
different audit implementation; this is a cache identity, not a signature.

Bound evidence includes captured input/submitted specifications and source bytes,
the selected revision's specification and selection record, native run manifest,
immutable result and exported STEP, raw audit JSON, actual section comparisons,
and the native audit worker's observation/usage receipt. The engine's captured
submitted-specification digest must equal the current revision file's digest.
Calibration and source-selection edits cannot reuse a prior result unnoticed.

The raw audit JSON is authoritative native evidence. Replacing only cached
metadata, even with a plausible `outcome=passed`, cannot override it. On every
cache hit and finalization, the code reopens/rechecks bound artifacts and checks
the raw JSON against the cached fields. Missing or changed files do not trigger
an automatic lucky re-audit; the old cached report stays preserved and blocked.

## Controller integration

`DomainTools.validation_context()` reloads the persistent domain checkpoint,
checks captured inputs, verifies the current immutable native run and returns
current binding, evidence, sampling, section metadata and engine measurements.
It does not compute a new audit or erase a failure.

The Python finish path retains `DomainTools.validation_guard()` from fresh
context construction through `ready_for_review(observation, context, task_dir)`
and the review-ready event commit. A second allowed domain selection cannot
advance the revision between the check and that commit. Cancellation and the
wall deadline are checked again inside the guard after the predicate. A
snapshot returned by `validation_context()` alone is not an atomic finish.
A permissive tool envelope is insufficient.
The Rust controller must enforce the same contract independently and hash-check
the references; it must not call the Python Harness to delegate state authority.
Protocol golden fixtures distinguish controlled serialization tests from real
native CAD measurements.

Generation identity alone is insufficient. Selecting A, then B, then A creates
a new revision. The third selection must produce a new revision-bound build;
it cannot reuse the first A build as a current candidate. Rendering an older
preserved candidate is allowed for comparison, but it is stale if either its
generation or revision differs, and it cannot satisfy current validation.
Checkpoint revisions must be exact nonnegative integers bounded to eight
digits; booleans, floats, strings, null and out-of-range values cannot inherit
a cached revision identity.

## Compatibility and interpretation

Old 0.3 records are retained without rewriting their history or claiming this
stronger contract was previously enforced. A legacy cached validation lacks the
new binding/evidence contract and is not accepted by the new finalization gate.
Use the recorded source in a new task for new assurance. The frozen published
0.3 source remains the historical comparison/rollback implementation.

The sampling policy is first two stations, middle station and last two stations,
with duplicate indices removed. It is bounded, not an exhaustive surface audit.
Distances measure raw selected source-centre samples to actual reimported STEP
section boundaries. They do not establish source interpretation correctness,
independent vessel accuracy, professional review, or engineering certification.
The old terminal-spur failure and the raw `1.1 mm` threshold remain unchanged.
Any future material-boundary interpretation must use a separately versioned
contract and report the original raw score as well.

Local hashes and exclusive controller locks detect inconsistent records and
ordinary concurrent/interrupted changes. They do not authenticate a professional
or defeat an actor who controls the host and rewrites every file and hash.

## Region runs (`step_source_regions_v2`, 2026-11-07)

A section spec may declare `pieces` (1..8 drawn curves, each an explicit corridor and height
interval; an `inner_selection` makes an offset piece such as a skeg). The reader closes each piece
into a ring and decomposes the rings into regions (`section_regions.py`); `build_region_hull` lofts
matched regions into a compound of closed solids. Such a run carries `metrics.region_loft`, and its
audit uses `step_source_regions_v2`. Tolerances, units and sampling are the v1 values. Additions:

- `geometry_audit` adds `expected_solid_count` (must equal the run's `metrics.solid_count`),
  `solids` (each reimported solid: volume, validity, shell count, closed shell; sorted by volume) and
  `solid_volume_relative_error` (sorted reimported volumes against the engine's
  `region_loft.solid_volumes_m3`). CAD validity needs every solid valid and closed with one shell,
  the engine's solid count, and both relative errors at most 1e-6.
- Each sampled section adds `pieces` (per piece: index, sample count, maximum distance); the
  section maximum must equal the largest piece maximum. The STEP cut joins cuts 0.1 um aft and
  forward of the station, so a solid that ends on the station plane is included.
- The validation context adds `regions` (contract version, engine solid count, sorted solid
  volumes, per-piece sample counts of the sampled sections). Python and Rust recompute it from the
  run record; a region run without it, or a v1 claim for a region run, is refused
  (`audit_contract_version_not_current_run`, `context_regions_not_current_run`).

Single-solid runs keep the v1 contract, the v1 context and the v1 observation identity
(`run_record.observed_geometry`), so earlier receipts still verify.
