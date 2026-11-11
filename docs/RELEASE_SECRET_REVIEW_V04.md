# Release credential and privacy preflight

The completed read-only preflight detected **no copy of the authorized OpenCode credential**, whether raw or in the common encodings checked. It found no local UI bootstrap/session/CSRF credential, bearer literal, private-key header, provider-key-shaped string, JWT-shaped string or signed-URL credential in the scanned scope. Two generic assignment-pattern findings were the same **synthetic provider test fixture** in the working tree and its reachable Git blob. No release-copy redaction is required by these findings.

This is a bounded preflight, not proof that every possible secret or personal datum is absent. The final newly locked evaluation material, delivery commits and packaged archives require another invocation before publication.

## Completed scope

| Pass | Scope and exact boundary | Result |
|---|---|---|
| Initial complete pass | Working tree at Git head `3c546c39dad9a1ed6ec13bbd488a9d9e9bc386cd`; all reachable objects; allowed terminal `artifacts/v04` evidence; completed dev1–7 snapshots and original dev8 trials01/02 | 18,960 scanned items including expanded archive members; 1,960,331,237 raw bytes and 1,269,815 expanded archive bytes; 62 archive members; zero scan errors |
| Terminal dev8 addendum | All six completed trials plus the remaining dev8 tree, both its release copy and `/tmp/marinaframe-v04-dev8` original | 2,744 scanned items; 76,595,496 raw bytes; zero findings, exclusions or scan errors |

A final limited addendum also scans the newly completed `artifacts/v04/live/accounting` evidence and rechecks `artifacts/v04/review` with the current reusable scanner. Its exact counts and cutoff are recorded in `late-evidence-addendum/report.json`; it produced no findings or scan errors. The separate addendum preserves the earlier scan records and does not imply that newly generated evaluation files were inspected.

The counts are **item visits**, not a count of distinct underlying contents. The addendum intentionally overlaps the original two dev8 trials. All six dev8 checkpoints were checked for terminal status before admission. The coordinator separately retained their strict integrity-verifier results and completed-copy hash checks; a secret scan does not replace those checks.

The Git pass selected 178 working-tree files and scanned **25 commits, 116 trees and 237 blobs** reachable from all refs and HEAD: **378 objects** in total. There were no reachable annotated tag objects to scan. Ref identities and HEAD were unchanged during that portion of the scan; the repository was not shallow. Git replacement objects and lazy fetching were disabled. Dangling/unreachable and reflog-only objects are outside this scope.

The locked final-live release copy at `artifacts/v04/live/final-evaluation` was included only after verifying its output-lock SHA-256:

`aa6c7fb5a6cb333b68ee9b1f2d1ba3a33f7ba063cc4aba0c1917fe73fa79070d`

For data evidence, the scanner used **exactly the 485 individual paths and hashes** in `artifacts/v04/data/release-allowlist.json`. A listed file had to match its expected hash before scan admission. The allowlist itself was admitted as control metadata. The entire `artifacts/v04/data/restricted/` directory was excluded without reading its files. No broad data-directory allow rule was substituted.

## Safe classification of the two candidates

| Location | Category | Disposition |
|---|---|---|
| `tests/test_agent_provider.py`, working tree | Generic assigned authentication-secret pattern | Synthetic provider test fixture; no redaction required |
| Reachable blob `ed5ff3ccf70c07ea3d31f87aea70998783553c70`, same path | Same pattern and same fixture contents | Synthetic provider test fixture; no redaction required |

AST inspection placed the literal in the `provider` helper, which constructs `FakeTransport` and `OpenCodeGoAgentProvider`. It is a human-readable hyphenated test literal, has no known service-key prefix, and does not match the authorized credential. The current fixture's Git object ID matches the historical finding. Its value is deliberately not included here or in the classification artifact.

The authorization comparison input was read only by the scanner's credential loader. The loader never printed the credential, emitted a credential hash, placed it in a subprocess argument/environment, or added the input file to the scan/release inventory. The scanner checks the raw value and common JSON, URL and base64 representations in memory. Reports contain paths, Git object IDs, categories and counts, with no matched values, snippets, offsets, token fingerprints or token hashes.

