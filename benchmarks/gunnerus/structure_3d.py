"""Gunnerus 3D internal structure from its own drawings (docs/STRUCTURE_V2.md sections 8 and 9).

The members of midship section #I are extruded along the parallel body at the drawn frame spacing
and cut to the built hull at every frame; the transverse members are placed at every frame, with
the bulkheads of the longitudinal construction section (step 2 internals reader) in their place.
Thicknesses and profiles come from the labels of the midship section, the shell expansion and the
profile-and-plan sheet, each labelled ``printed`` or ``guessed``. Outputs: steel tables, OCX 3.0.1
(plates and stiffeners) and a JSON report with the metrics G6 to G11. No model call; every output
has ``engineering_approved=false``.

    PYTHONPATH=src:. python -m benchmarks.gunnerus.structure_3d --sources work/sources/gunnerus \\
        --assembly work/whole-vessel/final --out work/step3/gunnerus \\
        --ocx-schema work/sources/ocx_schema/ocx/ocx_301
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import statistics

import numpy as np

from benchmarks.gunnerus import structure_3d_reading as reading
from benchmarks.gunnerus import whole_vessel_internals as internals
from vessel_reconstruction.structure import extrude, ocx, steel
from vessel_reconstruction.structure.extrude import HullSections, Profile, Seam
from vessel_reconstruction.tanks import HullSlicer

# Parallel body: frames whose hull section is one piece with an area within this share of the
# new-part mean (plan section 8.2 item 2).
PARALLEL_AREA_SHARE = 0.03
HULL_Z_RANGE_M = (-0.6, 4.30)
# Deepest search for a bulkhead station: a long-section bulkhead within this distance of a frame.
STATION_SNAP_M = 0.10
# Web frame of the side-frame key ("PL 8.0, KN.FL. 50"): the key prints the plate and the flange,
# not the depth; the depth is the "WEB PL 8,0x200" of section #A on the midship sheet (guessed).
WEB_FRAME_DEPTH_MM = 200.0
WEB_FRAME_FLANGE_MM = 50.0
GUESSED_SIDE_FRAME = "HP 100x6"  # most common profile of the side-frame key
TARGETS = {"G6a_mm": 10.0, "G6b_mm": 25.0, "G6c_median_mm": 30.0, "G7a_share": 0.70, "G8_mm": 5.0, "G11_share": 1.0}


@dataclass(frozen=True)
class Station:
    label: str
    index: int  # 500 mm steps from frame 0
    x: float

    @property
    def new_part(self) -> bool:
        return self.label in reading.NEW_PART_FRAMES


def frame_label(index: int) -> str:
    """Inverse of ``whole_vessel_internals.frame_index``: lettered frames A to J follow frame 27."""
    letters = internals.FRAME_LETTERS
    if 27 < index <= 27 + len(letters):
        return letters[index - 28]
    return str(index if index <= 27 else index - len(letters))


def station(index: int) -> Station:
    return Station(frame_label(index), index, index * internals.FRAME_SPACING_MM / internals.MM)


def parallel_body(sections: HullSections) -> tuple[list[Station], dict]:
    """New-part frames and the neighbours whose section matches them (one piece, area within 3 %)."""
    new_part = [station(internals.frame_index(label)) for label in reading.NEW_PART_FRAMES]
    mean_area = statistics.mean(sections.area(s.x) for s in new_part)

    def matches(s: Station) -> bool:
        return sections.pieces(s.x) == 1 and abs(sections.area(s.x) / mean_area - 1) <= PARALLEL_AREA_SHARE

    low, high = new_part[0].index, new_part[-1].index
    while matches(station(low - 1)):
        low -= 1
    while matches(station(high + 1)):
        high += 1
    stations = [station(i) for i in range(low, high + 1)]
    return stations, {"frames": [stations[0].label, stations[-1].label], "x_m": [stations[0].x, stations[-1].x],
                      "stations": len(stations), "new_part_mean_area_m2": round(mean_area, 3),
                      "new_part_frames_one_piece_within_share": all(matches(s) for s in new_part)}


# --- thickness sources ------------------------------------------------------------------------

def printed(mm: float, basis: str) -> dict:
    return {"mm": mm, "source": "printed", "basis": basis}


def guessed(mm: float, basis: str) -> dict:
    return {"mm": mm, "source": "guessed", "basis": basis}


def scope_label(thickness: dict, s: Station) -> dict:
    """A section #I value is printed for the new-part frames; elsewhere it is carried over (guessed)."""
    if s.new_part or thickness["source"] != "printed":
        return thickness
    return guessed(thickness["mm"], f"{thickness['basis']}; carried over to frame {s.label} outside the new part")


