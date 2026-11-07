# Historical 0.3 validation-cache probe

`benchmarks/reproduce_validation_cache.py` was removed in 0.5 together with the Python Harness it drove. This note keeps its result.

## What the probe did

It injected a failed geometric audit into the real `DomainTools` cache and the Harness finish path of the published 0.3 head `5b0b48e3dd9bcef25427d27ce800118935f58d1a`. It was a controlled state-machine reproduction. It was not a measurement of a real invalid hull. Engineering approval stayed false.

## Recorded output (published 0.3)

| Field | Value |
| --- | --- |
| `first_ok` | `false` |
| `second_ok` (cache hit) | **`true`** (the defect) |
| `cached_geometry_passed` | `false` |
| `audit_calls` | 1 |
| `controller_rejections` | 1 |
| `controller_actions` | 2 |
| `final_controller_status` | `awaiting_human_review` (wrong) |
| `engineering_approved` | `false` |

Expected output after the minimal fix `a36457a`: `first_ok` and `second_ok` both `false`, final status `blocked`. See `docs/VALIDATION_FIX_RESULTS.md` and `docs/VALIDATION_CONTRACT_V1.md`.

## Where the defect is guarded now

- `rust-control/tests/finalization_guards.rs` (finish path, restart, permissive envelope, selection race, cancellation).
- `tests/test_validation_cache.py` (cache semantics of the typed contract in `DomainTools`).

The full 0.3 result file was kept outside the repository (private handoff folder) and is not copied here.
