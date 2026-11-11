# Re-export finished runs

PM approved atomic refresh on 2026-11-12. Restored after worktree recreation.

## Design
Hold the run's controller lock from before reading state through atomic publication and post-publication ownership checks. Hard-link that locked inode into the private sibling staging copy so directory exchange never exposes an unlocked replacement inode. Roll back the exchange if post-publication checks fail. Use existing atomic directory exchange/publication helpers.

Preserve all existing geometry files, readings, sealed build results/manifests, identities, source inputs and controller events byte-for-byte. Add task-level provenance sidecars from existing evidence only; missing evidence is unknown. Preserve existing reviews and presentation; create neutral defaults when missing. Register existing run-held sheets; optional explicit sheet additions must use hash-pinned sources. Refresh packages from existing build outputs, never invoke reconstruction. Missing native CAD formats remain absent unless a conversion is explicitly implemented; report limitations. Engineering approval stays false.

Compared with a copied new run (path-rebasing risk) or independent bundle (new app resolution system), atomic refresh preserves app paths and existing checkpoint identity.

## Implementation steps
1. Add synthetic tests for immutable hashes, new derived records, unknown evidence, failure rollback and lock contention through publication.
2. Add Python re-export service and CLI. Bound inventories and reject symlinks/active runs. Stage exports, provenance, source-sheet registration, presentation and review defaults; write derived manifest/history. Restrict writes to derived paths.
3. Add app sidecar fallback and headless command routing. Test record reading.
4. Review, run targeted tests and background quick tier to completion. Commit/push lane only. Remove this worktree's target build directory after checks.

## Checks
No full Gunnerus builds, restricted data, holdouts or truth files. Command: `make test-quick PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python`.

## Implementation and review results
- Added Python service/CLI and desktop headless routing, task provenance sidecar readers, portable defaults, package refresh, manifest/history, and explicit `--cad-format iges|3dm` translations from existing STEP.
- Refresh accepts only the current finished revision. The app binds source sidecars to revision and result hash, and retains native records first.
- 17 synthetic Python tests pass; focused Rust source-sidecar test passes. Tests cover exact original bytes, hash inventories, unknown evidence, repeat identity, protected-file tampering, busy locks, lock inode continuity, post-publication lock loss, rollback failure snapshot retention, cleanup lock release, CLI and format conversion routing.
- Review found and fixed legacy review shadowing, recursive manifest hashing, rollback snapshot deletion, descriptor cleanup, and stale-revision source links.
- No CAD builds or real Gunnerus runs. Explicit converter routing is unit-tested; real STEP conversion is not exercised in this lane.
- Existing sheet registrations are retained. Missing drawings are not searched/rendered; the explicit hash-pinned add-run-sheets script remains separate. Tank/structure inputs are not inferred. Large task copies and explicit CAD conversions can take longer than seconds.
- Exception failures before commit restore the original tree. If rollback itself fails, the original sibling snapshot remains for recovery. Power-loss recovery across exchange is not added by this lane.
- No `.codesight` cache exists in this worktree. The refresh helper dry-run targets this worktree; actual refresh was skipped because its bootstrap downloads tooling and rewrites managed instruction files, outside this change's scope.

Final quick tier completed with exit 0 (`work/reexport/quick-final.log`): Rust format/clippy/tests, Python 1970 passed / 84 deselected (5 warnings), UI tests and secret scan (0 findings). Final Rust lint/quick rerun also exited 0 after revision-binding changes. The first quick attempt overlapped an unfinished format-test edit and failed that test (1967 Python passes); the completed targeted suite and final tier pass.

Resume: validation complete. Commit/push only lane/reexport-runs, then remove inspected untracked `target/` (3.7 GiB). No merge or PR.
