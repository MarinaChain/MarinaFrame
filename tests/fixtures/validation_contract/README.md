# Validation protocol fixtures

`passed.json` is the typed contract from a fresh native audit of the preserved
three-station synthetic-drawing STEP. Its earlier complete task included one
STEP build, reimported render, independent STEP section cuts and controller
finalization; the current contract was refreshed without rebuilding. Its maximum measured raw
source-sample-to-STEP distance was `0.0008965163934533248 m`. The full task,
source, context and observation are in the separate validation evidence at
`artifacts/v04/validation/`. These relative artifact references are examples;
the JSON file alone does not contain the bytes or prove their integrity.

`failed.json` is a controlled injected native-audit fixture, with a valid-shaped
candidate and a `0.01 m` trace distance that fails the unchanged `0.0011 m`
threshold. It deliberately uses test-double artifact bytes and does not claim
an actual invalid hull was measured. It tests that successful worker execution
and intact evidence can coexist with a failed geometric audit.

`failed-native.json` is a real native audit of the preserved 25-station
`holdout_multichine-241001-drafting` STEP. Its topology is valid, but its raw
source-sample-to-STEP distance is `0.043264475428473 m`, above the unchanged
`0.0011 m` threshold. Fresh, cached and restarted validation all remain false;
finalization remains blocked. No measurements are injected for this fixture.

All three records pass full JSON Schema Draft 2020-12 structure validation and the
Python exact-type/semantic contract validator. Each controller must also reject
mutated/missing fields and stale current identities, and check actual referenced
files before finalization. None of these records grants engineering approval.
