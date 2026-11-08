# MarinaFrame visual design language (lane C)

Date: 2026-11-08. Branch: `design-c-visual` from `continue/v0.5`. Scope: visual language only, no code.

## Problem

The current UI (`app/ui/index.html`, `styles.css`, `js/app.js`; screenshots in
`work/ui-polish/after/`) reads as a prototype dashboard: system fonts, flat warm-grey
panels, orange used for both brand and warning, chips with mixed meaning, a 3D view that
shows bounding boxes rather than a hull taking form, and a timeline that lists events but
does not show thinking. The founder wants a polished native app where the agent's
reasoning and the hull forming are visible live.

Founder rules that apply to all directions:

- Chips of one or two words replace text labels (`Traced`, `AI corrected`, `Needs review`).
- Pickers, segmented controls and buttons replace typing.
- Nothing overflows: truncate with ellipsis and a tooltip, wrap chips to a second row, never clip.

Shared constraints: Tauri 2 webview, offline. All fonts are bundled as WOFF2 in
`app/ui/assets/fonts/` with system fallbacks. All fonts below use SIL OFL 1.1, which allows
bundling in a commercial app (keep the `OFL.txt` with the files; do not sell the fonts alone).

The five section source labels need one fixed encoding in every direction. Colour is never
the only signal; each label also has a stroke pattern and a glyph, so the encoding survives
colour-blindness, greyscale print and PDF export.

| Label | Stroke in 2D | Glyph in chip | Meaning to the user |
|---|---|---|---|
| `traced` | solid | filled dot | Read from the drawing |
| `repaired` | solid with small ticks | wrench | Read, then a gap or kink was fixed |
| `interpolated` | long dash | two-dot bridge | Computed between neighbours |
| `ai_inferred` | dotted | sparkle outline | AI proposed a line with no clear trace |
| `ai_corrected` | solid with diamond nodes | sparkle filled | AI changed a traced line |

## Direction A: Vellum (a modern drafting table)

**Mood.** Calm, exact, trusted. A clean drafting table under good light. The drawing is the
evidence, so the UI looks like the paper the drawing came from.

**References in words.** Drafting film and tracing vellum; a Rotring pen line; the title
block of a lines plan; the restraint of a Swiss engineering catalogue; a blueprint in its
modern reverse form (dark ink on light, blue as the drafting colour, not as a background).

**Palette.**

| Token | Light | Dark ("night vellum") |
|---|---|---|
| `--paper` (app background) | `#F4F1EA` | `#14181E` |
| `--surface` (panels) | `#FBFAF6` | `#1A1F27` |
| `--raised` (cards, dialogs) | `#FFFFFF` | `#222833` |
| `--sunken` (wells, strips) | `#ECE8DE` | `#0F1216` |
| `--rule` / `--rule-strong` | `#DAD4C6` / `#BFB7A5` | `#2C3340` / `#3D4555` |
| `--ink` / `--ink-2` / `--ink-3` | `#1D2430` / `#4A5260` / `#7A8190` | `#E8E4DA` / `#B3B0A8` / `#7F8590` |
| `--drafting` (selection, focus, links) | `#1F4E79` | `#6FA3D6` |
| `--signal` (agent activity, primary action) | `#D9532B` | `#F0703F` |
| `--pass` / `--warn` / `--fail` | `#2E7D5B` / `#A86A12` / `#B83227` | `#4FB389` / `#E0A84A` / `#E5675A` |
| `traced` | `#1D2430` | `#E8E4DA` |
| `repaired` | `#1F7A7A` | `#4CC2C2` |
| `interpolated` | `#5E62A0` | `#9EA2E0` |
| `ai_inferred` | `#A86A12` | `#E8B04A` |
| `ai_corrected` | `#D9532B` | `#F0703F` |

Signal orange is reserved for "the AI acted here" and for the one primary button per view.
Warnings use the amber `--warn`, never the signal colour. This fixes today's overload of orange.

**Typography.** IBM Plex Sans (UI, 400/500/600) with IBM Plex Mono (numbers, offsets,
station labels, tool arguments). Plex Sans Condensed 500 for chips and column heads where
width is tight. Licence: OFL 1.1. Fallbacks: `"IBM Plex Sans", -apple-system, "Segoe UI
Variable Text", system-ui, sans-serif` and `"IBM Plex Mono", ui-monospace, "SF Mono",
"Cascadia Mono", Consolas, monospace`. Scale 11/12/13/15/18/24 px, tabular figures on.

**Iconography.** 1.5 px stroke, 16 px grid, square caps, no fills except state glyphs.
Draw a small custom set for domain nouns: station, waterline, buttock, body plan, sheet,
hull, offset table. Lucide (ISC licence) as the base set for generic actions.

