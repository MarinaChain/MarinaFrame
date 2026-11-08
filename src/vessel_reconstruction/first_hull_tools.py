"""Initialize investigation geometry from the anchored W19a vessel fit."""
from __future__ import annotations

import copy
from uuid import uuid4

from . import investigation as inv
from .draft import make_guesses
from .form_fit import Anchor, BuildFailure, PriorDimensions, first_hull, panel_dimensions
from .isolation import run_isolated
from .provenance import write_json

# Worker states that depend on machine load, not on the specification: a build
# that ends in one of them is run once more before its anchors are judged.
RETRY_STATES = ("timed_out",)


def run_build(tools, spec_path, prefix: str, *, export_cad: bool):
    """Run one isolated build; run it once more when the worker timed out.

    Returns ``(outcome, out_dir, retried)``. A time-out says nothing about the
    geometry, so it must not decide which anchors the first hull keeps.
    """
    retried = False
    while True:
        out = tools.root / "builds" / f"{prefix}-{uuid4().hex[:12]}"
        outcome = run_isolated(spec_path, out, export_cad=export_cad, cancel_event=tools.cancel_event)
        if outcome.get("result") is not None or outcome.get("state") not in RETRY_STATES or retried:
            return outcome, out, retried
        retried = True


def build_failure(outcome: dict) -> BuildFailure:
    """Why a build made no solid: timeout, invalid geometry or another worker state."""
    record = outcome.get("result") or {}
    state = outcome.get("state")
    if state == "timed_out":
        return BuildFailure("timeout", "the build worker timed out twice")
    if record:
        kinds = [g.get("kind") for g in record.get("gaps", []) if g.get("severity") != "warning"][:3]
        return BuildFailure("invalid_geometry", ", ".join(k for k in kinds if k) or record.get("status", ""))
    return BuildFailure(str(state or "failed"), str(outcome.get("error_code", ""))[:120])


def prior_dimensions(spec: dict, sections: list[dict]) -> PriorDimensions | None:
    """Vessel size for a hull with no usable ink.

    The description's beam and depth (already applied to ``spec`` constraints
    by first_hull_spec, only when not doubtful) come first; else the drawing's
    calibrated panel extents.
    """
    constraints = spec.get("constraints") or {}
    beam = constraints.get("beam_m")
    if isinstance(beam, (int, float)) and beam > 0:
        depth = constraints.get("depth_m")
        top = float(depth) if isinstance(depth, (int, float)) and depth > 0 else None
        return PriorDimensions(half_beam_m=float(beam) / 2, top_z_m=top, source="vessel description")
    return panel_dimensions(sections)


