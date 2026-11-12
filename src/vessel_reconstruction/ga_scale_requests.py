"""Commercial GA requests; rules and constants unchanged."""
from __future__ import annotations

from .ga_scale_overlaps import (
    _label_centre,
)
from .ga_scale_settings import (
    EXTENT_PRIORITY,
    EXTENT_SPACES_PER_REQUEST,
    MAX_EXTENT_REQUESTS,
    MAX_IMAGES,
    PLAN_KINDS,
    PLAN_PLACES,
    PROFILE_PLACES,
    PURPOSE,
    REQUEST_SCHEMA,
    VIEW_PAD_X,
    VIEW_PAD_Y,
)
from .provenance import write_json
from PIL import Image
from pathlib import Path
import hashlib
import math
import re

import numpy as np


# ------------------------------------------------------------------ request images

def _pad(box, sheet_size) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    pad_x, pad_y = (right - left) * VIEW_PAD_X, max(40.0, (bottom - top) * VIEW_PAD_Y)
    return (max(0, math.floor(left - pad_x)), max(0, math.floor(top - pad_y)),
            min(sheet_size[0], math.ceil(right + pad_x)), min(sheet_size[1], math.ceil(bottom + pad_y)))


def chosen_views(result: dict) -> dict[str, dict]:
    """The largest profile, deck plan and tank top plan of a reading, by kind."""
    def area(view):
        left, top, right, bottom = view["box_px"]
        return (right - left) * (bottom - top)
    chosen = {}
    for kind in ("profile", *PLAN_KINDS):
        views = [v for v in result.get("views", []) if v["kind"] == kind]
        if views:
            chosen[kind] = max(views, key=area)
    return chosen


def _write_request(plan: list[tuple[str, str, tuple, float]], sheet_path: Path, out: Path, context) -> None:
    """One ``ga_scale`` request directory: (image_id, view, sheet box, scale) images of the sheet.

    ``context`` is the request context, or a function of ``{image_id: (width, height)}`` that
    returns it. Images can be sent smaller than planned (request size), so anything in image
    pixels must come from the sizes actually written.
    """
    from . import ga_commercial_settings, ga_images
    out.mkdir(parents=True, exist_ok=False)
    sheet = Image.open(sheet_path).convert("L")
    for grey_levels, shrink in [(None, 1.0), (ga_commercial_settings.REDUCED_GREY_LEVELS, 1.0),
                                *[(ga_commercial_settings.REDUCED_GREY_LEVELS, 0.9 ** k) for k in range(1, 12)]]:
        encoded = [ga_images._png(sheet.crop(box), scale * shrink, grey_levels) for _, _, box, scale in plan]
        if sum(len(data) for data, _, _ in encoded) <= ga_commercial_settings.MAX_TOTAL_IMAGE_BYTES:
            break
    else:
        raise ValueError("the images do not fit the provider request size")
    entries, tiles = [], []
    for (image_id, view, box, _), (data, width, height) in zip(plan, encoded):
        (out / f"{image_id}.png").write_bytes(data)
        entries.append({"image_id": image_id, "file": f"{image_id}.png", "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data), "width": width, "height": height, "view": view,
                        "crop_box_px": list(box)})
        tiles.append({"image_id": image_id, "view": view, "sheet": Path(sheet_path).name,
                      "crop_box_px": list(box), "width": width, "height": height})
    if callable(context):
        context = context({entry["image_id"]: (entry["width"], entry["height"]) for entry in entries})
    write_json(out / "request.json", {
        "schema_version": REQUEST_SCHEMA, "purpose": PURPOSE,
        "source_sha256": hashlib.sha256(Path(sheet_path).read_bytes()).hexdigest(),
        "engineering_approved": False, "context": context, "images": entries})
    write_json(out / "sources.json", {"tiles": tiles})


def _spacing_note_box(sheet_path: Path, view_boxes: list[tuple]) -> tuple | None:
    """Locate uncovered spacing-note lines; OCR never supplies a measured value.

    Use the existing optional local OCR reader. Missing OCR leaves the view request
    unchanged. One enclosing crop keeps all found notes within one image slot.
    """
    from .sheet_types import ocr_read

    with Image.open(sheet_path) as image:
        gray = np.asarray(image.convert("L"))
    words = []
    ocr_read(gray, side=max(gray.shape), words_out=words)
    lines = {}
    for word in words:
        lines.setdefault(tuple(word["line"]), []).append(word)
    uncovered = []
    for line in lines.values():
        text = " ".join(word["text"] for word in line).upper()
        if not re.search(r"\b(?:FRAME\s+SPAC(?:ING|E)|FR\.?\s*SP\.?|F\s*\.\s*S\.)", text):
            continue
        boxes = [word["bbox"] for word in line]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        if not any(v[0] <= box[0] and v[1] <= box[1] and v[2] >= box[2] and v[3] >= box[3]
                   for v in view_boxes):
            uncovered.append(box)
    if not uncovered:
        return None
    return _pad((min(b[0] for b in uncovered), min(b[1] for b in uncovered),
                 max(b[2] for b in uncovered), max(b[3] for b in uncovered)),
                (gray.shape[1], gray.shape[0]))


