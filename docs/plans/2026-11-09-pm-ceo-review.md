# MarinaFrame: PM and CEO review (2026-11-09, end of day)

Read with `docs/plans/2026-11-09-gap-analysis.md` (vision, Forge comparison) and
`docs/research/2026-11-09-beyond-hull-features.md` (what buyers pay for). All numbers are development
or holdout results from today; every output is a draft and `engineering_approved` is always false.

## 1. Where we are (facts)

| Area | State | Evidence |
|---|---|---|
| Hull from clean sheets (live, Sonnet 5.5) | 4 of 10 dev cases pass the frozen gates (2 % RMS, 5 % volume) | `docs/HULL_SELECTION.md` section 7 |
| Hull from old scans (body-plan reader) | Holdouts: BUE GIRL pass (1.4 mm RMS); PARDON ME (hard chine) misses by 1 cell; BUMBLE BEE invalid (our calibration swapped bow and stern) | `docs/WHOLE_VESSEL_GUNNERUS.md` 5.9, `docs/holdouts/` |
| Tanks | Gunnerus (vector): 24/24 built, volume median 10 %; Huddell (scan): 0/22 at holdout, 14/22 after round 2 (now a dev case) | `docs/TANKS_V1.md`, `docs/TANKS_V2.md` |
| Steel structure | MiDShip blocks + Gunnerus parallel body; OCX 3.0.1 valid; positions match print to the mm | `docs/STRUCTURE_V2.md` |
| App | Intake, live run, review, parts, tanks panel, steel and tank 3D views with capacity-plan colours, exports (STEP, OCX, GLB/STL, CSV, PDF, ZIP) | merged on `continue/v0.5` |
| Quality | 1325 Python + 42 UI tests; independent code review, 11 of 14 findings fixed | CI on PR #4 |
| Packaging | macOS build, not signed; Windows not built (CI portability watch only) | `docs/plans/2026-11-09-packaging.md` |
| Customers | None. No buyer calls, no prices validated | research doc section 1 |

## 2. PM lens: what the product still needs

Ranked by how much each blocks a first paying user.

1. **The best reader is not in the product.** The scanned body-plan reader (1.4 mm on a holdout)
   runs only in benchmark harnesses, and every holdout used a sheet calibration written by an agent
   or person (centreline, waterline rows, scale, which half is the bow). A customer's run has no such
   person. Needed: automatic sheet calibration (with a second, independent check of bow/stern and
   scale, as the BUMBLE BEE lesson shows), then the reader wired into the app's hull path as the
   default for scanned body plans, with a one-click person check of the calibration overlay.
2. **One real drawing set end to end.** Every result today uses sheets we chose and prepared. A real
   customer set is 10 to 40 mixed sheets (GA, lines, midship, tank plan, capacity plan), mixed units,
   partly scanned. Needed: run intake to export on a complete real set without hand steps, and fix
   what breaks. Gunnerus is the obvious first set; then a HAER vessel with a full set.
