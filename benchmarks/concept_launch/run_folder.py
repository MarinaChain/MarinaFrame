"""Write the concept vessel as a desktop-app run folder (the form app/core reads).

Layout of ``<out>/runs/<slug>/`` (only what the app's read commands use):

    state.json                         controller state: status, the hull build, the concept label
    concept_preview.json               who made this run and how (the generator, not a reader)
    domain/state.json                  section catalog (one line per station) and the build list
    domain/input/spec.json             the stations and their regions on the lines plan
    domain/input/source.png            the lines plan (the drawing pane's page)
    domain/builds/r0001/               hull build: result.json (sections and source records),
                                       model.stl and model.step (mm)
    intake/intake.json, intake/sources the three generated sheets (the Sources tab)
    whole_vessel/execution.json        every part with its source record (app/core/src/parts.rs)
    whole_vessel/<id>.step             one STEP per part (mm)
    whole_vessel/whole-vessel-draft.glb  one node per part (mm, glTF Y-up)
    tanks.npz, tank_tables/            capacity plan, sounding tables and tank source records
    exports/r0001/                     STEP, STL, hydrostatics and tank tables to download

Outside the run folder: ``drawings/`` (the sheets), ``model/`` (whole-vessel STEP and GLB) and
``manifest-entry.json`` (the entry the web demo build needs).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

from . import CONCEPT_LABEL, GENERATOR, SHEET_LABEL
from . import model as M
from . import sheets as S
from . import structure as T

SLUG = "concept-survey-launch"
RUN_NAME = "Concept preview: Survey launch 24 m (example vessel made for this demo)"
REVISION = "r0001"
BUILD_PATH = f"domain/builds/{REVISION}"
TABLE_STEM = "Survey_launch_CONCEPT_DRAFT"
EXPORT_STEM = "Survey_launch_CONCEPT"
SHEET_FILES = {
    "ga": "concept-survey-launch-general-arrangement.png",
    "lines": "concept-survey-launch-lines-plan.png",
    "tanks": "concept-survey-launch-tank-arrangement.png",
    "construction": "concept-survey-launch-construction.png",
}
SHEET_TYPES = {"ga": "General arrangement", "lines": "Lines plan", "tanks": "Tank arrangement",
               "construction": "Construction plan"}
# A fixed time (2026-11-11 00:00 UTC), so the same code writes the same files.
CREATED_MS = int(datetime(2026, 11, 11, tzinfo=timezone.utc).timestamp() * 1000)
MM_PER_M = 1000.0
# Mesh tolerances (metres, radians) of the hull and tanks, and of the parts that are only drawn.
FINE_MESH = (0.0005, 0.05)
PART_MESH = (0.002, 0.2)
STAMP_LINES = [CONCEPT_LABEL, "Units metres; x forward from the transom (frame 0), y to port, z up from the baseline."]
PART_REASON = "Concept preview: drawn on the example sheets from the concept model (not read by MarinaFrame)."


# --- the model ------------------------------------------------------------------------------

def build_model():
    """Parts, meshes, tank model, capacity rows and hydrostatics of the concept vessel."""
    from vessel_reconstruction import tanks

    parts = M.build_parts()
    by_id = {part.id: part for part in parts}
    # The hull and tank meshes are finer: the lines plan cuts the hull mesh, and the capacity
    # plan computes tank volumes from the tank meshes (within 0.2 % of the CAD solids).
    triangles = {part.id: M.triangles_of(part.solid, *(FINE_MESH if part.op in ("hull", "tank") else PART_MESH))
                 for part in parts}
    tank_model = [tank_of(part, triangles[part.id]) for part in parts if part.op == "tank"]
    capacity = {row["id"]: row for row in tanks.capacity_plan(tank_model)}
    table = M.hydrostatic_table(by_id["hull"].solid)
    design = next(row for row in table if abs(row["draft_m"] - M.DESIGN_DRAFT_M) < 1e-9)
    return S.Model(by_id, triangles, capacity, design, T.members()), tank_model, table


def tank_of(part: M.Part, triangles: np.ndarray):
    from vessel_reconstruction import tanks

    spec = part.tank
    frames = (str(round(spec.x_m[0] / M.FRAME_SPACING_M)), str(round(spec.x_m[1] / M.FRAME_SPACING_M)))
    geometry = "guessed" if part.guess else "traced"
    return tanks.Tank(spec.id, spec.name, spec.content, triangles, frames, spec.density_t_m3,
                      {"name": "read", "content": "read", "frames": "read", "density": "guessed",
                       "geometry": geometry, "sounding_origin": "guessed"},
                      None, ["concept preview: example tank made for this demo"])


# --- source records --------------------------------------------------------------------------

def regions_by_item(sheet_list: list[S.Sheet]) -> dict[str, list[dict]]:
    """Every recorded sheet region as a source-record region, by item id."""
    from vessel_reconstruction import source_record

    found: dict[str, list[dict]] = {}
    for sheet in sheet_list:
        for item, view, box in sheet.regions:
            found.setdefault(item, []).append(
                source_record.region(sheet.file_name, view=view, box_px=box, page_px=list(S.SHEET_PX)))
    return found


def part_record(part: M.Part, regions: dict[str, list[dict]]) -> dict:
    from vessel_reconstruction import source_record

    found = regions.get(part.id, [])
    if not found:
        raise ValueError(f"part {part.id} is drawn on no sheet")
    if part.guess:
        inputs = found + [source_record.part_input(other) for other in part.guess_parts]
        return source_record.validate(source_record.guessed(part.guess, inputs))
    return source_record.validate(source_record.read(found))


# --- writers ---------------------------------------------------------------------------------

def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round(value, digits: int = 4):
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, (list, tuple)):
        return [_round(v, digits) for v in value]
    return value


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _export_step(solid, path: Path) -> None:
    import cadquery as cq

    cq.exporters.export(cq.Workplane().add(solid.scale(MM_PER_M)), str(path), exportType="STEP")


def _write_stl(triangles: np.ndarray, path: Path) -> None:
    import trimesh

    vertices = triangles.reshape(-1, 3) * MM_PER_M
    faces = np.arange(len(vertices)).reshape(-1, 3)
    trimesh.Trimesh(vertices=vertices, faces=faces, process=True).export(path)


def component_entry(part: M.Part, record: dict, model: S.Model) -> dict:
    labels = {name: argument.source for name, argument in part.arguments.items()}
    provenance = {f"{part.id}_{name}": {"status": "measured" if argument.source == "traced" else "guessed",
                                        "source": argument.source, "value": _round(argument.value),
                                        "basis": argument.basis, "method": "concept_preview_generator"}
                  for name, argument in part.arguments.items()}
    box = M.bbox_of(part.solid)
    entry = {
        "id": part.id, "op": part.op, "kind": "concept_preview", "label": part.label,
        "status": "draft_guess" if part.guess else "measured_draft", "built": True,
        "reason": PART_REASON + (f" Guess: {part.guess}." if part.guess else ""),
        "source": {"view": part.drawn_in[0][1], "region": part.id, "method": "concept_preview_generator"},
        "source_labels": labels, "provenance": provenance, "source_record": record,
        "args": {name: f"{part.id}_{name}" for name in part.arguments},
        "geometry": {name: _round(argument.value) for name, argument in part.arguments.items()},
        "bbox_m": {"min": _round(box["min"]), "max": _round(box["max"])},
        "volume_m3": round(model.capacity[part.id]["volume_100_m3"] if part.op == "tank" else part.solid.Volume(), 4),
        "engineering_approved": False,
    }
    if part.op == "tank":
        from vessel_reconstruction.tanks import content_class

        tri = model.triangles[part.id]
        entry["display"] = {"profile_m": [_round(S.silhouette(tri, 0, 2), 3)],
                            "plan_m": [_round(S.silhouette(tri, 0, 1), 3)],
                            "content_class": content_class(part.tank.content, part.label)}
    return entry


def write_whole_vessel(task: Path, model: S.Model, records: dict[str, dict]) -> None:
    from vessel_reconstruction.display_mesh import tank_style, write_glb

    folder = task / "whole_vessel"
    folder.mkdir(parents=True)
    components = []
    meshes = {}
    styles = {}
    # Steel parts (bulkheads, web frames, girder, inner bottom) are drawn by the structure GLB;
    # they keep their part entry and source record, but no second mesh here.
    steel_ids = {member["member_id"] for member in model.members}
    for part in model.parts.values():
        _export_step(part.solid, folder / f"{part.id}.step")
        if part.id not in steel_ids:
            vertices, faces = M.mesh_of(part.solid)
            meshes[part.id] = (vertices * MM_PER_M, faces)
        if part.op == "tank":
            styles[part.id] = tank_style(part.label, part.tank.content, {"name": "read", "content": "read"})
        components.append(component_entry(part, records[part.id], model))
    execution = {"exit_code": 0, "result": {
        "schema": "ship-cad-execution/v1", "status": "draft_only", "engineering_approved": False,
        "readiness_authority": "none: concept preview made by a generator for a demo",
        "generator": GENERATOR, "concept_preview": True, "label": CONCEPT_LABEL,
        "components": components, "cross_view": []}}
    _write_json(folder / "execution.json", execution)
    write_glb(meshes, folder / "whole-vessel-draft.glb", styles)


def write_tank_tables(task: Path, tank_model: list, records: dict[str, dict]) -> list[Path]:
    from vessel_reconstruction import source_record, tanks
    from vessel_reconstruction.exports.tank_tables import write_tank_tables as write_tables

    tanks.save_tanks(tank_model, task / "tanks.npz")
    _, entries = write_tables(tank_model, task / "tank_tables", TABLE_STEM, STAMP_LINES)
    source_record.write_records(task / "tank_tables" / f"{TABLE_STEM}{source_record.TANK_RECORDS_SUFFIX}",
                                {tank.id: records[tank.id] for tank in tank_model})
    return [path for path, _, _ in entries]


def write_structure(task: Path, members: list[dict], regions: dict[str, list[dict]]) -> list[Path]:
    """Structure GLB (member groups), steel tables and one source record per member."""
    from vessel_reconstruction import source_record
    from vessel_reconstruction.structure.display import write_structure_glb
    from vessel_reconstruction.structure.steel import write_steel_tables

    folder = task / "structure"
    folder.mkdir(parents=True)
    write_structure_glb(members, folder / f"{TABLE_STEM}_structure.glb")
    tables = write_steel_tables({"members": members}, folder, TABLE_STEM)
    records = {member["member_id"]: source_record.read(regions[member["member_id"]]) for member in members}
    source_record.write_records(folder / f"{TABLE_STEM}{source_record.TANK_RECORDS_SUFFIX}", records)
    return [tables["members"], tables["totals"]]


HYDRO_COLUMNS = ("draft_m", "volume_m3", "displacement_t", "lcb_m", "kb_m", "bm_m", "km_m", "waterplane_area_m2",
                 "lcf_m", "tpc_t_cm", "mct_1cm_tm", "waterline_length_m", "waterline_breadth_m",
                 "block_coefficient", "waterplane_coefficient")


def hydrostatics_csv(table: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in STAMP_LINES + ["Moulded hull, level trim, sea water 1.025 t/m3. Not approved for any use."]:
        writer.writerow([f"# {line}"])
    writer.writerow(HYDRO_COLUMNS)
    for row in table:
        writer.writerow([f"{row[name]:.4f}" for name in HYDRO_COLUMNS])
    return buffer.getvalue()


def write_hull_build(task: Path, model: S.Model, regions: dict[str, list[dict]], hull_volume: float) -> dict:
    """The hull build the app shows as the run's model, with one source record per station."""
    from vessel_reconstruction import source_record

    build = task / BUILD_PATH
    build.mkdir(parents=True)
    hull = model.parts["hull"]
    _export_step(hull.solid, build / "model.step")
    _write_stl(model.triangles["hull"], build / "model.stl")
    sections = []
    for station_id, x in M.BODY_PLAN_STATIONS:
        record = source_record.validate(source_record.read(regions[station_id]))
        sections.append({"id": station_id, "x_m": x, "source_label": "traced", "source_record": record,
                         "points_yz_m": _round(M.section_points(x).tolist(), 5),
                         "evidence": {"note": "Concept preview station: drawn from the concept model."}})
    box = M.bbox_of(hull.solid)
    metrics = {"length_m": round(box["max"][0] - box["min"][0], 4), "beam_m": round(box["max"][1] - box["min"][1], 4),
               "depth_m": round(box["max"][2] - box["min"][2], 4), "volume_m3": round(hull_volume, 4),
               "bbox_m": {"min": _round(box["min"]), "max": _round(box["max"])}, "cad_valid": True,
               "solid_count": 1, "section_count": len(sections),
               "volume_definition": "Moulded hull envelope to the main deck; not displacement."}
    result = {"schema_version": "1.0", "record_kind": "concept_preview", "vessel_id": SLUG, "status": "concept_preview",
              "method": GENERATOR, "label": CONCEPT_LABEL, "sections": sections, "metrics": metrics,
              "exports": {"stl": "model.stl", "stl_units": "mm", "step": "model.step", "step_units": "mm"},
              "engineering_approved": False}
    _write_json(build / "result.json", result)
    return metrics


