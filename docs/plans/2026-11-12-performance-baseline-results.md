# Performance baseline continuation — draft results

## Data exposure inventory — PM continuation, before further data reads

PM decision: JBC is development; a separate evaluator will select and score
an unexposed ship. This lane will not open any additional ship's test data.
This inventory distinguishes direct reads in this continuation from evidence
left by the previous run. Previous-run exposure is conservatively inferred
from its manifest, protocol and test draft; its complete interaction history
is not available here. A downloaded or quoted result is treated as exposed
whether or not a comparison was run.

All file paths below are relative to the existing public
`work/sources/simman_modeltests/` collection, whose manifest was read in full.

| Ship | Files opened/read/quoted or conservatively exposed | Values visible before this continuation |
|---|---|---|
| KVLCC1 | `simman2008_pdf/KVLCC_CMT_NMRI_test_prog.pdf` downloaded by prior run; manifest read here | Test conditions: Fr 0.142, model Lpp 5.5172 m, appended hull; no measured resistance series quoted. Protocol says no public measured table found. |
| KVLCC2 | Same KVLCC conditions PDF; inherited synthetic/plausibility test draft | Same conditions; draft test quoted L 320 m, B 58 m, T 20.8 m, volume 312622 m³, speed 14.5 kn, and inconsistent LCB 0.9652 labelled 3.48% aft. These are particulars, not measured force. No measured resistance series quoted. |
| KCS | `jbc/KCS_vary_Fr_2-1.xls` downloaded and read by prior run (protocol evidence); `simman2008_pdf/KCS_CMT_NMRI_test_prog.pdf`; manifest and protocol read here | CT×1000, sinkage and trim series exist at Fr 0.108, 0.152, 0.195, 0.227, 0.260, 0.282. CT/sinkage/trim numerical cells not quoted in inherited code/protocol, but conservatively the full six-point file is exposed. Speeds 0.915, 1.281, 1.647, 1.922, 2.196, 2.379 m/s; Lpp 7.2786 m; T 0.3418 m; rho 999.5 kg/m³, nu 1.27e-6 m²/s. Conditions PDF noted NMRI speeds 0.7–1.2 m/s. |
| DTMB 5415 | `simman2008_pdf/free_model_test_program.pdf` downloaded by prior run; its manifest entry names 5415 | No measured resistance/self-propulsion value read or quoted. Only test-program/geometry availability was visible. **Do not open its result data.** |
| JBC | `jbc/JBC_VOV_1-1a_template.xls`, `jbc/JBC_VOV_1-5a_template.xls`, `jbc/Open_Water_Tests_for_JBC_NMRI.txt`, `jbc/MP687_particulars.txt`; prior run downloaded and quoted; manifest/protocol/test draft read here | Resistance CT×1000=4.289, Fr=0.142, Re=7.46e6, S0/Lpp²=0.2494, sinkage −0.086%Lpp, trim −0.18%Lpp. Self-propulsion CT×1000=4.811, KT=0.217, KQ=0.0279, n=7.8 rps, RT(SP)−T=18.2 N. Open-water draft fixtures (J,KT,KQ): (0.3,0.2598,0.03210), (0.5,0.1798,0.02479), (0.7,0.0867,0.01509); the entire downloaded table is considered exposed. Propeller D=0.203 m, P/D=0.75, EAR=0.50, Z=5, AU sections. Hull Lpp=280 m, T=16.5 m; design 14.5 kn, rho=999.0 kg/m³ quoted. |
| Other ships | None of their measured test files were opened/read/quoted in this lane | Original Holtrop hypothetical worked example is exposed (not a candidate blind ship): LWL205 m, Lpp200 m, B32 m, T10 m, volume37500 m³, speed25 kn, RT1793.26 kN, PE23063 kW, w0.2584, t0.1747, n1.6594 Hz, shaft power32621 kW. Unsupported Lewis/Series60 draft fixture L122 m, B16.226 m, T6.502 m, volume9862 m³, Fn0.25, RT234 kN / PE690 kW was read and rejected as inconsistent. |