3. **Accuracy the user can trust per output.** We measure well, but the user sees only labels
   (traced, read, guessed). Needed: a per-output confidence summary in the app and report ("hull:
   within about X mm where traced; tanks: volumes within about 10 % where outlines are traced"),
   from our measured error bands, and a short published benchmark page for sales.
4. **Cost and time per ship.** A live hull case uses about 300k to 500k input tokens on Sonnet 5.5,
   plus tank label questions. Needed: a measured cost and wall time per complete ship, and the
   cheapest path that keeps accuracy (code-only where it already wins, as on BUE GIRL; Crouton is 25
   to 30 times cheaper in tokens for label questions and matched Sonnet on two holdouts).
5. **Windows.** Target users are likely on Windows. Needed: a Windows build, Windows worker
   isolation (job objects / AppContainer), and code signing (SmartScreen). The CI watch already lists
   the Unix-only spots.
6. **Hard-chine hulls and the remaining reader gaps.** Join station pieces across the chine
   (PARDON ME), DTMB deck heights, better best-of-N picks.
7. **Beyond-hull depth.** Tanks need a fresh holdout ship; structure beyond the parallel body; OCX
   compartments (in progress); thickness gauging needs partner data.
8. **Engineering health.** The router path to Sol and GLM failed on long jobs all day; work moved to
   Claude agents. Fix or retire it, so lanes can use cheaper models again.

## 3. CEO lens: what decides whether this becomes a business

1. **No customer is the main risk, not technology.** We have strong, measured technology and no
   buyer evidence: no calls, no prices, no partner. Every week without a design partner is a week of
   building on guesses. Decision: the founder starts 5 to 10 conversations this week through
   MarinaChain's ship-manager and repair-yard contacts, with the call guide in the research doc.
2. **Pick the first wedge.** Three candidate first products, from the research:
   - (a) "Old drawings to a 3D hull and capacity model for retrofit and stability work" (naval
     architecture offices, owners' technical departments);
   - (b) "Steel model with plate IDs for drydock and gauging" (repair yards, owners at special
     survey);
   - (c) "Hull model for performance and CII work" (owners, retrofit engineers).
   Our evidence is strongest for (a) (hull plus tanks work today); (b) needs partner gauging data.
   Recommendation: lead with (a), offer (b) as the pilot's second phase.
3. **Our edge is measured accuracy and honest gaps.** Forge publishes no accuracy numbers; we have
   frozen protocols, holdouts and failures reported. Make this the sales story: a public benchmark
   page and a per-ship accuracy summary in every delivery.
4. **Pilot offer to test willingness to pay.** For example: one vessel's drawing set in, within 5
   working days a draft 3D hull, tank capacity tables, a steel model of the midbody (where drawings
   allow), OCX/STEP files and an accuracy report; a fixed price to be set from the first calls; a
   naval architect reviews it with us. Price discovery comes from the first three pilots.
5. **Delivery model.** The desktop app keeps drawings local (a selling point for owners). For the
   first pilots, deliver as a service run by us with the app, then hand over the app once Windows
   and signing exist. This avoids blocking sales on packaging.
6. **Data and rights.** Commercial licences are in place for today's data; PyMuPDF licence bought.
   Open items: third-party notices file; a data agreement template for partner drawings and gauging
   records.
7. **Team and model costs.** Development runs on parallel AI lanes; the binding constraint today was
   the subscription rate limit and the router reliability, not engineering ideas. Decide on more model
   capacity before pilots, and on one person who can sign off drafts as a naval architect for pilot
   deliveries.

## 4. Proposed next four weeks

| Week | Engineering (lanes) | Founder |
|---|---|---|
| 1 | Auto sheet calibration with a second bow/stern check; wire the scanned body-plan reader into the app hull path; OCX compartments (running) | 5 to 10 buyer calls; pick the wedge; draft the pilot offer |
| 2 | Gunnerus full drawing set intake-to-export with no hand steps; per-output accuracy summary in app and report | 2 pilot candidates; data agreement template |
| 3 | Cost and time per ship; cheaper label path (Crouton or code-only where it wins); hard-chine station joining | First pilot drawing set received |
| 4 | Windows build and worker isolation; signing; fix what the pilot set breaks | Pilot delivery and price feedback |

Resume point: section 2 item 1 and section 3 item 1 are the two first actions.

## 5. Parked for the marketing and visuals work

- **vork** (github.com/voyager-so/vork): an agent-driven GPU renderer for offline stills and films.
  Use it for pitch-deck, website and pilot-proposal renders from our own GLB models (for example
  Gunnerus with coloured tanks, a cut steel block, a "drawing to ship" film). Not for the app's 3D
  view (Three.js stays): its preview licence forbids selling, sublicensing or hosting it, but allows
  commercial renders delivered to clients. Research preview; later versions may be paid. Decided by
  the founder on 2026-11-09: wait for the marketing work.