**Line and grid for drawings.** The source sheet stays as scanned. Overlays sit on a
10 mm-equivalent grid at 6% ink, with a stronger rule every fifth line. Traced lines are
1.25 px ink; candidates are 1 px `--ink-3`; the chosen line gets a 3 px halo of
`--drafting` at 18%. Station labels use Plex Mono in a small boxed tag, like a
draughtsman's leader. Corners of the sheet get crop marks, and a title-block chip shows
sheet name, scale and view.

**3D viewport.** Background `--paper` with a faint ground grid that fades at 40 m. The hull
is a matte "drafting resin" (light: `#E9E5DC`, roughness 0.85, no metalness) with a fine
1 px silhouette line in `--ink`. Each station section is drawn as a ribbon in its source
colour and pattern; the hull surface between stations is tinted 12% toward the weaker of
the two neighbouring labels. Lighting: one soft key from upper left at 35°, a hemisphere
fill, and screen-space ambient occlusion at low strength; no coloured lights, no bloom.
Default camera: three-quarter view from the bow, starboard side, orthographic option one
click away.

**Motion.** Motion explains change, nothing else. A new section draws itself as a pen
stroke (stroke-dashoffset, 400 ms, ease-out). The hull skin grows between finished
stations (600 ms). The agent stream adds lines with a 120 ms fade and 4 px rise. No
spinners: a thin signal-coloured "pen" line moves along the active tool card. All motion
off under `prefers-reduced-motion`.

**Density.** Medium. 28 px rows, 8 px base spacing, 13 px body. Comfortable for long
review sessions; the drawing and the hull get at least 60% of the window.

## Direction B: Graphite (a precision-engineering CAD workspace)

**Mood.** Focused, technical, powerful. A dark tool that disappears behind the geometry.

**References in words.** A modern parametric CAD workspace at night; machined anodised
aluminium; a metrology lab's measurement report; a code editor's quiet dark chrome.

**Palette.**

| Token | Light | Dark (primary) |
|---|---|---|
| `--bg` / `--surface` / `--raised` | `#F2F3F5` / `#FFFFFF` / `#FFFFFF` | `#0E1013` / `#16191E` / `#1E2228` |
| `--rule` | `#DDE0E5` | `#2A2F37` |
| `--text` / `--text-2` | `#15181D` / `#5B6370` | `#E6E8EB` / `#9097A3` |
| `--accent` (cyan) | `#0B7FA8` | `#38BDF8` |
| `--agent` (violet, AI activity) | `#6D4FD8` | `#A78BFA` |
| `--pass` / `--warn` / `--fail` | `#15803D` / `#B45309` / `#B91C1C` | `#4ADE80` / `#FBBF24` / `#F87171` |
| `traced` / `repaired` / `interpolated` | `#334155` / `#0F766E` / `#64748B` | `#CBD5E1` / `#2DD4BF` / `#94A3B8` |
| `ai_inferred` / `ai_corrected` | `#7C3AED` / `#C026D3` | `#A78BFA` / `#E879F9` |

**Typography.** Inter (UI) with JetBrains Mono (data). Both OFL 1.1. Fallbacks as in A.
Tighter scale 11/12/13/14/16/20 px.

**Iconography.** Lucide at 1.25 px stroke, 14 px, monochrome; state shown by colour only
on the glyph, never on the whole control.

**Line and grid for drawings.** The scan is inverted and desaturated in dark mode (paper
becomes `#1A1D22`, ink becomes `#C9CDD3`) so overlays dominate. Overlays are 1.5 px with
end caps and live length readouts. Grid is a dot grid at 8% text colour.

**3D viewport.** Dark gradient background `#0E1013` to `#1A1E24`. Hull in satin
"titanium" (`#8A919C`, metalness 0.3, roughness 0.45) with a curvature (zebra) toggle.
Source labels shown as emissive section ribbons. Three-point studio light plus a cool rim.

**Motion.** Fast and mechanical: 120-180 ms, linear-out easing, sections snap in with a
brief cyan scan line. Agent stream types out tokens.

**Density.** High. 24 px rows, 12 px body, collapsible everything.

## Direction C: Bridge (a ship's bridge instrument panel)

**Mood.** Maritime, operational, legible at a glance. The app is an instrument you watch.

**References in words.** An integrated bridge system in night mode; ECDIS chart display;
a brass-and-glass clinometer re-imagined as flat instruments; Airbus cockpit typography.

**Palette.**