def build_first_hull(tools):
    from .vessel_description import first_hull_spec, describe_table
    description = tools.state.get("vessel_description")
    materialization = None
    if tools.state.get("sheet_only") and not tools.state.get("materialized_spec_sha256"):
        # A sheet-only intake: declare the sections from the phase-1 reading first.
        materialization = tools._materialize_sections()
    sections = first_hull_spec(tools.spec, description)["sections"]
    while not all(s["id"] in tools.state["catalog"] for s in sections):
        observed = tools._inspect_source()
        if not observed.get("ok") and not observed.get("recovery_tools"):
            break
    tools._assign_shared_panels()
    guesses = make_guesses(sections, tools.state["selected"], tools.state["catalog"], tools.state.get("model_choices"))
    tools.state["guesses"] = guesses
    tools._save()
    base = tools._write_revision()
    from .schema import load_bounded_json
    base_spec = first_hull_spec(load_bounded_json(base), description)
    baseline, _, _ = run_build(tools, base, "anchors", export_cad=False)
    measured = {s["id"]: s for s in (baseline.get("result") or {}).get("sections", [])}
    image, _, _ = tools._source()
    chosen = {g["section_id"]: g["chosen_candidate_id"] for g in guesses}
    chosen.update(tools.state["selected"])
    anchors = []
    for section in sections:
        candidate = next((c for c in tools.state["catalog"].get(section["id"], {}).get("candidates", [])
                          if c["candidate_id"] == chosen.get(section["id"])), None)
        if not candidate or "contour_selection" not in candidate:
            continue
        trace = inv.dense_trace(candidate)
        if trace is None:
            continue
        rows, xs = trace
        cal = section["calibration"]
        points = [[(float(x) - cal["centerline_px"]) / cal["pixels_per_metre"],
                   (cal["baseline_px"] - float(y)) / cal["pixels_per_metre"]] for y, x in zip(rows, xs)]
        points.sort(key=lambda p: p[1])
        if section["id"] in measured:
            points = measured[section["id"]]["points_yz_m"]
        from .form_fit import measure_stroke_width_px
        width = measure_stroke_width_px(image, points, cal)
        selected = copy.deepcopy(section)
        selected["contour_selection"] = copy.deepcopy(candidate["contour_selection"])
        anchors.append(Anchor(section["id"], section["x_m"], points, selected,
            z_max_m=section["z_max_m"], pixels_per_metre=cal["pixels_per_metre"], stroke_width_px=width))
    built = {}
    retried_builds = []

    def build(spec):
        # Keep the table spec at the captured revision so source paths resolve.
        write_json(base, spec)
        outcome, out, retried = run_build(tools, base, "first", export_cad=True)
        if retried:
            retried_builds.append(out.name)
        record = outcome.get("result") or {}
        if record.get("exports", {}).get("step"):
            built.update(out=out, record=record, spec=spec)
            return True
        return build_failure(outcome)

    table, success, left_out = first_hull(sections, anchors, base_spec, build,
                                          prior=prior_dimensions(base_spec, sections))
    if not success:
        reason = getattr(success, "reason", "build_failed")
        return tools._observation(False, "blocked", error_code=f"first_hull_{reason}",
                                  message="First hull could not form a solid; use propose_section to complete it.")
    describe_table(table, description)
    warnings = hull_warnings(table, retried_builds)
    if tools.state.get("materialization"):
        # Sections of a sheet-only intake came from the model's reading: say so.
        warnings = [w[:300] for w in tools.state["materialization"]["warnings"]] + warnings
        warnings.insert(0, "Stations and calibration were set from the model's reading of the sheet (ai_inferred).")
    tools.state["vessel_table"] = table.to_json()
    write_json(tools.root / "vessel.json", {"description": description, "table": table.to_json()})
    from .fit_feedback import score
    tools.state["fit_score"] = score(tools, table)
    tools.state["first_hull_spec"] = built["spec"]
    tools.state["guesses"] = built["spec"].get("draft", {}).get("guesses", guesses)
    candidate = {"id":tools.generation_id,"generation_id":tools.generation_id,"revision_id":tools.revision_id,
        "path":built["out"].relative_to(tools.task_dir).as_posix(),"status":"review_required","valid":True,"draft":True,
        "run_id":built["record"]["run_id"],"gaps":built["record"]["gaps"],"metrics":built["record"]["metrics"],
        "engineering_approved":False,"human_semantic_review_required":True,"identity_certified":False,
        "warnings":warnings}
    tools.state["builds"].append(candidate)
    candidate["combined_fit"] = tools.state["fit_score"].get("combined_fit")
    tools.state["last_valid_candidate"] = candidate
    tools.state["best_valid_candidate"] = copy.deepcopy(candidate)
    tools._save()
    no_ink = all(row.source == "prior" for row in table.stations)
    message = ("No usable ink: the first hull is the prior form scaled to the vessel size. Author or correct "
               "sections from the drawing." if no_ink else
               "Anchored first hull ready. Render it, preserve good ink and improve only the weak sections.")
    extra = {"materialized_sections": materialization} if materialization else {}
    return tools._observation(True,"first_hull_built",candidate=candidate,left_out_anchor_ids=left_out,
                              warnings=warnings, message=message, **extra)


# Kinds of table warning that say what happened to the ink (fairness notes stay in the table).
REPORTED_WARNINGS = ("no_ink", "anchor_dropped", "anchor_left_out")


def hull_warnings(table, retried_builds: list) -> list[str]:
    """Draft warnings of the first hull: no ink, each dropped or left-out anchor and why, retries."""
    lines = []
    for item in table.warnings:
        if item.get("kind") in REPORTED_WARNINGS:
            where = f"{item['section_id']}: " if item.get("section_id") else ""
            lines.append(f"{where}{item.get('message', '')}"[:300])
    if retried_builds:
        lines.append(f"{len(retried_builds)} build(s) timed out and were run once more.")
    return lines
