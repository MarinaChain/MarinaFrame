# Public tanker data for the blocked 13a gates

Lane `public-tanker-data`, batch 2026-11-13b. Goal: cited public data that lets the three blocked
13a gates run (concept-dimensions G2, tank-arrangement G3, weights-efficiency public-ship gate).
This lane collects data only. It changes no code and no frozen gate.

## Where the data is

All third-party data is outside git, in the main checkout's ignored folder
`work/public-tankers/` (main checkout, not the worktree):

| File | Content |
|---|---|
| `fleet_particulars.csv` | One row per ship and source. Columns include name, IMO, year, builder, yard number, segment, derived `design_id`, `reserved_or_sister` and `sister_rule`, LOA, Lpp, B (with basis), D, summer draft (with basis), DWT, displacement, lightship, Cb (with basis), cargo capacity with fill basis, slop capacity, service speed (with basis), MCR, engine, reported EEDI/EEXI, `complete_for_concept_fit`, `derived_fields`, `quality_flags`, source URL, title, location, source date, access date. |
| `capacity_cases.csv` | Candidate public capacity cases for tank-arrangement G3, with what each one lacks. |
| `weights_efficiency_cases.csv` | Candidate weight and efficiency cases with every published input and the missing ones. |
| `manifest.tsv` | Every downloaded file: local path, URL, access date, SHA-256, size. |
| `raw/<source>-20261113/` | Downloads, one new directory per source. |
| `scripts/` | Fetch, parse, table-build, manifest and coverage scripts (run with `python3 -I`). |

Rebuild from the downloads (no network):

```sh
cd work/public-tankers
python3 -I scripts/parse_q88.py q88_ardmore_raw.csv https://www.ardmoreshipping.com/s/ text/ardmore-raw/*.txt
python3 -I scripts/parse_q88.py q88_misc_raw.csv - text/misc-raw/*.txt
python3 -I scripts/parse_av.py raw/aukevisser-pages-20261113 av_raw.csv
python3 -I scripts/parse_owner_lists.py text/thenamaris.txt raw/owner-lists-20261113/www.minervamarine.com_minerva-marine-fleet_.html owner_partial_raw.csv
python3 -I scripts/build_manifest.py && python3 -I scripts/build_tables.py && python3 -I scripts/coverage.py
```

## Sources

Access date for all: 2026-11-13. No accounts, no paywalls, no sites whose terms forbid collection.

| Source | Type | Used for | Notes |
|---|---|---|---|
| Ardmore Shipping owner website, 23 INTERTANKO Q88 PDFs (`/s/Ardmore-*_q88_02Sep2025.pdf`) | owner primary | MR rows; lightship; reported EEDI/EEXI | Already used by the weights lane for its frozen cases. |
| Gungen owner website, 5 Q88 PDFs (`/uploads/gungen/OT*Y.pdf`) | owner primary | Suezmax rows | HHI 150-153k DWT, two designs. |
| Public Q88 PDFs: Apolytares (US MARAD docket MARAD-2019-0094, attachment 21), PGC Marina (paradisenet.gr), Alam Bakti (maybulk.com.my), Histria Atlas (histria.ro, archived copy at web.archive.org because the site is under revision) | owner / government docket | VLCC, LR1, MR rows | |
| Auke Visser's International Super Tankers (aukevisser.nl): VLCC year listings, letter indexes and ship pages for ships built 2000 onward | secondary (hobby site that mirrors the Miramar Ship Index and owner Q88 excerpts) | VLCC rows, the two reserved ships | No robots.txt and no terms notice; fetched about 370 pages, one request per 1.5 s. Treat as secondary: values are transcriptions. |
| Thenamaris tanker list PDF (May 2026); Minerva Marine fleet page | owner primary, partial | partial rows (no Lpp, D, displacement) | Inventory only; not usable for fits. |
| NTUA diploma thesis 58817 (I. Alexiou, 2023, CC BY-NC-ND 3.0 GR): main text, Lines Plan, Capacity Plan | published design study | capacity case CAP01 | Licence forbids derivatives being redistributed; keep outside git. |
| Virginia Tech AOE design report, Hibernia shuttle tanker, 2001 Team 2 | published student design | capacity case CAP02 (alternative) | |
| I. Bosoanca, "Estimated EEDI versus calculated EEDI using S/P trials for a chemical oil tanker", Annals of Dunarea de Jos Univ. of Galati, Fasc. XI, 2020 | journal paper | weights case WE01 | |