| Token | Light ("day") | Dark ("night", primary) |
|---|---|---|
| `--bg` / `--surface` / `--raised` | `#E8ECEF` / `#F6F8F9` / `#FFFFFF` | `#071018` / `#0C1823` / `#13222F` |
| `--rule` | `#C8D0D6` | `#1F3344` |
| `--text` / `--text-2` | `#0B1A26` / `#4B5D6B` | `#D7E3EA` / `#7F97A8` |
| `--accent` (sea green) | `#0E7C66` | `#34D3A6` |
| `--agent` (amber) | `#B86E00` | `#FFB547` |
| `--pass` / `--warn` / `--fail` | `#0E7C66` / `#B86E00` / `#C62828` | `#34D3A6` / `#FFB547` / `#FF5C5C` |
| `traced` / `repaired` / `interpolated` | `#0B1A26` / `#00838F` / `#5C6BC0` | `#D7E3EA` / `#4DD0E1` / `#8C9EFF` |
| `ai_inferred` / `ai_corrected` | `#B86E00` / `#D84315` | `#FFB547` / `#FF8A50` |

**Typography.** B612 (UI) with B612 Mono (data). OFL 1.1; designed for cockpit displays,
so it stays legible at small sizes. Fallbacks as in A.

**Iconography.** Filled 2 px instrument glyphs inside round bezels; dials, gauges and
compass-rose motifs for status.

**Line and grid for drawings.** Drawing sits in a "chart window" with a bezel; grid in
the style of a chart graticule with lat/long-style tick labels for stations and waterlines.

**3D viewport.** Deep navy void with a horizon glow; hull in pale matte with a sea-plane
at the design waterline (transparent, 15%). Section ribbons glow softly.

**Motion.** Sweeps and needles: confidence gauges swing, a radar-style sweep marks the
active sheet. 300-500 ms, ease-in-out.

**Density.** Low. Large readouts, 32 px rows, 14 px body.

## Recommendation: Vellum (Direction A)

1. **The drawing is the evidence.** Naval architects sign off against the lines plan.
   Vellum keeps the scan in its native paper look and puts the UI in the same material, so
   overlays read as annotations on the real sheet, not as a game layer. Graphite inverts the
   scan, which weakens trust in "what the drawing really says".
2. **Review is long, careful work.** Engineers check offsets for hours. A light paper default
   with a true dark mode is easier on the eyes in a lit office than a dark-only tool; Bridge
   is tuned for a dark bridge at night, not a design office.
3. **It shows the AI honestly.** One reserved signal colour for AI action plus the stroke
   patterns gives an instant, auditable picture of what is traced and what is guessed.
4. **It is distinct.** Every CAD tool is dark grey; every AI tool is violet. A drafting-table
   look is recognisable, fits shipyard culture and suits exports and PDFs.
5. **It is the shortest path from today.** The current warm neutrals and orange already
   point this way; the change is discipline (tokens, fonts, reserved colour), not a rewrite.

Take from the others: Graphite's zebra-curvature toggle in 3D; Bridge's ring gauge for the
scoreboard.

## Component kit (Vellum)

All sizes are at 100% zoom. All text in chips is one or two words.

- **App shell.** Native title bar (40 px) with traffic-light inset; left sidebar 240 px;
  centre stage split drawing | 3D with a 1 px `--rule` splitter and a grab handle; right
  inspector 340 px, collapsible; status bar 24 px in `--sunken`. Panel corners 8 px,
  no drop shadows except dialogs (0 8 24 rgba(29,36,48,0.14)). Window min 1024 x 680.
- **Sidebar.** Project switcher at top (picker, not a text field). Sections: `Runs`,
  `Sheets`, `Datasets`. Run rows: name (truncate), one state chip, relative time in
  `--ink-3`. Selected row: `--raised` card with a 2 px `--drafting` left rule.
- **Sheet thumbnails.** 4:3 card, scan at full fidelity on `--paper`, crop marks at corners,
  title-block chip bottom-left (`Body plan`, `Profile`, `Half-breadth`), a progress hairline
  along the bottom edge in source colours (one segment per station). Hover lifts 2 px.
- **Status chips.** 22 px tall, 8 px side padding, 11 px Plex Sans Condensed 500, radius 11.
  Outline style for states (`Draft`, `Running`, `Needs review`, `Approved`, `Declined`),
  tinted-fill style with glyph for source labels. Max two chips per row item; extra
  collapse into `+2`.
- **Confidence indicators.** A 5-segment bar (12 x 4 px segments) in `--ink`, segments
  hatched when below threshold; number in Plex Mono beside it (`0.62`). In 3D, the same
  value drives ribbon opacity (40-100%). Never a bare percentage without the bar.
