# MarinaFrame lessons

### Freeze executable and Python source for concurrent evaluation
- **Date:** 2026-11-08
- **Trigger:** W11 `make test-full` rebuilt `target/release/marinaframe` while a live benchmark used it. The controller correctly stopped at `controller_binary_changed`. The smoke target also lacked `--worker-source`, so its cleared environment could use the main checkout's editable Python install.
- **Rule:** Copy the evaluation executable to `work/` before starting batches and point every arm at that immutable copy. Freeze the Python worker source too. Always pass `--worker-source` for worktree runs, including smoke. Do not rebuild or clean an executable used by active runs. Keep interrupted attempts and their usage; label retries separately.
- **Why:** A git commit label does not pin executable bytes or the source imported by an editable Python installation.

### Keep source stable during pinned worker tests
- **Date:** 2026-11-08
- **Trigger:** W12 CAD finalization tests failed with `worker_implementation_changed` while another step edited or mutated `llm_setup.py`.
- **Rule:** Finish Python edits and restore mutations before starting a task or CAD integration test. Do not edit any Python module until that task ends. Re-run on stable source; do not weaken the implementation identity check.
- **Why:** `provenance.implementation_identity` hashes every Python module in the worker package, including modules outside the tested operation.

### Separate supplied calibration from independent model measurements
- **Date:** 2026-11-08
- **Trigger:** W14 combined half-breadth and grid-scale questions in one request. The breadth question supplied the scale that the scale question was meant to measure.
- **Rule:** Ask independent scale questions in separate requests without supplied scale. Exclude contaminated answers, retain their usage, and keep planned case denominators fixed when a driver fails. State which crop, axes and scale are caller-supplied.
- **Why:** A model can copy supplied calibration without reading the grid; returned-only denominators also hide missing measurements.

### Refuse mixed strokes without erasing review alternatives
- **Date:** 2026-11-08
- **Trigger:** The sysser45 identity fix first removed all sustained ruler overlaps. It promoted formerly ambiguous sole candidates and broke real-CAD tests that require an explicit complete-ruler alternative.
- **Rule:** Keep competing source evidence before refusal. Reject the mixed ruler/hull path, not every complete ruler hypothesis. Preserve explicit operator alternatives and check both policy selection and real-CAD revision tests. Count source-complete reads separately from controller builds and correct builds.
- **Why:** Removing a candidate changes selection authority; it can silently promote another trace or remove a valid review operation even when the main wrong build abstains.

### Reach the forbidden operation in sandbox tests
- **Date:** 2026-11-08
- **Trigger:** W13 file/network tests first passed on Python import-path denial; socket construction was also mistaken for a network operation.
- **Rule:** Use isolated Python for direct OS probes, require the expected forbidden-operation failure, and mutation-check the exact file or network permission. Test bind/connect, not only socket construction.
- **Why:** An earlier permission error can hide a missing guard; Seatbelt permits socket construction without permitting network use.

### Count plan crossings before combining scan columns
- **Date:** 2026-11-08
- **Trigger:** W15 review found that taking the darkest pixel across a three-column strip merged two diagonal waterline crossings into one run and accepted an anchor on white station-column pixels.
- **Rule:** Count ink runs separately in each scan column. Refuse any competing crossing, and measure the accepted anchor on the actual station column. Test diagonal competitors as well as separated horizontal strokes.
- **Why:** A union of neighbouring pixels loses stroke multiplicity; apparent strip continuity does not establish unique station-column evidence.
