# Published holdout results: two small boats from public lines drawings (2026-11-11)

MarinaFrame reads the body plan of a scanned lines drawing and gives half-breadths at the drawn
waterlines. We tested that reader once on two drawings it had never seen, and scored it against the
table of offsets printed on each sheet. One boat passed its pre-written rule; the other failed.

## What was tested

| | CAMA BEACH SKIFF No. 22 | 14'-3" Double Ended Davis Boat |
|---|---|---|
| Hull | 14 ft flat-bottom, hard-chine rowing skiff (1934) | 14 ft 3 in double-ended, round-bilge boat |
| Sheet | HAER WA-199, sheet 1 (Library of Congress, hhh.wa0881) | HAER WA-227, sheet 1 (Library of Congress, hhh.wa0928) |
| Truth | printed table of offsets, transcribed twice independently (77 cells agree) | printed table of offsets, transcribed twice independently (184 cells agree) |
| Scored cells | 36 waterline half-breadths, 18 sheer and chine points (stations 1 to 9) | 44 nonblank waterline half-breadths (stations 1 to 7) |
| Reader | code only (no model calls); product rule against the frozen reader | code only (no model calls); product reader `body_plan_sides` |
| Protocol | `docs/BODY_PLAN_CHINE.md`, "Holdout protocol: CAMA BEACH SKIFF No. 22" | `docs/holdouts/davis-boat.md` |

Both drawings are US Government works with no known restrictions. The sheets and truth files are kept
outside git; their SHA-256 values are in the protocols.

## How the test was kept blind

1. **Protocol before the run.** Each protocol fixed the sheet, the truth file, the scored cells, the scorer
   and the pass rule before any reader ran on the sheet. The pass rules were not changed after the run.
2. **Truth-blind calibration.** The scale, axes, measuring rows and station names were set by an agent that
   did not open the truth file and saw the printed table only at an illegible scale. A second independent
   agent measured them again and agreed.
3. **Frozen code.** Every reader, scorer and calibration file was pinned by SHA-256 and checked just before
   the run; none had changed. The one new file, the round-bilge run script, was written and pinned before
   the run and was checked end to end on a different, already-used sheet only.
4. **One run, no tuning.** Each holdout ran exactly once (code commit `c473190`). The truth file was read
   only after every reader had finished.
5. **Disclosed incident (Davis Boat).** One crop made by the second calibration checker caught the bottom
   row of the printed table at a legible scale. The checker reports that it did not use those digits, and
   no calibration value came from the checker. Separately, the agent that transcribed the truth saw the
   table in a whole-sheet overview before the protocol was written; that agent develops no reader.

## Results

**CAMA BEACH SKIFF No. 22 (hard chine): FAIL.** All gates had to hold; one failed.

| Gate (product rule vs frozen reader) | Waterline cells | Point cells |
|---|---|---|
| cells given >= frozen | pass (22 of 36 = 22) | pass (5 of 18 = 5) |
| RMS not worse | **fail** (0.0618 m vs 0.0616 m) | pass (0.0506 m) |
| wrong cells (> 0.15 m) not worse | pass (0) | pass (0) |
| wrong cells <= 10 % | pass | pass |
| no value where the printed cell is blank | pass | pass |
| by eye: every named knuckle on a drawn corner | pass | |

The hard-chine reader did not engage on this sheet: it declined both halves and fell back to the older
crossing reader for all stations but one. Four stations (2, 3, 8, 9) show a constant offset of 0.04 to
0.11 m that looks like stations carrying a neighbour's name. Coverage is 61 % of waterline cells and 28 %
of point cells.

**Davis Boat (round bilge): PASS by rule 3.5.9** (at least 60 % of scored cells and RMS at most 0.15 m).

| Metric | Product reader |
|---|---|
| cells given | 37 of 44 (84 %) |
| RMS / max error | 0.022 m / 0.134 m |
| within 0.05 m / 0.15 m | 97 % / 100 % |
| station naming errors | none |
| values where the printed cell is blank | 4 (reported; not part of the rule) |

On stations 1 to 6, every given cell is within 3 mm of the printed offset. Station 7 gives one of its seven
cells, 0.134 m off. Sheer and rabbet points were reported only: 3 of 14 given.

## Limits

- Two small boats (14 ft). This is not a whole-ship result and says nothing about large hulls, other
  drafting styles or poor scans.
- Reader-only path: body-plan half-breadths at drawn waterlines. No profile, no plan view, no fairing, no
  hull surface and no structure were scored.
- Each result is one run of deterministic code; one sheet per hull type gives no estimate of spread.
- The calibration (scale, axes, station names) was made by an agent with the drawing, not by the product.
- The hard-chine test failed, so this is not evidence that the reader handles hard-chine hulls.
- Both sheets are now development cases and cannot be used as holdouts again.
- `engineering_approved` is false for both results. These are research measurements, not an engineering
  sign-off.
