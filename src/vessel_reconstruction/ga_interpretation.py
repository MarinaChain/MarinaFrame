"""Commercial GA interpretation."""
from __future__ import annotations

from . import source_record
from .ga_commercial_settings import (
    APPROXIMATE,
    COUNT_KINDS,
    DEFINITIONS,
    INK_LEVEL,
    LENGTH_FIELDS,
    MIN_INK_CONTRAST,
    MIN_INK_SHARE,
    NOISE_FACTOR,
    PAPER_BAND,
    PLAUSIBLE,
    PURPOSE,
    RULE_CONTINUES_SHARE,
    RULE_MAX_WIDTH_PX,
    SCHEMA,
    SLIVER_SHARE,
    VALUE_SEARCH_SHARE,
)
from .ga_counts import (
    finish_counts,
)
from .ga_images import (
    Tile,
    _sha256,
    load_grey,
)
from .ga_provider import (
    usage_of,
)
from .ga_spaces import (
    add_space,
)
from .particulars import _LENGTH, _PREFIX_LENGTH, _length
from .provenance import write_json
from pathlib import Path
import json
import numpy as np
import re


# ------------------------------------------------------------------ interpretation

def _number_options(text: str) -> list[float]:
    """Every reading of a printed number: a lone comma may be decimal or thousands."""
    text = text.strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", text):
        options = {float(text.replace(",", ""))}
        if text.count(",") == 1 and "." not in text:
            options.add(float(text.replace(",", ".")))
        return sorted(options)
    if re.fullmatch(r"\d+,\d+", text):
        return [float(text.replace(",", "."))]
    if re.fullmatch(r"\d+(\.\d+)?|\.\d+", text):
        return [float(text)]
    return []


def parse_length(printed: str, unit_context: str | None, field: str) -> tuple[float | None, str]:
    """Metres from a printed length, or (None, reason). Ambiguity is refused, never resolved."""
    text = " ".join(APPROXIMATE.sub("", printed).replace(" ", " ").split())
    has_unit = bool(re.search(r"[a-zA-Z'’′\"”]", text))
    if not has_unit and unit_context:
        unit = re.sub(r"[\[\]()]", "", unit_context).strip()
        text = f"{text} {unit}"
    match = _LENGTH.fullmatch(text) or _PREFIX_LENGTH.fullmatch(text)
    if not match:
        return None, f"no unit or unreadable value in {printed[:48]!r}"
    if match.groupdict().get("metric") is not None:
        factor = {"mm": 0.001, "cm": 0.01}.get(match["unit"].lower(), 1.0)
        options = [value * factor for value in _number_options(match["metric"])]
    else:
        options = [_length(match)] if _length(match) is not None else []
    low, high = PLAUSIBLE[field]
    plausible = sorted({round(v, 6) for v in options if v is not None and low <= v <= high})
    if len(plausible) == 1:
        return plausible[0], "parsed"
    if not plausible:
        return None, f"{printed[:48]!r} is not a plausible {field}"
    return None, f"{printed[:48]!r} has more than one plausible reading"


def parse_mass(printed: str, unit_context: str | None) -> tuple[float | None, str]:
    """Metric tonnes from a printed deadweight, or (None, reason)."""
    text = " ".join(APPROXIMATE.sub("", printed).split())
    match = re.fullmatch(r"([\d.,]+)\s*(?:metric\s+)?(t|mt|tonnes?|tons?|m/t|ltons?|long\s+tons?)?\.?", text, re.I)
    unit = (match[2] if match and match[2] else (unit_context or "")).strip().lower()
    if not match or not unit:
        return None, f"no unit or unreadable value in {printed[:48]!r}"
    if "l" in unit.replace("metric", ""):
        return None, "long tons are not converted"
    low, high = PLAUSIBLE["deadweight_t"]
    plausible = sorted({v for v in _number_options(match[1]) if low <= v <= high})
    if len(plausible) == 1:
        return plausible[0], "parsed"
    return None, f"{printed[:48]!r} has no single plausible tonnage"


