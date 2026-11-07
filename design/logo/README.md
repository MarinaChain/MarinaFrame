# MarinaFrame logo options

Status: draft for CEO review. Nothing is committed. Five options, all built from the MarinaChain product-mark recipe.

## 1. Brand rules extracted from the existing marks

Sources read: `marinaai-wordmark.svg`, `marinanet-wordmark.svg`, `marinanet-mark.svg`, the MarinaAI chip candidates (A4 to A4d), `marinavalue-mark.svg`, the MarinaNet and MarinaAI candidate sheets, the Media Kit `03-Logos` files, and the two Esbjerg one-pagers. Copies of the files used by the build are in `reference/`. The originals are unchanged.

### Colours (exact values from the SVGs)

| Use | Hex |
| --- | --- |
| Wordmark, navy backgrounds | `#06448E` |
| Waves (two strips) | `#00CCFF` |
| Sign (the product-specific shape) | `#09DBA9` |
| Gaps and white version | `#FFFFFF` |

The Media Kit `logo_navy.svg` and `logo_white.svg` files are single-colour: all navy, or all white. The white-on-navy lockups here follow that rule.

### Product mark construction

- Canvas: `viewBox="0 0 196 164"`.
- The two cyan wave paths are MarinaChain's own, copied unchanged. They are the same in every product mark.
- MarinaChain's logo has a mint "roof" above the waves. A product mark replaces this roof with a product sign in the same mint.
- The sign is clipped to the MarinaChain hexagon: `M45 63 L68 22 Q78 4 99 4 L138 4 Q156 4 164 20 L196 76 L178 116 L148 160 L40 160 L0 82 Z`.
- A white gap, 7.5 units wide, separates the sign from the top wave (the top wave is stroked 15 units in the mask).
- The sign shows only above the waves. It is clipped at the middle of the top wave's band.
- Detail inside the sign is a cut-out gap, 5 units wide (MarinaNet net lines: 5; MarinaAI die: 5; chip pin-1 mark: 7). Outer corners are rounded: 6 (MarinaValue bars), 10 (chip body), 2 (chip pins).
- The sign is a flat, solid, single-colour pictogram. It has no letters (the CEO asked for "just the chip without the letters AI").

### Wordmark construction

- Outlined paths, no live text. Cap height 11.97 units (0.2394 to 12.2094); x-height from 3.76; stem width about 2.7. The viewBox is 13 units high.
- The face is a geometric sans with a single-storey "a", round "o"-like bowls and a flat-cut "r" and "n". It looks like Outfit. Outfit is not installed here, and the files are outlines, so I re-used the outlines instead of matching a font.
- "Marina" is the official outlines, unchanged. The product suffix follows with no space, in the same navy, the same weight and the same size. There is no colour split and no separator. Letter gaps are about 0.9 to 1.5 units.
- The existing product wordmarks re-use official glyphs wherever the official files have them (`e`) and draw the others to the same cap height, x-height and stem width (A, I, N, t, D, c, s).

### Lockup

Horizontal only: mark on the left, wordmark on the right, centred on each other vertically. From the product sheets: mark 110 px high, wordmark 52 px high, gap 34 px. In mark units: wordmark scale 5.96, gap 50.7. The company logo (`logo.svg`) is the same idea: mark left, one-word camel-case wordmark, navy.

### How the product marks relate to the MarinaChain logo

Same waves, same hexagon, same mint, same gap above the waves. Only the sign changes. This gives a family. A new mark that changes the waves, the colours or the clipping will not look related.

## 2. What I built

Files for each option (`N-name/`): `mark.svg`, `lockup.svg`, `lockup-white-on-navy.svg`, `app-icon.svg`, PNG previews of each, `app-icon-{1024,128,32,16}.png`, and `icon-test.png` (all four sizes on one sheet).

Also: `overview.png` (all options next to MarinaNet and MarinaAI), `marinaframe-wordmark.svg`, and `build/` (the generator: `python3 build/build.py`, then `python3 build/overview.py`).

Wordmark: "Marina", r, a, n and e are official outlines. F is drawn (stem and arms match the stem and cap height of M and N). The m is two official n glyphs joined, so its stems and arches are identical to the official ones. The result is close to a font-set "m" but its arches are slightly wider than a true Outfit m.

App icon test: macOS style. Canvas 1024, tile 824 with a 185 corner radius, navy tile, the full-colour mark at 3.3 times scale. The white bare mark on a light ground is also shown at 16, 32 and 64 px.

Renderer: `rsvg-convert` and `cairosvg` are not installed, so all PNGs come from headless Google Chrome (the same renderer the MarinaAI and MarinaNet sheets used).

## 3. The options

### 1. Body plan (`1-body-plan/`)
Two nested hull section curves, as a naval architect draws a body plan, with the keel under water. Idea: the drawing type the app reads. Weakness: thin lines, lighter than the sibling marks; at 16 px it is a few mint strokes.

