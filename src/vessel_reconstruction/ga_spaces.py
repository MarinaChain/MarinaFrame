"""Commercial GA spaces."""
from __future__ import annotations

from . import source_record
from .ga_commercial_settings import (
    RECORD_VIEWS,
)
from .ga_counts import (
    _number_with_side,
)


def view_of(result: dict, sheet: str, box: list[float]) -> dict | None:
    """The smallest drawn view whose box holds the centre of ``box``."""
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    holding = [v for v in result["views"] if v["sheet"] == sheet
               and v["box_px"][0] <= x <= v["box_px"][2] and v["box_px"][1] <= y <= v["box_px"][3]]
    return min(holding, key=lambda v: (v["box_px"][2] - v["box_px"][0]) * (v["box_px"][3] - v["box_px"][1]),
               default=None)


def add_space(result: dict, space_id: str, kind: str, label: str, number: str | None, status: str,
              region: dict, found_by: str) -> dict:
    """Add one space with its source record and the view it lies in."""
    view = view_of(result, region["sheet"], region["box_px"])
    region = {**region, "view": RECORD_VIEWS.get(view["kind"]) if view else None}
    number = _number_with_side(number, label)
    if status == "read":
        record = source_record.read([region])
    else:
        record = source_record.guessed("identified from the drawn outline by the model; no printed label", [region])
    space = {"id": space_id, "kind": kind, "label": label, "number": number, "status": status,
             "view_id": view["view_id"] if view else None, "found_by": found_by,
             "source_record": source_record.validate(record)}
    result["spaces"].append(space)
    return space