def _sheet_box(tile: Tile, box_px) -> list[float]:
    """Model box (pixels of the attached image) to source pixels of the tile's sheet."""
    left, top, right, bottom = tile.crop_box_px
    scale_x, scale_y = (right - left) / tile.width, (bottom - top) / tile.height
    x0, y0, x1, y1 = (float(v) for v in box_px)
    return [left + x0 * scale_x, top + y0 * scale_y, left + x1 * scale_x, top + y1 * scale_y]


def _ink_share(ink: np.ndarray, box: list[float]) -> float:
    left, top, right, bottom = (int(round(v)) for v in box)
    patch = ink[max(0, top):max(0, bottom), max(0, left):max(0, right)]
    return float(patch.mean()) if patch.size else 0.0


def image_ink_level(grey: np.ndarray) -> float:
    """The grey level below which a pixel of this image is ink: clearly darker than its paper,
    never below ``INK_LEVEL`` (noise on blank paper never counts)."""
    paper = float(np.median(grey))
    near = grey[grey > paper - PAPER_BAND].astype(np.float64)
    noise = 1.4826 * float(np.median(np.abs(near - np.median(near)))) if near.size else 0.0
    return max(float(INK_LEVEL), paper - max(MIN_INK_CONTRAST, NOISE_FACTOR * noise))


def _ink_runs(inked: np.ndarray, join: int) -> list[list[int]]:
    """[start, stop) of each run of inked columns, joining gaps up to ``join`` columns."""
    runs, current, gap = [], None, 0
    for index, value in enumerate(inked):
        if value:
            if current is not None and gap <= join:
                current[1] = index + 1
            else:
                current = [index, index + 1]
                runs.append(current)
            gap = 0
        elif current is not None:
            gap += 1
    return runs


def value_box(grey: np.ndarray, box: list[float], level: float) -> list[float] | None:
    """The box of a printed value: the model's box when it holds its ink, else the only text run
    beside it in the same rows (within one box width or ``VALUE_SEARCH_SHARE`` of the image width,
    left and right); None when there is no such run or more than one.

    A box with only a sliver of ink (below ``SLIVER_SHARE``) also moves to the one text run beside
    it. Table ruling lines are not text runs.
    """
    height, width = grey.shape
    left, top, right, bottom = (int(round(v)) for v in box)
    top, bottom = max(0, top), min(height, bottom)
    if bottom <= top:
        return None
    ink = grey < level
    share = _ink_share(ink, box)
    if share >= SLIVER_SHARE:
        return box
    rows = bottom - top
    margin = max(right - left, round(VALUE_SEARCH_SHARE * width))
    start, stop = max(0, left - margin), min(width, right + margin)
    # Glyphs of one value are joined across gaps up to most of a text height (the space before
    # the unit); a wider gap starts another run (a label, another value).
    join = max(2, round(0.6 * rows))
    band_above, band_below = ink[max(0, top - rows):top], ink[bottom:min(height, bottom + rows)]

    def ruling_line(run) -> bool:
        columns = slice(start + run[0], start + run[1])
        return (run[1] - run[0] <= RULE_MAX_WIDTH_PX and band_above.size and band_below.size
                and band_above[:, columns].any(axis=1).mean() >= RULE_CONTINUES_SHARE
                and band_below[:, columns].any(axis=1).mean() >= RULE_CONTINUES_SHARE)

    runs = [run for run in _ink_runs(ink[top:bottom, start:stop].any(axis=0), join)
            if run[1] - run[0] >= 2 and not ruling_line(run)]
    if len(runs) != 1:
        return box if share >= MIN_INK_SHARE else None  # a sliver with no single run beside it stays
    # Follow the run beyond the search window to its full width in the same rows.
    whole = _ink_runs(ink[top:bottom].any(axis=0), join)
    run_start, run_stop = start + runs[0][0], start + runs[0][1]
    for full in whole:
        if full[0] <= run_start < full[1]:
            run_start, run_stop = full[0], max(full[1], run_stop)
            break
    found = [float(run_start), float(top), float(run_stop), float(bottom)]
    return found if _ink_share(ink, found) >= MIN_INK_SHARE else None


