# Beyond the hull: which features would buyers pay for?

Date: 2026-11-09. Author: product research (Claude). Status: desk research, no buyer interviews.

Labels used below:
- **FACT** = stated in a cited source (the source may be a vendor, so read it as a claim).
- **INFERENCE** = our reasoning. Not proven.
- **Not found** = we searched and found no public figure.

Main limit of this study: almost no one publishes prices for ship engineering services, scanning,
or gauging. Price evidence is weak. Demand evidence (regulation, trade press, vendor claims) is
better. We need 5-10 buyer calls before we set prices.

## 1. Summary

1. **Build next: a compartment and tank model with capacity plan, tank tables and sounding tables.**
   It needs only the GA, tank plan and hull we already read. It feeds stability, loading and
   retrofit space checks. A competitor (ShipReality) already sells "compartment models" and lists
   GA, construction drawings and the stability booklet as inputs. Effort: medium.
2. **Then: 3D structure with plate IDs, steel weight and a steel-renewal estimate.** Steel work is
   the cost line that drives drydock surprises. Class needs thickness gauging every 5-year cycle.
   Inputs (midship section, shell expansion, construction plans) usually exist. Effort: high.
3. **Then: gauging import, wastage check and drydock work package, with a design partner.**
   Gauging data is today stuck in PDFs. Software-only price anchors are low ($5 per vessel per
   month for one tool), so we must sell the model-linked result, not a database.
4. Retrofit space model (BWTS, ESD, fuel conversion) is real demand, but accurate work needs laser
   scans. We offer a "concept model from drawings" and import scan data later.
5. Weak spots: no verified price for any service. Competitor claims are unverified. Run buyer calls.

## 2. Buyer personas