Not used: Scribd copies of Q88s (account and terms), DHT and International Seaways fleet pages (TLS failure and HTTP 403), KOTC fleet Q88 pages (under maintenance), Stena fleet list (DWT and year only), scheepvaartwest.be (hobby site without cited sources), Equasis and class registers that need accounts.

## Method and derived values

- Q88 values are copied as printed. Parsers use `pdftotext -raw`; whitespace is collapsed before matching.
- Auke Visser pages: the Miramar block (decimal commas) and, when present, the Q88 excerpt. When both exist, Q88 values win. Several pages can describe one ship; one row per IMO is kept (the most complete).
- **Derived** (listed per row in `derived_fields`):
  - `cb` = summer displacement / (1.025 x Lpp x B x T_summer). B is the stated breadth (Q88 extreme breadth), and the Q88 displacement includes shell and appendages, so Cb is approximate (about 0.5% high). Only computed where displacement is published.
  - `lightship_t` = displacement - DWT when the lightship is not printed.
  - `cargo_capacity_m3` = listed 98% total minus listed slops, when a Q88 lists slops inside the cargo-tank table.
  - `design_id` = builder group + Lpp (0.5 m) + B (0.1 m) + D (0.1 m). It is a grouping aid, not a confirmed sister list.
  - `segment` from summer DWT: MR < 55k, LR1/Panamax < 85k, Aframax/LR2 < 125k, Suezmax < 200k, VLCC < 330k.
  - Service speed for Auke Visser rows comes from the Miramar machinery code (for example `1D-15.5`); the loading condition is not stated. Q88 rows carry the owner's laden maximum speed, which is not a reference speed.
- **Quality checks** (`quality_flags`): Q88 IMO differs from Miramar IMO; Miramar year differs from the site's year listing (listing year used); implausible Lpp/B, D/B, T/D or Cb (row kept, excluded from `complete_for_concept_fit`); sister 98% capacities differing by more than 5% (slop inclusion differs).

## Coverage per gate

Counts from `python3 -I scripts/coverage.py` on 2026-11-13.

**Fleet table.** 462 rows, 404 unique IMO numbers. By segment (summer DWT): VLCC 340, Suezmax 23,
Aframax/LR2 48, LR1/Panamax 1, MR 50. 103 rows are partial owner-list rows (no Lpp, D or displacement).
148 rows are complete for a concept fit (DWT, Lpp, B, D, summer T and Cb, plausibility checks passed):
VLCC 117, MR 25, Suezmax 5, LR1 1, Aframax/LR2 0. 142 rows have a cargo capacity with an explicit 98%
fill basis. 154 rows have lightship (32 printed, the rest displacement minus DWT). 300 rows have MCR,
282 have a service speed, 25 have an owner-reported EEDI or EEXI value. 435 downloaded files in the manifest.

### concept-dimensions G2 (withheld fit of DHT Harrier and DHT Falcon): data sufficient, can run

- Reserved ships found with full particulars (both from Q88 excerpts on the Auke Visser pages):
  - DHT Harrier = IMO 9762986, ex Eco Queen, DSME 2016: Lpp 325.0, B 60.0, D 29.5, T 21.534, DWT 299,985.4,
    displacement 343,178.2, derived Cb 0.797, 98% cargo 325,764.1 m3. Page `VLCC-E/id1053.htm` (Q88 dated Feb 21, 2018).
  - DHT Falcon = IMO 9310147, ex Front Shanghai and Gulf Eyadah, Nantong COSCO KHI 2006: Lpp 320.0, B 60.0, D 29.3,
    T 20.878, DWT 298,971, displacement 344,300, derived Cb 0.838, 98% cargo 324,706 m3. Page `VLCC-F/id1028.htm`
    (Q88 dated Oct 19, 2018). Its Q88 values are nearly the same as Front Tina (KHI Sakaide 2000), which supports a
    licence-built sister design; check before use.
- Sister exclusion: 21 rows are flagged `reserved_or_sister` (same derived design id, or Lpp within 1 m, B and D within
  0.1 m, DWT within 2% of a reserved ship). This deliberately also removes the KHI/JMU 320 m family and the SWS 324 m
  ships.
- Training rows left: 103 complete VLCC rows, 50 derived designs, DWT 286,120 to 319,464 t, which spans both reserved
  DWTs (gate needs at least 10 designs). Over all segments: 134 complete non-reserved rows, 62 designs.
- Loading basis: Lpp, T, DWT and displacement are all at the Q88 summer load line, so Cb, draft and DWT describe one
  basis. Cargo is 98% capacity. Speed for these rows is the Miramar service speed (condition not stated), which is
  weaker than the gate's "published loading basis" wording for speed; the concept module uses speed only for ranking.