def write_domain(task: Path, sheet_lines: S.Sheet, regions: dict[str, list[dict]], metrics: dict) -> None:
    """Captured spec, the source page and the section catalog (one picked line per station)."""
    input_dir = task / "domain" / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    source_png = input_dir / "source.png"
    sheet_lines.finish().save(source_png, optimize=True)
    stations = []
    catalog = {}
    selected = {}
    for station_id, x in M.BODY_PLAN_STATIONS:
        box = next(r["box_px"] for r in regions[station_id] if r["view"] == "body plan")
        roi = [int(box[0]), int(box[1]), int(round(box[2])), int(round(box[3]))]
        side = -1.0 if x <= M.LENGTH_M / 2 + 1e-9 else 1.0
        anchors = [[round(c, 1), round(r, 1)] for c, r in
                   (S.BODY_PLAN.px(side * y, z) for y, z in M.section_points(x))]
        candidate_id = f"concept-{station_id}"
        stations.append({"id": station_id, "x_m": x, "roi_px": roi,
                         "evidence": "Concept preview station drawn from the concept model."})
        catalog[station_id] = {"section_id": station_id, "x_m": x, "roi_px": roi, "candidates": [
            {"candidate_id": candidate_id, "selectable": True, "concept_preview": True,
             "contour_selection": {"anchors_px": anchors, "half_width_px": 2.0}}]}
        selected[station_id] = candidate_id
    spec = {"schema_version": "1.0", "vessel_id": RUN_NAME, "units": "m", "symmetry": "port_starboard",
            "source": {"file": "source.png", "sha256": _sha256(source_png),
                       "description": CONCEPT_LABEL},
            "concept_preview": True, "sections": stations}
    _write_json(input_dir / "spec.json", spec)
    domain = {"version": "concept_preview_v1", "revision": REVISION, "selected": selected, "catalog": catalog,
              "builds": [{"id": "concept-build-1", "revision_id": REVISION, "path": BUILD_PATH, "valid": True,
                          "draft": False, "metrics": metrics}],
              "inspection_artifacts": [], "input_errors": [], "engineering_approved": False,
              "concept_preview": True}
    _write_json(task / "domain" / "state.json", domain)


