# Real-sheet holdout registry

Updated 2026-11-12. This is a status index, not a new scoring run. Results below
are the original blind-run decisions, not later development scores. One blind
experiment can include several fixed arms and repeats. `engineering_approved`
stays false. No truth file or image was opened to compile this index.

## Status rules

- `blind`: no blind reader run is recorded. This does not establish readiness.
- `spent`: the blind experiment has run; it cannot be a holdout again.
- `development`: the sheet is explicitly designated for development or has been
  used for post-run diagnosis, tuning or development comparisons. It cannot
  become blind again. This status includes a spent holdout used for development.

All ten sheets with a `holdout_value.py` module are now **development** cases.
There is no remaining blind sheet among these ten. This index does not grant
permission to open their truth or their old holdout folders.

## Sheets with holdout harnesses

| Sheet | Kind | Module | Protocol | Blind run | Original result | Status | Status evidence |
|---|---|---|---|---|---|---|---|
| CAMA BEACH SKIFF No. 22, HAER WA-199 s1 | Flat-bottom hard-chine rowing skiff | `benchmarks/cama_beach_skiff_22/holdout_value.py` | [Chine protocol](../BODY_PLAN_CHINE.md#holdout-protocol-cama-beach-skiff-no-22-written-before-any-run-lane-e-2026-11-11) | 2026-11-11 | FAIL: waterline RMS 0.0618 m versus frozen 0.0616 m; 22/36 cells | development | [Published limits and erratum](../results/2026-11-11-published-holdouts.md#limits): both sheets now development; later calibration correction does not change FAIL. |
| Double Ended Davis Boat, HAER WA-227 s1 | Round-bilge, double-ended boat | `benchmarks/davis_boat/holdout_value.py` | [Davis protocol](davis-boat.md) | 2026-11-11 | PASS by rule 3.5.9: 37/44 cells, RMS 0.022 m; 4 extra cells reported | development | [Published limits](../results/2026-11-11-published-holdouts.md#limits): both sheets now development and cannot be holdouts again. |
| CALEB JONES, HAER MD-171 s1 | Hard-chine skipjack | `benchmarks/caleb_jones/holdout_value.py` | [Chine protocol](../BODY_PLAN_CHINE.md#holdout-protocol-caleb-jones-written-before-any-run-folder-not-opened) | 2026-11-10 | FAIL for v2 and polyline: station naming failure | development | [Original result](../BODY_PLAN_CHINE.md#holdout-result-caleb-jones-one-run-no-tuning---fail): explicitly now a development case. |
| COLLEEN, lines s1 (md1887) | Chesapeake deadrise workboat | `benchmarks/colleen/holdout_value.py` | [Joint chine protocol](../BODY_PLAN_CHINE.md#holdout-protocol-white-gull-and-colleen-written-before-any-run-folders-not-opened) | 2026-11-10 | PASS for polyline, FAIL for v2 | development | [V-bottom v1.1](../BODY_PLAN_CHINE.md#v-bottom-reader-v11-branch-featurevbottom-v11-founder-approved-2026-11-10): development cases only; holdouts spent. |
| E. C. COLLIER, HAER MD-77 s2 | Hard-chine skipjack | `benchmarks/ec_collier/holdout_value.py` | [Chine protocol amendment](../BODY_PLAN_CHINE.md#holdout-protocol-amendment-pm-2026-11-10-before-any-reader-run-on-a-candidate) | 2026-11-10 | FAIL: v2 equals frozen reader; no chine line accepted | development | [V-bottom reader](../BODY_PLAN_CHINE.md#v-bottom-polyline-reader-branch-featurevbottom-reader-2026-11-10): explicitly a development case after its spent holdout. |
| WHITE GULL, lines s1 (md1939) | Chesapeake deadrise workboat | `benchmarks/white_gull/holdout_value.py` | [Joint chine protocol](../BODY_PLAN_CHINE.md#holdout-protocol-white-gull-and-colleen-written-before-any-run-folders-not-opened) | 2026-11-10 | FAIL for v2 and polyline | development | [V-bottom v1.1](../BODY_PLAN_CHINE.md#v-bottom-reader-v11-branch-featurevbottom-v11-founder-approved-2026-11-10): development cases only; holdouts spent. |
| PARDON ME, HAER NY-547 s4, round 14 | Hard-chine runabout launch | `benchmarks/pardon_me/holdout_value.py` | [Round 14 protocol](round14-pardon-me.md) | 2026-11-09 | All arms FAIL: 34/57 cells (59.6%), below fixed 60% coverage | development | [Chine metrics](../BODY_PLAN_CHINE.md#metrics-and-acceptance): explicitly DEVELOPMENT; round-14 holdout spent. |
| BUMBLE BEE 47, HAER OR-165 s2, round 13 | Round-bilge gillnet boat | `benchmarks/bumble_bee/holdout_value.py` | [Round 13 protocol](round13-bumble-bee.md) | 2026-11-09 | All arms PASS fixed rule, despite reversed calibrated halves and systematic station errors; not evidence of correct naming | development | [Auto-calibration development sheets, section 4](../AUTO_CALIBRATION.md): corrected development calibration and development comparisons. Original round-13 result stays unchanged. |
| BUE GIRL, HAER OR-166 s2, round 12 | Round-bilge gillnet boat | `benchmarks/bue_girl/holdout_value.py` | [Plan section 3.5.11](../plans/2026-11-09-whole-vessel-scope.md#3511-round-12-bue-girl-holdout-fixed-before-running) | 2026-11-09 | Code and Crouton PASS (median RMS 0.0014 m); Sonnet access failure. Separate round 12b Sonnet PASS on same date, not a fresh blind sheet | development | [Auto-calibration development sheets, section 4](../AUTO_CALIBRATION.md): BUE GIRL is in the development set. [Original results and 12b](../WHOLE_VESSEL_GUNNERUS.md#59-round-12-bue-girl-holdout-protocol-3511). |
| C.A. Thayer, HAER CA-61 s4, round 9 | Round-bilge schooner | `benchmarks/thayer/holdout_value.py` | [Plan section 3.5.9](../plans/2026-11-09-whole-vessel-scope.md#359-round-9-holdout-sheet-for-the-round-8-reader-fixed-before-running) | 2026-11-09 | Code FAIL (RMS 0.676 m), models PASS (0.0864 m) with 3 identity errors; fixed interpretation: does not generalise | development | [Round 10](../WHOLE_VESSEL_GUNNERUS.md#56-round-10-station-naming-fixed-on-two-development-sheets): explicitly now development, holdout result spent. |

## Other real sheets and unprepared candidates

| Sheet | Kind | Protocol / source | Blind run | Result | Status | Evidence / scope |
|---|---|---|---|---|---|---|
| Balclutha, HAER CA-54 s7 | Round-bilge sailing ship | [Rounds 4–8](../WHOLE_VESSEL_GUNNERUS.md#5-round-4-balclutha-sheet-7-model-value-on-a-scanned-body-plan-protocol-353-option-b) | None: development from the start | No blind result | development | Sections 5.3 and 5.6 explicitly call this one sheet with no holdout and a development sheet. No `holdout_value.py`. |

The following are **not registered test sheets**: no eligible blind experiment is
recorded. Do not infer a spent or development result from a catalogue mention.

- ALMA, NPS "Lines drawing and offsets" (B. Doll, May 1987): round 11 stopped at the eligibility check, 2026-11-09;
  no protocol, truth or reader run. See [section 5.8](../WHOLE_VESSEL_GUNNERUS.md#58-round-11-alma-holdout-not-run-sheet-fails-the-eligibility-check).
- Unused entries in the [next-round catalogue list, section 5.7](../WHOLE_VESSEL_GUNNERUS.md#57-holdout-candidates-for-the-next-round)
  are ENDEAVOR (OR-168, sheet unconfirmed), Mukilteo Boat (WA-224 s1),
  St. Lawrence River skiffs (NY-559 s1 and NY-560 s1), and Au Sable River Boat
  (MI-409 s1). BUE GIRL, BUMBLE BEE and PARDON ME in that historical list were
  later run and appear above; the old candidate label does not restore blindness.
- The [chine candidate list](../BODY_PLAN_CHINE.md#holdout-candidates-state-none-scored)
  names St. Lawrence River Skiff (catalogue resource ny2432; survey label there
  says NY-2432, unlike NY-560 in section 5.7), Mukilteo Boat (WA-224), USS Saginaw
  Gig (VA-146), and KATHRYN (MD-117). These are discovery entries, not evidence of
  a prepared or run holdout. The conflicting survey label is not resolved here.
- Synthetic and sealed benchmark suites are outside this real-sheet registry.
  No sealed IDs or holdout truth are needed to maintain it.

## Consistency check

`tests/test_holdout_registry.py` reads Python syntax trees and this table only.
It checks that every `benchmarks/*/holdout_value.py` declares one literal valid
`STATUS` and appears exactly once with the same status. It does not import a
harness, load a sheet/truth, call a model, or run a scorer. When a status changes,
update the module reason and the cited evidence in this table together.
