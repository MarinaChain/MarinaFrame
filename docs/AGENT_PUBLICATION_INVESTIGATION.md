# Publication investigation: delayed workspace state restoration

## Finding

Eight bounded runs of the exact reviewed baseline reproduced a location-dependent evidence failure. **All four runs published directly under the workspace became invalid after initially verifying. All four equivalent `/tmp` runs remained valid.** In the delayed workspace probe, verification passed immediately and after 0.5 seconds, then failed at 1, 2 and 3 seconds while the same observing command was still running. Command completion is therefore not required for the observed failure.

The failed workspace outputs retained their completed final directories and unchanged final file hashes/inodes. Previously removed run reservations and partial staging directories reappeared beside them. The reservations described an earlier `section_extraction` phase, with older modification times and later change times. The unchanged verifier correctly rejected these destinations as pending or unconfirmed publication.

This establishes a reproducible failure mechanism involving delayed restoration of transient workspace artifacts. It does **not** identify the external actor or prove its complete implementation. A separate preserved domain failure contains `.rsync-tmp/transaction.json` in its sealed inventory although that path later disappears and `transaction.json` reappears. That is concrete evidence consistent with synchronization interference, but the investigation does not attribute it to a particular daemon or vendor.

## Exact scope and controls

The tested source checkout is `marinaframe-reviewed-baseline`, commit `2b9ab4f905aff3dbbfed9a8c134ea85fad766546`. All ordinary probes used the existing clean DTMB5415 raster-section specification and the supported isolated CLI:

```text
python -m vessel_reconstruction reconstruct SPEC --out NEW_OUTPUT
```

The interpreter was the pinned hardening release environment, with `PYTHONPATH` selecting the reviewed checkout and `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`. Each run reached the known contour block in about four seconds, so these probes did not perform native CAD construction. They were executed sequentially. No core source, existing result, lock, stage, manifest, or recovery state was modified. Every destination was new.

`/tmp` and the workspace both reported device number 27 in this runtime. This is an observed path/context contrast, not a demonstrated contrast between filesystem types.

The original 47-case rerun had 21 immediate integrity rejections with the same pending/durability message. That observation motivated the reproduction; the 47 cases are not mixed into the eight-probe denominator.

## Results

| Experiment | Ordinary engine runs | Immediate verification | Later verification | Observation |
| --- | ---: | ---: | ---: | --- |
| Alternating workspace destinations | 3 | 3/3 valid | 0/3 valid after subsequent observation | Reservations and partial stages reappeared; final hashes/inodes unchanged |
| Alternating `/tmp` destinations | 3 | 3/3 valid | 3/3 valid | Exact inventories unchanged |
| Workspace with in-command delays | 1 | 1/1 valid | Invalid by 1 second | Passed at 0 and 0.5 seconds; failed at 1, 2 and 3 seconds |
| `/tmp` with in-command delays | 1 | 1/1 valid | 1/1 valid through 3 seconds | All five observations valid |
| Import completed `/tmp` records only | 0 new runs; 3 copies | 3/3 valid | 3/3 valid across a separate tool boundary | Exact hash inventories unchanged; no transaction siblings reappeared |

The ordinary-run total is eight. An earlier batch of six attempts to use `strace` never started the engine: the runtime denied `PTRACE_TRACEME` and `PTRACE_SETOPTIONS`. Their error receipts are preserved, they are excluded from the engine-run counts, and no privilege escalation or alternate tracing bypass was attempted. No syscall trace was obtained.

## Evidence package

Everything is under `artifacts/agentic/publication-investigation/`:

- `probe.py` and the first `within-command.json`: attempted tracing and exact denial receipts.
- `untraced/probe.py`: the ordinary reproduction driver.
- `untraced/within-command.json`: pre-run and immediate post-run inventory hashes, file stats, command outputs, and unchanged verifier results for six ordinary runs.
- `untraced/after-tool-return.json` and `pre-post-diff.json`: later observations and exact appearing/changed paths.
- `untraced/reappeared-lock-details.json`: earlier phase, modification/change times, and final inode comparisons.
- `delayed-within-command.json`: the two additional runs with 0, 0.5, 1, 2 and 3 second observations.
- `completed-import-within-command.json` and `completed-import-after-tool-return.json`: the three-copy mitigation check.
- Original failed workspace records, stages and reservations remain preserved. The successful `/tmp` records remain available at the recorded paths, with completed copies under `completed-imports/`.

The earlier independent domain failure remains at the preserved `harness-domain-evidence/native-tool-test-v2/` location recorded by the domain worker. Its inventory was inspected read-only. No cleanup or recovery was run on it.

## Concrete mitigation and limits

Run active native reconstruction/staging in a private temporary execution directory. Keep source inputs immutable. Once the worker has returned, verify the terminal record under the original strict checks; then copy only the complete terminal directory into a fresh workspace destination. Verify the copied evidence and check it again after synchronization has had an opportunity to act. Preserve the original execution directory and failure receipts until the imported result is confirmed.

The three completed-only imports passed this sequence. The result supports this environment-specific execution strategy; it is not a general proof that temporary storage can never race or that an external synchronization service has been repaired.

Do not fix the symptom by accepting leftover reservations, silently deleting stages, ignoring arbitrary temporary files in the immutable inventory, overwriting completed records, or weakening content verification. Those changes would erase the evidence of a real inconsistency. The existing gate's refusal is useful behavior.

The remaining unresolved question is which component restores the stale workspace artifacts and under what broader conditions. The narrow reproduction is complete; more optional repetitions are not needed to justify the tested mitigation. A platform-level investigation would require visibility beyond the denied tracing capability. Production readiness should not be inferred from this mitigation or from a clean unit-test total.