def band_thickness(labels, x_mid: float, band: tuple[float, float], fallback: float, what: str) -> dict:
    """Plate label of a plan view inside the |y| band nearest in x to the run, else a guess."""
    inside = [(x, mm) for x, y, mm in labels if band[0] <= y < band[1]]
    if not inside:
        return guessed(fallback, f"no {what} label between {band[0]:.3f} and {band[1]:.3f} m from the centre line; "
                                 "most common label of the plan")
    x, mm = min(inside, key=lambda item: abs(item[0] - x_mid))
    return printed(mm, f"{what} label PL {mm:g} at x {x:.2f} m, {abs(x - x_mid):.2f} m from the run middle")


# --- build ------------------------------------------------------------------------------------

@dataclass
class Context:
    reading: reading.GunnerusReading
    sections: HullSections
    stations: list[Station]
    section_deck_z: float  # 1-deck of section #I above the new baseline
    bulkhead_stations: dict[str, Station]
    step_x: float | None  # the plan's tank-top 'STEP', moved to the nearest frame

    def tank_top_mm(self, x: float) -> float:
        """Tank-top level (mm above the old baseline): the plan label on the same side of the step."""
        levels = self.reading.plan.tank_top_levels
        if self.step_x is None:
            return min(levels, key=lambda level: abs(level[0] - x))[1]
        same_side = [level for level in levels if (level[0] < self.step_x) == (x < self.step_x - 1e-6)]
        return min(same_side or levels, key=lambda level: abs(level[0] - x))[1]

    def tank_top_z(self, x: float) -> float:
        return self.reading.section_i.datums.old_bl_to_z_m(self.tank_top_mm(x))

    def deck_z(self, x: float) -> float:
        """1-deck height at x: the top of the built hull (it steps aft of the new part)."""
        return round(self.sections.top_z(x), 4)


def level_runs(stations: list[Station], level) -> list[list[Station]]:
    """Station runs of one level (``level(x)``). The step frame belongs to both neighbouring runs:
    it closes the aft run (at the aft level) and opens the forward one. The level of a run is the
    level of its first station."""
    runs, current = [], [stations[0]]
    for s in stations[1:]:
        if level(s.x) != level(current[-1].x):
            runs.append(current + [s])
            current = [s]
        else:
            current.append(s)
    runs.append(current)
    return [run for run in runs if len(run) >= 2]


def _run_name(run: list[Station]) -> str:
    return f"{run[0].label}-{run[-1].label}"


def longitudinal_members(ctx: Context) -> list[dict]:
    members = []
    section = ctx.reading.section_i
    plan = ctx.reading.plan
    sections = ctx.sections
    floor_mm = section.floor_plate["mm"]
    tank_top_labels = plan.tank_top_plates
    common_tank_top = statistics.mode([mm for _, _, mm in tank_top_labels])
    girders = section.db_girders_m
    edges = sorted({abs(y) for y in girders})  # 0, 1.875, 3.525
    bands = list(zip(edges, edges[1:] + [math.inf]))
    for run in level_runs(ctx.stations, ctx.tank_top_mm):
        level_mm = ctx.tank_top_mm(run[0].x)
        z = ctx.tank_top_z(run[0].x)
        xs = [s.x for s in run]
        x_mid = (xs[0] + xs[-1]) / 2
        sources = {"level": "printed", "extent": "traced", "breadth": "traced"}
        for band in bands:
            thickness = band_thickness(tank_top_labels, x_mid, band, common_tank_top, "tank-top")
            for side, sign in (("p", -1), ("s", +1)):
                y_band = (band[0], band[1]) if sign > 0 else (-band[1], -band[0])
                built = extrude.horizontal_plate(sections, xs, z, y_band)
                if built is None:
                    continue
                contour, area = built
                members.append(extrude.plate_member(
                    f"G/L/tank_top_{side}{band[0] * 1000:04.0f}/{_run_name(run)}", "inner_bottom", "longitudinal",
                    contour, area, thickness, sources,
                    f"tank top {level_mm:.0f} mm above the old baseline (plan label), section #I panel"))
        for y in girders:
            offset = abs(round(y * 1000))
            found = plan.girder_thickness.get(offset)
            thickness = (printed(found["mm"], found["basis"]) if found
                         else guessed(floor_mm, "no girder label; floor plate of section #I"))
            built = extrude.vertical_plate(sections, xs, y, z)
            if built is None:
                continue
            contour, area = built
            side = "c" if offset == 0 else ("s" if y > 0 else "p")
            members.append(extrude.plate_member(
                f"G/L/db_girder_{side}{offset:04d}/{_run_name(run)}", "girder", "longitudinal", contour, area,
                thickness, {"position": "traced", "height": "traced"},
                f"double-bottom girder of section #I at y {y:+.3f} m, bottom shell to the tank top"))
    members += _deck_members(ctx)
    members += _shell_members(ctx)
    return members


