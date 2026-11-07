# MarinaFrame 0.4 dependency and notice record

## Release audit result

The final Rust lockfile was queried against the official OSV API on
**6 November 2026 at 21:22 UTC**. All **155 exact external crate versions** were
checked, with **no advisory returned for that lockfile**. The separate optional
data-tool lock contains six exact Python packages; its query also completed
without a returned advisory. A later, separate audit of the optional learning
lock found **59 advisory records for historical Pillow 12.3.0**. Its recommended
setup now pins **Pillow 13.0.0**; the repeated two-package query returned no
advisory. The historical learning environment and experiments were preserved.
These are dated package-database results, not a
claim that the complete application or its native dependencies are vulnerability
free.

The audited `Cargo.lock` SHA-256 is
`06350565d56dc32368f51b7f47f79ac6c0bd14e59cfa5b7727d83b825cfd0e7e`.
The script verified that the lockfile did not change during the audit. The main
55-package Python lock was audited separately and still has the three scoped
VTK findings described below. No source code, drawings, model requests,
credentials or private package names were sent to an advisory service. Requests
contained only public ecosystem, package and version values.

Evidence is under `artifacts/v04/release/dependencies/`; the authoritative final
Rust result is `final-rust/summary.json`, with the exact queries, API responses
and reports in `final-rust/rust-osv/` and
`final-rust/optional-python-osv/`. The main Python audit is
`artifacts/v04/release/python-dependency-audit.json`.

## Finding corrected before the final lock

