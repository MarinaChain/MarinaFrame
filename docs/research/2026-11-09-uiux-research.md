# MarinaFrame UI/UX research (2026-11-09)

Status: research draft. Scope: web research pass of about 40 minutes.
Purpose: give the UI backlog a base in user practice and in current AI app patterns.
Rule for all of MarinaFrame: every result is a **draft**. The UI never says "approved" or "verified".

Source quality note: most naval sources are vendor pages and forum posts (boatdesign.net, McNeel).
Many forum posts are old (2003-2018). Most AI-pattern sources are product docs or third-party teardowns.
Eng-Tips gave no useful hits for this topic.

---

## 1. How target users work today

### 1.1 Tool landscape

| Tool | Main user | Role in workflow | Notes for MarinaFrame |
|---|---|---|---|
| NURBS hull design tools | Small craft, yacht, repair offices | Hull fairing, live sections and hydrostatics | Sections and hydrostatics update live as the surface changes. Section lists serve fairing, lines/offsets, or hydrostatics. Product-specific references are kept outside the repository. |
| [Maxsurf](https://www.bentley.com/products/maxsurf/) (Bentley) | Design offices, education | Surface model, grid of stations/WL/buttocks, curvature, hydrostatics | Grid is set in Data > Grid Spacing. User sets frame of reference and zero point first ([tutorial](https://worldshipconstruction.blogspot.com/2010/06/maxsurf-tutorial.html)). |
| [DELFTship / FREE!ship](https://www.boatdesign.net/goto/post?id=168990) | Small offices, hobby, students | Subdivision hull, background-image trace | Load scan as background in body plan view, scale from a known dimension, then trace ([DELFTship tutorial](https://www.scribd.com/doc/96304152/Tutorial-01)). |
| [NAPA Designer](https://www.napa.fi/napa-release-2024-1/) | Large yards, class | Hull form, 3D model, class review via OCX | 3D model-based class review is in pilot with classification societies ([DNV](https://dnv.com/news/dnv-damen-and-napa-use-3d-model-based-approval-to-streamline-ship-design-approval-244942)). |
| ShipConstructor/SSI, AVEVA Marine, Cadmatic | Production yards | Detail and production design downstream of the hull | They import the hull surface as STEP/IGES/SAT ([AVEVA Surface Manager](https://docs.aveva.com/bundle/hull-and-outfitting/page/1119906.html)). Surface import often needs a Rhino step ([boatdesign.net](https://www.boatdesign.net/threads/aveva-hull-surface-import.62129/latest)). |
| Ship design and classification rule tools | Yards, class | Structure and rule checks | Optional exports serve third-party tools the customer already owns. Ported calculations run inside MarinaFrame, without an original runtime. |

Result: MarinaFrame does not replace these tools. It feeds them a clean draft fast.
The key export is a STEP surface that opens in Rhino/AVEVA without repair, plus an offsets table.

### 1.2 Core screen conventions users expect

- **Three orthographic views**: profile (side), half-breadth or plan (top), body plan (sections) ([overview](https://eathealthy365.com/using-cad-in-boat-design-software/)).
- **Body plan layout**: aft stations on the left half, forward stations on the right half, centreline in the middle. Users read it as one view.
- **Grid of reference lines**: stations (X), waterlines (Z), buttocks (Y). A point on a station must agree with its waterline and buttock values ([lines-plan explanation](https://www.ukriversguidebook.co.uk/forum/viewtopic.php?p=762772)).
- **Station numbering differs**: ISO 5572 puts station 0 at the AP and 10 (or 100) at the FP ([ISO 5572](https://cdn.standards.iteh.ai/samples/11640/80860b37aa6b43dc803fd431e739eea1/ISO-5572-1987.pdf)). US naval practice uses 20 stations with 0 at the FP ([UFC 4-159-03](https://buildingcriteria2.tpub.com/ufc_4_159_03/ufc_4_159_030048.htm)). The app must read and show the drawing's own convention.
- **Table of offsets**: rows are waterlines and buttocks, columns are stations. Half-breadths from centreline, heights above baseline ([offsets explanation](https://www.boatdesign.net/threads/generating-offsets.67640/latest)). Old tables use feet-inches-eighths, for example "5-2-4" ([boatdesign.net](https://www.boatdesign.net/goto/post?id=949872)). Offsets are usually to outside of shell or planking.
- **Fairness checks**: curvature combs ("porcupines") on sections, zebra stripes, environment maps ([boatdesign.net](https://www.boatdesign.net/threads/how-to-design-in-3d.47744/)). Maxsurf updates curvature live while the user drags ([Maxsurf overview](https://kastenmarine.com/maxsurf/modeler.htm)).
- **Sectional area curve (curve of areas)** and **upright hydrostatics** are standard live checks ([Maxsurf brochure](https://www.scribd.com/doc/257959862/Maxsurf-Brochure)).
- **Hydrostatic report**: table per draft plus plots. Common output formats include PDF, Excel, CSV and XML; product-specific references are kept outside the repository.
- **Tables move to Excel**: Maxsurf supports copy-paste of numeric tables to and from Excel. Users expect this.
- **Shortcuts**: CAD users expect view keys (top/front/side/perspective), zoom-extents, orbit with mouse, and Rhino-style typed commands. No single standard exists across tools.

### 1.3 How they digitise a scanned lines plan today

1. Scan or photograph the drawing. Sometimes stitch several scans ([boatdesign.net](https://www.boatdesign.net/goto/post?id=499980)).
2. Fix paper distortion. Stretch the image to known dimensions ([Model Ship World](https://modelshipworld.com/topic/27443-no-buttocks)).
3. Set grid (stations, waterlines) to match the scan, then scale ([Model Ship World](https://modelshipworld.com/topic/10525-delftship-ship-design-software)).
4. Trace sections over the background image in body plan view.
5. Fair the surface. Add sections where waves appear between stations ([McNeel forum](https://discourse.mcneel.com/t/how-to-create-section-frames-for-a-hull-in-grasshopper/131097)).
6. Cut offsets, compute hydrostatics, export.

Repair yards do this by hand from owner drawings. It is slow and error-prone ([Park & Ham 2024, JCDE](https://api.crossref.org/works/10.1093/JCDE/QWAE099)).
Data preparation often takes longer than surface modelling ([Pérez-Arribas et al.](https://dcain.etsin.upm.es/~leonardo/papers/cad06.pdf)).

### 1.4 What users complain about

| Pain | Evidence | MarinaFrame response |
|---|---|---|
| Tracing a scan is slow and manual | [JCDE 2024](https://api.crossref.org/works/10.1093/JCDE/QWAE099), [boatdesign.net](https://www.boatdesign.net/goto/post?id=499980) | AI does the first trace; human fixes only flagged sections. |
| Traced hull is not fair | "Tracing won't give a fair hull" theme ([boatdesign.net](https://www.boatdesign.net/threads/using-3dboat-design-software-on-a-mac-w-wine.34314/previous)) | Show fairness (curvature comb) and drawing deviation together. |
| Too many control points make surfaces unfair | [boatdesign.net](https://www.boatdesign.net/posts/121138) | Keep control-point count low by default. Do not expose CVs in v1. |
| Old drawings are distorted or "illustrative" | [McNeel forum](https://discourse.mcneel.com/t/3d-fairing-of-table-of-offsets/80812), [Model Ship World](https://modelshipworld.com/topic/27443-no-buttocks) | Calibrate per view. Show residuals in mm. Mark "drawing vs offsets table" conflicts. |
| Real hulls are asymmetric; drawings show design intent | [Zodiac scan case](https://3dsystems.com/learning-center/case-studies/turning-tall-ship-3d-scan-data-cad-model-3d-systems-geomagic) | State in report: draft reflects drawing, not as-built hull. |
| Export to production CAD needs repair | [boatdesign.net](https://www.boatdesign.net/posts/902836/), [boatdesign.net](https://www.boatdesign.net/threads/aveva-hull-surface-import.62129/latest) | Test STEP in Rhino/AVEVA. Show tolerance and surface count on Export. |
| Learning curve of surface tools | [boatdesign.net](https://www.boatdesign.net/posts/956562) | Reviewer edits points on 2D sections, not NURBS nets. |

---

## 2. AI-era app patterns

### 2.1 Pattern catalogue

| Pattern | Reference product | What it does | Fit for MarinaFrame |
|---|---|---|---|
| Canvas beside chat | [ChatGPT canvas](https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt), Claude artifacts | Work object is primary; chat is secondary | High. The hull and drawing are the canvas. The agent log is a side rail. |
| Select a region, then prompt | [ChatGPT canvas](https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt), [Figma Make point-and-edit](https://help.figma.com/hc/en-us/articles/31304485164695) | Edit is scoped to the selection | High. Box a region on the scan or pick a station: "re-trace this", "this is a knuckle". |
| Inpainting with variations | [Firefly generative fill](https://www.adobe.com/learn/firefly/web/add-content-generative-fill) | Paint area, prompt, get 3 variants in a filmstrip, Keep one | Medium. Offer 2-3 alternative traces for a hard section; user keeps one. |
| Plan first, then execute | [Claude Code plan mode](https://code.claude.com/docs/en/checkpointing), Shape of AI "Action plan" ([shapeof.ai](https://www.shapeof.ai/)) | User sees steps before run | High. Show run plan: calibrate, identify lines, trace, fit, check. |
| Visible step list and log | [agent UX consensus](https://jacar.es/en/ux-for-agents-first-design-consensus/), Shape of AI "Stream of thought" | Progress prevents "is it hung?" | High. Step list with current step, elapsed time, and a short "now doing" line. |
| Interrupt and steer mid-run | Claude Code Esc and queued messages ([guide](https://www.memorylake.ai/en/blogs/claude-code-queue-messages)), Shape of AI "Controls" | User redirects without restart | High. Pause, add a hint ("station 0 is at the FP"), resume. |
| Review diffs, keep/undo per change | [Cursor review](https://forum.cursor.com/t/per-change-keep-undo-buttons-missing-after-agent-edits-only-undo-all-available/158983) | Accept or reject per file or hunk | High. Per-section accept/reject. Forum reports show users get angry when per-change control goes missing. |
| Checkpoints and rewind | [Claude Code checkpoints](https://code.claude.com/docs/en/checkpointing), [Cursor](https://stevekinney.com/courses/ai-development/cursor-checkpoints) | Snapshot before each agent turn | High. Version timeline per run; restore any snapshot. |
| Inline citations with hover preview | [Perplexity teardown](https://ai-design-patterns.pages.dev/teardowns/perplexity/citations) | Numbered marker opens source card | High. Each value links to its evidence: a crop of the scan or a table cell. |
| Disclosure, caveat, footprints | [Shape of AI trust builders](https://www.shapeof.ai/) | Mark AI content; trace steps | High. Mark every AI-made item; keep an audit trail. |
| Confidence only with action | [trust patterns](https://ai-design-patterns.pages.dev/patterns/trust) | No decorative trust badges | High. Low confidence must link to "review this". |
| Editable output, not a dead mesh | [Zoo Text-to-CAD](https://docs.zoo.dev/research/introducing-text-to-cad) | Output is an editable feature tree (KCL) | High. Output is editable sections and offsets, not only a mesh. |
| Command palette | [Linear Cmd+K](https://blakecrosley.com/guides/design/linear) | Search any action by keyboard | High. Power users want keyboard for "go to station 7", "export offsets". |
| Draft mode / cost estimate | Shape of AI "Draft mode", "Cost estimates" | Cheap preview before full run | Medium. Show model time and cost estimate before run. |

### 2.2 Lessons from failures in AI tools

- Cursor users report that auto-apply without review breaks trust ([forum](https://forum.cursor.com/t/agent-mode-no-longer-shows-review-accept-interface-and-applies-file-changes-automatically-after-recent-update/152581.md)). Never auto-apply AI section edits to the reviewed state.
- Figma Make users report the selection is lost when the prompt is sent ([forum](https://forum.figma.com/report-a-problem-6/selected-element-not-passed-to-figma-make-ai-prompt-51238)). Show the selection as a chip inside the prompt box, so the user sees it goes with the prompt.
- Cursor checkpoint rollback sometimes left files changed ([guide](https://www.rapidevelopers.com/md/cursor-tutorial/how-to-revert-partial-code-merges-after-accepting-incomplete-cursor-ai-suggestions)). Restore must be complete and must show what changed.
- Fake or unbacked citations are worse than none ([trust article](https://mspk.substack.com/p/designing-for-confident-wrong-answers)). Only link evidence that exists in the run data.
- Put human review only where a mistake is expensive ([agent UX guide](https://hatchworks.com/blog/ai-agents/agent-ux-patterns/)). Do not ask for approval at every step.

### 2.3 Zoo Design Studio (KittyCAD/modeling-app, MIT)

Scope: UX study of the open-source app ([repo](https://github.com/KittyCAD/modeling-app), MIT) and its docs.
The geometry engine (the 3D view is a video stream over WebSockets) and the Text-to-CAD model are closed cloud services.
We adopt ideas only. We do not use those services.
The older [text-to-cad-ui](https://github.com/KittyCAD/text-to-cad-ui) (SvelteKit, MIT) has been archived and read-only since Jan 2026. It is only a small API demo.

| Topic | How Zoo does it | Evidence |
|---|---|---|
| Single source of truth | All point-and-click actions write KCL code. The README says GUI actions are "actions performed on this code representation". | [README](https://github.com/KittyCAD/modeling-app) |
| Code and 3D in sync | Each AST node keeps a `source_range`. Selection in the scene, code editor or feature tree resolves to the same reference. | [kcl-lib Metadata](https://docs.rs/kcl-lib/0.2.75/src/kcl_lib/execution/mod.rs.html), `src/components/SelectionReferencesPopover.tsx` |
| Selection as prompt context | A popover lists resolved selection references. The user can remove one or copy its KCL reference. | `SelectionReferencesPopover.tsx` |
| Point-and-click edits | The command bar opens a dialog. Selection fields accept picks from scene, code or tree. Submit writes code. On a validation error the draft stays open for a fix. | [Command bar docs](https://zoo.dev/docs/zoo-design-studio/features/workspace/command-bar) |
| Review before write | The command dialog has a collapsible "Code changes" diff: "Current file" vs "Proposed file" (CodeMirror MergeView). | `src/components/CommandBar/CodemodReviewDiff.tsx`, `CodeDiffView.tsx` |
| Feature tree | Ordered list of operations plus a Bodies pane. Click goes to the KCL source. Double-click reopens the parameter dialog. Some items are view-only. | [Feature tree docs](https://zoo.dev/docs/zoo-design-studio/features/workspace/feature-tree) |
| Prompt-to-edit a region | "Zoodle": draw marks on the viewport, send the image with a prompt. The marks show where; the text says what. | [Edit parts docs](https://zoo.dev/docs/zoo-design-studio/features/ml-ai/zoodle/edit-parts) |
| AI edit review | Zookeeper agent with queue and steer while it runs. AI edits are revertible with undo/redo, compare with previous state, and one history for manual and AI edits. Docs tell users to check geometry, KCL and parameters after each edit. | [ML/AI docs](https://zoo.dev/docs/zoo-design-studio/features/ml-ai) |
| Project rules for the agent | An `AGENTS.md` per project holds units, naming and modelling conventions. | [ML/AI docs](https://zoo.dev/docs/zoo-design-studio/features/ml-ai) |

Gaps: the docs do not show a per-hunk accept/reject step for Zookeeper edits. The flow is apply first, then compare or undo. MarinaFrame needs a stricter flow, because a human must sign off each section.

MarinaFrame takeaways:
1. Make one editable record (sections + offsets) the source of truth. Drawing pane, 3D pane, section strip and offsets table are views of it. A selection in one view highlights the same station in all views.
2. Every human click-edit and every AI edit becomes a typed change in that record. Show it as a before/after diff (values and section overlay) in a collapsible "Changes" panel before it is applied.
3. Add mark-on-drawing prompts ("Zoodle"-style): the user draws on the scan or the 3D view, and the marks go with the prompt as a chip.
4. Use one undo/version history for manual and AI edits. Add a "compare with previous" toggle in the drawing and 3D panes.
5. Add per-vessel conventions (units, station direction, LPP, offsets side) in one place. The agent reads them on every run.

---

## 3. Decisions for MarinaFrame

### 3.1 Keep the naval architect's conventions

- Use the words: station, waterline, buttock, half-breadth, body plan, profile, offsets, sectional area curve, LPP, AP, FP, baseline, DWL. Do not rename them.
- Body plan: aft half left, forward half right. Profile: bow to the right unless the drawing differs (make it a setting).
- Offsets table: stations as columns; waterlines and buttocks as rows. Units switch: mm, m, ft-in-eighths.
- Keep the drawing's station numbering and direction. Show the convention in the inspector ("St 0 = AP, 10 stations").
- Fairness: curvature comb on the selected section, on by default in review. Zebra in 3D as an option.
- Hydrostatics table per draft, plus curves. Copy table to clipboard as tab-separated text for Excel.
- Exports by name the users know: STEP (surface), IGES (optional later), STL, offsets CSV, DXF lines (later), PDF report.

### 3.2 Where AI-era patterns make it faster

- **Run live screen** = canvas + rail. Drawing pane and 3D pane are primary. Agent rail shows the plan, current step, and a short log.
- **Steer**: one input under the step list. User can type a hint at any time. Hint queues to the next step boundary.
- **Region prompt**: draw a box on the scan or pick sections in the strip, then type. The selection shows as a chip.
- **Section strip** = review queue. Each station is a thumbnail with a state: AI guess, needs review, edited by human, conflict. Sort by worst first.
- **Per-section accept/reject**, plus "accept all above threshold" for speed. Keep a reviewed count: "14 of 21 reviewed".
- **Evidence links**: each point or offset value opens the scan crop it came from (Perplexity-style hover card).
- **Overlay diff**: show AI trace over the scan in one color, human edit in another, and the deviation in mm.
- **Version timeline**: auto snapshot before each agent step and each human edit batch. Restore with a preview.
- **Command palette** (Cmd/Ctrl+K): go to station, toggle view, run check, export.

### 3.3 What to avoid

- Do not use "approved", "verified", "certified", "class-ready", or green check marks for geometry. Use "Draft", "Reviewed by <name>", "Needs review".
- Do not show percent confidence alone. Show the cause ("line crosses station 6", "table and drawing differ by 12 mm") and the action.
- Do not hide the source scan after AI fitting. The scan must stay visible under the trace.
- Do not auto-apply AI re-traces to sections the human already edited. Human edits win; AI proposes.
- Do not expose NURBS control nets in v1. Users fight too many control points.
- Do not make chat the main screen. Chat-first agent UX fails for work objects ([HatchWorks](https://hatchworks.com/?p=34963)).
- Do not block the user while the agent runs. They can review finished sections while later steps run.
- Do not guess station direction silently. Ask once if the title block does not say.

### 3.4 Screen notes

| Screen | Must have |
|---|---|
| Home | Recent drafts with status chips (Running, Needs review N, Draft ready). Empty state: "Drop a lines drawing" plus a sample vessel to try. |
| Intake | Per-sheet view tag (body plan / half-breadth / profile / offsets table). Calibration: click two known points, enter distance. Units and station convention. Run plan preview with time estimate. |
| Run (live/review) | Drawing pane (scan + overlay), 3D pane, section strip, inspector, agent rail with steer input. Pause/Resume. Keyboard: J/K next/previous section, A accept, R reject, E edit. |
| Export | File list with formats, units, tolerance. "Draft" watermark in PDF. Pre-export check list with open issues count. Never a "certified" export. |
| Queue | Batch of drawings, state per job, retry, cost/time per job. |
| Settings | Units, station convention default, model/provider, export defaults, keyboard map. |

---

## 4. Top 10 UI findings for the backlog (ranked)

1. Run screen: section strip as review queue, sorted worst-first, each station tagged AI guess / Needs review / Human-edited / Conflict, with "N of M reviewed" counter.
2. Per-section Accept / Reject / Edit with keyboard (J/K/A/R/E); never auto-apply AI re-traces over human edits.
3. Drawing pane overlay: scan always visible under AI trace (one color) and human edit (second color), with point deviation in mm on hover.
4. Evidence hover card: click any point or offset value to see the scan crop or table cell it came from (numbered markers, Perplexity-style).
5. Agent rail: visible run plan with current step, elapsed time, short "now doing" line, Pause/Resume, and a steer input that queues a hint to the next step.
6. Region select-to-prompt: box or freehand marks on scan/3D, or multi-select stations, selection shown as a chip in the prompt box, optional 2-3 alternative traces to keep one.
7. Intake calibration and conventions panel: two-point scale per sheet, units (mm/m/ft-in-eighths), station 0 at AP or FP, station count, bow direction; ask if unknown.
8. Inspector shows naval checks next to the section: curvature comb on by default, sectional area curve with the selected station marked, upright hydrostatics at DWL.
9. One source of truth and one history: drawing, 3D, strip and offsets table are linked views with cross-highlighting. Manual and AI edits share one undo/version timeline with a before/after "Changes" diff and a "compare with previous" toggle (Zoo Design Studio pattern).
10. Draft-only language and marks everywhere: "Draft" badge, PDF watermark, "Reviewed by", open-issue count on Export; no "approved/verified" words or green checks; Cmd/Ctrl+K palette for go-to-station, views, checks, exports.