def _deck_members(ctx: Context) -> list[dict]:
    plan, section = ctx.reading.plan, ctx.reading.section_i
    xs = [s.x for s in ctx.stations]
    x_mid = (xs[0] + xs[-1]) / 2
    deck_label = min(plan.deck_plates, key=lambda p: abs(p[0] - x_mid), default=None)
    thickness = (printed(deck_label[2], f"1-deck plan label PL {deck_label[2]:g} at x {deck_label[0]:.2f} m "
                                        f"({abs(deck_label[0] - x_mid):.2f} m from the run middle)")
                 if deck_label else guessed(section.floor_plate["mm"], "no deck plate label"))
    members = []
    for deck_run in level_runs(ctx.stations, ctx.deck_z):
        z = ctx.deck_z(deck_run[0].x)
        built = extrude.horizontal_plate(ctx.sections, [s.x for s in deck_run], z, (-50.0, 50.0))
        if built:
            contour, area = built
            members.append(extrude.plate_member(
                f"G/L/deck/{_run_name(deck_run)}", "deck", "longitudinal", contour, area, thickness,
                {"level": "traced", "breadth": "traced"}, "1-deck plate at the built-hull deck, hull breadth"))
        members += _deck_girders(ctx, deck_run, z)
    for aft, forward in zip(ctx.stations, ctx.stations[1:]):
        low, high = sorted((ctx.deck_z(aft.x), ctx.deck_z(forward.x)))
        if high - low < 1e-3:
            continue
        built = extrude.transverse_plate(ctx.sections, forward.x, (low, high))
        if built:
            contour, area = built
            members.append(extrude.plate_member(
                f"G/T/{forward.label}/deck_step", "deck", "transverse", contour, area,
                guessed(thickness["mm"], "1-deck plate thickness"), {"position": "traced"},
                "1-deck step of the built hull between two deck levels"))
    return members


def _deck_girders(ctx: Context, deck_run: list[Station], z: float) -> list[dict]:
    members = []
    for girder in ctx.reading.section_i.deck_girders:
        thickness_mm, width = reading.plate_value(reading.Label(0, 0, girder["label"], "PL", ""))
        profile = Profile(f"FB {girder['web_mm']:g}x{thickness_mm:g}", "FlatBar", girder["web_mm"], thickness_mm)
        y = girder["y_m"]
        for run in extrude.runs_of(deck_run, lambda s: ctx.sections.inside(s.x, y, z - 0.01)):
            side = "s" if y > 0 else "p"
            trace = [(run[0].x, y, z), (run[-1].x, y, z)]
            members.append(extrude.stiffener_member(
                f"G/L/deck_girder_{side}{abs(y) * 1000:04.0f}/{_run_name(run)}", "deck_girder", "longitudinal",
                trace, profile, "printed", f"section #I label PL {girder['label']} (web depth drawn {girder['web_mm']:g} mm)",
                (0, 0, -1), {"position": "traced", "depth": "traced"}, "deck girder of section #I"))
    return members


def shell_seams(ctx: Context) -> list[Seam]:
    datums = ctx.reading.section_i.datums
    seams = []
    for axis, value, text in ctx.reading.strakes.seams:
        position = value / 1000 if axis == "y" else datums.old_bl_to_z_m(value)
        seams.append(Seam(axis, position, text))
    return seams


def _shell_members(ctx: Context) -> list[dict]:
    seams = shell_seams(ctx)
    strakes = ctx.reading.strakes
    xs = [s.x for s in ctx.stations]
    members = []
    names = ["keel"] + [f"above {seam.label}" for seam in seams]
    for index, mm in enumerate(strakes.thickness_mm):
        thickness = (printed(mm, f"shell expansion, new part: PL {mm:g} between seams") if mm
                     else guessed(8.0, "no shell expansion label in this strake"))
        label = "side_shell" if index == len(seams) else "bottom_shell"
        for side, sign in (("p", -1), ("s", +1)):
            built = extrude.shell_strake(ctx.sections, xs, sign, seams, index, ctx.deck_z)
            if built is None:
                continue
            contour, area, _ = built
            members.append(extrude.plate_member(
                f"G/L/shell_{side}{index + 1}/{_run_name(ctx.stations)}", label, "longitudinal", contour, area,
                thickness, {"girth": "traced", "seams": "printed"},
                f"shell strake {index + 1} ({names[index]}), built-hull girth between the printed seams"))
    return members


