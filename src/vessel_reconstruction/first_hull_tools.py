"""Initialize investigation geometry from the anchored W19a vessel fit."""
from __future__ import annotations

import copy
from uuid import uuid4

from . import investigation as inv
from .draft import make_guesses
from .form_fit import Anchor, first_hull
from .isolation import run_isolated
from .provenance import write_json


def build_first_hull(tools):
    from .vessel_description import first_hull_spec, describe_table
    description = tools.state.get("vessel_description")
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
    baseline_out = tools.root / "builds" / f"anchors-{uuid4().hex[:12]}"
    baseline = run_isolated(base, baseline_out, export_cad=False, cancel_event=tools.cancel_event)
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
    def build(spec):
        # Keep the table spec at the captured revision so source paths resolve.
        write_json(base, spec)
        out = tools.root / "builds" / f"first-{uuid4().hex[:12]}"
        outcome = run_isolated(base, out, export_cad=True, cancel_event=tools.cancel_event)
        record = outcome.get("result") or {}
        if record.get("exports", {}).get("step"):
            built.update(out=out, record=record, spec=spec)
            return True
        return False
    table, success, left_out = first_hull(sections, anchors, base_spec, build)
    if not success:
        return tools._observation(False, "blocked", message="First hull could not form a solid; use propose_section to complete it.")
    describe_table(table, description)
    tools.state["vessel_table"] = table.to_json()
    write_json(tools.root / "vessel.json", {"description": description, "table": table.to_json()})
    from .fit_feedback import score
    tools.state["fit_score"] = score(tools, table)
    tools.state["first_hull_spec"] = built["spec"]
    tools.state["guesses"] = built["spec"].get("draft", {}).get("guesses", guesses)
    candidate = {"id":tools.generation_id,"generation_id":tools.generation_id,"revision_id":tools.revision_id,
        "path":built["out"].relative_to(tools.task_dir).as_posix(),"status":"review_required","valid":True,"draft":True,
        "run_id":built["record"]["run_id"],"gaps":built["record"]["gaps"],"metrics":built["record"]["metrics"],
        "engineering_approved":False,"human_semantic_review_required":True,"identity_certified":False}
    tools.state["builds"].append(candidate)
    candidate["combined_fit"] = tools.state["fit_score"].get("combined_fit")
    tools.state["last_valid_candidate"] = candidate
    tools.state["best_valid_candidate"] = copy.deepcopy(candidate)
    tools._save()
    return tools._observation(True,"first_hull_built",candidate=candidate,left_out_anchor_ids=left_out,
                              message="Anchored first hull ready. Render it, preserve good ink and improve only the weak sections.")
