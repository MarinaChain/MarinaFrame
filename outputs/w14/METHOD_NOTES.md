# W14 method notes and resume state

## Frozen data recovery

Only the 40 W12 development cases were rendered. All final drawing hashes match the frozen case manifest (drawing_hashes.json). The worktree did not have work/sources. Public sources were downloaded into this worktree only.

- DTMB 5415: frozen HTTP URL in hulls.json; SHA-256 daae8a4bca5e586721f2ee71285d390625ec299782d5ee45a4fb22a4e789f50c. HTTPS failed certificate validation; the frozen HTTP archive was fetched and its exact hash checked. Certificate checks were not disabled.
- Series 60 and Wigley: frozen FreeCAD commit URLs in hulls.json; both archive hashes match.
- Ship-D vectors: Harvard Dataverse DOI 10.7910/DVN/MMGAUS, original constrained-set CSVs. Example selected vector hash matches the frozen manifest. The Dataverse generator has old NumPy empty-array comparisons. A backed-up compatibility probe ran but did not reproduce drawing hashes. The published GitHub generator at noahbagz/ShipD commit a281d92958451a2c8c4ac1efe6056fcf804fe6e0 reproduces all 28 Ship-D drawing hashes. It is used for final renders. No frozen data or manifests were changed.

## Request provenance

Every actual model request uses the Rust worker and its per-request bounds. All receipts, including failed probes and original attempts, are included in final accounting. Preflight rejections such as 4096-wide image_dimension_limit do not send a provider request; driver_error.json records these separately. Source-size 2048 and 4096 square probes are explicitly downsampled to 896 square attachments.

The first calibration prompt omitted the literal JSON keyword. Some upstream routes rejected it with HTTP 400. This was diagnosed from bounded retained response bodies and fixed; those calls remain in accounting. The worker now retains bounded response bodies for all purposes, never a body that echoes the selected key.

## Setup evaluation

The first normalized 40-case run is the primary after table. It is not replaced with successful retries. Eleven cases ended in driver exceptions: nine out-of-range frame answers and two preflight crop-directory collisions. Rejection handling and unique request-directory numbering were then repaired; separate retries verify graceful failure. Raw original records remain unchanged. No result from a rejected coordinate frame is silently rescaled by answer magnitude.

## Drawing evaluation

40 cases x two stations (3,7) x two waterlines x two views = 320 point/breadth rows. Waterlines are the nearest printed nice-step levels to 30% and 60% of depth. All 320 truth intersections exist. Full-sheet/crop views use the same original pixels. Crop and calibration are caller-supplied, not model-discovered. Truth uses exact rendered station curves and the factory affine/composite transforms. No sealed truth folder is opened.

Strict deterministic tracing abstains on all 80 station inputs. A separate best-score deterministic draft comparison uses only image candidate support for selection. Drafts are not approved traces. Missing candidates and inspection failures remain in denominators.

The combined point/breadth requests also asked scale. This was a design error: supplied breadth calibration contains the scale answer. Those scale answers are excluded. Forty separate scale requests contain no calibration answer; only those results support independent scale claims. Units are absent in the factory images, so grid-scale accuracy is pixels per printed drawing unit, not independently established pixels per metre.

## Verification status

Initial make test-quick failed at Rust compilation because three pre-existing test initializers lacked newer receipt fields. Those test fixtures were repaired without changing runtime authority. A fresh complete quick tier is required before commit.

refresh-codesight generated .codesight locally. Its managed bootstrap then failed with ModuleNotFoundError: render_bootstrap. No external checkout was changed. Generated index files are not source deliverables.

## Resume point

All experiments ended. Twenty W11 cases attempted: 18 native no-progress stops and two supervised/manual no-progress stops; two interrupted receipts remain unknown and are not retried. Final accounting: 874 provider requests, 2,795,859 returned prompt tokens, 223,445 returned completion tokens, list USD 0.54123162; 18 receipts omit usage. Final quick checks passed with 652 Python tests and all Rust/format/Clippy/secret checks. Cargo clean and commit remain. No push is authorized.