def side_frame_profile(ctx: Context, s: Station) -> tuple[Profile, str, str]:
    key = ctx.reading.frame_key.get(s.label)
    if key and key["profiles"]:
        return extrude.parse_profile(key["profiles"][0]), "printed", f"side-frame key '{key['key']}'"
    if key and key["plate_mm"]:
        mm = key["plate_mm"]
        profile = Profile(f"PL {WEB_FRAME_DEPTH_MM:g}x{mm:g} KN.FL {WEB_FRAME_FLANGE_MM:g}", "TBar",
                          WEB_FRAME_DEPTH_MM, mm, WEB_FRAME_FLANGE_MM, mm)
        return profile, "printed", (f"side-frame key '{key['key']}' prints PL {mm:g} KN.FL. 50; "
                                    f"depth {WEB_FRAME_DEPTH_MM:g} mm guessed (section #A web)")
    return extrude.parse_profile(GUESSED_SIDE_FRAME), "guessed", f"frame {s.label} not in the side-frame key"


def transverse_members(ctx: Context) -> list[dict]:
    members = []
    section_i, section_g, plan = ctx.reading.section_i, ctx.reading.section_g, ctx.reading.plan
    floor = printed(section_i.floor_plate["mm"], f"section #I double-bottom labels {section_i.floor_plate['labels']}")
    floor_stiffener = extrude.parse_profile(section_i.floor_stiffener_profile)
    beam = extrude.parse_profile(plan.deck_beam_profile)
    bulkhead_plate = printed(section_g.bulkhead_plate["mm"], "section #G label above the tank top")
    bulkhead_stiffener = extrude.parse_profile(section_g.bulkhead_stiffener_profile)
    for s in ctx.stations:
        z_tt = ctx.tank_top_z(s.x)
        deck = ctx.deck_z(s.x)
        prefix = f"G/T/{s.label}"
        built = extrude.transverse_plate(ctx.sections, s.x, (HULL_Z_RANGE_M[0], z_tt))
        if built:
            contour, area = built
            members.append(extrude.plate_member(f"{prefix}/floor", "floor", "transverse", contour, area,
                                                scope_label(floor, s), {"position": "traced", "outline": "traced"},
                                                "floor: hull section below the tank top (lightening holes not cut)"))
        for y in section_i.floor_stiffeners_m:
            bottom = ctx.sections.bottom_z(s.x, y)
            if bottom is None or bottom >= z_tt:
                continue
            side = "s" if y > 0 else "p"
            members.append(extrude.stiffener_member(
                f"{prefix}/floor_stiffener_{side}{abs(y) * 1000:04.0f}", "floor_stiffener", "transverse",
                [(s.x, y, bottom), (s.x, y, z_tt)], floor_stiffener,
                "printed" if s.new_part else "guessed", f"section #I label '{section_i.floor_stiffener_profile}'",
                (1, 0, 0), {"position": "traced"}, "floor stiffener (dashed line of section #I)"))
        if s.label in ctx.bulkhead_stations:
            members += _bulkhead_members(ctx, s, z_tt, deck, bulkhead_plate, bulkhead_stiffener)
            continue
        profile, source, basis = side_frame_profile(ctx, s)
        for side, sign in (("p", -1), ("s", +1)):
            shell = [(y, z) for y, z in ctx.sections.outer_contour(s.x, sign, deck) if z >= z_tt]
            if len(shell) >= 2:
                members.append(extrude.stiffener_member(
                    f"{prefix}/side_frame_{side}", "frame", "transverse", [(s.x, y, z) for y, z in shell], profile,
                    source, basis, (0, -sign, 0), {"position": "traced", "trace": "traced"},
                    "side frame on the shell from the tank top to the 1-deck"))
        port, starboard = (ctx.sections.half_breadth(s.x, deck, side) for side in (-1, +1))
        if port is not None:
            members.append(extrude.stiffener_member(
                f"{prefix}/deck_beam", "deck_beam", "transverse", [(s.x, port, deck), (s.x, starboard, deck)],
                beam, "printed" if s.new_part else "guessed", f"1-deck plan note 'DECK BEAMS: {plan.deck_beam_profile}' (new part)",
                (0, 0, -1), {"position": "traced", "span": "traced"}, "deck beam at the frame"))
    members += _tank_top_steps(ctx)
    return members