### 2. Block (`2-block/`)
An isometric block (a hexagon, like MarinaChain's own mint shape) with a hull section cut into one face. Idea: a flat section becomes a 3D solid. It has the most mint area, so it matches the weight of the MarinaNet globe and the MarinaAI chip. It is still readable as a cube at 32 px.

### 3. Dividers (`3-dividers/`)
Dividers, the tool that takes offsets off a lines plan. The points are under water. Idea: precision, and measuring a drawing. It is the most specific picture of the product's job. Weakness: thin legs; at 16 px it reads as a small mint spike.

### 4. Frames (`4-frames/`)
Three rounded frames that converge, like ship frames seen along the hull, or picture frames; a flat shape that reads as depth. It plays on the name directly. Weakness: the wave cuts the outer frame at an angle, and the shape can read as an arch or a "P". It is the weakest of the five.

### 5. Verified (`5-verified/`)
A hull curve that closes as a check mark. Idea: every line is checked against the drawing. Weakness: a check mark is a generic symbol, and a single stroke is light next to the sibling marks.

## 4. Recommendation

Use option 2, Block.

- Weight: it is the only option as solid as the MarinaNet globe and the MarinaAI chip, so it sits in the family without looking thin (see `overview.png`).
- Link to MarinaChain: its hexagon outline repeats the shape that the product mark is clipped to.
- Story: a flat face with a hull section on a solid block says "2D drawing to 3D model" without text.
- Small sizes: the cube silhouette and the three faces still read at 32 px, and the tile test at 128 px is the cleanest of the five.

Second choice: option 3, Dividers. It tells the best story but needs a heavier stroke or a larger sign to match the others.

## 5. Known limits

- The "m" in the wordmark is built from two official "n" glyphs and is a little wider than a true Outfit "m". A designer with the Outfit font should redraw "Frame" (F, m) before final use.
- The sign sits in the hexagon above the waves, so a tall sign is cut by the wave at the lower right. This is the same constraint the existing marks have.
- The white-on-navy lockups are all white, as in the Media Kit white logo. A full-colour mark on navy (mint and cyan) also works, but no existing file defines it.
- The MarinaAI mark in the overview is candidate A4d. I do not know which chip candidate the CEO chose.
- All PNGs come from headless Chrome. No other renderer was available.


## 6. Round 2: ship under construction

Files: `round-2/N-name/` (same set as round 1), `overview-round-2.png`, generator `build/round2.py` and `build/overview_round2.py`. The brand system is unchanged. The hull is placed so that its keel lies in the trough of the top wave and its stem rises along the crest, inside the free area above the 7.5-unit wave gap.

1. **Half-built hull:** stern plated solid, bow half open frames (keel, stem, sheer stringer, three ribs).
2. **Slipway:** a plated hull cut at two stations, under a tower crane with a hook. Clearest at 32 px.
3. **Skeleton:** keel, stem, three frames in 3/4 view, joined by a near-side rail. The first version looked like antlers; the rail fixed this.
4. **Berth:** option 1's half-built hull under the crane. It tells the whole story, but its ribs merge at 32 px.

Recommendation: option 4 for the story; use option 2 where the mark is 32 px or smaller.

## 7. Final: Slipway

The founder chose round 2, option 2. Files are in `final/`; the generator is `build/final.py` (`python3 build/final.py`, then `python3 build/overview_final.py`). `overview-final.png` shows the lockup, the icon sizes, white on navy, and MarinaNet and MarinaAI beside it.

**Refinement.** The crane jib is 11 units thick (was 9) and the mast 15 (was 12). The hull is larger (scale 0.9, was 0.78) with an 8-unit plating outline, and its bow is lower, so the bow stays clear of the jib and mast. Station gaps are 5 units. The hook sits clear of the hull and the gaps no longer cross it. Weight now matches the MarinaNet globe and the MarinaAI chip (`overview-final.png`).

**Wordmark m.** The m is now one outline built from the official n: the n's left stem and first arch, then the n's arch again on a shared middle stem (pitch = the n's own stem pitch). The first arch ends in the notch where the second arch starts. The earlier "two n glyphs on top of each other" m had a small flat ledge on the middle stem; it is gone. F is still drawn by hand.

| File | Use |
| --- | --- |
| `mark.svg` | Full colour mark, transparent background |
| `lockup.svg` | Horizontal lockup, full colour, for light backgrounds |
| `lockup-white.svg` | All white, for photos or dark backgrounds |
| `lockup-on-navy.svg` | Navy plate, colour mark, white wordmark |
| `mark-mono-navy.svg`, `mark-mono-white.svg` | One-colour mark (stamps, fax, emboss) |
| `app-icon.svg`, `app-icon-1024.png` | macOS tile: 1024 canvas, 824 tile, 100 px margin, radius 185 |
| `favicon.svg` | Browser tab and small UI use: navy tile, mark larger in the tile |
| `wordmark.svg` | Wordmark only |
| `ui-mock-sidebar.png` | The app UI with the mark in the sidebar (browser mock, dark scheme) |

**Colours.** Navy `#06448E`, cyan `#00CCFF`, mint `#09DBA9`, white. Use the colour lockup on white or very light grey. Use `lockup-on-navy.svg` or `lockup-white.svg` on navy or dark photos. Do not recolour the sign or the waves, and do not put the colour mark on mid-tone backgrounds.

**Clear space.** Keep free space equal to the height of the wordmark's capital M (about half the mark's visible height) on all sides of the lockup and the mark.

**Minimum size.** Lockup: 120 px wide on screen, 30 mm in print. Mark alone: 24 px (the crane, hull and waves all read at 32 px; at 16 px only the shape reads). Below 24 px use `favicon.svg`.

**App icon in the app.** `app/src-tauri/icons/` was regenerated from `app-icon-1024.png` with `npx tauri icon`. The android and ios folders that the tool also writes were removed because the app is desktop only. The previous icons are not kept; git history holds them. `bundle.icon` in `tauri.conf.json` already lists files that exist, so it is unchanged. The mark is also in `app/ui/assets/` and sits beside the window buttons at the top of the sidebar; `favicon.svg` is the page icon.
