# Rules v1: cited rule data and agreement with MiDShip

Workstream W4 of `docs/STRATEGY_2026Q4.md`. Status: v1 complete for the MiDShip rule set.

## What this is

Rules are data. Each rule has a citation, units, applicability, a status, and an executable check.
The checks run without network access. They give the same output for the same input.

This version encodes the 25 hull scantling constraints in the MiDShip dataset. MiDShip (arXiv
2610.02214) derives them from the ABS Rules for Building and Classing Marine Vessels (MVR).
The agreement run compares the checks with MiDShip's own stored values and thresholds.

An honest reading of the agreement figures is in "How to read the results". Read it before you quote them.

## Files

| Path | Content |
|---|---|
| `rules/abs_mvr_part3_midship_v1.json` | The rule data (25 rules). Source of truth for citations, inputs, assumptions, status. |
| `rules/sources_manifest.tsv` | URL, retrieval date, bytes, SHA-256 and stated terms of each source. |
| `rules/agreement/summary.json` | Agreement figures (population, BOM sample, strict option, evidence). |
| `rules/agreement/disagreement_examples.csv` | Up to 5 examples per rule and cause. |
| `src/vessel_reconstruction/rules/` | `engine.py` (load, validate, run), `formulas.py` (checks), `units.py`, `midship.py` (adapters), `agreement.py` (comparison). |
| `scripts/rules_agreement.py` | Reruns the agreement measurement. |
| `tests/test_rules.py` | 30 tests, most worked by hand from the rule text. |

The ABS PDF and the MiDShip data are not committed. They are in `work/sources/` (git-ignored).

## Schema (version 1)

The file has `schema_version`, `rule_set`, `sources` and `rules`. `engine.validate` rejects a file that
breaks these rules.

A rule has:

| Field | Meaning |
|---|---|
| `id` | Stable id, for example `ABS-3-2-4-FLOORT`. |
| `midship_column` | The MiDShip constraint column that the rule maps to. |
| `title` | Short name. |
| `citations[]` | `source` (key in `sources`), `ref` (paragraph) and `page` (printed page). |
| `applicability` | `ship_types` (`tanker`, `container_ship`, `bulk_carrier`), `region`, `member`. |
| `inputs[]` | `name`, `unit`, `role` (`geometry` or `provided`), `description`. One input is `provided`: the member value that is compared with the requirement. |
| `assumptions[]` | `name`, `value`, `unit`, `basis`. Option choices and design-basis constants, each with its reason. |
| `criterion` | `kind` (`min` or `max`), `required_unit`, `provided_input`, `formula` (short text, not a copy of the rule). |
| `check` | Key of the executable function in `formulas.CHECKS`. |
| `status` | `encoded`, `partial` or `not_encoded`. |
| `status_reason` | Required unless `encoded`. Names what is missing or replaced by a proxy. |

Status meaning:

* `encoded`: the formula, its constants and its inputs follow the cited text. Option choices are listed as assumptions.
* `partial`: the check runs, but one rule quantity is replaced by a proxy (for example a span or a breadth), or part of the paragraph is not encoded. The reason says which.
* `not_encoded`: no check. None in v1.

Units are checked. Inputs can be `float` (read in the declared unit) or `Quantity(value, unit)`. A
`Quantity` is converted to the declared unit. A conversion between unlike dimensions raises `UnitError`.

Citations use the ABS MVR Part 3, **July 2023** edition. Page numbers are the printed page numbers of
that PDF. Quotations are not stored. Each `formula` field is a short statement of the equation only.

## Coverage

25 of 25 constraints have an executable check: 9 `encoded`, 16 `partial`, 0 `not_encoded`.

