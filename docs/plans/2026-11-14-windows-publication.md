# Windows Run Publication — Round 4

## Goal and fixed gates

Merged local continue/v0.5 by fast-forward to `09cf7f0` before changes. Baseline Windows: **101 failed, 43 errors**, 2,666 passed, 128 skipped.

Gates set before native run: native Windows publication contract passes without skips; all 43 evidence fixture setup errors disappear; no new skips; Linux and macOS publication contracts pass; required local quick tier passes. Full suite counts remain visible even when unrelated tests fail. Commit small steps; push lane/windows-portability only; no merge back.

## Design and platform guarantees

Runs are immutable and always publish to a **new** name. They do not require swapping two existing populated directories. Keep the existing on-disk format and its verifier/recovery reservation gate; a pointer migration is unnecessary for this contract.

| Platform | Visibility/no-clobber | Durability and failure |
|---|---|---|
| Linux | same-filesystem renameat2(RENAME_NOREPLACE); target collision preserves stage and target | files fsync, stage/parent directory fsync; success withheld on required flush failure |
| macOS | same-filesystem renamex_np(RENAME_EXCL); target collision preserves both | existing file/directory fsync behavior unchanged; no claim against hardware that ignores flush |
| Windows local filesystem | same-volume MoveFileExW(stage,target,MOVEFILE_WRITE_THROUGH), **without** REPLACE_EXISTING or COPY_ALLOWED; one namespace rename of completed stage; existing target refused | file contents FlushFileBuffers via writable handles; write-through move requested; directory flush attempted where supported, documented lack of portable directory-entry flush remains. Reservation blocks verifier until commit cleanup. No copy/delete or non-atomic replacement fallback. Network filesystem/power-loss guarantees depend on filesystem/device; do not claim stronger guarantees than Win32 provides. |

Mutable JSON files on Windows use a completed/fsynced temporary file and MoveFileExW(REPLACE_EXISTING|WRITE_THROUGH). Existing JSON is not deleted before replacement.

Windows reservation handles must allow delete sharing while remaining locked. Use native CreateFileW with OPEN_REPARSE_POINT, reject reparse/non-regular handles, then transfer ownership to a CRT descriptor. POSIX O_NOFOLLOW/flock paths remain unchanged. Read recovery JSON from the already-held descriptor so Windows byte-range locking does not block a second open. Never unlock-before-delete to work around sharing violations.

## Steps

1. Add native publication tests: complete stage, collision with file/directory, abandoned stage recovery, Win32 flag/error mapping. Run red regression before implementation.
2. Implement native move and reservation handle boundary; use it in transaction and JSON replacement. Run focused publication/evidence tests and commit.
3. Run publication contract in a Windows/Linux/macOS CI matrix (no skips); local quick tier in background with log. Push only lane branch and read native results with commit-matched run IDs.
4. Record counts and remaining failures. No new skips.

## Capability review and next rounds queue

All reviewed gates mean **not yet implemented**, not that the product feature is impossible on Windows.

| Feature | Windows path to parity | Estimate (engineering days incl. tests) |
|---|---|---:|
| Isolated inspection/native workers | Job Objects with kill-on-close, descendant ownership, memory/CPU quotas and cancellation; sandbox untrusted code separately with restricted tokens/AppContainer or equivalent | 5–8 for trusted isolated inspection; 8–15 extra for hostile-code sandbox parity |
| Atomic replacement of existing export package | immutable generation directories plus one write-through manifest/pointer file replacement; migrate consumers/recovery and retain old generation until safe cleanup | 3–5 |
| Private shared worker pool | private per-user directory with checked DACL/SID, non-reparse token handles, Windows byte locks and process-death release | 2–4 |
| Secure descriptor-relative reads (related gate) | native relative handle opens, reparse rejection at every component and file-type checks; bounded reads | 3–5 |

Estimates are focused implementation ranges, not commitments. Existing skips remain a temporary queue, not a Windows support claim. No new skips in this round.

## Review and resume

Architecture PASS: new-name publication uses the native no-replace move, no format migration. Security PASS: preserve no-clobber and locked reservation removal. Tests WARN until all native matrix results exist. Performance PASS: no copies of artifact trees and no unbounded retries.

Regression: four native POSIX contract tests passed; two Windows boundary tests failed because move_windows_path was absent.
Native publication implementation committed and pushed. First native run: publication contract **8 passed on Windows, macOS and Linux**; Linux full probe **2,942 passed, 20 skipped**; Windows **96 failed, 2,695 passed, 128 skipped, 43 errors**. Atomic publication errors are removed. The 43 setup errors now reach a different blocker: implementation_capture produces Windows backslash keys that safe_relative_file correctly rejects. Follow-up uses Path.as_posix for generated evidence keys only; no validator relaxation, no skips. Snapshot regression added to the three-platform contract. Follow-up `00b60ff` native results: **Windows 33 failed, 2,802 passed, 128 skipped, zero errors** (1,066.42 s). All **43 fixture setup errors removed**, no collection errors and no new skips. Native publication plus snapshot contract **9 passed on each of Windows, Linux, macOS**, with no skips. Linux full probe **2,943 passed, 20 skipped**. Required local quick tier: **2,829 Python passed, 4 skipped, 130 deselected; UI 275 passed, zero failed; Rust checks passed; bounded secrets and private identity zero findings**. Gates met for publication; full Windows suite remains failing on 33 unrelated/remaining portability tests.

## Final counts and resume point

| Windows | Failed | Errors | Passed | Skipped |
|---|---:|---:|---:|---:|
| Before round 4 | 101 | 43 | 2,666 | 128 |
| Native publication implementation | 96 | 43 | 2,695 | 128 |
| Portable implementation evidence keys | **33** | **0** | **2,802** | **128** |

Net **68 fewer failures and all 43 errors removed**. Guarantees are limited as documented above; do not claim power-loss guarantees beyond the OS/filesystem. No new skips and no POSIX security relaxation. Capability estimates above are the next-round queue, not impossibility claims. No merge back. Resume only on a new task: re-rank the remaining 33 native failures; prioritize real Windows feature implementations from the queue rather than expanding capability skips. Preserve shared Rust target; this worktree has no local target folder.
