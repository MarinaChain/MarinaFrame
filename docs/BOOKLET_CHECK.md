# Booklet check

Compare a built hull with the ship's printed hydrostatic values. This is evidence
for that hull and those loading conditions. It is not a stability approval.

The booklet comparison is secondary evidence only. Integrated quantities such as
displacement, LCB and KMT can agree while the local hull shape is wrong. The
primary accuracy number remains the section-shape error at withheld stations.
A booklet match does not replace that shape check or supply a missing shape-error
measurement.

## Plan

1. Define the quantities, units, datums, tolerances and labels here.
2. Read the DSYHS workbooks and IGES canoe bodies. Run the existing mesh engine
   before adding the customer comparison. Save all rows and error statistics in
   `work/booklet-check/` (git-ignored). Keep extracted geometry in `work/booklet-check/`.
3. Add a JSON booklet reader and a comparison module. Test against exact box and
   Wigley integrals, then test missing data, trim, units and range boundaries.
4. Add optional booklet input to the export API and CLI. Add a short PDF section,
   a complete CSV in the package, and a run-specific hull accuracy summary.
   Run the related tests and the Python quick tier. Leave all changes uncommitted.

## Quantities and starting tolerances

These are our starting values for a reconstruction check, not class rules or
published acceptance limits. They allow for drawing resolution, hull tessellation
and rounded printed values. The architect must review limits for each ship.
An error equal to the limit is within tolerance. Where two limits are given,
use the larger one. `L` is the built hull's overall x extent, in metres.

| Quantity | Canonical unit | Maximum absolute error |
| --- | --- | --- |
| Displacement volume | m3 | 2% of printed volume |
| Displacement mass | t | 2% of printed mass |
| LCB | m | max(1% L, 0.5 m) |
| VCB (above booklet vertical datum) | m | max(1% of printed VCB magnitude, 0.05 m) |
| KMT (above keel) | m | max(1% of printed KMT magnitude, 0.05 m) |
| Waterplane area | m2 | 2% of printed area |
| LCF | m | max(1% L, 0.5 m) |
| TPC | t/cm | 2% of printed TPC |
| MCT 1 cm | t m/cm | 2% of printed MCT |

Volume, mass, area and their small-change derivatives use 2% to expose a scale
or shape error. Centre positions use length or an absolute floor because a centre
can lie at or near the datum, where a relative percentage is not useful. KMT and
VCB use a small absolute floor for the same reason. The 0.5 m floor is generous
for small craft; always show the numerical error as well as the label.

TPC = density * Awp / 100. MCT here means the hydrostatic small-angle moment for
1 cm trim over the stated trim length: density * I_LCF / (100 * trim_length).
It omits the displacement * (KB - KG) contribution to the exact longitudinal
righting moment. An exact stability MCT needs KG, which this hull check does not
know; such a booklet MCT is not comparable. KMT = KB + BMt.

## Drafts and labels

Keep every printed row, in printed order. Compare every even-keel row inside the
built vertical range. No interpolation of booklet values or draft extrapolation.
Draft is height above the booklet's vertical datum; convert it to model z before
calling the engine. The keel itself has zero immersed volume and is not comparable.
The upper bound is the highest point of the built geometry, inclusive.

Each draft has all nine quantity rows. Labels are exactly `within tolerance`,
`outside tolerance`, and `not comparable`. Missing printed quantities, non-even
keel conditions, drafts outside the range, unsupported MCT definitions and failed
calculations get `not comparable` with a reason. A zero printed reference has an
absolute error but no relative error. Never replace missing values with zero.
The summary is `booklet check: N of M within tolerance`, where M counts comparable
quantity cells, not drafts. Report the number not comparable separately. A 0 of 0
summary must state that no values are comparable.

## Engine check data