| Rule | MiDShip column | Citation (ABS MVR Part 3, Jul 2023) | Status | Rule-side agreement (12 753 designs) | BOM sample (independent) |
|---|---|---|---|---|---|
| ABS-3-2-4-DBH | Double_Bottom_Height | 3-2-4/3.1.1(c) p93, 1.1.i p92 | encoded | 100.0% | 36/36 |
| ABS-3-2-4-FLOORT | Bottom_Floor_Thickness | 3-2-4/5.1 p94 | encoded | 100.0% | 36/36 |
| ABS-3-2-4-GIRDT | Bottom_Girder_Thickness | 3-2-4/5.1 p94, 3.1.1(a) p93 | partial | 100.0% | 36/36 |
| ABS-3-2-4-FLOORS | Bottom_Floor_Spacing | 3-2-4/5.1 p94 | encoded | 100.0% | 36/36 |
| ABS-3-2-4-IBT | Inner_Bottom_Deck_Thickness | 3-2-3/5.1 p84, 3-2-4/9.5 p98, 3-2-10/3.1 p181, 3-2-3/5.17 p85 | partial | 100.0% | 36/36 |
| ABS-3-2-4-HOPT | Hopper_Plate_Thickness | 3-2-4/9.5 p98, 3-2-10/3.1 p181 | partial | 100.0% | 24/24 |
| ABS-3-2-4-BSTIFF | Bottom_Stiffener_SM | 3-2-4/7.3 p95, 3-2-10/3.3 p182 | partial | 100.0% | 36/36 |
| ABS-3-2-4-BTRANS | Bottom_Transverse_Stiffener_SM | 3-2-4/7.3 p95, 3-2-10/3.3 p182 | partial | 100.0% | 36/36 |
| ABS-3-2-4-HSTIFF | Hopper_Stiffener_SM | 3-2-4/7.3 p95, 3-2-10/3.3 p182 | partial | 100.0% | 21/24 |
| ABS-3-2-5-SFRAME | Side_Frame_SM | 3-2-5/3.1.1 p116 | partial | 100.0% | 36/36 |
| ABS-3-2-6-WEBSM | Webframe_SM | 3-2-6/3.1.2 p129 | partial | 100.0% | 36/36 |
| ABS-3-2-6-WEBD | Webframe_Depth | 3-2-6/3.5.2 p130 | encoded | 100.0% | 36/36 |
| ABS-3-2-6-WEBT | Webframe_Thickness | 3-2-6/3.5.2 p130 | encoded | 100.0% | 36/36 |
| ABS-3-2-6-STRSM | Side_Stringer_SM | 3-2-6/5.1 p132, 3-2-10/3.3 p182 | partial | 100.0% | 36/36 |
| ABS-3-2-6-STRD | Side_Stringer_Depth | 3-2-6/5.3 p132 | encoded | 100.0% | 36/36 |
| ABS-3-2-9-BHDT | Bulkhead_Thickness | 3-2-9/5.1 p162, 3-2-10/3.1 p181 | encoded | 94.9% | 36/36 |
| ABS-3-2-9-BHDH | Trans_Bulkhead_Horizontal_Stiffener_SM | 3-2-9/5.3 p163, 3-2-10/3.3 p182 | partial | 92.5% | 36/36 |
| ABS-3-2-9-BHDV | Trans_Bulkhead_Vertical_Stiffener_SM | 3-2-9/5.3 p163, 3-2-10/3.3 p182 | partial | 96.1% | 36/36 |
| ABS-3-2-7-DTSM | Deck_Trans_Stiff_SM | 3-2-7/3.1 p136 | partial | 90.2% | 24/24 |
| ABS-3-2-3-DECKT | Deck_Thickness | 3-2-3/5.1 p84, 3-2-4/9.5 p98, 3-2-3/5.17 p85 | partial | 99.9% | 36/36 |
| ABS-3-2-8-DBSM | Deck_Beam_SM | 3-2-8/5.3 p151, 5.13 p153 | partial | 98.4% | 24/24 |
| ABS-3-2-8-DBD | Deck_Beam_Depth | 3-2-8/5.13 p153, 5.7 p151 | encoded | 98.3% | 24/24 |
| ABS-3-2-8-DBT | Deck_Beam_Thickness | 3-2-8/5.7 p152 | partial | 100.0% | 24/24 |
| ABS-3-2-2-SSHELL | Side_Shell_Thickness | 3-2-2/3.9.3 p69, 5.1 p74 | encoded | 100.0% | 36/36 |
| ABS-3-2-2-BSHELL | Bottom_Shell_Thickness | 3-2-2/3.15.1 p71, 3.15.2 p73 | partial | 100.0% | 36/36 |

