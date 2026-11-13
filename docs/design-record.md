# Design record v1

Frozen v1 contract: `schemas/design-record-v1.schema.json` (`1.0.0`).
The separate `schemas/design-record-v1.1.schema.json` contract (`1.1.0`) adds
`g CO2/(t nm)` for emitted efficiency indices and `nm` for distance inputs.
No other fields, units or semantics change. Both schemas ship in the wheel.

## Python

Install the project's `data` extra. Import `DesignRecord`, `quantity`,
`capture_result`, and `restore_result` from `vessel_reconstruction.design_record`.
`DesignRecord.from_dict(data)` validates and copies a record. `load(path)`,
`save(path)`, `loads(text)`, `to_dict()` and `to_json()` provide JSON transport.
The schema is installed under `share/marinaframe/schemas` for wheel deployments.

## Rust

`marinaframe_app_core::design_record` exports serde structs and the embedded
canonical schema. Use `DesignRecord::from_json` and `to_json` for validated
transport. Direct serde deserialization gives structural checks only; it is not
the supported validation entry point. Public fields allow editing, but save
rechecks the complete contract. The schema evaluator supports only the vocabulary
used in this contract, not arbitrary third-party JSON Schemas.

For a stdin/stdout bridge:

```sh
cargo run --locked -p marinaframe-app-core --example design_record_roundtrip < record.json
```

## Content and extension points

All top-level sections are required. Empty lists/maps and explicit null values
mean not supplied, not calculated zero. `midship_section_inputs` contains inputs
only: no strength result is implied. `results.stability` is an empty map until a
method supplies evidence. File references have lowercase SHA-256 content hashes;
the loader checks the hash format, not file existence or content.

Components contain named quantities, text labels, files and notes. Store computed
numbers in `quantities`, not text labels. Quantity maps intentionally permit new
names, but each value must conform to the quantity contract. Structural unknown
fields fail. Numeric values use SI units, with tonnes, kW and daily fuel accounting
as stated in the unit enumeration. Speed carries both knots and m/s, checked at
1e-12 relative/absolute tolerance. `1` means dimensionless. Absolute uncertainty
bounds use the quantity unit; relative bounds are fractions. Lower/upper are
nonnegative deviations from the stated value, not endpoint coordinates. Unknown
uncertainty must be null with a nonempty reason.

Solver result evidence is recursively tagged as quantity, text, flag, missing,
list or object. This preserves source output, warnings, method inputs and arrays
without storing opaque JSON numbers. `capture_result` requires explicit numeric
field units; it never guesses or silently drops a field. Capture each method with
its own method/version/source metadata. `restore_result` recovers the original
JSON values. Tuple/list distinctions are intentionally normalized by JSON.

## Version and migration policy

There is no implicit migration. Readers select the schema from the declared
`schema_version`, accept `1.0.0` or `1.1.0`, and preserve that version on save.
The Python `SCHEMA_VERSION` default stays `1.0.0` for existing builders. New
fields or changed semantics require a new schema version.

Python `migrate_v1_0_0_to_v1_1_0(data: dict) -> dict` and Rust
`migrate_v1_0_0_to_v1_1_0(source: &serde_json::Value) -> Result<Value, String>`
validate a `1.0.0` source, copy it, change only `schema_version`, and validate the
`1.1.0` target. The input is not modified. No quantity is converted, inferred or
repaired. Keep the original record for audit. Unknown fields fail instead of
being discarded. Do not use serde defaults to fill absent required fields.

## Scope and decisions

Public/synthetic scope requires a null customer ID. Customer scope requires an
ID and permitted uses. This label is not an access-control boundary. Storage,
query, source resolution and authorization must enforce customer separation before
customer records are used. A parent design ID must be resolved within the allowed
scope by that service; this module makes no cross-customer queries.

Designer decisions record accepted/deferred/rejected choices with a reason,
designer ID and timestamp. These are choices, not engineering clearance. Record
and quantity status is always draft or review_required; engineering_approved is
always false.

## Public example limits

`scripts/build_design_record_example.py` reads only public KVLCC2 IGES geometry.
It computes a +1% Cb retained-shell variation and hydrostatics, plus a separate
full-vessel Holtrop baseline with explicit illustrative propulsion/SFOC inputs.
The trimmed shell is not a full KVLCC2 reconstruction. No measured resistance or
holdout truth is used, and no accuracy claim follows from a serialization test.