def interpret(reading: dict, request_dir: Path, sources_dir: Path) -> dict:
    """Turn a completed reading into particulars, counts and spaces with source records."""
    request_dir, sources_dir = Path(request_dir), Path(sources_dir)
    meta = json.loads((request_dir / "sources.json").read_text())
    tiles = {t["image_id"]: Tile(**{**t, "crop_box_px": tuple(t["crop_box_px"])}) for t in meta["tiles"]}
    sources = meta["sources"]

    def role_of(tile: Tile) -> str:
        # Runs before 2026-11-12 name only the file; the view says which source a tile shows.
        if tile.source:
            return tile.source
        return "particulars" if tile.view.startswith("particulars_table") and "particulars" in sources else "ga"

    # Each source is found by its role and checked by its hash: matched by file name alone, a
    # table and a GA of one name (or in two folders) gave the table's boxes the GA's ink.
    ink, sizes, grey, value_level = {}, {}, {}, {}
    for role, source in sources.items():
        file = Path(source["path"]) if source.get("path") and Path(source["path"]).exists() else sources_dir / source["file"]
        if source.get("sha256") and _sha256(file.read_bytes()) != source["sha256"]:
            raise ValueError(f"the {role} source {file.name} is not the file the request was made from")
        grey[role] = np.asarray(load_grey(file))
        ink[role] = grey[role] < INK_LEVEL
        value_level[role] = image_ink_level(grey[role])
        sizes[role] = source["size_px"]
    result = {"schema": SCHEMA, "engineering_approved": False, "model": reading.get("requested_model"),
              "sources": meta["sources"], "usage": usage_of(reading),
              "definitions": {**DEFINITIONS, **meta.get("definitions", {})},
              "particulars": {}, "ship_type": {"value": None, "status": "unknown"},
              "counts": {}, "views": [], "spaces": [], "checks": []}
    reply = (reading.get("reply") or {}).get(PURPOSE)
    if reply is None:
        reason = reading.get("stop_reason") or "the model gave no valid reply"
        for field in [*LENGTH_FIELDS.values(), "deadweight_t"]:
            result["particulars"][field] = {"value": None, "status": "unknown", "reason": reason}
        for name in COUNT_KINDS:
            result["counts"][name] = {"value": None, "status": "unknown", "reason": reason}
        return result

    def region_of(image_id: str, box_normalized, view: str | None = None) -> tuple[dict, float]:
        tile = tiles[image_id]
        box = _sheet_box(tile, box_normalized)
        record = source_record.region(tile.sheet, view=view, box_px=box, page_px=sizes[role_of(tile)])
        return record, _ink_share(ink[role_of(tile)], box)

    for refused in reply.get("refused") or []:
        result["checks"].append({"code": refused["error_code"], "status": "refused",
                                 "label": str(refused["entry"].get("label") or refused["entry"].get("field"))[:64]})
    ship_type = reply["ship_type"]
    if "value" in ship_type:
        result["ship_type"] = {"value": ship_type["value"], "status": "read", "evidence": ship_type["evidence"]}
    else:
        result["ship_type"]["reason"] = ship_type["missing"]

    # Particulars: the model gives printed text; code parses it or abstains.
    printed = {p["field"]: p for p in reply["particulars"]}
    for field, key in [*LENGTH_FIELDS.items(), ("deadweight", "deadweight_t")]:
        entry = printed.get(field)
        if entry is None:
            result["particulars"][key] = {"value": None, "status": "unknown", "reason": "not found printed"}
            continue
        tile = tiles[entry["image_id"]]
        view = "table" if tile.view.startswith("particulars_table") else None
        region, _ = region_of(entry["image_id"], entry["box"], view)
        if key == "deadweight_t":
            value, why = parse_mass(entry["printed"], entry["unit_context"])
        else:
            value, why = parse_length(entry["printed"], entry["unit_context"], key)
        shift = None
        if value is not None:
            # The value must be printed where the model says: ink at the image's own level in its
            # box, or the one ink run beside it in the same rows (holdout exam: boxes 40 px right
            # of light-grey text). A blank box with a blank neighbourhood is refused.
            box = _sheet_box(tile, entry["box"])
            found = value_box(grey[role_of(tile)], box, value_level[role_of(tile)])
            if found is None:
                value, why = None, "the value's box holds no ink"
            elif found != box:
                shift = round(found[0] - box[0])
                region = source_record.region(tile.sheet, view=view, box_px=found, page_px=sizes[role_of(tile)])
        item = {"value": value, "status": "read" if value is not None else "unknown",
                "printed": entry["printed"], "unit_context": entry["unit_context"], "evidence": entry["evidence"]}
        if value is not None and APPROXIMATE.match(entry["printed"]):
            item["approximate"] = True  # printed as "about": the value as printed
        if value is not None and shift is not None:
            item["evidence"] = f"{entry['evidence']} [box moved {shift:+d} px to the only ink in its rows]"
            item["box_shift_px"] = shift
        if value is None:
            item["reason"] = why
        item["source_record"] = source_record.read([region]) if value is not None else source_record.unknown(why)
        result["particulars"][key] = item
    loa, lbp = result["particulars"]["loa_m"], result["particulars"]["lbp_m"]
    if loa["value"] is not None and lbp["value"] is not None and lbp["value"] > loa["value"] * 1.001:
        for item in (loa, lbp):
            item.update(value=None, status="unknown", reason="LBP read longer than LOA")
            item["source_record"] = source_record.unknown("LBP read longer than LOA")
        result["checks"].append({"code": "lbp_above_loa", "status": "check"})

    # Views: where each drawn view lies on the sheet, so every space can name its view.
    for view in reply.get("views") or []:
        region, _ = region_of(view["image_id"], view["box"])
        if region["box_px"] is None:
            continue
        result["views"].append({"view_id": view["view_id"], "kind": view["kind"], "title": view["title"],
                                "sheet": region["sheet"], "box_px": region["box_px"]})

    # Spaces: every item with its region; boxes on blank paper are dropped.
    for index, item in enumerate(reply["items"]):
        region, share = region_of(item["image_id"], item["box"])
        if share < MIN_INK_SHARE or region["box_px"] is None:
            result["checks"].append({"code": "item_box_without_ink", "status": "dropped", "label": item["label"]})
            continue
        kind = item["kind"]
        if item["basis"] == "read":
            # The same text check as the fine pass: a label read as a cargo crane must not say HOSE.
            from .ga_labels import label_kind
            kind = label_kind(kind, item["label"], result["definitions"])
            if kind != item["kind"]:
                result["checks"].append({"code": "coarse_kind_not_in_text", "status": "changed",
                                         "label": item["label"][:64], "kind": item["kind"]})
        add_space(result, f"{kind}-{index + 1:03d}", kind, item["label"], item["number"],
                  "read" if item["basis"] == "read" else "guessed", region, "coarse")
    result["model_counts"] = reply["counts"]
    finish_counts(result)
    return result


def reinterpret_particulars(case_dir: Path, inputs: Path, out_case: Path) -> list[str]:
    """Rebuild the particulars of a stored reading from its stored coarse reply with the current
    checks; no model call. Everything else of the reading stays as stored. Returns the fields
    whose value changed."""
    reading = json.loads((case_dir / "provider" / "vision_reading.json").read_text())
    fresh = interpret(reading, case_dir / "request", inputs)
    stored = json.loads((case_dir / "ga_reading.json").read_text())
    changed = [field for field, item in fresh["particulars"].items()
               if item.get("value") != (stored["particulars"].get(field) or {}).get("value")]
    stored["particulars"] = fresh["particulars"]
    stored["checks"] = ([c for c in stored["checks"] if c.get("code") != "lbp_above_loa"]
                        + [c for c in fresh["checks"] if c.get("code") == "lbp_above_loa"])
    stored.setdefault("passes", {})["particulars_reinterpreted"] = {"changed": changed, "model_calls": 0}
    out_case.mkdir(parents=True, exist_ok=False)
    write_json(out_case / "ga_reading.json", stored)
    return changed