The agreement columns are pass/fail agreement. Container designs have no deck girders, deck beams or
deck brackets, so the deck-girder rules apply to tankers and bulk carriers only (8 834 designs). Hopper
rules apply to container ships and bulk carriers only (8 371 designs).

## Data and method

MiDShip sample (`work/sources/midship/`): three subsets with parameter, property, constraint-value and
constraint-threshold tables. The tables hold 12 804 candidate rows; 12 753 are retained (complete
property and constraint rows): Random 6 020, Repaired 6 237, SGLD 496. A constraint passes when
`value >= threshold`. MiDShip stores the one maximum-spacing constraint with both numbers negated.

Per design, the evaluator measures spacings and member sizes from the structural-element table, then
computes 25 `(value, threshold)` pairs. Only 36 designs have that table in the sample.

Two comparisons are made:

1. **Rule side, all 12 753 designs.** The rule inputs (spacings, spans) are rebuilt from the 120-column
   parameter row. The member value is read from MiDShip's value table. The test is whether the
   executable rule gives the same required value, and the same pass/fail, as MiDShip's threshold.
   The layout laws that rebuild the spacings were inferred from the 36 bills of materials and reproduce
   all 17 geometry inputs on all 36 designs. They are not rule text.
2. **Independent, 36 designs with a bill of materials.** Required values and member values are both
   computed here from the bill of materials. This also tests the member-side geometry.

## Agreement results

### Rule side, 12 753 designs (294 385 active comparisons)

* Pass/fail agreement: **98.89%** (291 114 of 294 385).
* Required value equal to the MiDShip threshold (relative tolerance 1e-4): **91.97%**.
* Rules with 100% agreement on required values and pass/fail: 16 of 25.
* All 3 271 disagreements have the same direction: the MiDShip threshold is lower than the rule
  requirement, so this check fails a member that MiDShip passes (`mine_fail_ms_pass`).
  The per-rule table of confusion matrices is in `rules/agreement/summary.json`.

Rules below 100%:

| Rule | Threshold equal | Pass/fail agree | Confusion (both pass / both fail / mine pass, MiDShip fail / mine fail, MiDShip pass) |
|---|---|---|---|
| Bulkhead_Thickness | 73.8% | 94.9% | 7 719 / 4 381 / 0 / 653 |
| Trans_Bulkhead_Horizontal_Stiffener_SM | 63.9% | 92.5% | 9 246 / 2 554 / 0 / 953 |
| Trans_Bulkhead_Vertical_Stiffener_SM | 63.9% | 96.1% | 10 586 / 1 668 / 0 / 499 |
| Deck_Trans_Stiff_SM | 58.6% | 90.2% | 6 760 / 1 208 / 0 / 866 |
| Deck_Beam_SM | 58.6% | 98.4% | 8 510 / 185 / 0 / 139 |
| Deck_Beam_Depth | 58.6% | 98.3% | 8 488 / 192 / 0 / 154 |
| Deck_Thickness | 99.1% | 99.9% | 7 689 / 5 057 / 0 / 7 |

### Independent run, 36 bills of materials (828 comparisons)

* Required value equal: 769 of 828 (92.9%). Pass/fail agreement: 825 of 828 (99.6%).
* With the evaluator's spacing method reproduced (`legacy_unique`): **828 of 828 on both**. The
  required values and member values then match MiDShip for all 25 rules on all 36 designs.
  This shows that the encoded formulas and the extraction reproduce the evaluator, and that the
  remaining differences come from its spacing method.

### Disagreement causes

All 23 639 rows with a mismatch have a cause. No mismatch is unexplained.

