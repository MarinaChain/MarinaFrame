# MarinaFrame app design, lane A: storyboard and information architecture

Date 2026-11-08. Base `continue/v0.5`. Branch `design-a-storyboard`. Design only; no code change.
Inputs: `docs/APP_SPEC.md`, `app/ui/index.html`, `app/ui/js/app.js`, UI screenshots in main
`work/ui-polish/after/`, `docs/plans/2026-11-08-whole-vessel-design.md` (phases: read the vessel,
first hull, match views), `docs/LLM_INVESTIGATOR.md`, `docs/CONTINUATION_STATUS.md`.
Resume point: section 5 (open questions for the founder).

## 0. Summary

The current app is a run viewer: one run, one source page, one inspector. The user thinks in
**vessels and drawing sets**, not in run specs. This design makes the vessel the centre of the app,
makes the live run a screen you watch (the agent reads, measures, builds; the hull grows), and adds
the steps after the draft: review, compare versions, export, next drawing.

Fixed product rules that every frame keeps:

- Every result is a draft. `engineering_approved` is always false. Say it once, in the export and
  in the first-run onboarding, not on every screen.
- The AI does not stop on bad data. Problems are warnings and open guesses, not dead ends.
- Text follows the APP_SPEC writing rules (plain verbs, one fact in one place, no slogans).

## 1. Storyboard (18 frames)

Notation: **Sees** / **Does** / **App and agent** / **Beat** (what the user should feel).

