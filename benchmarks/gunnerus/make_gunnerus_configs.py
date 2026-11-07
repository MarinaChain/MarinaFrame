"""Write the Gunnerus vector and raster configurations from the lines-plan drawing.

Every value here is read from the lines-plan drawing (DXF for the vector
path, rendered PDF pixels for the raster path) by rules stated below and
written down before any Gunnerus run. No truth data is read. All values are
assistant-read and provisional.

Station identity rules (vector path, body plan on layer 03_Lines_Frames1):

1. Frame positions come from the profile grid: each 00_Grid frame label
   (MTEXT "0", "5", ..., "27", "A".."J", "28", ...) sits next to a short
   00_Grid tick; x = (tick X - tick X of frame 0) / 1000 m.
2. Forward body (right of the centreline), straight raked keel: the labels
   #40, #45 and #50 mark their nearest station curve. The curves' keel heights
   (where they leave the centreline) are linear in x along the raked keel. A
   curve whose keel height lies within 0.2 frame of a whole frame by this rule
   takes that frame; other curves are not used.
3. Forward body, stem: curves that leave the centreline above the straight
   keel are ordered by keel height; labels #55 and #58 must match the count.
   Upper bow pieces (leaving the centreline above WL 3000) are ordered the
   same way and must match labels #55 and #60. Stations #55-#58 are drawn as
   a lower (bulb) piece and an upper piece; both picks are passed so the
   reader abstains on them.
4. Aft body (left of the centreline): curves (or curve pieces split at skeg
   junctions) that leave the centreline are ordered by keel height, highest
   (aftmost) first;
   labels #0, #5, #10, #15 and #20 must match the count. Frames 21-27 and
   A-G are not identified by this rule: their keel heights converge and the
   drawing gives no label to anchor them.

Round 2 rules (``vector_config(round2=True)``, the default; ``round2=False``
reproduces the round 1 configuration):

5. Midbody (aft pieces after frame 20): each curve is compared with the
   half-breadth plan. At every labelled waterline up to WL 1800 the curve's
   outer half-breadth must equal the plan waterline's half-breadth at the
   frame (lines_dxf.cross_view_identity: RMS <= 0.05 m, second-best frame at
   least 2x worse, one curve per frame). Curves that fail are not used; a
   frame with no matching curve is not read.
6. Station top: each station ends at the upper crossing of the centreline
   profile outline (the closed curve on the buttock layer) when that is below
   the drawn top of the station curves (WL 7586.5). A curve that ends on the
   side line follows it to this height.
7. Stations are read as outline regions (multi-region sections), so twin-skeg
   and bulb stations are no longer refused.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from vessel_reconstruction import lines_dxf
from vessel_reconstruction.lines_dxf import _distance_to_polyline

CENTRELINE_X = 58433.8      # body-plan centreline (BT labels symmetric about it)
BASELINE_Y = 25121.5        # BASELINE: WL 250 grid at 25371.5 less 250 mm
SIDE_X = (53633.8, 63233.8)  # drawn vertical side lines, BT -4800 / +4800
TOP_Y = 32708.0             # upper end of every full station curve
VIEW_BOUNDS = (53500.0, 24400.0, 63400.0, 32800.0)
LAYER = "03_Lines_Frames1"
ENDPOINT_TOLERANCE = 1.0
# Round 2 (docs/BENCHMARK_GUNNERUS.md section 7). The profile and the plan share
# the body plan's drawing x: the transom is at X = 14343.7 in both, and the
# profile grid tick of frame 0 is at X = 15343.7.
PROFILE_FRAME0_X = 15343.7
PLAN_FRAME0_X = 15343.7
BASELINE_PROFILE_Y = BASELINE_Y       # the profile keel line sits on the same BASELINE
PLAN_BOUNDS = (12000.0, 16400.0, 52000.0, 22000.0)
PLAN_CENTRELINE_Y = 16646.0           # plan CL; the 4.8 m side line is at 21446
# Stem and bulb pieces end on the drawn stem bar, 50 mm off the centreline; an
# end within 0.1 m of the centreline is closed horizontally to it.
CENTRELINE_CLOSURE_M = 0.1


def frame_positions(doc) -> dict[str, float]:
    """Frame label -> x (m) from the profile grid ticks and their labels."""
    ticks = sorted({round(e.dxf.start.x, 1) for e in doc.modelspace()
                    if e.dxftype() == "LINE" and e.dxf.layer == "00_Grid"
                    and abs(e.dxf.start.x - e.dxf.end.x) < 1e-6 and 25000 < e.dxf.start.y < 25300})
    ticks = np.array(ticks)
    labels = {}
    for e in doc.modelspace():
        if e.dxftype() == "MTEXT" and e.dxf.layer == "00_Grid" and abs(e.dxf.insert.y - 24657.3) < 1:
            text = re.sub(r"\\[A-Za-z][^;]*;|[{}]", "", e.text).strip()
            # Labels sit just left of their tick (about 75-110 units).
            right = ticks[ticks > e.dxf.insert.x]
            labels[text] = float(right[0])
    zero = labels["0"]
    return {name: round((x - zero) / 1000.0, 4) for name, x in labels.items()}


def frame_name(x: float, frames: dict[str, float]) -> str:
    for name, value in frames.items():
        if abs(value - x) < 1e-6:
            return name
    # Frames between labelled ticks: integer frames are 0.5 m apart outside the
    # lettered block A-J (x 14.0-18.5), where numbering skips by ten.
    n = x / 0.5 if x < 14.0 else x / 0.5 - 10
    return str(int(round(n)))


def distinctive_point(index: int, chains: list[np.ndarray]) -> list[float]:
    """Vertex of a chain farthest from every other chain (endpoints excluded)."""
    chain = chains[index]
    others = [c for k, c in enumerate(chains) if k != index]
    candidates = chain[len(chain) // 10: len(chain) - len(chain) // 10: max(1, len(chain) // 60)]
    if not len(candidates):
        candidates = chain
    best, best_distance = candidates[0], -1.0
    for point in candidates:
        distance = min(_distance_to_polyline(point, c) for c in others)
        if distance > best_distance:
            best, best_distance = point, distance
    return [float(best[0]), float(best[1])]


def label_points(doc) -> dict[str, list[tuple[np.ndarray, float]]]:
    """Station labels: text -> [(insertion point, rotation in degrees)]."""
    found: dict[str, list[tuple[np.ndarray, float]]] = {}
    for e in doc.modelspace():
        if e.dxftype() == "TEXT" and re.fullmatch(r"#\d+", e.dxf.text) and VIEW_BOUNDS[0] < e.dxf.insert.x < VIEW_BOUNDS[2]:
            found.setdefault(e.dxf.text, []).append((np.array([e.dxf.insert.x, e.dxf.insert.y]), float(e.dxf.rotation)))
    return found


def _closest_point(point: np.ndarray, polyline: np.ndarray) -> np.ndarray:
    a, b = polyline[:-1], polyline[1:]
    ab = b - a
    t = np.clip(((point - a) * ab).sum(axis=1) / np.maximum((ab ** 2).sum(axis=1), 1e-30), 0.0, 1.0)
    nearest = a + t[:, None] * ab
    return nearest[int(np.argmin(np.hypot(*(nearest - point).T)))]


def labelled_chain(label: tuple[np.ndarray, float], chains: list[np.ndarray], allowed: list[int]) -> int:
    """Nearest curve on the lower side of the label text.

    Labelling convention of this drawing: a station label is written just
    above its curve, so the curve lies on the text's lower side. The labels
    whose identity is fixed by other evidence (#40/#45/#50 by the keel rake,
    #58, #60 and the upper #55 as the only nearby curve) all follow it.
    """
    point, rotation = label
    angle = np.radians(rotation)
    up = np.array([-np.sin(angle), np.cos(angle)])
    below = [k for k in allowed if float((_closest_point(point, chains[k]) - point) @ up) < 0]
    return min(below, key=lambda k: _distance_to_polyline(point, chains[k]))


def vector_config(dxf: Path, round2: bool = True) -> tuple[dict, list[dict]]:
    import ezdxf

    doc = ezdxf.readfile(str(dxf))
    frames = frame_positions(doc)
    view = lines_dxf.BodyPlanView(centreline_x=CENTRELINE_X, baseline_y=BASELINE_Y, units_per_metre=1000.0,
                                  bounds=VIEW_BOUNDS, layers=(LAYER,), flatten_tolerance=0.5,
                                  join_tolerance=ENDPOINT_TOLERANCE)
    chains = lines_dxf.chain_fragments(lines_dxf.read_view_curves(doc, view), ENDPOINT_TOLERANCE)
    labels = label_points(doc)

    def keel(k: int) -> float:
        """Height where the curve leaves the centreline: the lower end nearest to it."""
        ends = chains[k][[0, -1]]
        gaps = np.abs(ends[:, 0] - CENTRELINE_X)
        near = ends[gaps <= gaps.min() + ENDPOINT_TOLERANCE]
        return float(near[:, 1].min())

    def starts_at_centreline(k: int) -> bool:
        return min(abs(chains[k][0, 0] - CENTRELINE_X), abs(chains[k][-1, 0] - CENTRELINE_X)) < ENDPOINT_TOLERANCE

    forward = [k for k, c in enumerate(chains) if len(c) > 40 and c[:, 0].min() > CENTRELINE_X - 1]
    # Aft station curves can be split at skeg junctions into short pieces, so
    # every piece that leaves the centreline counts in the aft ordering.
    aft = [k for k, c in enumerate(chains) if len(c) > 10 and c[:, 0].max() < CENTRELINE_X + 1]
    stations: list[dict] = []
    ledger: list[dict] = []

    # Rule 2: forward straight keel.
    straight = [k for k in forward if starts_at_centreline(k) and keel(k) < 25650]
    anchor = {n: labelled_chain(labels[f"#{n}"][0], chains, straight) for n in (40, 45, 50)}
    k40, k45, k50 = (keel(anchor[n]) for n in (40, 45, 50))
    per_frame = (k50 - k40) / 10.0
    check = abs((k45 - k40) / 5.0 - per_frame) / per_frame
    ledger.append({"rule": "forward keel rake", "keel_heights_40_45_50": [k40, k45, k50],
                   "per_frame_units": per_frame, "consistency_45": check})
    if check > 0.05:
        raise SystemExit("Labels #40/#45/#50 disagree with a straight raked keel; stop.")
    x40 = frames["40"]
    for k in straight:
        offset = (keel(k) - k40) / per_frame
        if abs(offset - round(offset)) > 0.2:
            ledger.append({"rule": "forward keel rake", "rejected_keel_height": keel(k), "frame_offset": offset})
            continue
        x = round(x40 + 0.5 * round(offset), 4)
        stations.append({"id": f"fr{frame_name(x, frames)}", "x_m": x, "side": 1,
                         "pick_xy": distinctive_point(k, chains),
                         "evidence": f"keel-rake rule: offset {offset:+.2f} frames from #40"})

    # Rule 3: stem and upper bow pieces.
    stem = sorted([k for k in forward if keel(k) >= 25650 and keel(k) < 28000
                   and min(abs(chains[k][0, 0] - CENTRELINE_X), abs(chains[k][-1, 0] - CENTRELINE_X)) < 100], key=keel)
    upper = sorted([k for k in forward if starts_at_centreline(k) and keel(k) >= 28900], key=keel)
    lower_label_55 = min(labels["#55"], key=lambda label: label[0][1])
    upper_label_55 = max(labels["#55"], key=lambda label: label[0][1])
    stem_55 = labelled_chain(lower_label_55, chains, stem)
    stem_58 = labelled_chain(labels["#58"][0], chains, stem)
    upper_55 = labelled_chain(upper_label_55, chains, upper)
    upper_60 = labelled_chain(labels["#60"][0], chains, upper)
    if stem.index(stem_58) - stem.index(stem_55) != 3 or upper.index(upper_60) - upper.index(upper_55) != 5:
        raise SystemExit("Stem labels disagree with the curve count; stop.")
    first_stem_frame = 55 - stem.index(stem_55)
    lower_piece = {first_stem_frame + i: k for i, k in enumerate(stem)}
    upper_piece = {55 + i - upper.index(upper_55): k for i, k in enumerate(upper)}
    ledger.append({"rule": "stem ordering", "lower_pieces": {str(f): keel(k) for f, k in lower_piece.items()},
                   "upper_pieces": {str(f): keel(k) for f, k in upper_piece.items()}})
    for frame in sorted(set(lower_piece) | set(upper_piece)):
        x = frames.get(str(frame), round(0.5 * (frame + 10), 4))
        pieces = [k for k in (lower_piece.get(frame), upper_piece.get(frame)) if k is not None]
        stations.append({"id": f"fr{frame}", "x_m": x, "side": 1,
                         "pick_xy": distinctive_point(pieces[0], chains),
                         "extra_picks": [distinctive_point(k, chains) for k in pieces[1:]],
                         "evidence": f"stem ordering rule; drawn in {len(pieces)} piece(s)"})

    # Rule 4: aft body.
    full_aft = sorted([k for k in aft if starts_at_centreline(k)], key=keel, reverse=True)
    anchors = {n: labelled_chain(labels[f"#{n}"][0], chains, full_aft) for n in (0, 5, 10, 15, 20)}
    base = full_aft.index(anchors[0])
    consistent = all(base + n < len(full_aft) and full_aft[base + n] == anchors[n] for n in (5, 10, 15, 20))
    resolved = base if consistent else None
    ledger.append({"rule": "aft ordering", "aft_pieces_from_centreline": [round(keel(k), 1) for k in full_aft], "resolved_frame0_rank": resolved})
    if resolved is None:
        raise SystemExit("Aft labels disagree with the curve count; stop.")
    for rank, k in enumerate(full_aft):
        frame = rank - resolved
        if frame > 20:
            break
        x = round(0.5 * frame, 4)
        stations.append({"id": f"fr{frame}", "x_m": x, "side": -1, "pick_xy": distinctive_point(k, chains),
                         "evidence": "aft ordering rule anchored on #0/#5/#10/#15/#20"})
    side_top = (TOP_Y - BASELINE_Y) / 1000.0
    if round2:
        # Rule 5: midbody frames by cross-view half-breadths (plan waterlines).
        midbody = full_aft[resolved + 21:]
        known = {s["id"] for s in stations}
        wanted = [name for name in [*(str(n) for n in range(21, 28)), *"ABCDEFG"] if f"fr{name}" not in known]
        references = plan_waterline_references(doc, {name: frames[name] if name in frames else 0.5 * int(name)
                                                      for name in wanted})
        curves = {str(k): lines_dxf.to_half_section_m(chains[k], view, -1) for k in midbody}
        assigned, cross_ledger = lines_dxf.cross_view_identity(curves, references)
        ledger.append({"rule": "midbody cross-view", "waterline_heights_m": sorted({z for t in references.values() for z in t}),
                       "curves": cross_ledger, "frames_without_curve": sorted(set(wanted) - set(assigned.values()))})
        for key, name in assigned.items():
            x = frames[name] if name in frames else round(0.5 * int(name), 4)
            best = next(e for e in cross_ledger if e["curve"] == key)["candidates"][:2]
            stations.append({"id": f"fr{name}", "x_m": x, "side": -1, "pick_xy": distinctive_point(int(key), chains),
                             "evidence": f"cross-view rule: plan waterline half-breadths, best {best}"})
        # Rule 6: each station ends at the top of the centreline profile outline.
        outline = profile_outline(doc)
        for station in stations:
            top = profile_top(outline, station["x_m"])
            if top is not None and top < side_top:
                station["top_z_m"] = round(top, 4)
                station["top_evidence"] = "upper crossing of the centreline profile outline (03_Lines_Buttocks) at the station"
    stations.sort(key=lambda s: s["x_m"])
    config = {"dxf": str(dxf), "view": {**view.__dict__, "bounds": list(view.bounds), "layers": list(view.layers)},
              "side_line": {"y_m": (SIDE_X[1] - CENTRELINE_X) / 1000.0, "top_z_m": side_top,
                            "tolerance_m": 0.002, "require_end": True},
              "stations": stations, "pick_tolerance": 5.0,
              "provenance": "Assistant-read from Lines Plan Rev0.dxf by make_gunnerus_configs.py rules; provisional.",
              "frames_from_profile_grid": frames}
    if round2:
        config.update(regions=True, centreline_closure_m=CENTRELINE_CLOSURE_M)
    return config, ledger


def plan_waterline_references(doc, frame_x: dict[str, float]) -> dict[str, dict[float, float]]:
    """Plan-view half-breadth of each labelled waterline at each frame: {frame: {z_m: hb_m}}.

    A waterline chain takes the WL label nearest to it if that label is within
    120 drawing units and at least twice as near as the next label. Only
    waterlines up to WL 1800 are used: above it the midbody is wall sided and
    every frame has the same half-breadth.
    """
    view = lines_dxf.BodyPlanView(centreline_x=PLAN_BOUNDS[0], baseline_y=PLAN_BOUNDS[1], units_per_metre=1000.0,
                                  bounds=PLAN_BOUNDS, layers=("03_Lines_Waterlines",))
    chains = lines_dxf.chain_fragments(lines_dxf.read_view_curves(doc, view), ENDPOINT_TOLERANCE)
    labels = []
    for e in doc.modelspace():
        if e.dxftype() == "TEXT" and re.fullmatch(r"WL\s+\d+", e.dxf.text.strip()):
            point = np.array([e.dxf.insert.x, e.dxf.insert.y])
            if PLAN_BOUNDS[0] < point[0] < PLAN_BOUNDS[2] and PLAN_BOUNDS[1] < point[1] < PLAN_BOUNDS[3]:
                labels.append((int(e.dxf.text.split()[-1]), point))
    by_height: dict[int, list[np.ndarray]] = {}
    for chain in chains:
        nearest = sorted((_distance_to_polyline(point, chain), height) for height, point in labels)
        if nearest[0][0] < 120 and (len(nearest) < 2 or nearest[1][0] > 2 * nearest[0][0]):
            by_height.setdefault(nearest[0][1], []).append(chain)
    references = {}
    for name, x in frame_x.items():
        table = {}
        for height, wl_chains in by_height.items():
            if height <= 1800:
                value = lines_dxf.plan_half_breadth_at(wl_chains, PLAN_FRAME0_X + 1000.0 * x, PLAN_CENTRELINE_Y, 1000.0)
                if np.isfinite(value):
                    table[height / 1000.0] = value
        references[name] = table
    return references


def profile_outline(doc) -> np.ndarray:
    """The centreline profile outline: the longest closed curve on the buttock layer in the profile view."""
    best = None
    for e in doc.modelspace():
        if e.dxf.layer == "03_Lines_Buttocks" and e.dxftype() in lines_dxf.SUPPORTED_ENTITIES:
            points = lines_dxf._entity_points(e, 1.0)
            if points is not None and np.allclose(points[0], points[-1]) and (best is None or len(points) > len(best)):
                best = points
    if best is None:
        raise SystemExit("No closed centreline profile outline found; stop.")
    return best


def profile_top(outline: np.ndarray, x_m: float) -> float | None:
    """Highest point of the profile outline at a station, as height above the baseline."""
    values = lines_dxf._level_crossings(outline, 0, PROFILE_FRAME0_X + 1000.0 * x_m)
    return (float(values.max()) - BASELINE_PROFILE_Y) / 1000.0 if len(values) else None


def raster_config(pdf: Path, stations: list[dict]) -> dict:
    """Calibration read from long grid lines of the 500 dpi render (raster_path measure)."""
    bt_minus_4500, bt_plus_4500 = 328.0, 3182.0       # column centres of BT -4500 and BT +4500
    wl_7500, wl_250 = 376.0, 2675.0                    # row centres of WL 7500 and WL 250
    ppm_horizontal = (bt_plus_4500 - bt_minus_4500) / 9.0
    ppm_vertical = (wl_250 - wl_7500) / 7.25
    ppm = round((ppm_horizontal + ppm_vertical) / 2.0, 3)
    return {"pdf": str(pdf), "page_index": 0, "clip_pt": [1950, 790, 2450, 1290], "dpi": 500,
            "vessel_id": "R/V Gunnerus lines plan body plan (sealed benchmark, raster path)",
            "license": "CC BY-NC 4.0 (shiplab/gunnerus); not for redistribution or provider transfer",
            "description": "Lines Plan Rev0.pdf body plan, polarkonsult; local benchmark use only",
            "calibration": {"centreline_px": 1755.5, "baseline_px": round(wl_250 + 0.25 * ppm, 2),
                            "pixels_per_metre": ppm,
                            "evidence": {"bt_columns": [bt_minus_4500, bt_plus_4500], "wl_rows": [wl_7500, wl_250],
                                         "ppm_horizontal": ppm_horizontal, "ppm_vertical": ppm_vertical,
                                         "centreline": "longest vertical line between BT -500 and BT 500"}},
            "z_range_m": {"1": [0.0, 7.5], "-1": [0.0, 7.5]},
            "stations": [{"id": s["id"], "x_m": s["x_m"], "side": s["side"],
                          "evidence": "station list shared with the vector path; positions from the profile frame grid"}
                         for s in stations]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    vector, ledger = vector_config(args.dxf)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gunnerus_vector.json").write_text(json.dumps(vector, indent=2) + "\n")
    (args.out / "gunnerus_identity_ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
    (args.out / "gunnerus_raster.json").write_text(json.dumps(raster_config(args.pdf, vector["stations"]), indent=2) + "\n")
    print(json.dumps({"stations": [s["id"] for s in vector["stations"]], "ledger": ledger}, indent=1))


if __name__ == "__main__":
    main()