| Persona | Who signs | Budget owner | Trigger events | FACT/INFERENCE |
|---|---|---|---|---|
| Ship-repair yard (engineering / estimating) | Yard planning manager or commercial director | Yard overhead; cost is hidden in quote preparation | A drydock enquiry arrives with only old 2D PDFs; steel quantities must be priced fast | INFERENCE. Yards are busy: Chinese repair yards report backlogs of weeks and slots booked months ahead ([Maritime Optima](https://maritimeoptima.com/maritime-news/chinas-repair-yards-surge-on-wave-of-global-fleet-maintenance), FACT, secondary source) |
| Owner / ship manager technical department | Technical superintendent, fleet manager, technical director | Drydock budget, retrofit capex, class costs | 5-year special survey and intermediate survey; CII low rating; EU ETS / FuelEU cost; BWTS or ESD retrofit; sale or purchase inspection | FACT for survey cycle and regulation (section 4). BIMCO shows "actual drydocking cost" as a KPI with an example of US$3,920,800 ([BIMCO Ship PI](https://ship-pi.bimco.org/documentation/2.6/definition/pi/pi001-actual-drydocking-costs)); one example, not an average |
| Naval architecture / retrofit engineering office | Principal naval architect, project manager | Project fee from the owner or yard | Conversion or retrofit design needs a space model; stability booklet reissue; class submission | FACT that older vessels often have records only on paper or legacy 2D PDFs ([Maritime Executive](https://maritime-executive.com/blog/managing-vessel-repairs-with-a-digital-twin)) |
| Class society / third-party gauging firm (not a buyer now) | n/a | n/a | They own thickness-report software (LR Argonaut, DNV ShipManager Hull, RS VOLNA). We should export to them, not compete | FACT: LR made Argonaut mandatory for new TM reports from 2014 ([LR](https://www.lr.org/en/class-news-resources/20-14)) |

MarinaChain angle (INFERENCE): the first calls should go to Singapore / Asia ship managers and to
one repair yard, because those are the shipping relationships we already have.

## 3. Feature table

Effort = our inference for MarinaFrame (low / med / high). Evidence strength: A = sourced demand and
a sourced price signal; B = sourced demand, no price; C = inference or vendor claim only.

| # | Feature | Buyer | What they pay today (source) | Frequency / urgency | Inputs usually available from drawings | Build effort | Evidence |
|---|---|---|---|---|---|---|---|
| 1 | Compartment and tank model; capacity plan, tank table, sounding table | Naval architecture offices, owners, yards | Not found for the service. Freelance naval architects list 80-100 EUR per hour ([CadCrowd listing](https://www.cadcrowd.com/service/2153-autocad-3d-models-naval-architecture)); a blog gives about $90-$120 per hour ([CadCrowd blog](https://www.cadcrowd.com/blog/?p=28660)). Software: Maxsurf from $11,375 per 12-month licence ([Bentley](https://www.bentley.com/products/maxsurf)) | Once per ship to build; again at each conversion or stability booklet reissue. US rules list capacity plan and sounding tables as booklet content ([46 CFR 170.180](https://www.law.cornell.edu/cfr/text/46/170.180)) | Capacity plan, tank plan, GA, lines. Often PDF or scan. Tank tables printed in the booklet (vision-table reader exists in repo) | Med | B |
| 2 | Stability booklet inputs (hydrostatics, tank data, lightship from records) | Naval architecture offices, ship managers | Not found. Inclining test fee in South Africa is R975 per hour for the authority witness ([SAMSA fee table](https://www.acts.co.za/south-african-maritime-safety-authority-act-1998/n1042_27__approval_of_plans_an.php)); not a market price | At conversion, after lightship change, on class demand | Lines, tank data, old booklet. Lightship needs a real weighing, not a drawing | Low-med (hydrostatics exist today) | B |
| 3 | 3D structure model (plates, stiffeners), OCX export | Yards, retrofit offices, class | Not found. ABS and DNV have accepted 3D models in class approval, newbuild only ([DNV](https://www.dnv.com/expert-story/maritime-impact/Paving-the-way-for-3D-model-based-class-approval.html), [Hellenic Shipping News](https://www.hellenicshippingnews.com/?p=904864)) | Needed at conversion, major repair, class submission. Demand for existing ships: not found | Midship section, shell expansion, construction plans, longitudinal section. Scantlings often in tables | High | C for existing ships |
| 4 | Steel weight and renewal estimate (plate IDs, tonnage) | Yards, owners | Mill plate: about 3,400 yuan per tonne in eastern China, April 2025 ([Fastmarkets via search](https://www.fastmarkets.com/insights/us-port-fee-proposals-to-have-little-effect-on-china-amid-healthy-bulk-ship-orders/)); installed renewal rate: not found. Drydock "steel findings" are a named cost driver ([ShipUniverse](https://www.shipuniverse.com/maritime-tools/ship-drydock-cost-calculator/)) | Every drydock (about every 2.5 to 5 years). Special survey every 5 years ([IACS UR Z15 mirror](https://www.turkloydu.org/pdf-files/iacs-karar-ve-csr-degisimleri/iacs-es-gereklilikleri/UR_Z15_Rev1_Corr.1_TR_EN.pdf)) | Same as 3, plus gauging report | High | B |
| 5 | Thickness-gauging management and wastage report vs rule minimums | Owners, ship managers, gauging firms | Software is cheap: Fleet Rabbit $5 per vessel per month ([Fleet Rabbit](https://fleetrabbit.com/industry/vessel-fleet/commercial-vessel-hull-inspection-software-and-drydock)). Gauging service price: not found. Class tools are tied to surveys (LR Argonaut, DNV ShipManager Hull, RS VOLNA) | Each special and intermediate survey; ESP ships over 10 years need more ballast-tank exams ([IACS UR Z summary](https://www.turkloydu.org/pdf-files/iacs-karar-ve-csr-degisimleri/iacs-es-gereklilikleri/UR_Z15_Rev1_Corr.1_TR_EN.pdf)) | Gauging data comes from the partner, not from drawings. Drawings give the plate map | Med (after 3) | B |
| 6 | Drydock / repair work package and specification | Owners, ship managers, yards | Software exists: ABS NS Drydock Manager, DNV ShipManager Drydock, others ([ABS](https://www.abs-group.com/content/documents/resources/ns-resources/NS_Drydock_Manager.pdf), [DNV](https://www.dnv.com/services/dry-docking-and-ship-repair-shipmanager-drydock-197968/)); prices not found. Owner saving claims are vendor claims | Every drydock | Spec text is mostly templates; the 3D link to plates and tanks is what is missing | Med | B |
| 7 | Retrofit space model (BWTS, scrubber, ESD, fuel conversion) | Retrofit offices, yards, owners | BWTS retrofit per vessel: about $0.2-1 million all-in ([JAES paper](https://aseestant.ceon.rs/index.php/jaes/article/download/42108/22493)); trade press range $0.5-5 million ([MarineLink](https://www.marinelink.com/news/management-conundrum384469)); 2009 study: $62,000-$85,000 install plus design engineering as a line item ([MERC](https://mercserver1.cbl.umces.edu/Downloads/Reports/Other_Publications/MERC_Preliminary_Cost/MERC_Preliminary_Cost.pdf)). Scan savings: 37% cost and 39% time in a 2007 Navy-backed study ([GeoWeek](https://www.geoweeknews.com/articles/ship-check-data-capture-37-cheaper-39-faster-with-3d-laser-scanning-nsrp-and-electric-boat-report/)) | Wave-driven: BWM D-2 deadline passed 8 Sep 2024 ([DNV BWM FAQ](https://www.dnv.com/maritime/ballast-water-management/frequently-asked-questions/)); CII, EU ETS and FuelEU continue | GA, machinery room arrangement, piping diagrams. Accuracy limited; scans needed for tight rooms | High (needs machinery, piping) | B |
| 8 | Laser scan to model (point cloud) | Retrofit offices, yards | Service price: not found. Old scanner hardware $150,000+ ([Maritime Professional](https://www.maritimeprofessional.com/news/laser-scanning-marine-industry-243523)) | At each retrofit | Not from drawings. A scan merge feature would add value | Med (import and align) | C |
| 9 | Piping and outfitting model | Yards, offices | Not found | Retrofit only | P&IDs, rarely routed 3D | High | C |
| 10 | Digital twin / asset model | Owners | Analysis says structural twins for drydock planning are "growing", visualisation-only twins are weak ([ShipUniverse](https://www.shipuniverse.com/?p=16116)) | Continuous, but buyers want a decision tied to it | All of the above | High | B (as a frame) |

## 4. Pricing and competitor notes

**Software (FACT unless marked).**
- Maxsurf (Bentley): from US$11,375 for a 12-month subscription with one licence; a reseller lists US$10,484 ([Bentley](https://www.bentley.com/products/maxsurf), [Virtuosity](https://en.virtuosity.com/maxsurf)). A Bentley wiki says tiers merged on 1 April 2023 at about 6% above the old Advanced price ([Bentley community](https://communities.bentley.com/products/offshore/w/wiki/66156/maxsurf-advanced---license-expired)).
- NAPA: price not found. DNV Nauticus Hull and ShipManager Hull: quote only ([DNV knowledge centre](https://www.ntnu.no/wiki/display/imtsoftware/Nauticus+Hull)); price not found.
- ShipConstructor, AVEVA Marine: price not found. Cadmatic uses a token-based subscription or perpetual plus maintenance; no figure ([G2](https://www.g2.com/products/cadmatic-hull/pricing)).
- Fleet Rabbit (hull gauging and drydock scheduling): $5 per vessel per month, billed annually ([Fleet Rabbit](https://fleetrabbit.com/industry/vessel-fleet/commercial-vessel-hull-inspection-software-and-drydock)). Vendor page.
- Class tools: LR Argonaut is free to download for surveyors and suppliers ([LR](https://www.lr.org/en/class-news-resources/20-14)).

**Services.**
- Engineering rates: 80-100 EUR per hour (freelance listing) and $90-$120 per hour (blog), see table. Low quality sources.
- Reverse engineering from drawings, laser scan plus modelling per ship: **not found**.
- Underwater hull inspection in Singapore: about $3,000-$15,000 per vessel (vendor page, adjacent service) ([page](https://droneinspections.pages.dev/underwater-hull-inspection-singapore/)).

**Price anchors for our own offer (INFERENCE).**
- A hull-only model replaces weeks of manual work. At 80-120 per hour, 3-6 weeks is roughly 10,000-30,000 per ship in labour value. This is arithmetic on the rate above, not a market price.
- Per-seat software at $10,000+ per year (Maxsurf) shows that engineering offices pay for tools tied to billable work. Fleet software at $5 per vessel per month shows that owners will not pay much for a database alone.

**Competitors.**
- Forge Shipyard: drawings to model plus compliance, reconciliation and drydock packages. Facts in `docs/plans/2026-11-09-gap-analysis.md`. Pricing: not found.
- ShipReality (ShipHULL, ShipCAD, ShipFORCE): AI 3D hull and compartment reconstruction from legacy 2D drawings; inputs named as GA, construction drawings and trim and stability booklet; claims "hours, not weeks"; pricing "Contact Us" ([ShipReality](https://shipreality.com), [LinkedIn post via search](https://gr.linkedin.com/in/georgios-bourtzos)). Claims unverified. Treat as a direct competitor.
- Academic: Raster2Hull addresses the same gap for aging vessels (named in search results; not read by us).
- Sell-side software that already holds the hull data: class tools and ShipManager Hull, ABS NS Drydock Manager. We should export to them.

**Regulation pull (FACT).**
- EU ETS: shipping must surrender allowances for 100% of in-scope emissions from 2026 (40% in 2024, 70% in 2025); ships of 5,000 GT and above ([UK P&I](https://www.ukpandi.com/news-and-resources/news/article/eu-ets-and-shipping-from-1-january-2026/)).
- FuelEU: 2% GHG intensity cut from 2025, 6% by 2030; penalty EUR 2,400 per tonne VLSFO-equivalent ([DNV](https://www.dnv.com/news/2023/the-eu-agrees-on-well-to-wake-ghg-limits-to-energy-used-on-board-ships-from-2025-243501/), [CTI-Maritec](https://www.manifoldtimes.com/news/cti-maritec-fueleu-maritime-regulation-effective-1-january-2025/)). One source gives a conflicting figure; we use the majority.
- CII: a ship rated E for one year, or D for three years, needs an approved corrective action plan ([DNV](https://www.dnv.com/maritime/insights/topics/seemp-part-iii/corrective-actions-plan)).
- BWM D-2: all existing ships by 8 Sep 2024 ([DNV](https://www.dnv.com/maritime/ballast-water-management/frequently-asked-questions/)). That retrofit wave is over; new waves are CII, EU ETS, FuelEU, fuel conversion (INFERENCE).

## 5. Pain points heard

Few buyer voices are public. Most items come from vendor or trade pages. Short quotes below; read as claims.

- Lifetimes: "Vessel lifespans average between 30 and 50 years" ([Maritime Executive](https://maritime-executive.com/blog/managing-vessel-repairs-with-a-digital-twin)). Records no longer match the ship; older ships may have only paper or legacy 2D PDFs (paraphrase, same source).
- Gauging data: reports "stored across physical PDF files" ([Fleet Rabbit](https://fleetrabbit.com/industry/vessel-fleet/commercial-vessel-hull-inspection-software-and-drydock)). Vendor says plate corrosion surprises led to steel change orders and drydock delays (paraphrase).
- Spec work: compiling a drydock spec takes weeks of reading logs, diver reports and thickness sheets (paraphrase, same vendor page).
- Scope control: a Meratus case says a solid yard specification lets the owner bill only agreed scope; extras need a variation order (paraphrase, [Maritime Executive](https://maritime-executive.com/corporate/digital-outcomes-meratus-saves-millions-in-annual-dry-docking-costs-1)).
- Twins without a use: an "expensive screen saver" if not tied to a workflow ([ShipUniverse](https://www.shipuniverse.com/?p=16116)). Also: "The value sits in decisions, not graphics".
- Scan to model: point clouds take considerable time and labour to turn into models (paraphrase, [Fanship paper](https://ojs.ugal.ro/index.php/fanship/article/view/2496) via search).
- Retrofit conditions: tight spaces and inaccurate existing-condition data are named problems in an engine-room retrofit case ([Cadmatic podcast](https://cadmatic.com/en/podcast/from-scan-to-sea-trials-modernizing-an-engine-room/)).
- Gauging access: staging in holds is slow and risky; drones need flag approval and miss corrugation turns (paraphrase, [Riviera](https://www.rivieramm.com/news-content-hub/abs-facilitates-innovative-drone-inspection-of-tank-steel-thickness-67544)).
- Navy view: shipbuilders cite continued use of 2D data for legacy classes ([Defense One](https://www.defenseone.com/technology/2024/05/navy-slow-adopt-modern-ship-designing-tools-gao-finds/396313/)).
- Gap in our evidence: no forum, RFQ or job-post complaints found. Next step is calls (section 6).

## 6. Recommended sequence and pilot offer

**Sequence (INFERENCE, ranked by evidence of demand and fit with our tools).**
1. **Compartments and tanks (3-5 weeks).** Extends GA reading and the vision-table reader. Output: tank volumes, capacity plan, sounding table in PDF and CSV, each value labelled traced / read by AI / guessed. Check against the printed tank table: gate on volume error per tank.
2. **Structure with plate IDs and steel weight (4-6 weeks, existing plan step 2).** Output: plate list with weight, OCX export. Gate on weight against the printed midship section weight or the class steel weight, where known.
3. **Gauging import, wastage vs rule minimum, renewal list, drydock work package (3-4 weeks after partner data).** Export to class formats where open. Do not build a gauging database that competes with class tools.
4. **Retrofit concept model plus scan import (later).** Needs machinery and piping first.

**Pilot offer idea for a design partner (INFERENCE).**
- Who: a ship manager or repair yard with 3-10 ships near a special survey, and old drawings only.
- Offer: for one ship, we deliver in 5 working days a labelled draft: hull, decks, tank and compartment model, tank table, and (when ready) plate list with steel weight. Fixed pilot fee or free for a case study; price to be set after calls.
- They give: drawings for 2-3 ships, one past gauging report and one past drydock spec for the same ship.
- Success test, set before the pilot: tank volumes within 3% of the printed table for 80% of tanks; engineer time to correct the draft under 20% of manual rebuild time; and a yes/no on "would you pay for the next ship".
- Second step: use their gauging report to run the wastage check and compare our renewal estimate to the yard's real steel change orders.
- Why this design: it proves value on a decision (drydock scope and steel cost) that buyers already pay for.

**Buyer calls first (to close evidence gaps):** ask what they pay today for (a) a capacity plan or tank table rebuild, (b) a steel renewal estimate before a tender, (c) a retrofit space model, and who signs.

## 7. Sources

Retrieved 2026-11-09 through web search; many via search summaries. Where we did not open the page ourselves, the claim is marked "via search".

- Bentley Maxsurf: https://www.bentley.com/products/maxsurf ; https://en.virtuosity.com/maxsurf ; https://communities.bentley.com/products/offshore/w/wiki/66156/maxsurf-advanced---license-expired
- DNV Nauticus Hull (NTNU wiki): https://www.ntnu.no/wiki/display/imtsoftware/Nauticus+Hull
- Cadmatic pricing (G2): https://www.g2.com/products/cadmatic-hull/pricing
- LR Argonaut notice: https://www.lr.org/en/class-news-resources/20-14
- Fleet Rabbit: https://fleetrabbit.com/industry/vessel-fleet/commercial-vessel-hull-inspection-software-and-drydock
- ShipUniverse drydock calculator: https://www.shipuniverse.com/maritime-tools/ship-drydock-cost-calculator/
- ShipUniverse digital twins: https://www.shipuniverse.com/?p=16116
- BIMCO Ship PI drydocking cost: https://ship-pi.bimco.org/documentation/2.6/definition/pi/pi001-actual-drydocking-costs
- ABS NS Drydock Manager: https://www.abs-group.com/content/documents/resources/ns-resources/NS_Drydock_Manager.pdf
- DNV ShipManager Drydock: https://www.dnv.com/services/dry-docking-and-ship-repair-shipmanager-drydock-197968/
- Meratus case: https://maritime-executive.com/corporate/digital-outcomes-meratus-saves-millions-in-annual-dry-docking-costs-1
- Maritime Executive digital twin repairs: https://maritime-executive.com/blog/managing-vessel-repairs-with-a-digital-twin
- Riviera drone UTM: https://www.rivieramm.com/news-content-hub/abs-facilitates-innovative-drone-inspection-of-tank-steel-thickness-67544
- Singapore hull inspection vendor: https://droneinspections.pages.dev/underwater-hull-inspection-singapore/
- IACS UR Z15 mirror: https://www.turkloydu.org/pdf-files/iacs-karar-ve-csr-degisimleri/iacs-es-gereklilikleri/UR_Z15_Rev1_Corr.1_TR_EN.pdf
- Fastmarkets plate price: https://www.fastmarkets.com/insights/us-port-fee-proposals-to-have-little-effect-on-china-amid-healthy-bulk-ship-orders/
- Maritime Optima Chinese repair yards: https://maritimeoptima.com/maritime-news/chinas-repair-yards-surge-on-wave-of-global-fleet-maintenance
- BWTS cost: https://aseestant.ceon.rs/index.php/jaes/article/download/42108/22493 ; https://www.marinelink.com/news/management-conundrum384469 ; https://mercserver1.cbl.umces.edu/Downloads/Reports/Other_Publications/MERC_Preliminary_Cost/MERC_Preliminary_Cost.pdf
- Laser scanning: https://www.geoweeknews.com/articles/ship-check-data-capture-37-cheaper-39-faster-with-3d-laser-scanning-nsrp-and-electric-boat-report/ ; https://www.maritimeprofessional.com/news/laser-scanning-marine-industry-243523 ; https://ojs.ugal.ro/index.php/fanship/article/view/2496 ; https://cadmatic.com/en/podcast/from-scan-to-sea-trials-modernizing-an-engine-room/
- Naval architect rates: https://www.cadcrowd.com/service/2153-autocad-3d-models-naval-architecture ; https://www.cadcrowd.com/blog/?p=28660
- Stability booklet content: https://www.law.cornell.edu/cfr/text/46/170.180 ; SAMSA fees: https://www.acts.co.za/south-african-maritime-safety-authority-act-1998/n1042_27__approval_of_plans_an.php
- 3D class approval / OCX: https://www.dnv.com/expert-story/maritime-impact/Paving-the-way-for-3D-model-based-class-approval.html ; https://www.hellenicshippingnews.com/?p=904864
- ShipReality: https://shipreality.com ; https://gr.linkedin.com/in/georgios-bourtzos
- Defense One / GAO: https://www.defenseone.com/technology/2024/05/navy-slow-adopt-modern-ship-designing-tools-gao-finds/396313/
- EU ETS: https://www.ukpandi.com/news-and-resources/news/article/eu-ets-and-shipping-from-1-january-2026/
- FuelEU: https://www.dnv.com/news/2023/the-eu-agrees-on-well-to-wake-ghg-limits-to-energy-used-on-board-ships-from-2025-243501/ ; https://www.manifoldtimes.com/news/cti-maritec-fueleu-maritime-regulation-effective-1-january-2025/
- CII corrective action: https://www.dnv.com/maritime/insights/topics/seemp-part-iii/corrective-actions-plan
- BWM D-2 deadline: https://www.dnv.com/maritime/ballast-water-management/frequently-asked-questions/
- Repo: docs/plans/2026-11-09-gap-analysis.md ; docs/plans/2026-11-09-whole-vessel-scope.md