Other inherited files: `simman2008_pdf/TOC.pdf` (table of contents),
`simman2008_pdf/free_model_test_program.pdf` (test program, not a result
series). Public hull ZIP names were listed for KVLCC1/2, KCS and 5415;
JBC and KCS geometry ZIP entries were read in the manifest. No geometry ZIP
was opened by this continuation before this inventory. Method papers and
synthetic boxes are not ship-test exposure. No licensed, pilot, holdout or
sealed data was opened.

**Permitted measured-data development set: KCS and JBC only.** Conditions-only
exposure does not authorize opening KVLCC1/2 or DTMB result data. This is the
conservative boundary until the PM selects the independent blind ship.

### Additional reads after inventory (development only)

- Opened all nonempty cells of KCS `KCS_vary_Fr_2-1.xls` Sheet1:
  D5:D10 CT×1000 = 3.796, 3.641, 3.475, 3.467, 3.711, 4.501;
  C5:C10 Fr as listed above. E5:E10 Sf×100 = −0.195, −0.613,
  −1.213, −1.750, −2.465, −2.710; F5:F10 Sa×100 = 0.015, 0.063,
  0.015, −0.138, −0.322, −0.695; G5:G10 mean sinkage×100 =
  −0.090, −0.275, −0.599, −0.944, −1.394, −1.702;
  H5:H10 trim degrees = −0.017, −0.053, −0.097, −0.127, −0.169, −0.159.
- Opened all nonempty cells of the two already-exposed JBC templates;
  numerical result values match the inventory above (resistance C4/C10/C12;
  self-propulsion C4/C10/C12/C14/C16). Reference area is A14/A18 respectively.
- Opened public KCS Case2.1 page, KCS geometry/conditions page, JBC
  geometry/conditions page, KCS geometry memo, and JBC CAD description.
  These expose additional particulars/conditions of **the same two ships**,
  including full/ballast/model variants. No new ship's test data was opened.
- Extracted KCS starboard-half IGES and JBC `jbc.igs` only. Did not open
  other JBC case measurements or any other ship's measured results.
- Local cell transcript: ignored `work/performance-baseline/exposed-tables.txt`;
  downloaded condition HTML and geometry under ignored `work/sources/{kcs,jbc}-geometry/`.

## Outcome and exact stop point (previous checkpoint; superseded by continuation below)

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
- First completed quick tier: exit 0; Python **2375 passed, 4 skipped,
  87 deselected, 5 warnings** (747.97 s), UI **275 passed**, Rust fmt/clippy
  and workspace tests passed, secret pattern scan 0 findings. It preceded
  the signed-coefficient review fix.
- Post-review quick tier: one attempt stopped at the unrelated Rust
  `real_worker_replaces_one_unreadable_extra_sheet_without_a_hull_rebuild`
  test (`sheet_replacement_failed`). Push was blocked. Explicit worker Python
  and `RUST_BACKTRACE=1` recheck: **4 passed**, no registry error. No app code
  changed. The following full quick tier passed with exit 0: Python **2377
  passed, 4 skipped, 87 deselected, 5 warnings** (465.54 s), UI **275 passed**,
  Rust fmt/clippy/workspace tests passed, secret pattern scan 0 findings.
  Log: ignored `work/performance-baseline/quick-recheck.log`.
  `1c62a00` was pushed to `origin/lane/performance-baseline`; no merge.
  This final evidence-only update is gated by another quick tier before push.
- Independent review found that wake and thrust deduction are signed;
  commit `b87c51d` removes the incorrect zero lower bound and adds a red/green
  test. Final focused suite: **42 passed**.
- The suite includes a red/green translated-keel
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
| 4: published formula and runner tests | 42 synthetic/equation tests; original worked-example and published-file runner tests not done |
| 5: error table and blind result | Not done; no performance accuracy claim |

Resume with the PM assigning an independent public blind split. Implement one
named Holtrop version from the original paper, check all component terms and
its worked example, then transcribe/cross-check B-series tables and implement
propeller matching. Keep scale and Reynolds corrections explicit. Add public
file loaders with source/cell provenance and geometry checks before KCS
comparisons. Freeze and push the code before the independent evaluator scores
once. Do not use JBC as a blind result or tune constants against it.
