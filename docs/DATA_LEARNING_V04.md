# v0.4 data, annotations and local learning evidence

This work continues the published v0.3 PR2 source at
`5b0b48e3dd9bcef25427d27ce800118935f58d1a`. It adds an executable data
preparation path and a narrow learned-weight experiment. It does not establish
engineering accuracy on authentic ship drawings.

## Actual acquisition and source access

The current acquisition downloaded all six original TIFF assets from the
previously identified **ALMA / Tri-Coastal Marine / Bill Doll NPS Gallery
package**: **725,271,046 bytes**, six HTTP200 receipts, six original SHA-256
hashes, and verified image headers. The package contains **five drawings and one
photo/title cover**, representing **one additional vessel**. Original files are
preserved unchanged. Six bounded previews and four native-resolution crops were
actually opened and inspected; the ledger distinguishes those views from a
claim to have inspected every original pixel.

The [NPS package record](https://npgallery.nps.gov/AssetDetail/dc1e70a0-f7a8-4718-93df-bdfb84ecab17)
provides the six related item links and their original download links. The five
drawings comprise a sail plan, deck/outboard profile, hold/inboard profile, cross
sections, and a lines/offsets sheet. The package includes drawings dated 1987 and
1989; the cover commemorates 1991. These are dated source records of the same
vessel, not independent vessels or a modern commercial fleet dataset.

The owner's current instruction authorizes acquisition, local training and
local testing of the previously discussed commercial sources. That authorization
is recorded and was used: no additional permission request or purchase was made.
The private contract was **not independently inspected**. The NPS metadata has
both general copyright/study wording and a public-domain constraint, while
naming private creators. Source redistribution, derived distribution and transfer
to a model provider remain separately unresolved. Therefore all six originals,
their previews/crops, new annotations, local packet and restricted label exports
stay under `artifacts/v04/data/restricted/`. They must not enter an unrestricted
release or a provider request. The
[NPS copyright guidance](https://www.nps.gov/subjects/heritagedocumentation/copyright-guidance.htm)
distinguishes formal HAER documentation from third-party or collaborative
material; hosting alone is not treated as a universal license.

The recovered project source list is Balclutha HAER CA54, Wapama HAER CA67,
Monitor NH50954, mathLab DTMB5415, ALMA HAER CA60, the ALMA third-party package,
and HERCULES HAER CA62. DTMB is an authored CAD reference, not an authentic scan.
A current HERCULES official-page request returned HTTP403. The previous ALMA
HAER original request also returned HTTP403; that historical receipt is retained.
No alternate route was used to circumvent either denial. No exact private-vendor
account, licensed download entitlement or contract appeared in the available
project records or recovered conversation context. Those access details were not
invented; that is the concrete remaining acquisition gap.

`scripts/data_acquire.py` consumes an explicit operator manifest. It records
intent before each download, restricts HTTPS requests and redirects to declared
hosts, rejects serialized credential-bearing URLs, bounds bytes/time/pixels,
checks optional expected hashes, preserves partial failures, and does not retry
or select mirrors. A mixed or failed acquisition exits unsuccessfully while
retaining receipts. Fifty focused data/acquisition tests pass, including mocked
HTTP403, hash mismatch, byte bounds and rejected redirects.

## Versioned annotation pipeline

| Measure | Actual count |
|---|---:|
| Inherited authentic items | 5 |
| Newly acquired drawings / cover | 5 / 1 |
| Total authentic items / drawings | 11 / 10 |
| Vessels / source families | 4 / 3 |
| New annotation documents / features | 6 / 43 |
| Total annotation documents / features | 11 / 73 |
| Provisional raw offset-cell transcriptions | 45 |
| Qualified expert gold sets | 0 |
| Authentic final holdout vessels | 0 |

The 45 cells are a raw transcription inside one provisional table feature; they
are not 45 independent expert labels. Fraction conventions and plus suffixes
remain unresolved. No coordinates were converted into a 3D hull. Source-specific
review questions include two different scales on the cross-section sheet,
looking-forward versus looking-aft orientation, nonuniform end station spacing,
internal versus exterior structural boundaries, and later replacement rigging.

`src/vessel_reconstruction/dataset_pipeline.py` uses **jsonschema 4.26.0's full
Draft202012Validator**, format assertions and additional domain checks. The
previous v1 schema itself is retained. The checks cover conditional requirements,
strict types, positional arrays, unknown fields, source asset hashes/dimensions,
confined ordinary-file paths, coordinate bounds, feature identities, conflicting
alternatives, evidence references, review references and revision hashes. Remote
schema retrieval is disabled. Gold-marked documents require two distinct
registered qualified-reviewer assertions covering every feature; locally supplied
role records are explicitly **not authenticated professional identities**.
Validation never promotes an annotation or sets engineering approval.

All **11 documents pass**. Vessel, design, source-family, exact-byte duplicate
and declared near-duplicate links form connected split groups. Three connected
groups result, all in **development**. A dHash256 candidate screen found no close
pairs among the eleven display assets, but that does not prove independence;
all views/crops of each vessel stay together regardless. Historical final sets
remain development knowledge. No authentic generalization score is claimed.

The strict export emits **0 accepted training rows**. Explicit
`--allow-provisional` emits **61 research rows**, each retaining provisional
status, source identity, rights and `gold_truth=false`. Unknown/disputed/rejected
labels and non-development examples are withheld from training. These rows were
**not used for weight updates**.

The local review packet contains all eleven images and expandable complete
labels, coordinates, source evidence and uncertainties. The release packet
contains the five inherited cleared images and visibly omits the six restricted
items. Browser checks found eleven/five complete images respectively, six
omissions, working disclosure controls, no page errors and no external requests.
Both screenshot outputs were actually viewed. A qualified naval architect's
review remains outstanding; a packet is preparation for that review, not a
substitute for it.

## Actual local learned-weight experiment

`scripts/data_line_learning.py` trains a small NumPy MLP to classify an
**already supplied isolated ink location** as grid or contour. It reads two
pixel patches, with no coordinates, family IDs, render masks or reference CAD
passed to the learner. Known procedural drawing layers supply the labels.
Grid/contour darkness and width vary independently. Intersections and locations
within three pixels of another class are excluded, so dense crossings are a
stated coverage gap. No authentic drawings or expert gold labels enter training.

The model has **18,594 trainable parameters** and performed **4,320 gradient
updates per run**. Development comprises 144 panels / 6,912 query patches from
four shape families; validation comprises 36 panels / 1,728 patches from a
fifth family. Validation alone selects the checkpoint and heuristic threshold.
The protocol and selection record are written before final-test pixels are
generated. Initial/selected weights, hashes, manifests and training history are
retained. Training cross entropy fell from 0.702888 to 0.001244; selected weights
have an L2 change of 2.636911 from initialization. This is real weight updating,
not a prompt or retrieval experiment.

Run1 is preserved unchanged. Its best baseline threshold was at the upper edge
of the originally declared search range. The corrected run2 protocol expanded
that search over 0.05–1.01 and reserved a newly generated tumblehome family for
one final evaluation. Validation still selected 0.80. Both runs selected the
same learned weights; this is **one learned model configuration evaluated in two
procedural experiments**, not two independent trained capabilities. The earlier
reverse-flare test is now development knowledge.

| Run2 final procedural test | Axis-support heuristic | Learned MLP |
|---|---:|---:|
| Panels / labelled queries | 36 / 1,728 | 36 / 1,728 |
| Balanced accuracy | 80.79% | **96.59%** |
| Macro F1 | 80.79% | **96.58%** |
| Grid recall | 80.32% | 99.65% |
| Contour recall | 81.25% | 93.52% |

The accuracy difference is **15.80 percentage points**; a paired bootstrap that
resamples whole panels gives a 95% interval of **11.23–20.89 points**. The model
still misclassified **56 contour queries as grid and 3 grid queries as contour**.
All predictions and selected failure patches are preserved. Those failures are
why the experiment does not enable automatic ink deletion or production contour
selection. The synthetic reference is authored by this project, so the test is
not an independent external benchmark. It says nothing quantitative about
calibration, tracing complete curves, selecting station identities, building CAD,
or real-vessel hull accuracy. No base LLM was fine-tuned and no paid training
provider was used.

Two optimizer runs were executed; shared development/validation images and
identical selected weights must not inflate data/model counts. Across both runs
there are 252 distinct procedural panels: 144 development, 36 validation, and
72 across the two separately recorded test families. Real-source training images,
qualified labels and provider calls in this workstream are all **zero**.

## Reproduce and inspect

Install the data validator into a project environment using
`requirements-data-linux-py312.lock`. The learning experiment has a separate
`requirements-learning-linux-py312.lock`, now recommending **NumPy 2.3.5 and
Pillow 13.0.0** in its own Python 3.12 environment. Both recorded runs actually
used **Pillow 12.3.0**, NumPy 2.3.5 and Python 3.12.14 on Linux x86_64; their
environment records and experimental results remain unchanged. Inputs and
schema are explicit; outputs must be new directories.

The optional Pillow pin/hash was corrected after the inference freeze because
the official OSV query on **6 November 2026** returned 59 advisory records for
12.3.0 (41 groups connected by aliases); the repeated query for 13.0.0 returned
none. No exclusion or filename-only mitigation was applied. The original lock,
all advisory records and actual installed wheel notices are preserved under
`artifacts/v04/release/dependencies/learning-python/`; see
`docs/DEPENDENCIES_V04.md` for exact hashes, scope and limitations. The base CAD
lock, frozen application and historical learning environment were not changed.

A read-only compatibility replay under the existing old and release environments
used Run 2's unchanged selected weights, threshold and 36 retained PNGs
(1,728 queries). Both reproduced the historical prediction lists and metrics
exactly; newly derived pixel, feature, normalized-feature, probability and
prediction arrays were byte-identical. All 43 original files were unchanged.
The original feature arrays were not persisted, so that array comparison is
between the two new replays. This check involved no installs, retraining,
parameter selection or new untouched accuracy evaluation. Its report is
`artifacts/v04/release/dependencies/learning-pillow13-compatibility/comparison.json`.

```bash
python -m venv /tmp/marinaframe-data
/tmp/marinaframe-data/bin/pip install --require-hashes -r requirements-learning-linux-py312.lock
/tmp/marinaframe-data/bin/pip install --require-hashes -r requirements-data-linux-py312.lock
PYTHONPATH=src /tmp/marinaframe-data/bin/python scripts/data_pipeline.py \
  --schema schemas/annotation-v1.schema.json --asset-root artifacts/v04/data \
  build --manifest artifacts/v04/data/dataset-manifest.json --out /tmp/dataset-checked
/tmp/marinaframe-data/bin/python scripts/data_line_learning.py --out /tmp/learning-replay
```

Key evidence under `artifacts/v04/data/`:

- `acquisition-summary.json`, `public-acquisition-receipts.json`,
  `dataset-validation-summary.json`, `duplicate-audit.json`, `tests.log`.
- `procedural-learning-run1/` and `procedural-learning-run2/`: protocols, actual
  script snapshots, images, weights, metrics and failure evidence.
- `release-review.html` and `review-packet-browser-qa.json`.
- `restricted/`: originals, derived ALMA content, all original receipts,
  provisional annotations, complete local review packet and both label exports.

The release inventory explicitly excludes `restricted/`. This exclusion does
not withdraw the owner's local training/testing authorization. Additional real
training should follow independent label review and a genuinely separated
vessel/source holdout; professional accuracy requires independent reference
measurements and qualified review beyond these experiments.
