# Performance baseline continuation — draft results

## Outcome and exact stop point

**Lane incomplete. No ship resistance, propulsion or fuel prediction is reported.**
No published ship comparison was run, and no JBC score was produced.
`engineering_approved` remains false in every new output.

The continuation stops after implementing independently testable primitives.
The original protocol had already exposed the proposed blind JBC CT and
propulsion measurements. The uncommitted tests also used JBC open-water truth
as a development target. Freezing code now cannot restore a blind split.
A fresh public ship/split or an independent evaluator is required from the PM.
No restricted holdout or sealed data was opened as a substitute.

## Review of inherited work

- Kept protocol commit `90ccf3e` in history. Commit `4893059` adds the corrective
  review and supersedes its blind-check and power-accounting claims.
- Replaced the uncommitted test draft rather than implement against its
  unsupported expected values. The original ITTC values do not satisfy its
  formula. At Re=1e7 the formula yields 0.003, not 0.002920.
- The claimed 234 kN and 690 kW worked example is inconsistent with PE=R*U
  at its stated speed. It is not evidence for a resistance implementation.
- MP687 is an AU five-blade propeller, not a B4-55 numerical reference.
- Density inputs use kg/m³. Shaft efficiency converts delivered to brake
  power, not effective to delivered power.
- Published CT and effective power must use the experiment's own reference
  surface area. An estimated hull area must not replace the measured basis
  when recovering measured force or power.

## Implemented scope

`src/vessel_reconstruction/performance.py` and `tests/test_performance.py`
(commit `9bdf519`):

1. ITTC-1957 friction line, with a low-Reynolds-number warning and rejection
   of the singular/nonphysical lower branch.
2. Delivered and brake power from **caller-supplied** thrust deduction, wake,
   open-water efficiency, relative rotative efficiency and shaft efficiency.
   No Holtrop regression or propeller matching is implied.
3. Main-engine fuel per day from explicit brake power and SFOC; auxiliaries
   and engine-load corrections are excluded.
4. Mesh particulars through existing `mesh_hydrostatics`: explicit Lpp,
   waterline length, breadth, draft, volume, Cb, Cp, Cm, Cwp, LCB and wetted
   area. Largest sampled section substitutes for midship area. Transom area
   is **not computed**. Mesh coordinates are metres; waterline input is z.
5. A scalar resistance comparison with separate measured/predicted area
   bases, explicit model/ship scale and required source text. This is not
   the published-file comparison runner.

The box check uses a synthetic 100 × 20 m hull at 6 m draft: volume
12,000 m³ and wetted area 3,440 m². The synthetic comparison check gives
0% CT error but +10% effective-power error when the predicted/reference areas
differ by 10%; this checks accounting, not ship accuracy.

## Public method sources for continuation

- Holtrop & Mennen (1982), *An approximate power prediction method*,
  International Shipbuilding Progress 29, pp. 166–170, and Holtrop's 1984
  reprint: [public university-hosted scan](https://moodle2.units.it/pluginfile.php/493107/mod_resource/content/0/Holtrop%20calcolo%20statistico%20resistenza.pdf).
  Downloaded to ignored `work/sources/holtrop-original/holtrop.pdf`, with
  URL, size, SHA-256 and terms in its `manifest.tsv`.
  PDF pp. 1–5 are 1982; pp. 6–8 are 1984. The original author example is
  PDF pp. 4–5. Visually check all exponents before transcription.
- Oosterveld & van Oossanen (1975), *Further computer-analyzed data of the
  Wageningen B-screw series*, [original DOI](https://doi.org/10.3233/ISP-1975-2225102).
  Original coefficient tables were not obtained in this continuation.
- MacKenzie & Forrester, *Sailboat propeller drag*,
  [public accepted manuscript](https://strathprints.strath.ac.uk/5670/6/strathprints005670.pdf),
  PDF pp. 26–27: secondary reproduction of 39 KT and 47 KQ terms. A research
  agent located this source; its tables have not been independently transcribed
  or checked here. Do not treat it as a tested implementation.
- Helma (2019), [Wageningen polynomial analysis](https://www.marinepropulsors.com/proceedings/2019/MA2-4.pdf):
  useful discussion of regression limits, not a ship-performance blind check.

The prior run's public data inventory remains at the main checkout's
`work/sources/simman_modeltests/manifest.tsv`. Its existence and contents were
reviewed; no ship result file was scored. No data file is committed.

## Checks

- Red phase: importing the missing performance module failed as expected.
- Initial green phase: 32 focused tests passed.
- Comparison red phase: eight tests failed because `compare_resistance`
  was absent; after implementation all **40 focused tests passed**.
- `git diff --check`: passed.
- A separate all-marker Python run was stopped before completion to avoid
  duplicate CPU-heavy suites alongside the quick tier and other active lanes.
  It had no reported failure at the stop, but is **not a passing full-suite
  result**. The all-marker/CAD suite remains not completed.
- Quick tier: pending final results below.
- Final focused suite: **41 passed**, including a red/green translated-keel
  regression. Commit `93cf439` fixes physical draft to be waterline z minus
  keel z; existing hydrostatics stores waterline z in its draft field.
- First quick-tier attempt failed in the existing desktop build:
  `frontendDist ../ui-release` did not exist. Ran the documented
  `cargo check -p marinaframe-app` staging step and restarted the quick tier;
  no application source was changed.

## Brief completion and resume point

| Brief step | State |
|---|---|
| 1: protocol before comparisons | Kept and corrected before any comparison; blind requirement blocked |
| 2: public data and provenance | Prior public inventory inspected; method scan and local manifest added; complete paired-data audit not done |
| 3: particulars/resistance/propulsion/fuel | Partial primitives only; Holtrop-Mennen, B-series, transom area and matching not implemented |
| 4: published formula and runner tests | 41 synthetic/equation tests; original worked-example and published-file runner tests not done |
| 5: error table and blind result | Not done; no performance accuracy claim |

Resume with the PM assigning an independent public blind split. Implement one
named Holtrop version from the original paper, check all component terms and
its worked example, then transcribe/cross-check B-series tables and implement
propeller matching. Keep scale and Reynolds corrections explicit. Add public
file loaders with source/cell provenance and geometry checks before KCS
comparisons. Freeze and push the code before the independent evaluator scores
once. Do not use JBC as a blind result or tune constants against it.
