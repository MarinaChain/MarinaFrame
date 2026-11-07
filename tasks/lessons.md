# MarinaFrame lessons

### Keep source stable during pinned worker tests
- **Date:** 2026-11-08
- **Trigger:** W12 CAD finalization tests failed with `worker_implementation_changed` while another step edited or mutated `llm_setup.py`.
- **Rule:** Finish Python edits and restore mutations before starting a task or CAD integration test. Do not edit any Python module until that task ends. Re-run on stable source; do not weaken the implementation identity check.
- **Why:** `provenance.implementation_identity` hashes every Python module in the worker package, including modules outside the tested operation.
