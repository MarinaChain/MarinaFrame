# GA arrangement input (estimated 3D arrangement from one GA)

`src/vessel_reconstruction/ga_arrangement.py` and `benchmarks/ga_arrangement/` build an
ESTIMATED 3D arrangement from a GA reading. They do no reading themselves: the GA reader
(`ga_commercial`, schema `marinaframe.ga_reading.v1`) is the only reader. This file says what
that reading must carry for the arrangement step.

Every run made this way shows on every page (presentation `credit`):

> Estimated 3D arrangement from a single GA drawing. The hull shape is estimated (no lines plan);
> compartments are read from the GA. Not a CAD model; not for construction.

The hull is labelled "Estimated hull, no lines plan". `engineering_approved` is always false.

## Input

A `marinaframe.ga_reading.v1` file, as the GA reader writes it, with these additions. Fields not
listed here are ignored. Axes: metres; x forward from the aft perpendicular (frame 0), y to
port, z up from the baseline.

| Field | Required | Meaning |
|---|---|---|
| `schema` | yes | `marinaframe.ga_reading.v1` |
| `case_id` | yes | case ID (for example GA-005); the run is named by it only |
| `engineering_approved` | yes | false |
| `sources.ga.file` | yes | the GA image file name; every region's `sheet` names it |
| `particulars.breadth_m`, `.depth_m` | yes | `{value, status, source_record}`. `read` and `measured_from_scale` are from the drawing; any other status with a value (`guessed`, `derived_from_space_tops`, ...) is used as an estimate and named in the hull's record and the run note; `unknown` is refused |
| `particulars.depth_m.uncertainty_m` | no | measurement uncertainty; the depth check's tolerance (at least 0.3 m). Only a depth from the drawing is checked (never one derived from the space tops) |
| `particulars.lbp_m` or `.loa_m` | one of them | as above; with both, the hull length is LOA, else LOA = 1.04 LBP (guessed) |
| `frames.spacings` | when an extent uses frames | `[{from_frame, to_frame, spacing_mm}]`; frame 0 is the AP |
| `hull_outline.deck_half_breadth_m` | no | `[[x, half_breadth], ...]` of the deck edge (upper deck plan) |
| `hull_outline.profile_xz_m` | no | closed polygon `[[x, z], ...]` of the hull in the profile; the lofted hull is cut by it |
| `spaces[]` | yes | the reader's spaces (`id`, `kind`, `label`, `status`, `source_record`), plus `extent` |
| `test_fixture` | no | true for test data; such a run is named "(TEST DATA)" and needs `--test-fixture` |

### `spaces[].extent`

```json
{"frames": [34, 70], "z_m": [1.5, 12.05], "side": "both",
 "status": {"x": "read", "z": "read"}}
```

| Field | Meaning |
|---|---|
| `frames` or `x_m` | aft and forward ends (frame numbers or metres) |
| `y_m` | `[starboard, port]` limits; absent: a rule below (guessed) |
| `z_m` | bottom and top above the baseline; absent: a rule below (guessed) |
| `side` | `both` (default), `port`, `starboard`, `centre` |
| `tier` | deckhouse tier number (1 = on the upper deck), used when `z_m` is absent |
| `status` | `read`, `measured_from_scale` or `guessed` per axis (`x`, `y`, `z`); an axis given without a status is `read`. `measured_from_scale` counts as read (drawn ink measured with the frame scale) |

A space without `extent` is skipped and listed in the run's `ga_estimate.json` (`skipped`).

Kinds (the reader's vocabulary): below the deck, cut by the hull: `cargo_hold`, `cargo_tank`,
`slop_tank`, `ballast_tank`, `fuel_tank`, `other_tank`, `engine_room`, `other_space`; on or above
the deck: `accommodation_deck` (a deckhouse tier), `cargo_hatch` (coaming), `cargo_crane` (post).
Other kinds are skipped.

### Rules for a missing extent (each is recorded as `guessed`, with its basis)

| Item | y | z |
|---|---|---|
| space, side `both` | full breadth inside the hull | baseline to deck |
| side `port` / `starboard` | that half of the hull | baseline to deck |
| side `centre` | 30 % of the breadth about the centreline | baseline to deck |
| deckhouse tier | breadth less 1.0 m a side | tier n: deck + 2.8 (n-1) to deck + 2.8 n |
| hatch coaming | (required) | deck to deck + 1.5 m |
| crane post | on the centreline | deck to deck + 0.6 B |

## Method

1. **Estimated hull.** A station table (31 stations, every row `prior`) in the section family
   of `form_fit.section_shape`. Deck half-breadth from `hull_outline.deck_half_breadth_m`, else
   a full-form plan shape (parallel body from 22 % to 70 % of the length, transom 80 % of the
   half-breadth, tapered bow). Section fullness and bottom flat run from fine ends to a
   wall-sided body with a bilge. The keel rises at the stern (guessed) unless a profile outline
   is given; then the loft is cut by that outline. The hull is lofted in CadQuery. Hull ends:
   the overhang LOA - LBP is split 40 % aft of the AP and 60 % forward of the FP (guessed); when
   an item read on the GA reaches further aft, the hull starts at that item (at most the whole
   overhang aft of the AP) and keeps the length LOA.
2. **Items.** Boxes in metres; below-deck spaces are cut by the hull and carved from the
   smallest to the largest, so a tank drawn inside a hold keeps its volume and the hold gets the
   rest. Checks (findings, not refusals; a run with a finding is not shown until it is
   explained): L/B in 4..9 and B/D in 1.2..2.6; the depth agrees with the median top of the
   cargo holds and tanks whose z was read, within the depth's `uncertainty_m` (at least 0.3 m);
   an item outside the hull length; cargo holds that overlap by more than 1 m in x; a space with
   nothing left after carving.
3. **Source records.** Each part keeps the reader's regions. A part whose extents were all read
   keeps a `read` record; a part with a guessed extent gets a `guessed` record whose method names
   the rule and whose inputs are the reader's regions, so hover-to-source still shows them. The
   hull's record is `guessed` with the particulars' regions as inputs.

## Output

`python -m benchmarks.ga_arrangement --reading R.json --image GA.png --out work/... --split SPLIT.json`
writes `runs/<case>-ga-estimate/` in the concept run's form (`state.json` with policy
`ga_estimate`, `presentation.json`, `whole_vessel/execution.json` and GLB, the hull build,
`intake/` with the GA, `exports/r0001/` with the estimated hull STEP/STL and an arrangement CSV,
`ga_estimate.json` with the findings, the skipped spaces and `reading_source`: `--source-round`
and `--source-commit` name the reader's round and commit) and `<slug>.web-selection-entry.json` for `scripts/web_demo_runs.json`
(licence `owner-cleared-ga`, credit = the label above). Images, readings and runs stay under
`work/` (git-ignored).