## Deferred material and packaging gate

The sealed-evaluation tree `artifacts/v04/evaluation` and `/tmp/marinaframe-v04-independent` were not opened by this scan. The following evaluation implementation files were also deferred pending the evaluator's output lock and permission:

- `benchmarks/v04_sealed_eval.py`
- `benchmarks/v04_amend_input_format.py`
- `benchmarks/v04_current_runs.py`
- `benchmarks/v04_legacy_runs.py`
- `benchmarks/v04_prepare_transfer.py`
- `docs/INDEPENDENT_EVALUATION_V04.md`

The initial report correctly retains dev8 as deferred at that time; the separate terminal addendum closes that specific gap. It does not retroactively edit the original report. Later source commits, evaluation results and release archives remain outside the original cutoff until rescanned.

The reusable scanner supports explicit archive-only runs and scoped addenda. It expands supported ZIP, wheel, NPZ and TAR-family containers without extracting files to disk. A restricted member or the credential input filename inside an archive is a release blocker; the member is not expanded. Packaged data that retains the `artifacts/v04/data/` path must satisfy the same exact allowlist and hashes. Renamed archive layouts require a separate inventory check against the release plan.

After all evaluation outputs are locked and the evaluator permits inspection, run a fresh full pass with `--include-locked-evaluation`, `--include-locked-final-live`, and `--include-terminal-dev8`. Add each actual final archive with `--archive`. For a separate final archive-only pass, use `--archives-only` with the same appropriate lock-admission flags. Supply the authorized key-file path with `--credential-file`; never put the key value on the command line. Use a fresh output directory for every invocation.

The current scanner exits with code 3 for a confirmed comparison-credential match or an unresolved scan/admission error. Exit 0 means that such a hard blocker was not observed; heuristic candidates still require safe classification, and deferred material remains unreviewed. It is not an automatic publication approval.

Any future real finding must name the precise release-copy exclusion or redaction. Original forensic evidence, its manifests and Git history must remain unchanged. A redacted derivative needs a new, explicitly labeled derivative manifest; regenerating an original manifest over altered contents is not acceptable.

## Detector checks and limitations

The current reusable scanner passed **26 synthetic checks**, without reading the real credential: 20 detector/encoding/boundary cases and six archive-admission cases. The archive cases cover an allowed file, an unlisted file, a changed allowlisted file, an excluded restricted member, an excluded credential-input member, and nested-archive secret detection. Earlier completed passes retain the exact scanner sources executed at their respective timestamps; later archive-admission improvements do not rewrite those records.

An initial CPU-bound implementation was interrupted before completing artifact traversal. Its source, partial log and explicit incomplete status are retained. The complete replacement added logically necessary literal prefilters before regex searches; it retained exact-key comparison over every scanned byte and all detection categories. No result is claimed for the interrupted pass.

Limits are explicit in each machine-readable report:

- 16 GiB raw-byte and 8 GiB expanded-archive budgets; 512 MiB per archive member; 64 MiB nested-archive buffering; 100,000 members; three nested archive levels. Errors or skipped members are reported rather than treated as clean results.
- No network, provider or native CAD calls. No original file or Git history modifications. Symlinks and nonregular members are not followed.
- Heuristic patterns can produce false positives and miss unknown formats. The checks are not general entropy analysis, exhaustive arbitrary encoding/decryption, screenshot OCR, or a semantic review for all personal information.
- Secrets visible only in raster pixels, encrypted containers, unsupported compressed formats, arbitrary obfuscation, or unscanned roots remain outside the claim. A zero-pattern result is not a guarantee of their absence.

Evidence and reusable tools are under `artifacts/v04/release/secret-review/`: `initial-preflight/`, `dev8-addendum/`, `late-evidence-addendum/`, `scan_release_secrets.py`, `test_scanner.py`, and `synthetic-checks.json`. `summary.json` binds the three reports and current tools. The initial safe classification is `initial-preflight/safe-classification.json`. Full scanned-item inventories and all exclusions are retained alongside each report.
