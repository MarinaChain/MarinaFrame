# Run view: geometry first (lane K, 2026-11-11)

Branch `lane/run-view-focus` from `origin/continue/v0.5` at b4f70cb (lane J merged).

## Problem

The user asked whether the Run view still shows too much information compared with incumbent
tools (surface modelling and naval design tools give about 80-85 % of the screen to geometry and
show information on demand). The user approved this pass. Before (mock backend, details column
folded, sidebar expanded), the drawing and 3D panes take this share of the window area:

| Window | Stage (px) | Share |
| --- | --- | --- |
| 1440 x 900 | 1216 x 494 | 46.3 % |
| 1280 x 800 | 1056 x 394 | 40.6 % |
| 2000 x 1300 | 1396 x 894 (column open) | 48.0 % |

Rows besides the stage: counter row 37 px, sheets and requests 142 px, narration 32 px, section
strip 91 px, run history 36 px. The 3D tool bar is 74 px (two rows) and 114 px (three rows) at
1280 px with a part picked. Share = stage box area / window area; the pane heads count as
geometry. Screenshots: `work/run-view-focus/before-*.png` (git-ignored `work/`).

## Design

1. **One run bar** above the panes (`#run-bar`), one row:
   - a status sentence button (`#run-status-toggle`): "Draft · 2 sections need you · Lines plan:
     lines too faint", with the primary action inline ("Replace" for a bad sheet) and Next (N);
   - the section tiles, compact (one line each: place, state glyph, source glyph, ink distance;
     a small shape), still the keyboard list box of the review;
   - at the end, Watch again and the fit as a small text chip ("fit 0.90", with the live change).
   A click or Enter on the sentence opens a drawer (`#run-drawer`) over the top of the panes with
   the detail: the review in words ("1 traced · 1 interpolated · 1 AI corrected · 2 warnings"),
   the hull error in words ("0.8–14 % from the drawing", tooltip explains), the parts link, the
   sheets, outputs and requests (`renderSheetReview`, unchanged), the revision ladder, and the
   run facts. Escape or a click outside closes it.
2. **Words, not codes**: the glyph-and-count chips leave the run view; the drawer uses words.
   The fit dial leaves the 3D pane (it becomes the text chip; it still counts up and flashes,
   not under reduced motion).
3. **Costs and timings** (step costs, step times, tool durations, list cost) are hidden on the
   Run tab unless Settings > Appearance > "Show costs and timings" is on (per viewer, `prefs`
   key `showCosts`). History shows the open run's model requests and list cost always.
4. **Run history**: the revision ladder moves into the drawer; the bottom strip shows only the
   replay transport while a replay is open. The narration row shows only while the run works or
   a replay is open.
5. **3D tool bar**: one row; groups that do not fit move into a "More" menu at the end of the
   bar (`splitToolbar` in `js/controls3d.js`, a pure function). Lane H's "best guess" label
   slides along its line off the tool bar (`labelSpot` in `js/provenance.js`).
6. **Sidebar**: on the Run view, a window under 1800 px starts with the global sidebar
   collapsed (icons only); the person's own toggle on the Run view is remembered (`railRun`).

Kept: hover-to-source (H), the details rail and docked card (J), Accept / Mark / Next, keyboard
access, reduced motion, light and dark.

## Steps and checks

| Step | Files | Check |
| --- | --- | --- |
| 1 Status sentence, words, drawer | `js/run_status.js` (pure), `js/run_header.js`, `index.html`, `styles.css` | `ui-tests/run_status.test.mjs` |
| 2 Fit chip, ladder in drawer, narration only when active | `js/live.js`, `js/workspace.js`, `styles.css` | screenshots |
| 3 Costs and timings switch | `js/settings_view.js`, `js/app.js`, `js/live.js`, `js/inspector.js`, `js/vessel_pages.js`, `index.html` | `run_status.test.mjs`, screenshots |
| 4 Tool bar one row + More; label off the tool bar | `js/controls3d.js`, `js/model3d.js`, `js/provenance.js` | `ui-tests/run_status.test.mjs` (split, label) |
| 5 Sidebar collapsed on Run below 1800 px | `js/commands.js`, `js/router.js` | screenshots |
| 6 Screenshots + share at 1280x800, 1440x900, 2000x1300 | `work/run-view-focus/shots.mjs` | `after-*` PNGs, share >= 80 % at 1440 and 1280 |
| 7 Quick tier | — | `node --test app/ui-tests`, `node app/ui-tests/a11y.mjs`, `make test-quick` |

## Resume point

Read this file and `git log origin/lane/run-view-focus`. The status list below says which steps
are done. Screenshots: serve `app/ui` (`python3 -m http.server 4327 --directory app/ui`), make
the mock GLB (`PYTHONPATH=src .venv/bin/python app/ui/mock/make_whole_vessel_mock.py`), then
`node work/run-view-focus/shots.mjs <label>` from the worktree root (needs `npm ci` in `app/`).

## Status (2026-11-11)

- [x] 1 Status sentence and drawer (`js/run_status.js`, `#run-bar`, `#run-drawer`; Escape and a
  click outside close it, focus returns to the sentence). No tooltip on the sentence: it covered
  the drawer.
- [x] 2 Fit chip in the bar; ladder and run facts in the drawer; narration and transport rows
  only while the run works or a replay is open (checked: replay 628 px stage, closed 696 px).
- [x] 3 Costs and timings: `.cost-timing` + `body[data-costs]`; Settings switch; History line
  "Run 1: 3 model requests · $0.0121 list cost".
- [x] 4 Tool bar one row (34 px at every size); at 1280 x 800 with parts, "Parts and spaces" and
  "Show" go into More. Best-guess label checked at 1280 x 800: clear of the tool bar.
- [x] 5 Sidebar collapsed on Run below 1800 px (`railRun`). The collapsed brand name is now
  visually hidden text, not `display: none` (axe flagged the bare `aria-label` on `.brand`).
- [x] 6 Share after (before): 1440 x 900 82.3 % (46.3 %), 1280 x 800 80.2 % (40.6 %),
  2000 x 1300 64.2 % (48.0 %; the details column is open there by lane J's rule).
  Screenshots `work/run-view-focus/{before,after}-<size>-{run,pick}.png`, after-only
  `status-open`, `after-1280x800-best-guess.png`.
- [x] 7 `node --test app/ui-tests`: 237 pass. `node app/ui-tests/a11y.mjs`: no violations.
  `make test-quick`: see the commit message.

## Notes for review

- At 1280 px with the details column open, the bar shows about two section tiles; the strip
  scrolls. The sentence ends in "…" first.
- 2000 x 1300 stays under 80 % because the details column starts open at >= 1800 px (lane J).
- Screenshots and the two scripts (`shots.mjs`, `guess_label.mjs`) are in the main checkout's
  `work/run-view-focus/` (git-ignored).
- Not checked in the Tauri shell; Chrome on the mock backend only.
