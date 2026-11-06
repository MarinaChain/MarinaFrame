# Authentic data, annotation, and evaluation protocol

## What was acquired

The bounded authentic development tranche contains **five drawing items from three vessels and two source families**. Two items from two new vessels were downloaded during this work. Three Balclutha pages were already present; their bytes, visible drawing identities, and rights basis were rechecked. They are not counted as new acquisitions.

The evidence lives in `artifacts/agentic/data/` and is intentionally separate from committed application source. `inventory.json` describes every item, exact bytes, origin, transformations, calibration evidence, limitations, and permitted uses. `rights-sources.json` records the authoritative sources and whether they were opened directly or available only through an official search result. `split-manifest.json` groups vessels, source families, and cross-collection copies. Acquisition receipts preserve actual HTTP outcomes.

| Item | Acquisition | Available evidence | Limits |
| --- | --- | --- | --- |
| Wapama, HAER CA-67, sheet 5 | New original TIFF and bounded official preview | Two body-plan panels, fractional station labels, feet/metre scale bars, separate port/starboard curves | The drawing explicitly depicts hull distortion; symmetry is unsupported. Companion field notes and corrected offsets were not acquired. |
| USS Monitor, NH50954 | New 1,200 × 431 JPEG archive derivative | Inboard profile, plan, selected machinery cross sections | Low resolution, unresolved calibration, incomplete station set; no complete hull truth. |
| Balclutha, HAER CA-54, sheet 48 | Existing file reverified | One detailed transverse structural section and scale bars | One section cannot determine the whole vessel; structural boundaries compete with the hull boundary. |
| Balclutha, sheet 7 | Existing file reverified | Overlaid body plan and an offset table | The table describes the inner hull. Cells and curve identities have not been independently transcribed/adjudicated. |
| Balclutha, sheet 3 | Existing file reverified | Body, sheer and half-breadth panels; source notes; station spacing evidence | Different panel scales; source assumptions and fairing limit interpretation. |

Three files were newly downloaded: the Monitor JPEG, Wapama TIFF, and Wapama preview. The original Wapama TIFF is 239,360,000 pixels despite its small compressed size. It was retained and its header checked, but not decoded or submitted to the reconstruction engine. Visual inspection used the official 1,920 × 2,485 preview. The TIFF SHA-1 matches the value published in the Commons item metadata. This is provenance checking, not proof of geometric accuracy.

An ALMA HAER lines sheet was identified and its rights basis checked. A bounded request for the observed official TIFF URL returned HTTP 403. That failed acquisition is preserved; no alternate route was attempted for that item. A separate NPS Gallery ALMA package names private creators, so its rights remain unresolved and only its URL was retained. HERCULES was recorded as a candidate, without acquisition. No archive was contacted, no access was purchased, and no whole bundle was transferred to a model provider by the data worker.

## Rights and origin

The National Park Service states that material created for formal HABS/HAER/HALS documentation is public domain. Its copyright guidance separately requires investigation and, where necessary, releases for material created outside the program. An NPS or Library of Congress URL alone is therefore insufficient clearance. The acquired Wapama item has a matching official HAER catalog identity, explicit item-level public-domain metadata, and a visible NPS/HAER title block naming its delineator and date. Balclutha's visible title blocks and official catalog identities were likewise checked. [NPS collection](https://www.nps.gov/subjects/heritagedocumentation/collection.htm), [NPS copyright guidance](https://www.nps.gov/subjects/heritagedocumentation/copyright-guidance.htm), [Wapama catalog](https://www.loc.gov/resource/hhh.ca1521.sheet/?sp=5&st=text).

The NHHC catalog identifies Monitor NH50954 as a plan published in 1862. The acquired Commons file explicitly identifies expired US copyright and describes its upstream caption crop and attempted shadow removal. The generic NHHC collection statement says most images are public domain, with exceptions; the item/date evidence is what supports this file's decision. Direct NHHC page opens timed out or failed during this run; the official search results and successful Commons item retrieval are recorded without claiming a successful direct NHHC fetch. [NHHC item](https://www.history.navy.mil/content/history/nhhc/our-collections/photography/numerical-list-of-images/nhhc-series/nh-series/NH-50000/NH-50954.html), [NHHC archive guidance](https://www.history.navy.mil/about-us/services-and-policies/scan-copyright.html), [acquired file description](https://commons.wikimedia.org/wiki/File:USSMonitorPlan1862.ws.jpg).

Every inventory item distinguishes local evaluation, redistribution, provider inference, and training eligibility. These are US copyright assessments for the specific files, not blanket worldwide claims. Requested archive credit and derivative history are retained. Copyright eligibility does not execute a provider transfer or establish a provider's supported API, retention terms, authorization, or spending budget. The harness must apply its own run gate before any approved inference. No training was run by this workstream.

The origin label is **authentic archival drawing reproduction**. These are real archive drawings, not synthetic curves generated for this benchmark. Some are later measured documentation or digital derivatives rather than original shipyard construction sheets. The complete upstream raster-production process is not established for every file, so the inventory does not invent a physical scanning history. Synthetic renderings and their degradations must retain separate origin labels.

## What the drawings actually support

Balclutha's sheet 3 describes measurements of the **inner** hull, with only the starboard side measured. Symmetry, absence of hogging, sweep, and racking were assumptions. The source says curves were faired, describes finite drawing accuracy, and notes a possible damaged region. Those assumptions must remain attached to any derived model. A visually plausible outer shell is not a measured exterior hull.

