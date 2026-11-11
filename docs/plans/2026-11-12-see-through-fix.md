# See-through hull toggle shows no change (lane Z, 2026-11-12)

Branch: `lane/see-through-fix`, from `origin/lane/ga-arrangement-demo` (5b618bf).

## Report

On https://frame.marinachain.io and in the desktop app, the See-through button changed its
pressed state, but the hull on screen did not change.

## Cause

The 3D view has two hull meshes: the solid STL hull of the section lines (`hull`, made in
`setModel`) and the hull part of the whole-vessel GLB (a shell mesh). `setWholeVessel` hides the
STL hull, but only when the STL hull is already there. The web demo loads the whole vessel
first and the section-lines model after it. `setModel` then added a new STL hull that was
visible and opaque, on top of the faint whole-vessel hull. See-through changed the GLB hull
correctly, but the solid STL hull covered it in both themes.

Evidence (demo build with real data, debug hook in a scratch copy only): with See-through on,
the GLB hull opacity was 0.1, but `hull.visible` was true and its material was opaque
(opacity 1, transparent false).

## Fix

- `visibility3d.js`: new rule `sectionHullShown({ wholeVesselShown })`.
- `model3d.js`: `setModel` sets the new STL hull's visibility from that rule; the two other
  places that show or hide the STL hull use the same rule.

## Test

`app/ui-tests/visibility3d.test.mjs`: the rule, and a check that every `hull.visible`
assignment in `model3d.js` uses it, including the one in `setModel` right after the hull is
made. The check fails on 5b618bf and passes with the fix. Node has no WebGL, so the test
reads the source; the browser check below covers the behaviour.

## Browser check (demo build, Survey launch concept preview)

- Opens see-through: tanks and steel show inside the hull (before the fix: solid hull).
- See-through off and on: the view changes at once, dark and light theme.
- Hull only: STL hull shows. Back to the whole vessel: STL hull hidden again.
- Section cut, Section lines, Fairness (zebra, curvature, off): STL hull stays hidden; no
  console errors.

## Note (not changed)

With tanks shown, See-through off draws the hull at 0.22 opacity and on at 0.1
(`SHELL_OPACITY_WITH_INSIDES`, an existing tested rule). The difference is small. The button
text says "Press again for a solid hull", which is true only when no tanks or steel show.
A product decision is needed if off must mean a solid hull.

## Resume point

Done when `make test-quick` passes and the branch is pushed. Not merged.
