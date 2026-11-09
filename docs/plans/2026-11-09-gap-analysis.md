# MarinaFrame: vision and gap analysis (2026-11-09)

Owner: CEO/PM (Claude, for the founder). Read with `docs/STRATEGY_2026Q4.md`,
`docs/plans/2026-11-09-whole-vessel-scope.md` and `docs/CONTINUATION_STATUS.md`.
All numbers below are development results unless the row says otherwise. Every output is a draft;
`engineering_approved` is always false.

## 1. Vision

**One line.** Drop a ship's drawing set, watch the AI read it and the vessel take shape, check the
few places that need an expert in minutes, and hand off a labelled 3D draft today; then do the
next fifty.

**For whom.** Ship-repair yards, owners' technical departments and naval architecture offices that
hold old 2D drawings (paper scans, PDFs, dead CAD) and need a usable 3D model for repair planning,
conversions, class work and digital twins. Today a person rebuilds that model by hand in weeks.

**What we sell.** Speed and coverage with honest accuracy:
- **The AI fills the gaps.** Missing or bad data does not stop a run. Every value carries its
  source label (traced from ink, read by the AI, or guessed) so the expert checks only the guesses.
- **Measured accuracy.** We publish error figures against true CAD. Nobody in this market does.
- **Feeds the tools the user already has.** STEP, offsets, hydrostatics and a review report that
  open in Rhino, Maxsurf, NAPA or AVEVA. We do not replace those tools.
- **Local and private.** A desktop app; the customer's drawings stay on their machine (only the
  model calls leave it).
- **Whole vessel, then the ship's life.** Hull first, then decks, superstructure, appendages and
  structure; later thickness gauging, wastage against class rules and drydock work packages.

**Model strategy (founder, 2026-11-09, revised).** The happy path uses **Claude Sonnet 5.5**, called through the Claude subscription (never through OpenCode Go). Reason: on the hardest reading task we have (the 1886 Balclutha body plan) Sonnet 5.5, Opus 5.5 and GPT-6 Astra pass the fixed rule, while DeepSeek V4.1 Flash and Crouton Alpha Free fail; open models are expected to reach today's closed-model level in 2-3 months. So we develop the product and close the gaps with Sonnet 5.5 now, keep the harness model-agnostic (a model setting, receipts per model), and re-test the open models (DeepSeek, Crouton and successors) on the same frozen benchmarks as they improve.

**Founder rules that shape it.** Accuracy and coverage over model cost; the AI writes geometry and
fills gaps; happy path first (builds do not fail on bad data); a person signs a draft off as "usable
as a starting model"; engineering approval stays outside the app.

## 2. Gap analysis: MarinaFrame against Forge Shipyard

Forge facts checked on forgeshipyard.com on 2026-11-09 (see the whole-vessel plan, section 1).

| Area | Forge | MarinaFrame now | Gap | Who leads |
|---|---|---|---|---|
| Hull from drawings | Yes (their stated product today) | Yes: live sheet-only runs; Series 60 L0 passes 2 % / 5 % gates; others 3-9 % RMS | Our hull still misses the RMS gate on most cases | Even; we have numbers, they have none |
| Decks, deckhouses, appendages | Balclutha research case: hull, decks, bulkheads, framing, deckhouses, rigging; 44 of 114 parts have geometry | Gunnerus: 7 GA parts + 4 appendages; deckhouse IoU 0.94, volume +9.4 %; one STEP + GLB; Parts tab in the app | Ours is one development ship; no rigging; appendage contact gaps | Even on breadth; ours is measured |
| Internal structure (3D) | Bulkheads and framing (visual) | 2D midship reader (MiDShip F1 0.999, 4.4 mm median); no 3D structure yet | We need step 2 (3D structure, OCX) | Forge |
| Engine, machinery, outfitting, piping | "Next" in their marketing | Not started (planned last) | Both early | Even |
| Gaps in drawings | Refuse to fill: no evidence, no geometry | AI fills with labelled guesses | This is our product choice | MarinaFrame |
| Accuracy evidence | None published; rebuild-repeatability only | Frozen gates, sealed sets, per-section ink distance, STEP reimport audit | We still need one published real-ship result | MarinaFrame |
| Compliance | USCG 46 CFR, plan review guides, NVICs as cited evidence | ABS rule subset with citations (W4), not in the app | Rules not tied to the app or to 3D structure | Forge |
| Review and sign-off | Propose, approve, sign; append-only decision ledger | Per-section and per-part review, Mark and revise, sign-off "usable as a starting model", event ledger | No multi-user sign-off or roles | Close |
| Reconciliation over the ship's life | Survey, thickness and repair data update the model | None | Needs gauging data and a design partner | Forge |
| Drydock work packages | Yes | None | Depends on structure and gauging | Forge |
| Delivery | Hosted web, on-premise, 90-day governed pilots | macOS desktop app (release build 1.2 GB with bundled worker); not signed or notarized | Signing, Windows, a pilot offer | Forge |
| Customers | Pilots with design partners, a shipyard owner giving feedback | None | A first design partner | Forge |
| Live AI view | Not shown | Live thinking, attention ring, hull growing on screen | - | MarinaFrame |