- To run: the concept lane converts `fleet_particulars.csv` rows with `complete_for_concept_fit=True` and
  `reserved_or_sister=False` to its fleet JSON (`ship_id`=IMO, `design_id`, `dwt_t`, `lpp_m`, `beam_m`, `depth_m`,
  `draft_m`, `cb`, `sources`), stores the freeze under main `work/concept/`, and fits once.
- Caveat: Cb is derived from displacement with the stated (extreme) breadth, so absolute Cb is about 0.5% high; it
  is the same derivation for training and withheld ships.

### tank-arrangement G3 (public capacity within 2% at 98%): cannot run as frozen; best case found

- The frozen reference (Tokachi) still has no public hull and no fill basis. No built tanker with both public hull
  geometry and a published 98% capacity was found.
- **Best case, CAP01: NTUA diploma thesis design "ARGYRO" (handle 123456789/58817, 2023).** Lpp 318.00, B 60.00,
  D 29.00, T 21.00, DWT 290,318, Cb 0.810. Published: a vector lines plan (body plan, waterlines, buttocks), a capacity
  plan, the full frame table (distance from AP for every frame), wing width 3.5 m and double-bottom height 2.8 m, tank
  frame ranges, and per-tank capacities at 100% and 98% with centroids. Total cargo plus slops: 327,757.473 m3 at
  100%, 321,202.327 m3 at 98% (thesis section 4.4 tank table).
  Lacks: numeric offsets or IGES (the lines must be digitised from the vector PDF); the capacity comes from the
  author's own hull model, so it checks our generator against another model of the same lines, not against a built
  ship. Licence CC BY-NC-ND 3.0 GR: keep it outside git and do not redistribute derived geometry.
- Alternative, CAP02: Virginia Tech Hibernia shuttle tanker report (2001). Tank bounds and volumes are published and
  cargo capacity is stated at 98% fill (in tonnes at 0.853 t/m3), but the offsets appendix is not in the public PDF.
- Using CAP01 needs a PM decision, because G3 names Tokachi as its reference. G3 says not to tune extents to capacity;
  CAP01 publishes the extents, so none need tuning.

### weights-efficiency public-ship gate (lightship <=20%, attained index <=10%): cannot run

- Frozen cases (Ardmore Gibraltar, Purpose, Persistence): this lane found no public Vref, SFC at 75% MCR, auxiliary
  power or correction factors for them. Their Q88s give lightship (10,354.0; 11,086.7; 10,804.7 t), MCR and the
  owner-reported EEDI/EEXI only. Still blocked.
- One complete public EEDI input set found, WE01 Histria Atlas (IMO 9800790, Constanta Shipyard 2019, 40,000 DWT):
  journal paper (Bosoanca 2020) Fig. 9 gives P_ME 3,907.5 kW (75% of 5,210 kW), Vref 13.98 kn (S/P trials, 75% load),
  SFC_ME 168.3 g/kWh (shop test, ISO corrected), P_AE 416 kW, SFC_AE 234 g/kWh, fi 1.022499, capacity 37,364 t at
  10.6 m; Q88 gives lightship 9,762.1 t and MCR 6,480 kW. Problems: the text says attained EEDI 5.17, the figure
  shows 4.63; the ship name is only in the acknowledgement; the index capacity is at 10.6 m, not the summer draft; no
  lightship breakdown. A second complete case was not found, so the gate's two-case minimum is not met even if the PM
  accepts WE01.
- Power/speed trial points: only the single WE01 point (3,907.5 kW at 13.98 kn, 10.6 m). The full curve exists only as
  a graph (paper Fig. 8).

## Gaps

- No full-particular Aframax/LR2 rows (48 partial owner-list rows only). Suezmax has 5 complete rows (two HHI designs);
  LR1 has 1. Searches for public Aframax/LR2 Q88 PDFs found none outside Scribd or hobby sites.
- VLCC rows depend on a secondary hobby site that mirrors the Miramar Ship Index and Q88 excerpts. Spot checks of three
  random rows matched the page text; the pages themselves are transcriptions. 13 rows carry a year disagreement flag;
  2 rows fail ratio checks (likely source typos) and are excluded from fits.
- `design_id` is a derived grouping (builder group plus rounded Lpp, B, D). Different builder names for one licence
  design can split a design; the sister rule for the reserved ships compensates with a dimension match.