Wapama is a valuable counterexample: the source explicitly presents both sides because the hull is distorted. A tool restricted to symmetric reconstruction should preserve that uncertainty and request review or decline reconstruction. It should not mirror one side to satisfy its input schema. Monitor tests another boundary: visible plans and sections do not supply a complete, calibrated station set.

Without independent authoritative geometry, useful real-data measures are:

- Agreement of independently checked labels, scale anchors, station identities, and dimensions.
- Pixel tracing agreement against separately reviewed source annotations, with unresolved alternatives retained.
- Number and type of reviewer corrections, review time, and reproducibility from immutable inputs.
- Detection of unsupported symmetry, incomplete stations, conflicting revisions, and calibration gaps.

The same trace cannot generate a hull and serve as independent proof that the hull is correct. STEP round trips and reprojection of that trace assess implementation consistency, not true vessel accuracy. This tranche has **zero independent whole-hull ground truths and zero expert-reviewed gold annotation sets**.

## Annotation contract and review workflow

`schemas/annotation-v1.schema.json` defines the annotation document. Coordinates refer to one exact hashed image, with top-left origin, x right, y down, and half-open bounding boxes. A crop or resize is a new asset with an explicit parent transform. Do not silently reuse coordinates across image versions.

Feature kinds cover panels, station identities and positions, centreline, datum, scale anchors, contour alternatives, occlusions, dimensions, revision marks, unsupported geometry, source notes, and explicit unknowns. Each feature records whether it is directly observed, inferred, or unknown; its evidence asset/hash/inspection reference; its review status; and uncertainty. Inferences require a derivation. Unknown values are null, not invented estimates. Contour alternatives preserve distinct interpretations without forcing a selection.

Five example annotation documents are under `annotations/`. They contain provisional assistant panel regions, source notes, readable label sets, and explicit unresolved fields. They are not checked contour traces or training targets. The five corresponding `overlays/` images clearly label themselves provisional. A contact sheet makes their approximate regions reviewable while keeping the archival images unchanged.

Use this workflow for new annotations:

1. Verify the source hash, rights decision, and grouped split before opening the image. Final-held-out inputs must remain sealed until evaluation.
2. Inspect a bounded full-page image, then focused crops. Record the exact inspected files in an inspection ledger. Merely generating a preview is not inspection.
3. Annotate observed text and regions first. Keep station x positions, datum, curve identity, and units unresolved until direct evidence supports them. A printed scale ratio does not by itself calibrate a resized raster.
4. Save a new immutable annotation revision with the previous revision hash. Render a separate overlay and inspect it against the source. Preserve alternatives, changes, and disagreement positions.
5. Have a qualified human engineer review accepted geometry/calibration labels. For authoritative evaluation, use a second independent qualified reviewer and adjudicate disagreements. The same model's prediction cannot serve as its independent reference.
6. Promote only the accepted, independently reviewed revision to gold. Schema structure alone cannot verify professional qualification or that two reviewer IDs are different people; the review ledger must establish those facts. Unresolved unsupported geometry remains unresolved even after review.

`annotation-validation.json` records actual checks: JSON parsing, image hashes, unique feature IDs, in-image bounds, null unknowns, derivation for inferences, and absence of gold/expert claims. A full JSON Schema validator was not available in the data worker's Python environment, so full Draft 2020-12 validation is explicitly marked not run. No geometry accuracy is inferred from these structural checks.

## Splits and leakage

Split connected groups before selecting examples or tuning. A group includes all pages of one underlying vessel, original scans, thumbnails, crops, renderings, revised drawings, and cross-collection copies. Source families also stay in one split. Hash identity catches exact copies, while catalog identity and revision provenance catch copies with different bytes.

The current assignments are deliberately simple: **all five items are development data**. Balclutha and Wapama share the NPS HAER maritime source family. Monitor belongs to the NHHC historical-engraving family. Every acquired item was inspected during this work, so none is an untouched final holdout. No artificial train/test separation is claimed by placing one Balclutha page or one Wapama crop into another split.

For a future authentic final evaluation, reserve new vessels from disjoint source families before annotation or tuning. Keep their input pixels and evaluator annotations out of training, prompt examples, retrieval, active-learning selection, and tuning feedback. Evaluation-only access begins after code/configuration freeze. If a failure is used to change the system, that case becomes development data for the next iteration and requires a fresh final set.

Robustness coverage here includes overlapping curves, structural hatching, multiple scales, fractional station labels, asymmetric as-is geometry, low-resolution reproductions, and incomplete calibration. It does not establish broad coverage of damaged shipyard paper, diverse national drawing conventions, camera perspective, or proprietary contemporary CAD workflows. Synthetic degradation may complement these cases, but it does not add independent real vessels.

## Inference, examples, and training

Calling a pretrained model is inference. Changing prompts, tool contracts, retrieval, or the deterministic geometry pipeline does not update model weights. Permitted examples may improve context without training, but they can still disclose data to a provider or leak evaluation answers. Run evidence must identify the actual inputs sent.

This tranche does not justify fine-tuning: three vessels, no expert-reviewed contours, and no independent whole-hull truth are insufficient. First fix deterministic geometry and evaluator defects, make calibration and uncertainty explicit, and measure whether model assistance reduces review effort on development cases. Active learning can prioritize uncertain and diverse development cases such as Wapama's asymmetry or Balclutha's contour crossings. It must never select from the sealed final set.

Training becomes a concrete option only after a supported service, rights, authorization, budget, sufficient reviewed labels, and a measured bottleneck are established. OpenCode Go access alone does not establish fine-tuning capability. The current result is a rights-checked development dataset and usable labeling protocol, not a trained reconstruction model or a validated training corpus.
