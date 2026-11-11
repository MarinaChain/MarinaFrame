# MarinaFrame 0.4 — start here

**7 November 2026, Asia/Singapore.** This delivery continues the published reviewed 0.3 source at `5b0b48e3dd9bcef25427d27ce800118935f58d1a` in draft PR #2. The new application was frozen for inference at `8916e68f4c175bdab291d7c0bf2978862be8915d`. Later commits add evaluation, review and delivery material, plus the separately documented optional learning dependency correction. The exact final delivery commit and archive hashes are in `MarinaFrame-0.4-Verification.json` and the source archive's manifest.

No new source was pushed, no PR was merged and no service was deployed. All candidates remain provisional and require qualified human review.

## Choose a starting point

| File | Purpose |
| --- | --- |
| `MarinaFrame-0.4-Decision-Summary.md` | Short account of what works, measured limitations and next work |
| `MarinaFrame-0.4-Report.html` | Self-contained technical report with embedded actual geometry plots |
| `MarinaFrame-0.4-Review.html` | Self-contained recorded native browser task, including older and current candidates |
| `MarinaFrame-0.4-Runtime-Linux-x86_64.zip` | Exercised Rust binary, project wheel, exact dependency locks, examples and notices |
| `MarinaFrame-0.4-Source-and-Evidence.zip` | Complete tracked source, tests, reports, terminal experiment evidence, local Git history, patch and manifest |
| `MarinaFrame-0.4-Public-Data-and-Learning.zip` | Cleared archival subset, annotations/schema, acquisition metadata, training code, actual trained weights and predictions |
| `MarinaFrame-0.4-Verification.json` | Final delivery identities, archive checks and separately recorded release-scan receipts |

Extract the source archive beside the HTML report into `MarinaFrame-0.4/` to follow its relative evidence links. Reading the report and its figures requires no server or internet connection. The static review displays recorded evidence; use the installed local operator interface for a new mutable task.

## Run a new reconstruction

The exercised platform is Linux x86_64, Python 3.12.14, glibc 2.39 and Rust 1.99.1. Other platforms and libc versions are untested. The runtime package redistributes the project's Rust binary and Python wheel, but installs third-party Python/native dependencies from exact hashes. It does not bundle a complete native environment.

After extracting `MarinaFrame-0.4-Runtime-Linux-x86_64.zip`, follow its included README. The basic installation is:

```bash
cd MarinaFrame-0.4-Runtime
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-linux-py312.lock
python -m pip install --no-index --no-deps wheels/vessel_reconstruction-0.4.0-py3-none-any.whl
python -m pip check
chmod +x bin/marinaframe
bin/marinaframe help
```

The runtime README supplies the complete generated-source, deterministic reconstruction, live provider, review and installed-smoke commands. Deterministic use needs no API key or GPU. Live use requires the authorized OpenCode Go credential in the launching environment and an explicit source-transfer basis. No credential is supplied in this delivery.

Use a new task/output directory. Execution under `/tmp` was the tested mitigation for this managed environment's unresolved publication-restoration anomaly. Copy only completed tasks and verify their bytes afterward. Cross-machine migration of an existing mutable checkpoint is not automatic: runtime identities and paths are bound. Historical read-only evidence can be verified with a compatible reader; a deliberately read-only archive copy needs a writable empty `controller.lock` in a recorded working copy.

Exit zero does not mean the reconstructed shape is correct. Inspect the returned status, validation, source choices and assumptions. `awaiting_human_review` is provisional. A source trace can be reproduced accurately while the wrong line was selected.

## Inspect or rebuild the source

The source archive contains `git/MarinaFrame-0.4.git.bundle` and `git/MarinaFrame-0.4.patch`, together with delivery metadata. The Git bundle preserves the local commit series and historical base. Its manifest binds every included source/evidence file. The report records the separate application freeze, documentation/delivery identity and historical PR identities.

Follow the repository README for a source build. The old Python harness remains an explicit historical comparison/fallback; the new `marinaframe` executable is the Rust-authoritative control plane. Existing baseline commits and old failure records are preserved.

## Data and rights

The public-data package has its own minimal installation and strict five-item manifest. Its original full acquisition registry also records six omitted ALMA items. Those items were acquired for owner-authorized local training/testing; their source bytes and restricted derivatives are excluded from unrestricted archives because provider transfer and redistribution scope were not independently established.

All current authentic annotations are provisional. A strict training export correctly contains zero accepted gold rows. The included small model was trained on procedural labels; it is not enabled in reconstruction. The repository's all-rights-reserved license, dataset permissions and third-party dependency obligations are separate. The optional learning lock uses Pillow 13.0.0; historical Pillow 12.3.0 findings and compatibility evidence remain documented. Known VTK advisories remain open.

## Verification and boundaries

The full report distinguishes passing tests, preserved failed attempts, abstentions, blocked acquisition, compatibility failures and checks never run. Local tests are not remote CI. Exact-head CI was checked for the historical published 0.3 head; no new remote run exists for this local continuation.

The release includes all admitted completed experiment evidence and preserves failures. Final source/history and actual archive scans have separate receipts so the archive does not claim to contain a hash of itself. These bounded scans do not replace professional engineering, legal or deployment review.

No professional has approved these hull candidates. MarinaFrame reconstructs an interpolated hull envelope from supplied calibrated sections; it does not establish structure, stability, seaworthiness, class compliance or fabrication readiness.
