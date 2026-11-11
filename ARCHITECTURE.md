# Architecture and modeling choices

## Supported reconstruction task

The foundation reconstructs a bilaterally symmetric envelope from at least three calibrated transverse half-sections. A section is a single-valued curve `y(z)`, where `y >= 0` is half-breadth and `z` increases upward. Longitudinal station positions come from explicit metadata. Whole-vessel tips, detached bulb contours and appendages require additional topology adapters.

For curve input, the operator provides panel regions, station identity and position, drawing scale and datum, vertical interval, symmetry and terminal closure. For table input, the operator instead supplies cell/column regions, waterline elevations, station positions, and the feet/inches/eighths convention; pixel scale and a drawing datum do not determine the OCR widths. These are meaningful human inputs. The operator does not provide curve coordinates, numeric half-breadth answers, hidden source CAD or reference volume. Inference measures curve coordinates from drawing pixels or recognizes source measurement text.

## 1. Validate and preserve evidence

`schema.py` validates units, required views, physical scale, finite coordinates, unique stations, supported topology and independent dimensional constraints. It rejects fields that would supply target points or source geometry as hidden answers. Extreme physical extents are bounded before entering the geometry kernel.

`pipeline.py` copies the exact drawing and optional station-reference document, records SHA-256 hashes, preserves the original specification and creates a replay specification pointing to those copies. Inference then uses the snapshots. Every new run also retains the exact Python implementation source, its hashes and dependency versions. Earlier experimental runs retain the relevant source snapshots separately and the benchmark retains a full frozen inference tree for each evaluation.

## 2. Read source curves

`ingest.py` supports raster images and selected PDF pages rendered at a declared DPI. Transparent pixels are composited onto paper without silently rotating the coordinate system. It selects the declared source region and converts pixel positions to metres using explicit calibration.

Ink detection combines luminance contrast and color saturation. The revised parser retains broad-contrast candidate evidence instead of dropping lighter ink before ambiguity detection. Darkness may guide tracing but does not establish contour identity. Sustained competing lines block extraction unless an explicit human pixel corridor isolates one. Empty or overly broad corridors still abstain; excluded candidates remain in diagnostics. Very short, low-contrast or inseparable competing strokes remain limitations.

Connected-component filtering removes tiny fragments. A dynamic-programming trace chooses a continuous sequence of ink-run centres with a contrast preference and a modest outward preference relative to the supplied centreline. There is no procedural hull family or reference shape inside this algorithm. Required coverage, maximum erased-run and long-component-support checks reject weak evidence. A sustained competing contour produces an ambiguity gap.

Recovered curve sections contain 129 measured/interpolated samples by default, configurable from 65 to 1,025; these are not 129 independent observations. Table sections contain their accepted source row measurements. Quality scores are heuristic indicators, not calibrated probabilities. The recorded half-stroke-width estimate describes pixel measurement uncertainty only; it does not include scale, datum, document semantics, corrosion, drawing revisions or present-day vessel condition.

## 3. Construct explicit CAD boundaries

`geometry.py` validates and sorts the measured stations, adaptively simplifies each observed y(z) polyline under an explicit maximum error bound and uses a union of normalized-height knots for correspondence, mirrors the declared port/starboard symmetry, and joins corresponding section segments with ruled CAD faces. Elevations are ordered; breadth need not increase monotonically, so tumblehome can be represented. End faces and upper/lower envelope closures are explicit. Original observations remain separate from CAD points. The default maximum vertical half-breadth deviation is 0.001 m; every input/CAD knot is checked, RMS is integrated along the piecewise-linear error and significant features/zero transitions are preserved. A 513-knot and 20,000-estimated-face budget blocks excessive complexity. Different station heights/counts are supported; unsupported interior pinches and conflicting duplicate elevations block.

An earlier whole-wire loft failed when one measured keel touched the centreline while another had a small nonzero flat bottom. Those profiles have different edge counts, so automatic wire correspondence could stall or produce invalid geometry. The final implementation matches section segments explicitly and handles the observed lower boundaries without inventing a coordinate epsilon or consulting reference answers. The original implementation and its failed evaluations remain available.

The solid is a model between stations, not a measurement at every longitudinal position. Ruled interpolation is disclosed as an assumption. A valid positive-volume single solid is required before publishing geometry.

OpenCascade coordinates are millimetres. Public specifications, result metrics and viewer meshes are metres. Exported STEP is reimported and checked for validity, single-solid topology, volume and dimension agreement. STL is checked separately in unit tests with an independent mesh library for watertightness and scaling. The export is an editable CAD boundary representation, not a native shipbuilding feature tree.

## 4. Preserve uncertainty and review state

A required view failure blocks the entire envelope: the system does not quietly interpolate over missing evidence. Independent overall dimensions can block a geometrically valid result when scale or station information conflicts. A blocked run publishes no mesh or CAD asset.

Successful geometry has status `review_required`. The hull part links to its source IDs and observed sections. Assumptions about symmetry, station interpolation, ends, top, lower closure and vessel condition remain visible. Shell thickness, material and internal structure remain unresolved rather than being inferred from appearance.

*Historical (removed in 0.5):* `review.py` appended a Python-side review event to the run. Review state is now kept by the Rust controller and shown by `rust_review.py`; the immutable run record still allows the old mutable review files in its allowlist so archived runs verify.

