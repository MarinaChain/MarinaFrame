# Run view: more room for the drawing and the 3D model (lane J, 2026-11-11)

Branch `lane/run-view-space`. Base: `origin/continue/v0.5` after the merge of
`lane/provenance-view` (lane H); until that merge, `origin/lane/provenance-view`.

## Problem

User feedback at laptop size (mock data): the right column (section review, line legend, tabs,
a tall timeline of agent steps with quotes, tools, times and costs) takes about a third of the
width, and the floating fact card of a picked part ("Main deck") covers the 3D model next to the
part. Before: `work/run-view-space/before-*-{run,pick,hover}.png` (main checkout `work/`).

## Design (agreed with the PM)

1. **Details rail.** The right column folds to a thin icon rail (`#details-rail`, 40 px): Show
   details (⌘4), the review count (opens the column at the next section to check), and one icon
   per tab (opens the column at that tab). The choice is remembered per viewer in `prefs`
   (`details`). With no stored choice the column starts folded below 1800 px of window width.
   The column opens by itself, without changing the stored choice, when the person goes to a
   section that needs a decision (Next, N, a tile that needs a check).
2. **Hover label.** Hover on a part in 3D shows only a small label: part name and its source chip
   (read, guessed, ...). The hovered tank's own name label is left out then.
3. **Fact card.** A picked part's full fact card shows in the right column (`#part-card`, above
   the section review). With the column folded, a compact card docks in a corner of the 3D pane:
   title row and 3 key facts; the title row expands it to all facts.
4. **Free side.** The hover label and the docked card never cover the hovered or picked part, the
   lane-H source lines (`.source-links`), or an open part list. Placement is a pure function
   (`placeClear` in `js/dock3d.js`): the first candidate box that covers nothing, else the one
   that covers least. The docked card moves only when its corner starts to cover something.
5. **Timeline.** Each model step in the Thinking tab is one row (title, time, cost); a click
   expands its quote, tool card, Why, images and actions. A step with person actions (Keep anyway)
   starts expanded. Quiet code steps stay one line as before.

Motion: the column transition stays short and is off under reduced motion; nothing new animates.
Keyboard: rail buttons, card toggle and step rows are buttons with `aria-expanded` where they open
something; ⌘4 still toggles the column.

## Steps and checks

| Step | Files | Check |
| --- | --- | --- |
| 1 Placement rules | `js/dock3d.js` | `ui-tests/dock3d.test.mjs` |
| 2 Rail + default + auto-open | `index.html`, `js/details.js`, `js/inspector.js`, `js/run_strip.js`, `styles.css` | `ui-tests/details.test.mjs` |
| 3 Card in column / docked, key facts | `js/factcard3d.js`, `js/model3d.js`, `js/workspace.js` | `ui-tests/factcard3d.test.mjs` |
| 4 Hover label | `js/model3d.js`, `styles.css` | screenshots, `dock3d` tests |
| 5 One-line steps | `js/live.js`, `styles.css` | `ui-tests/details.test.mjs` (step rows) |
| 6 Screenshots 1440x900, 1280x800, 2000x1300 | `work/run-view-space/shots.mjs` | `after-*` PNGs |
| 7 Quick tier UI tests | — | `node --test app/ui-tests` |

## Resume point

Read this file and `git log origin/lane/run-view-space`. The status table below says which
steps are done. Screenshot script: `node work/run-view-space/shots.mjs <label>` with a static
server on `app/ui` at port 4317 (`python3 -m http.server 4317 --directory app/ui`) and the local
mock GLB copied to `app/ui/mock/files/whole-vessel-draft.glb` (ignored by git).

## Status

- [ ] 1 Placement rules
- [ ] 2 Rail
- [ ] 3 Card
- [ ] 4 Hover label
- [ ] 5 Steps
- [ ] 6 Screenshots
- [ ] 7 Tests, push
