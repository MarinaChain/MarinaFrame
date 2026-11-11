# New holdout candidates (lane P, research only)

Date: 2026-11-11 (file dated for the 2026-11-12 plan). Branch: `lane/holdout-candidates`, from `continue/v0.5` at 3865d8c.
Status: research only. No sheet was downloaded or opened. No reader was run. No holdout truth was opened.

## Goal

Find 6-10 new public-domain lines drawings for clean holdouts. Each must have a body plan and a printed table of offsets (the truth). The mix must include at least 2 hard-chine or V-bottom hulls, at least 2 round-bilge small craft, and at least 2 larger vessels.

## Method

- Exclusions: vessel names and survey numbers from `benchmarks/spent_real_sheet_holdouts.json`, `benchmarks/holdout_contract.json` (names only), `docs/`, `benchmarks/`, and folder names under `work/holdout/` and `work/` (names only). Sister vessels and same-project sisters are also excluded.
- loc.gov and tile.loc.gov return HTTP 403 (Cloudflare) to scripts and WebFetch. No CAPTCHA was attempted.
- Sheet titles came from Wikimedia Commons file titles (Commons mirrors HAER sheets with the LoC caption and a `Source` link to the LoC sheet). The LoC sheet ID in each row comes from that `Source` link.
- Public-domain books came from archive.org. Offset-table captions were found with the archive.org search-inside API (`fulltext/inside.php`). Only OCR text was read. No page image was opened.
- "Confirmed" means the sheet title or printed caption names an offsets table (or "table of hull measurements"). "Inferred" means the sheet is titled "Lines" only; HAER small-craft lines sheets usually carry an offsets table, but this was not seen.

## Ranked candidates

| Rank | Vessel | Type / hull form | Length | Survey / source | Item URL | Sheet(s) with body plan and offsets | Offsets printed? | Why it is a good test |
|---|---|---|---|---|---|---|---|---|
| 1 | Steam tug EPPLETON HALL (1914) | Steel side-paddle tug; round bilge, large | about 100 ft (confirm on sheet) | HAER CA-63 (call no. HAER CAL,38-SANFRA,167) | https://www.loc.gov/item/ca1508/ | Sheet 2 of 7 "Table of Hull Measurements, Body Plan, Hull Expansion Plan": https://www.loc.gov/resource/hhh.ca1508.sheet/?sp=2 . Sheet 3 of 7 "Body Plan, Half-Breadth Plan, Sheer Plan": https://www.loc.gov/resource/hhh.ca1508.sheet/?sp=3 | Confirmed (sheet title) | Larger steel vessel. Paddle-box sponsons make an unusual body plan. Same Hyde Street Pier drafting style as HERCULES (CA-62, already used), so score it apart from HERCULES results. |
| 2 | Ferry EUREKA (1890) | Wooden double-ended side-wheel ferry; round bilge, very large | about 277 ft hull (confirm) | HAER CA-59 (call no. HAER CAL,38-SANFRA,194-) | https://www.loc.gov/item/ca1504/ | Sheet 3 of 5 "Body Plan, Table of Hull Measurements, Hull Expansion Plan": https://www.loc.gov/resource/hhh.ca1504.sheet/?sp=3 . Sheets 1-2 are half-breadth and sheer plans. | Confirmed (sheet title) | Largest hull on the list. Double-ended, so fore and aft body halves are near mirror images; tests station order and side assignment. Commons TIFF is 17670 x 13632. |
| 3 | V-bottom cruiser ZENITH (W. H. Hand Jr.) | Hard-chine V-bottom power cruiser | 25 ft (caption) | Hand, "Twelve Complete V-Bottom Designs", Vol. III, Motor Boating, New York, 1920 (US, pre-1931, public domain) | https://archive.org/details/twelvecompletevb03hand | Scan index n28 "Table of offsets for 25-foot Hand V-bottom cruiser Zenith"; n29 "Complete set of lines ... including plan, profile and sections": https://archive.org/details/twelvecompletevb03hand/page/n28/mode/1up | Confirmed (printed caption, OCR) | Clean hard-chine V-bottom by the designer who set the type. Printed design offsets, so truth and drawing agree by construction. |
| 4 | V-bottom runabout DOROTHY (W. H. Hand Jr.) | Hard-chine V-bottom runabout | 25 or 28 ft (OCR "2S-foot"; confirm) | Same book as rank 3 | https://archive.org/details/twelvecompletevb03hand | Scan index n24 "Sections of lines and tables of offsets for Dorothy" (body plan and offsets on one page): https://archive.org/details/twelvecompletevb03hand/page/n24/mode/1up | Confirmed (printed caption, OCR) | Body plan and offsets on one page. A finer, faster V-bottom than ZENITH. Same designer and book, so treat 3 and 4 as one family when you report. |
| 5 | 10-foot flat-bottom dinghy (E. B. Schock) | Flat-bottom, hard chine, lapstrake sides | 10 ft | Schock, "How to Build a Rowboat", Rudder Publishing, New York, 1904 (public domain) | https://archive.org/details/howtobuildrowboa00scho | Text (n9) tells the builder to "get the table of offsets and lay off the sheer line". OCR finds an "OFFSETS" plate at scan index n35; the "TEN-FOOT DINGEY" heading is at n39: https://archive.org/details/howtobuildrowboa00scho/page/n35/mode/1up | Inferred, strong (text cites the table; plate OCR shows "OFFSETS") | Second hard-chine family, different designer and period. Flat bottom with a single chine is the simplest chine case. The PM must check that the n35 plate belongs to the 10-ft boat, not the 12-ft or 14-ft boat. |
| 6 | Purse seiner SHENANDOAH (Skansie, 1925) | Wooden purse seiner; round bilge, larger working vessel | about 65 ft (confirm) | HAER WA-178 | https://www.loc.gov/item/wa0757/ | Sheet 3 of 7 "Lines Drawing": https://www.loc.gov/resource/hhh.wa0757.sheet/?sp=3 | Inferred (title says "Lines Drawing" only) | Third larger vessel. Full, deep working-boat sections differ from the fine yacht and skiff forms already used. |
| 7 | Gil Smith P-boat KID | Round-bilge catboat (Great South Bay) | confirm on sheet | HAER NY-341 | https://www.loc.gov/item/ny2038/ | Sheet 1 of 2 "Lines": https://www.loc.gov/resource/hhh.ny2038.sheet/?sp=1 | Inferred | Round-bilge small sailing craft with a wide, shallow catboat section. New builder and region. |
| 8 | Excursion launch MOUNTAINEER | Round-bilge lake launch | confirm on sheet | HAER NY-346 | https://www.loc.gov/item/ny2057/ | Sheet 1 of 2 "Lines": https://www.loc.gov/resource/hhh.ny2057.sheet/?sp=1 | Inferred | Round-bilge power launch, long and narrow. Adirondack Museum, a new source. |
| 9 | Willits Launch | Round-bilge launch by a canoe builder | confirm on sheet | HAER WA-180 | https://www.loc.gov/item/wa0807/ | Sheet 1 of 2 "Lines": https://www.loc.gov/resource/hhh.wa0807.sheet/?sp=1 | Inferred | Round-bilge small craft with canoe-like sections. Same HAER programme (Croteau) as Cama Beach and Davis Boat, so the drafting style is similar; the hull is new. |

