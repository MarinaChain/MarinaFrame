# GA to estimated 3D arrangement (stretch demo, lane W)

Goal: from one GA image of a development case (no lines plan), make a MarinaFrame run that shows
an ESTIMATED 3D arrangement: an estimated hull sized from the GA's principal dimensions, and
compartments placed from the GA with source records (hover-to-source).

Honesty label on every page (presentation.json `credit`, web selection `credit`):
"Estimated 3D arrangement from a single GA drawing. The hull shape is estimated (no lines plan);
compartments are read from the GA. Not a CAD model; not for construction."

## Scope (changed 2026-11-11 about 21:40 SGT by the PM)

One GA reader only: lane U (`lane/ga-commercial`, `ga_commercial.py`) does all GA reading
(dimensions, labels, compartments, extents). Lane W builds only the step after reading. Lane W's
first reading prototype was deleted unused (no code, no readings kept).

Input schema: docs/GA_ARRANGEMENT_INPUT.md (a `marinaframe.ga_reading.v1` file whose spaces carry
an `extent` block, plus particulars and a frame-spacing table).

Data rules: SPLIT.json development_cases only; never sealed/ or holdout images. Images, readings,
fixtures with per-ship values and runs stay under work/ga-arrangement-demo/ (git-ignored). Ships
are named by case ID only. Test data (hand-written fixtures) is never shown in the demo.

Target ships: GA-005 (bulk carrier: complete bow and stern, frame spacings and mm dimension
strings, printed hatch sizes) and GA-120 (tanker: clean profile with frame-spacing notes, full
upper-deck plan). Not GA-121 (bow cut off at the sheet edge), not GA-023 (owner name on the hull).

## Code

- `src/vessel_reconstruction/ga_arrangement.py`: input checks, frames to metres, item boxes with
  read/guessed status per axis and the rules for missing extents, checks, carve order, and the
  estimated hull table (prior-form family `form_fit.section_shape`, rows `prior`).
- `benchmarks/ga_arrangement/model.py`: CadQuery loft of the hull (cut by a read profile outline
  when given), item solids (box and hull, carved smallest first).
- `benchmarks/ga_arrangement/run_folder.py`, `__main__.py`: the run folder (concept-run layout,
  policy `ga_estimate`, presentation.json with the label as credit, GA as drawing page and source)
  and the web selection entry. `--split` refuses a non-development case; a `test_fixture`
  reading needs `--test-fixture` and its run is named "(TEST DATA)".
- `scripts/build_web_demo.py`: licence key `owner-cleared-ga`.
- Tests: tests/test_ga_arrangement.py on a made-up ship (tests/fixtures/ga_arrangement_synthetic.json).

## Gates (written before the first run; not widened after)

- G3 proportions: L/B in [4, 9], B/D in [1.2, 2.6]. A ship that fails is not shown.
- G5 cargo holds do not overlap in x by more than 1 m and lie inside the hull length (findings in
  `ga_estimate.json`; a ship with a finding is not shown until it is explained).
- G6 every part has at least one GA region; engineering_approved false everywhere.
- Ready to show: the web build passes its gates; the 3D view and the GA agree by eye; hover on a
  hold shows its region on the GA.

## Results

- 21:50 SGT: lane U output r4..r8 has null dimensions on every development ship and label boxes
  only (no extents): the step after reading cannot run on it. Reported to the PM; lane U (Fable
  step) is adding dimensions measured from the frame scale and space extents per the schema.
- Test-fixture run (one development case, hand-written, TEST DATA, not for the demo): 24 parts,
  no findings; web build passes all gates; the run opens in the demo UI with the label strip, the
  GA in the drawing pane and the 3D arrangement; hover on a part opens its GA region
  ("Read from the drawing"). Fixes found this way: the GA is now the drawing pane's page
  (domain/input/source.png), the spec lists no estimated stations (the pane fitted an empty box),
  and extents use the app's source words (traced / guessed) so the hover chip reads "Read".
- Quick tier on 538b52d: 1955 passed, 0 failed.
- Lane U rounds (work/ga-internal-23/dev-runs): s1 measured the GA-005 depth under the poop deck
  (reported; fixed in s2). s3b first measured the GA-120 depth to the deck at centre (above its own
  cargo-tank tops by more than the tolerance); lane U then marked that depth `derived_from_space_tops`. PM rule: per
  ship, the newest round that passes the depth check; the round and reader commit are in each
  run's ga_estimate.json.
- Builder fixes found on lane U's data: depth check (G7 below), hull aft end at the aftmost read
  item (bounded by the overhang), spaces above the deck built on the deck, deckhouse tiers and
  above-deck spaces kept inside the deck outline, estimated particulars named on the page.
- Demo runs (round s3b for both): no findings. GA-005 (bulk carrier): holds, hatch coamings,
  crane posts, engine room, double-bottom and other tanks, five deckhouse tiers. GA-120 (tanker):
  slop and six cargo tanks, engine room, deckhouse tiers; depth estimated from the space tops.
  Many of lane U's spaces have no extent yet and are skipped (listed in ga_estimate.json),
  among them the tanker's ballast (W.B.T.) tanks, so the cargo tanks are full breadth (guessed).
- Web build of both runs passes every gate; screenshots of the 3D views and of hover-to-source on
  a hold, a cargo tank and a deckhouse tier are in work/ga-arrangement-demo/screenshots/.
- Known limits (outside this lane): the 3D view's "DWL" and "frames" values are always guessed by
  the UI from the hull size (app/ui/js/reference3d.js has no stated input), so the frame numbers it
  shows in 3D are not the GA's frames.

Gate added after the first lane U reading (before any demo run was accepted):
- G7 depth: a depth from the drawing agrees with the median top of the read cargo holds/tanks
  within its uncertainty (at least 0.3 m); a derived depth is not checked against itself.

## Resume point

Rebuild from a newer lane U round (for example the final `r9/<part>/<case>/`), then the web
check and screenshots (helper scripts kept in work/ga-arrangement-demo/):

```sh
bash work/ga-arrangement-demo/rebuild.sh <round for GA-005> <round for GA-120> "<lane U commit>"
python work/ga-arrangement-demo/serve.py work/ga-arrangement-demo/web-check 8773 &
node work/ga-arrangement-demo/shots.js http://127.0.0.1:8773/ work/ga-arrangement-demo/screenshots runs
node work/ga-arrangement-demo/shots.js http://127.0.0.1:8773/ work/ga-arrangement-demo/screenshots hover
```

rebuild.sh takes the round directory names under dev-runs (for r9 use `r9/<part>`). Keep a ship
on its last passing round when the new one has a finding. Hand the PM `runs/`, the two
`*.web-selection-entry.json` files and the screenshots.