def write_intake(task: Path, sheet_list: list[S.Sheet], drawings: Path) -> None:
    sources = task / "intake" / "sources"
    sources.mkdir(parents=True)
    pages = []
    for index, sheet in enumerate(sheet_list):
        shutil.copyfile(drawings / sheet.file_name, sources / sheet.file_name)
        width, height = S.SHEET_PX
        pages.append({"page_id": sheet.key, "source_file": f"sources/{sheet.file_name}", "file_name": sheet.file_name,
                      "page_index": 0, "width_px": width, "height_px": height, "dpi": None,
                      "sheet": {"type_label": SHEET_TYPES[sheet.key], "scale": {"main_text": "scale bar on sheet"}},
                      "concept_preview": True})
    record = {"particulars": {"vessel_name": RUN_NAME}, "spec_page_id": "lines", "pages": pages,
              "concept_preview": True, "label": CONCEPT_LABEL}
    _write_json(task / "intake" / "intake.json", record)


def write_state(task: Path, metrics: dict) -> None:
    candidate = {"id": "concept-build-1", "generation_id": "concept-generation-1", "revision_id": REVISION,
                 "path": BUILD_PATH, "valid": True, "draft": False, "metrics": metrics, "gaps": [],
                 "engineering_approved": False, "human_semantic_review_required": True, "identity_certified": False}
    state = {
        "schema_version": "marinaframe.control.v1",
        "task_id": f"concept-preview-{SLUG}",
        "status": "awaiting_human_review",
        "termination_reason": CONCEPT_LABEL,
        "created_ms": CREATED_MS,
        "revision_id": REVISION,
        "generation_id": "concept-generation-1",
        "engineering_approved": False,
        "config": {"policy": "concept_preview", "model": None, "generator": GENERATOR},
        "counters": {"builds": 1, "operations": 0, "requests_completed": 0, "observed_cost_usd": 0.0},
        "domain": {"section_count": len(M.BODY_PLAN_STATIONS), "current_candidate": candidate,
                   "engineering_approved": False, "revision_id": REVISION},
        "concept_preview": {"label": CONCEPT_LABEL, "generator": GENERATOR, "read_by_marinaframe": False},
    }
    body = json.dumps(state, sort_keys=True)
    _write_json(task / "state.json", {"head_sha256": hashlib.sha256(body.encode()).hexdigest(), "state": state})