1. **Evaluator float-uniqueness artifact (all rule-side disagreements).** The evaluator measures
   some spacings as the gap between the two lowest values of `np.unique(position)`. The CAD export
   writes one position with float noise (for example 0.0 and -1.8e-15 for two deck girders), so
   `np.unique` keeps both and the "spacing" is about 1e-15 m. The threshold then falls to about 0.
   This code merges positions closer than 1 micrometre.
   * Evidence 1 (BOM): with exact-float uniqueness, all differences in the 36-design sample vanish.
   * Evidence 2 (hatch bit): for tankers and bulk carriers, the deck-girder threshold implies a
     spacing below 1 micrometre in 3 659 designs, all with `Hatch Openings Bit = 1`. In the 4 367
     designs with bit 0 the implied spacing equals the rebuilt spacing in every case. (808 designs with bit 1 also match.)
   * Affected rules: bulkhead plate and stiffeners (26% to 36% of designs; 10 of 36 in the BOM
     sample), deck-girder rules (hatch designs), deck plate (115 designs), hopper stiffener member value.
   * Effect: MiDShip thresholds are too low in these designs, so MiDShip passes members that
     the rule would fail. The dataset counts fewer violations than the rules give.
2. **Evaluator member-value artifact (BOM sample only, 3 comparisons).** The hopper stiffener spacing
   of container ships uses the same exact-float minimum gap. The member section modulus is then
   too low in MiDShip. The required value is equal.
3. **Float tolerance.** None. The 1e-4 relative tolerance did not hide any real difference.

## Where the rule text differs from the MiDShip evaluator

The default profile reproduces the evaluator's scope. The `strict` option applies requirements that the
July 2023 text gives and that the evaluator leaves out. Run with `strict=True` on the 12 753 designs:

| Rule | Text requirement left out by MiDShip | Designs where requirement changes | Pass/fail agreement with MiDShip |
|---|---|---|---|
| Bottom_Girder_Thickness | Center girder: 0.056 L + 5.5 mm (3-2-4/3.1.1(a)). MiDShip uses the floor equation. | 12 753 | 73.5% (3 375 designs: this rule fails, MiDShip passes) |
| Bottom_Shell_Thickness | Spacing `s` is the bottom longitudinal spacing (3-2-2/3.15.1). MiDShip reuses the side shell spacing. | 12 750 | 77.6% (2 561 designs: this rule passes, MiDShip fails; 298 the other way) |
| Double_Bottom_Height | 1.1.i (B/20, 0.76 m, 2 m) for tankers. MiDShip applies it to non-tankers. | 837 | 100% |
| Bulkhead_Thickness | 3-2-10/3.1 minimums (6.5 mm, s/150 + 2.5) | 241 | 94.9% (same as default) |

These are findings about the evaluator, not tuning of the checks. The default profile is what the
agreement numbers above use. The strict option is available so that a user can choose the stricter reading.

Other points where the evaluator departs from the text or leaves the text open (recorded in
`status_reason` of the rules):

* MiDShip cites 3-2-4/9.2 for inner bottom plating. That paragraph is not in the July 2023 text.
* The 8.5 mm bottom shell minimum has no match in 3-2-2/3.15 of the July 2023 text.
* The deep-tank stiffener equation 3-2-10/3.3 allows `c` up to 1.00. MiDShip reuses `c` = 0.6 of 3-2-9/5.3.
* The bulkhead stiffener requirement uses a stiffener spacing as the span.
* Wheel loading uses an assumed `K` = 0.2. The text gives `K` as a polynomial of the wheel imprint.
* The floor 14 mm cap needs a buckling proof and is not applied (conservative).

## How to read the results

* **The high agreement is partly by construction.** The checks use the evaluator's design basis
  (L = 250 m, mild steel, the most conservative constants, a 13.8 t excavator for wheel loading). This is
  recorded as assumptions with a basis. Matching the evaluator therefore tests the encoding and the
  extraction. It does not test whether the design basis is right for a real ship.
* **The independent value** is in three results: each formula is traced to a paragraph and page of
  the public text; the text/evaluator differences are measured; and the evaluator artifact is found,
  explained and shown by evidence.