- Draft: only summer (Q88) draft is available; no design draft was published in these sources (`draft_design_m` empty).
- Q88 98% totals differ in slop treatment between owners and even between sisters (4 Fukuoka 25k DWT rows flagged).
- No public lightship weight breakdowns, no EEDI technical files for the frozen weights cases, and only one sea-trial
  point.
- The Histria site is under revision; its Q88 was taken from the Internet Archive copy (URL in the manifest).

## Resume point

Data collection is complete for this batch; nothing is running. To continue:

1. PM decides (a) whether concept-dimensions G2 uses `work/public-tankers/fleet_particulars.csv` as described above,
   (b) whether tank-arrangement G3 may switch its reference to CAP01, (c) whether WE01 is acceptable as one
   weights case (the gate still needs a second complete case).
2. For G3 with CAP01: digitise the vector lines plan (`raw/ntua-58817-vlcc-thesis-20261113/Lines_Plan.pdf`) into
   offsets, check them against the thesis principal particulars and Cb 0.810 before any capacity computation, and
   freeze that check first.
3. For more Aframax/LR2 or weights cases: search owner websites for further public Q88 PDFs and class or yard papers
   with EEDI verification data; add each source in a new `raw/<source>-<date>/` directory and rerun the rebuild
   commands at the top. Check `manifest.tsv` for 0 files without URL.

Checks run: parsers and table build re-run from downloads; coverage script; three random rows spot-checked against
source text; `make secrets` (bounded scan). The Rust, Python and UI quick tiers were not run: this branch changes
only this document.

## Second pass: mid-size tankers, source grades, more cases (2026-11-13)

Coordinator request: at least 60 complete 70,000-170,000 DWT rows (Lpp, B, D, T, DWT, displacement or Cb,
cargo capacity with fill basis, service speed, MCR, engine), prefer primary sources, grade every row, confirm
hobby-site VLCC rows from primary sources, and look again for capacity and EEDI/EEXI cases.

### New columns in `fleet_particulars.csv`

- `source_grade`: `primary` (owner, builder, government docket, journal or thesis document), `secondary` (Auke Visser:
  hobby site that names its sources, Miramar and owner Q88 excerpts), `copied` (scheepvaartwest.be: hobby site that
  copies owner Q88 data and cites nothing).
- `complete_full_spec`: `complete_for_concept_fit` plus cargo capacity with a fill basis, service speed, MCR and engine.
- `primary_confirmation`: for secondary and copied rows, the primary rows with the same IMO (or same name and build
  year when the primary list has no IMO) and whether DWT (0.5%), B (0.1 m), LOA and Lpp (0.5 m) agree.

### New sources (all access date 2026-11-13; downloads and URLs in `manifest.tsv`)

| Source | Grade | Rows / use |
|---|---|---|
| Neda Maritime owner brochures (32-page fleet brochure; Aframax newbuilding sheet) | primary | 11 ships (5 VLCC, 6 Aframax): Lpp, moulded B, D, summer draft, displacement, DWT, 98% capacity incl. slops, MCR (bhp; kW derived x 0.7457). No speed. |
| US MARAD docket MARAD-2018-0114-0004, attachment 17 (three Q88s in one file) | primary | Fontana (Suezmax 2017, complete), Apolytares and Seaways Raphael (VLCC). |
| Imperial Petroleum owner website (6 Q88 / spec PDFs) | primary | 4 MR rows, Suez Protopia (Suezmax, partial: no loadline). |
| Croatian Shipbuilding tankers reference brochure (hb.hr) | primary | 6 design rows (Brodosplit 166k, 114k, 108k, 95k, 75k Ice-1A, 45k): Lpp, B, D, design and scantling draught, DWT at both, SMCR, trial speed, 100% cargo capacity. No displacement. Page 5 values re-read by hand. |
| JSEA "Shipbuilding and Marine Engineering in Japan 2026" (tanker chapters) | primary | ARION (Aframax), IONIC SEMELI (Suezmax): partial (no draft, displacement, capacity). Older editions are not online. |
| scheepvaartwest.be tanker pages (site search for Aframax, Suezmax, LR2, LR1, Panamax and "segregation"; robots.txt allows; disclaimer has no data-use limit) | copied | 330 pages fetched at one request per 1.5-2 s; 220 rows after de-duplication by IMO. |
| NTUA diploma thesis 60283 (108,000 DWT Aframax, 2024, CC BY-NC-ND) | design study | capacity case CAP05 only. |