def _bulkhead_members(ctx: Context, s: Station, z_tt: float, deck: float, plate: dict,
                      stiffener: Profile) -> list[dict]:
    members = []
    prefix = f"G/T/{s.label}"
    thickness = plate if s.label == "G" else guessed(plate["mm"], f"{plate['basis']} (section #G), frame {s.label}")
    built = extrude.transverse_plate(ctx.sections, s.x, (z_tt, deck))
    if built:
        contour, area = built
        members.append(extrude.plate_member(f"{prefix}/bulkhead", "transverse_bulkhead", "transverse", contour, area,
                                            thickness, {"position": "traced", "outline": "traced"},
                                            "main bulkhead of the longitudinal construction section, tank top to 1-deck"))
    for y in ctx.reading.section_g.bulkhead_stiffeners_m:
        if not (ctx.sections.inside(s.x, y, z_tt) and ctx.sections.inside(s.x, y, deck - 0.01)):
            continue
        side = "s" if y > 0 else ("p" if y < 0 else "c")
        members.append(extrude.stiffener_member(
            f"{prefix}/bulkhead_stiffener_{side}{abs(y) * 1000:04.0f}", "bulkhead_stiffener", "transverse",
            [(s.x, y, z_tt), (s.x, y, deck)], stiffener, "printed" if s.label == "G" else "guessed",
            f"section #G label '{stiffener.name}'", (1, 0, 0), {"position": "traced"},
            "vertical bulkhead stiffener (dashed line of section #G)"))
    return members


def _tank_top_steps(ctx: Context) -> list[dict]:
    """A transverse plate where the tank top steps between two levels (plan 'STEP' label)."""
    members = []
    common = statistics.mode([mm for _, _, mm in ctx.reading.plan.tank_top_plates])
    for aft, forward in zip(ctx.stations, ctx.stations[1:]):
        low, high = sorted((ctx.tank_top_z(aft.x), ctx.tank_top_z(forward.x)))
        if high - low < 1e-3:
            continue
        built = extrude.transverse_plate(ctx.sections, forward.x, (low, high))
        if built:
            contour, area = built
            members.append(extrude.plate_member(
                f"G/T/{forward.label}/tank_top_step", "inner_bottom", "transverse", contour, area,
                guessed(common, "most common tank-top label of the plan"), {"position": "printed"},
                "tank-top step between the two plan levels"))
    return members


# --- metrics ---------------------------------------------------------------------------------

def _summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": round(statistics.median(values), 2), "max": round(max(values), 2)}


def g6a_positions(r: reading.GunnerusReading) -> dict:
    """Linework positions against printed FCL values (midship labels and shell-expansion seams)."""
    pairs = []

    def against(section_name, positions, labels, extra_values=()):
        printed_values = sorted({value for value, _ in labels} | set(extra_values))
        for y in positions:
            if abs(y) < 1e-6:
                continue
            value = min(printed_values, key=lambda v: abs(v - abs(y) * 1000))
            pairs.append({"member": f"{section_name} y {y:+.4f} m", "printed_mm": value,
                          "error_mm": round(abs(abs(y) * 1000 - value), 2)})

    seam_values = [value for axis, value, _ in r.strakes.seams if axis == "y"]
    against("#I double-bottom girder", r.section_i.db_girders_m, r.section_i.fcl_labels_mm, seam_values)
    against("#I deck girder", [g["y_m"] for g in r.section_i.deck_girders], r.section_i.fcl_labels_mm)
    against("#I floor stiffener", r.section_i.floor_stiffeners_m, r.section_i.fcl_labels_mm)
    against("#G bulkhead stiffener", r.section_g.bulkhead_stiffeners_m, r.section_g.fcl_labels_mm)
    errors = [p["error_mm"] for p in pairs]
    return {**_summary(errors), "target_mm": TARGETS["G6a_mm"],
            "met": bool(errors) and statistics.median(errors) <= TARGETS["G6a_mm"], "pairs": pairs}