Mix check: hard-chine or V-bottom = ranks 3, 4, 5 (two families: Hand 1920 and Schock 1904). Round-bilge small craft = ranks 7, 8, 9. Larger vessels = ranks 1, 2, 6. Offsets confirmed from title or caption = ranks 1, 2, 3, 4.

## Reserves

| Vessel | Source | Note |
|---|---|---|
| MAGNET, 28-ft Hand V-bottom cruiser | Hand 1920, scan index n46 "Complete table of offsets for Magnet" | Confirmed caption. Use if ZENITH or DOROTHY fails. Same family. |
| SHARK, 21-ft Hand runabout; KATHERINE, 30-ft Hand V-bottom cruiser | Hand 1920, n62 and n19 | Confirmed captions. Same family. |
| 12-ft round-bottom sailing dinghy (Schock) | Schock 1904, from n19 | Round-bilge; offsets probably printed. |
| Gil Smith BB catboat LORELEI (NY-342, likely ny2039) and R sloop PAULINE (NY-340) | HAER, sheet 1 "Lines" | Same builder as KID. Use only one Gil Smith boat. |
| R-Boat PIRATE (WA-187, sheet 2 "Lines"), Blanchard Junior Knockabout (WA-181, sheet 1 "Lines") | HAER, Center for Wooden Boats | Round-bilge sailing craft; offsets inferred. |
| Dolphin Club rowboat LAWTON C. HUGHES (HAER CA-2376) | https://www.loc.gov/item/ca4435/ | Record says offsets were generated in 2021. One drawing; sheet title not seen. |
| Trap-net boat JOY (HAER MI-429) and gill-net tugs (MI-421 to MI-426) | Great Lakes Fisheries project | Sheet titles and hull form not seen. Trap-net boats may be hard-chine; check. |

## Rejected

- HERCULES (CA-62): already in the repo acquisition ledger.
- ALKI (OR, `or0594`) and St. Lawrence River skiff NY-561 (`ny2433`): same projects and types as BUMBLE BEE, BUE GIRL, ENDEAVOR and the excluded St. Lawrence skiffs.
- Reserve-fleet ships with lines sheets (Glacier CA-341, General Edwin D. Patrick CA-344, American Racer CA-346, Maritime Victory TX-110, USS Gage VA-133, Husky II AK-52): titles show sheer, half-breadth and body plans but no offsets table. Same MARAD redraw programme as Saugatuck, Empire State V and Arthur M. Huddell.
- Rudder "How to Build a Flattie or Sharpie": no scan found.
- "Nine Motorboats and How to Build Them" (1913, archive.org `ninemotorboatsho00motorich`): mentions a table of offsets and chine construction, but no per-boat caption was confirmed. A possible extra hard-chine source.

## Checks for the PM (in order)

1. In a normal browser, open each LoC sheet URL. Confirm the sheet number, that a body plan is drawn, and that an offsets table is printed. For ranks 6-9, record "confirmed" or "rejected".
2. For ranks 3-5, open the archive.org page. The search-inside index can be off by one from the viewer page; step one page if needed. Confirm body plan and offsets are on the cited pages.
3. Record each accepted case in `benchmarks/holdout_contract.json` before any reader sees it. Write gates before runs.
4. Keep files under `work/holdout/<case>/` (ignored). Do not commit sheets or offsets.

## Resume point

Research is complete. Next step: PM check 1 above. If fewer than 2 hard-chine candidates pass, use the Hand reserves, then search `ninemotorboatsho00motorich` for per-boat offset captions.
