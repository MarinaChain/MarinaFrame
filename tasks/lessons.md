# MarinaFrame lessons

### Freeze executable and Python source for concurrent evaluation
- **Date:** 2026-11-08
- **Trigger:** W11 `make test-full` rebuilt `target/release/marinaframe` while a live benchmark used it. The controller correctly stopped at `controller_binary_changed`. The smoke target also lacked `--worker-source`, so its cleared environment could use the main checkout's editable Python install.
- **Rule:** Copy the evaluation executable to `work/` before starting batches and point every arm at that immutable copy. Freeze the Python worker source too. Always pass `--worker-source` for worktree runs, including smoke. Do not rebuild or clean an executable used by active runs. Keep interrupted attempts and their usage; label retries separately.
- **Why:** A git commit label does not pin executable bytes or the source imported by an editable Python installation.