* **Edition.** MiDShip states the July 2024 edition. The public PDF obtained is July 2023
  (the July 2024 PDF was not found at a public URL; see `rules/sources_manifest.tsv`). Paragraph numbers and
  small details can differ between editions. Equations that agree with the evaluator give no sign of a
  change that matters here, but this is not a proof for the 2024 text.
* **Not a class review.** The 25 constraints are a research subset. They are not a complete ABS approval.
  MiDShip's disclaimer says the same. Nothing here is a statement of ABS rules.
* **No tuning.** No formula was changed to match a result. Each assumption has a basis in the text or is
  marked as a MiDShip design basis.
* **Pass rates.** Many rules pass in 60 to 90% of the designs, so a trivial "always pass" rule scores
  that much. Compare with the `ms_pass_rate` in `summary.json`.

## Gaps

* ABS July 2024 text is not available. Re-check the 25 paragraph references if it is obtained.
* 16 rules are `partial`. The proxies are named in each `status_reason`.
* Strength-deck equations (3-2-3/5 Table 2), hull girder section modulus (3-2-1), and the forward and
  aft regions are not encoded. The MiDShip subset does not use them.
* The member-side geometry (section modulus of stiffener with plate) follows the dataset convention (full
  spacing as plate breadth, flange thickness equal to web thickness). It is not the ABS effective breadth.
* The parameter-to-spacing layout laws are inferred from 36 bills of materials. They are exact on that
  sample. They are unverified on the other designs, except through the agreement run: a wrong law would
  appear as an unexplained mismatch, and there are none.
* The IACS Common Structural Rules are not encoded. The strategy table names them for W4. They are not
  needed for the MiDShip subset (its constraints use ABS 3-2 equations). Plate and stiffener rules in
  CSR Part 1 Chapter 6 and 3 are candidates for the next version.

## Plan to extend to 46 CFR and SOLAS

1. **Reuse the schema.** Add `source` entries for 46 CFR (eCFR, US public domain) and the SOLAS
   consolidated text (IMO terms must be checked first; do not store text). Keep `citations` to
   paragraph and page.
2. **Add a rule kind for prose requirements.** The 25 rules here are equations. Many 46 CFR and SOLAS
   requirements are conditions (a count, a distance, a presence). Add `criterion.kind` values
   `present`, `count_min`, `distance_max`, with the same `inputs`, `applicability` and `status`.
3. **Add a source graph.** Link each rule to the evidence a design needs (a reconstructed member, a
   table cell, a drawing region). The `inputs` names already say what the rule reads.
4. **Pick a first slice that vessel reconstruction can feed:** 46 CFR Subchapter K or T items on
   subdivision, freeboard and openings for small passenger vessels, and SOLAS II-1 watertight
   bulkhead counts. The inputs are geometry that the hull modules produce.
5. **Measure agreement where ground truth exists.** MiDShip has none for these. Use cited worked
   examples in public guidance and signed expert reviews. Report `not_encoded` and `partial` openly.
6. **Gate.** For each new family: citations checked by a second reader, unit tests worked by hand,
   no tuning to results, and a recorded edition.

## Sources and terms

See `rules/sources_manifest.tsv`.

* ABS Rules for Building and Classing Marine Vessels, Part 3, July 2023, from ABS's public site.
  ABS terms allow download, copy and use in electronic form, keep ABS notices, require attribution
  in scholarly use, and forbid upload to third-party sites without written permission. The PDF is in
  `work/sources/rules/` and is not committed. The repository holds only equation statements, paragraph
  numbers and pages. Attribution: American Bureau of Shipping.
* MiDShip dataset (GPL-3.0) and its evaluator `Parametric_Structure_Eval.py` (GPL-3.0). The evaluator
  was read to find the rule paragraphs and design-basis choices. No code from it is copied.

## Rerun

```
PYTHONPATH=src python scripts/rules_agreement.py \
  --midship-root work/sources/midship --out rules/agreement --full-out work/rules_agreement
PYTHONPATH=src python -m pytest tests/test_rules.py
```