def write_exports(task: Path, model: S.Model, table: list[dict], tank_files: list[Path]) -> None:
    folder = task / "exports" / REVISION
    folder.mkdir(parents=True)
    shutil.copyfile(task / BUILD_PATH / "model.step", folder / f"{EXPORT_STEM}_model.step")
    shutil.copyfile(task / BUILD_PATH / "model.stl", folder / f"{EXPORT_STEM}_model.stl")
    (folder / f"{EXPORT_STEM}_hydrostatics.csv").write_text(hydrostatics_csv(table), encoding="utf-8")
    _write_json(folder / f"{EXPORT_STEM}_hydrostatics.json",
                {"label": CONCEPT_LABEL, "generator": GENERATOR, "engineering_approved": False,
                 "sea_water_t_m3": M.SEA_WATER_T_M3, "rows": [{k: round(v, 5) for k, v in row.items()} for row in table]})
    for path in tank_files:
        shutil.copyfile(path, folder / path.name)


def write_metadata(task: Path, model: S.Model, table: list[dict], sheet_list: list[S.Sheet], drawings: Path) -> dict:
    metadata = {
        "label": CONCEPT_LABEL, "sheet_label": SHEET_LABEL, "generator": GENERATOR,
        "generator_commit": _git_commit(), "read_by_marinaframe": False, "engineering_approved": False,
        "vessel": {"name": RUN_NAME, "length_m": M.LENGTH_M, "beam_m": 2 * M.HALF_BEAM_M, "depth_m": M.DEPTH_M,
                   "design_draft_m": M.DESIGN_DRAFT_M},
        "parts": {part.id: {"op": part.op, "label": part.label, "model_volume_m3": round(part.solid.Volume(), 4)}
                  for part in model.parts.values()},
        "tanks": {tank_id: {"capacity_volume_100_m3": round(row["volume_100_m3"], 4),
                            "model_volume_m3": round(model.parts[tank_id].solid.Volume(), 4)}
                  for tank_id, row in model.capacity.items()},
        "hydrostatics": [{k: round(v, 4) for k, v in row.items()} for row in table],
        "steel_members": len(model.members),
        "sheets": [{"file": sheet.file_name, "sha256": _sha256(drawings / sheet.file_name), "page_px": list(S.SHEET_PX),
                    "regions": len(sheet.regions)} for sheet in sheet_list],
    }
    _write_json(task / "concept_preview.json", metadata)
    return metadata