- **Agent thought stream.** Right-inspector tab `Agent`. A vertical pen rule on the left;
  each step is one plain sentence in Plex Sans 13 px, with the station chip it refers to.
  Current step has a moving signal-orange pen dot. "Why" disclosures expand to evidence
  crops. Groups collapse by station once done. Auto-scroll pauses when the user scrolls up
  and shows a `Live` chip to jump back.
- **Tool-call cards.** Compact card in the stream: tool glyph, tool name in Plex Mono
  (`trace_section`), target chip (`St 12`), duration, result chip (`Done`, `Retry`,
  `Failed`). Arguments and output fold away; open shows a two-column key/value table.
- **Scoreboard.** Top of inspector: ring gauge for overall fit (`Fair`), then four tiles
  in a 2 x 2 grid: `Sections` 18/21, `Max error` 4.2 mm, `AI edits` 3, `To check` 2.
  Each tile: label chip, big Plex Mono value, tiny sparkline of the run.
- **Timeline / scrubber.** Bottom strip 64 px across the stage. Ticks per agent step,
  coloured by source label produced; diamonds for user decisions; a draggable playhead
  replays drawing overlays and 3D state. Buttons: play/pause, step, `Live`.
- **Dialogs.** Centered sheet, 480 px, `--raised`, 12 px radius, title in 15 px 600, one
  primary (`--signal`) and one secondary button, choices as segmented controls or
  pickers. Escape closes; no free-text fields unless the field is a name.
- **Empty states.** A light line drawing of a body plan in `--rule-strong`, one sentence,
  one action. Example: drawing of stations with `Drop lines drawings to start` and a
  button `Choose files`.

## Image-generation prompts (Vellum)

Shared style for all prompts below; append it to each prompt:

> Photoreal UI mockup of a native macOS desktop application window, 16:10 aspect ratio,
> shown flat and straight-on at 2560x1600, crisp retina rendering. Visual style "Vellum":
> warm off-white paper background #F4F1EA, panels #FBFAF6, hairline rules #DAD4C6, dark
> ink text #1D2430, drafting blue #1F4E79 for selection, a single signal orange #D9532B
> reserved for AI activity and the primary button. Fonts in the style of IBM Plex Sans and
> IBM Plex Mono. Thin 1.5 px line icons. Small rounded chips with one or two words. Calm,
> precise, engineering-grade, generous whitespace, no text overflowing any box.
> Exclude: lorem ipsum, gibberish or misspelled text, emoji, stock photos, people, hands,
> device frames, laptops, desks, glossy gradients, neon, glassmorphism, drop shadows on
> every panel, browser chrome, watermarks, extra windows.

**1. Launch / project home.**
App window titled "MarinaFrame". Left sidebar with a project picker showing "Harbour Tug
HT-24", and sections "Runs", "Sheets", "Datasets". Main area heading "Recent projects"
with a grid of six project cards, each showing a scanned ship lines drawing thumbnail on
paper with crop marks and a status chip: "Survey Launch" chip "Approved", "Pilot Boat"
chip "Running", "Harbour Tug" chip "Needs review", "Passenger Ferry" chip "Draft",
"Workboat" chip "Draft", "Research Vessel" chip "Approved". Top right primary orange
button "New project" and a secondary button "Open folder". Status bar text "Offline ·
Local models ready".

**2. Drop-sheets moment.**
Same window. Centre a large dashed drop zone on paper with a faint line drawing of a body
plan, headline "Drop lines drawings", sub-line "PDF, PNG or TIFF". Three sheet thumbnails
are sliding in, each a scanned lines drawing with a title-block chip: "Body plan",
"Profile", "Half-breadth", and each has a small view picker chip below it. A row of
pickers below: "Units: mm", "Scale: 1:50", "Vessel: Tug". Primary orange button
"Start run", secondary button "Cancel". Sidebar shows project "Harbour Tug HT-24".

**3. Live run (drawing + agent stream + 3D hull forming).**
Three-pane layout. Left-centre: scanned body plan drawing on paper with a fine grid,
station curves overlaid; station "St 12" highlighted with a drafting-blue halo, an orange
pen stroke mid-way along "St 14". Right-centre: 3D viewport on paper-coloured background
with a faint ground grid, a matte off-white tug hull half-formed from bow to midship,
section ribbons in charcoal solid, teal, dashed indigo, dotted amber and orange with
diamond nodes. Right inspector tab "Agent" selected, thought stream lines: "Reading
station 12", "Two candidate lines found", "Chose the heavier outer line", "Checking
fairness with St 11 and St 13"; one tool card in monospace "trace_section" with chips
"St 14" and "Running". Scoreboard at top: ring gauge "Fair", tiles "Sections 14/21",
"Max error 4.2 mm", "AI edits 3", "To check 2". Bottom timeline strip with coloured ticks
and a "Live" chip. Header: "Harbour Tug HT-24 · Body plan" with chip "Running".

