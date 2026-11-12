"""Accuracy of the GA measuring pass against the drawing's own printed values (no model call).

A printed value is truth only when it was read as printed text and tied to exactly one item;
a measured value is never truth. Two kinds of item have such truth in stored development runs:

- hatch length and breadth: a printed hatch size tied to one hatch (``printed_size`` in the
  arrangement input) against the hatch's measured box (``measured_box_m``), not against the
  printed size that now stands as the hatch's size;
- hold length: a span of the printed dimension chain tied to one hold (``printed_span``) against
  the hold's measured box (``measured_box_m``);
- frame spacing: each printed spacing of the frame table against the spacing that the frame
  numbers of its range show on the fitted scale (ranges with at least ``MIN_RANGE_TICKS``
  numbers; the scale replies are replayed from the stored run, with no model call).

Per-ship rows go to ``--rows`` (keep it under work/); only the aggregate table is printed.

    PYTHONPATH=src python scripts/ga_printed_accuracy.py --hatch-run RUN --scale-run RUN \\
        --inputs INPUTS --rows work/.../rows.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from pathlib import Path

from vessel_reconstruction import ga_scale

THRESHOLDS_M = (0.1, 0.5, 1.0)


def printed_rows(arrangement: dict, case: str) -> list[dict]:
    """Rows (kind, printed, measured) of the hatches and holds whose printed size or printed
    span is tied to them: the printed value against the measured box."""
    rows = []
    for space in arrangement.get("spaces", []):
        extent = space.get("extent") or {}
        measured = extent.get("measured_box_m")
        if space["kind"] == "cargo_hatch" and extent.get("printed_size") and measured:
            axes = (("x_m", "hatch length"), ("y_m", "hatch breadth"))
        elif space["kind"] == "cargo_hold" and extent.get("printed_span") and measured:
            axes = (("x_m", "hold length"),)
        else:
            continue
        for axis, kind in axes:
            if axis in extent and axis in measured:
                rows.append({"case": case, "kind": kind, "item": space["id"],
                             "printed_m": round(extent[axis][1] - extent[axis][0], 3),
                             "measured_m": round(measured[axis][1] - measured[axis][0], 3)})
    return rows


def spacing_rows(ticks: list[tuple[int, float]], spans: list[dict], px_per_m: float, case: str) -> list[dict]:
    """Rows of the printed frame spacings whose range holds enough frame numbers: the printed
    spacing against the spacing the numbers show on the scale (``px_per_m``)."""
    rows = []
    for span in spans:
        inside = [(frame, x) for frame, x in ticks if span["from_frame"] <= frame <= span["to_frame"]]
        if len({frame for frame, _ in inside}) < ga_scale.MIN_RANGE_TICKS:
            continue
        shown_m = abs(ga_scale._range_slope(inside) / px_per_m)
        rows.append({"case": case, "kind": "frame spacing", "item": f"frames {span['from_frame']}-{span['to_frame']}",
                     "printed_m": round(span["spacing_mm"] / 1000.0, 4), "measured_m": round(shown_m, 4)})
    return rows


def summary(rows: list[dict]) -> dict:
    """Per kind: count, median and worst error (m and %), and the share within each threshold."""
    table = {}
    for kind in sorted({row["kind"] for row in rows}):
        errors = [abs(row["measured_m"] - row["printed_m"]) for row in rows if row["kind"] == kind]
        shares = [abs(row["measured_m"] - row["printed_m"]) / row["printed_m"] * 100
                  for row in rows if row["kind"] == kind]
        table[kind] = {"count": len(errors), "median_m": round(statistics.median(errors), 3),
                       "worst_m": round(max(errors), 3), "median_pct": round(statistics.median(shares), 2),
                       "worst_pct": round(max(shares), 2),
                       **{f"within_{limit}_m": sum(error <= limit for error in errors) for limit in THRESHOLDS_M}}
    return table


def scale_work(reading_path: Path, inputs: Path) -> dict | None:
    """The frame-scale working data (ticks, axes, table) of a stored case, from its stored scale
    replies; no model call (a request with no stored reply gets none)."""
    result = json.loads(reading_path.read_text())
    if "ga" not in result.get("sources", {}):
        return None
    case_dir = reading_path.parent
    kept = {}
    original = ga_scale.read_scale

    def recording(*args, **kwargs):
        work = original(*args, **kwargs)
        if work.get("table") is not None:
            kept["work"] = work
        return work

    def stored(request_dir, provider_dir):
        path = case_dir / "scale" / f"{request_dir.name}-provider" / "vision_reading.json"
        if path.exists() and request_dir.name.startswith("scale"):
            return json.loads(path.read_text())
        return {"reply": None, "stop_reason": "not replayed here", "usage": {}, "receipts": []}

    ga_scale.read_scale = recording
    try:
        with tempfile.TemporaryDirectory() as scratch:
            ga_scale.scale_pass(result, inputs / result["sources"]["ga"]["file"], Path(scratch), stored)
    finally:
        ga_scale.read_scale = original
    work = kept.get("work")
    if work is None:
        return None
    return {"work": work, "frames": result.get("frames") or {}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hatch-run", type=Path, nargs="*", default=[],
                        help="Runs (<case>/ga_arrangement_input.json) with printed hatch sizes or chain spans.")
    parser.add_argument("--scale-run", type=Path, help="A stored run with scale replies (<case>/ or <group>/<case>/).")
    parser.add_argument("--inputs", type=Path, help="The folder of the case images (for the scale replay).")
    parser.add_argument("--rows", required=True, type=Path, help="Per-ship rows (keep under work/).")
    args = parser.parse_args(argv)
    rows = []
    for run in args.hatch_run:
        for path in sorted(run.glob("GA-*/ga_arrangement_input.json")):
            rows += printed_rows(json.loads(path.read_text()), path.parent.name)
    if args.scale_run:
        for reading_path in sorted(list(args.scale_run.glob("*/GA-*/ga_reading.json"))
                                   + list(args.scale_run.glob("GA-*/ga_reading.json"))):
            data = scale_work(reading_path, args.inputs)
            if data is None:
                continue
            scale = data["frames"].get("scale") or {}
            view = scale.get("view_id")
            axis = data["work"]["axes"].get(view)
            ticks = [(frame, x) for frame, x, _ in data["work"]["raw"]["ticks"].get(view, [])]
            if axis is not None and ticks:
                rows += spacing_rows(ga_scale.consistent_ticks(ticks), data["frames"]["spacings"], axis.px_per_m,
                                     reading_path.parent.name)
    args.rows.parent.mkdir(parents=True, exist_ok=True)
    args.rows.write_text(json.dumps(rows, indent=1))
    print(json.dumps(summary(rows), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
