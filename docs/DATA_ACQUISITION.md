# Data acquisition record, workstream W5

Date: 2026-11-07. Scope: the OPEN rows of `docs/STRATEGY_2026Q4.md` section 3
(benchmark hulls, OCX, open hull libraries). Rule documents (W4) and MiDShip are out of scope.

All files are in `work/sources/<dataset>/` (git-ignored). Each folder has a `manifest.tsv` with
file, bytes, sha256, source_url, retrieved_utc, licence_terms, notes. Every file was checked
against the publisher checksum (git blob SHA-1 for GitHub files, MD5 for 4TU files). Downloads
were sequential with the User-Agent `MarinaFrame-research/0.5 (source acquisition)`. No login,
no access-control bypass. No archive had an unsafe path or an executable. No downloaded code was run.

Total acquired: 283,234,061 bytes (about 283 MB), 121 files. Limit of 2 GB: not reached.

## Status table

| Target | Status | Folder | Files | Size | Licence | Contents | Likely use |
|---|---|---|---|---|---|---|---|
| OCX schema (XSD) | acquired | `ocx_schema/` | 11 (OCX_Schema.xsd for 3.2.x working draft, 3.0.0, 3.0.1, 2.8.6; UnitsML lite XSD; LICENSE, README, CHANGELOG) | 1.56 MB | Apache-2.0. README: "OCX Public License" is Apache 2.0, governed by 3Docx.org Consortium. Commercial use allowed. | XML Schema for class-neutral 3D ship structure (frames, plates, stiffeners, brackets, compartments, materials). Units in UnitsML. Pinned to commit c8b66e3. | Interop, structure |
| OCX sample models, platform repo | acquired | `ocx_models_platform/` | 85 `.3docx` models plus LICENSE (TR02 to TR05 consortium test rounds from AVEVA, CADMATIC, NAPA, 3DEXPERIENCE, PROSTEP, STR-A; D-VLCC 1-hold; ROPAX) | 251.3 MB | MIT (repo LICENSE). No separate per-model notice. Models are consortium interoperability test files. | Plain XML, schema 3.0.0 to 3.2.0. Panels, stiffeners, frames, hold and full-hull structure. Largest: ROPAX (57 MB). | Structure, interop test set |
| OCX sample models, ocxtools | acquired | `ocx_models_ocxtools/` | NAPA-OCX M1 to M9, AVEVA-E3D Model01, LICENSE | 11.9 MB | MIT, Copyright (c) 2023 3Docx.org | `.3docx` XML, schema 3.0.0. Small to medium NAPA structure models. | Structure, parser tests |
| OCX sample model, OCXViewer | acquired | `ocx_models_viewer/` | `brackets.3docx`, LICENSE, MITLicense | 1.75 MB | Apache-2.0 (repo LICENSE) | Schema 3.1.0 model with bracket geometry. | Structure, interop |
| Series 60 (parent CB 0.60) and Wigley | acquired (digital copy of offsets as OpenCascade surface; not the original table) | `series60_freecad/` | `s60.fcstd`, `s60_katamaran.fcstd`, `wigley.fcstd`, `wigley_katamaran.fcstd`, LICENSE, Ship README, source header | 0.38 MB | Repo LICENSE is LGPL v2; Ship workbench headers say LGPL v2 or later. Each `.fcstd` file also carries the metadata "License: CC-BY 3.0" (attribution). Neither blocks commercial use. | FreeCAD 0.19.4 Ship workbench examples. `.fcstd` is a ZIP with `PartShape.brp` (OpenCascade BRep hull surface) and Document.xml. Hull sizes and units are not in the metadata; read them from the BRep. | Development set, hydrostatics check (compare to Todd 1963 particulars: L 121.92 m, B/T 2.5, L/B 7.5, CB 0.60) |
| Delft Systematic Yacht Hull Series (extra benchmark, not on the target list) | acquired | `dsyhs/` | `geometriesIGSmodelscale.zip` (59 hull IGES surfaces SYSSER01 onward, plus StandardKeel.igs and StandardRudder.igs), hydrostatics full scale and model scale (xlsx) | 16.28 MB | CC0 1.0 (4TU.ResearchData, DOI 10.4121/21501330.v1 and 10.4121/21501375.v1) | IGES NURBS surfaces (Rhino export), millimetres, model scale, bare hull. Hydrostatics (Lwl, Bwl, volume, at 0/10/20/30 deg heel) computed in Maxsurf. | Development set, hydrostatics check (ground-truth numbers beside exact geometry) |
| Duisburg Test Case (DTC) | blocked | none | none | 0 | No public licence. Developers (ISMT, University of Duisburg-Essen): the IGES model "is available upon request" (Ould el Moctar, Shigunov, Zorn, J. Ship Technology Research, 2012). | Would be 14,000 TEU post-Panamax IGES. | Needs a written request to ISMT. Founder decision. OpenFOAM tutorials carry a DTC STL, but its provenance and terms are not stated, so it is not used. |
| Japan Bulk Carrier (JBC) | blocked | none | none | 0 | The geometry is public (IGES at `t2015.nmri.go.jp/file/Geometry_IGES_files/jbc/JBC_IGES.zip`, above-water IGES at nmri.go.jp). No licence is stated. NMRI Site Policy: content may not be reproduced or processed without permission from NMRI, except personal use, quotation or acts allowed by copyright law. No permission for commercial use. | Capesize bulk carrier, Lpp 280 m, hull, duct, rudder, IGES. | Needs NMRI permission (info address on the site policy page). Not downloaded. |
| ONR Tumblehome (ONRT, model 5613) | blocked | none | none | 0 | Hull IGES is public on the Tokyo 2015 site (`onrt_w_gap.zip`, `onrt_wo_gap.zip`), described as "publicly accessible for fundamental research". No licence text. Commercial use is not stated. The SHIPSTAB page that also lists it returns 404. | Surface combatant, 1/49 model, L 3.147 m, IGES. | Needs a permission e-mail to IIHR or INSEAN. Not downloaded. |
| Series 60 original offset table (Todd, DTMB report) | blocked (access control) | none | none | 0 | Report is a US Government work, but DTIC (AD0419990) answered HTTP 403 with a bot challenge. I did not bypass it. The DeepBlue copy also shows a challenge page. | Scanned table of offsets, 1963. | A person can download the PDF in a browser. The FreeCAD copy above covers the need for now. |
| DELFTship free example hulls | blocked | none | none | 0 | Examples are inside the Windows program (installer is an executable; rules forbid downloading or extracting executables). No licence for the example hulls is published on delftship.net. | `.ship` project files. | Contact DELFTship for written terms, or a person exports examples in the app. |
| FREE!ship example hulls | blocked | none | none | 0 | Programme is GPLv2 (SourceForge). Examples ship in the win32 executable ZIP. The only separate sample, "Notus racing and cruising canoe" by Bryan Hansel, has no licence statement. | `.fbm` files. | Not downloaded. A canoe is also a weak match for our ship use. |
| Delft 372 catamaran | not found | none | none | 0 | No public geometry or offsets located in 4TU, Zenodo or the Tokyo 2015 site. | n/a | Skip. |
| Wigley hull | not needed as download | `series60_freecad/wigley.fcstd` and BUILD | see above | see above | analytic | Closed-form offsets. | Generate locally; check against `wigley.fcstd`. |
| Other benchmarks | none found with a clear licence | none | none | 0 | Third-party Series 60 reconstruction (andreacoraddu.github.io) has no licence. 4TU KCS FFD datasets are CC BY-NC (non-commercial), so not used. A Zenodo Piyade/Tirhandil record withholds its geometry. | n/a | n/a |