def manifest_entry(sheet_list: list[S.Sheet], drawings: Path) -> dict:
    """The run's entry for scripts/web_demo_runs.json (lane web-demo owns that file), in its form."""
    return {
        "slug": SLUG,
        "name": "Survey launch 24 m (concept preview)",
        "licence": "synthetic",
        "source": f"{CONCEPT_LABEL} Made by {GENERATOR}.",
        "drawing_sha256": sorted({_sha256(drawings / sheet.file_name) for sheet in sheet_list}),
    }


def generate(out: Path) -> dict:
    """Build the model, draw the sheets and write ``out`` (drawings/, model/, runs/<slug>/)."""
    out = Path(out)
    task = out / "runs" / SLUG
    if task.exists():
        shutil.rmtree(task)
    drawings, model_dir = out / "drawings", out / "model"
    drawings.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    task.mkdir(parents=True)

    model, tank_model, table = build_model()
    sheet_list = S.draw_all(model, SHEET_FILES)
    for sheet in sheet_list:
        sheet.finish().save(drawings / sheet.file_name, optimize=True)
    regions = regions_by_item(sheet_list)
    records = {part.id: part_record(part, regions) for part in model.parts.values()}

    hull_volume = model.parts["hull"].solid.Volume()
    metrics = write_hull_build(task, model, regions, hull_volume)
    write_domain(task, sheet_list[1], regions, metrics)
    write_intake(task, sheet_list, drawings)
    write_whole_vessel(task, model, records)
    tank_files = write_tank_tables(task, tank_model, records)
    steel_files = write_structure(task, model.members, regions)
    write_exports(task, model, table, tank_files + steel_files)
    write_state(task, metrics)
    metadata = write_metadata(task, model, table, sheet_list, drawings)
    shutil.copyfile(task / "whole_vessel" / "whole-vessel-draft.glb", model_dir / "concept-survey-launch.glb")
    entry = manifest_entry(sheet_list, drawings)
    _write_json(out / "manifest-entry.json", entry)
    _write_json(out / "regions.json", {sheet.file_name: [{"item": item, "view": view, "box_px": box}
                                                         for item, view, box in sheet.regions]
                                       for sheet in sheet_list})
    return {"task": str(task), "metadata": metadata, "manifest_entry": entry}