def printed_depth_m(sources: Path) -> float | None:
    """'DEPTH TO 1-DECK' value of the midship main-dimensions table (decimal comma)."""
    sheet = reading.read_sheet(sources / reading.MIDSHIP)
    title = next((l for l in sheet.labels if l.text.upper().startswith("DEPTH TO 1-DECK")), None)
    if title is None:
        return None
    row = [l for l in sheet.labels if abs(l.y - title.y) < 100 and l.x > title.x and re.fullmatch(r"\d+,\d+", l.text)]
    return float(min(row, key=lambda l: l.x - title.x).text.replace(",", ".")) if row else None


def g6b_levels(ctx: Context, sources: Path, long_section) -> dict:
    datums = ctx.reading.section_i.datums
    checks = []
    tank_top_old_bl = datums.tank_top_y - datums.old_baseline_y
    printed_levels = list(ctx.reading.section_i.levels.values())
    if printed_levels:
        checks.append({"check": "#I tank-top line above the old baseline vs '1250 O/BL.'",
                       "drawn_mm": round(tank_top_old_bl, 2), "printed_mm": printed_levels[0],
                       "error_mm": round(abs(tank_top_old_bl - printed_levels[0]), 2)})
    deck_old_bl = datums.deck_y - datums.old_baseline_y
    checks.append({"check": "#I 1-deck line above the old baseline vs '4200 O/BL.' (plan)", "drawn_mm": round(deck_old_bl, 2),
                   "printed_mm": 4200.0, "error_mm": round(abs(deck_old_bl - 4200.0), 2)})
    depth = printed_depth_m(sources)
    if depth:
        checks.append({"check": "#I 1-deck above the new baseline vs main dimensions 'DEPTH TO 1-DECK'",
                       "drawn_mm": round(ctx.section_deck_z * 1000, 2), "printed_mm": depth * 1000,
                       "error_mm": round(abs(ctx.section_deck_z - depth) * 1000, 2)})
    for s in (station(internals.frame_index("I")), station(internals.frame_index("C"))):
        run = internals.tank_top_run(long_section, s.x)
        if run:
            ours = ctx.tank_top_z(s.x)
            checks.append({"check": f"tank top at frame {s.label} (x {s.x:.1f} m): midship/plan level on the new "
                                    "baseline vs the step 2 internals run (longitudinal construction section)",
                           "drawn_mm": round(ours * 1000, 1), "printed_mm": run["z_m"] * 1000,
                           "error_mm": round(abs(ours - run["z_m"]) * 1000, 1)})
    for deck_run in level_runs(ctx.stations, ctx.deck_z):
        hull_top = ctx.deck_z(deck_run[0].x)
        checks.append({"check": f"#I 1-deck z vs top of the built hull, frames {_run_name(deck_run)}",
                       "drawn_mm": round(ctx.section_deck_z * 1000, 2), "printed_mm": round(hull_top * 1000, 2),
                       "error_mm": round(abs(ctx.section_deck_z - hull_top) * 1000, 2)})
    errors = [c["error_mm"] for c in checks]
    return {**_summary(errors), "target_mm": TARGETS["G6b_mm"],
            "met": all(e <= TARGETS["G6b_mm"] for e in errors), "checks": checks}


def _point_to_segments(point, segments: np.ndarray) -> float:
    a, b = segments[:, 0, :], segments[:, 1, :]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", np.asarray(point) - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    nearest = a + t[:, None] * ab
    return float(np.min(np.linalg.norm(nearest - np.asarray(point), axis=1)))


def g6c_shell(ctx: Context) -> dict:
    x = station(internals.frame_index("I")).x
    segments = ctx.sections.slicer.segments(x)
    points = [(y, z) for y, z in ctx.reading.section_i.shell_yz if z < ctx.section_deck_z - 0.02]
    distances = sorted(_point_to_segments(p, segments) * 1000 for p in points)
    p95 = distances[int(0.95 * (len(distances) - 1))] if distances else None
    median = statistics.median(distances) if distances else None
    return {"x_m": x, "points": len(distances), "median_mm": round(median, 1) if median is not None else None,
            "p95_mm": round(p95, 1) if p95 is not None else None, "max_mm": round(max(distances), 1) if distances else None,
            "target_median_mm": TARGETS["G6c_median_mm"], "met": median is not None and median <= TARGETS["G6c_median_mm"]}


