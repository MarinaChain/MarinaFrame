"""Write an estimated GA arrangement as a desktop-app run folder (the form the web exporter reads).

Layout of ``<out>/runs/<slug>/`` (the concept run's layout, ``benchmarks/concept_launch``):

    state.json                    controller state; config.policy "ga_estimate"; the label
    presentation.json             first view (whole vessel, see-through) and the label as credit
    ga_estimate.json              what was built from what: input digest, gates, skipped items
    domain/state.json             build list (the estimated hull)
    domain/input/spec.json        the estimated stations (no lines plan, no regions)
    domain/builds/r0001/          hull build: result.json (stations, guessed records), model.stl/.step
    intake/intake.json, sources/  the GA image (the Sources tab; hover-to-source pages)
    whole_vessel/execution.json   every part with its source record
    whole_vessel/<id>.step        one STEP per part (mm)
    whole_vessel/whole-vessel-draft.glb
    exports/r0001/                hull STEP/STL and the arrangement table (CSV)

Outside the run folder: ``web-selection-entry.json`` (for scripts/web_demo_runs.json).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np

from vessel_reconstruction import ga_arrangement as G

from . import ESTIMATE_LABEL, GENERATOR, POLICY
from . import model as M

REVISION = "r0001"
BUILD_PATH = f"domain/builds/{REVISION}"
CREATED_MS = int(datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp() * 1000)
MM_PER_M = 1000.0
HULL_MESH = (0.01, 0.2)
LICENCE = "owner-cleared-ga"
# Particulars as a run page names them.
PARTICULAR_NAMES = {"lbp_m": "LBP", "loa_m": "LOA", "breadth_m": "breadth", "depth_m": "depth"}
KIND_LABELS = {"cargo_hold": "Cargo hold", "cargo_tank": "Cargo tank", "slop_tank": "Slop tank",
               "ballast_tank": "Ballast tank", "fuel_tank": "Fuel tank", "other_tank": "Tank",
               "engine_room": "Engine room", "other_space": "Space", "accommodation_deck": "Deckhouse tier",
               "cargo_hatch": "Hatch coaming", "cargo_crane": "Deck crane", "hull": "Hull"}
# Ship-cad ops the app knows (app/core/src/parts.rs groups parts by op).
OPS = {"accommodation_deck": "deckhouse", "cargo_hatch": "other", "cargo_crane": "other", "hull": "hull"}
# Colours of parts that are not tanks (sRGB 0..1).
COLOURS = {"engine_room": (0.85, 0.45, 0.35), "other_space": (0.75, 0.75, 0.70),
           "accommodation_deck": (0.95, 0.95, 0.92), "cargo_hatch": (0.35, 0.45, 0.60),
           "cargo_crane": (0.95, 0.75, 0.15), "hull": (0.62, 0.66, 0.72)}


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
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
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


# --- source records ---------------------------------------------------------------------------

def _regions(record: dict) -> list[dict]:
    """Regions of a record: its own (read) or its inputs that are regions (guessed)."""
    found = record.get("regions") or [entry for entry in record.get("inputs") or [] if "sheet" in entry]
    return [entry for entry in found if entry.get("sheet")]


def item_record(item: G.Item, box: G.Box) -> dict:
    """The item's record: the reader's record, or a guessed record (with the reader's regions as
    inputs) when an extent came from a rule here."""
    from vessel_reconstruction import source_record

    record = item.source_record or {}
    guessed_axes = box.guessed
    if record.get("kind") == "read" and not guessed_axes:
        return source_record.validate(source_record.read(_regions(record)))
    reasons = [f"{axis}: {box.basis.get(axis, 'guessed by the reader')}" for axis in guessed_axes]
    method = record.get("method") or "Extent guessed"
    if reasons:
        method = "Placed from the GA; guessed " + "; ".join(reasons)
    return source_record.validate(source_record.guessed(method, _regions(record)))


def particulars_regions(data: G.ArrangementInput) -> list[dict]:
    regions = []
    for name in ("lbp_m", "loa_m", "breadth_m", "depth_m"):
        regions += _regions((data.particulars.get(name) or {}).get("source_record") or {})
    if not regions and data.sheet:
        from vessel_reconstruction import source_record

        regions = [source_record.region(data.sheet["file"], view=None)]
    return regions


def hull_record(data: G.ArrangementInput) -> dict:
    from vessel_reconstruction import source_record

    method = f"{G.HULL_LABEL}: prior hull form sized from the GA particulars"
    estimated = data.estimated()
    if estimated:
        method += "; estimated, not taken from the drawing: " + ", ".join(estimated)
    return source_record.validate(source_record.guessed(method, particulars_regions(data)))


# --- writers -------------------------------------------------------------------------------------

def part_style(part: M.Solid):
    from vessel_reconstruction.display_mesh import PartStyle, tank_style

    if part.kind in G.TANK_KINDS or part.kind == "cargo_hold":
        return tank_style(part.label, part.label, {"name": "read", "content": "read"})
    extras = {"kind": part.kind, "label": part.label, "engineering_approved": False}
    if part.kind == "hull":
        return PartStyle(COLOURS["hull"], "hull_estimated", {**extras, "estimated": True}, opacity=0.35)
    return PartStyle(COLOURS.get(part.kind, COLOURS["other_space"]), f"ga_{part.kind}", extras)


def ui_source(status: str) -> str:
    """The app's source word for an extent: ``printed`` (a size printed on the drawing),
    ``traced`` (taken from the drawing: read, or measured with its scale) or ``guessed``."""
    if status == "printed":
        return "printed"
    return "guessed" if status == "guessed" else "traced"


def default_basis(axis: str, status: str) -> str:
    """The basis of an extent that no rule here filled: taken from the GA by the reader, or
    guessed by the reader (it gave a value but marked it guessed)."""
    if status == "guessed":
        return f"{axis} extent guessed by the GA reader"
    if status == "printed":
        return f"{axis} extent printed on the drawing (a size tied to this item)"
    return f"{axis} extent from the GA reading"


def component_entry(part: M.Solid, record: dict) -> dict:
    box = M.bbox_of(part.solid)
    entry = {"id": part.id, "op": OPS.get(part.kind, "tank" if part.kind in G.TANK_KINDS else "other"),
             "kind": "ga_estimate", "ga_kind": part.kind, "label": part.label,
             "status": "draft_guess" if record["kind"] == "guessed" else "measured_draft", "built": True,
             "source_record": record, "bbox_m": {"min": _round(box["min"]), "max": _round(box["max"])},
             "volume_m3": round(part.solid.Volume(), 2), "engineering_approved": False}
    if part.box is not None:
        entry["geometry"] = {"x_m": _round(list(part.box.x)), "y_m": _round(list(part.box.y)),
                             "z_m": _round(list(part.box.z))}
        entry["extent_status"] = dict(part.box.status)
        entry["source_labels"] = {axis: ui_source(status) for axis, status in part.box.status.items()}
        # The Parts card's Value / Source / Basis rows (as the concept run's arguments).
        entry["args"] = {axis: f"{part.id}_{axis}" for axis in ("x", "y", "z")}
        entry["provenance"] = {
            f"{part.id}_{axis}": {
                "status": "guessed" if part.box.status[axis] == "guessed" else "measured",
                "source": ui_source(part.box.status[axis]), "value": _round(list(getattr(part.box, axis)), 2),
                "basis": part.box.basis.get(axis, default_basis(axis, part.box.status[axis])), "method": "ga_estimate"}
            for axis in ("x", "y", "z")}
        entry["reason"] = ESTIMATE_LABEL + "".join(f" {axis} guessed: {text}." for axis, text in part.box.basis.items())
    else:
        entry["source_labels"] = {"form": "guessed"}
        entry["args"] = {"form": "hull_form"}
        entry["provenance"] = {"hull_form": {
            "status": "guessed", "source": "guessed", "value": G.HULL_METHOD,
            "basis": "Prior hull form sized from the GA particulars; no lines plan", "method": "ga_estimate"}}
        entry["reason"] = f"{G.HULL_LABEL}. {ESTIMATE_LABEL}"
    if part.kind in G.TANK_KINDS or part.kind == "cargo_hold":
        entry["display"] = {"content_class": part_style(part).extras.get("content_class")}
    return entry


def write_whole_vessel(task: Path, parts: list[M.Solid], records: dict[str, dict]) -> list[dict]:
    from vessel_reconstruction.display_mesh import write_glb

    folder = task / "whole_vessel"
    folder.mkdir(parents=True)
    meshes, styles, components = {}, {}, []
    for part in parts:
        _export_step(part.solid, folder / f"{part.id}.step")
        vertices, faces = M.mesh_of(part.solid, *(HULL_MESH if part.kind == "hull" else M.MESH))
        meshes[part.id] = (vertices * MM_PER_M, faces)
        styles[part.id] = part_style(part)
        components.append(component_entry(part, records[part.id]))
    execution = {"exit_code": 0, "result": {
        "schema": "ship-cad-execution/v1", "status": "draft_only", "engineering_approved": False,
        "readiness_authority": "none: estimated arrangement from one GA drawing", "generator": GENERATOR,
        "ga_estimate": True, "label": ESTIMATE_LABEL, "components": components, "cross_view": []}}
    _write_json(folder / "execution.json", execution)
    write_glb(meshes, folder / "whole-vessel-draft.glb", styles)
    return components


def write_hull_build(task: Path, table, hull, record: dict, slug: str) -> dict:
    build = task / BUILD_PATH
    build.mkdir(parents=True)
    _export_step(hull, build / "model.step")
    vertices, faces = M.mesh_of(hull, *HULL_MESH)
    import trimesh

    trimesh.Trimesh(vertices=vertices * MM_PER_M, faces=faces, process=True).export(build / "model.stl")
    sections = [{"id": row.id, "x_m": row.x_m, "source_label": "ai_inferred", "source_record": record,
                 "points_yz_m": _round(np.asarray(row.points_yz_m).tolist(), 4),
                 "evidence": {"note": f"{G.HULL_LABEL}: prior form station sized from the GA particulars."}}
                for row in table.stations]
    box = M.bbox_of(hull)
    metrics = {"length_m": round(box["max"][0] - box["min"][0], 3), "beam_m": round(box["max"][1] - box["min"][1], 3),
               "depth_m": round(box["max"][2] - box["min"][2], 3), "volume_m3": round(hull.Volume(), 2),
               "bbox_m": {"min": _round(box["min"]), "max": _round(box["max"])}, "cad_valid": True,
               "solid_count": 1, "section_count": len(sections),
               "volume_definition": "Estimated moulded hull envelope to the deck; not displacement."}
    result = {"schema_version": "1.0", "record_kind": "ga_estimate", "vessel_id": slug, "status": "estimated",
              "method": G.HULL_METHOD, "label": G.HULL_LABEL, "run_label": ESTIMATE_LABEL, "sections": sections,
              "metrics": metrics, "warnings": table.warnings, "trend": _round(table.trend),
              "exports": {"stl": "model.stl", "stl_units": "mm", "step": "model.step", "step_units": "mm"},
              "engineering_approved": False}
    _write_json(build / "result.json", result)
    return metrics


def write_domain(task: Path, table, metrics: dict, run_name: str, image: Path) -> None:
    """Spec, build list and the GA as the drawing pane's page (``domain/input/source.png``)."""
    input_dir = task / "domain" / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image, input_dir / "source.png")
    # The estimated stations are not drawn on the GA, so the spec lists none: the drawing pane
    # then fits the whole GA (a station without a box would give it an empty box to fit). The
    # hull build keeps the stations (domain/builds/r0001/result.json).
    stations = []
    spec = {"schema_version": "1.0", "vessel_id": run_name, "units": "m", "symmetry": "port_starboard",
            "source": {"file": "source.png", "sha256": _sha256(input_dir / "source.png"),
                       "description": f"General arrangement. {ESTIMATE_LABEL}"},
            "ga_estimate": True, "sections": stations}
    _write_json(task / "domain" / "input" / "spec.json", spec)
    domain = {"version": "ga_estimate_v1", "revision": REVISION, "selected": {}, "catalog": {},
              "builds": [{"id": "ga-estimate-build-1", "revision_id": REVISION, "path": BUILD_PATH, "valid": True,
                          "draft": True, "metrics": metrics}],
              "inspection_artifacts": [], "input_errors": [], "engineering_approved": False, "ga_estimate": True}
    _write_json(task / "domain" / "state.json", domain)


