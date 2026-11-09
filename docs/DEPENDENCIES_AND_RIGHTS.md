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

### Decision 2026-11-09: PyMuPDF commercial licence bought

The founder states that MarinaChain bought an Artifex commercial licence for PyMuPDF (2026-11-09),
so MarinaFrame may ship PyMuPDF in a closed-source desktop app. The licence document is kept by
MarinaChain, not in this repository. The VTK and OpenCV items that were open then are closed in
"Worker runtime licence review" below. Still open: Developer ID signing.

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

## Desktop app worker runtime (macOS arm64, 2026-11-09)

`scripts/build_worker_runtime.sh` builds the Python that the app bundles at
`MarinaFrame.app/Contents/Resources/worker` (packaging plan step 3): CPython 3.12.15 from a
pinned python-build-standalone release (SHA-256 checked), the 44 wheels of
`requirements-worker-macos-arm64-py312.lock` (same versions as the Linux lock, minus OpenCV;
macOS arm64 wheels, installed with `--require-hashes`) and a `vessel_reconstruction` wheel built from the
committed source. `requirements-worker-tools-macos-arm64-py312.lock` holds the build and test
tools, which are never shipped. The runtime is built locally only and is not in Git; nothing
has been distributed.

`docs/WORKER_RUNTIME_LICENCES.md` (generated by `scripts/worker_runtime_licences.py`) lists
every bundled distribution with its declared licence and the native libraries that its wheel
vendors. The review below records how each copyleft item is handled.

### Worker runtime licence review (2026-11-09)

**OpenCV removed from the runtime.** Every published macOS arm64 `opencv-python-headless`
wheel (checked 4.8.1 to 5.0.0) vendors FFmpeg with `libx264`, `libx265` (GPL-2.0+) and
`libpostproc`, so no drop-in wheel exists. The worker used OpenCV only for morphological
opening, dilation and 8-connected component labelling (`structure/raster.py`,
`ga_reader.raster_levels`, `ga_reader.raster_transverse_walls`). These now use SciPy through
`src/vessel_reconstruction/raster_morphology.py`. The results are the same: identical
pixels, labels (including OpenCV's label order) and statistics on random images, and
identical strokes, levels and walls on the 24 drawings of `work/factory-3view` (480 checks;
`tests/test_raster_morphology.py` keeps the comparison when OpenCV is installed).
`ga_reader.PlanRaster` (line drawing and outline tracing) still uses OpenCV; it is used only
by benchmarks and tests, so OpenCV is now the optional `plan-raster` extra and stays in the
Linux development locks. If an app path starts to use `PlanRaster`, replace those calls first.
`build_worker_runtime.sh` fails if `cv2` can be imported in the runtime.

**VTK 9.3.1 stays.** `cadquery-ocp` pins `vtk==9.3.1`, `OCP.cpython-312-darwin.so` links
ten VTK libraries, and `import cadquery` imports `vtkmodules`, so the runtime cannot start
CadQuery without it. VTK is BSD-3-Clause. Its wheel bundles 208 libraries; the third-party
ones (expat, zlib, png, jpeg, tiff, hdf5, netcdf, exodusII, cgns, ioss, libxml2, libproj,
sqlite, ogg, theora, pugixml, jsoncpp, fmt, lz4, lzma, glew, libharu, VTK-m, DIY, zfp and
others) are permissive. Two are dual-licensed and used under the permissive option: gl2ps
(GL2PS licence, not the LGPL) and FreeType (FreeType licence, not the GPL). Eigen is
compiled in under MPL-2.0 (file-level; unmodified). No GPL text was found in the VTK
binaries. The scoped OSV exclusion above still applies.

**Other copyleft items** (all acceptable with notices and source pointers in the app's
third-party notices; none needs an owner decision):

- PyMuPDF: commercial licence (above), not the AGPL.
- Open CASCADE (`libTK*` in OCP): LGPL-2.1 with the OCCT exception, dynamically linked.
  In the same wheel, FreeImage (GPL or FreeImage Public License) is used under the FreeImage
  Public License, and LibRaw (LGPL-2.1 or CDDL-1.0) is dynamically linked.
- CasADi: LGPL-3.0+, dynamically linked; its folder also holds COIN-OR Ipopt, Cbc, Clp,
  Bonmin (EPL-2.0), MUMPS (CeCILL-C), fatrop and sleqp (LGPL-3.0), each a separate library.
- NLopt: the metadata says MIT, but `_nlopt.so` statically contains the LGPL-2.1+ Luksan
  routines. The file is a separate, replaceable Python extension (no MarinaFrame code is
  linked into it), which meets the LGPL's relinking terms; ship the notice and point to the
  NLopt 2.11.0 source.
- SciPy: `libgcc_s` and `libgfortran` (GPL-3.0+ with the GCC runtime exception, which
  permits this use) and `libquadmath` (LGPL-2.1+, dynamically linked).
- Pillow: `libfreetype`, used under the FreeType licence.

LGPL libraries are dynamically linked (or, for NLopt, a replaceable module); the LGPL allows
that in a closed-source app if the notices ship, the source is offered and users may
replace the library. Code signing does not conflict with LGPL-2.1, but write the notices
file before the first distribution.