**4. Review / correct a section.**
Drawing pane zoomed on station "St 8": three candidate curves, one dotted amber marked
"AI inferred", one solid charcoal marked "Traced". Right inspector heading "Section St 8"
with chips "AI inferred" and "Needs review"; a 5-segment confidence bar with "0.58";
evidence crop thumbnails of the scan; three option rows "Outer line", "Inner line",
"Waterline mark" each with a short one-line reason; buttons "Accept", "Use traced", and
primary orange "Confirm". 3D pane shows the hull with section St 8 lifted and outlined.
Section strip at bottom with cards "St 6", "St 7", "St 8" (selected), "St 9".

**5. Version compare.**
Split view titled "Compare" with two version pickers "r2 · Nov 6" and "r3 · Today".
Left and right 3D hulls in matte off-white with a shared camera; between them a slim
difference legend from drafting blue to orange labelled "0 mm" and "12 mm". Below, a table
of stations with columns "Station", "r2", "r3", "Change", rows "St 4 Traced Traced 0.0 mm",
"St 8 AI inferred Traced 6.1 mm", "St 14 Interpolated AI corrected 3.4 mm". Chips
"3 changed", "18 same". Primary button "Keep r3", secondary "Restore r2".

**6. Export.**
Centered dialog "Export" over a dimmed app. Segmented control "Offsets", "IGES", "STEP",
"DXF", "PDF report" with "STEP" selected. Pickers "Units: mm", "Stations: All 21",
"Include: AI edits". A checklist panel "Before export" with ticks: "All sections
reviewed", "Fairness check passed", "Engineer sign-off outside app". A preview thumbnail
of the hull and a PDF cover page with title block "Harbour Tug HT-24 · r3". Buttons
"Cancel" and primary orange "Export". Small note chip "Draft".

## Launch-screen prompts for the other directions

**Graphite launch.** Photoreal UI mockup of a native macOS desktop app window, 16:10,
2560x1600, flat straight-on. Dark precision CAD style: background #0E1013, panels #16191E,
hairlines #2A2F37, text #E6E8EB, cyan accent #38BDF8, violet #A78BFA for AI activity,
fonts in the style of Inter and JetBrains Mono, thin monochrome line icons, dense layout.
Window titled "MarinaFrame". Left sidebar sections "Runs", "Sheets", "Datasets"; project
picker "Harbour Tug HT-24". Main heading "Recent projects", six cards with a dark-inverted
lines-drawing thumbnail and a small satin-grey 3D hull, chips "Approved", "Running",
"Needs review", "Draft"; names "Survey Launch", "Pilot Boat", "Harbour Tug", "Passenger
Ferry", "Workboat", "Research Vessel". Cyan button "New project". Status bar "Offline ·
Local models ready". Exclude: lorem ipsum, misspelled text, emoji, people, device frames,
neon glow, glassmorphism, gradients on buttons, watermarks.

**Bridge launch.** Photoreal UI mockup of a native macOS desktop app window, 16:10,
2560x1600, flat straight-on. Ship's bridge instrument panel style in night mode:
background #071018, panels #0C1823 with thin bezels #1F3344, text #D7E3EA, sea-green
accent #34D3A6, amber #FFB547 for AI activity, fonts in the style of B612 and B612 Mono,
round instrument gauges, chart-graticule grid lines, large legible readouts, low density.
Window titled "MarinaFrame". Left rail with sections "Runs", "Sheets", "Datasets"; project
picker "Harbour Tug HT-24". Main area "Recent projects" as six instrument tiles, each with
a lines-drawing thumbnail in a chart window, a round confidence gauge and a chip
"Approved", "Running", "Needs review" or "Draft"; names "Survey Launch", "Pilot Boat",
"Harbour Tug", "Passenger Ferry", "Workboat", "Research Vessel". Sea-green button
"New project". Status bar "Offline · Local models ready". Exclude: lorem ipsum, misspelled
text, emoji, people, real ship bridges, photos of the sea, skeuomorphic brass, device
frames, watermarks.

## Next steps

1. Founder picks a direction from the three launch images.
2. Encode the chosen tokens in `styles.css` `:root` and `[data-theme="dark"]`; bundle fonts.
3. Rebuild components in kit order: shell, chips, sidebar, stream, tool cards, scoreboard,
   timeline, then 3D materials. Re-shoot `work/ui-polish/after/` at the same 3 sizes.