## 5. Inspect and operate locally

*Historical (removed in 0.5):* `server.py` (loopback HTTP workbench) and `jobs.py` (SQLite queue) are gone. `isolation.py` still supervises killable process groups with CPU, address-space, file, output and wall budgets; the Rust worker path uses it. The local review UI is `rust_review.py`.

The packaged JavaScript viewer renders the actual mesh, offers section selection and overlays observations on the original drawing coordinate system. It supports reduced-resolution display derivatives without changing evidence coordinates. A software renderer handles environments without WebGL. The calibration editor writes metadata only.

`write_snapshot()` embeds an existing result, source evidence and supported downloads into one offline HTML file. It makes no service calls and cannot reconstruct new inputs. Original assets over its per-file size limit are explicitly omitted; display derivatives and retained hashes remain distinguishable from original evidence.

## 6. Evaluate without feeding answers into inference

The benchmark generator writes images/specifications under `inference/` and targets under `private_labels/`. Procedural target volume uses independent dense numerical integration, not the volume of the reconstructed CAD. External targets come from slicing a published IGES surface and integrating densely sampled sections.

The evaluator verifies every frozen input hash, snapshots the inference implementation, and runs each case in a fresh subprocess directory containing only image and specification. It reads numerical targets after that inference returns. This makes the actual data flow inspectable, although it is not a hostile-code sandbox. All attempted cases, abstentions, exceptions, timeouts and baselines are retained.

A case passes only if every required station is present, the CAD is valid, and both volume and sectional error satisfy the predeclared gate. Section error is half-breadth RMS at 257 common elevations, with equal station weighting, normalized by full beam. Volume error is absolute relative error against the dense reference. Counts are reported alongside means so missing outputs cannot masquerade as low average error.

The comparison baseline simply chooses the rightmost dark pixel per row using the same calibration. It does not build CAD or share the main method's continuity and uncertainty logic. Its volume error can look favorable even when large local contour errors cancel, so both local and global measures are necessary.

The original evaluation exposed implementation failures. A second contract fixed fresh procedural seeds before confirmation scoring, while preserving the original gates, first suite and failed outputs. The second test establishes within-generator confirmation; the repeated DTMB geometry is identified as external regression evidence rather than newly unseen data.

## Experimental OCR adapter

`table_ingest.py` recognizes measurements written as feet, inches and eighths of an inch from explicitly selected table cells. It uses two configurations of pretrained Tesseract LSTM OCR and requires exact normalized token agreement plus the fixed confidence threshold. The two passes are correlated views of the same recognizer; they are not independent models and their confidence scores are not probabilities of correctness.

Malformed values, impossible inch/eighth fields, disagreement and low confidence create blocking gaps. Row heights and station positions are supplied with source evidence; numeric half-breadths are not allowed as input shortcuts. The archived Balclutha source states that values describe the inner surface, which is distinct from an outside-plating envelope.

The original 114-cell experiment and the separately versioned official `tessdata_best` model experiment are retained. They do not yield a complete accepted hull. Controlled printed-table tests verify the adapter's geometry and blocking behavior, but those tests are not evidence of successful historical OCR.

## Extending the foundation

The implemented interface for a future learned curve parser is the same section-observation structure: coordinates, source regions, diagnostics and explicit gaps. A model can replace curve extraction while the geometry kernel, evidence ledger, dimensional checks and evaluator remain in place. No project-specific curve model was trained or fine-tuned; OCR uses bundled pretrained Tesseract models. No training job is included in this release.

The generated paired image/geometry data can support initial training experiments. Broader capability will require separately licensed real drawing sets with checked cross-view correspondences, revision labels, station conventions and engineering review. Split future evaluation by vessel/design lineage, not merely image filename, and include full original scans with ambiguous and incomplete evidence. The historical failures here identify a concrete first target: semantic line selection and reliable measurement-table reading.

## Atomic state and trust boundaries (0.2)

A run reserves a fresh destination and stages on the same filesystem. Source
bytes are captured under byte bounds, typed schema validation and full source
metadata preflight precede any raster rendering, and native work runs in the
supported isolated CLI/server profile. Required evidence is fsynced, sealed and
verified before an atomic Linux `renameat2(NOREPLACE)` publication. Reservation
state gates incomplete/unconfirmed publication. Failed work loses all model
exports; orphan staging is quarantined and recovered conservatively. Storage
failures may make an error record impossible and are returned honestly.

`result.json` is the immutable schema 2 inference record. `manifest.json` hashes
every immutable file including that entire result; result does not hash manifest,
avoiding a cycle. Required inventory, local path confinement, identity, source/
replay/section relationships, ruled-section volume, dimensions, approximation
bounds and mesh bounds/counts are checked without re-running native CAD. Mutable
review events reference the manifest digest. This detects inconsistency against
a local manifest, not malicious replacement of the entire evidence package.

Queue state is distinct from inference state: receiving → queued → running →
a truthful terminal outcome. Cancellation is effective before publication; a
fully verified already-durable result is reconciled as committed if a worker dies
after committing but before recording its receipt. HTTP downloads require both
verified evidence and the appropriate terminal queue state for queue-owned runs.
Linux resource controls are not a filesystem/network sandbox or remote identity
service. Local session possession is not authenticated engineering signoff.
