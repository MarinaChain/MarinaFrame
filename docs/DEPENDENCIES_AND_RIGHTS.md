# Environment, dependencies and distribution rights

The exercised profile is Linux x86_64, Python 3.12.14, CadQuery 2.7.0 and OCP
7.8.1.1.post1. The package now declares Python 3.12 only. This is not M5/macOS
validation. Native worker isolation uses Linux resource limits/process groups;
other operating systems require separate implementation and tests.

`requirements-lock.txt` remains the original reference. The new
`requirements-linux-py312.lock` pins 55 exact Linux/CPython 3.12 wheels with SHA-256,
including pip, setuptools, wheel and build. A clean environment installed them
with `--require-hashes` and without system site packages. Regenerate from a
reviewed wheelhouse using `scripts/build_lock_inventory.py`; it does not resolve
updates. Other platforms need separate tested hashes. OS packages are identified
but not byte-pinned: this is a reproducible Python layer, not a hermetic OS image.

CI uses fixed Ubuntu/Python versions, commit-pinned actions, read-only repository
permissions, no persisted Git credentials and no model calls or PR secrets. It
tests the source and a freshly installed wheel, scans tracked text for common
secret patterns, and checks Python versions against OSV. Dependency-range updates
run separately on manual dispatch. No upload action publishes drawings/evidence.

`dependency-inventory.json` and `sbom.cdx.json` contain package declarations and
wheel hashes. License metadata may be incomplete and is not legal clearance.
OSV does not cover every native component or new issue. Pattern scanning is not
a guarantee of absent secrets.

## Desktop UI vendored code (app/ui/vendor)

three.js r170 (npm `three@0.170.0`, MIT, licence in `app/ui/vendor/three/LICENSE`): the module
build, `OrbitControls.js`, `STLLoader.js`, and since 2026-11-09 `GLTFLoader.js` and
`BufferGeometryUtils.js` (for the whole-vessel GLB). The only edits are import paths and a
two-line origin comment; see `app/ui/vendor/three/README.md`. The UI test tools are npm
devDependencies with exact versions (`axe-core` 4.10.3, MPL-2.0; `playwright-core` 1.56.1,
Apache-2.0) and are not shipped.

## Owner/legal decision: PDF dependency

PyMuPDF 1.26.6 declares **GNU AGPL 3.0 or Artifex Commercial License**. MarinaFrame
remains all rights reserved. Distribution/hosting with that component needs an
owner/legal decision on obligations and any commercial license. No license was
changed or acquired here. PyMuPDF remains optional for documents; raster-only
operation does not require importing it. An optional declaration alone does not
resolve distribution rights. A substitute renderer would need tested calibration,
pixel equivalence and resource/security behavior before replacement.

The patched lock uses PyMuPDF 1.26.7 with the same declared licensing family.
The [upstream licensing statement](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
describes both AGPL and commercial routes; the owner must assess the actual use.

## Vulnerability scan and scoped unresolved dependency

The initial 55-package OSV query reported msgpack 1.2.1, multidict 6.7.1,
Pillow 12.3.0, PyMuPDF 1.26.6 and VTK 9.3.1. The patched lock moves the first four to
1.2.3, 6.9.1, 13.0.0 and 1.26.7 respectively. The original lock remains historical.

OCP 7.8.1.1.post1 requires exactly VTK 9.3.1. OSV's three VTK advisories concern
`vtkGLTFDocumentLoader`. Supported source routing rejects GLTF/GLB/VTK contents,
including misleading `.png` filenames, before native decoding. No application
path imports a user GLTF file. Tests preserve this boundary. The vulnerable VTK
package nevertheless remains installed; this is a scoped mitigation, not a fix.
`dependency-scope-exclusions.json` records the exact three IDs/version, rationale
and review deadline (7 December 2026). The scanner reports all findings and fails
on new, unmatched or expired exclusions. A validated OCP/kernel migration remains
necessary before adding GLTF ingestion or broadening the deployment boundary.

Original DTMB MIT notices, Tesseract Apache-2.0 weights and claimed public-domain
archival documents have separate scope. No new third-party drawings or OCR
weights enter Git. New diagnostic fixtures are generated locally. Available
historical inputs are local regression material; availability does not grant new
model-processing or redistribution permission. No expert traces or new authentic
scan reconstruction success are claimed.

## Owner decision: commercial data licences (2026-11-09)

The founder states that MarinaChain holds a commercial licence for all acquired data sets,
including R/V Gunnerus (public licence CC BY-NC 4.0). Effects:

- Commercial development, benchmarking and model training on these data sets are allowed.
- Sending these drawings to the drafting model provider (DeepSeek through OpenCode Go) is allowed.
- The repository is public. Drawings, renders, truth files and derivatives stay in the
  git-ignored `work/` folder. Only hashes and numbers go into committed files.
