# Lane T: desktop demo kit (2026-11-11)

Branch `lane/desktop-kit` = origin/continue/v0.5 + origin/lane/web-demo (4e23996) +
origin/lane/concept-launch (1e75d7b). Design and steps: docs/DESKTOP_KIT.md.

## Plan and state

| Step | State |
|---|---|
| 1. Merge web-demo and concept-launch lanes | done, no conflicts |
| 2. Part reviews in the run folder (`review/part_reviews.json`), legacy config entries read and moved | done, tests in `parts.rs` |
| 3. Added sheets record (`sources/sheets.json`), listed by `sources.rs`, part boxes placed by `parts.rs`; `scripts/add_run_sheets.py` | done, tests in `sources/tests.rs`, `parts.rs`, `tests/test_add_run_sheets.py` |
| 4. `presentation.json` (first view, note, credit; concept label from the run's policy) | done, tests in `presentation.rs`, `app/ui-tests/presentation.test.mjs` |
| 5. `MarinaFrame make-run` (deterministic run with the app's own executable) | done (app shell; no unit test: it is a thin call of `actions::run_deterministic_now`, checked by making the kit runs) |
| 6. Build DMG from the final code commit; make kit runs with the DMG's binary | see work/desktop-kit/ |
| 7. Kit: runs zip, install-runs.command, README.md (for an AI agent), GUIDE.md/pdf, MarinaFrame-demo-kit.zip | see work/desktop-kit/ |
| 8. Clean-user check (temporary HOME), screenshots in work/desktop-kit/screenshots/ | see work/desktop-kit/ |

## Resume point

If the code commit exists but `work/desktop-kit/` is incomplete: rebuild the DMG from the branch
head (step 6). Kit runs must be made again with every new DMG, because the banner check compares
the run with the exact executable. Scripts used to make the kit: `work/desktop-kit/make/`.

## Gates (written before the runs)

- Each kit run opens in the built app with no "other-build" notice.
- Gunnerus Sources list holds the 10 named sheets; a tank part shows its box on the tank arrangement.
- Reviews from the web demo config show in the copied runs.
- The installer never uses sudo, xattr or security settings and never overwrites a run folder.
- `engineering_approved` stays false in every run.

## Results (2026-11-11)

- Code commit a4b7c7c; `make test-quick` passed (Rust, 1930 Python, UI 266 incl. new tests, secret scan 0).
- DMG built from a4b7c7c (app executable SHA-256 c32e4d37...). Kit runs made with that app (`make-run`):
  Gunnerus, DTMB 5415, Series 60 all `draft_not_verified`, same build; concept run has no controller binary.
- The shipped worker reads the Gunnerus body plan differently from the web demo's older worker
  (hull 450.2 against 446.8 m3), so the whole-vessel stages were rebuilt on the kit run
  (`work/desktop-kit/make/gunnerus_whole_vessel.sh`): 48 parts, 24 tanks, display model bound to
  the kit run's r0001. The aft_bulwark part revision of the web run is not in the kit run.
- Clean-user check (temporary HOME, app from the DMG, installer run twice): 4 runs installed, then
  "already there" for all 4. Both showcase runs open with no other-build notice; Gunnerus on its
  whole vessel with its credit line; a tank hover shows the Tank Arrangement sheet with the tank
  framed; Sources lists 11 drawings; concept run opens see-through with its concept label. A review
  saved in one HOME shows (1/48 reviewed) after the run is copied to a second HOME.
- Kit: `work/desktop-kit/` (MarinaFrame-demo-kit.zip and its parts; scripts in `make/`).
