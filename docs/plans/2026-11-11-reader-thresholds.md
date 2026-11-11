# Reader resolution thresholds (code-review item 8)

Branch `lane/reader-thresholds` from `continue/v0.5` (`4f03667`). Development sheets only.

## Finding before the change (measured 2026-11-11, base `4f03667`)

- The resolution factor of `continue/v0.5` (75th percentile of horizontal ink runs / 5) is 1.8 to 2.6 on
  the five HAER development sheets at native size. The perpendicular width of their body-plan curves,
  measured by the reader at the waterlines, is 4.4 to 5.9 px: they are at the 5 px reference. The
  horizontal-run estimate counts oblique lines, lettering and other views.
- So `continue/v0.5` scales its five distances up about 2x on these sheets. Its native reading differs from
  frozen v1 on all five; on Balclutha, cells within 5 cm fall from 149 to 32.
- At 50 % size both readers fail mainly because `typical_width` accepts only 3.5 to 8 px crossings: a
  2.5 px curve is then classed as a thin grid line.

## Design (fixed before the new reader was run)

- Stroke width = median perpendicular width of all crossings the reader measures on a side (first pass at
  reference thresholds). Resolution factor = stroke / 5 px. `low_resolution` flag when factor < 0.75
  (unchanged rule).
- Threshold scale = stroke / clip(stroke, 4.0 px, 6.5 px). Frozen v1 was checked on 4.4 to 5.9 px strokes
  (five HAER sheets) and 4.7 px (synthetic reference); inside the band the thresholds stay exactly as
  tuned, outside they scale from the nearest band edge.
- Crossings functions take the scale explicitly (default 1.0 = frozen v1 behaviour).
- Revision before the new reader ran: the median crossing width read 2.0 px on the calibration fixture
  (its many 2 px grid lines), so the stroke is the 75th percentile of crossing widths (native 4.7 to 6.6 px,
  reduced 1.9 to 3.0 px) and the band is 4.0 to 7.5 px.

## Gates (written before the runs)

- G1 native equivalence: on the five development sheets at native size and on the synthetic fixtures, the
  new reader's full reading (repr of every `SideReading`) is byte-identical to frozen v1.
- G2 degradation: at 50 % and at 35 %, summed over the five sheets, cells within 5 cm of truth for the new
  reader are at least those of frozen v1 and of `continue/v0.5`. Per-sheet cells, RMS and identity errors
  are reported, including any sheet where the new reader is worse.
- G3 flag: `low_resolution` is set for every reduced sheet whose factor is below 0.75, and for no native
  sheet.
- G4 ingest: development_wigley seeds 17, 23, 41 (clean and degraded): `extract_sections` output at native
  size is byte-identical to `continue/v0.5`. Run with clean and drafting instead: the benchmark's corridor
  proposal, needed to pass the grid-line ambiguity, refuses the degraded style.

## Steps and resume point

1. Measure frozen and base arms (`scripts/measure_reader_resolution.py`, output in `work/reader-thresholds/`,
   git-ignored). Done.
2. Implement the stroke-based scale, list and decide every fixed pixel threshold, tests. Done.
3. Run the new arm; check G1 to G4; write the table in `docs/BODY_PLAN_CHINE.md`; update item 8. Done:
   G1 to G4 pass (table and limits in `docs/BODY_PLAN_CHINE.md`).
4. Quick tier; push the branch.

Resume: check `git log` on the branch; rerun step 3 from `work/reader-thresholds/` if outputs are missing.