def prepare_scale(result: dict, sheet_path: Path, out: Path, previous_reason: str | None = None) -> bool:
    """The request that reads the frame scale: the profile and the plans in high-resolution parts.

    A request sent again after a refused reading says why the reading was refused, so the model
    looks again for what was missing (for example the drawn mark where the spacing changes).
    """
    from . import ga_commercial_settings, ga_images
    views = chosen_views(result)
    wanted = [views[kind] for kind in ("profile", "deck_plan", "tank_top_plan") if kind in views]
    if not wanted:
        return False
    sheet_size = Image.open(sheet_path).size
    boxes = [_pad(view["box_px"], sheet_size) for view in wanted]
    note_box = _spacing_note_box(sheet_path, boxes)
    image_slots = MAX_IMAGES - (1 if note_box else 0)
    plan = []
    for index, (view, (left, top, right, bottom)) in enumerate(zip(wanted, boxes)):
        # Share spare slots in view order so the note need not remove a tile from every view.
        limit = image_slots // len(wanted)
        if note_box and index < image_slots % len(wanted):
            limit += 1
        best = (1, ga_images._fit_scale(right - left, bottom - top))
        for columns in range(2, limit + 1):
            width = (right - left) / columns * (1 + ga_commercial_settings.TILE_OVERLAP)
            scale = ga_images._fit_scale(width, bottom - top) * ga_commercial_settings.SCALE_MARGIN
            if scale > best[1] * 1.05:
                best = (columns, scale)
        columns, scale = best
        for part, box in enumerate(ga_images.tile_boxes(right - left, bottom - top, columns, 1)):
            plan.append((f"{view['view_id']}p{part + 1}", f"{view['kind']}:{view['view_id']}:part{part + 1}",
                         (left + box[0], top + box[1], left + box[2], top + box[3]), scale))
    context = {"want": ["scale"]}
    if note_box:
        # The unchanged parser joins spacing labels and ticks by view ID. A sheet
        # note belongs to the profile's scale, or the first plan when no profile exists.
        view = wanted[0]
        image_id = f"{view['view_id']}note"
        scale = ga_images._fit_scale(note_box[2] - note_box[0], note_box[3] - note_box[1])
        plan.append((image_id, f"{view['kind']}:{view['view_id']}:spacing_note", note_box, scale))
        context["spacing_note"] = (f"{image_id} shows printed frame-spacing notes outside the view crops. "
                                   "Read the printed notes from this image; it is not another drawing view.")
    if previous_reason:
        context["previous_attempt"] = (f"The previous reading of this frame scale was refused: {previous_reason}. "
                                       "Look again at the whole scale, also for every drawn mark where the frame "
                                       "spacing changes (an arrow end, a tick or a dimension line end).")
    _write_request(plan, sheet_path, out, context)
    return True


def missing_places(work: dict) -> list[str]:
    """Named places and perpendicular marks that the scale request did not point.

    The first extents request names them, so the model points what the measurements still need
    (development round u3: F.P. or a shell side left out, so LBP or breadth was not measured).
    """
    raw = work.get("raw") or {}
    kinds = work["kinds"]
    named = {view: set(places) for view, places in raw.get("points", {}).items()}
    profile = [view for view, kind in kinds.items() if kind == "profile"]
    plans = [view for view, kind in kinds.items() if kind in PLAN_KINDS]
    missing = []
    if profile:
        missing += [name for name in PROFILE_PLACES if not any(name in named.get(v, ()) for v in profile)]
    if plans and not any(set(PLAN_PLACES) <= named.get(v, set()) for v in plans):
        missing += [name for name in PLAN_PLACES if not any(name in named.get(v, ()) for v in plans)]
    # The LBP needs A.P. and F.P. on the profile's frame scale, so they count there only.
    marks = {name for view in profile for name in raw.get("marks", {}).get(view, {})}
    if profile:
        missing += [label for name, label in (("ap", "A.P."), ("fp", "F.P.")) if name not in marks]
    return missing