### F1. First launch
- **Sees:** A calm window with the mark, one sentence ("Turn lines drawings into a 3D hull draft
  you can check"), and three short setup checks: CAD worker, AI key, runs folder. Each check is a
  row with a status chip.
- **Does:** Clicks "Check setup".
- **App:** Runs the three checks locally. No account, no network except the AI provider later.
- **Beat:** "This is a tool, not a demo." Quiet confidence.

### F2. Setup: no key, or worker missing
- **Sees:** AI key row "Not found" (amber) with two choices: "Add key file…" (path
  `~/.config/marinaframe/opencode-go-keys.txt`) or "Continue without AI". Worker row red if
  Python/CadQuery is missing, with "Choose Python…" and the auto-detected suggestions (keep the
  current suggestion chips).
- **Does:** Adds a key, or continues without AI.
- **App:** Without a key, runs use the deterministic draft. One line says so; the same fact
  appears later only as the run's mode chip ("No AI").
- **Beat:** Not blocked. The user knows exactly what they lose ("no AI reading; code-only draft").

### F3. Home, empty
- **Sees:** Empty projects area with one large drop target: "Drop a drawing set (PDF, PNG, TIFF)
  or a folder". Below: "Try a sample vessel" (opens a bundled sample project read-only).
- **Does:** Drops a PDF with 3 pages, or opens the sample.
- **Beat:** One obvious next step.

### F4. Intake: sort the sheets
- **Sees:** A sheet tray. Each page is a thumbnail card. Within 1-3 s, code (`survey_sheet`)
  marks view regions on each card with labels: Body plan, Half-breadth, Profile, Title block,
  Other. A form at the right asks for the vessel name (prefilled from the title block when read)
  and optional known particulars (LOA, Lpp, beam, depth, draft, scale).
- **Does:** Drags a wrong label onto the right region, deletes a cover page, types "Survey
  launch 24 m". Clicks "Start reading".
- **App:** Writes the run spec itself (the user never sees a spec file). Assigns `view_id`s.
  A low-resolution scan gets an amber chip "Scan 150 dpi: lines may be read less exactly".
- **Beat:** Control before the machine starts. The set is "mine".

### F5. Live run, phase 1: reading the sheets
- **Sees:** The Live screen (wireframe 3.3). The drawing pane shows the sheet; the region the agent
  is looking at now is outlined in accent and the outline moves as the agent asks for crops. The
  narrative pane writes short plain lines: "Found 3 views: body plan, half-breadth, profile",
  "Read scale 1:50 from the title block", "Stations: 21, spacing 1.2 m".
- **Does:** Watches. May scroll the narrative or pause.
- **App:** Phase 1 tools: `describe_views`, `propose_sheet_setup`, `describe_vessel`,
  `measure_description`. Particulars fill a card field by field; each value shows its source
  (title block, measured, AI read).
- **Beat:** "It is reading the drawing the way I would." Curiosity.

### F6. Live run, phase 1 conflict
- **Sees:** A particulars card row turns amber: "Beam: body plan 7.20 m, half-breadth 7.39 m
  (2.6 %)". The narrative says which value it used and why.
- **Does:** Nothing (it continues), or clicks the row to see both measurements on the drawing.
- **App:** Warning only (whole-vessel design section 3). The row is added to the review list.
- **Beat:** Trust through honesty: it shows disagreement instead of hiding it.

### F7. Live run, phase 2: first hull appears
- **Sees:** In the 3D pane, station curves draw in one by one at their x positions (traced = solid,
  filled = lighter), then the surface lofts between them in one short animation. The drawing pane
  shows the traced ink in accent over the sheet. A fit gauge appears: "Fit 0.81".
- **App:** Anchored form fit, `build_draft`, render. No model call.
- **Beat:** The payoff moment. The ship takes shape. This is the screen people screenshot.

### F8. Live run, phase 3: matching the views
- **Sees:** A revision ladder ("r1 0.81 → r2 0.86 → r3 0.86 rejected → r4 0.90"). Each model
  edit appears in the narrative as a card: target ("station 9, z 1-3 m"), what it changed, result
  "Kept: fit +0.04" or "Not kept: half-breadth WL2 worse by 0.4 m". On the 3D hull, the edited
  region flashes; residual colours (green/orange/red) show on the overlay of the active view.
- **Does:** May click any revision in the ladder to look at it (does not stop the run).
- **App:** Phase 3 keep rule; best revision is always the one delivered.
- **Beat:** Watching a colleague work. Rejected edits make the system look careful, not broken.

### F9. Live run, provider offline or key rejected
- **Sees:** An amber strip at the top of the narrative: "AI provider not reachable. Continuing with
  the code-only draft." The ladder continues with code revisions. A "Retry AI" button.
- **App:** Falls back to the deterministic draft; the run is not failed. When the network returns,
  "Retry AI" resumes phase 3 from the best revision.
- **Beat:** Resilience. No lost work.

### F10. Run failed or stopped
- **Sees:** Red status chip "Failed" with one sentence cause in plain words ("The CAD worker
  stopped: CadQuery not found") and two actions: "Fix setup" (opens F2 row) and "Resume". Last good
  revision stays visible and exportable if one exists.
- **Beat:** Clear cause, clear next step. Never a stack trace (that is in Evidence).

### F11. Draft ready: review summary
- **Sees:** The run ends; the Live screen becomes the Review screen in place (same panes, no page
  jump). A "What to check" list replaces the narrative, sorted by impact: open guesses, AI-authored
  sections, worst residuals, particulars conflicts. Header: "Draft r4 · fit 0.90 · 3 items to
  check". A notification is sent if the window is in the background.
- **Does:** Clicks the first item.
- **Beat:** From watching to working. The list is short and finite.

### F12. Review a low-confidence section
- **Sees:** Drawing zooms to the station; candidate lines drawn as today (chosen solid, others
  grey, guess dashed amber). The inspector shows the reason ("2 lines found; took the
  best-supported one, score 0.62") and actions: "Confirm this line", "Use another line", "Edit
  points…" (P1), "Ask the agent to look again" with a short note field.
- **Does:** Picks the inner line.
- **App:** `choose_line`, then rebuild and re-check in the background; a new revision r5 joins
  the ladder marked "You".
- **Beat:** Expert in charge; corrections are cheap.

### F13. Cross-view check
- **Sees:** View switcher above the drawing: Body / Half-breadth / Profile. Each shows the hull cut
  over the ink with residual colour, and the worst ranges listed. Hover gives the number in metres
  and % of B/2.
- **Does:** Steps through the views; flags one range "Check on paper" (a note kept in the report).
- **Beat:** The engineer sees the same evidence they would check by hand, in one place.

### F14. Body-plan-only set (degraded input)
- **Sees:** Half-breadth and Profile tabs are present but dimmed with "Not in this drawing set; shown
  from the AI reading". Particulars from AI read are marked so.
- **Beat:** Honest about what was measured vs inferred, without blocking.

### F15. Compare versions
- **Sees:** Two revisions or two runs side by side (wireframe 3.5): 3D hulls overlaid (A grey,
  B accent) with a difference heat map, a table of particulars and per-station RMS deltas, and
  which sections changed and by whom (agent / you).
- **Does:** Chooses "Use B as the draft" (sets the vessel's current draft).
- **Beat:** Decision with evidence.

### F16. Export and handoff
- **Sees:** Export sheet: checkboxes for STEP (hull draft), STL, offsets table (CSV), review report
  (PDF: particulars, sources per section, open items, checks, the "draft, not approved" line), and
  the package (zip with all plus the drawing set hashes). File names carry vessel, revision and
  "DRAFT".
- **Does:** Exports to a folder; opens it in Finder.
- **App:** Writes files; adds an "Exported r5" line to the vessel history.
- **Beat:** Something to hand to a colleague today.

### F17. Next drawing
- **Sees:** Back on the project: the vessel card shows "Draft r5 exported". The drop target is
  still there; a queue strip shows other vessels "Reading…", "Draft ready", "Waiting".
- **Does:** Drops the next 6 drawing sets at once.
- **App:** Creates one vessel per set (asks only when it cannot split them), runs up to N in
  parallel (setting), notifies on each "Draft ready".
- **Beat:** Leverage: ground covered across many drawings.

### F18. Returning user, mid-queue
- **Sees:** Home with a "Needs you" row on top (drafts ready to review, failed runs), then
  projects by last activity. Running vessels show a live mini-hull thumbnail and phase.
- **Beat:** The app tells them where their attention pays most.

## 2. Information architecture

### 2.1 Objects

| Object | What it is | Holds | Backend today |
|---|---|---|---|
| Project | A job or client folder (e.g. "Yard X tender, Nov") | vessels, notes | new (folder + `project.json`) |
| Vessel | One hull to model | name, particulars, sheet set, runs, current draft | new; today a task's `vessel_id` |
| Sheet | One drawing page (PDF page or image) | file, hash, dpi, view regions | today one `source_page` per task |
| View | A region on a sheet with a kind (body, half-breadth, profile, title) | calibration, halves | whole-vessel `views[]` |
| Run | One investigator execution over the vessel's sheets | mode (AI / code-only), status, phases, events, cost | today a task folder |
| Revision | One table/build state inside a run (r1, r2…) | fit, scoreboard, author (code / agent / you) | `vessel.json` revisions |
| Draft | The revision the user marks as current for the vessel | pointer | new |
| Artifact | A file from a revision | STEP, STL, renders, overlays, offsets CSV, report | task folder files |

Rules: a vessel has many runs; a run has many revisions; exactly one revision per vessel is the
current draft (default: the best revision of the latest finished run). User corrections create a
new revision in the same run. "Run again" creates a new run on the same sheets.

### 2.2 Navigation model

- **Left rail (global, narrow):** Home, Queue, Settings. Collapsible.
- **Breadcrumb in the title bar:** Project › Vessel › Run 2 · r5. Each part is a menu.
- **Vessel tabs (the main working level):** Sheets | Run (Live or Review, same screen) | Compare |
  Export | History.
- **Command palette (⌘K):** open vessel, jump to station ("st 9"), switch view, export.
- Keep the current shortcuts (⌘1/2/3 layout, arrows for sections, ⌘N new, ⌘, settings).

### 2.3 Screen list

1. Welcome and setup check (F1, F2)
2. Home: projects and "Needs you" (F3, F17, F18)
3. Project overview: vessel cards with status, mini-hull, current draft
4. Intake / Sheets: sheet tray, view-region labelling, particulars form (F4)
5. Run screen, Live mode (F5-F10)
6. Run screen, Review mode: drawing, 3D, section strip, "What to check", inspector (F11-F14)
7. Compare (F15)
8. Export sheet (F16)
9. Vessel history: runs, revisions, exports, cost
10. Queue: all running and waiting runs across projects (F17)
11. Details drawer inside the Run screen: Checks, Model calls, Evidence (today's tabs)
12. Settings: AI, CAD worker, storage, parallel runs, appearance, notices

## 3. Wireframes

### 3.1 Home

```text
+--+---------------------------------------------------------------+
|H | Needs you                                                     |
|Q | [Survey launch 24m  Draft r5 · 3 to check]  [Tug 32m  Failed] |
|S |---------------------------------------------------------------|
|  | Projects                                   [ + New project ]  |
|  | +-------------+ +-------------+ +-------------+               |
|  | | Yard X Nov  | | Sample      | |  Drop a     |               |
|  | | 4 vessels   | | 1 vessel    | |  drawing    |               |
|  | | 2 ready     | | read-only   | |  set here   |               |
|  | +-------------+ +-------------+ +-------------+               |
+--+---------------------------------------------------------------+
```

### 3.2 Intake

```text
Yard X Nov › New vessel                                [Start reading]
+---------------------------------------------+--------------------+
| p1 [Body plan][Title]  p2 [Half-breadth]    | Vessel name        |
| +---------+   +---------+   +---------+     | [Survey launch 24m]|
| |  ink    |   |  ink    |   | cover   |     | Known (optional)   |
| | [body]  |   | [plan]  |   | (skip)  |     | LOA [24.0] B [7.2] |
| +---------+   +---------+   +---------+     | Scale [1:50]       |
| p3 [Profile]  ! Scan 150 dpi                | Mode  [AI] No AI   |
+---------------------------------------------+--------------------+
```

### 3.3 Run screen, Live mode

```text
Yard X › Survey launch 24m › Run 1                Reading · 3 of 3 phases   [Pause] [Stop]
+-------------------------------+----------------------------+--------------------------+
| [Body][Half-breadth][Profile] | 3D                         | Agent                    |
|                               |                            | Phase 3: matching views  |
|   sheet with the crop the     |   hull growing; edited     | 13:29 Read scale 1:50    |
|   agent looks at outlined;    |   region flashes; station  | 13:30 Built first hull   |
|   traced ink in accent;       |   planes thin              | +----------------------+ |
|   residual colours            |                            | | Edit st 9, z 1-3 m   | |
|                               |                            | | Kept: fit +0.04      | |
|                               |                            | +----------------------+ |
+-------------------------------+----------------------------+ Particulars (card)       |
| r1 .81 > r2 .86 > r3 x > r4 .90   fit ▁▃▅▆  · 14 requests · $0.03  | Beam ! 2.6 % conflict |
+-------------------------------------------------------------+--------------------------+
```

The bottom bar is the revision ladder (clickable) with the fit sparkline and running cost.
Cost is shown, small; accuracy is the headline (founder priority 2026-11-08 22:05).

### 3.4 Run screen, Review mode

Same frame as 3.3. Changes: the Agent column becomes "What to check" (ranked list, each item
opens the section or view); the section strip appears under the panes (keep today's tiles with
source labels and amber dashed guesses); the inspector content for the selected item opens in the
right column under the list; Checks / Model calls / Evidence move to a bottom drawer (⌘J).

### 3.5 Compare

```text
Compare  [Run 1 r4 ▾]  vs  [Run 1 r5 (You) ▾]                       [Use r5 as draft]
+----------------------------------+--------------------------------------------+
| 3D overlay A grey / B accent     | Particulars    A       B       Δ           |
| difference heat map on B         | Beam         7.20    7.20    0           |
|                                  | Volume m3    212     208    -1.9 %       |
|                                  | Station RMS  st9 0.41 → 0.08 (You)        |
+----------------------------------+--------------------------------------------+
| Body plan: A and B cuts over the ink, side by side per station                |
+-------------------------------------------------------------------------------+
```

## 4. Screen inventory

| # | Screen | Priority | Why | Backend need beyond today |
|---|---|---|---|---|
| 1 | Run screen, Live mode | P0 | The founder's core ask: watch the agent and the ship | event stream with phase, crop box, revision, fit; narrative text from decisions |
| 2 | Run screen, Review mode | P0 | Where the expert's time goes | "What to check" ranking; revision per correction |
| 3 | Intake / Sheets (multi-page, view labels) | P0 | Replaces "Choose run spec…" | spec writer from files; PDF page render; `survey_sheet` preview |
| 4 | Home with "Needs you" | P0 | Many drawings, one place | project/vessel listing |
| 5 | Export sheet (STEP, STL, CSV, report) | P0 | Handoff is the value | offsets CSV, report PDF |
| 6 | Welcome and setup check, no-key path | P0 | First-run success | setup status command |
| 7 | Settings (simplified) | P0 | Exists; trim developer fields | none |
| 8 | Failure and offline states in Run | P0 | Trust | fallback event, retry action |
| 9 | Project overview | P1 | Grouping for many vessels | project files |
| 10 | Compare | P1 | Choose between revisions/runs | per-revision STL and scoreboard |
| 11 | Queue (parallel runs) | P1 | Ground covered | run scheduler, parallel limit |
| 12 | Cross-view overlays (half-breadth, profile) | P1 | Depends on phase 3 overlays landing | plan/profile overlay images |
| 13 | Details drawer: Checks, Model calls, Evidence | P1 | Exists as tabs; move, keep | none |
| 14 | Vessel history | P2 | Audit of runs, exports, cost | aggregate view |
| 15 | Edit points on a section | P2 | Direct geometry edits by the user | operator `edit_table` |
| 16 | "Ask the agent to look again" with note | P2 | Steer the agent | operator note into the loop |
| 17 | Sample vessel project | P2 | Onboarding without own drawings | bundled licensed-clean sample |

## 5. Current single-view UI: what is wrong, what to keep

### Wrong

1. **Run is the top object.** The sidebar lists runs ("Pilot boat, lines plan", "Survey launch,
   body plan"). The user owns vessels and drawing sets; runs are attempts.
2. **"Choose run spec…".** The entry point asks for a `.json/.toml/.yaml` file. A naval architect
   has a PDF. "Recent" and "Browse a dataset" are developer affordances.
3. **One source page.** `TaskView.source_page` is a single image. The whole-vessel design needs
   body, half-breadth and profile views across several pages.
4. **No live story.** The timeline shows four terse lines ("Read 3 sections", "Built a draft");
   model reasoning is a collapsed list inside the "Model calls" tab. Nothing moves on the drawing
   or the 3D while the agent works. The founder's "watch it think" is not met.
5. **3D shows boxes, not a hull taking shape.** Section planes are large translucent boxes that
   cover the hull; no growth, no residual colour, no link to which edit changed what.
6. **Status said three times.** "Draft" is in the title chip, the draft banner and the status bar;
   "AI corrected" is in the header, the sources row and the tile. Two banners plus a sources row
   take about 100 px above the panes at 1280×800.
7. **No end of the job.** No export, no report, no compare, no "next drawing". The app stops at
   "look at it".
8. **Developer settings in front.** "Worker Python" path and "Datasets" in the sidebar belong in an
   advanced section; the setup check should find them.
9. **Inspector does two jobs.** The selected section's choices and the run's tabs share one
   column; at 1280×800 the candidate list is cut off by the tab bar.

### Keep

- Drawing and 3D side by side with linked section selection; the ⌘1/2/3 layouts and the splitter.
- Candidate overlays with plain-language labels and reasons; "Confirm" / "Use instead" actions.
- Source labels (Traced, Interpolated, AI corrected, AI inferred) and amber dashed guess styling.
- Section strip tiles with a tiny curve thumbnail (move under Review mode).
- The anti-slop writing rules and status vocabulary (Running, Draft, Needs review, Failed).
- Dismissible notices stored by the backend; light and dark themes; brand colour.
- The adapter layer (`invoke`, `onTaskChanged`) so desktop and web share the UI.
- The Checks, Model calls and Evidence content (moved into a drawer, not deleted).
- Settings suggestion chips for detected paths (reuse in the setup check).

## 6. Open questions for the founder

1. Is "Project" needed in v1, or is a flat list of vessels enough (P1 project overview)?
2. Report PDF content and branding: does a shipyard expect its own template?
3. Parallel runs default (2?) and whether the queue may spend AI cost without a per-run click.
4. Should the user's line choice during a live run pause the agent, or queue until the run ends?
   (Proposal: queue; edits apply to the best revision after the run.)

## 7. Checks for this document

- 18 frames cover: onboarding (F1-F2), empty (F3), set intake (F4), live run (F5-F8), offline and
  no key (F2, F9), error (F10), low confidence (F12, F14), review (F11-F13), compare (F15), export
  (F16), next drawing (F17-F18).
- Every P0 screen maps to at least one frame. No frame claims engineering approval.