Searched and not usable: DHT, TORM (Q88 servlet behind a bot challenge; not bypassed), International Seaways (403),
Frontline, Tsakos, Teekay, Scorpio and Euronav (no public spec PDFs live or in the Internet Archive index), KOTC
(under maintenance), class registers (DNV terms unclear; others need accounts), Maersk Tankers (data only through an
undocumented API; not used), Scribd.

### Coverage after the second pass (`python3 -I scripts/coverage.py`)

- Fleet table: 708 rows, 626 unique IMO numbers. Grades: primary 161, secondary 327, copied 220.
- **70,000-170,000 DWT: 227 rows (primary 86, copied 141).**
  - Complete for a concept fit (Lpp, B, D, T, DWT, displacement and so Cb, ratio checks passed): **53 unique ships,
    36 derived designs** (primary 13, copied 40). By segment over all sizes: Aframax/LR2 36, LR1/Panamax 12, Suezmax 8.
  - Complete to the full coordinator list (adds capacity with basis, speed, MCR, engine): **15 ships** (primary 6:
    five Gungen Suezmax and Fontana; copied 9: seven Aframax/LR2, two LR1). Target of 60 **not met**. Most copied
    pages have no displacement or no 98% capacity, and the Neda brochure has no speed.
- All sizes: 245 rows complete for a concept fit; 43 rows complete to the full list.
- VLCC: 327 rows are secondary (Auke Visser). Only **5** could be checked against a primary source (Neda brochure,
  Minerva fleet page, MARAD Q88); all 5 agree on DWT, B, LOA and Lpp. The other 322 remain unconfirmed.
- Copied Aframax/Suezmax rows checked against the Minerva owner page: 9 agree; MINERVA ARIES differs on DWT
  (copied page 1,054,836.5 t, a source typo; the row fails the Cb check and is excluded from fits).
- New quality flags: 15 rows with a cargo capacity implausible for their DWT (capacity not used); rows failing ratio
  checks are excluded from fits.
- Concept-dimensions G2 numbers are unchanged in substance: 110 complete VLCC training rows (52 designs) after the
  sister exclusion; the reserved-ship rows are unchanged.

### Capacity cases (second pass)

No new case has both a usable hull geometry and a published capacity with fill basis. CAP01 (ARGYRO lines plan +
98% tank table) is still the best. Added to `capacity_cases.csv`:
- CAP05, NTUA thesis 60283 (108,000 DWT Aframax design): total cargo 120,185.8 m3 at 98%, per-tank 98% capacities with
  box extents (Xa, Xf, Yp, Ys, Zl, Zu). Hull lines only as figures. Tests tank-box arithmetic, not hull fitting.
- CAP06, WJAETS-2025-1486 Aframax stability paper: offsets at one station only. Not usable as a hull.

### EEDI/EEXI input sets (second pass)

No new complete tanker set was found. Searched: class-society and IMO sample technical files (generic or bulk carrier,
unnamed), ClassNK, IRClass and Tasneef guidance, EEXI papers, Japanese and Croatian builder documents (trial speeds at
design draught and 85-90% SMCR, but no reference speed at 75% MCR, SFC or index value). WE01 Histria Atlas remains the
only complete public set; the weights gate still lacks a second case.

### Second-pass rebuild and resume

Rebuild from downloads (adds to the commands above):

```sh
python3 -I scripts/parse_q88.py q88_primary2_raw.csv - text/primary2/*.txt
python3 -I scripts/parse_neda.py neda_raw.csv raw/brochures-20261113/nedamaritime.gr_img_media_room_brochures_32P-NEDA-WET-CARGO.pdf:6,8,12,16,18,22,26 raw/brochures-20261113/www.nedamaritime.gr_img_media_room_brochures_NedaAframaxNewBuildings.pdf:2
python3 -I scripts/parse_hb.py raw/brochures-20261113/hb.hr_wp-content_uploads_2014_12_tankers.pdf hb_raw.csv
python3 -I scripts/parse_sw.py raw/scheepvaartwest-pages-20261113 sw_raw.csv
python3 -I scripts/build_manifest.py && python3 -I scripts/build_tables.py && python3 -I scripts/coverage.py
```

Resume: to reach 60 full-spec mid-size rows, the missing fields are displacement and 98% capacity. The realistic
primary routes are further owner brochures or Q88 PDFs of the Neda type, and US deepwater-port dockets with Q88
appendices (search regulations.gov dockets MARAD-2019-0011, -0093, -0094 and MARAD-2020-0127 for Q88 attachments).
Fields could also be relaxed by the PM: 53 mid-size ships already have everything except capacity and/or speed. For
the VLCC rows, primary confirmation needs owner Q88 PDFs per ship; none were found in this pass.