The first exact-version query found **Tokio 1.50.0,
[RUSTSEC-2026-0386](https://rustsec.org/advisories/RUSTSEC-2026-0386.html)**.
RustSec classifies this as an informational **unsoundness** advisory: safe
`AsyncFd` construction can violate I/O safety and lead to use-after-free.
Informational, unsoundness and unmaintained notices are retained by the audit;
they are not silently filtered out as non-vulnerabilities.

The implementation owner updated Tokio to **1.51.6**. Its dependency resolution
also required changing the exact libc pin from **0.2.177 to 0.2.183**, and mio
resolved from **1.1.0 to 1.2.4**. Tokio 1.51.6 is within the advisory's documented
patched range. The first resolver attempt, which retained the incompatible
libc pin, failed; it was not treated as a completed update. The subsequent
updated lock is the one identified and audited above.

`rust-osv-initial.json` and `RUSTSEC-2026-0386.json` retain the original finding
and its full official advisory. Earlier development binaries and experiments
remain historical evidence. Their dependency state is not retroactively
relabeled by this release query.

## Cargo component and notice inventory

`scripts/audit_rust_dependencies.py` obtains metadata and the dependency tree
with Cargo's `--locked --offline` mode. For the exercised
`x86_64-unknown-linux-gnu` target, the resulting inventory has:

| Inventory | Observed result |
| --- | ---: |
| External components in the complete Cargo lock | 155 |
| Target metadata packages, including MarinaFrame | 124 |
| External normal/build dependencies for Linux | 102 |
| External installed crate manifests, including development tools | 123 |
| Copied upstream license/notice files | 229 |
| Installed crate archives matching Cargo lock SHA-256 | 123 of 123 |
| Notice inventory problems recorded | 0 |
| Off-target/uninstalled packages without a local license inventory | 32 |

The exact upstream files are copied into `final-rust/licenses/` and combined in
`final-rust/THIRD_PARTY_CARGO_NOTICES.txt`. Each copied file has a hash and size
in `final-rust/cargo-license-inventory.json`. Matching archive checksums verify
the cached downloaded crates against the lockfile; this is not a separate
cryptographic verification of every extracted local source file.

The installed manifests declare MIT, Apache-2.0, BSD-3-Clause, ISC,
Unicode-3.0 and associated alternatives or exceptions, including Zlib,
BSL-1.0, the LLVM exception and Unlicense alternatives. The exact expressions
are retained per package, including `AND` obligations. It would be inaccurate
to summarize the whole inventory as only MIT/Apache/BSD. Declared SPDX metadata
and copied notices support a distribution review; they are not legal clearance
for a particular binary or deployment.

`final-rust/cargo-sbom.cdx.json` is a CycloneDX **1.6** document containing all
155 locked external components and their registry archive hashes. Its dependency
graph is target-filtered and includes development/build tools. A component's
`marinaframe:linux_normal_or_build_dependency` property distinguishes the 102
normal/build dependencies. Other lock components are marked optional in this
inventory; that does not claim they are linked into the Linux binary. The 32
off-target/uninstalled components are explicitly listed in `summary.json` and
have `marinaframe:license_manifest_available=false`. Their Windows, macOS or
WebAssembly distribution rights were not established by this local inventory.

The SBOM passed full JSON Schema draft-07 validation, including format checks,
against the official CycloneDX 1.6 schema and its referenced SPDX/signature
schemas. The files, upstream URLs and exact hashes are retained in `schemas/`;
validation required no network. See
`final-rust/sbom-schema-validation.json`. The official schema site's direct
download returned HTTP 403, so the same public project's official
[GitHub schema sources](https://github.com/CycloneDX/specification/tree/master/schema)
were fetched through ordinary configured network access. The first inventory
attempt stopped on the virtual Cargo workspace's missing `resolve.root`;
`first-inventory-attempt-incomplete/` is preserved separately. The script now
uses the single explicit default workspace member and the final result passed.

## Python, CAD wheels and known VTK findings

The main, annotation-tool and optional learning locks have different purposes:

| Lock | Exact package queries | Result |
| --- | ---: | --- |
| `requirements-linux-py312.lock` | 55 | Completed; VTK findings below remain installed |
| `requirements-data-linux-py312.lock` | 6 | Completed; no returned advisory |
| Historical `requirements-learning-linux-py312.lock` | 2 | NumPy 2.3.5: none; Pillow 12.3.0: 59 advisory records, preserved in full |
| Current `requirements-learning-linux-py312.lock` | 2 | NumPy 2.3.5 / Pillow 13.0.0: completed; no returned advisory |

The main lock retains **VTK 9.3.1** with **PYSEC-2025-224**, **PYSEC-2025-225**
and **PYSEC-2025-226**. The package is vulnerable according to the database;
the scope entries do not fix it or constitute an owner security waiver. The
recorded engineering assessment is that the affected GLTF loader is not
reachable through the supported raster/PDF source routes. The regression
`tests/test_dependency_scope.py` rejects GLTF/GLB/VTK content, including a
misleading `.png` extension, before native decoding. The exact version and
review date, **7 December 2026**, remain in
`docs/dependency-scope-exclusions.json`. The scanner's `unresolved=[]` means
these findings match that recorded scope, not that no vulnerabilities exist.

The installed OCP distribution declares an exact requirement on `vtk==9.3.1`.
A kernel/OCP migration needs its own compatibility and geometric validation;
forcing a different VTK wheel would not establish that compatibility. No native
dependency migration was performed as part of this Rust advisory correction.
The earlier Python dependency changes and current VTK scope are documented in
`docs/DEPENDENCIES_AND_RIGHTS.md`.

A metadata-only inventory of the installed pinned CAD environment matched all
**55 installed versions** to the lock and copied **194 wheel license/notice
files**. It is at `python-wheel-licenses/inventory.json` with the files in
neighboring package directories. This supplements the existing wheel-hash
inventory; it does not enumerate every component embedded in a wheel or scan
every native library for CVEs.

The material distribution qualifications are:

- **PyMuPDF 1.26.7** declares GNU AGPL 3.0 or an Artifex commercial license. Its
  packaged `COPYING` is a short statement of these alternatives, not a complete
  license bundle. The [official licensing statement](https://pymupdf.io/licensing)
  confirms the alternatives. No commercial license was acquired and the
  project's all-rights-reserved license was not changed. PDF support being an
  optional feature does not by itself resolve obligations when this component
  is distributed or used in a deployment.
- **cadquery-ocp 7.8.1.1.post1** has no declared license field in its installed
  metadata. Its copied wrapper license is Apache-2.0, but that does not describe
  the complete embedded **Open CASCADE Technology** kernel. Upstream OCCT is
  [LGPL 2.1 with an additional exception](https://occt3d.com/dev/doc/overview/html/occt_public_license.html).
  A distribution review must account for the matching kernel, required notices,
  source availability and applicable relinking obligations. This inventory
  does not substitute the wrapper's Apache license for the kernel's terms.
- **CasADi 3.7.2** declares LGPLv3-or-later. Its 62 copied notice files cover
  numerous bundled solvers and interfaces with separate terms. See the
  [upstream license](https://github.com/casadi/casadi/blob/main/LICENSE.txt).
  The wheel is not established to be wholly permissively licensed by its
  package-level label.
- **OpenCV, NumPy and SciPy** include bundled third-party notices and native
  dependencies. For example, SciPy's notice bundle contains GCC-runtime and
  libquadmath terms; these cannot be reduced to SciPy's top-level BSD label.
  The actual copied bundles are retained for review. Native-file counts in the
  inventory are discovery aids, not a complete component SBOM.

## Optional learning environment: historical finding and setup correction

The two completed procedural-learning experiments actually used **NumPy 2.3.5
and Pillow 12.3.0** in the existing data environment. Those environment records,
images, weights, thresholds, labels and metrics retain their original identity.
The exact original learning lock is preserved at
`learning-python/historical-12.3.0/requirements-learning-linux-py312.lock`, under
the dependency evidence directory. Its SHA-256 is
`9150696fb3bc7b81aad422b9b99c7850ed0e85b229c534d67392a959444c6f28`.

The official OSV query completed on **6 November 2026 at 23:06 UTC**. It returned
no NumPy 2.3.5 advisory and **59 Pillow 12.3.0 records: 41 GHSA and 18 PYSEC**.
The returned records form **41 groups connected by advisory aliases**; 59 must
not be described as 59 unique vulnerabilities. The 41 GHSA records explicitly
declare **5 Critical, 23 High and 13 Moderate** severities. The 18 PYSEC records
lack a comparable explicit severity field. None of the returned records was
withdrawn. All 59 full records, their 114 distinct alias IDs (including 40 CVE
aliases), query/response files and record-to-group mapping are retained in
`learning-python/`. No exclusion or security waiver was applied. Every matching
Pillow affected range returned by this query declares **13.0.0** as fixed.

One material example is
[GHSA-78g4-xqwv-q3g8](https://osv.dev/vulnerability/GHSA-78g4-xqwv-q3g8), a High
severity, CVSS 8.1 heap-buffer-overflow write in bundled OpenJPEG. The advisory
covers Pillow 11.1.0 through versions before 13.0.0, including 12.3.0. The
historical installed wheel's component SBOM and RECORD identify OpenJPEG
**2.5.4**. Image decoding is content-based, so a `.png` filename alone is not
a mitigation for another supported decoder. No exploit was executed, and this
record does not claim that the retained procedural images exercised a vulnerable
decoder path.

With explicit authorization, the optional reproduction lock's Pillow pin and
wheel hash were updated to the exact **13.0.0** values already in the base CAD
lock; NumPy remained **2.3.5**. The obsolete header was corrected to identify
the historical version. The current learning lock SHA-256 is
`0522d0db687887cac2bdd46bd0c6427c1f2ae1fb3469e1f50a9dfecd8ac3454a`.
The second official query completed at **23:08 UTC** and returned no advisory
for either exact version, with no exclusions. This is a post-inference-freeze
security correction to optional future learning setup. It does not change the
frozen application, inference runtime, base CAD lock or any measured shape
score. Both queries verified unchanged lock bytes during their runs.

The addendum copied the actual installed **Pillow 12.3.0 and 13.0.0** metadata,
combined license notice and packaged component SBOMs: six files per version.
Both declare **MIT-CMU**, and the combined notice has SHA-256
`dda12a98c1979cf3d94df1cff45d27a4cb3f04a60c76f76902ac54cac03ec0ce`.
Each of the five files with a digest in its installed RECORD matched that
digest; RECORD has no self-hash. The historical wheel's Pillow SBOM lists 24
components, including OpenJPEG, libtiff, libwebp, libavif, libjpeg-turbo,
FreeType and raqm. Their notices and native dependency obligations cannot be
reduced to the top-level package label. This metadata-only addendum neither
redownloaded wheel archives nor exhaustively audited embedded native libraries.
The old data environment inherits existing packages; the separate release
environment already had Pillow 13.0.0. Neither environment was modified.

A narrow compatibility replay used the preserved Run 2 selected weights,
threshold and **36 PNGs / 1,728 queries** under both existing environments.
Both reproduced the historical true-label, learned-prediction and baseline
lists and both metric dictionaries exactly. Newly derived decoded pixels,
features, normalized features, probabilities and prediction arrays were
byte-identical, with zero maximum differences; **all 43 original files were
unchanged**. The original feature matrices had not been saved, so their equality
is an old/new environment replay comparison, not a comparison to historical
saved arrays. This is a compatibility regression, not retraining, model
selection, a new untouched accuracy test or a general codec-safety claim.

The auditable rollup and complete finding index are
`learning-python/learning-dependency-addendum.json`. Raw records are separated
into `historical-12.3.0/` and `recommended-13.0.0/`; their original files were not
rewritten. The compatibility report is
`learning-pillow13-compatibility/comparison.json`, SHA-256
`0b12c0c56438c1396ea5c680a4f177780296c1121aa48f2aad49dc3234b63ce8`.
The executed audit scripts, metadata inventories, compatibility script and
publication hashes accompany these files. `docs/DATA_LEARNING_V04.md` now
recommends the corrected setup while preserving the experiments' actual
historical versions.

## Toolchain, platform and audit limits

The exercised environment is Ubuntu 24.04.3/Linux x86_64, glibc **2.39**,
CPython **3.12.14**, Rust/Cargo **1.99.1** and LLVM **23.1.1**. Exact command
output is in `toolchain/inventory.json`. Fourteen distributed Rust toolchain
and standard-library notice files, including `COPYRIGHT-library.html`, were
copied into `toolchain/rust-distributed-notices/`. Toolchain notices are kept
separately because the compiler and standard library are not Cargo lockfile
components; copying the broader toolchain notices does not assert every listed
toolchain component is linked into MarinaFrame.

This is not macOS/M5, Windows, cross-compilation or a hermetic operating-system
validation. The worker supervisor relies on Linux behavior and needs separate
implementation/validation elsewhere. OS packages, compiler/toolchain
vulnerabilities, dynamically linked system libraries, embedded wheel libraries
and newly undisclosed advisories are outside the completeness claim of the
package-version OSV queries. The native CAD worker remains an attack surface
despite bounded process supervision.

## Reproduction

With the pinned toolchain and crate cache available, use a new output directory:

```sh
python scripts/audit_rust_dependencies.py \
  --cargo /root/.cargo/bin/cargo \
  --out /tmp/marinaframe-rust-dependency-audit \
  --optional-python-lock requirements-data-linux-py312.lock
```

The script refuses an existing output directory to preserve previous evidence.
Cargo metadata/tree access is offline and locked; only public package-version
advisory queries use the network. A failed or paginated/incomplete advisory
response is reported as incomplete, never as a clean result. All returned
classes are retained, including withdrawn or informational reports. Exit status
is 2 for an incomplete query or changed lock, 1 for returned advisories and 0
for completed queries with none. License inventory problems and target limits
remain explicit fields requiring review; exit status is not a legal assessment.

The optional data lock provides `jsonschema` for independent full-schema
validation; it is not added to the pinned native CAD environment. No advisory
exclusions were applied to the Rust or optional data-tool queries.

The separate learning audit can be repeated against the current lock using an
existing environment whose installed versions match that lock:

```sh
python artifacts/v04/release/dependencies/audit_learning_lock.py \
  --repo . --training-python /tmp/marinaframe-v04-release-env/bin/python \
  --out /tmp/marinaframe-learning-dependency-audit-new
```

The interpreter argument only reads installed metadata; it does not install
packages or train a model. Use a fresh output directory. Historical query
results remain immutable, including all returned advisories.