def prepare_extents(result: dict, sheet_path: Path, out: Path, missing: list[str] = (),
                    only_ids: set[str] | None = None,
                    exclude: dict[str, list[dict]] | None = None) -> list[Path]:
    """The requests that box the drawn boundary of each read space: one image per whole view.

    The spaces go out in requests of ``EXTENT_SPACES_PER_REQUEST`` (at most
    ``MAX_EXTENT_REQUESTS``), holds and tanks first; only the first request also asks for the
    named places. ``exclude`` gives, per space id, the spaces whose labels its box must not hold
    (a redrawn box). Returns the request directories (``out``, ``out-2``, ...); empty when
    nothing can be asked.
    """
    from . import ga_commercial_settings, ga_images
    views = chosen_views(result)
    if not views:
        return []
    sheet_size = Image.open(sheet_path).size
    plan, boxes = [], {}
    for view in views.values():
        box = _pad(view["box_px"], sheet_size)
        scale = ga_images._fit_scale(box[2] - box[0], box[3] - box[1])
        boxes[view["view_id"]] = (box, scale)
        plan.append((view["view_id"], f"{view['kind']}:{view['view_id']}", box, scale))
    spaces = _extent_spaces(result, views, boxes, only_ids, exclude)
    if not spaces:
        return []
    order = {kind: index for index, kind in enumerate(EXTENT_PRIORITY)}
    # Stable: within a kind, labels with a known place first, then reading order.
    spaces.sort(key=lambda entry: order.get(entry["kind"], len(order)))  # stable: reading order within a kind
    # Labels with a known place and labels from a shared crop ("near") go in separate requests,
    # the known ones first: mixed in one request, the model marked most boxes "uncertain"
    # (round u9n: outline boxes fell from 23 of 52 to 10 of 77 on one ship).
    known = [entry for entry in spaces if "near" not in entry]
    near = [entry for entry in spaces if "near" in entry]
    chunks = ([known[i:i + EXTENT_SPACES_PER_REQUEST] for i in range(0, len(known), EXTENT_SPACES_PER_REQUEST)]
              + [near[i:i + EXTENT_SPACES_PER_REQUEST] for i in range(0, len(near), EXTENT_SPACES_PER_REQUEST)])
    chunks = chunks[:MAX_EXTENT_REQUESTS]
    directories = []
    for index, chunk in enumerate(chunks):
        want = ["extents", "points"] if index == 0 else ["extents"]
        note = None
        if index == 0 and missing:
            note = {"places": list(missing),
                    "note": "These were not pointed yet; point each one that is drawn. Named places go in "
                            "points; the perpendicular marks go in ticks, at the frame scale."}

        context = _extent_context(boxes, chunk, want, note)

        directory = out if index == 0 else out.with_name(f"{out.name}-{index + 1}")
        _write_request(plan, sheet_path, directory, context)
        directories.append(directory)
    return directories


def _extent_spaces(result, views, boxes, only_ids, exclude):
    profile = views.get("profile")
    spaces = []
    # Several labels read from one crop of the fine pass share its region; the place of each
    # label is then not known, so its boundary cannot be asked for.
    shared: dict[tuple, int] = {}
    for space in result["spaces"]:
        key = tuple(space["source_record"].get("regions", [{}])[0].get("box_px") or ())
        shared[key] = shared.get(key, 0) + 1
    for space in result["spaces"]:
        if space["status"] != "read" or (only_ids is not None and space["id"] not in only_ids):
            continue
        in_shared_crop = shared[tuple(space["source_record"]["regions"][0]["box_px"] or ())] > 1
        entry = {"space_id": space["id"], "kind": space["kind"], "label": space["label"][:64]}
        if space["view_id"] in boxes and in_shared_crop:
            # Several labels were read from one crop of the fine pass: the place of this label
            # in it is not known. The crop goes as "near" with the label text (round u8: 457
            # read spaces, 48 of them fuel tanks, were never asked for).
            entry.update(image_id=space["view_id"], at=None,
                         near=tuple(space["source_record"]["regions"][0]["box_px"]))
        elif in_shared_crop:
            continue
        elif space["view_id"] in boxes:
            region = space["source_record"]["regions"][0]["box_px"]
            # The label centre in sheet pixels; it is put in image pixels once the image size is known.
            entry.update(image_id=space["view_id"],
                         at=((region[0] + region[2]) / 2, (region[1] + region[3]) / 2))
            if exclude and space["id"] in exclude:
                entry["exclude"] = [{"label": other["label"][:64], "at": _label_centre(other)}
                                    for other in exclude[space["id"]]]
        elif space["kind"] == "accommodation_deck" and profile:
            entry.update(image_id=profile["view_id"], at=None)
        else:
            continue
        spaces.append(entry)
    return spaces


def _extent_context(boxes, chunk, want, note):
    def context(sizes: dict, chunk=chunk, want=want, note=note) -> dict:
        placed = []
        for entry in chunk:
            if entry["at"] is not None:
                (left, top, right, bottom), _ = boxes[entry["image_id"]]
                width, height = sizes[entry["image_id"]]

                def in_image(point, left=left, top=top, right=right, bottom=bottom, width=width, height=height):
                    return [round((point[0] - left) * width / (right - left)),
                            round((point[1] - top) * height / (bottom - top))]

                entry = {**entry, "at": in_image(entry["at"])}
                if "exclude" in entry:
                    entry["exclude"] = [{**other, "at": in_image(other["at"])} for other in entry["exclude"]]
            if entry.get("near") is not None:
                (left, top, right, bottom), _ = boxes[entry["image_id"]]
                width, height = sizes[entry["image_id"]]
                near = entry["near"]
                entry = {**entry, "near": [round((near[0] - left) * width / (right - left)),
                                           round((near[1] - top) * height / (bottom - top)),
                                           round((near[2] - left) * width / (right - left)),
                                           round((near[3] - top) * height / (bottom - top))]}
            placed.append(entry)
        context = {"want": want, "spaces": placed}
        if note:
            context["missing"] = note
        return context

    return context