Source files are named in `work/sources/dsyhs/manifest.tsv` in the main checkout.
The manifest records hashes, retrieval dates and CC0 terms. Sources:
[DSYHS geometries](https://doi.org/10.4121/21501330.v1) and
[DSYHS hydrostatics](https://doi.org/10.4121/21501375.v1).
The workbook `Info` sheet defines `lcb0` and `lcf0` relative to half the upright
waterline length. Only upright `*0` columns apply; `*10`, `*20`, `*30` are heeled.
There are 61 printed rows per scale, including shortened overhang variants.
The archive contains model-scale surfaces in millimetres, plus separate appendages.
Most canoe bodies have one side; SYSSER43 has both sides. Reflect only a single-sided
canoe body about y=0, preserve face orientation, and omit appendages. A full hull
must be kept once. Some half-hull splines overshoot y=0 slightly. A sign crossing
alone is not a full side: the adapter requires equal port/starboard breadth
extents within twice the absolute chord tolerance for these symmetric canoe bodies.
Full-scale geometry is obtained by the full/model printed Lwl ratio;
there is no independent full-scale IGES archive in the supplied manifest.

## Booklet JSON (version 1)

See `examples/booklet_box.json` for a complete, exact-answer example. Input is
JSON; output is CSV. Do not supply a screenshot or guess a printed number.

Required fields:

- `schema_version`: integer `1`.
- `trim`: `even_keel`, `trimmed` or `unknown`. Only `even_keel` is compared.
- `density`: `{ "value": 1.025, "unit": "t/m3" }`. Density is required; no
  seawater default is used for a booklet. `kg/m3` is also accepted.
- `datum`: `{ "x_origin_m": 0, "x_direction": 1, "z_origin_m": 0 }`.
  Origins are the booklet datums' positions in model coordinates, in metres.
  `x_direction` is +1 if positive booklet distances run along model +x, or -1
  if they run along model -x. Positive vertical distances run upwards.
  Draft and VCB use this vertical datum. KMT uses the built keel, regardless of
  the booklet datum. Convert a printed KM above another datum before entering it.
- `units`: unit for `draft` and for each supplied quantity column.
- `rows`: a non-empty array. Each row has `draft` and any of `volume`,
  `displacement`, `lcb`, `vcb`, `kmt`, `waterplane_area`, `lcf`, `tpc`, `mct`.
  Omitted quantities and JSON `null` mean not printed. Zero is a real value.

Optional fields: `title` (text), `trim_m` and `heel_deg` (default zero). Nonzero
trim or heel makes all cells not comparable, even if `trim` says `even_keel`.
For MCT, specify `mct_basis: "hydrostatic"` and positive `trim_length_m` in metres.
`stability`, `unknown`, or an omitted basis makes MCT not comparable. An omitted
trim length also makes MCT not comparable. Other quantities still apply.

Supported units (converted once at input; results always use the canonical units
in the quantity table):

| Quantity group | Input units |
| --- | --- |
| Draft, centres, KMT | `m`, `mm`, `ft` |
| Volume | `m3`, `ft3` |
| Mass | `t`, `kg` |
| Area | `m2`, `ft2` |
| TPC | `t/cm`, `kg/cm` |
| MCT | `t*m/cm`, `kN*m/cm` (divide by standard gravity, 9.80665 m/s2) |
| Density | `t/m3`, `kg/m3` |

Unknown units, misspelled quantity fields, non-numeric or non-finite values and
missing metadata are input errors. The CLI returns exit 2 with a JSON error
before writing exports. Booklet rows can repeat a draft; the CSV has a printed
row number so each remains distinct. It gives signed error (computed minus
printed), signed percentage error (divided by the magnitude of the printed
value), absolute tolerance, label, reason and engine method.

The engine first uses the built STL, in its declared units. Without an STL it
uses the built section curves and states that the table method integrates only
the stations. It does not compare another reconstruction or substitute a table
value as a computed value. The PDF lists per-quantity counts and maximum absolute
errors; the CSV keeps all cells. Both preserve the draft status.

## Usage and product hooks

```bash
set -o pipefail
PYTHONPATH=src:. .venv/bin/python -m vessel_reconstruction.exports \
  --task /path/to/task --revision r3 --out outputs/my-ship \
  --booklet /path/to/booklet.json
```

Python: `export_draft(task, "r3", out, booklet=Path("booklet.json"))`, or pass a
`Booklet` from `parse_booklet` / `load_booklet`. The input file and task are read
only. With no booklet, the existing export file list and summary stay the same.
With a booklet, `<stem>_booklet_check.csv` has manifest role `booklet_check` and
goes into the ZIP. `manifest["booklet_check"]` gives the cell counts.
`accuracy_summary.facts_from_build(..., booklet_summary=check.summary)` adds the
run-specific check to `summarise(...)["hull"].line`. Existing measured bands stay
separate; a booklet result does not create a general accuracy band.
No app screen or booklet upload flow is added. The Python export API and CLI are
the product entry points in this change.

To repeat the engine check (the source path may be in the main checkout):

```bash
set -o pipefail
PYTHONPATH=src:. .venv/bin/python scripts/check_dsyhs_hydrostatics.py \
  --source /path/to/MarinaFrame/work/sources/dsyhs \
  --scratch work/booklet-check --out work/booklet-check
```

The runner checks input SHA-256 hashes against the supplied manifest. It uses
absolute 0.05 mm chord deflection and 0.05 rad angular deflection on model-scale
IGES surfaces. Each geometry import and mesh runs in a separate process with a
60 s limit. Missing geometries and failed imports are listed separately, never
removed from the printed-row count. CSV contains every computed comparison;
JSON contains per-quantity mean signed error, mean/max absolute error, RMS error,
and mean/max absolute percentage error. A zero printed centre is excluded only
from percentage statistics. Absolute errors still include it. For centres near
zero, use the absolute errors or the CSV's percentage of Lwl instead.

## Validation

Tests use a closed box barge (40 x 8 x 5 m), including the exact top draft, and a
Wigley hull. The box values are exact for both the mesh and the table integration
except for the table's longitudinal inertia quadrature. The test uses 101
stations and a 0.03% numerical limit. Wigley half breadth is
`B/2 * (1 - (2*x/L - 1)^2) * (1 - ((z-T)/T)^2)`, with keel z=0 and design
waterline z=T. Integrating the polynomial gives exact volume, VCB, waterplane
area and both waterplane moments. Tests at d=T/2 and d=T compare all nine
quantities to those integrals with a 0.1% numerical limit. These numerical test
limits are much tighter than the product's starting reconstruction tolerances.

The top-draft test exposed an existing mesh-engine edge case: a horizontal deck
face on the cut plane cancelled the waterplane flux. Coplanar cap triangles are
now excluded from the wetted shell, so the result at the top is the limit from
below. A separate regression checks area, LCF, volume and BMt at that boundary.

Final focused check: **104 passed**. It includes the closed-form comparisons,
input and condition edge cases, CSV/PDF/ZIP and CLI integration, the required
secondary-evidence wording, the accuracy summary and band regressions, and the
DSYHS reader tests (including full-hull preservation and centreline overshoots). Command:

```bash
set -o pipefail
MPLCONFIGDIR="$PWD/work/booklet-check/mpl-cache" \
XDG_CACHE_HOME="$PWD/work/booklet-check/xdg-cache" \
PYTHONPATH=src:. .venv/bin/python -m pytest -q \
  tests/test_booklet_check.py tests/test_booklet_exports.py \
  tests/test_dsyhs_engine_check.py tests/test_exports.py \
  tests/test_accuracy_summary.py tests/test_accuracy_bands.py
```

An earlier broader Python quick-tier run had **1,487 passed, 4 failed, 11 setup
errors, 45 deselected**. The four failures were in `test_runtime.py`: process
identity was unavailable because macOS process inspection was denied in this
sandbox, so the process-group cleanup tests also timed out. The eleven setup
errors were in `test_rust_review.py`: binding a local HTTP socket was denied
(`PermissionError: Operation not permitted`). No unrelated runtime or review
code was changed. Rust checks and the full CAD test tier were not run. These
limits do not change the final focused-suite result.

## Measured DSYHS engine results (2026-11-10)

Final files: `work/booklet-check/dsyhs_engine_check.csv` (464 comparison
cells) and `work/booklet-check/dsyhs_engine_check.json` (input hashes,
settings, omissions and statistics). There are **58 of 61 printed variants
compared at each scale**. The full-scale check uses the scaled model IGES, not
an independent full-scale geometry sample.

| Quantity | Model mean absolute error | Model maximum absolute error | Full mean absolute error | Full maximum absolute error |
| --- | --- | --- | --- | --- |
| Volume (m3) | 0.000192886 | 0.000675762 | 0.0393162 | 0.140536 |
| LCB (m) | 0.00244479 | 0.0119750 | 0.0129605 | 0.0598749 |
| Waterplane area (m2) | 0.00452038 | 0.0123499 | 0.148556 | 0.350351 |
| LCF (m) | 0.00290085 | 0.0139362 | 0.0152365 | 0.0696812 |

Volume mean/max absolute percentage errors are **0.563% / 1.531%** at both
scales. Waterplane-area mean/max errors are **0.741% / 1.734%**. All 58 volume
and all 58 area values at each scale are within 2%. Maximum centre errors are
**0.599% Lwl for LCB** and **0.697% Lwl for LCF**, both within 1% of Lwl (tighter
than the product's length-or-0.5 m starting limit). All 464 available cells are
within the stated starting tolerances. Signed means, RMS and percentage
statistics for every available quantity are retained in the JSON. One printed
LCB is zero; it remains in the absolute-error statistics and is excluded from
relative-error statistics only.

Three printed variants per scale remain unavailable:

- SYSSER18, original overhang: the IGES import/mesh exceeded the 60 s limit.
- SYSSER29, half overhang: `SYSSER29_05_surface.igs` is absent from the archive.
- SYSSER29, no overhang: `SYSSER29_0_surface.igs` is absent from the archive.

The runner returns exit 1 for these incomplete inputs; this is not an assertion
that the available comparisons failed. No missing geometry was replaced by
another variant. The DSYHS canoe-body tables do not print displacement mass,
VCB, KMT, TPC or MCT. Those quantities have **no DSYHS printed-value comparison**;
their formula and engine paths are tested with the exact barge and Wigley
answers instead. The data check supports the integrated engine calculations;
it does not measure local section-shape error at withheld stations.