def g7_thickness(members: list[dict], r: reading.GunnerusReading) -> dict:
    rows = steel.member_weights(members)
    total = sum(row["weight_t"] for row in rows)
    printed_weight = sum(row["weight_t"] for row in rows if row["thickness_source"] == "printed")
    share = printed_weight / total if total else 0.0
    pairs = []
    note = r.plan.long_girder_note or ""
    tee = extrude.parse_profile(note) if note else None
    for girder in r.section_i.deck_girders:
        mm, width = reading.plate_value(reading.Label(0, 0, girder["label"], "PL", ""))
        pairs.append({"member": f"deck girder y {girder['y_m']:+.3f} m: web depth", "sheet_a": f"#I drawn {girder['web_mm']:g} mm",
                      "sheet_b": f"#I label {girder['label']}", "agree": width == girder["web_mm"]})
        if tee:
            pairs.append({"member": f"deck girder y {girder['y_m']:+.3f} m: web", "sheet_a": f"#I label {girder['label']}",
                          "sheet_b": f"plan note '{note}'", "agree": tee.web_mm == mm and tee.height_mm - tee.flange_thickness_mm == width})
    pairs.append({"member": "floor plate", "sheet_a": f"#I PL {r.section_i.floor_plate['mm']:g}",
                  "sheet_b": f"#G PL {r.section_g.floor_plate['mm']:g}",
                  "agree": r.section_i.floor_plate["mm"] == r.section_g.floor_plate["mm"]})
    pairs.append({"member": "floor stiffener", "sheet_a": f"#I '{r.section_i.floor_stiffener_profile}'",
                  "sheet_b": f"#G '{r.section_g.floor_stiffener_profile}'",
                  "agree": extrude.parse_profile(r.section_i.floor_stiffener_profile) ==
                  extrude.parse_profile(r.section_g.floor_stiffener_profile.split(" Below")[0])})
    pairs.append({"member": "deck beam", "sheet_a": f"plan note '{r.plan.deck_beam_profile}' (new part)",
                  "sheet_b": f"#I deck label '{r.section_i.bulkhead_stiffener_profile}' (marked EXIST)",
                  "agree": extrude.parse_profile(r.plan.deck_beam_profile) ==
                  extrude.parse_profile(r.section_i.bulkhead_stiffener_profile or "")})
    i_level = list(r.section_i.levels.values())
    plan_forward = [mm for x, mm, _ in r.plan.tank_top_levels if r.plan.tank_top_step_x_m and x > r.plan.tank_top_step_x_m]
    if i_level and plan_forward:
        pairs.append({"member": "tank-top level forward of the step (frame I)", "sheet_a": f"#I {i_level[0]:g} O/BL",
                      "sheet_b": f"plan TANKTOP {plan_forward[0]:g}", "agree": i_level[0] == plan_forward[0]})
    return {"printed_weight_share": round(share, 4), "target_share": TARGETS["G7a_share"],
            "met": share >= TARGETS["G7a_share"], "pairs": pairs,
            "pairs_agree": sum(p["agree"] for p in pairs), "pairs_total": len(pairs)}


def g8_spacing(r: reading.GunnerusReading) -> dict:
    axes = {f"plan {name}": axis for name, axis in r.plan.axes.items()}
    axes.update({f"shell expansion {k}": axis for k, axis in enumerate(r.shell_axes)})
    result, all_errors = {}, []
    for name, axis in axes.items():
        errors = [abs(s - internals.FRAME_SPACING_MM) for s in axis.spacings_mm]
        all_errors += errors
        result[name] = {"pairs": len(errors), "median_spacing_mm": round(statistics.median(axis.spacings_mm), 2),
                        "median_abs_error_mm": round(statistics.median(errors), 2), "max_abs_error_mm": round(max(errors), 2)}
    median = statistics.median(all_errors)
    return {"axes": result, "median_abs_error_mm": round(median, 2), "target_mm": TARGETS["G8_mm"],
            "met": median <= TARGETS["G8_mm"],
            "note": "label-to-label spacing between labels of equal length (left-aligned text)"}


WEIGHT_PATTERN = re.compile(r"LIGHT\s*WEIGHT|LIGHTSHIP|LIGHT\s*SHIP|STEEL\s*WEIGHT|STÅLVEKT|LETTSKIP", re.I)


def g9_weight(sources: Path, steel_t: float) -> dict:
    found = []
    for name in (reading.MIDSHIP, reading.SHELL_EXPANSION, reading.PROFILE_AND_PLAN):
        found += [f"{name}: {l.text}" for l in reading.read_sheet(sources / name).labels if WEIGHT_PATTERN.search(l.text)]
    metadata = sources / "metadata" / "gunnerus_metadata.json"
    if metadata.is_file():
        found += [f"metadata: {line.strip()}" for line in metadata.read_text().splitlines()
                  if WEIGHT_PATTERN.search(line) and re.search(r"\d", line)]
    return {"printed_figures": found, "result": "compared" if found else "not found",
            "parallel_body_steel_t": round(steel_t, 2),
            "note": "searched the three construction sheets and the GA metadata; the GA prints deadweight 164 t only"}


