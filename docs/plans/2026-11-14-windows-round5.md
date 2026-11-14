# Windows Round 5

## Baseline and boundaries

Merged local continue/v0.5 to `8a23b84` before edits. Last Windows suite: 33 failed, zero errors, 2,802 passed, 128 skipped. No new skips. No restricted holdout/sealed source or truth inspection, and no expected checkpoint hash changes. No CFD edits. All edits stay in this worktree and lane branch.

## Gates set before runs

1. Remaining ordinary portability failures fixed without adding skips; full native failure count recorded, including restricted summary-only failures if still present.
2. Package replacement, private pooling and trusted isolated inspection implemented in that order, with Windows/Linux/macOS native contracts; remove their capability skips only after parity is tested.
3. Keep no-clobber/durability, reader consistency, private ACL/ownership/no-reparse, descendant cancellation/resource limits; do not implement weaker fallbacks to turn tests green.
4. Commit each small step. Background quick tier logs under work/windows-portability/round5-*.log; use main venv and private identity denylist. Push lane/windows-portability only; no merge back.
5. Inventory actual Windows skips by exact reason/count after native run. Distinguish OS-specific tests from unimplemented product capabilities; do not call a feature impossible merely because Python lacks the POSIX API.

## Work order

### 1. Remaining 33 failures

Baseline groups (summary metadata): POSIX-only lifecycle test probes/patches and resource receipts 11; path/text serialization and assertions 8; restricted/frozen checkpoint hashes 5 (do not investigate restricted entries); progress lock 3; invalid Windows wildcard filenames 2; FIFO probes 2; wheel backend 1; ordinary frozen reader hash 1 (hash group total includes five summary checkpoint failures). Reconcile exact groups before final report.

Start with portable progress locking and path/text fixes. Existing runtime security-cap unit tests must simulate a supported backend rather than depend on absent Windows signal symbols. FIFO tests need a native special-file probe, not a skip. Invalid wildcard test cases should assert a clear unsupported filename rejection on Windows while retaining literal-name recovery on POSIX.

### 2. Package replacement

Immutable generations with one atomic/write-through current-generation file; resolve once per reader operation. Preserve old generations for active readers. Migrate export readers and recovery; no multi-rename replacement of populated directories. Test interrupted writes, readers racing publication, symlink/reparse refusal and old package preservation on all three OSs. Remove atomic-exchange feature gate.

### 3. Private pooling

Per-user SID/DACL private directory; validate ownership/allowed access via native security descriptors; no reparse token opens; native byte locks release on process death. Keep POSIX mode/uid/flock unchanged. Test cross-process bound, foreign/shared directories and crash release. Remove private-pool capability gate.

### 4. Trusted isolated inspection

Windows Job Objects with suspended-process assignment before execution, process-tree lifetime, cancellation, identity and enforceable resource quotas. Hostile model code still needs separate sandbox policy; never confuse trusted isolation with sandboxing. Test child/grandchild cleanup, abrupt parent exit, quotas and receipts. Remove isolated-inspection gates after native parity.

## Review

Architecture WARN: package format migration requires consumer inventory before implementation. Security PASS for unchanged contract; native implementations need adversarial tests. Tests WARN: local mocks are not Windows evidence. Performance PASS: retain bounded operations and avoid artifact copies.

## Resume

- Portable blocking progress lock committed as `bda75eb`: retains POSIX flock, Windows uses byte lock with waiting. Red regression observed before implementation; focused lock/progress tests 34 passed.
- Portable path serialization/order and Make path assertions: focused tests 39 passed. UTF-8 performance report output: 13 passed. Windows wheel-test backend installed explicitly (setuptools/wheel), not skipped.
- First native check: **25 failed, 2,811 passed, 128 skipped, zero errors**. Linux **2,944 passed, 20 skipped**. No new skips. Package/private pool/isolated inspection implementations not started.
- Skip inventory reconciles exactly to 128: **55** secure lifecycle (work not done); **36** secure no-follow reads (work not done); **6** atomic package replacement (work not done); **6** private pool (work not done); **4** Linux-kernel-specific sandbox tests (that exact kernel API is OS-specific, Windows sandbox equivalent work not done); **5** macOS sandbox/part-revise tests (Seatbelt itself is macOS-only, equivalent Windows product support work not done); **1** POSIX UID-specific test (exact UID API OS-specific); **15** missing tools/data (5 raster sources, 4 schema/xmllint, 2 OCX samples, 2 licensed drawing fixtures, 1 tesseract, 1 sample). Missing tools/data are environment provisioning, not impossible Windows features. No product capability in this inventory is claimed genuinely impossible on Windows.
- Follow-up ordinary output tests: decode UTF-8 explicitly and render comparison labels with POSIX separators. Native result pending.
Resume: run quick tier on these stable changes, push, inspect native failures and skip inventory; continue remaining failure groups before feature migrations.
