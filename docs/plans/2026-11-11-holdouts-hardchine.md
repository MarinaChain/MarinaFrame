# Lane E: new hard-chine holdout data (2026-11-11)

Branch `lane/holdouts-hardchine` from `continue/v0.5` (`4f03667`). Data lane: no reader runs, no
existing holdout truth or sealed folders opened.

## Goal

Find up to four unseen public-domain hard-chine or deadrise vessels (LoC HAER/HABS) with a body
plan and a printed table of offsets. Download the sheets to `work/holdout/<boat>/`, transcribe the
table into the truth format of `benchmarks/deadrise_holdout/score.py` (`parse_truth`), check the
bow/stern side assignment twice (lesson of 2026-11-09), and commit one protocol per boat with
pinned SHA-256 values before any run.

## Update (2026-11-11, after the PM download)

The PM downloaded two sheets through a normal browser. Both SHA-256 values match SOURCE.md.
- Cama Beach Skiff No. 22 (WA-199): hard-chine. Truth frozen (`work/holdout/cama_beach_skiff_22/truth.json`,
  SHA-256 `473ef776...1b1e`; two blind readings agree on all 77 cells). Sides read twice and in
  agreement. Protocol committed: `docs/BODY_PLAN_CHINE.md`, "Holdout protocol: CAMA BEACH SKIFF No. 22".
- Davis Boat (WA-227): round-bilge double-ender, dropped.
- KATHRYN: not downloaded (rounded chine).

**Resume point:** calibration of CAMA BEACH SKIFF No. 22 by an agent that has not seen the truth
(step 1 of its protocol), then one run. No reader has run on it.

## Earlier state: BLOCKED at the download step (no sheet, no truth, no protocol)

Access checks from this host on 2026-11-11:

| Route | Result |
|---|---|
| `curl` to `www.loc.gov` search JSON, `/pictures/item/`, `memory.loc.gov`, `cdn.loc.gov` | HTTP 403, Cloudflare "Just a moment" page |
| `curl` to `tile.loc.gov` (IIIF `info.json`, image, data PDF) | HTTP 403 |
| Built-in browser pane (Chromium) to `www.loc.gov` | Cloudflare page, then a "Verify you are human" checkbox. This is a CAPTCHA; it was not clicked. |
| Claude in Chrome (user's own browser) | Extension not connected |
| Wikimedia Commons (mirrors part of HABS/HAER) | Reachable. Has KATHRYN and LOUISE TRAVERS photographs, but no Chesapeake hard-chine lines sheet. All 55 HAER "Lines" sheet titles on Commons are round-bilge, lapstrake or ship sheets. |
| `loc.getarchive.net` (third-party LoC mirror) | HTTP 403 |

So no file was downloaded, no `work/holdout/<boat>/` folder was made, no truth was read and no
protocol can pin a sheet hash. Nothing was committed except this file.

## Candidates (from web search; LoC pages not opened from here)

Exclusions: every vessel named in `benchmarks/`, `docs/` or `tasks/` (CALEB JONES, E. C. COLLIER,
WHITE GULL, COLLEEN, PARDON ME, BUMBLE BEE 47, BUE GIRL, BALCLUTHA, C. A. THAYER, WAPAMA, Au Sable
River Boat MI-409, St. Lawrence skiffs NY-559/560, Mukilteo WA-224, Saginaw gig VA-146, and the
others found by `rg -i 'haer [a-z]{2}-?[0-9]+|hhh\.'`). KATHRYN is named only as an unlocated
candidate row in `docs/BODY_PLAN_CHINE.md` ("Holdout candidates"); it was never downloaded or run.

| Rank | Vessel | HAER | LoC URLs | Hull form | Offsets table | Note |
|---|---|---|---|---|---|---|
| 1 | Skipjack KATHRYN (1901), Tilghman MD | MD-117 | item https://www.loc.gov/item/md1454/ ; sheets https://www.loc.gov/resource/hhh.md1454.sheet/ | Skipjack, V-bottom (NHL nomination: V-bottom with a "rounded chine") | Not confirmed; 8 measured drawings | Best fit. Check that one sheet has a body plan and a printed table. The rounded chine is a risk for chine cells. |
| 2 | Cama Beach Skiff No. 22, Camano Island WA | WA-199 | https://www.loc.gov/resource/hhh.wa0881.sheet/ | Unknown (rental rowing skiff; may be flat-bottom hard-chine) | Sheet title "Lines Plans with Table of Offsets" | Use only if the body plan shows a hard chine. |
| 3 | 14'-3" Double Ended Davis Boat, Seattle WA | WA-227 | https://www.loc.gov/resource/hhh.wa0928.sheet | Probably round or lapstrake | "Profile, body plan, table of offsets" | Low; reject if not hard-chine. |
| - | Bugeye EDNA E. LOCKWOOD (MD-167, `md1812`), bugeye LOUISE TRAVERS (MD-55, `md1071`) | | https://www.loc.gov/item/md1812 ; https://www.loc.gov/resource/hhh.md1071.sheet | Log-built, round bilge | | Not hard-chine: rejected. |

No other HAER skipjack, deadrise, buyboat or draketail set with lines was found by search
(REBECCA T. RUARK, HILDA M. WILLING and others have NHL or MHT files, not HAER drawings).

Rights: HAER drawings are US Government works; the LoC rights advisory for HABS/HAER states no
known restrictions. Confirm on each item page when downloading.

## Resume point (needs a person)

1. A person opens each candidate's LoC sheet page in a normal browser (the Cloudflare check passes
   for a person), confirms hull form and that a body plan and a printed table of offsets are on
   the sheet, and downloads the master TIFF (or the largest JPEG) into a new empty folder
   `work/holdout/<boat>/` (for example `work/holdout/kathryn/`), with the item URL and rights line
   in `work/holdout/<boat>/SOURCE.md`. No one else opens the folder.
2. Lane E (or any lane that never sees reader output) then, per boat:
   - records `shasum -a 256` of each sheet in SOURCE.md;
   - transcribes the printed table into `work/holdout/<boat>/truth.json` in the `parse_truth`
     format: `{"units": "ft-in-eighths", "stations": [...], "x_positions": [...], "heights":
     {"SHEER": [...], "CHINE": [...], "RABBET": [...]}, "half_breadths": {"SHEER": [...],
     "CHINE": [...], "RABBET": [...], "WL <h>": [...]}, "notes": {...}, "unsure": [...]}`; values
     as printed ("5-2-4+"), blank or illegible cells null;
   - a second agent re-reads the table in its own crops and the two transcriptions are diffed;
     each disagreement is resolved from the sheet or set to null and listed in `unsure`;
   - side check: reading 1 = station labels in the body plan; reading 2 = stem and transom
     position in the profile and half-breadth plan against the body-plan halves, by a different
     agent; both recorded; stop if they disagree;
   - records the truth SHA-256.
3. Commit, before any run, a section "Holdout protocol: <BOAT>" in `docs/BODY_PLAN_CHINE.md`
   modelled on "Holdout protocol: CALEB JONES": sheet and truth SHA-256, pinned reader file
   hashes at that commit, both side readings, cells and metrics, gates (unchanged from CALEB
   JONES), one run, no tuning. The calibration module `benchmarks/<boat>/holdout_value.py` is
   written by a different agent that never opens `truth.json` or the table crops, because this
   lane will have read the table.

## Verification

Checked: the branch is cut from `origin/continue/v0.5` at `4f03667`; only this file changes;
no file under `work/holdout/` was opened.