def g11_inside(ctx: Context, members: list[dict]) -> dict:
    total = inside = 0
    outside = []
    for member in members:
        points = member.get("contour") or member.get("trace") or []
        flags = [ctx.sections.inside(x, y, min(z, ctx.deck_z(x) - 0.005)) for x, y, z in points]
        total += len(flags)
        inside += sum(flags)
        if not all(flags):
            outside.append(member["member_id"])
    share = inside / total if total else 0.0
    return {"points": total, "inside_share": round(share, 5), "members_with_outside_points": outside[:20],
            "members_outside": len(outside), "target_share": TARGETS["G11_share"], "met": share >= TARGETS["G11_share"]}


# --- run ---------------------------------------------------------------------------------------

def build(sources: Path, slicer: HullSlicer):
    r = reading.read_all(sources)
    sections = HullSections(slicer, *HULL_Z_RANGE_M)
    stations, body = parallel_body(sections)
    long_section = internals.read_long_section(sources / internals.LONG_SECTION)
    bulkheads = {}
    for x in long_section.bulkheads_x_m:
        near = min(stations, key=lambda s: abs(s.x - x))
        if abs(near.x - x) <= STATION_SNAP_M:
            bulkheads[near.label] = near
    body["bulkhead_frames"] = sorted(bulkheads, key=lambda k: bulkheads[k].x)
    step = r.plan.tank_top_step_x_m
    step_x = min((s.x for s in stations), key=lambda x: abs(x - step)) if step is not None else None
    ctx = Context(r, sections, stations, r.section_i.datums.z_m(r.section_i.datums.deck_y), bulkheads, step_x)
    members = longitudinal_members(ctx) + transverse_members(ctx)
    return ctx, members, body, long_section


def by_count(members: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for member in members:
        counts[str(member[key])] = counts.get(str(member[key]), 0) + 1
    return dict(sorted(counts.items()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ocx-schema", type=Path, required=True)
    args = parser.parse_args(argv)
    slicer = HullSlicer(internals.hull_triangles_from_glb(args.assembly / "whole-vessel-draft.glb"))
    ctx, members, body, long_section = build(args.sources, slicer)
    block = {"engineering_approved": False, "status": "draft_only", "members": members,
             "breadth_m": ctx.reading.section_i.breadth_m / 2, "depth_m": ctx.section_deck_z,
             "length_m": body["x_m"][1] - body["x_m"][0],
             "stations": {"frames": [s.x for s in ctx.stations],
                          "bulkheads": [s.x for s in ctx.bulkhead_stations.values()]}}
    args.out.mkdir(parents=True, exist_ok=True)
    steel.write_steel_tables(block, args.out, "gunnerus_structure_DRAFT")
    path = args.out / "gunnerus_structure_DRAFT.3docx"
    ocx.export_ocx(block, path, name="Gunnerus parallel-body structure (draft)")
    check = ocx.validate(path, args.ocx_schema)
    rows = steel.member_weights(members)
    totals = steel.weight_totals(rows)
    steel_t = sum(row["weight_t"] for row in rows)
    report = {
        "engineering_approved": False, "status": "draft_only", "parallel_body": body,
        "members": len(members), "members_by_label": by_count(members, "label"),
        "members_by_thickness_source": by_count(members, "thickness_source"),
        "stiffeners": sum(1 for m in members if ocx.is_stiffener(m)),
        "steel_weight_t": round(steel_t, 3),
        "steel_by_label_t": {t["key"]: round(t["weight_t"], 3) for t in totals if t["group_by"] == "label"},
        "steel_by_thickness_source_t": {t["key"]: round(t["weight_t"], 3) for t in totals if t["group_by"] == "thickness_source"},
        "G6a": g6a_positions(ctx.reading), "G6b": g6b_levels(ctx, args.sources, long_section), "G6c": g6c_shell(ctx),
        "G7": g7_thickness(members, ctx.reading), "G8": g8_spacing(ctx.reading), "G9": g9_weight(args.sources, steel_t),
        "G10": {"schema_valid": check.valid, "schema_errors": check.errors[:5], "round_trip": ocx.round_trip(block, path)},
        "G11": g11_inside(ctx, members),
    }
    (args.out / "structure_3d.json").write_text(json.dumps({**report, "member_records": members}, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