def write_intake(task: Path, image: Path, run_name: str) -> dict:
    from PIL import Image

    sources = task / "intake" / "sources"
    sources.mkdir(parents=True)
    shutil.copyfile(image, sources / image.name)
    with Image.open(image) as opened:
        width, height = opened.size
    page = {"page_id": "ga", "source_file": f"sources/{image.name}", "file_name": image.name, "page_index": 0,
            "width_px": width, "height_px": height, "dpi": None,
            "sheet": {"type_label": "General arrangement", "scale": {"main_text": "read by the GA reader"}}}
    _write_json(task / "intake" / "intake.json", {"particulars": {"vessel_name": run_name}, "spec_page_id": "ga",
                                                  "pages": [page], "label": ESTIMATE_LABEL})
    return {"file": image.name, "sha256": _sha256(image), "size_px": [width, height]}


def write_state(task: Path, metrics: dict, slug: str) -> None:
    candidate = {"id": "ga-estimate-build-1", "generation_id": "ga-estimate-1", "revision_id": REVISION,
                 "path": BUILD_PATH, "valid": True, "draft": True, "metrics": metrics, "gaps": [],
                 "engineering_approved": False, "human_semantic_review_required": True, "identity_certified": False}
    state = {"schema_version": "marinaframe.control.v1", "task_id": f"ga-estimate-{slug}",
             "status": "awaiting_human_review", "termination_reason": ESTIMATE_LABEL, "created_ms": CREATED_MS,
             "revision_id": REVISION, "generation_id": "ga-estimate-1", "engineering_approved": False,
             "config": {"policy": POLICY, "model": None, "generator": GENERATOR},
             "counters": {"builds": 1, "operations": 0, "requests_completed": 0, "observed_cost_usd": 0.0},
             "domain": {"section_count": metrics["section_count"], "current_candidate": candidate,
                        "engineering_approved": False, "revision_id": REVISION},
             "ga_estimate": {"label": ESTIMATE_LABEL, "generator": GENERATOR}}
    body = json.dumps(state, sort_keys=True)
    _write_json(task / "state.json", {"head_sha256": hashlib.sha256(body.encode()).hexdigest(), "state": state})