## Notes and cautions

1. OCX model files: the repositories give MIT or Apache-2.0 for the whole repo. The models were
   exported by vendors for consortium tests. No file states a different licence. Risk is low but
   not zero. The record is inference from the repo licence, not a per-file grant.
2. FreeCAD examples: the repo licence is LGPL. The in-file "CC-BY 3.0" is a FreeCAD default field.
   Attribution: José Luis Cercos Pita and FreeCAD contributors.
3. Do not send any `work/sources/` file to a model provider without a recorded decision, as
   `docs/STRATEGY_2026Q4.md` section 3 requires.
4. Items with open geometry but no commercial grant (JBC, ONRT) have a single clear next step:
   one permission e-mail each. Do this only on founder approval.
5. The DTIC and DeepBlue blocks are access controls. A person may download them by hand.

## Source URLs (for audit)

- OCX: https://github.com/OCXStandard/OCX_Schema, `.../ocx-platform`, `.../ocxtools`, `.../OCXViewer`
- DSYHS: https://data.4tu.nl/datasets/555b6bdc-0352-4287-bc1c-a47eb62ec901 and https://data.4tu.nl/datasets/e198553e-0130-45d4-88cc-680d9f441b9b
- FreeCAD: https://github.com/FreeCAD/FreeCAD, tag 0.19.4 (`src/Mod/Ship/resources/examples/`)
- JBC, ONRT (blocked): https://t2015.nmri.go.jp/jbc_gc.html, https://t2015.nmri.go.jp/onrt_gc.html, https://www.nmri.go.jp/en/info/site_policy.html