**Summary.** Forge leads on workflow breadth after the model exists (compliance, reconciliation,
work packages) and on having customers. We lead on measured geometry, filling gaps instead of
leaving holes, and the live AI experience. Their own site says their 3D scope today is mostly the
hull, so the geometry race is open.

## 3. Gap analysis: MarinaFrame now against where we intend to be

Target state: a signed desktop app that a design partner uses on its own fleet drawings, with
whole-vessel drafts inside published error bands, and a repair workflow on top.

| Area | Now | Target | Gap and next step |
|---|---|---|---|
| Hull accuracy, clean sheets | 1 of 5 L0 cases passes live (Series 60 1.4 %); run-to-run spread 1-2 points | Most clean sheets pass 2 % RMS and 5 % volume | Hull ends beyond the end stations (DTMB and Series 60 hulls stop at the last station: 80 m of 99.8 m); fore-curve identity; best-of-N drafts by fit score |
| Hull accuracy, scans | L1 blurred sheets 9-29 % RMS | Within 2x of clean-sheet error | Curve identity in blurred panels; more centreline and station-line work; tiles of at most 2048 px for the model |
| AI value | On clean vector input the model copies the code reading; on a whole Balclutha sheet it read nothing (image downscaled) | The model fixes what code gets wrong on old scans | Tiled reads at full resolution under a fixed protocol; give the model analysis tools (hydrostatics against particulars) |
| Real-ship proof | Gunnerus hull benchmark sealed; whole-vessel numbers are development results | One published, frozen-code result on a real ship | Run the frozen pipeline once on a held-out real ship and publish the numbers |
| Whole vessel | Gunnerus GA parts + appendages; Part re-run from a mark (CLI) | Decks, superstructure, appendages, openings on any GA; parts revisable in the app | Generalise the GA reader beyond Gunnerus; openings and hatches; wire part re-run into the app |
| 3D structure | 2D midship reader only | Plates and stiffeners along the ship; OCX export | Whole-vessel plan step 2 (MiDShip 3D truth) |
| Rules and repair | ABS subset outside the app | Gauging on plate IDs, wastage against rules, steel-renewal list | Needs step 2 and partner gauging data |
| App | Intake, live run, review, Parts, Export, batch queue, key usage, notifications; real-app checked today | Polished, reliable for a full day of use by a naval architect | Fix the stale 3D model bug and Model-only resize (in progress); notices file; Windows later |
| Packaging | Release build with bundled worker (1.2 GB app, 360 MB DMG); PyMuPDF licence bought; OpenCV removed | Signed, notarized installer with update channel | Apple Developer ID and notarization (owner); third-party notices file; smaller runtime |
| Keys and cost | 3 OpenCode Go keys; 2 at monthly limit until 14-15 Nov | Enough model capacity for batches | More keys or a higher plan for batch use (owner) |
| Go to market | No partner, no pilot offer | 1 design partner with a fleet drawing set and gauging records | Founder outreach through MarinaChain shipping relationships; a pilot package (the app + a review session + measured report) |

## 4. Priorities (next four weeks)

1. **Hull accuracy to the gate on clean sheets**: hull ends beyond end stations, fore-curve
   identity, best-of-N by fit. Measure on the 24 development cases each round.
2. **One published real-ship result** with frozen code (this is the edge Forge cannot show).
3. **Design partner** (founder): one owner or yard with real drawings and gauging data.
4. **Signed installer** (founder: Developer ID) so the partner can install it.
5. **Whole vessel beyond Gunnerus**: a second GA, openings, part re-run in the app.
6. **Step 2, 3D structure**, then rules and repair workflow once partner data exists.

## 5. Owner decisions open

- Apple Developer ID account for signing and notarization.
- More model capacity (keys or plan) before batch pilots.
- Design-partner outreach and the pilot offer.