def write_presentation(task: Path, note: str) -> dict:
    presentation = {"schema": "marinaframe.presentation.v1", "whole_vessel_first": True, "section_lines": False,
                    "see_through": True, "credit": ESTIMATE_LABEL, "note": note}
    _write_json(task / "presentation.json", presentation)
    return presentation


ARRANGEMENT_COLUMNS = ("id", "kind", "label", "x_from_m", "x_to_m", "y_from_m", "y_to_m", "z_from_m", "z_to_m",
                       "x_status", "y_status", "z_status", "volume_m3", "record")


def arrangement_csv(components: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([f"# {ESTIMATE_LABEL}"])
    writer.writerow(["# Units metres; x forward from the aft perpendicular (frame 0), y to port, z up from the baseline."])
    writer.writerow(ARRANGEMENT_COLUMNS)
    for entry in components:
        geometry = entry.get("geometry")
        if not geometry:
            continue
        labels = entry["extent_status"]
        writer.writerow([entry["id"], entry["ga_kind"], entry["label"], *geometry["x_m"], *geometry["y_m"],
                         *geometry["z_m"], labels["x"], labels["y"], labels["z"], entry["volume_m3"],
                         entry["source_record"]["kind"]])
    return buffer.getvalue()


def write_exports(task: Path, stem: str, components: list[dict]) -> None:
    folder = task / "exports" / REVISION
    folder.mkdir(parents=True)
    shutil.copyfile(task / BUILD_PATH / "model.step", folder / f"{stem}_estimated_hull.step")
    shutil.copyfile(task / BUILD_PATH / "model.stl", folder / f"{stem}_estimated_hull.stl")
    (folder / f"{stem}_arrangement.csv").write_text(arrangement_csv(components), encoding="utf-8")


def selection_entry(slug: str, case_id: str, run_name: str, sheet: dict, note: str, runs_folder: str) -> dict:
    """The run's entry for scripts/web_demo_runs.json (the web demo lane owns that file)."""
    return {"slug": slug, "runs_folder": runs_folder, "name": run_name, "tagline": "GA to estimated 3D arrangement",
            "licence": LICENCE, "source": f"General arrangement drawing of development case {case_id}, shown with the owner's permission.", "credit": ESTIMATE_LABEL, "note": note,
            "file_stem": case_id, "drawing_sha256": [sheet["sha256"]],
            "whole_vessel_first": True, "section_lines": False, "see_through": True}


def generate(reading: dict, image: Path, out: Path, slug: str, run_name: str, source: dict | None = None) -> dict:
    """``source`` says which reading this is (for example the reader's round and commit); it is
    kept in ``ga_estimate.json``."""
    """Build the estimated arrangement of one GA reading and write ``out/runs/<slug>``."""
    data = G.load_input(reading)
    if data.sheet and data.sheet.get("file") and data.sheet["file"] != Path(image).name:
        raise G.InputError(f"the reading is of {data.sheet['file']}, not {Path(image).name}")
    out = Path(out)
    task = out / "runs" / slug
    if task.exists():
        shutil.rmtree(task)
    task.mkdir(parents=True)
    table, size, parts, findings = M.build(data)
    records = {"hull": hull_record(data)}
    records.update({part.id: item_record(part.item, part.box) for part in parts if part.item is not None})
    sheet = write_intake(task, Path(image), run_name)
    metrics = write_hull_build(task, table, parts[0].solid, records["hull"], slug)
    write_domain(task, table, metrics, run_name, Path(image))
    components = write_whole_vessel(task, parts, records)
    write_exports(task, data.case_id, components)
    write_state(task, metrics, slug)
    read_count = sum(1 for entry in components if entry["source_record"]["kind"] == "read")
    note = (f"{len(components) - 1} parts placed from the GA; each part's card says which extents were read "
            f"and which guessed. Hull {metrics['length_m']:.0f} x {metrics['beam_m']:.1f} x {metrics['depth_m']:.1f} m, "
            "estimated.")
    estimated = [name for name in PARTICULAR_NAMES
                 if data.value(name) is not None and data.status(name) not in G.FROM_DRAWING]
    if estimated:
        note += " Not from the drawing: " + ", ".join(
            f"{PARTICULAR_NAMES[name]} ({data.status(name).replace('_', ' ')})" for name in estimated) + "."
    write_presentation(task, note)
    summary = {"label": ESTIMATE_LABEL, "generator": GENERATOR, "generator_commit": _git_commit(),
               "reading_source": source or {}, "particulars_estimated": data.estimated(),
               "engineering_approved": False, "case_id": data.case_id, "test_fixture": data.test_fixture,
               "input_sha256": hashlib.sha256(json.dumps(reading, sort_keys=True).encode()).hexdigest(),
               "hull": {"size": _round(size.__dict__), "metrics": metrics, "label": G.HULL_LABEL},
               "particulars_used": {name: (data.particulars.get(name) or {}).get("value")
                                    for name in ("lbp_m", "loa_m", "breadth_m", "depth_m")},
               "parts": len(components), "parts_read": read_count, "skipped": data.skipped, "findings": findings}
    _write_json(task / "ga_estimate.json", summary)
    # scripts/build_web_demo.py reads "runs_folder" relative to its --runs folder, which
    # docs/WEB_DEMO.md puts at work/web-demo-runs/runs (a sibling of this output folder).
    web_runs = out.resolve().parent / "web-demo-runs" / "runs"
    entry = selection_entry(slug, data.case_id, run_name, sheet, note,
                            os.path.relpath((out / "runs").resolve(), web_runs))
    _write_json(out / f"{slug}.web-selection-entry.json", entry)
    return {"task": str(task), "summary": summary, "selection_entry": entry}
